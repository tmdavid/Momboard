"""Small helpers for building safe text filters."""


def like_contains(text: str) -> str:
    """A ``LIKE`` pattern matching ``text`` literally anywhere (use with ``escape="\\\\"``)."""
    needle = text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{needle}%"
