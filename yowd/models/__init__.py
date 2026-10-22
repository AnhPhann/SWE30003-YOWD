"""The ten YOWD domain classes and their shared values."""

from .availability_schedule import AvailabilitySchedule
from .common import DomainError, ParcelStatus, QuoteDecision, RequestStatus
from .customer import Customer
from .delivery_assignment import DeliveryAssignment
from .delivery_quote import DeliveryQuote
from .delivery_request import DeliveryRequest
from .delivery_staff import DeliveryStaff
from .delivery_statistics import DeliveryStatistics
from .parcel import Parcel
from .payment_record import PaymentRecord
from .staff_list import StaffList

__all__ = [
    "AvailabilitySchedule", "Customer", "DeliveryAssignment", "DeliveryQuote",
    "DeliveryRequest", "DeliveryStaff", "DeliveryStatistics", "DomainError", "Parcel",
    "ParcelStatus", "PaymentRecord", "QuoteDecision", "RequestStatus", "StaffList",
]
