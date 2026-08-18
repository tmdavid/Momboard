"""Settings status API: safe configuration and capability status (#22).

Exposes masked key states (never full secrets), active model names, service
connection states, digest schedule, taxonomy/company counts, and whether the
current user may administer taxonomy.
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
    api_key_hint: str  # "configured", "not set", or "not required"


class DigestStatus(BaseModel):
    slack_configured: bool
    schedule: str


class SettingsStatusResponse(BaseModel):
    llm: LLMStatus
    vexa: ServiceStatus
    gdrive: ServiceStatus
    slack: ServiceStatus
    digest: DigestStatus
    taxonomy_count: int
    active_company_count: int
    can_manage_taxonomy: bool


def _mask_key(key: str) -> str:
    """Report configuration without exposing any part of the secret."""
    return "configured" if key else "not set"


@router.get("/settings/status", response_model=SettingsStatusResponse)
async def get_settings_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return safe system configuration and current-user capabilities."""
    settings = request.app.state.settings

    taxonomy_result = await db.execute(select(func.count()).select_from(Tag))
    taxonomy_count = taxonomy_result.scalar_one()

    active_companies_result = await db.execute(
        select(func.count(func.distinct(Company.id))).where(
            Company.id.in_(
                select(Conversation.company_id).where(Conversation.company_id.is_not(None))
            )
        )
    )
    active_company_count = active_companies_result.scalar_one()

    is_local = settings.llm_backend == "local"
    if is_local:
        active_models = {
            "normalizer": settings.llm_local_model,
            "tagger": settings.llm_local_model,
            "analyst": settings.llm_local_model,
            "synthesizer": settings.llm_local_model,
        }
        api_key_hint = "not required"
    else:
        active_models = {
            "normalizer": settings.llm_model_normalizer,
            "tagger": settings.llm_model_tagger,
            "analyst": settings.llm_model_analyst,
            "synthesizer": settings.llm_model_synthesizer,
        }
        api_key_hint = _mask_key(settings.openai_api_key)

    llm_status = LLMStatus(
        backend=settings.llm_backend,
        model_normalizer=active_models["normalizer"],
        model_tagger=active_models["tagger"],
        model_analyst=active_models["analyst"],
        model_synthesizer=active_models["synthesizer"],
        api_key_configured=bool(settings.openai_api_key),
        api_key_hint=api_key_hint,
    )

    vexa_configured = bool(settings.vexa_base_url and settings.vexa_api_key)
    vexa_status = ServiceStatus(
        configured=vexa_configured,
        detail="connected" if vexa_configured else "not configured",
    )

    gdrive_configured = bool(
        settings.gdrive_folder_id and settings.gdrive_service_account_json
    )
    gdrive_status = ServiceStatus(
        configured=gdrive_configured,
        detail="connected" if gdrive_configured else "not configured",
    )

    slack_configured = bool(settings.slack_webhook_url)
    slack_status = ServiceStatus(
        configured=slack_configured,
        detail="configured" if slack_configured else "not configured",
    )
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
        can_manage_taxonomy=user.role == "admin",
    )
