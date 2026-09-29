"""Copy G-SEND CADCAM's own code (gsend_cad: Python, fonts, logo, docs) into a built folder.

The Windows build is two layers:

    G-SEND CADCAM\\
      G-SEND CADCAM.exe, _internal\\   RUNTIME: Python, Qt, VTK, OpenCascade (~800 binaries).
                                 Built with PyInstaller and signed once. Rebuild only when a
                                 dependency or packaging/gsend_cadcam.spec changes.
      app\\gsend_cad\\            APP: plain .py files + assets. Any code, font, logo or colour
                                 change only replaces this folder: no PyInstaller, no re-signing
                                 (Smart App Control checks .exe/.dll files, not .py files).

Usage:
    python packaging/update_app.py "dist/G-SEND CADCAM"                         # after a code change
    python packaging/update_app.py "%USERPROFILE%\\Downloads\\G-SEND CADCAM Rev1"  # patch an installed copy
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "screenshots", "README.md")


def app_version() -> str:
    try:
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        sha = "unknown"
    return sha


def copy_app(folder) -> Path:
    folder = Path(folder)
    if not folder.is_dir():
        raise SystemExit(f"{folder} is not a built G-SEND CADCAM folder")
    dest = folder / "app" / "gsend_cad"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ROOT / "gsend_cad", dest, ignore=SKIP)
    (folder / "app" / "APP_VERSION.txt").write_text(app_version() + "\n", encoding="utf-8")
    return dest


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print("app updated:", copy_app(sys.argv[1]))
