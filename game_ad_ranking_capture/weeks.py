"""Game days and calendar weeks: which week file a ranking belongs to and whether a day is over.

The game's server time is UTC-2, so its day starts (the reset) at 02:00 UTC: 03:00 CET, 04:00 CEST (the game does not
follow daylight saving time). The Alliance Duel runs Monday to Saturday of a calendar (ISO) week, counted by game
days. A day's numbers are preliminary until its game day has ended: a scan that started after that holds the last ones
and never has to be taken again.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import config as C

RESET = timedelta(hours=2)  # the game day's start after UTC midnight


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def game_date(moment: datetime) -> date:
    """The game day (as a date) a moment belongs to."""
    return (moment.astimezone(timezone.utc) - RESET).date()


def week_monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_id(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def day_date(monday: date, day: str) -> date:
    return monday + timedelta(days=C.DAYS.index(day))


def day_end(day: date) -> datetime:
    """When the game day of `day` ends (the next reset)."""
    return datetime.combine(day + timedelta(days=1), datetime.min.time(), timezone.utc) + RESET


def is_final(day: date, captured_at: datetime) -> bool:
    return captured_at >= day_end(day)


def is_future(day: date, moment: datetime) -> bool:
    return day > game_date(moment)
