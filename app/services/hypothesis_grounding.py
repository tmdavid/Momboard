"""Hypothesis grounding bands — one pure rule set, thresholds from settings.

A band tells people whether to act on a belief. It is derived at read time from
**confirmed** links only; suggested (unreviewed) links never move it.

    hunch      no confirmed links
    refuted    >= refuted_min_contradict contradicting, and more than ratio x the supporting
    contested  >= contested_min_each supporting AND >= contested_min_each contradicting
    grounded   >= grounded_min_support supporting from >= grounded_min_companies companies,
               and <= grounded_max_contradict contradicting
    candidate  anything else that has confirmed evidence (not enough yet to call it)

Order matters where rules overlap: refuted is checked before contested (a belief that
is overwhelmingly contradicted is refuted, not merely "contested"), and contested before
grounded (enough contradictions keep a well-supported belief from being grounded).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class BandThresholds:
    grounded_min_support: int = 3
    grounded_min_companies: int = 2
    grounded_max_contradict: int = 1
    contested_min_each: int = 2
    refuted_min_contradict: int = 3
    refuted_ratio: float = 2.0


@lru_cache(maxsize=1)
def get_band_thresholds() -> BandThresholds:
    """Thresholds from settings (env / .env). Cached for the process lifetime."""
    from app.config import get_settings

    s = get_settings()
    return BandThresholds(
        grounded_min_support=s.hypothesis_grounded_min_support,
        grounded_min_companies=s.hypothesis_grounded_min_companies,
        grounded_max_contradict=s.hypothesis_grounded_max_contradict,
        contested_min_each=s.hypothesis_contested_min_each,
        refuted_min_contradict=s.hypothesis_refuted_min_contradict,
        refuted_ratio=s.hypothesis_refuted_ratio,
    )


def compute_band(
    supports: Mapping[str, int],
    contradicts: Mapping[str, int],
    companies_supporting: int,
    thresholds: BandThresholds | None = None,
) -> str:
    """The grounding band for confirmed link counts. Suggested counts are ignored."""
    t = thresholds or get_band_thresholds()
    sup = supports.get("confirmed", 0)
    con = contradicts.get("confirmed", 0)

    if sup == 0 and con == 0:
        return "hunch"
    if con >= t.refuted_min_contradict and con > t.refuted_ratio * sup:
        return "refuted"
    if sup >= t.contested_min_each and con >= t.contested_min_each:
        return "contested"
    if (
        sup >= t.grounded_min_support
        and companies_supporting >= t.grounded_min_companies
        and con <= t.grounded_max_contradict
    ):
        return "grounded"
    return "candidate"


def _n(count: int, noun: str) -> str:
    if count == 1:
        return f"{count} {noun}"
    plural = f"{noun[:-1]}ies" if noun.endswith("y") else f"{noun}s"
    return f"{count} {plural}"


def explain_band(
    supports: Mapping[str, int],
    contradicts: Mapping[str, int],
    companies_supporting: int,
    companies_contradicting: int,
    thresholds: BandThresholds | None = None,
) -> str:
    """One plain sentence saying why a hypothesis sits where it does (and what is missing)."""
    t = thresholds or get_band_thresholds()
    sup = supports.get("confirmed", 0)
    con = contradicts.get("confirmed", 0)
    band = compute_band(supports, contradicts, companies_supporting, t)

    sup_part = f"{_n(sup, 'supporting quote')} from {_n(companies_supporting, 'company')}"
    con_part = f"{_n(con, 'contradicting quote')} from {_n(companies_contradicting, 'company')}"

    if band == "hunch":
        pending = supports.get("suggested", 0) + contradicts.get("suggested", 0)
        if pending:
            return (
                f"No confirmed evidence yet; {_n(pending, 'suggested quote')} awaiting review."
            )
        return "No evidence yet."
    if band == "grounded":
        return f"{sup_part}, {con} contradicting."
    if band == "contested":
        return f"{sup_part} vs {con_part}."
    if band == "refuted":
        return f"{con_part}, none supporting." if sup == 0 else f"{con_part}, only {sup} supporting."

    # candidate: say what is still missing
    if sup and con:
        return f"{sup_part} vs {con_part} — not enough on either side to call it yet."
    if con:
        return (
            f"{con_part} — Refuted needs {t.refuted_min_contradict} contradicting quotes."
        )
    return (
        f"{sup_part} — Grounded needs {t.grounded_min_support} supporting quotes "
        f"from {t.grounded_min_companies} companies."
    )


def band_rules(thresholds: BandThresholds | None = None) -> list[dict[str, str]]:
    """Human-readable rule per band, with the live numbers (for the board's explainer)."""
    t = thresholds or get_band_thresholds()
    ratio = f"{t.refuted_ratio:g}"
    return [
        {
            "band": "grounded",
            "label": "Grounded",
            "rule": (
                f"{t.grounded_min_support}+ confirmed supporting quotes from "
                f"{t.grounded_min_companies}+ companies, and at most {t.grounded_max_contradict} contradicting"
            ),
        },
        {
            "band": "contested",
            "label": "Contested",
            "rule": (
                f"{t.contested_min_each}+ confirmed supporting and "
                f"{t.contested_min_each}+ confirmed contradicting quotes"
            ),
        },
        {
            "band": "candidate",
            "label": "Candidate",
            "rule": "Some confirmed evidence, but not enough to call it (for example 1–2 quotes, or only one company)",
        },
        {
            "band": "hunch",
            "label": "Hunch",
            "rule": "No confirmed quotes yet. Suggested matches don’t count until you review them",
        },
        {
            "band": "refuted",
            "label": "Refuted",
            "rule": (
                f"{t.refuted_min_contradict}+ confirmed contradicting quotes, "
                f"more than {ratio}× the supporting ones"
            ),
        },
    ]
