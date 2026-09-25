import math

import pytest

from gsend_cad.core import bracket_plate, sketch_regions
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
