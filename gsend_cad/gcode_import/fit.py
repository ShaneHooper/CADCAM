"""Fit the reconstructed outline to the lines and arcs a sketch is made of. Stdlib only.

The reconstruction's outline is a faceted polygon: a nose radius is 24 short chords, a
shoulder is one long one. A sketch wants real geometry, so:

    1. collinear chords are merged into one straight piece (same tag only)
    2. a run of gently turning pieces (same direction, each turn <= 12 deg) whose vertices
       sit on one circle is replaced by an arc; its end points stay the polygon's own
       vertices, so every piece meets the next exactly and the sketch closes
    3. everything else stays a line

Nothing is invented: every vertex of the outline lies within `max_dev` of what replaced it.
Each piece keeps the weakest tag of the outline it covers (STOCK < ASSUMED < EXACT) so Phase 6
knows which pieces to dimension.

Coordinates: (z, radius). The outline carries diameter; it is halved here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from ..core import sketch as sk

Pt = tuple[float, float]

LINE_TOL = 2e-6                 # a vertex this close to the line through its piece's ends is on it
ARC_MAX_TURN = math.radians(15.0)   # the most one chord may bend from the next and still be an arc
ARC_MIN_TURN = 1e-5             # (rad) a gentler bend than this per chord is a very large radius, still an arc
ARC_MAX_SWEEP = math.radians(200.0)
ARC_MIN_PIECES = 3              # fewer chords than this cannot tell an arc from a corner
ARC_TOL = 2e-4                  # every vertex of an arc's run is this close to the circle. Absolute, NOT a
                                # fraction of R: a looser tolerance lets a long line plus the start of a
                                # nose radius pass as one big arc (measured: 6.6e-4 off on a shoulder).
                                # A chord cut by a boolean sits off the circle by its sagitta, 1.7e-5 on a
                                # 1/32 nose and 1.3e-4 on a 1/4 round insert, so 2e-4 holds them all.
SNAP_TOL = 5e-6                 # a vertex / radius this close to a grid value IS that value (float and boolean dust)
GRID_INCH = 1e-4                # an inch program's resolution (diameters and Z); a metric one's is GRID_MM / 25.4
GRID_MM = 1e-3
R_MAX = 1000.0
REGULAR = 1.5                   # the chords between an arc's two end chords differ by at most this factor
END_LONGER = 1.3                # an end chord is at most this much longer than the longest chord between
CLOSE_TOL = 1e-6
_RANK = {"STOCK": 0, "ASSUMED": 1, "EXACT": 2, "AXIS": 3}


@dataclass(frozen=True)
class Prim:
    kind: str                   # "line" | "arc"
    p: Pt                       # start, in outline order
    q: Pt                       # end
    tag: str
    tool: str = ""
    c: Pt | None = None         # arcs: centre
    r: float = 0.0              # arcs: radius
    ccw: bool = True            # arcs: p -> q turns counter-clockwise about c
    dev: float = 0.0            # worst distance of the covered outline vertices from this piece
    n: int = 1                  # outline segments it replaced


@dataclass
class Fit:
    ok: bool = True
    error: str = ""
    prims: list[Prim] = field(default_factory=list)
    max_dev: float = 0.0        # worst distance of any outline vertex from what replaced it (snapping included)
    segments: int = 0           # outline segments before fitting
    snapped: int = 0            # vertices moved onto the program's grid (see _snap)
    assumed: int = 0            # pieces that are only ASSUMED: never snapped, drawn in warning yellow

    def count(self, kind: str) -> int:
        return sum(1 for p in self.prims if p.kind == kind)


# ---- small geometry ----
def _sub(a: Pt, b: Pt) -> Pt:
    return (a[0] - b[0], a[1] - b[1])


def _len(a: Pt) -> float:
    return math.hypot(a[0], a[1])


def _dist_to_line(p: Pt, a: Pt, b: Pt) -> float:
    d = _sub(b, a)
    n = _len(d)
    if n < 1e-12:
        return _len(_sub(p, a))
    return abs(d[0] * (p[1] - a[1]) - d[1] * (p[0] - a[0])) / n


def _turn(d0: Pt, d1: Pt) -> float:
    """Signed angle from direction d0 to d1 (+ = counter-clockwise, i.e. a left turn)."""
    return math.atan2(d0[0] * d1[1] - d0[1] * d1[0], d0[0] * d1[0] + d0[1] * d1[1])


def _circle_through(pts: list[Pt]) -> tuple[Pt, float] | None:
    """Least-squares circle (Kasa) through the points, then moved so the FIRST and LAST point lie on
    it exactly (centre slid along their perpendicular bisector). None when the points are straight."""
    n = len(pts)
    mx, my = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    sxx = sxy = syy = sxz = syz = 0.0
    for x, y in pts:
        x, y = x - mx, y - my
        z = x * x + y * y
        sxx += x * x
        sxy += x * y
        syy += y * y
        sxz += x * z
        syz += y * z
    det = sxx * syy - sxy * sxy
    if abs(det) < 1e-18:
        return None
    cx = (sxz * syy - syz * sxy) / (2.0 * det)
    cy = (syz * sxx - sxz * sxy) / (2.0 * det)
    c = (cx + mx, cy + my)
    a, b = pts[0], pts[-1]
    m = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    ab = _sub(b, a)
    L = _len(ab)
    if L < 1e-12:
        return None
    nrm = (-ab[1] / L, ab[0] / L)
    t = (c[0] - m[0]) * nrm[0] + (c[1] - m[1]) * nrm[1]
    c = (m[0] + nrm[0] * t, m[1] + nrm[1] * t)
    return c, _len(_sub(a, c))


def _arc_dev(pts: list[Pt], c: Pt, r: float) -> float:
    return max(abs(_len(_sub(p, c)) - r) for p in pts)


# ---- the fit ----
def _vertices(edges) -> tuple[list[Pt], list[str], list[str]] | str:
    """The outline as a closed vertex ring plus a tag and a tool per segment, or an error text."""
    if len(edges) < 3:
        return "the outline has too few edges to build a part"
    pts: list[Pt] = []
    tags: list[str] = []
    tools: list[str] = []
    for i, e in enumerate(edges):
        a, b = (e.z0, e.x0 / 2.0), (e.z1, e.x1 / 2.0)
        if pts and _len(_sub(a, pts[-1])) > CLOSE_TOL:
            return "the outline is not one closed loop"
        if not pts:
            pts.append(a)
        if _len(_sub(b, pts[-1])) < 1e-9:
            continue                                    # a zero-length edge
        pts.append(b)
        tags.append(e.tag)
        tools.append(e.tool)
    if _len(_sub(pts[-1], pts[0])) > CLOSE_TOL:
        return "the outline does not close"
    pts[-1] = pts[0]
    # the centerline is exactly r = 0 (the booleans leave dust there)
    pts = [(z, 0.0 if abs(r) < 1e-9 else r) for z, r in pts]
    return pts, tags, tools


def _snap_value(v: float, g: float, tol: float) -> float:
    s = round(v / g) * g
    return s if abs(v - s) <= tol else v


def _snap(prims: list[Prim], grid: float) -> tuple[list[Prim], int]:
    """Clean round values: put every vertex on the program's own resolution (Z and diameters to `grid`) and
    every arc radius on half of it, wherever the value is within SNAP_TOL of a grid point.

    Only noise moves: a tangent point like Z-0.46875 is 5e-5 from the nearest grid value, so it stays. A vertex
    is snapped ONCE and shared by the two pieces it joins, so the profile stays closed. Anything touching an
    ASSUMED piece is left alone (its numbers are a guess, not a reading). Returns the new pieces and how many
    vertices moved."""
    n = len(prims)
    verts: list[Pt] = []
    moved = 0
    for k in range(n):
        z, r = prims[k].p
        if prims[k].tag != "ASSUMED" and prims[k - 1].tag != "ASSUMED":
            z2 = _snap_value(z, grid, SNAP_TOL)
            r2 = _snap_value(2.0 * r, grid, 2.0 * SNAP_TOL) / 2.0
            if (z2, r2) != (z, r):
                moved += 1
            z, r = z2, r2
        verts.append((z, r))
    out: list[Prim] = []
    for k, pr in enumerate(prims):
        p, q = verts[k], verts[(k + 1) % n]
        if pr.kind == "line":
            out.append(replace(pr, p=p, q=q))
            continue
        R = pr.r if pr.tag == "ASSUMED" else _snap_value(pr.r, grid / 2.0, SNAP_TOL)
        ab = _sub(q, p)
        L = _len(ab)
        if L < 1e-12:
            out.append(replace(pr, p=p, q=q))
            continue
        R = max(R, L / 2.0)
        h = math.sqrt(max(R * R - (L / 2.0) ** 2, 0.0))
        mid = ((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0)
        nrm = (-ab[1] / L, ab[0] / L)
        side = 1.0 if (pr.c[0] - mid[0]) * nrm[0] + (pr.c[1] - mid[1]) * nrm[1] >= 0 else -1.0
        out.append(replace(pr, p=p, q=q, c=(mid[0] + side * h * nrm[0], mid[1] + side * h * nrm[1]), r=R))
    return out, moved


def _dist_to_prim(pt: Pt, pr: Prim) -> float:
    if pr.kind == "arc":
        return abs(_len(_sub(pt, pr.c)) - pr.r)
    return _dist_to_line(pt, pr.p, pr.q)


def fit_outline(edges, grid: float | None = GRID_INCH) -> Fit:
    """Lines and arcs for a reconstruction's outline (its `edges`), in order, closed.

    grid: the program's resolution in inches (GRID_INCH, or GRID_MM / 25.4 for a metric program). The fitted
    EXACT geometry is snapped onto it (see _snap); None leaves the fit as the outline gave it."""
    res = Fit()
    got = _vertices(edges)
    if isinstance(got, str):
        return Fit(ok=False, error=got)
    ring, tags, tools = got
    n = len(tags)
    res.segments = n
    seg = lambda i: (ring[i], ring[i + 1])

    # --- rotate so index 0 starts a piece (the first place two segments cannot merge) ---
    def mergeable(i: int, j: int) -> bool:              # segment i then segment j (j = i + 1 mod n)
        if tags[i] != tags[j]:
            return False
        d0, d1 = _sub(*reversed(seg(i))), _sub(*reversed(seg(j)))
        return abs(_turn(d0, d1)) < 1e-4 and d0[0] * d1[0] + d0[1] * d1[1] > 0
    start = next((j for j in range(n) if not mergeable((j - 1) % n, j)), None)
    if start is None:
        return Fit(ok=False, error="the outline is a single straight line")
    order = [(start + k) % n for k in range(n)]

    # --- 1. straight pieces: (first index, last index) into `order` ---
    pieces: list[tuple[int, int]] = []
    k = 0
    while k < n:
        a = ring[order[k]]
        end = k
        while end + 1 < n:
            j = order[end + 1]
            if tags[j] != tags[order[k]]:
                break
            b = ring[j + 1]
            inner = [ring[order[m]] for m in range(k + 1, end + 2)]
            d = _sub(b, a)
            ok = all(_dist_to_line(p, a, b) <= LINE_TOL for p in inner)
            ok = ok and all((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1] > 0 for p in inner)
            if not ok:
                break
            end += 1
        pieces.append((k, end))
        k = end + 1

    def ends(pc):
        return ring[order[pc[0]]], ring[order[pc[1]] + 1]
    P = len(pieces)
    dirs = [_sub(ends(pc)[1], ends(pc)[0]) for pc in pieces]
    ptag = [tags[order[pc[0]]] for pc in pieces]
    turns = [_turn(dirs[i], dirs[(i + 1) % P]) for i in range(P)]     # turn at the end of piece i

    # --- rotate again so no arc has to wrap: start after a hard corner ---
    hard = lambda i: abs(turns[i]) > ARC_MAX_TURN or ptag[i] != ptag[(i + 1) % P]
    h = next((i for i in range(P) if hard(i)), None)
    r0 = 0 if h is None else (h + 1) % P
    pieces = pieces[r0:] + pieces[:r0]
    dirs, ptag, turns = dirs[r0:] + dirs[:r0], ptag[r0:] + ptag[:r0], turns[r0:] + turns[:r0]

    def tool_of(i0: int, i1: int) -> str:
        best, bl = "", -1.0
        for m in range(pieces[i0][0], pieces[i1][1] + 1):
            a, b = seg(order[m])
            if _len(_sub(b, a)) > bl:
                best, bl = tools[order[m]], _len(_sub(b, a))
        return best

    def weakest(i0: int, i1: int) -> str:
        return min((ptag[i] for i in range(i0, i1 + 1)), key=lambda t: _RANK.get(t, 9))

    def verts(i0: int, i1: int) -> list[Pt]:
        return [ends(pieces[i0])[0]] + [ends(pieces[i])[1] for i in range(i0, i1 + 1)]

    def arc_fit(i0: int, i1: int):
        """(centre, radius, deviation, ccw) when pieces i0..i1 are one arc, else None."""
        if i1 - i0 + 1 < ARC_MIN_PIECES or i1 >= P:
            return None
        if len({ptag[i] for i in range(i0, i1 + 1)}) != 1:
            return None
        ts = turns[i0:i1]
        if not ts or any(abs(t) > ARC_MAX_TURN or abs(t) < ARC_MIN_TURN for t in ts):
            return None
        if any((t > 0) != (ts[0] > 0) for t in ts) or abs(sum(ts)) > ARC_MAX_SWEEP:
            return None
        vs = verts(i0, i1)
        # a tessellated arc is made of chords of one length; only the first and last may be partial
        # (a boolean cut them) - so neither end can be LONGER than the chords between. This is what
        # keeps a long shoulder line out of the arc that starts at its end.
        ls = [_len(_sub(b, a)) for a, b in zip(vs, vs[1:])]
        inner = ls[1:-1]
        if max(inner) > REGULAR * min(inner) or max(ls[0], ls[-1]) > END_LONGER * max(inner):
            return None
        got = _circle_through(vs)
        if got is None:
            return None
        c, r = got
        if not (1e-4 < r < R_MAX):
            return None
        dev = _arc_dev(vs, c, r)
        if dev > ARC_TOL:
            return None
        return c, r, dev, ts[0] > 0

    # --- 2. arcs, greedily, else lines ---
    prims: list[Prim] = []
    i = 0
    while i < P:
        best = None
        k = i + ARC_MIN_PIECES - 1
        while k < P:
            f = arc_fit(i, k)
            if f is None:
                break
            best = (k, f)
            k += 1
        if best:
            k, (c, r, dev, ccw) = best
            a, b = ends(pieces[i])[0], ends(pieces[k])[1]
            prims.append(Prim("arc", a, b, ptag[i], tool_of(i, k), c, r, ccw, dev,
                              pieces[k][1] - pieces[i][0] + 1))
            i = k + 1
        else:
            a, b = ends(pieces[i])
            dev = max(_dist_to_line(ring[order[m]], a, b) for m in range(pieces[i][0], pieces[i][1] + 2 - 1))
            prims.append(Prim("line", a, b, ptag[i], tool_of(i, i), None, 0.0, True, dev,
                              pieces[i][1] - pieces[i][0] + 1))
            i += 1
    if grid:
        prims, res.snapped = _snap(prims, grid)
    res.prims = prims
    # the honest number: every vertex of the outline against the pieces that replaced it, after snapping too
    res.max_dev = max((min(_dist_to_prim(v, pr) for pr in prims) for v in ring[:-1]), default=0.0)
    res.assumed = sum(1 for p in prims if p.tag == "ASSUMED")
    return res


def to_entities(fit: Fit) -> list[dict]:
    """The sketch entities for a fit: x = lathe Z, y = radius. A piece's tag rides along as "src"."""
    out = []
    for p in fit.prims:
        if p.kind == "line":
            e = sk.line(p.p, p.q)
        else:
            ang = lambda q: math.degrees(math.atan2(q[1] - p.c[1], q[0] - p.c[0]))
            if p.ccw:
                e = sk.arc(p.c, p.r, ang(p.p), ang(p.q), [p.p, p.q])
            else:
                e = sk.arc(p.c, p.r, ang(p.q), ang(p.p), [p.q, p.p])
        e["src"] = p.tag
        out.append(e)
    return out
