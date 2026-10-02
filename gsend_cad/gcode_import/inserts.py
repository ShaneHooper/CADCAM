"""Insert codes and tool sizes read out of a comment. Separate from keywords.

Pure stdlib, inches out.

    ANSI inch   CNMG 432      shape letter -> angle; IC in 1/8", thickness in 1/16", nose radius in 1/64"
    ISO metric  CNMG 120408   edge length in mm, thickness code, nose radius in 0.1 mm
"""
from __future__ import annotations

from dataclasses import dataclass
import re

MM = 25.4
# insert shape letter -> included (nose) angle in degrees; R is round
SHAPE_ANGLE = {"C": 80.0, "D": 55.0, "V": 35.0, "T": 60.0, "S": 90.0, "W": 80.0, "K": 55.0, "E": 75.0, "M": 86.0,
               "A": 85.0, "B": 82.0, "L": 90.0, "H": 120.0, "O": 135.0, "P": 108.0, "R": 0.0}
SHAPE_NAME = {"C": "80° diamond", "D": "55° diamond", "V": "35° diamond", "T": "triangle", "S": "square",
              "W": "trigon", "K": "55° parallelogram", "E": "75° diamond", "M": "86° diamond", "A": "85° parallelogram",
              "B": "82° parallelogram", "L": "rectangle", "H": "hexagon", "O": "octagon", "P": "pentagon", "R": "round"}
_ISO_THICK = {"01": 1.59, "T1": 1.98, "02": 2.38, "T2": 2.78, "03": 3.18, "T3": 3.97, "04": 4.76, "05": 5.56,
              "06": 6.35, "07": 7.94, "09": 9.52}

# shape, clearance, tolerance, type - restricted so ordinary words (TOOL, FACE...) do not match
_LETTERS = r"([CDVTSWKEMABLHOPR])([A-GNOP])([ACE-HJ-NU])([A-CF-HJMNQRTUWX])"
_ISO = re.compile(r"(?<![A-Z0-9])" + _LETTERS + r"[\s-]*(\d{2})([0-9T]\d)(\d{2})(?![0-9])")
_ANSI = re.compile(r"(?<![A-Z0-9])" + _LETTERS + r"[\s-]*(\d)(\d(?:\.5)?)(\d(?:\.5)?)(?![0-9])")


@dataclass(frozen=True)
class Insert:
    code: str               # "CNMG 432" as written, tidied
    system: str             # "ANSI" | "ISO"
    shape: str              # the shape letter
    angle: float            # included angle, degrees (0 for round)
    size: float             # inscribed circle (ANSI) or cutting edge length (ISO), inches
    thickness: float        # inches
    nose_radius: float      # inches
    span: tuple[int, int]   # where it sits in the comment

    @property
    def shape_name(self) -> str:
        return SHAPE_NAME.get(self.shape, self.shape)


def parse_insert(text: str) -> Insert | None:
    """The first insert code in the text, or None."""
    up = text.upper()
    m = _ISO.search(up)
    if m:
        shape = m.group(1)
        thick = _ISO_THICK.get(m.group(6))
        return Insert(f"{''.join(m.group(1, 2, 3, 4))} {m.group(5)}{m.group(6)}{m.group(7)}", "ISO", shape,
                      SHAPE_ANGLE[shape], int(m.group(5)) / MM, (thick or 0.0) / MM, int(m.group(7)) * 0.1 / MM,
                      m.span())
    m = _ANSI.search(up)
    if m:
        shape = m.group(1)
        return Insert(f"{''.join(m.group(1, 2, 3, 4))} {m.group(5)}{m.group(6)}{m.group(7)}", "ANSI", shape,
                      SHAPE_ANGLE[shape], int(m.group(5)) / 8.0, float(m.group(6)) / 16.0, float(m.group(7)) / 64.0,
                      m.span())
    return None


# ---- sizes: drill diameters, groove widths, tap sizes ----
NUMBER_DRILLS = dict(zip(range(1, 81), (
    .2280, .2210, .2130, .2090, .2055, .2040, .2010, .1990, .1960, .1935, .1910, .1890, .1850, .1820, .1800, .1770,
    .1730, .1695, .1660, .1610, .1590, .1570, .1540, .1520, .1495, .1470, .1440, .1405, .1360, .1285, .1200, .1160,
    .1130, .1110, .1100, .1065, .1040, .1015, .0995, .0980, .0960, .0935, .0890, .0860, .0820, .0810, .0785, .0760,
    .0730, .0700, .0670, .0635, .0595, .0550, .0520, .0465, .0430, .0420, .0410, .0400, .0390, .0380, .0370, .0360,
    .0350, .0330, .0320, .0310, .0292, .0280, .0260, .0250, .0240, .0225, .0210, .0200, .0180, .0160, .0145, .0135)))
LETTER_DRILLS = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", (
    .234, .238, .242, .246, .250, .257, .261, .266, .272, .277, .281, .290, .295, .302, .316, .323, .332, .339,
    .348, .358, .368, .377, .386, .397, .404, .413)))

_NUM = r"(\d+\.\d*|\.\d+|\d+)"
_SIZES = (
    ("number", re.compile(r"(?:#|\bNO\.?\s*)(\d{1,2})\b")),
    ("letter", re.compile(r"\bLETTER\s+([A-Z])\b|(?<![A-Z0-9])([A-Z])\s+(?:DRILL|DR\b)")),
    ("metric", re.compile(r"(?<![A-Z0-9.])" + _NUM + r"\s*MM\b")),
    ("mixed", re.compile(r"(?<![\d./])(\d+)[-\s](\d+)/(\d+)(?![\d/])")),
    ("fraction", re.compile(r"(?<![\d./])(\d+)/(\d+)(?![\d/])")),
    ("decimal", re.compile(r"(?<![\d.A-Z])(\d*\.\d+)(?![\d.])")),
)
_METRIC_THREAD = re.compile(r"(?<![A-Z0-9])M" + _NUM + r"\s*X\s*" + _NUM)
_INCH_THREAD = re.compile(r"(?<![\d./])(\d+/\d+|\d*\.\d+)\s*-\s*(\d+)(?![\d/.])")


@dataclass(frozen=True)
class Size:
    value: float            # inches
    text: str               # as written
    kind: str               # "number" | "letter" | "metric" | "mixed" | "fraction" | "decimal" | "thread"
    pitch: float | None = None      # threads only, inches


def parse_size(text: str) -> Size | None:
    """A drill diameter / width / tap size written in a comment, or None.

    1/2, 1-1/8, .201, 8MM, #7, LETTER F (or F DRILL), 1/4-20, M8X1.25. An insert code is
    skipped first so its digits are not read as a size."""
    up = text.upper()
    ins = parse_insert(up)
    if ins:
        up = up[:ins.span[0]] + " " * (ins.span[1] - ins.span[0]) + up[ins.span[1]:]
    m = _METRIC_THREAD.search(up)
    if m:
        return Size(float(m.group(1)) / MM, m.group(0), "thread", float(m.group(2)) / MM)
    m = _INCH_THREAD.search(up)
    if m and int(m.group(2)) > 0:
        return Size(_number(m.group(1)), m.group(0), "thread", 1.0 / int(m.group(2)))
    for kind, pat in _SIZES:
        m = pat.search(up)
        if not m:
            continue
        if kind == "number":
            n = int(m.group(1))
            if n in NUMBER_DRILLS:
                return Size(NUMBER_DRILLS[n], m.group(0).strip(), kind)
        elif kind == "letter":
            return Size(LETTER_DRILLS[m.group(1) or m.group(2)], m.group(0).strip(), kind)
        elif kind == "metric":
            return Size(float(m.group(1)) / MM, m.group(0), kind)
        elif kind == "mixed" and int(m.group(3)):
            return Size(int(m.group(1)) + int(m.group(2)) / int(m.group(3)), m.group(0), kind)
        elif kind == "fraction" and int(m.group(2)):
            return Size(int(m.group(1)) / int(m.group(2)), m.group(0), kind)
        elif kind == "decimal":
            return Size(float(m.group(1)), m.group(0), kind)
    return None


def _number(text: str) -> float:
    if "/" in text:
        a, b = text.split("/")
        return int(a) / int(b)
    return float(text)
