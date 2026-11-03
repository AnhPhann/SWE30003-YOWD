"""Tests for customer contact changes and request ownership."""

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from yowd.__main__ import DemoClock
from yowd.application import YowdApplication
from yowd.models import Customer, DomainError

try:
    import tkinter as tk
    from tkinter import ttk
except ModuleNotFoundError:
    tk = None
else:
    from yowd.ui import FormDialog, MainWindow


PARCEL = {
    "description": "Shoes", "weight_kg": "1", "length_cm": "30",
    "width_cm": "20", "height_cm": "15",
}


class CustomerModelTests(unittest.TestCase):
    def customer(self):
        return Customer(
            "C1", "Anh Phan", "anh@example.com", "0400 123 456",
            request_ids=["R1", "R2"],
        )

    def test_contact_details_can_be_updated(self):
        customer = self.customer()
        customer.update_contact(
            " Anh Tran ", "anh.tran@example.com", "0400999888",
        )
        self.assertEqual(
            (customer.name, customer.email, customer.phone),
            ("Anh Tran", "anh.tran@example.com", "0400999888"),
        )

    def test_invalid_update_changes_nothing(self):
        customer = self.customer()
        with self.assertRaises(DomainError):
            customer.update_contact("New Name", "not-an-email", "0400999888")
        self.assertEqual(customer.name, "Anh Phan")
        self.assertEqual(customer.email, "anh@example.com")

    def test_owns_request(self):
        customer = self.customer()
        self.assertTrue(customer.owns_request("R1"))
        self.assertFalse(customer.owns_request("R9"))


class CustomerApplicationTests(unittest.TestCase):
    def setUp(self):
        self.clock = DemoClock(datetime(2026, 10, 22, 9))
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database = Path(self.folder.name) / "customers.sqlite3"
        self.app = YowdApplication(self.database, clock=self.clock)
        # Closing twice is harmless, so tests may also close it early.
        self.addCleanup(self.app.close)
        self.app.seed_demo()
        self.first_request = next(iter(self.app.requests))
        self.second_request = self.app.create_request(
            "Sample Customer", "customer@example.com", "0400000002",
            "Richmond", "Footscray", [PARCEL],
            pickup_address="1 Church Street",
            destination_address="2 Barkly Street",
        )
        self.customer_id = self.app.requests[
            self.first_request
        ].customer.customer_id

    def test_details_list_every_request_and_its_status(self):
        self.app.prepare_quote(self.first_request)
        details = self.app.customer_details(self.second_request)
        self.assertEqual(details["name"], "Sample Customer")
        self.assertEqual(details["requests"], [
            (self.first_request, "Quoted"),
            (self.second_request, "Requested"),
        ])

    def test_update_applies_to_all_requests_and_survives_restart(self):
        self.app.update_customer_contact(
            self.customer_id, "Sam Sample", "sam@example.com", "0400777666",
        )
        self.assertEqual(
            self.app.requests[self.second_request].customer.name,
            "Sam Sample",
        )
        self.app.close()
        reopened = YowdApplication(self.database, clock=self.clock)
        self.addCleanup(reopened.close)
        for request_id in (self.first_request, self.second_request):
            customer = reopened.requests[request_id].customer
            self.assertEqual(customer.email, "sam@example.com")

    def test_email_of_another_customer_is_rejected(self):
        self.app.create_request(
            "Other Person", "other@example.com", "0400555444",
            "Richmond", "Footscray", [PARCEL],
            pickup_address="3 Swan Street",
            destination_address="4 Barkly Street",
        )
        with self.assertRaisesRegex(DomainError, "another customer"):
            self.app.update_customer_contact(
                self.customer_id, "Sample Customer", "OTHER@example.com",
                "0400000002",
            )
        customer = self.app.customers[self.customer_id]
        self.assertEqual(customer.email, "customer@example.com")

    def test_unknown_customer_is_rejected(self):
        with self.assertRaises(DomainError):
            self.app.update_customer_contact(
                "CUS-NONE", "Name", "name@example.com", "0400111222",
            )

    def test_quote_response_requires_request_ownership(self):
        self.app.prepare_quote(self.first_request)
        customer = self.app.requests[self.first_request].customer
        customer.request_ids.remove(self.first_request)
        with self.assertRaises(DomainError):
            self.app.requests[self.first_request].respond_to_quote(
                customer.customer_id, True,
            )


@unittest.skipIf(tk is None, "Tk runtime is not installed.")
class EditCustomerFormTests(unittest.TestCase):
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
        self.window._edit_customer()
        forms = []
        for child in self.root.winfo_children():
            if isinstance(child, FormDialog):
                forms.append(child)
        self.assertEqual(len(forms), 1)
        forms[0].withdraw()
        return forms[0]

    def press_save(self, form):
        pending = list(form.winfo_children())
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if isinstance(widget, ttk.Button):
                if widget.cget("text") == "Save customer":
                    widget.invoke()
                    return
        self.fail("Save customer button not found.")

    def test_form_is_prefilled_and_saves_changes(self):
        form = self.open_form()
        self.assertEqual(form.variables["name"].get(), "Sample Customer")
        form.variables["phone"].set("0400123123")
        self.press_save(form)
        self.assertFalse(form.winfo_exists())
        customer = self.app.requests[self.request_id].customer
        self.assertEqual(customer.phone, "0400123123")

    def test_invalid_email_keeps_form_open(self):
        form = self.open_form()
        form.variables["email"].set("broken")
        self.press_save(form)
        self.assertTrue(form.winfo_exists())
        self.assertIn("email", form.error.get())


if __name__ == "__main__":
    unittest.main()
