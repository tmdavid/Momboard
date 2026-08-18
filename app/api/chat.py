"""T42: Corpus chat API — citation-or-silence."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth import get_current_user

router = APIRouter()


class ChatQuestion(BaseModel):
    question: str
    chat_id: int | None = None
    filters: dict[str, Any] | None = None


class ChatClaimResponse(BaseModel):
    text: str
    evidence_highlight_ids: list[int] = Field(default_factory=list)


class ChatAnswerResponse(BaseModel):
    claims: list[ChatClaimResponse] = Field(default_factory=list)
    gap: bool = False
    suggested_interview_question: str | None = None
    chat_id: int | None = None


class ChatListItem(BaseModel):
    id: int
    title: str | None = None
    turn_count: int = 0
    updated_at: str

    model_config = {"from_attributes": True}


@router.post("", response_model=ChatAnswerResponse)
async def ask_corpus_endpoint(
    body: ChatQuestion,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Ask a question over the evidence corpus. Citations or silence."""
    from app.config import get_settings
    from app.llm.factory import create_llm_client
    from app.services.corpus_chat import ask_corpus, store_chat_turn

    settings = get_settings()
    llm = create_llm_client(settings, agent="chat")
    try:
        answer = await ask_corpus(
            db,
            body.question,
            llm=llm,
            filters=body.filters,
            user_id=user.id,
        )
    finally:
        if hasattr(llm, "close"):
            await llm.close()

    # Store turn
    chat = await store_chat_turn(db, user.id, body.chat_id, body.question, answer)
    await db.commit()

    return ChatAnswerResponse(
        claims=[
            ChatClaimResponse(text=c["text"], evidence_highlight_ids=c["evidence_highlight_ids"])
            for c in answer.get("claims", [])
        ],
        gap=answer.get("gap", False),
        suggested_interview_question=answer.get("suggested_interview_question"),
        chat_id=chat.id,
    )


@router.get("", response_model=list[ChatListItem])
async def list_chats(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """List user's chat history."""
    from app.services.corpus_chat import list_user_chats

    chats = await list_user_chats(db, user.id)
    return [
        ChatListItem(
            id=c.id,
            title=c.title,
            turn_count=len(c.turns) if isinstance(c.turns, list) else 0,
            updated_at=c.updated_at.isoformat(),
        )
        for c in chats
    ]


@router.get("/{chat_id}", response_model=dict)
async def get_chat(
    chat_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get a specific chat with all turns."""
    from app.models import Chat

    chat = await db.get(Chat, chat_id)
    if chat is None or chat.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat not found")

    return {
        "id": chat.id,
        "title": chat.title,
        "turns": chat.turns,
        "created_at": chat.created_at.isoformat(),
        "updated_at": chat.updated_at.isoformat(),
    }
