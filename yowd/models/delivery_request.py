"""Coordinate one delivery lifecycle while retaining assignment and payment history."""

from dataclasses import dataclass, field
from datetime import datetime

from .common import (
    DeliveryFailure, DomainError, ParcelStatus, PickupFailure, QuoteDecision,
    RequestStatus, local_datetime, require_text,
)
from .customer import Customer
from .delivery_assignment import DeliveryAssignment
from .delivery_quote import DeliveryQuote
from .delivery_staff import DeliveryStaff
from .parcel import Parcel
from .payment_record import PaymentRecord


@dataclass
class DeliveryRequest:
    request_id: str
    customer: Customer
    pickup: str
    destination: str
    parcels: list[Parcel]
    created_at: datetime
    status: RequestStatus = RequestStatus.REQUESTED
    quote: DeliveryQuote | None = None
    assignments: list[DeliveryAssignment] = field(default_factory=list)
    payment: PaymentRecord | None = None
    picked_up_at: datetime | None = None
    completed_at: datetime | None = None
    failure_reason: str = ""
    pickup_address: str = ""
    destination_address: str = ""

    def __post_init__(self) -> None:
        self.validate()
        if self.request_id not in self.customer.request_ids:
            self.customer.request_ids.append(self.request_id)

    def validate(self) -> None:
        """Validate details and retained-record identities, including restored data."""
        request_id = require_text(self.request_id, "Request ID")
        pickup = require_text(self.pickup, "Pickup suburb")
        destination = require_text(self.destination, "Destination suburb")
        pickup_address, destination_address = self._address_pair(
            self.pickup_address, self.destination_address
        )
        local_datetime(self.created_at, "Request creation")
        if not isinstance(self.customer, Customer):
            raise DomainError("A request must belong to one customer.")
        if not self.parcels or not all(isinstance(p, Parcel) for p in self.parcels):
            raise DomainError("A request must contain at least one valid parcel.")
        if len({p.parcel_id for p in self.parcels}) != len(self.parcels):
            raise DomainError("Parcel IDs must be unique within a request.")
        for parcel in self.parcels:
            parcel.validate()
        try:
            status = RequestStatus(self.status)
        except (ValueError, TypeError):
            raise DomainError("Unknown request status.") from None
        if self.quote is not None:
            if not isinstance(self.quote, DeliveryQuote) or self.quote.request_id != request_id:
                raise DomainError("The quote must belong to this request.")
            self.quote.validate()
        assignment_ids = set()
        for assignment in self.assignments:
            if not isinstance(assignment, DeliveryAssignment) or assignment.request_id != request_id:
                raise DomainError("Every assignment must belong to this request.")
            if assignment.assignment_id in assignment_ids:
                raise DomainError("Assignment IDs must be unique within a request.")
            assignment_ids.add(assignment.assignment_id)
        if sum(assignment.active for assignment in self.assignments) > 1:
            raise DomainError("A request can have at most one active assignment.")
        if self.payment is not None and (
            not isinstance(self.payment, PaymentRecord) or self.payment.request_id != request_id
        ):
            raise DomainError("The payment record must belong to this request.")
        for value, label in (
            (self.picked_up_at, "Pickup time"), (self.completed_at, "Completion time")
        ):
            if value is not None:
                local_datetime(value, label)
                if value < self.created_at:
                    raise DomainError(f"{label} cannot precede request creation.")
        if self.completed_at and self.picked_up_at and self.completed_at < self.picked_up_at:
            raise DomainError("Delivery completion cannot precede pickup.")
        self.request_id, self.pickup, self.destination = request_id, pickup, destination
        self.pickup_address, self.destination_address = pickup_address, destination_address
        self.status = status

    @staticmethod
    def _address_pair(pickup_address: str, destination_address: str) -> tuple[str, str]:
        """Allow unknown legacy addresses as a pair, never a partial address pair."""
        if not isinstance(pickup_address, str) or not isinstance(destination_address, str):
            raise DomainError("Pickup and destination addresses must be text.")
        pickup_address, destination_address = pickup_address.strip(), destination_address.strip()
        if bool(pickup_address) != bool(destination_address):
            raise DomainError("Provide both pickup and destination addresses.")
        return pickup_address, destination_address

    @property
    def has_full_addresses(self) -> bool:
        """Whether actual addresses are known instead of legacy suburb-only data."""
        return bool(self.pickup_address and self.destination_address)

    def update_addresses(self, pickup_address: str, destination_address: str) -> None:
        """Repair or correct addresses before quoting; validate both before mutation."""
        self._require_status(RequestStatus.REQUESTED)
        pickup_address = require_text(pickup_address, "Pickup address")
        destination_address = require_text(destination_address, "Destination address")
        self.pickup_address, self.destination_address = pickup_address, destination_address

    @property
    def active_assignment(self) -> DeliveryAssignment | None:
        active = [assignment for assignment in self.assignments if assignment.active]
        if len(active) > 1:
            raise DomainError("A request can have at most one active assignment.")
        return active[0] if active else None

    def _require_status(self, status: RequestStatus) -> None:
        if self.status != status:
            raise DomainError(f"This action requires status {status.value}; current status is {self.status.value}.")

    def _reporting_assignment(self, staff_id: str, when: datetime) -> DeliveryAssignment:
        local_datetime(when, "Outcome time")
        assignment = self.active_assignment
        if assignment is None:
            raise DomainError("There is no active assignment for this request.")
        assignment.assert_reporter(staff_id)
        if when < assignment.started_at:
            raise DomainError("Outcome time cannot precede allocation.")
        return assignment

    def issue_quote(self, quote: DeliveryQuote) -> None:
        self._require_status(RequestStatus.REQUESTED)
        self.validate()
        if not isinstance(quote, DeliveryQuote):
            raise DomainError("A valid delivery quote is required.")
        quote.validate()
        if self.quote is not None:
            raise DomainError("This request already has a current offer.")
        if quote.request_id != self.request_id:
            raise DomainError("The quote belongs to a different request.")
        if quote.decision != QuoteDecision.PENDING:
            raise DomainError("A new quote cannot already have a customer response.")
        if quote.issued_at < self.created_at:
            raise DomainError("A quote cannot be issued before the request was created.")
        self.quote, self.status = quote, RequestStatus.QUOTED

    def reject(self, reason: str) -> None:
        """Record an office rejection before quotation or operational work starts."""
        self._require_status(RequestStatus.REQUESTED)
        reason = require_text(reason, "Rejection reason")
        if self.quote is not None or self.assignments or self.payment is not None:
            raise DomainError("Only an unquoted request without operational records can be rejected.")
        self.status, self.failure_reason = RequestStatus.REJECTED, reason

    def respond_to_quote(self, customer_id: str, accepted: bool) -> None:
        self._require_status(RequestStatus.QUOTED)
        # The responder must be this request's customer, and the customer
        # must list this request as one of theirs (A2 Customer CRC).
        is_own_customer = (
            customer_id == self.customer.customer_id
            and self.customer.owns_request(self.request_id)
        )
        if not is_own_customer:
            raise DomainError("Only this request's customer can respond to its quote.")
        if self.quote is None:
            raise DomainError("The request has no current quote.")
        self.quote.record_response(accepted)
        self.status = RequestStatus.ACCEPTED if accepted else RequestStatus.QUOTE_DECLINED

    def allocate(self, worker: DeliveryStaff, assignment_id: str, when: datetime) -> None:
        self._require_status(RequestStatus.ACCEPTED)
        if self.active_assignment:
            raise DomainError("This request already has an active assignment.")
        if self.quote is None or self.quote.decision != QuoteDecision.ACCEPTED:
            raise DomainError("Allocation requires an accepted quote.")
        if not isinstance(worker, DeliveryStaff):
            raise DomainError("A delivery worker is required.")
        local_datetime(when, "Allocation time")
        if when < self.quote.issued_at:
            raise DomainError("Allocation cannot precede quote issue.")
        eligible, reason = worker.eligibility(self.quote.pickup_at, self.quote.delivery_at)
        if not eligible:
            raise DomainError(reason)
        assignment_id = require_text(assignment_id, "Assignment ID")
        if assignment_id in worker.assignment_ids or any(
            item.assignment_id == assignment_id for item in self.assignments
        ):
            raise DomainError("That assignment ID has already been used.")
        assignment = DeliveryAssignment(assignment_id, self.request_id, worker.staff_id, when)
        self.assignments.append(assignment)
        worker.assignment_ids.append(assignment_id)
        self.status = RequestStatus.ALLOCATED
        self.failure_reason = ""

    def _pickup_failure_reason(self, failure: str | None, parcel_id: str | None) -> str:
        # Check Failure Reason and Return Specific Fail Text

        if failure is None: # Standard Fail Message with No Specific Reason
            return "Required parcels were not all collected in acceptable condition."
        try:
            failure = PickupFailure(failure)
        except ValueError:
            raise DomainError("Unknown Pickup Failure") from None
        
        if failure == PickupFailure.CUSTOMER_NOT_PRESENT:
            return f"Failed Pickup: {failure.value}."
        
        parcel = next((p for p in self.parcels if p.parcel_id == parcel_id), None)  # Check for Each Parcel

        if parcel is None: 
            raise DomainError("Select the affected parcel from this request.") # If a Parcel Outcome is Set But No Parcel is Selected Raise the Following Error
        return f"Failed Pickup: {failure.value} - {parcel.description} ({parcel.parcel_id})." # Marked Failed Pickup Stating Specific Parcel & Reason

    def record_pickup(
        self, staff_id: str, parcel_ok: bool, payment: PaymentRecord | None, when: datetime, *, failure: str | None = None, parcel_id: str | None = None,
    ) -> bool:
        self._require_status(RequestStatus.ALLOCATED)
        assignment = self._reporting_assignment(staff_id, when)
        if not isinstance(parcel_ok, bool):
            raise DomainError("Parcel collection result must be true or false.")
        if any(parcel.status != ParcelStatus.PENDING for parcel in self.parcels):
            raise DomainError("All required parcels must still be awaiting collection.")
        if not parcel_ok:
            if self.payment is not None:
                raise DomainError("A pickup with a recorded payment cannot be discarded as a failed unpaid attempt.")
            reason = self._pickup_failure_reason(failure, parcel_id) # State the Parcel That Failed
            assignment.end(when, RequestStatus.FAILED_PICKUP.value, reason)
            self.status = RequestStatus.FAILED_PICKUP
            self.failure_reason = reason # State Specific Failure Reason
            return False
        if not isinstance(payment, PaymentRecord):
            raise DomainError("A payment outcome record is required before pickup can succeed.")
        if self.quote is None or self.quote.decision != QuoteDecision.ACCEPTED:
            raise DomainError("Pickup requires an accepted quote.")
        if payment.request_id != self.request_id or payment.quoted_amount != self.quote.amount:
            raise DomainError("Payment must match this request and its accepted quoted amount.")
        if not assignment.started_at <= payment.received_at <= when:
            raise DomainError("Payment record time must fall between allocation and this pickup report.")
        if self.payment is not None:
            if payment is not self.payment:
                raise DomainError("The payment already recorded for this request must be reused without replacement.")
            # Legacy records retain their payment while awaiting actual worker confirmation.
            if not payment.allows_pickup:
                return False
        
        # Record the Payment and Collect Parcels, Even if the Amount Does Not Match
        self.payment = payment
        for parcel in self.parcels:
            parcel.status = ParcelStatus.COLLECTED
        self.picked_up_at, self.status = when, RequestStatus.PICKED_UP
        self.failure_reason = ""
        
        # New requests collect first; delivery waits for exception authorisation.
        return payment.allows_pickup

    def delivery_failure_text(
        self, failure: str | None, parcel_id: str | None, details: str,
    ) -> str:
        """Validate a failed delivery reason and return the text to record.

        This method does not change the request. With no failure reason
        selected, the free-text details are required and recorded as they
        are. Missing and damaged parcel reasons require a parcel from this
        request. The Other reason requires details.
        """
        if not isinstance(details, str):
            raise DomainError("Failed delivery details must be text.")
        details = details.strip()
        if failure is None:
            return require_text(details, "Failed delivery reason")
        try:
            failure = DeliveryFailure(failure)
        except ValueError:
            raise DomainError("Unknown failed delivery reason.") from None
        if failure == DeliveryFailure.OTHER and not details:
            raise DomainError(
                "Describe the failed delivery reason in the details."
            )

        reason = f"Failed delivery: {failure.value}"
        parcel_reasons = (
            DeliveryFailure.PARCEL_MISSING, DeliveryFailure.PARCEL_DAMAGED,
        )
        if failure in parcel_reasons:
            affected_parcel = None
            for parcel in self.parcels:
                if parcel.parcel_id == parcel_id:
                    affected_parcel = parcel
            if affected_parcel is None:
                raise DomainError(
                    "Select the affected parcel from this request."
                )
            description = affected_parcel.description
            reason += f" - {description} ({affected_parcel.parcel_id})"
        if details:
            # A trailing full stop is removed so the text ends with one.
            reason += f". Details: {details.rstrip('.')}"
        return reason + "."

    def record_delivery(
        self, staff_id: str, successful: bool, reason: str, when: datetime,
        *, failure: str | None = None, parcel_id: str | None = None,
    ) -> None:
        self._require_status(RequestStatus.PICKED_UP)

        # Delivery Waits Until Office Staff Authorise a Payment Exception
        if self.payment is None or not self.payment.allows_pickup:
            raise DomainError("The payment exception must be authorised by Office Staff before delivery.")

        assignment = self._reporting_assignment(staff_id, when)
        if not isinstance(successful, bool):
            raise DomainError("Delivery result must be true or false.")
        if self.picked_up_at is None or when < self.picked_up_at:
            raise DomainError("Delivery outcome cannot precede recorded pickup.")
        if any(parcel.status != ParcelStatus.COLLECTED for parcel in self.parcels):
            raise DomainError("All required parcels must have been collected.")
        if not successful:
            reason = self.delivery_failure_text(failure, parcel_id, reason)
        status = RequestStatus.DELIVERED if successful else RequestStatus.FAILED_DELIVERY
        assignment.end(when, status.value, reason)
        for parcel in self.parcels:
            parcel.status = ParcelStatus.DELIVERED if successful else ParcelStatus.RETURN_REQUIRED
        self.status = status
        if successful:
            self.completed_at, self.failure_reason = when, ""
        else:
            self.failure_reason = reason

    def retry_pickup(self) -> None:
        """Allow an explicit office action after a failed, unpaid pickup attempt."""
        self._require_status(RequestStatus.FAILED_PICKUP)
        if self.active_assignment or self.payment is not None:
            raise DomainError("Retry requires no active assignment and no payment record.")
        if self.quote is None or self.quote.decision != QuoteDecision.ACCEPTED:
            raise DomainError("Retry requires the retained accepted quote.")
        if any(parcel.status != ParcelStatus.PENDING for parcel in self.parcels):
            raise DomainError("Retry requires every parcel to remain awaiting collection.")
        if self.assignments:
            last = self.assignments[-1]
            if (not last.active and last.outcome == RequestStatus.FAILED_PICKUP.value
                    and not last.outcome_details):
                last.outcome_details = self.failure_reason
        self.status, self.failure_reason = RequestStatus.ACCEPTED, ""
