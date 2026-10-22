"""Payment outcome records only; no financial transaction is performed."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .common import DomainError, local_datetime, money, require_text


@dataclass
class PaymentRecord:
    payment_id: str
    request_id: str
    quoted_amount: Decimal
    received_amount: Decimal
    received_at: datetime
    authorised_by: str = ""
    authorisation_reason: str = ""

    def __post_init__(self) -> None:
        self.payment_id = require_text(self.payment_id, "Payment ID")
        self.request_id = require_text(self.request_id, "Request ID")
        self.quoted_amount = money(self.quoted_amount, "Quoted amount")
        self.received_amount = money(self.received_amount, "Received amount")
        local_datetime(self.received_at, "Payment record time")
        if not isinstance(self.authorised_by, str) or not isinstance(self.authorisation_reason, str):
            raise DomainError("Payment authorisation name and reason must be text.")
        if bool(self.authorised_by.strip()) != bool(self.authorisation_reason.strip()):
            raise DomainError("Payment authorisation requires both a name and reason.")
        self.authorised_by = self.authorised_by.strip()
        self.authorisation_reason = self.authorisation_reason.strip()

    @property
    def exception(self) -> bool:
        return self.received_amount != self.quoted_amount

    @property
    def allows_pickup(self) -> bool:
        return not self.exception or bool(self.authorised_by and self.authorisation_reason)

    def authorise(self, name: str, reason: str) -> None:
        """Record an explicit business decision; the application supplies the actor."""
        name = require_text(name, "Authorising person")
        reason = require_text(reason, "Authorisation reason")
        if not self.exception:
            raise DomainError("Matching payment does not require exception authorisation.")
        if self.authorised_by and (name, reason) != (
            self.authorised_by, self.authorisation_reason
        ):
            raise DomainError("Recorded payment authorisation cannot be overwritten.")
        self.authorised_by, self.authorisation_reason = name, reason
