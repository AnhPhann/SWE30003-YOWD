"""Keep source data in the project and packaged data in the user's profile."""

import os
from pathlib import Path
import sys


def default_database_path() -> Path:
    """Return a stable database location, independent of the working directory."""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent.parent / "data" / "yowd.sqlite3"
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    return base / "YOWD" / "yowd.sqlite3"
