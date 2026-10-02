"""CAM setups as plain data, plus the stock and WCS math (stdlib only, like the rest of core).

A setup is what Fusion calls a Setup: which kind of machine (milling or turning), which
body, the stock around it and where the work zero (WCS) sits. It lives in
Document.setups (saved in the .gcad file), not in the design timeline.

    {"id": "setup1", "name": "Setup", "type": "milling", "body": "all" | body id,
     "stock": {"mode": "offset", "side": .1, "top": .05, "bottom": 0,       stock per side
               or "mode": "size", "x": 4.25, "y": 3.25, "z": 1.5, "top": .05},  fixed size, centered
                                                                               in X/Y, `top` above
     "wcs": "top-center" | "top-corner" | "model"}

    {"id": "setup2", "name": "Setup2", "type": "turning", "body": ...,
     "axis": "x" | "y" | "z", "front": "+" | "-",           spindle axis, which end faces the tool
     "stock": {"mode": "offset", "od": .05, "face": .05, "back": .5},   radial, face, chuck side
           or {"mode": "size", "dia": 1.625, "length": 3.5, "face": .05},  bar size, face stock
     "wcs": "stock-face" | "part-face"}                       Z0 on the axis at that face

All values inches. bbox arguments are ((xmin, ymin, zmin), (xmax, ymax, zmax)).
"""
from __future__ import annotations

import copy
import math

MILLING, TURNING = "milling", "turning"
TYPES = {MILLING: "Milling", TURNING: "Turning"}
MILL_WCS = {"top-center": "Stock top, center", "top-corner": "Stock top, front-left corner",
            "model": "Model origin", "point": "Picked point"}
# which model direction the WCS +X points along (a turn about Z; the WCS stays right-handed)
X_DIRS = {"+x": ("Model +X", (1.0, 0.0)), "-x": ("Model −X", (-1.0, 0.0)),
          "+y": ("Model +Y", (0.0, 1.0)), "-y": ("Model −Y", (0.0, -1.0))}
TURN_WCS = {"stock-face": "Stock front face", "part-face": "Part front face"}
AXES = {"x": 0, "y": 1, "z": 2}
STOCK_MODES = {"offset": "Stock per side", "size": "Fixed size"}


def new_setup(kind: str) -> dict:
    """A setup of that type with everyday defaults (no id/name yet; Document.add_setup gives them)."""
    if kind == MILLING:
        return {"type": MILLING, "body": "all", "stock": {"mode": "offset", "side": 0.1, "top": 0.05, "bottom": 0.0},
                "wcs": "top-center"}
    if kind == TURNING:
        return {"type": TURNING, "body": "all", "axis": "z", "front": "+",
                "stock": {"mode": "offset", "od": 0.05, "face": 0.05, "back": 0.5}, "wcs": "stock-face"}
    raise ValueError(f"setup type must be milling or turning, not {kind!r}")


def validate(s: dict) -> dict:
    s = copy.deepcopy(s)
    if s.get("type") not in TYPES:
        raise ValueError("setup type must be milling or turning")
    st = s["stock"]
    st["mode"] = st.get("mode", "offset")
    if st["mode"] not in STOCK_MODES:
        raise ValueError(f"bad stock mode {st['mode']!r}")
    for k, v in st.items():
        if k == "mode":
            continue
        st[k] = float(v)
        if st[k] < 0:
            raise ValueError("stock values can't be negative")
    for k in ("x", "y", "z", "dia", "length"):
        if st["mode"] == "size" and k in st and st[k] <= 0:
            raise ValueError("stock size must be greater than 0")
    if s["type"] == MILLING and s["wcs"] not in MILL_WCS:
        raise ValueError(f"bad milling WCS {s['wcs']!r}")
    if s["type"] == MILLING:
        s["x_dir"] = s.get("x_dir", "+x")
        if s["x_dir"] not in X_DIRS:
            raise ValueError(f"bad X direction {s['x_dir']!r}")
        if s["wcs"] == "point":
            pt = s.get("wcs_point")
            if not pt or len(pt) != 3:
                raise ValueError("pick the WCS point in the view first")
            s["wcs_point"] = [float(v) for v in pt]
    if s["type"] == TURNING:
        if s["axis"] not in AXES or s["front"] not in "+-" or s["wcs"] not in TURN_WCS:
            raise ValueError("bad turning axis / front / WCS")
    return s


def guess_axis(bbox) -> str:
    """Spindle axis for a turned part: the axis whose two cross extents match (the part is round
    across it); failing that, the longest side."""
    lo, hi = bbox
    size = [h - l for l, h in zip(lo, hi)]
    best, pick = None, None
    for ax, i in AXES.items():
        a, b = (size[j] for j in range(3) if j != i)
        mismatch = abs(a - b) / max(a, b, 1e-9)
        if mismatch < 0.01 and (best is None or size[i] > best):
            best, pick = size[i], ax
    return pick or "xyz"[max(range(3), key=lambda i: size[i])]


def stock_box(bbox, s):
    """Milling stock: the part's box grown by the offsets. Returns (lo, hi)."""
    (x0, y0, z0), (x1, y1, z1) = bbox
    st = s["stock"]
    if st.get("mode") == "size":                  # centered on the part in X/Y, `top` above it
        cx, cy, top = (x0 + x1) / 2, (y0 + y1) / 2, z1 + st["top"]
        return ((cx - st["x"] / 2, cy - st["y"] / 2, top - st["z"]), (cx + st["x"] / 2, cy + st["y"] / 2, top))
    return ((x0 - st["side"], y0 - st["side"], z0 - st["bottom"]),
            (x1 + st["side"], y1 + st["side"], z1 + st["top"]))


def _unit(i):
    v = [0.0, 0.0, 0.0]
    v[i] = 1.0
    return v


def turning_frame(bbox, s):
    """(i, center, along) for a turning setup: i = axis index, center = the axis line's point in
    the bbox middle, along = (back, front) part ends measured along the axis."""
    i = AXES[s["axis"]]
    lo, hi = bbox
    center = [(l + h) / 2 for l, h in zip(lo, hi)]
    back, front = (lo[i], hi[i]) if s["front"] == "+" else (hi[i], lo[i])
    return i, center, (back, front)


def stock_cylinder(bbox, radius: float, s) -> dict:
    """Turning stock (round bar). radius = the part's largest distance from the axis (the kernel
    measures it). Returns {"axis": [unit], "center": [x, y, z] on the axis at the back end,
    "length", "r", "front": [x, y, z] (center of the front face)}."""
    i, center, (back, front) = turning_frame(bbox, s)
    sign = 1.0 if s["front"] == "+" else -1.0
    st = s["stock"]
    f = front + sign * st["face"]
    if st.get("mode") == "size":                  # a bar of that size, face stock in front
        b = f - sign * st["length"]
        r = st["dia"] / 2
    else:
        b = back - sign * st["back"]
        r = radius + st["od"]
    p_back, p_front = list(center), list(center)
    p_back[i], p_front[i] = b, f
    axis = _unit(i)
    axis[i] = sign
    return {"axis": axis, "center": p_back, "front": p_front, "length": abs(f - b), "r": r}


def round_up(v: float, step: float = 0.125) -> float:
    """Next stock size up (1/8 in steps), for filling in Fixed size."""
    return math.ceil(v / step - 1e-9) * step


def size_from_offsets(bbox, s, radius: float = 0.0) -> dict:
    """Fixed-size stock values matching the setup's per-side stock, rounded up to 1/8 in (what
    switching the Stock mode fills in)."""
    st = s["stock"]
    if s["type"] == MILLING:
        lo, hi = stock_box(bbox, {**s, "stock": {**st, "mode": "offset"}})
        return {"mode": "size", "x": round_up(hi[0] - lo[0]), "y": round_up(hi[1] - lo[1]),
                "z": round_up(hi[2] - lo[2]), "top": st.get("top", 0.05)}
    c = stock_cylinder(bbox, radius, {**s, "stock": {**st, "mode": "offset"}})
    return {"mode": "size", "dia": round_up(c["r"] * 2), "length": round_up(c["length"]), "face": st.get("face", 0.05)}


def fits(bbox, s, radius: float = 0.0) -> str | None:
    """Why fixed-size stock can't hold the part (a message), or None when it fits."""
    st = s["stock"]
    if st.get("mode") != "size":
        return None
    if s["type"] == MILLING:
        lo, hi = stock_box(bbox, s)
        (x0, y0, z0), (x1, y1, z1) = bbox
        for name, need, have in (("X", x1 - x0, hi[0] - lo[0]), ("Y", y1 - y0, hi[1] - lo[1]),
                                 ("Z", z1 - z0 + st["top"], hi[2] - lo[2])):
            if have < need - 1e-9:
                return f"Stock {name} {have:.4f} is smaller than the part needs ({need:.4f})"
        return None
    if st["dia"] / 2 < radius - 1e-9:
        return f"Bar Ø{st['dia']:.4f} is smaller than the part (Ø{radius * 2:.4f})"
    i, _c, (back, front) = turning_frame(bbox, s)
    need = abs(front - back) + st["face"]
    if st["length"] < need - 1e-9:
        return f"Bar length {st['length']:.4f} is shorter than the part + face stock ({need:.4f})"
    return None


def wcs(bbox, s, radius: float = 0.0) -> dict:
    """Work zero: {"origin": [x, y, z], "x": [..], "z": [..]} (unit axes). Milling: Z up. Turning:
    Z along the spindle pointing out of the part at the tool, X radial (like a lathe)."""
    if s["type"] == MILLING:
        lo, hi = stock_box(bbox, s)
        if s["wcs"] == "model":
            o = [0.0, 0.0, 0.0]
        elif s["wcs"] == "point":
            o = list(s["wcs_point"])
        elif s["wcs"] == "top-corner":
            o = [lo[0], lo[1], hi[2]]
        else:
            o = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, hi[2]]
        cx, cy = X_DIRS[s.get("x_dir", "+x")][1]
        return {"origin": o, "x": [cx, cy, 0.0], "z": [0.0, 0.0, 1.0]}
    cyl = stock_cylinder(bbox, radius, s)
    i, center, (_back, front) = turning_frame(bbox, s)
    if s["wcs"] == "part-face":
        o = list(center)
        o[i] = front
    else:
        o = cyl["front"]
    x = _unit((i + 1) % 3)            # any radial direction; X of the lathe
    return {"origin": o, "x": x, "z": cyl["axis"]}


def describe(s: dict) -> str:
    st = s["stock"]
    sized = st.get("mode") == "size"
    if s["type"] == MILLING:
        stock = (f"stock {st['x']:.3f} × {st['y']:.3f} × {st['z']:.3f}" if sized
                 else f"stock +{st['side']:.3f} sides, +{st['top']:.3f} top")
        where = MILL_WCS[s["wcs"]].lower()
        if s["wcs"] == "point":
            where = "at " + ", ".join(f"{v:.4f}" for v in s["wcs_point"])
        turn = "" if s.get("x_dir", "+x") == "+x" else f" · X along {X_DIRS[s['x_dir']][0].lower()}"
        return f"Milling · {stock} · WCS {where}{turn}"
    stock = (f"bar Ø{st['dia']:.3f} × {st['length']:.3f}" if sized
             else f"OD +{st['od']:.3f}, face +{st['face']:.3f}")
    return f"Turning · {s['axis'].upper()} axis · {stock} · Z0 {TURN_WCS[s['wcs']].lower()}"


# ---------------------------------------------------------------- operations
# An operation belongs to a setup (setup["ops"]). Toolpaths are lists of moves in the setup's
# WCS: ("rapid" | "feed", (x, y, z)). Milling: WCS axes are the model's (Z up). Turning:
# (X = radius, 0, Z along the spindle), like lathe G-code but X as radius, not diameter.

FACE_MILL = {"type": "face", "tool": 1, "tool_dia": 2.0, "stepover": 70.0, "stepdown": 0.05, "leave": 0.0,
             "direction": "x", "rpm": 3000.0, "feed": 60.0, "clearance": 0.5}
# turning Face / Roughing / Contour default to the canned cycles (G72 / G71 / G70), Shane 10/1/26
FACE_TURN = {"type": "face", "tool": 1, "stepdown": 0.02, "leave": 0.0, "past_center": 0.02, "sfm": 600.0,
             "ipr": 0.008, "max_rpm": 3000.0, "clearance": 0.1, "output": "cycle"}
TURN_OUTPUT = {"lines": "Single lines (G01)", "cycle": "Canned cycle (G72)"}
GROOVE_TURN = {"type": "groove", "tool": 6, "tool_dia": 0.125, "side": "od", "stepover": 80.0, "peck": 0.0,
               "leave": 0.0, "sfm": 400.0, "ipr": 0.003, "max_rpm": 2500.0, "clearance": 0.1,
               "start_at": None, "end_at": None, "start_ext": 0.0, "past_back": 0.0}
GROOVE_SIDES = {"od": "External (OD)", "id": "Internal (ID)", "face": "Face"}
FACE_PULL = 0.02            # G72 pull-off (45°) after each facing pass
CONTOUR_MILL = {"type": "contour", "tool": 2, "tool_dia": 0.5, "stepdown": 0.25, "leave": 0.0,
                "bottom_offset": 0.0, "direction": "climb", "rpm": 5000.0, "feed": 30.0, "plunge": 10.0,
                "lead": 0.1, "clearance": 0.5}
MILL_ROUGH = {"type": "rough", "tool": 2, "tool_dia": 0.5, "stepdown": 0.1, "stepover": 40.0, "leave": 0.02,
              "leave_floor": 0.01, "direction": "climb", "rpm": 5000.0, "feed": 40.0, "plunge": 10.0,
              "clearance": 0.5, "islands": [], "boundary": None}
ROUGH_TURN = {"type": "rough", "tool": 2, "stepdown": 0.05, "leave_x": 0.01, "leave_z": 0.005, "retract": 0.02,
              "past_back": 0.0, "sfm": 600.0, "ipr": 0.01, "max_rpm": 3000.0, "clearance": 0.1, "output": "cycle",
              "start_at": None, "end_at": None, "start_ext": 0.0, "internal": False, "bore_dia": 0.0}
ROUGH_OUTPUT = {"lines": "Single lines (G01)", "cycle": "Canned cycle (G71)"}
FINISH_TURN = {"type": "finish", "tool": 3, "leave_x": 0.0, "leave_z": 0.0, "retract": 0.02, "past_back": 0.0,
               "sfm": 800.0, "ipr": 0.005, "max_rpm": 3000.0, "clearance": 0.1, "output": "cycle",
               "start_at": None, "end_at": None, "start_ext": 0.0, "internal": False, "bore_dia": 0.0}
DRILL_MILL = {"type": "drill", "tool": 4, "tool_dia": 0.25, "cycle": "peck", "peck": 0.1, "breakthrough": 0.05,
              "retract": 0.1, "clearance": 0.5, "rpm": 2500.0, "feed": 10.0, "hole_dia": 0.0, "depth": 0.0,
              "picked": []}                    # picked holes (their top centres, model coords); [] = by size
DRILL_TURN = {"type": "drill", "tool": 5, "tool_dia": 0.25, "cycle": "peck", "peck": 0.1, "breakthrough": 0.05,
              "retract": 0.1, "clearance": 0.1, "rpm": 1200.0, "ipr": 0.004, "hole_dia": 0.0, "depth": 0.0,
              "start_at": None, "end_at": None, "start_ext": 0.0, "past_back": 0.0}
DRILL_CYCLES = {"drill": "Drill (G81)", "peck": "Peck (G83)", "chip": "Chip break (G73)"}
TURN_DRILL_CYCLES = ("drill", "peck")          # G73 is a pattern cycle on a lathe, not chip breaking
DRILL_TIP = 0.5 / math.tan(math.radians(59))   # 118° point: tip length = 0.3004 x drill Ø
PECK_GAP = 0.02                                # rapid back down to this far above the last peck
OP_TYPES = {"face": "Face", "contour": "Contour", "rough": "Roughing", "finish": "Contour", "drill": "Drill",
            "groove": "Groove"}


def next_name(base: str, taken) -> str:
    """The first one is just its name (Setup, Face, Roughing); a second gets a 2 (Face2), ..."""
    if base not in taken:
        return base
    k = 2
    while f"{base}{k}" in taken:
        k += 1
    return f"{base}{k}"


def new_op(setup: dict, kind: str = "face") -> dict:
    if kind == "face":
        return copy.deepcopy(FACE_MILL if setup["type"] == MILLING else FACE_TURN)
    if kind == "contour":
        if setup["type"] != MILLING:
            raise ValueError("2D Contour needs a Milling setup")
        return copy.deepcopy(CONTOUR_MILL)
    if kind == "rough":
        return copy.deepcopy(ROUGH_TURN if setup["type"] == TURNING else MILL_ROUGH)
    if kind == "drill":
        return copy.deepcopy(DRILL_MILL if setup["type"] == MILLING else DRILL_TURN)
    if kind == "groove":
        if setup["type"] != TURNING:
            raise ValueError("Groove needs a Turning setup")
        return copy.deepcopy(GROOVE_TURN)
    if kind == "finish":
        if setup["type"] != TURNING:
            raise ValueError("turning Contour needs a Turning setup")
        return copy.deepcopy(FINISH_TURN)
    raise ValueError(f"operation {kind!r} is not built yet")


def validate_op(setup: dict, op: dict) -> dict:
    op = {**new_op(setup, op.get("type", "face")), **copy.deepcopy(op)}
    for k, v in list(op.items()):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            op[k] = float(v)
    for k in ("tool_dia", "stepdown", "rpm", "feed", "sfm", "ipr", "max_rpm", "plunge", "retract"):
        if k in op and op[k] <= 0:
            raise ValueError(f"{k.replace('_', ' ')} must be greater than 0")
    op["tool"] = int(round(op["tool"]))
    if not 1 <= op["tool"] <= 99:
        raise ValueError("tool number must be 1 to 99")
    if op["type"] == "face" and setup["type"] == MILLING:
        if not 1 <= op["stepover"] <= 100:
            raise ValueError("stepover must be 1 to 100 % of the tool")
        if op["direction"] not in ("x", "y"):
            raise ValueError("direction must be x or y")
    if op.get("output", "lines") not in ("lines", "cycle"):
        raise ValueError("output must be lines or cycle")
    if op["type"] == "contour" and op["direction"] not in ("climb", "conventional"):
        raise ValueError("direction must be climb or conventional")
    if op["type"] == "groove":
        if op["side"] not in GROOVE_SIDES:
            raise ValueError("groove must be od, id or face")
        if not 1 <= op["stepover"] <= 100:
            raise ValueError("stepover must be 1 to 100 % of the groove width")
        if op["peck"] < 0:
            raise ValueError("peck can't be negative")
    if op["type"] == "drill":
        if op["cycle"] not in (DRILL_CYCLES if setup["type"] == MILLING else TURN_DRILL_CYCLES):
            raise ValueError("drill cycle must be " + " / ".join(DRILL_CYCLES if setup["type"] == MILLING
                                                                  else TURN_DRILL_CYCLES))
        if op["cycle"] != "drill" and op["peck"] <= 0:
            raise ValueError("peck must be greater than 0")
    for k in ("leave", "past_center", "clearance", "lead", "leave_x", "leave_z", "past_back", "breakthrough",
              "hole_dia", "start_ext", "depth", "bore_dia"):
        if k in op and op[k] < 0:
            raise ValueError(f"{k.replace('_', ' ')} can't be negative")
    return op


def _levels(top: float, bottom: float, stepdown: float) -> list[float]:
    """Z of each pass from top down to bottom, equal steps no bigger than stepdown."""
    depth = top - bottom
    if depth <= 1e-9:
        return [bottom]                           # nothing to remove: one skim pass at the target
    n = math.ceil(depth / stepdown - 1e-9)
    return [top - depth * k / n for k in range(1, n + 1)]


def face_toolpath(bbox, setup: dict, op: dict, radius: float = 0.0) -> list[tuple]:
    """Moves for a Face operation, in the setup's WCS (see the note above)."""
    op = validate_op(setup, op)
    w = wcs(bbox, setup, radius)
    moves = []
    if setup["type"] == MILLING:
        o = w["origin"]
        lo, hi = stock_box(bbox, setup)
        lo = [lo[i] - o[i] for i in range(3)]      # stock in WCS coordinates
        hi = [hi[i] - o[i] for i in range(3)]
        part_top = bbox[1][2] - o[2]
        r = op["tool_dia"] / 2
        step = op["tool_dia"] * op["stepover"] / 100
        a, b = (0, 1) if op["direction"] == "x" else (1, 0)   # a = cutting direction, b = stepping
        start, end = lo[a] - r - 0.1, hi[a] + r + 0.1         # fully off the stock at both ends
        width = hi[b] - lo[b]
        if op["tool_dia"] >= width + 0.2:                     # one pass down the middle covers it
            rows = [(lo[b] + hi[b]) / 2]
        else:
            rows, v = [], lo[b] - r + step
            while True:
                rows.append(v)
                if v + r >= hi[b] - 1e-9:
                    break
                v += step
        safe = hi[2] + op["clearance"]
        levels = _levels(hi[2], part_top + op["leave"], op["stepdown"])

        def pt(u, v, z):
            p = [0.0, 0.0, z]
            p[a], p[b] = u, v
            return tuple(p)

        for z in levels:
            moves.append(("rapid", pt(start, rows[0], safe)))
            moves.append(("rapid", pt(start, rows[0], z + 0.1)))
            moves.append(("feed", pt(start, rows[0], z)))
            fwd = True
            for k, v in enumerate(rows):
                u0, u1 = (start, end) if fwd else (end, start)
                if k:
                    moves.append(("feed", pt(u0, v, z)))      # step over, off the stock
                moves.append(("feed", pt(u1, v, z)))
                fwd = not fwd
            moves.append(("rapid", pt(moves[-1][1][a], rows[-1], safe)))
        return moves
    # turning: X = radius, Z along the spindle (0 at the WCS), tool comes from +Z
    c = stock_cylinder(bbox, radius, setup)
    i, center, (_back, front) = turning_frame(bbox, setup)
    sign = 1.0 if setup["front"] == "+" else -1.0
    z_stock = (c["front"][i] - w["origin"][i]) * sign
    z_part = (front - w["origin"][i]) * sign
    x_out = c["r"] + op["clearance"]
    x_end = -op["past_center"]
    levels = _levels(z_stock, z_part + op["leave"], op["stepdown"])
    z_start = z_stock + op["clearance"]
    moves.append(("rapid", (x_out, 0.0, z_start)))
    if op.get("output") == "cycle":               # G72: Z in rapid, face in X, 45° pull-off, rapid back out
        for z in levels:
            moves += [("rapid", (x_out, 0.0, z)), ("feed", (x_end, 0.0, z)),
                      ("rapid", (x_end + FACE_PULL, 0.0, z + FACE_PULL)), ("rapid", (x_out, 0.0, z + FACE_PULL))]
        return moves + [("rapid", (x_out, 0.0, z_start))]
    for z in levels:
        moves.append(("rapid", (x_out, 0.0, z)))
        moves.append(("feed", (x_end, 0.0, z)))
        moves.append(("rapid", (x_end, 0.0, z + op["clearance"])))
        moves.append(("rapid", (x_out, 0.0, z + op["clearance"])))
    return moves


def contour_toolpath(bbox, setup: dict, op: dict, loops) -> list[tuple]:
    """2D Contour around the part's outside. `loops` = where the tool CENTER runs, in model XY
    (kernel.outline_loops already grew them by tool radius + stock to leave). Climb = clockwise
    around the outside (spindle M03). Lead in / out square off the wall at the middle of the
    longest side; stepdowns from the stock top to the part bottom (minus bottom_offset)."""
    op = validate_op(setup, op)
    if setup["type"] != MILLING:
        raise ValueError("2D Contour needs a Milling setup")
    if not loops:
        raise ValueError("no outline to contour")
    w = wcs(bbox, setup)
    o = w["origin"]
    lo, hi = stock_box(bbox, setup)
    top, part_bottom = hi[2] - o[2], bbox[0][2] - o[2]
    safe = top + op["clearance"]
    moves = []
    for loop in loops:
        # a picked chain: {"pts", "bottom" (its floor, model Z), "inside" (a pocket / bore wall)}
        inside = isinstance(loop, dict) and loop.get("inside", False)
        bottom = (loop["bottom"] - o[2] if isinstance(loop, dict) and "bottom" in loop else part_bottom) \
            - op["bottom_offset"]
        levels = _levels(top, bottom, op["stepdown"])
        pts = [(x - o[0], y - o[1]) for x, y in (loop["pts"] if isinstance(loop, dict) else loop)]
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])) / 2
        climb = op["direction"] == "climb"
        if (area > 0) == (climb != inside):
            pts.reverse()                       # climb: clockwise outside, counter-clockwise inside
        cw = climb != inside
        k = max(range(len(pts)), key=lambda i: math.dist(pts[i], pts[(i + 1) % len(pts)]))
        a, b = pts[k], pts[(k + 1) % len(pts)]
        start = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        ring = [start] + pts[k + 1:] + pts[:k + 1] + [start]
        d = math.dist(a, b) or 1.0
        dx, dy = (b[0] - a[0]) / d, (b[1] - a[1]) / d
        nx, ny = (-dy, dx) if climb else (dy, -dx)         # away from the wall (out / into the pocket)
        lead = (start[0] + nx * op["lead"], start[1] + ny * op["lead"])
        moves.append(("rapid", (lead[0], lead[1], safe)))
        moves.append(("rapid", (lead[0], lead[1], top + 0.1)))
        for z in levels:
            moves.append(("feed", (lead[0], lead[1], z)))    # plunge off the part
            moves += [("feed", (x, y, z)) for x, y in ring]
            moves.append(("feed", (lead[0], lead[1], z)))
        moves.append(("rapid", (lead[0], lead[1], safe)))
    return moves


def mill_rough_layers(bbox, setup: dict, op: dict) -> list[tuple]:
    """Mill Roughing's depths: [(z WCS, [index of each island standing at that depth])], from just
    under the stock top down to the islands' floor + floor stock. An island (a picked
    kernel.slice_chains wall) stands at depths between its floor z0 and its top z1."""
    op = validate_op(setup, op)
    isl = op.get("islands") or []
    if not isl:
        raise ValueError("pick the geometry to rough around (the select button, then the part's walls)")
    o = wcs(bbox, setup)["origin"]
    lo, hi = stock_box(bbox, setup)
    top = hi[2] - o[2]
    floor = min(c["z0"] for c in isl) - o[2] + op["leave_floor"]
    if floor >= top - 1e-9:
        raise ValueError("nothing to rough: the picked walls start at the stock top")
    out = []
    for z in _levels(top, floor, op["stepdown"]):
        zm = z + o[2]                                        # back in model Z
        out.append((z, [i for i, c in enumerate(isl) if c["z0"] - 1e-6 <= zm - op["leave_floor"] < c["z1"] - 1e-9
                        or c["z0"] - 1e-6 <= zm < c["z1"] - 1e-9]))
    return out


def _inside(p, loop) -> bool:
    x, y = p
    c = False
    for (x0, y0), (x1, y1) in zip(loop, loop[1:] + loop[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            c = not c
    return c


def mill_rough_toolpath(bbox, setup: dict, op: dict, layers) -> list[tuple]:
    """Mill Roughing: clear the stock around the picked islands, layer by layer. `layers` =
    [(z WCS, passes)] with passes = kernel.clearing_passes for that depth's islands (model XY,
    tool center paths, outermost first). Each layer: the outside passes inward (the first runs
    in the air past the stock), then the passes round the islands from the middle out; a short
    hop to the next pass is fed at depth, a long one goes up and over. Climb = counter-clockwise
    on the outside, clockwise round islands."""
    op = validate_op(setup, op)
    o = wcs(bbox, setup)["origin"]
    lo, hi = stock_box(bbox, setup)
    safe = hi[2] - o[2] + op["clearance"]
    climb = op["direction"] == "climb"
    hop = op["tool_dia"] * 1.01
    moves, at = [], None
    for z, passes in layers:
        outer, inner = [], []
        for k, loops in enumerate(passes):
            for q in loops:
                q = [(x - o[0], y - o[1]) for x, y in q]
                around = sum(1 for other in loops if other is not q and len(other) > 2
                             and _inside((q[0][0] + o[0], q[0][1] + o[1]), other)) % 2 == 1
                (inner if around else outer).append((k, q))
        order = sorted(outer, key=lambda t: t[0]) + sorted(inner, key=lambda t: -t[0])
        for _k, q in order:
            area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(q, q[1:] + q[:1])) / 2
            island = (_k, q) in inner
            if (area > 0) != (climb != island):             # outside: CCW, islands: CW (climb)
                q = q[::-1]
            if at is not None and at[2] == z:
                i = min(range(len(q)), key=lambda j: math.dist(at[:2], q[j]))
            else:
                i = 0
            q = q[i:] + q[:i]
            start = q[0]
            if at is not None and at[2] == z and math.dist(at[:2], start) <= hop:
                moves.append(("feed", (start[0], start[1], z)))           # a short hop at depth
            else:
                if at is not None:
                    moves.append(("rapid", (at[0], at[1], safe)))
                moves += [("rapid", (start[0], start[1], safe)), ("rapid", (start[0], start[1], z + 0.1)),
                          ("feed", (start[0], start[1], z))]
            moves += [("feed", (x, y, z)) for x, y in q[1:] + [q[0]]]
            at = (q[0][0], q[0][1], z)
    if not moves:
        raise ValueError("nothing to rough inside the boundary")
    moves.append(("rapid", (at[0], at[1], safe)))
    return moves


def _envelope(pts):
    """Running max of a (z, r) polyline walked from the front (z falling): what an OD tool
    cutting toward the chuck can reach - it never dips into a groove or undercut."""
    out = [pts[0]]
    top = pts[0][1]
    for (z0, r0), (z1, r1) in zip(pts, pts[1:]):
        if r1 >= top - 1e-12:
            if r0 < top - 1e-12 and r1 > top:           # climbing back out of a dip: meet the flat
                z = z0 + (top - r0) * (z1 - z0) / (r1 - r0)
                out.append((z, top))
            out.append((z1, r1))
            top = r1
        elif out[-1][1] >= top - 1e-12:
            out.append((z1, top))                        # hold the height across the dip
        else:
            out[-1] = (z1, top)
    clean = [out[0]]
    for q in out[1:]:
        if abs(q[0] - clean[-1][0]) <= 1e-9 and abs(q[1] - clean[-1][1]) <= 1e-9:
            continue                                     # same point twice
        if len(clean) >= 2:                              # still on the same straight line: extend it
            (z0, r0), (z1, r1) = clean[-2], clean[-1]
            same_way = (z1 - z0) * (q[0] - z1) + (r1 - r0) * (q[1] - r1) > 0
            if same_way and abs((z1 - z0) * (q[1] - r0) - (r1 - r0) * (q[0] - z0)) < 1e-9:
                clean[-1] = q
                continue
        clean.append(q)
    return clean


def rough_contour(bbox, setup: dict, op: dict, profile, radius: float = 0.0) -> list[tuple]:
    """The finished OD the rough works toward, in WCS (z, r) from the part's front to the back
    limit: the part's silhouette as an OD tool reaches it (no grooves / undercuts), front first.
    `profile` = kernel.turn_profile about the setup axis (t measured from the bbox middle)."""
    w = wcs(bbox, setup, radius)
    i, center, (back, front) = turning_frame(bbox, setup)
    sign = 1.0 if setup["front"] == "+" else -1.0

    def z_of(t):
        return (center[i] + t - w["origin"][i]) * sign
    pts = [(z_of(t), r) for t, r in (reversed(profile) if sign > 0 else profile)]   # front first
    if not pts:
        raise ValueError("no part profile to rough")
    z_lo, z_hi = toolpath_limits(bbox, setup, op, radius)
    if z_hi <= z_lo + 1e-6:
        raise ValueError("Start must be in front of End (Start nearer the part's front face)")
    env = _envelope(pts)
    if env[0][0] < z_hi - 1e-9:                             # Extend start: in the air ahead of the face
        env.insert(0, (z_hi, env[0][1]))
    if env[-1][0] > z_lo + 1e-9:                            # past the part's back end
        env.append((z_lo, env[-1][1]))
    return _clip(env, z_lo, z_hi)


def _clip(env, z_lo, z_hi):
    """The part of a front-first (z, r) polyline between z_hi (start) and z_lo (end)."""
    def at(z0, r0, z1, r1, z):
        return r0 + (r1 - r0) * (z - z0) / (z1 - z0) if z1 != z0 else r1
    cut = []
    for (z0, r0), (z1, r1) in zip(env, env[1:]):
        if z1 > z_hi + 1e-12 or z0 < z_lo - 1e-12:          # wholly before the start / past the end
            continue
        a = (z_hi, at(z0, r0, z1, r1, z_hi)) if z0 > z_hi else (z0, r0)
        b = (z_lo, at(z0, r0, z1, r1, z_lo)) if z1 < z_lo else (z1, r1)
        if not cut:
            cut.append(a)
        if b != cut[-1]:
            cut.append(b)
    return cut or [(z_hi, env[0][1])]


def axial_to_wcs(bbox, setup: dict, coord: float, radius: float = 0.0) -> float:
    """A model coordinate along the spindle axis (what Start / End store) as WCS Z."""
    i = AXES[setup["axis"]]
    sign = 1.0 if setup["front"] == "+" else -1.0
    return (coord - wcs(bbox, setup, radius)["origin"][i]) * sign


def toolpath_limits(bbox, setup: dict, op: dict, radius: float = 0.0) -> tuple:
    """(z_end, z_start) in WCS for a turning rough / contour: Start = the picked spot (or the part's
    front face) + Extend start; End = the picked spot (or the part's back end) + Extend end."""
    w = wcs(bbox, setup, radius)
    i, _center, (back, front) = turning_frame(bbox, setup)
    start = op.get("start_at")
    end = op.get("end_at")
    z_hi = axial_to_wcs(bbox, setup, front if start is None else start, radius) + op.get("start_ext", 0.0)
    z_lo = axial_to_wcs(bbox, setup, back if end is None else end, radius) - op["past_back"]
    return z_lo, z_hi


def rough_toolpath(bbox, setup: dict, op: dict, profile, radius: float = 0.0) -> list[tuple]:
    """OD roughing: passes along Z (toward the chuck) at falling radii, `stepdown` per side, each
    stopping at the part (+ stock to leave X / Z) with a 45° pull-off, then one pass following the
    profile at the stock to leave to take off the steps. X is radius, like the face path."""
    op = validate_op(setup, op)
    if setup["type"] != TURNING:
        raise ValueError("Roughing needs a Turning setup")
    prof, top, x_out, z_start, flip = _turn_side(bbox, setup, op, profile, radius)
    rt = op["retract"]
    r_min = prof[0][1]
    moves = [("rapid", (x_out, 0.0, z_start))]
    if r_min >= top - 1e-9:
        raise ValueError("nothing to bore: the bore is no bigger than the pre-drilled hole" if flip else
                         "nothing to rough: the part is as big as the stock")

    def z_hit(r):
        """Where the profile first reaches radius r, walking back from the front."""
        for (z0, r0), (z1, r1) in zip(prof, prof[1:]):
            if r0 >= r - 1e-12:
                return z0
            if r1 >= r - 1e-12:
                return z0 + (r - r0) * (z1 - z0) / (r1 - r0)
        return prof[-1][0]
    for r in _levels(top, r_min, op["stepdown"]):
        ze = z_hit(r)
        if r <= r_min + 1e-9:
            continue                                         # the front diameter itself: profile pass does it
        moves += [("rapid", (r, 0.0, z_start)), ("feed", (r, 0.0, ze)),
                  ("feed", (r + rt, 0.0, ze + rt)), ("rapid", (r + rt, 0.0, z_start))]
    return _unflip(moves + _profile_pass(prof, rt, x_out, z_start), flip)  # profile pass at the stock to leave


def _turn_side(bbox, setup, op, profile, radius):
    """What Roughing / Contour work on, OD or ID (op["internal"]): (profile front-first with the
    stock to leave, top = the radius the cuts start from, x_out, z_start, flip). An ID is worked
    as a mirror image (radius negated), so the same OD rules apply - an ID bar can't reach into a
    bigger bore behind a smaller one, just as an OD tool can't reach a groove; `flip` says to turn
    the moves back. ID `profile` = kernel.turn_bore; the cuts start from the pre-drilled hole
    (bore_dia, 0 = the smallest bore the path runs along) and stop where the bore gets smaller."""
    c = stock_cylinder(bbox, radius, setup)
    w = wcs(bbox, setup, radius)
    i = AXES[setup["axis"]]
    sign = 1.0 if setup["front"] == "+" else -1.0
    z_start = (c["front"][i] - w["origin"][i]) * sign + op["clearance"]
    flip = bool(op.get("internal"))
    if not flip:
        env = rough_contour(bbox, setup, op, profile, radius)
        top, x_out = c["r"], c["r"] + op["clearance"]
    else:
        env = rough_contour(bbox, setup, op, [(t, -r) for t, r in profile], radius)
        if env[0][1] > -1e-6:
            raise ValueError("no bore at the front of the part to cut")
        r0 = op.get("bore_dia", 0.0) / 2 or min(-r for _z, r in env if -r > 1e-6)
        env = _stop_below(env, -r0)                          # not past where the hole is smaller
        top, x_out = -r0, -max(r0 - op["clearance"], 0.0)
    prof = [(z + op["leave_z"], r + op["leave_x"]) for z, r in env]
    if op.get("start_at") is not None:                       # a picked Start: come in just ahead of it
        z_start = prof[0][0] + op["clearance"]
    return prof, top, x_out, z_start, flip


def _stop_below(env, top):
    """A front-first (z, r) polyline up to where r first rises above `top` (mirrored ID: the
    bore gets smaller than the pre-drilled hole)."""
    out = [env[0]]
    for (z0, r0), (z1, r1) in zip(env, env[1:]):
        if r1 > top + 1e-9:
            if r0 < top - 1e-9:
                out.append((z0 + (top - r0) * (z1 - z0) / (r1 - r0), top))
            break
        out.append((z1, r1))
    return out


def _unflip(moves, flip):
    return [(k, (-x, y, z)) for k, (x, y, z) in moves] if flip else moves


def _profile_pass(prof, rt, x_out, z_start):
    """Down to the profile's front in rapid (in the air ahead of the part), along it at feed,
    45° pull-off at the back, out and home."""
    zl, rl = prof[-1]
    return ([("rapid", (prof[0][1], 0.0, z_start))] + [("feed", (r, 0.0, z)) for z, r in prof] +
            [("feed", (rl + rt, 0.0, zl + rt)), ("rapid", (x_out, 0.0, zl + rt)), ("rapid", (x_out, 0.0, z_start))])


def finish_toolpath(bbox, setup: dict, op: dict, profile, radius: float = 0.0) -> list[tuple]:
    """Turning Contour (finish): one pass along the part's OD from the front to the back limit,
    at the stock to leave (0 = finished size). Same reach rules as Roughing (no grooves)."""
    op = validate_op(setup, op)
    if setup["type"] != TURNING:
        raise ValueError("turning Contour needs a Turning setup")
    prof, _top, x_out, z_start, flip = _turn_side(bbox, setup, op, profile, radius)
    return _unflip([("rapid", (x_out, 0.0, z_start))] + _profile_pass(prof, op["retract"], x_out, z_start), flip)


def _strips(segs):
    """[(u0, u1, h)]: the (u, v) segments cut at every end point into strips along u, h = the
    highest v over the strip (where an OD / ID / face tool coming down in v first meets metal)."""
    segs = [(u0, v0, u1, v1) if u0 <= u1 else (u1, v1, u0, v0) for u0, v0, u1, v1 in segs]
    us = sorted({round(v, 9) for q in segs for v in (q[0], q[2])})
    out = []
    for a, b in zip(us, us[1:]):
        hs = [max(v0 + (v1 - v0) * (x - u0) / (u1 - u0) for x in (a, b))
              for u0, v0, u1, v1 in segs if u0 <= a + 1e-9 and u1 >= b - 1e-9 and u1 - u0 > 1e-12]
        if hs:
            out.append((a, b, max(hs)))
    return out


def _groove_regions(strips):
    """[(u_lo, u_hi, rim)]: dips with metal on BOTH sides (a groove; a step open to one end is
    not one). rim = the lower wall's height."""
    n = len(strips)
    pre, suf, m = [0.0] * n, [0.0] * n, -math.inf
    for k, (a, b, h) in enumerate(strips):
        if k and abs(strips[k - 1][1] - a) > 1e-9:
            m = -math.inf                                    # a gap: open there
        m = max(m, h)
        pre[k] = m
    m = -math.inf
    for k in range(n - 1, -1, -1):
        if k < n - 1 and abs(strips[k + 1][0] - strips[k][1]) > 1e-9:
            m = -math.inf
        m = max(m, strips[k][2])
        suf[k] = m
    out = []
    for k, (a, b, h) in enumerate(strips):
        level = min(pre[k], suf[k])
        if h < level - 1e-6:
            if out and abs(out[-1][1] - a) < 1e-9:
                out[-1] = (out[-1][0], b, max(out[-1][2], level))
            else:
                out.append((a, b, level))
    return out


def groove_toolpath(bbox, setup: dict, op: dict, section, radius: float = 0.0) -> list[tuple]:
    """Groove: straight plunges side by side (stepover % of the insert width) into every groove
    of the part - on the OD, in the bore (ID) or in the front face. `section` =
    kernel.turn_section about the setup axis. The insert's programmed point is its front corner
    (OD / ID) or its outer corner (face); each plunge stops on the highest metal under the insert
    (+ stock to leave), so it never cuts the part. Peck > 0: pecks with a short pull back."""
    op = validate_op(setup, op)
    if setup["type"] != TURNING:
        raise ValueError("Groove needs a Turning setup")
    c = stock_cylinder(bbox, radius, setup)
    w = wcs(bbox, setup, radius)
    i, center, _ = turning_frame(bbox, setup)
    sign = 1.0 if setup["front"] == "+" else -1.0
    z_stock = (c["front"][i] - w["origin"][i]) * sign
    z_start, x_out = z_stock + op["clearance"], c["r"] + op["clearance"]

    def z_of(t):
        return (center[i] + t - w["origin"][i]) * sign
    side, W, cl = op["side"], op["tool_dia"], op["clearance"]
    zr = [(z_of(t0), r0, z_of(t1), r1) for t0, r0, t1, r1 in section]
    uv = {"od": [(z0, r0, z1, r1) for z0, r0, z1, r1 in zr],
          "id": [(z0, -r0, z1, -r1) for z0, r0, z1, r1 in zr],
          "face": [(r0, z0, r1, z1) for z0, r0, z1, r1 in zr]}[side]

    def xz(u, v):
        return {"od": (v, 0.0, u), "id": (-v, 0.0, u), "face": (u, 0.0, v)}[side]
    strips = _strips(uv)
    regions = _groove_regions(strips)
    if side != "face":
        z_lo, z_hi = toolpath_limits(bbox, setup, op, radius)
        regions = [(max(a, z_lo), min(b, z_hi), rim) for a, b, rim in regions if b > z_lo and a < z_hi]
    if not regions:
        raise ValueError("no " + GROOVE_SIDES[side].split(" (")[0].lower() + " groove found on the part" +
                         (" between Start and End" if side != "face" else ""))
    fits = [g for g in regions if g[1] - g[0] >= W - 1e-9]
    if not fits:
        raise ValueError(f"every groove is narrower than the insert (Ø{W:.4f} wide)")

    def top(u0, u1):
        return max((h for a, b, h in strips if b > u0 + 1e-9 and a < u1 - 1e-9), default=-math.inf)
    step = W * op["stepover"] / 100
    home = ("rapid", (x_out, 0.0, z_start))
    moves = [home]
    for lo, hi, rim in fits:
        us, u = [], hi
        while u > lo + W + 1e-9:
            us.append(u)
            u -= step
        us.append(lo + W)
        v_app = rim + cl
        if side == "od":
            v_safe = x_out
        elif side == "id":                                   # in through the bore: below its smallest Ø
            v_safe = max(v_app, top(hi, math.inf) + cl)
        else:
            v_safe = z_start
        first = True
        for u in us:
            bottom = top(u - W, u) + op["leave"]
            if bottom >= v_app - cl - 1e-9:
                continue                                     # metal up to the rim here: nothing to cut
            if first:
                if side == "face":
                    moves.append(("rapid", xz(u, v_safe)))
                else:
                    x_safe = xz(u, v_safe)[0]                # to the travel Ø in front of the part, then in
                    moves += [("rapid", (x_safe, 0.0, z_start)), ("rapid", xz(u, v_safe))]
                first = False
            moves.append(("rapid", xz(u, v_app)))
            q = op["peck"] if op["peck"] > 0 else v_app - bottom
            v = v_app
            while v > bottom + 1e-9:
                v = max(v - q, bottom)
                moves.append(("feed", xz(u, v)))
                if v > bottom + 1e-9:
                    moves.append(("rapid", xz(u, v + PECK_GAP)))
            moves.append(("rapid", xz(u, v_app)))
        if not first:
            last = moves[-1][1]
            moves.append(("rapid", xz(last[0] if side == "face" else last[2], v_safe)))   # back up
            if side != "face":
                moves.append(("rapid", (moves[-1][1][0], 0.0, z_start)))
    if len(moves) == 1:
        raise ValueError("the grooves are already cut to size")
    return moves + [home]


def drill_targets(bbox, setup: dict, op: dict, holes, radius: float = 0.0) -> list[tuple]:
    """(x, y, top, bottom) in WCS for each hole the Drill op will make (kernel.find_holes gives
    `holes`). Milling: holes opening upward (+Z), Ø = op hole_dia (0 = every size), nearest first.
    Turning: the hole on the spindle axis opening at the front (x = y = 0). Bottom = full-Ø
    depth; through holes go the breakthrough plus the drill's point further."""
    w = wcs(bbox, setup, radius)
    o = w["origin"]
    want = op.get("hole_dia", 0.0)
    picked = op.get("picked") or []
    out = []
    for h in holes:
        if picked:                                               # just the holes clicked in the view
            if not any(math.dist(h["p"], q) < 1e-4 for q in picked):
                continue
        elif want and abs(h["dia"] - want) > 1e-4:
            continue
        extra = op["breakthrough"] + op["tool_dia"] * DRILL_TIP if h["through"] else 0.0
        if setup["type"] == MILLING:
            if h["axis"][2] < 1 - 1e-6:
                continue
            x, y, top = (h["p"][k] - o[k] for k in range(3))
            out.append((x, y, top, top - h["depth"] - extra))
        else:
            i, center, _ = turning_frame(bbox, setup)
            sign = 1.0 if setup["front"] == "+" else -1.0
            off = [h["p"][k] - center[k] for k in range(3) if k != i]
            if h["axis"][i] * sign < 1 - 1e-6 or math.hypot(*off) > 1e-4:
                continue
            top = (h["p"][i] - o[i]) * sign
            out.append((0.0, 0.0, top, top - h["depth"] - extra))
    if setup["type"] == TURNING:
        out = sorted(out, key=lambda t: -t[2])[:1]               # the one that opens at the front
        if not out and (op.get("end_at") is not None or op.get("depth", 0) > 0):
            f = axial_to_wcs(bbox, setup, turning_frame(bbox, setup)[2][1], radius)
            out = [(0.0, 0.0, f, f)]                             # no hole modelled: from the front face
    out = [(x, y) + _drill_span(bbox, setup, op, top, bottom, radius) for x, y, top, bottom in out]
    if setup["type"] == TURNING:
        return out
    order, at = [], (0.0, 0.0)
    while out:                                                   # nearest hole next
        k = min(range(len(out)), key=lambda j: math.dist(at, out[j][:2]))
        order.append(out.pop(k))
        at = order[-1][:2]
    return order


def _drill_span(bbox, setup, op, top, bottom, radius):
    """(top, bottom) of a hole after the op's own Start / End (turning picks), Depth (drill point
    this far below the start; 0 = the model's hole) and Extend start / end."""
    if op.get("start_at") is not None:
        top = axial_to_wcs(bbox, setup, op["start_at"], radius)
    if op.get("end_at") is not None:
        bottom = axial_to_wcs(bbox, setup, op["end_at"], radius)
    elif op.get("depth", 0) > 0:
        bottom = top - op["depth"]
    top, bottom = top + op.get("start_ext", 0.0), bottom - op.get("past_back", 0.0)
    if bottom >= top - 1e-9:
        raise ValueError("the drill End must be deeper than its Start")
    return top, bottom


def _pecks(pt, R, bottom, op):
    """Moves from the R plane to the bottom and back to R, as the control runs the cycle."""
    moves, cur = [], R
    q = op["peck"] if op["cycle"] != "drill" else R - bottom
    while cur > bottom + 1e-9:
        nxt = max(cur - q, bottom)
        moves.append(("feed", pt(nxt)))
        if nxt > bottom + 1e-9:
            if op["cycle"] == "peck":                           # G83: all the way out, back down
                moves += [("rapid", pt(R)), ("rapid", pt(nxt + PECK_GAP))]
            else:                                               # G73: a short pull to break the chip
                moves.append(("rapid", pt(nxt + PECK_GAP)))
        cur = nxt
    return moves + [("rapid", pt(R))]


def drill_toolpath(bbox, setup: dict, op: dict, holes, radius: float = 0.0) -> list[tuple]:
    """Drill: every target hole from `op["retract"]` above its top down to its bottom (G81 / G83 /
    G73 moves spelled out for the preview and Simulate). Milling returns to the clearance height
    between holes (G98). Turning: on center from the face, X = 0."""
    op = validate_op(setup, op)
    targets = drill_targets(bbox, setup, op, holes, radius)
    if not targets:
        raise ValueError("no hole to drill" + (" of that size" if op.get("hole_dia") else "") +
                         (" · model the hole in CAD (a round hole opening up +Z)" if setup["type"] == MILLING else
                          " · model a hole down the spindle axis, or give a Depth or pick an End"))
    if setup["type"] == MILLING:
        lo, hi = stock_box(bbox, setup)
        safe = hi[2] - wcs(bbox, setup)["origin"][2] + op["clearance"]
        moves = []
        for x, y, top, bottom in targets:
            def pt(z, x=x, y=y):
                return (x, y, z)
            R = top + op["retract"]
            moves += [("rapid", pt(safe)), ("rapid", pt(R))] + _pecks(pt, R, bottom, op) + [("rapid", pt(safe))]
        return moves
    c = stock_cylinder(bbox, radius, setup)
    w = wcs(bbox, setup, radius)
    i = AXES[setup["axis"]]
    sign = 1.0 if setup["front"] == "+" else -1.0
    z_start = (c["front"][i] - w["origin"][i]) * sign + op["clearance"]
    x_out = c["r"] + op["clearance"]
    _x, _y, top, bottom = targets[0]
    R = top + op["retract"]
    z_start = max(z_start, R)                                    # a Start picked off the part

    def pt(z):
        return (0.0, 0.0, z)
    return ([("rapid", (x_out, 0.0, z_start)), ("rapid", pt(z_start)), ("rapid", pt(R))] + _pecks(pt, R, bottom, op)
            + [("rapid", pt(z_start)), ("rapid", (x_out, 0.0, z_start))])


def toolpath(bbox, setup: dict, op: dict, radius: float = 0.0, loops=None, profile=None, holes=None) -> list[tuple]:
    """Moves for any operation (face, contour, OD rough), in the setup's WCS - turned about Z when
    the setup's X points another way (the path generators work in model-aligned axes)."""
    if op.get("type") == "drill":
        moves = drill_toolpath(bbox, setup, op, holes or [], radius)
        if setup["type"] == MILLING and setup.get("x_dir", "+x") != "+x":
            cx, cy = X_DIRS[setup["x_dir"]][1]
            moves = [(k, (x * cx + y * cy, -x * cy + y * cx, z)) for k, (x, y, z) in moves]
        return moves
    if op.get("type") == "groove":
        return groove_toolpath(bbox, setup, op, profile or [], radius)
    if op.get("type") == "rough" and setup["type"] == MILLING:
        moves = mill_rough_toolpath(bbox, setup, op, loops or [])
        if setup.get("x_dir", "+x") != "+x":
            cx, cy = X_DIRS[setup["x_dir"]][1]
            moves = [(k, (x * cx + y * cy, -x * cy + y * cx, z)) for k, (x, y, z) in moves]
        return moves
    if op.get("type") == "rough":
        return rough_toolpath(bbox, setup, op, profile or [], radius)
    if op.get("type") == "finish":
        return finish_toolpath(bbox, setup, op, profile or [], radius)
    if op.get("type", "face") == "contour":
        moves = contour_toolpath(bbox, setup, op, loops)
    else:
        moves = face_toolpath(bbox, setup, op, radius)
    if setup["type"] == MILLING and setup.get("x_dir", "+x") != "+x":
        cx, cy = X_DIRS[setup["x_dir"]][1]
        moves = [(k, (x * cx + y * cy, -x * cy + y * cx, z)) for k, (x, y, z) in moves]
    return moves


def toolpath_world(bbox, setup: dict, moves, radius: float = 0.0) -> list[tuple]:
    """The same moves in model coordinates (for drawing)."""
    w = wcs(bbox, setup, radius)
    o, x, z = w["origin"], w["x"], w["z"]
    y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
    return [(kind, tuple(o[k] + p[0] * x[k] + p[1] * y[k] + p[2] * z[k] for k in range(3))) for kind, p in moves]


RAPID_IPM = 400.0          # assumed rapid rate for simulation timing (machines vary: 400-1400)


def move_times(moves, setup: dict, op: dict, rapid_ipm: float = RAPID_IPM) -> list[float]:
    """Minutes each move takes (the first is 0): feeds at the op's feed (plunges at its plunge
    feed; turning at constant surface speed, RPM capped), rapids at rapid_ipm. For Simulate."""
    out, prev = [], None
    for kind, p in moves:
        if prev is None:
            out.append(0.0)
        elif kind == "rapid":
            out.append(math.dist(prev, p) / rapid_ipm)
        else:
            out.append(cycle_time([("feed", prev), ("feed", p)], setup, op))
        prev = p
    return out


def cycle_time(moves, setup: dict, op: dict) -> float:
    """Rough cutting time in minutes (feed moves only; rapids assumed quick)."""
    t, prev = 0.0, None
    for kind, p in moves:
        if prev is not None and kind == "feed":
            d = math.dist(prev, p)
            if setup["type"] == MILLING:
                z_only = abs(prev[0] - p[0]) < 1e-9 and abs(prev[1] - p[1]) < 1e-9
                t += d / (op.get("plunge", op["feed"]) if z_only else op["feed"])
            elif op.get("type") == "drill":           # lathe drill: fixed RPM (G97), in/rev
                t += d / (op["ipr"] * op["rpm"])
            else:                                   # constant surface speed, capped RPM
                r_mid = max((abs(prev[0]) + abs(p[0])) / 2, 1e-3)
                rpm = min(op["sfm"] * 12 / (2 * math.pi * r_mid), op["max_rpm"])
                t += d / (op["ipr"] * rpm)
        prev = p
    return t


def describe_op(setup: dict, op: dict) -> str:
    if op.get("type") == "drill":
        size = f"Ø{op['hole_dia']:.4f} holes" if op.get("hole_dia") else "all holes"
        return f"Drill · Ø{op['tool_dia']:.4f} · {DRILL_CYCLES[op['cycle']]} · {size}"
    if op.get("type") == "groove":
        return (f"{GROOVE_SIDES[op['side']]} Groove · {op['tool_dia']:.4f} wide · {op['stepover']:.0f}% step · "
                f"{op['sfm']:.0f} SFM · {op['ipr']:.4f} IPR")
    if op.get("type") == "finish":
        return (("ID " if op.get("internal") else "") + f"Contour · leave X {op['leave_x']:.3f} Z {op['leave_z']:.3f} · {op['sfm']:.0f} SFM · "
                f"{op['ipr']:.4f} IPR" + (" · G70 cycle" if op.get("output") == "cycle" else ""))
    if op.get("type") == "rough" and setup["type"] == MILLING:
        return (f"Roughing · Ø{op['tool_dia']:.3f} tool · {op['stepover']:.0f}% stepover · {op['stepdown']:.3f} DOC · "
                f"{len(op.get('islands') or [])} picked · " + ("boundary" if op.get("boundary") else "whole stock"))
    if op.get("type") == "rough":
        return (("ID " if op.get("internal") else "") + f"Roughing · {op['stepdown']:.3f} DOC · leave X {op['leave_x']:.3f} Z {op['leave_z']:.3f} · "
                f"{op['sfm']:.0f} SFM · {op['ipr']:.4f} IPR" + (" · G71 cycle" if op.get("output") == "cycle" else ""))
    if op.get("type") == "contour":
        return (f"2D Contour · Ø{op['tool_dia']:.3f} tool · {op['direction']} · {op['stepdown']:.3f} DOC · "
                f"leave {op['leave']:.3f}")
    if setup["type"] == MILLING:
        return f"Face · Ø{op['tool_dia']:.3f} tool · {op['stepover']:.0f}% stepover · {op['stepdown']:.3f} DOC"
    return (f"Face · {op['stepdown']:.3f} per pass · {op['sfm']:.0f} SFM · {op['ipr']:.4f} IPR"
            + (" · G72 cycle" if op.get("output") == "cycle" else ""))


def stock_snap_points(bbox, setup: dict) -> list[tuple]:
    """Milling stock box snap points for picking the WCS: [((x, y, z), kind)] with kind
    'stock corner' | 'stock edge mid' | 'stock face center'."""
    lo, hi = stock_box(bbox, setup)
    mid = [(a + b) / 2 for a, b in zip(lo, hi)]
    xs, ys, zs = (lo[0], mid[0], hi[0]), (lo[1], mid[1], hi[1]), (lo[2], mid[2], hi[2])
    out = []
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            for k, z in enumerate(zs):
                n_mid = (i == 1) + (j == 1) + (k == 1)   # 0 corner, 1 edge middle, 2 face center, 3 inside
                if n_mid < 3:
                    out.append(((x, y, z), ("stock corner", "stock edge mid", "stock face center")[n_mid]))
    return out
