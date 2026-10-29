"""Tests for successful and failed delivery outcomes and their reasons."""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from yowd.__main__ import DemoClock
from yowd.application import YowdApplication
from yowd.models import (
    Customer, DeliveryQuote, DeliveryRequest, DeliveryStaff, DomainError,
    Parcel, ParcelStatus, PaymentRecord, RequestStatus,
)

try:
    import tkinter as tk
    from tkinter import ttk
except ModuleNotFoundError:
    tk = None
else:
    from yowd.ui import FormDialog, MainWindow


def take_sample_request_to_pickup(app, clock):
    """Load sample data and take its request through quote and pickup.

    The clock is moved to the quoted pickup time, then to the quoted
    delivery time. Returns the request ID and the allocated staff ID.
    """
    app.seed_demo()
    request_id = next(iter(app.requests))
    staff_id = next(iter(app.staff_list.staff))
    amount = app.prepare_quote(request_id)
    app.respond_quote(request_id, True)
    app.allocate(request_id, staff_id)
    clock.now = app.requests[request_id].quote.pickup_at
    app.pickup(request_id, staff_id, str(amount))
    clock.now = app.requests[request_id].quote.delivery_at
    return request_id, staff_id


class FailedDeliveryReasonTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 22, 9)
        self.customer = Customer(
            "C1", "Anh Phan", "anh@example.com", "0400 123 456",
        )
        self.outcome_time = self.now + timedelta(hours=2)

    def picked_up_request(self):
        """Build a two-parcel request that has been picked up and paid.

        A new worker is created each time because a worker keeps the IDs
        of every assignment it has been given.
        """
        worker = DeliveryStaff(
            "S1", "Alex Tran", "alex@example.com", "0400111222",
        )
        worker.schedule.add_period(self.now, self.now + timedelta(hours=10))
        parcels = [
            Parcel(
                "P1", "Books",
                Decimal("2"), Decimal("20"), Decimal("15"), Decimal("10"),
            ),
            Parcel(
                "P2", "Clothing",
                Decimal("1"), Decimal("30"), Decimal("25"), Decimal("15"),
            ),
        ]
        request = DeliveryRequest(
            "R1", self.customer, "Richmond", "Footscray", parcels, self.now,
        )
        request.issue_quote(DeliveryQuote(
            "Q1", "R1", Decimal("25"),
            self.now + timedelta(hours=1), self.now + timedelta(hours=2),
            self.now + timedelta(minutes=1),
        ))
        request.respond_to_quote("C1", True)
        request.allocate(worker, "A1", self.now + timedelta(minutes=5))
        pickup_time = self.now + timedelta(hours=1)
        payment = PaymentRecord(
            "PAY1", "R1", Decimal("25"), Decimal("25"), pickup_time,
        )
        request.record_pickup("S1", True, payment, pickup_time)
        return request

    def assert_unchanged(self, request):
        """Check a rejected report left the request picked up and active."""
        self.assertEqual(request.status, RequestStatus.PICKED_UP)
        self.assertIsNotNone(request.active_assignment)
        self.assertEqual(request.failure_reason, "")
        for parcel in request.parcels:
            self.assertEqual(parcel.status, ParcelStatus.COLLECTED)

    def test_recipient_not_present_is_recorded(self):
        request = self.picked_up_request()
        request.record_delivery(
            "S1", False, "", self.outcome_time,
            failure="Recipient not present",
        )
        self.assertEqual(request.status, RequestStatus.FAILED_DELIVERY)
        self.assertEqual(
            request.failure_reason, "Failed delivery: Recipient not present.",
        )

    def test_destination_problem_keeps_optional_details(self):
        request = self.picked_up_request()
        request.record_delivery(
            "S1", False, "Gate locked, no answer on intercom.",
            self.outcome_time,
            failure="Destination inaccessible or incorrect",
        )
        self.assertEqual(
            request.failure_reason,
            "Failed delivery: Destination inaccessible or incorrect. "
            "Details: Gate locked, no answer on intercom.",
        )

    def test_damaged_parcel_names_the_affected_parcel(self):
        request = self.picked_up_request()
        request.record_delivery(
            "S1", False, "", self.outcome_time,
            failure="Parcel damaged", parcel_id="P2",
        )
        self.assertEqual(
            request.failure_reason,
            "Failed delivery: Parcel damaged - Clothing (P2).",
        )
        for parcel in request.parcels:
            self.assertEqual(parcel.status, ParcelStatus.RETURN_REQUIRED)

    def test_parcel_reasons_require_a_parcel_from_this_request(self):
        for failure in ("Parcel missing", "Parcel damaged"):
            for parcel_id in (None, "NOT-IN-REQUEST"):
                request = self.picked_up_request()
                with self.subTest(failure=failure, parcel_id=parcel_id):
                    with self.assertRaises(DomainError):
                        request.record_delivery(
                            "S1", False, "", self.outcome_time,
                            failure=failure, parcel_id=parcel_id,
                        )
                    self.assert_unchanged(request)

    def test_other_reason_requires_details(self):
        request = self.picked_up_request()
        with self.assertRaises(DomainError):
            request.record_delivery(
                "S1", False, "  ", self.outcome_time, failure="Other",
            )
        self.assert_unchanged(request)
        request.record_delivery(
            "S1", False, "Vehicle breakdown", self.outcome_time,
            failure="Other",
        )
        self.assertEqual(
            request.failure_reason,
            "Failed delivery: Other. Details: Vehicle breakdown.",
        )

    def test_unknown_reason_is_rejected_without_changes(self):
        request = self.picked_up_request()
        with self.assertRaises(DomainError):
            request.record_delivery(
                "S1", False, "", self.outcome_time, failure="Lost in transit",
            )
        self.assert_unchanged(request)

    def test_free_text_reason_without_selection_still_works(self):
        request = self.picked_up_request()
        request.record_delivery(
            "S1", False, "Recipient absent", self.outcome_time,
        )
        self.assertEqual(request.failure_reason, "Recipient absent")

    def test_wrong_worker_is_rejected_before_reason_is_recorded(self):
        request = self.picked_up_request()
        with self.assertRaises(DomainError):
            request.record_delivery(
                "S9", False, "", self.outcome_time,
                failure="Recipient not present",
            )
        self.assert_unchanged(request)

    def test_successful_delivery_ignores_failure_fields(self):
        request = self.picked_up_request()
        request.record_delivery(
            "S1", True, "", self.outcome_time, failure="Parcel damaged",
        )
        self.assertEqual(request.status, RequestStatus.DELIVERED)
        self.assertEqual(request.failure_reason, "")


class ApplicationDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.clock = DemoClock(datetime(2026, 10, 22, 9))
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database = Path(self.folder.name) / "delivery.sqlite3"

    def test_reasons_offered_match_the_domain_values(self):
        self.assertEqual(
            YowdApplication.delivery_failure_reasons(),
            [
                "Recipient not present",
                "Destination inaccessible or incorrect",
                "Parcel missing",
                "Parcel damaged",
                "Other",
            ],
        )

    def test_failed_delivery_reason_survives_restart(self):
        app = YowdApplication(self.database, clock=self.clock)
        request_id, staff_id = take_sample_request_to_pickup(app, self.clock)
        parcel_id = app.requests[request_id].parcels[0].parcel_id
        message = app.deliver(
            request_id, staff_id, False, "Box crushed",
            failure="Parcel damaged", parcel_id=parcel_id,
        )
        self.assertIn("Parcel damaged", message)
        app.close()

        reopened = YowdApplication(self.database, clock=self.clock)
        self.addCleanup(reopened.close)
        request = reopened.requests[request_id]
        self.assertEqual(request.status, RequestStatus.FAILED_DELIVERY)
        self.assertIn(parcel_id, request.failure_reason)
        self.assertIn("Details: Box crushed", request.failure_reason)
        self.assertIsNotNone(request.payment)
        self.assertIn(
            "Parcel damaged", reopened.request_details(request_id),
        )

    def test_check_returns_text_without_saving(self):
        app = YowdApplication(self.database, clock=self.clock)
        self.addCleanup(app.close)
        request_id, _staff_id = take_sample_request_to_pickup(app, self.clock)
        text = app.check_failed_delivery(
            request_id, failure="Recipient not present",
        )
        self.assertEqual(text, "Failed delivery: Recipient not present.")
        self.assertEqual(
            app.requests[request_id].status, RequestStatus.PICKED_UP,
        )
        with self.assertRaises(DomainError):
            app.check_failed_delivery(request_id, failure="Parcel missing")

    def test_rejected_failure_report_saves_nothing(self):
        app = YowdApplication(self.database, clock=self.clock)
        self.addCleanup(app.close)
        request_id, staff_id = take_sample_request_to_pickup(app, self.clock)
        with self.assertRaises(DomainError):
            app.deliver(request_id, staff_id, False, failure="Parcel missing")
        self.assertEqual(
            app.requests[request_id].status, RequestStatus.PICKED_UP,
        )


@unittest.skipIf(tk is None, "Tk runtime is not installed.")
class FailedDeliveryFormTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk graphical runtime unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.clock = DemoClock(datetime(2026, 10, 22, 9))
        self.app = YowdApplication(":memory:", clock=self.clock)
        self.addCleanup(self.app.close)
        self.confirm = self.enterContext(
            patch("yowd.ui.messagebox.askyesno", return_value=True)
        )
        self.show_error = self.enterContext(
            patch("yowd.ui.messagebox.showerror")
        )
        self.enterContext(patch("yowd.ui.messagebox.showinfo"))
        self.window = MainWindow(self.root, self.app)
        self.request_id, _staff_id = take_sample_request_to_pickup(
            self.app, self.clock,
        )
        self.window.refresh()
        self.window.request_tree.selection_set(self.request_id)
        self.window._show_request()

    def open_form(self):
        """Open the failed delivery form and return it hidden."""
        self.window._delivery(False)
        forms = []
        for child in self.root.winfo_children():
            if isinstance(child, FormDialog):
                forms.append(child)
        self.assertEqual(len(forms), 1)
        forms[0].withdraw()
        return forms[0]

    def submit(self, form):
        """Press the form's Record Failed Delivery button."""
        pending = list(form.winfo_children())
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if isinstance(widget, ttk.Button):
                if widget.cget("text") == "Record Failed Delivery":
                    widget.invoke()
                    return
        self.fail("Record Failed Delivery button not found.")

    def test_form_offers_reasons_and_parcels(self):
        form = self.open_form()
        self.assertEqual(
            form.choices["failure"], self.app.delivery_failure_reasons(),
        )
        self.assertEqual(len(form.choices["parcel"]), 2)

    def test_empty_form_shows_error_and_records_nothing(self):
        form = self.open_form()
        form.variables["staff"].set(form.choices["staff"][0])
        self.submit(form)
        self.assertTrue(form.winfo_exists())
        self.assertIn("failure reason", form.error.get())
        self.assertEqual(
            self.app.requests[self.request_id].status,
            RequestStatus.PICKED_UP,
        )

    def test_missing_parcel_without_parcel_keeps_form_open(self):
        form = self.open_form()
        form.variables["staff"].set(form.choices["staff"][0])
        form.variables["failure"].set("Parcel missing")
        self.submit(form)
        self.assertTrue(form.winfo_exists())
        self.assertIn("affected parcel", form.error.get())
        self.confirm.assert_not_called()
        self.assertEqual(
            self.app.requests[self.request_id].status,
            RequestStatus.PICKED_UP,
        )

    def test_confirmation_shows_the_text_to_be_recorded(self):
        form = self.open_form()
        form.variables["staff"].set(form.choices["staff"][0])
        form.variables["failure"].set("Recipient not present")
        self.submit(form)
        prompt = self.confirm.call_args.args[1]
        self.assertIn("Failed delivery: Recipient not present.", prompt)

    def test_selected_reason_and_parcel_are_recorded(self):
        form = self.open_form()
        form.variables["staff"].set(form.choices["staff"][0])
        form.variables["failure"].set("Parcel missing")
        form.variables["parcel"].set(form.choices["parcel"][1])
        self.submit(form)
        request = self.app.requests[self.request_id]
        self.assertEqual(request.status, RequestStatus.FAILED_DELIVERY)
        self.assertIn("Parcel missing - Clothing", request.failure_reason)
        self.assertIn(
            "Failed delivery", self.window.details.get("1.0", "end"),
        )
        self.show_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()