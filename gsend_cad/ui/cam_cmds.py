"""CAM in the window: setups (stock, WCS), operations (Face, Roughing, Contour, Groove, Drill...),
toolpath drawing and Simulate.
"""
from __future__ import annotations

import math

import numpy as np
import pyvista as pv
from PySide6.QtCore import QSize, Qt, QTimer
from functools import partial

from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QMenu, QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget)

from ..core import cam, tools
from ..core import plane as pl
from ..kernel import (bodies_bbox, edge_list, max_radius, model_snap_points, outline_loops, turn_profile, turn_bore, turn_section, find_holes, slice_chains, chain_face, grown_chain, clearing_passes)
from . import icons, theme
from .cmd_base import NumBox, Panel, _RightClick, _dlg_footer, regions_for
from .solid_cmds import edge_at


# ------------------------------------------------------------------ CAM setup
def setup_bodies(win, setup):
    bodies = win.model.bodies
    return bodies if setup.get("body", "all") == "all" else [b for b in bodies if b.id == setup["body"]]


def turning_radius(win, setup, bodies):
    """The part's largest radius about the setup's spindle axis (cached per model + axis)."""
    i, center, _ = cam.turning_frame(bodies_bbox(bodies), setup)
    key = (tuple(b.id for b in bodies), setup["axis"])
    cache = win.cam_cache
    if key not in cache:
        cache.clear() if len(cache) > 32 else None
        cache[key] = max_radius(bodies, center, cam._unit(i))
    return cache[key]


def draw_setup(vp, win, setup, group="cam") -> bool:
    """Stock (translucent) + WCS triad of a setup into a viewport group. False if no body."""
    bodies = setup_bodies(win, setup)
    if not bodies:
        return False
    bbox = bodies_bbox(bodies)
    if setup["type"] == cam.MILLING:
        lo, hi = cam.stock_box(bbox, setup)
        box = pv.Box(bounds=(lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]))
        vp.add_surface(group, box, theme.WARN, 0.12, lit=False)
        xs, ys, zs = (lo[0], hi[0]), (lo[1], hi[1]), (lo[2], hi[2])
        edges = [[(xs[0], y, z), (xs[1], y, z)] for y in ys for z in zs] + \
                [[(x, ys[0], z), (x, ys[1], z)] for x in xs for z in zs] + \
                [[(x, y, zs[0]), (x, y, zs[1])] for x in xs for y in ys]
        vp.add_lines(group, edges, theme.WARN, 1.2)
        w = cam.wcs(bbox, setup)
    else:
        r = turning_radius(win, setup, bodies)
        c = cam.stock_cylinder(bbox, r, setup)
        a = np.array(c["axis"])
        back = np.array(c["center"])
        mid = back + a * c["length"] / 2
        cyl = pv.Cylinder(center=mid, direction=a, radius=c["r"], height=c["length"], resolution=64)
        vp.add_surface(group, cyl, theme.WARN, 0.12, lit=False)
        u = np.cross(a, [0, 0, 1] if abs(a[2]) < 0.9 else [1, 0, 0])
        u /= np.linalg.norm(u)
        v = np.cross(a, u)
        ring = [(np.cos(t) * u + np.sin(t) * v) * c["r"] for t in np.linspace(0, 2 * np.pi, 65)]
        lines = [np.array([back + q for q in ring]), np.array([back + a * c["length"] + q for q in ring])]
        lines += [np.array([back + q, back + a * c["length"] + q]) for q in ring[::16]]
        lines.append(np.array([back - a * 0.5, back + a * (c["length"] + 0.5)]))     # spindle centerline
        vp.add_lines(group, lines, theme.WARN, 1.2)
        w = cam.wcs(bbox, setup, r)
    o, x, z = (np.array(w[k]) for k in ("origin", "x", "z"))
    y = np.cross(z, x)
    L = 0.6
    for d, col in ((x, theme.BAD), (y, theme.OK), (z, "#3b8cff")):
        vp.add_lines(group, [np.array([o, o + d * L])], col, 3.0)
    vp.add_labels(group, [(tuple(o + z * (L + 0.12)), "WCS  " + setup.get("name", "Setup"))], theme.WARN)
    return True


class SetupPanel(Panel):
    def __init__(self, session: "SetupSession"):
        super().__init__("Setup", 250)
        s = session
        seg = QWidget()
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(10, 8, 10, 6)
        sl.setSpacing(0)
        self.type_btn = {}
        for i, (key, label) in enumerate(cam.TYPES.items()):
            b = QPushButton(label.upper())
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            rad = "border-top-left-radius:11px;border-bottom-left-radius:11px;" if i == 0 else \
                  "border-top-right-radius:11px;border-bottom-right-radius:11px;"
            b.setStyleSheet(f"QPushButton{{border:1px solid {theme.ACCENT};{rad}padding:3px 0;font-weight:700;"
                            f"letter-spacing:2px;color:{theme.FG2};background:{theme.BG};}}"
                            f"QPushButton:checked{{background:{theme.ACCENT};color:#ffffff;}}")
            b.clicked.connect(partial(s.set_type, key))
            sl.addWidget(b)
            self.type_btn[key] = b
        self.v.addWidget(seg)
        self.name = self.row("Name", self.value(""))
        self.body = QComboBox()
        self.body.addItem("All bodies", "all")
        for b in s.win.model.bodies:
            self.body.addItem(b.name, b.id)
        self.row("Part", self.body)
        self.mode = QComboBox()
        for k, label in cam.STOCK_MODES.items():
            self.mode.addItem(label, k)
        self.mode.setToolTip("Stock per side: extra material around the part. Fixed size: the blank's real size.")
        self.row("Stock", self.mode)

        def box(v):
            nb = NumBox(v)
            nb.setRange(0, 1000)
            nb.valueChanged.connect(s.preview)
            return nb

        def rows(widget, items):
            lay = QVBoxLayout(widget)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            out = {}
            for label, w in items:
                r = QWidget()
                r.setObjectName("panelRow")
                hl = QHBoxLayout(r)
                hl.setContentsMargins(10, 4, 10, 4)
                hl.addWidget(QLabel(label))
                hl.addStretch()
                hl.addWidget(w)
                lay.addWidget(r)
                out[label] = r
            return out

        # milling fields
        self.mill = QWidget()
        self.side, self.top, self.bottom = box(0.1), box(0.05), box(0.0)
        self.sx, self.sy, self.sz = box(4.25), box(3.25), box(1.0)
        self.mwcs = QComboBox()
        for k, label in cam.MILL_WCS.items():
            self.mwcs.addItem(label, k)
        self.pick = QPushButton("PICK IN VIEW")
        self.pick.setMinimumWidth(130)
        self.pick.setObjectName("dlgBtn")
        self.pick.setCheckable(True)
        self.pick.setToolTip("Hover the model, stock or a sketch point: ends, midpoints and centers light up. "
                             "Click one to put X0 Y0 Z0 there.")
        self.pick.toggled.connect(s.set_picking)
        self.picked = QLabel("—")
        self.picked.setStyleSheet(f"color:{theme.FG2};")
        self.xdir = QComboBox()
        for k, (label, _v) in cam.X_DIRS.items():
            self.xdir.addItem(label, k)
        self.xdir.setToolTip("Which way the WCS +X points. The WCS turns about Z: −X also flips Y, ±Y turns it 90°.")
        mr = rows(self.mill, [("Stock: sides", self.side), ("Stock width X", self.sx), ("Stock length Y", self.sy),
                              ("Stock height Z", self.sz), ("Stock: top", self.top), ("Stock: bottom", self.bottom),
                              ("WCS origin", self.mwcs), ("Origin point", self.pick), ("Picked", self.picked),
                              ("X axis points", self.xdir)])
        self.v.addWidget(self.mill)
        # turning fields
        self.turn = QWidget()
        self.axis = QComboBox()
        for k in cam.AXES:
            self.axis.addItem(f"Model {k.upper()}", k)
        self.front = QComboBox()
        self.od, self.face, self.back = box(0.05), box(0.05), box(0.5)
        self.dia, self.length = box(1.625), box(3.5)
        self.twcs = QComboBox()
        for k, label in cam.TURN_WCS.items():
            self.twcs.addItem(label, k)
        tr = rows(self.turn, [("Spindle axis", self.axis), ("Front (tool) end", self.front),
                              ("Stock: OD (radial)", self.od), ("Bar diameter", self.dia), ("Bar length", self.length),
                              ("Stock: front face", self.face), ("Stock: chuck side", self.back), ("Z0 at", self.twcs)])
        # rows that only belong to one stock mode (the rest show in both)
        self.offset_rows = [mr["Stock: sides"], mr["Stock: bottom"], tr["Stock: OD (radial)"], tr["Stock: chuck side"]]
        self.size_rows = [mr["Stock width X"], mr["Stock length Y"], mr["Stock height Z"], tr["Bar diameter"],
                          tr["Bar length"]]
        self.v.addWidget(self.turn)
        _dlg_footer(self, s)
        for w in (self.body, self.front, self.twcs, self.xdir):
            w.currentIndexChanged.connect(s.preview)
        self.mwcs.currentIndexChanged.connect(s.wcs_changed)
        self.axis.currentIndexChanged.connect(s.axis_changed)
        self.mode.currentIndexChanged.connect(s.mode_changed)

    def fit(self):
        self.layout().activate()
        self.resize(self.width(), self.sizeHint().height())
        vp = self.parent()
        if hasattr(vp, "_place"):
            vp._place()                      # a tall panel moves up so OK / CANCEL stay on screen


class SetupSession:
    """CAM → Setup: pick Milling or Turning, the part, stock and work zero. Also edits a setup."""
    captures_left = False

    def __init__(self, win, kind: str = cam.MILLING, edit: dict | None = None):
        self.win, self.vp = win, win.viewport
        self.edit_id = edit["id"] if edit else None
        self.wcs_point = list(edit["wcs_point"]) if edit and edit.get("wcs_point") else None
        self.picking, self.hover, self._snaps = False, None, None
        self.panel = SetupPanel(self)
        p = self.panel
        self._loading = True
        p.name.setText(edit["name"] if edit else cam.next_name("Setup", {x["name"] for x in win.doc.setups}))
        start = edit or cam.new_setup(kind)
        self._fill(start)
        self._loading = False
        self.set_type(start["type"], keep=bool(edit))

    def _fill(self, st):
        p = self.panel
        p.body.setCurrentIndex(max(0, p.body.findData(st.get("body", "all"))))
        stock = st["stock"]
        p.mode.setCurrentIndex(p.mode.findData(stock.get("mode", "offset")))
        for w, k in ((p.side, "side"), (p.top, "top"), (p.bottom, "bottom"), (p.sx, "x"), (p.sy, "y"), (p.sz, "z"),
                     (p.od, "od"), (p.face, "face"), (p.back, "back"), (p.dia, "dia"), (p.length, "length")):
            if k in stock:
                w.setValue(stock[k])
        if st["type"] == cam.MILLING:
            p.mwcs.setCurrentIndex(p.mwcs.findData(st["wcs"]))
            p.xdir.setCurrentIndex(max(0, p.xdir.findData(st.get("x_dir", "+x"))))
            self._show_picked()
        else:
            p.axis.setCurrentIndex(p.axis.findData(st["axis"]))
            self.axis_changed()
            p.front.setCurrentIndex(0 if st["front"] == "+" else 1)
            p.twcs.setCurrentIndex(p.twcs.findData(st["wcs"]))

    def set_type(self, kind: str, keep=False):
        p = self.panel
        self.kind = kind
        for k, b in p.type_btn.items():
            b.setChecked(k == kind)
        if kind == cam.TURNING and not keep:          # start on the axis the part is round about
            bodies = setup_bodies(self.win, {"body": p.body.currentData()})
            if bodies:
                self._loading = True
                p.axis.setCurrentIndex(p.axis.findData(cam.guess_axis(bodies_bbox(bodies))))
                self.axis_changed()
                self._loading = False
        p.mill.setVisible(kind == cam.MILLING)
        p.turn.setVisible(kind == cam.TURNING)
        self._show_mode_rows()
        p.fit()
        self.vp.set_side(p)
        self.preview()

    def _show_mode_rows(self):
        sized = self.panel.mode.currentData() == "size"
        for r in self.panel.offset_rows:
            r.setVisible(not sized)
        for r in self.panel.size_rows:
            r.setVisible(sized)

    def mode_changed(self, *_):
        """Stock per side <-> Fixed size. Going to Fixed size fills in the part + the per-side
        stock, rounded up to 1/8 in, so the numbers start sensible."""
        p = self.panel
        if p.mode.currentData() == "size" and not self._loading:
            cur = self.setup("offset")          # from the per-side fields
            bodies = setup_bodies(self.win, cur)
            if bodies:
                bbox = bodies_bbox(bodies)
                r = turning_radius(self.win, cur, bodies) if self.kind == cam.TURNING else 0.0
                size = cam.size_from_offsets(bbox, cur, r)
                self._loading = True
                for w, k in ((p.sx, "x"), (p.sy, "y"), (p.sz, "z"), (p.dia, "dia"), (p.length, "length")):
                    if k in size:
                        w.setValue(size[k])
                self._loading = False
        self._show_mode_rows()
        p.fit()
        self.vp.set_side(p)
        self.preview()

    def axis_changed(self, *_):
        p = self.panel
        ax = (p.axis.currentData() or "z").upper()
        i = p.front.currentIndex()
        p.front.blockSignals(True)
        p.front.clear()
        p.front.addItem(f"+{ax} end", "+")
        p.front.addItem(f"−{ax} end", "-")
        p.front.setCurrentIndex(max(0, i))
        p.front.blockSignals(False)
        self.preview()

    def setup(self, mode: str | None = None) -> dict:
        p = self.panel
        s = {"type": self.kind, "body": p.body.currentData(), "name": p.name.text()}
        mode = mode or p.mode.currentData() or "offset"
        if self.kind == cam.MILLING:
            stock = ({"mode": "size", "x": p.sx.value(), "y": p.sy.value(), "z": p.sz.value(), "top": p.top.value()}
                     if mode == "size" else
                     {"mode": "offset", "side": p.side.value(), "top": p.top.value(), "bottom": p.bottom.value()})
            s.update(stock=stock, wcs=p.mwcs.currentData(), x_dir=p.xdir.currentData())
            if self.wcs_point:
                s["wcs_point"] = list(self.wcs_point)
        else:
            stock = ({"mode": "size", "dia": p.dia.value(), "length": p.length.value(), "face": p.face.value()}
                     if mode == "size" else
                     {"mode": "offset", "od": p.od.value(), "face": p.face.value(), "back": p.back.value()})
            s.update(axis=p.axis.currentData(), front=p.front.currentData() or "+", wcs=p.twcs.currentData(),
                     stock=stock)
        return s

    def fit_problem(self):
        """Fixed-size stock smaller than the part: the message, else None."""
        st = self.setup()
        bodies = setup_bodies(self.win, st)
        if not bodies:
            return None
        r = turning_radius(self.win, st, bodies) if self.kind == cam.TURNING else 0.0
        return cam.fits(bodies_bbox(bodies), st, r)

    def preview(self, *_):
        if self._loading:
            return
        self.vp.clear("cam", render=False)
        self.vp.clear("setup", render=False)
        st = self.setup()
        if st.get("wcs") == "point" and not st.get("wcs_point"):
            st["wcs"] = "model"                    # nothing picked yet: show the stock, WCS at the model origin
        ok = draw_setup(self.vp, self.win, st, "setup")
        word = "MILLING" if self.kind == cam.MILLING else "TURNING"
        problem = self.fit_problem() if ok else None
        if problem:
            self.win.message(f"SETUP · {word}: {problem}")
            self.vp.render()
            return
        self.win.message(f"SETUP · {word}: yellow = stock, arrows = WCS (red X, green Y, blue Z) · "
                         "Enter / OK saves · Esc cancels" if ok else "SETUP: there is no solid to machine yet")
        self.vp.render()

    def commit(self):
        if not setup_bodies(self.win, self.setup()):
            self.vp.show_toast("No solid to machine · make a part in CAD first", bad=True)
            return
        if self.kind == cam.MILLING and self.panel.mwcs.currentData() == "point" and not self.wcs_point:
            self.vp.show_toast("Pick the origin point in the view first (PICK IN VIEW)", bad=True)
            return
        problem = self.fit_problem()
        if problem:
            self.vp.show_toast(problem, bad=True)
            return
        self.win.commit_setup(self.setup(), self.edit_id)

    # ---- picking the WCS origin in the view
    SNAP_NAMES = {"end": "ENDPOINT", "mid": "MIDPOINT", "center": "CENTER", "point": "SKETCH POINT",
                  "stock corner": "STOCK CORNER", "stock edge mid": "STOCK EDGE MIDPOINT",
                  "stock face center": "STOCK FACE CENTER"}

    def _show_picked(self):
        pt = self.wcs_point
        self.panel.picked.setText("—" if not pt else "X{:.4f} Y{:.4f} Z{:.4f}".format(*pt))

    def wcs_changed(self, *_):
        if self.panel.mwcs.currentData() == "point" and not self.wcs_point and not self._loading:
            self.panel.pick.setChecked(True)       # "Picked point" with nothing picked: start picking
        self.preview()

    def set_picking(self, on: bool):
        self.picking = on
        self._snaps = None
        self.panel.pick.setText("PICKING…" if on else "PICK IN VIEW")
        self.vp.clear("pick")
        self.win.message("PICK THE ORIGIN: hover the part, stock or a sketch point · ends, midpoints and centers "
                         "light up · click one · Esc stops picking" if on else "SETUP: Enter / OK saves · Esc cancels")

    def snaps(self):
        """Every point the origin can go on: model ends / mids / centers, the stock box, sketch points."""
        if self._snaps is None:
            st = self.setup()
            bodies = setup_bodies(self.win, st)
            pts = model_snap_points(bodies) if bodies else []
            if bodies and self.kind == cam.MILLING:
                pts += cam.stock_snap_points(bodies_bbox(bodies), {**st, "wcs": "top-center"})
            for f in self.win.doc.applied():
                if f["kind"] == "sketch":
                    fr = self.win.doc.sketch_plane(f)
                    pts += [(tuple(pl.to_world(fr, e["p"])), "point") for e in f["ents"] if e["type"] == "point"]
            self._snaps = pts
        return self._snaps

    def _hit(self, ev):
        pts = self.snaps()
        if not pts:
            return None
        q = self.vp.project([p for p, _k in pts])
        pos = ev.position()
        d = np.hypot(q[:, 0] - pos.x(), q[:, 1] - pos.y())
        near = np.where(d <= 12)[0]
        if not len(near):
            return None
        best = min(near, key=lambda i: (round(d[i] / 4), q[i, 2]))     # nearest, then front-most
        return pts[best]

    def on_move(self, w, ev):
        if not self.picking or ev.buttons():
            return
        hit = self._hit(ev)
        if hit == self.hover:
            return
        self.hover = hit
        self.vp.clear("pick", render=False)
        if hit:
            (x, y, z), kind = hit
            r = 10 * self.vp.pixel_size(ev.position().toPoint())
            ring = [(x + r * math.cos(t), y + r * math.sin(t), z) for t in np.linspace(0, 2 * math.pi, 25)]
            self.vp.add_lines("pick", [ring, [(x - r, y, z), (x + r, y, z)], [(x, y - r, z), (x, y + r, z)]],
                              theme.WARN, 2.4)
            self.vp.add_labels("pick", [((x, y, z + 3 * r), self.SNAP_NAMES.get(kind, kind.upper()))], theme.WARN)
        self.vp.plotter.setCursor(Qt.CrossCursor if hit else Qt.ArrowCursor)
        self.vp.render()

    def on_click(self, w, ev):
        if not self.picking:
            return
        hit = self._hit(ev)
        if not hit:
            self.vp.show_toast("Click right on a lit-up point", bad=True)
            return
        self.wcs_point = [float(v) for v in hit[0]]
        self.panel.mwcs.setCurrentIndex(self.panel.mwcs.findData("point"))
        self._show_picked()
        self.panel.pick.setChecked(False)          # stops picking
        self.vp.plotter.setCursor(Qt.ArrowCursor)
        self.vp.show_toast(f"Origin on the {self.SNAP_NAMES.get(hit[1], hit[1]).lower()}")
        self.preview()

    def on_key(self, ev) -> bool:
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.commit()
            return True
        if ev.key() == Qt.Key_Escape:
            if self.picking:
                self.panel.pick.setChecked(False)
            else:
                self.win.cancel_command()
            return True
        return False

    def ribbon_tool(self, label):
        if label == "Setup":
            return
        self.win.cancel_command()
        self.win.run_tool(label)

    def close(self):
        self.vp.clear("setup", render=False)
        self.vp.clear("pick", render=False)
        self.vp.plotter.setCursor(Qt.ArrowCursor)


# ------------------------------------------------------------------ CAM operations (Face)
def setup_holes(win, setup):
    """Round holes in the setup's bodies (kernel.find_holes), cached per model."""
    bodies = setup_bodies(win, setup)
    key = ("holes", tuple(b.id for b in bodies))
    cache = win.cam_cache
    if key not in cache:
        cache[key] = find_holes(bodies) if bodies else []
    return cache[key]


def _mill_rough_layers(win, setup, op, bodies, bbox):
    """[(z WCS, clearing passes)] for mill Roughing: each depth's passes round the islands that
    stand there (kernel.clearing_passes), cached for the same islands / boundary / tool."""
    import json
    o = cam.validate_op(setup, op)
    R, step = o["tool_dia"] / 2, o["tool_dia"] * o["stepover"] / 100
    if o.get("boundary"):                        # the tool stays inside a picked shape
        b = o["boundary"]
        f = None if b.get("sketch") else chain_face(bodies, b)
        boundary, grow_b = (f if f is not None else b["pts"]), -R
    else:                                        # the whole stock: the outside pass just clears its edge
        lo, hi = cam.stock_box(bbox, setup)
        boundary, grow_b = [(lo[0], lo[1]), (hi[0], lo[1]), (hi[0], hi[1]), (lo[0], hi[1])], R - 0.05
    cache = win.cam_cache
    faces = []
    for c in o["islands"]:
        f = None if c.get("sketch") else chain_face(bodies, c)
        faces.append(f if f is not None else c["pts"])
    out = []
    for z, act in cam.mill_rough_layers(bbox, setup, o):
        key = ("rough", json.dumps([o["islands"][i] for i in act], sort_keys=True),
               json.dumps(o.get("boundary"), sort_keys=True), round(R, 6), round(o["leave"], 6), round(step, 6),
               json.dumps(cam.stock_box(bbox, setup)))
        if key not in cache:
            isl = [faces[i] if not isinstance(faces[i], list) else _poly(faces[i]) for i in act]
            cache[key] = clearing_passes(boundary, grow_b, isl, R + o["leave"], step)
        out.append((z, cache[key]))
    return out


def _poly(pts):
    from build123d import Face, Wire
    return Face(Wire.make_polygon([(x, y, 0) for x, y in pts], close=True))


def op_moves(win, setup, op):
    """(WCS moves, world moves) for an operation; ([], []) when there's no part."""
    bodies = setup_bodies(win, setup)
    if not bodies:
        return [], []
    bbox = bodies_bbox(bodies)
    r = turning_radius(win, setup, bodies) if setup["type"] == cam.TURNING else 0.0
    loops = None
    if op.get("type") == "rough" and setup["type"] == cam.MILLING:
        loops = _mill_rough_layers(win, setup, op, bodies, bbox)
    elif op.get("type") == "contour" and op.get("chains"):    # the picked walls, each to its own floor
        grow = op["tool_dia"] / 2 + op.get("leave", 0.0)
        loops = [{"pts": q, "bottom": c["z0"], "inside": bool(c.get("hole"))}
                 for c in op["chains"] for q in grown_chain(bodies, c, -grow if c.get("hole") else grow)]
        if not loops:
            raise ValueError("the tool doesn't fit inside the picked pocket wall")
    elif op.get("type") == "contour":         # the part outline grown by tool radius + stock to leave
        grow = op["tool_dia"] / 2 + op.get("leave", 0.0)
        key = ("outline", tuple(b.id for b in bodies), round(grow, 6))
        cache = win.cam_cache
        if key not in cache:
            cache[key] = outline_loops(bodies, grow)
        loops = cache[key]
    profile = None
    if op.get("type") in ("rough", "finish") and setup["type"] == cam.TURNING:   # OD (or ID: bore) silhouette
        i, center, _ = cam.turning_frame(bbox, setup)
        inner = bool(op.get("internal"))
        key = ("bore" if inner else "profile", tuple(b.id for b in bodies), setup["axis"])
        cache = win.cam_cache
        if key not in cache:
            cache[key] = (turn_bore if inner else turn_profile)(bodies, center, cam._unit(i))
        profile = cache[key]
    if op.get("type") == "groove":              # the part cut through the axis: grooves on OD / ID / face
        i, center, _ = cam.turning_frame(bbox, setup)
        key = ("section", tuple(b.id for b in bodies), setup["axis"])
        cache = win.cam_cache
        if key not in cache:
            cache[key] = turn_section(bodies, center, cam._unit(i))
        profile = cache[key]
    holes = setup_holes(win, setup) if op.get("type") == "drill" else None
    moves = cam.toolpath(bbox, setup, op, r, loops, profile, holes)
    return moves, cam.toolpath_world(bbox, setup, moves, r)


def draw_toolpath(vp, world, group="cam", dim=False):
    """Feeds blue, rapids yellow (thin), like Fusion."""
    feeds, rapids = [], []
    for (_k0, a), (k1, b) in zip(world, world[1:]):
        (feeds if k1 == "feed" else rapids).append([a, b])
    vp.add_lines(group, rapids, theme.WARN, 1.0, opacity=0.5 if dim else 0.8)
    vp.add_lines(group, feeds, theme.ACCENT, 1.4 if dim else 2.2, opacity=0.6 if dim else 1.0)


class OpPanel(Panel):
    # op kind -> setup type -> [(key, label, decimals)]. The tool (T number, Ø) comes from the Tool
    # box (the tool library); combos (cut direction, cycle, output) are added per kind below.
    FIELDS = {"face": {cam.MILLING: [("stepover", "Stepover %", 1), ("stepdown", "Max stepdown", 4),
                                     ("leave", "Stock to leave", 4), ("rpm", "Spindle RPM", 0),
                                     ("feed", "Feed (in/min)", 2)],
                       cam.TURNING: [("stepdown", "Max stepdown", 4),
                                     ("leave", "Stock to leave", 4), ("past_center", "Past center (X)", 4),
                                     ("sfm", "Surface speed SFM", 0), ("ipr", "Feed (in/rev)", 4),
                                     ("max_rpm", "Max RPM", 0)]},
              "contour": {cam.MILLING: [("stepdown", "Max stepdown", 4), ("leave", "Wall stock", 4),
                                        ("bottom_offset", "Below part bottom", 4), ("lead", "Lead in / out", 4),
                                        ("rpm", "Spindle RPM", 0), ("feed", "Feed (in/min)", 2),
                                        ("plunge", "Plunge (in/min)", 2)]},
              "rough": {cam.MILLING: [("stepdown", "Max stepdown", 4), ("stepover", "Stepover % of tool", 1),
                                      ("leave", "Wall stock", 4), ("leave_floor", "Floor stock", 4),
                                      ("rpm", "Spindle RPM", 0), ("feed", "Feed (in/min)", 2),
                                      ("plunge", "Plunge (in/min)", 2)],
                        cam.TURNING: [("stepdown", "Depth of cut (side)", 4),
                                      ("leave_x", "Stock to leave X", 4), ("leave_z", "Stock to leave Z", 4),
                                      ("retract", "Pull-off", 4), ("bore_dia", "Drilled hole Ø (0 = auto)", 4),
                                      ("sfm", "Surface speed SFM", 0), ("ipr", "Feed (in/rev)", 4),
                                      ("max_rpm", "Max RPM", 0)]},
              "finish": {cam.TURNING: [("leave_x", "Stock to leave X", 4), ("leave_z", "Stock to leave Z", 4),
                                       ("retract", "Pull-off", 4), ("bore_dia", "Drilled hole Ø (0 = auto)", 4),
                                       ("sfm", "Surface speed SFM", 0),
                                       ("ipr", "Feed (in/rev)", 4), ("max_rpm", "Max RPM", 0)]},
              "groove": {cam.TURNING: [("stepover", "Stepover % of width", 0), ("peck", "Peck (0 = none)", 4),
                                       ("leave", "Stock to leave", 4), ("sfm", "Surface speed SFM", 0),
                                       ("ipr", "Feed (in/rev)", 4), ("max_rpm", "Max RPM", 0)]},
              "drill": {cam.MILLING: [("depth", "Depth (0 = hole)", 4), ("peck", "Peck (Q)", 4), ("breakthrough", "Breakthrough", 4),
                                      ("retract", "R plane above hole", 4), ("rpm", "Spindle RPM", 0),
                                      ("feed", "Feed (in/min)", 2)],
                        cam.TURNING: [("depth", "Depth (0 = hole)", 4), ("peck", "Peck (Q)", 4), ("breakthrough", "Breakthrough", 4),
                                      ("retract", "R plane off face", 4), ("rpm", "Spindle RPM", 0),
                                      ("ipr", "Feed (in/rev)", 4)]}}
    DIRECTIONS = {"face": [("Along X", "x"), ("Along Y", "y")],
                  "contour": [("Climb", "climb"), ("Conventional", "conventional")]}
    NEW_TOOL = "__new__"

    def __init__(self, session: "OpSession", kind: str):
        super().__init__({"face": "Face", "contour": "2D Contour", "rough": "Roughing", "finish": "Contour",
                          "drill": "Drill", "groove": "Groove"}[kind], 300)
        s = session
        # the setup and the name aren't shown: the op goes in the setup it was started from, and is
        # named Face1, Contour2, ... (rename it in the Browser)
        self.setup = QComboBox(self)
        self.setup.hide()
        for st in s.win.doc.setups:
            if st["type"] in self.FIELDS[kind]:
                self.setup.addItem(f"{st['name']} · {cam.TYPES[st['type']]}", st["id"])
        self.name = QLabel("", self)
        self.name.hide()
        self.boxes = {}
        self.groups = {}
        self.direction = QComboBox()
        for label, key in self.DIRECTIONS.get(kind, []):
            self.direction.addItem(label, key)
        self.direction.currentIndexChanged.connect(s.preview)
        self.output = QComboBox()                # turning: G01 lines or a canned cycle (G72 / G71)
        for key, label in (cam.ROUGH_OUTPUT if kind == "rough" else cam.TURN_OUTPUT).items():
            self.output.addItem(label, key)
        self.output.currentIndexChanged.connect(s.preview)
        self.g70 = QCheckBox("")                 # turning Contour: G70 (on the rough's G71 blocks) or lines
        self.g70.setToolTip("On: G70 P Q over the contour of a Roughing (G71) earlier in this setup.\n"
                            "Off: every move line by line (G01).")
        self.g70.toggled.connect(s.preview)
        self.internal = QCheckBox("")            # turning Roughing / Contour: OD (off) or ID / bore (on)
        self.internal.setToolTip("Off: the outside (OD).\nOn: the inside - bore the ID from the drilled hole out.")
        self.internal.toggled.connect(s.internal_changed)
        self.side = QComboBox()                  # Groove: on the OD, in the bore or in the front face
        for k, label in cam.GROOVE_SIDES.items():
            self.side.addItem(label, k)
        self.side.currentIndexChanged.connect(s.side_changed)
        self.cycles = {}                         # Drill: G81 / G83 (/ G73 on a mill), one box per setup type
        for stype, keys in ((cam.MILLING, list(cam.DRILL_CYCLES)), (cam.TURNING, list(cam.TURN_DRILL_CYCLES))):
            cb = QComboBox()
            for k in keys:
                cb.addItem(cam.DRILL_CYCLES[k], k)
            cb.currentIndexChanged.connect(s.preview)
            self.cycles[stype] = cb
        self.sfm = {}                            # SFM box next to each RPM box, per setup type
        self.tools = {}                          # the Tool box (from the tool library), per setup type
        for stype in self.FIELDS[kind]:
            cb = QComboBox()
            cb.setMinimumWidth(200)
            cb.currentIndexChanged.connect(partial(s.tool_changed, stype))
            cb._right = _RightClick(cb.view().viewport(), partial(s.tool_menu, stype))   # right-click: Edit
            self.tools[stype] = cb
        self.ends = {}                           # turning rough / contour: Start / End (cursor) + Extend
        for which, key in (("start", "start_ext"), ("end", "past_back")) if kind in ("rough", "finish", "drill", "groove") else ():
            w = QWidget()
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)
            pick = QToolButton()
            pick.setObjectName("pickBtn")
            pick.setCheckable(True)
            pick.setIconSize(QSize(16, 16))
            pick.setFixedSize(30, 24)
            pick.toggled.connect(partial(s.set_picking, which))
            pick.setContextMenuPolicy(Qt.CustomContextMenu)
            pick.customContextMenuRequested.connect(partial(s.clear_end, which))
            ext = NumBox(0, 4)
            ext.setRange(0, 100000)
            ext.valueChanged.connect(s.preview)
            ext.setToolTip("Run the toolpath this much further " + ("ahead of the start" if which == "start"
                                                                    else "past the end"))
            self.boxes[(cam.TURNING, key)] = ext
            hl.addWidget(pick)
            hl.addStretch()
            hl.addWidget(QLabel("Extend"))
            hl.addWidget(ext)
            self.ends[which] = (w, pick)
        # 2D Contour / mill Roughing: pick the part's walls (or sketch shapes) to work on
        self.geo_rows = {}
        for which, tip in (("geo", "Click, then click the walls to work on (the hub, the outside...). Again drops one.\n"
                                    "Right-click: none picked (2D Contour: the whole outline)."),
                           ("boundary", "Click, then click a sketch shape (or a pocket wall) to keep the tool inside.\n"
                                         "Right-click: back to the stock.")):
            w = QWidget()
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)
            b = QToolButton()
            b.setObjectName("pickBtn")
            b.setCheckable(True)
            b.setIconSize(QSize(16, 16))
            b.setFixedSize(30, 24)
            b.setIcon(icons.icon("cursor", theme.FG2))
            b.setToolTip(tip)
            b.toggled.connect(partial(s.set_geo_pick, which))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(partial(s.clear_geo, which))
            lb = QLabel("")
            lb.setStyleSheet(f"color:{theme.FG};")
            hl.addWidget(b)
            hl.addStretch()
            hl.addWidget(lb)
            self.geo_rows[which] = (w, b, lb)
        self.holes = QComboBox()                 # Drill (mill): which hole size, found in the model
        self.holes.currentIndexChanged.connect(s.holes_changed)
        self.hole_btn = QToolButton()            # ... or click the holes themselves in the view
        self.hole_btn.setObjectName("pickBtn")
        self.hole_btn.setCheckable(True)
        self.hole_btn.setIconSize(QSize(16, 16))
        self.hole_btn.setFixedSize(30, 24)
        self.hole_btn.setIcon(icons.icon("cursor", theme.FG2))
        self.hole_btn.setToolTip("Select holes: click a hole to pick it, click it again to drop it.\n"
                                 "Only the picked holes are drilled. Pick a size in the list to go back.")
        self.hole_btn.toggled.connect(s.set_hole_pick)
        self.holes_row = QWidget()
        hl = QHBoxLayout(self.holes_row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        hl.addWidget(self.hole_btn)
        hl.addWidget(self.holes)
        for stype, fields in self.FIELDS[kind].items():
            g = QWidget()
            lay = QVBoxLayout(g)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            items = []
            for key, label, dec in fields:
                nb = NumBox(0, dec)
                nb.setRange(0, 100000)
                nb.valueChanged.connect(s.preview)
                self.boxes[(stype, key)] = nb
                if key == "rpm":                 # RPM and SFM side by side, each works out the other
                    sfm = NumBox(0, 0)
                    sfm.setRange(0, 100000)
                    sfm.setFixedWidth(64)
                    nb.setFixedWidth(64)
                    sfm.setToolTip("Surface speed (ft/min) at the tool's diameter. Type one, the other follows.")
                    nb.valueChanged.connect(partial(s.rpm_changed, stype))
                    sfm.valueChanged.connect(partial(s.sfm_changed, stype))
                    self.sfm[stype] = sfm
                    w = QWidget()
                    hl = QHBoxLayout(w)
                    hl.setContentsMargins(0, 0, 0, 0)
                    hl.setSpacing(4)
                    hl.addWidget(nb)
                    hl.addWidget(QLabel("SFM"))
                    hl.addWidget(sfm)
                    items.append(("RPM", w))
                    continue
                items.append((label, nb))
            if kind == "drill":
                items.insert(0, ("Cycle", self.cycles[stype]))
                if stype == cam.MILLING:
                    items.insert(0, ("Holes", self.holes_row))
            elif stype == cam.MILLING:
                items.insert(3, ("Cut direction", self.direction))
            elif kind in ("face", "rough"):
                items.append(("Output", self.output))
            elif kind == "finish":
                items.append(("Use G70 cycle", self.g70))
            if stype == cam.TURNING and (kind in ("rough", "finish", "groove") or kind == "drill"):
                items[0:0] = [("Start", self.ends["start"][0]), ("End", self.ends["end"][0])]
            if kind == "groove":
                items.insert(0, ("Groove", self.side))
            if kind in ("rough", "finish") and stype == cam.TURNING:
                items.insert(0, ("Internal (ID)", self.internal))
            if stype == cam.MILLING and kind in ("contour", "rough"):
                items[0:0] = [("Geometry", self.geo_rows["geo"][0])] + \
                    ([("Boundary", self.geo_rows["boundary"][0])] if kind == "rough" else [])
            items.insert(0, ("Tool", self.tools[stype]))
            for label, w in items:
                r = QWidget()
                r.setObjectName("panelRow")
                hl = QHBoxLayout(r)
                hl.setContentsMargins(10, 4, 10, 4)
                hl.addWidget(QLabel(label))
                hl.addStretch() if label not in ("Start", "End") else None
                hl.addWidget(w, 1 if label in ("Start", "End") else 0)
                lay.addWidget(r)
            self.v.addWidget(g)
            self.groups[stype] = g
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setStyleSheet(f"color:{theme.FG2};padding:4px 10px;")
        self.v.addWidget(self.info)
        _dlg_footer(self, s)
        self.setup.currentIndexChanged.connect(s.setup_changed)

    fit = SetupPanel.fit


class OpSession:
    """CAM → Face / 2D Contour: pick the setup, set the cut, see the toolpath. Also edits an op."""
    captures_left = False
    wants_any_click = True                   # picks on screen (holes, Start / End), whatever the view

    def __init__(self, win, setup_id: str | None, kind: str = "face", edit_id: str | None = None):
        self.win, self.vp = win, win.viewport
        self.edit_id = edit_id
        op = None
        if edit_id:
            st, op = win.doc.op(edit_id)
            setup_id, kind = st["id"], op.get("type", "face")
        self.kind = kind
        self.panel = OpPanel(self, kind)
        p = self.panel
        self._loading = True
        if edit_id:
            p.setup.setEnabled(False)          # an op stays in its setup
        p.setup.setCurrentIndex(max(0, p.setup.findData(setup_id)))
        self._loading = False
        self.setup_changed(op=op)

    def current_setup(self):
        return self.win.doc.setup(self.panel.setup.currentData())

    def setup_changed(self, *_, op=None):
        p = self.panel
        st = self.current_setup()
        op = op or cam.new_op(st, self.kind)
        self._loading = True
        for (stype, key), box in p.boxes.items():
            if stype == st["type"] and key in op:
                box.setValue(op[key])
        if "direction" in op:
            p.direction.setCurrentIndex(max(0, p.direction.findData(op["direction"])))
        self.start_at, self.end_at = op.get("start_at"), op.get("end_at")
        if st["type"] == cam.TURNING and self.kind in ("rough", "finish", "groove", "drill"):
            self.show_ends()
        if self.kind == "groove":
            p.side.setCurrentIndex(max(0, p.side.findData(op.get("side", "od"))))
            self.show_end_rows()
        if self.kind == "drill":
            cb = p.cycles[st["type"]]
            cb.setCurrentIndex(max(0, cb.findData(op["cycle"])))
            p.holes.clear()
            sizes = sorted({h["dia"] for h in setup_holes(self.win, st) if h["axis"][2] > 1 - 1e-6})
            p.holes.addItem("All holes", 0.0)
            for d in sizes:
                p.holes.addItem(f"Ø{d:.4f}", d)
            want = op.get("hole_dia", 0.0) if op.get("id") else (sizes[0] if sizes else 0.0)
            p.holes.setCurrentIndex(max(0, p.holes.findData(want)))
            self.picked_holes = [list(q) for q in op.get("picked") or []]
            self.show_picked()
            if not op.get("id") and want and st["type"] == cam.MILLING:
                op = self._drill_for(st, op, want)
        self.fill_tools(st, op)
        self.rpm_changed(st["type"])
        if "output" in op:
            p.output.setCurrentIndex(max(0, p.output.findData(op["output"])))
            p.g70.setChecked(op["output"] == "cycle")
        if self.kind in ("rough", "finish") and st["type"] == cam.TURNING:
            p.internal.setChecked(bool(op.get("internal")))
            self.show_bore_row()
        self.geo = [dict(c) for c in (op.get("islands") if self.kind == "rough" else op.get("chains")) or []]
        self.bnd = dict(op["boundary"]) if op.get("boundary") else None
        if st["type"] == cam.MILLING and self.kind in ("contour", "rough"):
            self.show_geo()
        p.name.setText(op.get("name", cam.next_name(cam.OP_TYPES[self.kind], {o["name"] for o in st.get("ops", [])})))
        self._loading = False
        for stype, g in p.groups.items():
            g.setVisible(stype == st["type"])
        p.fit()
        self.vp.set_side(p)
        self.preview()

    # ---- the Tool box: tools from the library that fit this op (+ "New tool…")
    def fill_tools(self, st, op):
        """List the library tools for this op and select the one it uses. A tool that isn't in
        the library (deleted, or from an older file) stays listed as it is, so nothing changes
        until another tool is picked."""
        cb = self.panel.tools[st["type"]]
        lib = self.win.tool_lib
        self._own_tool = None
        cb.blockSignals(True)
        cb.clear()
        for t in tools.choices(lib, st["type"], self.kind):
            cb.addItem(tools.describe(t), t["id"])
        hit = tools.find(lib, op, st["type"], self.kind)
        if hit is None and "tool" in op:
            self._own_tool = {"number": int(op["tool"]), "dia": op.get("tool_dia", 0.0),
                              "name": op.get("tool_name", "not in library")}
            cb.insertItem(0, tools.describe(self._own_tool) + " (not in library)", "__own__")
        cb.addItem("New tool…", OpPanel.NEW_TOOL)
        cb.setCurrentIndex(max(0, cb.findData(hit["id"] if hit else "__own__")))
        cb.blockSignals(False)

    def tool(self, st):
        """The picked tool as a library-style dict."""
        cb = self.panel.tools[st["type"]]
        d = cb.currentData()
        if d == "__own__":
            return self._own_tool
        return next((t for t in self.win.tool_lib if t["id"] == d), None)

    def tool_changed(self, stype, *_):
        cb = self.panel.tools[stype]
        if cb.currentData() == OpPanel.NEW_TOOL:
            st = self.current_setup()
            keep = self.op()
            self.win.open_tool_library(st["type"], tools.FITS[(st["type"], self.kind)][0])
            self.fill_tools(st, keep)            # the new tool (if one was made) shows in the list
            new = [t for t in tools.choices(self.win.tool_lib, st["type"], self.kind)
                   if t["id"] == getattr(self.win, "last_new_tool", None)]
            if new:
                cb.setCurrentIndex(cb.findData(new[0]["id"]))
        self.rpm_changed(stype)                  # same RPM, new Ø: its SFM
        self.preview()

    # ---- RPM <-> SFM through the tool's diameter: SFM = RPM x pi x D / 12
    _sfm_busy = False

    def _dia(self, stype):
        t = self.tool(self.current_setup()) if self.current_setup()["type"] == stype else None
        return (t or {}).get("dia") or 0.0

    def rpm_changed(self, stype, *_):
        """RPM typed (or loaded): show the SFM it gives at this tool's diameter."""
        box = self.panel.sfm.get(stype)
        d = self._dia(stype)
        if box is None or self._sfm_busy or d <= 0:
            return
        self._sfm_busy = True
        box.setValue(self.panel.boxes[(stype, "rpm")].value() * math.pi * d / 12)
        self._sfm_busy = False

    def sfm_changed(self, stype, *_):
        """SFM typed: work out the RPM for it."""
        d = self._dia(stype)
        if self._sfm_busy or d <= 0:
            return
        self._sfm_busy = True
        self.panel.boxes[(stype, "rpm")].setValue(round(self.panel.sfm[stype].value() * 12 / (math.pi * d)))
        self._sfm_busy = False
        self.preview()

    def show_bore_row(self):
        """The drilled hole Ø only matters for an ID."""
        box = self.panel.boxes.get((cam.TURNING, "bore_dia"))
        if box is not None:
            box.parentWidget().setVisible(self.panel.internal.isChecked())
            self.panel.fit()

    def show_end_rows(self):
        """Groove: Start / End limit OD and ID grooves along Z; a face groove has none."""
        on = self.panel.side.currentData() != "face"
        for which in ("start", "end"):
            self.panel.ends[which][0].parentWidget().setVisible(on)
        self.panel.fit()

    def side_changed(self, *_):
        self.show_end_rows()
        self.preview()

    def internal_changed(self, *_):
        self.show_bore_row()
        self.preview()

    def tool_menu(self, stype, pos):
        """Right-click a tool in the open Tool list: Edit tool… opens it in the Tool Library."""
        cb = self.panel.tools[stype]
        idx = cb.view().indexAt(pos)
        tid = idx.data(Qt.UserRole) if idx.isValid() else None
        t = next((t for t in self.win.tool_lib if t["id"] == tid), None)
        if t is None:
            return
        m = QMenu(cb.view())
        act = m.addAction(f"Edit {tools.describe(t)}…")
        if m.exec(cb.view().viewport().mapToGlobal(pos)) is not act:
            return
        cb.hidePopup()
        self.edit_tool(stype, t["id"])

    def edit_tool(self, stype, tid):
        st = self.current_setup()
        keep = self.op()
        self.win.open_tool_library(st["type"], select=tid)
        t = next((t for t in self.win.tool_lib if t["id"] == tid), None)
        if t is not None:
            keep = tools.apply(keep, t)            # the op picks up the edited number / size
        self.fill_tools(st, keep)
        cb = self.panel.tools[stype]
        if cb.findData(tid) >= 0:
            cb.setCurrentIndex(cb.findData(tid))   # the edited tool, with its new sizes
        self.rpm_changed(stype)
        self.preview()

    def _drill_for(self, st, op, dia):
        """A new mill Drill on a hole size: use a library drill of that size if there is one."""
        t = next((t for t in tools.choices(self.win.tool_lib, st["type"], "drill") if abs(t["dia"] - dia) < 1e-6),
                 None)
        return tools.apply(op, t) if t else op

    def op(self) -> dict:
        p = self.panel
        st = self.current_setup()
        o = {"type": self.kind, "name": p.name.text()}
        for (stype, key), box in p.boxes.items():
            if stype == st["type"]:
                o[key] = box.value()
        t = self.tool(st)
        if t is not None:
            o = tools.apply(o, t) if t is not self._own_tool else \
                {**o, "tool": t["number"], "tool_name": t["name"], **({"tool_dia": t["dia"]} if t["dia"] else {})}
        if st["type"] == cam.MILLING:
            o["direction"] = p.direction.currentData()
        elif self.kind in ("face", "rough"):
            o["output"] = p.output.currentData()
        elif self.kind == "finish":
            o["output"] = "cycle" if p.g70.isChecked() else "lines"
        if st["type"] == cam.TURNING and self.kind in ("rough", "finish", "groove", "drill"):
            o["start_at"], o["end_at"] = self.start_at, self.end_at
        if self.kind == "groove":
            o["side"] = p.side.currentData()
        if self.kind in ("rough", "finish") and st["type"] == cam.TURNING:
            o["internal"] = p.internal.isChecked()
        if st["type"] == cam.MILLING and self.kind == "rough":
            o["islands"], o["boundary"] = [dict(c) for c in self.geo], (dict(self.bnd) if self.bnd else None)
        if st["type"] == cam.MILLING and self.kind == "contour":
            o["chains"] = [dict(c) for c in self.geo]
        if self.kind == "drill":
            o["cycle"] = p.cycles[st["type"]].currentData()
            o["hole_dia"] = (p.holes.currentData() or 0.0) if st["type"] == cam.MILLING else 0.0
            if p.holes.currentData() == "picked":
                o["hole_dia"] = 0.0
            o["picked"] = [list(q) for q in self.picked_holes] if st["type"] == cam.MILLING else []
        return o

    # ---- 2D Contour / mill Roughing: pick the part's walls (islands) and a boundary in the view
    geo: list = []
    bnd = None
    geo_pick = None

    def _cands(self):
        """Everything pickable: the part's walls level by level (kernel.slice_chains) and the
        closed shapes of the XY sketches (sketch=True, at their plane)."""
        st = self.current_setup()
        bodies = setup_bodies(self.win, st)
        key = ("chains", tuple(b.id for b in bodies))
        cache = self.win.cam_cache
        if key not in cache:
            cache[key] = slice_chains(bodies) if bodies else []
        out = list(cache[key])
        regions, planes = regions_for(self.win.doc)
        for r in regions:
            fr = planes.get(r.sketch)
            if fr is None or not pl.is_xy(fr):
                continue
            z = fr["origin"][2]
            out.append({"pts": [[x + fr["origin"][0], y + fr["origin"][1]] for x, y in r.outer.pts],
                        "z0": z, "z1": z, "hole": False, "sketch": True})
        return out

    @staticmethod
    def _same(a, b) -> bool:
        if a is None or b is None or len(a["pts"]) != len(b["pts"]) or bool(a.get("sketch")) != bool(b.get("sketch")):
            return False
        return abs(a["z0"] - b["z0"]) < 1e-6 and all(math.dist(p, q) < 1e-6 for p, q in zip(a["pts"], b["pts"]))

    def show_geo(self):
        p = self.panel
        n = len(self.geo)
        none = "whole outline" if self.kind == "contour" else "none (pick)"
        p.geo_rows["geo"][2].setText(f"{n} picked" if n else none)
        p.geo_rows["geo"][1].setIcon(icons.icon("cursor", theme.ACCENT if n else theme.FG2))
        if self.kind == "rough":
            b = self.bnd
            p.geo_rows["boundary"][2].setText("Stock" if b is None else ("Sketch shape" if b.get("sketch") else "Part wall"))
            p.geo_rows["boundary"][1].setIcon(icons.icon("cursor", theme.ACCENT if b else theme.FG2))

    def set_geo_pick(self, which, on: bool):
        if on:
            other = self.panel.geo_rows["boundary" if which == "geo" else "geo"][1]
            other.blockSignals(True)
            other.setChecked(False)
            other.blockSignals(False)
            self.geo_pick = which
            self.win.message("PICK " + ("WALLS: click the part's walls (or a sketch shape), again to drop one"
                                        if which == "geo" else "BOUNDARY: click a sketch shape or a pocket wall")
                             + " · Esc stops")
        elif self.geo_pick == which:
            self.geo_pick = None
            self.vp.dim.hide()
        self.preview()

    def clear_geo(self, which, *_):
        if which == "geo":
            self.geo = []
        else:
            self.bnd = None
        self.show_geo()
        self.preview()

    def _geo_under(self, ev, tol=10.0):
        """The pickable outline nearest the cursor on screen (drawn at its top), within tol px."""
        best, hit = tol, None
        p = np.array([ev.position().x(), ev.position().y()])
        for c in self._cands():
            q = self.vp.project([[x, y, c["z1"]] for x, y in c["pts"] + c["pts"][:1]])[:, :2]
            a, b = q[:-1], q[1:]
            ab = b - a
            L = (ab ** 2).sum(1)
            t = np.clip(((p - a) * ab).sum(1) / np.where(L > 0, L, 1), 0, 1)
            d = float(np.min(np.hypot(*(a + ab * t[:, None] - p).T)))
            if d < best:
                best, hit = d, c
        return hit

    def draw_geo(self):
        def ring(c, dz=0.003):
            return [[x, y, c["z1"] + dz] for x, y in c["pts"] + c["pts"][:1]]
        if self.geo_pick:
            self.vp.add_lines("op", [ring(c) for c in self._cands()], theme.FG2, 1.2, opacity=0.7)
        if self.geo:
            self.vp.add_lines("op", [ring(c, 0.005) for c in self.geo], theme.ACCENT, 3.0)
        if self.bnd:
            self.vp.add_lines("op", [ring(self.bnd, 0.005)], theme.WARN, 3.0)

    # ---- Drill (mill): click holes in the view to pick / drop them
    picked_holes: list = []
    hole_pick = False

    def show_picked(self):
        """The Holes list says "N picked" while holes are picked (a size / All holes clears them)."""
        cb = self.panel.holes
        cb.blockSignals(True)
        k = cb.findData("picked")
        if self.picked_holes:
            text = f"{len(self.picked_holes)} picked"
            if k < 0:
                cb.insertItem(0, text, "picked")
                k = 0
            cb.setItemText(k, text)
            cb.setCurrentIndex(k)
        elif k >= 0:
            cb.removeItem(k)
        cb.blockSignals(False)
        self.panel.hole_btn.setIcon(icons.icon("cursor", theme.ACCENT if self.picked_holes else theme.FG2))

    def set_hole_pick(self, on: bool):
        self.hole_pick = on
        if on:
            self.win.message("SELECT HOLES: click a hole to pick it, again to drop it · Esc or the button stops")
        else:
            self.vp.dim.hide()
        self.preview()

    def _hole_under(self, ev):
        """The mill-able hole (opening up +Z) nearest the cursor on screen, within 18 px."""
        holes = [h for h in setup_holes(self.win, self.current_setup()) if h["axis"][2] > 1 - 1e-6]
        if not holes:
            return None
        xy = self.vp.project([h["p"] for h in holes])[:, :2]
        p = ev.position()
        d = np.hypot(xy[:, 0] - p.x(), xy[:, 1] - p.y())
        k = int(np.argmin(d))
        if d[k] > 18:                            # or inside its circle on screen
            r = self.vp.project([np.add(holes[k]["p"], (holes[k]["dia"] / 2, 0, 0))])[0, :2]
            if d[k] > np.hypot(*(r - xy[k])) + 4:
                return None
        return holes[k]

    def _is_picked(self, h):
        return any(math.dist(h["p"], q) < 1e-4 for q in self.picked_holes)

    def draw_holes(self, st):
        """Rings on the holes while selecting: picked blue, the rest grey."""
        if not (self.hole_pick or self.picked_holes):
            return
        rings_on, rings_off = [], []
        for h in setup_holes(self.win, st):
            if h["axis"][2] < 1 - 1e-6:
                continue
            r = h["dia"] / 2 + 0.03
            ring = [[h["p"][0] + r * math.cos(a * math.pi / 24), h["p"][1] + r * math.sin(a * math.pi / 24),
                     h["p"][2] + 0.002] for a in range(49)]
            (rings_on if self._is_picked(h) else rings_off).append(ring)
        if rings_off and self.hole_pick:
            self.vp.add_lines("op", rings_off, theme.FG2, 1.4, opacity=0.8)
        if rings_on:
            self.vp.add_lines("op", rings_on, theme.ACCENT, 2.6)

    def holes_changed(self, *_):
        """Picking a hole size picks a library drill of that size (when there is one)."""
        d = self.panel.holes.currentData()
        if d == "picked":
            return
        if not self._loading and self.picked_holes:          # a size / All holes: picks are dropped
            self.picked_holes = []
            self.show_picked()
        if not self._loading and d:
            st = self.current_setup()
            op = self._drill_for(st, self.op(), d)
            self._loading = True
            self.fill_tools(st, op)
            self._loading = False
            self.rpm_changed(st["type"])
        self.preview()

    def preview(self, *_):
        if self._loading:
            return
        st = self.current_setup()
        self.vp.clear("cam", render=False)
        self.vp.clear("op", render=False)
        draw_setup(self.vp, self.win, st, "op")
        try:
            moves, world = op_moves(self.win, st, self.op())
        except ValueError as exc:
            self.panel.info.setText(str(exc))
            if self.kind == "drill" and st["type"] == cam.MILLING:
                self.draw_holes(st)              # (rings to pick from, even with nothing to drill yet)
            if st["type"] == cam.MILLING and self.kind in ("contour", "rough"):
                self.draw_geo()
            self.vp.render()
            return
        draw_toolpath(self.vp, world, "op")
        if self.kind in ("rough", "finish") and st["type"] == cam.TURNING:
            self.draw_ends(st, self.op())
        if st["type"] == cam.MILLING and self.kind in ("contour", "rough"):
            self.draw_geo()
        if self.kind == "drill" and st["type"] == cam.MILLING:
            self.draw_holes(st)
        zs = {round(p[2], 6) for k, p in moves if k == "feed"} if st["type"] == cam.MILLING else \
            {i for i, (k, _p) in enumerate(moves) if k == "feed" and moves[i - 1][0] == "rapid"}   # facing cuts
        t = cam.cycle_time(moves, st, self.op())
        n = len(zs)
        if self.kind == "drill":
            n = len({p[:2] for k, p in moves if k == "feed"}) if st["type"] == cam.MILLING else 1
            self.panel.info.setText(f"{n} hole{'s' if n != 1 else ''} · about {t:.1f} min cutting")
        elif self.kind == "groove":
            n = sum(1 for i, (k, _p) in enumerate(moves) if k == "feed" and moves[i - 1][0] == "rapid"
                    and (i < 2 or moves[i - 2][0] != "feed"))
            self.panel.info.setText(f"{n} plunge{'s' if n != 1 else ''} · about {t:.1f} min cutting")
        elif self.kind == "finish":
            self.panel.info.setText(f"1 finish pass along the profile · about {t:.1f} min cutting")
        elif self.kind == "rough" and st["type"] == cam.MILLING:
            self.panel.info.setText(f"{n} depth{'s' if n != 1 else ''} · about {t:.1f} min cutting")
        elif self.kind == "rough":
            self.panel.info.setText(f"{n - 1} roughing pass{'es' if n != 2 else ''} + profile pass · about {t:.1f} min "
                                    "cutting")
        else:
            self.panel.info.setText(f"{n} depth pass{'es' if n != 1 else ''} · about {t:.1f} min cutting")
        word = self.panel.title.text()
        self.win.message(f"{word}: blue = cutting, yellow = rapid · change values to update · Enter / OK saves · "
                         "Esc cancels")
        self.vp.render()

    def commit(self):
        st = self.current_setup()
        try:
            cam.validate_op(st, self.op())
        except ValueError as exc:
            self.vp.show_toast(str(exc), bad=True)
            return
        self.win.commit_op(st["id"], self.op(), self.edit_id)

    def draw_ends(self, st, op):
        """A ring around the bar at the Start and End (with their extensions): where the path runs."""
        bodies = setup_bodies(self.win, st)
        if not bodies:
            return
        bb = bodies_bbox(bodies)
        rad = turning_radius(self.win, st, bodies)
        i, center, _ = cam.turning_frame(bb, st)
        r = cam.stock_cylinder(bb, rad, st)["r"] + 0.08
        w = cam.wcs(bb, st, rad)
        sign = 1.0 if st["front"] == "+" else -1.0
        u, v = [k for k in range(3) if k != i]
        rings = []
        for z in cam.toolpath_limits(bb, st, op, rad):
            a = w["origin"][i] + z * sign
            ring = []
            for k in range(49):
                p = list(center)
                p[i] = a
                p[u] += r * math.cos(k * math.pi / 24)
                p[v] += r * math.sin(k * math.pi / 24)
                ring.append(p)
            rings.append(ring)
        self.vp.add_lines("op", rings, theme.FG, 1.6, opacity=0.9)

    # ---- turning Start / End: pick an edge or end point of the part
    picking = None

    def show_ends(self):
        """The cursor buttons: blue once a Start / End is picked; the tooltip says where."""
        st = self.current_setup()
        bodies = setup_bodies(self.win, st)
        for which in ("start", "end"):
            v = self.start_at if which == "start" else self.end_at
            btn = self.panel.ends[which][1]
            home = (("the hole's top", "the hole's bottom (or Depth)") if self.kind == "drill" else
                    ("the part's front face", "the part's back end"))[which == "end"]
            if v is None or not bodies:
                where = home
            else:
                where = f"Z{cam.axial_to_wcs(bodies_bbox(bodies), st, v, turning_radius(self.win, st, bodies)):.4f}"
            btn.setIcon(icons.icon("cursor", theme.ACCENT if v is not None else theme.FG2))
            btn.setToolTip(f"{which.capitalize()}: {where}\nClick, then click an edge or end point of the part."
                           f"\nRight-click: back to {home}")

    def set_picking(self, which, on: bool):
        if on:
            other = self.panel.ends["end" if which == "start" else "start"][1]
            other.blockSignals(True)
            other.setChecked(False)
            other.blockSignals(False)
            self.edges = edge_list(setup_bodies(self.win, self.current_setup()))
            self.picking = which
            self.win.message(f"PICK {which.upper()}: click an edge or end point of the part · Esc stops picking")
        elif self.picking == which:
            self.picking = None
            self.vp.clear("pick")
            self.vp.dim.hide()
        self.show_ends()

    def clear_end(self, which, *_):
        setattr(self, "start_at" if which == "start" else "end_at", None)
        self.show_ends()
        self.preview()

    def _axial(self, ev):
        """(edge index, model coordinate along the spindle axis) under the cursor."""
        i, w = edge_at(self.vp, self.edges, ev.position(), 8)
        if i is None:
            return None, None
        return i, w[cam.AXES[self.current_setup()["axis"]]]

    def on_move(self, w, ev):
        if self.geo_pick and not ev.buttons():
            c = self._geo_under(ev)
            if c is None:
                self.vp.dim.hide()
            else:
                what = "sketch shape" if c.get("sketch") else ("pocket wall" if c["hole"] else "wall") + \
                    f" Z{c['z0']:.3f}–{c['z1']:.3f}"
                self.vp.show_dim(what, ev.position().toPoint())
            return
        if self.hole_pick and not ev.buttons():
            h = self._hole_under(ev)
            if h is None:
                self.vp.dim.hide()
            else:
                self.vp.show_dim(f"Ø{h['dia']:.4f} · click to {'drop' if self._is_picked(h) else 'pick'}",
                                 ev.position().toPoint())
            return
        if not self.picking or ev.buttons():
            return
        i, a = self._axial(ev)
        self.vp.clear("pick", render=False)
        if i is not None:
            self.vp.add_lines("pick", [self.edges[i]["pts"]], theme.FG, 3.0)
            st = self.current_setup()
            bodies = setup_bodies(self.win, st)
            z = cam.axial_to_wcs(bodies_bbox(bodies), st, a, turning_radius(self.win, st, bodies))
            self.vp.show_dim(f"{self.picking.upper()} Z{z:.4f}", ev.position().toPoint())
        else:
            self.vp.dim.hide()
        self.vp.render()

    def on_click(self, w, ev):
        if self.geo_pick:
            c = self._geo_under(ev)
            if c is None:
                return
            if self.geo_pick == "boundary":
                self.bnd = None if self._same(c, self.bnd) else dict(c)
                self.panel.geo_rows["boundary"][1].setChecked(False)
            elif any(self._same(c, g) for g in self.geo):
                self.geo = [g for g in self.geo if not self._same(c, g)]
            else:
                self.geo = self.geo + [dict(c)]
            self.show_geo()
            self.preview()
            return
        if self.hole_pick:
            h = self._hole_under(ev)
            if h is None:
                return
            if self._is_picked(h):
                self.picked_holes = [q for q in self.picked_holes if math.dist(h["p"], q) >= 1e-4]
            else:
                self.picked_holes = self.picked_holes + [list(h["p"])]
                if len(self.picked_holes) == 1:                   # first pick: a drill that size
                    st = self.current_setup()
                    self._loading = True
                    self.fill_tools(st, self._drill_for(st, self.op(), h["dia"]))
                    self._loading = False
                    self.rpm_changed(st["type"])
            self.show_picked()
            self.preview()
            return
        if not self.picking:
            return
        i, a = self._axial(ev)
        if i is None:
            return
        which = self.picking
        setattr(self, "start_at" if which == "start" else "end_at", a)
        self.panel.ends[which][1].setChecked(False)
        self.show_ends()
        self.preview()

    def on_key(self, ev) -> bool:
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.commit()
            return True
        if ev.key() == Qt.Key_Escape:
            if self.geo_pick:
                self.panel.geo_rows[self.geo_pick][1].setChecked(False)
            elif self.hole_pick:
                self.panel.hole_btn.setChecked(False)
            elif self.picking:
                self.panel.ends[self.picking][1].setChecked(False)
            else:
                self.win.cancel_command()
            return True
        return False

    def ribbon_tool(self, label):
        self.win.cancel_command()
        self.win.run_tool(label)

    def close(self):
        self.vp.clear("op", render=False)
        self.vp.clear("pick", render=False)
        self.vp.dim.hide()


# ------------------------------------------------------------------ simulate
class SimPanel(Panel):
    SPEEDS = [1, 2, 5, 10, 25, 100]

    def __init__(self, session: "SimSession", what: str):
        super().__init__("Simulate", 300)
        s = session
        self.row("Toolpath", self.value(what))
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 6, 10, 4)
        self.play = QPushButton("▶  PLAY")
        self.play.setObjectName("dlgBtn")
        self.play.setProperty("ok", True)
        self.play.clicked.connect(s.toggle)
        restart = QPushButton("⏮")
        restart.setObjectName("dlgBtn")
        restart.setToolTip("Back to the start")
        restart.clicked.connect(lambda: s.seek(0.0))
        self.speed = QComboBox()
        for x in self.SPEEDS:
            self.speed.addItem(f"{x}×", x)
        self.speed.setCurrentIndex(3)
        bl.addWidget(restart)
        bl.addWidget(self.play, 1)
        bl.addWidget(self.speed)
        self.v.addWidget(bar)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(lambda v: s.seek(v / 1000 * s.total))
        sw = QWidget()
        sl = QHBoxLayout(sw)
        sl.setContentsMargins(10, 2, 10, 2)
        sl.addWidget(self.slider)
        self.v.addWidget(sw)
        self.at = self.row("Tool at", self.value(""))
        self.step = self.row("Move", self.value(""))
        self.time = self.row("Time", self.value(""))
        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(10, 6, 10, 6)
        fl.addStretch()
        close = QPushButton("CLOSE")
        close.setObjectName("dlgBtn")
        close.clicked.connect(s.win.cancel_command)
        fl.addWidget(close)
        self.v.addWidget(foot)


class SimSession:
    """Plays an operation's (or a whole setup's) toolpath: the tool rides the path at the
    programmed feeds (rapids at cam.RAPID_IPM), sped up by the chosen factor. Blue behind the
    tool = cut so far. Material removal is G-SEND.IO's simulator's job; this checks the motion."""
    captures_left = False

    def __init__(self, win, setup: dict, ops: list):
        self.win, self.vp = win, win.viewport
        self.setup = setup
        self.world, self.times, self.op_of = [], [], []
        skipped = []
        for op in ops:
            try:
                moves, world = op_moves(win, setup, op)
            except ValueError as exc:                    # an op with no toolpath: play the rest
                skipped.append(f"{op.get('name', 'op')}: {exc}")
                continue
            t = cam.move_times(moves, setup, op)
            if self.world and world:                     # rapid from the last op to the next
                t[0] = math.dist(self.world[-1][1], world[0][1]) / cam.RAPID_IPM
            self.world += world
            self.times += t
            self.op_of += [op] * len(world)
        self.cum = list(np.cumsum(self.times)) if self.times else [0.0]
        self.total = self.cum[-1] or 1e-9
        what = ops[0]["name"] if len(ops) == 1 else f"{setup['name']} · {len(ops)} ops"
        self.panel = SimPanel(self, what)
        self.t = 0.0
        self.timer = QTimer()
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        self.vp.clear("cam", render=False)
        draw_setup(self.vp, win, setup, "sim")
        draw_toolpath(self.vp, self.world, "sim", dim=True)
        self.tool, self.tool_op = None, None             # each op shows its own tool (a 2" face mill
        self.vp.set_side(self.panel)                     # must not ride on into the 1/4 drill's holes)
        self.seek(0.0)
        self.win.message("SIMULATE: ▶ plays · drag the slider to scrub · Space = play / pause · Esc closes"
                         + (" · LEFT OUT: " + " · ".join(skipped) if skipped else ""))

    def _show_tool(self, op):
        """The tool of the op being played: a cylinder its diameter (mill), a ball (lathe)."""
        if op is self.tool_op and self.tool is not None:
            return
        self.vp.clear("simtool", render=False)
        if self.setup["type"] == cam.MILLING:
            dia = op.get("tool_dia", 0.5) or 0.5
            shape = pv.Cylinder(center=(0, 0, 0.75), direction=(0, 0, 1), radius=dia / 2, height=1.5,
                                resolution=32)
        else:
            shape = pv.Sphere(radius=0.05, center=(0, 0, 0))
        self.tool, self.tool_op = self.vp.add_surface("simtool", shape, theme.FG, 0.85), op

    def toggle(self):
        if self.timer.isActive():
            self.timer.stop()
        else:
            if self.t >= self.total:
                self.t = 0.0
            self.timer.start()
        self.panel.play.setText("❚❚  PAUSE" if self.timer.isActive() else "▶  PLAY")

    def tick(self):
        self.seek(self.t + 0.033 / 60 * self.panel.speed.currentData())
        if self.t >= self.total:
            self.timer.stop()
            self.panel.play.setText("▶  PLAY")

    def seek(self, t: float):
        self.t = max(0.0, min(t, self.total))
        if not self.world:
            return
        i = int(np.searchsorted(self.cum, self.t))
        i = min(max(i, 0), len(self.world) - 1)
        p1 = np.array(self.world[i][1])
        if i > 0 and self.times[i] > 0:
            p0 = np.array(self.world[i - 1][1])
            f = 1 - (self.cum[i] - self.t) / self.times[i]
            at = p0 + (p1 - p0) * min(max(f, 0.0), 1.0)
        else:
            at = p1
        self._show_tool(self.op_of[i])
        self.tool.SetPosition(*at)
        self.vp.clear("simdone", render=False)
        done = [np.array(w[1]) for w in self.world[:i]] + [at]
        feeds = [[a, b] for (a, b), k in zip(zip(done, done[1:]), [w[0] for w in self.world[1:i + 1]]) if k == "feed"]
        self.vp.add_lines("simdone", feeds, theme.ACCENT, 3.0)
        p = self.panel
        p.slider.blockSignals(True)
        p.slider.setValue(int(self.t / self.total * 1000))
        p.slider.blockSignals(False)
        kind = self.world[i][0]
        p.at.setText(f"X{at[0]:.4f} Y{at[1]:.4f} Z{at[2]:.4f}")
        p.step.setText(f"{i + 1} / {len(self.world)} · {'FEED' if kind == 'feed' else 'RAPID'} · {self.op_of[i]['name']}")
        p.time.setText(f"{self.t:.2f} / {self.total:.2f} min")
        self.vp.render()

    def on_move(self, w, ev):
        pass

    def on_click(self, w, ev):
        pass

    def on_key(self, ev) -> bool:
        if ev.key() == Qt.Key_Space:
            self.toggle()
            return True
        if ev.key() == Qt.Key_Escape:
            self.win.cancel_command()
            return True
        return False

    def ribbon_tool(self, label):
        self.win.cancel_command()
        self.win.run_tool(label)

    def close(self):
        self.timer.stop()
        for g in ("sim", "simdone", "simtool"):
            self.vp.clear(g, render=False)
