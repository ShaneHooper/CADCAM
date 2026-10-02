"""G-code import, Phase 5: fit the outline to lines and arcs, build the sketch and the revolved body.

Pass criteria are ABSOLUTE: sizes within the 0.0005" fit tolerance, volumes within 0.001 in3.

    python -m pytest -q tests/test_gcode_import_build.py
"""
import math
from pathlib import Path

import pytest

pytest.importorskip("shapely")

from gsend_cad.core import Document                                   # noqa: E402
from gsend_cad.core import sketch as sk                               # noqa: E402
from gsend_cad.gcode_import import build as B                         # noqa: E402
from gsend_cad.gcode_import.fit import check, fit_outline             # noqa: E402
from gsend_cad.gcode_import.reconstruct import Edge, Reconstruction   # noqa: E402

from test_gcode_import_reconstruct import BAR, run                    # noqa: E402

TOL = 0.0005
CASES = {
    "turn_and_face.nc": dict(BAR, od=1.25, length=1.25),
    "stepped_shaft.nc": dict(BAR, od=2.25, length=1.25),
    "chamfer_nose.nc": dict(BAR, od=1.25, length=1.25),
    "groove.nc": dict(BAR, od=1.25, length=1.25),
    "g71_pq.nc": dict(BAR, od=2.0, length=2.0),
    "drill_bore.nc": dict(BAR, od=2.0, length=2.0),
    "g76_thread.nc": dict(BAR, od=1.75, length=1.25),
    "multi_tool.nc": dict(BAR, od=2.0, length=2.0),
}


def pappus(edges):
    """Volume of the outline spun about the centerline (independent of the fit and of the kernel)."""
    pts = [(e.x0 / 2, e.z0) for e in edges]
    area = moment = 0.0
    for i in range(len(pts)):
        (x0, y0), (x1, y1) = pts[i - 1], pts[i]
        cr = x0 * y1 - x1 * y0
        area += cr / 2
        moment += (x0 + x1) * cr / 6
    return 2 * math.pi * abs(moment)


def rec_edges(*pts, tag="EXACT"):
    """A closed Reconstruction outline from (z, diameter) points."""
    ring = list(pts) + [pts[0]]
    return [Edge(a[0], a[1], b[0], b[1], tag, "01") for a, b in zip(ring, ring[1:])]


# ---- the fitter on made-up outlines with known answers ----
def test_a_sampled_arc_comes_back_as_one_arc_of_the_right_radius():
    R, c = 0.25, (0.6, -0.5)                     # (u, v) centre; a quarter circle bulging out
    pts = [(c[0] + R * math.cos(math.radians(a)), c[1] + R * math.sin(math.radians(a))) for a in range(-90, 1, 5)]
    z_d = [(v, 2 * u) for u, v in pts]            # (z, diameter) in outline order
    edges = rec_edges((-1.0, 0.0), *z_d, (0.0, 0.0))
    fit = fit_outline(edges)
    arcs = [s for s in fit.segs if s.kind == "arc"]
    assert len(arcs) == 1 and abs(arcs[0].r - R) < TOL
    assert abs(arcs[0].c[0] - c[0]) < TOL and abs(arcs[0].c[1] - c[1]) < TOL
    assert check(fit) == [] and fit.max_dev <= TOL


def test_a_long_straight_run_is_never_swallowed_by_the_arc_after_it():
    # a 0.7 long cylinder then a 1/32 blend: one line and one arc, and the cylinder stays exactly 0.5
    R, c = 1 / 32, (0.5 + 1 / 32, -0.72)
    blend = [(c[0] + R * math.cos(math.radians(a)), c[1] + R * math.sin(math.radians(a))) for a in range(180, 271, 5)]
    z_d = [(v, 2 * u) for u, v in blend]
    edges = rec_edges((0.0, 0.0), (0.0, 1.0), (-0.72, 1.0), *z_d[1:], (-0.75, 1.5), (-1.0, 1.5), (-1.0, 0.0))
    fit = fit_outline(edges)
    cyl = next(s for s in fit.segs if s.kind == "line" and s.a[0] == s.b[0] == 0.5)
    assert abs(cyl.a[1] - cyl.b[1]) > 0.7
    arcs = [s for s in fit.segs if s.kind == "arc"]
    assert len(arcs) == 1 and abs(arcs[0].r - R) < TOL


def test_three_points_are_a_corner_not_an_arc():
    fit = fit_outline(rec_edges((0.0, 0.0), (0.0, 1.0), (-0.5, 1.0), (-0.5, 0.0)))
    assert fit.arcs == 0 and fit.lines == 4


def test_two_shallow_edges_are_lines_not_an_arc():
    # three points always lie on some circle; only a run of four or more points is evidence of an arc
    p1 = (0.5, -0.5)
    p2 = (p1[0] + 0.3 * math.cos(math.radians(-82)), p1[1] + 0.3 * math.sin(math.radians(-82)))
    p3 = (p2[0] + 0.3 * math.cos(math.radians(-74)), p2[1] + 0.3 * math.sin(math.radians(-74)))
    to_zd = lambda p: (p[1], 2 * p[0])
    fit = fit_outline(rec_edges((0.0, 0.0), (0.0, 1.0), to_zd(p1), to_zd(p2), to_zd(p3), (p3[1], 0.0)))
    assert fit.arcs == 0 and fit.lines == 6


def test_near_level_and_near_plumb_lines_snap_exactly():
    fit = fit_outline(rec_edges((0.0, 0.0), (0.0003, 1.0), (-0.5, 1.0002), (-0.5, 0.0)))
    kinds = {c["type"] for c in fit.constraints}
    assert "horizontal" in kinds and "vertical" in kinds
    for s in fit.segs:
        assert s.a[0] == s.b[0] or s.a[1] == s.b[1]


# ---- every fixture ----
@pytest.mark.parametrize("name", sorted(CASES))
def test_fixture_fits_closes_and_stays_within_tolerance(name):
    r = run(name, CASES[name])
    assert r.ok
    b = B.build(r)
    assert B.verify(b) == []
    assert b.fit.max_dev <= TOL
    assert b.fit.lines + b.fit.arcs < len(r.edges)              # it really did reduce the outline
    u = [p[0] for e in b.ents for p in e["pts"]]
    v = [p[1] for e in b.ents for p in e["pts"]]
    assert min(u) == 0.0 and max(v) == 0.0                      # bottom on the centerline, front face on Z0


@pytest.mark.parametrize("name", sorted(CASES))
def test_fixture_makes_one_sketch_one_region_and_one_revolved_body(name):
    pytest.importorskip("build123d")
    from gsend_cad.kernel import Kernel
    r = run(name, CASES[name])
    b = B.build(r)
    doc = Document("t")
    ids = B.add_to_document(doc, b, "Imported part")
    model = Kernel().build(doc)
    assert model.errors == {} and len(model.bodies) == 1
    assert model.bodies[0].volume == pytest.approx(pappus(r.edges), abs=1e-3)
    (_, _, zlo), (_, _, zhi) = model.bodies[0].bbox()
    assert zhi == pytest.approx(0.0, abs=1e-6) and zlo == pytest.approx(r.z_min - r.z_max, abs=TOL)
    assert doc.feature(ids["revolve"])["op"] == "new" and doc.feature(ids["revolve"])["angle"] == 360.0


# ---- the numbers a machinist reads off the print ----
def test_straight_turn_gives_exact_diameters_and_a_nose_radius_blend():
    b = B.build(run("turn_and_face.nc", CASES["turn_and_face.nc"]))
    cyl = next(s for s in b.fit.segs if s.kind == "line" and s.a[0] == s.b[0] == 0.5 and s.tag == "EXACT")
    assert cyl.a[0] == 0.5                                      # the 1.000 diameter, not 1.0002
    arc = next(s for s in b.fit.segs if s.kind == "arc")
    assert arc.r == pytest.approx(1 / 32, abs=TOL)              # the CNMG 432's 1/32 nose, in the inside corner
    assert arc.tag == "EXACT"


def test_45_degree_chamfer_is_a_45_degree_line():
    b = B.build(run("chamfer_nose.nc", CASES["chamfer_nose.nc"]))
    slope = [s for s in b.fit.segs if s.kind == "line" and s.a[0] != s.b[0] and s.a[1] != s.b[1]]
    assert len(slope) == 1
    du, dv = slope[0].b[0] - slope[0].a[0], slope[0].b[1] - slope[0].a[1]
    assert abs(abs(du) - abs(dv)) < TOL
    assert slope[0].a[0] == pytest.approx(0.8366 / 2, abs=0.002)    # the nose offsets the cut 0.0129 outside the line


def test_a_defaulted_nose_radius_keeps_the_chamfer_assumed_and_the_straight_cuts_exact():
    text = (Path(__file__).parent / "fixtures" / "gcode" / "chamfer_nose.nc").read_text().replace(
        "(OD FINISH CNMG 432)", "(OD FINISH)")
    b = B.build(run(text, CASES["chamfer_nose.nc"]))
    tags = {(s.kind, s.tag) for s in b.fit.segs}
    assert ("line", "ASSUMED") in tags and ("line", "EXACT") in tags
    assert b.meta["assumed"] >= 1 and "ASSUMED" in b.meta["tags"]


def test_an_arc_never_mixes_exact_and_assumed_edges():
    text = (Path(__file__).parent / "fixtures" / "gcode" / "turn_and_face.nc").read_text().replace(
        "T0101 (OD FINISH CNMG 432)", "T0101 (OD FINISH)")
    b = B.build(run(text, CASES["turn_and_face.nc"]))
    for s in b.fit.segs:
        assert s.tag in ("EXACT", "ASSUMED", "STOCK", "AXIS")


def test_the_thread_callout_rides_along():
    b = B.build(run("g76_thread.nc", CASES["g76_thread.nc"]))
    assert len(b.meta["threads"]) == 1 and "16" in b.meta["threads"][0]


def test_tube_stock_makes_a_profile_that_leaves_the_bore_open():
    pytest.importorskip("build123d")
    from gsend_cad.kernel import Kernel
    r = run("turn_and_face.nc", dict(BAR, od=1.25, length=1.25, id=0.5))
    b = B.build(r)
    assert B.verify(b) == [] and "AXIS" not in b.meta["tags"]
    assert min(p[0] for e in b.ents for p in e["pts"]) == pytest.approx(0.25, abs=TOL)      # bore radius
    doc = Document("t")
    B.add_to_document(doc, b, "Tube")
    m = Kernel().build(doc)
    assert m.errors == {} and m.bodies[0].volume == pytest.approx(pappus(r.edges), abs=1e-3)


# ---- what goes into the document ----
def test_the_reference_sketch_is_hidden_locked_and_holds_the_raw_outline():
    r = run("stepped_shaft.nc", CASES["stepped_shaft.nc"])
    b = B.build(r)
    doc = Document("t")
    ids = B.add_to_document(doc, b, "Shaft")
    ref, prof = doc.feature(ids["reference"]), doc.feature(ids["profile"])
    assert ref["show"] is False and ref["locked"] is True and ref["reference"] is True
    assert len(ref["ents"]) == len(r.edges) and all(e["type"] == "line" for e in ref["ents"])
    assert prof["show"] is True and prof["imported"]["tolerance"] == TOL
    assert {c["type"] for c in prof["constraints"]} >= {"coincident", "horizontal", "vertical", "tangent"}


def test_the_sketch_is_on_the_xz_plane_and_revolves_about_the_spindle():
    from gsend_cad.core import plane as pl
    doc = Document("t")
    ids = B.add_to_document(doc, B.build(run("turn_and_face.nc", CASES["turn_and_face.nc"])), "P")
    fr = pl.of_feature(doc.feature(ids["profile"]))
    assert pl.to_world(fr, (0.5, -0.25)) == pytest.approx([0.5, 0.0, -0.25])     # radius along X, depth along Z
    assert doc.feature(ids["revolve"])["axis"] == {"sketch": ids["profile"], "kind": "y"}


def test_the_import_survives_save_and_load(tmp_path):
    doc = Document("t")
    ids = B.add_to_document(doc, B.build(run("groove.nc", CASES["groove.nc"])), "G")
    p = tmp_path / "g.gcad"
    doc.save(p)
    back = Document.load(p)
    prof = back.feature(ids["profile"])
    assert prof["constraints"] == doc.feature(ids["profile"])["constraints"]
    assert prof["imported"]["max_deviation"] <= TOL and back.feature(ids["reference"])["locked"] is True


def test_the_sketch_entities_are_ordinary_lines_and_arcs():
    b = B.build(run("stepped_shaft.nc", CASES["stepped_shaft.nc"]))
    assert {e["type"] for e in b.ents} == {"line", "arc"}
    for e in b.ents:
        if e["type"] == "arc":
            assert e["a1"] > e["a0"] and e["r"] > 0
            for q in e["pts"]:
                assert math.hypot(q[0] - e["c"][0], q[1] - e["c"][1]) == pytest.approx(e["r"], abs=1e-8)
    assert sk.entity_label(b.ents[0])                          # the sketch tools can read them


# ---- failures say why and leave the document alone ----
def test_a_failed_reconstruction_is_a_clear_error():
    with pytest.raises(B.BuildError, match="no material"):
        B.build(run("turn_and_face.nc", dict(BAR, od=0.5, length=1.25, id=0.75)))


def test_an_outline_that_is_not_one_region_is_refused_and_the_document_is_untouched():
    bowtie = Reconstruction(ok=True, z_max=0.0, edges=rec_edges((0.0, 0.0), (-1.0, 1.0), (0.0, 1.0), (-1.0, 0.0)))
    doc = Document("t")
    doc.add_sketch([sk.line((0, 0), (1, 0))], name="keep")
    before = doc.to_dict()
    with pytest.raises(B.BuildError, match="single region"):
        B.add_to_document(doc, B.build(bowtie), "Bad")
    assert doc.to_dict() == before


def test_a_too_small_outline_is_refused():
    with pytest.raises(B.BuildError, match="fewer than three"):
        B.build(Reconstruction(ok=True, z_max=0.0, edges=rec_edges((0.0, 0.0), (-1.0, 0.0))))
