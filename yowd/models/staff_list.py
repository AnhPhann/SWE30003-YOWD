"""Roster retaining both current and former delivery workers."""

from dataclasses import dataclass, field
from datetime import datetime

from .common import DomainError, require_text, validate_window
from .delivery_staff import DeliveryStaff


@dataclass
class StaffList:
    staff: dict[str, DeliveryStaff] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for key, worker in self.staff.items():
            if not isinstance(worker, DeliveryStaff) or key != worker.staff_id:
                raise DomainError("Roster keys must match their workers' staff IDs.")

    def register(self, worker: DeliveryStaff) -> None:
        """Register a worker without overwriting an existing or historical identity."""
        if not isinstance(worker, DeliveryStaff):
            raise DomainError("A delivery worker is required.")
        if worker.staff_id in self.staff:
            raise DomainError("That staff ID is already registered.")
        self.staff[worker.staff_id] = worker

    def get(self, staff_id: str) -> DeliveryStaff:
        staff_id = require_text(staff_id, "Staff ID")
        try:
            return self.staff[staff_id]
        except KeyError:
            raise DomainError("Delivery worker was not found.") from None

    def deactivate(self, staff_id: str) -> None:
        """Prevent new allocations while preserving the worker and existing work."""
        self.get(staff_id).active = False

    def eligible_for(self, start: datetime, end: datetime) -> list[DeliveryStaff]:
        """Ask workers to assess eligibility through their own schedules."""
        validate_window(start, end, allow_zero=True)
        return [worker for worker in self.staff.values() if worker.eligibility(start, end)[0]]
