"""Use-case tests through the same public API as the desktop screens."""

from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from yowd.__main__ import DemoClock, run_demo
from yowd.application import YowdApplication
from yowd.models import DomainError, ParcelStatus, RequestStatus
from yowd.serialization import encode_state
from yowd.storage import StorageError


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.clock = DemoClock(datetime(2026, 10, 22, 9))
        self.app = YowdApplication(clock=self.clock)
        self.addCleanup(self.app.close)
        self.worker_id = self.app.register_staff(
            "Alex Tran", "alex@example.com", "0400111222",
            self.clock.now, self.clock.now + timedelta(hours=10),
        )

    def parcel(self, **changes):
        values = {
            "description": "Books", "weight_kg": "2", "length_cm": "20",
            "width_cm": "15", "height_cm": "10",
        }
        return values | changes

    def request(self, **changes):
        values = {
            "customer_name": "Anh Phan", "email": "anh@example.com",
            "phone": "0400123456", "pickup": "Richmond",
            "destination": "Footscray", "parcels": [self.parcel()],
        }
        return self.app.create_request(**(values | changes))

    def accepted(self, **changes):
        request_id = self.request(**changes)
        self.app.prepare_quote(request_id)
        self.app.respond_quote(request_id, True)
        return request_id

    def allocated(self, **changes):
        request_id = self.accepted(**changes)
        self.app.allocate(request_id, self.worker_id)
        return request_id

    def snapshot(self):
        return encode_state(
            self.app.customers, self.app.staff_list, self.app.requests,
        )

    def test_connected_multi_parcel_delivery_and_completion_date_statistics(self):
        request_id = self.allocated(parcels=[
            self.parcel(), self.parcel(description="Clothing", weight_kg="1"),
        ])
        request = self.app.requests[request_id]
        self.assertEqual(request.quote.amount, Decimal("25.00"))
        self.clock.now = request.quote.pickup_at
        self.app.pickup(request_id, self.worker_id, "25")
        self.clock.now = request.quote.delivery_at
        self.app.deliver(request_id, self.worker_id, True)
        request = self.app.requests[request_id]
        self.assertEqual(request.status, RequestStatus.DELIVERED)
        self.assertIsNone(request.active_assignment)
        self.assertTrue(all(p.status == ParcelStatus.DELIVERED for p in request.parcels))
        self.assertEqual(self.app.statistics(date(2026, 10, 22), date(2026, 10, 22)), {
            "completed": 1, "failed": 0,
            "by_staff": {self.worker_id: 1}, "average_minutes": 105.0,
        })
        self.assertEqual(self.app.statistics(date(2026, 10, 23), date(2026, 10, 23))["completed"], 0)

    def test_quotes_use_all_parcels_and_volumetric_weight(self):
        request_id = self.request(parcels=[
            self.parcel(), self.parcel(weight_kg="1", length_cm="50", width_cm="50", height_cm="50"),
        ])
        self.assertEqual(self.app.prepare_quote(request_id), Decimal("73.00"))
        other_id = self.request(pickup="Southbank", destination="Docklands")
        self.assertEqual(self.app.prepare_quote(other_id), Decimal("18.00"))

    def test_unsupported_suburb_retains_rejection_and_never_quotes(self):
        request_id = self.request(destination="Sydney")
        self.assertEqual(self.app.requests[request_id].status, RequestStatus.REJECTED)
        self.assertIn("Sydney", self.app.requests[request_id].failure_reason)
        before = self.snapshot()
        with self.assertRaises(DomainError):
            self.app.prepare_quote(request_id)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_lodgement_never_leaves_phantom_customers_or_requests(self):
        cases = [
            {"customer_name": ""}, {"email": "bad-email"}, {"pickup": " "},
            {"parcels": []}, {"parcels": [self.parcel(weight_kg="NaN")]},
            {"parcels": [self.parcel(weight_kg="0")]},
            {"parcels": [{"description": "No measurements"}]},
        ]
        before = self.snapshot()
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                self.request(**changes)
            self.assertEqual(self.snapshot(), before)

    def test_existing_customer_is_shared_but_conflicting_contact_is_rejected(self):
        first = self.request(pickup=" richmond ")
        second = self.request(email="ANH@example.com")
        self.assertEqual(len(self.app.customers), 1)
        self.assertIs(self.app.requests[first].customer, self.app.requests[second].customer)
        self.assertEqual(self.app.requests[first].pickup, "Richmond")
        before = self.snapshot()
        with self.assertRaises(DomainError):
            self.request(phone="0400999888")
        self.assertEqual(self.snapshot(), before)

    def test_quote_requires_coverage_without_creating_or_reserving_assignments(self):
        request_id = self.request()
        before = self.snapshot()
        with self.assertRaises(DomainError):
            self.app.prepare_quote(
                request_id, self.clock.now + timedelta(days=1),
                self.clock.now + timedelta(days=1, hours=2),
            )
        self.assertEqual(self.snapshot(), before)
        self.app.prepare_quote(request_id)
        self.app.respond_quote(request_id, True)
        self.assertEqual(self.app.requests[request_id].assignments, [])
        self.assertEqual(self.app.staff_list.get(self.worker_id).assignment_ids, [])
        self.app.deactivate_staff(self.worker_id)
        with self.assertRaises(DomainError):
            self.app.allocate(request_id, self.worker_id)
        self.assertEqual(self.app.requests[request_id].status, RequestStatus.ACCEPTED)

    def test_quote_estimate_accounts_for_age_and_available_window(self):
        older = self.request()
        self.clock.now += timedelta(minutes=1)
        newer = self.request()
        old_window = self.app.suggest_quote_window(older)
        new_window = self.app.suggest_quote_window(newer)
        self.assertEqual(old_window[0], self.clock.now + timedelta(minutes=15))
        self.assertEqual(new_window[0], self.clock.now + timedelta(minutes=30))
        later = self.clock.now + timedelta(hours=2)
        self.app.set_availability(self.worker_id, [(later, later + timedelta(hours=5))])
        self.assertEqual(self.app.suggest_quote_window(older)[0], later)

    def test_quote_decline_and_wrong_customer_have_no_operational_side_effects(self):
        request_id = self.request()
        self.app.prepare_quote(request_id)
        before = self.snapshot()
        with self.assertRaises(DomainError):
            self.app.respond_quote(request_id, True, "OTHER-CUSTOMER")
        with self.assertRaises(DomainError):
            self.app.respond_quote(request_id, True, "")
        self.assertEqual(self.snapshot(), before)
        self.app.respond_quote(request_id, False)
        request = self.app.requests[request_id]
        self.assertEqual(request.status, RequestStatus.QUOTE_DECLINED)
        self.assertEqual(request.assignments, [])
        self.assertIsNone(request.payment)

    def test_overlap_allowed_but_request_cannot_be_allocated_twice(self):
        first, second = self.allocated(), self.allocated()
        self.assertEqual(len(self.app.staff_list.get(self.worker_id).assignment_ids), 2)
        self.assertIsNotNone(self.app.requests[second].active_assignment)
        before = self.snapshot()
        with self.assertRaises(DomainError):
            self.app.allocate(first, self.worker_id)
        self.assertEqual(self.snapshot(), before)

    def test_wrong_worker_and_premature_delivery_leave_everything_unchanged(self):
        request_id = self.allocated()
        before = self.snapshot()
        with self.assertRaises(DomainError):
            self.app.pickup(request_id, "SOMEONE-ELSE", "21")
        with self.assertRaises(DomainError):
            self.app.deliver(request_id, self.worker_id, True)
        self.assertEqual(self.snapshot(), before)

    def test_non_boolean_pickup_outcomes_do_not_bypass_domain_validation(self):
        request_id = self.allocated()
        before = self.snapshot()
        for invalid in ("no", 1, None):
            with self.subTest(outcome=invalid), self.assertRaises(DomainError):
                self.app.pickup(request_id, self.worker_id, "21", parcel_ok=invalid)
            self.assertEqual(self.snapshot(), before)

    def test_pending_payment_requires_explicit_authorisation_and_worker_confirmation(self):
        request_id = self.allocated()
        self.clock.now += timedelta(hours=1)
        self.app.pickup(request_id, self.worker_id, "20")
        request = self.app.requests[request_id]
        payment_id = request.payment.payment_id
        self.assertEqual(request.status, RequestStatus.ALLOCATED)
        self.assertTrue(all(p.status == ParcelStatus.PENDING for p in request.parcels))
        before = self.snapshot()
        with self.assertRaises(DomainError):
            self.app.pickup(request_id, self.worker_id, "21")
        with self.assertRaises(DomainError):
            self.app.authorise_payment(request_id, "", "Approved discount")
        self.assertEqual(self.snapshot(), before)
        self.app.authorise_payment(request_id, "Office manager", "Approved discount")
        self.assertEqual(self.app.requests[request_id].status, RequestStatus.ALLOCATED)
        self.app.pickup(request_id, self.worker_id, "20")
        self.assertEqual(self.app.requests[request_id].status, RequestStatus.PICKED_UP)
        self.assertEqual(self.app.requests[request_id].payment.payment_id, payment_id)

    def test_failed_pickup_then_retry_retains_both_assignments(self):
        request_id = self.allocated()
        first_id = self.app.requests[request_id].active_assignment.assignment_id
        self.clock.now += timedelta(hours=1)
        self.app.pickup(request_id, self.worker_id, "", parcel_ok=False)
        request = self.app.requests[request_id]
        self.assertEqual(request.status, RequestStatus.FAILED_PICKUP)
        self.assertIsNone(request.payment)
        self.assertIsNone(request.active_assignment)
        self.app.retry_pickup(request_id)
        self.app.allocate(request_id, self.worker_id)
        request = self.app.requests[request_id]
        self.assertEqual(len(request.assignments), 2)
        self.assertEqual(request.assignments[0].assignment_id, first_id)
        self.assertFalse(request.assignments[0].active)
        self.assertNotEqual(request.active_assignment.assignment_id, first_id)

    def test_failed_delivery_retains_payment_and_flags_return_without_completion(self):
        request_id = self.allocated()
        self.app.pickup(request_id, self.worker_id, "21")
        payment_id = self.app.requests[request_id].payment.payment_id
        before = self.snapshot()
        with self.assertRaises(DomainError):
            self.app.deliver(request_id, self.worker_id, False, " ")
        self.assertEqual(self.snapshot(), before)
        self.app.deliver(request_id, self.worker_id, False, "Recipient absent")
        request = self.app.requests[request_id]
        self.assertEqual(request.status, RequestStatus.FAILED_DELIVERY)
        self.assertEqual(request.payment.payment_id, payment_id)
        self.assertIsNone(request.active_assignment)
        self.assertIsNone(request.completed_at)
        self.assertTrue(all(p.status == ParcelStatus.RETURN_REQUIRED for p in request.parcels))
        result = self.app.statistics(self.clock.now.date(), self.clock.now.date())
        self.assertEqual((result["completed"], result["failed"]), (0, 1))

    def test_deactivation_and_schedule_changes_preserve_existing_work(self):
        request_id = self.allocated()
        self.app.deactivate_staff(self.worker_id)
        self.app.set_availability(self.worker_id, [])
        self.app.pickup(request_id, self.worker_id, "21")
        self.app.deliver(request_id, self.worker_id, True)
        result = self.app.statistics(self.clock.now.date(), self.clock.now.date())
        self.assertEqual(result["by_staff"][self.worker_id], 1)
        self.assertFalse(self.app.staff_list.get(self.worker_id).active)

    def test_invalid_availability_replacement_retains_previous_schedule(self):
        before = self.snapshot()
        with self.assertRaises(DomainError):
            self.app.set_availability(self.worker_id, [
                (self.clock.now, self.clock.now + timedelta(hours=1)),
                (self.clock.now, self.clock.now),
            ])
        with self.assertRaises(DomainError):
            self.app.register_staff(
                "Duplicate", "alex@example.com", "0400123456",
                self.clock.now, self.clock.now + timedelta(hours=1),
            )
        self.assertEqual(self.snapshot(), before)

    def test_storage_failure_rolls_back_all_objects_and_reverse_indexes(self):
        request_id = self.accepted()
        before = self.snapshot()
        with patch.object(self.app.store, "save", side_effect=StorageError("Disk failure")):
            with self.assertRaisesRegex(StorageError, "Disk failure"):
                self.app.allocate(request_id, self.worker_id)
        self.assertEqual(self.snapshot(), before)
        self.app.allocate(request_id, self.worker_id)
        self.assertEqual(len(self.app.staff_list.get(self.worker_id).assignment_ids), 1)

    def test_oversized_tariff_input_returns_validation_error_without_issuing_quote(self):
        request_id = self.request(parcels=[self.parcel(length_cm="1E+999999")])
        before = self.snapshot()
        with self.assertRaisesRegex(DomainError, "too large"):
            self.app.prepare_quote(request_id)
        self.assertEqual(self.snapshot(), before)

    def test_empty_period_and_reversed_range(self):
        result = self.app.statistics(date(2020, 1, 1), date(2020, 1, 1))
        self.assertEqual((result["completed"], result["failed"], result["average_minutes"]), (0, 0, 0))
        with self.assertRaises(DomainError):
            self.app.statistics(date(2026, 10, 23), date(2026, 10, 22))


class PersistenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "nested" / "review.sqlite3"
        self.clock = DemoClock(datetime(2026, 10, 22, 9))

    def open_app(self):
        app = YowdApplication(self.db_path, clock=self.clock)
        self.addCleanup(app.close)
        return app

    def test_restart_restores_pending_payment_and_shared_customer_history(self):
        app = self.open_app()
        app.seed_demo()
        request_id = next(iter(app.requests))
        worker_id = next(iter(app.staff_list.staff))
        app.prepare_quote(request_id)
        app.respond_quote(request_id, True)
        app.allocate(request_id, worker_id)
        self.clock.now = app.requests[request_id].quote.pickup_at
        app.pickup(request_id, worker_id, "20")
        app.deactivate_staff(worker_id)
        before = encode_state(app.customers, app.staff_list, app.requests)
        app.close()
        reopened = self.open_app()
        self.assertEqual(encode_state(reopened.customers, reopened.staff_list, reopened.requests), before)
        request = reopened.requests[request_id]
        self.assertIs(request.customer, reopened.customers[request.customer.customer_id])
        reopened.authorise_payment(request_id, "Office manager", "Goodwill reduction")
        reopened.pickup(request_id, worker_id, "20")
        self.clock.now = request.quote.delivery_at
        reopened.deliver(request_id, worker_id, True)
        reopened.close()
        final = self.open_app()
        self.assertEqual(final.requests[request_id].status, RequestStatus.DELIVERED)
        self.assertEqual(final.statistics(self.clock.now.date(), self.clock.now.date())["by_staff"][worker_id], 1)

    def test_stale_application_does_not_overwrite_newer_data(self):
        first, stale = self.open_app(), self.open_app()
        first.seed_demo()
        with self.assertRaisesRegex(StorageError, "changed|another|reload|newer"):
            stale.seed_demo()
        self.assertEqual(stale.requests, {})
        self.assertEqual(stale.staff_list.staff, {})
        reloaded = self.open_app()
        self.assertEqual(len(reloaded.requests), 1)

    def test_console_demo_simulates_outcomes_at_quoted_times(self):
        app = self.open_app()
        with redirect_stdout(StringIO()) as output:
            run_demo(app, self.clock)
        request = next(iter(app.requests.values()))
        self.assertEqual(request.picked_up_at, request.quote.pickup_at)
        self.assertEqual(request.completed_at, request.quote.delivery_at)
        self.assertIn("AUD 25.00", output.getvalue())
        self.assertIn("simulated clock", output.getvalue())
        with self.assertRaises(DomainError):
            app.seed_demo()


if __name__ == "__main__":
    unittest.main()
