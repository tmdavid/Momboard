"""v0.5 D5: measure the tagger. Per-tag precision/recall on a hand-tagged test set, and a gate
that must pass before any full retag."""

import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.client import FakeLLMClient
from app.llm.tagger_eval import (
    ExpectedHighlight,
    Predicted,
    gate,
    load_test_set,
    run_evaluation,
    score,
    top_tags_by_usage,
)

EXAMPLE = Path(__file__).parent / "fixtures" / "tagger_eval" / "example.json"


def exp(call, idx, tag):
    return ExpectedHighlight(call_id=call, utterance_idx=idx, tag_key=tag)


def pred(call, idx, tag):
    return Predicted(call_id=call, utterance_idx=idx, tag_key=tag)


class TestScore:
    def test_perfect(self):
        s = score([pred("c", 1, "pain")], [exp("c", 1, "pain")])
        assert s["pain"].precision == 1.0 and s["pain"].recall == 1.0

    def test_extra_prediction_lowers_precision_not_recall(self):
        s = score([pred("c", 1, "pain"), pred("c", 2, "pain")], [exp("c", 1, "pain")])
        assert s["pain"].precision == 0.5 and s["pain"].recall == 1.0
        assert (s["pain"].tp, s["pain"].fp, s["pain"].fn) == (1, 1, 0)

    def test_missed_expectation_lowers_recall_not_precision(self):
        s = score([pred("c", 1, "pain")], [exp("c", 1, "pain"), exp("c", 2, "pain")])
        assert s["pain"].precision == 1.0 and s["pain"].recall == 0.5

    def test_wrong_tag_is_a_false_positive_and_a_miss(self):
        s = score([pred("c", 1, "money")], [exp("c", 1, "pain")])
        assert s["money"].fp == 1 and s["pain"].fn == 1

    def test_same_utterance_in_a_different_call_is_not_a_match(self):
        s = score([pred("a", 1, "pain")], [exp("b", 1, "pain")])
        assert s["pain"].tp == 0

    def test_precision_is_none_when_nothing_was_predicted(self):
        s = score([], [exp("c", 1, "pain")])
        assert s["pain"].precision is None and s["pain"].recall == 0.0

    def test_duplicates_are_counted_once(self):
        s = score([pred("c", 1, "pain"), pred("c", 1, "pain")], [exp("c", 1, "pain")])
        assert s["pain"].tp == 1 and s["pain"].fp == 0


class TestGate:
    def scores(self):
        return score(
            [pred("c", i, "pain") for i in range(10)] + [pred("c", 20, "money")],
            [exp("c", i, "pain") for i in range(9)] + [exp("c", 21, "money")],
        )

    def test_top_tags_are_ordered_by_how_often_the_set_uses_them(self):
        assert top_tags_by_usage([exp("c", i, "pain") for i in range(3)] + [exp("c", 9, "money")], 1) == ["pain"]

    def test_fails_when_a_top_tag_is_below_threshold(self):
        result = gate(self.scores(), ["pain", "money"], threshold=0.8)
        assert not result.passed
        assert [f.tag_key for f in result.failures] == ["money"]  # 0/1 precision

    def test_passes_when_all_top_tags_meet_the_threshold(self):
        result = gate(self.scores(), ["pain"], threshold=0.8)
        assert result.passed and not result.failures

    def test_a_tag_with_no_predictions_cannot_pass(self):
        result = gate(score([], [exp("c", 1, "pain")]), ["pain"], threshold=0.8)
        assert not result.passed and result.failures[0].reason == "no predictions"


class TestLoad:
    def test_loads_the_example_set(self):
        ts = load_test_set(EXAMPLE)
        assert [c.id for c in ts.calls] == ["example-01", "example-02"]
        assert len(ts.expected()) == 4 and ts.calls[0].utterances[1].side == "them"

    def test_rejects_an_expectation_pointing_past_the_transcript(self, tmp_path):
        bad = {"version": 1, "calls": [{"id": "x", "utterances": [{"speaker": "A", "side": "them", "text": "hi there friend"}],
                                        "expected": [{"utterance_idx": 5, "tag_key": "pain"}]}]}
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(bad))
        with pytest.raises(ValueError, match="utterance_idx"):
            load_test_set(p)

    def test_rejects_duplicate_call_ids(self, tmp_path):
        call = {"id": "x", "utterances": [{"speaker": "A", "side": "them", "text": "hello there my friend"}], "expected": []}
        p = tmp_path / "dup.json"
        p.write_text(json.dumps({"version": 1, "calls": [call, call]}))
        with pytest.raises(ValueError, match="duplicate"):
            load_test_set(p)

    def test_rejects_unsupported_version(self, tmp_path):
        p = tmp_path / "v.json"
        p.write_text(json.dumps({"version": 99, "calls": []}))
        with pytest.raises(ValueError, match="version"):
            load_test_set(p)


@pytest.mark.asyncio
async def test_end_to_end_with_a_stub_llm_runs_the_real_pipeline(session_factory: async_sessionmaker[AsyncSession]):
    """The runner uses run_tag, so D1-D3 (sides, filler, one tag per quote) apply to the score."""
    ts = load_test_set(EXAMPLE)

    def llm_for(call):
        fake = FakeLLMClient()
        # Correct answers, plus a rep line (must be dropped) and filler (must be dropped).
        base = {"example-01": [
            (1, "workaround", "Every Monday I export the report to Excel and clean it by hand"),
            (2, "pain", "It honestly takes me about two hours and nobody trusts the numbers"),
            (3, "pain", "We can automate all of that for you with one click"),
            (4, "commitment", "Yes."),
        ], "example-02": [
            (1, "commitment", "Yes, 2 p.m. Thursday works for the pilot kickoff"),
            (2, "money", "Our budget for this is about 5,000 euros per quarter"),
        ]}[call.id]
        fake.set_fixture("tagger", {"highlights": [
            {"utterance_idx": i, "tag_key": t, "quote": q, "confidence": 0.9, "rationale": "r"} for i, t, q in base
        ]})
        return fake

    report = await run_evaluation(ts, llm_for, session_factory)
    assert report.scores["pain"].precision == 1.0
    assert report.scores["workaround"].precision == 1.0
    assert report.scores["commitment"].precision == 1.0   # the filler 'Yes.' never counted
    assert report.scores["money"].recall == 1.0
    assert report.predicted_total == 4                      # rep line and filler were dropped by the rules


@pytest.mark.asyncio
async def test_a_wrong_prediction_shows_up_as_lower_precision(session_factory: async_sessionmaker[AsyncSession]):
    ts = load_test_set(EXAMPLE)

    def llm_for(call):
        fake = FakeLLMClient()
        h = {"example-01": [(1, "pain", "Every Monday I export the report to Excel and clean it by hand")],
             "example-02": [(2, "money", "Our budget for this is about 5,000 euros per quarter")]}[call.id]
        fake.set_fixture("tagger", {"highlights": [{"utterance_idx": i, "tag_key": t, "quote": q, "confidence": 0.9, "rationale": "r"} for i, t, q in h]})
        return fake

    report = await run_evaluation(ts, llm_for, session_factory)
    assert report.scores["pain"].precision == 0.0           # idx 1 should have been 'workaround'
    assert report.scores["workaround"].recall == 0.0


class TestCommandLine:
    """scripts/eval_tagger.py end to end: a throwaway migrated database, the real pipeline,
    a stub LLM, and an exit code that says whether the gate passed."""

    @staticmethod
    def _llm_factory(answers: dict[str, list[tuple[int, str, str]]]):
        def factory(call):
            fake = FakeLLMClient()
            fake.set_fixture("tagger", {"highlights": [
                {"utterance_idx": i, "tag_key": t, "quote": q, "confidence": 0.9, "rationale": "r"}
                for i, t, q in answers[call.id]
            ]})
            return fake
        return factory

    GOOD = {
        "example-01": [
            (1, "workaround", "Every Monday I export the report to Excel and clean it by hand"),
            (2, "pain", "It honestly takes me about two hours and nobody trusts the numbers"),
        ],
        "example-02": [
            (1, "commitment", "Yes, 2 p.m. Thursday works for the pilot kickoff"),
            (2, "money", "Our budget for this is about 5,000 euros per quarter"),
        ],
    }

    def _run(self, answers, capsys, *extra):
        import importlib.util

        spec = importlib.util.spec_from_file_location("eval_tagger", Path(__file__).parent.parent / "scripts" / "eval_tagger.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        code = mod.main([str(EXAMPLE), *extra], llm_factory=self._llm_factory(answers))
        return code, capsys.readouterr().out

    def test_passes_the_gate_when_the_tagger_is_right(self, capsys):
        code, out = self._run(self.GOOD, capsys)
        assert code == 0
        assert "GATE PASSED" in out and "workaround" in out

    def test_fails_the_gate_and_says_why(self, capsys):
        bad = {**self.GOOD, "example-01": [(1, "pain", "Every Monday I export the report to Excel and clean it by hand")]}
        code, out = self._run(bad, capsys)
        assert code == 1
        assert "GATE FAILED" in out
        assert "pain: precision 0.00" in out          # right quote, wrong tag
        assert "workaround: no predictions" in out    # the tag it should have used

    def test_custom_tags_can_be_supplied_and_scored(self, capsys, tmp_path):
        tags = tmp_path / "tags.json"
        tags.write_text(json.dumps([{"key": "budget", "emoji": "💶", "name": "Budget", "origin": "custom", "category": "money",
                                     "sort_order": 70, "is_active": True, "min_confidence": 0.6, "ignored_extra_field": 1}]))
        answers = {**self.GOOD, "example-02": [
            (1, "commitment", "Yes, 2 p.m. Thursday works for the pilot kickoff"),
            (2, "budget", "Our budget for this is about 5,000 euros per quarter"),
        ]}
        code, out = self._run(answers, capsys, "--tags-json", str(tags), "--threshold", "0.5")
        assert "budget" in out

    def test_bad_test_set_exits_with_a_usage_code(self, capsys, tmp_path):
        import importlib.util

        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"version": 7, "calls": []}))
        spec = importlib.util.spec_from_file_location("eval_tagger2", Path(__file__).parent.parent / "scripts" / "eval_tagger.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.main([str(bad)], llm_factory=lambda c: FakeLLMClient()) == 2
        assert "Unsupported test-set version" in capsys.readouterr().out
