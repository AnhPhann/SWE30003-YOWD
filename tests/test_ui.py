"""Withdrawn-window integration checks against the real application service.

No test loads user data or opens native message boxes. A graphical Tk runtime is
required; environments without a display report a specific skipped test reason.
"""

from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch

from yowd.application import YowdApplication

try:
    import tkinter as tk
    from tkinter import ttk
except ModuleNotFoundError as error:
    if error.name not in ("tkinter", "_tkinter"):
        raise
    tk = None
    TK_IMPORT_ERROR = str(error)
else:
    from yowd.ui import FormDialog, MainWindow, NewRequestDialog


class DesktopIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        if tk is None:
            self.skipTest(f"Tk runtime is not installed: {TK_IMPORT_ERROR}")
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk graphical runtime unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = YowdApplication(":memory:", clock=lambda: datetime(2026, 10, 22, 9))
        self.addCleanup(self.app.close)
        self.confirm = self.enterContext(patch("yowd.ui.messagebox.askyesno", return_value=True))
        self.show_error = self.enterContext(patch("yowd.ui.messagebox.showerror"))
        self.enterContext(patch("yowd.ui.messagebox.showinfo"))
        self.window = MainWindow(self.root, self.app)
        self.root.update_idletasks()

    def dialog(self) -> FormDialog:
        windows = [item for item in self.root.winfo_children() if isinstance(item, FormDialog)]
        self.assertEqual(len(windows), 1)
        windows[0].withdraw()
        return windows[0]

    def invoke(self, container: tk.Misc, label: str) -> None:
        def descendants(widget: tk.Misc):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        buttons = [
            widget for widget in descendants(container)
            if isinstance(widget, ttk.Button) and widget.cget("text") == label
        ]
        self.assertEqual(len(buttons), 1, f"Expected one {label!r} button")
        buttons[0].invoke()
        self.root.update_idletasks()

    @staticmethod
    def fill(dialog: FormDialog, **values: str) -> None:
        for key, value in values.items():
            dialog.variables[key].set(value)

    def seed_and_select(self) -> tuple[str, str]:
        self.window._seed_demo()
        request_id = self.app.overview()["requests"][0]["id"]
        staff_id = self.app.overview()["staff"][0]["id"]
        self.window.request_tree.selection_set(request_id)
        self.window._show_request()
        return request_id, staff_id

    def quote_accept_allocate(self) -> tuple[str, str]:
        request_id, staff_id = self.seed_and_select()
        self.window._quote()
        dialog = self.dialog()
        self.assertTrue(dialog.variables["pickup"].get())
        self.invoke(dialog, "Prepare quote")
        self.window._respond(True)
        self.window._allocate()
        dialog = self.dialog()
        worker_display = next(iter(self.window._worker_choices()))
        self.fill(dialog, staff=worker_display)
        self.invoke(dialog, "Allocate")
        self.assertEqual(self.app.overview()["requests"][0]["status"], "Allocated")
        return request_id, staff_id

    def pickup(self, amount: str | None = None) -> None:
        self.window._pickup()
        dialog = self.dialog()
        self.assertTrue(dialog.variables["amount"].get())
        self.fill(
            dialog, staff=next(iter(self.window._worker_choices())),
            parcels="All parcels collected and checked",
        )
        if amount is not None:
            self.fill(dialog, amount=amount)
        self.invoke(dialog, "Record pickup")

    def test_empty_startup_does_not_create_sample_records(self) -> None:
        self.assertEqual(self.app.overview()["requests"], [])
        self.assertEqual(self.app.overview()["staff"], [])
        self.assertFalse(self.window.request_tree.get_children())
        self.assertIn("No request selected", self.window.details.get("1.0", "end"))
        self.assertEqual(len(self.window.notebook.tabs()), 3)

    def test_new_request_validation_preserves_inputs_then_saves_correction(self) -> None:
        dialog = NewRequestDialog(self.window)
        dialog.withdraw()
        values = {
            "customer_name": "Anh Phan", "email": "invalid-email", "phone": "0400000001",
            "pickup": "Richmond", "destination": "Footscray",
        }
        for key, value in values.items():
            dialog.customer_variables[key].set(value)
        for key, variable in dialog.parcel_variables.items():
            variable.set("Books" if key == "description" else "2")
        self.invoke(dialog, "Add parcel")
        self.invoke(dialog, "Create request")
        self.assertTrue(dialog.winfo_exists())
        self.assertTrue(dialog.error.get())
        self.assertEqual(dialog.customer_variables["email"].get(), "invalid-email")
        self.assertEqual(len(dialog.parcels), 1)
        self.assertFalse(self.app.overview()["requests"])
        dialog.customer_variables["email"].set("anh@example.com")
        self.invoke(dialog, "Create request")
        self.assertFalse(dialog.winfo_exists())
        self.assertEqual(len(self.app.overview()["requests"]), 1)
        self.assertEqual(len(self.window.request_tree.get_children()), 1)

    def test_parcel_editing_and_cancel_do_not_save_a_request(self) -> None:
        dialog = NewRequestDialog(self.window)
        dialog.withdraw()
        for description in ("Books", "Clothing"):
            for key, variable in dialog.parcel_variables.items():
                variable.set(description if key == "description" else "2")
            self.invoke(dialog, "Add parcel")
        self.assertEqual(len(dialog.parcels), 2)
        dialog.parcel_tree.selection_set("0")
        self.invoke(dialog, "Remove selected parcel")
        self.assertEqual([parcel["description"] for parcel in dialog.parcels], ["Clothing"])
        self.invoke(dialog, "Cancel")
        self.assertFalse(self.app.overview()["requests"])

    def test_sample_data_requires_explicit_confirmation_then_refreshes(self) -> None:
        self.confirm.return_value = False
        self.window._seed_demo()
        self.assertFalse(self.app.overview()["requests"])
        self.confirm.return_value = True
        self.window._seed_demo()
        self.assertEqual(len(self.window.request_tree.get_children()), 1)
        self.assertEqual(len(self.window.staff_tree.get_children()), 1)
        self.assertIn("Sample data loaded", self.window.status.get())

    def test_successful_workflow_uses_real_service_and_refreshes_details(self) -> None:
        request_id, _staff_id = self.quote_accept_allocate()
        self.pickup()
        self.assertEqual(self.app.overview()["requests"][0]["status"], "Picked Up")
        self.window._delivery(True)
        dialog = self.dialog()
        self.fill(dialog, staff=next(iter(self.window._worker_choices())))
        self.invoke(dialog, "Record delivered")
        self.assertEqual(self.app.overview()["requests"][0]["status"], "Delivered")
        self.assertIn("Status: Delivered", self.window.details.get("1.0", "end"))
        self.assertIn(request_id, self.window.details.get("1.0", "end"))
        self.show_error.assert_not_called()

    def test_payment_exception_authorisation_requires_later_pickup_confirmation(self) -> None:
        self.quote_accept_allocate()
        self.pickup("1.00")
        row = self.app.overview()["requests"][0]
        self.assertEqual(row["status"], "Allocated")
        self.assertTrue(row["payment_exception"])
        self.window._authorise()
        dialog = self.dialog()
        self.fill(dialog, authorised_by="Office manager", reason="Approved business exception")
        self.invoke(dialog, "Record authorisation")
        self.assertEqual(self.app.overview()["requests"][0]["status"], "Allocated")
        self.assertIn("confirm pickup again", self.window.status.get())
        self.window._pickup()
        dialog = self.dialog()
        self.assertEqual(dialog.variables["amount"].get(), "1.00")
        self.fill(
            dialog, staff=next(iter(self.window._worker_choices())),
            parcels="All parcels collected and checked",
        )
        self.invoke(dialog, "Record pickup")
        self.assertEqual(self.app.overview()["requests"][0]["status"], "Picked Up")
        self.show_error.assert_not_called()

    def test_failed_pickup_retry_failed_delivery_and_statistics_forms(self) -> None:
        request_id, _staff_id = self.quote_accept_allocate()
        self.window._pickup()
        dialog = self.dialog()
        self.fill(
            dialog, staff=next(iter(self.window._worker_choices())),
            parcels="Pickup failed / parcels not collected",
        )
        self.invoke(dialog, "Record pickup")
        row = self.app.overview()["requests"][0]
        self.assertEqual(row["status"], "Failed pickup")
        self.assertEqual(row["payment"], "")
        self.window._retry_pickup()
        self.assertEqual(self.app.overview()["requests"][0]["status"], "Accepted")
        self.window._allocate()
        dialog = self.dialog()
        self.fill(dialog, staff=next(iter(self.window._worker_choices())))
        self.invoke(dialog, "Allocate")
        self.pickup()
        self.window._delivery(False)
        dialog = self.dialog()
        self.fill(dialog, staff=next(iter(self.window._worker_choices())))
        self.invoke(dialog, "Record failed delivery")
        self.assertTrue(dialog.winfo_exists())
        self.assertIn("reason", dialog.error.get())
        self.fill(dialog, reason="Recipient unavailable")
        self.invoke(dialog, "Record failed delivery")
        row = self.app.overview()["requests"][0]
        self.assertEqual(row["status"], "Failed delivery")
        self.assertEqual(row["payment"], "Recorded")
        self.assertIn("Recipient unavailable", self.app.request_details(request_id))
        self.window.statistics_start.set("2026-10-22")
        self.window.statistics_end.set("2026-10-22")
        self.window._statistics()
        self.assertIn("Failed outcomes: 1", self.window.statistics_text.get("1.0", "end"))
        self.show_error.assert_not_called()

    def test_staff_registration_replacement_and_deactivation_forms(self) -> None:
        self.window._register_staff()
        dialog = self.dialog()
        self.fill(
            dialog, name="New Driver", email="new@example.com", phone="0400000004",
            start="2026-10-23 08:00", end="2026-10-23 18:00",
        )
        self.invoke(dialog, "Register staff")
        staff_id = self.app.overview()["staff"][0]["id"]
        self.window.staff_tree.selection_set(staff_id)
        self.window._availability()
        dialog = self.dialog()
        self.fill(dialog, start1="2026-10-24 09:00", end1="2026-10-24 17:00")
        self.invoke(dialog, "Replace availability")
        self.assertIn("2026-10-24 09:00", self.app.overview()["staff"][0]["availability"])
        self.window._deactivate()
        self.assertFalse(self.app.overview()["staff"][0]["active"])
        self.assertEqual(len(self.window.staff_tree.get_children()), 1)
        self.show_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
