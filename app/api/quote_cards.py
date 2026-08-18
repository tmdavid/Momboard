"""T44: Quote card export API."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.quote_cards import (
    get_highlight_card_data,
    render_quote_card_svg,
    svg_to_png,
)

router = APIRouter()


@router.get("/{highlight_id}/card.png")
async def get_quote_card_png(
    highlight_id: int,
    theme: str = Query("light", regex="^(light|dark)$"),
    anonymize: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """Export a highlight as a 1600x900 PNG quote card."""
    data = await get_highlight_card_data(db, highlight_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Highlight not found or rejected")

    svg = render_quote_card_svg(
        quote=data["quote"],
        tag_emoji=data["tag_emoji"],
        tag_name=data["tag_name"],
        company_name=data.get("company_name"),
        happened_at=data.get("happened_at"),
        theme=theme,
        anonymize=anonymize,
    )

    png_bytes = svg_to_png(svg)
    return Response(content=png_bytes, media_type="image/png")


@router.get("/{highlight_id}/card.svg")
async def get_quote_card_svg(
    highlight_id: int,
    theme: str = Query("light", regex="^(light|dark)$"),
    anonymize: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """Export a highlight as SVG (fallback if cairosvg is unavailable)."""
    data = await get_highlight_card_data(db, highlight_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Highlight not found or rejected")

    svg = render_quote_card_svg(
        quote=data["quote"],
        tag_emoji=data["tag_emoji"],
        tag_name=data["tag_name"],
        company_name=data.get("company_name"),
        happened_at=data.get("happened_at"),
        theme=theme,
        anonymize=anonymize,
    )

    return Response(content=svg, media_type="image/svg+xml")
