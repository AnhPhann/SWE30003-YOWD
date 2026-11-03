"""Application actions coordinating domain objects and local persistence.

The interface uses these methods instead of editing domain objects directly.
Each action is persisted atomically; a failed action restores the prior graph.
"""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from .models import (
    AvailabilitySchedule,
    Customer,
    DeliveryQuote,
    DeliveryRequest,
    DeliveryStaff,
    DeliveryStatistics,
    DomainError,
    Parcel,
    PaymentRecord,
    QuoteDecision,
    RequestStatus,
    StaffList,
)
from .operating_hours import (
    CLOSE,
    OPEN,
    SUMMARY,
    ensure_availability_period,
    ensure_quoted_window,
    next_operating_day,
    within_operating_hours,
)
from .pricing import SERVICE_ZONES, TariffPolicy, normalise_suburb
from .models.common import DeliveryFailure, require_text, validate_contact
from .models.delivery_statistics import REPORTING_PERIODS
from .serialization import decode_state, encode_state
from .storage import SQLiteStore


Result = TypeVar("Result")


def _identifier(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _number(value: object, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise DomainError(f"{label} must be a number.") from None
    if not parsed.is_finite():
        raise DomainError(f"{label} must be a finite number.")
    return parsed


def _parcel_from_input(data: dict[str, str], parcel_id: str) -> Parcel:
    """Use one domain validation path for draft edits and final lodgement."""
    if not isinstance(data, dict):
        raise DomainError("Each parcel must provide its description and measurements.")
    try:
        return Parcel(
            parcel_id, data["description"],
            _number(data["weight_kg"], "Parcel weight"),
            _number(data["length_cm"], "Parcel length"),
            _number(data["width_cm"], "Parcel width"),
            _number(data["height_cm"], "Parcel height"),
        )
    except KeyError as exc:
        raise DomainError(f"A required parcel field is missing: {exc.args[0]}.") from None


class YowdApplication:
    """One local application session; inject a clock for reproducible tests."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or datetime.now
        self.tariff = TariffPolicy()
        self.store = SQLiteStore(db_path)
        self.customers: dict[str, Customer] = {}
        self.staff_list = StaffList()
        self.requests: dict[str, DeliveryRequest] = {}
        try:
            saved = self.store.load()
            if saved is not None:
                self.customers, self.staff_list, self.requests = decode_state(saved)
        except Exception:
            self.store.close()
            raise

    def close(self) -> None:
        self.store.close()

    def _change(self, action: Callable[[], Result]) -> Result:
        """Commit one action, restoring in-memory state if validation/save fails."""
        before = encode_state(self.customers, self.staff_list, self.requests)
        try:
            result = action()
            after = encode_state(self.customers, self.staff_list, self.requests)
            # Validate the same graph invariants used during startup before saving.
            decode_state(after)
            self.store.save(after)
            return result
        except Exception:
            self.customers, self.staff_list, self.requests = decode_state(before)
            raise

    def _request(self, request_id: str) -> DeliveryRequest:
        try:
            return self.requests[request_id]
        except (KeyError, TypeError):
            raise DomainError("Delivery request was not found.") from None

    def create_request(
        self,
        customer_name: str,
        email: str,
        phone: str,
        pickup: str,
        destination: str,
        parcels: list[dict[str, str]],
        *,
        pickup_address: str = "",
        destination_address: str = "",
    ) -> str:
        """Lodge a validated multi-parcel request, retaining outside-area rejection."""
        def create() -> str:
            pickup_detail = require_text(pickup_address, "Pickup address")
            destination_detail = require_text(destination_address, "Destination address")
            candidate = Customer(_identifier("CUS"), customer_name, email, phone)
            customer = next(
                (
                    existing for existing in self.customers.values()
                    if existing.email.casefold() == candidate.email.casefold()
                ),
                candidate,
            )
            if customer is not candidate and (
                customer.name != candidate.name or customer.phone != candidate.phone
            ):
                raise DomainError(
                    "That email already belongs to a customer with different details. "
                    "Use their recorded name and phone for another request."
                )
            if not isinstance(parcels, list):
                raise DomainError("Supply a list containing at least one parcel.")
            items = [_parcel_from_input(data, _identifier("PAR")) for data in parcels]
            request_id = _identifier("REQ")
            request = DeliveryRequest(
                request_id, customer, normalise_suburb(pickup),
                normalise_suburb(destination), items, self._clock(),
                pickup_address=pickup_detail, destination_address=destination_detail,
            )
            unsupported = [
                name for name in (request.pickup, request.destination)
                if name not in SERVICE_ZONES
            ]
            if unsupported:
                request.reject(
                    "Outside the configured sample service area: "
                    + ", ".join(unsupported)
                    + "."
                )
            self.customers[customer.customer_id] = customer
            self.requests[request_id] = request
            return request_id

        return self._change(create)

    @staticmethod
    def validate_parcel(data: dict[str, str]) -> None:
        """Validate an unsaved parcel draft without changing business state."""
        _parcel_from_input(data, "DRAFT-PARCEL")

    def update_request_addresses(
        self, request_id: str, pickup_address: str, destination_address: str,
    ) -> None:
        """Correct street details before quotation, preserving route suburbs."""
        self._change(lambda: self._request(request_id).update_addresses(
            pickup_address, destination_address,
        ))

    def customer_details(self, request_id: str) -> dict:
        """Return the contact details and request statuses of a customer.

        The customer is the one who owns the given request.
        """
        customer = self._request(request_id).customer
        return {
            "customer_id": customer.customer_id,
            "name": customer.name,
            "email": customer.email,
            "phone": customer.phone,
            "requests": customer.request_statuses(self.requests.values()),
        }

    def update_customer_contact(
        self, customer_id: str, name: str, email: str, phone: str,
    ) -> None:
        """Change a customer's contact details for all of their requests.

        The email must not belong to another customer, because new requests
        are matched to existing customers by email.
        """
        def update() -> None:
            customer = self.customers.get(customer_id)
            if customer is None:
                raise DomainError("Customer was not found.")
            validated_name, validated_email, validated_phone = (
                validate_contact(name, email, phone)
            )
            for other_customer in self.customers.values():
                if other_customer is customer:
                    continue
                other_email = other_customer.email.casefold()
                if other_email == validated_email.casefold():
                    raise DomainError(
                        "That email already belongs to another customer."
                    )
            customer.update_contact(
                validated_name, validated_email, validated_phone,
            )

        self._change(update)

    def register_staff(
        self, name: str, email: str, phone: str,
        available_from: datetime, available_until: datetime,
    ) -> str:
        def register() -> str:
            ensure_availability_period(available_from, available_until)
            worker = DeliveryStaff(_identifier("STA"), name, email, phone)
            if any(
                existing.email.casefold() == worker.email.casefold()
                for existing in self.staff_list.staff.values()
            ):
                raise DomainError("That worker email is already registered, including former staff.")
            worker.schedule.add_period(available_from, available_until)
            self.staff_list.register(worker)
            return worker.staff_id

        return self._change(register)

    def operating_hours_summary(self) -> str:
        return SUMMARY

    def availability_periods(self, staff_id: str) -> list[tuple[datetime, datetime]]:
        """Return the saved periods. Callers may edit a copy without changing them."""
        return list(self.staff_list.get(staff_id).schedule.periods)

    def merged_availability(
        self, periods: list[tuple[datetime, datetime]],
    ) -> list[tuple[datetime, datetime]]:
        """Validate and merge a draft schedule without saving it."""
        if not isinstance(periods, list):
            raise DomainError("Availability must be a list of periods.")
        schedule = AvailabilitySchedule()
        for period in periods:
            if not isinstance(period, (tuple, list)) or len(period) != 2:
                raise DomainError("Each availability period needs a start and end.")
            start, end = period
            ensure_availability_period(start, end)
            schedule.add_period(start, end)
        return list(schedule.periods)

    def set_availability(
        self, staff_id: str, periods: list[tuple[datetime, datetime]],
    ) -> None:
        """Replace the saved schedule. An empty list clears it and keeps past jobs."""
        def update() -> None:
            self.staff_list.get(staff_id).schedule = AvailabilitySchedule(
                self.merged_availability(list(periods)),
            )

        self._change(update)

    def deactivate_staff(self, staff_id: str) -> None:
        self._change(lambda: self.staff_list.deactivate(staff_id))

    def suggest_quote_window(self, request_id: str) -> tuple[datetime, datetime]:
        """Sample policy: give earlier pending requests an earlier readiness rank.

        Each older pending request adds fifteen minutes of queue allowance. This
        is a deterministic estimate, not a booking or exclusive worker reservation.
        """
        request = self._request(request_id)
        if request.status != RequestStatus.REQUESTED:
            raise DomainError("A time estimate can be prepared only for a Requested delivery.")
        queue_states = {RequestStatus.REQUESTED, RequestStatus.QUOTED, RequestStatus.ACCEPTED}
        rank = sum(
            other.created_at < request.created_at and other.status in queue_states
            for other in self.requests.values()
        )
        ready = max(self._clock(), request.created_at) + timedelta(minutes=15 * (rank + 1))
        duration = self.tariff.duration(request)
        windows = []
        for worker in self.staff_list.staff.values():
            if not worker.active:
                continue
            for start, end in worker.schedule.periods:
                pickup_at = max(start, ready)
                delivery_at = pickup_at + duration
                if delivery_at <= end and within_operating_hours(pickup_at, delivery_at):
                    windows.append((pickup_at, delivery_at))
        if not windows:
            raise DomainError(
                "No active worker's availability covers a suggested delivery window "
                f"inside operating hours ({SUMMARY}). "
                "Register a worker or update availability first."
            )
        return min(windows)
    
    def quote_estimate(self, request_id: str) -> tuple[Decimal, str]:
        request = self._request(request_id) # Get DeliveryRequest 
        return self.tariff.estimate(request), self.tariff.explain(request) # Return Estimate Explanation

    def prepare_quote(
        self, request_id: str,
        pickup_at: datetime | None = None, delivery_at: datetime | None = None,
    ) -> Decimal:
        def prepare() -> Decimal:
            request = self._request(request_id)
            if not request.has_full_addresses:
                raise DomainError("Record full pickup and destination addresses before quotation.")
            if pickup_at is None and delivery_at is None:
                pickup, delivery = self.suggest_quote_window(request_id)
            elif pickup_at is None or delivery_at is None:
                raise DomainError("Both estimated pickup and delivery times are required.")
            else:
                pickup, delivery = pickup_at, delivery_at
            ensure_quoted_window(pickup, delivery)
            amount = self.tariff.estimate(request)
            quote = DeliveryQuote(
                _identifier("QUO"), request_id, amount, pickup, delivery, self._clock(),
            )
            if not self.staff_list.eligible_for(pickup, delivery):
                raise DomainError("No active worker currently covers the proposed quote window.")
            request.issue_quote(quote)
            return amount

        return self._change(prepare)

    def respond_quote(
        self, request_id: str, accepted: bool, customer_id: str | None = None,
    ) -> None:
        def respond() -> None:
            request = self._request(request_id)
            responder = request.customer.customer_id if customer_id is None else customer_id
            request.respond_to_quote(responder, accepted)

        self._change(respond)

    def _allocation_refusal(self, request: DeliveryRequest, worker: DeliveryStaff) -> str | None:
        """Return why this worker cannot take this request, using the same order as allocation."""
        if request.status != RequestStatus.ACCEPTED:
            return (
                f"This action requires status {RequestStatus.ACCEPTED.value}; "
                f"current status is {request.status.value}."
            )
        if request.active_assignment is not None:
            return "This request already has an active assignment."
        if request.quote is None or request.quote.decision != QuoteDecision.ACCEPTED:
            return "Allocation requires an accepted quote."
        try:
            ensure_quoted_window(request.quote.pickup_at, request.quote.delivery_at)
        except DomainError as error:
            return str(error)
        eligible, reason = worker.eligibility(request.quote.pickup_at, request.quote.delivery_at)
        if not eligible:
            return reason
        return None

    def allocation_options(self, request_id: str) -> dict:
        """Explain every worker's eligibility for the accepted quoted window."""
        request = self._request(request_id)
        if request.quote is None:
            window_text = "This request has no quote yet."
        else:
            window_text = (
                f"Quoted window: {request.quote.pickup_at:%Y-%m-%d %H:%M} to "
                f"{request.quote.delivery_at:%Y-%m-%d %H:%M}."
            )
        options = []
        for worker in self.staff_list.staff.values():
            reason = self._allocation_refusal(request, worker)
            options.append({
                "id": worker.staff_id,
                "name": worker.name,
                "active": worker.active,
                "eligible": reason is None,
                "reason": reason or "Worker is active and their schedule covers the quoted window.",
            })
        return {
            "operating_hours": SUMMARY,
            "window_text": window_text,
            "options": options,
        }

    def allocate(self, request_id: str, staff_id: str) -> None:
        def assign() -> None:
            request = self._request(request_id)
            worker = self.staff_list.get(staff_id)
            reason = self._allocation_refusal(request, worker)
            if reason:
                raise DomainError(reason)
            request.allocate(worker, _identifier("ASN"), self._clock())

        self._change(assign)

    def request_parcels(self, request_id: str) -> list[tuple[str, str]]:
        # This is Used to Return a List with Their ID and Name
        return [(p.parcel_id, p.description) for p in self._request(request_id).parcels]

    def pickup(
        self, request_id: str, staff_id: str, received_amount: str, parcel_ok: bool = True, *, failure: str | None = None, parcel_id: str | None = None,
    ) -> str:
        def collect() -> str:
            request = self._request(request_id)
            if not isinstance(parcel_ok, bool):
                raise DomainError("Parcel collection result must be true or false.")
            
            if not parcel_ok:
                request.record_pickup(
                    staff_id, False, None, self._clock(), failure=failure, parcel_id=parcel_id,
                )
                return f"{request.failure_reason} No payment was created; the assignment ended." # State Specific Fail Reason
            if request.quote is None:
                raise DomainError("Pickup requires an accepted quote and allocation.")
            amount = _number(received_amount, "Received amount")
            payment = request.payment
            if payment is None:
                payment = PaymentRecord(
                    _identifier("PAY"), request_id, request.quote.amount,
                    amount, self._clock(),
                )
            elif amount != payment.received_amount:
                raise DomainError("The received amount must match the payment already recorded for this request.")
            authorised = request.record_pickup(staff_id, True, payment, self._clock())
            if request.status == RequestStatus.ALLOCATED:
                return (
                    "Pickup is awaiting Office Staff payment authorisation. "
                    "The existing payment is retained and parcels remain awaiting collection."
                )
            if authorised:
                return "Pickup recorded. Payment outcome saved; no bank transaction was performed."
            
            # Amount Did Not Match it was Picked Up, but Flagged for Office Staff
            return (
                f"Pickup recorded with a payment exception (received AUD {payment.received_amount} of quoted AUD {payment.quoted_amount}). Flagged for Office Staff to authorise before delivery."
            )
        return self._change(collect)

    def authorise_payment(self, request_id: str, authorised_by: str, reason: str) -> None:
        def approve() -> None:
            request = self._request(request_id)
            if request.status not in {RequestStatus.ALLOCATED, RequestStatus.PICKED_UP} or request.payment is None:
                raise DomainError("Only an allocated or picked-up request with a payment exception can be authorised.")
            
            if not request.payment.exception:
                raise DomainError("This payment matches the quote and needs no exception authorisation.")
            request.payment.authorise(authorised_by, reason)

        self._change(approve)

    def deliver(
        self, request_id: str, staff_id: str, successful: bool,
        reason: str = "", *, failure: str | None = None,
        parcel_id: str | None = None,
    ) -> str:
        """Record a delivery outcome reported by the allocated worker.

        For a failed delivery, failure is one of delivery_failure_reasons()
        and reason holds optional details. Without a failure value, reason
        is required and recorded as the full failure text.
        """
        def finish() -> str:
            request = self._request(request_id)
            request.record_delivery(
                staff_id, successful, reason, self._clock(),
                failure=failure, parcel_id=parcel_id,
            )
            if successful:
                return "Delivery completed and its assignment ended."
            return (
                f"{request.failure_reason} Payment retained; "
                "parcels flagged for return to depot."
            )

        return self._change(finish)

    def check_failed_delivery(
        self, request_id: str, reason: str = "", *,
        failure: str | None = None, parcel_id: str | None = None,
    ) -> str:
        """Validate a failed delivery report without saving anything.

        Returns the failure text that deliver() would record. Raises
        DomainError when the reason, parcel or details are invalid.
        """
        request = self._request(request_id)
        return request.delivery_failure_text(failure, parcel_id, reason)

    @staticmethod
    def delivery_failure_reasons() -> list[str]:
        """Return the failed delivery reasons offered to delivery staff."""
        reasons = []
        for failure in DeliveryFailure:
            reasons.append(failure.value)
        return reasons

    def retry_pickup(self, request_id: str) -> None:
        self._change(lambda: self._request(request_id).retry_pickup())

    def reject_request(self, request_id: str, reason: str) -> None:
        """Record an office decision that YOWD cannot fulfil a request.

        DeliveryRequest only allows this before a quote is issued, and the
        reason is required. The reason is kept with the rejected request.
        """
        def reject() -> None:
            request = self._request(request_id)
            request.reject(reason)

        self._change(reject)

    def statistics(
        self, start: date, end: date, staff_id: str | None = None,
    ) -> dict:
        """Summarise outcomes for all staff, or for one given worker."""
        return DeliveryStatistics.summarise(
            self.requests.values(), self.staff_list, start, end, staff_id,
        )

    def statistics_report(
        self, start: date, end: date, staff_id: str | None,
        period_name: str, scope_label: str,
    ) -> str:
        """Return the statistics summary text built by DeliveryStatistics."""
        result = self.statistics(start, end, staff_id)
        lines = DeliveryStatistics.format_summary(
            result, period_name, start, end, scope_label,
        )
        return "\n".join(lines)

    @staticmethod
    def statistics_periods() -> tuple[str, ...]:
        """Return the named reporting periods for the statistics screen."""
        return REPORTING_PERIODS

    def statistics_period_range(
        self, period_name: str, reference_date: date | None = None,
    ) -> tuple[date, date]:
        """Return the inclusive dates of a named reporting period.

        The application clock's current date is used when no reference
        date is given.
        """
        if reference_date is None:
            reference_date = self._clock().date()
        return DeliveryStatistics.period_range(period_name, reference_date)

    def statistics_staff_choices(self) -> list[tuple[str, str]]:
        """Return (staff ID, label) pairs for current and former workers."""
        choices = []
        for worker in self.staff_list.staff.values():
            if worker.active:
                label = worker.name
            else:
                label = f"{worker.name} (former)"
            choices.append((worker.staff_id, label))
        return choices

    def overview(self) -> dict:
        rows = []
        counts: dict[str, int] = {}
        for request in self.requests.values():
            counts[request.status.value] = counts.get(request.status.value, 0) + 1
            # The list reads the request's own tracking view (A2 section 3.7).
            tracking = request.tracking_info()
            # The worker is the one on the latest assignment. "(ended)" marks
            # a worker whose assignment has finished.
            worker_text = ""
            if tracking["latest_staff_id"] is not None:
                worker = self.staff_list.staff.get(tracking["latest_staff_id"])
                if worker is not None:
                    worker_text = worker.name
                if tracking["active_staff_id"] is None:
                    worker_text += " (ended)"
            delivery_due = ""
            if tracking["quoted_delivery"] is not None:
                delivery_due = f"{tracking['quoted_delivery']:%Y-%m-%d %H:%M}"
            rows.append({
                "id": request.request_id,
                "customer": request.customer.name,
                "pickup": request.pickup,
                "destination": request.destination,
                "pickup_address": request.pickup_address,
                "destination_address": request.destination_address,
                "status": request.status.value,
                "quote_amount": str(request.quote.amount) if request.quote else "",
                "worker": worker_text,
                "delivery_due": delivery_due,
                "payment": (
                    "Authorised exception" if request.payment.exception and request.payment.allows_pickup
                    else "Exception awaiting authorisation" if request.payment.exception
                    else "Recorded"
                ) if request.payment else "",
                "received_amount": str(request.payment.received_amount) if request.payment else "",
                "payment_authorised": bool(request.payment and request.payment.authorised_by),
                "payment_exception": bool(request.payment and request.payment.exception),
            })
        staff_rows = [{
            "id": worker.staff_id,
            "name": worker.name,
            "active": worker.active,
            "availability": "; ".join(
                f"{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M}"
                for start, end in worker.schedule.periods
            ) or "No availability",
        } for worker in self.staff_list.staff.values()]
        return {
            "requests": rows, "staff": staff_rows, "counts": counts,
            "storage_path": str(self.store.path),
        }

    def request_details(self, request_id: str) -> str:
        request = self._request(request_id)
        lines = [
            f"Request: {request.request_id}",
            f"Customer: {request.customer.name} ({request.customer.customer_id})",
            f"Contact: {request.customer.email} | {request.customer.phone}",
            f"Route: {request.pickup} to {request.destination}",
            f"Pickup address: {request.pickup_address or 'Not recorded'}",
            f"Destination address: {request.destination_address or 'Not recorded'}",
            f"Status: {request.status.value}",
            f"Lodged: {request.created_at:%Y-%m-%d %H:%M}",
            "Actual pickup: " + (
                f"{request.picked_up_at:%Y-%m-%d %H:%M}"
                if request.picked_up_at else "Not recorded"
            ),
            "", "Parcels:",
        ]
        for parcel in request.parcels:
            parcel_line = (
                f"  {parcel.description}: {parcel.weight_kg} kg, "
                f"{parcel.length_cm} x {parcel.width_cm} x {parcel.height_cm} cm; "
                f"{parcel.status.value}"
            )
            # A recorded parcel exception is shown on that parcel's line.
            if parcel.has_exception:
                parcel_line += f"; exception: {parcel.exception}"
            lines.append(parcel_line)
        if request.quote:
            quote = request.quote
            lines.extend([
                "", f"Current quote: AUD {quote.amount} | {quote.decision.value}",
                f"  Pickup estimate: {quote.pickup_at:%Y-%m-%d %H:%M}",
                f"  Delivery estimate: {quote.delivery_at:%Y-%m-%d %H:%M}",
            ])
            # Tariff Breakdown Line
            try:
                lines.append(f"  Tariff Working: {self.tariff.explain(request)}")
            except DomainError:
                pass
        lines.extend(["", "Assignments (retained history):"])
        if not request.assignments:
            lines.append("  None")
        for assignment in request.assignments:
            worker = self.staff_list.get(assignment.staff_id)
            outcome = "Active" if assignment.active else assignment.outcome
            lines.append(f"  {assignment.assignment_id}: {worker.name}; {outcome}")
            lines.append(f"    Started: {assignment.started_at:%Y-%m-%d %H:%M}")
            lines.append("    Ended: " + (
                f"{assignment.ended_at:%Y-%m-%d %H:%M}"
                if assignment.ended_at else "Active"
            ))
            if assignment.outcome_details:
                lines.append(f"    Outcome details: {assignment.outcome_details}")
        if request.payment:
            payment = request.payment
            lines.extend([
                "", f"Payment outcome: quoted AUD {payment.quoted_amount}; "
                f"received AUD {payment.received_amount}",
                f"  Exception: {'Yes' if payment.exception else 'No'}",
                f"  Authorised by: {payment.authorised_by or 'Not authorised'}",
            ])
            if payment.authorisation_reason:
                lines.append(f"  Authorisation reason: {payment.authorisation_reason}")
        if request.failure_reason:
            lines.extend(["", f"Exception/rejection: {request.failure_reason}"])
        if request.completed_at:
            lines.append(f"Completed: {request.completed_at:%Y-%m-%d %H:%M}")
        return "\n".join(lines)

    def seed_demo(self) -> None:
        """Explicit sample loading is allowed only into a completely empty store."""
        if self.customers or self.staff_list.staff or self.requests:
            raise DomainError("Sample data can be loaded only into an empty application.")

        def seed() -> None:
            now = self._clock()
            day = next_operating_day(now)
            start = datetime.combine(day, OPEN)
            worker = DeliveryStaff(_identifier("STA"), "Sample Driver", "driver@example.com", "0400000001")
            worker.schedule.add_period(start, datetime.combine(day, CLOSE))
            self.staff_list.register(worker)
            customer = Customer(_identifier("CUS"), "Sample Customer", "customer@example.com", "0400000002")
            parcels = [
                Parcel(_identifier("PAR"), "Books", Decimal("2"), Decimal("20"), Decimal("15"), Decimal("10")),
                Parcel(_identifier("PAR"), "Clothing", Decimal("1"), Decimal("20"), Decimal("15"), Decimal("10")),
            ]
            request = DeliveryRequest(
                _identifier("REQ"), customer, "Richmond", "Footscray", parcels, now,
                pickup_address="12 Bridge Road", destination_address="8 Hopkins Street",
            )
            self.customers[customer.customer_id] = customer
            self.requests[request.request_id] = request

        self._change(seed)
