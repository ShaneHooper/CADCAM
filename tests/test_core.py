import math

import pytest

from gsend_cad.core import Document, bracket_plate, region_at, sketch_regions
from gsend_cad.core import sketch as sk


def test_rect_with_circle_inside_makes_two_regions():
    ents = [sk.rect((0, 0), (2, 1)), sk.circle((1, 0.5), 0.25)]
    regs = sketch_regions("s", ents)
    assert len(regs) == 2
    outer = region_at(regs, (0.1, 0.1))
    inner = region_at(regs, (1, 0.5))
    assert outer.outer.ents == [0] and [h.ents for h in outer.holes] == [[1]]
    assert inner.outer.ents == [1] and inner.holes == []
    assert outer.area == pytest.approx(2 - math.pi * 0.0625, rel=1e-2)


def test_closed_line_chain_is_a_profile_and_open_chain_is_not():
    tri = [sk.line((0, 0), (1, 0)), sk.line((1, 0), (0.5, 1)), sk.line((0.5, 1), (0, 0))]
    assert [r.outer.ents for r in sketch_regions("s", tri)] == [[0, 1, 2]]
    assert sketch_regions("s", tri[:2]) == []


def test_circle_touching_rect_edge_is_still_a_hole():
    ents = [sk.rect((0, 0), (2, 2)), sk.circle((1, 1), 1.0)]
    outer = next(r for r in sketch_regions("s", ents) if r.outer.ents == [0])
    assert [h.ents for h in outer.holes] == [[1]]


def test_add_inserts_at_marker_and_roundtrips(tmp_path):
    doc = bracket_plate()
    assert [f["name"] for f in doc.features] == ["Sketch1", "Extrude1", "Sketch2", "Extrude2", "Hole1", "Hole2"]
    doc.set_marker(2)
    s = doc.add_sketch([sk.circle((1, 0), 0.2)])
    assert doc.features[2] is s and doc.marker == 3 and s["name"] == "Sketch3"
    p = tmp_path / "part.gcad"
    doc.save(p)
    back = Document.load(p)
    assert back.to_dict() == doc.to_dict()


def test_consumed_sketches_follow_marker():
    doc = bracket_plate()
    s1, s2 = doc.features[0]["id"], doc.features[2]["id"]
    assert doc.consumed_sketches() == {s1, s2}
    doc.set_marker(1)
    assert doc.consumed_sketches() == set()


def test_bad_extrude_rejected():
    doc = Document()
    with pytest.raises(ValueError):
        doc.add_extrude([], 1.0)
    with pytest.raises(ValueError):
        doc.add_extrude([{"sketch": "x", "outer": [0], "holes": []}], 0.0)


def test_edit_sketch_keeps_extrude_refs_and_breaks_deleted_ones():
    doc = Document()
    s = doc.add_sketch([sk.rect((0, 0), (2, 1)), sk.circle((1, 0.5), 0.25)])
    ring = next(r for r in sketch_regions(s["id"], s["ents"]) if r.outer.ents == [0])
    e = doc.add_extrude([ring], 0.5)
    # delete nothing, add a shape: refs unchanged
    doc.update_sketch(s["id"], s["ents"] + [sk.circle((5, 5), 0.1)], 0.25, [0, 1, None])
    assert e["profiles"][0]["outer"] == [0] and e["profiles"][0]["holes"] == [[1]]
    assert doc.feature(s["id"])["plane_z"] == 0.25
    # delete the rect (index 0): the circle moves to index 0 and the ring's outer is gone
    ents = doc.feature(s["id"])["ents"]
    doc.update_sketch(s["id"], ents[1:], 0.25, [1, 2])
    assert e["profiles"][0]["outer"] == [-1] and e["profiles"][0]["holes"] == [[0]]


def test_sketch_visibility_default_and_override(tmp_path):
    doc = bracket_plate()
    s1 = doc.features[0]
    assert not doc.sketch_shown(s1)            # used by Extrude1: hidden like Fusion
    s1["show"] = True
    assert doc.sketch_shown(s1)
    p = tmp_path / "v.gcad"
    doc.save(p)
    assert Document.load(p).sketch_shown(Document.load(p).features[0])
    s3 = doc.add_sketch([sk.circle((0, 0), 1)])
    assert doc.sketch_shown(s3)
    s3["show"] = False
    assert not doc.sketch_shown(s3)
