"""Tests for the tracking view provided by DeliveryRequest."""

from datetime import datetime
import unittest

from yowd.__main__ import DemoClock
from yowd.application import YowdApplication


class TrackingInfoTests(unittest.TestCase):
    def setUp(self):
        self.clock = DemoClock(datetime(2026, 10, 22, 9))
        self.app = YowdApplication(clock=self.clock)
        self.addCleanup(self.app.close)
        self.app.seed_demo()
        self.request_id = next(iter(self.app.requests))
        self.staff_id = next(iter(self.app.staff_list.staff))

    def tracking(self):
        return self.app.requests[self.request_id].tracking_info()

    def allocate(self):
        self.app.prepare_quote(self.request_id)
        self.app.respond_quote(self.request_id, True)
        self.app.allocate(self.request_id, self.staff_id)

    def test_new_request_has_status_only(self):
        self.assertEqual(self.tracking(), {
            "status": "Requested",
            "quoted_pickup": None,
            "quoted_delivery": None,
            "active_staff_id": None,
            "latest_staff_id": None,
            "ended_assignments": 0,
        })

    def test_allocated_request_shows_window_and_active_worker(self):
        self.allocate()
        tracking = self.tracking()
        quote = self.app.requests[self.request_id].quote
        self.assertEqual(tracking["status"], "Allocated")
        self.assertEqual(tracking["quoted_pickup"], quote.pickup_at)
        self.assertEqual(tracking["quoted_delivery"], quote.delivery_at)
        self.assertEqual(tracking["active_staff_id"], self.staff_id)
        self.assertEqual(tracking["ended_assignments"], 0)

    def test_retry_keeps_history_distinct_from_current_allocation(self):
        self.allocate()
        request = self.app.requests[self.request_id]
        self.clock.now = request.quote.pickup_at
        self.app.pickup(
            self.request_id, self.staff_id, "", parcel_ok=False,
            failure="Customer not present",
        )
        self.app.retry_pickup(self.request_id)
        tracking = self.tracking()
        self.assertEqual(tracking["status"], "Accepted")
        self.assertIsNone(tracking["active_staff_id"])
        self.assertEqual(tracking["latest_staff_id"], self.staff_id)
        self.assertEqual(tracking["ended_assignments"], 1)

    def test_overview_shows_due_time_and_ended_worker(self):
        self.allocate()
        row = self.app.overview()["requests"][0]
        quote = self.app.requests[self.request_id].quote
        self.assertEqual(
            row["delivery_due"], f"{quote.delivery_at:%Y-%m-%d %H:%M}",
        )
        self.assertEqual(row["worker"], "Sample Driver")
        self.clock.now = quote.pickup_at
        self.app.pickup(
            self.request_id, self.staff_id, "", parcel_ok=False,
            failure="Customer not present",
        )
        row = self.app.overview()["requests"][0]
        self.assertEqual(row["worker"], "Sample Driver (ended)")

    def test_unquoted_request_has_blank_due_time(self):
        row = self.app.overview()["requests"][0]
        self.assertEqual(row["delivery_due"], "")
        self.assertEqual(row["worker"], "")


if __name__ == "__main__":
    unittest.main()
