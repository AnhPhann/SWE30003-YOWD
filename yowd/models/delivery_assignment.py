"""A retained allocation linking a request to its reporting worker."""

from dataclasses import dataclass
from datetime import datetime

from .common import DomainError, local_datetime, require_text


@dataclass
class DeliveryAssignment:
    assignment_id: str
    request_id: str
    staff_id: str
    started_at: datetime
    ended_at: datetime | None = None
    outcome: str = ""
    outcome_details: str = ""

    def __post_init__(self) -> None:
        self.assignment_id = require_text(self.assignment_id, "Assignment ID")
        self.request_id = require_text(self.request_id, "Request ID")
        self.staff_id = require_text(self.staff_id, "Staff ID")
        local_datetime(self.started_at, "Allocation time")
        if not isinstance(self.outcome_details, str):
            raise DomainError("Assignment outcome details must be text.")
        self.outcome_details = self.outcome_details.strip()
        if self.ended_at is not None:
            local_datetime(self.ended_at, "Assignment end")
            if self.ended_at < self.started_at:
                raise DomainError("Assignment cannot end before it starts.")
            self.outcome = require_text(self.outcome, "Assignment outcome")
        elif self.outcome or self.outcome_details:
            raise DomainError("An active assignment cannot have a final outcome or details.")

    @property
    def active(self) -> bool:
        return self.ended_at is None

    def assert_reporter(self, staff_id: str) -> None:
        """Require an active assignment and its allocated reporting worker."""
        if not self.active:
            raise DomainError("This assignment is no longer active.")
        if staff_id != self.staff_id:
            raise DomainError("Only the allocated worker can report this outcome.")

    def end(self, when: datetime, outcome: str, details: str = "") -> None:
        local_datetime(when, "Assignment end")
        outcome = require_text(outcome, "Assignment outcome")
        if not isinstance(details, str):
            raise DomainError("Assignment outcome details must be text.")
        details = details.strip()
        if not self.active:
            raise DomainError("This assignment has already ended.")
        if when < self.started_at:
            raise DomainError("Assignment cannot end before it starts.")
        self.ended_at, self.outcome, self.outcome_details = when, outcome, details
