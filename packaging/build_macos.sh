#!/usr/bin/env bash
# Build the macOS .app bundle for Real Lives 2007.
#
# Usage (from project root):
#     packaging/build_macos.sh
#
# Output:
#     dist/Real Lives 2007.app
#     dist/RealLives2007-<version>-macos.zip
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${VERSION:-1.1.0}"
ARCH="$(uname -m)"

if [[ ! -d .venv ]]; then
    echo "error: .venv not found. Create a virtualenv first:" >&2
    echo "    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

# Install PyInstaller into the existing venv if missing.
if ! .venv/bin/python -c "import PyInstaller" 2>/dev/null; then
    echo "→ Installing PyInstaller into .venv"
    .venv/bin/pip install --quiet pyinstaller
fi

echo "→ Cleaning previous build"
rm -rf build dist

echo "→ Running PyInstaller"
.venv/bin/pyinstaller packaging/RealLives2007.spec --clean --noconfirm

APP="dist/Real Lives 2007.app"
if [[ ! -d "$APP" ]]; then
    echo "error: build did not produce $APP" >&2
    exit 1
fi

echo "→ Build complete: $APP"

# Zip the .app for distribution. ditto preserves macOS extended attributes
# and resource forks, which a plain `zip` would strip.
ZIP="dist/RealLives2007-${VERSION}-macos-${ARCH}.zip"
echo "→ Packaging $ZIP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

echo
echo "Done."
echo "  App:    $APP"
echo "  Zip:    $ZIP"
echo
echo "To test, double-click the .app or run:"
echo "  open '$APP'"
echo
echo "First-launch on macOS: right-click → Open → Open (Gatekeeper)"
