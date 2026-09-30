from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np
from build123d import (Axis, Circle, Cylinder, Edge, Face, GeomType, Kind, Part, Plane, Pos, Rectangle,
                       RectangleRounded, Vector, Wire, export_step, extrude, offset, revolve)

from ..core import DENSITY, resolve
from ..core import plane as pl
from ..core.profiles import Loop, Region
from ..core.sketch import arc_mid

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
    if any(e["type"] == "arc" for e in L.segs):         # true arcs (Fillet), not a faceted polygon
        edges = []
        for e in L.segs:
            (x0, y0), (x1, y1) = e["pts"]
            if e["type"] == "arc":
                mx, my = arc_mid(e)
                edges.append(Edge.make_three_point_arc(Vector(x0, y0, 0), Vector(mx, my, 0), Vector(x1, y1, 0)))
            else:
                edges.append(Edge.make_line(Vector(x0, y0, 0), Vector(x1, y1, 0)))
        return Face(Wire(edges))
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


def revolve_axis(f: dict, feats: list) -> Axis:
    """World axis of a revolve: the sketch's own X or Y axis, or one of its lines."""
    s = next((g for g in feats if g["kind"] == "sketch" and g["id"] == f["axis"]["sketch"]), None)
    if s is None:
        raise ValueError(f"{f['name']}: its sketch is gone")
    fr = pl.of_feature(s)
    ax = f["axis"]
    if ax["kind"] == "line":
        ents = s["ents"]
        if not (0 <= ax["ent"] < len(ents)) or ents[ax["ent"]]["type"] != "line":
            raise ValueError(f"{f['name']}: its axis line is gone")
        a, b = ents[ax["ent"]]["pts"]
    else:
        a, b = (0.0, 0.0), ((1.0, 0.0) if ax["kind"] == "x" else (0.0, 1.0))
    wa, wb = pl.to_world(fr, a), pl.to_world(fr, b)
    return Axis(tuple(wa), tuple(q - p for p, q in zip(wa, wb)))


def revolve_tool(f: dict, feats: list):
    """The solid a revolve feature adds or removes (also the live preview)."""
    sketches = {s["id"]: s for s in feats if s["kind"] == "sketch"}
    axis = revolve_axis(f, feats)
    tool = None
    for ref in f["profiles"]:
        s = sketches.get(ref["sketch"])
        if s is None:
            raise ValueError(f"{f['name']}: sketch {ref['sketch']} is not before it in the timeline")
        face = region_face(resolve(ref, s["ents"]), pl.of_feature(s))
        try:
            solid = revolve(face, axis, f["angle"])
        except Exception as exc:
            raise ValueError(f"{f['name']}: can't revolve - the profile must not cross the axis") from exc
        tool = solid if tool is None else tool + solid
    if not _nonempty(tool):
        raise ValueError(f"{f['name']}: the profile must sit on one side of the axis")
    return tool


def edge_list(bodies, segments=24) -> list[dict]:
    """Every real edge of the bodies (no seams), for picking: [{"body", "mid": [x, y, z], "pts"}].
    `mid` (the edge's halfway point) is how a Fillet feature remembers which edges it rounds."""
    out = []
    for b in bodies:
        count: dict[int, int] = {}
        for f in b.shape.faces():
            for e in f.edges():
                count[hash(e)] = count.get(hash(e), 0) + 1
        for e in b.shape.edges():
            if count.get(hash(e), 0) < 2:
                continue
            n = 1 if e.geom_type == GeomType.LINE else segments
            m = e.position_at(0.5)
            out.append({"body": b.id, "mid": [m.X, m.Y, m.Z],
                        "pts": np.array([tuple(p) for p in e.positions([i / n for i in range(n + 1)])], float)})
    return out


def _find_edges(shape, mids, tol=1e-4):
    edges, missing = [], 0
    all_e = shape.edges()
    for m in mids:
        v = Vector(*m)
        best = min(all_e, key=lambda e: (e.position_at(0.5) - v).length, default=None)
        if best is None or (best.position_at(0.5) - v).length > tol:
            missing += 1
        elif best not in edges:
            edges.append(best)
    return edges, missing


def outline_loops(bodies, grow: float, tol: float = 0.0005) -> list[list[tuple]]:
    """The parts' outside outline seen from above (Z), grown by `grow` (tool radius + stock to
    leave), as closed XY point loops - where a 2D Contour tool center runs. The outline is the
    union of sections through every Z slab of the part (between its flat horizontal faces), so a
    boss or flange anywhere up the part counts. Arcs are split to within `tol`."""
    zs = set()
    for b in bodies:
        lo, hi = b.bbox()
        zs |= {lo[2], hi[2]}
        for f in b.shape.faces():
            if f.geom_type == GeomType.PLANE and abs(abs(f.normal_at(f.center()).Z) - 1) < 1e-9:
                zs.add(f.center().Z)
    zs = sorted(zs)
    region = None
    for b in bodies:
        for z0, z1 in zip(zs, zs[1:]):
            if z1 - z0 < 1e-6:
                continue
            z = (z0 + z1) / 2
            for f in b.shape.intersect(Plane.XY.offset(z)).faces():
                f = Pos(0, 0, -z) * f
                region = f if region is None else region + f
    if region is None:
        return []
    loops = []
    for f in region.faces():
        face = f if grow <= 0 else offset(f, grow, kind=Kind.ARC).faces()[0]
        pts = []
        for e in face.outer_wire().order_edges() if hasattr(face.outer_wire(), "order_edges") else face.outer_wire().edges():
            n = 1 if e.geom_type == GeomType.LINE else max(4, int(math.ceil(e.length / max(math.sqrt(8 * tol * e.radius), 1e-3))))
            seg = [(p.X, p.Y) for p in e.positions([i / n for i in range(n + 1)])]
            if pts and math.dist(pts[-1], seg[0]) > math.dist(pts[-1], seg[-1]):
                seg.reverse()
            pts.extend(seg[1:] if pts else seg)
        if len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-6:
            pts.pop()
        loops.append(pts)
    return loops


def bodies_bbox(bodies):
    """((xmin, ymin, zmin), (xmax, ymax, zmax)) around several bodies (a CAM setup's part)."""
    boxes = [b.bbox() for b in bodies]
    return (tuple(min(bx[0][i] for bx in boxes) for i in range(3)),
            tuple(max(bx[1][i] for bx in boxes) for i in range(3)))


def max_radius(bodies, point, direction) -> float:
    """Largest distance of the bodies from an axis line (turning stock size). Measured on the
    shape's vertices plus a light surface mesh; arcs are sampled to within 0.002 in."""
    p, d = np.asarray(point, float), np.asarray(direction, float)
    d = d / np.linalg.norm(d)
    r = 0.0
    for b in bodies:
        v, _ = triangles(b.shape, 0.002, 0.1)
        if len(v):
            w = v - p
            r = max(r, float(np.sqrt(((w - np.outer(w @ d, d)) ** 2).sum(1)).max()))
    return r


def _tangent_chain(shape, edges, tol=1e-6, cos_tol=0.9999):
    """The picked edges plus every edge running on smoothly from them (like Fusion's default
    "tangent chain"): a straight edge that flows into a rounded corner takes the corner too."""
    pool = shape.edges()
    ends = []
    for e in pool:
        ends.append(((e.position_at(0), e.tangent_at(0)), (e.position_at(1), e.tangent_at(1))))
    todo = [i for i, e in enumerate(pool) if any(e.is_same(x) for x in edges)]
    seen = set(todo)
    while todo:
        i = todo.pop()
        for p, t in ends[i]:
            for j, other in enumerate(ends):
                if j in seen:
                    continue
                for q, u in other:
                    if (p - q).length < tol and abs(t.dot(u)) > cos_tol:
                        seen.add(j)
                        todo.append(j)
                        break
    return [pool[i] for i in sorted(seen)]


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
        if k == "revolve":
            tool = revolve_tool(f, feats)
            if f["op"] == "new" or (f["op"] == "join" and not state):
                count += 1
                return state + [(f"body{count}", f"Body{count}", tool)], count
            if f["op"] == "join":
                bid, name, shape = state[0]
                return [(bid, name, shape + tool)] + state[1:], count
            return self._cut(state, tool, f), count
        if k == "fillet":
            return self._fillet(state, f), count
        if k == "hole":
            if not state:
                raise ValueError(f"{f['name']}: no body to drill")
            zmin = min(s.bounding_box().min.Z for _, _, s in state)
            return self._cut(state, _hole_tool(f, zmin), f), count
        raise ValueError(f"unknown feature kind {k!r}")

    @staticmethod
    def _fillet(state, f):
        """Round (fillet) or bevel (chamfer) the picked edges of each body."""
        out, done, lost = [], 0, 0
        size = f["size"]
        for bid, name, shape in state:
            edges, _ = _find_edges(shape, f["edges"])
            n_found = len(edges)
            if edges:
                edges = _tangent_chain(shape, edges)
                try:
                    shape = shape.fillet(size, edges) if f["op"] == "fillet" else shape.chamfer(size, None, edges)
                except Exception as exc:
                    word = "Fillet" if f["op"] == "fillet" else "Chamfer"
                    raise ValueError(f"{f['name']}: {word} {size:.4f} does not fit these edges "
                                     "(too big for a face next to them?)") from exc
                done += n_found
            out.append((bid, name, shape))
        lost = len(f["edges"]) - done
        if done == 0:
            raise ValueError(f"{f['name']}: its edges are gone (an earlier change moved them)")
        if lost > 0:
            raise ValueError(f"{f['name']}: {lost} of its edges are gone (an earlier change moved them)")
        return out

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
