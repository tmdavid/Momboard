"""T36: Vexa meeting-bot integration API routes.

Official contract addressing: platform + native_meeting_id (not bot_id).
X-API-Key stays server-side. Errors sanitized.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth import get_current_user
from app.models import User
from app.services.vexa import SUPPORTED_PLATFORMS

router = APIRouter()


class SendBotRequest(BaseModel):
    meeting_url: str | None = None
    platform: str | None = None
    native_meeting_id: str | None = None


class StopBotRequest(BaseModel):
    platform: str = Field(min_length=1)
    native_meeting_id: str = Field(min_length=1)


class ImportTranscriptRequest(BaseModel):
    platform: str = Field(min_length=1)
    native_meeting_id: str = Field(min_length=1)
    meeting_title: str | None = None


@router.post("/bots", status_code=201)
async def send_bot(
    body: SendBotRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Send a Vexa bot to a meeting.

    Requires either meeting_url or (platform + native_meeting_id).
    Fails 503 when Vexa is not configured.
    """
    from app.services.vexa import VexaDisabledError, VexaError
    from app.services.vexa import send_bot as _send_bot

    settings = request.app.state.settings

    if not body.meeting_url and not (body.platform and body.native_meeting_id):
        raise HTTPException(
            status_code=422,
            detail="Either meeting_url or (platform + native_meeting_id) required",
        )

    # Validate platform enum if provided
    if body.platform and body.platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported platform '{body.platform}'. "
            f"Supported: {sorted(SUPPORTED_PLATFORMS)}",
        )

    try:
        result = await _send_bot(
            settings,
            meeting_url=body.meeting_url,
            platform=body.platform,
            native_meeting_id=body.native_meeting_id,
        )
        return result
    except VexaDisabledError:
        raise HTTPException(status_code=503, detail="Vexa integration is disabled")
    except VexaError as e:
        raise HTTPException(
            status_code=e.status_code or 502,
            detail="Vexa API error" if not e.detail else e.detail,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/bots/{platform}/{native_meeting_id}")
async def stop_bot(
    platform: str,
    native_meeting_id: str,
    request: Request,
    user: User = Depends(get_current_user),
):
    """Stop a Vexa bot by platform/native_meeting_id.

    Official contract: DELETE {base}/bots/{platform}/{native_meeting_id}
    """
    from app.services.vexa import VexaDisabledError, VexaError
    from app.services.vexa import stop_bot as _stop_bot

    settings = request.app.state.settings

    try:
        return await _stop_bot(
            settings, platform=platform, native_meeting_id=native_meeting_id
        )
    except VexaDisabledError:
        raise HTTPException(status_code=503, detail="Vexa integration is disabled")
    except VexaError as e:
        raise HTTPException(
            status_code=e.status_code or 502,
            detail="Vexa API error" if not e.detail else e.detail,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/transcripts/{platform}/{native_meeting_id}")
async def get_transcript(
    platform: str,
    native_meeting_id: str,
    request: Request,
    user: User = Depends(get_current_user),
):
    """Get completed transcript segments for a meeting.

    Official contract: GET {base}/transcripts/{platform}/{native_meeting_id}
    Only returns segments where completed=true.
    """
    from app.services.vexa import VexaDisabledError, VexaError
    from app.services.vexa import get_transcript as _get_transcript

    settings = request.app.state.settings

    try:
        segments = await _get_transcript(
            settings, platform=platform, native_meeting_id=native_meeting_id
        )
        return {"segments": segments, "total": len(segments)}
    except VexaDisabledError:
        raise HTTPException(status_code=503, detail="Vexa integration is disabled")
    except VexaError as e:
        raise HTTPException(
            status_code=e.status_code or 502,
            detail="Vexa API error" if not e.detail else e.detail,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/import", status_code=201)
async def import_transcript(
    body: ImportTranscriptRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Import completed transcript segments into staging inbox.

    Addresses by platform/native_meeting_id. Deduplicates — calling twice is a no-op.
    """
    from app.services.vexa import VexaDisabledError, VexaError
    from app.services.vexa import import_transcript as _import

    settings = request.app.state.settings

    # Validate platform
    if body.platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported platform '{body.platform}'. "
            f"Supported: {sorted(SUPPORTED_PLATFORMS)}",
        )

    try:
        item = await _import(
            db,
            settings,
            platform=body.platform,
            native_meeting_id=body.native_meeting_id,
            meeting_title=body.meeting_title,
        )
        await db.commit()
        if item is None:
            return {
                "status": "already_imported",
                "platform": body.platform,
                "native_meeting_id": body.native_meeting_id,
            }
        return {
            "status": "imported",
            "inbox_item_id": item.id,
            "source_ref": item.source_ref,
            "title": item.title,
        }
    except VexaDisabledError:
        raise HTTPException(status_code=503, detail="Vexa integration is disabled")
    except VexaError as e:
        raise HTTPException(
            status_code=e.status_code or 502,
            detail="Vexa API error" if not e.detail else e.detail,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
