"""Business rule tests for the A2 model, independent of UI and persistence."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from yowd.models import (
    AvailabilitySchedule, Customer, DeliveryAssignment, DeliveryQuote,
    DeliveryRequest, DeliveryStaff, DeliveryStatistics, DomainError, Parcel,
    ParcelStatus, PaymentRecord, QuoteDecision, RequestStatus, StaffList,
)


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 22, 9)
        self.customer = Customer("C1", "Anh Phan", "anh@example.com", "0400 123 456")
        self.worker = DeliveryStaff("S1", "Alex Tran", "alex@example.com", "0400111222")
        self.worker.schedule.add_period(self.now, self.now + timedelta(hours=10))
        self.roster = StaffList()
        self.roster.register(self.worker)

    def request(self, request_id="R1"):
        parcels = [
            Parcel(f"{request_id}-P1", "Books", Decimal("2"), Decimal("20"), Decimal("15"), Decimal("10")),
            Parcel(f"{request_id}-P2", "Clothing", Decimal("1"), Decimal("30"), Decimal("25"), Decimal("15")),
        ]
        return DeliveryRequest(request_id, self.customer, "Richmond", "Footscray", parcels, self.now)

    def accepted(self, request_id="R1"):
        request = self.request(request_id)
        request.issue_quote(DeliveryQuote(
            f"{request_id}-Q", request_id, Decimal("25"),
            self.now + timedelta(hours=1), self.now + timedelta(hours=2),
            self.now + timedelta(minutes=1),
        ))
        request.respond_to_quote(self.customer.customer_id, True)
        return request

    def allocated(self, request_id="R1"):
        request = self.accepted(request_id)
        request.allocate(self.worker, f"{request_id}-A1", self.now + timedelta(minutes=5))
        return request

    def payment(self, request, received="25"):
        return PaymentRecord(
            f"{request.request_id}-PAY", request.request_id, Decimal("25"), Decimal(received),
            self.now + timedelta(hours=1),
        )

    def pickup(self, request):
        request.record_pickup(self.worker.staff_id, True, self.payment(request), self.now + timedelta(hours=1))

    def addressed_request(self, pickup_address="12 Swan Street", destination_address="8 Hopkins Street"):
        self.assertIn("pickup_address", DeliveryRequest.__dataclass_fields__)
        self.assertIn("destination_address", DeliveryRequest.__dataclass_fields__)
        base = self.request()
        return DeliveryRequest(
            base.request_id, self.customer, base.pickup, base.destination, base.parcels, self.now,
            pickup_address=pickup_address, destination_address=destination_address,
        )

    def test_legacy_request_keeps_addresses_unknown(self):
        request = self.request()
        self.assertEqual(getattr(request, "pickup_address", None), "")
        self.assertEqual(getattr(request, "destination_address", None), "")
        self.assertIs(getattr(request, "has_full_addresses", None), False)

    def test_request_trims_full_addresses_without_changing_suburbs(self):
        request = self.addressed_request("  Unit 2, 12 Swan Street  ", "  8 Hopkins Street ")
        self.assertEqual(request.pickup_address, "Unit 2, 12 Swan Street")
        self.assertEqual(request.destination_address, "8 Hopkins Street")
        self.assertEqual((request.pickup, request.destination), ("Richmond", "Footscray"))
        self.assertTrue(request.has_full_addresses)

    def test_request_rejects_partial_or_non_text_address_pairs(self):
        self.assertIn("pickup_address", DeliveryRequest.__dataclass_fields__)
        for pickup, destination in (("12 Swan Street", ""), (" ", "8 Hopkins Street"),
                                    (None, "8 Hopkins Street"), ("12 Swan Street", 8)):
            with self.subTest(pickup=pickup, destination=destination), self.assertRaises(DomainError):
                self.addressed_request(pickup, destination)

    def test_requested_addresses_can_be_updated_and_invalid_update_is_atomic(self):
        request = self.request()
        self.assertTrue(callable(getattr(request, "update_addresses", None)))
        request.update_addresses("  12 Swan Street  ", " 8 Hopkins Street ")
        self.assertEqual((request.pickup_address, request.destination_address),
                         ("12 Swan Street", "8 Hopkins Street"))
        for pickup, destination in (("20 Swan Street", ""), (None, "9 Hopkins Street"), ("", "")):
            with self.subTest(pickup=pickup, destination=destination), self.assertRaises(DomainError):
                request.update_addresses(pickup, destination)
            self.assertEqual((request.pickup_address, request.destination_address),
                             ("12 Swan Street", "8 Hopkins Street"))

    def test_addresses_cannot_be_changed_after_quotation(self):
        for status in RequestStatus:
            if status == RequestStatus.REQUESTED:
                continue
            request = self.addressed_request()
            request.status = status
            self.assertTrue(callable(getattr(request, "update_addresses", None)))
            with self.subTest(status=status), self.assertRaises(DomainError):
                request.update_addresses("20 Swan Street", "9 Hopkins Street")
            self.assertEqual((request.pickup_address, request.destination_address),
                             ("12 Swan Street", "8 Hopkins Street"))

    def test_complete_multi_parcel_workflow_and_completion_statistics(self):
        request = self.allocated()
        self.pickup(request)
        payment = request.payment
        request.record_delivery(self.worker.staff_id, True, "", self.now + timedelta(hours=2))
        self.assertEqual(request.status, RequestStatus.DELIVERED)
        self.assertTrue(all(parcel.status == ParcelStatus.DELIVERED for parcel in request.parcels))
        self.assertIsNone(request.active_assignment)
        self.assertIs(request.payment, payment)
        self.roster.deactivate(self.worker.staff_id)
        result = DeliveryStatistics.summarise([request, request], self.roster, self.now.date(), self.now.date())
        self.assertEqual(result, {"completed": 1, "failed": 0, "by_staff": {"S1": 1}, "average_minutes": 120.0})
        empty = DeliveryStatistics.summarise([request], self.roster, date(2026, 10, 23), date(2026, 10, 24))
        self.assertEqual(empty["completed"], 0)
        self.assertEqual(empty["average_minutes"], 0)

    def test_request_requires_parcels_and_valid_customer(self):
        with self.assertRaises(DomainError):
            DeliveryRequest("R1", self.customer, "Richmond", "Footscray", [], self.now)
        self.assertEqual(self.customer.request_ids, [])
        with self.assertRaises(DomainError):
            Customer("C2", "", "not-email", "abc")

    def test_invalid_parcel_measurements_rejected(self):
        for weight in ("0", "-1", "NaN", "Infinity"):
            with self.subTest(weight=weight), self.assertRaises(DomainError):
                Parcel("P1", "Books", Decimal(weight), Decimal("1"), Decimal("1"), Decimal("1"))

    def test_quote_response_requires_correct_customer_and_current_status(self):
        request = self.accepted()
        self.assertEqual(request.quote.decision, QuoteDecision.ACCEPTED)
        with self.assertRaises(DomainError):
            request.respond_to_quote("C2", False)
        self.assertEqual(request.status, RequestStatus.ACCEPTED)
        self.assertEqual(request.quote.decision, QuoteDecision.ACCEPTED)

    def test_wrong_customer_does_not_change_pending_offer(self):
        request = self.request()
        quote = DeliveryQuote("Q1", "R1", Decimal("25"), self.now + timedelta(hours=1), self.now + timedelta(hours=2), self.now)
        request.issue_quote(quote)
        with self.assertRaises(DomainError):
            request.respond_to_quote("OTHER", True)
        self.assertEqual(request.status, RequestStatus.QUOTED)
        self.assertEqual(quote.decision, QuoteDecision.PENDING)
        request.respond_to_quote("C1", False)
        self.assertEqual(request.status, RequestStatus.QUOTE_DECLINED)
        self.assertEqual(request.assignments, [])
        self.assertIsNone(request.payment)

    def test_quote_validation_and_issue_do_not_reserve_staff(self):
        request = self.accepted()
        self.assertEqual(self.worker.assignment_ids, [])
        self.assertEqual(request.assignments, [])
        for amount in ("-1", "NaN", "25.001"):
            with self.subTest(amount=amount), self.assertRaises(DomainError):
                DeliveryQuote("Q", "R1", Decimal(amount), self.now, self.now, self.now)
        with self.assertRaises(DomainError):
            DeliveryQuote("Q", "R1", Decimal("25"), self.now, self.now - timedelta(minutes=1), self.now)

    def test_allocation_rejects_inactive_or_unavailable_worker_without_mutation(self):
        request = self.accepted()
        self.roster.deactivate("S1")
        with self.assertRaisesRegex(DomainError, "inactive"):
            request.allocate(self.worker, "A1", self.now + timedelta(minutes=5))
        self.worker.active = True
        self.worker.schedule = AvailabilitySchedule()
        with self.assertRaisesRegex(DomainError, "outside"):
            request.allocate(self.worker, "A1", self.now + timedelta(minutes=5))
        self.assertEqual(request.status, RequestStatus.ACCEPTED)
        self.assertEqual(request.assignments, [])
        self.assertEqual(self.worker.assignment_ids, [])

    def test_overlapping_jobs_are_allowed_but_duplicate_active_request_is_not(self):
        first, second = self.allocated("R1"), self.allocated("R2")
        self.assertEqual(len(self.worker.assignment_ids), 2)
        self.assertIsNotNone(first.active_assignment)
        self.assertIsNotNone(second.active_assignment)
        with self.assertRaises(DomainError):
            first.allocate(self.worker, "A3", self.now + timedelta(minutes=6))
        self.assertEqual(len(first.assignments), 1)

    def test_payment_mismatch_waits_for_explicit_authorisation(self):
        request = self.allocated()
        payment = self.payment(request, "20")
        self.assertFalse(request.record_pickup("S1", True, payment, self.now + timedelta(hours=1)))
        self.assertIs(request.payment, payment)
        self.assertEqual(request.status, RequestStatus.ALLOCATED)
        self.assertTrue(all(parcel.status == ParcelStatus.PENDING for parcel in request.parcels))
        with self.assertRaises(DomainError):
            payment.authorise("", "Approved short payment")
        payment.authorise("Office manager", "Approved goodwill reduction")
        self.assertTrue(request.record_pickup("S1", True, payment, self.now + timedelta(hours=1, minutes=2)))
        self.assertEqual(request.status, RequestStatus.PICKED_UP)
        self.assertIs(request.payment, payment)

    def test_pending_payment_cannot_be_overwritten_or_discarded(self):
        request = self.allocated()
        original = self.payment(request, "20")
        request.record_pickup("S1", True, original, self.now + timedelta(hours=1))
        with self.assertRaises(DomainError):
            request.record_pickup("S1", True, self.payment(request, "25"), self.now + timedelta(hours=1))
        with self.assertRaises(DomainError):
            request.record_pickup("S1", False, None, self.now + timedelta(hours=1))
        self.assertIs(request.payment, original)
        self.assertEqual(request.status, RequestStatus.ALLOCATED)
        self.assertIsNotNone(request.active_assignment)

    def test_pickup_rejects_wrong_worker_or_payment_identity_before_mutation(self):
        request = self.allocated()
        with self.assertRaises(DomainError):
            request.record_pickup("OTHER", True, self.payment(request), self.now + timedelta(hours=1))
        wrong_payment = PaymentRecord("PAY", "OTHER", Decimal("25"), Decimal("25"), self.now + timedelta(hours=1))
        with self.assertRaises(DomainError):
            request.record_pickup("S1", True, wrong_payment, self.now + timedelta(hours=1))
        wrong_amount = PaymentRecord("PAY", "R1", Decimal("30"), Decimal("30"), self.now + timedelta(hours=1))
        with self.assertRaises(DomainError):
            request.record_pickup("S1", True, wrong_amount, self.now + timedelta(hours=1))
        self.assertIsNone(request.payment)
        self.assertEqual(request.status, RequestStatus.ALLOCATED)

    def test_failed_pickup_retains_assignment_and_explicit_retry(self):
        request = self.allocated()
        assignment = request.active_assignment
        request.record_pickup("S1", False, None, self.now + timedelta(hours=1))
        self.assertEqual(request.status, RequestStatus.FAILED_PICKUP)
        self.assertFalse(assignment.active)
        self.assertIsNone(request.payment)
        request.retry_pickup()
        request.allocate(self.worker, "A2", self.now + timedelta(hours=1, minutes=5))
        self.assertEqual(len(request.assignments), 2)
        self.assertIs(request.assignments[0], assignment)
        self.assertEqual(request.active_assignment.assignment_id, "A2")

    def test_failed_delivery_preserves_payment_and_flags_return(self):
        request = self.allocated()
        self.pickup(request)
        payment = request.payment
        with self.assertRaises(DomainError):
            request.record_delivery("S1", False, " ", self.now + timedelta(hours=2))
        self.assertEqual(request.status, RequestStatus.PICKED_UP)
        self.assertIsNotNone(request.active_assignment)
        request.record_delivery("S1", False, "Recipient absent", self.now + timedelta(hours=2))
        self.assertEqual(request.status, RequestStatus.FAILED_DELIVERY)
        self.assertIs(request.payment, payment)
        self.assertIsNone(request.active_assignment)
        self.assertIsNone(request.completed_at)
        self.assertTrue(all(parcel.status == ParcelStatus.RETURN_REQUIRED for parcel in request.parcels))
        result = DeliveryStatistics.summarise([request], self.roster, self.now.date(), self.now.date())
        self.assertEqual((result["completed"], result["failed"]), (0, 1))

    def test_reject_is_only_allowed_before_quote(self):
        request = self.request()
        with self.assertRaises(DomainError):
            request.reject("")
        request.reject("Destination outside configured service area")
        self.assertEqual(request.status, RequestStatus.REJECTED)
        self.assertTrue(request.failure_reason)
        with self.assertRaises(DomainError):
            self.accepted("R2").reject("Too late")

    def test_timezone_and_backwards_outcomes_rejected(self):
        request = self.allocated()
        with self.assertRaises(DomainError):
            self.worker.schedule.add_period(self.now.replace(tzinfo=timezone.utc), self.now + timedelta(hours=1))
        with self.assertRaises(DomainError):
            request.record_pickup("S1", True, self.payment(request), self.now)
        self.assertEqual(request.status, RequestStatus.ALLOCATED)
        self.assertIsNone(request.payment)

    def test_roster_and_schedule_validation_and_retention(self):
        with self.assertRaises(DomainError):
            self.roster.register(self.worker)
        with self.assertRaises(DomainError):
            self.roster.get("UNKNOWN")
        schedule = AvailabilitySchedule()
        schedule.add_period(self.now, self.now + timedelta(hours=1))
        schedule.add_period(self.now + timedelta(hours=1), self.now + timedelta(hours=2))
        self.assertTrue(schedule.covers(self.now, self.now + timedelta(hours=2)))
        self.assertEqual(len(schedule.periods), 1)
        schedule.remove_period(self.now, self.now + timedelta(hours=2))
        self.assertEqual(schedule.periods, [])
        with self.assertRaises(DomainError):
            schedule.remove_period(self.now, self.now + timedelta(hours=2))
        with self.assertRaises(DomainError):
            schedule.add_period(self.now, self.now)
        self.roster.deactivate("S1")
        self.assertIs(self.roster.get("S1"), self.worker)


if __name__ == "__main__":
    unittest.main()
