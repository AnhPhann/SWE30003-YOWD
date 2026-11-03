"""Parcel characteristics and physical collection/handover status."""

from dataclasses import dataclass
from decimal import Decimal

from .common import (
    DomainError, ParcelException, ParcelStatus, decimal_value, require_text,
)


@dataclass
class Parcel:
    parcel_id: str
    description: str
    weight_kg: Decimal
    length_cm: Decimal
    width_cm: Decimal
    height_cm: Decimal
    status: ParcelStatus = ParcelStatus.PENDING
    exception: str = ""
    request_id: str = ""

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Check all parcel details before the request proceeds to quotation."""
        parcel_id = require_text(self.parcel_id, "Parcel ID")
        description = require_text(self.description, "Parcel description")
        values = {
            label: decimal_value(getattr(self, label), label.replace("_", " "), positive=True)
            for label in ("weight_kg", "length_cm", "width_cm", "height_cm")
        }
        try:
            status = ParcelStatus(self.status)
        except (ValueError, TypeError):
            raise DomainError("Unknown parcel status.") from None
        exception = self._checked_exception(self.exception)
        if not isinstance(self.request_id, str):
            raise DomainError("Parcel request ID must be text.")
        self.parcel_id, self.description, self.status = parcel_id, description, status
        self.exception = exception
        self.request_id = self.request_id.strip()
        for label, value in values.items():
            setattr(self, label, value)

    @staticmethod
    def _checked_exception(exception: str) -> str:
        """Return a blank or known exception value, or raise DomainError."""
        if exception == "":
            return ""
        try:
            return ParcelException(exception).value
        except (ValueError, TypeError):
            raise DomainError("Unknown parcel exception.") from None

    @property
    def has_exception(self) -> bool:
        """Return whether this parcel has a recorded exception."""
        return self.exception != ""

    def record_exception(self, exception: str) -> None:
        """Flag this parcel as missing, damaged or not matching the request."""
        checked = self._checked_exception(exception)
        if checked == "":
            raise DomainError("A parcel exception is required.")
        self.exception = checked

    def clear_exception(self) -> None:
        """Remove a recorded exception, for example before a pickup retry."""
        self.exception = ""
