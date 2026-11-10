"""Seed data for the MomBoard taxonomy and initial setup."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tag

TAXONOMY = [
    {
        "key": "pain",
        "emoji": "⚡",
        "name": "Pain / problem",
        "description": "A problem the customer actually has",
        "signal_strength": "strong",
        "sort_order": 1,
    },
    {
        "key": "obstacle",
        "emoji": "🧱",
        "name": "Obstacle",
        "description": "Something blocking them from solving it",
        "signal_strength": "strong",
        "sort_order": 2,
    },
    {
        "key": "workaround",
        "emoji": "➡️",
        "name": "Workaround",
        "description": "What they already do to cope (past behavior!)",
        "signal_strength": "very strong",
        "sort_order": 3,
    },
    {
        "key": "emotion_pos",
        "emoji": "😄",
        "name": "Excitement",
        "description": "Genuine excitement / strong positive emotion",
        "signal_strength": "strong",
        "sort_order": 4,
    },
    {
        "key": "emotion_neg",
        "emoji": "😠",
        "name": "Anger / embarrassment",
        "description": "Strong negative emotion",
        "signal_strength": "strong",
        "sort_order": 5,
    },
    {
        "key": "context",
        "emoji": "🎯",
        "name": "Background / context",
        "description": "Facts about their world, team, process",
        "signal_strength": "medium",
        "sort_order": 6,
    },
    {
        "key": "feature_request",
        "emoji": "☐",
        "name": "Feature request / buying criteria",
        "description": "What they say they want — treat skeptically",
        "signal_strength": "weak",
        "sort_order": 7,
    },
    {
        "key": "money",
        "emoji": "💰",
        "name": "Money / budget",
        "description": "Budget, willingness to pay, buying process",
        "signal_strength": "strong",
        "sort_order": 8,
    },
    {
        "key": "person",
        "emoji": "👤",
        "name": "Intro / person",
        "description": "A specific person or company to talk to next",
        "signal_strength": "medium",
        "sort_order": 9,
    },
    {
        "key": "followup",
        "emoji": "☆",
        "name": "Follow-up task",
        "description": "Something we must do next",
        "signal_strength": "n/a",
        "sort_order": 10,
    },
    {
        "key": "commitment",
        "emoji": "🤝",
        "name": "Commitment",
        "description": "Gave up time, reputation, or money (advancement)",
        "signal_strength": "very strong",
        "sort_order": 11,
    },
    {
        "key": "compliment",
        "emoji": "🎈",
        "name": "Compliment / fluff",
        "description": '"Sounds great, I\'d totally use it" — zero signal',
        "signal_strength": "anti-signal",
        "sort_order": 12,
    },
]


async def seed_tags(session: AsyncSession) -> None:
    """Upsert all taxonomy tags. Idempotent.

    All shipped taxonomy tags are marked origin="core" (they have no category).
    This both stamps new installs and re-stamps any pre-007 rows back to core on
    the next seed run, so the core/custom split is self-healing.
    """
    for tag_data in TAXONOMY:
        data = {**tag_data, "origin": "core", "category": None}
        existing = await session.get(Tag, data["key"])
        if existing is None:
            session.add(Tag(**data))
        else:
            for k, v in data.items():
                if k != "key":
                    setattr(existing, k, v)
    await session.flush()


async def run_seed(session: AsyncSession) -> None:
    """Run all seed operations."""
    await seed_tags(session)


if __name__ == "__main__":
    import asyncio

    from app.config import get_settings
    from app.db import create_engine, create_session_factory

    async def main() -> None:
        settings = get_settings()
        engine = create_engine(settings)
        factory = create_session_factory(engine)
        async with factory() as session:
            await run_seed(session)
            await session.commit()
        await engine.dispose()
        print("Seed complete.")

    asyncio.run(main())
