"""Availability periods owned by one delivery worker."""

from dataclasses import dataclass, field
from datetime import datetime

from .common import DomainError, validate_window


@dataclass
class AvailabilitySchedule:
    periods: list[tuple[datetime, datetime]] = field(default_factory=list)

    def __post_init__(self) -> None:
        validated = []
        for period in self.periods:
            if not isinstance(period, (tuple, list)) or len(period) != 2:
                raise DomainError("Each availability period needs a start and end.")
            validated.append(validate_window(*period))
        self.periods = []
        for start, end in validated:
            self.add_period(start, end)

    def add_period(self, start: datetime, end: datetime) -> None:
        """Add coverage and merge overlapping or adjacent periods."""
        validate_window(start, end)
        merged: list[tuple[datetime, datetime]] = []
        for period_start, period_end in sorted([*self.periods, (start, end)]):
            if merged and period_start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], period_end))
            else:
                merged.append((period_start, period_end))
        self.periods = merged

    def covers(self, start: datetime, end: datetime) -> bool:
        """Return whether the whole proposed window is covered."""
        validate_window(start, end, allow_zero=True)
        return any(left <= start and end <= right for left, right in self.periods)
