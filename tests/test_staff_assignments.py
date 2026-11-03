"""Tests for showing a worker's current and past assignments."""

from datetime import datetime
import unittest
from unittest.mock import patch

from yowd.__main__ import DemoClock
from yowd.application import YowdApplication

try:
    import tkinter as tk
except ModuleNotFoundError:
    tk = None
else:
    from yowd.ui import MainWindow


PARCEL = {
    "description": "Shoes", "weight_kg": "1", "length_cm": "30",
    "width_cm": "20", "height_cm": "15",
}


class StaffAssignmentHistoryTests(unittest.TestCase):
    def setUp(self):
        self.clock = DemoClock(datetime(2026, 10, 22, 9))
        self.app = YowdApplication(clock=self.clock)
        self.addCleanup(self.app.close)
        self.app.seed_demo()
        self.first_request = next(iter(self.app.requests))
        self.staff_id = next(iter(self.app.staff_list.staff))
        self.second_request = self.app.create_request(
            "Mia Chen", "mia@example.com", "0400123456",
            "Richmond", "Footscray", [PARCEL],
            pickup_address="1 Church Street",
            destination_address="2 Barkly Street",
        )

    def allocate(self, request_id):
        self.app.prepare_quote(request_id)
        self.app.respond_quote(request_id, True)
        self.app.allocate(request_id, self.staff_id)

    def fail_pickup(self, request_id):
        request = self.app.requests[request_id]
        self.clock.now = request.quote.pickup_at
        self.app.pickup(
            request_id, self.staff_id, "", parcel_ok=False,
            failure="Customer not present",
        )

    def test_history_lists_own_assignments_in_allocation_order(self):
        self.allocate(self.first_request)
        self.allocate(self.second_request)
        worker = self.app.staff_list.get(self.staff_id)
        history = worker.assignment_history(self.app.requests.values())
        request_ids = []
        for request, _assignment in history:
            request_ids.append(request.request_id)
        self.assertEqual(
            request_ids, [self.first_request, self.second_request],
        )

    def test_new_worker_has_no_assignments(self):
        text = self.app.staff_assignment_details(self.staff_id)
        self.assertIn("0 current, 0 past assignments", text)
        self.assertEqual(text.count("  None"), 2)

    def test_current_and_past_assignments_are_separated(self):
        self.allocate(self.first_request)
        self.fail_pickup(self.first_request)
        self.allocate(self.second_request)
        text = self.app.staff_assignment_details(self.staff_id)
        self.assertIn("1 current, 1 past assignments", text)
        current_part, past_part = text.split("Past assignments:")
        self.assertIn(self.second_request, current_part)
        self.assertIn(self.first_request, past_part)
        self.assertIn("outcome: Failed pickup", past_part)
        self.assertIn("Customer not present", past_part)

    def test_retry_keeps_the_earlier_attempt_in_history(self):
        self.allocate(self.first_request)
        self.fail_pickup(self.first_request)
        self.app.retry_pickup(self.first_request)
        self.app.allocate(self.first_request, self.staff_id)
        text = self.app.staff_assignment_details(self.staff_id)
        self.assertIn("1 current, 1 past assignments", text)
        self.assertEqual(text.count(self.first_request), 2)

    def test_former_worker_keeps_their_history(self):
        self.allocate(self.first_request)
        self.fail_pickup(self.first_request)
        self.app.deactivate_staff(self.staff_id)
        text = self.app.staff_assignment_details(self.staff_id)
        self.assertIn(", former):", text)
        self.assertIn(self.first_request, text)


@unittest.skipIf(tk is None, "Tk runtime is not installed.")
class StaffAssignmentPanelTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk graphical runtime unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = YowdApplication(
            ":memory:", clock=DemoClock(datetime(2026, 10, 22, 9)),
        )
        self.addCleanup(self.app.close)
        self.enterContext(patch("yowd.ui.messagebox.showerror"))
        self.enterContext(patch("yowd.ui.messagebox.showinfo"))
        self.app.seed_demo()
        self.staff_id = next(iter(self.app.staff_list.staff))
        self.window = MainWindow(self.root, self.app)

    def panel_text(self):
        return self.window.staff_details.get("1.0", "end")

    def test_panel_asks_for_a_selection_first(self):
        self.assertIn("Select a worker", self.panel_text())

    def test_selecting_a_worker_shows_their_assignments(self):
        self.window.staff_tree.selection_set(self.staff_id)
        self.window._show_staff_assignments()
        self.assertIn("Sample Driver", self.panel_text())
        self.assertIn("Current assignments:", self.panel_text())


if __name__ == "__main__":
    unittest.main()
