"""Rules a tagger's output must satisfy (v0.5 D1-D3), enforced in code.

A prompt can ask for these but cannot guarantee them, and one model upgrade can quietly change
the behaviour. These pure functions are the guarantee; the prompt is just the first line.

D1  Evidence tags apply to customer turns only. Follow-up and Commitment may sit on either side.
D2  No filler: nothing under 5 words, and no bare acknowledgements ("yes", "okay", "sounds good").
    The one exception is a Commitment that names a date, time, amount or person
    ("Yes, 2 p.m. Thursday works").
D3  One tag per quote. A second tag is allowed only from a different category and only when both
    tags are at 0.7 or above. The same sentence is never stored twice in one call.
"""

import re
from dataclasses import dataclass

# Tags that legitimately apply to either side of the conversation.
EITHER_SIDE_TAGS = frozenset({"followup", "commitment"})

MIN_WORDS = 5
SECOND_TAG_MIN_CONFIDENCE = 0.7
# A shorter quote counts as "the same sentence" as a longer one only above this many characters.
CONTAINMENT_MIN_CHARS = 12

_ACK_WORDS = frozenset(
    """yes yeah yep yup ok okay sure right alright fine good great cool sounds that thats it got
    uh um huh mm mhm hmm thanks thank you so exactly absolutely definitely correct works work
    perfect agreed i see is""".split()
)
_LEADING_ACK = frozenset("yes yeah yep yup ok okay sure right alright absolutely definitely".split())

_WEEKDAYS = r"(?:mon|tues?|wednes|thurs?|fri|satur|sun)day"
_MONTHS = (
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
)
_SPECIFICS = [
    r"(?i:\b\d{1,2}(?::\d{2})?\s?(?:a\.?m\.?|p\.?m\.?)(?!\w))",          # 2 p.m. / 2pm
    r"\b\d{1,2}:\d{2}\b",                                                # 14:30
    rf"(?i:\b{_WEEKDAYS}s?\b)",                                          # Thursday
    rf"(?i:\b{_MONTHS}\b)",                                              # March
    r"(?i:\b(?:today|tomorrow|tonight|next\s+(?:week|month|quarter|year|monday|tuesday|wednesday|thursday|friday)"
    r"|this\s+(?:week|month|quarter)|end\s+of\s+(?:the\s+)?(?:week|month|quarter|year))\b)",
    r"[$€£]\s?\d",                                                       # $5,000
    r"(?i:\b\d[\d,.]*\s?(?:k|m|usd|eur|gbp|euros?|dollars?|pounds?|%)(?!\w))",  # 20k, 5000 euros
    r"(?i:\b\d+\s+(?:people|users|seats|licen[cs]es|reps|clients|accounts|teams|brands)\b)",
    r"\b(?:with|to|and|from|introduce|intro)\s+[A-Z][a-z]+\b",           # with Sarah / to Sarah
]
_SPECIFICS_RE = [re.compile(p) for p in _SPECIFICS]


def allowed_on_side(tag_key: str, side: str) -> bool:
    """D1: may this tag be placed on a turn spoken by ``side`` ('us' | 'them' | 'unknown')?

    Unknown sides are allowed: if we cannot tell who spoke we do not throw the evidence away.
    """
    return side != "us" or tag_key in EITHER_SIDE_TAGS


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[\w€$£][\w.,:'’%-]*", text) if re.search(r"\w", w)]


def names_specifics(text: str) -> bool:
    """Does the text name a date, time, amount or person? (what makes a commitment real)"""
    return any(p.search(text) for p in _SPECIFICS_RE)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.casefold())


def is_filler(quote: str, tag_key: str) -> bool:
    """D2: should this quote be dropped as filler?"""
    words = _words(quote)
    is_commitment = tag_key == "commitment"
    specific = is_commitment and names_specifics(quote)

    if len(words) < MIN_WORDS:
        return not specific
    tokens = _tokens(quote)
    if tokens and all(t in _ACK_WORDS for t in tokens):
        return True
    # "Yeah we will do that": a commitment led by an acknowledgement, with nothing concrete.
    if is_commitment and not specific and tokens and tokens[0] in _LEADING_ACK and len(words) < 8:
        return True
    return False


def normalize_quote(text: str) -> str:
    """Case-, punctuation- and whitespace-insensitive form used to compare quotes."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.casefold())).strip()


def _same_sentence(a: str, b: str) -> bool:
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= CONTAINMENT_MIN_CHARS and short in long_


@dataclass(frozen=True)
class TagInfo:
    key: str
    origin: str = "custom"
    category: str | None = None

    @property
    def group(self) -> str:
        """The category used for D3. All core tags share one; custom tags use their category;
        an uncategorised custom tag stands alone."""
        if self.origin == "core":
            return "core"
        return self.category or f"tag:{self.key}"


@dataclass(frozen=True)
class Candidate:
    utterance_idx: int
    tag_key: str
    quote: str
    confidence: float


def _group_of(tags: dict[str, TagInfo], key: str) -> str:
    info = tags.get(key)
    return info.group if info else f"tag:{key}"


def select_highlights(
    new: list[Candidate], existing: list[Candidate], tags: dict[str, TagInfo]
) -> list[Candidate]:
    """D3: choose which new candidates to store.

    ``existing`` are highlights already stored for the call (for example ones a person accepted
    or rejected, which a retag keeps): they are never returned, but they count — a new candidate
    cannot duplicate them or become a second tag in the same category.
    """
    items: list[tuple[Candidate, bool, str]] = [
        *((c, True, normalize_quote(c.quote)) for c in existing),
        *((c, False, normalize_quote(c.quote)) for c in new),
    ]
    # Cluster candidates that are the same sentence (union-find over a small list).
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i][2] and items[j][2] and _same_sentence(items[i][2], items[j][2]):
                parent[find(j)] = find(i)

    clusters: dict[int, list[int]] = {}
    for i in range(len(items)):
        clusters.setdefault(find(i), []).append(i)

    kept: list[Candidate] = []
    for members in clusters.values():
        selected = [items[i][0] for i in members if items[i][1]]  # existing always count
        incoming = sorted((items[i][0] for i in members if not items[i][1]), key=lambda c: -c.confidence)
        for cand in incoming:
            if any(s.tag_key == cand.tag_key for s in selected):
                continue  # same tag on the same sentence
            if selected:
                different_category = all(
                    _group_of(tags, s.tag_key) != _group_of(tags, cand.tag_key) for s in selected
                )
                strong_enough = cand.confidence >= SECOND_TAG_MIN_CONFIDENCE and all(
                    s.confidence >= SECOND_TAG_MIN_CONFIDENCE for s in selected
                )
                if not (different_category and strong_enough):
                    continue
            selected.append(cand)
            kept.append(cand)
    return sorted(kept, key=lambda c: (c.utterance_idx, -c.confidence))
