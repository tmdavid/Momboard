"""T42: Ask-the-corpus chat — citation-or-silence, SQL-first retrieval, shared service."""

import logging
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chat,
    Conversation,
    Highlight,
    utcnow,
)

logger = logging.getLogger(__name__)


async def _retrieve_candidates(
    db: AsyncSession,
    question: str,
    *,
    filters: dict[str, Any] | None = None,
    limit: int = 60,
) -> list[Highlight]:
    """Stage 1: SQL-first retrieval of candidate highlights.

    Uses keyword LIKE matching + optional tag/company/date filters.
    Excludes simulated conversations and rejected highlights.
    """
    query = (
        select(Highlight)
        .join(Conversation, Conversation.id == Highlight.conversation_id)
        .where(
            Highlight.status.in_(["accepted", "suggested"]),
            # Exclude simulated conversations — portable: source != 'simulator'
            Conversation.source != "simulator",
        )
    )

    # Apply filters
    if filters:
        if "tag_key" in filters:
            query = query.where(Highlight.tag_key == filters["tag_key"])
        if "company_id" in filters:
            query = query.where(Conversation.company_id == filters["company_id"])
        if "date_from" in filters:
            query = query.where(Conversation.happened_at >= filters["date_from"])
        if "date_to" in filters:
            query = query.where(Conversation.happened_at <= filters["date_to"])

    # Keyword matching on quote text
    keywords = [w.strip() for w in question.split() if len(w.strip()) > 2]
    if keywords:
        # Match any keyword in the quote
        keyword_conditions = [
            Highlight.quote.ilike(f"%{kw}%") for kw in keywords[:5]
        ]
        query = query.where(or_(*keyword_conditions))

    query = query.order_by(Highlight.created_at.desc()).limit(limit)
    result = await db.execute(query)
    candidates = list(result.scalars().all())

    # If keyword matching returns too few, fall back to recent accepted highlights
    if len(candidates) < 5:
        fallback_query = (
            select(Highlight)
            .join(Conversation, Conversation.id == Highlight.conversation_id)
            .where(
                Highlight.status.in_(["accepted", "suggested"]),
                # Exclude simulated conversations — portable
                Conversation.source != "simulator",
            )
            .order_by(Highlight.created_at.desc())
            .limit(limit)
        )
        if filters:
            if "tag_key" in filters:
                fallback_query = fallback_query.where(Highlight.tag_key == filters["tag_key"])
            if "company_id" in filters:
                fallback_query = fallback_query.where(Conversation.company_id == filters["company_id"])

        fallback_result = await db.execute(fallback_query)
        candidates = list(fallback_result.scalars().all())

    return candidates


async def ask_corpus(
    db: AsyncSession,
    question: str,
    *,
    llm: Any,
    filters: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Two-stage corpus chat: SQL retrieval → LLM composition.

    Returns dict matching CorpusChatOutput schema:
    - claims: [{text, evidence_highlight_ids}] — every claim cites IDs
    - gap: bool — true if no evidence found
    - suggested_interview_question: str | None — drafted question for gaps
    """
    from app.llm.schemas import CorpusChatOutput

    # Stage 1: Retrieve candidates
    candidates = await _retrieve_candidates(db, question, filters=filters)

    valid_ids = {h.id for h in candidates}

    if not candidates:
        # Gap answer — no evidence
        return {
            "claims": [],
            "gap": True,
            "suggested_interview_question": (
                f"Based on your question '{question}', consider asking: "
                "'How do you currently handle this?' in your next interview."
            ),
        }

    # Stage 2: LLM composition from candidates only
    candidate_data = [
        {"id": h.id, "tag": h.tag_key, "quote": h.quote}
        for h in candidates[:30]  # Limit context
    ]

    prompt = (
        "You are answering a question about customer evidence. "
        "ONLY use the provided evidence — cite highlight IDs for every claim. "
        "If the evidence doesn't answer the question, set gap=true and suggest an interview question.\n\n"
        "HARD RULES:\n"
        "- Every claim MUST cite at least one evidence_highlight_id from the candidates\n"
        "- NEVER invent or hallucinate customer sentiment\n"
        "- If evidence is insufficient, return gap=true\n\n"
        f"QUESTION: {question}\n\n"
        f"EVIDENCE CANDIDATES:\n{candidate_data}"
    )

    result = await llm.generate(
        prompt=prompt,
        schema=CorpusChatOutput,
        model="corpus_chat",
    )

    # Validate: drop claims with no valid IDs
    validated_claims = []
    for claim in result.claims:
        valid_claim_ids = [hid for hid in claim.evidence_highlight_ids if hid in valid_ids]
        if valid_claim_ids:
            validated_claims.append({
                "text": claim.text,
                "evidence_highlight_ids": valid_claim_ids,
            })

    output = {
        "claims": validated_claims,
        "gap": result.gap or len(validated_claims) == 0,
        "suggested_interview_question": result.suggested_interview_question,
    }

    return output


async def store_chat_turn(
    db: AsyncSession,
    user_id: int,
    chat_id: int | None,
    question: str,
    answer: dict[str, Any],
) -> Chat:
    """Store a chat turn. Creates a new chat if chat_id is None."""
    if chat_id:
        chat = await db.get(Chat, chat_id)
        if chat is None or chat.user_id != user_id:
            raise ValueError("Chat not found or not owned by user")
        turns: list[dict[str, Any]] = chat.turns if isinstance(chat.turns, list) else []
    else:
        chat = Chat(
            user_id=user_id,
            title=question[:100],
            turns=[],
        )
        db.add(chat)
        await db.flush()
        turns = []

    # Append turn
    turns.append({
        "role": "user",
        "content": question,
    })
    turns.append({
        "role": "assistant",
        "content": answer,  # type: ignore[dict-item]
    })

    chat.turns = turns  # type: ignore[assignment]
    chat.updated_at = utcnow()
    await db.flush()
    return chat


async def list_user_chats(
    db: AsyncSession,
    user_id: int,
    *,
    limit: int = 50,
) -> list[Chat]:
    """List chats for a user, newest first."""
    result = await db.execute(
        select(Chat)
        .where(Chat.user_id == user_id)
        .order_by(Chat.updated_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
