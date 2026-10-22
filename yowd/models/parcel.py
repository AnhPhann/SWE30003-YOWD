"""Parcel characteristics and physical collection/handover status."""

from dataclasses import dataclass
from decimal import Decimal

from .common import DomainError, ParcelStatus, decimal_value, require_text


@dataclass
class Parcel:
    parcel_id: str
    description: str
    weight_kg: Decimal
    length_cm: Decimal
    width_cm: Decimal
    height_cm: Decimal
    status: ParcelStatus = ParcelStatus.PENDING

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
        self.parcel_id, self.description, self.status = parcel_id, description, status
        for label, value in values.items():
            setattr(self, label, value)
