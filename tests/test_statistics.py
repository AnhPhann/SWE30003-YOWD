"""Tests for reporting periods, staff scope and delivery averages."""

from datetime import date, datetime, timedelta
from decimal import Decimal
import unittest

from yowd.__main__ import DemoClock
from yowd.application import YowdApplication
from yowd.models import (
    Customer, DeliveryQuote, DeliveryRequest, DeliveryStaff,
    DeliveryStatistics, DomainError, Parcel, PaymentRecord, StaffList,
)


class ReportingPeriodTests(unittest.TestCase):
    def test_day_is_the_reference_date_only(self):
        reference_date = date(2026, 10, 22)
        self.assertEqual(
            DeliveryStatistics.period_range("Day", reference_date),
            (reference_date, reference_date),
        )

    def test_week_runs_monday_to_sunday(self):
        # 22 October 2026 is a Thursday.
        self.assertEqual(
            DeliveryStatistics.period_range("Week", date(2026, 10, 22)),
            (date(2026, 10, 19), date(2026, 10, 25)),
        )

    def test_month_covers_the_full_calendar_month(self):
        self.assertEqual(
            DeliveryStatistics.period_range("Month", date(2026, 2, 10)),
            (date(2026, 2, 1), date(2026, 2, 28)),
        )

    def test_year_covers_the_full_calendar_year(self):
        self.assertEqual(
            DeliveryStatistics.period_range("Year", date(2026, 6, 15)),
            (date(2026, 1, 1), date(2026, 12, 31)),
        )

    def test_year_to_date_ends_on_the_reference_date(self):
        self.assertEqual(
            DeliveryStatistics.period_range(
                "Year to date", date(2026, 10, 22),
            ),
            (date(2026, 1, 1), date(2026, 10, 22)),
        )

    def test_unknown_period_and_datetime_reference_are_rejected(self):
        with self.assertRaises(DomainError):
            DeliveryStatistics.period_range("Fortnight", date(2026, 10, 22))
        with self.assertRaises(DomainError):
            DeliveryStatistics.period_range("Day", datetime(2026, 10, 22, 9))


class StaffScopeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 22, 9)
        self.customer = Customer(
            "C1", "Anh Phan", "anh@example.com", "0400 123 456",
        )
        self.first_worker = DeliveryStaff(
            "S1", "Alex Tran", "alex@example.com", "0400111222",
        )
        self.second_worker = DeliveryStaff(
            "S2", "Sam Lee", "sam@example.com", "0400333444",
        )
        self.roster = StaffList()
        for worker in (self.first_worker, self.second_worker):
            worker.schedule.add_period(
                self.now, self.now + timedelta(hours=10),
            )
            self.roster.register(worker)

    def finished_request(self, request_id, worker, successful=True):
        """Build a request that is quoted, allocated, picked up and closed.

        The request is lodged at 09:00, picked up at 10:00 and given its
        delivery outcome at 10:30.
        """
        parcel = Parcel(
            f"{request_id}-P1", "Books",
            Decimal("2"), Decimal("20"), Decimal("15"), Decimal("10"),
        )
        request = DeliveryRequest(
            request_id, self.customer, "Richmond", "Footscray",
            [parcel], self.now,
        )
        request.issue_quote(DeliveryQuote(
            f"{request_id}-Q", request_id, Decimal("25"),
            self.now + timedelta(hours=1), self.now + timedelta(hours=2),
            self.now + timedelta(minutes=1),
        ))
        request.respond_to_quote(self.customer.customer_id, True)
        request.allocate(
            worker, f"{request_id}-A1", self.now + timedelta(minutes=5),
        )
        pickup_time = self.now + timedelta(hours=1)
        payment = PaymentRecord(
            f"{request_id}-PAY", request_id,
            Decimal("25"), Decimal("25"), pickup_time,
        )
        request.record_pickup(worker.staff_id, True, payment, pickup_time)
        outcome_time = self.now + timedelta(hours=1, minutes=30)
        if successful:
            request.record_delivery(worker.staff_id, True, "", outcome_time)
        else:
            request.record_delivery(
                worker.staff_id, False, "Recipient not present", outcome_time,
            )
        return request

    def three_outcomes(self):
        """Return one delivery and one failure for S1, one delivery for S2."""
        return [
            self.finished_request("R1", self.first_worker),
            self.finished_request(
                "R2", self.first_worker, successful=False,
            ),
            self.finished_request("R3", self.second_worker),
        ]

    def test_staff_rows_use_names_and_count_each_worker_separately(self):
        result = DeliveryStatistics.summarise(
            self.three_outcomes(), self.roster,
            self.now.date(), self.now.date(),
        )
        self.assertEqual((result["completed"], result["failed"]), (2, 1))
        rows_by_name = {}
        for row in result["staff_rows"]:
            rows_by_name[row["name"]] = (row["completed"], row["failed"])
        self.assertEqual(
            rows_by_name, {"Alex Tran": (1, 1), "Sam Lee": (1, 0)},
        )

    def test_staff_scope_counts_only_the_selected_worker(self):
        result = DeliveryStatistics.summarise(
            self.three_outcomes(), self.roster,
            self.now.date(), self.now.date(), staff_id="S2",
        )
        self.assertEqual((result["completed"], result["failed"]), (1, 0))
        self.assertEqual(result["by_staff"], {"S2": 1})
        self.assertEqual(len(result["staff_rows"]), 1)
        self.assertEqual(result["staff_rows"][0]["name"], "Sam Lee")

    def test_unknown_staff_scope_is_rejected(self):
        with self.assertRaises(DomainError):
            DeliveryStatistics.summarise(
                [], self.roster, self.now.date(), self.now.date(),
                staff_id="S9",
            )

    def test_former_worker_remains_in_scope_and_is_marked_inactive(self):
        request = self.finished_request("R1", self.first_worker)
        self.roster.deactivate("S1")
        result = DeliveryStatistics.summarise(
            [request], self.roster, self.now.date(), self.now.date(),
            staff_id="S1",
        )
        self.assertEqual(result["completed"], 1)
        self.assertFalse(result["staff_rows"][0]["active"])

    def test_pickup_average_is_separate_from_lodgement_average(self):
        request = self.finished_request("R1", self.first_worker)
        result = DeliveryStatistics.summarise(
            [request], self.roster, self.now.date(), self.now.date(),
        )
        self.assertEqual(result["average_pickup_to_delivery_minutes"], 30.0)
        self.assertEqual(result["average_minutes"], 90.0)

    def test_empty_period_returns_zero_averages(self):
        result = DeliveryStatistics.summarise(
            [], self.roster, self.now.date(), self.now.date(),
        )
        self.assertEqual(result["average_minutes"], 0.0)
        self.assertEqual(result["average_pickup_to_delivery_minutes"], 0.0)
        self.assertEqual(len(result["staff_rows"]), 2)


class ApplicationStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.clock = DemoClock(datetime(2026, 10, 22, 9))
        self.app = YowdApplication(clock=self.clock)
        self.addCleanup(self.app.close)
        self.worker_id = self.app.register_staff(
            "Alex Tran", "alex@example.com", "0400111222",
            datetime(2026, 10, 22, 8), datetime(2026, 10, 22, 18),
        )

    def test_period_range_defaults_to_the_application_clock(self):
        self.assertEqual(
            self.app.statistics_period_range("Month"),
            (date(2026, 10, 1), date(2026, 10, 31)),
        )

    def test_periods_offered_match_the_case_study(self):
        self.assertEqual(
            self.app.statistics_periods(),
            ("Day", "Week", "Month", "Year", "Year to date"),
        )

    def test_staff_choices_mark_former_workers(self):
        self.app.deactivate_staff(self.worker_id)
        self.assertEqual(
            self.app.statistics_staff_choices(),
            [(self.worker_id, "Alex Tran (former)")],
        )


if __name__ == "__main__":
    unittest.main()