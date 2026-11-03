"""Tests for office staff rejecting a request that cannot be fulfilled."""

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from yowd.__main__ import DemoClock
from yowd.application import YowdApplication
from yowd.models import DomainError, RequestStatus

try:
    import tkinter as tk
    from tkinter import ttk
except ModuleNotFoundError:
    tk = None
else:
    from yowd.ui import FormDialog, MainWindow


class RejectRequestTests(unittest.TestCase):
    def setUp(self):
        self.clock = DemoClock(datetime(2026, 10, 22, 9))
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database = Path(self.folder.name) / "rejection.sqlite3"
        self.app = YowdApplication(self.database, clock=self.clock)
        # Closing twice is harmless, so tests may also close it early.
        self.addCleanup(self.app.close)
        self.app.seed_demo()
        self.request_id = next(iter(self.app.requests))

    def test_requested_request_is_rejected_with_its_reason(self):
        self.app.reject_request(self.request_id, "Oversized for our vehicles")
        request = self.app.requests[self.request_id]
        self.assertEqual(request.status, RequestStatus.REJECTED)
        self.assertEqual(request.failure_reason, "Oversized for our vehicles")
        self.assertIn(
            "Oversized for our vehicles",
            self.app.request_details(self.request_id),
        )

    def test_blank_reason_is_rejected_without_changes(self):
        with self.assertRaises(DomainError):
            self.app.reject_request(self.request_id, "   ")
        request = self.app.requests[self.request_id]
        self.assertEqual(request.status, RequestStatus.REQUESTED)
        self.assertEqual(request.failure_reason, "")

    def test_quoted_request_cannot_be_rejected(self):
        self.app.prepare_quote(self.request_id)
        with self.assertRaises(DomainError):
            self.app.reject_request(self.request_id, "Too late to reject")
        request = self.app.requests[self.request_id]
        self.assertEqual(request.status, RequestStatus.QUOTED)

    def test_unknown_request_is_rejected(self):
        with self.assertRaises(DomainError):
            self.app.reject_request("REQ-NONE", "No such request")

    def test_rejection_survives_restart(self):
        self.app.reject_request(self.request_id, "Address is unsafe to visit")
        self.app.close()
        reopened = YowdApplication(self.database, clock=self.clock)
        self.addCleanup(reopened.close)
        request = reopened.requests[self.request_id]
        self.assertEqual(request.status, RequestStatus.REJECTED)
        self.assertEqual(request.failure_reason, "Address is unsafe to visit")

    def test_rejected_request_is_not_counted_as_an_outcome(self):
        self.app.reject_request(self.request_id, "Cannot fulfil")
        day = self.clock.now.date()
        result = self.app.statistics(day, day)
        self.assertEqual((result["completed"], result["failed"]), (0, 0))


@unittest.skipIf(tk is None, "Tk runtime is not installed.")
class RejectRequestFormTests(unittest.TestCase):
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
        self.window.request_tree.selection_set(self.request_id)

    def open_form(self):
        """Open the Reject Request form and return it hidden."""
        self.window._reject_request()
        forms = []
        for child in self.root.winfo_children():
            if isinstance(child, FormDialog):
                forms.append(child)
        self.assertEqual(len(forms), 1)
        forms[0].withdraw()
        return forms[0]

    def press_reject(self, form):
        """Press the form's Reject request button."""
        pending = list(form.winfo_children())
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if isinstance(widget, ttk.Button):
                if widget.cget("text") == "Reject request":
                    widget.invoke()
                    return
        self.fail("Reject request button not found.")

    def test_blank_reason_keeps_form_open(self):
        form = self.open_form()
        self.press_reject(form)
        self.assertTrue(form.winfo_exists())
        self.assertIn("Rejection reason", form.error.get())
        self.assertEqual(
            self.app.requests[self.request_id].status,
            RequestStatus.REQUESTED,
        )

    def test_reason_rejects_request_and_closes_form(self):
        form = self.open_form()
        form.variables["reason"].set("Parcel type not accepted")
        self.press_reject(form)
        self.assertFalse(form.winfo_exists())
        self.assertEqual(
            self.app.requests[self.request_id].status,
            RequestStatus.REJECTED,
        )
        self.assertIn("rejected", self.window.status.get())


if __name__ == "__main__":
    unittest.main()
