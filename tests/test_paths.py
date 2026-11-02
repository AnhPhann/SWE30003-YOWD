"""Database location regressions without using the user's real database."""

from contextlib import redirect_stdout
import importlib
import importlib.util
from io import StringIO
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from yowd.__main__ import main


class DatabasePathTests(unittest.TestCase):
    def path_module(self):
        self.assertIsNotNone(
            importlib.util.find_spec("yowd.paths"),
            "Database locations need a frozen-aware path policy.",
        )
        return importlib.import_module("yowd.paths")

    def test_source_default_keeps_existing_data_independent_of_working_directory(self):
        paths = self.path_module()
        source = Path(__file__).resolve().parents[1]
        original = Path.cwd()
        with TemporaryDirectory() as temporary, patch.object(sys, "frozen", False, create=True):
            try:
                os.chdir(temporary)
                self.assertEqual(paths.default_database_path(), source / "data" / "yowd.sqlite3")
            finally:
                os.chdir(original)

    def test_frozen_windows_default_uses_local_app_data(self):
        paths = self.path_module()
        with TemporaryDirectory() as temporary, patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "platform", "win32"), \
                patch.dict(os.environ, {"LOCALAPPDATA": temporary}):
            self.assertEqual(
                paths.default_database_path(), Path(temporary) / "YOWD" / "yowd.sqlite3"
            )

    def test_frozen_windows_missing_environment_uses_home_app_data(self):
        paths = self.path_module()
        with TemporaryDirectory() as temporary, patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "platform", "win32"), \
                patch.dict(os.environ, {}, clear=True), patch.object(Path, "home", return_value=Path(temporary)):
            self.assertEqual(
                paths.default_database_path(),
                Path(temporary) / "AppData" / "Local" / "YOWD" / "yowd.sqlite3",
            )

    def test_frozen_linux_default_uses_a_per_user_directory(self):
        paths = self.path_module()
        with TemporaryDirectory() as temporary, patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "platform", "linux"), \
                patch.dict(os.environ, {}, clear=True), patch.object(Path, "home", return_value=Path(temporary)):
            self.assertEqual(
                paths.default_database_path(), Path(temporary) / ".local" / "share" / "YOWD" / "yowd.sqlite3"
            )

    def test_normal_frozen_launch_opens_a_writable_user_database(self):
        from yowd import ui
        entrypoint = importlib.import_module("yowd.__main__")

        with TemporaryDirectory() as temporary, patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "platform", "win32"), \
                patch.dict(os.environ, {"LOCALAPPDATA": temporary}), \
                patch.object(entrypoint, "__file__", str(Path(temporary) / "install" / "yowd" / "__main__.py")), \
                patch.object(ui, "launch", side_effect=lambda app: app.close()):
            self.assertEqual(main([]), 0)
            self.assertTrue((Path(temporary) / "YOWD" / "yowd.sqlite3").is_file())

    def test_diagnostics_default_to_memory_even_when_frozen(self):
        with TemporaryDirectory() as temporary, patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "platform", "win32"), \
                patch.dict(os.environ, {"LOCALAPPDATA": temporary}), redirect_stdout(StringIO()):
            self.assertEqual(main(["--demo"]), 0)
            self.assertEqual(main(["--check-ui"]), 0)
            self.assertFalse((Path(temporary) / "YOWD").exists())

    def test_explicit_database_overrides_frozen_default_and_demo_memory(self):
        with TemporaryDirectory() as temporary, patch.object(sys, "frozen", True, create=True), \
                patch.dict(os.environ, {"LOCALAPPDATA": str(Path(temporary) / "user")}), \
                redirect_stdout(StringIO()):
            chosen = Path(temporary) / "chosen" / "demo.sqlite3"
            self.assertEqual(main(["--demo", "--db", str(chosen)]), 0)
            self.assertTrue(chosen.is_file())
            self.assertFalse((Path(temporary) / "user").exists())


if __name__ == "__main__":
    unittest.main()
