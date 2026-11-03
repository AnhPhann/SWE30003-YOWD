"""Tests for item-level parcel exceptions and the parcel-request link."""

import copy
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from yowd.__main__ import DemoClock
from yowd.application import YowdApplication
from yowd.models import (
    Customer, DeliveryQuote, DeliveryRequest, DeliveryStaff, DomainError,
    Parcel, PaymentRecord, RequestStatus,
)
from yowd.serialization import decode_state, encode_state
from yowd.storage import StorageError


class ParcelTests(unittest.TestCase):
    def parcel(self, **changes):
        values = {
            "parcel_id": "P1", "description": "Books",
            "weight_kg": Decimal("2"), "length_cm": Decimal("20"),
            "width_cm": Decimal("15"), "height_cm": Decimal("10"),
        }
        values.update(changes)
        return Parcel(**values)

    def test_new_parcel_has_no_exception(self):
        parcel = self.parcel()
        self.assertEqual(parcel.exception, "")
        self.assertFalse(parcel.has_exception)

    def test_exception_can_be_recorded_and_cleared(self):
        parcel = self.parcel()
        parcel.record_exception("Damaged")
        self.assertTrue(parcel.has_exception)
        self.assertEqual(parcel.exception, "Damaged")
        parcel.clear_exception()
        self.assertFalse(parcel.has_exception)

    def test_unknown_or_blank_exception_is_rejected(self):
        parcel = self.parcel()
        for value in ("Lost", ""):
            with self.subTest(value=value):
                with self.assertRaises(DomainError):
                    parcel.record_exception(value)
        self.assertFalse(parcel.has_exception)
        with self.assertRaises(DomainError):
            self.parcel(exception="Wet")


class RequestParcelExceptionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 22, 9)
        self.customer = Customer(
            "C1", "Anh Phan", "anh@example.com", "0400 123 456",
        )

    def allocated_request(self):
        """Build a two-parcel request allocated to a new worker."""
        self.worker = DeliveryStaff(
            "S1", "Alex Tran", "alex@example.com", "0400111222",
        )
        self.worker.schedule.add_period(
            self.now, self.now + timedelta(hours=10),
        )
        parcels = [
            Parcel(
                "P1", "Books",
                Decimal("2"), Decimal("20"), Decimal("15"), Decimal("10"),
            ),
            Parcel(
                "P2", "Clothing",
                Decimal("1"), Decimal("30"), Decimal("25"), Decimal("15"),
            ),
        ]
        request = DeliveryRequest(
            "R1", self.customer, "Richmond", "Footscray", parcels, self.now,
        )
        request.issue_quote(DeliveryQuote(
            "Q1", "R1", Decimal("25"),
            self.now + timedelta(hours=1), self.now + timedelta(hours=2),
            self.now + timedelta(minutes=1),
        ))
        request.respond_to_quote("C1", True)
        request.allocate(
            self.worker, "A1", self.now + timedelta(minutes=5),
        )
        return request

    def picked_up_request(self):
        request = self.allocated_request()
        pickup_time = self.now + timedelta(hours=1)
        payment = PaymentRecord(
            "PAY1", "R1", Decimal("25"), Decimal("25"), pickup_time,
        )
        request.record_pickup("S1", True, payment, pickup_time)
        return request

    def exceptions(self, request):
        """Return each parcel's exception keyed by parcel ID."""
        result = {}
        for parcel in request.parcels:
            result[parcel.parcel_id] = parcel.exception
        return result

    def test_parcels_know_their_request(self):
        request = self.allocated_request()
        for parcel in request.parcels:
            self.assertEqual(parcel.request_id, "R1")

    def test_parcel_from_another_request_is_rejected(self):
        parcel = Parcel(
            "P9", "Books",
            Decimal("2"), Decimal("20"), Decimal("15"), Decimal("10"),
            request_id="OTHER",
        )
        with self.assertRaises(DomainError):
            DeliveryRequest(
                "R1", self.customer, "Richmond", "Footscray", [parcel],
                self.now,
            )

    def test_failed_pickup_flags_only_the_affected_parcel(self):
        request = self.allocated_request()
        request.record_pickup(
            "S1", False, None, self.now + timedelta(hours=1),
            failure="Parcel damaged", parcel_id="P2",
        )
        self.assertEqual(self.exceptions(request), {"P1": "", "P2": "Damaged"})

    def test_mismatched_parcel_is_flagged(self):
        request = self.allocated_request()
        request.record_pickup(
            "S1", False, None, self.now + timedelta(hours=1),
            failure="Parcel does not match request", parcel_id="P1",
        )
        self.assertEqual(
            request.parcels[0].exception, "Does not match request",
        )

    def test_customer_not_present_flags_no_parcel(self):
        request = self.allocated_request()
        request.record_pickup(
            "S1", False, None, self.now + timedelta(hours=1),
            failure="Customer not present",
        )
        self.assertEqual(self.exceptions(request), {"P1": "", "P2": ""})

    def test_retry_clears_exceptions_but_keeps_history(self):
        request = self.allocated_request()
        request.record_pickup(
            "S1", False, None, self.now + timedelta(hours=1),
            failure="Parcel missing", parcel_id="P1",
        )
        request.retry_pickup()
        self.assertEqual(self.exceptions(request), {"P1": "", "P2": ""})
        self.assertIn("Books", request.assignments[0].outcome_details)

    def test_failed_delivery_flags_the_affected_parcel(self):
        request = self.picked_up_request()
        request.record_delivery(
            "S1", False, "", self.now + timedelta(hours=2),
            failure="Parcel missing", parcel_id="P1",
        )
        self.assertEqual(self.exceptions(request), {"P1": "Missing", "P2": ""})

    def test_rejected_report_flags_nothing(self):
        request = self.picked_up_request()
        with self.assertRaises(DomainError):
            request.record_delivery(
                "S9", False, "", self.now + timedelta(hours=2),
                failure="Parcel missing", parcel_id="P1",
            )
        self.assertEqual(self.exceptions(request), {"P1": "", "P2": ""})


class ParcelExceptionStorageTests(unittest.TestCase):
    def setUp(self):
        self.clock = DemoClock(datetime(2026, 10, 22, 9))
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database = Path(self.folder.name) / "parcels.sqlite3"

    def failed_delivery_app(self):
        """Return an app holding one failed delivery with a missing parcel."""
        app = YowdApplication(self.database, clock=self.clock)
        app.seed_demo()
        request_id = next(iter(app.requests))
        staff_id = next(iter(app.staff_list.staff))
        amount = app.prepare_quote(request_id)
        app.respond_quote(request_id, True)
        app.allocate(request_id, staff_id)
        self.clock.now = app.requests[request_id].quote.pickup_at
        app.pickup(request_id, staff_id, str(amount))
        self.clock.now = app.requests[request_id].quote.delivery_at
        parcel_id = app.requests[request_id].parcels[1].parcel_id
        app.deliver(
            request_id, staff_id, False,
            failure="Parcel missing", parcel_id=parcel_id,
        )
        return app, request_id

    def test_exception_survives_restart_and_shows_in_details(self):
        app, request_id = self.failed_delivery_app()
        app.close()
        reopened = YowdApplication(self.database, clock=self.clock)
        self.addCleanup(reopened.close)
        parcels = reopened.requests[request_id].parcels
        self.assertEqual(parcels[0].exception, "")
        self.assertEqual(parcels[1].exception, "Missing")
        self.assertEqual(parcels[1].request_id, request_id)
        self.assertIn(
            "exception: Missing", reopened.request_details(request_id),
        )

    def test_older_snapshot_without_exception_field_still_loads(self):
        app, request_id = self.failed_delivery_app()
        self.addCleanup(app.close)
        snapshot = encode_state(app.customers, app.staff_list, app.requests)
        legacy = copy.deepcopy(snapshot)
        legacy["schema_version"] = 3
        for row in legacy["requests"]:
            for parcel in row["parcels"]:
                parcel.pop("exception")
        _customers, _staff, requests = decode_state(legacy)
        for parcel in requests[request_id].parcels:
            self.assertEqual(parcel.exception, "")

    def test_older_snapshot_cannot_hold_an_exception(self):
        app, _request_id = self.failed_delivery_app()
        self.addCleanup(app.close)
        snapshot = encode_state(app.customers, app.staff_list, app.requests)
        snapshot["schema_version"] = 3
        with self.assertRaisesRegex(StorageError, "version 4"):
            decode_state(snapshot)

    def test_exception_on_a_request_that_has_not_failed_is_rejected(self):
        app = YowdApplication(clock=self.clock)
        self.addCleanup(app.close)
        app.seed_demo()
        request_id = next(iter(app.requests))
        self.assertEqual(
            app.requests[request_id].status, RequestStatus.REQUESTED,
        )
        snapshot = encode_state(app.customers, app.staff_list, app.requests)
        snapshot["requests"][0]["parcels"][0]["exception"] = "Damaged"
        with self.assertRaisesRegex(StorageError, "failed request"):
            decode_state(snapshot)


if __name__ == "__main__":
    unittest.main()
