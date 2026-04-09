"""
Runtime path resolution for both dev and PyInstaller-frozen bundles.

When the app runs from source (`python src/main.py`):
  - PROJECT_ROOT is the git repo root
  - DATA_DIR is `<repo>/data`
  - DB_PATH is `<repo>/data/reallives.db`

When the app runs from a PyInstaller-frozen bundle (e.g. RealLives2007.app):
  - The read-only data files (world.dat, jobs.dat, flags/, src/frontend/)
    live inside the bundle at `sys._MEIPASS`
  - The writable database lives in a per-user app-support directory so
    save games persist across launches and the bundle stays read-only

The build_db, parse_dat, and FastAPI app modules all import from here so
there is one canonical source of truth for where things live.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running inside a PyInstaller-frozen bundle."""
    return getattr(sys, "frozen", False)


def bundle_root() -> Path:
    """The directory holding read-only data + the src tree.

    In a frozen bundle this is `sys._MEIPASS`. In dev it's the project root.
    """
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    # src/runtime_paths.py → parents[1] = project root
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    """Read-only data directory: world.dat, jobs.dat, flags/, etc."""
    return bundle_root() / "data"


def frontend_dir() -> Path:
    """Static frontend assets (HTML / JS / CSS)."""
    return bundle_root() / "src" / "frontend"


def user_data_dir() -> Path:
    """Per-user, writable directory for the SQLite database and any other
    runtime state. Created on first access.

    macOS:   ~/Library/Application Support/RealLives2007
    Linux:   $XDG_DATA_HOME/RealLives2007  (or ~/.local/share/RealLives2007)
    Windows: %APPDATA%\\RealLives2007
    Dev:     <repo>/data  (so dev runs share the same DB as before)
    """
    if not is_frozen():
        return data_dir()
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    p = base / "RealLives2007"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    """Where the SQLite database lives at runtime."""
    return user_data_dir() / "reallives.db"
