"""Post processor: a setup's operations -> G-code text (stdlib only, like the rest of core).

    from gsend_cad.core import post
    text = post.post_setup(setup, [(op, moves), ...], controller="haas", program=1000)

`moves` are the WCS toolpaths from cam.face_toolpath (turning X is a radius there; the lathe
post writes it as a diameter). Inch, absolute, one tool change per operation. Controllers:
"haas" and "fanuc" (generic Fanuc: same codes, homes X and Y together).
"""
from __future__ import annotations

from . import cam

CONTROLLERS = {"haas": "Haas", "fanuc": "Fanuc (generic)"}
OFFSETS = ["G54", "G55", "G56", "G57", "G58", "G59"]


def num(v: float) -> str:
    """Fanuc-style number: 4 places, trailing zeros dropped, always a decimal point (1.25, 0., -0.02)."""
    s = f"{v:.4f}".rstrip("0")
    return "0." if s in ("-0.", "0.", "-0") else s


ASCII = {"·": "-", "Ø": "DIA ", "×": "X", "°": " DEG", "−": "-"}


def _comment(text: str) -> str:
    """(UPPER CASE, plain ASCII, no nested parentheses) - what every control accepts."""
    t = "".join(ASCII.get(c, c) for c in text.upper())
    return "(" + "".join(c for c in t if c not in "()" and 32 <= ord(c) < 127) + ")"


class _Modal:
    """Writes only the words that changed since the last block (X, Y, Z, F, G0/G1)."""

    def __init__(self):
        self.last = {}

    def block(self, words: list[tuple[str, str]]) -> str:
        out = []
        for k, v in words:
            if k in ("X", "Y", "Z", "F", "G") and self.last.get(k) == v:
                continue
            self.last[k] = v
            out.append(v if k == "G" else k + v)
        return " ".join(out)

    def forget(self, *keys):
        for k in keys:
            self.last.pop(k, None)


def post_setup(setup: dict, ops: list[tuple[dict, list]], controller: str = "haas", program: int = 1000,
               offset: str = "G54", coolant: bool = True, doc_name: str = "") -> str:
    """G-code for every operation of a setup, in order."""
    if controller not in CONTROLLERS:
        raise ValueError(f"controller must be one of {', '.join(CONTROLLERS)}")
    if offset not in OFFSETS:
        raise ValueError(f"work offset must be one of {', '.join(OFFSETS)}")
    if not 1 <= int(program) <= 9999:
        raise ValueError("program number must be 1 to 9999")
    if not ops:
        raise ValueError(f"{setup['name']} has no operations to post")
    turning = setup["type"] == cam.TURNING
    L = ["%", f"O{int(program):04d} {_comment(setup['name'])}"]
    if doc_name:
        L.append(_comment(f"PART {doc_name}"))
    L.append(_comment(f"G-SEND CAD/CAM {CONTROLLERS[controller]} {'LATHE' if turning else 'MILL'}"))
    L.append(_comment(cam.describe(setup)))
    L.append("G20 G18 G40 G80 G99" if turning else "G20 G17 G40 G49 G80 G90")
    for op, moves in ops:
        L += (_lathe_op if turning else _mill_op)(setup, op, moves, offset, coolant)
    if turning:
        L += ["G28 U0. W0.", "M30", "%"]
    else:
        L += ["G28 G91 Z0.", "G28 G91 Y0." if controller == "haas" else "G28 G91 X0. Y0.", "G90", "M30", "%"]
    return "\n".join(L) + "\n"


def _mill_op(setup, op, moves, offset, coolant):
    t = int(op.get("tool", 1))
    L = ["", _comment(f"{op['name']} T{t} D{num(op['tool_dia'])} FACE MILL"),
         f"T{t} M06", f"{offset} G90", f"S{int(round(op['rpm']))} M03"]
    m = _Modal()
    first = True
    for kind, (x, y, z) in moves:
        if first:                                     # XY first, then Z with length comp
            L.append(m.block([("G", "G00"), ("X", num(x)), ("Y", num(y))]))
            L.append(f"G43 Z{num(z)} H{t:02d}" + (" M08" if coolant else ""))
            m.last["Z"] = num(z)
            first = False
            continue
        words = [("G", "G00" if kind == "rapid" else "G01"), ("X", num(x)), ("Y", num(y)), ("Z", num(z))]
        if kind == "feed":
            words.append(("F", num(op["feed"])))
        line = m.block(words)
        if line and line not in ("G00", "G01"):
            L.append(line)
    L += ["M09" if coolant else None, "M05"]
    return [x for x in L if x is not None]


def _lathe_op(setup, op, moves, offset, coolant):
    t = int(op.get("tool", 1))
    L = ["", _comment(f"{op['name']} T{t:02d} FACE"), "G28 U0. W0.", f"T{t:02d}{t:02d}", offset,
         f"G50 S{int(round(op['max_rpm']))}", f"G96 S{int(round(op['sfm']))} M03" + (" M08" if coolant else "")]
    m = _Modal()
    for kind, (x, _y, z) in moves:                    # X radius -> diameter
        words = [("G", "G00" if kind == "rapid" else "G01"), ("X", num(x * 2)), ("Z", num(z))]
        if kind == "feed":
            words.append(("F", num(op["ipr"])))
        line = m.block(words)
        if line and line not in ("G00", "G01"):
            L.append(line)
    L += ["M09" if coolant else None, "M05"]
    return [x for x in L if x is not None]
