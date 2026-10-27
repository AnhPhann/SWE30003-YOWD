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
    RequestStatus,
    StaffList,
)
from .pricing import SERVICE_ZONES, TariffPolicy, normalise_suburb
from .models.common import require_text
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

    def register_staff(
        self, name: str, email: str, phone: str,
        available_from: datetime, available_until: datetime,
    ) -> str:
        def register() -> str:
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

    def set_availability(
        self, staff_id: str, periods: list[tuple[datetime, datetime]],
    ) -> None:
        def update() -> None:
            schedule = AvailabilitySchedule()
            for start, end in periods:
                schedule.add_period(start, end)
            self.staff_list.get(staff_id).schedule = schedule

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
                if delivery_at <= end:
                    windows.append((pickup_at, delivery_at))
        if not windows:
            raise DomainError(
                "No active worker's availability covers a suggested delivery window. "
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

    def allocate(self, request_id: str, staff_id: str) -> None:
        def assign() -> None:
            request = self._request(request_id)
            worker = self.staff_list.get(staff_id)
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
            if request.payment is not None:
                payment = request.payment
                if payment.received_amount != amount:
                    raise DomainError(
                        "A payment outcome is already recorded. Use the same received amount; "
                        "record business authorisation separately if needed."
                    )
            else:
                payment = PaymentRecord(
                    _identifier("PAY"), request_id, request.quote.amount,
                    amount, self._clock(),
                )
            completed = request.record_pickup(staff_id, True, payment, self._clock())
            if completed:
                return "Pickup recorded. Payment outcome saved; no bank transaction was performed."
            return (
                "Payment exception recorded. The request remains Allocated. Office staff must record authorisation before the assigned worker confirms pickup."
            )

        return self._change(collect)

    def authorise_payment(self, request_id: str, authorised_by: str, reason: str) -> None:
        def approve() -> None:
            request = self._request(request_id)
            if request.status != RequestStatus.ALLOCATED or request.payment is None:
                raise DomainError("Only an allocated request with a pending payment exception can be authorised.")
            if not request.payment.exception:
                raise DomainError("This payment matches the quote and needs no exception authorisation.")
            request.payment.authorise(authorised_by, reason)

        self._change(approve)

    def deliver(
        self, request_id: str, staff_id: str, successful: bool, reason: str = "",
    ) -> str:
        def finish() -> str:
            request = self._request(request_id)
            request.record_delivery(staff_id, successful, reason, self._clock())
            if successful:
                return "Delivery completed and its assignment ended."
            return "Failed delivery recorded. Payment retained; parcels flagged for return to depot."

        return self._change(finish)

    def retry_pickup(self, request_id: str) -> None:
        self._change(lambda: self._request(request_id).retry_pickup())

    def statistics(self, start: date, end: date) -> dict:
        return DeliveryStatistics.summarise(
            self.requests.values(), self.staff_list, start, end,
        )

    def overview(self) -> dict:
        rows = []
        counts: dict[str, int] = {}
        for request in self.requests.values():
            counts[request.status.value] = counts.get(request.status.value, 0) + 1
            assignment = request.active_assignment
            if assignment is None and request.assignments:
                assignment = request.assignments[-1]
            worker = self.staff_list.staff.get(assignment.staff_id) if assignment else None
            rows.append({
                "id": request.request_id,
                "customer": request.customer.name,
                "pickup": request.pickup,
                "destination": request.destination,
                "pickup_address": request.pickup_address,
                "destination_address": request.destination_address,
                "status": request.status.value,
                "quote_amount": str(request.quote.amount) if request.quote else "",
                "worker": worker.name if worker else "",
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
            "", "Parcels:",
        ]
        for parcel in request.parcels:
            lines.append(
                f"  {parcel.description}: {parcel.weight_kg} kg, "
                f"{parcel.length_cm} x {parcel.width_cm} x {parcel.height_cm} cm; "
                f"{parcel.status.value}"
            )
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
            start = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
            worker = DeliveryStaff(_identifier("STA"), "Sample Driver", "driver@example.com", "0400000001")
            worker.schedule.add_period(start, start.replace(hour=18))
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
