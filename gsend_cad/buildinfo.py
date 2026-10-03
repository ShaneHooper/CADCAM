"""Version and update date for Help → About.

packaging/update_app.py writes build.json next to this file every time it updates the app, so
the installed copy always says which code it runs and when it was put there:
    {"version": "0.1.312", "commit": "abc1234", "date": "2026-10-01"}
version = __version__'s major.minor + the number of commits (goes up with every change).
From a git checkout (no build.json) the same numbers come from git; otherwise just __version__.
"""
from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILE = HERE / "build.json"


def _git(*args) -> str:
    return subprocess.run(["git", "-C", str(HERE.parent), *args], capture_output=True, text=True,
                          check=True, timeout=5).stdout.strip()


def from_git() -> dict:
    """What build.json gets: from the repo this file sits in. Raises when there's no git."""
    from . import __version__
    count = _git("rev-list", "--count", "HEAD")
    return {"version": f"{__version__.rsplit('.', 1)[0]}.{count}", "commit": _git("rev-parse", "--short", "HEAD"),
            "date": datetime.date.today().isoformat()}


def info() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        return {**from_git(), "date": _git("log", "-1", "--format=%cs")}       # dev: the last commit's date
    except Exception:
        from . import __version__
        return {"version": __version__, "commit": "", "date": ""}


def pretty_date(iso: str) -> str:
    try:
        d = datetime.date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.strftime('%B')} {d.day}, {d.year}"
