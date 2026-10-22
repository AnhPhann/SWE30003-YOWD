"""Worker identity, employment status and delegated availability checks."""

from dataclasses import dataclass, field
from datetime import datetime

from .availability_schedule import AvailabilitySchedule
from .common import DomainError, require_text, validate_contact, validate_window


@dataclass
class DeliveryStaff:
    staff_id: str
    name: str
    email: str
    phone: str
    active: bool = True
    schedule: AvailabilitySchedule = field(default_factory=AvailabilitySchedule)
    assignment_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.staff_id = require_text(self.staff_id, "Staff ID")
        self.name, self.email, self.phone = validate_contact(
            self.name, self.email, self.phone
        )
        if not isinstance(self.active, bool):
            raise DomainError("Employment status must be active or inactive.")
        if not isinstance(self.schedule, AvailabilitySchedule):
            raise DomainError("Each worker must have an availability schedule.")
        self.assignment_ids = list(dict.fromkeys(
            require_text(value, "Assignment ID") for value in self.assignment_ids
        ))

    def eligibility(self, start: datetime, end: datetime) -> tuple[bool, str]:
        """Assess current employment and schedule coverage, not workload overlap."""
        validate_window(start, end, allow_zero=True)
        if not self.active:
            return False, "Worker is inactive and cannot receive a new allocation."
        if not self.schedule.covers(start, end):
            return False, "Quoted window is outside the worker's availability."
        return True, "Worker is active and their schedule covers the quoted window."
