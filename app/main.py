"""FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.db import create_engine, create_session_factory


async def _seed_recurring_jobs(
    session_factory: Any, settings: Settings
) -> None:
    """Seed initial recurring jobs (gmeet_poll, digest) if none queued."""
    from sqlalchemy import select

    from app.models import Job

    async with session_factory() as db:
        # Seed gmeet_poll if configured and no queued job exists
        if getattr(settings, "gdrive_folder_id", ""):
            existing = await db.execute(
                select(Job.id).where(Job.kind == "gmeet_poll", Job.status == "queued").limit(1)
            )
            if existing.scalar_one_or_none() is None:
                db.add(Job(kind="gmeet_poll", payload={}, status="queued"))

        # Seed digest if no queued digest job exists
        existing_digest = await db.execute(
            select(Job.id).where(Job.kind == "digest", Job.status == "queued").limit(1)
        )
        if existing_digest.scalar_one_or_none() is None:
            from datetime import date, timedelta

            from app.services.digest import _next_monday_0800_utc

            today = date.today()
            next_run = _next_monday_0800_utc(today)
            # Target next Monday's ISO week
            next_week_of = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
            db.add(Job(
                kind="digest",
                payload={"week_of": next_week_of.isoformat()},
                status="queued",
                run_after=next_run,
            ))

        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """App lifespan: start worker + backup scheduler, dispose engine on shutdown."""
    import asyncio

    from app.worker import worker_loop

    settings: Settings = app.state.settings
    engine = app.state.engine

    # Start background worker
    task = asyncio.create_task(worker_loop(app.state.session_factory, settings))
    app.state.worker_task = task

    # Seed initial recurring jobs if not already queued
    await _seed_recurring_jobs(app.state.session_factory, settings)

    # Start backup scheduler if /data exists (production)
    backup_task = None
    if Path("/data").exists() and settings.env != "test":
        from app.backup import backup_scheduler

        backup_task = asyncio.create_task(backup_scheduler(settings))
        app.state.backup_task = backup_task

    yield

    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    if backup_task is not None:
        backup_task.cancel()
        try:
            await backup_task
        except asyncio.CancelledError:
            pass

    await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI app."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
    )

    # Store settings and DB on app state
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory

    # Health check
    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "version": settings.version}

    # Register API routes
    from app.api.router import api_router

    app.include_router(api_router, prefix="/api")

    # Auth routes (no /api prefix)
    from app.api.auth import auth_router

    app.include_router(auth_router)

    # Serve SPA static files if built
    spa_path = Path(__file__).parent.parent / "web" / "dist"
    if spa_path.exists():
        # Mount static assets (JS, CSS, images) — this handles /assets/* files
        assets_path = spa_path / "assets"
        if assets_path.exists():
            app.mount(
                "/assets", StaticFiles(directory=str(assets_path)), name="spa-assets"
            )

        # SPA fallback: serve index.html for any route not handled by API/auth/docs
        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(request: Request, full_path: str) -> Response:
            """Serve SPA index.html for client-side routes.

            This is reached only for paths NOT matched by /api, /auth, /healthz,
            /docs, /openapi.json, or /assets.
            """
            # Check if the path maps to a real file in dist (e.g., favicon.ico)
            file_path = spa_path / full_path
            if full_path and file_path.is_file():
                return FileResponse(str(file_path))
            # Otherwise serve the SPA shell
            return FileResponse(str(spa_path / "index.html"))

    return app
