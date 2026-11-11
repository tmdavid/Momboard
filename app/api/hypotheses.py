"""Hypothesis CRUD, evidence links, and detail rollup endpoints."""

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    HypothesisCreate,
    HypothesisDetailResponse,
    HypothesisIntakeCommit,
    HypothesisIntakeRequest,
    HypothesisIntakeResponse,
    HypothesisLinkCreate,
    HypothesisLinkResponse,
    HypothesisListResponse,
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

VALID_HYPOTHESIS_STATUSES = {"open", "supported", "refuted", "parked", "archived"}
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


def _compute_grounding(
    supports: dict[str, int],
    contradicts: dict[str, int],
) -> str:
    """Derive the 2D grounding band from confirmed/suggested link counts (T48).

    Support and contradiction are independent axes — the same belief can be both
    supported and contradicted by different customers — so grounding is a 2x2, not a
    single gradient:

        has confirmed support?  has confirmed contradiction?  -> band
        yes                     no                            -> grounded
        yes                     yes                           -> contested
        no                      yes                           -> refuted
        no                      no  (some suggested links)    -> candidate
        no                      no  (no links at all)         -> hunch

    Confirmed evidence always beats suggested: a confirmed support makes the band
    `grounded`/`contested` regardless of how many suggested links exist. Pure and
    computed at read time — never stored (mirrors T41 freshness).
    """
    has_support = supports.get("confirmed", 0) > 0
    has_contradiction = contradicts.get("confirmed", 0) > 0

    if has_support and has_contradiction:
        return "contested"
    if has_support:
        return "grounded"
    if has_contradiction:
        return "refuted"
    # No confirmed evidence either way.
    if supports.get("suggested", 0) > 0 or contradicts.get("suggested", 0) > 0:
        return "candidate"
    return "hunch"


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _compute_grounding_reason(
    supports: dict[str, int],
    contradicts: dict[str, int],
    companies_supporting: int,
    companies_contradicting: int,
) -> str:
    """One plain sentence explaining the band, from confirmed links (suggested never count)."""
    sup = supports.get("confirmed", 0)
    con = contradicts.get("confirmed", 0)
    sup_part = (
        f"{_plural(sup, 'supporting quote')} from {_plural(companies_supporting, 'company')}"
    )
    con_part = (
        f"{_plural(con, 'contradicting quote')} from {_plural(companies_contradicting, 'company')}"
    )
    if sup and con:
        return f"{sup_part} vs {con_part}."
    if sup:
        return f"{sup_part}, 0 contradicting."
    if con:
        return f"{con_part}, none supporting."
    pending = supports.get("suggested", 0) + contradicts.get("suggested", 0)
    if pending:
        return f"No confirmed evidence yet; {_plural(pending, 'suggested quote')} awaiting review."
    return "No evidence yet."


def _build_rollup_model(
    supports: dict[str, int],
    contradicts: dict[str, int],
    co_sup: int,
    co_con: int,
    last_ev: datetime | None,
    freshness_data: dict,
) -> HypothesisRollup:
    return HypothesisRollup(
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
        grounding=_compute_grounding(supports, contradicts),
        pending_count=supports.get("suggested", 0) + contradicts.get("suggested", 0),
        grounding_reason=_compute_grounding_reason(supports, contradicts, co_sup, co_con),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


BandFilter = Literal["grounded", "contested", "refuted", "candidate", "hunch"]
SortKey = Literal["newest", "evidence", "support", "pending"]


@router.get("", response_model=HypothesisListResponse)
async def list_hypotheses(
    request: Request,
    band: BandFilter | None = Query(default=None, description="Filter by grounding band"),
    segment: str | None = Query(default=None, description="Filter by segment (case-insensitive)"),
    status: str | None = Query(
        default=None,
        description="Filter by status. Archived hypotheses are hidden unless status=archived.",
    ),
    has_pending: bool | None = Query(
        default=None, description="Only hypotheses with suggested links awaiting review"
    ),
    sort: SortKey = Query(default="newest", description="newest|evidence|support|pending"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
) -> dict:
    """List hypotheses with rollup data for the board.

    The band is computed at read time (never stored), so band/has_pending filters and
    sorting are applied after the rollup is built, then the page is cut. Archived
    hypotheses are hidden unless ``status=archived``.
    """
    from app.services.staleness import get_hypothesis_freshness

    if status is not None and status not in VALID_HYPOTHESIS_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {status}")

    session_factory = request.app.state.session_factory
    async with session_factory() as db:
        stmt = select(Hypothesis).order_by(Hypothesis.created_at.desc(), Hypothesis.id.desc())
        if status is not None:
            stmt = stmt.where(Hypothesis.status == status)
        else:
            stmt = stmt.where(Hypothesis.status != "archived")
        if segment:
            stmt = stmt.where(func.lower(Hypothesis.segment) == segment.strip().lower())
        hypotheses = (await db.execute(stmt)).scalars().all()

        items: list[dict] = []
        for hyp in hypotheses:
            supports, contradicts, co_sup, co_con, last_ev = await _build_rollup(db, hyp.id)
            rollup = _build_rollup_model(
                supports, contradicts, co_sup, co_con, last_ev,
                await get_hypothesis_freshness(db, hyp.id),
            )
            if band and rollup.grounding != band:
                continue
            if has_pending is True and rollup.pending_count == 0:
                continue
            if has_pending is False and rollup.pending_count > 0:
                continue
            items.append({
                "id": hyp.id,
                "statement": hyp.statement,
                "segment": hyp.segment,
                "status": hyp.status,
                "created_by": hyp.created_by,
                "decided_at": hyp.decided_at,
                "created_at": hyp.created_at,
                "rollup": rollup,
                "verdict_hint": _compute_verdict_hint(supports, contradicts, co_sup, co_con),
            })

        if sort == "evidence":
            items.sort(
                key=lambda i: (i["rollup"].last_evidence_at is not None,
                               i["rollup"].last_evidence_at or datetime.min),
                reverse=True,
            )
        elif sort == "support":
            items.sort(key=lambda i: i["rollup"].supports["confirmed"], reverse=True)
        elif sort == "pending":
            items.sort(key=lambda i: i["rollup"].pending_count, reverse=True)
        # "newest" is already the query order; list.sort is stable for the others.

        return {"items": items[offset : offset + limit], "total": len(items)}


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


@router.post("/intake", response_model=HypothesisIntakeResponse)
async def preview_hypothesis_intake(
    body: HypothesisIntakeRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    """T48: preview corpus evidence for a typed belief. Read-only — saves nothing.

    Returns matched highlights (scored supports/contradicts), a grounding preview,
    and past-behavior validation questions when evidence is thin.
    """
    from app.llm.factory import create_llm_client
    from app.services.hypothesis_intake import preview_intake

    settings = request.app.state.settings
    session_factory = request.app.state.session_factory
    llm = create_llm_client(settings, agent="corpus_chat")
    try:
        async with session_factory() as db:
            return await preview_intake(
                db, body.statement, llm=llm, segment=body.segment,
                min_confidence=body.min_confidence,
            )
    finally:
        await llm.close()


@router.post("/intake/commit", response_model=HypothesisResponse, status_code=201)
async def commit_hypothesis_intake(
    body: HypothesisIntakeCommit,
    request: Request,
    user: User = Depends(get_current_user),
) -> Hypothesis:
    """T48: save a belief from intake with human-confirmed evidence links.

    Creates a Hypothesis (origin='human') and, for each confirmed match, a
    HypothesisLink (origin='human', status='confirmed') — the human actively
    asserted these quotes are evidence. Grounding then derives from the confirmed
    links on read (fetch the hypothesis detail to see it). ``validation_questions``
    are accepted for a thin belief but not persisted in this iteration (no store
    column yet; a follow-up may add one).
    """
    session_factory = request.app.state.session_factory
    async with session_factory() as db:
        hyp = Hypothesis(
            statement=body.statement,
            segment=body.segment,
            status="open",
            origin="human",
            created_by=user.id,
        )
        db.add(hyp)
        await db.flush()

        for item in body.confirmed:
            highlight = await db.get(Highlight, item.highlight_id)
            if highlight is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Highlight {item.highlight_id} not found",
                )
            db.add(
                HypothesisLink(
                    hypothesis_id=hyp.id,
                    highlight_id=item.highlight_id,
                    stance=item.stance,
                    origin="human",
                    status="confirmed",
                )
            )
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
            if link.status in ("rejected", "invalid"):
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
        rollup = _build_rollup_model(
            supports, contradicts, co_sup, co_con, last_ev, freshness_data
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
