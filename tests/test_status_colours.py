"""Tests for the colour-coded request statuses and their legend."""

from datetime import datetime
import unittest

from yowd.__main__ import DemoClock
from yowd.application import YowdApplication
from yowd.models import RequestStatus

try:
    import tkinter as tk
except ModuleNotFoundError:
    tk = None
else:
    from yowd.ui import (
        SELECTED_ROW_TAG, STATUS_COLOURS, STATUS_LEGEND, MainWindow,
    )


class FakeClick:
    """Stands in for a mouse click event at a height in the table."""

    def __init__(self, y):
        self.y = y


@unittest.skipIf(tk is None, "Tk runtime is not installed.")
class StatusColourTests(unittest.TestCase):
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
        self.app.seed_demo()
        self.request_id = next(iter(self.app.requests))
        self.window = MainWindow(self.root, self.app)

    def row_colour(self):
        """Return the background colour of the request's row as text."""
        tags = self.window.request_tree.item(self.request_id, "tags")
        colour = self.window.request_tree.tag_configure(
            tags[0], "background",
        )
        return str(colour)

    def select_request(self):
        self.window.request_tree.selection_set(self.request_id)
        self.window._show_request()

    def row_tags(self):
        tags = self.window.request_tree.item(self.request_id, "tags")
        return list(tags)

    def test_every_status_has_a_colour(self):
        for status in RequestStatus:
            with self.subTest(status=status.value):
                self.assertIn(status.value, STATUS_COLOURS)

    def test_main_statuses_have_their_own_colours(self):
        main_statuses = ("Requested", "Accepted", "Picked Up", "Delivered")
        colours = set()
        for status in main_statuses:
            colours.add(STATUS_COLOURS[status])
        self.assertEqual(len(colours), len(main_statuses))

    def test_every_colour_appears_in_the_legend(self):
        legend_colours = set()
        for status, _legend_text in STATUS_LEGEND:
            legend_colours.add(STATUS_COLOURS[status])
        self.assertEqual(legend_colours, set(STATUS_COLOURS.values()))

    def test_row_colour_follows_the_request_status(self):
        self.assertEqual(self.row_colour(), STATUS_COLOURS["Requested"])
        self.app.prepare_quote(self.request_id)
        self.window.refresh()
        self.assertEqual(self.row_colour(), STATUS_COLOURS["Quoted"])

    def test_selected_row_keeps_its_status_colour(self):
        self.select_request()
        self.assertEqual(self.row_tags(), ["Requested", SELECTED_ROW_TAG])
        self.assertEqual(self.row_colour(), STATUS_COLOURS["Requested"])

    def test_escape_clears_the_selection(self):
        self.select_request()
        self.window._clear_request_selection()
        self.assertEqual(self.window.request_tree.selection(), ())
        self.assertEqual(self.row_tags(), ["Requested"])
        self.assertIn("Select a request", self.window.next_step.get())

    def test_clicking_empty_space_clears_the_selection(self):
        self.select_request()
        self.window._click_request_table(FakeClick(5000))
        self.assertEqual(self.window.request_tree.selection(), ())


if __name__ == "__main__":
    unittest.main()
