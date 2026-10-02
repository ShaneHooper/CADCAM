"""Operations: the program cut into steps, each with a type and how sure we are of it.

Pure stdlib. The program is segmented by tool change, then by operation comment, then by
motion pattern. A type is found, in this order:

    KEYWORD   a keyword in the operation's comment            -> HIGH
    G71 ...   the canned cycle that made the moves            -> HIGH
    MOTION    the shape of the moves (see pass_class)         -> MED
    (nothing fits)                                            -> NEEDS TYPE
    YOU       picked in Step 3                                -> SET BY YOU

The type is a label (and future training data). It does not change the geometry: an
operation with no type still contributes its cuts. SKIP is the one exception - it says
"this is not geometry", and Step 4 leaves its cuts out.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from . import keywords as kw
from .flip import part_of
from .parser import WORD_RE, Program, _strip_comments
from .tooling import Tool

HIGH, MED, NEEDS, YOU = "HIGH", "MED", "NEEDS TYPE", "SET BY YOU"
CONFIDENCES = (HIGH, MED, NEEDS, YOU)
CYCLES = ("G70", "G71", "G72", "G74", "G76", "G81", "G82", "G83", "G84", "G92")
_FLAT = 0.002           # a move holds an axis within this (Z inches / X diameter)
_AXIS = 0.02            # diameter at or under this is on the centerline
_FACE_BAND = 0.1        # an X sweep this close to the front-most one is a facing pass
_CHAMFER_MAX = 0.25     # a lone diagonal longer than this is a taper, not a chamfer

# which operation types a motion class can be (used to pair keywords with motion)
FAMILY = {
    "FACE": ("FACE",),
    "TURN": ("OD ROUGH", "OD FINISH", "ID ROUGH", "ID FINISH", "ROUGH", "FINISH"),
    "CONTOUR": ("OD ROUGH", "OD FINISH", "ID ROUGH", "ID FINISH", "ROUGH", "FINISH"),
    "GROOVE": ("OD GROOVE", "FACE GROOVE"),
    "PARTOFF": ("PART-OFF",),
    "DRILL": ("DRILL", "SPOT DRILL", "TAP"),
    "THREAD": ("THREAD",),
    "CHAMFER": ("CHAMFER",),
    "AMBIG": ("FACE GROOVE", "DRILL"),
}
FAMILY["G71"] = FAMILY["G72"] = FAMILY["G70"] = FAMILY["TURN"]
FAMILY["G76"] = FAMILY["G92"] = FAMILY["THREAD"]
FAMILY["G74"] = FAMILY["G81"] = FAMILY["G82"] = FAMILY["G83"] = FAMILY["G84"] = FAMILY["DRILL"]


@dataclass(frozen=True)
class Thread:
    major: float | None
    minor: float | None
    pitch: float | None
    z0: float
    z1: float
    side: str

    @property
    def callout(self) -> str:
        dia = self.major if self.major is not None else self.minor
        size = f"Ø{dia:.4f}" if dia is not None else "Ø?"
        if self.pitch:
            tpi = 1.0 / self.pitch
            lead = f"{tpi:.0f} TPI" if abs(tpi - round(tpi)) < 0.01 else f"pitch {self.pitch:.4f}"
        else:
            lead = "pitch ?"
        root = f", minor {self.minor:.4f}" if self.side == "OD" and self.minor is not None and self.major is not None else (
            f", major {self.major:.4f}" if self.side == "ID" and self.major is not None and self.minor is not None else "")
        return f"{self.side} THREAD {size} x {lead}{root}, Z{self.z0:.3f} to Z{self.z1:.3f}"


@dataclass(frozen=True)
class Operation:
    index: int                      # 1-based "#"
    key: str                        # stable id for a user override: "<tool>@<first line>"
    tool: str
    comment: str
    line0: int
    line1: int
    lines: str                      # "N100-N140" when the block is numbered, else "L8-L15"
    found_by: str                   # KEYWORD | G71 ... | MOTION | YOU | "-"
    type: str | None
    confidence: str
    why: str
    side: str                       # OD | ID | CENTER
    motion: str                     # the motion class (FACE, TURN, G71 ...)
    passes: int
    moves: tuple[int, ...]          # indices into program.moves (approach rapids included)
    thread: Thread | None = None
    part: int = 1                   # 2 for the operations after a flip (OP2), see flip.py


# ---- passes: runs of cutting moves between rapids ----
def _dz(m) -> float:
    return abs(m.z1 - m.z0)


def _dx(m) -> float:
    return abs(m.x1 - m.x0)


def pass_class(cuts) -> str:
    """The motion class of one pass, before context: THREAD, DRILL, XSWEEP, TURN, AMBIG, CHAMFER, CONTOUR.

        X-only moves                         XSWEEP   (face / groove / part-off, by where it is)
        Z-only moves on the centerline       DRILL
        one Z run (+ an X feed in or out)    TURN     (repeated, stepping in X = rough)
        Z in and straight back out, off axis AMBIG    (face groove? off-centre drill?)
        one short diagonal                   CHAMFER
        anything else                        CONTOUR  (one continuous contour = finish)
    """
    if any(m.kind == "thread" for m in cuts):
        return "THREAD"
    if all(max(m.x0, m.x1) <= _AXIS for m in cuts):
        return "DRILL"
    x_only = [m for m in cuts if m.kind != "arc" and _dz(m) <= _FLAT and _dx(m) > _FLAT]
    z_only = [m for m in cuts if m.kind != "arc" and _dx(m) <= _FLAT and _dz(m) > _FLAT]
    other = [m for m in cuts if m not in x_only and m not in z_only and (_dx(m) > _FLAT or _dz(m) > _FLAT)]
    if not other and not z_only and x_only:
        return "XSWEEP"
    if not other and len(z_only) == 1:
        return "TURN"
    if not other and not x_only and len(z_only) == 2 and (z_only[0].z1 - z_only[0].z0) * (z_only[1].z1 - z_only[1].z0) < 0:
        return "AMBIG"
    if len(other) == 1 and not z_only and other[0].kind != "arc" and (
            other[0].z1 - other[0].z0) ** 2 + ((other[0].x1 - other[0].x0) / 2) ** 2 <= _CHAMFER_MAX ** 2:
        return "CHAMFER"
    return "CONTOUR"


def _passes(program: Program) -> list[dict]:
    out, run = [], []

    def close():
        if run:
            cuts = [program.moves[i] for i in run]
            first = cuts[0]
            cyc = first.code.split()[0]
            out.append({"moves": list(run), "tool": first.tool, "comment": first.comment,
                        "cycle": cyc if cyc in CYCLES else None, "cls": pass_class(cuts),
                        "part": part_of(program, first)})
            run.clear()

    for i, m in enumerate(program.moves):
        if m.kind == "rapid" or (run and (m.tool != program.moves[run[-1]].tool
                                          or part_of(program, m) != part_of(program, program.moves[run[-1]]))):
            close()
        if m.kind != "rapid":
            run.append(i)
    close()
    return out


def _resolve_sweeps(program: Program, passes: list[dict], bore: float | None):
    """XSWEEP -> FACE / PARTOFF / GROOVE, from where the sweep sits along Z. Each half of a flip program is
    judged in its own frame (its own front and back), never against the other's."""
    for part in sorted({p["part"] for p in passes}):
        _resolve_part(program, [p for p in passes if p["part"] == part], part, bore)


def _resolve_part(program: Program, passes: list[dict], part: int, bore: float | None):
    sweeps = [p for p in passes if p["cls"] == "XSWEEP" and not p["cycle"]]
    if not sweeps:
        return
    z_of = lambda p: program.moves[p["moves"][0]].z1
    top = max(z_of(p) for p in sweeps)
    cuts = [m for m in program.moves if m.kind != "rapid" and part_of(program, m) == part]
    bottom = min(min(m.z0, m.z1) for m in cuts)
    for p in sweeps:
        low = min(min(program.moves[i].x0, program.moves[i].x1) for i in p["moves"])
        z = z_of(p)
        if z >= top - _FACE_BAND:
            p["cls"] = "FACE"
        elif low <= max(_AXIS, bore or 0.0) and z <= bottom + 0.05:
            p["cls"] = "PARTOFF"
        else:
            p["cls"] = "GROOVE"


# ---- naming ----
def _sided(kind: str, side: str) -> str:
    return f"{'ID' if side == 'ID' else 'OD'} {kind}"


def _from_cycle(cycle: str, side: str, tool: Tool | None) -> str:
    if cycle in ("G71", "G72"):
        return _sided("ROUGH", side)
    if cycle == "G70":
        return _sided("FINISH", side)
    if cycle in ("G76", "G92"):
        return "THREAD"
    if cycle == "G84" or (tool and tool.type == "TAP"):
        return "TAP"
    return "SPOT DRILL" if tool and tool.type == "SPOT DRILL" else "DRILL"


def _from_motion(cls: str, n: int, side: str, tool: Tool | None) -> tuple[str | None, str]:
    if cls == "FACE":
        return "FACE", "X sweep at near-constant Z, at the front of the part"
    if cls == "TURN":
        if n >= 2:
            return _sided("ROUGH", side), f"{n} Z passes stepping in X"
        return _sided("FINISH", side), "one Z pass"
    if cls == "CONTOUR":
        return _sided("FINISH", side), "one continuous contour"
    if cls == "GROOVE":
        if side == "ID":
            return None, "X plunges inside the bore - there is no ID GROOVE type, pick the closest"
        return "OD GROOVE", "X plunges with little Z travel"
    if cls == "PARTOFF":
        return "PART-OFF", "X to the centerline at the back of the part"
    if cls == "DRILL":
        if tool and tool.type in ("SPOT DRILL", "TAP"):
            return tool.type, f"Z-only moves at X0 with a {tool.type.lower()}"
        return "DRILL", "Z-only moves at X0"
    if cls == "THREAD":
        return "THREAD", "threading moves"
    if cls == "CHAMFER":
        return "CHAMFER", "one short diagonal cut"
    return None, "Z in and straight back out, off the centerline - face groove or off-centre drill?"


def _from_keywords(matches, cls: str, n: int, side: str, alone: bool) -> tuple[str, str] | None:
    """(type, keyword) when a keyword in the comment fits this motion, else None."""
    named = [(m.op, m.keyword) for m in matches if m.op]
    if not named:
        return None
    fits = [(op, key) for op, key in named if op in FAMILY.get(cls, ())]
    if not fits:
        # a comment that names ONE operation and is ONE run of motion: take the user's word
        return _generic(*named[0], side) if alone and len(named) == 1 else None
    if len(fits) > 1 and cls in ("TURN", "CONTOUR"):
        want = "ROUGH" if cls == "TURN" and n >= 2 else "FINISH"
        fits = [f for f in fits if want in f[0]] or fits
    return _generic(*fits[0], side)


def _generic(op: str, key: str, side: str) -> tuple[str, str]:
    return (_sided(op, side) if op in ("ROUGH", "FINISH") else op), key


# ---- line ranges and threads ----
def _words(line: str) -> dict[str, float]:
    return {l.upper(): float(v) for l, v in WORD_RE.findall(_strip_comments(line))}


def _line_range(program: Program, line0: int, line1: int, cycle: str | None) -> tuple[int, int, str]:
    if cycle in ("G70", "G71", "G72"):                  # take in the P-Q block the cycle points at
        for i in range(line0 - 1, min(line1, len(program.lines))):
            w = _words(program.lines[i])
            if "P" in w and "Q" in w:
                for j in range(i + 1, len(program.lines)):
                    n = _words(program.lines[j]).get("N")
                    if n is not None and int(n) == int(w["Q"]):
                        if cycle != "G70":
                            line1 = max(line1, j + 1)
                        break
    ns = [int(n) for n in (_words(program.lines[i]).get("N") for i in range(line0 - 1, min(line1, len(program.lines))))
          if n is not None]
    text = (f"N{ns[0]}-N{ns[-1]}" if len(ns) > 1 else f"N{ns[0]}") if ns else (
        f"L{line0}-L{line1}" if line1 != line0 else f"L{line0}")
    return line0, line1, text


def _thread(program: Program, idx: list[int], cycle: str | None) -> Thread:
    th = [program.moves[i] for i in idx if program.moves[i].kind == "thread"]
    k = 1.0 / 25.4 if program.units == "mm" else 1.0
    root_od = min(m.x1 for m in th)
    clear = max((program.moves[i].x0 for i in idx if program.moves[i].kind == "rapid"), default=root_od)
    side = "OD" if clear >= max(m.x1 for m in th) else "ID"
    root = root_od if side == "OD" else max(m.x1 for m in th)
    pitch = th[0].feed * k if th[0].feed else None
    other = None
    if cycle == "G76":                                  # P on the data line is the thread height
        w = _words(program.lines[th[0].line - 1])
        if w.get("P", 0) > 0 and "X" in w:
            h = w["P"] / (1000.0 if program.units == "mm" else 10000.0) * k
            other = root + 2 * h if side == "OD" else root - 2 * h
    major, minor = (other, root) if side == "OD" else (root, other)
    return Thread(major, minor, pitch, th[0].z0, th[0].z1, side)


# ---- the operation list ----
def build_operations(program: Program, tools: list[Tool], table: list[dict],
                     overrides: dict[str, str] | None = None, stock_id: float = 0.0) -> list[Operation]:
    overrides = overrides or {}
    by_number = {t.number: t for t in tools}
    passes = _passes(program)
    _resolve_sweeps(program, passes, stock_id or None)

    groups: list[list[dict]] = []
    for p in passes:
        key = (p["part"], p["tool"], p["comment"], p["cycle"] or p["cls"])
        if groups and groups[-1][0]["_key"] == key:
            groups[-1].append(p)
        else:
            groups.append([p])
        p["_key"] = key
    per_comment: dict[tuple, int] = {}
    for g in groups:
        k = (g[0]["tool"], g[0]["comment"])
        per_comment[k] = per_comment.get(k, 0) + 1

    ops: list[Operation] = []
    bore = stock_id or None                             # the hole so far (diameter); None = solid
    prev_end = -1
    for g in groups:
        first, last = g[0]["moves"][0], g[-1]["moves"][-1]
        tool = by_number.get(g[0]["tool"])
        cls, cycle, n = g[0]["cls"], g[0]["cycle"], len(g)
        motion = cycle or cls
        cut_idx = [i for p in g for i in p["moves"]]
        hi = max(max(program.moves[i].x0, program.moves[i].x1) for i in cut_idx)
        if cls == "DRILL":
            side = "CENTER"
        elif bore is not None and hi <= bore + 1e-6:
            side = "ID"                                 # the cuts sit inside the drilled / bored diameter
        elif tool is not None and tool.side == "ID" and bore is not None:
            side = "ID"
        else:
            side = "OD"
        comment = g[0]["comment"]
        hit = _from_keywords(kw.match(comment, table), motion, n, side, per_comment[(g[0]["tool"], comment)] == 1)
        if hit:
            type_, found, conf, why = hit[0], "KEYWORD", HIGH, f'keyword "{hit[1]}" in the comment'
        elif cycle:
            type_, found, conf, why = _from_cycle(cycle, side, tool), cycle, HIGH, f"{cycle} canned cycle"
        else:
            type_, why = _from_motion(cls, n, side, tool)
            found, conf = ("MOTION", MED) if type_ else ("-", NEEDS)
        lines = [program.moves[i].line for i in cut_idx]
        line0, line1, text = _line_range(program, min(lines), max(lines), cycle)
        key = f"{g[0]['tool']}@{line0}"
        if key in overrides:
            type_, found, conf, why = overrides[key], "YOU", YOU, "set by you"
        thread = _thread(program, list(range(first, last + 1)), cycle) if motion in ("THREAD", "G76", "G92") else None
        ops.append(Operation(len(ops) + 1, key, g[0]["tool"], comment, line0, line1, text, found, type_, conf, why,
                             side, motion, n, tuple(range(prev_end + 1, last + 1)), thread, g[0]["part"]))
        prev_end = last
        if cls == "DRILL":
            bore = max(bore or 0.0, (tool.size or 0.0) if tool else 0.0)
        elif side == "ID":
            bore = max(bore or 0.0, hi)
    return ops


def counts(ops: list[Operation]) -> dict[str, int]:
    return {c: sum(1 for o in ops if o.confidence == c) for c in CONFIDENCES}


def summary(program: Program, ops: list[Operation], tools: list[Tool], stock: dict) -> dict:
    """What is known before the reconstruction (Step 4 adds the profile's own numbers)."""
    cuts = [m for o in ops if o.type != "SKIP" for i in o.moves for m in (program.moves[i],) if m.kind != "rapid"]
    drills = [t.size for t in tools if t.type == "DRILL" and t.size]
    inside = [max(program.moves[i].x0, program.moves[i].x1) for o in ops if o.side == "ID" and o.type != "SKIP"
              for i in o.moves if program.moves[i].kind != "rapid"]
    bore = max(drills + inside + [stock.get("id", 0.0)], default=0.0)
    zs = [z for m in cuts for z in (m.z0, m.z1)]
    return {
        "operations": len(ops),
        "needs_type": sum(1 for o in ops if o.confidence == NEEDS),
        "stock_od": stock.get("od", 0.0),
        "cut_z": (min(zs), max(zs)) if zs else None,
        "bore": bore or None,
        "threads": [o.thread.callout for o in ops if o.thread and o.type != "SKIP"],
        "skipped": sum(1 for o in ops if o.type == "SKIP"),
    }
