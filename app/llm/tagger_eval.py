"""Measure the tagger against a hand-tagged test set (v0.5 D5).

Run it after every prompt or taxonomy change. The retag rollout is gated on it: precision of
0.8 or better on the ten most-used tags before any full retag.

A test set is a JSON file of calls, each with its utterances (and who spoke) and the highlights
a person expects: ``{"utterance_idx": 3, "tag_key": "pain"}``. A prediction counts as correct
when the same tag lands on the same utterance of the same call. Matching on the utterance (not
the exact quote text) keeps the set robust to harmless quote-boundary differences.

The runner calls the real ``run_tag`` against a throwaway database, so the sides / filler /
one-tag-per-quote rules (D1-D3) are part of what is measured. Real test sets contain customer
text: keep them OUTSIDE the repository. ``tests/fixtures/tagger_eval/example.json`` is a
synthetic example of the format.
"""

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.client import LLMClient
from app.llm.tagging import run_tag
from app.models import Company, Conversation, Highlight, Tag, Utterance
from app.seed import seed_tags

SUPPORTED_VERSION = 1
SIDES = {"us", "them", "unknown"}
DEFAULT_THRESHOLD = 0.8
DEFAULT_TOP_N = 10


@dataclass(frozen=True)
class ExpectedHighlight:
    call_id: str
    utterance_idx: int
    tag_key: str


@dataclass(frozen=True)
class Predicted:
    call_id: str
    utterance_idx: int
    tag_key: str


@dataclass(frozen=True)
class TestUtterance:
    speaker: str
    side: str
    text: str


@dataclass(frozen=True)
class TestCall:
    id: str
    utterances: list[TestUtterance]
    expected: list[ExpectedHighlight]
    interviewer: str | None = None
    company: str | None = None
    meta: dict[str, Any] | None = None


@dataclass(frozen=True)
class TestSet:
    calls: list[TestCall]
    description: str = ""

    def expected(self) -> list[ExpectedHighlight]:
        return [e for c in self.calls for e in c.expected]


@dataclass
class TagScore:
    tag_key: str
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else None


def score(predicted: list[Predicted], expected: list[ExpectedHighlight]) -> dict[str, TagScore]:
    """Per-tag true/false positives and misses. Duplicate predictions count once."""
    pred = {(p.call_id, p.utterance_idx, p.tag_key) for p in predicted}
    want = {(e.call_id, e.utterance_idx, e.tag_key) for e in expected}
    scores: dict[str, TagScore] = {}

    def bucket(tag: str) -> TagScore:
        return scores.setdefault(tag, TagScore(tag))

    for key in pred & want:
        bucket(key[2]).tp += 1
    for key in pred - want:
        bucket(key[2]).fp += 1
    for key in want - pred:
        bucket(key[2]).fn += 1
    return scores


def top_tags_by_usage(expected: list[ExpectedHighlight], n: int = DEFAULT_TOP_N) -> list[str]:
    """The tags the test set uses most (ties broken alphabetically)."""
    counts = Counter(e.tag_key for e in expected)
    return [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


@dataclass(frozen=True)
class GateFailure:
    tag_key: str
    precision: float | None
    reason: str


@dataclass(frozen=True)
class GateResult:
    passed: bool
    threshold: float
    failures: list[GateFailure] = field(default_factory=list)


def gate(scores: dict[str, TagScore], tags: list[str], threshold: float = DEFAULT_THRESHOLD) -> GateResult:
    """Pass only if every listed tag has precision >= threshold. A tag the tagger never
    produced cannot pass: silence is not accuracy."""
    failures: list[GateFailure] = []
    for tag in tags:
        precision = scores[tag].precision if tag in scores else None
        if precision is None:
            failures.append(GateFailure(tag, None, "no predictions"))
        elif precision < threshold:
            failures.append(GateFailure(tag, precision, f"precision {precision:.2f} < {threshold:.2f}"))
    return GateResult(passed=not failures, threshold=threshold, failures=failures)


def load_test_set(path: str | Path) -> TestSet:
    """Load and validate a test-set file. Raises ValueError with a pointed message."""
    data = json.loads(Path(path).read_text())
    if data.get("version") != SUPPORTED_VERSION:
        raise ValueError(f"Unsupported test-set version {data.get('version')!r} (expected {SUPPORTED_VERSION})")
    calls: list[TestCall] = []
    seen: set[str] = set()
    for raw in data.get("calls", []):
        call_id = str(raw.get("id", "")).strip()
        if not call_id:
            raise ValueError("Every call needs an id")
        if call_id in seen:
            raise ValueError(f"duplicate call id {call_id!r}")
        seen.add(call_id)
        utterances = []
        for u in raw.get("utterances", []):
            side = u.get("side", "unknown")
            if side not in SIDES:
                raise ValueError(f"{call_id}: side must be one of {sorted(SIDES)}, got {side!r}")
            utterances.append(TestUtterance(str(u.get("speaker", "")), side, str(u.get("text", ""))))
        expected = []
        for e in raw.get("expected", []):
            idx = e.get("utterance_idx")
            if not isinstance(idx, int) or not 0 <= idx < len(utterances):
                raise ValueError(f"{call_id}: utterance_idx {idx!r} is outside the transcript (0-{len(utterances) - 1})")
            expected.append(ExpectedHighlight(call_id, idx, str(e.get("tag_key", ""))))
        calls.append(TestCall(call_id, utterances, expected, raw.get("interviewer"), raw.get("company"), raw.get("meta")))
    return TestSet(calls=calls, description=str(data.get("description", "")))


@dataclass
class EvalReport:
    scores: dict[str, TagScore]
    predicted_total: int
    expected_total: int
    predictions: list[Predicted]


async def run_evaluation(
    test_set: TestSet,
    llm_for_call: Callable[[TestCall], LLMClient],
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tags: list[dict[str, Any]] | None = None,
) -> EvalReport:
    """Tag every call in the set with the real pipeline and score the result.

    ``session_factory`` MUST point at a throwaway database: this inserts conversations.
    ``tags`` optionally adds custom tags (dicts of Tag columns) on top of the core seed.
    """
    predictions: list[Predicted] = []
    async with session_factory() as db:
        await seed_tags(db)
        for spec in tags or []:
            if await db.get(Tag, spec["key"]) is None:
                db.add(Tag(**spec))
        await db.commit()

    for call in test_set.calls:
        async with session_factory() as db:
            company = None
            if call.company:
                company = Company(name=f"{call.company} ({call.id})")
                db.add(company)
                await db.flush()
            convo = Conversation(
                title=call.id, company_id=company.id if company else None, interviewer=call.interviewer,
                status="processing", raw_transcript="", transcript_format="name_colon", meta=call.meta,
            )
            db.add(convo)
            await db.flush()
            for i, u in enumerate(call.utterances):
                db.add(Utterance(conversation_id=convo.id, idx=i, speaker_label=u.speaker, speaker_side=u.side, text=u.text))
            await db.flush()

            llm = llm_for_call(call)
            try:
                await run_tag(db, convo.id, llm)
            finally:
                if hasattr(llm, "close"):
                    await llm.close()
            await db.commit()

            rows = await db.execute(
                select(Highlight, Utterance.idx)
                .join(Utterance, Highlight.utterance_id == Utterance.id)
                .where(Highlight.conversation_id == convo.id)
            )
            predictions += [Predicted(call.id, idx, h.tag_key) for h, idx in rows.all()]

    expected = test_set.expected()
    return EvalReport(
        scores=score(predictions, expected),
        predicted_total=len({(p.call_id, p.utterance_idx, p.tag_key) for p in predictions}),
        expected_total=len(expected),
        predictions=predictions,
    )


def format_report(report: EvalReport, result: GateResult, tags: list[str]) -> str:
    """A plain-text table for the terminal."""
    def pct(v: float | None) -> str:
        return "  n/a" if v is None else f"{v:5.2f}"

    lines = [f"{'tag':<22}{'precision':>10}{'recall':>8}{'tp':>5}{'fp':>5}{'fn':>5}", "-" * 55]
    for key in sorted(report.scores, key=lambda k: (k not in tags, k)):
        s = report.scores[key]
        mark = " *" if key in tags else ""
        lines.append(f"{key:<22}{pct(s.precision):>10}{pct(s.recall):>8}{s.tp:>5}{s.fp:>5}{s.fn:>5}{mark}")
    lines += ["", "* = a top tag the gate checks"]
    lines.append(
        f"GATE {'PASSED' if result.passed else 'FAILED'} (precision >= {result.threshold:.2f} on {len(tags)} top tags)"
    )
    lines += [f"  - {f.tag_key}: {f.reason}" for f in result.failures]
    return "\n".join(lines)
