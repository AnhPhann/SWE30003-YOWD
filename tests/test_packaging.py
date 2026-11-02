"""Release archives must include runnable files and exclude private working data."""

import importlib
import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile


class WindowsPackagingTests(unittest.TestCase):
    def build_module(self):
        helper = Path(__file__).resolve().parents[1] / "tools" / "build_windows.py"
        self.assertTrue(helper.is_file(), "A reproducible Windows release helper is required.")
        spec = importlib.util.spec_from_file_location("yowd_build_windows", helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def write_file(self, root, relative, content="fixture"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_archive_excludes_private_data_caches_and_builds(self):
        helper = self.build_module()
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            for relative in (
                "run.py", "README.md", "yowd/paths.py", "yowd/operating_hours.py",
                "yowd/pricing.py", "yowd/suburbs.py", "tools/build_windows.py",
                "requirements-build.txt", "tests/test_paths.py",
                "data/yowd.sqlite3", "backup.sqlite3", "backup.sqlite3-wal", "private.db",
                "yowd/__pycache__/paths.cpython-312.pyc", ".git/config", ".venv/pyvenv.cfg",
                "build-env/pyvenv.cfg", "build/YOWD.spec", "dist/old-release.zip",
                ".pytest_cache/cache", ".coverage", "old-release.zip",
            ):
                self.write_file(root, relative)
            bundle = Path(temporary) / "bundle"
            self.write_file(bundle, "YOWD.exe", "executable fixture")
            self.write_file(bundle, "_internal/python312.dll", "runtime fixture")
            archive = helper.create_release_archive(root, bundle, Path(temporary) / "release.zip")
            with ZipFile(archive) as release:
                names = set(release.namelist())
                self.assertEqual(names, {
                    "RUN-WINDOWS.txt", "source/run.py", "source/README.md", "source/yowd/paths.py",
                    "source/yowd/operating_hours.py", "source/yowd/pricing.py", "source/yowd/suburbs.py",
                    "source/tools/build_windows.py", "source/requirements-build.txt", "source/tests/test_paths.py",
                    "windows/YOWD/YOWD.exe", "windows/YOWD/_internal/python312.dll",
                })
                self.assertEqual(release.read("windows/YOWD/YOWD.exe"), b"executable fixture")

    def test_archive_of_current_source_includes_all_application_modules(self):
        helper = self.build_module()
        source = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            self.write_file(bundle, "YOWD.exe")
            archive = helper.create_release_archive(source, bundle, Path(temporary) / "release.zip")
            with ZipFile(archive) as release:
                names = set(release.namelist())
                for module in ("paths.py", "operating_hours.py", "pricing.py", "models/delivery_assignment.py"):
                    self.assertIn(f"source/yowd/{module}", names)
                self.assertIn("source/tools/build_windows.py", names)
                self.assertIn("source/requirements-build.txt", names)
                self.assertFalse(any("__pycache__" in name or name.startswith("source/data/") for name in names))

    def test_archive_excludes_a_worktree_git_file(self):
        helper = self.build_module()
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            self.write_file(root, "run.py")
            self.write_file(root, ".git", "gitdir: private-worktree-path")
            bundle = Path(temporary) / "bundle"
            self.write_file(bundle, "YOWD.exe")
            archive = helper.create_release_archive(root, bundle, Path(temporary) / "release.zip")
            with ZipFile(archive) as release:
                self.assertNotIn("source/.git", release.namelist())

    def test_missing_executable_fails_before_creating_an_archive(self):
        helper = self.build_module()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "release.zip"
            with self.assertRaises(FileNotFoundError):
                helper.create_release_archive(root, root / "missing", target)
            self.assertFalse(target.exists())

    def test_build_uses_this_python_and_keeps_outputs_inside_ignored_directories(self):
        helper = self.build_module()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(helper.sys, "platform", "win32"), patch.object(helper.subprocess, "run") as run:
                helper.build_windows(root)
            command = run.call_args.args[0]
            self.assertEqual(command[:3], [sys.executable, "-m", "PyInstaller"])
            self.assertIn("--onedir", command)
            self.assertIn("--console", command)
            self.assertEqual(command[command.index("--name") + 1], "YOWD")
            self.assertEqual(command[command.index("--distpath") + 1], str(root / "dist" / "windows"))
            self.assertEqual(command[command.index("--workpath") + 1], str(root / "build" / "pyinstaller"))
            self.assertEqual(command[command.index("--specpath") + 1], str(root / "build"))
            self.assertEqual(command[-1], str(root / "run.py"))
            self.assertEqual(run.call_args.kwargs, {"cwd": root, "check": True})


if __name__ == "__main__":
    unittest.main()
