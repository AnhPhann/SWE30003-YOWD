"""Tests for the required-field marks on the New Request form."""

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
    from yowd.ui import MainWindow, NewRequestDialog


REQUIRED_LABELS = [
    "Customer name *", "Email *", "Phone *",
    "Pickup street / delivery address *", "Pickup suburb *",
    "Destination street / delivery address *", "Destination suburb *",
    "Description *", "Weight (kg) *", "Length (cm) *", "Width (cm) *",
    "Height (cm) *",
]


@unittest.skipIf(tk is None, "Tk runtime is not installed.")
class RequiredFieldTests(unittest.TestCase):
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
        window = MainWindow(self.root, self.app)
        self.dialog = NewRequestDialog(window)
        self.dialog.withdraw()

    def label_texts(self):
        """Return the text of every label in the form, top to bottom."""
        texts = []
        pending = [self.dialog]
        while pending:
            widget = pending.pop(0)
            pending.extend(widget.winfo_children())
            if isinstance(widget, ttk.Label):
                texts.append(str(widget.cget("text")))
        return texts

    def test_every_required_field_has_an_asterisk(self):
        texts = self.label_texts()
        for label in REQUIRED_LABELS:
            with self.subTest(label=label):
                self.assertIn(label, texts)

    def test_form_explains_the_asterisk(self):
        self.assertIn("* Required field", self.label_texts())


if __name__ == "__main__":
    unittest.main()
