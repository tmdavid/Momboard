"""A per-token sliding-window rate limit for tool calls (in memory; MomBoard runs as one process)."""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def _trim(self, key: int, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        return hits

    def try_consume(self, key: int, count: int = 1) -> int | None:
        """Take ``count`` calls from the budget. ``None`` means allowed; otherwise the seconds to wait.

        A request that does not fit takes nothing, so a rejected batch does not eat the budget.
        """
        if count <= 0:
            return None
        now = self._clock()
        hits = self._trim(key, now)
        if len(hits) + count > self.limit:
            if count > self.limit or not hits:
                return max(1, math.ceil(self.window))
            # Wait until enough of the oldest calls have aged out.
            needed = len(hits) + count - self.limit
            oldest = list(hits)[needed - 1]
            return max(1, min(math.ceil(self.window), math.ceil(self.window - (now - oldest))))
        hits.extend([now] * count)
        return None
