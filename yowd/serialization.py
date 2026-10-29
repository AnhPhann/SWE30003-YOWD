"""Write version-two domain snapshots and read both current and legacy snapshots.

Money and measurements use decimal strings; timestamps use naive local ISO
datetimes. Staff schedules are lists of [start, end] timestamp pairs. Requests
own their parcels, offer, retained assignments and payment. Customer and worker
indexes are checked against that graph rather than silently repaired. Historical
allocations are not reassessed against a worker's current employment or hours.
Legacy version-one requests retain unknown addresses as blank pairs. Loading
never writes or invents street addresses from a suburb name.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import (
    AvailabilitySchedule, Customer, DeliveryAssignment, DeliveryQuote,
    DeliveryRequest, DeliveryStaff, DomainError, Parcel, ParcelStatus, PaymentRecord,
    QuoteDecision, RequestStatus, StaffList,
)
from .storage import SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS, StorageError


def _object(value: Any, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise StorageError(f"{label} must be an object.")
    missing, extra = fields - value.keys(), value.keys() - fields
    if missing:
        raise StorageError(f"{label} is missing fields: {', '.join(sorted(missing))}.")
    if extra:
        raise StorageError(f"{label} has unsupported fields: {', '.join(map(str, extra))}.")
    return value


def _list(value: Any, label: str) -> list:
    if not isinstance(value, list):
        raise StorageError(f"{label} must be a list.")
    return value


def _text(value: Any, label: str, *, blank: bool = False) -> str:
    if not isinstance(value, str) or (not blank and not value.strip()):
        raise StorageError(f"{label} must be {'a string' if blank else 'nonempty text'}.")
    return value


def _identifier(value: Any, label: str) -> str:
    value = _text(value, label)
    if value != value.strip():
        raise StorageError(f"{label} cannot have surrounding whitespace.")
    return value


def _ids(value: Any, label: str) -> list[str]:
    result = [_identifier(item, label) for item in _list(value, label)]
    if len(result) != len(set(result)):
        raise StorageError(f"{label} contains duplicate IDs.")
    return result


def _decimal(value: Any, label: str) -> Decimal:
    if not isinstance(value, str):
        raise StorageError(f"{label} must be a decimal string.")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise StorageError(f"{label} is not a valid decimal.") from exc
    if not number.is_finite():
        raise StorageError(f"{label} must be finite.")
    return number


def _time(value: Any, label: str, *, optional: bool = False) -> datetime | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or "T" not in value:
        raise StorageError(f"{label} must be an ISO local date and time.")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise StorageError(f"{label} is not a valid ISO date and time.") from exc
    if result.tzinfo is not None:
        raise StorageError(f"{label} must not include a timezone.")
    return result


def _construct(cls: type, fields: dict, label: str) -> Any:
    try:
        return cls(**fields)
    except (DomainError, TypeError, ValueError) as exc:
        raise StorageError(f"Invalid {label}: {exc}") from exc


def _unique(seen: set[str], value: str, label: str) -> None:
    if value in seen:
        raise StorageError(f"Duplicate {label} ID: {value}.")
    seen.add(value)


def _decode_quote(value: Any, seen: set[str]) -> DeliveryQuote | None:
    if value is None:
        return None
    row = _object(value, {
        "quote_id", "request_id", "amount", "pickup_at", "delivery_at", "issued_at", "decision",
    }, "Quote")
    fields = {
        key: _identifier(row[key], f"Quote {key}") for key in ("quote_id", "request_id")
    }
    _unique(seen, fields["quote_id"], "quote")
    fields.update(amount=_decimal(row["amount"], "Quote amount"))
    fields.update({key: _time(row[key], f"Quote {key}") for key in (
        "pickup_at", "delivery_at", "issued_at",
    )})
    fields["decision"] = _text(row["decision"], "Quote decision")
    return _construct(DeliveryQuote, fields, "quote")


def _decode_payment(value: Any, seen: set[str]) -> PaymentRecord | None:
    if value is None:
        return None
    row = _object(value, {
        "payment_id", "request_id", "quoted_amount", "received_amount", "received_at",
        "authorised_by", "authorisation_reason",
    }, "Payment")
    fields = {
        key: _identifier(row[key], f"Payment {key}") for key in ("payment_id", "request_id")
    }
    _unique(seen, fields["payment_id"], "payment")
    fields.update({key: _decimal(row[key], f"Payment {key}") for key in (
        "quoted_amount", "received_amount",
    )})
    fields["received_at"] = _time(row["received_at"], "Payment received_at")
    fields.update({key: _text(row[key], f"Payment {key}", blank=True) for key in (
        "authorised_by", "authorisation_reason",
    )})
    return _construct(PaymentRecord, fields, "payment")


def _decode_parcels(value: Any, seen: set[str]) -> list[Parcel]:
    parcels = []
    for row in _list(value, "Request parcels"):
        row = _object(row, {
            "parcel_id", "description", "weight_kg", "length_cm", "width_cm", "height_cm", "status",
        }, "Parcel")
        parcel_id = _identifier(row["parcel_id"], "Parcel ID")
        _unique(seen, parcel_id, "parcel")
        fields = {
            "parcel_id": parcel_id,
            "description": _text(row["description"], "Parcel description"),
            "status": _text(row["status"], "Parcel status"),
        }
        fields.update({key: _decimal(row[key], f"Parcel {key}") for key in (
            "weight_kg", "length_cm", "width_cm", "height_cm",
        )})
        parcels.append(_construct(Parcel, fields, "parcel"))
    return parcels


def _decode_assignments(value: Any, seen: set[str]) -> list[DeliveryAssignment]:
    assignments = []
    for row in _list(value, "Request assignments"):
        row = _object(row, {
            "assignment_id", "request_id", "staff_id", "started_at", "ended_at", "outcome",
        }, "Assignment")
        fields = {key: _identifier(row[key], f"Assignment {key}") for key in (
            "assignment_id", "request_id", "staff_id",
        )}
        _unique(seen, fields["assignment_id"], "assignment")
        fields.update(
            started_at=_time(row["started_at"], "Assignment start"),
            ended_at=_time(row["ended_at"], "Assignment end", optional=True),
            outcome=_text(row["outcome"], "Assignment outcome", blank=True),
        )
        assignments.append(_construct(DeliveryAssignment, fields, "assignment"))
    return assignments


def _check_lifecycle(request: DeliveryRequest) -> None:
    label = f"Request {request.request_id}"

    def require(condition: bool, explanation: str) -> None:
        if not condition:
            raise StorageError(f"{label}: {explanation}.")

    status = request.status
    quote, payment = request.quote, request.payment
    assignments = request.assignments
    active = request.active_assignment
    initial = {RequestStatus.REQUESTED, RequestStatus.REJECTED}
    before_allocation = initial | {RequestStatus.QUOTED, RequestStatus.QUOTE_DECLINED}
    after_pickup = {RequestStatus.PICKED_UP, RequestStatus.DELIVERED, RequestStatus.FAILED_DELIVERY}

    if status in initial:
        require(quote is None, "an unquoted request cannot have a quote")
    else:
        require(quote is not None, "this status requires a quote")
        expected = {
            RequestStatus.QUOTED: QuoteDecision.PENDING,
            RequestStatus.QUOTE_DECLINED: QuoteDecision.DECLINED,
        }.get(status, QuoteDecision.ACCEPTED)
        require(quote.decision == expected, "quote decision does not match request status")
    if quote is not None:
        require(quote.issued_at >= request.created_at, "quote predates request creation")

    if status in before_allocation:
        require(not assignments, "this status cannot have retained assignments")
    if status in {RequestStatus.ALLOCATED, RequestStatus.PICKED_UP}:
        require(active is not None, "this status requires one active assignment")
    else:
        require(active is None, "this status cannot have an active assignment")
    if status in {RequestStatus.FAILED_PICKUP, RequestStatus.DELIVERED, RequestStatus.FAILED_DELIVERY}:
        require(bool(assignments), "this outcome requires an ended assignment")
        require(assignments[-1].outcome == status.value, "last assignment outcome does not match status")

    previous = None
    for index, assignment in enumerate(assignments):
        require(assignment.started_at >= request.created_at, "assignment predates request creation")
        if quote is not None:
            require(assignment.started_at >= quote.issued_at, "assignment predates quote issue")
        if previous is not None:
            require(previous.ended_at is not None and assignment.started_at >= previous.ended_at,
                    "retained assignments overlap or are out of order")
        if assignment.ended_at is not None:
            permitted = {RequestStatus.FAILED_PICKUP.value}
            if index == len(assignments) - 1 and status in after_pickup:
                permitted.add(status.value)
            require(assignment.outcome in permitted, "unsupported historical assignment outcome")
        previous = assignment

    expected_parcel = {
        RequestStatus.PICKED_UP: ParcelStatus.COLLECTED,
        RequestStatus.DELIVERED: ParcelStatus.DELIVERED,
        RequestStatus.FAILED_DELIVERY: ParcelStatus.RETURN_REQUIRED,
    }.get(status, ParcelStatus.PENDING)
    require(all(parcel.status == expected_parcel for parcel in request.parcels),
            "parcel states do not match the request status")

    if status not in after_pickup:
        require(request.picked_up_at is None and request.completed_at is None,
                "pickup or completion timestamp is inconsistent with status")
    else:
        require(request.picked_up_at is not None, "a recorded pickup time is required")

        # A Picked Up Request can Hold a Payment Exception as it is Awaiting Office Authorisation
        require(payment is not None, "pickup requires a payment record")
        if status != RequestStatus.PICKED_UP:
            require(payment.allows_pickup,
                    "delivery requires matching payment or recorded business authorisation")
            
        require(request.picked_up_at >= assignments[-1].started_at,
                "pickup predates its assignment")
    if status == RequestStatus.DELIVERED:
        require(request.completed_at is not None, "delivered request requires completion time")
        require(assignments[-1].ended_at == request.completed_at,
                "assignment end must match delivery completion")
    else:
        require(request.completed_at is None, "only delivered requests have a completion timestamp")
    if status == RequestStatus.FAILED_DELIVERY:
        require(assignments[-1].ended_at >= request.picked_up_at,
                "failed delivery predates pickup")
    if status in {RequestStatus.REJECTED, RequestStatus.FAILED_PICKUP, RequestStatus.FAILED_DELIVERY}:
        require(bool(request.failure_reason.strip()), "failure or rejection requires a reason")
    else:
        require(not request.failure_reason, "non-failed request cannot retain a failure reason")

    if payment is not None:
        require(status in after_pickup | {RequestStatus.ALLOCATED},
                "this status cannot have a payment record")
        require(quote is not None and payment.quoted_amount == quote.amount,
                "payment quoted amount differs from the accepted quote")
        require(bool(assignments) and payment.received_at >= assignments[-1].started_at,
                "payment predates its assignment")
        if request.picked_up_at is not None:
            require(payment.received_at <= request.picked_up_at, "payment was recorded after pickup")


def decode_state(snapshot: dict) -> tuple[dict[str, Customer], StaffList, dict[str, DeliveryRequest]]:
    """Restore and validate an untrusted snapshot without changing its contents."""
    snapshot = _object(snapshot, {"schema_version", "customers", "staff", "requests"}, "Snapshot")
    version = snapshot["schema_version"]
    if type(version) is not int or version not in SUPPORTED_SCHEMA_VERSIONS:
        raise StorageError("Unsupported snapshot schema version; expected 1 or 2.")

    customers: dict[str, Customer] = {}
    declared_requests: dict[str, list[str]] = {}
    for row in _list(snapshot["customers"], "Customers"):
        row = _object(row, {"customer_id", "name", "email", "phone", "request_ids"}, "Customer")
        customer_id = _identifier(row["customer_id"], "Customer ID")
        if customer_id in customers:
            raise StorageError(f"Duplicate customer ID: {customer_id}.")
        request_ids = _ids(row["request_ids"], f"Customer {customer_id} request_ids")
        fields = {key: _text(row[key], f"Customer {key}") for key in ("name", "email", "phone")}
        customers[customer_id] = _construct(Customer, {
            "customer_id": customer_id, **fields, "request_ids": request_ids,
        }, "customer")
        declared_requests[customer_id] = request_ids.copy()

    workers: dict[str, DeliveryStaff] = {}
    for row in _list(snapshot["staff"], "Staff"):
        row = _object(row, {
            "staff_id", "name", "email", "phone", "active", "schedule", "assignment_ids",
        }, "Staff member")
        staff_id = _identifier(row["staff_id"], "Staff ID")
        if staff_id in workers:
            raise StorageError(f"Duplicate staff ID: {staff_id}.")
        if type(row["active"]) is not bool:
            raise StorageError(f"Staff {staff_id} active must be true or false.")
        periods = []
        for period in _list(row["schedule"], "Staff schedule"):
            if not isinstance(period, list) or len(period) != 2:
                raise StorageError("Each staff schedule period must be a [start, end] list.")
            periods.append((_time(period[0], "Schedule start"), _time(period[1], "Schedule end")))
        schedule = _construct(AvailabilitySchedule, {"periods": periods}, "availability schedule")
        workers[staff_id] = _construct(DeliveryStaff, {
            "staff_id": staff_id,
            **{key: _text(row[key], f"Staff {key}") for key in ("name", "email", "phone")},
            "active": row["active"], "schedule": schedule,
            "assignment_ids": _ids(row["assignment_ids"], f"Staff {staff_id} assignment_ids"),
        }, "staff member")

    requests: dict[str, DeliveryRequest] = {}
    seen = {kind: set() for kind in ("parcel", "quote", "assignment", "payment")}
    graph_requests = {customer_id: set() for customer_id in customers}
    graph_assignments = {staff_id: set() for staff_id in workers}
    for row in _list(snapshot["requests"], "Requests"):
        fields = {
            "request_id", "customer_id", "pickup", "destination", "parcels", "created_at", "status",
            "quote", "assignments", "payment", "picked_up_at", "completed_at", "failure_reason",
        }
        if version == 2:
            fields.update({"pickup_address", "destination_address"})
        row = _object(row, fields, "Request")
        request_id = _identifier(row["request_id"], "Request ID")
        customer_id = _identifier(row["customer_id"], "Request customer ID")
        if request_id in requests:
            raise StorageError(f"Duplicate request ID: {request_id}.")
        if customer_id not in customers:
            raise StorageError(f"Request {request_id} refers to an unknown customer: {customer_id}.")
        request = _construct(DeliveryRequest, {
            "request_id": request_id, "customer": customers[customer_id],
            "pickup": _text(row["pickup"], "Pickup suburb"),
            "destination": _text(row["destination"], "Destination suburb"),
            "pickup_address": (
                _text(row["pickup_address"], "Pickup address", blank=True) if version == 2 else ""
            ),
            "destination_address": (
                _text(row["destination_address"], "Destination address", blank=True) if version == 2 else ""
            ),
            "parcels": _decode_parcels(row["parcels"], seen["parcel"]),
            "created_at": _time(row["created_at"], "Request creation"),
            "status": _text(row["status"], "Request status"),
            "quote": _decode_quote(row["quote"], seen["quote"]),
            "assignments": _decode_assignments(row["assignments"], seen["assignment"]),
            "payment": _decode_payment(row["payment"], seen["payment"]),
            "picked_up_at": _time(row["picked_up_at"], "Pickup time", optional=True),
            "completed_at": _time(row["completed_at"], "Completion time", optional=True),
            "failure_reason": _text(row["failure_reason"], "Failure reason", blank=True),
        }, f"request {request_id}")
        _check_lifecycle(request)
        requests[request_id] = request
        graph_requests[customer_id].add(request_id)
        for assignment in request.assignments:
            if assignment.staff_id not in workers:
                raise StorageError(f"Assignment {assignment.assignment_id} refers to unknown staff.")
            graph_assignments[assignment.staff_id].add(assignment.assignment_id)

    for customer_id, expected in graph_requests.items():
        if set(declared_requests[customer_id]) != expected:
            raise StorageError(f"Customer {customer_id} request_ids do not match the request graph.")
    for staff_id, expected in graph_assignments.items():
        if set(workers[staff_id].assignment_ids) != expected:
            raise StorageError(f"Staff {staff_id} assignment_ids do not match the request graph.")
    return customers, StaffList(workers), requests


def _encode_time(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise StorageError("Snapshot timestamps must be naive local datetimes.")
    return value.isoformat()


def encode_state(
    customers: dict[str, Customer], staff_list: StaffList,
    requests: dict[str, DeliveryRequest],
) -> dict:
    """Create primitives and validate a separate restored graph, never live objects."""
    if not isinstance(customers, dict) or not isinstance(requests, dict) or not isinstance(staff_list, StaffList):
        raise StorageError("State requires customer/request dictionaries and a StaffList.")
    if not isinstance(staff_list.staff, dict):
        raise StorageError("The staff roster must contain a dictionary of workers.")
    for key, customer in customers.items():
        if not isinstance(customer, Customer) or key != customer.customer_id:
            raise StorageError("Customer dictionary keys must match their customer IDs.")
    for key, worker in staff_list.staff.items():
        if not isinstance(worker, DeliveryStaff) or key != worker.staff_id:
            raise StorageError("Staff dictionary keys must match their staff IDs.")
    for key, request in requests.items():
        if not isinstance(request, DeliveryRequest) or key != request.request_id:
            raise StorageError("Request dictionary keys must match their request IDs.")
        if not isinstance(request.customer, Customer) or customers.get(
            request.customer.customer_id
        ) is not request.customer:
            raise StorageError("Requests must reference the registered shared Customer object.")
    try:
        customer_rows = [{
            "customer_id": customer.customer_id, "name": customer.name,
            "email": customer.email, "phone": customer.phone, "request_ids": list(customer.request_ids),
        } for customer in customers.values()]
        staff_rows = [{
            "staff_id": worker.staff_id, "name": worker.name, "email": worker.email,
            "phone": worker.phone, "active": worker.active,
            "assignment_ids": list(worker.assignment_ids),
            "schedule": [[_encode_time(start), _encode_time(end)] for start, end in worker.schedule.periods],
        } for worker in staff_list.staff.values()]
        request_rows = []
        for request in requests.values():
            quote, payment = request.quote, request.payment
            request_rows.append({
                "request_id": request.request_id, "customer_id": request.customer.customer_id,
                "pickup": request.pickup, "destination": request.destination,
                "pickup_address": request.pickup_address,
                "destination_address": request.destination_address,
                "created_at": _encode_time(request.created_at), "status": RequestStatus(request.status).value,
                "picked_up_at": _encode_time(request.picked_up_at),
                "completed_at": _encode_time(request.completed_at), "failure_reason": request.failure_reason,
                "parcels": [{
                    "parcel_id": parcel.parcel_id, "description": parcel.description,
                    **{key: str(getattr(parcel, key)) for key in (
                        "weight_kg", "length_cm", "width_cm", "height_cm",
                    )},
                    "status": ParcelStatus(parcel.status).value,
                } for parcel in request.parcels],
                "quote": None if quote is None else {
                    "quote_id": quote.quote_id, "request_id": quote.request_id, "amount": str(quote.amount),
                    "pickup_at": _encode_time(quote.pickup_at), "delivery_at": _encode_time(quote.delivery_at),
                    "issued_at": _encode_time(quote.issued_at), "decision": QuoteDecision(quote.decision).value,
                },
                "assignments": [{
                    "assignment_id": assignment.assignment_id, "request_id": assignment.request_id,
                    "staff_id": assignment.staff_id, "started_at": _encode_time(assignment.started_at),
                    "ended_at": _encode_time(assignment.ended_at), "outcome": assignment.outcome,
                } for assignment in request.assignments],
                "payment": None if payment is None else {
                    "payment_id": payment.payment_id, "request_id": payment.request_id,
                    "quoted_amount": str(payment.quoted_amount), "received_amount": str(payment.received_amount),
                    "received_at": _encode_time(payment.received_at), "authorised_by": payment.authorised_by,
                    "authorisation_reason": payment.authorisation_reason,
                },
            })
    except (AttributeError, TypeError, ValueError) as exc:
        raise StorageError(f"Cannot encode the domain state: {exc}") from exc
    snapshot = {
        "schema_version": SCHEMA_VERSION, "customers": customer_rows,
        "staff": staff_rows, "requests": request_rows,
    }
    decode_state(snapshot)
    return snapshot
