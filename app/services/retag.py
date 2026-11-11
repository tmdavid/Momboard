"""Re-tagging calls safely, in staged and resumable batches (v0.5 R1).

Rules from the rollout plan, enforced here:

* A highlight a person already accepted or rejected is never touched (it keeps its decision).
* A suggestion that something now *depends on* is kept too: a highlight cited by a decision
  receipt, or used by a confirmed hypothesis link. Deleting it would silently break the
  decision or the belief, so the retag leaves it in place (and the new run will not duplicate it).
  Plain, unreviewed suggestions are replaced as usual.
* "Resumable" falls out of the taxonomy stamp: a call is eligible when it was never stamped or was
  tagged under an older taxonomy, so a re-run only picks up what is left, newest first.
"""

from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Conversation,
    DecisionEvidence,
    Highlight,
    HypothesisLink,
    Job,
)
from app.services.taxonomy_version import get_taxonomy_version


async def _protected_ids(db: AsyncSession, highlight_ids: list[int]) -> set[int]:
    """Which of these highlights something depends on."""
    if not highlight_ids:
        return set()
    cited = await db.execute(
        select(DecisionEvidence.highlight_id).where(DecisionEvidence.highlight_id.in_(highlight_ids))
    )
    used = await db.execute(
        select(HypothesisLink.highlight_id).where(
            HypothesisLink.highlight_id.in_(highlight_ids), HypothesisLink.status == "confirmed"
        )
    )
    return {i for (i,) in cited.all() if i is not None} | {i for (i,) in used.all()}


async def _replaceable_suggestions(db: AsyncSession, conversation_id: int) -> list[int]:
    rows = await db.execute(
        select(Highlight.id).where(
            Highlight.conversation_id == conversation_id,
            Highlight.origin == "ai",
            Highlight.status == "suggested",
        )
    )
    return [i for (i,) in rows.all()]


async def count_protected(db: AsyncSession, conversation_ids: list[int]) -> int:
    """How many AI suggestions in these calls a retag would keep because something depends on them."""
    total = 0
    for cid in conversation_ids:
        total += len(await _protected_ids(db, await _replaceable_suggestions(db, cid)))
    return total


async def clear_suggestions(db: AsyncSession, conversation_id: int) -> tuple[int, int]:
    """Delete the replaceable AI suggestions of a call. Returns (deleted, kept_because_depended_on)."""
    ids = await _replaceable_suggestions(db, conversation_id)
    protected = await _protected_ids(db, ids)
    doomed = [i for i in ids if i not in protected]
    if doomed:
        await db.execute(delete(Highlight).where(Highlight.id.in_(doomed)))
    return len(doomed), len(protected)


async def queue_retag(db: AsyncSession, convo: Conversation) -> tuple[int, int]:
    """Clear the call's replaceable suggestions and queue a tag job. Returns (deleted, protected)."""
    deleted, protected = await clear_suggestions(db, convo.id)
    db.add(Job(conversation_id=convo.id, kind="tag", payload={"conversation_id": convo.id}, status="queued"))
    convo.status = "processing"
    await db.flush()
    return deleted, protected


def _eligible_query(version: int):  # noqa: ANN202
    return (
        select(Conversation.id)
        .where(
            Conversation.status == "ready",
            Conversation.source != "simulator",
            (Conversation.taxonomy_version.is_(None)) | (Conversation.taxonomy_version < version),
        )
        .order_by(Conversation.happened_at.desc().nullslast(), Conversation.id.desc())
    )


async def eligible_ids(db: AsyncSession, limit: int | None = None) -> list[int]:
    query = _eligible_query(await get_taxonomy_version(db))
    if limit is not None:
        query = query.limit(limit)
    return [i for (i,) in (await db.execute(query)).all()]


async def count_eligible(db: AsyncSession) -> int:
    version = await get_taxonomy_version(db)
    sub = _eligible_query(version).order_by(None).subquery()
    return (await db.execute(select(func.count()).select_from(sub))).scalar_one()


@dataclass
class BatchResult:
    queued: int
    would_queue: int
    remaining: int
    ids: list[int]
    protected_highlights: int
    taxonomy_version: int


async def retag_batch(db: AsyncSession, limit: int, dry_run: bool = False) -> BatchResult:
    """Queue the newest ``limit`` eligible calls (or just report what would be queued)."""
    version = await get_taxonomy_version(db)
    total = await count_eligible(db)
    ids = await eligible_ids(db, limit)
    if dry_run:
        return BatchResult(0, len(ids), total, ids, await count_protected(db, ids), version)
    protected = 0
    for cid in ids:
        convo = await db.get(Conversation, cid)
        if convo is None:
            continue
        _deleted, kept = await queue_retag(db, convo)
        protected += kept
    return BatchResult(len(ids), len(ids), total - len(ids), ids, protected, version)
