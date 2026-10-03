"""G-code import, Phase 5: the outline fitted to lines and arcs, and the sketch + revolve built from it.

The pass criterion is geometric: every outline vertex within 2e-4" of the fitted piece, the sketch
closes into one profile, and the revolved solid's volume equals the outline's own volume
(V = pi * integral of r^2 dz) - a fit that dropped or invented a stretch would move it.

    python -m pytest -q tests/test_gcode_import_fit.py
"""
import math
from pathlib import Path

import pytest

pytest.importorskip("shapely")

from gsend_cad.core import profiles as pf                              # noqa: E402
from gsend_cad.gcode_import import keywords as kw                      # noqa: E402
from gsend_cad.gcode_import import operations, parse_program, tooling  # noqa: E402
from gsend_cad.gcode_import.build import build_document                # noqa: E402
from gsend_cad.gcode_import.fit import fit_outline, to_entities, ARC_TOL  # noqa: E402
from gsend_cad.gcode_import.reconstruct import Edge, Reconstruction, reconstruct  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "gcode"
TABLE = kw.defaults()
BAR = {"z0": "finished", "front": 0.03, "id": 0.0}
STEPPED = ("stepped_shaft.nc", {"z0": "finished", "front": 0.05, "id": 0.0, "od": 2.0, "length": 1.25})
ALL = [STEPPED,
       ("chamfer_nose.nc", dict(BAR, od=1.25, length=1.5)),
       ("drill_bore.nc", dict(BAR, od=1.5, length=1.5)),
       ("g71_pq.nc", dict(BAR, od=1.5, length=1.5)),
       ("turn_and_face.nc", dict(BAR, od=1.25, length=1.25)),
       ("groove.nc", dict(BAR, od=1.5, length=1.5)),
       ("g76_thread.nc", dict(BAR, od=1.5, length=1.5))]

# a G03 arc finishing the OD: the arc is programmed, so it is tessellated by the parser, not a 96-gon
ARC_PROGRAM = """%
O1 (ARC TEST)
G20 G40 G99
T0101 (OD ROUGH CNMG 432)
G50 S3000
G96 S400 M3
G0 X2.2 Z0.1
G1 X-0.03 Z0.1
G0 Z0.05
G1 Z0 F0.006
X1.0
Z-0.2
G3 X1.8 Z-0.6 R0.5
G1 Z-1.0
X2.1
G0 X2.2 Z0.1
G28 U0 W0
M30
%"""


def recon(source, stock):
    text = (FIXTURES / source).read_text() if source.endswith(".nc") else source
    program = parse_program(text)
    tools = tooling.build_tools(program, TABLE, None)
    ops = operations.build_operations(program, tools, TABLE, None, stock.get("id", 0.0))
    return reconstruct(program, tools, ops, stock, False)


def polygon_volume(edges):
    """Volume of the outline turned about the axis, from its edges alone."""
    return abs(sum(math.pi * (e.z1 - e.z0) * ((e.x0 / 2) ** 2 + (e.x0 / 2) * (e.x1 / 2) + (e.x1 / 2) ** 2) / 3.0
                   for e in edges))


def dist_to_prim(p, prim):
    if prim.kind == "arc":
        return abs(math.hypot(p[0] - prim.c[0], p[1] - prim.c[1]) - prim.r)
    (ax, ay), (bx, by) = prim.p, prim.q
    t = max(0.0, min(1.0, ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)))
    return math.hypot(p[0] - (ax + t * (bx - ax)), p[1] - (ay + t * (by - ay)))


@pytest.mark.parametrize("source,stock", ALL, ids=[a[0] for a in ALL])
def test_every_fixture_fits_and_closes_into_one_profile(source, stock):
    r = recon(source, stock)
    f = fit_outline(r.edges)
    assert f.ok and f.prims and f.max_dev <= ARC_TOL
    for a, b in zip(f.prims, f.prims[1:] + f.prims[:1]):
        assert a.q == b.p                                   # exact joins: the pieces chain with no gap
    for e in r.edges:                                       # nothing strays from what replaced it
        for p in ((e.z0, e.x0 / 2), (e.z1, e.x1 / 2)):
            assert min(dist_to_prim(p, pr) for pr in f.prims) <= ARC_TOL
    ents = to_entities(f)
    regions = pf.sketch_regions("sk1", ents)
    assert len(regions) == 1 and not regions[0].holes and len(regions[0].outer.ents) == len(ents)
    assert len(f.prims) < f.segments or f.segments <= 4     # it actually simplified


def test_a_nose_radius_becomes_one_true_arc_with_its_exact_centre():
    f = fit_outline(recon(*STEPPED).edges)
    arcs = [p for p in f.prims if p.kind == "arc" and abs(p.r - 1 / 32) < 1e-6]
    assert len(arcs) == 2                                   # the two inside corners, one 1/32 nose each
    assert sorted(round(p.c[0], 5) for p in arcs) == [-0.96875, -0.46875]
    assert sorted(round(p.c[1], 5) for p in arcs) == [0.53125, 0.78125]


def test_a_long_line_does_not_become_part_of_the_arc_that_starts_at_its_end():
    """The shoulder line then 24 chords of a 1/32 nose, tangent: a loose fit once read this as one R0.98 arc."""
    n, rc, c = 24, 1 / 32, (-0.46875, 0.53125)
    arc = [(c[0] + rc * math.cos(math.radians(-90 - 90 * i / n)), c[1] + rc * math.sin(math.radians(-90 - 90 * i / n)))
           for i in range(n + 1)]
    pts = [(0.0, 0.0), (0.0, 0.5), *arc, (-0.5, 0.0), (0.0, 0.0)]
    edges = [Edge(a[0], 2 * a[1], b[0], 2 * b[1], "EXACT") for a, b in zip(pts, pts[1:])]
    f = fit_outline(edges)
    assert f.ok and f.count("arc") == 1
    assert f.prims[[p.kind for p in f.prims].index("arc")].r == pytest.approx(rc, abs=1e-9)
    shoulder = [p for p in f.prims if p.kind == "line" and p.p == (0.0, 0.5)]
    assert len(shoulder) == 1 and shoulder[0].q == arc[0]                       # the shoulder line stayed whole


def test_a_programmed_arc_is_one_arc():
    r = recon(ARC_PROGRAM, dict(BAR, od=2.0, length=1.2))
    f = fit_outline(r.edges)
    big = [p for p in f.prims if p.kind == "arc" and p.r > 0.2]
    assert f.ok and len(big) == 1 and big[0].n > 20 and 0.4 < big[0].r < 0.5     # R0.5 less the nose radius


@pytest.mark.parametrize("source,stock", ALL[:3] + [(ARC_PROGRAM, dict(BAR, od=2.0, length=1.2))],
                         ids=["stepped", "chamfer", "bore", "arc"])
def test_the_revolved_solid_has_the_outlines_own_volume(source, stock):
    pytest.importorskip("build123d")
    from gsend_cad.kernel.model import Kernel
    r = recon(source, stock)
    b = build_document(r, "t")
    assert b.ok
    m = Kernel().build(b.doc)
    assert not m.errors and len(m.bodies) == 1
    assert m.bodies[0].shape.volume == pytest.approx(polygon_volume(r.edges), rel=1e-4)
    bb = m.bodies[0].shape.bounding_box()                   # spindle axis is the document's X axis, X = lathe Z
    assert (bb.min.X, bb.max.X) == pytest.approx((r.z_min, r.z_max), abs=1e-4)
    assert max(bb.max.Y, bb.max.Z) == pytest.approx(r.max_dia / 2, abs=1e-4)


def test_the_document_is_a_profile_sketch_and_a_revolve_about_x():
    b = build_document(recon(*STEPPED), "Shaft")
    assert [f["kind"] for f in b.doc.features] == ["sketch", "revolve"]
    sketch, rev = b.doc.features
    assert (sketch["name"], sketch["plane_z"]) == ("Profile", 0.0) and "plane" not in sketch
    assert rev["axis"] == {"sketch": sketch["id"], "kind": "x"} and rev["angle"] == 360.0 and rev["op"] == "join"
    assert {e["type"] for e in sketch["ents"]} == {"line", "arc"}
    assert {e["src"] for e in sketch["ents"]} == {"EXACT", "STOCK", "AXIS"}      # Phase 6 reads these


def test_the_axis_and_uncut_stock_keep_their_tags_and_are_never_merged_into_cut_lines():
    f = fit_outline(recon(*STEPPED).edges)
    assert [p.tag for p in f.prims if p.tag == "AXIS"] == ["AXIS"]
    assert sum(1 for p in f.prims if p.tag == "STOCK") == 2
    # one straight cylinder at r = 0.5 in four collinear edges: two cut (EXACT), two uncut (STOCK)
    pts = [(0.0, 0.0), (0.0, 0.5), (-0.5, 0.5), (-1.0, 0.5), (-1.5, 0.5), (-2.0, 0.5), (-2.0, 0.0), (0.0, 0.0)]
    tags = ["EXACT", "EXACT", "EXACT", "STOCK", "STOCK", "STOCK", "AXIS"]
    g = fit_outline([Edge(a[0], 2 * a[1], b[0], 2 * b[1], t) for a, b, t in zip(pts, pts[1:], tags)])
    cyl = sorted((p for p in g.prims if p.p[1] == 0.5 and p.q[1] == 0.5), key=lambda p: -p.p[0])
    assert [(p.tag, p.n) for p in cyl] == [("EXACT", 2), ("STOCK", 2)]       # merged within a tag, never across
    assert cyl[0].q == cyl[1].p == (-1.0, 0.5) and len(g.prims) == 5


def test_an_outline_walked_the_other_way_gives_the_same_part():
    r = recon(*STEPPED)
    rev = [Edge(e.z1, e.x1, e.z0, e.x0, e.tag, e.tool) for e in reversed(r.edges)]
    a, b = fit_outline(r.edges), fit_outline(rev)
    assert b.ok and (a.count("line"), a.count("arc")) == (b.count("line"), b.count("arc"))
    assert not any(p.ccw for p in b.prims if p.kind == "arc") or any(p.ccw != q.ccw for p, q in
                                                                     zip(b.prims, a.prims) if p.kind == "arc")
    assert len(pf.sketch_regions("sk1", to_entities(b))) == 1


def test_failures_say_what_is_wrong_and_build_nothing():
    gap = [Edge(0, 0, 0, 1, "EXACT"), Edge(0, 1, -1, 1, "EXACT"), Edge(-1, 1, -1, 0, "EXACT"), Edge(-1.5, 0, 0, 0, "AXIS")]
    f = fit_outline(gap)
    assert not f.ok and "closed" in f.error
    assert not fit_outline(gap[:2]).ok
    bad = Reconstruction(ok=False, error="nothing is left of the stock")
    b = build_document(bad)
    assert not b.ok and "nothing is left of the stock" in b.error and b.doc is None


# ---- Phase 6: clean, round values; ASSUMED pieces are never touched ----
def _box(dz=0.0, dd=0.0, tags=("EXACT", "EXACT", "EXACT", "AXIS")):
    """A plain turned part (dia 1.5 x 1.2 long) whose far corner carries dust: dz in Z, dd in diameter."""
    pts = [(0.0, 0.0), (0.0, 1.5), (-1.2 + dz, 1.5 + dd), (-1.2 + dz, 0.0), (0.0, 0.0)]
    return [Edge(a[0], a[1], b[0], b[1], t) for a, b, t in zip(pts, pts[1:], tags)]


def test_dust_is_cleaned_to_the_programs_resolution():
    f = fit_outline(_box(dz=-1.2e-6, dd=8e-7))              # Z-1.2000012 and dia 1.5000008
    zs = sorted({round(v, 12) for p in f.prims for v in (p.p[0], p.q[0])})
    assert zs == [-1.2, 0.0] and f.snapped >= 1
    assert sorted({round(2 * v, 12) for p in f.prims for v in (p.p[1], p.q[1])}) == [0.0, 1.5]
    assert f.max_dev <= 2e-6                                # the dust was all that moved
    assert len(pf.sketch_regions("sk", to_entities(f))) == 1  # still one closed profile


def test_a_real_number_that_is_not_on_the_grid_is_left_alone():
    """Z-0.46875 (a nose radius's tangent point) is 5e-5 from the nearest 1e-4: a value, not dust."""
    n, rc, c = 24, 1 / 32, (-0.46875, 0.53125)
    arc = [(c[0] + rc * math.cos(math.radians(-90 - 90 * i / n)), c[1] + rc * math.sin(math.radians(-90 - 90 * i / n)))
           for i in range(n + 1)]
    pts = [(0.0, 0.0), (0.0, 0.5), *arc, (-0.5, 0.0), (0.0, 0.0)]
    f = fit_outline([Edge(a[0], 2 * a[1], b[0], 2 * b[1], "EXACT") for a, b in zip(pts, pts[1:])])
    a = next(p for p in f.prims if p.kind == "arc")
    assert a.p == pytest.approx((-0.46875, 0.5), abs=1e-12) and a.r == pytest.approx(1 / 32, abs=1e-12)


def test_an_arc_radius_a_hair_off_snaps_to_its_round_value():
    n, rc, c = 24, 0.0312496, (-0.46875, 0.53125)           # a radius 4e-7 under 1/32
    arc = [(c[0] + rc * math.cos(math.radians(-90 - 90 * i / n)), c[1] + rc * math.sin(math.radians(-90 - 90 * i / n)))
           for i in range(n + 1)]
    pts = [(0.0, 0.0), (0.0, 0.5), *arc, (-0.5, 0.0), (0.0, 0.0)]
    f = fit_outline([Edge(a[0], 2 * a[1], b[0], 2 * b[1], "EXACT") for a, b in zip(pts, pts[1:])])
    assert next(p for p in f.prims if p.kind == "arc").r == 0.03125


def test_an_assumed_piece_and_the_corners_it_touches_are_never_rounded():
    f = fit_outline(_box(dz=-1.2e-6, dd=8e-7, tags=("EXACT", "ASSUMED", "EXACT", "AXIS")))
    assumed = next(p for p in f.prims if p.tag == "ASSUMED")
    assert assumed.q[0] == -1.2 + -1.2e-6 and assumed.p[1] * 2 == pytest.approx(1.5)      # its own end points untouched
    assert f.assumed == 1
    ents = to_entities(f)
    assert sum(1 for e in ents if e["src"] == "ASSUMED") == 1 and len(pf.sketch_regions("sk", ents)) == 1


def test_no_grid_leaves_the_fit_as_the_outline_gave_it():
    f = fit_outline(_box(dz=-1.2e-6, dd=8e-7), grid=None)
    assert f.snapped == 0 and min(p.p[0] for p in f.prims) == pytest.approx(-1.2000012, abs=1e-12)


def test_a_metric_program_snaps_to_its_own_resolution():
    mm = 0.001 / 25.4                                       # 0.001 mm in inches
    z = -10.0 / 25.4                                        # Z-10 mm
    dust = z + 1e-7 / 25.4                                  # 1e-7 mm of dust
    pts = [(0.0, 0.0), (0.0, 1.0), (dust, 1.0), (dust, 0.0), (0.0, 0.0)]
    f = fit_outline([Edge(a[0], a[1], b[0], b[1], "EXACT") for a, b in zip(pts, pts[1:])], grid=mm)
    assert min(p.p[0] for p in f.prims) == pytest.approx(-10.0 / 25.4, abs=1e-12) and f.snapped >= 1


def test_snapping_keeps_every_fixture_closed_and_within_tolerance():
    for source, stock in ALL:
        r = recon(source, stock)
        f = fit_outline(r.edges)
        assert f.ok and f.max_dev <= ARC_TOL
        for a, b in zip(f.prims, f.prims[1:] + f.prims[:1]):
            assert a.q == b.p
        assert len(pf.sketch_regions("sk", to_entities(f))) == 1


def test_the_summary_says_what_was_cleaned_and_what_is_only_assumed():
    from gsend_cad.gcode_import.recon_page import fit_text
    f = fit_outline(_box(dz=-1.2e-6, dd=8e-7, tags=("EXACT", "ASSUMED", "EXACT", "AXIS")))
    text = fit_text(Reconstruction(edges=_box()), f)
    assert "ASSUMED" in text and "never rounded" in text