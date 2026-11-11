"""v0.5 D8: check hypothesis matching against beliefs with known answers."""

import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.schemas import IntakeMatch, IntakeMatchOutput, SearchTerms
from app.models import Company, Conversation, Utterance
from app.seed import seed_tags
from app.services.matching_eval import (
    Belief,
    Selector,
    gate,
    load_beliefs,
    matches_selector,
    run_evaluation,
    score_belief,
)

EXAMPLE = Path(__file__).parent / "fixtures" / "tagger_eval" / "known_beliefs_example.json"
TITLES = {1: "Call with Pierce Law", 2: "Watch Shop call", 3: "Other call", 4: "Another", 5: "Fifth", 6: "Sixth"}


def m(conv):
    return {"conversation_id": conv}


class TestSelector:
    def test_by_id(self):
        assert matches_selector(m(2), Selector(conversation_id=2), TITLES)
        assert not matches_selector(m(3), Selector(conversation_id=2), TITLES)

    def test_by_title_is_case_insensitive_and_partial(self):
        assert matches_selector(m(1), Selector(conversation_title_contains="pierce"), TITLES)
        assert not matches_selector(m(2), Selector(conversation_title_contains="pierce"), TITLES)

    def test_an_empty_selector_matches_nothing(self):
        assert not matches_selector(m(1), Selector(), TITLES)


class TestScoreBelief:
    belief = Belief("b", None, [Selector(conversation_title_contains="Pierce")], [Selector(conversation_title_contains="Watch")])

    def test_hit_rank_is_one_based(self):
        r = score_belief(self.belief, [m(3), m(1), m(2)], TITLES)
        assert r.hit_rank == 2 and r.found_in_top is True and r.unrelated == 1 and r.total == 3

    def test_miss(self):
        r = score_belief(self.belief, [m(3), m(4)], TITLES)
        assert r.hit_rank is None and not r.found_in_top

    def test_only_the_top_five_count_for_the_hit(self):
        r = score_belief(self.belief, [m(3), m(4), m(5), m(6), m(2), m(1)], TITLES)
        assert r.hit_rank == 6 and not r.found_in_top

    def test_no_matches_at_all_is_a_miss(self):
        r = score_belief(self.belief, [], TITLES)
        assert r.hit_rank is None and r.total == 0


class TestGate:
    def results(self, hits, unrelated=0, total=10):
        from app.services.matching_eval import BeliefResult

        return [BeliefResult("b", h, h is not None and h <= 5, unrelated, total) for h in hits]

    def test_passes_when_every_belief_is_found_and_unrelated_is_low(self):
        g = gate(self.results([1, 3], unrelated=1, total=10))
        assert g.passed and g.unrelated_rate == 0.1

    def test_fails_when_a_belief_is_missed(self):
        g = gate(self.results([1, None]))
        assert not g.passed and "not found in the top 5" in g.reasons[0]

    def test_fails_when_more_than_one_in_five_is_unrelated(self):
        g = gate(self.results([1, 1], unrelated=5, total=20))
        assert not g.passed and any("unrelated" in r for r in g.reasons)

    def test_unrelated_rate_is_unknown_without_labels(self):
        g = gate(self.results([1], unrelated=0, total=10), labelled=False)
        assert g.passed and g.unrelated_rate is None


class TestLoad:
    def test_loads_the_example(self):
        beliefs = load_beliefs(EXAMPLE)
        assert beliefs[0].segment == "law firm" and beliefs[0].expected[0].conversation_title_contains == "Pierce"

    def test_rejects_a_belief_with_no_expected_call(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_text(json.dumps({"version": 1, "beliefs": [{"belief": "x" * 20, "expected": []}]}))
        with pytest.raises(ValueError, match="expected"):
            load_beliefs(p)

    def test_rejects_a_selector_with_no_criteria(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_text(json.dumps({"version": 1, "beliefs": [{"belief": "x" * 20, "expected": [{}]}]}))
        with pytest.raises(ValueError, match="selector"):
            load_beliefs(p)

    def test_rejects_an_unsupported_version(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_text(json.dumps({"version": 3, "beliefs": []}))
        with pytest.raises(ValueError, match="version"):
            load_beliefs(p)


class RoutedLLM:
    def __init__(self, terms, judge_ids_fn):
        self.terms, self.judge_ids_fn = terms, judge_ids_fn

    async def generate(self, *, prompt, schema, model="default"):  # noqa: ARG002
        if schema is SearchTerms:
            return SearchTerms(terms=self.terms)
        import re

        ids = [int(x) for x in re.findall(r"id=(-?\d+)", prompt)]
        return IntakeMatchOutput(matches=[IntakeMatch(highlight_id=i, relation="supports", confidence=0.9, rationale="r") for i in ids if self.judge_ids_fn(prompt, i)])

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_end_to_end_finds_the_known_call(session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as db:
        await seed_tags(db)
        law, shop = Company(name="Pierce Law Group", notes="law firm"), Company(name="Watch Shop")
        db.add_all([law, shop])
        await db.flush()
        for company, title, text in (
            (law, "Call with Pierce Law", "We would want a pilot with two attorneys before any annual contract."),
            (shop, "Watch Shop call", "We handle takedowns by hand, and a pilot would not change that for us."),
        ):
            c = Conversation(title=title, company_id=company.id, status="ready", source="upload", raw_transcript="x", transcript_format="name_colon")
            db.add(c)
            await db.flush()
            db.add(Utterance(conversation_id=c.id, idx=0, speaker_label="P", speaker_side="them", text=text))
        await db.commit()

    beliefs = load_beliefs(EXAMPLE)
    report = await run_evaluation(beliefs, lambda b: RoutedLLM(["pilot"], lambda p, i: True), session_factory)
    r = report.results[0]
    assert r.found_in_top and r.unrelated == 1 and r.total == 2     # watch shop surfaced, labelled unrelated
    assert report.titles_by_conversation and report.match_lists[0]
    assert not gate(report.results).passed                          # 1 of 2 unrelated = 50% > 20%


def _load_cli():
    import importlib.util

    spec = importlib.util.spec_from_file_location("eval_matching", Path(__file__).parent.parent / "scripts" / "eval_matching.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bad_file_exits_with_a_usage_code(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"version": 9, "beliefs": []}))
    assert _load_cli().main([str(bad)]) == 2
    assert "version" in capsys.readouterr().out


def test_only_sqlite_is_accepted_and_the_url_is_read_only():
    mod = _load_cli()
    assert "mode=ro" in mod.readonly_url("sqlite+aiosqlite:////tmp/x.db")
    with pytest.raises(SystemExit):
        mod.readonly_url("postgresql+asyncpg://u@h/db")


def test_end_to_end_on_a_real_file_database_is_read_only(tmp_path, capsys):
    """Build a migrated database file, run the CLI with a stub LLM, and prove nothing was written."""
    import asyncio
    import os
    import sqlite3
    import subprocess
    import sys

    db_file = tmp_path / "live.db"
    root = Path(__file__).parent.parent
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True,
                   env={**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_file}"})

    async def seed():
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            await seed_tags(db)
            law = Company(name="Pierce Law Group", notes="law firm")
            db.add(law)
            await db.flush()
            c = Conversation(title="Call with Pierce Law", company_id=law.id, status="ready", source="upload",
                             raw_transcript="x", transcript_format="name_colon")
            db.add(c)
            await db.flush()
            db.add(Utterance(conversation_id=c.id, idx=0, speaker_label="P", speaker_side="them",
                             text="We would want a pilot with two attorneys before any annual contract."))
            await db.commit()
        await engine.dispose()

    asyncio.run(seed())
    before = sqlite3.connect(db_file).execute("select (select count(*) from highlights), (select count(*) from hypotheses), (select count(*) from hypothesis_links)").fetchone()

    code = _load_cli().main([str(EXAMPLE), "--db", f"sqlite+aiosqlite:///{db_file}", "-v"],
                            llm_factory=lambda b: RoutedLLM(["pilot"], lambda p, i: True))
    out = capsys.readouterr().out
    after = sqlite3.connect(db_file).execute("select (select count(*) from highlights), (select count(*) from hypotheses), (select count(*) from hypothesis_links)").fetchone()
    assert code == 0 and "GATE PASSED" in out and "found at #1" in out
    assert before == after == (0, 0, 0)
