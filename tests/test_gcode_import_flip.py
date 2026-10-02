"""G-code import: flip programs - OP1 and OP2 in one program, the part turned end for end between them.

flip_part.nc is a 2.000 long part. OP1 faces it and turns dia 1.500 to Z-1.2; the program says FLIP PART; OP2 faces the
other end and turns dia 1.000 for 0.500. Known answer, in OP1's frame (Z0 = the front, the part runs to Z-2.0):
dia 1.5 for Z0..-1.2, the uncut 2.0 bar for Z-1.2..-1.5, dia 1.0 for Z-1.5..-2.0.

    python -m pytest -q tests/test_gcode_import_flip.py
"""
from pathlib import Path

import pytest

from gsend_cad.gcode_import import flip as fl
from gsend_cad.gcode_import import keywords as kw
from gsend_cad.gcode_import import operations, parse_program, tooling
from gsend_cad.gcode_import.stock import guess_stock

FIXTURES = Path(__file__).parent / "fixtures" / "gcode"
TABLE = kw.defaults()
TOL = 0.005
LENGTH = 2.0


def base():
    return parse_program((FIXTURES / "flip_part.nc").read_text())


def flipped(length=LENGTH):
    b = base()
    return fl.with_flip(b, fl.find_marker(b), length)


def program(text):
    return parse_program(text)


# ---- finding the marker ----
def test_the_flip_comment_is_found_after_the_first_cut_and_the_title_is_not_a_marker():
    m = fl.find_marker(base())
    assert (m.line, m.text, m.keyword) == (20, "FLIP PART", "FLIP PART")
    # the title and the header comment both say FLIP / OP2 / OP1, before any cut: neither is a split
    lines = base().lines
    assert "FLIP PART FIXTURE" in lines[1] and "OP2" in lines[2]


@pytest.mark.parametrize("comment", ["OP2", "OP 2", "OP-2", "OP.2", "(2ND OP)", "FLIP", "FLIP PART", "SECOND OPERATION",
                                     "START OP2 HERE", "op2"])
def test_every_flip_keyword_splits_the_program(comment):
    c = comment.strip("()")
    text = f"G20\nT0101\nG0 X2.1 Z0.1\nG1 Z0 F.01\nX-.03\nG0 X2.2 Z.1\nM0 ({c})\nT0202\nG0 X2.1 Z0.1\nG1 Z0 F.01\nX-.03\nM30\n"
    m = fl.find_marker(program(text))
    assert m is not None and m.text.upper() == c.upper()


@pytest.mark.parametrize("comment", ["OP1", "OP20", "OP 21", "STOP", "FLIPPER", "TOP2", "DROP2", "OP ROUGH"])
def test_other_words_are_not_flip_keywords(comment):
    text = f"G20\nT0101\nG0 X2.1 Z0.1\nG1 Z0 F.01\nX-.03\nM0 ({comment})\nT0202\nG0 X2.1 Z0.1\nG1 Z0 F.01\nX-.03\nM30\n"
    assert fl.find_marker(program(text)) is None


def test_op2_in_the_title_alone_is_a_program_that_IS_op2_not_a_split():
    """The shop's own O1678 (...DU100477725 REV A OP2): the whole file is operation 2. Nothing before it."""
    text = ("%\nO1678 (P1000270932 REV A OP2)\n(FACE)\nG20\nT0101\nG0 X2.1 Z0.1\nG1 Z0 F.01\nX-.03\nG0 X2.2 Z.1\n"
            "(OD ROUGH)\nT0202\nG0 X1.5 Z0.1\nG1 Z-1. F.01\nM30\n%")
    assert fl.find_marker(program(text)) is None


def test_a_flip_comment_with_nothing_cut_after_it_is_not_a_split():
    text = "G20\nT0101\nG0 X2.1 Z0.1\nG1 Z0 F.01\nX-.03\nG0 X2.2 Z.1\nM30 (OP2 NEXT)\n"
    assert fl.find_marker(program(text)) is None


def test_the_first_guess_for_the_length_is_how_deep_op1_cuts_to_a_quarter():
    b = base()
    assert fl.guess_length(b, fl.find_marker(b)) == 1.25          # OP1 cuts to Z-1.2


# ---- the model: OP2 mirrored into OP1's frame ----
def test_op2_is_mirrored_about_the_part_and_nothing_else_moves():
    p = flipped()
    mod = fl.model(p)
    assert len(mod.moves) == len(p.moves)
    for a, b in zip(p.moves, mod.moves):
        assert (a.kind, a.code, a.line) == (b.kind, b.code, b.line)
        if a.line < p.flip.line:
            assert (a.z0, a.z1, a.points) == (b.z0, b.z1, b.points)
        else:
            assert b.z0 == pytest.approx(-LENGTH - a.z0) and b.z1 == pytest.approx(-LENGTH - a.z1)
            assert [x for _z, x in b.points] == [x for _z, x in a.points]           # X (the diameter) never changes


def test_a_program_that_is_not_a_flip_is_its_own_model():
    p = program("G20\nT0101\nG0 X2.1 Z0.1\nG1 Z0 F.01\nX-.03\nM30\n")
    assert fl.model(p) is p


def test_arcs_reverse_when_mirrored():
    text = ("G20\nT0101\nG0 X1.0 Z0.1\nG1 Z0 F.01\nG2 X1.5 Z-0.25 R0.25\nG1 Z-0.5\nG0 X2.2 Z0.1\nM0 (OP2)\n"
            "T0101\nG0 X1.0 Z0.1\nG1 Z0 F.01\nG3 X1.5 Z-0.25 R0.25\nG1 Z-0.5\nM30\n")
    p = fl.with_flip(program(text), fl.find_marker(program(text)), 3.0)
    arcs = [(a, b) for a, b in zip(p.moves, fl.model(p).moves) if a.kind == "arc"]
    assert len(arcs) == 2
    first, second = arcs
    assert first[0].clockwise == first[1].clockwise                         # OP1's arc is untouched
    assert second[0].clockwise != second[1].clockwise                       # OP2's turns the other way


# ---- the operations: each half in its own frame ----
def test_each_half_is_its_own_operations_with_a_face_in_each():
    p = flipped()
    ops = operations.build_operations(p, tooling.build_tools(p, TABLE, None), TABLE, None, 0.0)
    assert [(o.part, o.type) for o in ops] == [(1, "FACE"), (1, "OD ROUGH"), (2, "FACE"), (2, "OD ROUGH")]
    assert [o.line0 < p.flip.line for o in ops] == [True, True, False, False]


def test_the_same_tool_in_both_halves_is_never_one_operation():
    p = flipped()                                           # T0101 runs OP1 and OP2 with the same comment
    ops = operations.build_operations(p, tooling.build_tools(p, TABLE, None), TABLE, None, 0.0)
    assert {o.tool for o in ops} == {"01"} and len(ops) == 4


# ---- the stock guess follows the flip ----
def test_the_stock_guess_covers_both_ends_with_no_extra_inch():
    p = flipped()
    g = guess_stock(fl.model(p))
    assert g.od == 2.0 and g.z0 == "finished" and g.front == pytest.approx(0.05)
    assert g.length == 2.25                                 # 0.05 + 2.000 + 0.05, up to the next quarter
    assert "flip program" in g.reasons["length"]
    single = guess_stock(base())                            # not told it is a flip: the plain rule (deepest cut + 1)
    assert "plus 1.000 more" in single.reasons["length"] and "plus 1.000 more" not in g.reasons["length"]


# ---- the reconstruction ----
def run(length=LENGTH, stock_length=None, mutate=None):
    pytest.importorskip("shapely")
    from gsend_cad.gcode_import.reconstruct import reconstruct
    p = flipped(length)
    mod = fl.model(p)
    g = guess_stock(mod)
    stock = {"z0": g.z0, "front": g.front, "id": 0.0, "od": g.od, "length": stock_length or g.length}
    tools = tooling.build_tools(p, TABLE, None)
    ops = operations.build_operations(p, tools, TABLE, None, 0.0)
    return reconstruct(mod, tools, ops, stock, False)


def test_the_two_ops_make_one_two_inch_part():
    r = run()
    assert r.ok and r.pieces == 1
    assert r.z_min == pytest.approx(-LENGTH, abs=1e-6)                     # OP2's face is OP2's Z0
    assert abs(r.diameter_at(-0.5) - 1.5) < TOL and abs(r.diameter_at(-1.35) - 2.0) < TOL
    assert abs(r.diameter_at(-1.75) - 1.0) < TOL                            # OP2's dia 1.0, at the far end
    assert abs(r.diameter_at(-1.95) - 1.0) < TOL


def test_op2_cuts_the_far_end_not_the_front():
    r = run()
    assert abs(r.diameter_at(-0.1) - 1.5) < TOL                             # the front is OP1's 1.5, untouched by OP2
    assert r.count("STOCK") >= 1                                            # the uncut bar between the two cuts


def test_the_part_ends_at_the_overall_length_even_when_the_bar_is_longer():
    r = run(stock_length=5.0)
    assert r.z_min == pytest.approx(-LENGTH, abs=1e-6) and r.pieces == 1


def test_the_length_the_user_types_is_where_op2_sits():
    r = run(length=2.5)
    assert r.z_min == pytest.approx(-2.5, abs=1e-6)
    assert abs(r.diameter_at(-2.25) - 1.0) < TOL and abs(r.diameter_at(-1.35) - 2.0) < TOL


def test_op2s_tool_is_turned_end_for_end_so_its_nose_fillet_is_on_the_right_side():
    """The concave corner at the shoulder (Z-1.5): OP2's tool comes from the far end, so its nose radius leaves the
    fillet on the FAR side of the wall (Z < -1.5). A tool left facing OP1's way would put it on the other side."""
    r = run()
    assert 1.0 < r.diameter_at(-1.51) < 1.07                                # the fillet rising to the wall
    assert abs(r.diameter_at(-1.49) - 2.0) < TOL                            # the wall itself: bar, not tool-cut
    assert abs(r.diameter_at(-1.6) - 1.0) < TOL


G71_FLIP = """%
O3002 (G71 FLIP - SYNTHETIC)
G20 G40 G99
(OP1)
T0101 (OD ROUGH CNMG 432)
G0 X2.1 Z0.1
G71 U0.1 R0.02
G71 P100 Q140 U0.02 W0.005 F0.012
N100 G0 X1.0
N110 G1 Z-0.5 F0.006
N120 X1.5
N130 Z-1.0
N140 X2.0
G70 P100 Q140
G28 U0 W0
M0 (FLIP PART)
(OP2)
T0101 (OD ROUGH CNMG 432)
G0 X2.1 Z0.1
G71 U0.1 R0.02
G71 P200 Q240 U0.02 W0.005 F0.012
N200 G0 X1.0
N210 G1 Z-0.5 F0.006
N220 X1.5
N230 Z-1.0
N240 X2.0
G70 P200 Q240
G28 U0 W0
M30
%"""


def test_the_g71_finish_allowance_W_is_mirrored_with_op2():
    """OP1 and OP2 run the same G71 profile; OP2's final contour in OP1's frame is OP1's mirrored about the part."""
    pytest.importorskip("shapely")
    from gsend_cad.gcode_import.reconstruct import _pq_final
    b = parse_program(G71_FLIP)
    p = fl.with_flip(b, fl.find_marker(b), 3.0)
    mod = fl.model(p)
    ops = operations.build_operations(p, tooling.build_tools(p, TABLE, None), TABLE, None, 0.0)
    g71 = [o for o in ops if o.motion == "G71"]
    assert [o.part for o in g71] == [1, 2]
    one = [pt for run in _pq_final(mod, g71[0]) for pt in run]
    two = [pt for run in _pq_final(mod, g71[1]) for pt in run]
    assert len(one) == len(two) > 3
    for (z1, x1), (z2, x2) in zip(one, two):
        assert x2 == pytest.approx(x1, abs=1e-9)
        assert z2 == pytest.approx(-3.0 - z1, abs=1e-9)         # the W allowance mirrors too, not just the points


def test_a_flip_program_without_its_length_is_one_operation_and_the_far_cut_misses_the_part():
    pytest.importorskip("shapely")
    from gsend_cad.gcode_import.reconstruct import reconstruct
    b = base()                                              # not told it is a flip: OP2's Z0 lands on OP1's
    g = guess_stock(b)
    tools = tooling.build_tools(b, TABLE, None)
    ops = operations.build_operations(b, tools, TABLE, None, 0.0)
    r = reconstruct(b, tools, ops, {"z0": g.z0, "front": g.front, "id": 0.0, "od": g.od, "length": g.length}, False)
    assert r.ok and abs(r.diameter_at(-1.75) - 1.0) > TOL                   # without the length, no dia 1.0 far end
