"""PRD grounding bands: confirmed links only, thresholds from settings."""

import pytest

from app.services.hypothesis_grounding import (
    BandThresholds,
    band_rules,
    compute_band,
    explain_band,
)


def band(sup: int, con: int, co_sup: int, *, pending: int = 0, t: BandThresholds | None = None) -> str:
    return compute_band(
        {"confirmed": sup, "suggested": pending},
        {"confirmed": con, "suggested": 0},
        co_sup,
        t,
    )


# (confirmed supports, confirmed contradicts, companies supporting) -> band
PRD_CASES = [
    # Hunch: 0 confirmed links
    (0, 0, 0, "hunch"),
    # Candidate: 1-2 supporting, or only 1 company
    (1, 0, 1, "candidate"),
    (2, 0, 2, "candidate"),
    (3, 0, 1, "candidate"),   # 3 quotes but a single company: "needs more companies"
    (5, 0, 1, "candidate"),
    # Grounded: 3+ supporting from 2+ companies, at most 1 contradicting
    (3, 0, 2, "grounded"),
    (3, 1, 2, "grounded"),
    (6, 1, 4, "grounded"),
    # Contested: 2+ supporting AND 2+ contradicting
    (2, 2, 2, "contested"),
    (3, 2, 2, "contested"),   # too many contradictions to stay grounded
    (4, 3, 3, "contested"),
    # Refuted: 3+ contradicting, more than twice the supporting
    (0, 3, 0, "refuted"),
    (1, 3, 1, "refuted"),
    (1, 4, 1, "refuted"),
    (2, 5, 2, "refuted"),     # also 2+/2+, but overwhelmingly contradicted -> refuted wins
    # Not enough on either side yet -> candidate (some evidence, no verdict)
    (1, 1, 1, "candidate"),
    (0, 1, 0, "candidate"),
    (0, 2, 0, "candidate"),
    (2, 3, 2, "contested"),   # 3 is not > 2*2, so not refuted; 2+/2+ -> contested
    (1, 2, 1, "candidate"),   # 2 contradicting is below the refuted floor of 3
]


@pytest.mark.parametrize("sup,con,co,expected", PRD_CASES)
def test_prd_band_rules(sup: int, con: int, co: int, expected: str):
    assert band(sup, con, co) == expected


def test_suggested_links_never_move_the_band():
    assert band(0, 0, 0, pending=9) == "hunch"
    assert band(3, 0, 2, pending=9) == "grounded"
    assert band(1, 0, 1, pending=9) == "candidate"


def test_thresholds_are_configurable():
    strict = BandThresholds(grounded_min_support=5, grounded_min_companies=3)
    assert band(3, 0, 2, t=strict) == "candidate"
    assert band(5, 0, 3, t=strict) == "grounded"
    loose = BandThresholds(grounded_min_support=1, grounded_min_companies=1)
    assert band(1, 0, 1, t=loose) == "grounded"


def test_defaults_are_the_prd_numbers():
    t = BandThresholds()
    assert (t.grounded_min_support, t.grounded_min_companies, t.grounded_max_contradict) == (3, 2, 1)
    assert t.contested_min_each == 2
    assert (t.refuted_min_contradict, t.refuted_ratio) == (3, 2.0)


class TestExplainBand:
    def _why(self, sup, con, co_sup, co_con=0, pending=0):
        return explain_band(
            {"confirmed": sup, "suggested": pending},
            {"confirmed": con, "suggested": 0},
            co_sup,
            co_con,
        )

    def test_hunch(self):
        assert self._why(0, 0, 0) == "No evidence yet."

    def test_hunch_with_pending_mentions_review(self):
        assert "awaiting review" in self._why(0, 0, 0, pending=2)
        assert "2 suggested quotes" in self._why(0, 0, 0, pending=2)

    def test_grounded(self):
        assert self._why(4, 0, 3) == "4 supporting quotes from 3 companies, 0 contradicting."

    def test_candidate_says_what_is_missing_for_grounded(self):
        why = self._why(1, 0, 1)
        assert why.startswith("1 supporting quote from 1 company")
        assert "Grounded needs 3 supporting quotes from 2 companies" in why

    def test_single_company_candidate_asks_for_more_companies(self):
        why = self._why(4, 0, 1)
        assert "needs more companies" in why.lower() or "from 2 companies" in why

    def test_contested_shows_both_sides(self):
        why = self._why(3, 2, 2, co_con=2)
        assert "3 supporting quotes from 2 companies vs 2 contradicting quotes from 2 companies" in why

    def test_refuted(self):
        assert self._why(0, 3, 0, co_con=2) == "3 contradicting quotes from 2 companies, none supporting."


def test_band_rules_describe_all_five_bands_with_live_numbers():
    rules = band_rules(BandThresholds(grounded_min_support=4))
    assert [r["band"] for r in rules] == ["grounded", "contested", "candidate", "hunch", "refuted"]
    grounded = next(r for r in rules if r["band"] == "grounded")
    assert "4" in grounded["rule"]


def test_thresholds_come_from_settings_env(monkeypatch: pytest.MonkeyPatch):
    from app.services.hypothesis_grounding import get_band_thresholds

    monkeypatch.setenv("HYPOTHESIS_GROUNDED_MIN_SUPPORT", "5")
    monkeypatch.setenv("HYPOTHESIS_GROUNDED_MIN_COMPANIES", "3")
    monkeypatch.setenv("HYPOTHESIS_REFUTED_RATIO", "3")
    get_band_thresholds.cache_clear()
    try:
        t = get_band_thresholds()
        assert (t.grounded_min_support, t.grounded_min_companies, t.refuted_ratio) == (5, 3, 3.0)
        # compute_band picks the configured numbers up by default
        assert band(3, 0, 2) == "candidate"
        assert band(5, 0, 3) == "grounded"
    finally:
        monkeypatch.undo()
        get_band_thresholds.cache_clear()
    assert get_band_thresholds().grounded_min_support == 3
