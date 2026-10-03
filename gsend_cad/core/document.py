"""Design document: an ordered feature timeline plus a rollback marker.

Features are plain dicts so a document saves as JSON and can be read by the CAM side
of G-SEND.IO without importing Qt or the geometry kernel:

    sketch:  {"id", "kind": "sketch",  "name", "plane_z", "ents": [...], "plane": frame}
             plane (see core/plane.py) is where the 2D entities sit: absent = the XY plane at
             plane_z, as every file before planes could be picked; on a picked face plane_z is
             the offset along the face normal from the frame's base.
    extrude: {"id", "kind": "extrude", "name", "op": "join"|"cut"|"new", "distance",
              "direction": "one"|"sym", "profiles": [{"sketch", "outer", "holes"}]}
    hole:    {"id", "kind": "hole",    "name", "points": [[x, y]], "diameter",
              "depth": "through" | float, "top_z"}
    remove:  {"id", "kind": "remove",  "name", "body": "body2"}     (Delete on a body)

A sketch may also carry "show": true/false (Hide / Show Sketch). `body_names` holds names
the user gave bodies ({"body1": "Base Plate"}); bodies are otherwise Body1, Body2, ...

`marker` is how many features are applied (the timeline's blue bar), exactly like the
prototype's `tlPos`.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Callable

from . import cam
from . import plane as pl
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
        self.body_names: dict[str, str] = {}
        self.setups: list[dict] = []           # CAM setups (core.cam); not part of the design timeline
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

    def add_sketch(self, ents, plane_z=0.0, plane=None, **kw):
        f = {"kind": "sketch", "plane_z": float(plane_z), "ents": copy.deepcopy(list(ents)), **kw}
        if plane is not None and not pl.is_xy(plane):
            f["plane"] = copy.deepcopy(plane)
        return self.add(f)

    @staticmethod
    def sketch_plane(f: dict) -> dict:
        """Where a sketch's entities sit (core.plane frame)."""
        return pl.of_feature(f)

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

    def add_revolve(self, profiles, axis: dict, angle=360.0, op="join", **kw):
        """axis: {"sketch": id, "kind": "x" | "y" | "line", "ent": index (for "line")} - the
        sketch's X / Y axis through its origin, or one of its lines."""
        if op not in ("join", "cut", "new"):
            raise ValueError(f"bad revolve op {op!r}")
        if not 0 < abs(angle) <= 360:
            raise ValueError("revolve angle must be between 0 and 360")
        refs = [p.to_data() if hasattr(p, "to_data") else dict(p) for p in profiles]
        if not refs:
            raise ValueError("revolve needs at least one profile")
        return self.add({"kind": "revolve", "op": op, "angle": float(angle), "axis": dict(axis),
                         "profiles": refs, **kw})

    def add_fillet(self, edges, size: float, op="fillet", **kw):
        """Round (op "fillet", size = radius) or bevel ("chamfer", size = distance) solid edges,
        each remembered by its halfway point [x, y, z] (kernel.edge_list's "mid")."""
        if op not in ("fillet", "chamfer"):
            raise ValueError(f"bad fillet op {op!r}")
        if size <= 0:
            raise ValueError("size must be greater than 0")
        if not edges:
            raise ValueError("pick at least one edge")
        if op == "chamfer" and "name" not in kw:
            n = 1
            while self.name_taken(f"Chamfer{n}"):
                n += 1
            kw["name"] = f"Chamfer{n}"
        return self.add({"kind": "fillet", "op": op, "size": float(size), "edges": [list(m) for m in edges], **kw})

    def add_remove(self, body_id: str, **kw):
        return self.add({"kind": "remove", "body": body_id, **kw})

    def remove_features(self, ids) -> list[dict]:
        """Delete features by id (keeps the marker on the same remaining feature)."""
        ids = set(ids)
        gone = [f for f in self.features if f["id"] in ids]
        before = sum(1 for f in self.features[: self.marker] if f["id"] in ids)
        self.features = [f for f in self.features if f["id"] not in ids]
        self.marker -= before
        self._changed("features")
        return gone

    def dependents(self, sketch_id: str) -> list[dict]:
        """Extrudes and revolves made from a sketch."""
        return [f for f in self.features if f["kind"] in ("extrude", "revolve")
                and any(p["sketch"] == sketch_id for p in f["profiles"])]

    def name_taken(self, name: str, skip_id: str | None = None) -> bool:
        return any(f["name"] == name and f["id"] != skip_id for f in self.features)

    def add_hole(self, points, diameter, depth="through", top_z=0.0, **kw):
        return self.add({"kind": "hole", "points": [list(p) for p in points], "diameter": float(diameter),
                         "depth": depth, "top_z": float(top_z), **kw})

    def update_sketch(self, fid: str, ents, plane_z: float, origin=None, plane=None):
        """Replace a sketch's entities in place (Edit Sketch) and keep later extrudes pointing
        at the same shapes. `origin[i]` is the old index of new entity i, or None if it is new.
        A profile that used a deleted entity is left unresolvable, so its extrude shows red."""
        f = self.feature(fid)
        if origin is None:
            origin = list(range(len(ents)))
        remap: dict[int, list] = {}           # one old shape can become several (Fillet splits a rect)
        for new, old in enumerate(origin):
            if old is not None:
                remap.setdefault(old, []).append(new)
        f["ents"] = copy.deepcopy(list(ents))
        f["plane_z"] = float(plane_z)
        if plane is not None and not pl.is_xy(plane):
            f["plane"] = copy.deepcopy(plane)
        elif plane is not None:
            f.pop("plane", None)
        for g in self.features:
            if g["kind"] not in ("extrude", "revolve"):
                continue
            ax = g.get("axis")
            if ax and ax["sketch"] == fid and ax["kind"] == "line":
                ax["ent"] = remap.get(ax["ent"], [-1])[0]
            for ref in g["profiles"]:
                if ref["sketch"] == fid:
                    ref["outer"] = [n for i in ref["outer"] for n in remap.get(i, [-1])]
                    ref["holes"] = [[n for i in h for n in remap.get(i, [-1])] for h in ref.get("holes", [])]
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
        return {p["sketch"] for f in self.features[:n] if f["kind"] in ("extrude", "revolve")
                for p in f["profiles"]}

    def sketch_shown(self, f: dict, consumed: set | None = None) -> bool:
        """Whether a sketch is drawn. Without a user choice ("show" on the feature) a sketch
        hides once an extrude uses it, like Fusion; Hide / Show Sketch stores the choice."""
        if "show" in f:
            return bool(f["show"])
        return f["id"] not in (self.consumed_sketches() if consumed is None else consumed)

    def describe(self, f: dict) -> str:
        k = f["kind"]
        if k == "sketch":
            return f"{len(f['ents'])} entities · {pl.label(pl.of_feature(f))}"
        if k == "extrude":
            op = {"join": "Join", "cut": "Cut", "new": "New Body"}[f["op"]]
            sym = " symmetric" if f["direction"] == "sym" else ""
            n = len(f["profiles"])
            return f"{op} · {f['distance']:.3f} in{sym} · {n} profile{'s' if n != 1 else ''}"
        if k == "revolve":
            op = {"join": "Join", "cut": "Cut", "new": "New Body"}[f["op"]]
            ax = {"x": "X axis", "y": "Y axis", "line": "a line"}[f["axis"]["kind"]]
            return f"{op} · {f['angle']:.1f}° about {ax}"
        if k == "fillet":
            n = len(f["edges"])
            word = "R" if f["op"] == "fillet" else "Chamfer "
            return f"{word}{f['size']:.4f} · {n} edge{'s' if n != 1 else ''}"
        if k == "remove":
            return f"Remove {self.body_names.get(f['body'], f['body'].replace('body', 'Body'))}"
        if k == "hole":
            d = "thru" if f["depth"] == "through" else f"{float(f['depth']):.3f} deep"
            n = len(f["points"])
            return f"{n}× Ø{f['diameter']:.3f} {d}" if n > 1 else f"Ø{f['diameter']:.3f} {d}"
        return k

    # ---- CAM setups (see core.cam) ----
    def add_setup(self, setup: dict) -> dict:
        s = cam.validate(setup)
        n = 1
        while any(x["id"] == f"setup{n}" for x in self.setups):
            n += 1
        s["id"] = f"setup{n}"
        s.setdefault("name", cam.next_name("Setup", {x["name"] for x in self.setups}))
        self.setups.append(s)
        self._changed("setups")
        return s

    def update_setup(self, sid: str, setup: dict) -> dict:
        i = next(i for i, x in enumerate(self.setups) if x["id"] == sid)
        s = cam.validate({**setup, "id": sid, "name": setup.get("name", self.setups[i]["name"]),
                          "ops": setup.get("ops", self.setups[i].get("ops", [])),
                          **({"post": self.setups[i]["post"]} if "post" in self.setups[i] else {})})
        self.setups[i] = s
        self._changed("setups")
        return s

    def remove_setup(self, sid: str):
        self.setups = [x for x in self.setups if x["id"] != sid]
        self._changed("setups")

    def add_op(self, sid: str, op: dict) -> dict:
        """Add an operation (core.cam) to a setup. Gets an id and a name like Face1."""
        st = self.setup(sid)
        o = cam.validate_op(st, op)
        ids = {x["id"] for s in self.setups for x in s.get("ops", [])}
        n = 1
        while f"op{n}" in ids:
            n += 1
        o["id"] = f"op{n}"
        o.setdefault("name", cam.next_name(cam.OP_TYPES[o["type"]], {x["name"] for x in st.get("ops", [])}))
        st.setdefault("ops", []).append(o)
        self._changed("setups")
        return o

    def op(self, oid: str):
        """(setup, op) for an operation id, or (None, None)."""
        for s in self.setups:
            for o in s.get("ops", []):
                if o["id"] == oid:
                    return s, o
        return None, None

    def update_op(self, oid: str, op: dict) -> dict:
        st, old = self.op(oid)
        o = cam.validate_op(st, {**op, "id": oid, "name": op.get("name", old["name"])})
        st["ops"] = [o if x["id"] == oid else x for x in st["ops"]]
        self._changed("setups")
        return o

    def remove_op(self, oid: str):
        for s in self.setups:
            s["ops"] = [x for x in s.get("ops", []) if x["id"] != oid]
        self._changed("setups")

    def setup(self, sid: str) -> dict | None:
        return next((x for x in self.setups if x["id"] == sid), None)

    # ---- save / load ----
    def to_dict(self) -> dict:
        return {"format": FORMAT, "name": self.name, "units": UNITS, "material": self.material,
                "marker": self.marker, "features": copy.deepcopy(self.features),
                "body_names": dict(self.body_names), "setups": copy.deepcopy(self.setups)}

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        if d.get("format") != FORMAT:
            raise ValueError(f"not a {FORMAT} document")
        doc = cls(d.get("name", "Untitled"), d.get("material", "6061-T6"))
        doc.features = copy.deepcopy(d["features"])
        doc.marker = min(int(d.get("marker", len(doc.features))), len(doc.features))
        doc.body_names = dict(d.get("body_names", {}))
        doc.setups = copy.deepcopy(d.get("setups", []))
        doc._next = len(doc.features) + 1
        return doc

    def save(self, path):
        """Written to a temp file next to it, then swapped in: a crash mid-save never corrupts the part."""
        path = os.fspath(path)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

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
