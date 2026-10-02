"""Lathe G-code parser for the G-code import module.

PORTED from G-SEND.IO REV 5 (g00c0de/lathe_simulator/engine.py, last changed in f12a9f6) -
a copy, not an import, so this module stands alone. Keep the two in step by hand;
what was changed here, on purpose:
  * REV 5's cycle-time and stock/simulator code is gone (nothing here needs it);
  * a Move now also carries the N number and, for G2/G3, the arc centre and direction;
  * MachineState tracks cutter comp (G40/G41/G42) and the latest comment (cleared at a
    tool call that has none of its own);
  * a one- or two-digit T word (T3, T12) is a tool with no offset, not tool 00;
  * G92 threading has its own branch (in REV 5 it is nested under the G70 test and never
    runs), and a two-line G76 applies its data line's F, so thread moves carry the lead;
  * X is not clamped at the centerline: a facing pass to X-0.0625 keeps its negative X;
  * G81/G82/G83/G84 and G74 (Z peck) are read as one drilling pass instead of being
    drawn with whatever motion was last active;
  * the result is converted to the canonical list at the bottom (parse_program).

Internally the engine works in millimetres with X as a RADIUS. parse_program() converts
to INCHES with X as a DIAMETER, which is what the rest of this module (and a lathe
programmer) uses. Pure stdlib: no Qt, no third-party imports.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import re

MM_PER_INCH = 25.4
WORD_RE = re.compile(r"([A-Z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))", re.I)
O_NUMBER_RE = re.compile(r"^\s*O(\d+)", re.I)


# Machine home (toolchange position) used for G28 / G53: X20. diameter / Z12. - a typical
# turret-home clearance. Display only; there is no machine coordinate system here.
HOME_X_RADIUS_MM = 10.0 * MM_PER_INCH
HOME_Z_MM = 12.0 * MM_PER_INCH

_DWELL_WORD_RE = re.compile(r"([XUPF])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))", re.I)


def dwell_seconds(code: str) -> float:
    """Seconds commanded by a G4 dwell line (X and U are seconds; an integer P is milliseconds)."""
    seconds = 0.0
    for letter, number in _DWELL_WORD_RE.findall(code):
        letter = letter.upper()
        if letter == "F":
            continue
        value = abs(float(number))
        if letter == "P" and "." not in number:
            value /= 1000.0
        seconds = max(seconds, value)
    return seconds


@dataclass(frozen=True)
class MachineState:
    x: float = 0.0
    z: float = 0.0
    motion: str = "G0"
    units: str = "inch"
    speed_mode: str = "G97"
    feed_mode: str = "G99"          # G99 = feed per revolution, G98 = per minute
    feed: float | None = None
    spindle: float | None = None
    max_rpm: float | None = None    # "G50 S____" clamp for G96
    tool: str = "--"
    offset: str = "--"
    absolute: bool = True
    invert_x: bool = False          # rear-turret lathes command negative X diameters
    comp: str = "G40"               # G40 / G41 / G42
    comment: str = ""               # the most recent (comment) seen


@dataclass(frozen=True)
class Move:
    line_index: int
    line_text: str
    kind: str
    code: str
    points: tuple[tuple[float, float], ...]
    state: MachineState
    dwell_seconds: float = 0.0
    n: int | None = None
    center: tuple[float, float] | None = None       # arcs only: (x radius, z), mm
    clockwise: bool | None = None                    # arcs only: as programmed (G2 = True)

    @property
    def end(self) -> tuple[float, float]:
        return self.points[-1]


@dataclass
class ParsedProgram:
    lines: list[str]
    moves: list[Move]
    warnings: list[str]


# G-codes that are read but not turned into motion. One deduped warning each, so a
# silently-dropped cycle cannot look like a complete program.
UNSUPPORTED_WARNINGS = {
    74: "G74 with an X word (face groove) is not simulated - its cutting is not read.",
    75: "G75 groove cycle is not simulated - its cutting is not read.",
    32: "G32 single-line threading is not simulated - its cutting is not read.",
    50: "G50 coordinate-set (X / Z preset) is not applied - positions after it may be offset from what the machine did.",
    53: "G53 machine-coordinate move is not read - the move is skipped and the tool is treated as parked clear of the work.",
}

# --- M98 / M99 subprogram expansion (P1 #18) -------------------------------
# Fanuc turning centers call subprograms exactly like the mill controls do:
# "M98 P<o> L<count>" runs the O<o> block found elsewhere in the same file and
# returns to the line after the call at M99 (L defaults to 1).
#
# The lathe engine had no M-code handling at all, so an M98 line was silently
# skipped (no axis words) and the trailing "O2000 ... M99" block was then walked
# as if it were ordinary main-line code AFTER M30: the subprogram cut ONCE, in
# the wrong order, starting from whatever position the main body ended at, with
# every L repeat dropped. Both halves are wrong for a backplot - a repeated
# roughing sub cut one pass, and the ordering broke the rapid-crash check.
#
# Expansion is a pre-pass that flattens the program into the order the control
# executes it, so modal state, position, tool and units carry across the call
# boundary for free. Caps mirror the mill parser (see its MAX_SUB_* notes).
MAX_SUB_DEPTH = 8
MAX_SUB_BLOCKS = 100_000
MAX_SUB_MOVES = 50_000


def _subprogram_blocks(lines: list["_ParsedLine"]) -> tuple[int, dict[int, tuple[int, int]]]:
    """Where the main program ends, and the body range of every O block.

    A trailing "O2000 ... M99" block is a call target, not main-line code, so
    the main body ends at the first O line that follows executable code (a
    leading "O0001" is only the program's own name). Bodies exclude their own O
    line and run to the next O line, which makes a subprogram with a missing
    M99 return at the end of its own block rather than bleeding into the next.
    """
    o_positions: list[tuple[int, int]] = []
    first_code: int | None = None
    for index, line in enumerate(lines):
        number = line.o_number
        if number is not None:
            o_positions.append((index, number))
        elif first_code is None and line.words:
            first_code = index
    main_end = len(lines)
    for index, _number in o_positions:
        if first_code is not None and index > first_code:
            main_end = index
            break
    bodies: dict[int, tuple[int, int]] = {}
    for slot, (index, number) in enumerate(o_positions):
        end = o_positions[slot + 1][0] if slot + 1 < len(o_positions) else len(lines)
        bodies.setdefault(number, (index + 1, end))
    return main_end, bodies


def _flatten_subprograms(
    lines: list["_ParsedLine"], warnings: list[str]
) -> tuple[list[int], list[int]]:
    """Line indices in execution order, plus the call depth of each one.

    Returns plain `range(len(lines))` at depth 0 for a program with no O blocks
    and no M98, so nothing changes for the common case.
    """
    main_end, bodies = _subprogram_blocks(lines)
    sequence: list[int] = []
    depths: list[int] = []
    # Frames are [next index, stop index, body start, repeats still to run].
    stack: list[list[int]] = [[0, main_end, 0, 0]]
    warned: set[str] = set()
    expanded = 0
    capped = False

    while stack:
        frame = stack[-1]
        if frame[0] >= frame[1]:
            if len(stack) > 1 and frame[3] > 0:
                frame[3] -= 1
                frame[0] = frame[2]
                continue
            stack.pop()
            continue
        index = frame[0]
        frame[0] += 1
        depth = len(stack) - 1
        sequence.append(index)
        depths.append(depth)
        if depth:
            expanded += 1
            if expanded > MAX_SUB_BLOCKS and not capped:
                capped = True
                warnings.append(
                    f"Line {index + 1}: subprogram expansion exceeded "
                    f"{MAX_SUB_BLOCKS} blocks (runaway M98 repeat or recursion?) "
                    "- the rest of the subprogram calls are not simulated."
                )
                del stack[1:]
                continue

        line = lines[index]
        m_codes = set(line.m_codes)
        # Both codes transfer control AFTER their own block runs, which is why
        # the line is appended above before either is acted on.
        if 99 in m_codes:
            if depth == 0:
                # M99 in the main program restarts it on the control (bar-feed
                # loop). A backplot draws one part, so stop here.
                break
            if frame[3] > 0:
                frame[3] -= 1
                frame[0] = frame[2]
            else:
                stack.pop()
            continue
        if 98 not in m_codes or capped:
            continue

        p_word = line.last("P")
        l_word = line.last("L")
        repeats = max(1, int(round(l_word))) if l_word is not None else 1
        target = int(round(p_word)) if p_word is not None else None
        if target is None:
            key = "m98-no-p"
            message = (
                f"Line {index + 1}: M98 has no P word, so there is no "
                "subprogram to call - nothing was expanded."
            )
        elif target not in bodies:
            key = f"m98-missing-{target}"
            message = (
                f"Line {index + 1}: M98 P{target} calls O{target}, which is not "
                "in this file - that subprogram's cutting is not simulated."
            )
        elif depth >= MAX_SUB_DEPTH:
            key = "m98-depth"
            message = (
                f"Line {index + 1}: subprogram nesting deeper than "
                f"{MAX_SUB_DEPTH} calls (recursive M98?) - expansion stopped "
                "here, so cutting below this call is not simulated."
            )
        else:
            start, stop = bodies[target]
            stack.append([start, stop, start, repeats - 1])
            continue
        if key not in warned:
            warned.add(key)
            warnings.append(message)

    return sequence, depths


def _pairs_with_next(sequence: list[int], position: int, index: int) -> bool:
    """True when the next block executed is the physically next line.

    Two-line cycle formats (G70/G71/G72/G76) read `lines[index + 1]` and then
    skip two blocks. That is only valid while execution is contiguous, which it
    is everywhere except at a subprogram boundary.
    """
    return position + 1 < len(sequence) and sequence[position + 1] == index + 1


def parse_gcode(text: str, display_units: str = "inch", invert_x: bool = False) -> ParsedProgram:
    lines = text.splitlines()
    parsed_lines = [_ParsedLine(index, raw) for index, raw in enumerate(lines)]
    by_number = {line.n: index for index, line in enumerate(parsed_lines) if line.n is not None}
    # Any G71/G72 line that carries P and Q defines the contour range:
    # the second line of the two-line format, or the whole one-line format.
    # P/Q resolve to the nearest matching N block AFTER the cycle line
    # (programs commonly reuse N100/N110 for every cycle).
    for cycle_index, line in enumerate(parsed_lines):
        if not ({70, 71, 72} & set(line.g_codes)):
            continue
        p = line.last("P")
        q = line.last("Q")
        start = _find_block(parsed_lines, cycle_index, int(p)) if p is not None else None
        end = _find_block(parsed_lines, cycle_index, int(q)) if q is not None else None
        if start is not None and end is not None:
            for skip_index in range(min(start, end), max(start, end) + 1):
                parsed_lines[skip_index].skip_profile = True

    state = MachineState(units="inch" if display_units.lower().startswith("in") else "mm", invert_x=invert_x)
    moves: list[Move] = []
    warnings: list[str] = []
    warned_codes: set[int] = set()
    # A dwell before the first motion block has no earlier move to be billed
    # to; it is held here and folded into the first move instead.
    leading_dwell_seconds = 0.0
    g92_z: float | None = None
    # M98 subprograms are expanded into one flat execution stream (P1 #18);
    # `depths` marks which blocks came from inside a subprogram so the move cap
    # can abandon the expansion and still finish the main-line program.
    sequence, depths = _flatten_subprograms(parsed_lines, warnings)
    sub_capped = False
    comment_at = -10        # line index of the comment now in state.comment
    position = 0
    while position < len(sequence):
        index = sequence[position]
        if depths[position]:
            if not sub_capped and len(moves) > MAX_SUB_MOVES:
                sub_capped = True
                warnings.append(
                    f"Line {index + 1}: subprogram expansion passed "
                    f"{MAX_SUB_MOVES} moves - the remaining subprogram calls "
                    "are not simulated."
                )
            if sub_capped:
                position += 1
                continue
        line = parsed_lines[index]
        if line.comment:
            state = replace(state, comment=line.comment)
            comment_at = index
        elif line.last("T") is not None and not 0 < index - comment_at <= 2:
            # a tool call with no comment of its own (or just above it): the last tool's
            # comment does not carry over to this one
            state = replace(state, comment="")
        if not line.words or line.skip_profile:
            position += 1
            continue
        state = _apply_modal(line, state)
        g_codes = line.g_codes
        # Surface codes the sim does not simulate so the picture is not trusted
        # blindly (one warning per distinct code). Previously `warnings` was
        # built but never appended to and these codes were dropped silently.
        for g in g_codes:
            if g in UNSUPPORTED_WARNINGS and g not in warned_codes:
                warnings.append(f"Line {line.index + 1}: {UNSUPPORTED_WARNINGS[g]}")
                warned_codes.add(g)
        m_codes = line.m_codes
        if 98 in m_codes or 99 in m_codes:
            # The call and the return were resolved by the expansion pre-pass.
            # Stop here so their words cannot be read as machining data: M98's P
            # is the target O number, not a G70/G71 contour block range. Axis
            # words on a call or return block are not drawn (both codes get
            # their own block in real programs).
            position += 1
            continue
        if 4 in g_codes:
            # G4 dwell: X / U / P are a TIME, not a diameter. Parsed as an axis
            # word, "G4 X1.5" became a FEED to radius 0.75 - the sim carved the
            # bar down to a 1.5 diameter the machine never cut, and left the tool
            # at that radius for whatever followed (P1 #17). A dwell is not
            # motion, so emit nothing and leave the position alone.
            #
            # It is real TIME though (item 22): counted as zero, ten 2-second
            # dwells vanished from the cycle estimate. Bill it to the block that
            # just finished, so nothing is drawn and no phantom step appears.
            seconds = dwell_seconds(line.code)
            if seconds > 0.0:
                if moves:
                    moves[-1] = replace(moves[-1], dwell_seconds=moves[-1].dwell_seconds + seconds)
                else:
                    leading_dwell_seconds += seconds
            # `position`, not `index`: the M98/M99 expansion pre-pass (P1 #18)
            # renamed this cursor when it started walking a flattened execution
            # order rather than raw source lines.
            position += 1
            continue
        if 53 in g_codes:
            # G53 moves in MACHINE coordinates. The sim has no machine coordinate
            # system, so drawing the programmed numbers as work coordinates
            # invented a move (P1 #17): "G53 X0" drew a rapid onto the spindle
            # centerline, and the next retract then swept out through the part
            # and registered as a FALSE crash from the P0 #11 check.
            #
            # Draw nothing, and park the commanded axes at the same machine-home
            # clearance G28 uses below - after a machine-coordinate move the tool
            # is clear of the work, NOT at program zero. Axes this line does not
            # command keep their work position, so a single-axis G53 does not
            # move the other one. Motion mode is left as programmed.
            state = replace(
                state,
                x=HOME_X_RADIUS_MM if (line.last("X") is not None or line.last("U") is not None) else state.x,
                z=HOME_Z_MM if (line.last("Z") is not None or line.last("W") is not None) else state.z,
            )
            position += 1
            continue
        if 28 in g_codes:
            # Reference return: rapid through the intermediate point (axis
            # words on the G28 line; U/W incremental, X/Z absolute) to
            # machine home - the toolchange position, NOT program X0 Z0.
            mid_x, mid_z = _target(line, state)
            if abs(mid_x - state.x) > 1e-9 or abs(mid_z - state.z) > 1e-9:
                moves.append(_line_move(line, state, mid_x, mid_z, "rapid", "G28"))
            moves.append(_raw_move(line, mid_x, mid_z, HOME_X_RADIUS_MM, HOME_Z_MM, "rapid", "G28", state))
            state = replace(state, x=HOME_X_RADIUS_MM, z=HOME_Z_MM, motion="G0")
            position += 1
            continue
        pairs_ahead = _pairs_with_next(sequence, position, index)
        if 71 in g_codes and pairs_ahead and 71 in parsed_lines[index + 1].g_codes:
            cycle_moves = _expand_roughing(parsed_lines, index, state, "G71")
            moves.extend(cycle_moves)
            position += 2
            continue
        if 72 in g_codes and pairs_ahead and 72 in parsed_lines[index + 1].g_codes:
            cycle_moves = _expand_roughing(parsed_lines, index, state, "G72")
            moves.extend(cycle_moves)
            position += 2
            continue
        if ({71, 72} & set(g_codes)) and line.last("P") is not None and line.last("Q") is not None:
            # One-line format: G71/G72 P_ Q_ U(finish) W(finish) D(depth) F_
            cycle = "G71" if 71 in g_codes else "G72"
            moves.extend(_expand_roughing(parsed_lines, index, state, cycle, single_line=True))
            position += 1
            continue
        if 70 in g_codes:
            # G70 finish pass: cut the P/Q contour once at final size. The old
            # code dropped G70 entirely, so the finish pass never cut.
            two_line = pairs_ahead and 70 in parsed_lines[index + 1].g_codes
            has_pq = line.last("P") is not None and line.last("Q") is not None
            if two_line or has_pq:
                finish_moves = _expand_finish(parsed_lines, index, state, single_line=has_pq)
                if finish_moves:
                    moves.extend(finish_moves)
                elif 70 not in warned_codes:
                    warnings.append(
                        f"Line {line.index + 1}: G70 finish pass P/Q contour not "
                        "found - finish pass not simulated."
                    )
                    warned_codes.add(70)
                position += 2 if (two_line and not has_pq) else 1
                continue
        if 92 in g_codes and line.has_axis:
            # G92 box threading cycle: one pass per line, tool returns to
            # the cycle start point. Modal: following bare X (or X/Z)
            # lines repeat the cycle until an explicit motion G code.
            target_x, target_z = _target(line, state)
            g92_z = target_z
            moves.extend(_thread_pass(line, state, target_x, target_z))
            state = replace(state, motion="G92")
            position += 1
            continue
        if 76 in g_codes:
            # Fanuc G76: params on the first line, X/Z/P/Q/F on the second.
            two_line = pairs_ahead and 76 in parsed_lines[index + 1].g_codes
            data_line = parsed_lines[index + 1] if two_line else line
            if two_line:
                state = _apply_modal(data_line, state)
            g76_moves, g76_warn = _expand_g76(line, data_line, state)
            moves.extend(g76_moves)
            if g76_warn and 76 not in warned_codes:
                warnings.append(f"Line {line.index + 1}: {g76_warn}")
                warned_codes.add(76)
            position += 2 if two_line else 1
            continue

        drill = {81, 82, 83, 84} & set(g_codes)
        if not drill and 74 in g_codes and line.last("X") is None and line.last("U") is None and line.last("Z") is not None:
            drill = {74}
        if drill:
            # Lathe drilling / tapping cycle: one feed in Z at the current diameter (or the X
            # word), then back out. Depth is the Z word; the pecks inside it are not drawn.
            code = f"G{sorted(drill)[0]}"
            target_x, target_z = _target(line, state)
            start_z = state.z
            moves.append(_raw_move(line, state.x, state.z, target_x, state.z, "rapid", code, state))
            moves.append(_raw_move(line, target_x, state.z, target_x, target_z, "feed", code, state))
            moves.append(_raw_move(line, target_x, target_z, target_x, start_z, "rapid", code, state))
            state = replace(state, x=target_x, z=start_z)
            position += 1
            continue
        explicit_motion = _explicit_motion(g_codes)
        if explicit_motion:
            state = replace(state, motion=explicit_motion)
        if state.motion == "G92" and line.has_axis and 4 not in g_codes:
            target_x, target_z = _target(line, state)
            if line.last("Z") is None and line.last("W") is None and g92_z is not None:
                target_z = g92_z
            else:
                g92_z = target_z
            moves.extend(_thread_pass(line, state, target_x, target_z))
            position += 1
            continue
        if not line.has_axis or state.motion not in {"G0", "G1", "G2", "G3"}:
            position += 1
            continue
        target_x, target_z = _target(line, state)
        if state.motion in {"G2", "G3"}:
            # Item 67: an arc a control would alarm on is still drawn, but it
            # must not vanish in silence. One warning per source line.
            arc_problem = _arc_problem(line, state, target_x, target_z)
            if arc_problem is not None:
                message = f"Line {line.index + 1}: {arc_problem}"
                if message not in warnings:
                    warnings.append(message)
            moves.append(_arc_move(line, state, target_x, target_z, state.motion == "G2"))
        else:
            moves.append(_line_move(line, state, target_x, target_z, "rapid" if state.motion == "G0" else "feed", state.motion))
        state = replace(state, x=target_x, z=target_z)
        position += 1

    if leading_dwell_seconds and moves:
        moves[0] = replace(moves[0], dwell_seconds=moves[0].dwell_seconds + leading_dwell_seconds)

    return ParsedProgram(lines, moves, warnings)


class _ParsedLine:
    def __init__(self, index: int, raw: str) -> None:
        self.index = index
        self.raw = raw
        self.skip_profile = False
        self.code = _strip_comments(raw)
        self.comment = _comment_text(raw)
        self.words = [(letter.upper(), float(value)) for letter, value in WORD_RE.findall(self.code)]
        n_word = self.last("N")
        self.n = int(n_word) if n_word is not None else None

    @property
    def g_codes(self) -> list[int]:
        return [int(round(value)) for letter, value in self.words if letter == "G"]

    @property
    def m_codes(self) -> list[int]:
        return [int(round(value)) for letter, value in self.words if letter == "M"]

    @property
    def o_number(self) -> int | None:
        """The O number this line declares (a block header), if any."""
        match = O_NUMBER_RE.match(self.code)
        return int(match.group(1)) if match else None

    @property
    def has_axis(self) -> bool:
        return any(letter in {"X", "Z", "U", "W"} for letter, _value in self.words)

    def last(self, letter: str) -> float | None:
        matches = [value for word_letter, value in self.words if word_letter == letter]
        return matches[-1] if matches else None


def _comment_text(line: str) -> str:
    """Text of the (parenthesised) comment(s) on a line, or of a trailing ; comment."""
    parts = re.findall(r"\(([^)]*)\)", line)
    if not parts and ";" in line:
        parts = [line.split(";", 1)[1]]
    return " ".join(p.strip() for p in parts if p.strip())


def _strip_comments(line: str) -> str:
    line = re.sub(r"\([^)]*\)", " ", line)
    return line.split(";", 1)[0]


def _apply_modal(line: _ParsedLine, state: MachineState) -> MachineState:
    for g in line.g_codes:
        if g == 20:
            state = replace(state, units="inch")
        elif g == 21:
            state = replace(state, units="mm")
        elif g == 90:
            state = replace(state, absolute=True)
        elif g == 91:
            state = replace(state, absolute=False)
        elif g in (40, 41, 42):
            state = replace(state, comp=f"G{g}")
        elif g == 96:
            state = replace(state, speed_mode="G96")
        elif g == 97:
            state = replace(state, speed_mode="G97")
        elif g in (98, 94):
            # Feed per MINUTE: G98 on A-type controls, G94 on B/C-type.
            state = replace(state, feed_mode="G98")
        elif g in (99, 95):
            # Feed per REVOLUTION: G99 on A-type controls, G95 on B/C-type.
            state = replace(state, feed_mode="G99")
    feed = line.last("F")
    spindle = line.last("S")
    tool = line.last("T")
    if feed is not None:
        state = replace(state, feed=feed)
    if spindle is not None:
        # "G50 S3000" is the maximum-RPM CLAMP, not a commanded speed. Feeding
        # it into `spindle` made the estimate run the job at the clamp value
        # (item 22); the clamp only caps what G96 asks for.
        if 50 in line.g_codes:
            state = replace(state, max_rpm=max(1.0, abs(spindle)))
        else:
            state = replace(state, spindle=spindle)
    if tool is not None:
        number = int(round(tool))
        if number < 100:
            # T3 / T12: a tool with no offset word (a 4-digit T0303 is tool 03 offset 03)
            state = replace(state, tool=str(number).zfill(2), offset="00")
        else:
            tool_text = str(number).zfill(4)
            state = replace(state, tool=tool_text[:2], offset=tool_text[2:])
    return state


def _explicit_motion(g_codes: list[int]) -> str | None:
    for code in reversed(g_codes):
        if code in {0, 1, 2, 3}:
            return f"G{code}"
    return None


def _scale(units: str) -> float:
    return MM_PER_INCH if units == "inch" else 1.0


def _dim(value: float, units: str) -> float:
    return value * _scale(units)


def _x_dia_to_radius(value: float, units: str) -> float:
    return _dim(value, units) / 2.0


def _target(line: _ParsedLine, state: MachineState) -> tuple[float, float]:
    x = state.x
    z = state.z
    sign = -1.0 if state.invert_x else 1.0
    x_word = line.last("X")
    z_word = line.last("Z")
    u_word = line.last("U")
    w_word = line.last("W")
    if x_word is not None:
        x = _x_dia_to_radius(sign * x_word, state.units) if state.absolute else x + _x_dia_to_radius(sign * x_word, state.units)
    if z_word is not None:
        z = _dim(z_word, state.units) if state.absolute else z + _dim(z_word, state.units)
    if u_word is not None:
        x += _x_dia_to_radius(sign * u_word, state.units)
    if w_word is not None:
        z += _dim(w_word, state.units)
    return x, z


def _line_move(line: _ParsedLine, state: MachineState, x1: float, z1: float, kind: str, code: str) -> Move:
    return _raw_move(line, state.x, state.z, x1, z1, kind, code, state)


def _thread_pass(line: _ParsedLine, state: MachineState, target_x: float, target_z: float) -> list[Move]:
    """One G92 box cycle pass; the tool ends back at the cycle start point."""
    start_x = state.x
    start_z = state.z
    return [
        _raw_move(line, start_x, start_z, target_x, start_z, "rapid", "G92", state),
        _raw_move(line, target_x, start_z, target_x, target_z, "thread", "G92", state),
        _raw_move(line, target_x, target_z, start_x, target_z, "rapid", "G92", state),
        _raw_move(line, start_x, target_z, start_x, start_z, "rapid", "G92", state),
    ]


def _expand_g76(param_line: _ParsedLine, data_line: _ParsedLine, state: MachineState) -> tuple[list[Move], str | None]:
    """Fanuc G76 threading as REAL infeed passes, replacing the old decorative
    6-equal-diagonal-passes fake.

    Passes follow the constant cross-section rule (cumulative depth grows with
    sqrt(pass number)), reaching the true root diameter (X on the data line)
    over the true thread length (Z), followed by the finish/spring passes given
    by the repeat count in the param line's P word. The first-pass depth comes
    from the data line's Q (least-increment convention) but is clamped so the
    pass count stays sane for a backplot across control dialects. Returns
    (moves, warning); warning is set when the block can't be parsed.
    """
    if data_line.last("X") is None:
        return [], "G76 has no root X word - thread not simulated."
    root_x, target_z = _target(data_line, state)
    start_x, start_z = state.x, state.z
    divisor = 10000.0 if state.units == "inch" else 1000.0  # least input increment
    # Thread height (total depth, radius) from the data-line P word - NOT the
    # start-to-root distance, which includes the approach clearance. Values are
    # converted from program units to the sim's internal mm. Falls back to the
    # geometric distance only when P is absent.
    p_height = data_line.last("P")
    if p_height is not None and p_height > 0:
        total = _dim(abs(p_height) / divisor, state.units)
    else:
        total = abs(start_x - root_x)
    if total < 1e-9:
        return [], "G76 thread height is zero - thread not simulated."
    # OD thread: the root sits below the start clearance, so the crest (where
    # cutting begins) is ABOVE the root by the thread height; ID is mirrored.
    outward = 1.0 if root_x <= start_x else -1.0
    crest_x = root_x + outward * total
    # First-pass depth from Q (constant cross-section infeed: cumulative depth
    # grows with sqrt(pass)); clamp so the pass count stays sane for a backplot.
    q = data_line.last("Q")
    first_depth = _dim(abs(q) / divisor, state.units) if q else 0.0
    if not (0.0 < first_depth < total):
        first_depth = total / math.sqrt(6.0)           # ~6 passes when Q is unusable
    first_depth = min(max(first_depth, total / 50.0), total)  # cap 1..~50 passes
    finish = 0
    p_param = param_line.last("P")
    if p_param is not None and p_param >= 10000:         # 6-digit param P = (m)(chamfer)(angle)
        finish = max(0, min(int(p_param // 10000), 9))
    depths: list[float] = []
    n = 1
    while True:
        cum = min(first_depth * math.sqrt(n), total)
        depths.append(cum)
        if cum >= total - 1e-9 or n > 60:
            break
        n += 1
    depths.extend([total] * finish)                      # spring / finish passes at full depth
    moves: list[Move] = []
    for cum in depths:
        pass_x = crest_x - outward * cum
        moves.append(_raw_move(data_line, start_x, start_z, pass_x, start_z, "rapid", "G76", state))
        moves.append(_raw_move(data_line, pass_x, start_z, pass_x, target_z, "thread", "G76", state))
        moves.append(_raw_move(data_line, pass_x, target_z, start_x, target_z, "rapid", "G76", state))
        moves.append(_raw_move(data_line, start_x, target_z, start_x, start_z, "rapid", "G76", state))
    return moves, None


def _raw_move(line: _ParsedLine, x0: float, z0: float, x1: float, z1: float, kind: str, code: str, state: MachineState) -> Move:
    return Move(line.index, line.raw, kind, code, ((x0, z0), (x1, z1)), state, n=line.n)


def _arc_move(line: _ParsedLine, state: MachineState, x1: float, z1: float, clockwise: bool) -> Move:
    radius = line.last("R")
    i_word = line.last("I")
    k_word = line.last("K")
    sign = -1.0 if state.invert_x else 1.0
    # An inverted-X (rear turret) machine is simulated by negating every X / U
    # / I word, i.e. by REFLECTING the programmed geometry about the spindle
    # axis. A reflection reverses orientation, so a G2 in the machine's own
    # frame traces a counter-clockwise arc in the mirrored space the sim draws
    # in. XOR the direction flag back so the mirrored arc keeps the physical
    # shape (a round-over stays a round-over). The Move still reports the word
    # the program actually contained.
    sweep_cw = bool(clockwise) != bool(state.invert_x)
    if radius is not None:
        cx, cz, sweep = _solve_r_center(state.x, state.z, x1, z1, _dim(radius, state.units), sweep_cw)
    else:
        # I/K are the incremental start-to-center vector. On Fanuc/Haas lathes I
        # is a RADIUS value even in diameter mode, so it is unit-scaled only -
        # NOT halved like a diameter-programmed X/U word. (state.x is already in
        # radius space.) Halving it put every I/K arc center in the wrong place.
        cx = state.x + _dim(sign * (i_word or 0.0), state.units)
        cz = state.z + _dim(k_word or 0.0, state.units)
        sweep = None
    points = _arc_points(state.x, state.z, x1, z1, cx, cz, sweep_cw, sweep)
    return Move(line.index, line.raw, "feed", "G2" if clockwise else "G3", tuple(points), state,
                n=line.n, center=(cx, cz), clockwise=bool(clockwise))


# Item 67: the tolerances an arc block has to hold to before the sim calls it
# impossible. Same reasoning as the mill's g00c0de/simulator/arcs.py.
ARC_R_TOLERANCE_MM = 0.01
ARC_ENDPOINT_TOLERANCE_MM = 0.01


def arc_geometry_problem(
    x0: float, z0: float, x1: float, z1: float, radius_mm: float | None,
    i_mm: float | None, k_mm: float | None,
) -> str | None:
    """Describe why this arc block cannot be cut as written, or None.

    Item 67: an R shorter than half the chord, or an I/K center the endpoint
    does not sit on, used to draw as a silent straight line (`_solve_r_center`
    returns a zero sweep) or as a silently snapped arc (`_arc_points` forces
    its last point onto the programmed endpoint). A control alarms on both.
    All distances are millimeters, X in radius.
    """
    chord = math.hypot(x1 - x0, z1 - z0)
    if radius_mm is not None:
        r_abs = abs(radius_mm)
        if r_abs < 1e-9:
            return "arc has R0 - a zero-radius arc has no geometry; it is drawn as a straight line."
        if chord > 2.0 * r_abs + ARC_R_TOLERANCE_MM:
            return (
                f"arc is impossible: the endpoint is {chord:.4f} mm away but R{r_abs:.4f} "
                f"can only span {2.0 * r_abs:.4f} mm. A control alarms here; the sim draws "
                "a straight line instead of the arc."
            )
        return None
    if i_mm is None and k_mm is None:
        return "arc has no R and no I / K offset, so it has no center - it is drawn as a straight line."
    cx = x0 + (i_mm or 0.0)
    cz = z0 + (k_mm or 0.0)
    r_start = math.hypot(x0 - cx, z0 - cz)
    r_end = math.hypot(x1 - cx, z1 - cz)
    if r_start < 1e-9:
        return (
            "arc center is on the start point (I0 K0) - a zero-radius arc has no "
            "geometry; it is drawn as a straight line."
        )
    if abs(r_end - r_start) > ARC_ENDPOINT_TOLERANCE_MM:
        return (
            f"arc endpoint is {abs(r_end - r_start):.4f} mm off the circle its I / K "
            f"offsets describe (start radius {r_start:.4f} mm, end radius {r_end:.4f} mm). "
            "A control alarms here; the sim snaps the endpoint onto the arc, so the drawn "
            "path is not what the machine would cut."
        )
    return None


def _arc_problem(line: "_ParsedLine", state: MachineState, x1: float, z1: float) -> str | None:
    """arc_geometry_problem for one parsed block, in the engine's units."""
    radius = line.last("R")
    i_word = line.last("I")
    k_word = line.last("K")
    sign = -1.0 if state.invert_x else 1.0
    return arc_geometry_problem(
        state.x,
        state.z,
        x1,
        z1,
        None if radius is None else _dim(radius, state.units),
        None if i_word is None else _dim(sign * i_word, state.units),
        None if k_word is None else _dim(k_word, state.units),
    )


def _sweep_for(x0: float, z0: float, x1: float, z1: float, cx: float, cz: float, clockwise: bool) -> float:
    """Signed sweep, in the engine's internal (X abscissa, Z ordinate) angle.

    A lathe arc lives in the ZX plane (G18), where the standard defines the
    hand from the cyclic axis order Z -> X with Y as the plane normal: draw Z
    to the right and X up, look from +Y, and G3 is the counter-clockwise
    direction (G2 clockwise).

    This engine parameterises points as x = cx + cos(a)*r, z = cz + sin(a)*r,
    so its angle is a = atan2(Z-cz, X-cx) -- X is the abscissa, the axes are
    SWAPPED relative to the ZX view. Swapping two axes mirrors the plane, and
    the standard angle t = atan2(X-cx, Z-cz) satisfies t = pi/2 - a, so
    dt = -da: a counter-clockwise (G3) arc in the ZX view is a NEGATIVE sweep
    in this internal angle, and G2 a positive one.

    The code used to force the sign the other way round, which reversed every
    arc on the machine: a convex corner round-over came out as a concave gouge
    into the part. Getting this backwards is invisible on a semicircle and
    obvious on a quarter-circle blend.
    """
    a0 = math.atan2(z0 - cz, x0 - cx)
    a1 = math.atan2(z1 - cz, x1 - cx)
    sweep = a1 - a0
    if clockwise:
        # G2 (CW in the ZX view) = increasing internal angle.
        while sweep <= 0.0:
            sweep += math.tau
    else:
        # G3 (CCW in the ZX view) = decreasing internal angle.
        while sweep >= 0.0:
            sweep -= math.tau
    return sweep


def _solve_r_center(x0: float, z0: float, x1: float, z1: float, radius: float, clockwise: bool) -> tuple[float, float, float]:
    if abs(radius) < 1e-12:
        return (x0 + x1) / 2.0, (z0 + z1) / 2.0, 0.0
    dx = x1 - x0
    dz = z1 - z0
    chord = math.hypot(dx, dz)
    r_abs = abs(radius)
    if chord < 1e-12 or chord > 2.0 * r_abs + 1e-9:
        return (x0 + x1) / 2.0, (z0 + z1) / 2.0, 0.0
    mx = (x0 + x1) / 2.0
    mz = (z0 + z1) / 2.0
    h = math.sqrt(max(r_abs * r_abs - (chord * 0.5) ** 2, 0.0))
    nx = -dz / chord
    nz = dx / chord
    candidates = ((mx + nx * h, mz + nz * h), (mx - nx * h, mz - nz * h))
    solved = [(cx, cz, _sweep_for(x0, z0, x1, z1, cx, cz, clockwise)) for cx, cz in candidates]
    return max(solved, key=lambda item: abs(item[2])) if radius < 0 else min(solved, key=lambda item: abs(item[2]))


def _arc_points(x0: float, z0: float, x1: float, z1: float, cx: float, cz: float, clockwise: bool, sweep: float | None) -> list[tuple[float, float]]:
    radius = math.hypot(x0 - cx, z0 - cz)
    if radius < 1e-12:
        return [(x0, z0), (x1, z1)]
    if sweep is None:
        sweep = _sweep_for(x0, z0, x1, z1, cx, cz, clockwise)
    segments = max(8, int(math.ceil(abs(sweep) * radius / 0.25)))
    a0 = math.atan2(z0 - cz, x0 - cx)
    points = []
    for index in range(segments + 1):
        t = index / segments
        angle = a0 + sweep * t
        points.append((cx + math.cos(angle) * radius, cz + math.sin(angle) * radius))
    points[-1] = (x1, z1)
    return points


def _find_block(lines: list[_ParsedLine], from_index: int, number: int) -> int | None:
    """Index of the nearest N`number` line after `from_index` (Fanuc scans
    forward from the cycle); falls back to anywhere in the program."""
    for pos in range(from_index + 1, len(lines)):
        if lines[pos].n == number:
            return pos
    for pos, line in enumerate(lines):
        if line.n == number:
            return pos
    return None


def _d_word_depth(line: _ParsedLine, units: str) -> float | None:
    """Depth of cut from a one-line cycle's D word.

    Fanuc one-line format: no decimal point means least-input-increment
    units (D0500 = 0.0500 inch on inch controls, D1000 = 1.000 mm on
    metric). A value written with a decimal point is taken as-is.
    Returns millimeters (radius depth for G71, Z depth for G72).
    """
    match = re.search(r"[Dd]\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))", line.code)
    if not match:
        return None
    text = match.group(1)
    value = float(text)
    if "." in text:
        return _dim(value, units)
    return value * (0.0001 * MM_PER_INCH if units == "inch" else 0.001)


def _clip_pass_z(contour: list[tuple[float, float]], pass_x: float, z_min: float, z_max: float, id_cycle: bool) -> float:
    """Z where a constant-X roughing pass must stop (cutting toward -Z).

    Walks the contour segments and finds the frontmost Z at which the
    contour blocks the pass diameter (contour x >= pass_x for OD work,
    <= for ID work). Returns z_min when nothing blocks the pass.
    """
    z_stop = z_min
    for (x0, z0), (x1, z1) in zip(contour, contour[1:]):
        blocked0 = (x0 <= pass_x) if id_cycle else (x0 >= pass_x)
        blocked1 = (x1 <= pass_x) if id_cycle else (x1 >= pass_x)
        if blocked0 and blocked1:
            candidate = max(z0, z1)
        elif blocked0 or blocked1:
            if abs(x1 - x0) < 1e-12:
                candidate = max(z0, z1)
            else:
                t = (pass_x - x0) / (x1 - x0)
                candidate = z0 + (z1 - z0) * t
        else:
            continue
        z_stop = max(z_stop, min(candidate, z_max))
    return z_stop


def _clip_face_x(contour: list[tuple[float, float]], pass_z: float, x_end: float, sweep_negative: bool, cutting_down: bool) -> float:
    """X where a constant-Z facing pass must stop.

    A facing pass sweeps X at a fixed Z; the contour blocks it wherever
    the profile extends past the pass Z (contour z >= pass_z when facing
    toward -Z). Returns x_end when nothing blocks the sweep.
    """
    x_stop = x_end
    for (x0, z0), (x1, z1) in zip(contour, contour[1:]):
        blocked0 = (z0 >= pass_z) if cutting_down else (z0 <= pass_z)
        blocked1 = (z1 >= pass_z) if cutting_down else (z1 <= pass_z)
        if blocked0 and blocked1:
            candidate = max(x0, x1) if sweep_negative else min(x0, x1)
        elif blocked0 or blocked1:
            if abs(z1 - z0) < 1e-12:
                candidate = max(x0, x1) if sweep_negative else min(x0, x1)
            else:
                t = (pass_z - z0) / (z1 - z0)
                candidate = x0 + (x1 - x0) * t
        else:
            continue
        if sweep_negative:
            x_stop = max(x_stop, candidate)
        else:
            x_stop = min(x_stop, candidate)
    return x_stop


def _expand_roughing(lines: list[_ParsedLine], index: int, state: MachineState, cycle: str, single_line: bool = False) -> list[Move]:
    first = lines[index]
    second = first if single_line else lines[index + 1]
    p_word = second.last("P")
    q_word = second.last("Q")
    if p_word is None or q_word is None:
        return []
    start = _find_block(lines, index, int(p_word))
    end = _find_block(lines, index, int(q_word))
    if start is None or end is None:
        return []
    u_sign = -1.0 if state.invert_x else 1.0
    finish_x = _x_dia_to_radius(u_sign * (second.last("U") or 0.0), state.units)
    finish_z = _dim(second.last("W") or 0.0, state.units)
    profile = _profile_points(lines[min(start, end) : max(start, end) + 1], state)
    if len(profile) < 2:
        return []
    contour = profile[1:] or profile
    profile_x = [point[0] + finish_x for point in contour]
    min_x = max(0.0, min(profile_x))
    max_x = max(profile_x)
    z_values = [point[1] + finish_z for point in profile]
    z_min = min(z_values)
    z_max = max(z_values)
    shifted_contour = list(zip(profile_x, [point[1] + finish_z for point in contour]))
    moves: list[Move] = []
    if cycle == "G72":
        # Facing cycle: depth of cut is the D word (one-line format) or the
        # FIRST G72 line's W word (two-line format) - a Z distance. Passes
        # step along Z from the start point toward the contour face; each
        # pass feeds across X to the contour end.
        if single_line:
            depth = _d_word_depth(first, state.units) or _dim(0.05, state.units)
        else:
            depth = abs(_dim(first.last("W") or 0.05, state.units))
        depth = max(depth, 0.05)
        x_end = min_x if state.x >= (min_x + max_x) * 0.5 else max_x
        if state.z >= z_min:
            z_target = z_min
            z_step = -depth
        else:
            z_target = z_max
            z_step = depth
        sweep_negative = x_end < state.x
        pass_z = state.z + z_step
        while (pass_z > z_target + 1e-6) if z_step < 0.0 else (pass_z < z_target - 1e-6):
            x_stop = _clip_face_x(shifted_contour, pass_z, x_end, sweep_negative, z_step < 0.0)
            moves.append(_raw_move(first, state.x, state.z, state.x, pass_z, "rapid", cycle, state))
            moves.append(_raw_move(first, state.x, pass_z, x_stop, pass_z, "feed", cycle, state))
            moves.append(_raw_move(first, x_stop, pass_z, state.x, pass_z, "rapid", cycle, state))
            pass_z += z_step
    else:
        # G71: depth of cut is the D word (one-line, radius value) or the
        # FIRST G71 line's U word (two-line).
        if single_line:
            depth = _d_word_depth(first, state.units) or _x_dia_to_radius(0.05, state.units)
        else:
            depth = abs(_x_dia_to_radius(first.last("U") or 0.05, state.units))
        depth = max(depth, 0.05)
        is_id_cycle = (u_sign * (second.last("U") or 0.0)) < 0.0 or max_x > state.x
        if is_id_cycle:
            pass_x = state.x + depth
            while pass_x < max_x - 1e-6:
                z_stop = _clip_pass_z(shifted_contour, pass_x, z_min, z_max, id_cycle=True)
                moves.append(_raw_move(first, state.x, state.z, pass_x, z_max, "rapid", cycle, state))
                moves.append(_raw_move(first, pass_x, z_max, pass_x, z_stop, "feed", cycle, state))
                moves.append(_raw_move(first, pass_x, z_stop, pass_x, z_max, "rapid", cycle, state))
                pass_x += depth
        else:
            pass_x = state.x - depth
            while pass_x > min_x + 1e-6:
                z_stop = _clip_pass_z(shifted_contour, pass_x, z_min, z_max, id_cycle=False)
                moves.append(_raw_move(first, state.x, state.z, pass_x, z_max, "rapid", cycle, state))
                moves.append(_raw_move(first, pass_x, z_max, pass_x, z_stop, "feed", cycle, state))
                moves.append(_raw_move(first, pass_x, z_stop, pass_x, z_max, "rapid", cycle, state))
                pass_x -= depth
    moves.append(
        _raw_move(
            second,
            profile[0][0],
            profile[0][1],
            profile[1][0] + finish_x,
            profile[1][1] + finish_z,
            "rapid",
            f"{cycle} profile approach",
            state,
        )
    )
    for p0, p1 in zip(profile[1:], profile[2:]):
        kind = "rapid" if p1[2] == "G0" else "feed"
        moves.append(_raw_move(second, p0[0] + finish_x, p0[1] + finish_z, p1[0] + finish_x, p1[1] + finish_z, kind, f"{cycle} profile", state))
    return moves


def _expand_finish(lines: list[_ParsedLine], index: int, state: MachineState, single_line: bool = False) -> list[Move]:
    """G70 finish pass: trace the P/Q contour once at FINAL size (no roughing
    offset), as a feed pass. Returns [] if P/Q cannot be resolved."""
    first = lines[index]
    ref = first if single_line else lines[index + 1]
    p_word = ref.last("P")
    q_word = ref.last("Q")
    if p_word is None or q_word is None:
        return []
    start = _find_block(lines, index, int(p_word))
    end = _find_block(lines, index, int(q_word))
    if start is None or end is None:
        return []
    profile = _profile_points(lines[min(start, end) : max(start, end) + 1], state)
    if len(profile) < 2:
        return []
    moves: list[Move] = []
    moves.append(_raw_move(ref, profile[0][0], profile[0][1], profile[1][0], profile[1][1], "rapid", "G70 approach", state))
    for p0, p1 in zip(profile[1:], profile[2:]):
        kind = "rapid" if p1[2] == "G0" else "feed"
        moves.append(_raw_move(ref, p0[0], p0[1], p1[0], p1[1], kind, "G70 profile", state))
    return moves


def _profile_points(profile_lines: list[_ParsedLine], state: MachineState) -> list[tuple[float, float, str]]:
    """Contour points as (x, z, motion) - motion is how the point is REACHED
    ("G0" segments are rapids: the P-block approach cuts nothing)."""
    points = [(state.x, state.z, "G0")]
    local = state
    for line in profile_lines:
        local = _apply_modal(line, local)
        motion = _explicit_motion(line.g_codes)
        if motion:
            local = replace(local, motion=motion)
        if not line.has_axis:
            continue
        x1, z1 = _target(line, local)
        if local.motion in {"G2", "G3"}:
            arc = _arc_move(line, local, x1, z1, local.motion == "G2")
            points.extend((x, z, local.motion) for x, z in arc.points[1:])
        else:
            points.append((x1, z1, local.motion))
        local = replace(local, x=x1, z=z1)
    return points


# --- the canonical list -----------------------------------------------------------------
# One machine-neutral list of moves, in INCHES with X as a DIAMETER, whatever the program's
# units were. Every later stage (tools, operations, reconstruction) reads only this.

@dataclass(frozen=True)
class Flag:
    """Something the importer did not understand or did not fully do - never silent."""
    line: int           # 1-based source line, 0 when it belongs to the whole program
    level: str          # "unsupported" (not read) | "warn" (read, but doubtful) | "info"
    text: str


@dataclass(frozen=True)
class CMove:
    kind: str                       # "rapid" | "feed" | "arc" | "thread"
    code: str                       # G0 / G1 / G2 / G3 / "G71 profile" / "G76" ...
    z0: float
    x0: float                       # diameter
    z1: float
    x1: float                       # diameter
    center: tuple[float, float] | None   # (z, x diameter) - arcs only
    clockwise: bool | None
    points: tuple[tuple[float, float], ...]   # polyline (z, x diameter) - arcs flattened
    tool: str
    offset: str
    feed: float | None              # program units (see Program.units), mode in feed_mode
    feed_mode: str                  # "G95" per revolution | "G94" per minute
    speed_mode: str                 # "G96" | "G97"
    spindle: float | None
    max_rpm: float | None
    comp: str
    comment: str
    n: int | None
    line: int                       # 1-based


@dataclass
class Program:
    lines: list[str]
    moves: list[CMove]
    flags: list[Flag]
    units: str                      # "inch" or "mm": what the SOURCE was written in
    x_inverted: bool = False        # the source commands negative X diameters; every X here is already mirrored


_KNOWN_G = {0, 1, 2, 3, 4, 17, 18, 19, 20, 21, 28, 32, 40, 41, 42, 50, 53, 54, 55, 56, 57, 58, 59,
            70, 71, 72, 74, 75, 76, 80, 81, 82, 83, 84, 90, 91, 92, 94, 95, 96, 97, 98, 99}
_UNREAD = (
    (re.compile(r"#\s*\d|#\s*\["), "macro variable (#) - the value is not evaluated"),
    (re.compile(r"\b(WHILE|IF|GOTO|THEN|DO\s*\d|END\s*\d)\b", re.I), "macro flow control (WHILE/IF/GOTO) - not followed"),
    (re.compile(r"\bG0*6[567]\b", re.I), "G65/G66/G67 macro call - not followed"),
    (re.compile(r"\bG0*10\b", re.I), "G10 data setting - not applied"),
    (re.compile(r"\bM0*97\b", re.I), "M97 local subprogram call - not followed"),
    (re.compile(r"\bG0*73\b", re.I), "G73 - not read"),
)


def _flags(lines: list[str], warnings: list[str]) -> list[Flag]:
    out: list[Flag] = []
    for w in warnings:
        m = re.match(r"Line (\d+): (.*)", w, re.S)
        out.append(Flag(int(m.group(1)), "warn", m.group(2)) if m else Flag(0, "warn", w))
    for i, raw in enumerate(lines):
        code = _strip_comments(raw)
        hit = False
        for pat, text in _UNREAD:
            if pat.search(code):
                out.append(Flag(i + 1, "unsupported", text))
                hit = True
        for g in sorted({int(round(float(v))) for l, v in WORD_RE.findall(code) if l.upper() == "G"}):
            if g not in _KNOWN_G and not hit:
                out.append(Flag(i + 1, "unsupported", f"G{g} is not recognised - ignored"))
        if re.search(r"\bM0*98\b", code, re.I):
            out.append(Flag(i + 1, "info", "M98 subprogram call - expanded in place"))
    out.sort(key=lambda f: (f.line, f.level))
    return out


def detect_units(lines: list[str]) -> str:
    """The first G20/G21 decides; a program with neither is read as inch."""
    for raw in lines:
        gs = [int(round(float(v))) for l, v in WORD_RE.findall(_strip_comments(raw)) if l.upper() == "G"]
        if 20 in gs:
            return "inch"
        if 21 in gs:
            return "mm"
    return "inch"


def looks_x_negative(program: Program) -> bool:
    """True when the cutting happens at negative X (rear-turret lathes, e.g. Mori Seiki: OD = X-3.5).

    Weighted by size, so the few points where a facing pass crosses the centerline (X+0.0625) do not
    outvote the hundreds at X-3.5. Rapids are left out: a G28 home position says nothing about the part."""
    neg = pos = 0.0
    for m in program.moves:
        if m.kind == "rapid":
            continue
        for _z, x in m.points:
            if x < 0:
                neg -= x
            else:
                pos += x
    return neg > 0.0 and neg >= 0.9 * (neg + pos)


def parse_program(text: str, invert_x: bool | None = None) -> Program:
    """Parse a lathe program into the canonical move list (inches, X diameter).

    invert_x: None (the default) reads the program and mirrors X when it is written with negative
    diameters; True / False force it. Nothing downstream cares about the sign - the part is turned
    about the centerline - so every consumer sees ordinary positive diameters."""
    if invert_x is None:
        first = _parse_program(text, False)
        if not looks_x_negative(first):
            return first
        invert_x = True
    return _parse_program(text, invert_x)


def _parse_program(text: str, invert_x: bool) -> Program:
    raw = parse_gcode(text, "inch", invert_x)
    units = detect_units(raw.lines)
    k = 1.0 / MM_PER_INCH

    def zx(p):
        return (p[1] * k, p[0] * 2.0 * k)

    moves: list[CMove] = []
    for m in raw.moves:
        pts = tuple(zx(p) for p in m.points)
        st = m.state
        moves.append(CMove(
            kind="arc" if m.center is not None else m.kind,
            code=m.code,
            z0=pts[0][0], x0=pts[0][1], z1=pts[-1][0], x1=pts[-1][1],
            center=None if m.center is None else zx(m.center),
            clockwise=m.clockwise,
            points=pts,
            tool=st.tool, offset=st.offset,
            feed=st.feed, feed_mode="G95" if st.feed_mode == "G99" else "G94",
            speed_mode=st.speed_mode, spindle=st.spindle, max_rpm=st.max_rpm,
            comp=st.comp, comment=st.comment, n=m.n, line=m.line_index + 1,
        ))
    flags = _flags(raw.lines, raw.warnings)
    if invert_x:
        flags.insert(0, Flag(0, "info", "X is programmed as negative diameters (a rear-turret lathe): read as "
                                        "positive, since the part is turned about the centerline either way"))
    return Program(raw.lines, moves, flags, units, bool(invert_x))
