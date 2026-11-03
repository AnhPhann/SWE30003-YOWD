"""Worker identity, employment status and delegated availability checks."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from .availability_schedule import AvailabilitySchedule
from .common import DomainError, require_text, validate_contact, validate_window

if TYPE_CHECKING:
    from .delivery_assignment import DeliveryAssignment
    from .delivery_request import DeliveryRequest


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

    def assignment_history(
        self, requests: Iterable["DeliveryRequest"],
    ) -> list[tuple["DeliveryRequest", "DeliveryAssignment"]]:
        """Return this worker's assignments with the request each belongs to.

        Only assignments listed in this worker's assignment IDs are
        returned, in the order they were given. Active assignments are the
        current ones; ended assignments are the history (A2 DeliveryStaff
        CRC).
        """
        found_by_id = {}
        for request in requests:
            for assignment in request.assignments:
                is_own_assignment = (
                    assignment.staff_id == self.staff_id
                    and assignment.assignment_id in self.assignment_ids
                )
                if is_own_assignment:
                    found_by_id[assignment.assignment_id] = (
                        request, assignment,
                    )
        history = []
        for assignment_id in self.assignment_ids:
            if assignment_id in found_by_id:
                history.append(found_by_id[assignment_id])
        return history

    def eligibility(self, start: datetime, end: datetime) -> tuple[bool, str]:
        """Assess current employment and schedule coverage, not workload overlap."""
        validate_window(start, end, allow_zero=True)
        if not self.active:
            return False, "Worker is inactive and cannot receive a new allocation."
        if not self.schedule.covers(start, end):
            return False, "Quoted window is outside the worker's availability."
        return True, "Worker is active and their schedule covers the quoted window."
