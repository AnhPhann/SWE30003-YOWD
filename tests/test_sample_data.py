"""Tests for the full sample data set loaded by the Load Sample Data button."""

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from yowd.__main__ import DemoClock
from yowd.application import YowdApplication
from yowd.models import DomainError


class LoadSampleDataTests(unittest.TestCase):
    def setUp(self):
        self.clock = DemoClock(datetime(2026, 10, 22, 9))
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database = Path(self.folder.name) / "sample.sqlite3"
        self.app = YowdApplication(self.database, clock=self.clock)
        # Closing twice is harmless, so tests may also close it early.
        self.addCleanup(self.app.close)

    def customer_names(self, app):
        names = []
        for request in app.requests.values():
            names.append(request.customer.name)
        return names

    def test_three_customers_each_have_one_request(self):
        self.app.load_sample_data()
        self.assertEqual(self.customer_names(self.app), [
            "Sample Customer", "Sample Customer Two",
            "Sample Customer Three",
        ])
        self.assertEqual(len(self.app.customers), 3)
        for customer in self.app.customers.values():
            with self.subTest(customer=customer.name):
                self.assertEqual(len(customer.request_ids), 1)

    def test_every_sample_request_starts_as_requested(self):
        self.app.load_sample_data()
        for row in self.app.overview()["requests"]:
            with self.subTest(request=row["id"]):
                self.assertEqual(row["status"], "Requested")

    def test_every_sample_request_can_be_quoted(self):
        self.app.load_sample_data()
        for request_id in list(self.app.requests):
            with self.subTest(request=request_id):
                self.app.prepare_quote(request_id)

    def test_sample_data_survives_restart(self):
        self.app.load_sample_data()
        self.app.close()
        reopened = YowdApplication(self.database, clock=self.clock)
        self.addCleanup(reopened.close)
        self.assertEqual(len(reopened.requests), 3)

    def test_sample_data_needs_an_empty_application(self):
        self.app.load_sample_data()
        with self.assertRaises(DomainError):
            self.app.load_sample_data()
        self.assertEqual(len(self.app.requests), 3)


if __name__ == "__main__":
    unittest.main()
