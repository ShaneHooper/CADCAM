"""G-code import, Phase 4: the reconstruction (sweep the tool shapes, subtract, keep what is left).

Synthetic fixtures with known answers. Pass criterion: within 0.005" ABSOLUTE of the known
geometry (never a percentage).

    python -m pytest -q tests/test_gcode_import_reconstruct.py
"""
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("shapely")

from gsend_cad.gcode_import import keywords as kw                      # noqa: E402
from gsend_cad.gcode_import import operations, parse_program, tooling  # noqa: E402
from gsend_cad.gcode_import import toolshape as ts                     # noqa: E402
from gsend_cad.gcode_import.reconstruct import reconstruct             # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "gcode"
TABLE = kw.defaults()
TOL = 0.005
BAR = {"z0": "finished", "front": 0.03, "id": 0.0}


def close(value, want):
    return value is not None and abs(value - want) <= TOL


def run(source, stock, nose_center=False, tool_overrides=None, op_types=None, table=TABLE):
    text = (FIXTURES / source).read_text() if source.endswith(".nc") else source
    program = parse_program(text)
    tools = tooling.build_tools(program, table, tool_overrides)
    ops = operations.build_operations(program, tools, table, None, stock.get("id", 0.0))
    if op_types:
        ops = operations.build_operations(program, tools, table, {ops[i].key: t for i, t in op_types.items()},
                                          stock.get("id", 0.0))
    return reconstruct(program, tools, ops, stock, nose_center)


# ---- tool shapes ----
def test_the_imaginary_tip_sits_on_the_nose_circles_two_tangents():
    rn = 1 / 32
    pts = ts.insert(rn, 80.0)                           # about the nose centre
    tz, tr = ts.tip_vector(rn)
    assert min(z for z, _ in pts) == pytest.approx(-rn, abs=1e-6)       # leftmost point: one radius left of centre
    assert min(r for _, r in pts) == pytest.approx(-rn, abs=1e-6)       # lowest point: one radius below
    assert (tz, tr) == (rn, rn)                         # so the tip is at (centre - rn, centre - rn)


def test_an_id_tool_points_at_the_bore_wall_and_a_sharp_tool_is_a_point():
    pts = ts.insert(1 / 64, 80.0, rdir=-1)
    assert max(r for _, r in pts) == pytest.approx(1 / 64, abs=1e-6) and ts.tip_vector(1 / 64, rdir=-1) == (1 / 64, -1 / 64)
    sharp = ts.insert(0.0, None)
    assert (0.0, 0.0) in sharp and min(z for z, _ in sharp) >= -1e-9 and min(r for _, r in sharp) >= -1e-9


def test_drill_and_groove_shapes():
    d = ts.drill(0.5)
    assert d[0] == (0.0, 0.0) and d[1] == pytest.approx((0.25 / 1.6643, 0.25), abs=1e-3)       # 118 degree point
    g = ts.groove(0.125)
    assert (min(z for z, _ in g), max(z for z, _ in g), min(r for _, r in g)) == (0.0, 0.125, 0.0)


# ---- the seven fixtures ----
def test_straight_turn_and_face():
    r = run("turn_and_face.nc", dict(BAR, od=1.25, length=1.25))
    assert r.ok and close(r.z_max, 0.0)                         # faced to Z0
    assert close(r.diameter_at(-0.4), 1.0)                      # the turned diameter
    assert close(r.diameter_at(-0.9), 1.25)                     # uncut bar behind the shoulder
    assert close(r.max_dia, 1.25) and close(r.length, 1.22) and r.bore is None
    assert r.count("ASSUMED") == 0 and r.count("EXACT") >= 3 and r.count("STOCK") >= 2
    assert not [f for f in r.flags if "rapid" in f.text]


def test_stepped_shaft():
    r = run("stepped_shaft.nc", {"z0": "finished", "front": 0.05, "id": 0.0, "od": 2.0, "length": 1.25})
    assert close(r.diameter_at(-0.25), 1.0) and close(r.diameter_at(-0.75), 1.5) and close(r.diameter_at(-1.1), 2.0)
    assert close(r.z_max, 0.0)
    # the shoulders: 1.0 -> 1.5 at Z-0.5 and 1.5 -> 2.0 at Z-1.0
    assert close(r.diameter_at(-0.46), 1.0) and close(r.diameter_at(-0.505), 1.5)
    assert close(r.diameter_at(-0.96), 1.5) and close(r.diameter_at(-1.005), 2.0)
    # ... and the 1/32 nose leaves its radius in each inside corner: 0.010 from the shoulder
    # the fillet stands rn - sqrt(rn^2 - (rn - 0.010)^2) = 0.0083 proud, 0.0167 on diameter
    assert close(r.diameter_at(-0.49), 1.0167) and close(r.diameter_at(-0.99), 1.5167)


def test_a_45_degree_chamfer_cut_with_a_1_32_nose_radius():
    r = run("chamfer_nose.nc", dict(BAR, od=1.25, length=1.5))
    # the nose radius leaves the chamfer rn*(sqrt(2)-1) = 0.0129 outside the programmed line
    assert close(r.diameter_at(-0.05), 0.9366)
    assert not close(r.diameter_at(-0.05), 0.9)                 # what ignoring the radius would give (0.0366 off)
    assert close(r.diameter_at(-0.0005), 0.8376) and close(r.diameter_at(-0.5), 1.0)
    # the chamfer runs out onto the Ø1.000 at Z-0.0817, not at the programmed Z-0.1
    assert close(r.diameter_at(-0.0817), 1.0) and r.diameter_at(-0.07) < 1.0 - 2 * TOL
    assert r.count("ASSUMED") == 0                              # CNMG 432: the radius was read, not assumed


def test_the_same_chamfer_with_cutter_comp_is_cut_on_the_programmed_line():
    text = (FIXTURES / "chamfer_nose.nc").read_text().replace("G1 Z0 F0.006", "G42 G1 Z0 F0.006").replace(
        "X1.35\nG28", "G40 X1.35\nG28")
    r = run(text, dict(BAR, od=1.25, length=1.5))
    assert close(r.diameter_at(-0.05), 0.9) and close(r.diameter_at(-0.5), 1.0)


def test_a_defaulted_nose_radius_marks_the_chamfer_assumed_and_the_straight_cuts_exact():
    text = (FIXTURES / "chamfer_nose.nc").read_text().replace("(OD FINISH CNMG 432)", "(OD FINISH)")
    r = run(text, dict(BAR, od=1.25, length=1.5))
    assumed = [e for e in r.edges if e.tag == "ASSUMED"]
    assert assumed and r.assumed_runs >= 1
    assert all(abs(e.z1 - e.z0) > 1e-7 and abs(e.x1 - e.x0) > 1e-7 for e in assumed)       # only the sloped edges
    assert any(e.tag == "EXACT" and abs(e.x0 - 1.0) < 1e-6 and abs(e.x1 - 1.0) < 1e-6 for e in r.edges)


def test_an_unknown_tool_still_cuts_and_everything_it_cuts_is_assumed():
    text = (FIXTURES / "turn_and_face.nc").read_text().replace("T0101 (OD FINISH CNMG 432)", "T0101")
    program = parse_program(text)
    tools = [replace(t, type="UNKNOWN", status="UNKNOWN", nose_radius=0.0) for t in tooling.build_tools(program, TABLE)]
    ops = operations.build_operations(program, tools, TABLE)
    r = reconstruct(program, tools, ops, dict(BAR, od=1.25, length=1.25))
    assert close(r.diameter_at(-0.4), 1.0) and close(r.z_max, 0.0)
    assert r.count("EXACT") == 0 and r.count("ASSUMED") >= 3


def test_groove():
    r = run("groove.nc", dict(BAR, od=1.25, length=1.5))
    assert close(r.diameter_at(-0.44), 0.8)                     # groove bottom
    assert close(r.diameter_at(-0.3), 1.0) and close(r.diameter_at(-0.55), 1.0)
    # walls at Z-0.5 and Z-0.375 (the blade is 0.125 wide toward +Z from the programmed corner)
    assert close(r.diameter_at(-0.495), 0.8) and close(r.diameter_at(-0.505), 1.0)
    assert close(r.diameter_at(-0.38), 0.8) and close(r.diameter_at(-0.37), 1.0)


def test_drilled_and_bored_id():
    r = run("drill_bore.nc", dict(BAR, od=1.25, length=1.5))
    assert close(r.bore, 0.75) and close(r.bore_at(-0.25), 0.75)
    assert close(r.bore_at(-0.75), 0.5)                         # the drilled hole past the bore
    assert close(r.bore_at(-0.48), 0.75) and close(r.bore_at(-0.505), 0.5)         # bore shoulder at Z-0.5
    assert close(r.bore_at(-0.95), 2 * 0.05 * 1.6643)           # inside the 118 degree drill point
    assert r.bore_at(-1.01) is None and close(r.diameter_at(-0.5), 1.25)


def test_g71_p_q_program():
    stock = {"z0": "stock", "front": 0.0, "id": 0.0, "od": 2.0, "length": 1.5}
    r = run("g71_pq.nc", stock)
    assert close(r.diameter_at(-0.25), 1.0) and close(r.diameter_at(-0.75), 1.5) and close(r.diameter_at(-1.2), 2.0)
    assert close(r.diameter_at(-0.46), 1.0) and close(r.diameter_at(-0.505), 1.5)
    assert len(r.checks) == 1 and "agrees" in r.checks[0] and "N100-N140" in r.checks[0]


def test_a_g71_with_no_finish_pass_still_gives_the_p_q_contour_and_says_so():
    stock = {"z0": "stock", "front": 0.0, "id": 0.0, "od": 2.0, "length": 1.5}
    r = run((FIXTURES / "g71_pq.nc").read_text().replace("G70 P100 Q140\n", ""), stock)
    assert close(r.diameter_at(-0.25), 1.0) and close(r.diameter_at(-0.75), 1.5)
    assert "leave" in r.checks[0] and "used as the profile" in r.checks[0]


def test_g76_thread_is_a_feature_on_its_cylinder_not_a_helix():
    r = run("g76_thread.nc", dict(BAR, od=1.75, length=1.25))
    assert close(r.diameter_at(-0.3), 1.5)                      # the thread tool removed nothing
    assert len(r.threads) == 1
    t = r.threads[0]
    assert close(t.major, 1.5) and close(t.minor, 1.4234) and t.pitch == 0.0625 and "16 TPI" in t.callout


# ---- rules ----
def test_rapids_never_cut_and_a_rapid_into_stock_is_flagged_with_its_line():
    # line 4 rapids diagonally through the bar, from in front of it to above it at the back
    text = "G20 G40 G99\nT0101 (OD FINISH CNMG 432)\nG0 X0.5 Z0.1\nG0 X2.0 Z-1.0\nG1 X1.9 F.005\nG0 X2.0\n"
    stock = dict(BAR, od=1.25, length=1.5, front=0.0)
    r = run(text, stock)
    hits = [f for f in r.flags if "rapid into stock" in f.text]
    assert hits and hits[0].line == 4
    assert r.area == pytest.approx(1.5 * 0.625, abs=1e-6)       # the rapid's path removed nothing
    clear = run(text.replace("G0 X2.0 Z-1.0", "G0 X2.0 Z0.1\nG0 Z-1.0"), stock)
    assert not [f for f in clear.flags if "rapid" in f.text]    # the same move made round the bar is fine


def test_a_skip_operation_contributes_nothing():
    stock = dict(BAR, od=1.25, length=1.5)
    assert close(run("groove.nc", stock).diameter_at(-0.44), 0.8)
    r = run("groove.nc", stock, op_types={2: "SKIP"})
    assert close(r.diameter_at(-0.44), 1.0)


def test_the_type_label_does_not_change_the_geometry():
    stock = dict(BAR, od=1.25, length=1.5)
    a, b = run("groove.nc", stock), run("groove.nc", stock, op_types={2: "CHAMFER", 0: "THREAD"})
    assert a.area == pytest.approx(b.area, abs=1e-9)


def test_a_drill_with_no_diameter_cuts_nothing_and_says_so():
    text = (FIXTURES / "drill_bore.nc").read_text().replace("(1/2 DRILL)", "(DRILL)")
    r = run(text, dict(BAR, od=1.25, length=1.5))
    assert any("no diameter" in f.text for f in r.flags)


def test_defining_a_tool_changes_the_result():
    stock = dict(BAR, od=1.25, length=1.5)
    program = parse_program((FIXTURES / "groove.nc").read_text())
    blade = {t.number: t for t in tooling.build_tools(program, TABLE)}["04"]
    wide = replace(blade, size=0.25)
    r = run("groove.nc", stock, tool_overrides={"04": wide})
    assert close(r.diameter_at(-0.3), 0.8)                      # the wider blade reaches Z-0.25


def test_a_user_tool_type_is_cut_with_the_shape_of_its_base_type(monkeypatch):
    from gsend_cad.gcode_import import keywords as kw
    monkeypatch.setattr(kw, "_CUSTOM", {"WIDE BLADE": "GROOVE"})
    stock = dict(BAR, od=1.25, length=1.5)
    program = parse_program((FIXTURES / "groove.nc").read_text())
    blade = {t.number: t for t in tooling.build_tools(program, TABLE)}["04"]
    r = run("groove.nc", stock, tool_overrides={"04": replace(blade, type="WIDE BLADE")})
    assert close(r.diameter_at(-0.44), 0.8) and close(r.diameter_at(-0.3), 1.0)     # same groove as a GROOVE


def test_a_part_off_keeps_the_front_piece():
    text = (FIXTURES / "turn_and_face.nc").read_text().replace(
        "M30", "T0404 (.118 CUTOFF)\nG0 X1.4 Z-0.618\nG1 X-0.03 F0.003\nG0 X1.4\nM30")
    r = run(text, dict(BAR, od=1.25, length=1.25))
    assert r.pieces == 2 and close(r.z_min, -0.5) and close(r.length, 0.5)
    assert any("part-off" in f.text for f in r.flags)


def test_nose_centre_output_setting_moves_the_cut_by_the_radius():
    stock = dict(BAR, od=1.25, length=1.25)
    tip, centre = run("turn_and_face.nc", stock), run("turn_and_face.nc", stock, nose_center=True)
    assert close(tip.diameter_at(-0.4), 1.0) and close(centre.diameter_at(-0.4), 1.0 - 2 / 32)


def test_tube_stock_starts_with_its_bore():
    r = run("turn_and_face.nc", dict(BAR, od=1.25, length=1.25, id=0.5))
    assert close(r.bore, 0.5) and close(r.bore_at(-0.6), 0.5)


def test_no_material_is_an_error_not_a_crash():
    r = run("turn_and_face.nc", dict(BAR, od=0.5, length=1.25, id=0.75))
    assert not r.ok and "no material" in r.error
