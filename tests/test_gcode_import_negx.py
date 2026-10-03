"""G-code import: programs written with NEGATIVE X diameters (rear-turret lathes, e.g. Mori Seiki: OD = X-3.5).

The part is turned about the centerline, so the sign must not matter. Each fixture is rewritten the way such a
machine would write it - every X negated, and the finish allowance U on a G71 / G72 P-Q line (a depth-of-cut U
on the first line stays positive) - and must read back as the SAME part as the original.

    python -m pytest -q tests/test_gcode_import_negx.py
"""
import re
from pathlib import Path

import pytest

from gsend_cad.gcode_import import keywords as kw
from gsend_cad.gcode_import import operations, parse_program, tooling
from gsend_cad.gcode_import.parser import looks_x_negative
from gsend_cad.gcode_import.stock import guess_stock

FIXTURES = Path(__file__).parent / "fixtures" / "gcode"
NAMES = sorted(p.name for p in FIXTURES.glob("*.nc"))
TABLE = kw.defaults()
_NUM = r"-?(?:\d+\.?\d*|\.\d+)"


def negate(text: str) -> str:
    """The program as a negative-X machine writes it."""
    def flip(m):
        return f"{m.group(1)}{-float(m.group(2)):.6f}"

    out = []
    for line in text.splitlines():
        code, paren, comment = line.partition("(")
        code = re.sub(rf"(?<![A-Za-z])(X)({_NUM})", flip, code)
        if re.search(r"(?<![A-Za-z])P\d", code) and re.search(r"(?<![A-Za-z])Q\d", code):
            code = re.sub(rf"(?<![A-Za-z])(U)({_NUM})", flip, code)            # the allowance, not the depth of cut
        out.append(code + paren + comment)
    return "\n".join(out) + "\n"


def read(name):
    return (FIXTURES / name).read_text()


@pytest.mark.parametrize("name", NAMES)
def test_a_negative_x_program_is_read_as_the_same_moves(name):
    pos, neg = parse_program(read(name)), parse_program(negate(read(name)))
    assert not pos.x_inverted and neg.x_inverted
    assert len(pos.moves) == len(neg.moves)
    for a, b in zip(pos.moves, neg.moves):
        assert (a.kind, a.code, a.line) == (b.kind, b.code, b.line)
        assert [(z, x) for z, x in b.points] == pytest.approx([(z, x) for z, x in a.points], abs=1e-5)


@pytest.mark.parametrize("name", NAMES)
def test_the_stock_guess_is_the_same_either_way(name):
    a, b = guess_stock(parse_program(read(name))), guess_stock(parse_program(negate(read(name))))
    assert (a.od, a.length, a.z0, a.front) == (b.od, b.length, b.z0, b.front)


@pytest.mark.parametrize("name", NAMES)
def test_the_reconstruction_is_the_same_part_either_way(name):
    pytest.importorskip("shapely")
    from gsend_cad.gcode_import.reconstruct import reconstruct

    def run(text):
        p = parse_program(text)
        g = guess_stock(p)
        stock = {"z0": g.z0, "front": g.front if g.z0 == "finished" else 0.0, "id": 0.0, "od": g.od, "length": g.length}
        tools = tooling.build_tools(p, TABLE, None)
        ops = operations.build_operations(p, tools, TABLE, None, 0.0)
        return reconstruct(p, tools, ops, stock, False)
    a, b = run(read(name)), run(negate(read(name)))
    assert a.ok and b.ok
    assert b.area == pytest.approx(a.area, abs=1e-6) and len(b.edges) == len(a.edges)
    assert (b.max_dia, b.length) == pytest.approx((a.max_dia, a.length), abs=1e-6)
    assert [e.tag for e in b.edges] == [e.tag for e in a.edges]


def test_the_g71_allowance_sign_flips_with_x():
    """G71 U-0.04 (negative X) is the allowance G71 U0.04 is on a positive-X machine."""
    pytest.importorskip("shapely")
    from gsend_cad.gcode_import.reconstruct import _pq_final

    def final(text):
        p = parse_program(text)
        ops = operations.build_operations(p, tooling.build_tools(p, TABLE, None), TABLE, None, 0.0)
        op = next(o for o in ops if o.motion == "G71")
        return [pt for run in _pq_final(p, op) for pt in run]          # the P-Q contour at FINAL size
    assert "U0.02" in read("g71_pq.nc") and "U-0.020000" in negate(read("g71_pq.nc"))
    pos, neg = final(read("g71_pq.nc")), final(negate(read("g71_pq.nc")))
    assert pos and neg == pytest.approx(pos, abs=1e-9)


def test_a_positive_program_that_faces_just_past_centre_is_not_mirrored():
    p = parse_program(read("stepped_shaft.nc"))             # faces to X-0.03
    assert min(x for m in p.moves for _z, x in m.points) < 0 and not p.x_inverted and not looks_x_negative(p)
    assert not any("negative diameters" in f.text for f in p.flags)


def test_a_mori_facing_cut_across_centre_does_not_stop_the_mirror():
    p = parse_program("G20\nT0101\nG0 X-3.57 Z1.5\nZ0.1\nG1 Z0 F.01\nX0.0625\nZ0.1\nG0 X-3.57 Z0.125\nG1 Z-.55\n"
                      "X-3.2\nG0 X-3.57 Z1.5\nG28 U0.\nM30\n")
    assert p.x_inverted and max(x for m in p.moves if m.kind != "rapid" for _z, x in m.points) == pytest.approx(3.57)


def test_the_mirror_says_so_and_can_be_forced_either_way():
    neg = negate(read("stepped_shaft.nc"))
    p = parse_program(neg)
    assert p.flags[0].level == "info" and "negative diameters" in p.flags[0].text and p.flags[0].line == 0
    assert parse_program(read("stepped_shaft.nc"), invert_x=True).x_inverted          # forced on
    raw = parse_program(neg, invert_x=False)                                          # forced off: left as written
    assert not raw.x_inverted and min(x for m in raw.moves for _z, x in m.points) < -2.0
