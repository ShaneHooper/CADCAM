"""Solid commands: Extrude, Revolve and edge Fillet / Chamfer (with their right-hand panels).
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt

from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QToolButton,
                               QWidget)

from ..core import sketch as sk
from ..core.profiles import region_at
from ..kernel import (edge_list, extrude_tool, region_face, revolve_axis,
                      revolve_tool)
from . import icons, theme
from .cmd_base import NumBox, Panel, _dlg_footer, mesh_of


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
    PANEL = ExtrudePanel

    def __init__(self, win, regions, planes):
        self.win, self.vp = win, win.viewport
        self.regions = regions          # [Region]
        self.planes = planes            # sketch id -> plane frame (core.plane)
        self.sel: list = []             # selected region keys, in pick order
        self.hover = None
        self.fill_actors = {}
        self.panel = self.PANEL(self)
        for r in regions:
            m = mesh_of(region_face(r, self.planes[r.sketch], 0.002))
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
        for sid, fr in self.planes.items():
            w = self.vp.world_at(ev.position().toPoint(), frame=fr)
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


# ------------------------------------------------------------------ revolve


def _point_segment(p, a, b) -> float:
    """Distance from point p to the segment a-b (sketch coordinates)."""
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


class RevolvePanel(Panel):
    def __init__(self, session: "RevolveSession"):
        super().__init__("Revolve")
        s = session
        self.prof = self.row("Profile", self.value("Select"))
        # the axis is PICKED in the sketch (a line, or the red / green axis), not chosen from a list
        self.axis_val = self.value("Sketch X axis")
        self.axis_btn = QToolButton()
        self.axis_btn.setObjectName("pickBtn")
        self.axis_btn.setCheckable(True)
        self.axis_btn.setIcon(icons.icon("cursor", theme.FG2))
        self.axis_btn.setFixedSize(30, 24)
        self.axis_btn.setToolTip("Click, then click the line or axis in the sketch to revolve about")
        self.axis_btn.toggled.connect(s.set_axis_pick)
        wrap = QWidget()
        hl = QHBoxLayout(wrap)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        hl.addWidget(self.axis_val)
        hl.addWidget(self.axis_btn)
        self.row("Axis", wrap)
        self.angle = QDoubleSpinBox()
        self.angle.setRange(-360, 360)
        self.angle.setDecimals(2)
        self.angle.setSuffix(" °")
        self.angle.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.angle.setValue(360)
        self.row("Angle", self.angle)
        self.op = QComboBox()
        for label, key in (("Join", "join"), ("Cut", "cut"), ("New Body", "new")):
            self.op.addItem(label, key)
        self.row("Operation", self.op)
        _dlg_footer(self, s)
        self.op.currentIndexChanged.connect(s.update_preview)
        self.angle.valueChanged.connect(s.update_preview)

    set_count = ExtrudePanel.set_count

    def show_axis(self, text: str):
        self.axis_val.setText(text)


class RevolveSession(ExtrudeSession):
    """Pick closed profiles (like Extrude), pick the axis, spin them into a round body."""
    PANEL = RevolvePanel

    def __init__(self, win, regions, planes):
        self._axis_sketch = None
        self.axis = ("x", None)             # ("x" | "y" | "line", entity index): what the part spins about
        self.axis_pick = False              # the panel's cursor button is down: the next click picks the axis
        super().__init__(win, regions, planes)

    def _sketch_id(self):
        if self.sel:
            return next(r for r in self.regions if r.key == self.sel[0]).sketch
        return self.regions[-1].sketch

    def _default_axis(self):
        """When the profiles' sketch changes: a profile drawn above the X axis spins about X, one
        right of the Y axis about Y. The user can then pick any line or axis instead."""
        sid = self._sketch_id()
        if sid == self._axis_sketch:
            return
        self._axis_sketch = sid
        pts = [p for r in self.regions if r.key in self.sel for p in r.outer.pts] or [(0, 1)]
        self.set_axis("x" if min(p[1] for p in pts) >= -1e-9 else "y", None, preview=False)

    def set_axis(self, kind: str, ent, preview: bool = True):
        self.axis = (kind, ent)
        if hasattr(self.panel, "axis_val"):
            if kind == "line":
                e = self.win.doc.feature(self._sketch_id())["ents"][ent]
                self.panel.show_axis(f"Line {ent + 1} · {sk.entity_label(e)[1]}")
            elif kind == "pts":
                e = self.win.doc.feature(self._sketch_id())["ents"][ent[2]]
                self.panel.show_axis(f"Edge of {sk.entity_label(e)[0].lower()} {ent[2] + 1}")
            else:
                self.panel.show_axis(f"Sketch {kind.upper()} axis")
        if preview:
            self.update_preview()

    def set_axis_pick(self, on: bool):
        self.axis_pick = bool(on)
        self.vp.plotter.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        self.update_preview()

    def pick_axis(self, ev) -> bool:
        """The click lands on the sketch's red X axis, green Y axis or one of its lines: that is the axis."""
        sid = self._sketch_id()
        pos = ev.position().toPoint()
        w = self.vp.world_at(pos, frame=self.planes[sid])
        if not w:
            return False
        tol = 8 * self.vp.pixel_size(pos)
        ents = self.win.doc.feature(sid)["ents"]
        best = min((abs(w[1]), ("x", None)), (abs(w[0]), ("y", None)))
        for i, e in enumerate(ents):
            if e["type"] in ("point", "circle", "arc"):
                continue                                # nothing straight to spin about
            pts = sk.entity_points(e)                   # a line, a parallel line, or a rectangle's / polygon's sides
            for a, b in zip(pts, pts[1:]):
                d = _point_segment(w, a, b)
                if d < best[0]:
                    best = (d, ("line", i) if e["type"] == "line" else ("pts", (tuple(a), tuple(b), i)))
        if best[0] > tol:
            self.vp.show_toast("Click a line or an edge in the sketch, or the red / green axis", bad=True)
            return False
        self.set_axis(*best[1], preview=False)
        self.panel.axis_btn.setChecked(False)           # set_axis_pick(False) redraws
        return True

    def on_click(self, w, ev):
        if self.axis_pick:
            self.pick_axis(ev)
            return
        super().on_click(w, ev)

    def on_key(self, ev) -> bool:
        if ev.key() == Qt.Key_Escape and self.axis_pick:
            self.panel.axis_btn.setChecked(False)       # Esc leaves axis picking before it leaves Revolve
            return True
        return super().on_key(ev)

    def paint(self):
        if hasattr(self.panel, "axis_val"):
            self._default_axis()
        super().paint()

    def feature(self) -> dict:
        regs = [next(r for r in self.regions if r.key == k) for k in self.sel]
        kind, ent = self.axis
        axis = {"sketch": self._sketch_id(), "kind": kind}
        if kind == "line":
            axis["ent"] = ent
        elif kind == "pts":
            axis["a"], axis["b"] = list(ent[0]), list(ent[1])
        return {"kind": "revolve", "name": "preview", "op": self.panel.op.currentData(),
                "angle": self.panel.angle.value(), "axis": axis,
                "profiles": [r.to_data() for r in regs if r.sketch == axis["sketch"]]}

    def update_preview(self, *_):
        if not hasattr(self.panel, "axis_val"):
            return
        self.vp.clear("preview", render=False)
        f = self.feature()
        try:                                  # the axis: a long line through it
            ax = revolve_axis(f, self.win.doc.applied())
            o, d = ax.position, ax.direction
            self.vp.add_lines("preview", [[tuple(o - d * 20), tuple(o + d * 20)]], theme.WARN, 1.4)
        except Exception:
            pass
        if f["profiles"] and abs(f["angle"]) >= 0.01:
            try:
                tool = revolve_tool(f, self.win.doc.applied())
                col = theme.BAD if f["op"] == "cut" else theme.ACCENT
                self.vp.add_surface("preview", mesh_of(tool), col, 0.35)
            except Exception as exc:
                self.win.message(f"Revolve: {exc}")
                self.vp.render()
                return
        n = len(f["profiles"])
        if self.axis_pick:
            self.win.message("REVOLVE: click the line or the red / green axis to revolve about · Esc = back")
        else:
            self.win.message(f"REVOLVE {self.panel.op.currentText().upper()} · {n} profile{'s' if n != 1 else ''} · "
                             "axis: the yellow line (cursor button to pick another) · Enter = OK · Esc = cancel"
                             if n else "REVOLVE: click a profile (a half cross-section) · Esc = cancel")
        self.vp.render()

    def commit(self):
        f = self.feature()
        if not f["profiles"]:
            self.vp.show_toast("Select a profile", bad=True)
            return
        if abs(f["angle"]) < 0.01:
            self.vp.show_toast("Angle must not be zero", bad=True)
            return
        self.win.commit_feature(f)


# ------------------------------------------------------------------ fillet / chamfer (solid edges)
class EdgePanel(Panel):
    def __init__(self, session: "EdgeSession", op: str):
        super().__init__("Fillet" if op == "fillet" else "Chamfer")
        s = session
        self.edges = self.row("Edges", self.value("Select"))
        self.op = QComboBox()
        self.op.addItem("Fillet (round)", "fillet")
        self.op.addItem("Chamfer (bevel)", "chamfer")
        self.op.setCurrentIndex(0 if op == "fillet" else 1)
        self.row("Type", self.op)
        self.size = NumBox(0.125)
        self.size.setRange(0.0001, 1000)
        self.size_row = self.row("Radius", self.size)
        _dlg_footer(self, s)
        self.op.currentIndexChanged.connect(s.op_changed)

    def set_count(self, n: int):
        self.edges.setText(f"{n} selected" if n else "Select")
        self.edges.setProperty("none", not n)
        self.edges.style().polish(self.edges)


def edge_at(vp, edges, pos, px: float = 8):
    """(index, world point) of the edge under screen point `pos` (nearest in px, front-most on a
    tie), or (None, None). The point is the spot on the edge nearest the cursor; within `px` of
    one of the edge's ends it snaps to that end."""
    best, hit, at = None, None, None
    for i, e in enumerate(edges):
        q = vp.project(e["pts"])
        a, b = q[:-1], q[1:]
        d = b[:, :2] - a[:, :2]
        L = (d ** 2).sum(1)
        t = np.clip(((pos.x() - a[:, 0]) * d[:, 0] + (pos.y() - a[:, 1]) * d[:, 1]) / np.where(L, L, 1), 0, 1)
        dist = np.hypot(a[:, 0] + t * d[:, 0] - pos.x(), a[:, 1] + t * d[:, 1] - pos.y())
        k = int(dist.argmin())
        if dist[k] <= px:
            depth = a[k, 2] + t[k] * (b[k, 2] - a[k, 2])
            score = (round(dist[k] / 3), depth)
            if best is None or score < best:
                P = e["pts"]
                w = P[k] + t[k] * (P[k + 1] - P[k])
                for end, qe in ((P[0], q[0]), (P[-1], q[-1])):
                    if math.hypot(qe[0] - pos.x(), qe[1] - pos.y()) <= px:
                        w = end
                best, hit, at = score, i, tuple(float(v) for v in w)
    return hit, at


class EdgeSession:
    """Click edges of the solid to round (fillet) or bevel (chamfer) them."""
    captures_left = False                   # left drag still orbits; a click picks
    PICK_PX = 8

    def __init__(self, win, op: str):
        self.win, self.vp = win, win.viewport
        self.edges = edge_list(win.model.bodies)
        self.sel: list[int] = []
        self.hover = None
        self.panel = EdgePanel(self, op)
        self.op_changed()

    def op_changed(self, *_):
        fil = self.panel.op.currentData() == "fillet"
        self.panel.title.setText("FILLET" if fil else "CHAMFER")
        for lb in self.panel.findChildren(QLabel):
            if lb.text() in ("Radius", "Distance"):
                lb.setText("Radius" if fil else "Distance")
        self.win.ribbon.set_active("Fillet" if fil else "Chamfer")
        self.paint()

    def pick(self, ev):
        """Index of the edge under the cursor (nearest in px; front-most on a tie)."""
        return edge_at(self.vp, self.edges, ev.position(), self.PICK_PX)[0]

    def paint(self):
        self.vp.clear("edges", render=False)
        if self.sel:
            self.vp.add_lines("edges", [self.edges[i]["pts"] for i in self.sel], theme.ACCENT, 3.5)
        if self.hover is not None and self.hover not in self.sel:
            self.vp.add_lines("edges", [self.edges[self.hover]["pts"]], theme.FG, 3.0)
        n = len(self.sel)
        self.panel.set_count(n)
        self.win.status.sel.setText(f"SEL: {n} EDGE{'' if n == 1 else 'S'}")
        word = self.panel.op.currentText().split()[0].upper()
        self.win.message(f"{word}: click edges to add or remove them · set the size · Enter = OK · Esc = cancel")
        self.vp.render()

    def on_move(self, w, ev):
        if ev.buttons():
            return
        h = self.pick(ev)
        if h != self.hover:
            self.hover = h
            self.vp.plotter.setCursor(Qt.PointingHandCursor if h is not None else Qt.ArrowCursor)
            self.paint()

    def on_click(self, w, ev):
        h = self.pick(ev)
        if h is None:
            return
        self.sel.remove(h) if h in self.sel else self.sel.append(h)
        self.paint()

    def commit(self):
        if not self.sel:
            self.vp.show_toast("Click at least one edge", bad=True)
            return
        self.win.commit_feature({"kind": "fillet", "op": self.panel.op.currentData(),
                                 "size": self.panel.size.value(), "edges": [self.edges[i]["mid"] for i in self.sel]})

    def on_key(self, ev) -> bool:
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.commit()
            return True
        if ev.key() == Qt.Key_Escape:
            self.win.cancel_command()
            return True
        return False

    def ribbon_tool(self, label):
        if label in ("Fillet", "Chamfer"):
            self.panel.op.setCurrentIndex(0 if label == "Fillet" else 1)
            return
        self.win.cancel_command()
        self.win.run_tool(label)

    def close(self):
        self.vp.clear("edges", render=False)
        self.vp.plotter.setCursor(Qt.ArrowCursor)
