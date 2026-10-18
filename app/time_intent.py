"""Conservative local-time interpretation for planned visits in Astana."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


ASTANA_TZ = ZoneInfo("Asia/Almaty")
_CLOCK = re.compile(
    r"(?iu)\b(?:в|к|около|at)\s*(\d{1,2})(?:[:.](\d{2}))?\s*"
    r"(утра|утром|дня|днём|днем|вечера|вечером|ночи|ночью|am|pm)?\b"
)
_PERIOD = re.compile(r"(?iu)\b(утром|днём|днем|вечером|ночью|in the morning|"
                     r"in the afternoon|in the evening|at night)\b")


def infer_start(query: str, now: datetime) -> tuple[datetime, str] | None:
    """Return local planned start and interpretation, or None for no unambiguous cue."""
    lowered = query.casefold()
    local_now = now.astimezone(ASTANA_TZ)
    explicit_today = bool(re.search(r"(?iu)\b(сегодня|today)\b", lowered))
    explicit_tomorrow = bool(re.search(r"(?iu)\b(завтра|tomorrow)\b", lowered))
    if explicit_today and explicit_tomorrow:
        raise ValueError("Conflicting dates in query")
    match = _CLOCK.search(lowered)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        period = match.group(3)
        if hour > 23 or minute > 59:
            raise ValueError("Invalid time in query")
        if period in {"утра", "утром", "am"}:
            if not 1 <= hour <= 12:
                raise ValueError("Invalid morning time in query")
            hour %= 12
        elif period in {"дня", "днём", "днем", "вечера", "вечером", "pm"}:
            if not 1 <= hour <= 12:
                raise ValueError("Invalid afternoon/evening time in query")
            hour = hour % 12 + 12
        elif period in {"ночи", "ночью"}:
            if not 1 <= hour <= 12:
                raise ValueError("Invalid night time in query")
            hour = hour % 12 if hour <= 6 or hour == 12 else hour + 12
        elif match.group(2) is None:
            # A bare "в 9" has no reliable AM/PM interpretation.
            match = None
        if match:
            label = match.group(0).strip()
    if not match:
        period_match = _PERIOD.search(lowered)
        if not period_match:
            return None
        label = period_match.group(0)
        hour = {"утром": 9, "днём": 14, "днем": 14, "вечером": 19,
                "ночью": 23, "in the morning": 9, "in the afternoon": 14,
                "in the evening": 19, "at night": 23}[label]
        minute = 0
    date = local_now.date() + timedelta(days=1 if explicit_tomorrow else 0)
    start = datetime(date.year, date.month, date.day, hour, minute, tzinfo=ASTANA_TZ)
    if not explicit_today and not explicit_tomorrow and start < local_now - timedelta(minutes=5):
        start += timedelta(days=1)
    return start, label
