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
    type: str = "time"  # time, reputation, money
    next_step: str = ""


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
