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


def _wire_pts(w, tol: float = 0.0005) -> list[list[float]]:
    """A closed wire as an XY point loop (arcs split to within tol), no repeated end point."""
    pts = []
    edges = w.order_edges() if hasattr(w, "order_edges") else w.edges()
    for e in edges:
        n = 1 if e.geom_type == GeomType.LINE else \
            max(4, int(math.ceil(e.length / max(math.sqrt(8 * tol * max(e.radius, 1e-6)) if e.geom_type == GeomType.CIRCLE
                                                 else 0.02, 1e-3))))
        seg = [[p.X, p.Y] for p in e.positions([i / n for i in range(n + 1)])]
        if pts and math.dist(pts[-1], seg[0]) > math.dist(pts[-1], seg[-1]):
            seg.reverse()
        pts.extend(seg[1:] if pts else seg)
    if len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-6:
        pts.pop()
    return pts


def slice_chains(bodies) -> list[dict]:
    """Every outline of the parts seen from above, level by level: what 2D Contour / mill
    Roughing pick. [{"pts": XY loop, "z0": floor, "z1": top, "hole": inside wall (a pocket /
    bore) or not}] - the hub's round wall, the plate's outside, a pocket's wall... A wall that
    runs through several levels is one chain."""
    out = []
    for b in bodies:
        lo, hi = b.bbox()
        zs = {lo[2], hi[2]}
        for f in b.shape.faces():
            if f.geom_type == GeomType.PLANE and abs(abs(f.normal_at(f.center()).Z) - 1) < 1e-9:
                zs.add(f.center().Z)
        zs = sorted(zs)
        for z0, z1 in zip(zs, zs[1:]):
            if z1 - z0 < 1e-6:
                continue
            for f in b.shape.intersect(Plane.XY.offset((z0 + z1) / 2)).faces():
                for w, hole in [(f.outer_wire(), False)] + [(x, True) for x in f.inner_wires()]:
                    pts = _wire_pts(w)
                    if len(pts) < 3:
                        continue
                    same = next((c for c in out if c["hole"] == hole and abs(c["z1"] - z0) < 1e-6
                                 and len(c["pts"]) == len(pts) and _same_loop(c["pts"], pts)), None)
                    if same:
                        same["z1"] = z1                  # the same wall, one level up
                    else:
                        out.append({"pts": pts, "z0": z0, "z1": z1, "hole": hole})
    return out


def _same_loop(a, b, tol=1e-5):
    k = min(range(len(b)), key=lambda i: math.dist(a[0], b[i]))
    if math.dist(a[0], b[k]) > tol:
        return False
    n = len(a)
    return all(math.dist(a[i], b[(k + i) % n]) < tol for i in range(n)) or \
        all(math.dist(a[i], b[(k - i) % n]) < tol for i in range(n))


def _poly_face(pts):
    return Face(Wire.make_polygon([(x, y, 0) for x, y in pts], close=True))


def _offset_face(face, d: float) -> list:
    """The face's outline offset by d (+ out, - in), as XY loops; [] when nothing is left."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
    from OCP.GeomAbs import GeomAbs_Arc
    from build123d import Compound
    if abs(d) < 1e-12:
        return [_wire_pts(w) for w in [face.outer_wire()] + face.inner_wires()]
    mk = BRepOffsetAPI_MakeOffset(face.wrapped, GeomAbs_Arc)
    try:
        mk.Perform(d)
    except Exception:
        return []
    if not mk.IsDone():
        return []
    return [p for p in (_wire_pts(w) for w in Compound(mk.Shape()).wires()) if len(p) > 2]


def offset_loop(pts, d: float) -> list[list]:
    """A closed XY loop grown by d (shrunk when d < 0): where a tool center runs around it."""
    return _offset_face(_poly_face(pts), d)


def chain_face(bodies, chain):
    """The exact face (real arcs, not points) inside a slice_chains chain: the part cut just
    above the chain's floor, the wire that is that chain. None if it isn't found."""
    xs, ys = [p[0] for p in chain["pts"]], [p[1] for p in chain["pts"]]
    want = (min(xs), min(ys), max(xs), max(ys))
    z = chain["z0"] + min(1e-3, (chain["z1"] - chain["z0"]) / 2)
    for b in bodies:
        for f in b.shape.intersect(Plane.XY.offset(z)).faces():
            f = Pos(0, 0, -z) * f
            for w in [f.outer_wire()] + f.inner_wires():
                bb = w.bounding_box()
                if all(abs(a - c) < 3e-3 for a, c in zip((bb.min.X, bb.min.Y, bb.max.X, bb.max.Y), want)):
                    return Face(w)
    return None


def _grow(face, d):
    """A face's outline grown by d (shrunk when d < 0), arcs kept, as a Face; None when nothing
    is left. (build123d's offset_2d: OCC's MakeOffset crashes on a one-circle face.)"""
    if abs(d) < 1e-12:
        return face
    try:
        w = face.outer_wire().offset_2d(d, kind=Kind.ARC)
        f = Face(w)
        return f if f.area > 1e-9 else None
    except Exception:
        return None


def clearing_passes(boundary, grow_boundary: float, islands, grow_islands: float, step: float,
                    max_passes: int = 400) -> list[list]:
    """Mill Roughing: where the tool center runs, pass after pass. The area = `boundary` (an XY
    loop, or an exact Face) grown by grow_boundary (- = shrunk) less every island (exact Faces,
    see chain_face) grown by grow_islands; pass k is its outline offset k x step inward, until
    nothing is left. [[loop, ...] per pass]."""
    base = boundary if isinstance(boundary, Face) else _poly_face(boundary)
    passes = []
    for k in range(max_passes):                      # pass k: boundary shrunk k x step, islands grown
        outer = _grow(base, grow_boundary - k * step)
        if outer is None:
            break
        region = outer
        for isl in islands:
            g = _grow(isl, grow_islands + k * step)
            if g is not None:
                region = region - g
        faces = region.faces() if hasattr(region, "faces") else [region]
        loops = [p for f in faces if f.area > 1e-9 for w in [f.outer_wire()] + f.inner_wires()
                 if len(p := _wire_pts(w)) > 2]
        if not loops:
            break
        passes.append(loops)
    return passes


def _area(pts):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])) / 2


def model_snap_points(bodies) -> list[tuple]:
    """Points a WCS can be picked on: [((x, y, z), kind)] with kind 'end' (edge ends / vertices),
    'mid' (edge middles) and 'center' (circle and arc centers), duplicates merged."""
    out, seen = [], set()

    def add(v, kind):
        key = (round(v.X, 6), round(v.Y, 6), round(v.Z, 6), kind)
        if key not in seen:
            seen.add(key)
            out.append(((v.X, v.Y, v.Z), kind))

    for b in bodies:
        for v in b.shape.vertices():
            add(Vector(v.X, v.Y, v.Z), "end")
        for e in b.shape.edges():
            add(e.position_at(0.5), "mid")
            if e.geom_type == GeomType.CIRCLE:
                add(e.arc_center, "center")
    return out


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


def turn_profile(bodies, point, direction) -> list[tuple]:
    """The parts' OD silhouette about an axis: [(t, r)] with t = distance along `direction` from
    `point`, r = the largest radius there, sorted by t. Steps (shoulders) show as two points at
    the same t. Built from a light mesh (arcs within 0.002 in), so it also sees features that
    aren't round - whatever sticks out furthest at each station."""
    p, d = np.asarray(point, float), np.asarray(direction, float)
    d = d / np.linalg.norm(d)
    segs = []
    for b in bodies:
        v, f = triangles(b.shape, 0.002, 0.1)
        if not len(v):
            continue
        w = v - p
        t = w @ d
        r = np.sqrt(np.maximum(((w - np.outer(t, d)) ** 2).sum(1), 0.0))
        f = np.asarray(f).reshape(-1, 3)
        e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
        e = np.unique(np.sort(e, 1), axis=0)
        segs.append(np.column_stack([t[e[:, 0]], r[e[:, 0]], t[e[:, 1]], r[e[:, 1]]]))
    if not segs:
        return []
    S = np.concatenate(segs)
    S = np.where((S[:, 0] > S[:, 2])[:, None], S[:, [2, 3, 0, 1]], S)   # t0 <= t1
    S[:, [0, 2]] = np.round(S[:, [0, 2]], 6)
    ts = np.unique(np.concatenate([S[:, 0], S[:, 2]]))
    flat = S[:, 2] - S[:, 0] > 0
    out = []
    for i, b in enumerate(ts):
        cover = (S[:, 0] <= b) & (S[:, 2] >= b)
        c = S[cover]
        k = (c[:, 2] - c[:, 0]) > 0
        at = np.where(k, c[:, 1] + (c[:, 3] - c[:, 1]) * (b - c[:, 0]) / np.where(k, c[:, 2] - c[:, 0], 1), 0)
        top = float(max(at[k].max(initial=0), c[~k][:, [1, 3]].max(initial=0)))
        left = S[flat & (S[:, 0] < b) & (S[:, 2] >= b)]
        right = S[flat & (S[:, 0] <= b) & (S[:, 2] > b)]

        def lim(c):
            return float((c[:, 1] + (c[:, 3] - c[:, 1]) * (b - c[:, 0]) / (c[:, 2] - c[:, 0])).max(initial=0))
        pts = [(b, lim(left))] if i else []
        pts.append((b, top))
        if i < len(ts) - 1:
            pts.append((b, lim(right)))
        for q in pts:
            if not out or abs(out[-1][1] - q[1]) > 1e-6 or abs(out[-1][0] - q[0]) > 1e-9:
                out.append((float(q[0]), float(q[1])))
    clean = []                                     # drop points in the middle of a straight run
    for q in out:
        while len(clean) >= 2:
            (x0, y0), (x1, y1) = clean[-2], clean[-1]
            if abs((x1 - x0) * (q[1] - y0) - (y1 - y0) * (q[0] - x0)) < 1e-9 and x0 <= x1 <= q[0]:
                clean.pop()
            else:
                break
        clean.append(q)
    return clean


def turn_bore(bodies, point, direction) -> list[tuple]:
    """The parts' ID (bore) silhouette about an axis: [(t, r)] like turn_profile, but r = the
    smallest radius of material at each station (0 where the axis runs through solid). Steps
    show as two points at the same t. Same light mesh as turn_profile."""
    p, d = np.asarray(point, float), np.asarray(direction, float)
    d = d / np.linalg.norm(d)
    segs, solids = [], []
    for b in bodies:
        v, f = triangles(b.shape, 0.002, 0.1)
        if not len(v):
            continue
        solids.append(b.shape)
        w = v - p
        t = w @ d
        r = np.sqrt(np.maximum(((w - np.outer(t, d)) ** 2).sum(1), 0.0))
        f = np.asarray(f).reshape(-1, 3)
        e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
        e = np.unique(np.sort(e, 1), axis=0)
        segs.append(np.column_stack([t[e[:, 0]], r[e[:, 0]], t[e[:, 1]], r[e[:, 1]]]))
    if not segs:
        return []
    S = np.concatenate(segs)
    S = np.where((S[:, 0] > S[:, 2])[:, None], S[:, [2, 3, 0, 1]], S)   # t0 <= t1
    S[:, [0, 2]] = np.round(S[:, [0, 2]], 6)
    S = S[S[:, 2] - S[:, 0] > 0]                     # faces square to the axis show as steps
    ts = np.unique(np.concatenate([S[:, 0], S[:, 2]]))

    def lim(c, b):
        return float((c[:, 1] + (c[:, 3] - c[:, 1]) * (b - c[:, 0]) / (c[:, 2] - c[:, 0])).min())

    def solid_at(t):
        q = Vector(*(p + t * d))
        return any(s.is_inside(q) for s in solids)
    out = []
    for a, b in zip(ts, ts[1:]):
        span = S[(S[:, 0] <= a) & (S[:, 2] >= b)]
        if not len(span):
            continue                                 # a gap between parts
        if solid_at((a + b) / 2):
            seg = [(a, 0.0), (b, 0.0)]
        else:
            seg = [(a, lim(span, a)), (b, lim(span, b))]
        for q in seg:
            if not out or abs(out[-1][1] - q[1]) > 1e-6 or abs(out[-1][0] - q[0]) > 1e-9:
                out.append((float(q[0]), float(q[1])))
    clean = []                                     # drop points in the middle of a straight run
    for q in out:
        while len(clean) >= 2:
            (x0, y0), (x1, y1) = clean[-2], clean[-1]
            if abs((x1 - x0) * (q[1] - y0) - (y1 - y0) * (q[0] - x0)) < 1e-9 and x0 <= x1 <= q[0]:
                clean.pop()
            else:
                break
        clean.append(q)
    return clean


def turn_section(bodies, point, direction) -> list[tuple]:
    """The parts cut through the spindle axis (one half): [(t0, r0, t1, r1)] boundary segments,
    t = distance along `direction` from `point`, r = distance from the axis (>= 0). Exact for
    turned (round) parts; what Groove finds its OD / ID / face grooves in. Curves come as short
    straight pieces (about 0.005 in)."""
    p, d = np.asarray(point, float), np.asarray(direction, float)
    d = d / np.linalg.norm(d)
    n = np.cross(d, [0.0, 0.0, 1.0])
    if np.linalg.norm(n) < 1e-6:
        n = np.cross(d, [0.0, 1.0, 0.0])
    n = n / np.linalg.norm(n)                       # the cut plane holds d; its normal is n
    y = np.cross(n, d)                              # the r direction in the cut plane
    L = 1000.0
    half = Face.make_rect(2 * L, L, Plane(origin=Vector(*(p + y * L / 2)), x_dir=Vector(*d), z_dir=Vector(*n)))
    out = []
    for b in bodies:
        try:
            sec = b.shape & half
        except Exception:
            continue
        for e in sec.edges():
            k = 1 if e.geom_type == GeomType.LINE else max(4, int(e.length / 0.005))
            pts = [_np(e.position_at(j / k)) - p for j in range(k + 1)]
            tr = [(float(q @ d), float(np.linalg.norm(q - (q @ d) * d))) for q in pts]
            out += [(a[0], a[1], c[0], c[1]) for a, c in zip(tr, tr[1:])]
    return out


def _np(v):
    return np.array([v.X, v.Y, v.Z], float)


def find_holes(bodies, tol: float = 1e-5) -> list[dict]:
    """Round holes in the parts: [{"p": point on the axis at the open end, "axis": unit vector
    pointing OUT of the hole, "dia", "depth" (full-diameter depth), "through": bool}].
    A hole is an inward-facing cylinder with at least one open end; coaxial pieces of the same
    size (a cylinder split at its seam) count as one hole. Holes open at both ends are listed
    once per open end, so a caller can take the end it can reach."""
    groups = []
    for b in bodies:
        for f in b.shape.faces():
            if f.geom_type != GeomType.CYLINDER:
                continue
            ax = f.axis_of_rotation
            o, d = _np(ax.position), _np(ax.direction)
            d = d / np.linalg.norm(d)
            q = _np(f.position_at(0.5, 0.5))
            n = _np(f.normal_at(f.position_at(0.5, 0.5)))
            w = q - o
            radial = w - (w @ d) * d
            if n @ radial >= 0:                          # normal points away from the axis: a boss
                continue
            ts = [(_np(v) - o) @ d for v in f.vertices()] or [0.0]
            for e in f.edges():
                ts += [(_np(e.position_at(k / 4)) - o) @ d for k in range(5)]
            r = float(f.radius)
            for g in groups:
                gd, go = g["d"], g["o"]
                off = o - go
                if abs(abs(gd @ d) - 1) < 1e-9 and np.linalg.norm(off - (off @ gd) * gd) < tol and \
                        abs(g["r"] - r) < tol and g["body"] is b:
                    ts = [((o + t * d) - go) @ gd for t in ts]
                    g["t0"], g["t1"] = min(g["t0"], min(ts)), max(g["t1"], max(ts))
                    break
            else:
                groups.append({"o": o, "d": d, "r": r, "t0": min(ts), "t1": max(ts), "body": b})
    out = []
    for g in groups:
        o, d, s = g["o"], g["d"], g["body"].shape
        ends = []
        for t, sgn in ((g["t1"], 1.0), (g["t0"], -1.0)):
            probe = o + (t + sgn * 0.001) * d
            ends.append((t, sgn, not s.is_inside(Vector(*probe))))
        open_ends = [e for e in ends if e[2]]
        for t, sgn, _ in open_ends:
            p = o + t * d
            out.append({"p": tuple(float(v) for v in p), "axis": tuple(float(v) for v in sgn * d),
                        "dia": round(2 * g["r"], 6), "depth": float(g["t1"] - g["t0"]),
                        "through": len(open_ends) == 2})
    return out


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
