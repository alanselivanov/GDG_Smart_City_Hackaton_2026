"""Small in-process budget for endpoints that call paid or shared external APIs."""
from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import HTTPException

from app.recommend import ASTANA_TZ


class ApiLimiter:
    def __init__(self, per_minute: int, per_day: int):
        self.per_minute = max(1, per_minute)
        self.per_day = max(1, per_day)
        self._lock = asyncio.Lock()
        self._recent: dict[str, deque[float]] = defaultdict(deque)
        self._day = datetime.now(ASTANA_TZ).date()
        self._daily_count = 0

    async def charge(self, client_id: str) -> None:
        now = time.monotonic()
        local_now = datetime.now(ASTANA_TZ)
        async with self._lock:
            if local_now.date() != self._day:
                self._day, self._daily_count = local_now.date(), 0
                self._recent.clear()
            recent = self._recent[client_id]
            while recent and now - recent[0] >= 60:
                recent.popleft()
            if len(recent) >= self.per_minute:
                retry = max(1, math.ceil(60 - (now - recent[0])))
                raise HTTPException(429, "Too many API requests; retry later",
                                    headers={"Retry-After": str(retry)})
            if self._daily_count >= self.per_day:
                tomorrow = datetime.combine(self._day + timedelta(days=1), datetime.min.time(), ASTANA_TZ)
                retry = max(1, math.ceil((tomorrow - local_now).total_seconds()))
                raise HTTPException(429, "Daily external API budget reached; retry tomorrow",
                                    headers={"Retry-After": str(retry)})
            recent.append(now)
            self._daily_count += 1

    def status(self) -> dict[str, int]:
        return {"daily_used": self._daily_count, "daily_limit": self.per_day,
                "per_client_minute_limit": self.per_minute}
