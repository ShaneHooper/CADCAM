"""Sketch entities as plain data (the same shapes the HTML prototype uses).

    {"type": "line",    "pts": [[x, y], [x, y]]}
    {"type": "circle",  "c": [x, y], "r": R}
    {"type": "rect",    "pts": [[x, y]] * 4}               closed loop
    {"type": "rect",    "pts": [...], "corner_r": R}        optional rounded corners
    {"type": "polygon", "pts": [[x, y]] * n, "r": R}       closed loop
    {"type": "point",   "p": [x, y]}                        reference point (no profile)
    {"type": "arc",     "c": [x, y], "r": R, "a0": deg, "a1": deg, "pts": [start, end]}
                        counter-clockwise a0 -> a1; made by Fillet, chains with lines

A rect drawn with Center Rect carries "anchor": "center" so its X/Y are its center.

All values are inches. Entities are dicts on purpose: they round-trip through JSON
unchanged and match the prototype's `FEATURES[i].ents`.
"""
from __future__ import annotations

import math

Point = list  # [x, y]


def line(a, b):
    return {"type": "line", "pts": [list(a), list(b)]}


def circle(c, r):
    return {"type": "circle", "c": list(c), "r": float(r)}


def arc(c, r, a0, a1, pts=None):
    """Counter-clockwise arc a0 -> a1 (degrees). `pts` pins the end points exactly (so they
    meet the lines they join without float drift)."""
    a0, a1 = float(a0), float(a1)
    while a1 <= a0:
        a1 += 360.0
    while a1 - a0 > 360.0:
        a1 -= 360.0
    ends = pts or [_on(c, r, a0), _on(c, r, a1)]
    return {"type": "arc", "c": list(c), "r": float(r), "a0": a0, "a1": a1, "pts": [list(q) for q in ends]}


def _on(c, r, deg):
    a = math.radians(deg)
    return [c[0] + r * math.cos(a), c[1] + r * math.sin(a)]


def arc_mid(e):
    return _on(e["c"], e["r"], (e["a0"] + e["a1"]) / 2)


def point(p):
    return {"type": "point", "p": list(p)}


def rect(a, b, corner_r=0.0):
    """Rectangle from two opposite corners."""
    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    e = {"type": "rect", "pts": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}
    if corner_r:
        e["corner_r"] = float(corner_r)
    return e


def center_rect(c, corner):
    dx, dy = abs(corner[0] - c[0]), abs(corner[1] - c[1])
    e = rect((c[0] - dx, c[1] - dy), (c[0] + dx, c[1] + dy))
    e["anchor"] = "center"
    return e


def polygon(c, vertex, sides):
    r = math.hypot(vertex[0] - c[0], vertex[1] - c[1])
    a0 = math.atan2(vertex[1] - c[1], vertex[0] - c[0])
    pts = [[c[0] + r * math.cos(a0 + i / sides * 2 * math.pi), c[1] + r * math.sin(a0 + i / sides * 2 * math.pi)]
           for i in range(sides)]
    return {"type": "polygon", "pts": pts, "r": r}


def build_entity(tool: str, a, b, sides: int = 6):
    """Entity for a two-click sketch tool (the prototype's buildEntity). None if degenerate."""
    if tool == "point":
        return point(a)
    if tool == "line":
        return None if a == b else line(a, b)
    if tool == "rect":
        return None if a[0] == b[0] or a[1] == b[1] else rect(a, b)
    if tool == "center_rect":
        return None if a[0] == b[0] or a[1] == b[1] else center_rect(a, b)
    r = math.hypot(b[0] - a[0], b[1] - a[1])
    if r == 0:
        return None
    if tool == "circle":
        return circle(a, r)
    if tool == "polygon":
        return polygon(a, b, sides)
    raise ValueError(f"unknown sketch tool {tool!r}")


def circle_points(c, r, n=64):
    return [[c[0] + r * math.cos(i / n * 2 * math.pi), c[1] + r * math.sin(i / n * 2 * math.pi)] for i in range(n)]


def rounded_rect_points(pts, cr, n=8):
    x0, y0 = pts[0]
    x1, y1 = pts[2]
    cr = min(cr, (x1 - x0) / 2, (y1 - y0) / 2)
    out = []
    for cx, cy, a0 in ((x1 - cr, y0 + cr, -90), (x1 - cr, y1 - cr, 0), (x0 + cr, y1 - cr, 90), (x0 + cr, y0 + cr, 180)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            out.append([cx + cr * math.cos(a), cy + cr * math.sin(a)])
    return out


POINT_MARK = 0.03


def entity_points(e, closed=True):
    """Polyline for drawing. Closed shapes repeat their first point when `closed`."""
    t = e["type"]
    if t == "point":                    # small diamond marker
        (x, y), d = e["p"], POINT_MARK
        return [[x + d, y], [x, y + d], [x - d, y], [x, y - d], [x + d, y]]
    if t == "line":
        return [list(p) for p in e["pts"]]
    if t == "arc":
        n = max(4, math.ceil((e["a1"] - e["a0"]) / 6))
        pts = [_on(e["c"], e["r"], e["a0"] + (e["a1"] - e["a0"]) * i / n) for i in range(n + 1)]
        pts[0], pts[-1] = list(e["pts"][0]), list(e["pts"][1])
        return pts
    if t == "circle":
        pts = circle_points(e["c"], e["r"])
    elif t == "rect" and e.get("corner_r"):
        pts = rounded_rect_points(e["pts"], e["corner_r"])
    else:
        pts = [list(p) for p in e["pts"]]
    return pts + [pts[0]] if closed else pts


def fmt(v: float) -> str:
    return f"{0.0 if abs(v) < 1e-9 else v:.4f}"


def entity_label(e):
    """(kind, detail) for the Sketch Palette list."""
    t = e["type"]
    if t == "point":
        return "Point", f"{fmt(e['p'][0])}, {fmt(e['p'][1])}"
    if t == "line":
        (x0, y0), (x1, y1) = e["pts"]
        if e.get("corner"):
            return "Chamfer", f"{fmt(abs(x1 - x0))} × {fmt(abs(y1 - y0))}"
        return "Line", "L " + fmt(math.hypot(x1 - x0, y1 - y0))
    if t == "circle":
        return "Circle", "Ø " + fmt(e["r"] * 2)
    if t == "arc":
        return ("Fillet" if e.get("corner") else "Arc"), "R " + fmt(e["r"])
    if t == "rect":
        p = e["pts"]
        return "Rect", f"{fmt(abs(p[2][0] - p[0][0]))} × {fmt(abs(p[2][1] - p[0][1]))}"
    return "Polygon", f"{len(e['pts'])} sides · R {fmt(e['r'])}"


def preview_label(tool, a, b, sides=6):
    """Live dimension text that follows the cursor."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if tool == "line":
        return f"L {fmt(L)}  ∠ {math.degrees(math.atan2(dy, dx)):.1f}°  ΔX {fmt(dx)} ΔY {fmt(dy)}"
    if tool == "rect":
        return f"{fmt(abs(dx))} × {fmt(abs(dy))}"
    if tool == "center_rect":
        return f"{fmt(abs(dx) * 2)} × {fmt(abs(dy) * 2)}"
    if tool == "circle":
        return f"Ø {fmt(L * 2)}  R {fmt(L)}"
    if tool == "polygon":
        return f"{sides} sides  R {fmt(L)}"
    return ""


def snap(v: float, step: float) -> float:
    return round(v / step) * step if step else v


# ---------------------------------------------------------------- exact values
# Every entity is described by a few numbers measured from the sketch origin (0, 0).
# params() reads them, set_param() rebuilds the entity with one of them changed.
LABELS = {"x": "X", "y": "Y", "x2": "End X", "y2": "End Y", "len": "Length", "ang": "Angle °",
          "dia": "Diameter", "w": "Width", "h": "Height", "cr": "Corner R", "r": "Radius", "sides": "Sides",
          "ch": "Horizontal", "cv": "Vertical"}


def _center(pts):
    return [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]


def params(e) -> dict:
    """Editable values of an entity, in panel order. Positions are from the origin."""
    t = e["type"]
    if t == "point":
        return {"x": e["p"][0], "y": e["p"][1]}
    if t == "line" and e.get("corner"):             # chamfer: its horizontal / vertical legs
        (x0, y0), (x1, y1) = e["pts"]
        return {"ch": abs(x1 - x0), "cv": abs(y1 - y0)}
    if t == "line":
        (x0, y0), (x1, y1) = e["pts"]
        return {"x": x0, "y": y0, "x2": x1, "y2": y1, "len": math.hypot(x1 - x0, y1 - y0),
                "ang": math.degrees(math.atan2(y1 - y0, x1 - x0))}
    if t == "circle":
        return {"x": e["c"][0], "y": e["c"][1], "dia": e["r"] * 2}
    if t == "arc" and e.get("corner"):              # fillet: just its radius (the corner places it)
        return {"r": e["r"]}
    if t == "arc":
        return {"x": e["c"][0], "y": e["c"][1], "r": e["r"]}
    if t == "rect":
        (x0, y0), (x1, y1) = e["pts"][0], e["pts"][2]
        w, h = x1 - x0, y1 - y0
        x, y = (x0 + w / 2, y0 + h / 2) if e.get("anchor") == "center" else (x0, y0)
        return {"x": x, "y": y, "w": w, "h": h, "cr": e.get("corner_r", 0.0)}
    c = _center(e["pts"])
    v = e["pts"][0]
    return {"x": c[0], "y": c[1], "r": e["r"], "sides": len(e["pts"]),
            "ang": math.degrees(math.atan2(v[1] - c[1], v[0] - c[0]))}


def set_param(e, key: str, value: float) -> dict:
    """New entity with one value changed. Raises ValueError for a size that can't exist."""
    return _clean(_set_param(e, key, value))


def _clean(v):
    """Round off float noise (6e-17 after a 90° turn) so values read back exactly."""
    if isinstance(v, float):
        return round(v, 10) + 0.0
    if isinstance(v, list):
        return [_clean(x) for x in v]
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    return v


def _set_param(e, key, value):
    if e.get("corner"):
        raise ValueError("A chamfer is changed with edit() (its sides move too)")
    v = params(e)
    v[key] = float(value)
    for k in ("len", "dia", "w", "h", "r"):
        if k in v and v[k] <= 1e-9:
            raise ValueError(f"{LABELS[k]} must be greater than 0")
    t = e["type"]
    if t == "point":
        return point((v["x"], v["y"]))
    if t == "line":
        if key in ("x", "y"):                       # its position: the whole line moves, angle kept
            d = v[key] - params(e)[key]
            v[key + "2"] += d
        if key in ("len", "ang"):
            a = math.radians(v["ang"])
            v["x2"], v["y2"] = v["x"] + v["len"] * math.cos(a), v["y"] + v["len"] * math.sin(a)
        if (v["x"], v["y"]) == (v["x2"], v["y2"]):
            raise ValueError("Line start and end are the same point")
        return line((v["x"], v["y"]), (v["x2"], v["y2"]))
    if t == "circle":
        return circle((v["x"], v["y"]), v["dia"] / 2)
    if t == "arc":
        return arc((v["x"], v["y"]), v["r"], e["a0"], e["a1"])
    if t == "rect":
        if v["cr"] < 0 or v["cr"] > min(v["w"], v["h"]) / 2 + 1e-9:
            raise ValueError("Corner R must be between 0 and half the short side")
        x0, y0 = (v["x"] - v["w"] / 2, v["y"] - v["h"] / 2) if e.get("anchor") == "center" else (v["x"], v["y"])
        out = rect((x0, y0), (x0 + v["w"], y0 + v["h"]), v["cr"])
        if e.get("anchor"):
            out["anchor"] = e["anchor"]
        return out
    n = int(round(v["sides"]))
    if n < 3:
        raise ValueError("A polygon needs at least 3 sides")
    a = math.radians(v["ang"])
    return polygon((v["x"], v["y"]), (v["x"] + v["r"] * math.cos(a), v["y"] + v["r"] * math.sin(a)), n)


def _bbox(e):
    pts = entity_points(e, closed=False)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _dim(a, b, off, text, at=None, key=None):
    """Linear dimension a-b. With `off` the dimension line sits `off` to the left of a->b and
    extension lines run back to a and b. `key` names the params() value the dimension shows,
    so a right-click on it can edit that value."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / L * off, dx / L * off
    a2, b2 = [a[0] + nx, a[1] + ny], [b[0] + nx, b[1] + ny]
    lines = [[a2, b2]] + _ticks(a2, b2)
    if off:
        ex, ey = nx / abs(off) * DIM_TICK, ny / abs(off) * DIM_TICK
        lines += [[a, [a2[0] + ex, a2[1] + ey]], [b, [b2[0] + ex, b2[1] + ey]]]
    return {"lines": lines, "at": at or [(a2[0] + b2[0]) / 2, (a2[1] + b2[1]) / 2], "text": text, "key": key}


DIM_GAP = 0.3     # inches between a shape and its dimension line
DIM_TICK = 0.06


def dimensions(e) -> list[dict]:
    """Dimension graphics for one entity: its X/Y from the origin and its size.

    Each item: {"lines": [polyline...], "at": [x, y], "text": "X 1.2500", "key": "x"}. Pure
    geometry, so the UI only has to draw it. `key` is the params() entry the dimension shows
    (its value is params(e)[key]); set_param(e, key, new) is how a right-click edits it."""
    v = params(e)
    g = DIM_GAP
    if e.get("corner") and e["type"] == "arc":
        return [_dim(e["c"], arc_mid(e), 0, "R " + fmt(e["r"]), key="r")]
    if e.get("corner"):
        return _chamfer_dims(e, g)
    ax, ay = v["x"], v["y"]
    x0, y0, x1, y1 = _bbox(e)
    out = []
    # position from the origin: X measured below everything, Y to the left of everything
    if abs(ax) > 1e-9:
        yb = min(0.0, y0, ay) - g
        d = _dim([0.0, yb], [ax, yb], 0, "X " + fmt(ax), key="x")
        d["lines"] += [[[0.0, 0.0], [0.0, yb - DIM_TICK]], [[ax, ay], [ax, yb - DIM_TICK]]]
        out.append(d)
    if abs(ay) > 1e-9:
        xb = min(0.0, x0, ax) - g
        d = _dim([xb, 0.0], [xb, ay], 0, "Y " + fmt(ay), key="y")
        d["lines"] += [[[0.0, 0.0], [xb - DIM_TICK, 0.0]], [[ax, ay], [xb - DIM_TICK, ay]]]
        out.append(d)
    t = e["type"]
    if t == "rect":
        out.append(_dim([x0, y1], [x1, y1], -g, fmt(v["w"]), key="w"))           # width above
        out.append(_dim([x1, y0], [x1, y1], -g, fmt(v["h"]), key="h"))           # height to the right
    elif t == "circle":
        r = v["dia"] / 2
        out.append(_dim([ax - r, ay], [ax + r, ay], 0, "Ø " + fmt(v["dia"]), [ax, ay + min(r * .35, .15)],
                        key="dia"))
    elif t == "line":
        out.append(_dim(e["pts"][0], e["pts"][1], g, fmt(v["len"]), key="len"))
    elif t == "polygon":
        out.append(_dim([ax, ay], e["pts"][0], 0, "R " + fmt(v["r"]), key="r"))
    elif t == "arc":
        out.append(_dim([ax, ay], arc_mid(e), 0, "R " + fmt(v["r"]), key="r"))
    return out


def _chamfer_dims(e, g):
    """A chamfer: horizontal leg dimensioned past the corner in Y, vertical leg past it in X."""
    (ax, ay), (bx, by) = e["pts"]
    px, py = e["corner"]
    sy = 1 if py >= (ay + by) / 2 else -1
    sx = 1 if px >= (ax + bx) / 2 else -1
    yb, xb = py + sy * g, px + sx * g
    h = _dim([min(ax, bx), yb], [max(ax, bx), yb], 0, fmt(abs(bx - ax)), key="ch")
    h["lines"] += [[[ax, ay], [ax, yb + sy * DIM_TICK]], [[bx, by], [bx, yb + sy * DIM_TICK]]]
    v = _dim([xb, min(ay, by)], [xb, max(ay, by)], 0, fmt(abs(by - ay)), key="cv")
    v["lines"] += [[[ax, ay], [xb + sx * DIM_TICK, ay]], [[bx, by], [xb + sx * DIM_TICK, by]]]
    return [d for d, n in ((h, abs(bx - ax)), (v, abs(by - ay))) if n > 1e-9]


def edit(ents, origin, i: int, key: str, value: float):
    """Change one value of entity i: new (ents, origin, index of the changed entity).
    A fillet's radius or a chamfer's legs move the two sides it cuts, so this works on the whole
    sketch: the corner is put back sharp and cut again, nothing else moves."""
    e = ents[i]
    if not e.get("corner"):
        ents = list(ents)
        ents[i] = set_param(e, key, value)
        return ents, list(origin), i
    v = params(e)
    v[key] = float(value)
    size = v["r"] if e["type"] == "arc" else (v["ch"], v["cv"])
    ents, origin = recorner(ents, origin, i, size)
    return ents, origin, len(ents) - 1


def dimension_at(e, p, tol: float):
    """The dimension of `e` under point p (within tol): the dict from dimensions(), else None.
    A hit is the label position or any line of the dimension - what a right-click aims at."""
    best, hit = tol, None
    for d in dimensions(e):
        dist = math.hypot(p[0] - d["at"][0], p[1] - d["at"][1])
        for ln in d["lines"]:
            for (ax, ay), (bx, by) in zip(ln, ln[1:]):
                dx, dy = bx - ax, by - ay
                L = dx * dx + dy * dy
                t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L)) if L else 0.0
                dist = min(dist, math.hypot(ax + t * dx - p[0], ay + t * dy - p[1]))
        if dist <= best:
            best, hit = dist, d
    return hit


def _ticks(a, b):
    """Arrow heads at both ends of a dimension line a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy) or 1.0
    ux, uy = dx / L * DIM_TICK, dy / L * DIM_TICK
    px, py = -uy * .4, ux * .4
    return [[[a[0] + ux + px, a[1] + uy + py], a, [a[0] + ux - px, a[1] + uy - py]],
            [[b[0] - ux + px, b[1] - uy + py], b, [b[0] - ux - px, b[1] - uy - py]]]


# ---------------------------------------------------------------- snap points
# What the cursor jumps to while drawing: ends, midpoints and centers of what is already
# there. Model edges lying on the sketch plane are added by the UI (kernel.plane_edges).

def snap_points(ents) -> list[tuple]:
    """(u, v, kind) for every snap point of the sketch: 'end', 'mid', 'center', 'quad'
    (a circle's four quadrant points), 'point'. The origin is always there."""
    out = [(0.0, 0.0, "origin")]
    for e in ents:
        t = e["type"]
        if t == "point":
            out.append((e["p"][0], e["p"][1], "point"))
        elif t == "circle":
            (cx, cy), r = e["c"], e["r"]
            out.append((cx, cy, "center"))
            out += [(cx + r, cy, "quad"), (cx - r, cy, "quad"), (cx, cy + r, "quad"), (cx, cy - r, "quad")]
        elif t == "line":
            (x0, y0), (x1, y1) = e["pts"]
            out += [(x0, y0, "end"), (x1, y1, "end"), ((x0 + x1) / 2, (y0 + y1) / 2, "mid")]
        elif t == "arc":
            m = arc_mid(e)
            out += [(*e["pts"][0], "end"), (*e["pts"][1], "end"), (m[0], m[1], "mid"),
                    (e["c"][0], e["c"][1], "center")]
        else:                                   # rect, polygon: every corner, every side's middle, the center
            pts = e["pts"]
            for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
                out += [(x0, y0, "end"), ((x0 + x1) / 2, (y0 + y1) / 2, "mid")]
            c = _center(pts)
            out.append((c[0], c[1], "center"))
    return out


def edge_snap_points(edges) -> list[tuple]:
    """Snap points of model edges on the plane, as kernel.plane_edges gives them:
    [{"pts": [[u, v], ...], "kind": "LINE" | "CIRCLE" | ..., "center": [u, v] | None}]."""
    out = []
    for ed in edges:
        pts = ed["pts"]
        if len(pts) < 2:
            continue
        a, b = pts[0], pts[-1]
        if ed["kind"] == "LINE":
            out += [(a[0], a[1], "end"), (b[0], b[1], "end"), ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, "mid")]
        else:
            closed = math.hypot(a[0] - b[0], a[1] - b[1]) < 1e-9
            if not closed:
                out += [(a[0], a[1], "end"), (b[0], b[1], "end")]
                m = pts[len(pts) // 2]
                out.append((m[0], m[1], "mid"))
            if ed.get("center") is not None:
                out.append((ed["center"][0], ed["center"][1], "center"))
    return out


SNAP_RANK = {"end": 0, "point": 0, "center": 1, "origin": 1, "mid": 2, "quad": 3}


def nearest_snap(points, p, tol: float):
    """The snap point within tol of p: closest wins, an end beats a midpoint at equal distance."""
    best, hit = None, None
    for u, v, kind in points:
        d = math.hypot(u - p[0], v - p[1])
        if d <= tol:
            score = (round(d / max(tol, 1e-12), 3), SNAP_RANK.get(kind, 9))
            if best is None or score < best:
                best, hit = score, (u, v, kind)
    return hit


def distance(e, p) -> float:
    """Distance from point p to an entity's outline (what a click near it measures)."""
    if e["type"] == "point":
        return math.hypot(p[0] - e["p"][0], p[1] - e["p"][1])
    if e["type"] == "circle":
        return abs(math.hypot(p[0] - e["c"][0], p[1] - e["c"][1]) - e["r"])
    pts = entity_points(e)
    best = math.inf
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L)) if L else 0.0
        best = min(best, math.hypot(ax + t * dx - p[0], ay + t * dy - p[1]))
    return best


def nearest(ents, p, tol: float):
    """Index of the entity closest to p within tol, else None. Points win ties (they're small)."""
    best, bi = tol, None
    for i, e in enumerate(ents):
        d = distance(e, p) * (0.5 if e["type"] == "point" else 1.0)
        if d <= best:
            best, bi = d, i
    return bi


# ---------------------------------------------------------------- corner fillet / chamfer
# A corner is where two lines (or a line and a rect/polygon side) meet at a sharp angle.
# Rects and polygons are split into lines first, like Fusion does; `origin` (old index of each
# entity, see ui SketchSession) follows along, so extrudes made from the shape keep working.

def _key(p):
    return (round(p[0], 6), round(p[1], 6))


def explode(e) -> list:
    """A rect / polygon as its sides (a rounded rect as sides + corner arcs)."""
    if e["type"] == "rect" and e.get("corner_r"):
        (x0, y0), (x1, y1), r = e["pts"][0], e["pts"][2], e["corner_r"]
        return [line((x0 + r, y0), (x1 - r, y0)), arc((x1 - r, y0 + r), r, -90, 0, [[x1 - r, y0], [x1, y0 + r]]),
                line((x1, y0 + r), (x1, y1 - r)), arc((x1 - r, y1 - r), r, 0, 90, [[x1, y1 - r], [x1 - r, y1]]),
                line((x1 - r, y1), (x0 + r, y1)), arc((x0 + r, y1 - r), r, 90, 180, [[x0 + r, y1], [x0, y1 - r]]),
                line((x0, y1 - r), (x0, y0 + r)), arc((x0 + r, y0 + r), r, 180, 270, [[x0, y0 + r], [x0 + r, y0]])]
    pts = e["pts"]
    return [line(a, b) for a, b in zip(pts, pts[1:] + pts[:1])]


def corners(ents) -> list[tuple]:
    """[(point, i, j)]: sharp corners. i, j are the two entities meeting there; for a
    rect/polygon corner i == j (the shape itself; it is split into lines when used)."""
    out, ends = [], {}
    for i, e in enumerate(ents):
        if e["type"] == "line":
            for p in e["pts"]:
                ends.setdefault(_key(p), []).append(i)
        elif e["type"] == "polygon" or (e["type"] == "rect" and not e.get("corner_r")):
            out += [(list(p), i, i) for p in e["pts"]]
    for k, lst in ends.items():
        if len(lst) == 2 and lst[0] != lst[1]:
            out.append((list(k), lst[0], lst[1]))
    return out


def nearest_corner(ents, p, tol: float):
    best, hit = tol, None
    for c in corners(ents):
        d = math.hypot(c[0][0] - p[0], c[0][1] - p[1])
        if d <= best:
            best, hit = d, c
    return hit


def corner_op(ents, origin, p, size, kind: str, tol: float):
    """Fillet (kind 'fillet', size = radius) or chamfer ('chamfer', size = distance along each
    side, or (horizontal, vertical) legs) the corner nearest p. Returns new (ents, origin);
    raises ValueError with a message for the user when there is no corner there or the size
    does not fit."""
    hv = size if isinstance(size, (tuple, list)) else None
    if min(hv or [size]) <= 1e-9:
        raise ValueError(f"{kind.capitalize()} size must be greater than 0")
    hit = nearest_corner(ents, p, tol)
    if hit is None:
        raise ValueError("Click on a sharp corner (where two lines meet)")
    ents, origin = [dict(e) for e in ents], list(origin)
    P, i, j = hit
    if i == j:                                    # split the rect / polygon into lines
        parts = explode(ents[i])
        ents[i] = parts[0]
        for q in parts[1:]:
            ents.append(q)
            origin.append(origin[i])
        mine = {i, *range(len(ents) - len(parts) + 1, len(ents))}
        P, i, j = next(c for c in corners(ents) if _key(c[0]) == _key(P) and {c[1], c[2]} <= mine)
    ends = []
    for k in (i, j):
        a, b = ents[k]["pts"]
        at_start = _key(a) == _key(P)
        other = b if at_start else a
        L = math.hypot(other[0] - P[0], other[1] - P[1])
        ends.append((k, at_start, other, [(other[0] - P[0]) / L, (other[1] - P[1]) / L], L))
    (_, _, _, u1, L1), (_, _, _, u2, L2) = ends
    cos_t = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
    theta = math.acos(cos_t)
    if theta < 1e-6 or abs(math.pi - theta) < 1e-6:
        raise ValueError("Those lines are in line with each other: no corner to round")
    if hv:
        ts = _legs(u1, u2, hv)
        if ts[0] > L1 + 1e-9 or ts[1] > L2 + 1e-9:
            raise ValueError(f"Chamfer {fmt(hv[0])} × {fmt(hv[1])} is too big here")
    else:
        t = size / math.tan(theta / 2) if kind == "fillet" else size
        if t > min(L1, L2) + 1e-9:
            biggest = min(L1, L2) * (math.tan(theta / 2) if kind == "fillet" else 1)
            raise ValueError(f"{kind.capitalize()} {fmt(size)} is too big here (max {fmt(biggest)})")
        ts = (t, t)
    T = []
    for (k, at_start, other, u, L), t in zip(ends, ts):
        tp = [P[0] + u[0] * t, P[1] + u[1] * t]
        T.append(tp)
        if abs(L - t) < 1e-9:                     # the side is used up entirely
            ents[k] = None
        else:
            ents[k] = _clean(line(tp, other) if at_start else line(other, tp))
    if kind == "fillet":
        bis = [u1[0] + u2[0], u1[1] + u2[1]]
        bl = math.hypot(*bis)
        d = size / math.sin(theta / 2)
        c = [P[0] + bis[0] / bl * d, P[1] + bis[1] / bl * d]
        a0 = math.degrees(math.atan2(T[0][1] - c[1], T[0][0] - c[0]))
        a1 = math.degrees(math.atan2(T[1][1] - c[1], T[1][0] - c[0]))
        span = (a1 - a0) % 360
        new = arc(c, size, a0, a1, T) if span <= 180 else arc(c, size, a1, a0, [T[1], T[0]])
        new["corner"] = list(P)
    else:
        new = line(T[0], T[1])
        new["corner"] = list(P)               # remembered, so the legs can be changed later
    ents.append(_clean(new))
    origin.append(origin[i])
    keep = [k for k, e in enumerate(ents) if e is not None]
    return [ents[k] for k in keep], [origin[k] for k in keep]


def _legs(u1, u2, hv):
    """Distances along the two sides (unit directions u1, u2 from the corner) that give a bevel
    `hv[0]` wide in X and `hv[1]` tall in Y. On a square corner that is simply h and v."""
    h, v = hv
    det = -u1[0] * u2[1] + u2[0] * u1[1]
    best = None
    for sx in (1, -1):
        for sy in (1, -1):
            dx, dy = sx * h, sy * v                  # u1 t1 - u2 t2 = (dx, dy)
            t1 = (-dx * u2[1] + u2[0] * dy) / det
            t2 = (u1[0] * dy - u1[1] * dx) / det
            if t1 > 1e-9 and t2 > 1e-9 and (best is None or t1 + t2 < sum(best)):
                best = (t1, t2)
    if best is None:
        raise ValueError("That chamfer can't be made on this corner")
    return best


def recorner(ents, origin, i: int, size):
    """Fillet (size = radius) or chamfer (size = (h, v)) i resized: its two sides go back to the
    sharp corner, then it is cut again there. The rest of the sketch stays where it is."""
    c = ents[i]
    P = c["corner"]
    ents, origin = [dict(e) for e in ents], list(origin)
    for X in c["pts"]:
        k = next((k for k, e in enumerate(ents) if k != i and e["type"] == "line"
                  and _key(X) in (_key(e["pts"][0]), _key(e["pts"][1]))), None)
        if k is not None:
            a, b = ents[k]["pts"]
            o = b if _key(a) == _key(X) else a      # the side's far end: must be in line with P
            if abs((X[0] - o[0]) * (P[1] - o[1]) - (X[1] - o[1]) * (P[0] - o[0])) < 1e-7:
                ents[k] = line(P, o) if _key(a) == _key(X) else line(o, P)
                continue
        ents.append(line(X, P))                     # that side had been used up: bring it back
        origin.append(origin[i])
    del ents[i]
    del origin[i]
    return corner_op(ents, origin, P, size, "fillet" if c["type"] == "arc" else "chamfer", 1e-6)


# ---------------------------------------------------------------- trim
# Click a piece of a line / arc / circle: the stretch between the nearest crossings on either side
# of the click is removed (a piece with nothing crossing it goes entirely). Rects and polygons
# are split into lines first, like Fillet does.

def _prims(e):
    """An entity's outline as ('seg', a, b) / ('arc', c, r, a0, a1) pieces (circle: 0..360)."""
    t = e["type"]
    if t == "line":
        return [("seg", e["pts"][0], e["pts"][1])]
    if t == "circle":
        return [("arc", e["c"], e["r"], 0.0, 360.0)]
    if t == "arc":
        return [("arc", e["c"], e["r"], e["a0"], e["a1"])]
    if t in ("rect", "polygon"):
        return [q for s in explode(e) for q in _prims(s)]
    return []


def _ang(c, p):
    return math.degrees(math.atan2(p[1] - c[1], p[0] - c[0]))


def _on_arc(q, p, eps=1e-7):
    _, c, r, a0, a1 = q
    if a1 - a0 >= 360 - 1e-9:
        return True
    d = (_ang(c, p) - a0) % 360
    return d <= a1 - a0 + eps or d >= 360 - eps


def _hits(q1, q2):
    """Points where two pieces cross."""
    eps = 1e-9
    if q1[0] == "arc" and q2[0] == "seg":
        q1, q2 = q2, q1
    out = []
    if q1[0] == "seg" and q2[0] == "seg":
        (ax, ay), (bx, by), (cx, cy), (dx, dy) = q1[1], q1[2], q2[1], q2[2]
        rx, ry, sx, sy = bx - ax, by - ay, dx - cx, dy - cy
        den = rx * sy - ry * sx
        if abs(den) < 1e-12:
            return []                                 # parallel / in line: no single crossing
        t = ((cx - ax) * sy - (cy - ay) * sx) / den
        u = ((cx - ax) * ry - (cy - ay) * rx) / den
        if -eps <= t <= 1 + eps and -eps <= u <= 1 + eps:
            out.append([ax + t * rx, ay + t * ry])
        return out
    if q1[0] == "seg":                                # segment x arc
        (ax, ay), (bx, by), (_, c, r, _a0, _a1) = q1[1], q1[2], q2
        dx, dy = bx - ax, by - ay
        fx, fy = ax - c[0], ay - c[1]
        A, B, C = dx * dx + dy * dy, 2 * (fx * dx + fy * dy), fx * fx + fy * fy - r * r
        disc = B * B - 4 * A * C
        if A < 1e-18 or disc < -1e-12:
            return []
        disc = math.sqrt(max(disc, 0.0))
        for t in {(-B - disc) / (2 * A), (-B + disc) / (2 * A)}:
            p = [ax + t * dx, ay + t * dy]
            if -eps <= t <= 1 + eps and _on_arc(q2, p):
                out.append(p)
        return out
    (_, c1, r1, *_), (_, c2, r2, *_) = q1, q2         # arc x arc
    d = math.hypot(c2[0] - c1[0], c2[1] - c1[1])
    if d < 1e-12 or d > r1 + r2 + 1e-9 or d < abs(r1 - r2) - 1e-9:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(r1 * r1 - a * a, 0.0))
    mx, my = c1[0] + a * (c2[0] - c1[0]) / d, c1[1] + a * (c2[1] - c1[1]) / d
    for s in ((1, -1) if h > 1e-12 else (1,)):
        p = [mx + s * h * (c2[1] - c1[1]) / d, my - s * h * (c2[0] - c1[0]) / d]
        if _on_arc(q1, p) and _on_arc(q2, p):
            out.append(p)
    return out


def _param(e, p):
    """Where p sits along entity e: 0..1 on a line, degrees past a0 on an arc / circle."""
    if e["type"] == "line":
        (ax, ay), (bx, by) = e["pts"]
        L = (bx - ax) ** 2 + (by - ay) ** 2
        return ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / L if L else 0.0
    return (_ang(e["c"], p) - e.get("a0", 0.0)) % 360


def _piece(e, lo, hi):
    """The part of line / arc e between params lo and hi (a circle: arc lo -> hi, degrees)."""
    if e["type"] == "line":
        (ax, ay), (bx, by) = e["pts"]
        return _clean(line([ax + lo * (bx - ax), ay + lo * (by - ay)], [ax + hi * (bx - ax), ay + hi * (by - ay)]))
    a0 = e.get("a0", 0.0)
    return _clean(arc(e["c"], e["r"], a0 + lo, a0 + hi))


def _trim_span(ents, i, p):
    """(lo, hi, end) of the stretch of entity i around p to remove; end = the param range."""
    e = ents[i]
    end = 1.0 if e["type"] == "line" else (360.0 if e["type"] == "circle" else e["a1"] - e["a0"])
    cuts = set()
    for j, o in enumerate(ents):
        if j == i:
            continue
        for q1 in _prims(e):
            for q2 in _prims(o):
                for h in _hits(q1, q2):
                    t = _param(e, h)
                    if e["type"] == "circle" or 1e-7 < t < end - 1e-7:
                        cuts.add(round(t, 9))
    t = _param(e, p)
    cuts = sorted(cuts)
    if e["type"] == "circle":
        if len(cuts) < 2:
            return None, None, end                    # nothing (or one thing) crossing: all of it
        lo = max((c for c in cuts if c <= t), default=cuts[-1] - 360)
        hi = min((c for c in cuts if c > t), default=cuts[0] + 360)
        return lo, hi, end
    lo = max((c for c in cuts if c <= t), default=0.0)
    hi = min((c for c in cuts if c > t), default=end)
    return lo, hi, end


def trim_preview(ents, p, tol: float):
    """The piece a Trim click at p would remove (an entity to draw), else None."""
    i = nearest(ents, p, tol)
    if i is None:
        return None
    if ents[i]["type"] in ("rect", "polygon"):
        parts = explode(ents[i])
        k = nearest(parts, p, tol)
        rest = ents[:i] + ents[i + 1:] + parts[:k] + parts[k + 1:]
        return trim_preview(rest + [parts[k]], p, tol) if k is not None else None
    e = ents[i]
    if e["type"] == "point":
        return e
    lo, hi, end = _trim_span(ents, i, p)
    if lo is None:
        return e
    return _piece(e, lo, hi)


def trim(ents, origin, p, tol: float):
    """Trim at p: returns new (ents, origin). Raises ValueError when nothing is under p."""
    i = nearest(ents, p, tol)
    if i is None:
        raise ValueError("Click on the piece of a line, arc or circle to trim")
    ents, origin = [dict(e) for e in ents], list(origin)
    if ents[i]["type"] in ("rect", "polygon"):        # split into sides, then trim the one clicked
        parts = explode(ents[i])
        ents[i] = parts[0]
        for q in parts[1:]:
            ents.append(q)
            origin.append(origin[i])
        i = nearest(ents, p, tol)
    e = ents[i]
    keep = []
    if e["type"] != "point":
        lo, hi, end = _trim_span(ents, i, p)
        if lo is not None:
            if e["type"] == "circle":
                keep = [_piece(e, hi, lo + 360)]
            else:
                keep = ([_piece(e, 0.0, lo)] if lo > 1e-9 else []) + \
                       ([_piece(e, hi, end)] if hi < end - 1e-9 else [])
    o = origin[i]
    del ents[i], origin[i]
    for k in keep:
        ents.append(k)
        origin.append(o)
    return ents, origin
