"""Explicit sample tariff, separate from payment and request lifecycle rules.

This is an implementation assumption for team review, not a YOWD price list.
The configured suburb set is a small demonstration service area.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, DecimalException

from .models import DeliveryRequest, DomainError


SERVICE_ZONES = {
    "Melbourne": "central",
    "Docklands": "central",
    "Southbank": "central",
    "Carlton": "north",
    "Brunswick": "north",
    "Richmond": "east",
    "Hawthorn": "east",
    "Footscray": "west",
    "St Kilda": "south",
    "South Yarra": "south",
}


def normalise_suburb(value: str) -> str:
    """Return canonical spelling for a configured suburb, or trimmed input."""
    cleaned = " ".join(str(value).split())
    for suburb in SERVICE_ZONES:
        if suburb.casefold() == cleaned.casefold():
            return suburb
    return cleaned


@dataclass(frozen=True)
class TariffPolicy:
    """Demonstration tariff using route zone and each parcel's billable weight."""

    base_fee: Decimal = Decimal("10.00")
    per_parcel: Decimal = Decimal("2.00")
    per_kg: Decimal = Decimal("2.00")
    same_zone_fee: Decimal = Decimal("2.00")
    cross_zone_fee: Decimal = Decimal("5.00")
    volumetric_divisor: Decimal = Decimal("5000")

    def estimate(self, request: DeliveryRequest) -> Decimal:
        """Return AUD rounded once to cents, with no network/pricing dependency."""
        same_zone, billable = self._route_and_weight(request)
        route = self.same_zone_fee if same_zone else self.cross_zone_fee
        try:
            # Quote Calculation and Rounded
            return (
                self.base_fee + self.per_parcel * len(request.parcels) + self.per_kg * billable + route
            ).quantize(Decimal("0.01"))
        except DecimalException:
            # Return Parcel to Large Error if Exceeds Decimal Limits
            raise DomainError(
                "Parcel measurements are too large to calculate a quote."
            ) from None

    def _route_and_weight(self, request: DeliveryRequest) -> tuple[bool, Decimal]:
        request.validate() # Check Delivery Request is Valid
        try:
            same_zone = SERVICE_ZONES[request.pickup] == SERVICE_ZONES[request.destination]
        except KeyError as exc:
            raise DomainError("The request is outside the configured sample service area.") from exc
        try:
            billable = sum(
                (
                    max(
                        parcel.weight_kg,
                        parcel.length_cm * parcel.width_cm * parcel.height_cm / self.volumetric_divisor,
                    )
                    for parcel in request.parcels
                ),
                Decimal("0"),
            )
        except DecimalException:
            raise DomainError(
                "Parcel measurements are too large to calculate a quote."
            ) from None
        return same_zone, billable

    def explain(self, request: DeliveryRequest) -> str:
        # Show how the Estimate was Reached, so Office Staff can Review
        total = self.estimate(request)

        same_zone, billable = self._route_and_weight(request) # Retrieve Quote
        count = len(request.parcels) # Count Number of Parcels
        
        route = "Same-Zone Fee" if same_zone else "Cross-Zone Fee" # Retrieve Route Wording
        route_fee = self.same_zone_fee if same_zone else self.cross_zone_fee
        # Explain Text Breakdown
        return (
            f"${self.base_fee} Base + {count} Parcel{'s' if count != 1 else ''} x ${self.per_parcel}"
            f" + {billable.quantize(Decimal('0.01'))} Billable KG x ${self.per_kg}"
            f" + {route} ${route_fee} = ${total}"
    )
    
    def duration(self, request: DeliveryRequest) -> timedelta:
        """Sample estimate: one hour within a zone, ninety minutes across zones."""
        try:
            same_zone = SERVICE_ZONES[request.pickup] == SERVICE_ZONES[request.destination]
        except KeyError as exc:
            raise DomainError("The request is outside the configured sample service area.") from exc
        return timedelta(minutes=60 if same_zone else 90)
