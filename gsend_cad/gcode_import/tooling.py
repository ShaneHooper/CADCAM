"""The program's tools: what each one is, how we know, and what is still assumed.

Pure stdlib. A tool is identified in this order, and its status says which one worked:

    READ      a keyword in its comment set the type
    GUESSED   no keyword, but its motion or a cycle gives it away (G76 means a thread tool)
    UNKNOWN   neither - treated as a sharp point; its cuts still count, marked ASSUMED
    DEFINED   set by the user in Step 2 (overrides all of the above)
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import re

from . import keywords as kw
from .inserts import Insert, Size, parse_insert, parse_size
from .parser import WORD_RE, Program, _comment_text, _strip_comments
from .stock import facing_passes

READ, GUESSED, UNKNOWN, DEFINED = "READ", "GUESSED", "UNKNOWN", "DEFINED"
STATUSES = (READ, GUESSED, UNKNOWN, DEFINED)
SIDES = ("OD", "ID", "CENTER")
DEFAULT_NOSE = 1.0 / 32.0           # a turning / boring tool whose insert is not written down
NOSED = ("OD TURN", "BORING BAR")   # types whose nose radius shapes the part
SIZED = {"DRILL": "DIAMETER", "SPOT DRILL": "DIAMETER", "TAP": "DIAMETER", "GROOVE": "WIDTH",
         "FACE GROOVE": "WIDTH", "CUTOFF": "WIDTH"}
_ON_AXIS = 0.002                    # diameter at or under this is "on the centerline"


@dataclass(frozen=True)
class Tool:
    number: str                         # "01"
    comment: str = ""
    keywords: tuple[str, ...] = ()
    type: str = kw.UNKNOWN
    insert: str = ""                    # the insert code as read / typed
    shape_angle: float | None = None
    nose_radius: float = 0.0
    nose_assumed: bool = True
    size: float | None = None           # drill / tap diameter or groove / cutoff width
    size_text: str = ""
    pitch: float | None = None
    hand: str = "RH"
    side: str = "OD"
    status: str = UNKNOWN
    why: str = ""                       # how the type was found
    line: int = 0                       # first T call (1-based)
    ops: tuple[str, ...] = field(default=())    # operations its keywords name

    @property
    def assumed(self) -> str:
        """One line: what stays assumed until this tool is defined."""
        if self.type == kw.UNKNOWN:
            return "Treated as a sharp point. Every edge this tool cuts is marked ASSUMED."
        if self.type in NOSED and self.nose_assumed:
            return (f"Nose radius {self.nose_radius:.4f} is a default, not read from the program. "
                    "Corners and tapers this tool cuts are marked ASSUMED.")
        if self.type in SIZED and self.size is None:
            return f"No {SIZED[self.type].lower()} found - this tool's cuts are left out until you type one."
        return "Nothing assumed."

    @property
    def resolved(self) -> bool:
        return self.status in (READ, DEFINED) and self.assumed == "Nothing assumed."


@dataclass(frozen=True)
class Reading:
    """What one comment says (also what the Settings 'test a comment' box shows)."""
    matches: tuple[kw.Match, ...]
    insert: Insert | None
    size: Size | None
    tool_type: str | None
    ops: tuple[str, ...]
    nose_radius: float | None


def read_comment(comment: str, table: list[dict]) -> Reading:
    matches = tuple(kw.match(comment, table))
    insert = parse_insert(comment)
    tool_type = next((m.tool for m in matches if m.tool), None)
    ops = tuple(dict.fromkeys(m.op for m in matches if m.op))
    return Reading(matches, insert, parse_size(comment), tool_type, ops,
                   insert.nose_radius if insert else None)


def default_side(tool_type: str) -> str:
    return {"BORING BAR": "ID", "DRILL": "CENTER", "SPOT DRILL": "CENTER", "TAP": "CENTER"}.get(tool_type, "OD")


# ---- T calls and their comments ----
def tool_calls(lines: list[str]) -> list[tuple[str, int, str]]:
    """(tool number, 1-based line, comment) for every T call, in program order.

    The comment is the one on the T line; failing that, a comment-only line just above or
    just below it."""
    codes = [_strip_comments(raw) for raw in lines]
    notes = [_comment_text(raw) for raw in lines]
    out = []
    for i, code in enumerate(codes):
        t = [v for l, v in WORD_RE.findall(code) if l.upper() == "T"]
        if not t:
            continue
        n = int(round(float(t[-1])))
        number = str(n).zfill(2) if n < 100 else str(n).zfill(4)[:2]
        note = notes[i]
        if not note:
            near = [j for j in (i - 1, i + 1, i - 2) if 0 <= j < len(lines) and notes[j] and not codes[j].strip()]
            note = notes[near[0]] if near else ""
        out.append((number, i + 1, note))
    return out


# ---- what the motion says ----
def _from_motion(number: str, program: Program) -> tuple[str | None, str, str]:
    """(type, side, why) from this tool's moves; type None when they do not say."""
    moves = [m for m in program.moves if m.tool == number]
    cuts = [m for m in moves if m.kind != "rapid"]
    if not cuts:
        return None, "OD", "it never cuts"
    codes = {m.code.split()[0] for m in cuts}
    side = _side(moves, cuts)
    if any(m.kind == "thread" for m in cuts):
        cyc = "/".join(sorted(c for c in codes if c in ("G76", "G92", "G32"))) or "threading"
        return "THREAD", side, f"{cyc} threading cycle"
    if "G84" in codes:
        return "TAP", "CENTER", "G84 tapping cycle"
    on_axis = all(max(m.x0, m.x1) <= _ON_AXIS for m in cuts)
    if on_axis:
        cyc = sorted(c for c in codes if c in ("G74", "G81", "G82", "G83"))
        return "DRILL", "CENTER", (f"{cyc[0]} drilling cycle" if cyc else "Z-only moves at X0")
    plunges = [m for m in cuts if abs(m.z1 - m.z0) <= 0.002 and abs(m.x1 - m.x0) > 0.01]
    if len(plunges) == len(cuts):
        front = max((m.z1 for m in facing_passes(program)), default=None)
        z_hi = max(m.z1 for m in cuts)
        if front is not None and z_hi >= front - 0.1:
            return "OD TURN", "OD", "X sweeps at the front face (facing)"
        if min(min(m.x0, m.x1) for m in cuts) <= 0.02:
            return "CUTOFF", "OD", "X plunges that end on the centerline"
        # a groove tool retracts to where it started, so the plunge direction says which side
        side = "OD" if plunges[0].x1 < plunges[0].x0 else "ID"
        return "GROOVE", side, "X plunges with no Z travel"
    if side == "ID":
        return "BORING BAR", "ID", "it cuts outward from inside a drilled hole"
    return "OD TURN", "OD", "it turns along Z from outside the part"


def _side(moves, cuts) -> str:
    """ID when the tool clears the work by going to a SMALLER diameter than it cuts at."""
    cut_hi = max(max(m.x0, m.x1) for m in cuts)
    z_hi = max(max(m.z0, m.z1) for m in cuts)
    near = [m.x1 for m in moves if m.kind == "rapid" and m.code == "G0" and m.z1 <= z_hi + 0.5]
    if near and max(near) <= cut_hi + 1e-6 and min(min(m.x0, m.x1) for m in cuts) > _ON_AXIS:
        return "ID"
    return "OD"


# ---- the tool list ----
def build_tools(program: Program, table: list[dict], overrides: dict[str, Tool] | None = None) -> list[Tool]:
    """One Tool per T number, in the order they first appear. overrides: user-defined tools."""
    overrides = overrides or {}
    calls: dict[str, list[tuple[int, str]]] = {}
    for number, line, note in tool_calls(program.lines):
        calls.setdefault(number, []).append((line, note))
    for m in program.moves:                                 # a tool that cuts with no T call (bare program)
        if m.kind != "rapid" and m.tool not in calls:
            calls.setdefault(m.tool, []).append((m.line, ""))
    drilled = False
    tools = []
    for number, hits in calls.items():
        comment = " / ".join(dict.fromkeys(note for _, note in hits if note))
        if number in overrides:
            tool = replace(overrides[number], comment=comment, line=hits[0][0], status=DEFINED)
        else:
            tool = _identify(number, comment, hits[0][0], program, table, drilled)
        drilled = drilled or tool.type in ("DRILL", "SPOT DRILL")
        tools.append(tool)
    return tools


def _identify(number: str, comment: str, line: int, program: Program, table: list[dict], drilled: bool) -> Tool:
    r = read_comment(comment, table)
    m_type, m_side, m_why = _from_motion(number, program)
    if m_type == "BORING BAR" and not drilled:              # nothing made a hole for it to be inside
        m_type, m_side, m_why = "OD TURN", "OD", "it turns along Z"
    words = tuple(m.keyword for m in r.matches)
    if r.tool_type:
        key = next(m.keyword for m in r.matches if m.tool)
        type_, status, why = r.tool_type, READ, f'keyword "{key}" in its comment'
        side = default_side(type_) if type_ in ("OD TURN", "BORING BAR", "DRILL", "SPOT DRILL", "TAP") else m_side
    elif m_type:
        type_, status, why, side = m_type, GUESSED, f"no keyword matched; {m_why}", m_side
    else:
        type_, status, why, side = kw.UNKNOWN, UNKNOWN, f"no keyword matched and {m_why}", "OD"
    nose, nose_assumed, angle, code = 0.0, True, None, ""
    if r.insert:
        nose, nose_assumed, angle, code = r.insert.nose_radius, False, r.insert.angle, r.insert.code
    elif type_ in NOSED:
        nose = DEFAULT_NOSE
    elif type_ != kw.UNKNOWN:
        nose_assumed = False                                # no nose radius to assume on a drill / groove tool
    size = r.size if type_ in SIZED or type_ == "THREAD" else None
    return Tool(number, comment, words, type_, code, angle, nose, nose_assumed,
                size.value if size else None, size.text if size else "", size.pitch if size else None,
                "RH", side, status, why, line, r.ops)


def apply_insert(tool: Tool, code: str) -> Tool:
    """Typing an insert code fills in the shape and the nose radius."""
    ins = parse_insert(code)
    if not ins:
        return replace(tool, insert=code.strip().upper())
    return replace(tool, insert=ins.code, shape_angle=ins.angle, nose_radius=ins.nose_radius, nose_assumed=False)


def counts(tools: list[Tool]) -> dict[str, int]:
    return {s: sum(1 for t in tools if t.status == s) for s in STATUSES}


def next_unresolved(tools: list[Tool], after: int = -1) -> int | None:
    """Index of the next tool that is not READ-and-complete or DEFINED, wrapping round."""
    order = list(range(after + 1, len(tools))) + list(range(0, after + 1))
    return next((i for i in order if not tools[i].resolved), None)


def keyword_suggestion(comment: str) -> str:
    """Comment words worth saving as a keyword: letters only, insert code and sizes dropped."""
    text = comment.upper()
    ins = parse_insert(text)
    if ins:
        text = text[:ins.span[0]] + " " + text[ins.span[1]:]
    words = [w for w in re.findall(r"[A-Z]{2,}", text) if w not in ("MM", "IN", "DIA", "TOOL", "DEG")]
    return " ".join(words[:3])
