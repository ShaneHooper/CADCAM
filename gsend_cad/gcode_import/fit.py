"""Phase 5, part 1: fit the reconstructed outline to clean lines and arcs. Stdlib only.

The reconstruction's outline is a polygon (a nose arc is dozens of tiny edges). This turns it
into the few lines and arcs a person would draw:

    split      where the outline changes from exact to assumed (an arc never mixes the two) and
               at every sharp corner
    fit        greedily, the longest run of points that one straight line holds within the
               tolerance, or else the longest run one circular arc holds within it
    pin        every arc passes exactly through its two end points, so segments join exactly
    snap       a line within the tolerance of level / plumb is made exactly level / plumb,
               and a point within it of the centerline sits exactly on it

Coordinates here are the sketch's: u = radius (the sketch X), v = Z (the sketch Y). The outline
comes in as the reconstruction's Edge list (Z, diameter) and is converted.

The sketch has no constraint solver, so the constraints the fit satisfies are RECORDED beside
the geometry (Fit.constraints) and the geometry is built to satisfy them exactly or to the
reported tolerance. See `check`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

TOL = 0.0005                    # fit tolerance in inches (configurable per call)
CORNER = math.radians(20.0)     # a turn this sharp between two edges is a real corner, not an arc
TANGENT = math.radians(1.0)     # junctions this close to smooth are recorded as tangent
MIN_ARC_POINTS = 4              # three points always lie on some circle: an arc needs more evidence
MAX_ARC_SWEEP = math.radians(270.0)
EXACT = 2e-6                    # "exactly straight": well under any fit tolerance
CHORD_RATIO = 2.5              # no edge of an arc may be this many times longer than its typical chord
MICRO = 1e-6                   # points closer than this are one point

Pt = tuple[float, float]


@dataclass
class Seg:
    kind: str                   # "line" | "arc"
    a: Pt                       # start (u, v), in outline order
    b: Pt                       # end
    tag: str = "EXACT"          # EXACT | ASSUMED | STOCK | AXIS (the least certain edge it covers)
    src: str = ""               # tool number(s) that cut it
    c: Pt | None = None         # arc centre
    r: float = 0.0              # arc radius
    ccw: bool = True            # arc direction a -> b
    dev: float = 0.0            # largest distance from the original outline


@dataclass
class Fit:
    segs: list[Seg] = field(default_factory=list)      # a closed chain, in order
    constraints: list[dict] = field(default_factory=list)
    tol: float = TOL
    max_dev: float = 0.0
    points_in: int = 0

    @property
    def lines(self) -> int:
        return sum(1 for s in self.segs if s.kind == "line")

    @property
    def arcs(self) -> int:
        return sum(1 for s in self.segs if s.kind == "arc")

    @property
    def assumed(self) -> int:
        return sum(1 for s in self.segs if s.tag == "ASSUMED")


def _dist(p: Pt, q: Pt) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _cross(o: Pt, a: Pt, b: Pt) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _turn(p: Pt, q: Pt, r: Pt) -> float:
    """Signed turn at q going p -> q -> r (radians, + = counter-clockwise)."""
    a1 = math.atan2(q[1] - p[1], q[0] - p[0])
    a2 = math.atan2(r[1] - q[1], r[0] - q[0])
    d = a2 - a1
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    return d


def _line_dev(pts: list[Pt], i: int, j: int) -> float:
    """Largest distance of points i..j from the chord i -> j."""
    a, b = pts[i], pts[j]
    L = _dist(a, b)
    if L < MICRO:
        return max((_dist(a, p) for p in pts[i:j + 1]), default=0.0)
    return max((abs(_cross(a, b, p)) / L for p in pts[i + 1:j]), default=0.0)


def _circle_through(pts: list[Pt]):
    """Least-squares circle (Kasa) through points: (centre, radius), or None if they are collinear."""
    n = len(pts)
    mu = sum(p[0] for p in pts) / n
    mv = sum(p[1] for p in pts) / n
    suu = suv = svv = suuu = svvv = suvv = svuu = 0.0
    for u, v in pts:
        x, y = u - mu, v - mv
        suu += x * x
        suv += x * y
        svv += y * y
        suuu += x * x * x
        svvv += y * y * y
        suvv += x * y * y
        svuu += y * x * x
    det = suu * svv - suv * suv
    if abs(det) < 1e-18:
        return None
    uc = (svv * (suuu + suvv) - suv * (svvv + svuu)) / (2 * det)
    vc = (suu * (svvv + svuu) - suv * (suuu + suvv)) / (2 * det)
    c = (uc + mu, vc + mv)
    return c, sum(_dist(c, p) for p in pts) / n


def _pin_circle(a: Pt, b: Pt, c: Pt) -> tuple[Pt, float]:
    """Move centre c onto the perpendicular bisector of a-b (so the circle passes through both ends)."""
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    L = _dist(a, b)
    nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
    t = (c[0] - mid[0]) * nx + (c[1] - mid[1]) * ny
    cc = (mid[0] + t * nx, mid[1] + t * ny)
    return cc, _dist(cc, a)


def _arc_ok(pts: list[Pt], i: int, k: int, tol: float):
    """Fit points i..k to one arc through points i and k. Returns (centre, radius, ccw, dev) or None."""
    if k - i + 1 < MIN_ARC_POINTS:
        return None
    seg = pts[i:k + 1]
    turns = [_turn(seg[m - 1], seg[m], seg[m + 1]) for m in range(1, len(seg) - 1)]
    if not (all(t > 0 for t in turns) or all(t < 0 for t in turns)):
        return None                                     # an arc turns one way the whole way
    if abs(sum(turns)) > MAX_ARC_SWEEP or max(abs(t) for t in turns) > CORNER:
        return None                                     # a corner in the middle is not an arc
    # a sampled arc is made of even chords (the end ones may be cut short). A long straight edge
    # beside a few short ones is a line meeting a blend, not one big shallow arc.
    chords = [_dist(seg[m], seg[m + 1]) for m in range(len(seg) - 1)]
    inner = chords[1:-1] or chords
    med = sorted(inner)[len(inner) // 2]
    if (max(chords) > CHORD_RATIO * med or min(inner) < med / CHORD_RATIO):
        return None
    lsq = _circle_through(seg)
    if lsq is None or lsq[1] > 1e4:
        return None
    c, r = _pin_circle(seg[0], seg[-1], lsq[0])
    if r > 1e4:
        return None
    dev = max(abs(_dist(c, p) - r) for p in seg)        # the outline's vertices lie on the true arc
    if dev > tol:
        return None
    return c, r, sum(turns) > 0, dev


def _dedupe(pts: list[Pt], tags: list[tuple[str, str]]):
    out, ot = [pts[0]], []
    for m in range(1, len(pts)):
        if _dist(pts[m], out[-1]) < MICRO:
            continue
        out.append(pts[m])
        ot.append(tags[m - 1])
    return out, ot


def _worse(a: str, b: str) -> str:
    order = {"EXACT": 0, "STOCK": 0, "AXIS": 0, "ASSUMED": 1}
    return a if order.get(a, 0) >= order.get(b, 0) else b


def fit_outline(edges, tol: float = TOL) -> Fit:
    """edges: the reconstruction's Edge list (closed, in order; Z and diameter). Returns the fit."""
    fit = Fit(tol=tol)
    if not edges:
        return fit
    pts: list[Pt] = [(e.x0 / 2.0, e.z0) for e in edges]
    tags = [(e.tag, e.tool) for e in edges]
    pts.append((edges[-1].x1 / 2.0, edges[-1].z1))
    pts, tags = _dedupe(pts, tags)
    if _dist(pts[0], pts[-1]) < MICRO:
        pts.pop()                                       # closed: the last point is the first
    else:
        tags = tags[:len(pts) - 1] + [tags[-1]]
    n = len(pts)
    fit.points_in = n
    if n < 3:
        return fit
    # edge m runs pts[m] -> pts[(m + 1) % n] and carries tags[m]
    cls = lambda t: "A" if t == "ASSUMED" else ("X" if t == "AXIS" else "E")

    # break points: vertices where the run must end (a corner, or the exact/assumed class changes)
    brk = []
    for m in range(n):
        p, q, r = pts[m - 1], pts[m], pts[(m + 1) % n]
        sharp = abs(_turn(p, q, r)) > CORNER
        change = cls(tags[m - 1][0]) != cls(tags[m][0])
        if sharp or change:
            brk.append(m)
    if not brk:
        brk = [0]
    start = brk[0]
    order = [(start + m) % n for m in range(n)]         # vertex indices from a break, round once
    P = [pts[m] for m in order] + [pts[start]]          # closed ring starting at a break
    T = [tags[m] for m in order]
    isbrk = [m in set(brk) for m in order] + [True]

    # greedy runs
    bounds = [0]
    runs = []                                           # (i, j, kind, arc data)
    i = 0
    last = len(P) - 1
    while i < last:
        # the furthest vertex a run may reach: the next break after i
        hard = next((m for m in range(i + 1, last + 1) if isbrk[m]), last)
        je = i + 1                                      # the exactly straight run (no tolerance used)
        while je + 1 <= hard and _line_dev(P, i, je + 1) <= EXACT:
            je += 1
        j = je                                          # ... stretched to the tolerance only if no arc starts there
        while j + 1 <= hard and _line_dev(P, i, j + 1) <= tol:
            j += 1
        k, arc = i + 1, None
        for kk in range(i + MIN_ARC_POINTS - 1, hard + 1):
            got = _arc_ok(P, i, kk, tol)
            if got:
                k, arc = kk, got
            elif arc is not None and kk - k > 2:
                break
        if arc is not None and k > je:
            runs.append((i, k, "arc", arc))
            i = k
        else:
            if j > je and _arc_ok(P, je, min(je + MIN_ARC_POINTS - 1, hard), tol):
                j = je                                  # an arc begins at the end of the straight part: do not eat it
            runs.append((i, j, "line", None))
            i = j
        bounds.append(i)

    # vertices of the fit (the run boundaries), then snap
    V = [list(P[r[0]]) for r in runs]
    nv = len(V)
    locked_u = [False] * nv
    locked_v = [False] * nv
    for m in range(nv):
        if abs(V[m][0]) <= tol:
            V[m][0], locked_u[m] = 0.0, True            # on the centerline exactly
    for m, (i, j, kind, arc) in enumerate(runs):
        if kind != "line":
            continue
        m2 = (m + 1) % nv
        a, b = V[m], V[m2]
        for ax, lock in ((0, locked_u), (1, locked_v)):
            if abs(a[ax] - b[ax]) <= tol:               # level / plumb
                tgt = a[ax] if lock[m] else (b[ax] if lock[m2] else (a[ax] + b[ax]) / 2)
                a[ax] = b[ax] = tgt
                lock[m] = lock[m2] = True

    # segments
    for m, (i, j, kind, arc) in enumerate(runs):
        a, b = tuple(V[m]), tuple(V[(m + 1) % nv])
        edge_tags = [T[q] for q in range(i, j)]
        tag = "EXACT"
        srcs: list[str] = []
        for t, s in edge_tags:
            tag = _worse(tag, t)
            if s and s not in srcs:
                srcs.append(s)
        if all(t == "AXIS" for t, _ in edge_tags):
            tag = "AXIS"
        elif all(t == "STOCK" for t, _ in edge_tags):
            tag = "STOCK"
        if _dist(a, b) < MICRO:
            continue
        if kind == "line":
            dev = _line_dev(P, i, j) if (a == P[i] and b == P[j]) else max(
                (abs(_cross(a, b, p)) / _dist(a, b) for p in P[i:j + 1]), default=0.0)
            fit.segs.append(Seg("line", a, b, tag, "/".join(srcs), dev=dev))
        else:
            _c, _r, ccw, _d = arc
            c, r = _pin_circle(a, b, _c)
            dev = max(abs(_dist(c, p) - r) for p in P[i:j + 1])
            fit.segs.append(Seg("arc", a, b, tag, "/".join(srcs), c=c, r=r, ccw=ccw, dev=dev))
    fit.max_dev = max((s.dev for s in fit.segs), default=0.0)
    fit.constraints = _constraints(fit)
    return fit


def _tangent_at(s: Seg, end: str) -> float:
    """Direction of travel (radians) at a segment's start or end."""
    if s.kind == "line":
        return math.atan2(s.b[1] - s.a[1], s.b[0] - s.a[0])
    p = s.a if end == "a" else s.b
    ang = math.atan2(p[1] - s.c[1], p[0] - s.c[0])
    return ang + (math.pi / 2 if s.ccw else -math.pi / 2)


def _constraints(fit: Fit) -> list[dict]:
    """What the geometry satisfies, by segment index (the sketch's entity order)."""
    out = []
    n = len(fit.segs)
    for m, s in enumerate(fit.segs):
        nxt = (m + 1) % n
        out.append({"type": "coincident", "a": [m, "end"], "b": [nxt, "start"]})
        if s.kind == "line":
            if abs(s.a[1] - s.b[1]) < 1e-12:
                out.append({"type": "horizontal", "ent": m})
            elif abs(s.a[0] - s.b[0]) < 1e-12:
                out.append({"type": "vertical", "ent": m})
        d = _tangent_at(s, "b") - _tangent_at(fit.segs[nxt], "a")
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        if abs(d) <= TANGENT and (s.kind == "arc" or fit.segs[nxt].kind == "arc"):
            out.append({"type": "tangent", "a": m, "b": nxt})
        if s.a[0] == 0.0 and s.b[0] == 0.0 and s.kind == "line":
            out.append({"type": "on_axis", "ent": m})
    return out


def check(fit: Fit) -> list[str]:
    """Problems with a fit (empty when it is sound): open chains, broken constraints, big deviations."""
    bad = []
    n = len(fit.segs)
    for m, s in enumerate(fit.segs):
        nx = fit.segs[(m + 1) % n]
        if s.b != nx.a:
            bad.append(f"segment {m} does not meet segment {(m + 1) % n}")
        if s.dev > fit.tol + 1e-12:
            bad.append(f"segment {m} is {s.dev:.5f} off the outline (tolerance {fit.tol})")
        if s.kind == "arc" and (abs(_dist(s.c, s.a) - s.r) > 1e-9 or abs(_dist(s.c, s.b) - s.r) > 1e-9):
            bad.append(f"arc {m} does not pass through its end points")
    return bad
