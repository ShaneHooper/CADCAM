"""CAM setups as plain data, plus the stock and WCS math (stdlib only, like the rest of core).

A setup is what Fusion calls a Setup: which kind of machine (milling or turning), which
body, the stock around it and where the work zero (WCS) sits. It lives in
Document.setups (saved in the .gcad file), not in the design timeline.

    {"id": "setup1", "name": "Setup1", "type": "milling", "body": "all" | body id,
     "stock": {"mode": "offset", "side": .1, "top": .05, "bottom": 0,       stock per side
               or "mode": "size", "x": 4.25, "y": 3.25, "z": 1.5, "top": .05},  fixed size, centered
                                                                               in X/Y, `top` above
     "wcs": "top-center" | "top-corner" | "model"}

    {"id": "setup2", "name": "Setup2", "type": "turning", "body": ...,
     "axis": "x" | "y" | "z", "front": "+" | "-",           spindle axis, which end faces the tool
     "stock": {"mode": "offset", "od": .05, "face": .05, "back": .5},   radial, face, chuck side
           or {"mode": "size", "dia": 1.625, "length": 3.5, "face": .05},  bar size, face stock
     "wcs": "stock-face" | "part-face"}                       Z0 on the axis at that face

All values inches. bbox arguments are ((xmin, ymin, zmin), (xmax, ymax, zmax)).
"""
from __future__ import annotations

import copy
import math

MILLING, TURNING = "milling", "turning"
TYPES = {MILLING: "Milling", TURNING: "Turning"}
MILL_WCS = {"top-center": "Stock top, center", "top-corner": "Stock top, front-left corner",
            "model": "Model origin"}
TURN_WCS = {"stock-face": "Stock front face", "part-face": "Part front face"}
AXES = {"x": 0, "y": 1, "z": 2}
STOCK_MODES = {"offset": "Stock per side", "size": "Fixed size"}


def new_setup(kind: str) -> dict:
    """A setup of that type with everyday defaults (no id/name yet; Document.add_setup gives them)."""
    if kind == MILLING:
        return {"type": MILLING, "body": "all", "stock": {"mode": "offset", "side": 0.1, "top": 0.05, "bottom": 0.0},
                "wcs": "top-center"}
    if kind == TURNING:
        return {"type": TURNING, "body": "all", "axis": "z", "front": "+",
                "stock": {"mode": "offset", "od": 0.05, "face": 0.05, "back": 0.5}, "wcs": "stock-face"}
    raise ValueError(f"setup type must be milling or turning, not {kind!r}")


def validate(s: dict) -> dict:
    s = copy.deepcopy(s)
    if s.get("type") not in TYPES:
        raise ValueError("setup type must be milling or turning")
    st = s["stock"]
    st["mode"] = st.get("mode", "offset")
    if st["mode"] not in STOCK_MODES:
        raise ValueError(f"bad stock mode {st['mode']!r}")
    for k, v in st.items():
        if k == "mode":
            continue
        st[k] = float(v)
        if st[k] < 0:
            raise ValueError("stock values can't be negative")
    for k in ("x", "y", "z", "dia", "length"):
        if st["mode"] == "size" and k in st and st[k] <= 0:
            raise ValueError("stock size must be greater than 0")
    if s["type"] == MILLING and s["wcs"] not in MILL_WCS:
        raise ValueError(f"bad milling WCS {s['wcs']!r}")
    if s["type"] == TURNING:
        if s["axis"] not in AXES or s["front"] not in "+-" or s["wcs"] not in TURN_WCS:
            raise ValueError("bad turning axis / front / WCS")
    return s


def guess_axis(bbox) -> str:
    """Spindle axis for a turned part: the axis whose two cross extents match (the part is round
    across it); failing that, the longest side."""
    lo, hi = bbox
    size = [h - l for l, h in zip(lo, hi)]
    best, pick = None, None
    for ax, i in AXES.items():
        a, b = (size[j] for j in range(3) if j != i)
        mismatch = abs(a - b) / max(a, b, 1e-9)
        if mismatch < 0.01 and (best is None or size[i] > best):
            best, pick = size[i], ax
    return pick or "xyz"[max(range(3), key=lambda i: size[i])]


def stock_box(bbox, s):
    """Milling stock: the part's box grown by the offsets. Returns (lo, hi)."""
    (x0, y0, z0), (x1, y1, z1) = bbox
    st = s["stock"]
    if st.get("mode") == "size":                  # centered on the part in X/Y, `top` above it
        cx, cy, top = (x0 + x1) / 2, (y0 + y1) / 2, z1 + st["top"]
        return ((cx - st["x"] / 2, cy - st["y"] / 2, top - st["z"]), (cx + st["x"] / 2, cy + st["y"] / 2, top))
    return ((x0 - st["side"], y0 - st["side"], z0 - st["bottom"]),
            (x1 + st["side"], y1 + st["side"], z1 + st["top"]))


def _unit(i):
    v = [0.0, 0.0, 0.0]
    v[i] = 1.0
    return v


def turning_frame(bbox, s):
    """(i, center, along) for a turning setup: i = axis index, center = the axis line's point in
    the bbox middle, along = (back, front) part ends measured along the axis."""
    i = AXES[s["axis"]]
    lo, hi = bbox
    center = [(l + h) / 2 for l, h in zip(lo, hi)]
    back, front = (lo[i], hi[i]) if s["front"] == "+" else (hi[i], lo[i])
    return i, center, (back, front)


def stock_cylinder(bbox, radius: float, s) -> dict:
    """Turning stock (round bar). radius = the part's largest distance from the axis (the kernel
    measures it). Returns {"axis": [unit], "center": [x, y, z] on the axis at the back end,
    "length", "r", "front": [x, y, z] (center of the front face)}."""
    i, center, (back, front) = turning_frame(bbox, s)
    sign = 1.0 if s["front"] == "+" else -1.0
    st = s["stock"]
    f = front + sign * st["face"]
    if st.get("mode") == "size":                  # a bar of that size, face stock in front
        b = f - sign * st["length"]
        r = st["dia"] / 2
    else:
        b = back - sign * st["back"]
        r = radius + st["od"]
    p_back, p_front = list(center), list(center)
    p_back[i], p_front[i] = b, f
    axis = _unit(i)
    axis[i] = sign
    return {"axis": axis, "center": p_back, "front": p_front, "length": abs(f - b), "r": r}


def round_up(v: float, step: float = 0.125) -> float:
    """Next stock size up (1/8 in steps), for filling in Fixed size."""
    return math.ceil(v / step - 1e-9) * step


def size_from_offsets(bbox, s, radius: float = 0.0) -> dict:
    """Fixed-size stock values matching the setup's per-side stock, rounded up to 1/8 in (what
    switching the Stock mode fills in)."""
    st = s["stock"]
    if s["type"] == MILLING:
        lo, hi = stock_box(bbox, {**s, "stock": {**st, "mode": "offset"}})
        return {"mode": "size", "x": round_up(hi[0] - lo[0]), "y": round_up(hi[1] - lo[1]),
                "z": round_up(hi[2] - lo[2]), "top": st.get("top", 0.05)}
    c = stock_cylinder(bbox, radius, {**s, "stock": {**st, "mode": "offset"}})
    return {"mode": "size", "dia": round_up(c["r"] * 2), "length": round_up(c["length"]), "face": st.get("face", 0.05)}


def fits(bbox, s, radius: float = 0.0) -> str | None:
    """Why fixed-size stock can't hold the part (a message), or None when it fits."""
    st = s["stock"]
    if st.get("mode") != "size":
        return None
    if s["type"] == MILLING:
        lo, hi = stock_box(bbox, s)
        (x0, y0, z0), (x1, y1, z1) = bbox
        for name, need, have in (("X", x1 - x0, hi[0] - lo[0]), ("Y", y1 - y0, hi[1] - lo[1]),
                                 ("Z", z1 - z0 + st["top"], hi[2] - lo[2])):
            if have < need - 1e-9:
                return f"Stock {name} {have:.4f} is smaller than the part needs ({need:.4f})"
        return None
    if st["dia"] / 2 < radius - 1e-9:
        return f"Bar Ø{st['dia']:.4f} is smaller than the part (Ø{radius * 2:.4f})"
    i, _c, (back, front) = turning_frame(bbox, s)
    need = abs(front - back) + st["face"]
    if st["length"] < need - 1e-9:
        return f"Bar length {st['length']:.4f} is shorter than the part + face stock ({need:.4f})"
    return None


def wcs(bbox, s, radius: float = 0.0) -> dict:
    """Work zero: {"origin": [x, y, z], "x": [..], "z": [..]} (unit axes). Milling: Z up. Turning:
    Z along the spindle pointing out of the part at the tool, X radial (like a lathe)."""
    if s["type"] == MILLING:
        lo, hi = stock_box(bbox, s)
        if s["wcs"] == "model":
            o = [0.0, 0.0, 0.0]
        elif s["wcs"] == "top-corner":
            o = [lo[0], lo[1], hi[2]]
        else:
            o = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, hi[2]]
        return {"origin": o, "x": [1.0, 0.0, 0.0], "z": [0.0, 0.0, 1.0]}
    cyl = stock_cylinder(bbox, radius, s)
    i, center, (_back, front) = turning_frame(bbox, s)
    if s["wcs"] == "part-face":
        o = list(center)
        o[i] = front
    else:
        o = cyl["front"]
    x = _unit((i + 1) % 3)            # any radial direction; X of the lathe
    return {"origin": o, "x": x, "z": cyl["axis"]}


def describe(s: dict) -> str:
    st = s["stock"]
    sized = st.get("mode") == "size"
    if s["type"] == MILLING:
        stock = (f"stock {st['x']:.3f} × {st['y']:.3f} × {st['z']:.3f}" if sized
                 else f"stock +{st['side']:.3f} sides, +{st['top']:.3f} top")
        return f"Milling · {stock} · WCS {MILL_WCS[s['wcs']].lower()}"
    stock = (f"bar Ø{st['dia']:.3f} × {st['length']:.3f}" if sized
             else f"OD +{st['od']:.3f}, face +{st['face']:.3f}")
    return f"Turning · {s['axis'].upper()} axis · {stock} · Z0 {TURN_WCS[s['wcs']].lower()}"
