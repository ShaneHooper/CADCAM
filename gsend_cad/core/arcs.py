"""Find the arcs in a polyline so the post can write G02 / G03 instead of a string of tiny G01s. Stdlib only.

The part profile a toolpath follows comes off a mesh of the part (kernel.turn_profile, arcs within 0.002"),
so a fillet arrives as 20-30 short chords. A machinist reads that as a mistake, and a control runs it
slower than one arc. The rule is the one gcode_import/fit.py uses on an imported outline: a run of
gently turning chords (same way, each bend <= 15 deg) whose vertices all sit on one circle is an arc. Its
ends are the polyline's own vertices, so the pieces still meet exactly. Everything else stays a line.

    fit([(u, v), ...]) -> [("line", i0, i1), ("arc", i0, i1, (cu, cv), r, ccw), ...]

i0 / i1 index the points; ccw = the arc turns counter-clockwise (a left turn) going from i0 to i1 in the
(u, v) plane as drawn with u to the right and v up. A lathe post passes (z, x radius): that is the G18 view
(Z right, X up), where counter-clockwise is G03.
"""
from __future__ import annotations

import math

Pt = tuple[float, float]

MAX_TURN = math.radians(15.0)   # the most one chord may bend from the next and still be an arc
MIN_TURN = 1e-5                 # (rad) gentler than this per chord is a very large radius, still an arc
MAX_SWEEP = math.pi             # an R-word arc is at most a half circle: a longer one stays lines
MIN_CHORDS = 3                  # fewer chords cannot tell an arc from a corner (a chamfer is 1 chord)
TOL = 2e-4                      # every vertex of an arc's run is this close to its circle. Absolute: a looser
                                # tolerance lets a long line plus the start of a radius pass as one big arc
REGULAR = 1.5                   # the chords between an arc's two end chords differ by at most this factor
END_LONGER = 1.3                # an end chord is at most this much longer than the longest chord between
R_MIN, R_MAX = 1e-4, 1000.0


def _sub(a: Pt, b: Pt) -> Pt:
    return (a[0] - b[0], a[1] - b[1])


def _len(a: Pt) -> float:
    return math.hypot(a[0], a[1])


def _turn(d0: Pt, d1: Pt) -> float:
    """Signed angle from direction d0 to d1 (+ = counter-clockwise, a left turn)."""
    return math.atan2(d0[0] * d1[1] - d0[1] * d1[0], d0[0] * d1[0] + d0[1] * d1[1])


def circle_through(pts: list[Pt]) -> tuple[Pt, float] | None:
    """Least-squares circle (Kasa) through the points, then moved so the FIRST and LAST point lie on it
    exactly (centre slid along their perpendicular bisector). None when the points are straight."""
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
    c = ((sxz * syy - syz * sxy) / (2.0 * det) + mx, (syz * sxx - sxz * sxy) / (2.0 * det) + my)
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


def _arc(pts: list[Pt], i0: int, i1: int, turns: list[float]):
    """(centre, radius, ccw) when the chords i0..i1-1 of `pts` are one arc, else None."""
    if i1 - i0 < MIN_CHORDS:
        return None
    ts = turns[i0:i1 - 1]                      # the bends between those chords
    if any(abs(t) > MAX_TURN or abs(t) < MIN_TURN for t in ts):
        return None
    if any((t > 0) != (ts[0] > 0) for t in ts) or abs(sum(ts)) > MAX_SWEEP:
        return None
    vs = pts[i0:i1 + 1]
    # a tessellated arc is chords of one length; only the first and last may be partial (cut by a
    # neighbour), so neither end may be LONGER than the chords between: that keeps a long line out
    # of the arc that starts at its end
    ls = [_len(_sub(b, a)) for a, b in zip(vs, vs[1:])]
    inner = ls[1:-1]
    if max(inner) > REGULAR * min(inner) or max(ls[0], ls[-1]) > END_LONGER * max(inner):
        return None
    got = circle_through(vs)
    if got is None:
        return None
    c, r = got
    if not (R_MIN < r < R_MAX) or max(abs(_len(_sub(p, c)) - r) for p in vs) > TOL:
        return None
    return c, r, ts[0] > 0


def fit(points: list[Pt]) -> list[tuple]:
    """The polyline's pieces, in order: ("line", i0, i1) or ("arc", i0, i1, centre, r, ccw). Arcs are
    taken greedily (the longest run that is still one circle); the rest are the chords as given."""
    pts = [(float(u), float(v)) for u, v in points]
    n = len(pts) - 1                            # chords
    if n < 1:
        return []
    dirs = [_sub(b, a) for a, b in zip(pts, pts[1:])]
    turns = [_turn(dirs[k], dirs[k + 1]) for k in range(n - 1)]
    out = []
    i = 0
    while i < n:
        best = None
        j = i + MIN_CHORDS
        while j <= n:
            f = _arc(pts, i, j, turns)
            if f is None:
                break
            best = (j, f)
            j += 1
        if best:
            j, (c, r, ccw) = best
            out.append(("arc", i, j, c, r, ccw))
            i = j
        else:
            out.append(("line", i, i + 1))
            i += 1
    return out
