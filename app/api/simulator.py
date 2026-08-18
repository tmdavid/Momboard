"""T39: Interview flight simulator API routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth import get_current_user
from app.models import User

router = APIRouter()


class PersonaBuildRequest(BaseModel):
    filters: dict | None = None


class SimulatorSessionCreateRequest(BaseModel):
    persona_id: int


class SimulatorTurnRequest(BaseModel):
    text: str = Field(min_length=1)


@router.post("/personas", status_code=201)
async def build_persona(
    body: PersonaBuildRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Build a persona from segment filters."""
    from app.llm.factory import create_llm_client
    from app.services.simulator import build_persona as _build_persona

    settings = request.app.state.settings
    llm = create_llm_client(settings)

    try:
        analysis = await _build_persona(db, filters=body.filters, llm=llm)
        await db.commit()
        return {
            "id": analysis.id,
            "kind": analysis.kind,
            "result": analysis.result,
        }
    finally:
        await llm.close()


@router.post("/sessions", status_code=201)
async def create_session(
    body: SimulatorSessionCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new simulator session from a persona."""
    from app.services.simulator import create_simulator_session

    try:
        convo = await create_simulator_session(db, body.persona_id)
        await db.commit()
        return {
            "id": convo.id,
            "title": convo.title,
            "source": convo.source,
            "meta": convo.meta,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/sessions/{session_id}/turns")
async def add_turn(
    session_id: int,
    body: SimulatorTurnRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Send a turn to the simulator and get the persona's reply."""
    from app.llm.factory import create_llm_client
    from app.services.simulator import add_simulator_turn

    settings = request.app.state.settings
    llm = create_llm_client(settings)

    try:
        result = await add_simulator_turn(db, session_id, body.text, llm=llm)
        await db.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        await llm.close()


@router.post("/sessions/{session_id}/end")
async def end_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """End a simulator session and trigger critique."""
    from app.services.simulator import end_simulator_session

    try:
        convo = await end_simulator_session(db, session_id)
        await db.commit()
        return {
            "id": convo.id,
            "title": convo.title,
            "status": convo.status,
            "meta": convo.meta,
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List past simulator sessions with their scores (#19).

    Returns conversations with source='simulator' and their latest analysis score.
    Read-only listing endpoint.
    """
    from sqlalchemy import select as sa_select

    from app.models import Analysis, Conversation

    # Get simulator conversations ordered by most recent
    result = await db.execute(
        sa_select(Conversation)
        .where(Conversation.source == "simulator")
        .order_by(Conversation.created_at.desc())
        .limit(50)
    )
    convos = result.scalars().all()

    sessions = []
    for convo in convos:
        # Fetch latest analysis/critique
        analysis_result = await db.execute(
            sa_select(Analysis)
            .where(
                Analysis.conversation_id == convo.id,
                Analysis.kind == "conversation",
            )
            .order_by(Analysis.created_at.desc())
            .limit(1)
        )
        analysis = analysis_result.scalar_one_or_none()

        score = None
        if analysis and analysis.result and isinstance(analysis.result, dict):
            critique = analysis.result.get("mom_test_critique", {})
            if isinstance(critique, dict):
                score = critique.get("score")

        sessions.append({
            "id": convo.id,
            "title": convo.title,
            "status": convo.status,
            "created_at": convo.created_at.isoformat() if convo.created_at else None,
            "score": score,
            "has_analysis": analysis is not None,
        })

    return {"items": sessions, "total": len(sessions)}


@router.get("/sessions/{session_id}/result")
async def get_session_result(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a simulator session result including conversation analysis (critique).

    Returns the conversation with its analysis if available.
    Used by the UI to poll for scoring completion.
    """
    from sqlalchemy import select as sa_select

    from app.models import Analysis, Conversation

    convo = await db.get(Conversation, session_id)
    if convo is None or convo.source != "simulator":
        raise HTTPException(status_code=404, detail="Simulator session not found")

    # Fetch analysis (critique) if available
    result = await db.execute(
        sa_select(Analysis)
        .where(
            Analysis.conversation_id == session_id,
            Analysis.kind == "conversation",
        )
        .order_by(Analysis.created_at.desc())
        .limit(1)
    )
    analysis = result.scalar_one_or_none()

    return {
        "id": convo.id,
        "title": convo.title,
        "status": convo.status,
        "meta": convo.meta,
        "analysis": {
            "id": analysis.id,
            "kind": analysis.kind,
            "result": analysis.result,
            "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        } if analysis else None,
    }
