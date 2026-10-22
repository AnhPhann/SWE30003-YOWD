"""Persist one versioned application snapshot in a local SQLite database.

This deliberately small storage boundary saves JSON, not live domain objects.
It suits the local starter application; it is not a multi-user server or a
record-by-record repository. Optimistic revision checks prevent two store
instances from silently overwriting snapshots loaded at different times.
After a conflict the caller must load the latest snapshot and resolve its
changes before saving again. Transactions make each complete save atomic.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any


SCHEMA_VERSION = 1


class StorageError(RuntimeError):
    """A snapshot could not be safely read or written."""


class SQLiteStore:
    """Store a single JSON snapshot and remember the last loaded revision.

    A new instance starts at revision zero. Its first save can create a state,
    but an existing state must be loaded before it can be updated. A failed
    load disables saving until a later load succeeds, so malformed data is
    never replaced as though the database were empty.
    """

    def __init__(self, path: str | Path) -> None:
        self.path: str | Path = ":memory:" if str(path) == ":memory:" else Path(path)
        self._revision: int | None = 0
        self._closed = False
        connection: sqlite3.Connection | None = None
        try:
            if isinstance(self.path, Path):
                self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.path), timeout=5.0)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS application_state (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        revision INTEGER NOT NULL CHECK (revision > 0),
                        snapshot TEXT NOT NULL
                    )
                    """
                )
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.close()
            raise StorageError(f"Cannot open the application database: {exc}") from exc
        self._connection = connection

    def load(self) -> dict[str, Any] | None:
        """Read the stored snapshot, returning None only for an empty store."""
        self._require_open()
        self._revision = None
        try:
            row = self._connection.execute(
                "SELECT revision, snapshot FROM application_state WHERE singleton = 1"
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(f"Cannot read the application snapshot: {exc}") from exc

        if row is None:
            self._revision = 0
            return None

        revision, encoded = row
        if type(revision) is not int or revision < 1:
            raise StorageError("The stored snapshot has an invalid revision.")
        try:
            snapshot = json.loads(encoded, parse_constant=self._reject_constant)
        except (TypeError, ValueError, RecursionError) as exc:
            raise StorageError("The stored snapshot is not valid JSON.") from exc
        self._validate_snapshot(snapshot)
        self._revision = revision
        return snapshot

    def save(self, snapshot: dict[str, Any]) -> None:
        """Atomically save a supported snapshot unless another writer changed it."""
        self._require_open()
        if self._revision is None:
            raise StorageError("Load a valid snapshot before attempting to save.")
        self._validate_snapshot(snapshot)
        try:
            encoded = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError, RecursionError) as exc:
            raise StorageError("The snapshot cannot be encoded as JSON.") from exc

        expected_revision = self._revision
        new_revision = expected_revision + 1
        try:
            with self._connection:
                if expected_revision == 0:
                    try:
                        self._connection.execute(
                            "INSERT INTO application_state "
                            "(singleton, revision, snapshot) VALUES (1, ?, ?)",
                            (new_revision, encoded),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise StorageError(
                            "The application state changed since it was loaded. "
                            "Close and reopen the application before saving."
                        ) from exc
                else:
                    cursor = self._connection.execute(
                        "UPDATE application_state SET revision = ?, snapshot = ? "
                        "WHERE singleton = 1 AND revision = ?",
                        (new_revision, encoded, expected_revision),
                    )
                    if cursor.rowcount != 1:
                        raise StorageError(
                            "The application state changed since it was loaded. "
                            "Close and reopen the application before saving."
                        )
        except sqlite3.Error as exc:
            raise StorageError(f"Cannot save the application snapshot: {exc}") from exc
        self._revision = new_revision

    def close(self) -> None:
        """Release the connection; repeated close calls are harmless."""
        if self._closed:
            return
        try:
            self._connection.close()
        except sqlite3.Error as exc:
            raise StorageError(f"Cannot close the application database: {exc}") from exc
        self._closed = True

    def __enter__(self) -> SQLiteStore:
        self._require_open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            raise StorageError("The application database is closed.")

    @staticmethod
    def _validate_snapshot(snapshot: Any) -> None:
        if not isinstance(snapshot, dict):
            raise StorageError("The application snapshot must be a JSON object.")
        version = snapshot.get("schema_version")
        if type(version) is not int or version != SCHEMA_VERSION:
            raise StorageError(
                f"Unsupported snapshot schema version {version!r}; "
                f"expected {SCHEMA_VERSION}."
            )

    @staticmethod
    def _reject_constant(value: str) -> None:
        raise ValueError(f"Invalid JSON constant: {value}")
