"""Settings status API: read-only, safe configuration status (#22).

Exposes masked key states (never full secrets), model names, service
connection states (booleans), digest schedule, taxonomy count, and
active company count.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth import get_current_user
from app.models import Company, Conversation, Tag, User

router = APIRouter()


class ServiceStatus(BaseModel):
    configured: bool
    detail: str = ""


class LLMStatus(BaseModel):
    model_config = {"protected_namespaces": ()}

    backend: str
    model_normalizer: str
    model_tagger: str
    model_analyst: str
    model_synthesizer: str
    api_key_configured: bool
    api_key_hint: str  # "configured" or "not set"


class DigestStatus(BaseModel):
    slack_configured: bool
    schedule: str  # e.g. "Slack · Mon 08:00" or "not configured"


class SettingsStatusResponse(BaseModel):
    llm: LLMStatus
    vexa: ServiceStatus
    gdrive: ServiceStatus
    slack: ServiceStatus
    digest: DigestStatus
    taxonomy_count: int
    active_company_count: int


def _mask_key(key: str) -> str:
    """Report configuration without exposing any part of the secret."""
    return "configured" if key else "not set"


@router.get("/settings/status", response_model=SettingsStatusResponse)
async def get_settings_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return safe, read-only system configuration status.

    Never returns full secrets — only booleans and masked hints.
    """
    settings = request.app.state.settings

    # Taxonomy count
    taxonomy_result = await db.execute(select(func.count()).select_from(Tag))
    taxonomy_count = taxonomy_result.scalar_one()

    # Active company count (companies with at least one conversation)
    active_companies_result = await db.execute(
        select(func.count(func.distinct(Company.id))).where(
            Company.id.in_(
                select(Conversation.company_id).where(Conversation.company_id.is_not(None))
            )
        )
    )
    active_company_count = active_companies_result.scalar_one()

    # LLM status
    llm_status = LLMStatus(
        backend=settings.llm_backend,
        model_normalizer=settings.llm_model_normalizer,
        model_tagger=settings.llm_model_tagger,
        model_analyst=settings.llm_model_analyst,
        model_synthesizer=settings.llm_model_synthesizer,
        api_key_configured=bool(settings.openai_api_key),
        api_key_hint=_mask_key(settings.openai_api_key),
    )

    # Vexa status
    vexa_status = ServiceStatus(
        configured=bool(settings.vexa_base_url and settings.vexa_api_key),
        detail="connected" if (settings.vexa_base_url and settings.vexa_api_key) else "not configured",
    )

    # Google Drive status
    gdrive_status = ServiceStatus(
        configured=bool(settings.gdrive_folder_id and settings.gdrive_service_account_json),
        detail="connected" if (settings.gdrive_folder_id and settings.gdrive_service_account_json) else "not configured",
    )

    # Slack status
    slack_configured = bool(settings.slack_webhook_url)
    slack_status = ServiceStatus(
        configured=slack_configured,
        detail="configured" if slack_configured else "not configured",
    )

    # Digest schedule
    digest_status = DigestStatus(
        slack_configured=slack_configured,
        schedule="Slack · Mon 08:00" if slack_configured else "not configured",
    )

    return SettingsStatusResponse(
        llm=llm_status,
        vexa=vexa_status,
        gdrive=gdrive_status,
        slack=slack_status,
        digest=digest_status,
        taxonomy_count=taxonomy_count,
        active_company_count=active_company_count,
    )
