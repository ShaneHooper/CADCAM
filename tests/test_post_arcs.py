"""The lathe post writes a radius as one G02 / G03 block, not the mesh's string of tiny G01s.

Shane's screenshot (10/3/26): a Ø2 nose with a R0.125 corner posted as 32 lines of X1.7623 Z-0.0002,
X1.7745 Z-0.0006 ... inside the G71 P-Q block. The profile comes off a mesh (kernel.turn_profile), so the
arc arrives as chords; core.arcs puts it back together and the post writes G03 X2. Z-0.125 R0.125.
"""
import math

import pytest

from gsend_cad.core import arcs, cam, post

BOX = ((0, -1.75, -1.75), (4, 1.75, 1.75))        # turned along X, front at +X, Z0 on the part face: z = t - 2
SETUP = {**cam.validate({**cam.new_setup("turning"), "axis": "x", "wcs": "part-face"}), "name": "S"}


def round_pts(cu, cv, r, a0, a1, n=24):
    """n+1 points on a circle of radius r about (cu, cv) from angle a0 to a1 (degrees)."""
    return [(cu + r * math.cos(math.radians(a0 + (a1 - a0) * k / n)),
             cv + r * math.sin(math.radians(a0 + (a1 - a0) * k / n))) for k in range(n + 1)]


def profile():
    """(t, radius), t from the bbox middle, back to front: Ø3.5 back, a shoulder face at t = -1.5 (z = -3.5),
    a concave R0.25 fillet from it onto the Ø2 nose (centre t = -1.25, r = 1.25), the nose, and a convex
    R0.125 round on its front corner (centre t = 1.875, r = 0.875) ending on the front face at t = 2 (z = 0).
    Both rounds are 24 chords, like the mesh gives them."""
    shoulder = round_pts(-1.25, 1.25, 0.25, 180.0, 270.0)            # (-1.5, 1.25) .. (-1.25, 1.0)
    front = round_pts(1.875, 0.875, 0.125, 90.0, 0.0)[1:]            # (1.875, 1.0) .. (2.0, 0.875)
    return [(-2.0, 1.75), (-1.5, 1.75)] + shoulder + [(1.875, 1.0)] + front


def code(g):
    return [ln for ln in g.splitlines() if not ln.startswith("(")]


def test_fit_finds_an_arc_and_leaves_a_chamfer_alone():
    arc = round_pts(0.0, 0.0, 1.0, 0.0, 90.0, 12)
    f = arcs.fit(arc)
    assert len(f) == 1 and f[0][:3] == ("arc", 0, 12)
    (cu, cv), r, ccw = f[0][3], f[0][4], f[0][5]
    assert (cu, cv, r) == pytest.approx((0.0, 0.0, 1.0)) and ccw        # 0 -> 90 deg is a left turn
    f = arcs.fit(list(reversed(arc)))
    assert f[0][:3] == ("arc", 0, 12) and not f[0][5]                    # the other way: clockwise
    chamfer = [(0.0, 0.0), (1.0, 0.0), (1.2, 0.2), (1.2, 2.0)]
    assert arcs.fit(chamfer) == [("line", 0, 1), ("line", 1, 2), ("line", 2, 3)]
    assert arcs.fit([(0.0, 0.0), (1.0, 0.0)]) == [("line", 0, 1)]
    # a line into an arc: the line is not swallowed into it, and the arc starts at the line's end
    f = arcs.fit([(-3.0, 1.0)] + round_pts(0.0, 0.0, 1.0, 90.0, 0.0, 10))
    assert f[0] == ("line", 0, 1) and f[1][:3] == ("arc", 1, 11)


def test_g71_block_writes_the_corner_round_as_g03_and_the_shoulder_fillet_as_g02():
    op = cam.validate_op(SETUP, {**cam.new_op(SETUP, "rough"), "name": "R", "output": "cycle"})
    mv = cam.toolpath(BOX, SETUP, op, 1.75, profile=profile())
    lines = code(post.post_setup(SETUP, [(op, mv)], "haas", 1))
    i = next(k for k, ln in enumerate(lines) if ln.startswith("N100"))
    j = next(k for k, ln in enumerate(lines) if ln.startswith("N101"))
    block = lines[i:j + 1]
    assert block[:2] == ["N100 G00 X1.75", "G01 Z0."]
    assert "G03 X2. Z-0.125 R0.125" in block                              # the convex front corner
    assert "G02 X2.5 Z-3.5 R0.25" in block                                # the concave shoulder fillet
    assert block[-1] == "N101 X3.8" and len(block) == 8, block            # not 50 tiny G01s
    assert not any(ln.startswith("X1.7") for ln in block)


def test_lines_output_and_the_contour_write_the_same_arcs():
    for kind in ("rough", "finish"):
        op = cam.validate_op(SETUP, {**cam.new_op(SETUP, kind), "name": kind, "output": "lines"})
        mv = cam.toolpath(BOX, SETUP, op, 1.75, profile=profile())
        lines = code(post.post_setup(SETUP, [(op, mv)], "haas", 1))
        g03 = [ln for ln in lines if ln.startswith("G03")]
        g02 = [ln for ln in lines if ln.startswith("G02")]
        assert len(g03) == 1 and g03[0].startswith("G03 X") and "R0.125" in g03[0], (kind, g03)
        assert len(g02) == 1 and "R0.25" in g02[0], (kind, g02)
        assert not any(ln.startswith("X1.7") and "Z-0.0" in ln for ln in lines), kind   # no chord strings
        k = lines.index(g03[0])                                             # G01 is restated after the arc
        assert lines[k + 1].startswith("G01 Z"), lines[k:k + 3]


def test_the_importer_reads_the_posted_arcs_back_onto_the_part():
    """The direction is checked against an independent reader: gcode_import's parser (ported from the REV5
    lathe simulator, proven on real programs) flattens the arcs, and every point must lie on the round the
    profile was built from. A G02 written where a G03 belongs bows the other way, into the part."""
    from gsend_cad.gcode_import.parser import parse_program
    op = cam.validate_op(SETUP, {**cam.new_op(SETUP, "finish"), "name": "C", "output": "lines",
                                 "leave_x": 0.0, "leave_z": 0.0})
    mv = cam.toolpath(BOX, SETUP, op, 1.75, profile=profile())
    p = parse_program(post.post_setup(SETUP, [(op, mv)], "haas", 1))
    read = [m for m in p.moves if m.code in ("G2", "G3")]
    assert [m.code for m in read] == ["G3", "G2"]
    for z, xd in read[0].points:                                            # (z, x diameter), inches
        assert math.hypot(z + 0.125, xd / 2 - 0.875) == pytest.approx(0.125, abs=2e-3)
    assert min(xd for _z, xd in read[0].points) >= 1.75 - 1e-6              # bows outward, never into the nose
    for z, xd in read[1].points:
        assert math.hypot(z + 3.25, xd / 2 - 1.25) == pytest.approx(0.25, abs=2e-3)
    assert max(xd for _z, xd in read[1].points) <= 2.5 + 1e-6               # stays inside the shoulder corner


def test_straight_profiles_post_exactly_as_before():
    prof = [(-1.5, 1.0), (-0.5, 1.0), (0.5, 0.5), (1.5, 0.5)]
    box = ((0, -1, -1), (3, 1, 1))
    s = {**cam.validate({**cam.new_setup("turning"), "axis": "x"}), "name": "S"}
    rough = cam.validate_op(s, {**cam.new_op(s, "rough"), "name": "R", "output": "cycle"})
    g = post.post_setup(s, [(rough, cam.toolpath(box, s, rough, 1.0, profile=prof))], "haas", 1)
    assert "G02" not in g and "G03" not in g
    assert "N100 G00 X1.\nG01 Z-0.05\nZ-1.05\nX2. Z-2.05\nZ-3.05\nN101 X2.3" in g     # Z0 = the stock front
