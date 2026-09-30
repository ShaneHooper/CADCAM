"""CAM setups as plain data, plus the stock and WCS math (stdlib only, like the rest of core).

A setup is what Fusion calls a Setup: which kind of machine (milling or turning), which
body, the stock around it and where the work zero (WCS) sits. It lives in
Document.setups (saved in the .gcad file), not in the design timeline.

    {"id": "setup1", "name": "Setup1", "type": "milling", "body": "all" | body id,
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
FACE_TURN = {"type": "face", "tool": 1, "stepdown": 0.02, "leave": 0.0, "past_center": 0.02, "sfm": 600.0,
             "ipr": 0.008, "max_rpm": 3000.0, "clearance": 0.1, "output": "lines"}
TURN_OUTPUT = {"lines": "Single lines (G01)", "cycle": "Canned cycle (G94)"}
CONTOUR_MILL = {"type": "contour", "tool": 2, "tool_dia": 0.5, "stepdown": 0.25, "leave": 0.0,
                "bottom_offset": 0.0, "direction": "climb", "rpm": 5000.0, "feed": 30.0, "plunge": 10.0,
                "lead": 0.1, "clearance": 0.5}
OP_TYPES = {"face": "Face", "contour": "Contour"}


def new_op(setup: dict, kind: str = "face") -> dict:
    if kind == "face":
        return copy.deepcopy(FACE_MILL if setup["type"] == MILLING else FACE_TURN)
    if kind == "contour":
        if setup["type"] != MILLING:
            raise ValueError("2D Contour needs a Milling setup")
        return copy.deepcopy(CONTOUR_MILL)
    raise ValueError(f"operation {kind!r} is not built yet")


def validate_op(setup: dict, op: dict) -> dict:
    op = {**new_op(setup, op.get("type", "face")), **copy.deepcopy(op)}
    for k, v in list(op.items()):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            op[k] = float(v)
    for k in ("tool_dia", "stepdown", "rpm", "feed", "sfm", "ipr", "max_rpm", "plunge"):
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
    if op.get("output", "lines") not in TURN_OUTPUT:
        raise ValueError("output must be lines or cycle")
    if op["type"] == "contour" and op["direction"] not in ("climb", "conventional"):
        raise ValueError("direction must be climb or conventional")
    for k in ("leave", "past_center", "clearance", "lead"):
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
    if op.get("output") == "cycle":               # G94: Z in rapid, face in X, feed back out in Z
        for z in levels:
            moves += [("rapid", (x_out, 0.0, z)), ("feed", (x_end, 0.0, z)), ("feed", (x_end, 0.0, z_start)),
                      ("rapid", (x_out, 0.0, z_start))]
        return moves
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
    top, bottom = hi[2] - o[2], bbox[0][2] - o[2] - op["bottom_offset"]
    levels = _levels(top, bottom, op["stepdown"])
    safe = top + op["clearance"]
    moves = []
    for loop in loops:
        pts = [(x - o[0], y - o[1]) for x, y in loop]
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])) / 2
        if (area > 0) == (op["direction"] == "climb"):
            pts.reverse()                       # climb: clockwise; conventional: counter-clockwise
        cw = op["direction"] == "climb"
        k = max(range(len(pts)), key=lambda i: math.dist(pts[i], pts[(i + 1) % len(pts)]))
        a, b = pts[k], pts[(k + 1) % len(pts)]
        start = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        ring = [start] + pts[k + 1:] + pts[:k + 1] + [start]
        d = math.dist(a, b) or 1.0
        dx, dy = (b[0] - a[0]) / d, (b[1] - a[1]) / d
        nx, ny = (-dy, dx) if cw else (dy, -dx)            # outward, away from the part
        lead = (start[0] + nx * op["lead"], start[1] + ny * op["lead"])
        moves.append(("rapid", (lead[0], lead[1], safe)))
        moves.append(("rapid", (lead[0], lead[1], top + 0.1)))
        for z in levels:
            moves.append(("feed", (lead[0], lead[1], z)))    # plunge off the part
            moves += [("feed", (x, y, z)) for x, y in ring]
            moves.append(("feed", (lead[0], lead[1], z)))
        moves.append(("rapid", (lead[0], lead[1], safe)))
    return moves


def toolpath(bbox, setup: dict, op: dict, radius: float = 0.0, loops=None) -> list[tuple]:
    """Moves for any operation (face or contour), in the setup's WCS - turned about Z when the
    setup's X points another way (the path generators work in model-aligned axes)."""
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
            else:                                   # constant surface speed, capped RPM
                r_mid = max((abs(prev[0]) + abs(p[0])) / 2, 1e-3)
                rpm = min(op["sfm"] * 12 / (2 * math.pi * r_mid), op["max_rpm"])
                t += d / (op["ipr"] * rpm)
        prev = p
    return t


def describe_op(setup: dict, op: dict) -> str:
    if op.get("type") == "contour":
        return (f"2D Contour · Ø{op['tool_dia']:.3f} tool · {op['direction']} · {op['stepdown']:.3f} DOC · "
                f"leave {op['leave']:.3f}")
    if setup["type"] == MILLING:
        return f"Face · Ø{op['tool_dia']:.3f} tool · {op['stepover']:.0f}% stepover · {op['stepdown']:.3f} DOC"
    return (f"Face · {op['stepdown']:.3f} per pass · {op['sfm']:.0f} SFM · {op['ipr']:.4f} IPR"
            + (" · G94 cycle" if op.get("output") == "cycle" else ""))


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
