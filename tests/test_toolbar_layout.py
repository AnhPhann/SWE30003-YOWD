"""Tests for the role grouping and order of the request action buttons."""

from datetime import datetime
import unittest

from yowd.__main__ import DemoClock
from yowd.application import YowdApplication

try:
    import tkinter as tk
    from tkinter import ttk
except ModuleNotFoundError:
    tk = None
else:
    from yowd.ui import MainWindow


EXPECTED_ORDER = {
    "Customer": [
        "New Request", "Edit Customer", "Edit Addresses",
        "Accept Quote", "Decline Quote",
    ],
    "Office Staff": [
        "Prepare Quote", "Reject Request", "Allocate Worker",
        "Authorise Payment Exception", "Retry Pickup",
    ],
    "Delivery Staff": ["Record Pickup", "Delivered", "Failed Delivery"],
}


@unittest.skipIf(tk is None, "Tk runtime is not installed.")
class ToolbarLayoutTests(unittest.TestCase):
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
        self.window = MainWindow(self.root, self.app)

    def button_labels(self, role):
        """Return a role's button labels, left to right then downwards."""
        positions = []
        for widget in self.window.action_rows[role].grid_slaves():
            if isinstance(widget, ttk.Button):
                grid = widget.grid_info()
                positions.append(
                    (grid["row"], grid["column"], widget.cget("text")),
                )
        positions.sort()
        labels = []
        for _row, _column, label in positions:
            labels.append(label)
        return labels

    def test_roles_are_listed_in_order(self):
        self.assertEqual(
            list(self.window.action_rows), list(EXPECTED_ORDER),
        )

    def test_each_role_lists_its_buttons_in_workflow_order(self):
        for role, expected_labels in EXPECTED_ORDER.items():
            with self.subTest(role=role):
                self.assertEqual(self.button_labels(role), expected_labels)

    def test_roles_sit_side_by_side_in_titled_boxes(self):
        column = 0
        for role, role_box in self.window.action_rows.items():
            with self.subTest(role=role):
                self.assertIsInstance(role_box, ttk.LabelFrame)
                self.assertEqual(role_box.cget("text"), role)
                self.assertEqual(role_box.grid_info()["row"], 0)
                self.assertEqual(role_box.grid_info()["column"], column)
            column += 1

    def test_buttons_are_two_to_a_row(self):
        for role, role_box in self.window.action_rows.items():
            with self.subTest(role=role):
                columns = set()
                for widget in role_box.grid_slaves():
                    columns.add(widget.grid_info()["column"])
                self.assertEqual(columns, {0, 1})


if __name__ == "__main__":
    unittest.main()
