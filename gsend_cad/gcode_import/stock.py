"""Stock and origin, guessed from the program for the Setup screen.

Pure stdlib. Everything here is a starting value the user can overwrite; each one comes
with the sentence that says where it came from, so nothing is guessed silently.
Inches; X is a diameter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

from .parser import Program

STEP = 0.250                    # stock OD and length round up to this
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


def cutting(program: Program):
    return [m for m in program.moves if m.kind != "rapid"]


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
    xs = [p[1] for m in cuts for p in m.points]
    g.z_min, g.z_max, g.max_cut_dia = min(zs), max(zs), max(xs)
    g.od = max(STEP, round_up(g.max_cut_dia))
    g.reasons["od"] = f"largest cut diameter {g.max_cut_dia:.4f}, rounded up to the next {STEP:.3f}"

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

    if g.z0 == "back":
        span = face_top if face_top is not None else g.z_max
        g.reasons["length"] = (f"Z0 to the highest {'facing pass' if face_top is not None else 'cut'} "
                               f"(Z{span:.4f}), rounded up to the next {STEP:.3f}")
    else:
        span = g.front - g.z_min
        g.reasons["length"] = (f"stock face to the lowest cut (Z{g.z_min:.4f}; the cutoff's far side, if "
                               f"there is one), rounded up to the next {STEP:.3f}")
    g.length = max(STEP, round_up(span))
    return g


def stock_z_range(z0: str, length: float, front: float) -> tuple[float, float]:
    """(back Z, front Z) of the bar for a Z0 choice."""
    if z0 == "back":
        return 0.0, length
    if z0 == "stock":
        return -length, 0.0
    return front - length, front
