"""Per-tag confidence floor for what the UI shows (v0.5 D4).

Every tag has a ``min_confidence`` (default 0.5). A *suggested* highlight below its tag's floor
still appears in conversation review, where a person judges it, but is left out of everything
that summarises or builds on the corpus: Library signal bars and tag filters, Explore's default
view, Insights, and hypothesis matching.

A highlight a person has accepted always passes: the human decision outranks the model's doubt.
A highlight with no recorded confidence (for example one added by hand) passes too.
"""

from sqlalchemy import ColumnElement, func, or_, select

from app.models import Highlight, Tag

DEFAULT_FLOOR = 0.5


def passes_floor() -> ColumnElement[bool]:
    """SQL condition: this highlight is accepted, has no score, or meets its tag's floor."""
    floor = (
        select(Tag.min_confidence)
        .where(Tag.key == Highlight.tag_key)
        .correlate(Highlight)
        .scalar_subquery()
    )
    return or_(
        Highlight.status == "accepted",
        Highlight.confidence.is_(None),
        Highlight.confidence >= func.coalesce(floor, DEFAULT_FLOOR),
    )
