"""T31: Weekly digest builder — pure function + Slack delivery + self-rescheduling."""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Analysis,
    Conversation,
    DigestLog,
    Drift,
    Highlight,
    Job,
    utcnow,
)

logger = logging.getLogger(__name__)


def _next_monday_0800_utc(from_date: date) -> datetime:
    """Compute next Monday 08:00 UTC from a given date."""

    days_ahead = 7 - from_date.weekday()  # Monday is 0
    if days_ahead == 0:
        days_ahead = 7
    next_monday = from_date + timedelta(days=days_ahead)
    return datetime(next_monday.year, next_monday.month, next_monday.day, 8, 0, 0, tzinfo=UTC)


def build_digest(snapshot: dict[str, Any], week_of: date) -> str:
    """Pure function: build digest markdown from a pre-fetched snapshot.

    Sections (omitted when empty, never rendered as "0 items"):
    - New commitments
    - Overdue follow-ups (>14d)
    - Compliment ratio delta
    - Hypothesis movements
    - Stale hypotheses needing re-validation
    - Drift alerts
    - Insight of the week (LLM-generated, passed in snapshot)
    """
    lines: list[str] = []
    lines.append(f"# Weekly Digest — {week_of.isoformat()}")
    lines.append("")

    # New commitments
    commitments = snapshot.get("new_commitments", [])
    if commitments:
        lines.append("## 🤝 New Commitments")
        for c in commitments:
            task = c.get("task") or c["quote"]
            lines.append(f"- **{task[:80]}** ({c.get('company', 'unknown')})")
        lines.append("")

    # Overdue follow-ups
    overdue = snapshot.get("overdue_followups", [])
    if overdue:
        lines.append("## ☆ Overdue Follow-ups (>14 days)")
        for f in overdue:
            lines.append(f"- {f['quote'][:80]} — {f.get('age_days', '?')}d ago")
        lines.append("")

    # Compliment ratio delta
    ratio_delta = snapshot.get("compliment_ratio_delta")
    if ratio_delta is not None:
        direction = "↓" if ratio_delta < 0 else "↑"
        lines.append(f"## 🎈 Compliment Ratio: {direction} {abs(ratio_delta):.0%}")
        lines.append("")

    # Hypothesis movements
    movements = snapshot.get("hypothesis_movements", [])
    if movements:
        lines.append("## 🔬 Hypothesis Movements")
        for m in movements:
            lines.append(f"- {m['statement'][:60]}: {m['change']}")
        lines.append("")

    # Stale hypotheses
    stale = snapshot.get("stale_hypotheses", [])
    if stale:
        lines.append("## ⏰ Needs Re-validation")
        for s in stale:
            lines.append(f"- {s['statement'][:60]} (last evidence: {s.get('newest_evidence_at', 'never')})")
        lines.append("")

    # Drift alerts
    drifts = snapshot.get("new_drifts", [])
    if drifts:
        lines.append("## 🔄 Drift Alerts")
        for d in drifts:
            lines.append(f"- {d.get('summary', 'Position change detected')}")
        lines.append("")

    # Insight of the week
    insight = snapshot.get("insight_of_the_week")
    if insight:
        lines.append("## 💡 Insight of the Week")
        lines.append(insight)
        lines.append("")

    # If completely empty
    if len(lines) <= 2:
        return ""

    return "\n".join(lines)


async def gather_digest_snapshot(
    db: AsyncSession,
    week_of: date,
    *,
    llm: Any = None,
) -> dict[str, Any]:
    """Gather all data needed for the digest. Pure queries, no mutations."""
    from app.services.staleness import get_stale_hypotheses

    week_start = datetime(week_of.year, week_of.month, week_of.day) - timedelta(days=7)
    now = utcnow()

    snapshot: dict[str, Any] = {}

    # New commitments (this week)
    commits_result = await db.execute(
        select(Highlight, Conversation.title, Conversation.id)
        .join(Conversation, Conversation.id == Highlight.conversation_id)
        .where(
            Highlight.tag_key.in_(["commitment", "followup"]),
            Highlight.status.in_(["accepted", "suggested"]),
            Highlight.created_at >= week_start,
            Conversation.source != "simulator",  # T39: exclude simulated evidence
        )
        .limit(20)
    )
    commit_rows = commits_result.all()
    commit_conversation_ids = {conversation_id for _, _, conversation_id in commit_rows}
    commitment_tasks: dict[int, str] = {}
    if commit_conversation_ids:
        analyses_result = await db.execute(
            select(Analysis.result)
            .where(
                Analysis.kind == "conversation",
                Analysis.conversation_id.in_(commit_conversation_ids),
            )
            .order_by(Analysis.created_at)
        )
        for result_data in analyses_result.scalars().all():
            if not isinstance(result_data, dict):
                continue
            commitments = result_data.get("commitments", [])
            if not isinstance(commitments, list):
                continue
            for commitment in commitments:
                if not isinstance(commitment, dict):
                    continue
                task = commitment.get("next_step") or commitment.get("what")
                evidence_ids = commitment.get("evidence_highlight_ids", [])
                if not isinstance(task, str) or not task.strip() or not isinstance(evidence_ids, list):
                    continue
                for highlight_id in evidence_ids:
                    if isinstance(highlight_id, int):
                        commitment_tasks[highlight_id] = task.strip()

    snapshot["new_commitments"] = [
        {
            "quote": highlight.quote,
            "task": commitment_tasks.get(highlight.id, highlight.quote),
            "company": title,
        }
        for highlight, title, _ in commit_rows
    ]

    # Overdue follow-ups (>14 days old, still open)
    overdue_cutoff = now - timedelta(days=14)
    overdue_result = await db.execute(
        select(Highlight)
        .join(Conversation, Conversation.id == Highlight.conversation_id)
        .where(
            Highlight.tag_key == "followup",
            Highlight.status.in_(["accepted", "suggested"]),
            Highlight.created_at < overdue_cutoff,
            Conversation.source != "simulator",  # T39: exclude simulated evidence
        )
        .limit(20)
    )
    snapshot["overdue_followups"] = [
        {
            "quote": h.quote,
            "age_days": (now.replace(tzinfo=None) - h.created_at.replace(tzinfo=None)).days
            if h.created_at
            else 0,
        }
        for h in overdue_result.scalars().all()
    ]

    # Stale hypotheses
    snapshot["stale_hypotheses"] = await get_stale_hypotheses(db)

    # Drift alerts (this week)
    drifts_result = await db.execute(
        select(Drift)
        .where(
            Drift.status == "open",
            Drift.created_at >= week_start,
        )
        .limit(10)
    )
    snapshot["new_drifts"] = [
        {"summary": d.summary, "kind": d.kind}
        for d in drifts_result.scalars().all()
    ]

    # Insight of the week (LLM if available)
    if llm:
        from app.llm.schemas import DigestInsightOutput

        recent_highlights_result = await db.execute(
            select(Highlight.id, Highlight.quote, Highlight.conversation_id)
            .join(Conversation, Conversation.id == Highlight.conversation_id)
            .where(
                Highlight.status == "accepted",
                Highlight.created_at >= week_start,
                Conversation.source != "simulator",  # T39: exclude simulated evidence
            )
            .limit(20)
        )
        recent_rows = recent_highlights_result.all()
        valid_highlight_ids = {row[0] for row in recent_rows}
        highlight_to_convo = {row[0]: row[2] for row in recent_rows}
        recent_quotes = [row[1] for row in recent_rows]

        if recent_quotes:
            prompt = (
                "Given these customer evidence quotes from the past week, "
                "produce ONE sentence insight — a pattern or surprising finding. "
                "You MUST cite at least 2 highlight IDs from the list below as evidence. "
                "Return highlight_ids referencing the IDs that back your insight.\n\n"
                + "\n".join(f"- [id={row[0]}] {row[1]}" for row in recent_rows)
            )
            try:
                result = await llm.generate(
                    prompt=prompt,
                    schema=DigestInsightOutput,
                    model="digest",
                )
                # Post-LLM validation: citation-or-silence
                # Must have >=2 valid highlight IDs from >=2 distinct non-simulator conversations
                cited_ids = [
                    hid for hid in result.highlight_ids if hid in valid_highlight_ids
                ]
                cited_conversations = {
                    highlight_to_convo[hid] for hid in cited_ids if hid in highlight_to_convo
                }
                if (
                    len(cited_ids) >= 2
                    and len(cited_conversations) >= 2
                    and result.insight.strip()
                ):
                    snapshot["insight_of_the_week"] = result.insight
                else:
                    snapshot["insight_of_the_week"] = "Not enough signal this week."
            except Exception:
                logger.warning("Failed to generate digest insight")

    return snapshot


async def run_digest(
    db: AsyncSession,
    *,
    week_of: date | None = None,
    llm: Any = None,
    slack_webhook_url: str | None = None,
) -> DigestLog | None:
    """Run the weekly digest: build, store, deliver, reschedule.

    Idempotent: if a digest for this ISO week already exists, returns None.
    """
    import httpx

    if week_of is None:
        week_of = date.today()

    iso_week = week_of.strftime("%G-W%V")

    # Idempotency check
    existing = await db.execute(
        select(DigestLog).where(DigestLog.iso_week == iso_week).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info("Digest for %s already exists, skipping", iso_week)
        return None

    # Gather and build
    snapshot = await gather_digest_snapshot(db, week_of, llm=llm)
    md = build_digest(snapshot, week_of)

    if not md:
        logger.info("Digest for %s is empty, skipping", iso_week)
        return None

    # Store
    digest_entry = DigestLog(
        iso_week=iso_week,
        markdown=md,
    )
    db.add(digest_entry)
    await db.flush()

    # Deliver to Slack
    if slack_webhook_url:
        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "blocks": [
                        {"type": "section", "text": {"type": "mrkdwn", "text": md[:3000]}}
                    ]
                }
                await client.post(slack_webhook_url, json=payload, timeout=10)
                digest_entry.delivered_at = utcnow()
                await db.flush()
        except Exception:
            logger.warning("Failed to deliver digest to Slack")

    # Self-reschedule for next Monday 08:00 UTC
    next_run = _next_monday_0800_utc(week_of)
    reschedule_job = Job(
        kind="digest",
        payload={"week_of": (week_of + timedelta(days=7)).isoformat()},
        status="queued",
        run_after=next_run,
    )
    db.add(reschedule_job)
    await db.flush()

    return digest_entry
