"""v0.5 D1-D3: rules the tagger's output must satisfy, enforced in code (not just the prompt)."""

import pytest

from app.llm.tag_rules import (
    Candidate,
    TagInfo,
    allowed_on_side,
    is_filler,
    names_specifics,
    normalize_quote,
    select_highlights,
)


class TestSides:
    @pytest.mark.parametrize("tag", ["pain", "workaround", "money", "compliment", "obstacle", "custom_x"])
    def test_evidence_tags_only_on_customer_turns(self, tag):
        assert allowed_on_side(tag, "them")
        assert allowed_on_side(tag, "unknown")  # can't tell -> don't throw evidence away
        assert not allowed_on_side(tag, "us")

    @pytest.mark.parametrize("tag", ["followup", "commitment"])
    def test_followup_and_commitment_may_be_either_side(self, tag):
        for side in ("us", "them", "unknown"):
            assert allowed_on_side(tag, side)


class TestFiller:
    @pytest.mark.parametrize(
        "quote",
        ["Yes.", "Okay", "Sure", "Sounds good", "Yeah, okay.", "We will discuss this.", "Got it.",
         "uh huh", "Right, right.", "That is fine."],
    )
    def test_short_or_acknowledgement_quotes_are_filler(self, quote):
        assert is_filler(quote, "commitment")
        assert is_filler(quote, "sample_tag")

    @pytest.mark.parametrize(
        "quote",
        ["Every Monday I export the report to Excel by hand",
         "We spend about two hours cleaning the data each week",
         "Honestly the pricing is the main blocker for us right now"],
    )
    def test_real_statements_are_not_filler(self, quote):
        assert not is_filler(quote, "pain")

    def test_five_words_is_the_minimum(self):
        assert is_filler("We lose a lot", "pain")            # 4 words
        assert not is_filler("We lose a lot daily", "pain")  # 5 words

    @pytest.mark.parametrize(
        "quote",
        ["Yes, 2 p.m. Thursday works", "Thursday works.", "Yes, 2pm works", "OK, €5,000 is fine",
         "Sure, I'll introduce you to Sarah Connor", "Yes, next Tuesday"],
    )
    def test_commitment_naming_a_date_time_amount_or_person_is_not_filler(self, quote):
        assert not is_filler(quote, "commitment")

    def test_the_exception_is_only_for_commitments(self):
        assert is_filler("Thursday works.", "pain")
        assert is_filler("Yes, 2 p.m. Thursday works", "sample_tag") is False  # 5 words, not an ack
        assert is_filler("Yes, Thursday.", "pain")

    def test_vague_commitment_is_still_filler(self):
        assert is_filler("Yes, sounds good.", "commitment")
        assert is_filler("Yeah we will do that.", "commitment")  # no date/time/amount/person


class TestSpecifics:
    @pytest.mark.parametrize("text", ["2 p.m.", "at 14:30", "on Friday", "next week", "in March", "$5,000", "20k", "€300", "3 people", "with Sarah"])
    def test_detects_dates_times_amounts_people(self, text):
        assert names_specifics(f"Yes, {text}")

    @pytest.mark.parametrize("text", ["sounds good", "we will discuss it", "okay sure", "I think so"])
    def test_plain_agreement_has_none(self, text):
        assert not names_specifics(text)


def test_normalize_quote_ignores_case_punctuation_and_whitespace():
    assert normalize_quote("  The   Export, is SLOW! ") == normalize_quote("the export is slow")


def tags():
    return {
        "pain": TagInfo("pain", origin="core", category=None),
        "outcome": TagInfo("outcome", origin="custom", category="outcome"),
        "sample_tag": TagInfo("sample_tag", origin="custom", category="sales"),
        "competitor": TagInfo("competitor", origin="custom", category="sales"),
        "money": TagInfo("money", origin="core", category=None),
    }


def cand(idx, tag, quote, conf=0.9):
    return Candidate(utterance_idx=idx, tag_key=tag, quote=quote, confidence=conf)


class TestOneTagPerQuote:
    Q = "We need to protect our reputation online"

    def test_same_quote_same_utterance_keeps_the_best_single_tag(self):
        kept = select_highlights(
            [cand(1, "pain", self.Q, 0.8), cand(1, "pain", self.Q, 0.9)], [], tags()
        )
        assert len(kept) == 1 and kept[0].confidence == 0.9

    def test_second_tag_in_the_same_category_is_dropped(self):
        kept = select_highlights(
            [cand(1, "sample_tag", self.Q, 0.9), cand(1, "competitor", self.Q, 0.85)], [], tags()
        )
        assert [k.tag_key for k in kept] == ["sample_tag"]  # both 'sales' -> keep the stronger

    def test_second_tag_from_a_different_category_needs_both_at_07(self):
        kept = select_highlights(
            [cand(1, "pain", self.Q, 0.9), cand(1, "outcome", self.Q, 0.75)], [], tags()
        )
        assert {k.tag_key for k in kept} == {"pain", "outcome"}

    def test_second_tag_below_07_is_dropped(self):
        kept = select_highlights(
            [cand(1, "pain", self.Q, 0.9), cand(1, "outcome", self.Q, 0.65)], [], tags()
        )
        assert [k.tag_key for k in kept] == ["pain"]

    def test_a_weak_first_tag_does_not_unlock_a_second(self):
        kept = select_highlights(
            [cand(1, "pain", self.Q, 0.65), cand(1, "outcome", self.Q, 0.9)], [], tags()
        )
        assert [k.tag_key for k in kept] == ["outcome"]  # 0.65 < 0.7 so only the strongest survives

    def test_never_two_highlights_with_the_same_text_and_tag(self):
        kept = select_highlights(
            [cand(1, "pain", self.Q, 0.9), cand(7, "pain", self.Q.upper(), 0.8)], [], tags()
        )
        assert len(kept) == 1  # same text in a different utterance of the same call

    def test_different_quotes_are_independent(self):
        kept = select_highlights(
            [cand(1, "pain", "The export takes two hours every single week", 0.9),
             cand(2, "pain", "Nobody trusts the numbers on the dashboard", 0.9)], [], tags()
        )
        assert len(kept) == 2

    def test_a_quote_contained_in_another_counts_as_the_same_sentence(self):
        kept = select_highlights(
            [cand(1, "pain", "The export takes two hours every single week", 0.9),
             cand(1, "pain", "export takes two hours", 0.7)], [], tags()
        )
        assert len(kept) == 1

    def test_existing_highlights_block_duplicates_on_retag(self):
        existing = [cand(1, "pain", self.Q, 1.0)]  # e.g. a human-accepted highlight
        kept = select_highlights([cand(1, "pain", self.Q, 0.9)], existing, tags())
        assert kept == []

    def test_existing_highlight_in_same_category_blocks_a_second_tag(self):
        existing = [cand(1, "sample_tag", self.Q, 1.0)]
        kept = select_highlights([cand(1, "competitor", self.Q, 0.95)], existing, tags())
        assert kept == []

    def test_existing_highlight_allows_a_strong_tag_from_another_category(self):
        existing = [cand(1, "pain", self.Q, 0.9)]
        kept = select_highlights([cand(1, "outcome", self.Q, 0.8)], existing, tags())
        assert [k.tag_key for k in kept] == ["outcome"]

    def test_unknown_tag_info_is_treated_as_its_own_category(self):
        kept = select_highlights(
            [cand(1, "mystery_a", self.Q, 0.9), cand(1, "mystery_b", self.Q, 0.8)], [], tags()
        )
        assert {k.tag_key for k in kept} == {"mystery_a", "mystery_b"}

    def test_two_core_tags_share_a_category(self):
        kept = select_highlights(
            [cand(1, "pain", self.Q, 0.9), cand(1, "money", self.Q, 0.85)], [], tags()
        )
        assert [k.tag_key for k in kept] == ["pain"]
