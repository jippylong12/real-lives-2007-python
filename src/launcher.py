"""
Desktop launcher entry point — used by the PyInstaller bundle.

Boots a local FastAPI server on a free port, then opens the system browser
pointed at it. The user double-clicks the .app, the browser pops up, and
they play. The terminal stays open for as long as the server is running;
closing the browser doesn't stop the server (the user closes the .app to
exit).

Run from source for testing:
    python -m src.launcher
"""

from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# When run as `python src/launcher.py` from the repo root, ensure `src` is
# importable. PyInstaller handles this on its own when frozen.
if __name__ == "__main__" and not getattr(sys, "frozen", False):
    HERE = Path(__file__).resolve().parent
    ROOT = HERE.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _find_free_port() -> int:
    """Bind to port 0 and let the OS pick a free one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _open_browser_when_ready(url: str, port: int) -> None:
    """Wait until the server starts accepting connections, then launch the
    system browser pointed at it. Bounded retry: if the server doesn't come
    up within a few seconds, open the browser anyway and let it 502 once."""
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    webbrowser.open(url)


def main() -> None:
    # Force unbuffered stdout/stderr so the launcher banner shows up
    # immediately when the app is run from a terminal — Python defaults
    # to block-buffering when stdout is not a TTY, which hides the URL
    # the user needs to copy.
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass

    from src.data import build_db
    from src import runtime_paths

    # Build the SQLite DB on first launch (or if it's missing). In a frozen
    # bundle this writes to ~/Library/Application Support/RealLives2007/.
    if not build_db.DB_PATH.exists():
        print(f"First-run setup: building game database at {build_db.DB_PATH}…", flush=True)
        build_db.build()
        print("Done.", flush=True)

    import uvicorn
    from src.api.app import app

    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"

    print(flush=True)
    print("==============================================================", flush=True)
    print("  Real Lives 2007 — Web Edition", flush=True)
    print(f"  Open in your browser: {url}", flush=True)
    print("  Quit by closing this window or pressing Ctrl+C.", flush=True)
    print("==============================================================", flush=True)
    print(flush=True)

    threading.Thread(
        target=_open_browser_when_ready,
        args=(url, port),
        daemon=True,
    ).start()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
