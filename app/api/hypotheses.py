"""Hypothesis CRUD, evidence links, and detail rollup endpoints."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    HypothesisCreate,
    HypothesisDetailResponse,
    HypothesisLinkCreate,
    HypothesisLinkResponse,
    HypothesisListItemResponse,
    HypothesisResponse,
    HypothesisRollup,
    HypothesisUpdate,
)
from app.auth import get_current_user
from app.models import (
    Company,
    Contact,
    Conversation,
    ConversationContact,
    Highlight,
    Hypothesis,
    HypothesisLink,
    User,
    utcnow,
)

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_HYPOTHESIS_STATUSES = {"open", "supported", "refuted", "parked"}
VALID_LINK_STATUSES = {"confirmed", "rejected"}
VALID_STANCES: set[str] = {"supports", "contradicts"}


# ---------------------------------------------------------------------------
# Shared rollup logic — used by both list and detail
# ---------------------------------------------------------------------------


async def _build_rollup(db: AsyncSession, hypothesis_id: int) -> tuple[
    dict[str, int], dict[str, int], int, int, datetime | None
]:
    """Compute rollup for a hypothesis: stance counts, distinct companies, last_evidence_at.

    Returns:
        Tuple of (supports_counts, contradicts_counts, companies_supporting,
                  companies_contradicting, last_evidence_at)
    """
    links_result = await db.execute(
        select(HypothesisLink).where(HypothesisLink.hypothesis_id == hypothesis_id)
    )
    links = links_result.scalars().all()

    supports: dict[str, int] = {"suggested": 0, "confirmed": 0, "rejected": 0}
    contradicts: dict[str, int] = {"suggested": 0, "confirmed": 0, "rejected": 0}
    last_evidence_at: datetime | None = None

    for link in links:
        bucket = supports if link.stance == "supports" else contradicts
        bucket[link.status] = bucket.get(link.status, 0) + 1
        if last_evidence_at is None or link.created_at > last_evidence_at:
            last_evidence_at = link.created_at

    # Count distinct confirmed-supporting companies
    companies_supporting = 0
    companies_contradicting = 0
    if links:
        company_sup_result = await db.execute(
            select(func.count(func.distinct(Conversation.company_id)))
            .select_from(HypothesisLink)
            .join(Highlight, HypothesisLink.highlight_id == Highlight.id)
            .join(Conversation, Highlight.conversation_id == Conversation.id)
            .where(
                HypothesisLink.hypothesis_id == hypothesis_id,
                HypothesisLink.stance == "supports",
                HypothesisLink.status == "confirmed",
                Conversation.company_id.isnot(None),
            )
        )
        companies_supporting = company_sup_result.scalar() or 0

        company_con_result = await db.execute(
            select(func.count(func.distinct(Conversation.company_id)))
            .select_from(HypothesisLink)
            .join(Highlight, HypothesisLink.highlight_id == Highlight.id)
            .join(Conversation, Highlight.conversation_id == Conversation.id)
            .where(
                HypothesisLink.hypothesis_id == hypothesis_id,
                HypothesisLink.stance == "contradicts",
                HypothesisLink.status == "confirmed",
                Conversation.company_id.isnot(None),
            )
        )
        companies_contradicting = company_con_result.scalar() or 0

    return supports, contradicts, companies_supporting, companies_contradicting, last_evidence_at


def _compute_verdict_hint(
    supports: dict[str, int],
    contradicts: dict[str, int],
    companies_supporting: int,
    companies_contradicting: int,
) -> str | None:
    """Compute a deterministic verdict hint based on evidence counts.

    Rules (symmetric):
    - 'leaning-supported': confirmed supports from ≥3 distinct companies
      AND confirmed contradicts from ≤1 distinct company.
    - 'leaning-refuted': confirmed contradicts from ≥3 distinct companies
      AND confirmed supports from ≤1 distinct company.
    - 'mixed': both confirmed supports and contradicts present
    - None: insufficient evidence

    This NEVER auto-changes hypothesis status.
    """
    confirmed_supports = supports.get("confirmed", 0)
    confirmed_contradicts = contradicts.get("confirmed", 0)

    if companies_supporting >= 3 and companies_contradicting <= 1:
        return "leaning-supported"
    if companies_contradicting >= 3 and companies_supporting <= 1:
        return "leaning-refuted"
    if confirmed_supports > 0 and confirmed_contradicts > 0:
        return "mixed"
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[HypothesisListItemResponse])
async def list_hypotheses(
    request: Request,
    user: User = Depends(get_current_user),
) -> list[dict]:
    """List all hypotheses with rollup data for the board."""
    session_factory = request.app.state.session_factory
    async with session_factory() as db:
        result = await db.execute(
            select(Hypothesis).order_by(Hypothesis.created_at.desc())
        )
        hypotheses = result.scalars().all()

        items = []
        for hyp in hypotheses:
            supports, contradicts, co_sup, co_con, last_ev = await _build_rollup(
                db, hyp.id
            )
            verdict_hint = _compute_verdict_hint(supports, contradicts, co_sup, co_con)

            # Freshness (T41)
            from app.services.staleness import get_hypothesis_freshness

            freshness_data = await get_hypothesis_freshness(db, hyp.id)

            items.append({
                "id": hyp.id,
                "statement": hyp.statement,
                "segment": hyp.segment,
                "status": hyp.status,
                "created_by": hyp.created_by,
                "decided_at": hyp.decided_at,
                "created_at": hyp.created_at,
                "rollup": HypothesisRollup(
                    supports={
                        "confirmed": supports.get("confirmed", 0),
                        "suggested": supports.get("suggested", 0),
                    },
                    contradicts={
                        "confirmed": contradicts.get("confirmed", 0),
                        "suggested": contradicts.get("suggested", 0),
                    },
                    companies_supporting=co_sup,
                    companies_contradicting=co_con,
                    last_evidence_at=last_ev,
                    freshness=freshness_data["freshness"],
                    newest_evidence_at=freshness_data.get("newest_evidence_at"),
                ),
                "verdict_hint": verdict_hint,
            })

        return items


@router.post("", response_model=HypothesisResponse, status_code=201)
async def create_hypothesis(
    body: HypothesisCreate,
    request: Request,
    user: User = Depends(get_current_user),
) -> Hypothesis:
    """Create a new hypothesis with status='open'."""
    session_factory = request.app.state.session_factory
    async with session_factory() as db:
        hyp = Hypothesis(
            statement=body.statement,
            segment=body.segment,
            status="open",
            created_by=user.id,
        )
        db.add(hyp)
        await db.commit()
        await db.refresh(hyp)
        return hyp


@router.get("/{hypothesis_id}", response_model=HypothesisDetailResponse)
async def get_hypothesis_detail(
    hypothesis_id: int,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    """Get hypothesis detail with rollup: supports/contradicts by status, companies, verdict_hint."""
    session_factory = request.app.state.session_factory
    async with session_factory() as db:
        hyp = await db.get(Hypothesis, hypothesis_id)
        if hyp is None:
            raise HTTPException(status_code=404, detail="Hypothesis not found")

        supports, contradicts, co_sup, co_con, last_ev = await _build_rollup(
            db, hypothesis_id
        )
        verdict_hint = _compute_verdict_hint(supports, contradicts, co_sup, co_con)

        # Load each link with the highlight and source context required by the UI.
        context_result = await db.execute(
            select(HypothesisLink, Highlight, Conversation, Company)
            .join(Highlight, HypothesisLink.highlight_id == Highlight.id)
            .join(Conversation, Highlight.conversation_id == Conversation.id)
            .outerjoin(Company, Conversation.company_id == Company.id)
            .where(HypothesisLink.hypothesis_id == hypothesis_id)
            .order_by(HypothesisLink.created_at, HypothesisLink.id)
        )
        context_rows = context_result.all()
        links = [row[0] for row in context_rows]

        conversation_ids = {conversation.id for _, _, conversation, _ in context_rows}
        contact_names: dict[int, str] = {}
        if conversation_ids:
            contacts_result = await db.execute(
                select(ConversationContact.conversation_id, Contact.name)
                .join(Contact, ConversationContact.contact_id == Contact.id)
                .where(ConversationContact.conversation_id.in_(conversation_ids))
                .order_by(ConversationContact.conversation_id, Contact.id)
            )
            for conversation_id, contact_name in contacts_result.all():
                contact_names.setdefault(conversation_id, contact_name)

        evidence: dict[str, list[dict]] = {
            "supports": [],
            "contradicts": [],
        }
        for link, highlight, conversation, company in context_rows:
            # Rejected suggestions are retained in the legacy links field for
            # auditability, but are not renderable evidence on the board.
            if link.status == "rejected":
                continue
            evidence[link.stance].append({
                "link_id": link.id,
                "highlight_id": highlight.id,
                "quote": highlight.quote,
                "conversation_id": conversation.id,
                "conversation_title": conversation.title,
                "utterance_id": highlight.utterance_id,
                "company_name": company.name if company else None,
                "contact_name": contact_names.get(conversation.id),
                "confidence": link.confidence,
                "origin": link.origin,
                "status": link.status,
                "rationale": link.rationale,
            })

        link_responses = [
            HypothesisLinkResponse(
                id=link.id,
                hypothesis_id=link.hypothesis_id,
                highlight_id=link.highlight_id,
                stance=link.stance,
                confidence=link.confidence,
                rationale=link.rationale,
                origin=link.origin,
                status=link.status,
                created_at=link.created_at,
            )
            for link in links
        ]

        from app.services.staleness import get_hypothesis_freshness

        freshness_data = await get_hypothesis_freshness(db, hypothesis_id)
        rollup = HypothesisRollup(
            supports={
                "confirmed": supports.get("confirmed", 0),
                "suggested": supports.get("suggested", 0),
            },
            contradicts={
                "confirmed": contradicts.get("confirmed", 0),
                "suggested": contradicts.get("suggested", 0),
            },
            companies_supporting=co_sup,
            companies_contradicting=co_con,
            last_evidence_at=last_ev,
            freshness=freshness_data["freshness"],
            newest_evidence_at=freshness_data.get("newest_evidence_at"),
        )

        return {
            "id": hyp.id,
            "statement": hyp.statement,
            "segment": hyp.segment,
            "status": hyp.status,
            "created_by": hyp.created_by,
            "decided_at": hyp.decided_at,
            "created_at": hyp.created_at,
            "rollup": rollup,
            "evidence": evidence,
            "supports": supports,
            "contradicts": contradicts,
            "companies_supporting": co_sup,
            "companies_contradicting": co_con,
            "last_evidence_at": last_ev,
            "verdict_hint": verdict_hint,
            "links": link_responses,
        }


@router.patch("/{hypothesis_id}", response_model=HypothesisResponse)
async def update_hypothesis(
    hypothesis_id: int,
    body: HypothesisUpdate,
    request: Request,
    user: User = Depends(get_current_user),
) -> Hypothesis:
    """Update hypothesis statement or status. Statement is immutable once links exist."""
    session_factory = request.app.state.session_factory
    async with session_factory() as db:
        hyp: Hypothesis | None = await db.get(Hypothesis, hypothesis_id)
        if hyp is None:
            raise HTTPException(status_code=404, detail="Hypothesis not found")

        # Validate status if provided
        if body.status is not None:
            if body.status not in VALID_HYPOTHESIS_STATUSES:
                raise HTTPException(
                    status_code=422, detail=f"Invalid status: {body.status}"
                )

        # Check statement immutability if statement is being changed
        if body.statement is not None:
            links_result = await db.execute(
                select(HypothesisLink.id)
                .where(HypothesisLink.hypothesis_id == hypothesis_id)
                .limit(1)
            )
            if links_result.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Statement is immutable once evidence links exist",
                )
            hyp.statement = body.statement

        if body.status is not None:
            hyp.status = body.status
            # Set decided_at for terminal statuses
            if body.status in ("supported", "refuted"):
                hyp.decided_at = utcnow()

        if body.segment is not None:
            hyp.segment = body.segment

        await db.commit()
        await db.refresh(hyp)
        return hyp


@router.post(
    "/{hypothesis_id}/links",
    response_model=HypothesisLinkResponse,
    status_code=201,
)
async def create_hypothesis_link(
    hypothesis_id: int,
    body: HypothesisLinkCreate,
    request: Request,
    user: User = Depends(get_current_user),
) -> HypothesisLink:
    """Manually create an evidence link between a hypothesis and a highlight."""
    session_factory = request.app.state.session_factory
    async with session_factory() as db:
        hyp = await db.get(Hypothesis, hypothesis_id)
        if hyp is None:
            raise HTTPException(status_code=404, detail="Hypothesis not found")

        highlight = await db.get(Highlight, body.highlight_id)
        if highlight is None:
            raise HTTPException(status_code=404, detail="Highlight not found")

        link = HypothesisLink(
            hypothesis_id=hypothesis_id,
            highlight_id=body.highlight_id,
            stance=body.stance,
            origin="human",
            status="suggested",
        )
        db.add(link)
        await db.commit()
        await db.refresh(link)
        return link
