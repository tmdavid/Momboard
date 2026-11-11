"""Pure helpers behind the MCP tools: deep links, paging and audit summaries."""

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from app.mcp import audit, paging, urls

BASE = "https://momboard.example.com"


class TestUrls:
    def test_deep_links(self):
        assert urls.conversation(BASE, 12) == "https://momboard.example.com/conversations/12"
        assert urls.quote(BASE, 12, 345) == "https://momboard.example.com/conversations/12?highlight=345"
        assert urls.hypothesis(BASE, 7) == "https://momboard.example.com/hypotheses?hypothesis=7"
        assert urls.decision(BASE, 3) == "https://momboard.example.com/decisions?decision=3"
        assert urls.summary(BASE, 9) == "https://momboard.example.com/summaries?summary=9"

    def test_a_trailing_slash_on_the_base_is_harmless(self):
        assert urls.conversation(BASE + "/", 1) == "https://momboard.example.com/conversations/1"

    def test_base_url_prefers_the_setting_then_forwarded_headers_then_the_host(self):
        scope = {"scheme": "http", "headers": [(b"host", b"10.0.0.5:8080")]}
        assert urls.base_url("https://pub.example.com/", scope) == "https://pub.example.com"
        assert urls.base_url("", scope) == "http://10.0.0.5:8080"
        fwd = {"scheme": "http", "headers": [(b"host", b"internal"), (b"x-forwarded-proto", b"https"),
                                             (b"x-forwarded-host", b"momboard.example.com")]}
        assert urls.base_url("", fwd) == "https://momboard.example.com"

    def test_forwarded_headers_cannot_inject_markup_or_other_schemes(self):
        evil = {"scheme": "http", "headers": [(b"host", b"internal"), (b"x-forwarded-proto", b"javascript"),
                                              (b"x-forwarded-host", b"a.com/<script>")]}
        assert urls.base_url("", evil) == "http://internal"


class TestPaging:
    def test_defaults_and_bounds(self):
        assert paging.page(None, None) == (20, 0)
        assert paging.page(50, None) == (50, 0)
        for bad in (0, -1, 51, 1000):
            with pytest.raises(ToolError, match="between 1 and 50"):
                paging.page(bad, None)

    def test_cursors_round_trip_and_are_opaque(self):
        c = paging.encode_cursor(40)
        assert isinstance(c, str) and "40" not in c
        assert paging.page(10, c) == (10, 40)

    @pytest.mark.parametrize("bad", ["garbage", "!!!", "", "bm9wZQ", paging.encode_cursor(0)[:-2]])
    def test_a_bad_cursor_is_a_fixable_error(self, bad):
        with pytest.raises(ToolError, match="cursor"):
            paging.page(10, bad if bad != "" else "   ")

    def test_next_cursor_only_when_there_is_more(self):
        assert paging.next_cursor(offset=0, limit=20, total=21) == paging.encode_cursor(20)
        assert paging.next_cursor(offset=20, limit=20, total=40) is None
        assert paging.next_cursor(offset=0, limit=20, total=0) is None

    def test_envelope(self):
        out = paging.envelope([1, 2], offset=0, limit=2, total=5)
        assert out == {"items": [1, 2], "total": 5, "next_cursor": paging.encode_cursor(2)}


class TestAuditSummary:
    def test_names_and_short_values_only(self):
        s = audit.summarize_args({"query": "pricing", "limit": 20, "tags": ["pain", "money"], "company": None})
        assert "query=pricing" in s and "limit=20" in s and "tags=" in s and "company" not in s

    def test_long_text_is_cut_so_transcripts_never_land_in_the_log(self):
        long = "We spent three hours every Monday reconciling the export by hand. " * 20
        s = audit.summarize_args({"query": long})
        assert len(s) <= 120 and s.endswith("…") or len(s) <= 120
        assert long[:200] not in s

    def test_lists_are_capped_and_secrets_are_masked(self):
        s = audit.summarize_args({"tags": [f"t{i}" for i in range(50)], "token": "mb_secretsecretsecret"})
        assert "mb_secret" not in s and "t49" not in s
        assert audit.summarize_args({}) == ""

    def test_newlines_cannot_forge_log_lines(self):
        assert "\n" not in audit.summarize_args({"query": "a\nstatus=ok\r\nb"})
