"""Shared domain values and validation for the local YOWD application."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
import re


class DomainError(ValueError):
    """An operation violates a business rule or contains invalid input."""


class RequestStatus(str, Enum):
    REQUESTED = "Requested"
    QUOTED = "Quoted"
    ACCEPTED = "Accepted"
    ALLOCATED = "Allocated"
    PICKED_UP = "Picked Up"
    DELIVERED = "Delivered"
    REJECTED = "Rejected"
    QUOTE_DECLINED = "Quote declined"
    FAILED_PICKUP = "Failed pickup"
    FAILED_DELIVERY = "Failed delivery"


class RequestAction(str, Enum):
    """Actions that can be taken on one delivery request.

    Each value is the name of the action as end users see it.
    """

    EDIT_CUSTOMER = "Edit Customer"
    EDIT_ADDRESSES = "Edit Addresses"
    PREPARE_QUOTE = "Prepare Quote"
    REJECT_REQUEST = "Reject Request"
    ACCEPT_QUOTE = "Accept Quote"
    DECLINE_QUOTE = "Decline Quote"
    ALLOCATE_WORKER = "Allocate Worker"
    AUTHORISE_PAYMENT = "Authorise Payment Exception"
    RETRY_PICKUP = "Retry Pickup"
    RECORD_PICKUP = "Record Pickup"
    RECORD_DELIVERED = "Delivered"
    RECORD_FAILED_DELIVERY = "Failed Delivery"


class ParcelStatus(str, Enum):
    PENDING = "Pending"
    COLLECTED = "Collected"
    DELIVERED = "Delivered"
    RETURN_REQUIRED = "Return required"


class QuoteDecision(str, Enum):
    PENDING = "Pending"
    ACCEPTED = "Accepted"
    DECLINED = "Declined"

class PickupFailure(str, Enum):
    # Current Failure Pickup Reasons
    CUSTOMER_NOT_PRESENT = "Customer not present"
    PARCEL_MISSING = "Parcel missing"
    PARCEL_DAMAGED = "Parcel damaged"
    PARCEL_MISMATCH = "Parcel does not match request"


class DeliveryFailure(str, Enum):
    """Reasons a delivery attempt can fail (A1 Task 6, variants 3a-4a)."""

    RECIPIENT_NOT_PRESENT = "Recipient not present"
    DESTINATION_PROBLEM = "Destination inaccessible or incorrect"
    PARCEL_MISSING = "Parcel missing"
    PARCEL_DAMAGED = "Parcel damaged"
    OTHER = "Other"


class ParcelException(str, Enum):
    """Problems recorded against one parcel (A2 Parcel CRC)."""

    MISSING = "Missing"
    DAMAGED = "Damaged"
    MISMATCH = "Does not match request"


# Pickup and delivery failure reasons that concern one parcel, and the
# exception each one records on that parcel. Both failure enumerations use
# the same text for missing and damaged parcels.
PARCEL_EXCEPTION_BY_FAILURE = {
    "Parcel missing": ParcelException.MISSING,
    "Parcel damaged": ParcelException.DAMAGED,
    "Parcel does not match request": ParcelException.MISMATCH,
}

def require_text(value: str, label: str) -> str:
    """Return trimmed, nonempty text or a useful validation error."""
    if not isinstance(value, str) or not value.strip():
        raise DomainError(f"{label} is required.")
    return value.strip()


def validate_contact(name: str, email: str, phone: str) -> tuple[str, str, str]:
    """Validate contact fields without claiming to verify their ownership."""
    name = require_text(name, "Name")
    email = require_text(email, "Email")
    phone = require_text(phone, "Phone")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise DomainError("Enter an email address such as name@example.com.")
    digits = re.sub(r"[\s()+.-]", "", phone)
    if not digits.isdigit() or not 6 <= len(digits) <= 15:
        raise DomainError("Phone must contain between 6 and 15 digits.")
    return name, email, phone


def decimal_value(value: Decimal, label: str, *, positive: bool = False) -> Decimal:
    """Normalise a decimal and reject nonfinite or out-of-range values."""
    try:
        if isinstance(value, bool):
            raise InvalidOperation
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise DomainError(f"{label} must be a number.") from None
    if not result.is_finite():
        raise DomainError(f"{label} must be finite.")
    if (positive and result <= 0) or (not positive and result < 0):
        qualifier = "greater than zero" if positive else "zero or greater"
        raise DomainError(f"{label} must be {qualifier}.")
    return result


def money(value: Decimal, label: str) -> Decimal:
    """Validate nonnegative currency with no fractions below one cent."""
    result = decimal_value(value, label)
    try:
        rounded = result.quantize(Decimal("0.01"))
    except InvalidOperation:
        raise DomainError(f"{label} is too large.") from None
    if result != rounded:
        raise DomainError(f"{label} must have at most two decimal places.")
    return rounded


def local_datetime(value: datetime, label: str) -> datetime:
    """Require a naive Melbourne local datetime, used consistently by this app."""
    if not isinstance(value, datetime):
        raise DomainError(f"{label} must be a date and time.")
    if value.tzinfo is not None:
        raise DomainError(f"{label} must use local time without a timezone suffix.")
    return value


def validate_window(
    start: datetime, end: datetime, *, allow_zero: bool = False
) -> tuple[datetime, datetime]:
    local_datetime(start, "Window start")
    local_datetime(end, "Window end")
    if end < start or (end == start and not allow_zero):
        raise DomainError("Window end must be after its start.")
    return start, end
