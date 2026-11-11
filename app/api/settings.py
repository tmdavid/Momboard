"""Settings status API: safe configuration and capability status (#22).

Exposes masked key states (never full secrets), active model names, service
connection states, digest schedule, taxonomy/company counts, and whether the
current user may administer taxonomy.
"""

import re

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth import get_current_user, require_admin
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
    # Backend-agnostic fields so the UI doesn't hardcode OpenAI framing.
    credential_ready: bool  # Whether the active backend has what it needs to run.
    credential_label: str  # Human-readable credential status for the active backend.
    single_model: bool  # True when all stages share one model (local/bedrock default view).


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

    backend = settings.llm_backend
    if backend == "local":
        active_models = {
            "normalizer": settings.llm_local_model,
            "tagger": settings.llm_local_model,
            "analyst": settings.llm_local_model,
            "synthesizer": settings.llm_local_model,
        }
        api_key_hint = "not required"
        credential_ready = True
        credential_label = "Local model — no API key required"
        single_model = True
    elif backend == "bedrock":
        from app.llm.factory import _build_bedrock_model_map, _has_aws_credentials

        model_map = _build_bedrock_model_map(settings)
        active_models = {
            "normalizer": model_map["normalizer"],
            "tagger": model_map["tagger"],
            "analyst": model_map["analyst"],
            "synthesizer": model_map["synthesizer"],
        }
        # OpenAI key is irrelevant to Bedrock; credentials come from the AWS chain.
        api_key_hint = "not required"
        credential_ready = _has_aws_credentials()
        credential_label = (
            "AWS credentials resolved"
            if credential_ready
            else "AWS credentials not found — using keyless fallback"
        )
        # Per-stage models are shown individually so per-agent overrides are visible.
        single_model = len({*active_models.values()}) == 1
    else:  # openai
        active_models = {
            "normalizer": settings.llm_model_normalizer,
            "tagger": settings.llm_model_tagger,
            "analyst": settings.llm_model_analyst,
            "synthesizer": settings.llm_model_synthesizer,
        }
        api_key_hint = _mask_key(settings.openai_api_key)
        credential_ready = bool(settings.openai_api_key)
        credential_label = api_key_hint
        single_model = False

    llm_status = LLMStatus(
        backend=settings.llm_backend,
        model_normalizer=active_models["normalizer"],
        model_tagger=active_models["tagger"],
        model_analyst=active_models["analyst"],
        model_synthesizer=active_models["synthesizer"],
        api_key_configured=bool(settings.openai_api_key),
        api_key_hint=api_key_hint,
        credential_ready=credential_ready,
        credential_label=credential_label,
        single_model=single_model,
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


# --- v0.5 D6: "Your company" ---

_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")


class CompanyProfileBody(BaseModel):
    name: str = Field(default="", max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    email_domains: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("aliases")
    @classmethod
    def _alias_length(cls, values: list[str]) -> list[str]:
        if any(len(v) > 200 for v in values):
            raise ValueError("Each alias must be 200 characters or fewer")
        return values

    @field_validator("email_domains")
    @classmethod
    def _domains(cls, values: list[str]) -> list[str]:
        for raw in values:
            domain = raw.strip().lstrip("@").lower()
            if domain and (len(domain) > 253 or not _DOMAIN_RE.match(domain)):
                raise ValueError(f"Not a valid email domain: {raw!r}")
        return values


class CompanyProfileResponse(CompanyProfileBody):
    configured: bool = False


def _profile_response(profile) -> dict:
    return {**profile.to_dict(), "configured": profile.configured}


@router.get("/settings/company", response_model=CompanyProfileResponse)
async def get_company_profile(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The seller's company profile (name, aliases, email domains)."""
    from app.services.seller_profile import load_seller_profile

    return _profile_response(await load_seller_profile(db))


@router.put("/settings/company", response_model=CompanyProfileResponse)
async def put_company_profile(
    body: CompanyProfileBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Save the profile (admin only). Prompts pick it up immediately."""
    from app.llm.seller import SellerProfile
    from app.services.seller_profile import save_seller_profile

    profile = SellerProfile.from_dict(body.model_dump())
    await save_seller_profile(db, profile)
    return _profile_response(profile)
