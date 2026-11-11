"""Before/after tag counts around a retag pilot (v0.5 R1).

Take a snapshot before the pilot, retag, then compare: a tag that jumps or vanishes means the
new prompt or taxonomy changed behaviour and needs a look before the full run. Counts are the same
numbers Insights shows (suggested + accepted, above each tag's floor, simulated calls excluded).
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Highlight, Tag, utcnow
from app.services.app_settings import get_setting, set_setting
from app.services.confidence_floor import passes_floor

SNAPSHOT_KEY = "tag_count_snapshot"
# A change is only worth flagging when it is both large in relative terms and in absolute numbers.
MIN_ABS_CHANGE = 10


async def tag_counts(db: AsyncSession) -> dict[str, int]:
    rows = await db.execute(
        select(Highlight.tag_key, func.count(Highlight.id))
        .join(Conversation, Conversation.id == Highlight.conversation_id)
        .where(
            Highlight.status.in_(["suggested", "accepted"]),
            Conversation.source != "simulator",
            passes_floor(),
        )
        .group_by(Highlight.tag_key)
    )
    return {key: n for key, n in rows.all()}


async def save_snapshot(db: AsyncSession, label: str) -> dict[str, Any]:
    snapshot = {"label": label.strip() or "snapshot", "taken_at": utcnow().isoformat(), "counts": await tag_counts(db)}
    await set_setting(db, SNAPSHOT_KEY, snapshot)
    return snapshot


def flag_for(before: int, after: int) -> str | None:
    """'vanished' / 'jumped' / 'dropped' / 'new', or None when the change is unremarkable."""
    if before == 0 and after > 0:
        return "new"
    if before >= 5 and after == 0:
        return "vanished"
    delta = after - before
    if abs(delta) >= MIN_ABS_CHANGE:
        if after >= 2 * before:
            return "jumped"
        if after * 2 <= before:
            return "dropped"
    return None


async def compare_to_snapshot(db: AsyncSession) -> dict[str, Any]:
    snapshot = await get_setting(db, SNAPSHOT_KEY)
    if not isinstance(snapshot, dict):
        return {"snapshot": None, "rows": [], "flagged": 0}
    before = snapshot.get("counts", {}) or {}
    after = await tag_counts(db)
    names = {t.key: t.name for t in (await db.execute(select(Tag))).scalars().all()}
    rows: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        b, a = int(before.get(key, 0)), int(after.get(key, 0))
        rows.append({
            "key": key, "name": names.get(key, key), "before": b, "after": a, "delta": a - b,
            "pct": round((a - b) / b * 100) if b else None, "flag": flag_for(b, a),
        })
    rows.sort(key=lambda r: (r["flag"] is None, -abs(int(r["delta"])), str(r["key"])))
    return {
        "snapshot": {"label": snapshot.get("label"), "taken_at": snapshot.get("taken_at")},
        "rows": rows,
        "flagged": sum(1 for r in rows if r["flag"]),
    }
