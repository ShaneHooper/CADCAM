"""Cutter comp for a lathe Contour: Off / Machine (G41 G42 G40) / Computer (the nose radius worked into the points).

The Haas ST/TL workbook (pages 55-57) is the reference: a 0.031 nose radius O.D. turning tool, the part with two
.300 / .250 x 45 deg chamfers, whose compensated program is given there.

    python -m pytest -q tests/test_nose_comp.py
"""
import math

import pytest

from gsend_cad.core import cam, nose, post, tools

TNR = 0.031
# the workbook part line, (z, radius), front first (dimensions on the page are diameters)
HAAS = [(0.0, 0.375), (-0.25, 0.625), (-1.0, 0.625), (-1.25, 0.875), (-1.25, 1.2), (-1.55, 1.5), (-2.375, 1.5)]
# the tip points the workbook's program (N7 .. N14) gives for it: (z, diameter)
HAAS_PROGRAM = [(0.0, 0.7134), (-0.2683, 1.2500), (-1.0183, 1.2500), (-1.2500, 1.7134), (-1.2500, 2.3634),
                (-1.5683, 3.0), (-2.375, 3.0)]


def finish_moves(prof, rt=0.02, x_out=2.0, z_start=0.1):
    """A turning Contour's moves the way cam.finish_toolpath builds them."""
    return [("rapid", (x_out, 0.0, z_start))] + cam._profile_pass(prof, rt, x_out, z_start)


def setup_and_op(**kw):
    s = {**cam.validate(cam.new_setup(cam.TURNING)), "name": "Setup"}
    op = {**cam.new_op(s, "finish"), "name": "Contour", "output": "lines", "nose_r": TNR, **kw}
    return s, op


def text(moves, comp, **kw):
    s, op = setup_and_op(**kw)
    return post.post_setup(s, [(op, moves)], "haas", 1000, "G54", True, "", comp)


def block(g, word):
    """The program lines (not the comments) that carry this G word."""
    return [ln for ln in g.splitlines() if not ln.startswith("(") and word in ln.split()]


# ---- the math, against the workbook ----
def test_the_nose_radius_math_reproduces_the_haas_workbook_example():
    tip = nose.tip_path(HAAS, TNR)
    assert len(tip) == len(HAAS_PROGRAM)
    for (z, r), (hz, hd) in zip(tip, HAAS_PROGRAM):
        # the workbook rounds its chart offsets (0.0366 where the exact figure is 0.0363): within 0.0004
        assert z == pytest.approx(hz, abs=4e-4) and 2 * r == pytest.approx(hd, abs=4e-4)


def test_the_exact_45_degree_offsets_are_the_charts_0_0183_and_0_0366():
    tip = nose.tip_path([(0.0, 0.375), (-0.25, 0.625), (-1.0, 0.625)], TNR)      # the chamfer, then the cylinder
    assert tip[0][0] == pytest.approx(0.0, abs=1e-9)                        # the face stays on Z0
    assert 0.75 - 2 * tip[0][1] == pytest.approx(0.0363, abs=1e-4)          # the chart's X-offset, on the diameter
    assert -0.25 - tip[1][0] == pytest.approx(0.0182, abs=1e-4)             # and its Z-offset


def test_moves_along_an_axis_need_no_compensation():
    shaft = [(0.0, 0.5), (-1.0, 0.5), (-1.0, 0.75), (-2.0, 0.75)]           # face, cylinder, shoulder, cylinder
    assert nose.tip_path(shaft, TNR) == pytest.approx(shaft)


def test_a_nose_radius_of_zero_changes_nothing():
    assert nose.tip_path(HAAS, 0.0) == HAAS


def test_a_concave_radius_smaller_than_the_nose_does_not_turn_the_path_inside_out():
    n, rc, c = 12, 0.01, (-0.5, 0.51)                                       # R0.01 inside corner, nose 0.031
    arc = [(c[0] + rc * math.cos(math.radians(-90 - 90 * i / n)), c[1] + rc * math.sin(math.radians(-90 - 90 * i / n)))
           for i in range(n + 1)]
    prof = [(0.0, 0.5), arc[0], *arc[1:], (-0.5, 1.0)]
    tip = nose.tip_path(prof, TNR)
    assert len(tip) >= 2
    assert all(tip[i + 1][0] <= tip[i][0] + 1e-9 or tip[i + 1][1] >= tip[i][1] - 1e-9 for i in range(len(tip) - 1))


# ---- a finish path's moves ----
def test_the_compensated_path_keeps_the_approach_the_pull_off_and_the_clearances():
    mv = finish_moves(HAAS)
    out = nose.compensate(mv, TNR)
    assert out[0] == mv[0] and out[-2:] == mv[-2:]                          # rapid out ... rapid out and home
    assert [k for k, _p in out].count("feed") == len(HAAS) + 1              # the profile + the pull-off
    x0 = out[1][1]
    assert x0[2] == 0.1 and x0[0] == pytest.approx(nose.tip_path(HAAS, TNR)[0][1])     # above the first tip point
    assert out[2][1][0] == pytest.approx(x0[0])                             # straight down at that X
    last, pull = out[-3][1], out[-4][1]
    assert last[0] - pull[0] == pytest.approx(0.02) and last[2] - pull[2] == pytest.approx(0.02)   # still 0.02 at 45


def test_an_id_is_the_mirror_of_an_od():
    od = finish_moves(HAAS)
    mirror = [(k, (-x, y, z)) for k, (x, y, z) in od]
    a = nose.compensate(od, TNR, internal=False)
    b = nose.compensate(mirror, TNR, internal=True)
    for (ka, pa), (kb, pb) in zip(a, b):
        assert ka == kb and (-pa[0], pa[1], pa[2]) == pytest.approx(pb, abs=1e-9)


def test_a_path_that_is_not_a_profile_pass_is_refused_not_guessed():
    with pytest.raises(ValueError):
        nose.compensate([("rapid", (1.0, 0.0, 1.0)), ("feed", (1.0, 0.0, 0.0))], TNR)
    assert nose.compensate(finish_moves(HAAS), 0.0) == finish_moves(HAAS)


# ---- the post: Off / Machine / Computer ----
def test_off_is_exactly_what_it_was():
    mv = finish_moves(HAAS)
    s, op = setup_and_op()
    assert post.post_setup(s, [(op, mv)], "haas", 1000, "G54", True, "") == text(mv, "off")
    g = text(mv, "off")
    assert not block(g, "G41") and not block(g, "G42") and len(block(g, "G40")) == 1       # only the header's G40
    assert "CUTTER COMP" not in g


def test_machine_comp_puts_g42_on_the_approach_and_g40_on_the_way_out_with_the_same_points():
    mv = finish_moves(HAAS)
    g = text(mv, "machine")
    assert len(block(g, "G42")) == 1 and len(block(g, "G40")) == 2                          # header + the cancel
    on = block(g, "G42")[0]
    assert on.startswith("G01 G42 Z") and "F" in on                                         # the approach feed down in Z
    after = g.splitlines()[g.splitlines().index(on):]
    assert [ln for ln in after if "G40" in ln.split()][0].startswith("G00 G40 X")           # off on the first move away
    off = text(mv, "off")
    strip = lambda s: [ln.replace(" G42", "").replace(" G40", "") for ln in s.splitlines() if "CUTTER COMP" not in ln]
    assert strip(g) == strip(off)                                                           # same coordinates as Off
    assert "CUTTER COMP G42 ON" in g and "R0.031" in g


def test_an_id_contour_uses_g41():
    prof = [(0.0, 0.75), (-1.0, 0.75)]
    mv = [(k, (x, y, z)) for k, (x, y, z) in finish_moves(prof)]
    g = text(mv, "machine", internal=True)
    assert len(block(g, "G41")) == 1 and not block(g, "G42")


def test_computer_comp_has_no_g41_g42_or_g40_and_writes_the_tip_points():
    mv = finish_moves(HAAS)
    g = text(mv, "computer")
    assert not block(g, "G41") and not block(g, "G42") and len(block(g, "G40")) == 1        # only the header
    assert "CUTTER COMP IN THE CODE: NOSE R0.031" in g
    tip = nose.tip_path(HAAS, TNR)
    for z, r in tip:
        assert f"X{post.num(2 * r)}" in g or post.num(2 * r) in g
    assert "X0.7137" in g and "Z-0.2682" in g and "X1.7137" in g                              # the workbook's figures


def test_a_tool_with_no_nose_radius_is_left_uncompensated_and_the_program_says_so():
    mv = finish_moves(HAAS)
    g = text(mv, "computer", nose_r=0.0)
    assert "NO NOSE RADIUS" in g
    strip = lambda s: [ln for ln in s.splitlines() if "CUTTER COMP" not in ln]
    assert strip(g) == strip(text(mv, "off"))


def test_a_canned_cycle_contour_is_posted_line_by_line_when_comp_is_on():
    mv = finish_moves(HAAS)
    for comp in ("machine", "computer"):
        g = text(mv, comp, output="cycle")
        assert not [ln for ln in g.splitlines() if ln.startswith("G70")] and "NOT G70" in g


def test_other_operations_and_a_mill_ignore_cutter_comp():
    s = {**cam.validate(cam.new_setup(cam.TURNING)), "name": "Setup"}
    rough = {**cam.new_op(s, "rough"), "name": "Roughing", "output": "lines", "nose_r": TNR}
    mv = finish_moves(HAAS)
    a = post.post_setup(s, [(rough, mv)], "haas", 1000, "G54", True, "", "off")
    assert post.post_setup(s, [(rough, mv)], "haas", 1000, "G54", True, "", "computer") == a
    assert post.post_setup(s, [(rough, mv)], "haas", 1000, "G54", True, "", "machine") == a
    with pytest.raises(ValueError):
        post.post_setup(s, [(rough, mv)], "haas", 1000, "G54", True, "", "magic")


def test_the_tools_nose_radius_travels_with_the_op():
    t = {"id": "t9", "number": 9, "name": "VNMG", "kind": "od turn", "machine": "turning", "dia": 0.0, "nose_r": 0.016}
    assert tools.apply({"tool": 1}, t)["nose_r"] == 0.016
    drill = {"id": "t5", "number": 5, "name": "Drill", "kind": "drill-t", "machine": "turning", "dia": 0.25, "nose_r": 0.0}
    assert "nose_r" not in tools.apply({"tool": 1}, drill)
