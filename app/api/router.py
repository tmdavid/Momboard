"""Main API router aggregating all sub-routers."""

from fastapi import APIRouter, Depends

from app.api.admin import router as admin_router
from app.api.briefs import router as briefs_router
from app.api.chat import router as chat_router
from app.api.contacts import router as contacts_router
from app.api.conversations import router as conversations_router
from app.api.decisions import router as decisions_router
from app.api.digest import router as digest_router
from app.api.explore import router as explore_router
from app.api.highlights import router as highlights_router
from app.api.hypotheses import router as hypotheses_router
from app.api.hypothesis_links import router as hypothesis_links_router
from app.api.inbox import router as inbox_router
from app.api.lenses import router as lenses_router
from app.api.notes import router as notes_router
from app.api.quote_cards import router as quote_cards_router
from app.api.schemas import UserResponse
from app.api.settings import router as settings_router
from app.api.simulator import router as simulator_router
from app.api.syntheses import router as syntheses_router
from app.api.vexa import router as vexa_router
from app.auth import get_current_user

api_router = APIRouter(dependencies=[Depends(get_current_user)])

api_router.include_router(conversations_router, prefix="/conversations", tags=["conversations"])
api_router.include_router(highlights_router, prefix="/highlights", tags=["highlights"])
api_router.include_router(notes_router, tags=["notes"])
api_router.include_router(explore_router, tags=["explore"])
api_router.include_router(syntheses_router, prefix="/syntheses", tags=["syntheses"])
api_router.include_router(hypotheses_router, prefix="/hypotheses", tags=["hypotheses"])
api_router.include_router(
    hypothesis_links_router, prefix="/hypothesis-links", tags=["hypothesis-links"]
)
api_router.include_router(inbox_router, prefix="/inbox", tags=["inbox"])
api_router.include_router(contacts_router, prefix="/contacts", tags=["contacts"])
api_router.include_router(briefs_router, prefix="/contacts", tags=["briefs"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_router.include_router(digest_router, prefix="/digest", tags=["digest"])
api_router.include_router(quote_cards_router, prefix="/highlights", tags=["quote-cards"])
api_router.include_router(decisions_router, prefix="/decisions", tags=["decisions"])
api_router.include_router(simulator_router, prefix="/simulator", tags=["simulator"])
api_router.include_router(lenses_router, prefix="/lenses", tags=["lenses"])
api_router.include_router(vexa_router, prefix="/vexa", tags=["vexa"])
api_router.include_router(settings_router, tags=["settings"])
api_router.include_router(admin_router, tags=["admin"])


@api_router.get("/me", response_model=UserResponse)
async def me(user=Depends(get_current_user)):
    """Return current user info."""
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role}
