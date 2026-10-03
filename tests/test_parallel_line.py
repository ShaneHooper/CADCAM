"""Parallel lines (a sketch drawing aid, ESPRIT's "Parallel Geometry"): infinite, parallel to an axis or a line, and
never part of a profile.

    python -m pytest -q tests/test_parallel_line.py
"""
import math

import pytest

from gsend_cad.core import sketch as sk
from gsend_cad.core.profiles import sketch_loops


def test_offset_from_the_x_axis_goes_to_the_side_the_cursor_is_on():
    up, off_up = sk.xline_offset((0, 0), (1, 0), (3.0, 1.0), 4.25)
    dn, off_dn = sk.xline_offset((0, 0), (1, 0), (3.0, -1.0), 4.25)
    assert up["p"][1] == pytest.approx(4.25) and up["d"] == pytest.approx([1.0, 0.0]) and off_up == pytest.approx(4.25)
    assert dn["p"][1] == pytest.approx(-4.25) and off_dn == pytest.approx(-4.25)


def test_with_no_typed_distance_it_goes_through_the_cursor():
    e, off = sk.xline_offset((0, 0), (0, 1), (2.5, 7.0))
    assert e["p"][0] == pytest.approx(2.5) and e["d"] == pytest.approx([0.0, 1.0]) and abs(off) == pytest.approx(2.5)


def test_parallel_to_a_slanted_line_is_that_far_away_square_to_it():
    e, _ = sk.xline_offset((0, 0), (3, 4), (-5.0, 5.0), 2.0)
    assert e["d"] == pytest.approx([0.6, 0.8])
    assert abs(sk._cross2(e["d"], e["p"])) == pytest.approx(2.0)          # the perpendicular distance from the line


def test_it_is_drawn_far_each_way_and_labelled_by_its_position():
    e = sk.xline((0, 4.25), (1, 0))
    pts = sk.entity_points(e)
    assert pts[0][0] < -100 and pts[1][0] > 100 and pts[0][1] == pts[1][1] == 4.25
    assert sk.entity_label(e) == ("Parallel", "Y 4.2500")
    assert sk.entity_label(sk.xline((1.5, 0), (0, 1))) == ("Parallel", "X 1.5000")


def test_its_value_is_edited_like_any_other_in_the_palette():
    e = sk.xline((0, 4.25), (1, 0))
    assert sk.params(e) == {"y": 4.25}
    assert sk.set_param(e, "y", 1.0)["p"] == [0.0, 1.0]
    assert sk.params(sk.xline((2, 0), (0, 1))) == {"x": 2.0}
    ents, origin, j = sk.edit([e], [None], 0, "y", 2.0)
    assert ents[j]["p"][1] == 2.0 and ents[j]["type"] == "xline"


def test_it_never_makes_a_profile_and_nothing_trims_it():
    ents = [sk.rect((0, 0), (2, 1)), sk.xline((0, 4.25), (1, 0)), sk.xline((1, 0), (0, 1))]
    loops = sketch_loops(ents)
    assert len(loops) == 1                    # the rectangle; the two parallel lines add nothing
    assert sk.nearest(ents, (5.0, 4.25), 0.1, solid=True) is None
    assert sk.nearest(ents, (5.0, 4.25), 0.1) == 1
    assert sk.trim_preview(ents, (5.0, 4.25), 0.1) is None


def test_the_cursor_snaps_to_where_parallel_lines_cross_the_axes_and_lines():
    ents = [sk.xline((0, 4.25), (1, 0)), sk.xline((1.5, 0), (0, 1)), sk.line((0, 0), (0, 10))]
    pts = {(round(u, 6), round(v, 6)) for u, v, k in sk.snap_points(ents) if k == "cross"}
    assert (1.5, 4.25) in pts                 # one parallel line on the other
    assert (0.0, 4.25) in pts                 # on the Y axis, and on the line drawn along it
    assert (1.5, 0.0) in pts                  # on the X axis
    hit = sk.nearest_snap(sk.snap_points(ents), (1.48, 4.27), 0.1)
    assert hit[2] == "cross" and (hit[0], hit[1]) == pytest.approx((1.5, 4.25))


def test_rotating_or_mirroring_turns_the_line_with_it():
    e = sk.xline((0, 2), (1, 0))
    r = sk.rotated([e], (0, 0), 90)[0]
    assert r["p"] == pytest.approx([-2.0, 0.0]) and r["d"] == pytest.approx([0.0, 1.0])
    m = sk.mirrored([e], (0, 0), (0, 1))[0]
    assert m["p"] == pytest.approx([0.0, 2.0]) and abs(m["d"][0]) == pytest.approx(1.0)


def test_a_direction_is_required():
    with pytest.raises(ValueError):
        sk.xline((0, 0), (0, 0))
