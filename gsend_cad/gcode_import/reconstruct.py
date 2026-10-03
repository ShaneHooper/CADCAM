"""Reconstruction: simulate the cutting and keep what is left.

Toolpath lines are NOT part edges. The stock's half-section (radius >= 0) is a polygon;
each tool's real shape is swept along every feed move and subtracted with exact polygon
booleans (geom2d). What remains is the part.

    rapids never cut; a rapid through the remaining stock is flagged
    insert      nose circle + its two edges, placed by the imaginary tip (default), the
                nose centre (per-import setting), or cutter comp when G41 / G42 is active
    drill       point angle + body          groove / cutoff   width + corner radius
    thread, tap no material removed: the thread is recorded as a feature on its cylinder
    G71 / G72   the P-Q block is the programmed finish contour: it is cut at size and
                cross-checked against the cutting moves
    SKIP        an operation typed SKIP contributes nothing

Every outline edge carries a tag: EXACT (a known tool or a P-Q block), ASSUMED (an unknown
tool, or a shape a defaulted nose radius decides), STOCK (never cut), AXIS (the centerline).

Coordinates: Z and X (diameter) in the results; (z, radius) internally.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import geom2d as g2
from . import keywords as kw
from . import toolshape as ts
from .inserts import parse_insert
from .operations import Operation, Thread, _words
from .parser import Flag, Program
from .stock import stock_z_range
from .tooling import NOSED, Tool

EXACT, ASSUMED, STOCK, AXIS = "EXACT", "ASSUMED", "STOCK", "AXIS"
_ON = 5e-6              # an outline point this close to a swept area's edge was cut by it
_INSIDE = 2e-4          # a rapid must be this deep in the stock, for this long, to be flagged
_RAPID_MIN = 0.002


@dataclass(frozen=True)
class Edge:
    z0: float
    x0: float           # diameter
    z1: float
    x1: float
    tag: str            # EXACT | ASSUMED | STOCK | AXIS
    tool: str = ""      # tool number that cut it ("PQ" for a P-Q block)


@dataclass
class Reconstruction:
    ok: bool = True
    error: str = ""
    edges: list[Edge] = field(default_factory=list)     # the outline, in order, closed
    max_dia: float = 0.0
    length: float = 0.0
    z_min: float = 0.0
    z_max: float = 0.0
    bore: float | None = None
    assumed_runs: int = 0                               # stretches of ASSUMED outline
    threads: list[Thread] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)     # P-Q cross-checks
    pieces: int = 1
    area: float = 0.0

    def count(self, tag: str) -> int:
        return sum(1 for e in self.edges if e.tag == tag)

    def spans_at(self, z: float) -> list[tuple[float, float]]:
        """Material on the line Z = z, as (inner diameter, outer diameter) spans."""
        xs = sorted(e.x0 + (e.x1 - e.x0) * (z - e.z0) / (e.z1 - e.z0) for e in self.edges
                    if min(e.z0, e.z1) < z <= max(e.z0, e.z1))
        return list(zip(xs[0::2], xs[1::2]))

    def diameter_at(self, z: float) -> float | None:
        """Outside diameter of the part at Z = z."""
        spans = self.spans_at(z)
        return spans[-1][1] if spans else None

    def bore_at(self, z: float) -> float | None:
        """Bore diameter at Z = z (None where the part is solid to the centerline)."""
        spans = self.spans_at(z)
        return spans[0][0] if spans and spans[0][0] > 1e-6 else None


# ---- the tool as a shape ----
@dataclass
class _Shape:
    kind: str                       # insert | drill | groove | none
    pts: list = field(default_factory=list)
    tip: tuple = (0.0, 0.0)         # programmed point -> the shape's own origin
    cls: str = "exact"              # exact | nose (nose radius is a default) | unknown
    rn: float = 0.0
    rdir: int = 1
    zdir: int = 1
    note: str = ""                  # why nothing is cut, when kind == "none"


def tool_shape(tool: Tool | None, side: str, flipped: bool = False) -> _Shape:
    """flipped: an OP2 tool - the part is turned end for end, so the tool's body lies the other way along Z."""
    if tool is None or tool.type == kw.UNKNOWN:
        rdir = -1 if side == "ID" else 1
        zd = -1 if flipped else 1
        return _Shape("insert", ts.insert(0.0, None, None, zd, rdir), (0.0, 0.0), "unknown", 0.0, rdir, zd)
    zdir = -1 if tool.hand == "LH" else 1
    if flipped:
        zdir = -zdir
    rdir = -1 if tool.side == "ID" else 1
    base = tool.base                                    # a user-made type cuts like the built-in it was given
    if base in NOSED:
        ins = parse_insert(tool.insert)
        rn = tool.nose_radius
        return _Shape("insert", ts.insert(rn, tool.shape_angle, ins.size * 1.1 if ins else None, zdir, rdir),
                      ts.tip_vector(rn, zdir, rdir), "nose" if tool.nose_assumed else "exact", rn, rdir, zdir)
    if base in ("DRILL", "SPOT DRILL"):
        if not tool.size:
            return _Shape("none", note=f"T{tool.number} ({tool.type.lower()}) has no diameter - its hole is not cut")
        return _Shape("drill", ts.drill(tool.size, ts.SPOT_POINT if base == "SPOT DRILL" else ts.DRILL_POINT,
                                        -1 if flipped else 1))
    if base in ("GROOVE", "CUTOFF", "FACE GROOVE"):
        if not tool.size:
            return _Shape("none", note=f"T{tool.number} ({tool.type.lower()}) has no width - its cuts are left out")
        return _Shape("groove", ts.groove(tool.size, tool.nose_radius, rdir, zdir, base == "FACE GROOVE"),
                      rdir=rdir, zdir=zdir)
    return _Shape("none")           # THREAD, TAP: a feature on the cylinder, no material removed


# ---- sweeping ----
def _sweep(shape: _Shape, path: list) -> list:
    """The area the shape covers moving along a path of its origin."""
    out = []
    for a, b in zip(path, path[1:]):
        out.append(g2.hull([(a[0] + z, a[1] + r) for z, r in shape.pts] + [(b[0] + z, b[1] + r) for z, r in shape.pts]))
    return out


def _centre_path(shape: _Shape, programmed: list, comp: bool, nose_center: bool) -> list:
    """Where the shape's origin goes for a run of programmed points."""
    if shape.kind != "insert" or nose_center or shape.rn <= 0.0:
        if shape.kind == "insert" and not nose_center:
            return [(z + shape.tip[0], r + shape.tip[1]) for z, r in programmed]
        return list(programmed)
    if comp and len(programmed) >= 2:
        # G41 / G42: the programmed path IS the finished contour, so the nose centre runs one
        # nose radius off it, on the side the tool is on.
        sides = [s for s in g2.offset_path(programmed, shape.rn) if len(s) >= 2]
        if sides:
            score = lambda s: sum(r * shape.rdir for _, r in s) / len(s) + 1e-3 * sum(z * shape.zdir for z, _ in s) / len(s)
            return max(sides, key=score)
    return [(z + shape.tip[0], r + shape.tip[1]) for z, r in programmed]


def _pts(move) -> list:
    return [(z, x / 2.0) for z, x in move.points]


def _runs(program: Program, op: Operation):
    """An operation's moves as ('cut', [moves]) / ('rapid', move) in order."""
    run = []
    for i in op.moves:
        m = program.moves[i]
        if m.kind == "rapid":
            if run:
                yield "cut", run
                run = []
            yield "rapid", (i, m)
        elif m.kind != "thread":
            if run and (m.comp != "G40") != (run[-1].comp != "G40"):
                yield "cut", run
                run = []
            run.append(m)
    if run:
        yield "cut", run


def _chain(moves) -> list:
    pts = _pts(moves[0])
    for m in moves[1:]:
        p = _pts(m)
        pts += p[1:] if abs(p[0][0] - pts[-1][0]) + abs(p[0][1] - pts[-1][1]) < 1e-9 else p
    return pts


def _pq_final(program: Program, op: Operation):
    """The P-Q contour at FINAL size: the cycle's profile moves with the finish allowance taken off."""
    prof = [program.moves[i] for i in op.moves
            if program.moves[i].code in ("G71 profile", "G72 profile") and program.moves[i].kind != "rapid"]
    if not prof:
        return []
    w = _words(program.lines[prof[0].line - 1])
    k = 1.0 / 25.4 if program.units == "mm" else 1.0
    du, dw = w.get("U", 0.0) * k, w.get("W", 0.0) * k
    if program.x_inverted:                              # U is written for the negative-X side: mirror it too
        du = -du
    if op.part == 2:                                    # OP2's Z is mirrored into OP1's frame, and W with it
        dw = -dw
    runs, run = [], []
    for m in prof:                                      # split where a rapid broke the contour
        p = [(z - dw, (x - du) / 2.0) for z, x in m.points]
        if run and abs(p[0][0] - run[-1][0]) + abs(p[0][1] - run[-1][1]) > 1e-9:
            runs.append(run)
            run = []
        run += p if not run else p[1:]
    if run:
        runs.append(run)
    return runs


# ---- the reconstruction ----
def reconstruct(program: Program, tools: list[Tool], ops: list[Operation], stock: dict,
                nose_center: bool = False) -> Reconstruction:
    """stock: the Setup step's settings (od, id, length, z0, front)."""
    res = Reconstruction()
    if not g2.AVAILABLE:
        res.ok, res.error = False, f"needs the shapely library ({g2.WHY_NOT})"
        return res
    zb, zf = stock_z_range(stock["z0"], stock["length"], stock.get("front", 0.0))
    r_in, r_out = stock.get("id", 0.0) / 2.0, stock["od"] / 2.0
    if r_out <= r_in or zf <= zb:
        res.ok, res.error = False, "the stock has no material (check OD, ID and length in Setup)"
        return res
    stock_poly = g2.rect(zb, r_in, zf, r_out)
    remaining = stock_poly
    by = {t.number: t for t in tools}
    swept: dict[str, list] = {}                         # source -> areas it cut ("01", "PQ")
    cls_of: dict[str, str] = {"PQ": "exact"}
    pq_areas: list[tuple[Operation, list]] = []
    flagged: set[int] = set()
    noted: set[str] = set()
    inner = None

    for op in ops:
        if op.type == "SKIP":
            continue
        shape = tool_shape(by.get(op.tool), op.side, op.part == 2)
        cls_of[op.tool] = shape.cls
        if shape.kind == "none":
            if shape.note and shape.note not in noted:
                noted.add(shape.note)
                res.flags.append(Flag(op.line0, "warn", shape.note))
            continue
        for kind, item in _runs(program, op):
            if kind == "rapid":
                i, m = item
                if i == 0 or m.code == "G28" or m.line in flagged:
                    continue                            # the start position / machine home are not known
                if inner is None:
                    inner = g2.shrink(remaining, _INSIDE)
                a, b = _centre_path(shape, [_pts(m)[0], _pts(m)[-1]], False, nose_center)
                if g2.length_inside(inner, a, b) > _RAPID_MIN:
                    flagged.add(m.line)
                    res.flags.append(Flag(m.line, "warn", f"rapid into stock (T{op.tool}) - a rapid never cuts, "
                                                           "so check the stock size, Z0, or this tool's definition"))
                continue
            comp = item[0].comp != "G40"
            areas = _sweep(shape, _centre_path(shape, _chain(item), comp, nose_center))
            if areas:
                cut = g2.union(areas)
                swept.setdefault(op.tool, []).append(cut)
                remaining = g2.subtract(remaining, cut)
                inner = None
        if op.motion in ("G71", "G72"):
            for run in _pq_final(program, op):
                comp = any(program.moves[i].comp != "G40" for i in op.moves)
                pq_areas.append((op, _sweep(shape, _centre_path(shape, run, comp, nose_center))))

    for op, areas in pq_areas:                          # the P-Q block is the profile; check it against the moves
        cut = g2.union(areas)
        left = g2.area(remaining.intersection(cut))
        if left < 1e-5:
            res.checks.append(f"P-Q block {op.lines}: agrees with the cutting moves.")
        else:
            res.checks.append(f"P-Q block {op.lines}: the cutting moves leave {left:.5f} sq in above it "
                              "(no finish pass at size?). The P-Q contour was used as the profile.")
        swept.setdefault("PQ", []).append(cut)
        remaining = g2.subtract(remaining, cut)

    if program.flip is not None:                        # a flip program: the part ends at the overall length
        remaining = g2.subtract(remaining, g2.rect(zb - 10.0, -1.0, -program.flip.length, r_out + 1.0))

    part = g2.clean(remaining)
    pcs = g2.pieces(part)
    if not pcs:
        res.ok, res.error = False, "nothing is left of the stock - check the stock size and Z0 in Setup"
        return res
    res.pieces = len(pcs)
    front = max(pcs, key=lambda p: (round(g2.bounds(p)[2], 6), g2.area(p)))
    if len(pcs) > 1:
        res.flags.append(Flag(0, "info", f"the cuts leave {len(pcs)} separate pieces (a part-off) - "
                                         "the front one is the part"))
    if g2.holes(front):
        res.flags.append(Flag(0, "warn", "the profile has an enclosed pocket no tool could have cut - "
                                         "check the tool definitions"))

    unions = {src: g2.union(areas) for src, areas in swept.items()}
    order = sorted(unions, key=lambda s: {"exact": 0, "nose": 1, "unknown": 2}[cls_of.get(s, "exact")])
    ring = g2.ring(front)
    for (z0, r0), (z1, r1) in zip(ring, ring[1:]):
        if abs(z1 - z0) + abs(r1 - r0) < 1e-9:
            continue
        mid = ((z0 + z1) / 2.0, (r0 + r1) / 2.0)
        if max(r0, r1) <= 1e-7:
            tag, src = AXIS, ""
        else:
            src = next((s for s in order if g2.boundary_distance(unions[s], mid) < _ON), None)
            if src is None:
                tag, src = STOCK, ""
            else:
                cls = cls_of.get(src, "exact")
                straight = abs(z1 - z0) < 1e-7 or abs(r1 - r0) < 1e-7
                # a defaulted nose radius cannot move a surface that runs along an axis:
                # the imaginary tip sets those. It decides every taper, arc and blend.
                tag = EXACT if cls == "exact" or (cls == "nose" and straight) else ASSUMED
        res.edges.append(Edge(z0, 2 * r0, z1, 2 * r1, tag, src))

    zmin, _rmin, zmax, rmax = g2.bounds(front)
    res.z_min, res.z_max, res.length, res.max_dia, res.area = zmin, zmax, zmax - zmin, 2 * rmax, g2.area(front)
    spans = g2.cross_section_r(front, zmax - min(1e-3, (zmax - zmin) / 10))
    res.bore = 2 * spans[0][0] if spans and spans[0][0] > 1e-6 else None
    tags = [e.tag for e in res.edges]
    res.assumed_runs = sum(1 for i, t in enumerate(tags) if t == ASSUMED and tags[i - 1] != ASSUMED) or (
        1 if tags and all(t == ASSUMED for t in tags) else 0)
    for op in ops:
        if op.thread and op.type != "SKIP":
            th = op.thread
            if th.major is None and th.side == "OD":    # G92 does not say: take the cylinder it sits on
                on = g2.cross_section_r(front, (th.z0 + th.z1) / 2.0)
                if on:
                    th = replace(th, major=2 * on[-1][1])
            res.threads.append(th)
    return res
