"""T39: Interview flight simulator — persona builder + chat loop + critique."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Analysis,
    Conversation,
    Highlight,
    Job,
    Utterance,
)

logger = logging.getLogger(__name__)


async def build_persona(
    db: AsyncSession,
    *,
    filters: dict[str, Any] | None = None,
    llm: Any,
) -> Analysis:
    """Build a persona from accepted highlights matching the given segment filters.

    Stores the result as analyses(kind='persona').
    Persona traits cite source highlight IDs; unknown IDs are stripped.
    """
    from app.llm.schemas import PersonaOutput

    # Gather accepted highlights (excluding simulated conversations)
    query = (
        select(Highlight)
        .join(Conversation, Conversation.id == Highlight.conversation_id)
        .where(
            Highlight.status == "accepted",
            Conversation.source != "simulator",
        )
    )

    if filters:
        if "company_id" in filters:
            query = query.where(Conversation.company_id == filters["company_id"])
        if "tag_key" in filters:
            query = query.where(Highlight.tag_key == filters["tag_key"])

    query = query.order_by(Highlight.created_at.desc()).limit(40)
    result = await db.execute(query)
    highlights = list(result.scalars().all())

    valid_ids = {h.id for h in highlights}

    if not highlights:
        # Return canned starter persona for empty repos
        persona = PersonaOutput(
            name="Marta",
            role="Operations Manager",
            company_profile="Mid-size enterprise, 200 employees",
            traits=[],
            sore_points=["Manual reporting", "Data silos"],
            vocabulary_hints=["spreadsheet", "weekly sync", "export"],
        )
    else:
        highlight_data = [
            {"id": h.id, "tag": h.tag_key, "quote": h.quote}
            for h in highlights
        ]
        prompt = (
            "You are building a customer persona for an interview practice simulator. "
            "Based on the evidence below, create a realistic persona with:\n"
            "- name, role, company_profile\n"
            "- traits: observable behaviors/attitudes (each citing evidence highlight IDs)\n"
            "- sore_points: things that frustrate this persona\n"
            "- vocabulary_hints: words/phrases they would naturally use\n\n"
            "RULES:\n"
            "- Persona must reflect the ACTUAL evidence, not generic stereotypes\n"
            "- Each trait must cite at least one valid highlight ID\n"
            "- The persona should behave per Mom Test principles when interviewed:\n"
            "  compliments when pitched at, vague on hypotheticals, concrete on past events\n\n"
            f"EVIDENCE:\n{highlight_data}"
        )
        persona = await llm.generate(
            prompt=prompt,
            schema=PersonaOutput,
            model="persona",
        )

        # Validate highlight IDs in traits
        for trait in persona.traits:
            trait.evidence_highlight_ids = [
                hid for hid in trait.evidence_highlight_ids if hid in valid_ids
            ]

    # Store as analysis
    analysis = Analysis(
        conversation_id=None,
        kind="persona",
        input_scope={"filters": filters or {}},
        result=persona.model_dump(),
        model=getattr(llm, "model_name", None),
        prompt_version="persona_v1",
    )
    db.add(analysis)
    await db.flush()
    return analysis


async def create_simulator_session(
    db: AsyncSession,
    persona_id: int,
) -> Conversation:
    """Create a new simulator session (stored as a conversation with source='simulator').

    The conversation meta includes simulated=true and persona_id.
    """
    persona_analysis = await db.get(Analysis, persona_id)
    if persona_analysis is None or persona_analysis.kind != "persona":
        raise ValueError(f"Persona analysis {persona_id} not found")

    persona_data = persona_analysis.result or {}
    persona_name = persona_data.get("name", "Persona")

    convo = Conversation(
        title=f"Simulator: {persona_name}",
        source="simulator",
        status="ready",
        meta={"simulated": True, "persona_id": persona_id},
    )
    db.add(convo)
    await db.flush()
    return convo


async def add_simulator_turn(
    db: AsyncSession,
    session_id: int,
    user_text: str,
    *,
    llm: Any,
) -> dict[str, Any]:
    """Add a user turn and get the persona's reply.

    Stores utterances on the simulator conversation.
    Returns the persona reply text.
    """
    from app.llm.schemas import SimulatorReplyOutput

    convo = await db.get(Conversation, session_id)
    if convo is None or convo.source != "simulator":
        raise ValueError(f"Simulator session {session_id} not found")

    # Get existing turns count
    existing_result = await db.execute(
        select(Utterance)
        .where(Utterance.conversation_id == session_id)
        .order_by(Utterance.idx.desc())
        .limit(1)
    )
    last_utterance = existing_result.scalar_one_or_none()
    next_idx = (last_utterance.idx + 1) if last_utterance else 0

    # Store user turn
    user_utt = Utterance(
        conversation_id=session_id,
        idx=next_idx,
        speaker_label="Interviewer",
        speaker_side="us",
        text=user_text,
    )
    db.add(user_utt)
    next_idx += 1

    # Build persona context for LLM
    persona_meta = convo.meta or {}
    persona_id = persona_meta.get("persona_id")
    persona_data: dict[str, Any] = {}
    if persona_id:
        persona_analysis = await db.get(Analysis, persona_id)
        if persona_analysis:
            persona_data = persona_analysis.result or {}

    # Get conversation history
    history_result = await db.execute(
        select(Utterance)
        .where(Utterance.conversation_id == session_id)
        .order_by(Utterance.idx)
    )
    history = list(history_result.scalars().all())

    history_text = "\n".join(
        f"{u.speaker_label}: {u.text}" for u in history
    )

    prompt = (
        f"You are roleplaying as {persona_data.get('name', 'a customer')} "
        f"({persona_data.get('role', 'unknown role')}).\n\n"
        f"Company: {persona_data.get('company_profile', 'unknown')}\n"
        f"Traits: {persona_data.get('traits', [])}\n"
        f"Sore points: {persona_data.get('sore_points', [])}\n"
        f"Vocabulary: {persona_data.get('vocabulary_hints', [])}\n\n"
        "BEHAVIOR RULES:\n"
        "- Give compliments when the interviewer pitches ideas at you\n"
        "- Answer hypotheticals vaguely ('yeah maybe', 'could be useful')\n"
        "- Give concrete stories when asked about past events\n"
        "- Only commit (time/money/reputation) under a real specific ask\n\n"
        f"CONVERSATION SO FAR:\n{history_text}\n\n"
        f"Interviewer: {user_text}\n\n"
        "Respond in character. Be concise (1-3 sentences)."
    )

    reply_output = await llm.generate(
        prompt=prompt,
        schema=SimulatorReplyOutput,
        model="simulator",
    )

    reply_text = reply_output.reply or "..."

    # Store persona reply
    persona_utt = Utterance(
        conversation_id=session_id,
        idx=next_idx,
        speaker_label=persona_data.get("name", "Persona"),
        speaker_side="them",
        text=reply_text,
    )
    db.add(persona_utt)
    await db.flush()

    return {"reply": reply_text, "turn_idx": next_idx}


async def end_simulator_session(
    db: AsyncSession,
    session_id: int,
) -> Conversation:
    """End a simulator session: enqueue critique job.

    The conversation is marked with meta.simulated=True and excluded from
    Explore/Insights/hypothesis-linking by that filter.
    Prevents duplicate end jobs if session was already ended.
    """
    convo = await db.get(Conversation, session_id)
    if convo is None or convo.source != "simulator":
        raise ValueError(f"Simulator session {session_id} not found")

    # Prevent duplicate end jobs: check if a tag/ingest job already exists
    existing_result = await db.execute(
        select(Job)
        .where(
            Job.conversation_id == session_id,
            Job.kind.in_(["tag", "ingest"]),
        )
    )
    existing_jobs = list(existing_result.scalars().all())
    if existing_jobs:
        raise ValueError(f"Session {session_id} has already been ended (jobs exist)")

    # Enqueue tag + analyze jobs (critique comes from analyst)
    job = Job(
        conversation_id=session_id,
        kind="tag",
        payload={"conversation_id": session_id},
        status="queued",
    )
    db.add(job)
    await db.flush()

    return convo
