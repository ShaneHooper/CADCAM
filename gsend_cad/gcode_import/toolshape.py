"""Tool shapes in the lathe's (Z, radius) plane, as convex point lists. Pure math, stdlib only.

Every shape is given relative to the point the reconstruction moves along a path:

    insert      the NOSE CENTRE   (tip_vector says where that is from the programmed point)
    drill       the drill point, on its axis
    groove      the programmed corner of the blade

zdir  +1: the tool body lies toward +Z (a right-hand tool, cutting toward the chuck); -1 mirrored
rdir  +1: the body lies toward +radius (OD work); -1 toward the centerline (ID work)
"""
from __future__ import annotations

import math

Pt = tuple[float, float]
CIRCLE_POINTS = 96              # a 1/32 nose drawn this fine is within 0.00002" of round
DRILL_POINT = 118.0
SPOT_POINT = 90.0
BODY = 6.0                      # how far a drill / blade body reaches behind its tip

# The holder decides how an insert sits. Leading-edge angle from the +Z axis, by insert angle:
# C/W 80 deg in a 95 deg holder (PCLN: 5 deg clear of a square shoulder, 5 deg end relief);
# D 55, V 35 and T 60 in a 93 deg holder (PDJN / SVJB / MTJN); S 90 at 45 deg (PSSN).
LEAD_BY_ANGLE = {80.0: 85.0, 55.0: 87.0, 35.0: 87.0, 60.0: 87.0, 90.0: 135.0}
DEFAULT_ANGLE = 80.0            # insert angle when none is known (the common CNMG / WNMG)
DEFAULT_EDGE = 0.5              # insert edge length when the size is not known


def circle(r: float, n: int = CIRCLE_POINTS) -> list[Pt]:
    return [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def tip_vector(nose_radius: float, zdir: int = 1, rdir: int = 1) -> Pt:
    """From the imaginary tool tip (the programmed point) to the nose centre."""
    return (zdir * nose_radius, rdir * nose_radius)


def insert(nose_radius: float, angle: float | None = None, edge: float | None = None,
           zdir: int = 1, rdir: int = 1, lead: float | None = None) -> list[Pt]:
    """A turning insert's corner: the nose circle and the two edges leaving it, about the nose centre.

    The convex hull of these points is the tool (the edges are tangent to the nose circle).
    A zero nose radius gives a sharp point."""
    eps = angle if angle else DEFAULT_ANGLE
    if angle == 0.0:                                    # round insert: the nose IS the insert
        return [(zdir * z, rdir * r) for z, r in circle(max(nose_radius, 1e-6))]
    a1 = math.radians(lead if lead is not None else LEAD_BY_ANGLE.get(eps, 87.0))
    a2 = a1 - math.radians(eps)
    mid = (a1 + a2) / 2.0
    back = nose_radius / math.sin(math.radians(eps) / 2.0)     # nose centre to the sharp corner
    apex = (-back * math.cos(mid), -back * math.sin(mid))
    length = min(max(edge or DEFAULT_EDGE, 0.25), 1.0)
    ends = [(apex[0] + length * math.cos(a), apex[1] + length * math.sin(a)) for a in (a1, a2)]
    pts = (circle(nose_radius) if nose_radius > 0 else [(0.0, 0.0)]) + ends
    return [(zdir * z, rdir * r) for z, r in pts]


def drill(diameter: float, point_angle: float = DRILL_POINT, zdir: int = 1) -> list[Pt]:
    """A drill about its point: cone, then the body reaching back toward +Z (zdir)."""
    r = diameter / 2.0
    cone = r / math.tan(math.radians(point_angle) / 2.0)
    return [(0.0, 0.0), (zdir * cone, r), (zdir * BODY, r), (zdir * BODY, -r), (zdir * cone, -r)]


def groove(width: float, corner_radius: float = 0.0, rdir: int = 1, zdir: int = 1, face: bool = False) -> list[Pt]:
    """A grooving / cutoff blade about its programmed corner.

    The programmed corner is the one on the chuck side at the cutting end; the blade is
    'width' wide toward +Z (zdir) and its body reaches away from the work (rdir). face=True
    turns it for a face groove: 'width' across the radius, body toward +Z."""
    rc = min(max(corner_radius, 0.0), width / 2.0)
    if rc > 0:
        arc = lambda cz, cr, a0: [(cz + rc * math.cos(a0 + math.pi / 2 * i / 8), cr + rc * math.sin(a0 + math.pi / 2 * i / 8))
                                  for i in range(9)]
        pts = arc(rc, rc, math.pi) + arc(width - rc, rc, 1.5 * math.pi) + [(width, BODY), (0.0, BODY)]
    else:
        pts = [(0.0, 0.0), (width, 0.0), (width, BODY), (0.0, BODY)]
    if face:                                            # swap the axes: width along r, body along Z
        return [(zdir * r, rdir * z) for z, r in pts]
    return [(zdir * z, rdir * r) for z, r in pts]
