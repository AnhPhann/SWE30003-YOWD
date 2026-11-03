"""Snapshot graph validation without writing to any real user database."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import json
import unittest

from yowd.models import (
    AvailabilitySchedule, Customer, DeliveryQuote, DeliveryRequest, DeliveryStaff,
    Parcel, PaymentRecord, RequestStatus, StaffList,
)
from yowd.serialization import decode_state, encode_state
from yowd.storage import SCHEMA_VERSION, StorageError


START = datetime(2026, 10, 22, 9)


def build_request(customer, worker, suffix="1", stage="Delivered", history=False):
    request = DeliveryRequest(
        f"R{suffix}", customer, "Richmond", "Footscray",
        [Parcel(f"P{suffix}", "Books", Decimal("2.50"), Decimal("20"), Decimal("15"), Decimal("10"))],
        START,
    )
    if stage == "Requested":
        return request
    if stage == "Rejected":
        request.status, request.failure_reason = RequestStatus.REJECTED, "Outside service area"
        return request
    quote = DeliveryQuote(
        f"Q{suffix}", request.request_id, Decimal("25.00"), START + timedelta(hours=1),
        START + timedelta(hours=2), START + timedelta(minutes=5),
    )
    request.issue_quote(quote)
    if stage == "Quoted":
        return request
    request.respond_to_quote(customer.customer_id, stage != "Quote declined")
    if stage == "Quote declined":
        return request
    if history:
        request.allocate(worker, f"A{suffix}-old", START + timedelta(minutes=10))
        request.record_pickup(worker.staff_id, False, None, START + timedelta(minutes=20))
        request.retry_pickup()
    if stage == "Accepted":
        return request
    request.allocate(worker, f"A{suffix}", START + timedelta(minutes=30))
    if stage == "Allocated":
        return request
    if stage == "Failed pickup":
        request.record_pickup(worker.staff_id, False, None, START + timedelta(minutes=40))
        return request
    payment = PaymentRecord(
        f"PAY{suffix}", request.request_id, quote.amount, Decimal("20.00"),
        START + timedelta(hours=1), "Business owner", "Approved account adjustment",
    )
    request.record_pickup(worker.staff_id, True, payment, START + timedelta(hours=1, minutes=5))
    if stage == "Picked Up":
        return request
    request.record_delivery(
        worker.staff_id, stage == "Delivered", "Recipient unavailable", START + timedelta(hours=2),
    )
    return request


def make_graph(stage="Delivered", *, history=False, two_requests=False):
    customer = Customer("C1", "Anh Phan", "anh@example.com", "0412345678")
    worker = DeliveryStaff(
        "S1", "Worker", "worker@example.com", "0498765432",
        schedule=AvailabilitySchedule([(START - timedelta(hours=1), START + timedelta(hours=9))]),
    )
    request = build_request(customer, worker, stage=stage, history=history)
    requests = {request.request_id: request}
    if two_requests:
        second = build_request(customer, worker, suffix="2", stage=stage, history=history)
        requests[second.request_id] = second
    return {customer.customer_id: customer}, StaffList({worker.staff_id: worker}), requests


class SerializationTests(unittest.TestCase):
    def snapshot(self, stage="Delivered", **options):
        return encode_state(*make_graph(stage, **options))

    def assert_invalid(self, snapshot, message=None):
        unchanged = deepcopy(snapshot)
        if message is None:
            with self.assertRaises(StorageError):
                decode_state(snapshot)
        else:
            with self.assertRaisesRegex(StorageError, message):
                decode_state(snapshot)
        self.assertEqual(snapshot, unchanged)

    def test_complete_round_trip_preserves_history_money_and_shared_identity(self):
        customers, staff, requests = make_graph(history=True, two_requests=True)
        staff.deactivate("S1")
        staff.get("S1").schedule.periods.clear()
        snapshot = encode_state(customers, staff, requests)
        restored_customers, restored_staff, restored_requests = decode_state(snapshot)
        self.assertEqual(encode_state(restored_customers, restored_staff, restored_requests), snapshot)
        first, second = restored_requests.values()
        self.assertIs(first.customer, restored_customers["C1"])
        self.assertIs(first.customer, second.customer)
        self.assertIsNot(first.customer, customers["C1"])
        self.assertEqual(len(first.assignments), 2)
        self.assertEqual(first.assignments[0].outcome, "Failed pickup")
        self.assertEqual(first.payment.received_amount, Decimal("20.00"))
        self.assertEqual(first.payment.authorised_by, "Business owner")
        self.assertEqual(first.completed_at, START + timedelta(hours=2))
        self.assertFalse(restored_staff.get("S1").active)
        self.assertEqual(restored_staff.get("S1").schedule.periods, [])

    def test_all_supported_lifecycle_states_round_trip(self):
        for status in RequestStatus:
            with self.subTest(status=status):
                snapshot = self.snapshot(status.value)
                self.assertEqual(encode_state(*decode_state(snapshot)), snapshot)

    def test_empty_graph_round_trips(self):
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "customers": [], "staff": [], "requests": [],
        }
        self.assertEqual(encode_state(*decode_state(snapshot)), snapshot)

    def test_version_three_round_trip_preserves_addresses_and_shared_history(self):
        graph = make_graph(history=True, two_requests=True)
        for request in graph[2].values():
            request.pickup_address = "12 Swan Street"
            request.destination_address = "8 Hopkins Street"
        snapshot = encode_state(*graph)
        self.assertEqual(snapshot["schema_version"], SCHEMA_VERSION)
        self.assertEqual(snapshot["requests"][0]["pickup_address"], "12 Swan Street")
        self.assertEqual(snapshot["requests"][0]["destination_address"], "8 Hopkins Street")
        customers, _, requests = decode_state(snapshot)
        first, second = requests.values()
        self.assertEqual((first.pickup_address, first.destination_address),
                         ("12 Swan Street", "8 Hopkins Street"))
        self.assertIs(first.customer, customers["C1"])
        self.assertIs(first.customer, second.customer)
        self.assertEqual(len(first.assignments), 2)
        self.assertEqual(first.assignments[0].outcome_details,
                         "Required parcels were not all collected in acceptable condition.")
        self.assertEqual(first.assignments[1].outcome_details, "Recipient unavailable")
        self.assertEqual(first.payment.received_amount, Decimal("20.00"))

    def test_version_one_lifecycle_graphs_migrate_without_inventing_addresses(self):
        for status in RequestStatus:
            with self.subTest(status=status):
                legacy = self.snapshot(status.value)
                legacy["schema_version"] = 1
                for row in legacy["requests"]:
                    row.pop("pickup_address", None)
                    row.pop("destination_address", None)
                    for assignment in row["assignments"]:
                        assignment.pop("outcome_details", None)
                before = deepcopy(legacy)
                graph = decode_state(legacy)
                self.assertEqual(legacy, before)
                request = graph[2]["R1"]
                self.assertEqual(getattr(request, "pickup_address", None), "")
                self.assertEqual(getattr(request, "destination_address", None), "")
                self.assertEqual(request.status, status)
                migrated = encode_state(*graph)
                self.assertEqual(migrated["schema_version"], SCHEMA_VERSION)
                self.assertEqual(migrated["requests"][0]["pickup_address"], "")
                self.assertEqual(migrated["requests"][0]["destination_address"], "")
                comparable = deepcopy(migrated)
                comparable["schema_version"] = 1
                for row in comparable["requests"]:
                    del row["pickup_address"], row["destination_address"]
                    for assignment in row["assignments"]:
                        self.assertEqual(assignment.pop("outcome_details"), "")
                self.assertEqual(comparable, legacy)

    def test_version_two_graph_defaults_unknown_assignment_details_without_changing_input(self):
        legacy = self.snapshot(history=True, two_requests=True)
        legacy["schema_version"] = 2
        for row in legacy["requests"]:
            row.update(pickup_address="12 Swan Street", destination_address="8 Hopkins Street")
            for assignment in row["assignments"]:
                assignment.pop("outcome_details", None)
        unchanged = deepcopy(legacy)
        customers, staff, requests = decode_state(legacy)
        self.assertEqual(legacy, unchanged)
        self.assertIs(requests["R1"].customer, customers["C1"])
        self.assertIs(requests["R2"].customer, customers["C1"])
        self.assertEqual(staff.get("S1").assignment_ids, ["A1-old", "A1", "A2-old", "A2"])
        for request in requests.values():
            self.assertEqual(request.pickup_address, "12 Swan Street")
            self.assertEqual([getattr(a, "outcome_details", None) for a in request.assignments], ["", ""])
            self.assertEqual(request.payment.payment_id, f"PAY{request.request_id[1:]}")
        migrated = encode_state(customers, staff, requests)
        self.assertEqual(migrated["schema_version"], SCHEMA_VERSION)
        comparable = deepcopy(migrated)
        comparable["schema_version"] = 2
        for row in comparable["requests"]:
            for assignment in row["assignments"]:
                assignment.pop("outcome_details")
        self.assertEqual(comparable, legacy)

    def test_version_three_requires_text_assignment_details(self):
        for value in (None, 42):
            with self.subTest(value=value):
                snapshot = self.snapshot()
                snapshot["schema_version"] = 3
                snapshot["requests"][0]["assignments"][0]["outcome_details"] = value
                self.assert_invalid(snapshot, "details.*string")
        snapshot = self.snapshot()
        snapshot["schema_version"] = 3
        snapshot["requests"][0]["assignments"][0].pop("outcome_details", None)
        self.assert_invalid(snapshot, "missing fields.*outcome_details")

    def test_version_two_requests_require_both_address_fields(self):
        for field in ("pickup_address", "destination_address"):
            with self.subTest(field=field):
                snapshot = self.snapshot("Requested")
                snapshot["schema_version"] = 2
                snapshot["requests"][0].update(
                    pickup_address="12 Swan Street", destination_address="8 Hopkins Street"
                )
                del snapshot["requests"][0][field]
                self.assert_invalid(snapshot, "missing fields")

    def test_version_two_rejects_partial_and_non_text_addresses(self):
        for pickup, destination in (("12 Swan Street", ""), ("", "8 Hopkins Street"),
                                    (None, "8 Hopkins Street"), ("12 Swan Street", 8)):
            with self.subTest(pickup=pickup, destination=destination):
                snapshot = self.snapshot("Requested")
                snapshot["schema_version"] = 2
                snapshot["requests"][0].update(
                    pickup_address=pickup, destination_address=destination
                )
                self.assert_invalid(snapshot, "address")

    def test_encoding_rejects_partial_addresses_without_mutating_live_graph(self):
        graph = make_graph("Requested")
        request = graph[2]["R1"]
        request.pickup_address, request.destination_address = "12 Swan Street", ""
        with self.assertRaisesRegex(StorageError, "address"):
            encode_state(*graph)
        self.assertEqual((request.pickup_address, request.destination_address), ("12 Swan Street", ""))

    def test_encoding_and_decoding_do_not_mutate_inputs(self):
        graph = make_graph(history=True)
        original_graph = deepcopy(graph)
        snapshot = encode_state(*graph)
        self.assertEqual(graph, original_graph)
        original_snapshot = deepcopy(snapshot)
        decode_state(snapshot)
        self.assertEqual(snapshot, original_snapshot)
        self.assertEqual(json.loads(json.dumps(snapshot)), snapshot)
        self.assertIsInstance(snapshot["requests"][0]["quote"]["amount"], str)

    def test_modern_mismatched_payment_is_retained_after_pickup_awaiting_authorisation(self):
        graph = make_graph("Allocated")
        request = graph[2]["R1"]
        payment = PaymentRecord("PAY1", "R1", Decimal("25"), Decimal("20"), START + timedelta(hours=1))
        self.assertFalse(request.record_pickup("S1", True, payment, START + timedelta(hours=1)))
        snapshot = encode_state(*graph)
        restored = decode_state(snapshot)[2]["R1"]
        self.assertEqual(restored.status, RequestStatus.PICKED_UP)
        self.assertFalse(restored.payment.allows_pickup)
        self.assertEqual(restored.picked_up_at, START + timedelta(hours=1))

    def test_legacy_allocated_pending_payment_remains_allocated_when_decoded(self):
        snapshot = self.snapshot("Allocated")
        snapshot["schema_version"] = 2
        snapshot["requests"][0]["assignments"][0].pop("outcome_details", None)
        snapshot["requests"][0]["payment"] = {
            "payment_id": "LEGACY-PAY", "request_id": "R1", "quoted_amount": "25.00",
            "received_amount": "20.00", "received_at": (START + timedelta(hours=1)).isoformat(),
            "authorised_by": "", "authorisation_reason": "",
        }
        unchanged = deepcopy(snapshot)
        request = decode_state(snapshot)[2]["R1"]
        self.assertEqual(snapshot, unchanged)
        self.assertEqual(request.status, RequestStatus.ALLOCATED)
        self.assertIsNone(request.picked_up_at)
        self.assertEqual(request.payment.payment_id, "LEGACY-PAY")
        self.assertFalse(request.payment.allows_pickup)

    def test_historical_staff_schedule_and_employment_changes_are_allowed(self):
        graph = make_graph("Picked Up", history=True)
        worker = graph[1].get("S1")
        worker.active = False
        worker.schedule.periods.clear()
        restored = decode_state(encode_state(*graph))
        self.assertFalse(restored[1].get("S1").active)
        self.assertIsNotNone(restored[2]["R1"].active_assignment)

    def test_encode_rejects_detached_customer_object(self):
        graph = make_graph("Requested")
        graph[2]["R1"].customer = deepcopy(graph[0]["C1"])
        with self.assertRaisesRegex(StorageError, "shared Customer"):
            encode_state(*graph)

    def test_encode_rejects_mismatched_dictionary_keys(self):
        graph = make_graph("Requested")
        graph[0]["wrong"] = graph[0].pop("C1")
        with self.assertRaisesRegex(StorageError, "keys must match"):
            encode_state(*graph)

    def test_encode_reports_invalid_live_references_as_storage_errors(self):
        graph = make_graph("Requested")
        graph[2]["R1"].customer = None
        with self.assertRaisesRegex(StorageError, "shared Customer"):
            encode_state(*graph)
        graph = make_graph("Requested")
        graph[1].staff = []
        with self.assertRaisesRegex(StorageError, "dictionary of workers"):
            encode_state(*graph)

    def test_missing_fields_and_malformed_collections_are_rejected(self):
        for field in ("customers", "staff", "requests"):
            with self.subTest(field=field):
                snapshot = self.snapshot()
                snapshot[field] = {}
                self.assert_invalid(snapshot, "must be a list")
        snapshot = self.snapshot()
        del snapshot["requests"][0]["created_at"]
        self.assert_invalid(snapshot, "missing fields")
        snapshot = self.snapshot()
        snapshot["extra"] = "must not disappear silently"
        self.assert_invalid(snapshot, "unsupported fields")

    def test_unsupported_schema_versions_are_rejected(self):
        for version in (None, True, "1", 99):
            with self.subTest(version=version):
                snapshot = self.snapshot()
                snapshot["schema_version"] = version
                self.assert_invalid(snapshot, "schema version")

    def test_unknown_statuses_are_rejected(self):
        for owner, field in (("request", "status"), ("parcel", "status"), ("quote", "decision")):
            with self.subTest(owner=owner):
                snapshot = self.snapshot()
                request = snapshot["requests"][0]
                target = request if owner == "request" else request["parcels"][0] if owner == "parcel" else request["quote"]
                target[field] = "Unknown"
                self.assert_invalid(snapshot)

    def test_duplicate_top_level_ids_are_rejected(self):
        for collection in ("customers", "staff", "requests"):
            with self.subTest(collection=collection):
                snapshot = self.snapshot()
                snapshot[collection].append(deepcopy(snapshot[collection][0]))
                self.assert_invalid(snapshot, "Duplicate")

    def test_duplicate_owned_record_ids_across_requests_are_rejected(self):
        for collection, field in (
            ("parcels", "parcel_id"), ("quote", "quote_id"),
            ("assignments", "assignment_id"), ("payment", "payment_id"),
        ):
            with self.subTest(collection=collection):
                snapshot = self.snapshot(two_requests=True)
                first, second = snapshot["requests"]
                left, right = first[collection], second[collection]
                if isinstance(left, list):
                    left, right = left[0], right[0]
                right[field] = left[field]
                self.assert_invalid(snapshot, "Duplicate")

    def test_dangling_customer_and_staff_links_are_rejected(self):
        snapshot = self.snapshot()
        snapshot["requests"][0]["customer_id"] = "missing"
        self.assert_invalid(snapshot, "unknown customer")
        snapshot = self.snapshot()
        snapshot["requests"][0]["assignments"][0]["staff_id"] = "missing"
        self.assert_invalid(snapshot, "unknown staff")

    def test_owned_records_must_reference_their_owning_request(self):
        for collection in ("quote", "assignments", "payment"):
            with self.subTest(collection=collection):
                snapshot = self.snapshot()
                target = snapshot["requests"][0][collection]
                if isinstance(target, list):
                    target = target[0]
                target["request_id"] = "wrong-request"
                self.assert_invalid(snapshot, "belong")

    def test_reverse_indexes_are_checked_and_not_silently_repaired(self):
        for collection, field in (("customers", "request_ids"), ("staff", "assignment_ids")):
            for value in ([], ["missing"], ["duplicate", "duplicate"]):
                with self.subTest(collection=collection, value=value):
                    snapshot = self.snapshot()
                    snapshot[collection][0][field] = value
                    self.assert_invalid(snapshot)

    def test_multiple_active_assignments_are_rejected(self):
        snapshot = self.snapshot("Allocated")
        duplicate = deepcopy(snapshot["requests"][0]["assignments"][0])
        duplicate["assignment_id"] = "A-extra"
        snapshot["requests"][0]["assignments"].append(duplicate)
        snapshot["staff"][0]["assignment_ids"].append("A-extra")
        self.assert_invalid(snapshot, "at most one active")

    def test_recorded_pickup_requires_payment_and_delivery_requires_authorisation(self):
        for stage in ("Picked Up", "Delivered", "Failed delivery"):
            for missing in (False, True):
                with self.subTest(stage=stage, missing=missing):
                    snapshot = self.snapshot(stage)
                    payment = snapshot["requests"][0]["payment"]
                    payment["authorised_by"] = payment["authorisation_reason"] = ""
                    if missing:
                        snapshot["requests"][0]["payment"] = None
                    if stage == "Picked Up" and not missing:
                        restored = decode_state(snapshot)[2]["R1"]
                        self.assertFalse(restored.payment.allows_pickup)
                    else:
                        self.assert_invalid(snapshot, "pickup requires a payment" if missing else
                                            "delivery requires matching payment")

    def test_payment_quoted_amount_must_match_quote(self):
        snapshot = self.snapshot()
        snapshot["requests"][0]["payment"]["quoted_amount"] = "99.00"
        self.assert_invalid(snapshot, "differs")

    def test_failed_pickup_cannot_retain_payment_or_active_assignment(self):
        snapshot = self.snapshot("Failed pickup")
        snapshot["requests"][0]["payment"] = self.snapshot()["requests"][0]["payment"]
        self.assert_invalid(snapshot, "cannot have a payment")
        snapshot = self.snapshot("Failed pickup")
        assignment = snapshot["requests"][0]["assignments"][0]
        assignment["ended_at"], assignment["outcome"] = None, ""
        assignment["outcome_details"] = ""
        self.assert_invalid(snapshot, "cannot have an active assignment")

    def test_parcel_and_quote_states_must_match_request_lifecycle(self):
        snapshot = self.snapshot()
        snapshot["requests"][0]["parcels"][0]["status"] = "Pending"
        self.assert_invalid(snapshot, "parcel states")
        snapshot = self.snapshot()
        snapshot["requests"][0]["quote"]["decision"] = "Pending"
        self.assert_invalid(snapshot, "quote decision")

    def test_time_ordering_is_validated(self):
        snapshot = self.snapshot()
        snapshot["requests"][0]["assignments"][0]["started_at"] = (START - timedelta(days=1)).isoformat()
        self.assert_invalid(snapshot, "predates request")
        snapshot = self.snapshot()
        snapshot["requests"][0]["payment"]["received_at"] = (START + timedelta(hours=3)).isoformat()
        self.assert_invalid(snapshot, "after pickup")
        snapshot = self.snapshot()
        snapshot["requests"][0]["completed_at"] = START.isoformat()
        self.assert_invalid(snapshot, "completion cannot precede pickup")
        snapshot = self.snapshot(history=True)
        snapshot["requests"][0]["assignments"][1]["started_at"] = (START + timedelta(minutes=15)).isoformat()
        self.assert_invalid(snapshot, "overlap or are out of order")

    def test_local_iso_timestamps_and_decimal_strings_are_required(self):
        for value in ("2026-10-22", "2026-10-22T09:00:00+10:00", "not-a-date"):
            with self.subTest(value=value):
                snapshot = self.snapshot()
                snapshot["requests"][0]["created_at"] = value
                self.assert_invalid(snapshot)
        for value in (25.0, "NaN", "-1.00", "1.001"):
            with self.subTest(value=value):
                snapshot = self.snapshot()
                snapshot["requests"][0]["quote"]["amount"] = value
                self.assert_invalid(snapshot)

    def test_malformed_schedule_and_authorisation_are_rejected(self):
        snapshot = self.snapshot()
        snapshot["staff"][0]["schedule"] = [[START.isoformat()]]
        self.assert_invalid(snapshot, "start, end")
        snapshot = self.snapshot()
        snapshot["requests"][0]["payment"]["authorisation_reason"] = ""
        self.assert_invalid(snapshot, "both a name and reason")


if __name__ == "__main__":
    unittest.main()
