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
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "screenshots", "README.md", "build.json")


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
    stamp_build(dest)
    bridge_runtime(folder)
    return dest


# Packages the app needs that an OLDER runtime does not bundle yet. Until that runtime is rebuilt
# with PyInstaller, they ride in the app layer as plain files (the .exe puts app/ on sys.path), so a
# code-only update still gives the installed copy the whole feature. Each is a package directory plus
# the ".libs" folder its wheel keeps its DLLs in, and its dist-info (for Help > Open-source licences).
BRIDGE = ("shapely",)


def bridge_runtime(folder: Path) -> list[str]:
    """Copy BRIDGE packages into <folder>/app when <folder>/_internal lacks them. Returns what was copied."""
    import importlib.util
    internal = folder / "_internal"
    done = []
    for name in BRIDGE:
        target = folder / "app" / name
        if (internal / name).is_dir():                  # the runtime has it: drop any bridge copy
            for stale in (target, folder / "app" / f"{name}.libs"):
                if stale.exists():
                    shutil.rmtree(stale)
            continue
        spec = importlib.util.find_spec(name)
        if not spec or not spec.submodule_search_locations:
            print(f"bridge: {name} is not installed in this Python, so it was not copied")
            continue
        src = Path(list(spec.submodule_search_locations)[0])
        if not _same_python(internal):
            print(f"bridge: {name} skipped - this Python is not the runtime's version")
            continue
        for s, d in ((src, target), (src.parent / f"{name}.libs", folder / "app" / f"{name}.libs")):
            if s.is_dir():
                if d.exists():
                    shutil.rmtree(d)
                shutil.copytree(s, d, ignore=SKIP)
        for info in src.parent.glob(f"{name}-*.dist-info"):
            d = folder / "app" / info.name
            if d.exists():
                shutil.rmtree(d)
            shutil.copytree(info, d)
        done.append(name)
    return done


def _same_python(internal: Path) -> bool:
    """The runtime's python3XY.dll must match the Python whose compiled modules we are copying."""
    want = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    return (internal / want).exists() or not internal.is_dir()


def stamp_build(dest: Path):
    """build.json for Help → About: version (goes up every commit), commit, today's date."""
    sys.path.insert(0, str(ROOT))
    import json
    from gsend_cad import buildinfo
    try:
        info = buildinfo.from_git()
    except Exception:
        import datetime
        from gsend_cad import __version__
        info = {"version": __version__, "commit": app_version(), "date": datetime.date.today().isoformat()}
    (dest / "build.json").write_text(json.dumps(info) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print("app updated:", copy_app(sys.argv[1]))
