import math

import pytest

from gsend_cad.core import Document, bracket_plate, sketch_regions
from gsend_cad.core import sketch as sk
from gsend_cad.kernel import Kernel

PLATE = 4 * 3 * 0.5 - 4 * (1 - math.pi / 4) * 0.25 ** 2 * 0.5
BOSS = math.pi * 0.625 ** 2 * 0.75
HOLES = 4 * math.pi * 0.133 ** 2 * 0.5
BORE = math.pi * 0.25 ** 2 * 1.25


@pytest.fixture(scope="module")
def kernel():
    return Kernel()


def test_bracket_plate_volume_and_bbox(kernel):
    m = kernel.build(bracket_plate())
    assert not m.errors
    assert len(m.bodies) == 1
    b = m.bodies[0]
    assert b.volume == pytest.approx(PLATE + BOSS - HOLES - BORE, rel=1e-4)
    assert b.size() == pytest.approx((4, 3, 1.25), abs=1e-6)
    assert b.mass("6061-T6") == pytest.approx(b.volume * 0.0975)


@pytest.mark.parametrize("n,vol", [(0, None), (1, None), (2, PLATE), (4, PLATE + BOSS), (5, PLATE + BOSS - HOLES)])
def test_rollback(kernel, n, vol):
    m = kernel.build(bracket_plate(), upto=n)
    if vol is None:
        assert m.bodies == []
    else:
        assert m.bodies[0].volume == pytest.approx(vol, rel=1e-4)


def test_cut_pocket_leaves_pin(kernel):
    doc = bracket_plate()
    s = doc.add_sketch([sk.rect((0.75, -0.75), (1.75, 0.75)), sk.circle((1.25, 0), 0.25)])
    ring = next(r for r in sketch_regions(s["id"], s["ents"]) if r.outer.ents == [0])
    doc.add_extrude([ring], 0.5, op="cut")
    m = kernel.build(doc)
    assert not m.errors
    removed = (1.0 * 1.5 - math.pi * 0.0625) * 0.5
    assert m.bodies[0].volume == pytest.approx(PLATE + BOSS - HOLES - BORE - removed, rel=1e-4)


def test_new_body_symmetric_and_negative(kernel):
    doc = bracket_plate()
    s = doc.add_sketch([sk.polygon((0, -2.5), (0.5, -2.5), 6)])
    doc.add_extrude(sketch_regions(s["id"], s["ents"]), 0.8, op="new", direction="sym")
    m = kernel.build(doc)
    assert [b.name for b in m.bodies] == ["Body1", "Body2"]
    (_, _, z0), (_, _, z1) = m.bodies[1].bbox()
    assert (z0, z1) == pytest.approx((-0.4, 0.4))
    doc2 = bracket_plate()
    s = doc2.add_sketch([sk.circle((0, -2.5), 0.3)])
    doc2.add_extrude(sketch_regions(s["id"], s["ents"]), -0.5, op="new")
    (_, _, z0), (_, _, z1) = kernel.build(doc2).bodies[1].bbox()
    assert (z0, z1) == pytest.approx((-0.5, 0.0))


def test_cut_that_misses_reports_error_but_model_survives(kernel):
    doc = bracket_plate()
    s = doc.add_sketch([sk.circle((10, 10), 0.3)])
    f = doc.add_extrude(sketch_regions(s["id"], s["ents"]), 0.5, op="cut")
    m = kernel.build(doc)
    assert f["id"] in m.errors and len(m.bodies) == 1


def test_step_export(kernel, tmp_path):
    p = tmp_path / "part.step"
    kernel.build(bracket_plate()).export_step(p)
    assert p.read_text(errors="ignore").startswith("ISO-10303-21")


def test_display_data(kernel):
    b = kernel.build(bracket_plate()).bodies[0]
    v, t = b.triangles()
    assert v.shape[1] == 3 and t.shape[1] == 3 and t.max() < len(v)
    assert len(b.edge_polylines()) > 10


def test_remove_feature_drops_a_body_and_renames_apply():
    from gsend_cad.core import bracket_plate
    from gsend_cad.core import sketch as sk
    doc = bracket_plate()
    s = doc.add_sketch([sk.circle((5, 0), 0.5)])
    doc.add_extrude([{"sketch": s["id"], "outer": [0], "holes": []}], 1.0, op="new")
    doc.body_names["body2"] = "Pin"
    k = Kernel()
    assert [b.name for b in k.build(doc).bodies] == ["Body1", "Pin"]
    doc.add_remove("body2")
    m = k.build(doc)
    assert [b.id for b in m.bodies] == ["body1"] and not m.errors
    doc.add_remove("body2")                 # already gone: that feature fails, model still builds
    m = k.build(doc)
    assert len(m.bodies) == 1 and doc.features[-1]["id"] in m.errors


# ---- sketches on a model face (core/plane.py frames through the kernel)
def test_extrude_from_a_side_face(kernel):
    """A circle sketched on the plate's +X face and extruded 0.5 grows the part along +X."""
    from gsend_cad.core import plane as pl
    from gsend_cad.kernel import planar_face_at, plane_edges
    doc = bracket_plate()
    m0 = kernel.build(doc)
    hit = planar_face_at(m0.bodies, (2.0, 0.3, 0.2))                 # a point on the +X side
    assert hit is not None
    body, face, fr = hit
    assert fr == pl.from_normal((2, 0, 0), (1, 0, 0)) and fr["origin"] == [2, 0, 0]
    assert planar_face_at(m0.bodies, (2.5, 0.3, 0.2)) is None         # off the part
    s = doc.add_sketch([sk.circle((0, 0.25), 0.2)], plane=fr)         # local (u, v): u = world Y, v = world Z
    doc.add_extrude(sketch_regions(s["id"], s["ents"]), 0.5, op="join")
    m = kernel.build(doc)
    assert not m.errors
    assert m.bodies[0].volume == pytest.approx(m0.bodies[0].volume + math.pi * 0.2 ** 2 * 0.5, rel=1e-4)
    (_, _, _), (x1, _, _) = m.bodies[0].bbox()
    assert x1 == pytest.approx(2.5)
    # the side face's in-plane edges, in sketch coordinates: the face is 0.5 tall (v) and, between
    # the two 0.25 corner radii, 2.5 wide (u); the corner arcs curve away and are not on the plane
    edges = plane_edges(m0.bodies, fr)
    assert edges and all(e["kind"] == "LINE" for e in edges) and len(edges) == 4
    us = [p[0] for e in edges for p in e["pts"]]
    vs = [p[1] for e in edges for p in e["pts"]]
    assert min(vs) == pytest.approx(0) and max(vs) == pytest.approx(0.5)
    assert min(us) == pytest.approx(-1.25) and max(us) == pytest.approx(1.25)


# ---- 2D corner fillet / chamfer, revolve, 3D edge fillet / chamfer
def _plate(ents, h=0.5):
    d = Document()
    s = d.add_sketch(ents)
    d.add_extrude([sketch_regions(s["id"], s["ents"])[0].to_data()], h)
    return d, s


def test_sketch_fillet_corner_extrudes_true_arc():
    ents, origin = sk.corner_op([sk.rect((0, 0), (2, 1))], [0], (2, 1), 0.25, "fillet", 0.05)
    d, _ = _plate(ents)
    m = Kernel().build(d)
    area = 2 - 0.25 ** 2 * (1 - math.pi / 4)
    assert not m.errors and abs(m.bodies[0].volume - area * 0.5) < 1e-6      # exact arc, not facets


def test_sketch_chamfer_and_edit_keeps_extrude():
    d, s = _plate([sk.rect((0, 0), (2, 1))])
    ents, origin = sk.corner_op(s["ents"], [0], (0, 0), 0.2, "chamfer", 0.05)
    d.update_sketch(s["id"], ents, 0.0, origin)                 # rect split into lines: extrude follows
    m = Kernel().build(d)
    assert not m.errors and abs(m.bodies[0].volume - (2 - 0.02) * 0.5) < 1e-6


def test_sketch_chamfer_horizontal_vertical_legs():
    d, s = _plate([sk.rect((0, 0), (2, 1))])
    ents, origin = sk.corner_op(s["ents"], [0], (2, 1), (0.5, 0.25), "chamfer", 0.05)
    assert sk.params(ents[-1]) == {"ch": 0.5, "cv": 0.25}
    ents, origin, i = sk.edit(ents, origin, len(ents) - 1, "cv", 1.0)   # uses up the right side
    ents, origin, i = sk.edit(ents, origin, i, "cv", 0.5)               # ... and brings it back
    d.update_sketch(s["id"], ents, 0.0, origin)
    m = Kernel().build(d)
    assert not m.errors and abs(m.bodies[0].volume - (2 - 0.125) * 0.5) < 1e-6


def test_revolve_about_sketch_y_axis():
    d = Document()
    s = d.add_sketch([sk.rect((1, 0), (2, 1))])
    d.add_revolve([sketch_regions(s["id"], s["ents"])[0].to_data()], {"sketch": s["id"], "kind": "y"})
    m = Kernel().build(d)
    assert not m.errors and abs(m.bodies[0].volume - 3 * math.pi) < 1e-6   # tube OD 4 ID 2 x 1


def test_revolve_about_a_line_and_half_turn():
    d = Document()
    s = d.add_sketch([sk.rect((0, 0), (1, 2)), sk.line((-1, 0), (-1, 1))])
    d.add_revolve([sketch_regions(s["id"], s["ents"])[0].to_data()],
                  {"sketch": s["id"], "kind": "line", "ent": 1}, angle=180)
    m = Kernel().build(d)
    assert not m.errors and abs(m.bodies[0].volume - math.pi * (4 - 1) * 2 / 2) < 1e-6


def test_revolve_crossing_axis_is_an_error():
    d = Document()
    s = d.add_sketch([sk.rect((-1, 0), (1, 1))])
    d.add_revolve([sketch_regions(s["id"], s["ents"])[0].to_data()], {"sketch": s["id"], "kind": "y"})
    assert Kernel().build(d).errors


def test_solid_fillet_and_chamfer_edges():
    from gsend_cad.kernel import edge_list
    d, _ = _plate([sk.rect((0, 0), (2, 1))], 1.0)
    k = Kernel()
    edges = edge_list(k.build(d).bodies)
    vertical = [e["mid"] for e in edges if abs(e["mid"][2] - 0.5) < 1e-9]
    assert len(vertical) == 4
    d.add_fillet(vertical, 0.25)
    m = k.build(d)
    assert not m.errors and abs(m.bodies[0].volume - (2 - 4 * 0.25 ** 2 * (1 - math.pi / 4))) < 1e-6
    d2, _ = _plate([sk.rect((0, 0), (2, 1))], 1.0)
    f = d2.add_fillet(vertical[:1], 0.2, op="chamfer")
    m2 = k.build(d2)
    assert f["name"] == "Chamfer1" and not m2.errors and abs(m2.bodies[0].volume - (2 - 0.02)) < 1e-6


def test_solid_fillet_too_big_is_an_error():
    from gsend_cad.kernel import edge_list
    d, _ = _plate([sk.rect((0, 0), (2, 1))], 1.0)
    edges = edge_list(Kernel().build(d).bodies)
    d.add_fillet([edges[0]["mid"]], 5.0)
    assert Kernel().build(d).errors


def test_max_radius_of_turned_part():
    from gsend_cad.kernel import max_radius
    d = Document()
    s = d.add_sketch([sk.rect((0, 0), (2, 0.75))])
    d.add_revolve([sketch_regions(s["id"], s["ents"])[0].to_data()], {"sketch": s["id"], "kind": "x"})
    r = max_radius(Kernel().build(d).bodies, (0, 0, 0), (1, 0, 0))
    assert abs(r - 0.75) < 1e-3


def test_outline_loops_grow_by_tool_radius():
    from gsend_cad.kernel import outline_loops
    loops = outline_loops(Kernel().build(bracket_plate()).bodies, 0.25)
    assert len(loops) == 1
    pts = loops[0]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert (min(xs), max(xs), min(ys), max(ys)) == pytest.approx((-2.25, 2.25, -1.75, 1.75), abs=1e-6)
    area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])) / 2)
    assert area == pytest.approx(15.5354, abs=2e-3)       # 4 x 3 rounded plate grown 0.25 all round


def test_model_snap_points():
    from gsend_cad.kernel import model_snap_points
    pts = model_snap_points(Kernel().build(bracket_plate()).bodies)
    kinds = {k for _p, k in pts}
    assert kinds == {"end", "mid", "center"}
    assert any(k == "center" and p[:2] == pytest.approx((0, 0)) for p, k in pts)   # the boss / bore center
    assert any(k == "end" and p == pytest.approx((-2, -1.25, 0.5)) for p, k in pts)     # side edge meets corner R
    assert any(k == "mid" and p == pytest.approx((-2, 0, 0.5)) for p, k in pts)          # middle of that side
