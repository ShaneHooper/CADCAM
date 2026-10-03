"""Stock and origin, guessed from the program for the Setup screen.

Pure stdlib. Everything here is a starting value the user can overwrite; each one comes
with the sentence that says where it came from, so nothing is guessed silently.
Inches; X is a diameter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

from .parser import Program

STEP = 0.250                    # stock sizes come in these increments
SNAP = 0.020                    # an X this far BELOW a step counts as that step (X1.99 is a 2.000 bar)
ADD_LENGTH = 1.0                # the bar runs this far past the deepest cut: a first guess, the user types the real one
_CANNED = ("G70", "G71", "G72", "G73", "G74", "G75", "G76")
Z0_CHOICES = ("finished", "stock", "back")
Z0_LABELS = {"finished": "FINISHED FRONT FACE", "stock": "STOCK FACE", "back": "BACK FACE"}
_FLAT = 0.002                   # a facing pass holds Z within this
_SWEEP = 0.050                  # ... while X (diameter) moves at least this


@dataclass
class StockGuess:
    od: float = 1.0
    length: float = 1.0
    front: float = 0.0          # stock in front of Z0
    z0: str = "finished"
    max_cut_dia: float = 0.0
    z_min: float = 0.0          # extent of the cutting moves
    z_max: float = 0.0
    reasons: dict[str, str] = field(default_factory=dict)   # "od" | "length" | "front" | "z0" -> why


def round_up(value: float, step: float = STEP) -> float:
    """Up to the next multiple of step; a value already on one stays there."""
    return round(math.ceil(value / step - 1e-6) * step, 6)


def round_down(value: float, step: float = STEP, snap: float = SNAP) -> float:
    """Down to the nearest multiple of step, unless the value is within `snap` below the next one."""
    k = math.floor(value / step + 1e-6)
    if (k + 1) * step - value <= snap:
        k += 1
    return round(k * step, 6)


def cutting(program: Program):
    return [m for m in program.moves if m.kind != "rapid"]


def work_diameters(program: Program) -> list[float]:
    """The size of every X the program works at: the points of every cutting move, plus the rapid that
    positions a cut (a facing pass or a G71 / G72 cycle starts from the clearance diameter just outside the
    bar). A tool-change retract (G28, or any rapid that does not lead into a cut) says nothing about the stock.

    Size, not sign: some machines (Mori Seiki) program the OD as X-3.5, so only |X| says how big it is."""
    out: list[float] = []
    mv = program.moves
    for i, m in enumerate(mv):
        if m.kind != "rapid":
            out += [abs(p[1]) for p in m.points]
        elif m.code != "G28" and i + 1 < len(mv):
            nxt = mv[i + 1]
            leads_in = nxt.kind != "rapid" or nxt.code[:3] in _CANNED
            if leads_in and abs(nxt.z0 - m.z1) + abs(nxt.x0 - m.x1) <= 1e-6:
                out.append(abs(m.x1))
    return out


def facing_passes(program: Program):
    """Cuts that sweep X at a near-constant Z."""
    return [m for m in cutting(program)
            if m.kind == "feed" and abs(m.z1 - m.z0) <= _FLAT and abs(m.x1 - m.x0) >= _SWEEP]


def first_facing_pass(program: Program):
    faces = facing_passes(program)
    return faces[0] if faces else None


def guess_stock(program: Program) -> StockGuess:
    g = StockGuess()
    cuts = cutting(program)
    if not cuts:
        for k in ("od", "length", "front", "z0"):
            g.reasons[k] = "no cutting moves were read - placeholder value"
        return g
    zs = [p[0] for m in cuts for p in m.points]
    g.z_min, g.z_max = min(zs), max(zs)
    g.max_cut_dia = max(work_diameters(program))
    g.od = max(STEP, round_down(g.max_cut_dia))
    g.reasons["od"] = (f"largest diameter the program works at, X{g.max_cut_dia:.4f} (a cut, or the approach to one), "
                       f"rounded down to the nearest {STEP:.3f} - the first pass starts outside the bar")

    face = first_facing_pass(program)
    if g.z_min >= -1e-6 and g.z_max > _FLAT:
        g.z0 = "back"
        g.reasons["z0"] = "every cut is at Z0 or above, so Z0 is the back of the part"
    elif face is None:
        g.z0 = "finished"
        g.reasons["z0"] = "no facing pass found - assumed the finished front face"
    elif abs(face.z1) <= _FLAT:
        g.z0 = "finished"
        g.reasons["z0"] = f"the first facing pass (line {face.line}) ends at Z0"
    elif face.z1 < 0:
        g.z0 = "stock"
        g.reasons["z0"] = f"the first facing pass (line {face.line}) cuts at Z{face.z1:.4f}, below Z0"
    else:
        g.z0 = "finished"
        g.reasons["z0"] = (f"the first facing pass (line {face.line}) is at Z{face.z1:.4f}, above Z0 - "
                           "assumed a roughing face before the finished one")

    # A feed move usually STARTS in the air in front of the bar, so the highest cutting Z is
    # an approach point, not the stock face. A facing pass is the cut that touches that face.
    face_top = max((m.z1 for m in facing_passes(program)), default=None)
    if g.z0 == "finished":
        g.front = max(0.0, face_top) if face_top is not None else 0.0
        g.reasons["front"] = (f"the highest facing pass is at Z{face_top:.4f}" if g.front > 0
                              else "no facing pass above Z0 - the program does not say how much was faced off")
    else:
        g.front = 0.0
        g.reasons["front"] = "Z0 is on the stock itself"

    if program.flip is not None and g.z0 != "back":
        # a flip program (the MODEL: OP2 mirrored into OP1's frame): the bar runs from OP1's stock face to OP2's,
        # so the overall length and the stock left on both ends are already in the span. No extra inch.
        g.length = max(STEP, round_up(g.front - g.z_min))
        g.reasons["length"] = (f"flip program: OP1's stock face (Z{g.front:.4f}) to OP2's (Z{g.z_min:.4f} in OP1's "
                               f"frame), rounded up to the next {STEP:.3f}")
        return g
    if g.z0 == "back":
        span = face_top if face_top is not None else g.z_max
        g.reasons["length"] = (f"Z0 to the highest {'facing pass' if face_top is not None else 'cut'} "
                               f"(Z{span:.4f}) plus {ADD_LENGTH:.3f} more, rounded up to the next {STEP:.3f}")
    else:
        span = g.front - g.z_min
        g.reasons["length"] = (f"stock face to the lowest cut (Z{g.z_min:.4f}; the cutoff's far side, if "
                               f"there is one) plus {ADD_LENGTH:.3f} more, rounded up to the next {STEP:.3f}")
    g.length = max(STEP, round_up(span + ADD_LENGTH))
    return g


def stock_z_range(z0: str, length: float, front: float) -> tuple[float, float]:
    """(back Z, front Z) of the bar for a Z0 choice."""
    if z0 == "back":
        return 0.0, length
    if z0 == "stock":
        return -length, 0.0
    return front - length, front
