"""G-code import, Phase 2: keyword matching, the insert-code and size parsers, the tool list.

Stdlib-only:
    python -m pytest -q tests/test_gcode_import_tools.py
"""
from dataclasses import replace
from pathlib import Path

import pytest

from gsend_cad.gcode_import import keywords as kw
from gsend_cad.gcode_import import parse_program, tooling
from gsend_cad.gcode_import.inserts import parse_insert, parse_size

FIXTURES = Path(__file__).parent / "fixtures" / "gcode"
TABLE = kw.defaults()


def names(comment, table=TABLE):
    return [m.keyword for m in kw.match(comment, table)]


# ---- keyword matching ----
def test_the_shipped_defaults():
    assert [r["keyword"] for r in TABLE] == [
        "FACE GROOVE", "OD FINISH", "OD ROUGH", "ID FINISH", "ID ROUGH", "CUTOFF", "GROOVE", "THREAD",
        "UN", "UNC", "UNF", "UNEF", "NPT", "TPI", "ACME", "FINISH", "ROUGH", "DRILL", "BORE", "FACE", "SPOT", "TAP"]
    assert all(r["source"] == "DEFAULT" for r in TABLE)


def test_the_longest_match_wins_and_uses_up_its_text():
    assert names("FACE GROOVE .125 WIDE") == ["FACE GROOVE"]            # not FACE, not GROOVE
    assert names("OD ROUGH CNMG 432") == ["OD ROUGH"]                   # not ROUGH as well
    assert names("FACE AND OD FINISH") == ["FACE", "OD FINISH"]         # two keywords, in comment order


def test_whole_words_only():
    assert names("DRILLING") == [] and names("TAPER TURN") == [] and names("SURFACE") == []
    assert names("1/2 DRILL") == ["DRILL"] and names("DRILL-1/2") == ["DRILL"]


def test_case_does_not_matter_and_spacing_is_loose():
    assert names("od   rough") == ["OD ROUGH"] and names("Face Groove") == ["FACE GROOVE"]


def test_a_dash_means_leave_it_to_motion():
    face = kw.match("FACE", TABLE)[0]
    bore = kw.match("BORE", TABLE)[0]
    assert (face.tool, face.op) == (None, "FACE") and (bore.tool, bore.op) == ("BORING BAR", None)


def test_user_keywords_are_stored_as_json_and_come_back(tmp_path):
    path = tmp_path / "sub" / "keywords.json"
    assert kw.load(path) == kw.defaults()                               # no file yet -> defaults
    table = kw.add(kw.defaults(), "wiper  tool", "OD TURN", None)
    kw.save(path, table)
    back = kw.load(path)
    assert back[0] == {"keyword": "WIPER TOOL", "tool": "OD TURN", "op": None, "source": "USER"}
    assert len(back) == len(TABLE) + 1 and names("WIPER TOOL", back) == ["WIPER TOOL"]


def test_thread_designators_read_as_a_thread_tool():
    for comment in ("2.75-8 UN", "1/4-20 UNC TAP", "1/8 NPT", "16 TPI THREAD", "ACME 1/2-10"):
        r = tooling.read_comment(comment, TABLE)
        assert "THREAD" in (r.tool_type, *r.ops) or r.tool_type == "TAP", comment
    assert tooling.read_comment("2.75-8 UN", TABLE).tool_type == "THREAD"
    assert names("UNDERCUT") == [] and names("RUN") == []                    # whole words only


def test_a_user_tool_type_cuts_like_the_built_in_it_was_given(tmp_path, monkeypatch):
    monkeypatch.setattr(kw, "_CUSTOM", {})
    assert kw.add_tool_type("back bore", "BORING BAR") == "BACK BORE"
    assert kw.add_tool_type("", "BORING BAR") is None and kw.add_tool_type("X", "NOT A TYPE") is None
    assert kw.add_tool_type("OD TURN", "DRILL") == "OD TURN" and kw.base_of("OD TURN") == "OD TURN"   # built-ins stay
    assert kw.base_of("BACK BORE") == "BORING BAR" and "BACK BORE" in kw.all_tool_types()
    assert tooling.default_side("BACK BORE") == "ID"
    t = replace(tooling.build_tools(parse_program(MULTI), TABLE)[2], type="BACK BORE", nose_assumed=True, insert="")
    assert t.base == "BORING BAR" and "Nose radius" in t.assumed
    # it is saved with the keywords and comes back, and a keyword may point at it
    path = tmp_path / "kw.json"
    kw.save(path, kw.add(kw.defaults(), "BB", "BACK BORE", None))
    monkeypatch.setattr(kw, "_CUSTOM", {})
    table = kw.load(path)
    assert kw.custom_types() == {"BACK BORE": "BORING BAR"} and table[0]["tool"] == "BACK BORE"
    assert tooling.read_comment("BB", table).tool_type == "BACK BORE"


def test_adding_an_existing_keyword_replaces_it_and_a_bad_file_falls_back(tmp_path):
    table = kw.add(kw.defaults(), "GROOVE", "FACE GROOVE", "FACE GROOVE")
    assert len(table) == len(TABLE) and table[0]["source"] == "USER"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert kw.load(bad) == kw.defaults()


# ---- insert codes ----
def test_ansi_inch_code():
    i = parse_insert("OD ROUGH CNMG 432")
    assert (i.system, i.shape, i.angle, i.code) == ("ANSI", "C", 80.0, "CNMG 432")
    assert (i.size, i.thickness, i.nose_radius) == (0.5, 3 / 16, 2 / 64)     # IC 4/8, T 3/16, R 2/64


@pytest.mark.parametrize("code, angle, ic, nose", [
    ("DNMG 431", 55.0, 0.5, 1 / 64), ("VNMG331", 35.0, 0.375, 1 / 64), ("TNMG 333", 60.0, 0.375, 3 / 64),
    ("WNMG 432", 80.0, 0.5, 2 / 64), ("CCMT 32.51", 80.0, 0.375, 1 / 64), ("DCMT 21.51", 55.0, 0.25, 1 / 64),
    ("VBMT 221", 35.0, 0.25, 1 / 64), ("CCGT 21.50.5", 80.0, 0.25, 0.5 / 64),
])
def test_ansi_codes(code, angle, ic, nose):
    i = parse_insert(code)
    assert i.system == "ANSI" and (i.angle, i.size) == (angle, ic) and i.nose_radius == pytest.approx(nose)


def test_iso_metric_code():
    i = parse_insert("CNMG 120408")
    assert (i.system, i.angle, i.code) == ("ISO", 80.0, "CNMG 120408")
    assert i.size == pytest.approx(12 / 25.4) and i.nose_radius == pytest.approx(0.8 / 25.4)
    assert i.thickness == pytest.approx(4.76 / 25.4)


@pytest.mark.parametrize("code, angle, nose_mm", [("DNMG 150604", 55.0, 0.4), ("CCMT 09T304", 80.0, 0.4),
                                                  ("VBMT160408", 35.0, 0.8), ("TNMG 160412", 60.0, 1.2)])
def test_iso_codes(code, angle, nose_mm):
    i = parse_insert(code)
    assert i.system == "ISO" and i.angle == angle and i.nose_radius == pytest.approx(nose_mm / 25.4)


@pytest.mark.parametrize("text", ["TOOL 432", "FACE 120408", "T0101", "OD ROUGH", "1/2 DRILL", "CNMG"])
def test_ordinary_words_are_not_insert_codes(text):
    assert parse_insert(text) is None


# ---- drill / tap / width sizes ----
@pytest.mark.parametrize("text, value", [
    ("1/2 DRILL", 0.5), ("27/64 DRILL", 27 / 64), ("1-1/8 DRILL", 1.125), (".201 DRILL", 0.201),
    ("0.3125 DIA DRILL", 0.3125), ("8MM DRILL", 8 / 25.4), ("8.5 MM DRILL", 8.5 / 25.4), ("#7 DRILL", 0.201),
    ("NO. 21 DRILL", 0.159), ("LETTER F DRILL", 0.257), ("F DRILL", 0.257), (".125 GROOVE", 0.125),
])
def test_sizes_written_in_a_comment(text, value):
    assert parse_size(text).value == pytest.approx(value)


def test_tap_sizes_carry_their_pitch():
    a, b = parse_size("1/4-20 TAP"), parse_size("M8X1.25 TAP")
    assert (a.value, a.pitch) == (0.25, 0.05)
    assert b.value == pytest.approx(8 / 25.4) and b.pitch == pytest.approx(1.25 / 25.4)


def test_an_insert_codes_digits_are_not_a_size_and_no_size_is_none():
    assert parse_size("CCMT 32.51") is None and parse_size("OD ROUGH CNMG 432") is None
    assert parse_size("DRILL") is None and parse_size("#99 DRILL") is None


# ---- the tool list ----
MULTI = """O2000 (MULTI TOOL)
G20 G40 G99
T0101 (OD ROUGH CNMG 432)
G50 S3000
G96 S400 M3
G0 X2.1 Z0
G1 X-0.03 F0.008
G0 X1.5 Z0.1
G1 Z-1.5 F0.01
X2.1
G28 U0 W0
T0202 (1/2 DRILL)
G97 S1200 M3
G0 X0 Z0.1
G83 Z-1.0 Q0.25 R0.1 F0.005
G80
G28 U0 W0
(BORE)
T0303
G0 X0.5 Z0.1
G1 Z-0.9 F0.006
X0.45
G0 Z0.1
X0.75
G1 Z-0.9
X0.7
G0 Z0.1
G28 U0 W0
T0404
G0 X1.6 Z-0.5
G1 X1.2 F0.003
G0 X1.6
G28 U0 W0
T0505
G0 X1.6 Z0.2
G76 P010060 Q20 R10
G76 X1.4234 Z-0.4 P383 Q100 F0.0625
G28 U0 W0
T0606 (PARTING BLADE)
G0 X2.2 Z-1.4
G28 U0 W0
M30
"""


@pytest.fixture(scope="module")
def tools():
    return {t.number: t for t in tooling.build_tools(parse_program(MULTI), TABLE)}


def test_one_row_per_tool_in_program_order(tools):
    assert list(tools) == ["01", "02", "03", "04", "05", "06"]
    assert tooling.counts(list(tools.values())) == {"READ": 3, "GUESSED": 2, "UNKNOWN": 1, "DEFINED": 0}


def test_a_keyword_and_insert_code_make_a_tool_read(tools):
    t = tools["01"]
    assert (t.type, t.status, t.side, t.keywords) == ("OD TURN", "READ", "OD", ("OD ROUGH",))
    assert (t.insert, t.shape_angle, t.nose_radius, t.nose_assumed) == ("CNMG 432", 80.0, 1 / 32, False)
    assert t.ops == ("OD ROUGH",) and t.resolved and t.assumed == "Nothing assumed."


def test_a_drill_reads_its_size_from_the_comment(tools):
    t = tools["02"]
    assert (t.type, t.status, t.side, t.size, t.size_text) == ("DRILL", "READ", "CENTER", 0.5, "1/2")
    assert t.resolved


def test_a_comment_line_above_the_t_call_is_its_comment(tools):
    t = tools["03"]
    assert t.comment == "BORE" and (t.type, t.status, t.side) == ("BORING BAR", "READ", "ID")
    assert t.nose_radius == tooling.DEFAULT_NOSE and t.nose_assumed            # no insert code written down
    assert "default" in t.assumed and not t.resolved


def test_no_keyword_but_the_motion_says_groove(tools):
    t = tools["04"]
    assert (t.type, t.status, t.side) == ("GROOVE", "GUESSED", "OD") and "X plunges" in t.why and not t.resolved


def test_no_keyword_but_a_g76_means_a_thread_tool(tools):
    t = tools["05"]
    assert (t.type, t.status) == ("THREAD", "GUESSED") and "G76" in t.why


def test_no_keyword_and_no_cutting_is_unknown_and_a_sharp_point(tools):
    t = tools["06"]
    assert (t.type, t.status, t.nose_radius) == ("UNKNOWN", "UNKNOWN", 0.0)
    assert "sharp point" in t.assumed and "ASSUMED" in t.assumed


def test_the_same_motion_with_a_keyword_is_read_not_guessed():
    text = MULTI.replace("T0404", "T0404 (.125 GROOVE)")
    t = {x.number: x for x in tooling.build_tools(parse_program(text), TABLE)}["04"]
    assert (t.type, t.status, t.size) == ("GROOVE", "READ", 0.125)


def test_motion_guesses_drill_face_and_cutoff_and_bore():
    text = ("G20\nT0101\nG0 X2.1 Z0\nG1 X-.03 F.01\nG28 U0 W0\n"                   # facing only
            "T0202\nG0 X0 Z.1\nG1 Z-1. F.005\nG0 Z.1\nG28 U0 W0\n"                 # Z-only at X0
            "T0303\nG0 X.5 Z.1\nG1 Z-.9 F.006\nX.45\nG0 Z.1\nG28 U0 W0\n"          # inside the hole, cutting outward
            "T0404\nG0 X2.2 Z-1.5\nG1 X-.03 F.003\nG0 X2.2\nG28 U0 W0\n")          # plunge to the centerline at the back
    t = {x.number: x for x in tooling.build_tools(parse_program(text), TABLE)}
    assert [(t[n].type, t[n].side) for n in ("01", "02", "03", "04")] == [
        ("OD TURN", "OD"), ("DRILL", "CENTER"), ("BORING BAR", "ID"), ("CUTOFF", "OD")]
    assert all(x.status == "GUESSED" for x in t.values())


def test_a_user_defined_tool_overrides_and_is_defined(tools):
    program = parse_program(MULTI)
    mine = replace(tools["06"], type="CUTOFF", size=0.118, nose_assumed=False)
    out = {t.number: t for t in tooling.build_tools(program, TABLE, {"06": mine})}
    assert (out["06"].type, out["06"].status, out["06"].size) == ("CUTOFF", "DEFINED", 0.118) and out["06"].resolved
    assert out["01"].status == "READ"                                   # the others are untouched


def test_typing_an_insert_code_fills_shape_and_nose_radius(tools):
    t = tooling.apply_insert(tools["03"], "ccmt 32.51")
    assert (t.insert, t.shape_angle, t.nose_radius, t.nose_assumed) == ("CCMT 32.51", 80.0, 1 / 64, False)
    junk = tooling.apply_insert(tools["03"], "abc")
    assert junk.insert == "ABC" and junk.nose_assumed                   # not a code: nothing is filled in


def test_next_unresolved_walks_the_ones_that_need_defining_and_wraps(tools):
    ts = list(tools.values())
    assert tooling.next_unresolved(ts) == 2                             # T03: nose radius is a default
    assert tooling.next_unresolved(ts, 2) == 3 and tooling.next_unresolved(ts, 5) == 2


def test_a_saved_keyword_identifies_the_tool_next_time(tools):
    table = kw.add(TABLE, tooling.keyword_suggestion(tools["06"].comment), "CUTOFF", None)
    assert table[0]["keyword"] == "PARTING BLADE"
    t = {x.number: x for x in tooling.build_tools(parse_program(MULTI), table)}["06"]
    assert (t.type, t.status) == ("CUTOFF", "READ") and "PARTING BLADE" in t.why


def test_the_test_a_comment_reading():
    r = tooling.read_comment("OD ROUGH CNMG 432", TABLE)
    assert (r.tool_type, r.ops, r.nose_radius, r.insert.code) == ("OD TURN", ("OD ROUGH",), 1 / 32, "CNMG 432")
    r = tooling.read_comment("FACE AND FINISH", TABLE)
    assert (r.tool_type, r.ops, r.nose_radius) == (None, ("FACE", "FINISH"), None)


def test_the_fixture_program_has_one_read_tool():
    ts = tooling.build_tools(parse_program((FIXTURES / "stepped_shaft.nc").read_text()), TABLE)
    assert [(t.number, t.type, t.status, t.insert) for t in ts] == [("01", "OD TURN", "READ", "CNMG 432")]
