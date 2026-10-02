"""Phase 5: the reconstructed outline becomes a Document - a fitted profile sketch and the
revolve that spins it into the part. Stdlib only (the kernel builds the solid when the app
rebuilds the document), so G-SEND.IO's CAM side can use it headless.

The sketch sits on the XY plane with x = lathe Z and y = radius, and the revolve turns it
about the sketch's X axis - so the part's spindle axis is the document's X axis, which is what
a CAM Turning setup picks up on its own.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core import profiles as pf
from ..core.document import Document
from .fit import Fit, fit_outline, to_entities


@dataclass
class Built:
    ok: bool
    error: str = ""
    doc: Document | None = None
    fit: Fit | None = None


def build_document(rec, name: str = "Imported part") -> Built:
    """rec: a Reconstruction. Returns a new Document holding the profile sketch and the revolve."""
    if not rec.ok:
        return Built(False, f"no profile to build: {rec.error}")
    fit = fit_outline(rec.edges)
    if not fit.ok:
        return Built(False, f"could not fit the outline: {fit.error}", fit=fit)
    ents = to_entities(fit)
    doc = Document(name)
    sketch = doc.add_sketch(ents, plane_z=0.0, name="Profile")
    regions = pf.sketch_regions(sketch["id"], sketch["ents"])
    if not regions:
        return Built(False, "the fitted outline does not close into a profile", fit=fit)
    outer = max(regions, key=lambda r: r.outer.area)       # the whole half-section, not a hole in it
    doc.add_revolve([outer], {"sketch": sketch["id"], "kind": "x"}, 360.0, op="join", name="Revolve1")
    return Built(True, "", doc, fit)
