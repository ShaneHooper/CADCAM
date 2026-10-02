"""Lathe or mill? Score the "tells" in a program and say why.

Pure stdlib. Each tell either points at a machine or says nothing; the verdict is a
count of the ones that point, and the reasons are kept so the Setup screen can show them
(the user can always override).
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .parser import WORD_RE, _strip_comments


@dataclass(frozen=True)
class Tell:
    label: str              # "T0101-style calls"
    found: bool
    points: str | None      # "lathe" | "mill" | None (says nothing either way)
    line: int = 0           # first line it was seen on (1-based), 0 when not found

    @property
    def text(self) -> str:
        return f"{self.label} {'FOUND' if self.found else 'NONE'}"


@dataclass(frozen=True)
class Detection:
    machine: str            # "lathe" | "mill"
    tells: tuple[Tell, ...]
    lathe: int              # how many tells point at a lathe
    mill: int

    @property
    def summary(self) -> str:
        """'T0101-style calls FOUND, ... -> 5 of 5 point to lathe'"""
        pointing = [t for t in self.tells if t.points]
        votes = self.lathe if self.machine == "lathe" else self.mill
        if not pointing:
            return "no tells found -> assumed lathe"
        return f"{', '.join(t.text for t in pointing)} -> {votes} of {len(pointing)} point to {self.machine}"


_T4 = re.compile(r"\bT\s*(\d{3,4})\b", re.I)
_LATHE_CYCLES = {70, 71, 72, 75, 76, 92}     # G73/G74 are left out: on a mill they are drilling cycles


def detect_machine(lines: list[str]) -> Detection:
    first: dict[str, int] = {}

    def see(key: str, number: int):
        first.setdefault(key, number)

    for i, raw in enumerate(lines):
        code = _strip_comments(raw)
        if not code.strip():
            continue
        words = [(l.upper(), v) for l, v in WORD_RE.findall(code)]
        gs = {int(round(float(v))) for l, v in words if l == "G"}
        ms = {int(round(float(v))) for l, v in words if l == "M"}
        letters = {l for l, _ in words}
        n = i + 1
        if _T4.search(code):
            see("t4", n)
        if 96 in gs or (50 in gs and "S" in letters):
            see("css", n)
        # G99 next to a drilling cycle is a mill's "return to R plane", not feed per rev
        if 95 in gs or (99 in gs and not (gs & set(range(73, 90)))):
            see("fpr", n)
        if ("U" in letters or "W" in letters) and 4 not in gs:
            see("uw", n)
        if gs & _LATHE_CYCLES and "Y" not in letters:
            see("cycle", n)
        if "Y" in letters:
            see("y", n)
        if 6 in ms or (43 in gs and "H" in letters):
            see("m6", n)
        if 17 in gs:
            see("g17", n)

    def tell(label: str, key: str, if_found: str | None, if_none: str | None) -> Tell:
        found = key in first
        return Tell(label, found, if_found if found else if_none, first.get(key, 0))

    tells = (
        tell("T0101-style calls", "t4", "lathe", None),
        tell("G96+G50", "css", "lathe", None),
        tell("G95/G99 feed per rev", "fpr", "lathe", None),
        tell("U/W words", "uw", "lathe", None),
        tell("G70-G76/G92 cycles", "cycle", "lathe", None),
        tell("Y moves", "y", "mill", "lathe"),
        tell("M6/G43", "m6", "mill", "lathe"),
        tell("G17", "g17", "mill", None),
    )
    lathe = sum(1 for t in tells if t.points == "lathe")
    mill = sum(1 for t in tells if t.points == "mill")
    return Detection("lathe" if lathe >= mill else "mill", tells, lathe, mill)
