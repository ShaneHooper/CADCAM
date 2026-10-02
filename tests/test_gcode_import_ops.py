"""G-code import, Phase 3: operation segmentation, classification, and the user's type choice.

Stdlib-only:
    python -m pytest -q tests/test_gcode_import_ops.py
"""
from pathlib import Path

import pytest

from gsend_cad.gcode_import import keywords as kw
from gsend_cad.gcode_import import operations as ops
from gsend_cad.gcode_import import parse_program, tooling

FIXTURES = Path(__file__).parent / "fixtures" / "gcode"
TABLE = kw.defaults()
HEAD = "G20 G40 G99\n"


def build(text, overrides=None, stock_id=0.0, table=TABLE):
    program = parse_program(text)
    tools = tooling.build_tools(program, table)
    return ops.build_operations(program, tools, table, overrides, stock_id)


def rows(text, **kw_):
    return [(o.tool, o.type, o.found_by, o.confidence) for o in build(text, **kw_)]


# ---- segmentation: tool change, then comment, then motion ----
def test_the_stepped_shaft_splits_one_tool_into_face_and_rough_by_motion():
    o = build((FIXTURES / "stepped_shaft.nc").read_text())
    assert [(x.type, x.found_by, x.confidence, x.passes) for x in o] == [
        ("FACE", "MOTION", "MED", 2), ("OD ROUGH", "KEYWORD", "HIGH", 3)]
    assert [x.lines for x in o] == ["L9-L12", "L14-L23"] and [x.index for x in o] == [1, 2]


def test_a_tool_change_starts_a_new_operation():
    o = build((FIXTURES / "multi_tool.nc").read_text())
    assert [x.tool for x in o] == ["01", "01", "02", "03", "04", "05"]
    assert [x.type for x in o] == ["FACE", "OD ROUGH", "DRILL", "ID ROUGH", "OD GROOVE", "THREAD"]


def test_an_operation_comment_starts_a_new_operation():
    text = HEAD + ("T0101 (OD ROUGH)\nG0 X2.1 Z.1\nX1.8\nG1 Z-1. F.01\nG0 X2.1\nZ.1\nX1.6\nG1 Z-1.\nG0 X2.1\nZ.1\n"
                   "(OD FINISH)\nX1.5\nG1 Z-1.\nG0 X2.1\n")
    assert rows(text) == [("01", "OD ROUGH", "KEYWORD", "HIGH"), ("01", "OD FINISH", "KEYWORD", "HIGH")]


def test_a_stale_comment_does_not_carry_to_the_next_tool():
    o = build((FIXTURES / "multi_tool.nc").read_text())
    assert [x.comment for x in o][3:] == ["BORE", "", ""]


# ---- the starting motion rules ----
def test_x_sweep_at_constant_z_is_a_face():
    assert rows(HEAD + "T0101\nG0 X2.1 Z0\nG1 X-.03 F.01\nG0 Z.1\n") == [("01", "FACE", "MOTION", "MED")]


def test_repeated_z_passes_stepping_in_x_are_a_rough_and_one_is_a_finish():
    two = HEAD + "T0101\nG0 X1.8 Z.1\nG1 Z-1. F.01\nG0 X2.\nZ.1\nX1.6\nG1 Z-1.\nG0 X2.\n"
    one = HEAD + "T0101\nG0 X1.8 Z.1\nG1 Z-1. F.01\nG0 X2.\n"
    assert rows(two) == [("01", "OD ROUGH", "MOTION", "MED")] and build(two)[0].passes == 2
    assert rows(one) == [("01", "OD FINISH", "MOTION", "MED")]


def test_one_continuous_contour_is_a_finish_split_from_the_roughing_before_it():
    text = HEAD + ("T0101\nG0 X1.8 Z.1\nG1 Z-1. F.01\nG0 X2.\nZ.1\nX1.6\nG1 Z-1.\nG0 X2.\nZ.1\n"
                   "X1.4\nG1 Z0 F.006\nG3 X1.5 Z-.05 R.05\nG1 Z-1.\nX2.\nG0 Z.1\n")
    assert [(t, f) for _, t, f, _ in rows(text)] == [("OD ROUGH", "MOTION"), ("OD FINISH", "MOTION")]
    assert "contour" in build(text)[1].why


def test_x_plunges_inside_the_part_are_a_groove():
    text = HEAD + "T0101\nG0 X2.1 Z0\nG1 X-.03 F.01\nG0 X2.1 Z.1\nT0404\nG0 X1.6 Z-.5\nG1 X1.2 F.003\nG0 X1.6\n"
    assert rows(text)[1] == ("04", "OD GROOVE", "MOTION", "MED")


def test_x_to_the_centerline_at_the_back_is_a_part_off():
    text = HEAD + ("T0101\nG0 X2.1 Z0\nG1 X-.03 F.01\nG0 X1.5 Z.1\nG1 Z-1.5\nG0 X2.2\n"
                   "T0404\nG0 X2.2 Z-1.5\nG1 X-.03 F.003\nG0 X2.2\n")
    assert rows(text)[-1] == ("04", "PART-OFF", "MOTION", "MED")


def test_z_only_moves_at_x0_are_a_drill():
    assert rows(HEAD + "T0202\nG0 X0 Z.1\nG1 Z-1. F.005\nG0 Z.1\n") == [("02", "DRILL", "MOTION", "MED")]


def test_a_short_diagonal_is_a_chamfer():
    assert rows(HEAD + "T0101\nG0 X.9 Z.05\nG1 X1. Z-.05 F.005\nG0 X2.\n") == [("01", "CHAMFER", "MOTION", "MED")]


def test_threading_cycles_are_threads_and_canned_cycles_name_themselves():
    assert rows(HEAD + "T0505\nG0 X1.1 Z.2\nG92 X.98 Z-1. F.0625\nX.96\nG0 X2.\n") == [("05", "THREAD", "G92", "HIGH")]
    g71 = HEAD + ("T0101\nG0 X2.1 Z.1\nG71 U.1 R.02\nG71 P100 Q140 U.02 W.005 F.012\nN100 G0 X1.\nN110 G1 Z-.5\n"
                  "N120 X1.5\nN130 Z-1.\nN140 X2.\nG70 P100 Q140\n")
    o = build(g71)
    assert [(x.type, x.found_by, x.confidence) for x in o] == [("OD ROUGH", "G71", "HIGH"), ("OD FINISH", "G70", "HIGH")]
    assert o[0].lines == "N100-N140"                    # the range takes in the P-Q block


def test_inside_or_outside_follows_the_drilled_hole():
    text = HEAD + ("T0202 (1/2 DRILL)\nG0 X0 Z.1\nG83 Z-1. Q.25 R.1 F.005\nG80\nG28 U0 W0\n"
                   "T0303\nG0 X.4 Z.1\nG1 Z-.9 F.006\nG0 X.35\nZ.1\n")                 # cuts inside the 0.5 hole
    o = build(text)
    assert (o[1].type, o[1].side) == ("ID FINISH", "ID")
    solid = build(HEAD + "T0303\nG0 X.4 Z.1\nG1 Z-.9 F.006\nG0 X.5\nZ.1\n")              # same cut, no hole
    assert (solid[0].type, solid[0].side) == ("OD FINISH", "OD")
    tube = build(HEAD + "T0303\nG0 X.4 Z.1\nG1 Z-.9 F.006\nG0 X.35\nZ.1\n", stock_id=0.5)
    assert tube[0].side == "ID"                         # tube stock is a hole too


def test_what_the_motion_cannot_name_needs_a_type():
    o = build(HEAD + "T0101\nG0 X1. Z.1\nG1 Z-.2 F.003\nZ.1\nG0 X2.\n")[0]           # Z in and straight back out
    assert (o.type, o.found_by, o.confidence) == (None, "-", "NEEDS TYPE") and "face groove" in o.why


# ---- keywords ----
def test_a_keyword_beats_the_motion_and_generic_rough_gets_its_side():
    text = HEAD + "T0101 (ROUGH)\nG0 X1.8 Z.1\nG1 Z-1. F.01\nG0 X2.\n"                  # one pass: motion says finish
    assert rows(text) == [("01", "OD ROUGH", "KEYWORD", "HIGH")]


def test_a_comment_naming_two_operations_gives_each_run_its_own():
    text = HEAD + ("T0101 (FACE AND OD ROUGH)\nG0 X2.1 Z0\nG1 X-.03 F.01\nG0 X1.8 Z.1\nG1 Z-1.\nG0 X2.\nZ.1\n"
                   "X1.6\nG1 Z-1.\nG0 X2.\n")
    assert rows(text) == [("01", "FACE", "KEYWORD", "HIGH"), ("01", "OD ROUGH", "KEYWORD", "HIGH")]


def test_a_single_run_takes_its_comments_one_keyword_even_when_the_motion_differs():
    text = HEAD + "T0404 (FACE GROOVE)\nG0 X1. Z.1\nG1 Z-.2 F.003\nZ.1\nG0 X2.\n"
    assert rows(text) == [("04", "FACE GROOVE", "KEYWORD", "HIGH")]


# ---- the user's choice ----
def test_a_type_set_by_the_user_wins_and_is_marked():
    text = (FIXTURES / "stepped_shaft.nc").read_text()
    key = build(text)[0].key
    o = build(text, overrides={key: "SKIP"})
    assert (o[0].type, o[0].found_by, o[0].confidence) == ("SKIP", "YOU", "SET BY YOU")
    assert o[1].confidence == "HIGH" and ops.counts(o) == {"HIGH": 1, "MED": 0, "NEEDS TYPE": 0, "SET BY YOU": 1}


def test_every_cutting_move_belongs_to_exactly_one_operation():
    program = parse_program((FIXTURES / "multi_tool.nc").read_text())
    o = ops.build_operations(program, tooling.build_tools(program, TABLE), TABLE)
    owned = [i for x in o for i in x.moves]
    cutting = [i for i, m in enumerate(program.moves) if m.kind != "rapid"]
    assert len(owned) == len(set(owned)) and set(cutting) <= set(owned)


# ---- threads and the summary ----
def test_a_g76_thread_callout_has_major_minor_and_pitch():
    o = build((FIXTURES / "multi_tool.nc").read_text())[-1]
    t = o.thread
    assert (t.side, t.pitch) == ("OD", 0.0625) and t.minor == pytest.approx(1.4234, abs=1e-4)
    assert t.major == pytest.approx(1.5, abs=1e-4) and (t.z0, t.z1) == pytest.approx((0.2, -0.4))
    assert "16 TPI" in t.callout and "1.5000" in t.callout and "minor 1.4234" in t.callout


def test_the_summary_before_reconstruction():
    program = parse_program((FIXTURES / "multi_tool.nc").read_text())
    tools = tooling.build_tools(program, TABLE)
    o = ops.build_operations(program, tools, TABLE)
    s = ops.summary(program, o, tools, {"od": 2.25, "id": 0.0})
    assert (s["operations"], s["needs_type"], s["stock_od"], s["skipped"]) == (6, 0, 2.25, 0)
    assert s["bore"] == pytest.approx(0.75) and s["cut_z"] == pytest.approx((-1.5, 0.2))
    assert len(s["threads"]) == 1 and "16 TPI" in s["threads"][0]
    skipped = ops.build_operations(program, tools, TABLE, {o[-1].key: "SKIP"})
    assert ops.summary(program, skipped, tools, {"od": 2.25, "id": 0.0})["threads"] == []
