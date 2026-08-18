"""T44: Quote card PNG dimension/layout tests — IHDR verification, themes, truncation."""

import struct

import pytest

from app.services.quote_cards import (
    _autoshrink_quote,
    render_quote_card_svg,
    svg_to_png,
)

# ─── PNG helpers ───

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def parse_png_ihdr(data: bytes) -> tuple[int, int]:
    """Parse PNG IHDR chunk and return (width, height)."""
    assert data[:8] == PNG_MAGIC, "Not a valid PNG file"
    # IHDR chunk starts at offset 8: 4 bytes length + 4 bytes type + 13 bytes data
    # length at 8:12, type at 12:16 (should be 'IHDR'), width at 16:20, height at 20:24
    chunk_type = data[12:16]
    assert chunk_type == b"IHDR", f"Expected IHDR chunk, got {chunk_type!r}"
    width = struct.unpack(">I", data[16:20])[0]
    height = struct.unpack(">I", data[20:24])[0]
    return width, height


# ─── Tests ───


class TestPNGDimensions:
    """Verify PNG output has correct 1600x900 dimensions."""

    def test_png_magic_bytes(self):
        """PNG output starts with correct magic bytes."""
        svg = render_quote_card_svg(
            quote="Test quote", tag_emoji="💡", tag_name="Insight", theme="light"
        )
        png = svg_to_png(svg)
        assert png[:8] == PNG_MAGIC

    def test_png_ihdr_1600x900(self):
        """PNG IHDR declares exactly 1600x900."""
        svg = render_quote_card_svg(
            quote="Short test", tag_emoji="⚡", tag_name="Pain", theme="light"
        )
        png = svg_to_png(svg)
        w, h = parse_png_ihdr(png)
        assert w == 1600, f"Expected width 1600, got {w}"
        assert h == 900, f"Expected height 900, got {h}"

    def test_png_content_type(self):
        """The raw bytes are valid PNG (content-type assertion for API)."""
        svg = render_quote_card_svg(
            quote="Content type test", tag_emoji="📝", tag_name="Note", theme="light"
        )
        png = svg_to_png(svg)
        # PNG magic is the canonical way to verify image/png content type
        assert png[:8] == PNG_MAGIC
        assert len(png) > 100  # Not empty/trivial


class TestThemeVariants:
    """Light and dark theme produce different PNG outputs."""

    def test_light_theme_produces_valid_png(self):
        svg = render_quote_card_svg(
            quote="Light mode", tag_emoji="☀️", tag_name="Test", theme="light"
        )
        png = svg_to_png(svg)
        w, h = parse_png_ihdr(png)
        assert (w, h) == (1600, 900)

    def test_dark_theme_produces_valid_png(self):
        svg = render_quote_card_svg(
            quote="Dark mode", tag_emoji="🌙", tag_name="Test", theme="dark"
        )
        png = svg_to_png(svg)
        w, h = parse_png_ihdr(png)
        assert (w, h) == (1600, 900)

    def test_light_and_dark_differ(self):
        """Light and dark PNGs are different byte sequences."""
        svg_light = render_quote_card_svg(
            quote="Same quote", tag_emoji="⚡", tag_name="X", theme="light"
        )
        svg_dark = render_quote_card_svg(
            quote="Same quote", tag_emoji="⚡", tag_name="X", theme="dark"
        )
        png_light = svg_to_png(svg_light)
        png_dark = svg_to_png(svg_dark)
        assert png_light != png_dark


class TestAnonymizeDefault:
    """Anonymize=True is the default and hides company names."""

    def test_anonymize_default_hides_company_in_svg(self):
        svg = render_quote_card_svg(
            quote="Secret info", tag_emoji="🔒", tag_name="Pain",
            company_name="TopSecretCorp", anonymize=True,
        )
        assert "TopSecretCorp" not in svg
        assert "Customer interview" in svg

    def test_anonymize_false_shows_company(self):
        svg = render_quote_card_svg(
            quote="Public info", tag_emoji="🔓", tag_name="Pain",
            company_name="PublicCorp", anonymize=False,
        )
        assert "PublicCorp" in svg

    def test_anonymize_png_valid(self):
        """Both anonymize modes produce valid 1600x900 PNG."""
        for anon in (True, False):
            svg = render_quote_card_svg(
                quote="Q", tag_emoji="💡", tag_name="T",
                company_name="Corp", anonymize=anon,
            )
            png = svg_to_png(svg)
            assert parse_png_ihdr(png) == (1600, 900)


class TestRejected404:
    """Rejected highlights return 404 from the API."""

    @pytest.mark.asyncio
    async def test_rejected_highlight_returns_404(self, auth_client, sample_conversation, seeded_db):
        from app.models import Highlight
        h = Highlight(
            conversation_id=sample_conversation.id,
            tag_key="compliment",
            quote="Looks great!",
            status="rejected",
            origin="ai",
        )
        seeded_db.add(h)
        await seeded_db.commit()

        r = await auth_client.get(f"/api/highlights/{h.id}/card.png")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_nonexistent_highlight_returns_404(self, auth_client):
        r = await auth_client.get("/api/highlights/99999/card.png")
        assert r.status_code == 404


class TestLongQuoteSizing:
    """Long quotes use auto-shrink with middle-ellipsis, no clipping."""

    def test_short_quote_large_font(self):
        text, size = _autoshrink_quote("Short")
        assert size == 48

    def test_medium_quote_medium_font(self):
        text, size = _autoshrink_quote("x" * 150)
        assert size == 40

    def test_long_quote_small_font(self):
        text, size = _autoshrink_quote("x" * 250)
        assert size == 32

    def test_very_long_quote_ellipsis(self):
        original = "A" * 500
        text, size = _autoshrink_quote(original)
        assert size == 24
        assert "…" in text
        assert len(text) < len(original)

    def test_long_quote_produces_valid_png_no_clip(self):
        """Even a 500-char quote produces a valid 1600x900 PNG (no overflow/clip)."""
        long_quote = "This is a very long customer quote that goes on and on. " * 12
        svg = render_quote_card_svg(
            quote=long_quote, tag_emoji="💬", tag_name="Pain", theme="light"
        )
        png = svg_to_png(svg)
        w, h = parse_png_ihdr(png)
        assert (w, h) == (1600, 900)


class TestSVGFallbackEndpoint:
    """SVG endpoint works as fallback."""

    @pytest.mark.asyncio
    async def test_svg_endpoint_returns_svg(self, auth_client, sample_conversation, seeded_db):
        from app.models import Highlight
        h = Highlight(
            conversation_id=sample_conversation.id,
            tag_key="pain",
            quote="Manual export takes 2 hours",
            status="accepted",
            origin="ai",
        )
        seeded_db.add(h)
        await seeded_db.commit()

        r = await auth_client.get(f"/api/highlights/{h.id}/card.svg")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/svg+xml"
        assert 'width="1600"' in r.text
        assert 'height="900"' in r.text
