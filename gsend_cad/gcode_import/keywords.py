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
# User-made tool types: name -> the built-in type it cuts like (that is what decides its shape, its side and
# which fields it needs). Kept in the keywords JSON under "tool_types"; load() fills this, save() writes it.
_CUSTOM: dict[str, str] = {}


def custom_types() -> dict[str, str]:
    return dict(_CUSTOM)


def all_tool_types() -> tuple[str, ...]:
    return TOOL_TYPES + tuple(_CUSTOM)


def base_of(tool_type: str) -> str:
    """The built-in behaviour behind a type name (a built-in is its own base)."""
    return _CUSTOM.get(tool_type, tool_type)


def add_tool_type(name: str, like: str) -> str | None:
    """Register a user tool type that cuts like a built-in one. Returns the clean name, or None."""
    name, like = clean(name), clean(like)
    if not name or like not in TOOL_TYPES or name == UNKNOWN:
        return None
    if name not in TOOL_TYPES:
        _CUSTOM[name] = like
    return name


def remove_tool_type(name: str) -> None:
    _CUSTOM.pop(clean(name), None)
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
    ("UN", "THREAD", "THREAD"),           # thread designators: 2.75-8 UN, 1/4-20 UNC, 1/2-20 UNF, 1/8 NPT
    ("UNC", "THREAD", "THREAD"),
    ("UNF", "THREAD", "THREAD"),
    ("UNEF", "THREAD", "THREAD"),
    ("NPT", "THREAD", "THREAD"),
    ("TPI", "THREAD", "THREAD"),
    ("ACME", "THREAD", "THREAD"),
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
    return {"keyword": key, "tool": tool if tool in all_tool_types() else None, "op": op if op in KEYWORD_OPS else None,
            "source": "USER" if raw.get("source") == "USER" else "DEFAULT"}


def load(path) -> list[dict]:
    """The saved table, or the defaults when there is no file (or it cannot be read)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        _CUSTOM.clear()                                 # the file's own tool types, before its rows are read
        for t in data.get("tool_types", []):
            if isinstance(t, dict):
                add_tool_type(t.get("name", ""), t.get("like", ""))
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
    types = [{"name": n, "like": l} for n, l in _CUSTOM.items()]
    p.write_text(json.dumps({"version": 1, "keywords": table, "tool_types": types}, indent=1), encoding="utf-8")


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
