"""Pydantic schemas for LLM structured outputs.

Each schema mirrors the JSON Schema sent to the OpenAI Responses API
with strict: true. They also validate the responses we get back.
"""


from typing import Literal

from pydantic import BaseModel, Field

# --- Normalizer Output ---


class NormalizerParticipant(BaseModel):
    name: str
    role: str | None = None


class NormalizerUtterance(BaseModel):
    idx: int
    speaker_label: str
    speaker_side: str  # "us" | "them" | "unknown"
    text: str


class NormalizerOutput(BaseModel):
    utterances: list[NormalizerUtterance]
    detected_participants: list[NormalizerParticipant] = Field(default_factory=list)
    language: str = "en"


# --- Tagger Output ---


class TaggerHighlight(BaseModel):
    utterance_idx: int
    tag_key: str
    quote: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


class TaggerOutput(BaseModel):
    highlights: list[TaggerHighlight]


# --- Analyst Output ---


class PainEvidence(BaseModel):
    pain: str
    evidence_highlight_ids: list[int] = Field(default_factory=list)
    severity: str = "medium"  # low, medium, high


class CommitmentDetail(BaseModel):
    what: str
    actor: str = ""  # who gives up something (specific person/role)
    cost: str = ""  # concrete cost/commitment (time, money, reputation)
    type: str = "time"  # time, reputation, money
    next_step: str = ""
    evidence_highlight_ids: list[int] = Field(default_factory=list)


class MomTestViolation(BaseModel):
    utterance_idx: int
    type: str  # pitched_the_idea, hypothetical_question, fished_for_compliment
    better: str = ""


class MomTestCritique(BaseModel):
    score: int = Field(ge=0, le=10)
    good_questions: list[str] = Field(default_factory=list)
    violations: list[MomTestViolation] = Field(default_factory=list)


class AnalystOutput(BaseModel):
    summary: str
    top_pains: list[PainEvidence] = Field(default_factory=list)
    commitments: list[CommitmentDetail] = Field(default_factory=list)
    compliment_ratio: float = Field(ge=0.0, le=1.0, default=0.0)
    mom_test_critique: MomTestCritique
    suggested_followups: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


# --- Synthesizer Output ---


class SynthesisTheme(BaseModel):
    name: str
    summary: str
    evidence_highlight_ids: list[int] = Field(default_factory=list)
    strength: str = "medium"


class SynthesisContradiction(BaseModel):
    description: str
    side_a_ids: list[int] = Field(default_factory=list)
    side_b_ids: list[int] = Field(default_factory=list)


class SynthesizerOutput(BaseModel):
    themes: list[SynthesisTheme] = Field(default_factory=list)
    contradictions: list[SynthesisContradiction] = Field(default_factory=list)
    validate_next: list[str] = Field(default_factory=list)


# --- Hypothesis Linker Output ---


class LinkerLink(BaseModel):
    hypothesis_id: int
    highlight_id: int
    stance: Literal["supports", "contradicts"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


class LinkerOutput(BaseModel):
    links: list[LinkerLink] = Field(default_factory=list)


# --- T29: Drift Detection Output ---


class DriftItem(BaseModel):
    earlier_highlight_id: int
    later_highlight_id: int
    kind: str = "change"  # contradiction | change
    summary: str = ""


class DriftOutput(BaseModel):
    drifts: list[DriftItem] = Field(default_factory=list)


# --- T38: Pre-call Brief Output ---


class BriefFact(BaseModel):
    fact: str
    evidence_highlight_ids: list[int] = Field(default_factory=list)


class BriefOutput(BaseModel):
    known_facts: list[BriefFact] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list, max_length=3)
    watch_out: str | None = None


# --- T42: Corpus Chat Output ---


class ChatClaim(BaseModel):
    text: str
    evidence_highlight_ids: list[int] = Field(default_factory=list)


class CorpusChatOutput(BaseModel):
    claims: list[ChatClaim] = Field(default_factory=list)
    gap: bool = False
    suggested_interview_question: str | None = None


# --- T31: Digest Insight Output ---


class DigestInsightOutput(BaseModel):
    insight: str = ""
    highlight_ids: list[int] = Field(default_factory=list)


# --- T39: Interview Flight Simulator ---


class PersonaTrait(BaseModel):
    trait: str
    evidence_highlight_ids: list[int] = Field(default_factory=list)


class PersonaOutput(BaseModel):
    name: str = "Customer"
    role: str = ""
    company_profile: str = ""
    traits: list[PersonaTrait] = Field(default_factory=list)
    sore_points: list[str] = Field(default_factory=list)
    vocabulary_hints: list[str] = Field(default_factory=list)


class SimulatorReplyOutput(BaseModel):
    reply: str = ""


# --- T40: Decision Integrity Check ---


class IntegrityReason(BaseModel):
    reason: str
    source_type: str = ""  # drift|contradiction|new_evidence
    source_id: int | None = None


class IntegrityCheckOutput(BaseModel):
    undermined: bool = False
    reasons: list[IntegrityReason] = Field(default_factory=list)


# --- T43: Segment Lenses ---


class LensTheme(BaseModel):
    name: str
    summary: str
    side: str = "both"  # a|b|both|contradiction
    evidence_highlight_ids: list[int] = Field(default_factory=list)


class LensOutput(BaseModel):
    themes_a: list[LensTheme] = Field(default_factory=list)
    themes_b: list[LensTheme] = Field(default_factory=list)
    themes_shared: list[LensTheme] = Field(default_factory=list)
    contradictions: list[LensTheme] = Field(default_factory=list)
