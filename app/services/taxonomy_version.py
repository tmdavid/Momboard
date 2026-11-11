"""Which taxonomy tagged each call, and how many calls miss a tag (v0.5 D7).

Adding a tag does not retag old calls, so filtering by a new tag would silently return fewer
results than the truth. The taxonomy has a version counter: it goes up whenever a tag becomes
active, each tag remembers the version it arrived in, and each call remembers the version it
was tagged under. A call is *stale* for a tag if it was tagged before that tag existed.

Calls tagged before versioning existed (``taxonomy_version`` NULL) are judged as follows:
  * a tag added AFTER versioning began (added_in_version >= 1): every legacy call predates it;
  * an older tag (added_in_version = 0): we cannot know when it was added, so we estimate from
    the data. A legacy call whose tagging finished before the tag was first ever used by the
    tagger cannot have had it. A tag never used gives no basis for a claim, so it counts as 0.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Highlight, Tag
from app.services.app_settings import get_setting, set_setting

VERSION_KEY = "taxonomy_version"


async def get_taxonomy_version(db: AsyncSession) -> int:
    value = await get_setting(db, VERSION_KEY, 0)
    return value if isinstance(value, int) else 0


async def bump_taxonomy_version(db: AsyncSession) -> int:
    """Called when a tag becomes active. Returns the new version."""
    new = await get_taxonomy_version(db) + 1
    await set_setting(db, VERSION_KEY, new)
    return new


@dataclass(frozen=True)
class StaleCount:
    key: str
    name: str
    added_in_version: int
    total_calls: int
    stale_calls: int


def _naive(value: datetime) -> datetime:
    """SQLite returns naive datetimes; compare everything as naive UTC."""
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


async def _finished_calls(db: AsyncSession) -> list[tuple[int, int | None, datetime]]:
    rows = await db.execute(
        select(Conversation.id, Conversation.taxonomy_version, Conversation.created_at).where(
            Conversation.status == "ready", Conversation.source != "simulator"
        )
    )
    return [(i, v, _naive(c)) for i, v, c in rows.all()]


async def stale_call_counts(db: AsyncSession, tag_keys: list[str] | None = None) -> dict[str, StaleCount]:
    """For each tag, how many finished calls were tagged before it existed.

    ``tag_keys=None`` means every active tag.
    """
    query = select(Tag).where(Tag.is_active == True)  # noqa: E712
    if tag_keys is not None:
        query = select(Tag).where(Tag.key.in_(tag_keys))
    tags = list((await db.execute(query)).scalars().all())
    if not tags:
        return {}

    calls = await _finished_calls(db)

    # When did each legacy call's tagging finish (its newest AI highlight, else its creation)?
    tagged_at: dict[int, datetime] = {}
    rows = await db.execute(
        select(Highlight.conversation_id, func.max(Highlight.created_at))
        .where(Highlight.origin == "ai")
        .group_by(Highlight.conversation_id)
    )
    for conversation_id, latest in rows.all():
        if latest is not None:
            tagged_at[conversation_id] = _naive(latest)

    # When did the tagger first ever use each (legacy) tag?
    first_use: dict[str, datetime] = {}
    rows = await db.execute(
        select(Highlight.tag_key, func.min(Highlight.created_at))
        .where(Highlight.origin == "ai", Highlight.tag_key.in_([t.key for t in tags]))
        .group_by(Highlight.tag_key)
    )
    for key, first in rows.all():
        if first is not None:
            first_use[key] = _naive(first)

    out: dict[str, StaleCount] = {}
    for tag in tags:
        stale = 0
        for call_id, version, created in calls:
            if version is not None:
                stale += version < tag.added_in_version
            elif tag.added_in_version >= 1:
                stale += 1
            elif tag.key in first_use:
                stale += tagged_at.get(call_id, created) < first_use[tag.key]
        out[tag.key] = StaleCount(tag.key, tag.name, tag.added_in_version, len(calls), stale)
    return out


async def current_progress(db: AsyncSession) -> tuple[int, int, int]:
    """(taxonomy version, finished calls, calls tagged under the current version)."""
    version = await get_taxonomy_version(db)
    calls = await _finished_calls(db)
    on_current = sum(1 for _, v, _ in calls if (v or 0) >= version)
    return version, len(calls), on_current
