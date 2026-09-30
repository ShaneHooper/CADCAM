"""Sketch planes: where a 2D sketch sits in 3D.

A sketch's entities are 2D (u, v) in the plane's own axes. The plane is a *frame*:

    {"origin": [x, y, z], "x": [...], "y": [...], "n": [...]}

`origin` is the world origin projected onto the plane, so "from origin" dimensions read
the same way on every plane; `x` / `y` are the sketch axes and `n` the normal (x × y).
The default is the XY plane at a height, :func:`xy`; a plane picked on a model face comes
from :func:`from_normal` (a point on the face and its normal). `y` is world Z projected
onto the plane - what a person calls "up" when looking at a side of the part - except on a
top or bottom face, where it is world Y; `x` follows so that x × y = n and the sketch reads
left-to-right when the view looks along -n.

Pure Python: the kernel places faces with it and the UI draws with it.
"""
from __future__ import annotations

import math

AXES = ("X", "Y", "Z")


def _norm(v):
    L = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / L for c in v]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _dot(a, b):
    return sum(p * q for p, q in zip(a, b))


def _clean(v):
    return [round(float(c), 10) + 0.0 for c in v]


def xy(z: float = 0.0) -> dict:
    """The XY plane at height z (what every sketch used before planes could be picked)."""
    return {"origin": [0.0, 0.0, float(z)], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "n": [0.0, 0.0, 1.0]}


def from_normal(point, normal) -> dict:
    """The plane through `point` with `normal`, axes chosen as the module docstring says."""
    n = _norm(normal)
    up = [0.0, 0.0, 1.0] if abs(n[2]) < 0.999 else [0.0, 1.0, 0.0]
    k = _dot(up, n)
    y = _norm([u - c * k for u, c in zip(up, n)])
    x = _norm(_cross(y, n))
    d = _dot(point, n)
    return {"origin": _clean([c * d for c in n]), "x": _clean(x), "y": _clean(y), "n": _clean(n)}


def is_xy(fr: dict) -> bool:
    return (abs(fr["n"][2] - 1) < 1e-9 and abs(fr["x"][0] - 1) < 1e-9
            and abs(fr["origin"][0]) < 1e-9 and abs(fr["origin"][1]) < 1e-9)


def height(fr: dict) -> float:
    """How far the plane sits from the world origin along its normal (plane_z for XY)."""
    return _dot(fr["origin"], fr["n"])


def offset(fr: dict, dist: float) -> dict:
    """The same plane moved `dist` along its normal."""
    return {**fr, "origin": _clean([o + c * dist for o, c in zip(fr["origin"], fr["n"])])}


def to_world(fr: dict, uv, off: float = 0.0) -> list:
    """World point of sketch (u, v), optionally lifted `off` along the normal (drawing on top)."""
    u, v = uv[0], uv[1]
    return [o + u * x + v * y + off * n for o, x, y, n in zip(fr["origin"], fr["x"], fr["y"], fr["n"])]


def to_local(fr: dict, p) -> tuple:
    """Sketch (u, v) of a world point (its distance off the plane is dropped)."""
    d = [c - o for c, o in zip(p, fr["origin"])]
    return _dot(d, fr["x"]), _dot(d, fr["y"])


def of_feature(f: dict) -> dict:
    """A sketch feature's plane: its stored frame, or XY at its plane_z (older files)."""
    return f.get("plane") or xy(f.get("plane_z", 0.0))


def label(fr: dict) -> str:
    """'XY plane Z 0.500' or 'face plane · +X 4.000 in' for the timeline and the palette."""
    if is_xy(fr):
        return f"XY plane Z {fr['origin'][2]:.3f}"
    n = fr["n"]
    i = max(range(3), key=lambda k: abs(n[k]))
    axis = ("+" if n[i] >= 0 else "-") + AXES[i]
    tilt = "" if abs(abs(n[i]) - 1) < 1e-6 else " (tilted)"
    return f"face plane · {axis}{tilt} {height(fr):.3f} in"
