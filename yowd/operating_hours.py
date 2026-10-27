"""Weekday operating hours for a small Melbourne same-day courier.

This is a team assumption for review, not a published YOWD roster. New
availability and quoted windows must fall inside one Monday-to-Friday day,
from 08:00 to 18:00, using naive Melbourne local time. Public holidays are
not excluded. Loading a previously saved schedule does not rewrite it.
"""

from datetime import date, datetime, time, timedelta

from .models.common import DomainError, validate_window


OPEN = time(8, 0)
CLOSE = time(18, 0)
SUMMARY = "Monday to Friday, 08:00 to 18:00 Melbourne local time"


def next_operating_day(moment: datetime) -> date:
    """Return the next weekday after the given local moment."""
    if not isinstance(moment, datetime):
        raise DomainError("A date and time is required.")
    day = moment.date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _require_operating_span(start: datetime, end: datetime, label: str) -> None:
    validate_window(start, end)
    if start.date() != end.date() or start.weekday() >= 5:
        raise DomainError(f"{label} must fall on one weekday. YOWD operates {SUMMARY}.")
    if start.time() < OPEN or end.time() > CLOSE:
        raise DomainError(f"{label} must sit inside operating hours, 08:00 to 18:00.")


def ensure_availability_period(start: datetime, end: datetime) -> None:
    """Reject a new availability period outside the operating calendar."""
    _require_operating_span(start, end, "An availability period")


def ensure_quoted_window(start: datetime, end: datetime) -> None:
    """Reject a pickup-to-delivery estimate outside the operating calendar."""
    _require_operating_span(start, end, "The quoted pickup and delivery window")


def within_operating_hours(start: datetime, end: datetime) -> bool:
    """Return whether a candidate quote window is inside the operating calendar."""
    try:
        ensure_quoted_window(start, end)
    except DomainError:
        return False
    return True
