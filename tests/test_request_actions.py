"""Tests for the actions each request accepts and the next-step line."""

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
    from yowd.ui import NO_REQUEST_STEP, MainWindow


class RequestActionTests(unittest.TestCase):
    def setUp(self):
        self.clock = DemoClock(datetime(2026, 10, 22, 9))
        self.app = YowdApplication(clock=self.clock)
        self.addCleanup(self.app.close)
        self.app.seed_demo()
        self.request_id = next(iter(self.app.requests))
        self.staff_id = next(iter(self.app.staff_list.staff))

    def actions(self):
        return self.app.request_actions(self.request_id)["actions"]

    def next_step(self):
        return self.app.request_actions(self.request_id)["next_step"]

    def allocate(self):
        self.app.prepare_quote(self.request_id)
        self.app.respond_quote(self.request_id, True)
        self.app.allocate(self.request_id, self.staff_id)

    def pick_up(self, received_amount):
        request = self.app.requests[self.request_id]
        self.clock.now = request.quote.pickup_at
        self.app.pickup(self.request_id, self.staff_id, received_amount)

    def quoted_amount(self):
        return str(self.app.requests[self.request_id].quote.amount)

    def test_new_request_can_be_quoted_rejected_or_edited(self):
        self.assertEqual(self.actions(), [
            "Edit Customer", "Edit Addresses", "Prepare Quote",
            "Reject Request",
        ])
        self.assertEqual(
            self.next_step(),
            "Next step: Office Staff - Prepare Quote or Reject Request.",
        )

    def test_quoted_request_waits_for_the_customer(self):
        self.app.prepare_quote(self.request_id)
        self.assertEqual(self.actions(), [
            "Edit Customer", "Accept Quote", "Decline Quote",
        ])
        self.assertEqual(
            self.next_step(),
            "Next step: Customer - Accept Quote or Decline Quote.",
        )

    def test_accepted_request_waits_for_allocation(self):
        self.app.prepare_quote(self.request_id)
        self.app.respond_quote(self.request_id, True)
        self.assertEqual(self.actions(), ["Edit Customer", "Allocate Worker"])

    def test_allocated_request_waits_for_pickup(self):
        self.allocate()
        self.assertEqual(self.actions(), ["Edit Customer", "Record Pickup"])
        self.assertEqual(
            self.next_step(), "Next step: Delivery Staff - Record Pickup.",
        )

    def test_picked_up_request_waits_for_the_delivery_outcome(self):
        self.allocate()
        self.pick_up(self.quoted_amount())
        self.assertEqual(self.actions(), [
            "Edit Customer", "Delivered", "Failed Delivery",
        ])

    def test_payment_exception_blocks_delivery_until_authorised(self):
        self.allocate()
        self.pick_up("1")
        self.assertEqual(
            self.actions(), ["Edit Customer", "Authorise Payment Exception"],
        )
        self.assertEqual(
            self.next_step(),
            "Next step: Office Staff - Authorise Payment Exception.",
        )
        self.app.authorise_payment(
            self.request_id, "Office Manager", "Customer paid the rest later",
        )
        self.assertEqual(self.actions(), [
            "Edit Customer", "Delivered", "Failed Delivery",
        ])

    def test_failed_pickup_can_be_retried(self):
        self.allocate()
        request = self.app.requests[self.request_id]
        self.clock.now = request.quote.pickup_at
        self.app.pickup(
            self.request_id, self.staff_id, "", parcel_ok=False,
            failure="Customer not present",
        )
        self.assertEqual(self.actions(), ["Edit Customer", "Retry Pickup"])

    def test_delivered_request_is_complete(self):
        self.allocate()
        self.pick_up(self.quoted_amount())
        self.clock.now = self.app.requests[self.request_id].quote.delivery_at
        self.app.deliver(self.request_id, self.staff_id, True)
        self.assertEqual(self.actions(), ["Edit Customer"])
        self.assertEqual(
            self.next_step(), "Complete. No further actions are needed.",
        )

    def test_rejected_request_is_closed(self):
        self.app.reject_request(self.request_id, "Cannot fulfil")
        self.assertEqual(self.actions(), ["Edit Customer"])
        self.assertEqual(
            self.next_step(),
            "Closed (Rejected). No further actions are possible.",
        )


@unittest.skipIf(tk is None, "Tk runtime is not installed.")
class ActionButtonStateTests(unittest.TestCase):
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
        self.request_id = next(iter(self.app.requests))
        self.window = MainWindow(self.root, self.app)

    def enabled_labels(self):
        labels = []
        for label, button in self.window.action_buttons.items():
            if not button.instate(["disabled"]):
                labels.append(label)
        return labels

    def test_only_new_request_is_available_without_a_selection(self):
        self.assertEqual(self.enabled_labels(), ["New Request"])
        self.assertEqual(self.window.next_step.get(), NO_REQUEST_STEP)

    def test_selecting_a_request_enables_its_actions(self):
        self.window.request_tree.selection_set(self.request_id)
        self.window._show_request()
        self.assertEqual(self.enabled_labels(), [
            "New Request", "Edit Customer", "Edit Addresses",
            "Prepare Quote", "Reject Request",
        ])
        self.assertIn("Office Staff", self.window.next_step.get())

    def test_buttons_follow_the_request_after_an_action(self):
        self.app.prepare_quote(self.request_id)
        self.window.refresh(self.request_id)
        self.assertEqual(self.enabled_labels(), [
            "New Request", "Edit Customer", "Accept Quote", "Decline Quote",
        ])


if __name__ == "__main__":
    unittest.main()
