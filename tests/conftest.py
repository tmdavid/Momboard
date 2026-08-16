"""Shared test fixtures."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.auth import create_session_token, hash_password
from app.config import Settings
from app.main import create_app
from app.models import (
    Base,
    Company,
    Contact,
    Conversation,
    ConversationContact,
    User,
    Utterance,
)
from app.seed import seed_tags

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _set_sqlite_pragmas(dbapi_conn, _rec):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create a test engine with in-memory SQLite."""
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        echo=False,
    )

    @event.listens_for(eng.sync_engine, "connect")
    def on_connect(dbapi_conn, _rec):
        _set_sqlite_pragmas(dbapi_conn, _rec)

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the test engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional test session."""
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def seeded_db(db_session: AsyncSession) -> AsyncSession:
    """Session with tags seeded."""
    await seed_tags(db_session)
    await db_session.commit()
    return db_session


def _test_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test-secret",
        openai_api_key="",
        env="test",
        worker_poll_interval=0.1,
    )


@pytest_asyncio.fixture
async def app(engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]):
    """Create a test app with worker disabled."""
    settings = _test_settings()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def test_lifespan(app):
        yield

    application = create_app(settings)
    # Override lifespan to not start worker
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.settings = settings

    # Seed tags
    async with session_factory() as session:
        await seed_tags(session)
        await session.commit()

    return application


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Unauthenticated HTTP client."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def user_david(session_factory: async_sessionmaker[AsyncSession]) -> User:
    """Create test user David (admin)."""
    async with session_factory() as session:
        user = User(
            email="d@rp.com",
            name="David",
            password_hash=hash_password("pw"),
            role="admin",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def user_member(session_factory: async_sessionmaker[AsyncSession]) -> User:
    """Create test user (member role)."""
    async with session_factory() as session:
        user = User(
            email="member@rp.com",
            name="Member",
            password_hash=hash_password("pw"),
            role="member",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def auth_client(app, user_david) -> AsyncGenerator[AsyncClient, None]:
    """Authenticated HTTP client with admin user."""
    settings = app.state.settings
    token = create_session_token(user_david.id, settings.session_secret)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session": token},
    ) as c:
        yield c


@pytest_asyncio.fixture
async def member_client(app, user_member) -> AsyncGenerator[AsyncClient, None]:
    """Authenticated HTTP client with member user."""
    settings = app.state.settings
    token = create_session_token(user_member.id, settings.session_secret)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session": token},
    ) as c:
        yield c


@pytest_asyncio.fixture
async def sample_conversation(
    session_factory: async_sessionmaker[AsyncSession], user_david: User
) -> Conversation:
    """Create a sample conversation with utterances."""
    async with session_factory() as session:
        await seed_tags(session)

        company = Company(name="Acme Watches")
        session.add(company)
        await session.flush()

        contact = Contact(name="Maria", role="Brand Manager", company_id=company.id)
        session.add(contact)
        await session.flush()

        convo = Conversation(
            title="Acme discovery call",
            company_id=company.id,
            interviewer="David",
            status="ready",
            raw_transcript="David: hi\nMaria: hello",
            transcript_format="name_colon",
        )
        session.add(convo)
        await session.flush()

        session.add(ConversationContact(conversation_id=convo.id, contact_id=contact.id))

        # Add some utterances
        for i, (speaker, side, text) in enumerate(
            [
                ("David", "us", "Hey Maria, thanks for taking the time today."),
                (
                    "Maria",
                    "them",
                    "Sure! So right now we have this spreadsheet where the team logs every infringement they find manually.",
                ),
                ("David", "us", "And when you find an infringement, what happens next?"),
                (
                    "Maria",
                    "them",
                    "Every Monday I export it to Excel and clean it by hand, takes about 2 hours.",
                ),
            ]
        ):
            session.add(
                Utterance(
                    conversation_id=convo.id,
                    idx=i,
                    speaker_label=speaker,
                    speaker_side=side,
                    text=text,
                )
            )

        await session.commit()
        await session.refresh(convo)
        return convo


def read_fixture(name: str) -> str:
    """Read a text fixture file."""
    path = FIXTURES_DIR / "transcripts" / name
    return path.read_text()


@pytest_asyncio.fixture(autouse=True)
async def _reset_sse_state():
    """Reset sse-starlette AppStatus between tests to avoid event loop binding issues."""
    yield
    try:
        from sse_starlette.sse import AppStatus

        AppStatus.should_exit_event = None
        AppStatus.should_exit = False
    except ImportError:
        pass
