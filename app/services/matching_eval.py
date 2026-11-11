"""Check hypothesis matching against beliefs with known answers (v0.5 D8).

Keep a list of about ten beliefs in a private file: for each, the call(s) that really do say it
(``expected``) and, optionally, calls that definitely do not (``unrelated``). After any change to
matching, run ``scripts/eval_matching.py``. The bar from the plan:

  * each known belief returns its known call in the TOP 5, and
  * no more than 1 in 5 matches is unrelated.

"Unrelated" is only counted for matches that hit an ``unrelated`` selector you labelled, so label a
few obvious wrong calls per belief; unlabelled extras are neither right nor wrong. The real list names
real calls, so it must live OUTSIDE the repository.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Conversation
from app.services.hypothesis_intake import preview_intake

SUPPORTED_VERSION = 1
TOP_N = 5
MAX_UNRELATED_RATE = 0.2


@dataclass(frozen=True)
class Selector:
    """Identifies a call by id, title text or company text. At least one criterion is required."""

    conversation_id: int | None = None
    conversation_title_contains: str | None = None
    company_name_contains: str | None = None

    @property
    def empty(self) -> bool:
        return not (self.conversation_id or self.conversation_title_contains or self.company_name_contains)


@dataclass(frozen=True)
class Belief:
    belief: str
    segment: str | None
    expected: list[Selector]
    unrelated: list[Selector] = field(default_factory=list)


def matches_selector(match: dict[str, Any], selector: Selector, titles: dict[int, str]) -> bool:
    if selector.empty:
        return False
    if selector.conversation_id is not None and match["conversation_id"] != selector.conversation_id:
        return False
    if selector.conversation_title_contains is not None and (
        selector.conversation_title_contains.lower() not in titles.get(match["conversation_id"], "").lower()
    ):
        return False
    if selector.company_name_contains is not None and (
        selector.company_name_contains.lower() not in (match.get("company_name") or "").lower()
    ):
        return False
    return True


@dataclass(frozen=True)
class BeliefResult:
    belief: str
    hit_rank: int | None       # 1-based position of the first expected call among the matches
    found_in_top: bool         # hit_rank <= TOP_N
    unrelated: int             # matches that hit a labelled 'unrelated' call
    total: int                 # matches returned


def score_belief(belief: Belief, matches: list[dict[str, Any]], titles: dict[int, str]) -> BeliefResult:
    hit = next(
        (i for i, m in enumerate(matches, start=1) if any(matches_selector(m, s, titles) for s in belief.expected)),
        None,
    )
    unrelated = sum(1 for m in matches if any(matches_selector(m, s, titles) for s in belief.unrelated))
    return BeliefResult(belief.belief, hit, hit is not None and hit <= TOP_N, unrelated, len(matches))


@dataclass(frozen=True)
class GateResult:
    passed: bool
    unrelated_rate: float | None
    reasons: list[str]


def gate(results: list[BeliefResult], labelled: bool = True) -> GateResult:
    reasons = [f'"{r.belief[:60]}": not found in the top {TOP_N}' for r in results if not r.found_in_top]
    total = sum(r.total for r in results)
    rate = (sum(r.unrelated for r in results) / total) if labelled and total else None
    if rate is not None and rate > MAX_UNRELATED_RATE:
        reasons.append(f"{rate:.0%} of matches are unrelated (limit {MAX_UNRELATED_RATE:.0%})")
    return GateResult(passed=not reasons, unrelated_rate=rate, reasons=reasons)


def _selector(raw: Any, where: str) -> Selector:
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: each selector must be an object")
    sel = Selector(
        conversation_id=raw.get("conversation_id"),
        conversation_title_contains=raw.get("conversation_title_contains"),
        company_name_contains=raw.get("company_name_contains"),
    )
    if sel.empty:
        raise ValueError(f"{where}: a selector needs conversation_id, conversation_title_contains or company_name_contains")
    return sel


def load_beliefs(path: str | Path) -> list[Belief]:
    data = json.loads(Path(path).read_text())
    if data.get("version") != SUPPORTED_VERSION:
        raise ValueError(f"Unsupported known-beliefs version {data.get('version')!r} (expected {SUPPORTED_VERSION})")
    beliefs: list[Belief] = []
    for i, raw in enumerate(data.get("beliefs", []), start=1):
        text = str(raw.get("belief", "")).strip()
        if len(text) < 15:
            raise ValueError(f"belief {i}: the statement must be at least 15 characters")
        expected = [_selector(s, f"belief {i} expected") for s in raw.get("expected", [])]
        if not expected:
            raise ValueError(f"belief {i}: needs at least one expected call")
        unrelated = [_selector(s, f"belief {i} unrelated") for s in raw.get("unrelated", [])]
        beliefs.append(Belief(text, raw.get("segment") or None, expected, unrelated))
    return beliefs


@dataclass
class EvalReport:
    results: list[BeliefResult]
    titles_by_conversation: dict[int, str]
    match_lists: list[list[dict[str, Any]]]


async def run_evaluation(
    beliefs: list[Belief],
    llm_for_belief: Callable[[Belief], Any],
    session_factory: async_sessionmaker[AsyncSession],
) -> EvalReport:
    """Run the real preview for each belief. Read-only: ``preview_intake`` saves nothing."""
    results: list[BeliefResult] = []
    lists: list[list[dict[str, Any]]] = []
    titles: dict[int, str] = {}
    for belief in beliefs:
        llm = llm_for_belief(belief)
        try:
            async with session_factory() as db:
                out = await preview_intake(db, belief.belief, llm=llm, segment=belief.segment)
                ids = {m["conversation_id"] for m in out["matches"]}
                if ids:
                    rows = await db.execute(select(Conversation.id, Conversation.title).where(Conversation.id.in_(ids)))
                    titles.update({i: t for i, t in rows.all()})
        finally:
            if hasattr(llm, "close"):
                await llm.close()
        lists.append(out["matches"])
        results.append(score_belief(belief, out["matches"], titles))
    return EvalReport(results, titles, lists)
