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
    g71 = []                                          # (contour, P, Q) of each G71 rough so far
    for k, (op, moves) in enumerate(ops):
        L += (_lathe_op(setup, op, moves, offset, coolant, controller, 100 * (k + 1), g71) if turning
              else _mill_op(setup, op, moves, offset, coolant))
    if turning:
        L += ["G28 U0. W0.", "M30", "%"]
    else:
        L += ["G28 G91 Z0.", "G28 G91 Y0." if controller == "haas" else "G28 G91 X0. Y0.", "G90", "M30", "%"]
    return "\n".join(L) + "\n"


def _mill_op(setup, op, moves, offset, coolant):
    t = int(op.get("tool", 1))
    what = {"face": "FACE MILL", "contour": "END MILL 2D CONTOUR"}.get(op.get("type", "face"), "")
    L = ["", _comment(f"{op['name']} T{t} D{num(op['tool_dia'])} {what}"),
         f"T{t} M06", f"{offset} G90", f"S{int(round(op['rpm']))} M03"]
    m = _Modal()
    first = True
    prev = None
    for kind, (x, y, z) in moves:
        if first:                                     # XY first, then Z with length comp
            L.append(m.block([("G", "G00"), ("X", num(x)), ("Y", num(y))]))
            L.append(f"G43 Z{num(z)} H{t:02d}" + (" M08" if coolant else ""))
            m.last["Z"] = num(z)
            first = False
            prev = (x, y, z)
            continue
        words = [("G", "G00" if kind == "rapid" else "G01"), ("X", num(x)), ("Y", num(y)), ("Z", num(z))]
        if kind == "feed":                            # straight down = plunge feed, when the op has one
            down = prev is not None and prev[:2] == (x, y) and z < prev[2]
            words.append(("F", num(op["plunge"] if down and "plunge" in op else op["feed"])))
        line = m.block(words)
        if line and line not in ("G00", "G01"):
            L.append(line)
        prev = (x, y, z)
    L += ["M09" if coolant else None, "M05"]
    return [x for x in L if x is not None]


def _lathe_op(setup, op, moves, offset, coolant, controller="haas", n=100, g71=None):
    t = int(op.get("tool", 1))
    cycle = op.get("output") == "cycle"
    rough = op.get("type") == "rough"
    kind = op.get("type", "face")
    what = {"rough": "OD ROUGH", "finish": "CONTOUR", "face": "FACE"}[kind] + \
        ({"rough": " G71 CYCLE", "finish": " G70 CYCLE", "face": " G94 CYCLE"}[kind] if cycle else "")
    if kind == "finish" and cycle:
        prof = _contour(moves, op)
        ref = next(((p, q) for c, p, q in reversed(g71 or []) if len(c) == len(prof) and
                    all(abs(a - b) < 1e-6 for u, v in zip(c, prof) for a, b in zip(u, v))), None)
        if ref is None:
            raise ValueError(f"{op['name']}: G70 needs an OD Rough with G71 output before it in this setup, "
                             "over the same profile · untick G70 to post it line by line")
    L = ["", _comment(f"{op['name']} T{t:02d} {what}"), "G28 U0. W0.", f"T{t:02d}{t:02d}", offset,
         f"G50 S{int(round(op['max_rpm']))}", f"G96 S{int(round(op['sfm']))} M03" + (" M08" if coolant else "")]
    m = _Modal()
    if cycle:
        if kind == "finish":
            _k, (xs, _y, zs) = moves[0]
            return L + [m.block([("G", "G00"), ("X", num(xs * 2)), ("Z", num(zs))]), f"F{num(op['ipr'])}",
                        f"G70 P{ref[0]} Q{ref[1]}", f"G00 X{num(xs * 2)} Z{num(zs)}"] + \
                (["M09"] if coolant else []) + ["M05"]
        if rough and g71 is not None:
            g71.append((_contour(moves, op), n, n + 1))
        return L + (_g71(moves, op, m, controller, n) if rough else _g94(moves, op, m)) + (["M09"] if coolant else []) + ["M05"]
    for kind, (x, _y, z) in moves:                    # X radius -> diameter
        words = [("G", "G00" if kind == "rapid" else "G01"), ("X", num(x * 2)), ("Z", num(z))]
        if kind == "feed":
            words.append(("F", num(op["ipr"])))
        line = m.block(words)
        if line and line not in ("G00", "G01"):
            L.append(line)
    L += ["M09" if coolant else None, "M05"]
    return [x for x in L if x is not None]


def _g94(moves, op, m):
    """Facing as a G94 canned cycle: one line per depth, after that only the new Z. The cycle
    starts and ends at the start point (the first move: clear of the stock in X and Z)."""
    _k, (xs, _y, zs) = moves[0]
    L = [m.block([("G", "G00"), ("X", num(xs * 2)), ("Z", num(zs))])]
    cuts = [p for k, p in moves if k == "feed" and abs(p[2] - zs) > 1e-9]
    for i, (x, _y, z) in enumerate(cuts):
        L.append(f"G94 X{num(x * 2)} Z{num(z)} F{num(op['ipr'])}" if i == 0 else f"Z{num(z)}")
    L.append(f"G00 X{num(xs * 2)} Z{num(zs)}")         # G00 ends the modal cycle
    return L


def _g71(moves, op, m, controller, n):
    """OD roughing as a G71 cycle. The finish contour (N n .. N n+1) is the rough's profile pass
    with the stock to leave taken back off (the control adds it again from U / W). Haas takes the
    depth of cut as D on one line; Fanuc wants two G71 blocks (U depth R retract, then P Q U W F)."""
    _k, (xs, _y, zs) = moves[0]
    prof = _contour(moves, op)
    p, q = n, n + 1
    u, w = num(2 * op["leave_x"]), num(op["leave_z"])
    L = [m.block([("G", "G00"), ("X", num(xs * 2)), ("Z", num(zs))])]
    if controller == "haas":
        L.append(f"G71 P{p} Q{q} U{u} W{w} D{num(op['stepdown'])} F{num(op['ipr'])}")
    else:
        L += [f"G71 U{num(op['stepdown'])} R{num(op['retract'])}", f"G71 P{p} Q{q} U{u} W{w} F{num(op['ipr'])}"]
    c = _Modal()
    L.append(f"N{p} " + c.block([("G", "G00"), ("X", num(prof[0][0] * 2))]))
    c.last["Z"] = num(zs)
    for x, z in prof:
        line = c.block([("G", "G01"), ("X", num(x * 2)), ("Z", num(z))])
        if line and line != "G01":
            L.append(line)
    L.append(f"N{q} " + c.block([("G", "G01"), ("X", num(xs * 2))]))
    L.append(f"G00 X{num(xs * 2)} Z{num(zs)}")
    return L


def _contour(moves, op):
    """The finished contour [(x radius, z)] of a rough / finish path: its last pass along the
    profile (without the pull-off), with the stock to leave taken back off."""
    end = max(i for i, (k, _p) in enumerate(moves) if k == "feed")
    a = end
    while moves[a - 1][0] == "feed":
        a -= 1
    lx, lz = op["leave_x"], op["leave_z"]
    return [(x - lx, z - lz) for _k, (x, _y, z) in moves[a:end]]
