# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Real Lives 2007 — cross-platform.

Build (from project root):
    pyinstaller packaging/RealLives2007.spec --clean --noconfirm

Output:
    macOS:    dist/Real Lives 2007.app   (also a CLI binary in dist/RealLives2007/)
    Windows:  dist/RealLives2007/RealLives2007.exe
    Linux:    dist/RealLives2007/RealLives2007

PyInstaller does NOT cross-compile — you must run it on the platform you
want to build for. CI builds via .github/workflows/release.yml run this
spec on macos-latest / windows-latest / ubuntu-latest in parallel.

The macOS bundle is unsigned. macOS will refuse to launch it on first try
with 'cannot be opened because the developer cannot be verified'. The user
right-clicks → Open → Open to bypass once; subsequent launches work
normally. Windows SmartScreen has the same warning ('Windows protected your
PC'); 'More info' → 'Run anyway'. Both could be cleared with code signing
+ notarization, which costs money and is out of scope for a hobby project.
"""

import sys
from pathlib import Path

# Resolve project root from the spec file's location.
ROOT = Path(SPECPATH).resolve().parent

# Read-only data + frontend assets that the bundle needs at runtime.
# Format: (source_path, dest_subdir_in_bundle)
datas = [
    (str(ROOT / "data" / "world.dat"),       "data"),
    (str(ROOT / "data" / "jobs.dat"),        "data"),
    (str(ROOT / "data" / "Investments.dat"), "data"),
    (str(ROOT / "data" / "Loans.dat"),       "data"),
    (str(ROOT / "data" / "world.idx"),       "data"),
    (str(ROOT / "data" / "jobs.idx"),        "data"),
    (str(ROOT / "data" / "Investments.idx"), "data"),
    (str(ROOT / "data" / "Loans.idx"),       "data"),
    (str(ROOT / "data" / "flags"),           "data/flags"),
    (str(ROOT / "src" / "frontend"),         "src/frontend"),
]

# uvicorn auto-imports a few stdlib + websocket bits at runtime that
# PyInstaller's static analysis can miss. List them explicitly.
hiddenimports = [
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.logging",
]


a = Analysis(
    [str(ROOT / "src" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest", "tkinter", "matplotlib", "numpy", "scipy", "pandas",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RealLives2007",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,         # keep the terminal so the user sees the URL + can quit
    disable_windowed_traceback=False,
    target_arch=None,     # native: arm64 on Apple Silicon, x86_64 on Intel
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RealLives2007",
)

# Mac-only: wrap COLLECT into a proper .app bundle. On Windows / Linux
# the COLLECT directory IS the distributable.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Real Lives 2007.app",
        icon=None,
        bundle_identifier="com.jippylong12.reallives2007",
        info_plist={
            "CFBundleName": "Real Lives 2007",
            "CFBundleDisplayName": "Real Lives 2007",
            "CFBundleShortVersionString": "1.3.0",
            "CFBundleVersion": "1.3.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
