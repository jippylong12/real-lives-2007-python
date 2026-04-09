"""
Single-command entry point: `python src/main.py`

Builds the SQLite database on first run, then starts the FastAPI server.
The server hosts the API at /api/* and serves the static frontend at /.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `src` importable when run as a script.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from src.data import build_db   # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Real Lives 2007 (Python rebuild)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--rebuild-db", action="store_true",
                        help="Wipe and rebuild data/reallives.db before serving")
    args = parser.parse_args()

    if args.rebuild_db or not build_db.DB_PATH.exists():
        report = build_db.build()
        print(f"Built database at {report['db_path']}: "
              f"{report['countries']} countries, {report['jobs']} jobs.")

    # Import after DB is ready so the app can open it eagerly if it wants to.
    import uvicorn
    print(f"Starting Real Lives 2007 on http://{args.host}:{args.port}")
    uvicorn.run("src.api.app:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
