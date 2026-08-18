"""Pydantic schemas for API request/response models."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# --- Auth ---


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    name: str | None = None
    role: str


# --- Companies ---


class CompanyCreate(BaseModel):
    name: str
    domain: str | None = None


class CompanyResponse(BaseModel):
    id: int
    name: str
    domain: str | None = None
    notes: str | None = None
    conversation_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Contacts ---


class ContactCreate(BaseModel):
    name: str
    role: str | None = None
    email: str | None = None
    company_id: int | None = None


class ContactResponse(BaseModel):
    id: int
    name: str
    role: str | None = None
    email: str | None = None
    company_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Tags ---


class TagResponse(BaseModel):
    key: str
    emoji: str
    name: str
    description: str | None = None
    signal_strength: str | None = None
    sort_order: int
    is_active: bool

    model_config = {"from_attributes": True}


class TagUpdate(BaseModel):
    emoji: str | None = None
    name: str | None = None
    description: str | None = None
    signal_strength: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


# --- Conversations ---


class ConversationCreate(BaseModel):
    title: str
    happened_at: datetime | None = None
    interviewer: str | None = None
    company: CompanyCreate | None = None
    contacts: list[ContactCreate] = Field(default_factory=list)
    transcript: str
    transcript_format: str | None = None
    meta: dict[str, Any] | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    happened_at: datetime | None = None
    interviewer: str | None = None
    meta: dict[str, Any] | None = None
    company_id: int | None = None


class UtteranceResponse(BaseModel):
    id: int
    idx: int
    speaker_label: str
    speaker_side: str
    text: str
    start_ms: int | None = None

    model_config = {"from_attributes": True}


class HighlightResponse(BaseModel):
    id: int
    conversation_id: int
    utterance_id: int | None = None
    tag_key: str
    quote: str
    char_start: int | None = None
    char_end: int | None = None
    note: str | None = None
    confidence: float | None = None
    origin: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalysisResponse(BaseModel):
    id: int
    conversation_id: int | None = None
    kind: str
    model: str | None = None
    prompt_version: str | None = None
    input_scope: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationListItem(BaseModel):
    id: int
    title: str
    happened_at: datetime | None = None
    status: str
    interviewer: str | None = None
    company: CompanyResponse | None = None
    contacts: list[ContactResponse] = Field(default_factory=list)
    meta: dict[str, Any] | None = None
    created_at: datetime
    tag_counts: dict[str, int] = Field(default_factory=dict)
    critique_score: int | None = None

    model_config = {"from_attributes": True}


class ConversationDetail(BaseModel):
    id: int
    title: str
    happened_at: datetime | None = None
    status: str
    source: str
    interviewer: str | None = None
    company: CompanyResponse | None = None
    contacts: list[ContactResponse] = Field(default_factory=list)
    meta: dict[str, Any] | None = None
    created_at: datetime
    utterances: list[UtteranceResponse] = Field(default_factory=list)
    highlights: list[HighlightResponse] = Field(default_factory=list)
    analyses: list[AnalysisResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    items: list[ConversationListItem]
    total: int
    limit: int
    offset: int


class ConversationCreateResponse(BaseModel):
    id: int
    title: str
    status: str
    created_at: str | None = None


class ConversationStatusResponse(BaseModel):
    id: int
    status: str


# --- Highlights ---


class HighlightCreate(BaseModel):
    utterance_id: int | None = None
    tag_key: str
    quote: str
    note: str | None = None
    confidence: float | None = None


class HighlightUpdate(BaseModel):
    status: str | None = None  # accepted, rejected
    tag_key: str | None = None
    quote: str | None = None
    note: str | None = None


class HighlightWithContext(BaseModel):
    id: int
    conversation_id: int
    utterance_id: int | None = None
    tag_key: str
    quote: str
    confidence: float | None = None
    status: str
    origin: str
    conversation_title: str
    conversation_happened_at: datetime | None = None
    company_name: str | None = None
    contact_names: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class HighlightsListResponse(BaseModel):
    items: list[HighlightWithContext]
    total: int
    limit: int
    offset: int


# --- Notes ---


class NoteResponse(BaseModel):
    id: int
    conversation_id: int
    body_md: str
    updated_by: int | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class NoteUpdate(BaseModel):
    body_md: str
    updated_at: datetime  # for optimistic concurrency


# --- Stats ---


class StatsResponse(BaseModel):
    tag_counts_by_month: dict[str, Any]
    critique_trend: list[dict[str, Any]]
    compliment_ratio_trend: list[dict[str, Any]]
    open_followups: list[dict[str, Any]]
    stale_hypotheses: int = 0  # T41: count of open hypotheses with stale evidence


# --- Syntheses ---


class SynthesisCreate(BaseModel):
    filters: dict[str, Any]


class SynthesisResponse(BaseModel):
    id: int
    kind: str
    input_scope: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    model: str | None = None
    prompt_version: str | None = None
    created_at: datetime
    status: str = "pending"
    error: str | None = None

    model_config = {"from_attributes": True}


# --- Jobs ---


class JobResponse(BaseModel):
    id: int
    kind: str
    status: str
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


# --- Hypotheses ---

VALID_STANCES = ("supports", "contradicts")


class HypothesisCreate(BaseModel):
    statement: str = Field(min_length=15)
    segment: str | None = None


class HypothesisUpdate(BaseModel):
    statement: str | None = Field(default=None, min_length=15)
    status: str | None = None
    segment: str | None = None


class HypothesisRollup(BaseModel):
    supports: dict[str, int] = Field(default_factory=lambda: {"confirmed": 0, "suggested": 0})
    contradicts: dict[str, int] = Field(default_factory=lambda: {"confirmed": 0, "suggested": 0})
    companies_supporting: int = 0
    companies_contradicting: int = 0
    last_evidence_at: datetime | None = None
    freshness: str = "stale"  # fresh|aging|stale (T41)
    newest_evidence_at: str | None = None  # ISO date of newest confirmed supporting evidence


class HypothesisListItemResponse(BaseModel):
    """List-level hypothesis response with rollup for the board."""

    id: int
    statement: str
    segment: str | None = None
    status: str
    created_by: int | None = None
    decided_at: datetime | None = None
    created_at: datetime
    rollup: HypothesisRollup = Field(default_factory=HypothesisRollup)
    verdict_hint: str | None = None

    model_config = {"from_attributes": True}


class HypothesisResponse(BaseModel):
    id: int
    statement: str
    segment: str | None = None
    status: str
    created_by: int | None = None
    decided_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class HypothesisLinkCreate(BaseModel):
    highlight_id: int
    stance: Literal["supports", "contradicts"]


class HypothesisLinkResponse(BaseModel):
    id: int
    hypothesis_id: int
    highlight_id: int
    stance: str
    confidence: float | None = None
    rationale: str | None = None
    origin: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class HypothesisLinkUpdate(BaseModel):
    status: str  # confirmed|rejected


class HypothesisEvidenceItemResponse(BaseModel):
    """Evidence link enriched with the quote and source context needed by the board."""

    link_id: int
    highlight_id: int
    quote: str
    conversation_id: int
    conversation_title: str
    utterance_id: int | None = None
    company_name: str | None = None
    contact_name: str | None = None
    confidence: float | None = None
    origin: str
    status: str
    rationale: str | None = None


class HypothesisEvidenceResponse(BaseModel):
    supports: list[HypothesisEvidenceItemResponse] = Field(default_factory=list)
    contradicts: list[HypothesisEvidenceItemResponse] = Field(default_factory=list)


class HypothesisDetailResponse(BaseModel):
    id: int
    statement: str
    segment: str | None = None
    status: str
    created_by: int | None = None
    decided_at: datetime | None = None
    created_at: datetime
    rollup: HypothesisRollup = Field(default_factory=HypothesisRollup)
    evidence: HypothesisEvidenceResponse = Field(default_factory=HypothesisEvidenceResponse)
    # Legacy flat rollup/link fields retained for API compatibility.
    supports: dict[str, int] = Field(default_factory=dict)
    contradicts: dict[str, int] = Field(default_factory=dict)
    companies_supporting: int = 0
    companies_contradicting: int = 0
    last_evidence_at: datetime | None = None
    verdict_hint: str | None = None
    links: list[HypothesisLinkResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}
