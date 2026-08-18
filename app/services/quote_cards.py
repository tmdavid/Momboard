"""T44: Quote card export — 1600x900 PNG with themes/anonymization."""

import logging
import textwrap
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Conversation, Highlight

logger = logging.getLogger(__name__)

CARD_WIDTH = 1600
CARD_HEIGHT = 900


def _autoshrink_quote(quote: str, max_chars: int = 420) -> tuple[str, int]:
    """Auto-shrink font size for long quotes. Returns (text, font_size).

    Breakpoints:
    - <=100 chars: 48px
    - <=200 chars: 40px
    - <=300 chars: 32px
    - <=420 chars: 28px
    - >420 chars: 24px + middle-ellipsis
    """
    if len(quote) > max_chars:
        mid = max_chars // 2
        quote = quote[:mid] + " … " + quote[-(mid - 10):]
        return quote, 24

    if len(quote) <= 100:
        return quote, 48
    elif len(quote) <= 200:
        return quote, 40
    elif len(quote) <= 300:
        return quote, 32
    else:
        return quote, 28


def _wrap_text_svg(text: str, font_size: int, max_width: int = 1400) -> list[str]:
    """Wrap text into lines that fit within max_width (approximate)."""
    # Approximate chars per line based on font size (monospace-ish estimate)
    chars_per_line = max(20, int(max_width / (font_size * 0.55)))
    return textwrap.wrap(text, width=chars_per_line)


def render_quote_card_svg(
    *,
    quote: str,
    tag_emoji: str,
    tag_name: str,
    company_name: str | None = None,
    contact_name: str | None = None,
    happened_at: str | None = None,
    theme: str = "light",
    anonymize: bool = True,
) -> str:
    """Render a quote card as SVG string.

    Args:
        theme: 'light' or 'dark'
        anonymize: if True, replaces company name with generic label
    """
    # Theme colors
    if theme == "dark":
        bg_color = "#1a1a2e"
        text_color = "#e8e8e8"
        accent_color = "#6366f1"
        subtle_color = "#8888aa"
    else:
        bg_color = "#ffffff"
        text_color = "#1a1a2e"
        accent_color = "#4f46e5"
        subtle_color = "#6b7280"

    # Anonymize company name
    attribution = ""
    if company_name and not anonymize:
        attribution = company_name
        if contact_name:
            attribution += f" · {contact_name}"
    elif anonymize:
        attribution = "Customer interview"
    if happened_at:
        attribution += f" · {happened_at[:10]}"

    # Auto-shrink and wrap quote
    display_quote, font_size = _autoshrink_quote(quote)
    lines = _wrap_text_svg(display_quote, font_size)

    # Compute text block height
    line_height = font_size * 1.4
    text_block_height = len(lines) * line_height
    text_y_start = max(200, (CARD_HEIGHT - text_block_height) / 2)

    # Build SVG
    svg_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}">',
        f'  <rect width="{CARD_WIDTH}" height="{CARD_HEIGHT}" fill="{bg_color}" rx="16"/>',
        # Tag badge
        f'  <text x="80" y="100" font-family="system-ui, -apple-system, sans-serif" font-size="32" fill="{accent_color}">{tag_emoji} {tag_name}</text>',
        # Quote open mark
        f'  <text x="60" y="{text_y_start - 20}" font-family="Georgia, serif" font-size="72" fill="{accent_color}" opacity="0.3">&#8220;</text>',
    ]

    # Quote lines
    for i, line in enumerate(lines):
        y = text_y_start + i * line_height
        # Escape XML special characters
        escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        svg_lines.append(
            f'  <text x="100" y="{y}" font-family="Georgia, serif" font-size="{font_size}" fill="{text_color}">{escaped}</text>'
        )

    # Attribution line
    attribution_y = CARD_HEIGHT - 80
    escaped_attr = attribution.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    svg_lines.append(
        f'  <text x="100" y="{attribution_y}" font-family="system-ui, sans-serif" font-size="20" fill="{subtle_color}">{escaped_attr}</text>'
    )

    # MomBoard subtle mark
    svg_lines.append(
        f'  <text x="{CARD_WIDTH - 180}" y="{CARD_HEIGHT - 40}" font-family="system-ui, sans-serif" font-size="14" fill="{subtle_color}" opacity="0.5">MomBoard</text>'
    )

    svg_lines.append("</svg>")
    return "\n".join(svg_lines)


async def get_highlight_card_data(
    db: AsyncSession,
    highlight_id: int,
) -> dict[str, Any] | None:
    """Fetch all data needed to render a quote card for a highlight.

    Returns None if highlight is rejected (never beautify rejected evidence).
    """
    highlight = await db.get(Highlight, highlight_id)
    if highlight is None:
        return None

    # Rejected guard
    if highlight.status == "rejected":
        return None

    # Get conversation for context
    convo = await db.get(Conversation, highlight.conversation_id)
    company_name = None
    if convo and convo.company_id:
        company = await db.get(Company, convo.company_id)
        if company:
            company_name = company.name

    # Get tag info
    from app.models import Tag
    tag = await db.get(Tag, highlight.tag_key)

    return {
        "quote": highlight.quote,
        "tag_emoji": tag.emoji if tag else "📌",
        "tag_name": tag.name if tag else highlight.tag_key,
        "company_name": company_name,
        "happened_at": convo.happened_at.isoformat() if convo and convo.happened_at else None,
    }


def svg_to_png(svg_content: str) -> bytes:
    """Convert SVG to PNG using cairosvg.

    Always produces actual PNG bytes (never returns SVG fallback).
    Raises RuntimeError if cairosvg is not available.
    """
    try:
        import cairosvg
    except ImportError as e:
        raise RuntimeError(
            "cairosvg is required for PNG card generation. "
            "Install it with: pip install cairosvg. "
            "On Debian/Ubuntu, also install: apt-get install libcairo2-dev"
        ) from e

    png_bytes: bytes = cairosvg.svg2png(
        bytestring=svg_content.encode("utf-8"),
        output_width=CARD_WIDTH,
        output_height=CARD_HEIGHT,
    )
    # Validate PNG magic bytes
    if not png_bytes or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("cairosvg did not produce valid PNG output")
    return png_bytes
