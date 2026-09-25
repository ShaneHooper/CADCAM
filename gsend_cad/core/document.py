"""Design document: an ordered feature timeline plus a rollback marker.

Features are plain dicts so a document saves as JSON and can be read by the CAM side
of G-SEND.IO without importing Qt or the geometry kernel:

    sketch:  {"id", "kind": "sketch",  "name", "plane_z", "ents": [...]}
    extrude: {"id", "kind": "extrude", "name", "op": "join"|"cut"|"new", "distance",
              "direction": "one"|"sym", "profiles": [{"sketch", "outer", "holes"}]}
    hole:    {"id", "kind": "hole",    "name", "points": [[x, y]], "diameter",
              "depth": "through" | float, "top_z"}

`marker` is how many features are applied (the timeline's blue bar), exactly like the
prototype's `tlPos`.
"""
from __future__ import annotations

import copy
import json
from typing import Callable

from . import sketch as sk

FORMAT = "gsend-cad/1"
UNITS = "in"
# lb / in^3
DENSITY = {"6061-T6": 0.0975, "7075-T6": 0.1015, "1018 Steel": 0.2836, "304 SS": 0.289, "Delrin": 0.0513}


class Document:
    def __init__(self, name: str = "Untitled", material: str = "6061-T6"):
        self.name = name
        self.material = material
        self.features: list[dict] = []
        self.marker = 0
        self._listeners: list[Callable[[str], None]] = []
        self._next = 1

    # ---- change notification (the UI subscribes; the CAM side can too) ----
    def subscribe(self, fn: Callable[[str], None]):
        self._listeners.append(fn)

    def _changed(self, what: str):
        for fn in list(self._listeners):
            fn(what)

    # ---- features ----
    def _new_id(self, kind):
        while True:
            fid = f"{kind[:2]}{self._next}"
            self._next += 1
            if all(f["id"] != fid for f in self.features):
                return fid

    def _new_name(self, kind):
        base = kind.capitalize()
        n = sum(1 for f in self.features if f["kind"] == kind) + 1
        names = {f["name"] for f in self.features}
        while f"{base}{n}" in names:
            n += 1
        return f"{base}{n}"

    def add(self, feature: dict) -> dict:
        """Insert a feature at the marker (like Fusion) and move the marker past it."""
        f = dict(feature)
        f.setdefault("id", self._new_id(f["kind"]))
        f.setdefault("name", self._new_name(f["kind"]))
        self.features.insert(self.marker, f)
        self.marker += 1
        self._changed("features")
        return f

    def add_sketch(self, ents, plane_z=0.0, **kw):
        return self.add({"kind": "sketch", "plane_z": float(plane_z), "ents": copy.deepcopy(list(ents)), **kw})

    def add_extrude(self, profiles, distance, op="join", direction="one", **kw):
        if op not in ("join", "cut", "new"):
            raise ValueError(f"bad extrude op {op!r}")
        if direction not in ("one", "sym"):
            raise ValueError(f"bad extrude direction {direction!r}")
        if abs(distance) < 1e-6:
            raise ValueError("extrude distance must not be zero")
        refs = [p.to_data() if hasattr(p, "to_data") else dict(p) for p in profiles]
        if not refs:
            raise ValueError("extrude needs at least one profile")
        return self.add({"kind": "extrude", "op": op, "distance": float(distance), "direction": direction,
                         "profiles": refs, **kw})

    def add_hole(self, points, diameter, depth="through", top_z=0.0, **kw):
        return self.add({"kind": "hole", "points": [list(p) for p in points], "diameter": float(diameter),
                         "depth": depth, "top_z": float(top_z), **kw})

    def update_sketch(self, fid: str, ents, plane_z: float, origin=None):
        """Replace a sketch's entities in place (Edit Sketch) and keep later extrudes pointing
        at the same shapes. `origin[i]` is the old index of new entity i, or None if it is new.
        A profile that used a deleted entity is left unresolvable, so its extrude shows red."""
        f = self.feature(fid)
        if origin is None:
            origin = list(range(len(ents)))
        remap = {old: new for new, old in enumerate(origin) if old is not None}
        f["ents"] = copy.deepcopy(list(ents))
        f["plane_z"] = float(plane_z)
        for g in self.features:
            if g["kind"] != "extrude":
                continue
            for ref in g["profiles"]:
                if ref["sketch"] == fid:
                    ref["outer"] = [remap.get(i, -1) for i in ref["outer"]]
                    ref["holes"] = [[remap.get(i, -1) for i in h] for h in ref.get("holes", [])]
        self._changed("features")
        return f

    def feature(self, fid: str) -> dict:
        for f in self.features:
            if f["id"] == fid:
                return f
        raise KeyError(fid)

    def index(self, fid: str) -> int:
        return next(i for i, f in enumerate(self.features) if f["id"] == fid)

    def set_marker(self, n: int):
        n = max(0, min(len(self.features), n))
        if n != self.marker:
            self.marker = n
            self._changed("marker")

    def applied(self) -> list[dict]:
        return self.features[: self.marker]

    def consumed_sketches(self, upto: int | None = None) -> set[str]:
        """Sketch ids used by an applied extrude (those sketches hide, like in Fusion)."""
        n = self.marker if upto is None else upto
        return {p["sketch"] for f in self.features[:n] if f["kind"] == "extrude" for p in f["profiles"]}

    def sketch_shown(self, f: dict, consumed: set | None = None) -> bool:
        """Whether a sketch is drawn. Without a user choice ("show" on the feature) a sketch
        hides once an extrude uses it, like Fusion; Hide / Show Sketch stores the choice."""
        if "show" in f:
            return bool(f["show"])
        return f["id"] not in (self.consumed_sketches() if consumed is None else consumed)

    def describe(self, f: dict) -> str:
        k = f["kind"]
        if k == "sketch":
            return f"{len(f['ents'])} entities · XY plane Z {f['plane_z']:.3f}"
        if k == "extrude":
            op = {"join": "Join", "cut": "Cut", "new": "New Body"}[f["op"]]
            sym = " symmetric" if f["direction"] == "sym" else ""
            n = len(f["profiles"])
            return f"{op} · {f['distance']:.3f} in{sym} · {n} profile{'s' if n != 1 else ''}"
        if k == "hole":
            d = "thru" if f["depth"] == "through" else f"{float(f['depth']):.3f} deep"
            n = len(f["points"])
            return f"{n}× Ø{f['diameter']:.3f} {d}" if n > 1 else f"Ø{f['diameter']:.3f} {d}"
        return k

    # ---- save / load ----
    def to_dict(self) -> dict:
        return {"format": FORMAT, "name": self.name, "units": UNITS, "material": self.material,
                "marker": self.marker, "features": copy.deepcopy(self.features)}

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        if d.get("format") != FORMAT:
            raise ValueError(f"not a {FORMAT} document")
        doc = cls(d.get("name", "Untitled"), d.get("material", "6061-T6"))
        doc.features = copy.deepcopy(d["features"])
        doc.marker = min(int(d.get("marker", len(doc.features))), len(doc.features))
        doc._next = len(doc.features) + 1
        return doc

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=1)

    @classmethod
    def load(cls, path) -> "Document":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


def bracket_plate() -> Document:
    """The prototype's demo part, built from real features: a 4 × 3 × 0.5 in plate with
    0.25 corner radii, a Ø1.25 × 0.75 boss, 4× Ø0.266 thru holes and a Ø0.5 bore."""
    doc = Document("Bracket Plate v3")
    L, W, T = 4.0, 3.0, 0.5
    s1 = doc.add_sketch([sk.rect((-L / 2, -W / 2), (L / 2, W / 2), corner_r=0.25)], name="Sketch1")
    doc.add_extrude([{"sketch": s1["id"], "outer": [0], "holes": []}], T, op="new", name="Extrude1")
    s2 = doc.add_sketch([sk.circle((0, 0), 0.625)], plane_z=T, name="Sketch2")
    doc.add_extrude([{"sketch": s2["id"], "outer": [0], "holes": []}], 0.75, op="join", name="Extrude2")
    hx, hy = L / 2 - 0.4, W / 2 - 0.4
    doc.add_hole([[hx, hy], [-hx, hy], [-hx, -hy], [hx, -hy]], 0.266, top_z=T, name="Hole1")
    doc.add_hole([[0, 0]], 0.5, top_z=T + 0.75, name="Hole2")
    return doc
