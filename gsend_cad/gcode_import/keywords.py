"""Keywords: words in a program's comments that say what a tool is and what an operation does.

Pure stdlib. The table is user-editable JSON (see load / save); each row is

    {"keyword": "OD ROUGH", "tool": "OD TURN", "op": "OD ROUGH", "source": "DEFAULT"}

where tool / op may be None ("-" on screen): leave that one to motion detection.

Matching rules: the longest keyword wins and uses up its text (FACE GROOVE beats FACE),
whole words only, case does not matter.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

TOOL_TYPES = ("OD TURN", "BORING BAR", "GROOVE", "FACE GROOVE", "CUTOFF", "THREAD", "DRILL", "SPOT DRILL", "TAP")
UNKNOWN = "UNKNOWN"
OP_TYPES = ("FACE", "OD ROUGH", "OD FINISH", "ID ROUGH", "ID FINISH", "DRILL", "SPOT DRILL", "TAP", "OD GROOVE",
            "FACE GROOVE", "THREAD", "CHAMFER", "PART-OFF", "SKIP")
# a keyword may also set just ROUGH / FINISH: OD or ID is then decided by the motion
KEYWORD_OPS = OP_TYPES + ("ROUGH", "FINISH")

DEFAULTS = (
    ("FACE GROOVE", "FACE GROOVE", "FACE GROOVE"),
    ("OD FINISH", "OD TURN", "OD FINISH"),
    ("OD ROUGH", "OD TURN", "OD ROUGH"),
    ("ID FINISH", "BORING BAR", "ID FINISH"),
    ("ID ROUGH", "BORING BAR", "ID ROUGH"),
    ("CUTOFF", "CUTOFF", "PART-OFF"),
    ("GROOVE", "GROOVE", "OD GROOVE"),
    ("THREAD", "THREAD", "THREAD"),
    ("FINISH", None, "FINISH"),
    ("ROUGH", None, "ROUGH"),
    ("DRILL", "DRILL", "DRILL"),
    ("BORE", "BORING BAR", None),
    ("FACE", None, "FACE"),
    ("SPOT", "SPOT DRILL", "SPOT DRILL"),
    ("TAP", "TAP", "TAP"),
)


def defaults() -> list[dict]:
    return [{"keyword": k, "tool": t, "op": o, "source": "DEFAULT"} for k, t, o in DEFAULTS]


def clean(text: str) -> str:
    """A keyword as stored: upper case, single spaces."""
    return " ".join(str(text).upper().split())


def _row(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    key = clean(raw.get("keyword", ""))
    tool, op = raw.get("tool"), raw.get("op")
    if not key:
        return None
    return {"keyword": key, "tool": tool if tool in TOOL_TYPES else None, "op": op if op in KEYWORD_OPS else None,
            "source": "USER" if raw.get("source") == "USER" else "DEFAULT"}


def load(path) -> list[dict]:
    """The saved table, or the defaults when there is no file (or it cannot be read)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = [r for r in (_row(x) for x in data["keywords"]) if r]
    except Exception:
        return defaults()
    seen, out = set(), []
    for r in rows:
        if r["keyword"] not in seen:
            seen.add(r["keyword"])
            out.append(r)
    return out


def save(path, table: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 1, "keywords": table}, indent=1), encoding="utf-8")


def add(table: list[dict], keyword: str, tool: str | None, op: str | None, source: str = "USER") -> list[dict]:
    """A new table with this keyword first (replacing a row of the same keyword)."""
    row = _row({"keyword": keyword, "tool": tool, "op": op, "source": source})
    if row is None:
        return list(table)
    return [row] + [r for r in table if r["keyword"] != row["keyword"]]


@dataclass(frozen=True)
class Match:
    keyword: str
    tool: str | None
    op: str | None
    start: int          # where it sits in the comment


def match(comment: str, table: list[dict]) -> list[Match]:
    """Keywords found in a comment, in the order they appear."""
    text = comment.upper()
    found: list[Match] = []
    for row in sorted(table, key=lambda r: (-len(r["keyword"].split()), -len(r["keyword"]))):
        words = [re.escape(w) for w in row["keyword"].split()]
        if not words:
            continue
        pat = re.compile(r"(?<![A-Z0-9])" + r"\s+".join(words) + r"(?![A-Z0-9])")
        while True:
            m = pat.search(text)
            if not m:
                break
            found.append(Match(row["keyword"], row["tool"], row["op"], m.start()))
            text = text[:m.start()] + "\x00" * (m.end() - m.start()) + text[m.end():]     # used up
    found.sort(key=lambda m: m.start)
    return found
