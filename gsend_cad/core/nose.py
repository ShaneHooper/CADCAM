"""Tool nose radius compensation ("cutter comp") for a lathe contour, worked out in the code. Stdlib only.

A program that places the IMAGINARY tool tip on the part line cuts angles and radii wrong: the real nose is round, so
it sits r (the nose radius) back from where the sharp tip would be. Axis-only moves don't care (the Haas ST/TL
workbook, p.55-57: chamfers and radii do). Computer comp moves the programmed points so the nose cuts the part line:

    1. each segment of the part line is shifted toward the tool by the nose radius (that is the line the nose
       CENTER follows), and the tip rides at (center - r in Z, center - r in X): in all, the line moved by
       s = r (n - (1, 1)), n = the unit normal on the tool's side
    2. each corner is where the two neighbouring shifted lines cross
    3. the first corner is taken against the part's front face (it is there: the profile starts at the front),
       and the last point just moves perpendicular - the pass stops where the contour stops, as the Haas example does

That reproduces the workbook's figures to 0.0001 (0.031 nose radius, 45 deg: 0.0183 in Z, 0.0366 on the diameter).

Coordinates are (z, r): Z along the spindle with the tool coming from +Z, r the radius, an OD tool outside (+r). An ID
is mirrored by the caller (r negated), the same way cam.py already works it, so everything here is an OD pass.
"""
from __future__ import annotations

import math

Pt = tuple[float, float]
EPS = 1e-9


def _dedupe(pts):
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > EPS:
            out.append((float(p[0]), float(p[1])))
    return out


def _unit(a: Pt, b: Pt) -> Pt:
    L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    return ((b[0] - a[0]) / L, (b[1] - a[1]) / L)


def _tool_side(u: Pt) -> Pt:
    """The unit normal pointing at the tool: toward +r, and for a face (no r component) toward +Z."""
    a, b = (-u[1], u[0]), (u[1], -u[0])                  # (z, r) components of the two perpendiculars
    return max((a, b), key=lambda n: n[1] + 1e-3 * n[0])


def _shift(n: Pt, r: float) -> Pt:
    """How far the tip's line sits from the part line: r (n - (1, 1))."""
    return (r * (n[0] - 1.0), r * (n[1] - 1.0))


def _cross(a: Pt, b: Pt) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _meet(a1: Pt, u1: Pt, a2: Pt, u2: Pt, fallback: Pt) -> Pt:
    """Where the line through a1 along u1 crosses the line through a2 along u2 (fallback when parallel)."""
    d = _cross(u1, u2)
    if abs(d) < 1e-9:
        return fallback
    t = _cross((a2[0] - a1[0], a2[1] - a1[1]), u2) / d
    return (a1[0] + t * u1[0], a1[1] + t * u1[1])


def tip_path(prof, r: float) -> list[Pt]:
    """The imaginary tip's path that makes a nose of radius r cut the OD profile `prof` [(z, r)], front first.
    r <= 0 gives the profile back unchanged."""
    pts = _dedupe(prof)
    if r <= 0 or len(pts) < 2:
        return pts
    n_seg = len(pts) - 1
    u = [_unit(pts[i], pts[i + 1]) for i in range(n_seg)]
    nrm = [_tool_side(x) for x in u]
    sh = [_shift(n, r) for n in nrm]
    # the part's front face (vertical at the first point, normal +Z) is the line the first corner is taken against
    face_u, face_s = (0.0, 1.0), _shift((1.0, 0.0), r)
    active = list(range(n_seg))

    def vertices(idx):
        """Tip points for the segments in idx: corners where neighbouring shifted lines cross."""
        first, last = idx[0], idx[-1]
        out = []
        a0 = (pts[first][0] + sh[first][0], pts[first][1] + sh[first][1])
        face_a = (pts[0][0] + face_s[0], pts[0][1] + face_s[1])
        out.append(_meet(face_a, face_u, a0, u[first], a0) if first == 0 else a0)
        for j in range(1, len(idx)):
            i0, i1 = idx[j - 1], idx[j]
            a_prev = (pts[i0][0] + sh[i0][0], pts[i0][1] + sh[i0][1])
            a_next = (pts[i1][0] + sh[i1][0], pts[i1][1] + sh[i1][1])
            out.append(_meet(a_prev, u[i0], a_next, u[i1], a_next))
        # the end: the last point shifted PERPENDICULAR to its segment only (the pass stops where the contour does)
        n = nrm[last]
        k = r * (1.0 - n[0] - n[1])
        out.append((pts[last + 1][0] + k * n[0], pts[last + 1][1] + k * n[1]))
        return out

    while True:                                           # drop segments the offset turned inside out (a concave
        verts = vertices(active)                          # radius smaller than the nose: the tool cannot go there)
        bad = next((j for j, i in enumerate(active)
                    if len(active) > 1 and (verts[j + 1][0] - verts[j][0]) * u[i][0]
                    + (verts[j + 1][1] - verts[j][1]) * u[i][1] < -1e-9), None)
        if bad is None:
            return verts
        active.pop(bad)


def compensate(moves, r: float, internal: bool = False):
    """A finish path's moves [(kind, (x radius, y, z))] with the imaginary tip's path in place of the part line.

    The shape cam.finish_toolpath makes: rapid out, rapid to the profile's start, feeds along the profile, a pull-off
    feed, rapid out and home. Only the profile's feeds change (and the start's X with the first of them); the
    approach Z, the pull-off size and the clearances stay as they are. Returns the moves unchanged for r <= 0.
    Raises ValueError for a path that isn't that shape."""
    if r <= 0:
        return list(moves)
    feeds = [i for i, (k, _p) in enumerate(moves) if k == "feed"]
    if len(feeds) < 3 or feeds != list(range(feeds[0], feeds[-1] + 1)) or feeds[0] < 1 or feeds[-1] + 1 >= len(moves):
        raise ValueError("this path has no profile pass to compensate")
    a, b = feeds[0], feeds[-1]
    sign = -1.0 if internal else 1.0                      # an ID is an OD pass in the mirror
    z_start = moves[a - 1][1][2]
    prof = [(moves[i][1][2], sign * moves[i][1][0]) for i in range(a, b)]     # the profile, without the pull-off
    pull = (moves[b][1][0] - moves[b - 1][1][0]) * sign                      # the pull-off's size (X and Z the same)
    tip = tip_path(prof, r)
    rl, zl = tip[-1][1], tip[-1][0]
    out = list(moves[:a - 1])
    out.append((moves[a - 1][0], (sign * tip[0][1], moves[a - 1][1][1], z_start)))    # above the first tip point
    out += [("feed", (sign * rr, 0.0, z)) for z, rr in tip]
    out.append(("feed", (sign * (rl + pull), 0.0, zl + abs(pull))))
    out += moves[b + 1:]
    return out
