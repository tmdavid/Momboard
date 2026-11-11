"""Contact emails and phone numbers must never leave in tool output, even inside quotes."""

import pytest

from app.mcp.redact import redact


@pytest.mark.parametrize("text,gone", [
    ("email me at maria.lopez+legal@acme-law.co.uk tomorrow", "maria.lopez"),
    ("Reach me: JOHN@EXAMPLE.COM.", "JOHN@EXAMPLE.COM"),
    ("call me on +34 612 345 678 please", "612 345 678"),
    ("my number is (415) 555-0132", "555-0132"),
    ("it's 0044 20 7946 0958", "7946 0958"),
    ("whatsapp 612345678", "612345678"),
])
def test_removes_emails_and_phone_numbers(text, gone):
    out = redact(text)
    assert gone not in out and "[" in out


@pytest.mark.parametrize("text", [
    "we have 7,000 clients and 40 attorneys",
    "it costs $5,000 a year, so 5000 euros",
    "the call was on 2026-11-02 at 14:30",
    "version 2.4.1 shipped in 2026",
    "about 1,234,567 rows",
    "Q3 2026 vs Q3 2025: up 12.5%",
    "pages 120-135 of 400",
])
def test_leaves_ordinary_numbers_and_dates_alone(text):
    assert redact(text) == text


def test_none_and_empty_pass_through():
    assert redact(None) is None and redact("") == ""


def test_the_surrounding_text_stays_readable():
    assert redact("write to a@b.co or call +1 202 555 0147 anytime") == "write to [email removed] or call [phone removed] anytime"
