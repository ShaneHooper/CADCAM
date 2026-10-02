"""Exact 2D polygon booleans for the reconstruction. The ONLY file that imports shapely.

Everything else in the module passes plain (z, r) point lists in and gets opaque geometry
handles or point lists back, so the library behind this file can be swapped (pyclipper is
the candidate) without touching the reconstruction.

Shapely is BSD 3-clause and bundles GEOS (LGPL 2.1); see Help > Open-source licences.
"""
from __future__ import annotations

try:
    from shapely import STRtree  # noqa: F401  (import check only)
    from shapely.geometry import LineString, MultiPoint, Point, Polygon
    from shapely.geometry import box as _box
    from shapely.ops import unary_union
    AVAILABLE, WHY_NOT = True, ""
except Exception as exc:        # not installed, or its DLLs are blocked: Steps 1-3 still work
    AVAILABLE, WHY_NOT = False, f"{type(exc).__name__}: {exc}"

Pt = tuple[float, float]


def need():
    if not AVAILABLE:
        raise RuntimeError("The reconstruction needs the 'shapely' library, which this copy does not have "
                           f"({WHY_NOT}). Steps 1-3 work without it.")


def rect(z0: float, r0: float, z1: float, r1: float):
    return _box(min(z0, z1), min(r0, r1), max(z0, z1), max(r0, r1))


def polygon(points: list[Pt]):
    return Polygon(points)


def hull(points: list[Pt]):
    """Convex hull: for a convex tool shape at two positions, exactly the area it sweeps between them."""
    return MultiPoint(points).convex_hull


def union(geoms: list):
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    return unary_union(geoms) if geoms else Polygon()


def subtract(a, b):
    return a if b is None or b.is_empty else a.difference(b)


def clean(g, tol: float = 2e-7):
    """Drop slivers and merge collinear points left by the booleans (well under the fit tolerance)."""
    g = g.buffer(0)
    return g.simplify(tol, preserve_topology=True)


def area(g) -> float:
    return g.area


def is_empty(g) -> bool:
    return g is None or g.is_empty


def pieces(g) -> list:
    """The separate polygons of a result (a part-off leaves two), largest first."""
    polys = [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon" and p.area > 1e-9]
    return sorted(polys, key=lambda p: -p.area)


def bounds(g) -> tuple[float, float, float, float]:
    """(z_min, r_min, z_max, r_max)"""
    return g.bounds


def ring(poly) -> list[Pt]:
    """The outline of one polygon, closed (first point repeated), counter-clockwise."""
    from shapely.geometry.polygon import orient
    return [(float(z), float(r)) for z, r in orient(poly, 1.0).exterior.coords]


def holes(poly) -> int:
    return len(poly.interiors)


def boundary_distance(g, p: Pt) -> float:
    """Distance from a point to the outline of a geometry (large when the geometry is empty)."""
    if is_empty(g):
        return 1e9
    return g.boundary.distance(Point(p))


def shrink(g, d: float):
    return g.buffer(-d)


def length_inside(g, a: Pt, b: Pt) -> float:
    """How much of the segment a-b lies inside the geometry."""
    if is_empty(g) or a == b:
        return 0.0
    return LineString([a, b]).intersection(g).length


def offset_path(points: list[Pt], d: float) -> list[list[Pt]]:
    """The path moved sideways by d: [left of travel, right of travel]. Round joins, so an
    outside corner rolls round it the way a nose radius does."""
    line = LineString(points)
    out = []
    for sign in (1.0, -1.0):
        off = line.offset_curve(sign * d, quad_segs=16, join_style="round")
        parts = [p for p in getattr(off, "geoms", [off]) if not p.is_empty]
        out.append([(float(z), float(r)) for z, r in max(parts, key=lambda p: p.length).coords] if parts else [])
    return out


def cross_section_r(g, z: float) -> list[tuple[float, float]]:
    """(r_low, r_high) spans of material on the line Z = z."""
    if is_empty(g):
        return []
    zmin, rmin, zmax, rmax = g.bounds
    cut = LineString([(z, rmin - 1.0), (z, rmax + 1.0)]).intersection(g)
    spans = []
    for part in getattr(cut, "geoms", [cut]):
        if part.geom_type == "LineString" and part.length > 1e-9:
            rs = [c[1] for c in part.coords]
            spans.append((min(rs), max(rs)))
    return sorted(spans)
