"""Sketch entities as plain data (the same shapes the HTML prototype uses).

    {"type": "line",    "pts": [[x, y], [x, y]]}
    {"type": "circle",  "c": [x, y], "r": R}
    {"type": "rect",    "pts": [[x, y]] * 4}               closed loop
    {"type": "rect",    "pts": [...], "corner_r": R}        optional rounded corners
    {"type": "polygon", "pts": [[x, y]] * n, "r": R}       closed loop

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
    return rect((c[0] - dx, c[1] - dy), (c[0] + dx, c[1] + dy))


def polygon(c, vertex, sides):
    r = math.hypot(vertex[0] - c[0], vertex[1] - c[1])
    a0 = math.atan2(vertex[1] - c[1], vertex[0] - c[0])
    pts = [[c[0] + r * math.cos(a0 + i / sides * 2 * math.pi), c[1] + r * math.sin(a0 + i / sides * 2 * math.pi)]
           for i in range(sides)]
    return {"type": "polygon", "pts": pts, "r": r}


def build_entity(tool: str, a, b, sides: int = 6):
    """Entity for a two-click sketch tool (the prototype's buildEntity). None if degenerate."""
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


def entity_points(e, closed=True):
    """Polyline for drawing. Closed shapes repeat their first point when `closed`."""
    t = e["type"]
    if t == "line":
        return [list(p) for p in e["pts"]]
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
    if t == "line":
        (x0, y0), (x1, y1) = e["pts"]
        return "Line", "L " + fmt(math.hypot(x1 - x0, y1 - y0))
    if t == "circle":
        return "Circle", "Ø " + fmt(e["r"] * 2)
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
