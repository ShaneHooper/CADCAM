"""Closed-profile detection for extrude (ported from the HTML prototype).

A *loop* is a closed shape found in a sketch: a rect, polygon, circle, or a chain of
lines that closes on itself. A loop sitting inside another loop becomes a hole of it,
so every pickable *region* is an outer loop minus the loops directly inside it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .sketch import circle_points, rounded_rect_points


@dataclass
class Loop:
    ents: list            # entity indices that make up the loop
    pts: list             # sampled polygon, for containment tests and picking
    area: float = 0.0
    circle: dict | None = None   # the circle entity, when the loop is one circle
    rect: dict | None = None     # the rect entity (may carry corner_r)


@dataclass
class Region:
    sketch: str           # feature id of the sketch
    outer: Loop
    holes: list = field(default_factory=list)
    area: float = 0.0

    @property
    def key(self) -> str:
        return self.sketch + ":" + "-".join(map(str, self.outer.ents))

    def to_data(self) -> dict:
        """Plain-data reference stored on an extrude feature."""
        return {"sketch": self.sketch, "outer": list(self.outer.ents), "holes": [list(h.ents) for h in self.holes]}


def poly_area(p) -> float:
    a = 0.0
    for i in range(len(p)):
        x0, y0 = p[i - 1]
        x1, y1 = p[i]
        a += (x0 + x1) * (y0 - y1)
    return a / 2


def point_in_poly(p, poly) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        (xi, yi), (xj, yj) = poly[i], poly[j]
        if (yi > p[1]) != (yj > p[1]) and p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def on_edge(p, poly, eps=1e-6) -> bool:
    for i in range(len(poly)):
        (ax, ay), (bx, by) = poly[i - 1], poly[i]
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L)) if L else 0.0
        if math.hypot(ax + t * dx - p[0], ay + t * dy - p[1]) < eps:
            return True
    return False


def _key(p):
    return f"{p[0]:.5f},{p[1]:.5f}"


def sketch_loops(ents) -> list[Loop]:
    loops, lines = [], []
    for i, e in enumerate(ents):
        t = e["type"]
        if t == "circle":
            loops.append(Loop([i], circle_points(e["c"], e["r"]), circle=e))
        elif t == "rect":
            pts = rounded_rect_points(e["pts"], e["corner_r"]) if e.get("corner_r") else [list(p) for p in e["pts"]]
            loops.append(Loop([i], pts, rect=e))
        elif t == "polygon":
            loops.append(Loop([i], [list(p) for p in e["pts"]]))
        elif t == "line":
            lines.append(i)

    # closed line chains: every vertex on the loop must join exactly two lines
    adj: dict[str, dict] = {}
    for i in lines:
        for p in ents[i]["pts"]:
            adj.setdefault(_key(p), {"p": p, "l": []})["l"].append(i)
    used = set()
    for i0 in lines:
        if i0 in used:
            continue
        start = _key(ents[i0]["pts"][0])
        chain, pts, cur, at, closed = [], [], i0, start, False
        while cur not in used:
            used.add(cur)
            chain.append(cur)
            pts.append(list(adj[at]["p"]))
            a, b = ents[cur]["pts"]
            nxt = _key(b) if _key(a) == at else _key(a)
            if len(adj[nxt]["l"]) != 2 or len(adj[start]["l"]) != 2:
                break
            if nxt == start:
                closed = True
                break
            l = adj[nxt]["l"]
            cur, at = (l[1] if l[0] == cur else l[0]), nxt
        if closed and len(chain) >= 3:
            loops.append(Loop(chain, pts))

    for L in loops:
        L.area = abs(poly_area(L.pts))
    return [L for L in loops if L.area > 1e-9]


def loop_inside(a: Loop, b: Loop) -> bool:
    """True when loop `a` lies inside loop `b` (touching the boundary counts as inside)."""
    if a is b or a.area >= b.area:
        return False
    on = [on_edge(p, b.pts) for p in a.pts]
    return all(o or point_in_poly(p, b.pts) for o, p in zip(on, a.pts)) and not all(on)


def sketch_regions(sketch_id: str, ents) -> list[Region]:
    loops = sketch_loops(ents)
    regions = []
    for L in loops:
        holes = [q for q in loops if loop_inside(q, L)
                 and not any(r is not L and loop_inside(q, r) and loop_inside(r, L) for r in loops)]
        regions.append(Region(sketch_id, L, holes, L.area - sum(h.area for h in holes)))
    return regions


def region_at(regions, p) -> Region | None:
    """Smallest region containing point p (what a click picks)."""
    best = None
    for r in regions:
        if point_in_poly(p, r.outer.pts) and not any(point_in_poly(p, h.pts) for h in r.holes):
            if best is None or r.area < best.area:
                best = r
    return best


def resolve(ref: dict, ents) -> Region:
    """Turn a stored profile reference ({sketch, outer, holes}) back into a Region."""
    loops = {tuple(L.ents): L for L in sketch_loops(ents)}
    try:
        outer = loops[tuple(ref["outer"])]
        holes = [loops[tuple(h)] for h in ref.get("holes", [])]
    except KeyError as exc:
        raise ValueError(f"profile {ref} no longer exists in sketch {ref['sketch']}") from exc
    return Region(ref["sketch"], outer, holes, outer.area - sum(h.area for h in holes))
