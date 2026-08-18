"""Tests for UX audit findings #8 (commitment trust) and #9 (citation-or-silence)."""

from app.llm.schemas import CommitmentDetail, DigestInsightOutput
from app.services.digest import build_digest


class TestCommitmentTrust:
    """UX #8: CommitmentDetail requires actor and cost fields."""

    def test_commitment_has_actor_and_cost_fields(self):
        c = CommitmentDetail(
            what="Session with Tomas from legal next week",
            actor="Tomas (legal)",
            cost="1 hour meeting time",
            type="time",
            next_step="Follow up on Monday",
            evidence_highlight_ids=[41, 42],
        )
        assert c.actor == "Tomas (legal)"
        assert c.cost == "1 hour meeting time"
        assert c.next_step == "Follow up on Monday"
        assert c.evidence_highlight_ids == [41, 42]

    def test_commitment_backwards_compatible_without_actor_cost(self):
        """Existing stored results without actor/cost should still parse."""
        c = CommitmentDetail(what="Session with Tomas", type="time", next_step="Follow up")
        assert c.actor == ""
        assert c.cost == ""


class TestDigestInsightCitationOrSilence:
    """UX #9: DigestInsightOutput requires highlight_ids for validation."""

    def test_insight_output_has_highlight_ids(self):
        result = DigestInsightOutput(insight="Pattern found", highlight_ids=[1, 2, 3])
        assert result.highlight_ids == [1, 2, 3]

    def test_insight_output_empty_highlight_ids_is_valid(self):
        """Schema allows empty but validation logic rejects post-LLM."""
        result = DigestInsightOutput(insight="Generic uncited prose", highlight_ids=[])
        assert result.highlight_ids == []

    def test_build_digest_with_insufficient_insight(self):
        """When insight is 'Not enough signal this week.', it should still appear."""
        from datetime import date

        snapshot = {
            "insight_of_the_week": "Not enough signal this week.",
        }
        md = build_digest(snapshot, date(2026, 8, 18))
        assert "Not enough signal this week." in md

    def test_build_digest_with_valid_insight(self):
        from datetime import date

        snapshot = {
            "insight_of_the_week": "Manual triage dominates across all enterprise segments.",
        }
        md = build_digest(snapshot, date(2026, 8, 18))
        assert "Manual triage dominates" in md

    def test_build_digest_empty_when_no_data(self):
        from datetime import date

        snapshot = {}
        md = build_digest(snapshot, date(2026, 8, 18))
        assert md == ""
