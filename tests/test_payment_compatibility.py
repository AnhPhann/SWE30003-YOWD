"""Keep saved pre-pickup payment exceptions usable without inventing pickup."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from yowd.__main__ import DemoClock
from yowd.application import YowdApplication
from yowd.models import DomainError, ParcelStatus, PaymentRecord, RequestStatus
from yowd.serialization import encode_state
from yowd.storage import SQLiteStore


class LegacyPaymentCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "legacy.sqlite3"
        self.clock = DemoClock(datetime(2026, 10, 22, 9))
        fixture = YowdApplication(self.db_path, clock=self.clock)
        fixture.seed_demo()
        self.request_id = next(iter(fixture.requests))
        self.worker_id = next(iter(fixture.staff_list.staff))
        fixture.prepare_quote(self.request_id)
        fixture.respond_quote(self.request_id, True)
        fixture.allocate(self.request_id, self.worker_id)
        self.recorded_at = fixture.requests[self.request_id].quote.pickup_at
        self.legacy = encode_state(fixture.customers, fixture.staff_list, fixture.requests)
        self.legacy["requests"][0]["payment"] = {
            "payment_id": "PAY-LEGACY-001", "request_id": self.request_id,
            "quoted_amount": "25.00", "received_amount": "20.00",
            "received_at": self.recorded_at.isoformat(),
            "authorised_by": "", "authorisation_reason": "",
        }
        self.expected_current = deepcopy(self.legacy)
        self.legacy["schema_version"] = 2
        for assignment in self.legacy["requests"][0]["assignments"]:
            assignment.pop("outcome_details", None)
        fixture.store.save(self.legacy)
        fixture.close()
        self.clock.now = self.recorded_at + timedelta(minutes=5)
        self.app = YowdApplication(self.db_path, clock=self.clock)
        self.addCleanup(self.app.close)

    def snapshot(self):
        return encode_state(self.app.customers, self.app.staff_list, self.app.requests)

    def assert_awaiting_pickup(self):
        request = self.app.requests[self.request_id]
        self.assertEqual(request.status, RequestStatus.ALLOCATED)
        self.assertIsNone(request.picked_up_at)
        self.assertIsNotNone(request.active_assignment)
        self.assertTrue(all(parcel.status == ParcelStatus.PENDING for parcel in request.parcels))

    def test_loading_legacy_payment_never_confirms_pickup_or_rewrites_saved_state(self):
        self.assert_awaiting_pickup()
        self.assertEqual(self.snapshot(), self.expected_current)
        with SQLiteStore(self.db_path) as store:
            self.assertEqual(store.load(), self.legacy)

    def test_office_authorisation_keeps_legacy_request_awaiting_worker_confirmation(self):
        self.app.authorise_payment(self.request_id, "Office manager", "Goodwill reduction")
        self.assert_awaiting_pickup()
        self.assertEqual(self.app.requests[self.request_id].payment.authorised_by, "Office manager")
        self.app.close()
        self.app = YowdApplication(self.db_path, clock=self.clock)
        self.addCleanup(self.app.close)
        self.assert_awaiting_pickup()
        self.assertEqual(self.app.requests[self.request_id].payment.payment_id, "PAY-LEGACY-001")

    def test_unapproved_legacy_pickup_stays_allocated_and_retains_exact_payment(self):
        before = self.snapshot()
        message = self.app.pickup(self.request_id, self.worker_id, "20")
        self.assert_awaiting_pickup()
        self.assertEqual(self.snapshot(), before)
        self.assertIn("authoris", message.lower())

    def test_authorised_legacy_worker_confirmation_reuses_payment_and_can_deliver(self):
        self.app.authorise_payment(self.request_id, "Office manager", "Goodwill reduction")
        self.app.close()
        self.app = YowdApplication(self.db_path, clock=self.clock)
        self.addCleanup(self.app.close)
        payment = self.app.requests[self.request_id].payment
        self.app.pickup(self.request_id, self.worker_id, "20.00")
        request = self.app.requests[self.request_id]
        self.assertEqual(request.status, RequestStatus.PICKED_UP)
        self.assertEqual(request.picked_up_at, self.clock.now)
        self.assertTrue(all(parcel.status == ParcelStatus.COLLECTED for parcel in request.parcels))
        self.assertIs(request.payment, payment)
        self.assertEqual((payment.payment_id, payment.received_amount, payment.received_at), (
            "PAY-LEGACY-001", Decimal("20.00"), self.recorded_at,
        ))
        self.clock.now = request.quote.delivery_at
        self.app.deliver(self.request_id, self.worker_id, True)
        self.assertEqual(self.app.requests[self.request_id].status, RequestStatus.DELIVERED)

    def test_legacy_changed_amount_or_reporter_is_rejected_without_mutation(self):
        for authorised in (False, True):
            if authorised:
                self.app.authorise_payment(self.request_id, "Office manager", "Goodwill reduction")
            for staff_id, amount in ((self.worker_id, "21"), ("OTHER", "20")):
                with self.subTest(authorised=authorised, staff_id=staff_id, amount=amount):
                    before = self.snapshot()
                    with self.assertRaises(DomainError):
                        self.app.pickup(self.request_id, staff_id, amount)
                    self.assertEqual(self.snapshot(), before)
                    self.assert_awaiting_pickup()

    def test_domain_confirmation_reuses_authorised_payment_without_replacing_it(self):
        request = self.app.requests[self.request_id]
        payment = request.payment
        payment.authorise("Office manager", "Goodwill reduction")
        self.assertTrue(request.record_pickup(self.worker_id, True, payment, self.clock.now))
        self.assertIs(request.payment, payment)
        self.assertEqual(request.status, RequestStatus.PICKED_UP)

    def test_domain_unapproved_legacy_confirmation_changes_nothing(self):
        request = self.app.requests[self.request_id]
        before = self.snapshot()
        self.assertFalse(request.record_pickup(self.worker_id, True, request.payment, self.clock.now))
        self.assertEqual(self.snapshot(), before)
        self.assert_awaiting_pickup()

    def test_domain_legacy_payment_cannot_be_replaced_even_with_same_amount(self):
        request = self.app.requests[self.request_id]
        before = self.snapshot()
        replacement = PaymentRecord(
            "PAY-REPLACEMENT", self.request_id, Decimal("25"), Decimal("20"), self.clock.now,
        )
        with self.assertRaises(DomainError):
            request.record_pickup(self.worker_id, True, replacement, self.clock.now)
        self.assertEqual(self.snapshot(), before)

    def test_failed_legacy_pickup_cannot_discard_pending_payment_or_end_assignment(self):
        request = self.app.requests[self.request_id]
        before = self.snapshot()
        with self.assertRaises(DomainError):
            request.record_pickup(self.worker_id, False, None, self.clock.now)
        self.assertEqual(self.snapshot(), before)
        self.assert_awaiting_pickup()


if __name__ == "__main__":
    unittest.main()
