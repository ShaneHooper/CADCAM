"""Interactive commands: Sketch mode and Extrude (with their right-hand panels).

Each session receives mouse events from the Viewport (`on_move`, `on_click`) and keys
from the main window (`on_key`). They edit the Document only when committed.
"""
from __future__ import annotations

import numpy as np
import pyvista as pv
from PySide6.QtCore import Qt
from functools import partial

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QToolButton, QVBoxLayout, QWidget)

from ..core import sketch as sk
from ..core.profiles import region_at, sketch_regions
from ..kernel import extrude_tool, region_face, triangles
from . import theme

TOOL_KEYS = {"Line": "line", "Rectangle": "rect", "Center Rect": "center_rect", "Circle": "circle", "Polygon": "polygon"}
HINTS = {"line": "Click start, click end. Keep clicking to chain. Esc ends the chain.",
         "rect": "Click two opposite corners.", "center_rect": "Click center, then a corner.",
         "circle": "Click center, then a point on the circle.", "polygon": "Click center, then a vertex."}


def mesh_of(shape) -> pv.PolyData:
    v, t = triangles(shape, 0.001, 0.2)
    return pv.PolyData(v, np.hstack([np.full((len(t), 1), 3), t]).ravel()) if len(t) else pv.PolyData()


class Panel(QFrame):
    """The prototype's right-hand panel: blue header, label/value rows, optional footer."""

    def __init__(self, title: str, width=230):
        super().__init__()
        self.setObjectName("panel")
        self.setFixedWidth(width)
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(0, 0, 0, 0)
        self.v.setSpacing(0)
        head = QWidget()
        head.setObjectName("panelHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(10, 5, 10, 5)
        self.title = QLabel(title.upper())
        self.title.setStyleSheet(f"color:{theme.ACCENT};font-weight:700;")
        self.count = QLabel("")
        self.count.setStyleSheet(f"color:{theme.ACCENT};")
        hl.addWidget(self.title)
        hl.addStretch()
        hl.addWidget(self.count)
        self.v.addWidget(head)

    def row(self, label: str, widget: QWidget):
        r = QWidget()
        r.setObjectName("panelRow")
        hl = QHBoxLayout(r)
        hl.setContentsMargins(10, 4, 10, 4)
        hl.addWidget(QLabel(label))
        hl.addStretch()
        hl.addWidget(widget)
        self.v.addWidget(r)
        return widget

    def value(self, text: str) -> QLabel:
        lb = QLabel(text)
        lb.setObjectName("val")
        return lb


# ------------------------------------------------------------------ sketch
class SketchPalette(Panel):
    def __init__(self, session: "SketchSession"):
        super().__init__("Edit Sketch" if session.edit_id else "Sketch Palette", 210)
        self.s = session
        self.plane = QDoubleSpinBox()
        self.plane.setRange(-100, 100)
        self.plane.setDecimals(3)
        self.plane.setSingleStep(0.25)
        self.plane.setPrefix("XY · Z ")
        self.plane.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.plane.setValue(session.plane_z)
        self.plane.valueChanged.connect(session.set_plane)
        self.row("Plane", self.plane)
        self.snap = QCheckBox("On")
        self.snap.setChecked(True)
        self.row("Grid snap", self.snap)
        self.size = QComboBox()
        for v in ("0.250", "0.125", "0.0625", "0.010"):
            self.size.addItem(f"{v} in", float(v))
        self.row("Snap size", self.size)
        self.sides = QComboBox()
        self.sides.addItems(["3", "4", "5", "6", "8"])
        self.sides.setCurrentText("6")
        self.sides.setStyleSheet("min-width: 36px;")
        self.row("Polygon sides", self.sides)
        self.list = QWidget()
        self.list.setObjectName("entList")
        self.lv = QVBoxLayout(self.list)
        self.lv.setContentsMargins(0, 0, 0, 0)
        self.lv.setSpacing(0)
        sc = QScrollArea()
        sc.setWidget(self.list)
        sc.setWidgetResizable(True)
        sc.setMaximumHeight(140)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.v.addWidget(sc)
        self.update_list([])

    def step(self) -> float:
        return self.size.currentData() if self.snap.isChecked() else 0.0

    def update_list(self, ents):
        while self.lv.count():
            w = self.lv.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.count.setText(str(len(ents)))
        if not ents:
            e = QLabel("No entities yet")
            e.setAlignment(Qt.AlignCenter)
            e.setStyleSheet(f"color:{theme.FG3};padding:3px;border-bottom:1px solid {theme.LINE};")
            self.lv.addWidget(e)
        for i, ent in enumerate(ents):
            kind, detail = sk.entity_label(ent)
            r = QWidget()
            hl = QHBoxLayout(r)
            hl.setContentsMargins(10, 3, 4, 3)
            a, b = QLabel(kind), QLabel(detail)
            a.setStyleSheet(f"color:{theme.FG2};")
            hl.addWidget(a)
            hl.addStretch()
            hl.addWidget(b)
            x = QToolButton()
            x.setObjectName("entDel")
            x.setText("×")
            x.setToolTip(f"Delete this {kind.lower()}")
            x.setFixedSize(16, 16)
            x.clicked.connect(partial(self.s.delete_ent, i))
            hl.addWidget(x)
            r.setStyleSheet(f"border-bottom:1px solid {theme.LINE};")
            self.lv.addWidget(r)
        self.lv.addStretch()


class SketchSession:
    captures_left = True

    def __init__(self, win, name: str, plane_z: float = 0.0, ents=None, edit_id: str | None = None):
        self.win, self.vp = win, win.viewport
        self.name = name
        self.plane_z = plane_z
        self.edit_id = edit_id               # set when editing a sketch that is already in the timeline
        self.ents: list = [dict(e) for e in ents or []]
        self.origin: list = list(range(len(self.ents)))   # old index of each entity; None = drawn now
        self.start = (list(self.ents), plane_z)
        self.pts: list = []
        self.tool = None
        self.palette = SketchPalette(self)
        self.vp.plane_z = plane_z
        if self.ents:
            self.redraw()

    def changed(self) -> bool:
        return (self.ents, self.plane_z) != self.start

    def delete_ent(self, i: int):
        if 0 <= i < len(self.ents):
            kind, _ = sk.entity_label(self.ents[i])
            del self.ents[i]
            del self.origin[i]
            self.redraw()
            self.vp.show_toast(f"{kind} deleted")

    def set_plane(self, z):
        self.plane_z = self.vp.plane_z = float(z)
        self.pts = []
        self.redraw()

    def set_tool(self, label: str | None):
        self.tool = TOOL_KEYS.get(label) if label else None
        self.pts = []
        self.vp.clear("preview")
        self.win.ribbon.set_active(label)
        name = label.upper() if label else "SELECT A TOOL"
        head = f"EDIT {self.name.upper()}" if self.edit_id else "SKETCH"
        self.vp.show_banner(f"{head} · XY PLANE · <span style='color:{theme.ACCENT}'>{name}</span>")
        self.win.message(HINTS.get(self.tool, "Pick a sketch tool: L line · R rectangle · C circle · P polygon · Enter finishes"))

    def _snap(self, w, ev):
        step = self.palette.step()
        if ev is not None and ev.modifiers() & Qt.ShiftModifier:
            step /= 4
        return [sk.snap(w[0], step), sk.snap(w[1], step)]

    def _lines(self, ents):
        z = self.plane_z + 0.004
        return [[(x, y, z) for x, y in sk.entity_points(e)] for e in ents]

    def redraw(self):
        self.vp.clear("sketch", render=False)
        self.vp.add_lines("sketch", self._lines(self.ents))
        self.palette.update_list(self.ents)
        self.win.refresh_tree()
        self.vp.render()

    def on_move(self, w, ev):
        p = self._snap(w, ev)
        pos = ev.position().toPoint()
        if not self.tool:
            return
        if not self.pts:
            self.vp.show_dim(f"X {sk.fmt(p[0])}  Y {sk.fmt(p[1])}", pos)
            return
        ent = sk.build_entity(self.tool, self.pts[0], p, int(self.palette.sides.currentText()))
        self.vp.clear("preview", render=False)
        if ent:
            self.vp.add_lines("preview", self._lines([ent]), opacity=0.45)
        self.vp.show_dim(sk.preview_label(self.tool, self.pts[0], p, int(self.palette.sides.currentText())), pos)
        self.vp.render()

    def on_click(self, w, ev):
        if not self.tool:
            return
        p = self._snap(w, ev)
        if not self.pts:
            self.pts = [p]
            return
        ent = sk.build_entity(self.tool, self.pts[0], p, int(self.palette.sides.currentText()))
        if ent:
            self.ents.append(ent)
            self.origin.append(None)
        self.pts = [p] if self.tool == "line" else []
        self.vp.clear("preview", render=False)
        self.redraw()

    def undo(self):
        if self.pts:
            self.pts = []
            self.vp.clear("preview")
        elif self.ents:
            self.ents.pop()
            self.origin.pop()
            self.redraw()

    def on_key(self, ev) -> bool:
        k = ev.key()
        if k == Qt.Key_Escape:
            if self.pts:
                self.pts = []
                self.vp.clear("preview")
            else:
                self.set_tool(None)
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self.win.finish_sketch()
        elif k == Qt.Key_Z and ev.modifiers() & Qt.ControlModifier:
            self.undo()
        elif k == Qt.Key_L:
            self.set_tool("Line")
        elif k == Qt.Key_R:
            self.set_tool("Rectangle")
        elif k == Qt.Key_C:
            self.set_tool("Circle")
        elif k == Qt.Key_P:
            self.set_tool("Polygon")
        else:
            return False
        return True

    def ribbon_tool(self, label: str):
        if label in TOOL_KEYS:
            self.set_tool(label)
        elif label == "Undo":
            self.undo()
        elif label == "Clear":
            self.ents, self.origin, self.pts = [], [], []
            self.vp.clear("preview", render=False)
            self.redraw()
            self.vp.show_toast("Sketch cleared")
        elif label == "Finish Sketch":
            self.win.finish_sketch()
        elif label == "Cancel":
            self.win.cancel_command()
            self.vp.show_toast("Edit discarded" if self.edit_id else "Sketch discarded")
        else:
            self.win.not_built(label)
            self.win.ribbon.set_active(None)

    def close(self):
        self.vp.clear("sketch", render=False)
        self.vp.clear("preview", render=False)
        self.vp.dim.hide()
        self.vp.show_banner(None)


# ------------------------------------------------------------------ extrude
class ExtrudePanel(Panel):
    def __init__(self, session: "ExtrudeSession"):
        super().__init__("Extrude")
        s = session
        self.prof = self.row("Profile", self.value("Select"))
        self.row("Start", self.value("Profile plane"))
        self.dir = QComboBox()
        self.dir.addItem("One side", "one")
        self.dir.addItem("Symmetric", "sym")
        self.row("Direction", self.dir)
        self.dist = QDoubleSpinBox()
        self.dist.setRange(-100, 100)
        self.dist.setDecimals(4)
        self.dist.setSingleStep(0.05)
        self.dist.setSuffix(" in")
        self.dist.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.dist.setValue(0.5)
        self.row("Distance", self.dist)
        self.op = QComboBox()
        for label, key in (("Join", "join"), ("Cut", "cut"), ("New Body", "new")):
            self.op.addItem(label, key)
        self.row("Operation", self.op)
        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(10, 6, 10, 6)
        fl.addStretch()
        cancel, ok = QPushButton("CANCEL"), QPushButton("OK")
        for b in (cancel, ok):
            b.setObjectName("dlgBtn")
            fl.addWidget(b)
        ok.setProperty("ok", True)
        cancel.clicked.connect(s.win.cancel_command)
        ok.clicked.connect(s.commit)
        self.v.addWidget(foot)
        for w in (self.dir, self.op):
            w.currentIndexChanged.connect(s.update_preview)
        self.dist.valueChanged.connect(s.update_preview)

    def set_count(self, n: int):
        self.prof.setText(f"{n} selected" if n else "Select")
        self.prof.setProperty("none", not n)
        self.prof.style().polish(self.prof)


class ExtrudeSession:
    captures_left = False       # left drag still orbits; a click picks

    def __init__(self, win, regions, planes):
        self.win, self.vp = win, win.viewport
        self.regions = regions          # [Region]
        self.planes = planes            # sketch id -> plane z
        self.sel: list = []             # selected region keys, in pick order
        self.hover = None
        self.fill_actors = {}
        self.panel = ExtrudePanel(self)
        for r in regions:
            m = mesh_of(region_face(r, self.planes[r.sketch] + 0.002))
            if m.n_points:
                a = self.vp.add_surface("fills", m, theme.ACCENT, 0.0, lit=False)
                self.fill_actors[r.key] = a
        last = regions[-1].sketch
        mine = [r for r in regions if r.sketch == last]
        if len(mine) == 1:                  # newest sketch has one region: start with it selected
            self.sel.append(mine[0].key)
        self.paint()
        self.update_preview()

    def pick(self, ev):
        best = None
        for sid, z in self.planes.items():
            w = self.vp.world_at(ev.position().toPoint(), z)
            if not w:
                continue
            r = region_at([r for r in self.regions if r.sketch == sid], w)
            if r and (best is None or r.area < best.area):
                best = r
        return best

    def paint(self):
        for key, a in self.fill_actors.items():
            a.prop.opacity = 0.45 if key in self.sel else (0.2 if self.hover and self.hover.key == key else 0.0)
        self.panel.set_count(len(self.sel))
        self.win.status.sel.setText(f"SEL: {len(self.sel)} PROFILE{'' if len(self.sel) == 1 else 'S'}")
        self.vp.render()

    def on_move(self, w, ev):
        if ev.buttons():
            return
        r = self.pick(ev)
        if r is not self.hover:
            self.hover = r
            self.vp.plotter.setCursor(Qt.PointingHandCursor if r else Qt.ArrowCursor)
            self.paint()

    def on_click(self, w, ev):
        r = self.pick(ev)
        if not r:
            return
        if r.key in self.sel:
            self.sel.remove(r.key)
        else:
            self.sel.append(r.key)
        self.paint()
        self.update_preview()

    def feature(self) -> dict:
        regs = [next(r for r in self.regions if r.key == k) for k in self.sel]
        return {"kind": "extrude", "name": "preview", "op": self.panel.op.currentData(),
                "distance": self.panel.dist.value(), "direction": self.panel.dir.currentData(),
                "profiles": [r.to_data() for r in regs]}

    def update_preview(self, *_):
        self.vp.clear("preview", render=False)
        f = self.feature()
        if f["profiles"] and abs(f["distance"]) >= 1e-4:
            try:
                tool = extrude_tool(f, self.win.doc.applied())
                col = theme.BAD if f["op"] == "cut" else theme.ACCENT
                self.vp.add_surface("preview", mesh_of(tool), col, 0.35)
                edges = [np.array([tuple(p) for p in e.positions([i / 32 for i in range(33)])]) for e in tool.edges()]
                self.vp.add_lines("preview", edges, col, 1.2)
            except Exception as exc:
                self.win.message(f"Preview failed: {exc}")
        op = self.panel.op.currentText().upper()
        n = len(self.sel)
        self.win.message(f"EXTRUDE {op} · {n} profile{'s' if n != 1 else ''} · click profiles to add or remove · "
                         "Enter = OK · Esc = cancel" if n else "EXTRUDE: click a profile to select it · Esc = cancel")
        self.vp.render()

    def commit(self):
        f = self.feature()
        if not f["profiles"]:
            self.vp.show_toast("Select a profile", bad=True)
            return
        if abs(f["distance"]) < 1e-4:
            self.vp.show_toast("Distance must not be zero", bad=True)
            return
        self.win.commit_extrude(f)

    def on_key(self, ev) -> bool:
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.commit()
            return True
        if ev.key() == Qt.Key_Escape:
            self.win.cancel_command()
            return True
        return False

    def ribbon_tool(self, label):
        self.win.cancel_command()
        self.win.run_tool(label)

    def close(self):
        self.vp.clear("fills", render=False)
        self.vp.clear("preview", render=False)
        self.vp.plotter.setCursor(Qt.ArrowCursor)


def regions_for(doc):
    """Pickable regions from every applied sketch, plus each sketch's plane height."""
    regions, planes = [], {}
    for f in doc.applied():
        if f["kind"] == "sketch" and f.get("show") is not False:     # a hidden sketch can't be picked
            rs = sketch_regions(f["id"], f["ents"])
            if rs:
                regions += rs
                planes[f["id"]] = f["plane_z"]
    return regions, planes
