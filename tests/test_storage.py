"""Portable persistence tests using temporary databases only."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from yowd.storage import SQLiteStore, StorageError


def make_snapshot(name: str = "Anh") -> dict:
    return {
        "schema_version": 1,
        "customers": [{"id": "customer-1", "name": name}],
        "staff": [],
        "requests": [{"id": "request-1", "parcels": [], "quote": None}],
    }


class SQLiteStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "data" / "yowd.sqlite3"

    def open_store(self) -> SQLiteStore:
        store = SQLiteStore(self.path)
        self.addCleanup(store.close)
        return store

    def write_raw_snapshot(self, encoded: str) -> None:
        with self.open_store():
            pass
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "INSERT INTO application_state VALUES (1, 1, ?)", (encoded,)
            )

    def test_empty_store_creates_parent_directory(self) -> None:
        store = self.open_store()
        self.assertEqual(store.path, self.path)
        self.assertTrue(self.path.exists())
        self.assertIsNone(store.load())

    def test_memory_database_is_supported(self) -> None:
        with SQLiteStore(":memory:") as store:
            self.assertEqual(store.path, ":memory:")
            self.assertIsNone(store.load())
            store.save(make_snapshot())
            self.assertEqual(store.load(), make_snapshot())

    def test_snapshot_survives_close_and_reopen(self) -> None:
        original = make_snapshot("Anh Phan \u2013 kh\u00e1ch h\u00e0ng")
        original["requests"][0]["collected"] = True
        with self.open_store() as store:
            store.save(original)
        with self.open_store() as reopened:
            self.assertEqual(reopened.load(), original)

    def test_version_two_snapshot_can_be_saved_and_reopened(self) -> None:
        snapshot = make_snapshot()
        snapshot["schema_version"] = 2
        snapshot["requests"][0].update(
            pickup_address="12 Swan Street", destination_address="8 Hopkins Street"
        )
        try:
            with self.open_store() as store:
                store.save(snapshot)
        except StorageError as error:
            self.fail(f"The current snapshot schema must be writable: {error}")
        with self.open_store() as reopened:
            self.assertEqual(reopened.load(), snapshot)

    def test_version_three_snapshot_preserves_assignment_details_when_reopened(self) -> None:
        snapshot = make_snapshot()
        snapshot["schema_version"] = 3
        snapshot["requests"][0]["assignments"] = [{
            "assignment_id": "A1", "outcome": "Failed pickup",
            "outcome_details": "Failed Pickup: Parcel damaged - Books (P1).",
        }]
        with self.open_store() as store:
            store.save(snapshot)
        with self.open_store() as reopened:
            self.assertEqual(reopened.load(), snapshot)

    def test_loading_legacy_snapshot_does_not_rewrite_or_advance_revision(self) -> None:
        encoded = json.dumps(make_snapshot())
        self.write_raw_snapshot(encoded)
        with self.open_store() as store:
            self.assertEqual(store.load(), make_snapshot())
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute(
                "SELECT revision, snapshot FROM application_state"
            ).fetchone(), (1, encoded))

    def test_multiple_saves_advance_revision(self) -> None:
        store = self.open_store()
        store.save(make_snapshot("First"))
        store.save(make_snapshot("Second"))
        self.assertEqual(store.load(), make_snapshot("Second"))
        with closing(sqlite3.connect(self.path)) as connection, connection:
            revision = connection.execute(
                "SELECT revision FROM application_state"
            ).fetchone()[0]
        self.assertEqual(revision, 2)

    def test_unserializable_snapshot_does_not_change_saved_state(self) -> None:
        store = self.open_store()
        store.save(make_snapshot("Original"))
        invalid = make_snapshot("Should not save")
        invalid["requests"][0]["invalid"] = {"a set"}
        with self.assertRaises(StorageError):
            store.save(invalid)
        with self.open_store() as reader:
            self.assertEqual(reader.load(), make_snapshot("Original"))
        store.save(make_snapshot("Recovered"))
        self.assertEqual(store.load(), make_snapshot("Recovered"))

    def test_non_finite_numbers_are_not_saved(self) -> None:
        store = self.open_store()
        for number in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(number=number):
                snapshot = make_snapshot()
                snapshot["invalid"] = number
                with self.assertRaises(StorageError):
                    store.save(snapshot)
        self.assertIsNone(store.load())

    def test_save_rejects_non_object_and_unsupported_versions(self) -> None:
        store = self.open_store()
        for snapshot in ([], {}, {"schema_version": 99}, {"schema_version": True}):
            with self.subTest(snapshot=snapshot):
                with self.assertRaises(StorageError):
                    store.save(snapshot)
        self.assertIsNone(store.load())

    def test_malformed_json_is_not_treated_as_empty(self) -> None:
        encoded = '{"schema_version": 1, invalid'
        self.write_raw_snapshot(encoded)
        store = self.open_store()
        with self.assertRaisesRegex(StorageError, "not valid JSON"):
            store.load()
        with self.assertRaisesRegex(StorageError, "Load a valid snapshot"):
            store.save(make_snapshot())
        with closing(sqlite3.connect(self.path)) as connection, connection:
            self.assertEqual(
                connection.execute("SELECT snapshot FROM application_state").fetchone()[0],
                encoded,
            )

    def test_load_rejects_unsupported_version(self) -> None:
        self.write_raw_snapshot('{"schema_version": 999}')
        with self.open_store() as store:
            with self.assertRaisesRegex(StorageError, "Unsupported snapshot schema"):
                store.load()

    def test_load_rejects_non_object_json(self) -> None:
        self.write_raw_snapshot("[]")
        with self.open_store() as store:
            with self.assertRaisesRegex(StorageError, "must be a JSON object"):
                store.load()

    def test_load_rejects_non_standard_nan_json(self) -> None:
        self.write_raw_snapshot('{"schema_version": 1, "invalid": NaN}')
        with self.open_store() as store:
            with self.assertRaisesRegex(StorageError, "not valid JSON"):
                store.load()

    def test_stale_writer_cannot_overwrite_a_newer_snapshot(self) -> None:
        first = self.open_store()
        first.save(make_snapshot("Original"))
        second = self.open_store()
        self.assertEqual(second.load(), make_snapshot("Original"))
        first.save(make_snapshot("First writer"))
        with self.assertRaisesRegex(StorageError, "state changed"):
            second.save(make_snapshot("Stale writer"))
        self.assertEqual(second.load(), make_snapshot("First writer"))
        second.save(make_snapshot("Resolved"))
        self.assertEqual(first.load(), make_snapshot("Resolved"))

    def test_two_initial_writers_cannot_both_insert(self) -> None:
        first = self.open_store()
        second = self.open_store()
        self.assertIsNone(first.load())
        self.assertIsNone(second.load())
        first.save(make_snapshot("First"))
        with self.assertRaisesRegex(StorageError, "state changed"):
            second.save(make_snapshot("Second"))
        self.assertEqual(second.load(), make_snapshot("First"))

    def test_existing_state_cannot_be_replaced_without_loading(self) -> None:
        self.open_store().save(make_snapshot("Original"))
        new_store = self.open_store()
        with self.assertRaisesRegex(StorageError, "state changed"):
            new_store.save(make_snapshot("Unloaded"))
        self.assertEqual(new_store.load(), make_snapshot("Original"))

    def test_database_write_failure_rolls_back_and_allows_retry(self) -> None:
        store = self.open_store()
        store.save(make_snapshot("Original"))
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TRIGGER block_update BEFORE UPDATE ON application_state "
                "BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END"
            )
        with self.assertRaisesRegex(StorageError, "Cannot save"):
            store.save(make_snapshot("Rejected"))
        with self.open_store() as reader:
            self.assertEqual(reader.load(), make_snapshot("Original"))
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("DROP TRIGGER block_update")
        store.save(make_snapshot("Retried"))
        self.assertEqual(store.load(), make_snapshot("Retried"))

    def test_corrupt_database_is_not_reset(self) -> None:
        self.path.parent.mkdir(parents=True)
        contents = b"This is not an SQLite database."
        self.path.write_bytes(contents)
        with self.assertRaises(StorageError):
            SQLiteStore(self.path)
        self.assertEqual(self.path.read_bytes(), contents)

    def test_closed_store_fails_clearly_and_close_is_idempotent(self) -> None:
        store = self.open_store()
        store.close()
        store.close()
        with self.assertRaisesRegex(StorageError, "closed"):
            store.load()
        with self.assertRaisesRegex(StorageError, "closed"):
            store.save(make_snapshot())


if __name__ == "__main__":
    unittest.main()
