"""G-code import, Phase 1: the parser's canonical move list, lathe/mill detection, stock guesses.

Stdlib-only module, so these run without Qt or the kernel:
    python -m pytest -q tests/test_gcode_import.py
"""
from pathlib import Path
import subprocess
import sys

import pytest

from gsend_cad.gcode_import import detect_machine, guess_stock, parse_program, stock_z_range
from gsend_cad.gcode_import.stock import first_facing_pass, round_down, round_up

FIXTURES = Path(__file__).parent / "fixtures" / "gcode"
HEAD = "G20 G40 G99\nT0101\nG0 X2. Z.1\n"


def cuts(text):
    return [m for m in parse_program(text).moves if m.kind != "rapid"]


def ends(m):
    return (round(m.z1, 4), round(m.x1, 4))


# ---- parser: one test per code in the canonical list ----
def test_g0_is_a_rapid_and_g1_a_feed_with_x_as_diameter():
    p = parse_program(HEAD + "G1 X1.5 Z-1. F.01\n")
    assert [m.kind for m in p.moves] == ["rapid", "feed"]
    m = p.moves[1]
    assert (m.z0, m.x0, m.z1, m.x1) == pytest.approx((0.1, 2.0, -1.0, 1.5))
    assert m.feed == 0.01 and m.line == 4


def test_a_facing_pass_past_centre_keeps_its_negative_x():
    m = cuts(HEAD + "G1 Z0 F.01\nX-.0625\n")[1]
    assert ends(m) == (0.0, -0.0625)                    # not clamped to X0: that is what clears the centre nub


def test_modal_motion_carries_to_bare_axis_lines():
    m = cuts(HEAD + "G1 Z-1. F.01\nX2.5\n")
    assert [x.code for x in m] == ["G1", "G1"] and ends(m[1]) == (-1.0, 2.5)


def test_g2_g3_r_arc_has_centre_direction_and_ends():
    m = cuts(HEAD + "G1 X1.5 Z0 F.01\nG3 X1.75 Z-.125 R.125\nG2 X2. Z-.25 R.125\n")
    ccw, cw = m[1], m[2]
    assert ccw.kind == cw.kind == "arc"
    assert ccw.clockwise is False and cw.clockwise is True
    assert ends(ccw) == (-0.125, 1.75) and ends(cw) == (-0.25, 2.0)
    for arc in (ccw, cw):                               # both ends sit 0.125 from the centre (radius, not diameter)
        cz, cx = arc.center
        for z, x in ((arc.z0, arc.x0), (arc.z1, arc.x1)):
            assert ((z - cz) ** 2 + ((x - cx) / 2) ** 2) ** 0.5 == pytest.approx(0.125, abs=1e-6)
    assert len(ccw.points) > 2                          # flattened for the backplot


def test_ijk_arc_i_is_a_radius_value():
    arc = cuts(HEAD + "G1 X1.5 Z0 F.01\nG3 X1.75 Z-.125 I0 K-.125\n")[1]
    assert arc.center == pytest.approx((-0.125, 1.5))


def test_g21_metric_program_is_converted_to_inches():
    p = parse_program("G21 G99\nT0101\nG0 X50.8 Z2.54\nG1 Z-25.4 F.2\n")
    assert p.units == "mm"
    assert ends(p.moves[-1]) == (-1.0, 2.0)


def test_u_w_incremental_and_g91():
    m = cuts(HEAD + "G1 U-.5 W-.6 F.01\nG91\nG1 X.25 Z-.1\nG90\nG1 X1. Z-2.\n")
    assert ends(m[0]) == (-0.5, 1.5)                    # U is a diameter change
    assert ends(m[1]) == (-0.6, 1.75)
    assert ends(m[2]) == (-2.0, 1.0)


def test_cutter_comp_state_rides_on_the_moves():
    m = cuts(HEAD + "G42 G1 X1.5 F.01\nZ-1.\nG40 X2.\n")
    assert [x.comp for x in m] == ["G42", "G42", "G40"]


def test_t_call_with_offset_and_short_t_word():
    p = parse_program("G20\nT0305\nG0 X1. Z0\nG1 Z-1. F.01\nT7\nG1 Z-2.\n")
    a, b = [m for m in p.moves if m.kind == "feed"]
    assert (a.tool, a.offset) == ("03", "05")
    assert (b.tool, b.offset) == ("07", "00")


def test_the_active_comment_and_n_number_ride_on_the_moves():
    p = parse_program("G20\nT0101 (OD ROUGH CNMG 432)\nG0 X2. Z.1\nN120 G1 Z-1. F.01\n(FINISH PASS)\nG1 X2.5\n")
    feeds = [m for m in p.moves if m.kind == "feed"]
    assert feeds[0].comment == "OD ROUGH CNMG 432" and feeds[0].n == 120
    assert feeds[1].comment == "FINISH PASS" and feeds[1].n is None


def test_feed_and_spindle_modes_and_g50_clamp():
    p = parse_program("G20 G98\nT0101\nG50 S3000\nG96 S400 M3\nG0 X2. Z.1\nG1 Z-1. F5.\nG99 G97 S1200\nG1 X2.2 F.01\n")
    a, b = [m for m in p.moves if m.kind == "feed"]
    assert (a.feed_mode, a.speed_mode, a.spindle, a.max_rpm) == ("G94", "G96", 400, 3000)
    assert (b.feed_mode, b.speed_mode, b.spindle) == ("G95", "G97", 1200)


G71 = """G20 G40 G99
T0101
G0 X2.1 Z.1
G71 U.1 R.02
G71 P100 Q140 U.02 W.005 F.012
N100 G0 X1.
N110 G1 Z-.5 F.006
N120 X1.5
N130 Z-1.
N140 X2.
G70 P100 Q140
"""


def test_g71_two_line_roughs_then_g70_cuts_the_p_q_contour_at_size():
    p = parse_program(G71)
    rough = [m for m in p.moves if m.code == "G71" and m.kind == "feed"]
    assert len(rough) >= 4 and all(m.x0 == pytest.approx(m.x1) for m in rough)     # Z passes stepping in X
    finish = [m for m in p.moves if m.code == "G70 profile" and m.kind == "feed"]
    assert [ends(m) for m in finish] == [(-0.5, 1.0), (-0.5, 1.5), (-1.0, 1.5), (-1.0, 2.0)]
    left = [ends(m) for m in p.moves if m.code == "G71 profile" and m.kind == "feed"]
    assert left[0] == (-0.495, 1.02)                    # the roughing contour keeps the U/W finish stock


def test_g71_one_line_format():
    p = parse_program(HEAD + "G71 P10 Q20 U.02 W.005 D500 F.012\nN10 G0 X1.\nN20 G1 Z-1.\n")
    assert [m for m in p.moves if m.code == "G71" and m.kind == "feed"]


def test_g72_facing_cycle_steps_in_z():
    p = parse_program(HEAD + "G72 W.05 R.02\nG72 P10 Q20 U0 W0 F.01\nN10 G0 Z-.2\nN20 G1 X.5\n")
    passes = [m for m in p.moves if m.code == "G72" and m.kind == "feed"]
    assert len(passes) >= 3 and all(m.z0 == pytest.approx(m.z1) for m in passes)


def test_g76_thread_reaches_the_root_over_the_thread_length():
    p = parse_program("G20\nT0505\nG0 X1.1 Z.2\nG76 P010060 Q20 R10\nG76 X.9234 Z-1. P383 Q100 F.0625\n")
    th = [m for m in p.moves if m.kind == "thread"]
    assert th and all(m.code == "G76" for m in th)
    assert min(m.x1 for m in th) == pytest.approx(0.9234, abs=1e-4)
    assert all(m.z1 == pytest.approx(-1.0) for m in th) and th[0].feed == 0.0625


def test_g92_thread_cycle_is_modal():
    p = parse_program("G20\nT0505\nG0 X1.1 Z.2\nG92 X.98 Z-1. F.0625\nX.96\nX.94\nG0 X2.\n")
    th = [m for m in p.moves if m.kind == "thread"]
    assert [round(m.x1, 2) for m in th] == [0.98, 0.96, 0.94]
    assert all(m.z1 == pytest.approx(-1.0) for m in th)


@pytest.mark.parametrize("cycle", ["G81 Z-1. R.1 F.005", "G83 Z-1. Q.25 R.1 F.005", "G74 Z-1. Q2500 F.005"])
def test_drilling_cycles_are_one_feed_in_z_on_the_centerline(cycle):
    p = parse_program(f"G20\nT0202 (1/2 DRILL)\nG0 X0 Z.1\n{cycle}\nG80\n")
    feed = [m for m in p.moves if m.kind == "feed"]
    assert len(feed) == 1
    assert (feed[0].x0, feed[0].x1) == (0, 0) and ends(feed[0]) == (-1.0, 0.0)
    assert not [f for f in p.flags if f.level == "unsupported"]


def test_m30_ends_cleanly_and_spindle_m_codes_are_not_flagged():
    text = HEAD + "M3\nG1 Z-1. F.01\nM5\nM30\n"
    assert len(cuts(text)) == 1 and parse_program(text).flags == []


# ---- flag, don't guess ----
@pytest.mark.parametrize("line, word", [
    ("#100=5.", "macro variable"), ("WHILE [#1 LT 5] DO1", "flow control"), ("IF [#1 EQ 2] GOTO 10", "flow control"),
    ("G65 P9000 A1.", "G65"), ("G10 L2 P1 X0 Z0", "G10"), ("M97 P200", "M97"), ("G37 X1.", "not recognised"),
    ("G75 X.5 P500 F.003", "G75"), ("G32 Z-1. F.0625", "G32"),
])
def test_what_is_not_understood_is_flagged_with_its_line(line, word):
    p = parse_program(HEAD + line + "\n")
    hits = [f for f in p.flags if word in f.text]
    assert hits and hits[0].line == 4


def test_m98_to_a_missing_subprogram_is_flagged_not_guessed():
    p = parse_program(HEAD + "M98 P2000\nM30\n")
    assert any("O2000" in f.text and f.line == 4 for f in p.flags)


def test_m98_in_file_subprogram_is_expanded_and_noted():
    p = parse_program(HEAD + "M98 P2000 L2\nM30\nO2000\nG1 W-.5 F.01\nM99\n")
    assert len([m for m in p.moves if m.kind == "feed"]) == 2
    assert any(f.level == "info" and f.line == 4 for f in p.flags)


def test_the_fixture_program_flags_only_its_g50_line():
    p = parse_program((FIXTURES / "stepped_shaft.nc").read_text())
    assert [(f.line, f.level) for f in p.flags] == [(6, "warn")]
    assert "G50" in p.flags[0].text


# ---- lathe / mill detection ----
def test_the_fixture_reads_as_a_lathe_with_its_reasons():
    d = detect_machine((FIXTURES / "stepped_shaft.nc").read_text().splitlines())
    assert d.machine == "lathe" and d.mill == 0
    found = {t.label for t in d.tells if t.found}
    assert {"T0101-style calls", "G96+G50", "G95/G99 feed per rev", "U/W words"} <= found
    assert d.summary.endswith(f"{d.lathe} of {d.lathe} point to lathe")
    assert "Y moves NONE" in d.summary and "M6/G43 NONE" in d.summary


def test_a_mill_program_reads_as_a_mill():
    d = detect_machine("G17 G20 G90\nT1 M6\nG43 H1 Z1.\nG0 X1. Y2.\nG99 G81 Z-.5 R.1 F5.\nM30".splitlines())
    assert d.machine == "mill" and d.mill == 3
    assert not next(t for t in d.tells if t.label.startswith("G95")).found      # G99 beside G81 is not feed/rev


def test_a_tell_inside_a_comment_does_not_count():
    d = detect_machine("(USE M6 AND Y AXIS)\nT0101\nG1 X1. Z0 F.01".splitlines())
    assert d.machine == "lathe" and d.mill == 0


# ---- stock + origin guesses ----
def test_round_up_goes_to_the_next_quarter_and_leaves_an_exact_one():
    assert round_up(2.1) == 2.25 and round_up(2.0) == 2.0 and round_up(0.01) == 0.25


def test_round_down_goes_to_the_quarter_below_unless_just_under_the_next():
    assert round_down(2.1) == 2.0 and round_down(1.75) == 1.75 and round_down(3.57) == 3.5
    assert round_down(1.99) == 2.0 and round_down(1.97) == 1.75         # 0.020 below a step still counts as the step


def test_a_facing_pass_starting_at_x2_1_means_a_2_inch_bar():
    g = guess_stock(parse_program(HEAD + "G0 X2.1 Z.1\nG1 Z0 F.01\nX-.03\nG0 Z.1\nX1.5\nG1 Z-1.\n"))
    assert g.od == 2.0 and "X2.1000" in g.reasons["od"]


def test_a_g71_cycle_starting_at_x1_75_means_a_1_75_bar_even_though_the_cuts_are_smaller():
    g = guess_stock(parse_program("G20\nT0101\nG0 X1.75 Z.1\nG71 U.1 R.05\nG71 P10 Q20 U.02 W.005 F.01\n"
                                  "N10 G0 X1.\nG1 Z-1.\nX1.5\nN20 Z-1.5\nG0 X1.75 Z.1\nG28 U0 W0\nM30\n"))
    assert g.od == 1.75


def test_a_negative_x_program_is_sized_by_the_size_of_x_not_its_sign():
    """Mori Seiki style: the OD is X-3.5 and the facing cut ends just past centre at X+0.0625."""
    g = guess_stock(parse_program("G20\nT0101\nG0 X-3.57 Z1.5\nZ0.1\nG1 Z0 F.01\nX0.0625\nZ0.1\nG0 X-3.57 Z0.125\n"
                                  "G1 Z-.55\nG0 X-3.57 Z1.5\nG28 U0.\nM30\n"))
    assert g.od == 3.5 and g.max_cut_dia == pytest.approx(3.57)


def test_a_tool_change_retract_does_not_make_the_bar_huge():
    g = guess_stock(parse_program(HEAD + "G1 Z0 F.01\nX-.03\nG0 X1.6 Z.1\nG1 Z-1.\nG0 X1.7 Z.1\n"
                                  "G28 U0 W0\nG0 X20. Z12.\nM30\n"))
    assert g.od == 2.0 and g.max_cut_dia == pytest.approx(2.0)      # the X2. approach in HEAD; the G0 X20 / G28 parking
                                                                    # spot after the last cut is not the stock


def test_the_bar_runs_an_inch_past_the_deepest_cut():
    g = guess_stock(parse_program(HEAD + "G1 Z0 F.01\nX-.03\nG0 Z.1\nX1.5\nG1 Z-1.\n"))
    assert g.length == 2.0 and "plus 1.000 more" in g.reasons["length"]


def test_stock_guess_for_the_stepped_shaft():
    g = guess_stock(parse_program((FIXTURES / "stepped_shaft.nc").read_text()))
    assert g.max_cut_dia == pytest.approx(2.1) and g.od == 2.0          # faces from X2.1: the bar is 2.000 (down, not up)
    assert g.z0 == "finished" and "above Z0" in g.reasons["z0"]     # the FIRST face is the rough one at Z.05
    assert g.front == pytest.approx(0.05)
    assert g.length == 2.25                             # 0.05 in front + 1.000 of cuts + 1.000 more, up to the next 0.250
    assert set(g.reasons) == {"od", "length", "front", "z0"}
    assert stock_z_range(g.z0, g.length, g.front) == pytest.approx((-2.2, 0.05))


def test_z0_is_the_finished_face_when_the_first_facing_pass_ends_at_z0():
    p = parse_program(HEAD + "G1 Z0 F.01\nX-.03\nG0 Z.1\nX1.5\nG1 Z-1.\n")
    assert first_facing_pass(p).line == 5
    g = guess_stock(p)
    assert g.z0 == "finished" and "ends at Z0" in g.reasons["z0"]


def test_z0_is_the_stock_face_when_facing_cuts_below_it():
    g = guess_stock(parse_program(HEAD + "G1 Z-.02 F.01\nX-.03\nG0 Z.1\nX1.5\nG1 Z-1.\n"))
    assert g.z0 == "stock" and g.front == 0.0
    assert stock_z_range("stock", g.length, 0.0) == (-g.length, 0.0)


def test_z0_is_the_back_face_when_every_cut_is_above_it():
    g = guess_stock(parse_program("G20\nT0101\nG0 X2.1 Z2.\nG1 X-.03 F.01\nG0 X1.5 Z2.1\nG1 Z1.\n"))
    assert g.z0 == "back" and g.length == 3.0           # 2.000 of cuts + 1.000 more
    assert stock_z_range("back", g.length, 0.0) == (0.0, 3.0)


def test_no_cutting_moves_gives_placeholders_that_say_so():
    g = guess_stock(parse_program("G20\nG0 X1. Z1.\nM30\n"))
    assert "no cutting moves" in g.reasons["od"]


# ---- the module stands alone ----
def test_the_stdlib_half_does_not_import_qt():
    code = "import sys, gsend_cad.gcode_import; sys.exit(1 if any('PySide6' in m for m in sys.modules) else 0)"
    assert subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parent.parent).returncode == 0
