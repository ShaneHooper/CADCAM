"""Flip programs: OP1 and OP2 in one program (the part is turned end for end between them).

Stdlib only. A comment that says OP2 / OP 2 / FLIP / FLIP PART / 2ND OP, found AFTER the first cut and BEFORE the
last one, splits the program in two. (An "OP2" in the title - or anywhere before the first cut - names a program
that IS operation 2 on its own, so it is not a split.) The user gives the part's overall length L, and then:

    OP2's Z0 is the far end of the part: L from OP1's Z0, with its +Z pointing away from the part the other way.
    A point at Z in OP2's own frame sits at  -L - Z  in OP1's frame, and its tool is mirrored end for end.

Each half is still classified in its own frame, as written (a face is a face at Z0 in both). Only the model - what
Step 4, the previews and the stock guess see - has OP2 mirrored into OP1's frame.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import re

from .parser import Program

_MARK = re.compile(r"(?<![A-Z0-9])(OP\s*[-.#]?\s*2|FLIP(?:\s*PART)?|2ND\s*OP|SECOND\s*OP(?:ERATION)?)(?![A-Z0-9])")
_COMMENT = re.compile(r"\(([^)]*)\)|;(.*)$")
STEP = 0.250


@dataclass(frozen=True)
class Marker:
    line: int                   # 1-based source line of the comment
    text: str                   # the comment
    keyword: str                # what matched: "OP2", "FLIP PART", ...


@dataclass(frozen=True)
class Flip:
    line: int                   # OP2 starts here: every move on this line or after it is OP2's
    text: str
    length: float               # the part's overall length, typed by the user


def find_marker(program: Program) -> Marker | None:
    """The first flip comment that has cutting before it and cutting after it, or None."""
    cut_lines = [m.line for m in program.moves if m.kind != "rapid"]
    if not cut_lines:
        return None
    first, last = min(cut_lines), max(cut_lines)
    for i, raw in enumerate(program.lines):
        n = i + 1
        if n <= first or n > last:
            continue
        for c in _COMMENT.finditer(raw):
            text = (c.group(1) if c.group(1) is not None else c.group(2)) or ""
            hit = _MARK.search(text.upper())
            if hit:
                return Marker(n, text.strip(), re.sub(r"\s+", " ", hit.group(1)))
    return None


def part_of(program: Program, move) -> int:
    """1 for OP1's moves, 2 for OP2's (always 1 when the program is not a flip)."""
    f = program.flip
    return 2 if f is not None and move.line >= f.line else 1


def with_flip(program: Program, marker: Marker, length: float) -> Program:
    """The same program, told where OP2 starts and how long the part is."""
    return replace(program, flip=Flip(marker.line, marker.text, float(length)))


def guess_length(program: Program, marker: Marker) -> float:
    """A first guess for the dialog: how deep OP1 cuts, up to the next quarter inch. The user types the real one."""
    zs = [min(m.z0, m.z1) for m in program.moves if m.kind != "rapid" and m.line < marker.line]
    depth = -min(zs) if zs and min(zs) < 0 else 0.0
    return max(STEP, round(math.ceil(depth / STEP - 1e-6) * STEP, 6))


def model(program: Program) -> Program:
    """The program as one part in OP1's frame: OP2's moves mirrored about the part (Z -> -L - Z), arcs reversed.
    The same moves in the same order, so an index into program.moves is an index into the model's."""
    f = program.flip
    if f is None:
        return program
    z = lambda v: -f.length - v
    out = []
    for m in program.moves:
        if m.line >= f.line:
            out.append(replace(
                m, z0=z(m.z0), z1=z(m.z1),
                center=None if m.center is None else (z(m.center[0]), m.center[1]),
                clockwise=None if m.clockwise is None else not m.clockwise,
                points=tuple((z(a), x) for a, x in m.points)))
        else:
            out.append(m)
    return replace(program, moves=out)
