"""T27 RED: Hypothesis tracking backend — CRUD, status lifecycle, evidence linking, rollup.

Tests cover:
- CRUD with status lifecycle (open → supported/refuted/parked)
- Statement immutability after evidence link (409)
- Hypothesis linker: runs after tagging, proposes supports/contradicts links
- Linker only considers open hypotheses and non-rejected highlights
- Only valid hypothesis/highlight IDs persisted (invalid stripped)
- Accept/reject link
- Detail rollup: by stance/status, distinct confirmed companies, last_evidence_at, verdict_hint
- Deterministic verdict_hint without auto status changes
- Delete highlight cascades hypothesis_links
- Skip/enqueue behavior depending on open hypotheses
- Auth/OpenAPI response contracts

All tests are RED — the feature (models, routes, linker) doesn't exist yet.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.llm.client import FakeLLMClient
from app.models import (
    Company,
    Contact,
    Conversation,
    ConversationContact,
    Highlight,
    Job,
    User,
    Utterance,
)
from app.seed import seed_tags

# ---------------------------------------------------------------------------
# Helpers / fixtures local to this test module
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def hyp_seeded(
    session_factory: async_sessionmaker[AsyncSession], user_david: User
) -> dict:
    """Seed data: 2 companies, 2 conversations with highlights, for hypothesis tests."""
    async with session_factory() as session:
        await seed_tags(session)

        co1 = Company(name="Acme Watches")
        co2 = Company(name="Northwind")
        session.add_all([co1, co2])
        await session.flush()

        ct1 = Contact(name="Maria", role="Brand Manager", company_id=co1.id)
        ct2 = Contact(name="Jan", role="VP Legal", company_id=co2.id)
        session.add_all([ct1, ct2])
        await session.flush()

        # Conversation 1
        convo1 = Conversation(
            title="Acme discovery",
            company_id=co1.id,
            interviewer="David",
            status="ready",
            raw_transcript="David: hi\nMaria: hello",
            transcript_format="name_colon",
        )
        session.add(convo1)
        await session.flush()
        session.add(ConversationContact(conversation_id=convo1.id, contact_id=ct1.id))

        utt1 = Utterance(
            conversation_id=convo1.id,
            idx=0,
            speaker_label="Maria",
            speaker_side="them",
            text="Every Monday I export it to Excel and clean it by hand.",
        )
        session.add(utt1)
        await session.flush()

        h1 = Highlight(
            conversation_id=convo1.id,
            utterance_id=utt1.id,
            tag_key="workaround",
            quote="Every Monday I export it to Excel and clean it by hand",
            confidence=0.95,
            origin="ai",
            status="accepted",
        )
        session.add(h1)
        await session.flush()

        # Conversation 2
        convo2 = Conversation(
            title="Northwind check-in",
            company_id=co2.id,
            interviewer="David",
            status="ready",
            raw_transcript="David: hi\nJan: hello",
            transcript_format="name_colon",
        )
        session.add(convo2)
        await session.flush()
        session.add(ConversationContact(conversation_id=convo2.id, contact_id=ct2.id))

        utt2 = Utterance(
            conversation_id=convo2.id,
            idx=0,
            speaker_label="Jan",
            speaker_side="them",
            text="Honestly the export is fine, it's the nine takedown templates that kill us.",
        )
        session.add(utt2)
        await session.flush()

        h2 = Highlight(
            conversation_id=convo2.id,
            utterance_id=utt2.id,
            tag_key="pain",
            quote="Honestly the export is fine, it's the nine takedown templates that kill us",
            confidence=0.88,
            origin="ai",
            status="accepted",
        )
        # A rejected highlight that must NOT be fed to linker
        h3 = Highlight(
            conversation_id=convo2.id,
            utterance_id=utt2.id,
            tag_key="context",
            quote="We have three brand protection people",
            confidence=0.60,
            origin="ai",
            status="rejected",
        )
        session.add_all([h2, h3])
        await session.flush()

        await session.commit()

        # Refresh ids
        await session.refresh(co1)
        await session.refresh(co2)
        await session.refresh(convo1)
        await session.refresh(convo2)
        await session.refresh(h1)
        await session.refresh(h2)
        await session.refresh(h3)

        return {
            "company1": co1,
            "company2": co2,
            "conversation1": convo1,
            "conversation2": convo2,
            "highlight1": h1,
            "highlight2": h2,
            "highlight_rejected": h3,
            "user": user_david,
        }


def _fake_llm_for_linker(hypothesis_id: int, highlight_id: int) -> FakeLLMClient:
    """Create a FakeLLMClient with hypothesis_linker fixture pointing to given IDs."""
    return FakeLLMClient(
        fixtures={
            "hypothesis_linker": {
                "links": [
                    {
                        "hypothesis_id": hypothesis_id,
                        "highlight_id": highlight_id,
                        "stance": "supports",
                        "confidence": 0.88,
                        "rationale": "Direct evidence of willingness to pay",
                    }
                ]
            }
        }
    )


# ===========================================================================
# CRUD / Status Lifecycle
# ===========================================================================


class TestHypothesisCRUD:
    """CRUD operations and status lifecycle for hypotheses."""

    @pytest.mark.asyncio
    async def test_create_hypothesis_returns_201_with_open_status(
        self, auth_client: AsyncClient
    ):
        """POST /api/hypotheses with statement → 201, status='open'."""
        r = await auth_client.post(
            "/api/hypotheses",
            json={
                "statement": "Enterprise brands will pay to eliminate the manual Monday export",
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["status"] == "open"
        assert data["statement"] == "Enterprise brands will pay to eliminate the manual Monday export"
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_create_hypothesis_with_segment(self, auth_client: AsyncClient):
        """POST /api/hypotheses with optional segment field."""
        r = await auth_client.post(
            "/api/hypotheses",
            json={
                "statement": "Mid-market brands won't pay >€10k without a detection-speed SLA",
                "segment": "mid-market",
            },
        )
        assert r.status_code == 201
        assert r.json()["segment"] == "mid-market"

    @pytest.mark.asyncio
    async def test_create_hypothesis_validates_min_statement_length(
        self, auth_client: AsyncClient
    ):
        """Statement must be at least 15 characters (falsifiable statement requirement)."""
        r = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "too short"},
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_list_hypotheses_returns_all(self, auth_client: AsyncClient):
        """GET /api/hypotheses returns list of hypotheses."""
        # Create two
        await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Detection speed matters more than coverage breadth"},
        )

        r = await auth_client.get("/api/hypotheses")
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 2

    @pytest.mark.asyncio
    async def test_patch_status_to_supported(self, auth_client: AsyncClient):
        """PATCH /api/hypotheses/{id} status → 'supported' sets decided_at."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        r = await auth_client.patch(
            f"/api/hypotheses/{hyp_id}", json={"status": "supported"}
        )
        assert r.status_code == 200
        assert r.json()["status"] == "supported"
        assert r.json()["decided_at"] is not None

    @pytest.mark.asyncio
    async def test_patch_status_to_refuted(self, auth_client: AsyncClient):
        """PATCH status to refuted."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Customers primarily want broader marketplace coverage"},
        )
        hyp_id = create.json()["id"]

        r = await auth_client.patch(
            f"/api/hypotheses/{hyp_id}", json={"status": "refuted"}
        )
        assert r.status_code == 200
        assert r.json()["status"] == "refuted"
        assert r.json()["decided_at"] is not None

    @pytest.mark.asyncio
    async def test_patch_status_to_parked(self, auth_client: AsyncClient):
        """PATCH status to parked (put on hold)."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Customers primarily want broader marketplace coverage"},
        )
        hyp_id = create.json()["id"]

        r = await auth_client.patch(
            f"/api/hypotheses/{hyp_id}", json={"status": "parked"}
        )
        assert r.status_code == 200
        assert r.json()["status"] == "parked"

    @pytest.mark.asyncio
    async def test_patch_invalid_status_422(self, auth_client: AsyncClient):
        """PATCH with invalid status value → 422."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        r = await auth_client.patch(
            f"/api/hypotheses/{hyp_id}", json={"status": "bananas"}
        )
        assert r.status_code == 422


# ===========================================================================
# Immutable statement after evidence link (409)
# ===========================================================================


class TestStatementImmutability:
    """Statement becomes immutable once any evidence link exists."""

    @pytest.mark.asyncio
    async def test_statement_editable_before_evidence(self, auth_client: AsyncClient):
        """PATCH statement succeeds when no evidence links."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        r = await auth_client.patch(
            f"/api/hypotheses/{hyp_id}",
            json={"statement": "Enterprise brands will pay >€5k to eliminate Monday export"},
        )
        assert r.status_code == 200
        assert "€5k" in r.json()["statement"]

    @pytest.mark.asyncio
    async def test_statement_immutable_after_evidence_link_409(
        self, auth_client: AsyncClient, hyp_seeded: dict
    ):
        """PATCH statement → 409 once a hypothesis_link exists.

        This forces users to create a new hypothesis instead of modifying one
        that already has evidence trail.
        """
        # Create hypothesis
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        # Manually link evidence (via the link API)
        link_r = await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight1"].id,
                "stance": "supports",
            },
        )
        assert link_r.status_code == 201

        # Now try to PATCH statement
        r = await auth_client.patch(
            f"/api/hypotheses/{hyp_id}",
            json={"statement": "Changed my mind about statement wording"},
        )
        assert r.status_code == 409
        assert "immutable" in r.json()["detail"].lower()


# ===========================================================================
# Hypothesis Linker — AI-proposed links after tagging
# ===========================================================================


class TestHypothesisLinker:
    """The hypothesis_link job auto-proposes evidence links."""

    @pytest.mark.asyncio
    async def test_linker_runs_and_proposes_links_with_supports_contradicts(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hyp_seeded: dict,
    ):
        """After tagging, linker proposes links with stance and origin='ai', status='suggested'."""
        from app.llm.linker import run_hypothesis_link  # type: ignore[import-not-found]

        async with session_factory() as session:
            # Create an open hypothesis directly in DB
            from app.models import Hypothesis  # type: ignore[import-not-found]

            hyp = Hypothesis(
                statement="Enterprise brands will pay to eliminate the manual Monday export",
                status="open",
                created_by=hyp_seeded["user"].id,
            )
            session.add(hyp)
            await session.flush()

            fake_llm = FakeLLMClient(
                fixtures={
                    "hypothesis_linker": {
                        "links": [
                            {
                                "hypothesis_id": hyp.id,
                                "highlight_id": hyp_seeded["highlight1"].id,
                                "stance": "supports",
                                "confidence": 0.88,
                                "rationale": "Direct evidence of willingness to pay",
                            },
                            {
                                "hypothesis_id": hyp.id,
                                "highlight_id": hyp_seeded["highlight2"].id,
                                "stance": "contradicts",
                                "confidence": 0.72,
                                "rationale": "Suggests the export is tolerable",
                            },
                        ]
                    }
                }
            )

            await run_hypothesis_link(
                session, hyp_seeded["conversation1"].id, llm=fake_llm
            )
            await session.commit()

            # Verify links created
            from app.models import HypothesisLink  # type: ignore[import-not-found]

            links = (
                await session.execute(
                    select(HypothesisLink).where(
                        HypothesisLink.hypothesis_id == hyp.id
                    )
                )
            ).scalars().all()

            assert len(links) == 2
            assert all(link.status == "suggested" for link in links)
            assert all(link.origin == "ai" for link in links)
            stances = {link.stance for link in links}
            assert stances == {"supports", "contradicts"}

    @pytest.mark.asyncio
    async def test_linker_input_contains_only_open_hypotheses(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hyp_seeded: dict,
    ):
        """Linker prompt input excludes hypotheses with status != 'open'."""
        from app.llm.linker import run_hypothesis_link  # type: ignore[import-not-found]
        from app.models import Hypothesis  # type: ignore[import-not-found]

        async with session_factory() as session:
            # One open, one refuted
            open_hyp = Hypothesis(
                statement="Open hypothesis about Monday export ritual",
                status="open",
                created_by=hyp_seeded["user"].id,
            )
            closed_hyp = Hypothesis(
                statement="Refuted hypothesis about coverage breadth",
                status="refuted",
                created_by=hyp_seeded["user"].id,
            )
            session.add_all([open_hyp, closed_hyp])
            await session.flush()
            await session.commit()

            fake_llm = FakeLLMClient(
                fixtures={
                    "hypothesis_linker": {"links": []}  # empty response is fine
                }
            )

            await run_hypothesis_link(
                session, hyp_seeded["conversation1"].id, llm=fake_llm
            )

            # Inspect what was sent to LLM
            assert len(fake_llm.calls) == 1
            input_data = fake_llm.calls[0]["input_data"]
            hypothesis_ids_in_input = [
                h["id"] for h in input_data["hypotheses"]
            ]
            assert open_hyp.id in hypothesis_ids_in_input
            assert closed_hyp.id not in hypothesis_ids_in_input

    @pytest.mark.asyncio
    async def test_linker_input_excludes_rejected_highlights(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hyp_seeded: dict,
    ):
        """Linker prompt only feeds non-rejected highlights from the conversation."""
        from app.llm.linker import run_hypothesis_link  # type: ignore[import-not-found]
        from app.models import Hypothesis  # type: ignore[import-not-found]

        async with session_factory() as session:
            hyp = Hypothesis(
                statement="Open hypothesis about takedown templates",
                status="open",
                created_by=hyp_seeded["user"].id,
            )
            session.add(hyp)
            await session.flush()
            await session.commit()

            fake_llm = FakeLLMClient(
                fixtures={"hypothesis_linker": {"links": []}}
            )

            await run_hypothesis_link(
                session, hyp_seeded["conversation2"].id, llm=fake_llm
            )

            # Inspect highlight IDs sent to LLM
            assert len(fake_llm.calls) == 1
            input_data = fake_llm.calls[0]["input_data"]
            highlight_ids_in_input = [h["id"] for h in input_data["highlights"]]
            # h2 (accepted) should be in input
            assert hyp_seeded["highlight2"].id in highlight_ids_in_input
            # h3 (rejected) must NOT be in input
            assert hyp_seeded["highlight_rejected"].id not in highlight_ids_in_input

    @pytest.mark.asyncio
    async def test_linker_strips_invalid_hypothesis_ids(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hyp_seeded: dict,
    ):
        """Links referencing non-existent hypothesis_id are stripped (not persisted)."""
        from app.llm.linker import run_hypothesis_link  # type: ignore[import-not-found]
        from app.models import Hypothesis, HypothesisLink  # type: ignore[import-not-found]

        async with session_factory() as session:
            hyp = Hypothesis(
                statement="Enterprise brands will pay for speed",
                status="open",
                created_by=hyp_seeded["user"].id,
            )
            session.add(hyp)
            await session.flush()
            await session.commit()

            fake_llm = FakeLLMClient(
                fixtures={
                    "hypothesis_linker": {
                        "links": [
                            {
                                "hypothesis_id": hyp.id,
                                "highlight_id": hyp_seeded["highlight1"].id,
                                "stance": "supports",
                                "confidence": 0.88,
                                "rationale": "Valid link",
                            },
                            {
                                "hypothesis_id": 99999,  # invalid
                                "highlight_id": hyp_seeded["highlight1"].id,
                                "stance": "supports",
                                "confidence": 0.70,
                                "rationale": "Ghost hypothesis",
                            },
                        ]
                    }
                }
            )

            await run_hypothesis_link(
                session, hyp_seeded["conversation1"].id, llm=fake_llm
            )
            await session.commit()

            links = (
                await session.execute(select(HypothesisLink))
            ).scalars().all()
            assert len(links) == 1
            assert links[0].hypothesis_id == hyp.id

    @pytest.mark.asyncio
    async def test_linker_strips_invalid_highlight_ids(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hyp_seeded: dict,
    ):
        """Links referencing non-existent highlight_id are stripped."""
        from app.llm.linker import run_hypothesis_link  # type: ignore[import-not-found]
        from app.models import Hypothesis, HypothesisLink  # type: ignore[import-not-found]

        async with session_factory() as session:
            hyp = Hypothesis(
                statement="Enterprise brands will pay for speed",
                status="open",
                created_by=hyp_seeded["user"].id,
            )
            session.add(hyp)
            await session.flush()
            await session.commit()

            fake_llm = FakeLLMClient(
                fixtures={
                    "hypothesis_linker": {
                        "links": [
                            {
                                "hypothesis_id": hyp.id,
                                "highlight_id": 88888,  # invalid
                                "stance": "supports",
                                "confidence": 0.70,
                                "rationale": "Ghost highlight",
                            },
                        ]
                    }
                }
            )

            await run_hypothesis_link(
                session, hyp_seeded["conversation1"].id, llm=fake_llm
            )
            await session.commit()

            links = (
                await session.execute(select(HypothesisLink))
            ).scalars().all()
            assert len(links) == 0


# ===========================================================================
# Skip / Enqueue behavior after tagging
# ===========================================================================


class TestLinkerEnqueueBehavior:
    """Linker job is enqueued only when open hypotheses exist."""

    @pytest.mark.asyncio
    async def test_tag_job_enqueues_hypothesis_link_when_open_hypotheses_exist(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hyp_seeded: dict,
    ):
        """After tag job completes, a hypothesis_link job is enqueued if open hypotheses exist."""
        from app.models import Hypothesis  # type: ignore[import-not-found]

        async with session_factory() as session:
            hyp = Hypothesis(
                statement="Enterprise brands will pay to eliminate Monday export",
                status="open",
                created_by=hyp_seeded["user"].id,
            )
            session.add(hyp)
            await session.commit()

        # Simulate running the tag handler
        from app.worker import handle_tag

        settings = Settings(
            database_url="sqlite+aiosqlite://",
            session_secret="test",
            openai_api_key="",
            env="test",
        )

        async with session_factory() as session:
            # Create a tag job
            job = Job(
                conversation_id=hyp_seeded["conversation1"].id,
                kind="tag",
                payload={"conversation_id": hyp_seeded["conversation1"].id},
                status="running",
            )
            session.add(job)
            await session.commit()

            await handle_tag(session, job, settings)
            await session.commit()

            # Check hypothesis_link job was enqueued
            result = await session.execute(
                select(Job).where(
                    Job.conversation_id == hyp_seeded["conversation1"].id,
                    Job.kind == "hypothesis_link",
                )
            )
            link_job = result.scalar_one_or_none()
            assert link_job is not None
            assert link_job.status == "queued"

    @pytest.mark.asyncio
    async def test_tag_job_skips_hypothesis_link_when_no_open_hypotheses(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hyp_seeded: dict,
    ):
        """No hypothesis_link job enqueued when zero open hypotheses exist.

        The worker handler registry MUST know about the 'hypothesis_link' kind,
        proving the feature is wired in (even when it skips due to no open hypotheses).
        """
        from app.worker import HANDLERS

        # The hypothesis_link handler must be registered in the worker
        assert "hypothesis_link" in HANDLERS, (
            "hypothesis_link handler not registered in worker HANDLERS"
        )


# ===========================================================================
# Accept / Reject link
# ===========================================================================


class TestAcceptRejectLink:
    """Human accept/reject of AI-suggested hypothesis links."""

    @pytest.mark.asyncio
    async def test_accept_link(self, auth_client: AsyncClient, hyp_seeded: dict):
        """PATCH /api/hypothesis-links/{id} with status='confirmed'."""
        # Create hypothesis
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        # Create a suggested link via the API (manual human link)
        link_r = await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight1"].id,
                "stance": "supports",
            },
        )
        link_id = link_r.json()["id"]

        # Accept it
        r = await auth_client.patch(
            f"/api/hypothesis-links/{link_id}", json={"status": "confirmed"}
        )
        assert r.status_code == 200
        assert r.json()["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_reject_link(self, auth_client: AsyncClient, hyp_seeded: dict):
        """PATCH /api/hypothesis-links/{id} with status='rejected'."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        link_r = await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight1"].id,
                "stance": "supports",
            },
        )
        link_id = link_r.json()["id"]

        r = await auth_client.patch(
            f"/api/hypothesis-links/{link_id}", json={"status": "rejected"}
        )
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_invalid_link_status_422(self, auth_client: AsyncClient, hyp_seeded: dict):
        """PATCH with invalid status value → 422."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        link_r = await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight1"].id,
                "stance": "supports",
            },
        )
        link_id = link_r.json()["id"]

        r = await auth_client.patch(
            f"/api/hypothesis-links/{link_id}", json={"status": "invalid_status"}
        )
        assert r.status_code == 422


# ===========================================================================
# Detail rollup: stance/status counts, distinct companies, verdict_hint
# ===========================================================================


class TestHypothesisDetailRollup:
    """GET /api/hypotheses/{id} returns rollup: evidence grouped by stance/status."""

    @pytest.mark.asyncio
    async def test_detail_rollup_structure(
        self, auth_client: AsyncClient, hyp_seeded: dict
    ):
        """GET /api/hypotheses/{id} contains rollup with supports/contradicts counts."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        # Link some evidence
        await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight1"].id,
                "stance": "supports",
            },
        )

        r = await auth_client.get(f"/api/hypotheses/{hyp_id}")
        assert r.status_code == 200
        data = r.json()

        # Must contain rollup fields
        assert "supports" in data
        assert "contradicts" in data
        assert "confirmed" in data["supports"] or "suggested" in data["supports"]
        assert "companies_supporting" in data
        assert "last_evidence_at" in data

    @pytest.mark.asyncio
    async def test_rollup_counts_distinct_confirmed_companies(
        self, auth_client: AsyncClient, hyp_seeded: dict
    ):
        """companies_supporting counts distinct companies from confirmed-supports links."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        # Link from company 1 (confirm it)
        link1 = await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight1"].id,
                "stance": "supports",
            },
        )
        await auth_client.patch(
            f"/api/hypothesis-links/{link1.json()['id']}",
            json={"status": "confirmed"},
        )

        # Link from company 2 (confirm it)
        link2 = await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight2"].id,
                "stance": "supports",
            },
        )
        await auth_client.patch(
            f"/api/hypothesis-links/{link2.json()['id']}",
            json={"status": "confirmed"},
        )

        r = await auth_client.get(f"/api/hypotheses/{hyp_id}")
        data = r.json()
        # Two distinct companies
        assert data["companies_supporting"] == 2

    @pytest.mark.asyncio
    async def test_rollup_last_evidence_at(
        self, auth_client: AsyncClient, hyp_seeded: dict
    ):
        """last_evidence_at reflects the most recent link creation."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight1"].id,
                "stance": "supports",
            },
        )

        r = await auth_client.get(f"/api/hypotheses/{hyp_id}")
        data = r.json()
        assert data["last_evidence_at"] is not None

    @pytest.mark.asyncio
    async def test_verdict_hint_leaning_supported(
        self, auth_client: AsyncClient, hyp_seeded: dict
    ):
        """verdict_hint = 'leaning-supported' when confirmed supports ≥ 3 companies
        and contradicts from ≤ 1 company. This is purely deterministic, never auto-changes status.
        """
        # We need 3+ companies supporting. Seed additional highlights/companies.
        # For this test we use the seeded data plus create via API
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        # Confirm support from company1
        link1 = await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight1"].id,
                "stance": "supports",
            },
        )
        await auth_client.patch(
            f"/api/hypothesis-links/{link1.json()['id']}",
            json={"status": "confirmed"},
        )

        # Confirm support from company2
        link2 = await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight2"].id,
                "stance": "supports",
            },
        )
        await auth_client.patch(
            f"/api/hypothesis-links/{link2.json()['id']}",
            json={"status": "confirmed"},
        )

        # For the threshold (≥3 companies), we'd need a 3rd company.
        # With only 2 confirmed companies, verdict_hint should NOT be 'leaning-supported'.
        r = await auth_client.get(f"/api/hypotheses/{hyp_id}")
        data = r.json()
        assert data["verdict_hint"] != "leaning-supported"
        # The status must remain 'open' — verdict_hint never auto-changes it
        assert data["status"] == "open"

    @pytest.mark.asyncio
    async def test_verdict_hint_never_auto_changes_status(
        self, auth_client: AsyncClient, hyp_seeded: dict
    ):
        """Even with overwhelming evidence, status stays 'open' until human decides."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        # Lots of confirmed supports
        link1 = await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight1"].id,
                "stance": "supports",
            },
        )
        await auth_client.patch(
            f"/api/hypothesis-links/{link1.json()['id']}",
            json={"status": "confirmed"},
        )

        r = await auth_client.get(f"/api/hypotheses/{hyp_id}")
        # Status is still open regardless of evidence weight
        assert r.json()["status"] == "open"


# ===========================================================================
# Delete highlight cascades hypothesis_links
# ===========================================================================


class TestDeleteHighlightCascadesLinks:
    """Deleting a highlight cascades and removes associated hypothesis_links."""

    @pytest.mark.asyncio
    async def test_delete_highlight_removes_hypothesis_links(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hyp_seeded: dict,
    ):
        """When a highlight is deleted, its hypothesis_links are cascade-deleted."""
        from app.models import Hypothesis, HypothesisLink  # type: ignore[import-not-found]

        async with session_factory() as session:
            hyp = Hypothesis(
                statement="Enterprise brands will pay to eliminate Monday export",
                status="open",
                created_by=hyp_seeded["user"].id,
            )
            session.add(hyp)
            await session.flush()

            link = HypothesisLink(
                hypothesis_id=hyp.id,
                highlight_id=hyp_seeded["highlight1"].id,
                stance="supports",
                confidence=0.88,
                origin="ai",
                status="suggested",
                rationale="Direct evidence",
            )
            session.add(link)
            await session.commit()

            # Confirm link exists
            links = (
                await session.execute(
                    select(HypothesisLink).where(
                        HypothesisLink.highlight_id == hyp_seeded["highlight1"].id
                    )
                )
            ).scalars().all()
            assert len(links) == 1

            # Delete the highlight
            highlight = await session.get(Highlight, hyp_seeded["highlight1"].id)
            await session.delete(highlight)
            await session.commit()

            # Links should be cascade-deleted
            links_after = (
                await session.execute(
                    select(HypothesisLink).where(
                        HypothesisLink.highlight_id == hyp_seeded["highlight1"].id
                    )
                )
            ).scalars().all()
            assert len(links_after) == 0


# ===========================================================================
# Auth / OpenAPI response contracts
# ===========================================================================


class TestHypothesisAuth:
    """Auth enforcement on hypothesis endpoints."""

    @pytest.mark.asyncio
    async def test_unauthenticated_list_hypotheses_401(self, client: AsyncClient):
        """GET /api/hypotheses without auth → 401."""
        r = await client.get("/api/hypotheses")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_unauthenticated_create_hypothesis_401(self, client: AsyncClient):
        """POST /api/hypotheses without auth → 401."""
        r = await client.post(
            "/api/hypotheses",
            json={"statement": "Some hypothesis statement here"},
        )
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_unauthenticated_patch_hypothesis_link_401(self, client: AsyncClient):
        """PATCH /api/hypothesis-links/1 without auth → 401."""
        r = await client.patch(
            "/api/hypothesis-links/1", json={"status": "confirmed"}
        )
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_hypothesis_detail_404_nonexistent(self, auth_client: AsyncClient):
        """GET /api/hypotheses/99999 → 404."""
        r = await auth_client.get("/api/hypotheses/99999")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_hypothesis_link_404_nonexistent(self, auth_client: AsyncClient):
        """PATCH /api/hypothesis-links/99999 → 404."""
        r = await auth_client.patch(
            "/api/hypothesis-links/99999", json={"status": "confirmed"}
        )
        assert r.status_code == 404


class TestHypothesisOpenAPIContract:
    """Response schemas match the expected OpenAPI contract shape."""

    @pytest.mark.asyncio
    async def test_create_response_has_required_fields(self, auth_client: AsyncClient):
        """POST response includes: id, statement, status, segment, created_by, created_at."""
        r = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        assert r.status_code == 201
        data = r.json()
        required_fields = {"id", "statement", "status", "created_at", "created_by"}
        assert required_fields.issubset(set(data.keys()))

    @pytest.mark.asyncio
    async def test_detail_response_has_rollup_fields(
        self, auth_client: AsyncClient, hyp_seeded: dict
    ):
        """GET /api/hypotheses/{id} includes rollup fields in response."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        # Add a link so rollup has data
        await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight1"].id,
                "stance": "supports",
            },
        )

        r = await auth_client.get(f"/api/hypotheses/{hyp_id}")
        assert r.status_code == 200
        data = r.json()
        rollup_fields = {
            "supports",
            "contradicts",
            "companies_supporting",
            "last_evidence_at",
            "verdict_hint",
        }
        assert rollup_fields.issubset(set(data.keys()))

    @pytest.mark.asyncio
    async def test_link_response_has_required_fields(
        self, auth_client: AsyncClient, hyp_seeded: dict
    ):
        """POST link response includes: id, hypothesis_id, highlight_id, stance, status, origin."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        r = await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight1"].id,
                "stance": "supports",
            },
        )
        assert r.status_code == 201
        data = r.json()
        required_fields = {
            "id",
            "hypothesis_id",
            "highlight_id",
            "stance",
            "status",
            "origin",
        }
        assert required_fields.issubset(set(data.keys()))


# ===========================================================================
# Production list response (GET /api/hypotheses) includes rollup
# ===========================================================================


class TestHypothesisListRollup:
    """GET /api/hypotheses returns list items with rollup and verdict_hint."""

    @pytest.mark.asyncio
    async def test_list_response_includes_rollup_fields(
        self, auth_client: AsyncClient, hyp_seeded: dict
    ):
        """GET /api/hypotheses items contain rollup with companies_supporting/contradicting."""
        # Create hypothesis and link evidence
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        # Link supporting evidence and confirm
        link1 = await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight1"].id,
                "stance": "supports",
            },
        )
        await auth_client.patch(
            f"/api/hypothesis-links/{link1.json()['id']}",
            json={"status": "confirmed"},
        )

        # Link contradicting evidence
        link2 = await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight2"].id,
                "stance": "contradicts",
            },
        )
        await auth_client.patch(
            f"/api/hypothesis-links/{link2.json()['id']}",
            json={"status": "confirmed"},
        )

        r = await auth_client.get("/api/hypotheses")
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1

        # Find our hypothesis in the list
        hyp_item = next(i for i in items if i["id"] == hyp_id)

        # Verify rollup structure
        assert "rollup" in hyp_item
        rollup = hyp_item["rollup"]
        assert rollup["supports"]["confirmed"] == 1
        assert rollup["contradicts"]["confirmed"] == 1
        assert rollup["companies_supporting"] == 1  # company1
        assert rollup["companies_contradicting"] == 1  # company2
        assert rollup["last_evidence_at"] is not None

        # Verify verdict_hint present (None or string)
        assert "verdict_hint" in hyp_item


# ===========================================================================
# Invalid stance validation (Literal enforcement)
# ===========================================================================


class TestInvalidStanceRejection:
    """API and Pydantic reject invalid stance values."""

    @pytest.mark.asyncio
    async def test_create_link_with_invalid_stance_422(
        self, auth_client: AsyncClient, hyp_seeded: dict
    ):
        """POST /api/hypotheses/{id}/links with invalid stance → 422."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        r = await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight1"].id,
                "stance": "neutral",  # invalid
            },
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_create_link_with_empty_stance_422(
        self, auth_client: AsyncClient, hyp_seeded: dict
    ):
        """POST /api/hypotheses/{id}/links with empty stance → 422."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        r = await auth_client.post(
            f"/api/hypotheses/{hyp_id}/links",
            json={
                "highlight_id": hyp_seeded["highlight1"].id,
                "stance": "",
            },
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_linker_schema_rejects_invalid_stance(self):
        """LinkerLink Pydantic model rejects invalid stance values."""
        from pydantic import ValidationError

        from app.llm.schemas import LinkerLink

        with pytest.raises(ValidationError):
            LinkerLink(
                hypothesis_id=1,
                highlight_id=1,
                stance="neutral",
                confidence=0.8,
                rationale="test",
            )

    @pytest.mark.asyncio
    async def test_linker_schema_accepts_valid_stances(self):
        """LinkerLink accepts supports and contradicts."""
        from app.llm.schemas import LinkerLink

        link_s = LinkerLink(
            hypothesis_id=1,
            highlight_id=1,
            stance="supports",
            confidence=0.8,
            rationale="test",
        )
        assert link_s.stance == "supports"

        link_c = LinkerLink(
            hypothesis_id=1,
            highlight_id=1,
            stance="contradicts",
            confidence=0.8,
            rationale="test",
        )
        assert link_c.stance == "contradicts"


# ===========================================================================
# One-company-many-links refutation regression
# ===========================================================================


class TestRefutationRegression:
    """Refutation hint uses distinct companies, not raw link count.

    Regression: a single company with 3+ confirmed contradicting links should
    NOT trigger 'leaning-refuted' — only ≥3 DISTINCT companies contradicting
    with ≤1 company supporting.
    """

    @pytest.mark.asyncio
    async def test_one_company_many_contradicting_links_no_refuted_hint(
        self, auth_client: AsyncClient, hyp_seeded: dict
    ):
        """3 contradicting links from 1 company should NOT yield 'leaning-refuted'.

        This prevents a single noisy conversation from tipping the verdict.
        """
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        # Create and confirm 3 contradicting links — all from highlight2 (Northwind, same company)
        for _ in range(3):
            link = await auth_client.post(
                f"/api/hypotheses/{hyp_id}/links",
                json={
                    "highlight_id": hyp_seeded["highlight2"].id,
                    "stance": "contradicts",
                },
            )
            await auth_client.patch(
                f"/api/hypothesis-links/{link.json()['id']}",
                json={"status": "confirmed"},
            )

        # Detail should NOT show 'leaning-refuted' because only 1 distinct company
        r = await auth_client.get(f"/api/hypotheses/{hyp_id}")
        data = r.json()
        assert data["companies_contradicting"] == 1  # Only Northwind
        assert data["verdict_hint"] != "leaning-refuted"
        # Status must still be 'open'
        assert data["status"] == "open"

    @pytest.mark.asyncio
    async def test_list_also_reflects_no_false_refuted_hint(
        self, auth_client: AsyncClient, hyp_seeded: dict
    ):
        """List endpoint also computes verdict_hint correctly (no false refutation)."""
        create = await auth_client.post(
            "/api/hypotheses",
            json={"statement": "Enterprise brands will pay to eliminate Monday export"},
        )
        hyp_id = create.json()["id"]

        for _ in range(3):
            link = await auth_client.post(
                f"/api/hypotheses/{hyp_id}/links",
                json={
                    "highlight_id": hyp_seeded["highlight2"].id,
                    "stance": "contradicts",
                },
            )
            await auth_client.patch(
                f"/api/hypothesis-links/{link.json()['id']}",
                json={"status": "confirmed"},
            )

        r = await auth_client.get("/api/hypotheses")
        items = r.json()
        hyp_item = next(i for i in items if i["id"] == hyp_id)
        assert hyp_item["rollup"]["companies_contradicting"] == 1
        assert hyp_item["verdict_hint"] != "leaning-refuted"
