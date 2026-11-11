"""The seller's own company profile (v0.5 D6).

MomBoard is open source, so the name of the company using it cannot be hard-coded. It is set
in Settings (name, aliases, email domains) and used in two places:

1. Every prompt starts with a short preamble ("The seller is X; spell it exactly"), so
   summaries stop misspelling or inventing the company name.
2. It marks which speakers are ours (used before tagging so a rep's lines never become
   customer evidence).

This module is pure and dependency-free. The profile lives in a process-wide slot that the
API/worker refresh from the database (see ``app/services/seller_profile.py``), so the LLM
clients can read it without a database session.
"""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SellerProfile:
    name: str = ""
    aliases: list[str] = field(default_factory=list)
    email_domains: list[str] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        return bool(self.name.strip())

    def names(self) -> list[str]:
        """The company's name and aliases, longest first (so matching prefers the full name)."""
        seen: dict[str, str] = {}
        for value in [self.name, *self.aliases]:
            cleaned = value.strip()
            if cleaned:
                seen.setdefault(cleaned.lower(), cleaned)
        return sorted(seen.values(), key=len, reverse=True)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "aliases": list(self.aliases), "email_domains": list(self.email_domains)}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SellerProfile":
        """Build a clean profile from untrusted input: trimmed, de-duplicated, domains lower-cased
        without a leading '@'."""
        if not isinstance(data, dict):
            return cls()

        def _clean_list(values: Any, *, domain: bool = False) -> list[str]:
            out: list[str] = []
            for raw in values if isinstance(values, list) else []:
                if not isinstance(raw, str):
                    continue
                value = raw.strip()
                if domain:
                    value = value.lstrip("@").lower()
                if value and value.lower() not in {v.lower() for v in out}:
                    out.append(value)
            return out

        name = data.get("name")
        return cls(
            name=name.strip() if isinstance(name, str) else "",
            aliases=_clean_list(data.get("aliases")),
            email_domains=_clean_list(data.get("email_domains"), domain=True),
        )


_current = SellerProfile()


def set_seller_profile(profile: SellerProfile) -> None:
    """Replace the process-wide profile (called on startup, after Settings saves, per job)."""
    global _current
    _current = profile


def get_seller_profile() -> SellerProfile:
    return _current


_MARKER = "[seller-profile]"


def seller_preamble(profile: SellerProfile | None = None) -> str:
    """The instruction placed in front of every prompt. Empty when no company is configured."""
    p = profile if profile is not None else _current
    if not p.configured:
        return ""
    names = p.names()
    others = [n for n in names if n.lower() != p.name.strip().lower()]
    alias_text = f" (also referred to as: {', '.join(others)})" if others else ""
    return (
        f"{_MARKER} The seller — the company whose team runs these conversations — is "
        f"{p.name.strip()}{alias_text}. When you mention it, spell it exactly as \"{p.name.strip()}\" "
        "and never invent or alter its name. Speakers from this company are the seller's team, "
        "not the customer."
    )


def with_seller(prompt: str, profile: SellerProfile | None = None) -> str:
    """Prepend the seller preamble to a prompt (no-op if unconfigured or already present)."""
    preamble = seller_preamble(profile)
    if not preamble or _MARKER in prompt:
        return prompt
    return f"{preamble}\n\n{prompt}"


def _domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower() if "@" in email else ""


def _email_matches(email: str, domains: list[str]) -> bool:
    host = _domain_of(email)
    return bool(host) and any(host == d or host.endswith("." + d) for d in domains)


def is_our_speaker(
    label: str, *, email: str | None = None, profile: SellerProfile | None = None
) -> bool:
    """Is this speaker part of the seller's team?

    True when the label contains the company name or an alias as a whole word, or when an
    email (given, or embedded in the label) belongs to one of the company's domains. Never
    true for an unconfigured profile — we only claim what we can show.
    """
    p = profile if profile is not None else _current
    if not p.configured:
        return False
    text = label or ""
    for name in p.names():
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", text, re.IGNORECASE):
            return True
    if p.email_domains:
        candidates = [email] if email else []
        candidates += re.findall(r"[\w.+-]+@[\w.-]+", text)
        if any(_email_matches(c, p.email_domains) for c in candidates if c):
            return True
    return False
