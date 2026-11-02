"""Build a local Windows executable and a source/executable release archive.

Run with the isolated build environment's Python after installing
requirements-build.txt. No application runtime dependency is added.
"""

from pathlib import Path
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile


EXCLUDED_DIRECTORIES = {
    ".git", ".venv", "venv", "build-env", "build", "dist", "data",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov",
    ".idea", ".vscode",
}

RUN_INSTRUCTIONS = """YOWD for Windows

1. Extract this entire ZIP to a folder on your computer.
2. Open windows, then YOWD, and double-click YOWD.exe.
3. Keep YOWD.exe beside its _internal folder. Both are required.

A console window opens with the application. Closing the application ends it.
Python does not need to be installed to run the Windows application.

Your records are stored separately at:
%LOCALAPPDATA%\\YOWD\\yowd.sqlite3
If LOCALAPPDATA is unavailable, the app uses AppData\\Local in your user folder.
The app creates this database on first launch. No user records are included.

Optional checks from PowerShell in the windows\\YOWD folder:
.\\YOWD.exe --demo
.\\YOWD.exe --check-ui
These checks use disposable memory databases by default.
Use --db followed by a file path to choose a different database explicitly.

The source folder contains the Python project, tests, and technical build
instructions in README.md. Running the source uses source\\data\\yowd.sqlite3
by default. It does not automatically use the Windows application's database.
"""


def build_windows(source: Path) -> Path:
    """Run PyInstaller with this interpreter and return the onedir bundle."""
    if sys.platform != "win32":
        raise RuntimeError("Build the Windows application on Windows.")
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--onedir", "--console", "--name", "YOWD",
            "--distpath", str(source / "dist" / "windows"),
            "--workpath", str(source / "build" / "pyinstaller"),
            "--specpath", str(source / "build"),
            str(source / "run.py"),
        ],
        cwd=source,
        check=True,
    )
    return source / "dist" / "windows" / "YOWD"


def _source_files(source: Path):
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if path.is_symlink() or not path.is_file():
            continue
        if any(part.lower() in EXCLUDED_DIRECTORIES for part in relative.parts):
            continue
        name = path.name.lower()
        if name.startswith(".coverage") or name == ".env":
            continue
        if path.suffix.lower() in {".pyc", ".pyo", ".zip", ".db"}:
            continue
        if ".sqlite" in name or ".db-" in name:
            continue
        yield path, relative


def create_release_archive(source: Path, bundle: Path, destination: Path) -> Path:
    """Package current source and the entire executable folder, without user data."""
    if not (bundle / "YOWD.exe").is_file():
        raise FileNotFoundError(f"Windows executable not found: {bundle / 'YOWD.exe'}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("RUN-WINDOWS.txt", RUN_INSTRUCTIONS)
        for path, relative in _source_files(source):
            archive.write(path, (Path("source") / relative).as_posix())
        for path in sorted(bundle.rglob("*")):
            if path.is_file() and not path.is_symlink():
                relative = path.relative_to(bundle)
                archive.write(path, (Path("windows") / "YOWD" / relative).as_posix())
    return destination


def main() -> int:
    source = Path(__file__).resolve().parents[1]
    bundle = build_windows(source)
    archive = create_release_archive(source, bundle, source / "dist" / "YOWD-Windows-Source.zip")
    print(f"Windows application: {bundle / 'YOWD.exe'}")
    print(f"Source and Windows application archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
