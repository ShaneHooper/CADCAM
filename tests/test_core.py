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


def test_remove_features_keeps_marker_and_dependents():
    doc = bracket_plate()
    s1 = doc.features[0]
    assert [f["name"] for f in doc.dependents(s1["id"])] == ["Extrude1"]
    doc.set_marker(4)
    gone = doc.remove_features([s1["id"], doc.features[1]["id"]])
    assert [f["name"] for f in gone] == ["Sketch1", "Extrude1"]
    assert doc.marker == 2 and doc.features[1]["name"] == "Extrude2"


def test_body_names_roundtrip(tmp_path):
    doc = bracket_plate()
    doc.body_names["body1"] = "Base Plate"
    doc.add_remove("body1")
    assert doc.describe(doc.features[-1]) == "Remove Base Plate"
    p = tmp_path / "n.gcad"
    doc.save(p)
    assert Document.load(p).body_names == {"body1": "Base Plate"}


# ---- exact values from the origin (sketch palette fields)
def test_rect_params_and_edit():
    r = sk.rect((1, 1), (3, 2))
    assert sk.params(r) == {"x": 1, "y": 1, "w": 2, "h": 1, "cr": 0.0}
    r = sk.set_param(sk.set_param(r, "w", 2.5), "x", 0.5)
    assert r["pts"][0] == [0.5, 1] and r["pts"][2] == [3.0, 2]


def test_center_rect_positions_by_center():
    r = sk.center_rect((0, 0), (1, 0.5))
    assert sk.params(r)["x"] == 0 and sk.params(r)["w"] == 2
    r = sk.set_param(r, "x", 2)
    assert r["anchor"] == "center" and r["pts"][0] == [1.0, -0.5]


def test_line_length_and_angle_keep_start():
    ln = sk.set_param(sk.line((1, 1), (2, 1)), "len", 3)
    assert ln["pts"] == [[1, 1], [4.0, 1.0]]
    ln = sk.set_param(ln, "ang", 90)
    assert ln["pts"] == [[1, 1], [1.0, 4.0]]          # float noise rounded off


def test_circle_polygon_point_edit():
    c = sk.set_param(sk.circle((0, 0), 1), "dia", 0.5)
    assert c["r"] == 0.25
    pg = sk.set_param(sk.polygon((1, 1), (2, 1), 6), "sides", 8)
    assert len(pg["pts"]) == 8 and abs(sk.params(pg)["r"] - 1) < 1e-9
    assert sk.set_param(sk.point((1, 2)), "y", 3) == {"type": "point", "p": [1.0, 3.0]}


def test_bad_sizes_refused():
    for e, k in ((sk.circle((0, 0), 1), "dia"), (sk.rect((0, 0), (1, 1)), "w"), (sk.line((0, 0), (1, 0)), "len")):
        with pytest.raises(ValueError):
            sk.set_param(e, k, 0)


def test_dimensions_from_origin():
    texts = [d["text"] for d in sk.dimensions(sk.rect((1, 2), (3, 3)))]
    assert texts == ["X 1.0000", "Y 2.0000", "2.0000", "1.0000"]
    assert [d["text"] for d in sk.dimensions(sk.circle((0, 0), 1))] == ["Ø 2.0000"]   # at origin: no X/Y


def test_every_dimension_names_the_value_it_shows():
    """A right-click on a dimension edits params(e)[key]; the key must exist and match the text."""
    for e in (sk.rect((1, 2), (3, 3)), sk.circle((0.5, 0), 1), sk.line((1, 1), (3, 2)),
              sk.polygon((1, 1), (2, 1), 6), sk.point((2, 3))):
        for d in sk.dimensions(e):
            assert d["key"] in sk.params(e), d
            assert sk.fmt(sk.params(e)[d["key"]]) in d["text"], d
    assert [d["key"] for d in sk.dimensions(sk.rect((1, 2), (3, 3)))] == ["x", "y", "w", "h"]
    assert [d["key"] for d in sk.dimensions(sk.circle((0, 0), 1))] == ["dia"]


def test_a_right_click_finds_the_dimension_under_it():
    c = sk.circle((0.5, 0), 1)                       # X dim below, Ø dim across the middle
    assert sk.dimension_at(c, (0.5, 0.1), 0.05)["key"] == "dia"      # on the Ø label
    assert sk.dimension_at(c, (0.25, -1.3), 0.05)["key"] == "x"      # on the X dimension line
    assert sk.dimension_at(c, (3, 3), 0.05) is None                  # nowhere near
    assert sk.dimension_at(sk.circle((0, 0), 1), (0.0, 0.15), 0.05)["key"] == "dia"


def test_points_are_not_profiles_and_pick():
    ents = [sk.rect((0, 0), (2, 2)), sk.point((1, 1))]
    assert len(sketch_regions("s", ents)) == 1
    assert sk.nearest(ents, (2.02, 1), 0.05) == 0
    assert sk.nearest(ents, (1.01, 1), 0.05) == 1
    assert sk.nearest(ents, (1.5, 1.5), 0.05) is None


# ---- sketch planes (core/plane.py) and snap points
from gsend_cad.core import plane as pl  # noqa: E402


def test_xy_plane_is_the_old_plane_z():
    fr = pl.xy(0.5)
    assert pl.is_xy(fr) and pl.height(fr) == 0.5 and pl.label(fr) == "XY plane Z 0.500"
    assert pl.to_world(fr, (1, 2)) == [1, 2, 0.5] and pl.to_local(fr, (1, 2, 0.5)) == (1, 2)
    assert pl.of_feature({"plane_z": 0.25}) == pl.xy(0.25)              # a file from before planes


def test_face_planes_read_left_to_right_and_up():
    """y is world Z (up) on any side face; x follows so x × y = n; the origin is the world
    origin projected onto the plane, so 'from origin' means the same thing on every face."""
    right = pl.from_normal((4, 1.5, 0.2), (1, 0, 0))
    assert right["origin"] == [4, 0, 0] and right["y"] == [0, 0, 1] and right["x"] == [0, 1, 0]
    left = pl.from_normal((0, 0, 0), (-1, 0, 0))
    assert left["y"] == [0, 0, 1] and left["x"] == [0, -1, 0]           # mirrored, seen from the left
    front = pl.from_normal((1, -1.5, 0), (0, -1, 0))
    assert front["x"] == [1, 0, 0] and front["y"] == [0, 0, 1] and front["origin"] == [0, -1.5, 0]
    top = pl.from_normal((3, 3, 1.25), (0, 0, 1))
    assert top == pl.xy(1.25) and pl.is_xy(top)
    bottom = pl.from_normal((0, 0, 0), (0, 0, -1))
    assert bottom["y"] == [0, 1, 0] and bottom["x"] == [-1, 0, 0]
    for fr in (right, left, front, bottom):
        x, y, n = fr["x"], fr["y"], fr["n"]
        assert [round(v, 9) for v in pl._cross(x, y)] == n
        assert pl.to_local(fr, pl.to_world(fr, (0.7, -0.3))) == pytest.approx((0.7, -0.3))
    assert pl.label(right) == "face plane · +X 4.000 in"
    assert pl.height(pl.offset(right, 0.5)) == 4.5


def test_snap_points_ends_mids_centers():
    pts = sk.snap_points([sk.line((0, 0), (2, 0)), sk.circle((1, 1), 0.5), sk.rect((3, 3), (5, 4))])
    kinds: dict = {}
    for u, v, k in pts:
        kinds.setdefault((u, v), set()).add(k)
    assert kinds[(0, 0)] == {"origin", "end"} and kinds[(2, 0)] == {"end"} and kinds[(1, 0)] == {"mid"}
    assert kinds[(1, 1)] == {"center"} and kinds[(1.5, 1)] == {"quad"}
    assert kinds[(3, 3)] == {"end"} and kinds[(4, 3)] == {"mid"} and kinds[(4, 3.5)] == {"center"}
    assert sk.nearest_snap(pts, (1.98, 0.03), 0.05) == (2, 0, "end")
    assert sk.nearest_snap(pts, (1.5, 0.5), 0.05) is None
    # the origin and a line end at the same spot: the end wins (a real vertex to build on)
    assert sk.nearest_snap(pts, (0.01, 0.0), 0.05)[2] == "end"
    edges = [{"pts": [[0, 0], [0, 2]], "kind": "LINE", "center": None},
             {"pts": [[1, 0], [1.5, 0.5], [1, 1]], "kind": "CIRCLE", "center": [1, 0.5]}]
    ek = {(u, v): k for u, v, k in sk.edge_snap_points(edges)}
    assert ek[(0, 2)] == "end" and ek[(0.0, 1.0)] == "mid" and ek[(1, 0.5)] == "center" and ek[(1.5, 0.5)] == "mid"


def test_document_keeps_a_face_plane_and_describes_it():
    doc = Document("t")
    fr = pl.from_normal((2, 0, 0), (1, 0, 0))
    s = doc.add_sketch([sk.circle((0, 0.25), 0.2)], plane_z=0.0, plane=fr)
    assert s["plane"] == fr and Document.sketch_plane(s) == fr
    assert doc.describe(s) == "1 entities · face plane · +X 2.000 in"
    xy = doc.add_sketch([sk.circle((0, 0), 1)], plane_z=0.5, plane=pl.xy(0.5))
    assert "plane" not in xy and doc.describe(xy) == "1 entities · XY plane Z 0.500"   # old shape kept
    doc.update_sketch(s["id"], s["ents"], 0.0, plane=pl.xy(0.0))
    assert "plane" not in doc.feature(s["id"])


# ---- CAM setups
def test_setup_defaults_and_document_roundtrip():
    from gsend_cad.core import cam
    d = Document()
    a = d.add_setup(cam.new_setup("milling"))
    b = d.add_setup(cam.new_setup("turning"))
    assert (a["id"], a["name"], b["name"]) == ("setup1", "Setup1", "Setup2")
    d2 = Document.from_dict(d.to_dict())
    assert [s["type"] for s in d2.setups] == ["milling", "turning"]
    d2.remove_setup("setup1")
    assert [s["id"] for s in d2.setups] == ["setup2"]
    with pytest.raises(ValueError):
        cam.new_setup("mill")


def test_milling_stock_and_wcs():
    from gsend_cad.core import cam
    s = cam.new_setup("milling")
    box = ((0, 0, 0), (4, 3, 0.5))
    lo, hi = cam.stock_box(box, s)
    assert lo == pytest.approx((-0.1, -0.1, 0.0)) and hi == pytest.approx((4.1, 3.1, 0.55))
    assert cam.wcs(box, s)["origin"] == pytest.approx([2.0, 1.5, 0.55])
    s["wcs"] = "top-corner"
    assert cam.wcs(box, s)["origin"] == pytest.approx([-0.1, -0.1, 0.55])


def test_turning_stock_and_wcs():
    from gsend_cad.core import cam
    box = ((-1, -1, 0), (1, 1, 3))                    # Ø2 x 3 long along Z
    assert cam.guess_axis(box) == "z"
    s = cam.new_setup("turning")
    c = cam.stock_cylinder(box, 1.0, s)
    assert abs(c["r"] - 1.05) < 1e-12 and abs(c["length"] - 3.55) < 1e-12 and c["front"] == [0.0, 0.0, 3.05]
    w = cam.wcs(box, s, 1.0)
    assert w["origin"] == [0.0, 0.0, 3.05] and w["z"] == [0.0, 0.0, 1.0]
    s["wcs"], s["front"] = "part-face", "-"
    w = cam.wcs(box, s, 1.0)
    assert w["origin"] == [0.0, 0.0, 0] and w["z"] == [0.0, 0.0, -1.0]


def test_fixed_size_stock():
    from gsend_cad.core import cam
    box = ((0, 0, 0), (4, 3, 0.5))
    s = cam.new_setup("milling")
    s["stock"] = cam.size_from_offsets(box, s)                       # 4.2 x 3.2 x .55 -> 1/8 up
    assert (s["stock"]["x"], s["stock"]["y"], s["stock"]["z"]) == (4.25, 3.25, 0.625)
    lo, hi = cam.stock_box(box, s)
    assert lo == pytest.approx((-0.125, -0.125, -0.075)) and hi == pytest.approx((4.125, 3.125, 0.55))
    assert cam.fits(box, s) is None
    s["stock"]["x"] = 3.9
    assert "X" in cam.fits(box, s)
    t = cam.new_setup("turning")
    tb = ((-1, -1, 0), (1, 1, 3))
    t["stock"] = cam.size_from_offsets(tb, t, 1.0)                   # Ø2.1 x 3.55 -> 2.125 x 3.625
    assert (t["stock"]["dia"], t["stock"]["length"]) == (2.125, 3.625)
    c = cam.stock_cylinder(tb, 1.0, t)
    assert c["r"] == 1.0625 and c["front"][2] == pytest.approx(3.05) and c["center"][2] == pytest.approx(-0.575)
    assert cam.fits(tb, t, 1.0) is None
    t["stock"]["dia"] = 1.9
    assert "Ø" in cam.fits(tb, t, 1.0)
    old = {"type": "milling", "body": "all", "stock": {"side": 0.1, "top": 0.05, "bottom": 0}, "wcs": "model"}
    assert cam.validate(old)["stock"]["mode"] == "offset"            # setups saved before modes still load


def test_milling_face_toolpath():
    from gsend_cad.core import cam
    box = ((0, 0, 0), (4, 3, 0.5))
    s = cam.new_setup("milling")                         # stock top 0.55, WCS on it (top center)
    op = cam.new_op(s)
    mv = cam.face_toolpath(box, s, op)
    feeds = [p for k, p in mv if k == "feed"]
    assert {round(p[2], 9) for p in feeds} == {-0.05}   # one 0.05 pass down to the part top
    ys = sorted({round(p[1], 6) for p in feeds})
    assert ys[0] - 1.0 <= -1.6 and ys[-1] + 1.0 >= 1.6   # tool edge covers the 3.2 wide stock
    assert all(b - a <= 1.4 + 1e-9 for a, b in zip(ys, ys[1:]))          # 70 % of Ø2
    xs = [p[0] for p in feeds]
    assert min(xs) <= -2.1 - 1.0 and max(xs) >= 2.1 + 1.0                # off the stock both ends
    s["stock"]["top"] = 0.12
    mv = cam.face_toolpath(box, s, op)
    assert sorted({round(p[2], 9) for k, p in mv if k == "feed"}) == [-0.12, -0.08, -0.04]
    assert cam.cycle_time(mv, s, op) > 0


def test_turning_face_toolpath():
    from gsend_cad.core import cam
    box = ((-1, -1, 0), (1, 1, 3))
    s = cam.new_setup("turning")                         # face stock 0.05, Z0 on the stock face
    op = cam.new_op(s)
    mv = cam.face_toolpath(box, s, op, 1.0)
    feeds = [p for k, p in mv if k == "feed"]
    assert [p[2] for p in feeds] == pytest.approx([-0.05 / 3, -0.1 / 3, -0.05])   # 3 passes <= 0.02
    assert all(p[0] == -0.02 for p in feeds)             # each pass runs past center
    w = cam.toolpath_world(box, s, mv, 1.0)
    assert abs(w[0][1][2] - (3.05 + 0.1)) < 1e-9         # first rapid clears the stock face


def test_ops_in_document():
    from gsend_cad.core import cam
    d = Document()
    st = d.add_setup(cam.new_setup("milling"))
    o = d.add_op(st["id"], cam.new_op(st))
    assert (o["id"], o["name"]) == ("op1", "Face1")
    d.update_op("op1", {**o, "stepover": 50})
    d.update_setup(st["id"], {**d.setup(st["id"]), "stock": {"mode": "offset", "side": .2, "top": .1, "bottom": 0}})
    assert d.setup(st["id"])["ops"][0]["stepover"] == 50         # editing the setup keeps its ops
    d2 = Document.from_dict(d.to_dict())
    assert d2.op("op1")[1]["name"] == "Face1"
    with pytest.raises(ValueError):
        d.update_op("op1", {**o, "tool_dia": 0})
    d.remove_op("op1")
    assert d.op("op1") == (None, None)
