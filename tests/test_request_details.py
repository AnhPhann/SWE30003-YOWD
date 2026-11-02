"""Actual lifecycle times and retained outcomes are visible to the operator."""

from datetime import datetime
import unittest

from yowd.__main__ import DemoClock
from yowd.application import YowdApplication


class RequestDetailsTests(unittest.TestCase):
    def setUp(self):
        self.clock = DemoClock(datetime(2026, 11, 3, 9))
        self.app = YowdApplication(clock=self.clock)
        self.addCleanup(self.app.close)
        self.app.seed_demo()
        self.request_id = next(iter(self.app.requests))
        self.worker_id = next(iter(self.app.staff_list.staff))
        self.app.prepare_quote(self.request_id)
        self.app.respond_quote(self.request_id, True)
        self.app.allocate(self.request_id, self.worker_id)

    def test_details_show_actual_pickup_and_assignment_start_end_times(self):
        request = self.app.requests[self.request_id]
        started = request.active_assignment.started_at
        self.clock.now = request.quote.pickup_at
        self.app.pickup(self.request_id, self.worker_id, str(request.quote.amount))
        picked_up = self.clock.now
        self.clock.now = request.quote.delivery_at
        self.app.deliver(self.request_id, self.worker_id, True)
        details = self.app.request_details(self.request_id)
        self.assertIn(f"Actual pickup: {picked_up:%Y-%m-%d %H:%M}", details)
        self.assertIn(f"Started: {started:%Y-%m-%d %H:%M}", details)
        self.assertIn(f"Ended: {self.clock.now:%Y-%m-%d %H:%M}", details)

    def test_retry_keeps_specific_failure_visible_in_assignment_history(self):
        request = self.app.requests[self.request_id]
        parcel = request.parcels[0]
        self.clock.now = request.quote.pickup_at
        self.app.pickup(
            self.request_id, self.worker_id, "", parcel_ok=False,
            failure="Parcel damaged", parcel_id=parcel.parcel_id,
        )
        self.app.retry_pickup(self.request_id)
        details = self.app.request_details(self.request_id)
        self.assertIn("Parcel damaged", details)
        self.assertIn(parcel.parcel_id, details)
        self.assertIn("Actual pickup: Not recorded", details)


if __name__ == "__main__":
    unittest.main()
