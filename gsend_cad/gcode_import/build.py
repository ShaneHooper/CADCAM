"""Phase 5, part 2: put the fitted profile into the document as a sketch and a revolved body.

    reference sketch   the raw reconstruction outline, hidden and marked locked, so what the
                       program actually cut can always be compared with the edited sketch
    profile sketch     the fitted lines and arcs (fit.py): closed chain, coincident ends,
                       level / plumb exact, front face on Z0 (sketch Y = 0), bottom on the
                       centerline (sketch X = 0)
    revolve            360 degrees about the sketch's Y axis = the spindle (world Z), new body

The sketch sits on the XZ plane: sketch X is the radius, sketch Y is Z, with the FINISHED FRONT
FACE at Y = 0 and the part running to -Y, the way a lathe job is set up in Fusion.

The sketch has no constraint solver; the constraints this geometry satisfies are stored on the
sketch feature ("constraints") for a later solver, and `verify` proves they hold.
Stdlib + core only (no Qt, no shapely).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..core import profiles as pf
from ..core import sketch as sk
from .fit import TOL, Fit, check, fit_outline

# the XZ plane: sketch X = world X (radius), sketch Y = world Z (along the spindle), normal -Y
XZ_PLANE = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 0.0, 1.0], "n": [0.0, -1.0, 0.0]}
REVOLVE_AXIS_KIND = "y"          # the sketch's own Y axis through its origin = world Z
_NDIG = 10


class BuildError(ValueError):
    """The profile could not be made into a sketch / solid; the message says why, for the user."""


@dataclass
class Built:
    fit: Fit
    ents: list                   # the profile sketch's entities, in segment order
    ref_ents: list               # the raw outline as lines
    meta: dict                   # what the importer knew: tags per entity, shift, tolerance, threads
    z_shift: float               # program Z of the finished front face (sketch Y = program Z - this)


def _r(x: float) -> float:
    return round(x, _NDIG) + 0.0


def _uv(p, z_shift: float) -> list:
    return [_r(p[0]), _r(p[1] - z_shift)]


def make_entities(fit: Fit, z_shift: float) -> list:
    """Sketch line / arc entities for a fit, endpoints shared exactly between neighbours."""
    ents = []
    for s in fit.segs:
        a, b = _uv(s.a, z_shift), _uv(s.b, z_shift)
        if s.kind == "line":
            ents.append(sk.line(a, b))
            continue
        c = _uv(s.c, z_shift)
        start, end = (a, b) if s.ccw else (b, a)            # a sketch arc runs counter-clockwise
        a0 = math.degrees(math.atan2(start[1] - c[1], start[0] - c[0]))
        a1 = math.degrees(math.atan2(end[1] - c[1], end[0] - c[0]))
        ents.append(sk.arc(c, _r(s.r), a0, a1, pts=[start, end]))
    return ents


def build(rec, tol: float = TOL) -> Built:
    """Fit a Reconstruction and make the sketch data. Raises BuildError with a reason when it can't."""
    if not rec.ok or not rec.edges:
        raise BuildError(rec.error or "there is no profile to build (check the stock, tools and operations)")
    fit = fit_outline(rec.edges, tol)
    if len(fit.segs) < 3:
        raise BuildError("the outline has fewer than three segments after fitting")
    bad = check(fit)
    if bad:
        raise BuildError("the fitted outline is not a sound closed chain: " + "; ".join(bad[:3]))
    z_shift = rec.z_max
    ents = make_entities(fit, z_shift)
    ref = [sk.line(_uv((e.x0 / 2.0, e.z0), z_shift), _uv((e.x1 / 2.0, e.z1), z_shift)) for e in rec.edges
           if abs(e.z1 - e.z0) + abs(e.x1 - e.x0) > 1e-9]
    meta = {
        "tags": [s.tag for s in fit.segs],
        "tools": [s.src for s in fit.segs],
        "tolerance": tol,
        "max_deviation": fit.max_dev,
        "z_shift": z_shift,
        "threads": [t.callout for t in rec.threads],
        "assumed": fit.assumed,
    }
    return Built(fit, ents, ref, meta, z_shift)


def add_to_document(doc, built: Built, name: str = "Imported part") -> dict:
    """Add the reference sketch, the profile sketch and the revolve (one new body). Returns their ids.

    Raises BuildError (and leaves the document as it was) if the profile does not close into one region."""
    n_before = len(doc.features)
    marker = doc.marker
    ref = doc.add_sketch(built.ref_ents, plane=dict(XZ_PLANE), name=f"{name} reference", show=False,
                         locked=True, reference=True)
    prof = doc.add_sketch(built.ents, plane=dict(XZ_PLANE), name=f"{name} profile", show=True,
                          constraints=list(built.fit.constraints), imported=built.meta)
    regions = pf.sketch_regions(prof["id"], prof["ents"])
    if len(regions) != 1 or len(regions[0].outer.ents) != len(built.ents):
        doc.remove_features([ref["id"], prof["id"]])
        doc.marker = marker
        raise BuildError(f"the fitted outline does not close into a single region ({len(regions)} found)")
    rev = doc.add_revolve([regions[0]], {"sketch": prof["id"], "kind": REVOLVE_AXIS_KIND}, 360.0, op="new",
                          name=f"{name} revolve")
    assert len(doc.features) == n_before + 3
    return {"reference": ref["id"], "profile": prof["id"], "revolve": rev["id"]}


# ---- proof that the geometry satisfies what it claims ----
def verify(built: Built) -> list[str]:
    """Check the sketch data against its recorded constraints and the front-face / centerline rules."""
    bad = list(check(built.fit))
    ents = built.ents
    n = len(ents)
    pts = lambda e: e["pts"]
    for c in built.fit.constraints:
        t = c["type"]
        if t == "coincident":
            a, b = ents[c["a"][0]], ents[c["b"][0]]
            if not any(p in pts(b) for p in pts(a)):        # an arc stores its ends counter-clockwise
                bad.append(f"entities {c['a'][0]} and {c['b'][0]} do not meet")
        elif t == "horizontal" and pts(ents[c["ent"]])[0][1] != pts(ents[c["ent"]])[1][1]:
            bad.append(f"entity {c['ent']} is not level")
        elif t == "vertical" and pts(ents[c["ent"]])[0][0] != pts(ents[c["ent"]])[1][0]:
            bad.append(f"entity {c['ent']} is not plumb")
    us = [p[0] for e in ents for p in pts(e)]
    if min(us) < 0:
        bad.append("the profile crosses the centerline")
    if "AXIS" in built.meta["tags"] and abs(min(us)) > 1e-9:       # a tube's bore keeps it off the centerline
        bad.append("the profile does not reach the centerline")
    if max(p[1] for e in ents for p in pts(e)) > 1e-9:
        bad.append("the profile sits in front of Z0")
    return bad
