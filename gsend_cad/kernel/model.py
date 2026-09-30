from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np
from build123d import (Circle, Cylinder, Face, GeomType, Part, Plane, Pos, Rectangle, RectangleRounded, Vector,
                       Wire, export_step, extrude)

from ..core import DENSITY, resolve
from ..core import plane as pl
from ..core.profiles import Loop, Region

EPS_VOL = 1e-9


def triangles(shape, tolerance=0.001, angular=0.2):
    """(vertices Nx3 float, faces Mx3 int) of any shape or face, for display."""
    verts, tris = shape.tessellate(tolerance, angular)
    return np.array([(v.X, v.Y, v.Z) for v in verts], float).reshape(-1, 3), np.array(tris, int).reshape(-1, 3)


@dataclass
class Body:
    id: str
    name: str
    shape: Part

    @property
    def volume(self) -> float:
        return self.shape.volume

    def bbox(self):
        """((xmin, ymin, zmin), (xmax, ymax, zmax))"""
        b = self.shape.bounding_box()
        return (b.min.X, b.min.Y, b.min.Z), (b.max.X, b.max.Y, b.max.Z)

    def size(self):
        lo, hi = self.bbox()
        return tuple(h - l for l, h in zip(lo, hi))

    def mass(self, material: str) -> float:
        return self.volume * DENSITY[material]

    def triangles(self, tolerance=0.001, angular=0.2):
        return triangles(self.shape, tolerance, angular)

    def edge_polylines(self, segments=48, sharp_only=True, tangent_deg=1.0):
        """B-rep edges as polylines (lines get 2 points, curves get `segments`).

        With sharp_only, seam edges (a cylinder's join line) and edges between tangent faces
        (a flat side running into a corner radius) are left out, like Fusion's default view."""
        faces_of: dict[int, list] = {}
        if sharp_only:
            for f in self.shape.faces():
                for e in f.edges():
                    faces_of.setdefault(hash(e), []).append(f)
        cos_t = math.cos(math.radians(tangent_deg))
        out = []
        for e in self.shape.edges():
            if sharp_only:
                fs = faces_of.get(hash(e), [])
                if len(fs) < 2:
                    continue                      # seam
                mid = e.position_at(0.5)
                try:
                    n0, n1 = fs[0].normal_at(mid), fs[1].normal_at(mid)
                    if n0.dot(n1) > cos_t:
                        continue                  # tangent faces: no visible crease
                except Exception:
                    pass
            n = 1 if e.geom_type.name == "LINE" else segments
            out.append(np.array([tuple(p) for p in e.positions([i / n for i in range(n + 1)])], float))
        return out


@dataclass
class Model:
    """Bodies after the first `upto` features."""
    upto: int
    bodies: list = field(default_factory=list)
    errors: dict = field(default_factory=dict)   # feature id -> message

    def body(self, bid: str) -> Body | None:
        return next((b for b in self.bodies if b.id == bid), None)

    def export_step(self, path):
        if not self.bodies:
            raise ValueError("nothing to export")
        shape = self.bodies[0].shape
        for b in self.bodies[1:]:
            shape = shape + b.shape
        export_step(shape, str(path))


def _loop_face(L: Loop):
    """The loop as a face in sketch coordinates (the XY plane, z = 0)."""
    if L.circle:
        (cx, cy), r = L.circle["c"], L.circle["r"]
        return Pos(cx, cy, 0) * Circle(r)
    if L.rect:
        (x0, y0), (x1, y1) = L.rect["pts"][0], L.rect["pts"][2]
        w, h = abs(x1 - x0), abs(y1 - y0)
        at = Pos((x0 + x1) / 2, (y0 + y1) / 2, 0)
        cr = L.rect.get("corner_r", 0)
        return at * (RectangleRounded(w, h, cr) if cr else Rectangle(w, h))
    return Face(Wire.make_polygon([Vector(x, y, 0) for x, y in L.pts], close=True))


def b123_plane(frame: dict, off: float = 0.0) -> Plane:
    """A core.plane frame as a build123d Plane (optionally lifted `off` along its normal)."""
    fr = pl.offset(frame, off) if off else frame
    return Plane(origin=tuple(fr["origin"]), x_dir=tuple(fr["x"]), z_dir=tuple(fr["n"]))


def region_face(region: Region, plane, off: float = 0.0):
    """The region as a face on `plane` - a core.plane frame, or a float for the XY plane at
    that height (how every caller spoke before planes could be picked). The face's normal is
    the plane's, so extrude() runs along it."""
    frame = pl.xy(plane) if isinstance(plane, (int, float)) else plane
    face = _loop_face(region.outer)
    for h in region.holes:
        face = face - _loop_face(h)
    return b123_plane(frame, off).location * face


def planar_face_at(bodies, point, tol: float = 1e-3):
    """(body, face, frame) for the flat face of a body that a picked world point lies on, or
    None. The frame is the sketch plane for that face (core.plane.from_normal)."""
    p = Vector(*point)
    best = None
    for b in bodies:
        for f in b.shape.faces():
            if f.geom_type != GeomType.PLANE:
                continue
            d = f.distance_to(p)
            if d <= tol and (best is None or d < best[0]):
                best = (d, b, f)
    if best is None:
        return None
    _, b, f = best
    c = f.center()
    n = f.normal_at(c)
    return b, f, pl.from_normal((c.X, c.Y, c.Z), (n.X, n.Y, n.Z))


def face_outline(face, segments=32):
    """The face's edges as world polylines (to highlight the face under the cursor)."""
    out = []
    for e in face.edges():
        n = 1 if e.geom_type == GeomType.LINE else segments
        out.append(np.array([tuple(p) for p in e.positions([i / n for i in range(n + 1)])], float))
    return out


def plane_edges(bodies, frame: dict, tol: float = 1e-6, segments=32) -> list[dict]:
    """Model edges lying on the sketch plane, in sketch coordinates - what the cursor can snap
    to and what the sketch shows of the part: [{"pts": [[u, v], ...], "kind": "LINE" | "CIRCLE"
    | ..., "center": [u, v] | None}]."""
    o, n = Vector(*frame["origin"]), Vector(*frame["n"])
    out = []
    for b in bodies:
        for e in b.shape.edges():
            k = 1 if e.geom_type == GeomType.LINE else segments
            world = e.positions([i / k for i in range(k + 1)])
            if any(abs((p - o).dot(n)) > tol for p in world):
                continue
            item = {"pts": [list(pl.to_local(frame, (p.X, p.Y, p.Z))) for p in world],
                    "kind": e.geom_type.name, "center": None}
            if e.geom_type == GeomType.CIRCLE:
                c = e.arc_center
                item["center"] = list(pl.to_local(frame, (c.X, c.Y, c.Z)))
            out.append(item)
    return out


def extrude_tool(f: dict, feats: list):
    """The solid an extrude feature adds or removes (also used for the live preview)."""
    sketches = {s["id"]: s for s in feats if s["kind"] == "sketch"}
    tool = None
    for ref in f["profiles"]:
        s = sketches.get(ref["sketch"])
        if s is None:
            raise ValueError(f"{f['name']}: sketch {ref['sketch']} is not before it in the timeline")
        face = region_face(resolve(ref, s["ents"]), pl.of_feature(s))
        d = f["distance"]
        solid = extrude(face, abs(d) / 2, both=True) if f["direction"] == "sym" else extrude(face, d)
        tool = solid if tool is None else tool + solid
    return tool


def _hole_tool(f: dict, zmin: float):
    r = f["diameter"] / 2
    top = f["top_z"]
    bottom = zmin - 1.0 if f["depth"] == "through" else top - float(f["depth"])
    tool = None
    for x, y in f["points"]:
        c = Pos(x, y, (top + 1e-3 + bottom) / 2) * Cylinder(r, top + 1e-3 - bottom)
        tool = c if tool is None else tool + c
    return tool


def _nonempty(shape) -> bool:
    return shape is not None and len(shape.solids()) > 0 and shape.volume > EPS_VOL


class Kernel:
    """Evaluates documents with a per-feature cache, so rolling the timeline back and
    forth only rebuilds what changed."""

    def __init__(self):
        self._cache: dict[str, tuple[list, dict, int]] = {}

    def build(self, doc: Document, upto: int | None = None) -> Model:
        n = doc.marker if upto is None else upto
        feats = doc.features[:n]
        state: list = []            # [(id, name, shape)]
        errors: dict = {}
        count = 0
        for i, f in enumerate(feats):
            key = json.dumps(feats[: i + 1], sort_keys=True)
            if key in self._cache:
                state, errors, count = self._cache[key]
                continue
            state, errors = list(state), dict(errors)
            try:
                state, count = self._apply(f, feats[: i + 1], state, count)
            except Exception as exc:  # a broken feature must not take the whole model down
                errors[f["id"]] = str(exc)
            self._cache[key] = (state, errors, count)
        names = doc.body_names        # user renames; they never change geometry, so not cached
        return Model(n, [Body(bid, names.get(bid, name), shape) for bid, name, shape in state], errors)

    def _apply(self, f, feats, state, count):
        k = f["kind"]
        if k == "sketch":
            return state, count
        if k == "extrude":
            tool = extrude_tool(f, feats)
            if f["op"] == "new" or (f["op"] == "join" and not state):
                count += 1
                return state + [(f"body{count}", f"Body{count}", tool)], count
            if f["op"] == "join":
                bid, name, shape = state[0]
                return [(bid, name, shape + tool)] + state[1:], count
            return self._cut(state, tool, f), count
        if k == "remove":
            if not any(bid == f["body"] for bid, _, _ in state):
                raise ValueError(f"{f['name']}: body {f['body']} is not there to remove")
            return [s for s in state if s[0] != f["body"]], count
        if k == "hole":
            if not state:
                raise ValueError(f"{f['name']}: no body to drill")
            zmin = min(s.bounding_box().min.Z for _, _, s in state)
            return self._cut(state, _hole_tool(f, zmin), f), count
        raise ValueError(f"unknown feature kind {k!r}")

    @staticmethod
    def _cut(state, tool, f):
        tb = tool.bounding_box()
        out, hit = [], False
        for bid, name, shape in state:
            sb = shape.bounding_box()
            if (sb.min.X > tb.max.X or sb.max.X < tb.min.X or sb.min.Y > tb.max.Y or sb.max.Y < tb.min.Y
                    or sb.min.Z > tb.max.Z or sb.max.Z < tb.min.Z):
                out.append((bid, name, shape))
                continue
            res = shape - tool
            if abs(res.volume - shape.volume) > EPS_VOL:
                hit = True
            if _nonempty(res):
                out.append((bid, name, res))
        if not hit:
            raise ValueError(f"{f['name']}: cut does not reach any body")
        return out
