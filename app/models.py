"""SQLAlchemy ORM models."""

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    """Base class for all models."""

    type_annotation_map = {
        dict: JSON().with_variant(JSONB, "postgresql"),
    }


def utcnow() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(UTC)


# --- Companies ---


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    contacts: Mapped[list["Contact"]] = relationship(back_populates="company")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="company")


# --- Contacts ---


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("companies.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    company: Mapped[Optional["Company"]] = relationship(back_populates="contacts")
    conversations: Mapped[list["Conversation"]] = relationship(
        secondary="conversation_contacts", back_populates="contacts"
    )


# --- Conversations ---


class ConversationContact(Base):
    __tablename__ = "conversation_contacts"

    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    contact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("companies.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    happened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[str] = mapped_column(String(50), default="upload")
    interviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    meta: Mapped[dict | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="processing")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    company: Mapped[Optional["Company"]] = relationship(back_populates="conversations")
    contacts: Mapped[list["Contact"]] = relationship(
        secondary="conversation_contacts", back_populates="conversations"
    )
    utterances: Mapped[list["Utterance"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    highlights: Mapped[list["Highlight"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    note: Mapped[Optional["Note"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", uselist=False
    )
    jobs: Mapped[list["Job"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_conversations_happened_at", "happened_at"),)


# --- Utterances ---


class Utterance(Base):
    __tablename__ = "utterances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker_label: Mapped[str] = mapped_column(String(255), nullable=False)
    speaker_side: Mapped[str] = mapped_column(String(20), default="unknown")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="utterances")

    __table_args__ = (
        Index("ix_utterances_conversation_idx", "conversation_id", "idx"),
    )


# --- Tags ---


class Tag(Base):
    __tablename__ = "tags"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    emoji: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal_strength: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# --- Highlights ---


class Highlight(Base):
    __tablename__ = "highlights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    utterance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("utterances.id", ondelete="SET NULL"), nullable=True
    )
    tag_key: Mapped[str] = mapped_column(
        String(50), ForeignKey("tags.key", ondelete="RESTRICT"), nullable=False
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    origin: Mapped[str] = mapped_column(String(20), default="ai")
    status: Mapped[str] = mapped_column(String(20), default="suggested")
    provenance: Mapped[dict | None] = mapped_column(nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="highlights")
    utterance: Mapped[Optional["Utterance"]] = relationship()
    tag: Mapped["Tag"] = relationship()
    hypothesis_links: Mapped[list["HypothesisLink"]] = relationship(
        back_populates="highlight", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_highlights_tag_status", "tag_key", "status"),)


# --- Analyses ---


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_scope: Mapped[dict | None] = mapped_column(nullable=True)
    result: Mapped[dict | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Optional["Conversation"]] = relationship(back_populates="analyses")


# --- Notes ---


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    body_md: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="note")


# --- Users ---


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --- Jobs ---


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    conversation: Mapped[Optional["Conversation"]] = relationship(back_populates="jobs")


# --- Hypotheses ---


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    segment: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")  # open|supported|refuted|parked
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    links: Mapped[list["HypothesisLink"]] = relationship(
        back_populates="hypothesis", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_hypotheses_status", "status"),)


class HypothesisLink(Base):
    __tablename__ = "hypothesis_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hypothesis_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hypotheses.id", ondelete="CASCADE"), nullable=False
    )
    highlight_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("highlights.id", ondelete="CASCADE"), nullable=False
    )
    stance: Mapped[str] = mapped_column(String(20), nullable=False)  # supports|contradicts
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str] = mapped_column(String(20), default="ai", server_default="ai")  # ai|human
    status: Mapped[str] = mapped_column(String(20), default="suggested", server_default="suggested")  # suggested|confirmed|rejected
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    hypothesis: Mapped["Hypothesis"] = relationship(back_populates="links")
    highlight: Mapped["Highlight"] = relationship(back_populates="hypothesis_links")

    __table_args__ = (
        Index("ix_hypothesis_links_hypothesis_id", "hypothesis_id"),
        Index("ix_hypothesis_links_highlight_id", "highlight_id"),
        CheckConstraint(
            "stance IN ('supports', 'contradicts')",
            name="ck_hypothesis_links_stance",
        ),
    )


# --- Staging Inbox (T34) ---


class StagingInboxItem(Base):
    __tablename__ = "staging_inbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # gmeet|drive|mcp|whisper
    source_ref: Mapped[str] = mapped_column(String(500), nullable=False)  # dedupe key
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    meta: Mapped[dict | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending_import", server_default="pending_import"
    )  # pending_import|imported|ignored|parse_error
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    imported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    conversation: Mapped[Optional["Conversation"]] = relationship()

    __table_args__ = (
        Index("ix_staging_inbox_source_ref", "source_ref", unique=True),
        Index("ix_staging_inbox_status", "status"),
    )


# --- Drifts (T29) ---


class Drift(Base):
    __tablename__ = "drifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    earlier_highlight_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("highlights.id", ondelete="CASCADE"), nullable=False
    )
    later_highlight_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("highlights.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(
        String(20), default="change"
    )  # contradiction|change
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="open"
    )  # open|dismissed|confirmed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    contact: Mapped["Contact"] = relationship()
    earlier_highlight: Mapped["Highlight"] = relationship(foreign_keys=[earlier_highlight_id])
    later_highlight: Mapped["Highlight"] = relationship(foreign_keys=[later_highlight_id])

    __table_args__ = (
        Index("ix_drifts_contact_id", "contact_id"),
        CheckConstraint(
            "kind IN ('contradiction', 'change')",
            name="ck_drifts_kind",
        ),
        CheckConstraint(
            "status IN ('open', 'dismissed', 'confirmed')",
            name="ck_drifts_status",
        ),
    )


# --- Chats (T42) ---


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    turns: Mapped[dict] = mapped_column(nullable=False)  # JSON array of turn objects
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship()

    __table_args__ = (Index("ix_chats_user_id", "user_id"),)


# --- Digest Log (T31) ---


class DigestLog(Base):
    __tablename__ = "digest_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    iso_week: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --- Decisions (T40) ---


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    rationale_md: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="proposed", server_default="proposed"
    )  # proposed|decided|superseded
    integrity: Mapped[str] = mapped_column(
        String(20), default="ok", server_default="ok"
    )  # ok|undermined
    integrity_reasons: Mapped[dict | None] = mapped_column(nullable=True)  # JSON list of reason objects
    hypothesis_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hypotheses.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    superseded_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("decisions.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    evidence: Mapped[list["DecisionEvidence"]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'decided', 'superseded')",
            name="ck_decisions_status",
        ),
        CheckConstraint(
            "integrity IN ('ok', 'undermined')",
            name="ck_decisions_integrity",
        ),
    )


class DecisionEvidence(Base):
    __tablename__ = "decision_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("decisions.id", ondelete="CASCADE"), nullable=False
    )
    highlight_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("highlights.id", ondelete="RESTRICT"), nullable=False
    )

    decision: Mapped["Decision"] = relationship(back_populates="evidence")
    highlight: Mapped["Highlight"] = relationship()

    __table_args__ = (
        Index("ix_decision_evidence_decision_id", "decision_id"),
        Index("ix_decision_evidence_highlight_id", "highlight_id"),
    )
