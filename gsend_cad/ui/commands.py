"""Interactive commands: Sketch mode and Extrude (with their right-hand panels).

Each session receives mouse events from the Viewport (`on_move`, `on_click`) and keys
from the main window (`on_key`). They edit the Document only when committed.
"""
from __future__ import annotations

import numpy as np
import pyvista as pv
from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from functools import partial

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QToolButton, QVBoxLayout, QWidget)

from ..core import plane as pl
from ..core import sketch as sk
from ..core.profiles import region_at, sketch_regions
from ..kernel import extrude_tool, face_outline, planar_face_at, plane_edges, region_face, triangles
from . import theme

TOOL_KEYS = {"Line": "line", "Rectangle": "rect", "Center Rect": "center_rect", "Circle": "circle",
             "Polygon": "polygon", "Point": "point"}
HINTS = {"line": "Click start, click end. Keep clicking to chain. Esc ends the chain.",
         "rect": "Click two opposite corners.", "center_rect": "Click center, then a corner.",
         "circle": "Click center, then a point on the circle.", "polygon": "Click center, then a vertex.",
         "point": "Click to place a point."}
SNAP_PX = 8         # how close (screen px) the cursor must come to an end / mid / center to snap
SELECT_HINT = ("Click a line or shape (or its row in the palette) to type exact values; right-click a "
               "dimension to change it. Delete removes it. L line · R rectangle · C circle · P polygon · "
               "Enter finishes")


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
class NumBox(QDoubleSpinBox):
    """Exact-value field. Enter applies it, Esc puts the old value back; keys stay here
    (so typing never triggers a sketch shortcut or finishes the sketch)."""

    def __init__(self, value: float, decimals=4):
        super().__init__()
        self.setRange(-1000, 1000)
        self.setDecimals(decimals)
        self.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.setKeyboardTracking(False)
        self.setFixedWidth(84)
        self.setAlignment(Qt.AlignRight)
        self.setValue(value)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.setValue(self.value())     # drops the half-typed text
            self.clearFocus()
        elif ev.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            return super().keyPressEvent(ev)
        else:
            super().keyPressEvent(ev)
        ev.accept()

    def wheelEvent(self, ev):
        ev.ignore()                         # scrolling the palette must not change a size


class EntRow(QWidget):
    def __init__(self, on_click):
        super().__init__()
        self._on_click = on_click

    def mousePressEvent(self, ev):
        self._on_click()


class DimEditor(QFrame):
    """Right-click a dimension in the view and this box opens on it with the value selected.
    Enter (or clicking away) applies it through set_param, exactly like a palette field;
    Esc closes it and changes nothing."""

    def __init__(self, vp):
        super().__init__(vp)
        self.setObjectName("dimEdit")
        self.setStyleSheet(f"#dimEdit {{ background:{theme.PANEL}; border:1px solid {theme.ACCENT}; }}")
        hl = QHBoxLayout(self)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(6)
        self.label = QLabel("")
        self.label.setStyleSheet(f"color:{theme.ACCENT};font-weight:700;")
        self.box = NumBox(0.0)
        hl.addWidget(self.label)
        hl.addWidget(self.box)
        self.box.installEventFilter(self)
        self.box.editingFinished.connect(self._done)
        self.on_apply = None
        self.hide()

    def open(self, label: str, value: float, decimals: int, pos: QPoint, on_apply):
        self.on_apply = on_apply
        self.label.setText(label)
        self.box.setDecimals(decimals)
        self.box.setValue(value)
        self.adjustSize()
        host = self.parentWidget()
        x = min(max(0, pos.x() - 12), max(0, host.width() - self.width()))
        y = min(max(0, pos.y() - self.height() // 2), max(0, host.height() - self.height()))
        self.move(x, y)
        self.show()
        self.raise_()
        self.box.setFocus()
        self.box.selectAll()

    def eventFilter(self, obj, ev):
        if obj is self.box and ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self.hide()                     # NumBox then drops the typed text; _done sees us hidden
        return super().eventFilter(obj, ev)

    def _done(self):
        if not self.isVisible():
            return
        self.hide()
        if self.on_apply is not None:
            self.on_apply(self.box.value())


class SketchPalette(Panel):
    def __init__(self, session: "SketchSession"):
        super().__init__("Edit Sketch" if session.edit_id else "Sketch Palette", 230)
        self.s = session
        self.plane = QDoubleSpinBox()
        self.plane.setRange(-100, 100)
        self.plane.setDecimals(3)
        self.plane.setSingleStep(0.25)
        self.plane.setPrefix("XY · Z " if pl.is_xy(session.base) else "Face · off ")
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
        self.all_dims = QCheckBox("All")
        self.all_dims.toggled.connect(lambda _on: session.draw_dims())
        self.row("Dimensions", self.all_dims)
        self.list = QWidget()
        self.list.setObjectName("entList")
        self.lv = QVBoxLayout(self.list)
        self.lv.setContentsMargins(0, 0, 0, 0)
        self.lv.setSpacing(0)
        self.sc = sc = QScrollArea()
        sc.setWidget(self.list)
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.v.addWidget(sc)
        # exact values of the selected entity (built by show_selected)
        self.edit = QWidget()
        self.ev = QVBoxLayout(self.edit)
        self.ev.setContentsMargins(0, 0, 0, 0)
        self.ev.setSpacing(0)
        self.v.addWidget(self.edit)
        self.boxes: dict[str, NumBox] = {}
        self._rows: list[EntRow] = []
        self.update_list([])
        self.show_selected(None)

    def step(self) -> float:
        return self.size.currentData() if self.snap.isChecked() else 0.0

    def update_list(self, ents):
        while self.lv.count():
            w = self.lv.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.count.setText(str(len(ents)))
        self._rows = []
        if not ents:
            e = QLabel("No entities yet")
            e.setAlignment(Qt.AlignCenter)
            e.setStyleSheet(f"color:{theme.FG3};padding:3px;border-bottom:1px solid {theme.LINE};")
            self.lv.addWidget(e)
        for i, ent in enumerate(ents):
            kind, detail = sk.entity_label(ent)
            r = EntRow(partial(self.s.select, i))
            r.setCursor(Qt.PointingHandCursor)
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
            sel = i == self.s.sel
            r.setAttribute(Qt.WA_StyledBackground, True)
            r.setStyleSheet(f"border-bottom:1px solid {theme.LINE};"
                            + (f"background:{theme.ACCENT_DIM};" if sel else ""))
            r.setFixedHeight(r.sizeHint().height())
            self.lv.addWidget(r)
            self._rows.append(r)
        self.lv.addStretch()
        # up to 7 rows, then scroll - measured from a real row, not an assumed 22 px (fonts and
        # DPI scaling make rows taller on Shane's laptop, and a too-short list clips its last row)
        rh = self._rows[0].height() if self._rows else 22
        self.sc.setFixedHeight(rh * min(7, max(1, len(ents))) + 2)
        self.fit()

    def show_selected(self, ent):
        """Fields for the selected entity (X/Y from the origin, then its size)."""
        while self.ev.count():
            w = self.ev.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.boxes = {}
        self.edit.setVisible(ent is not None)
        if ent is not None:
            kind, _ = sk.entity_label(ent)
            head = QLabel(f"{kind.upper()} · FROM ORIGIN")
            head.setStyleSheet(f"color:{theme.ACCENT};font-weight:700;padding:6px 10px 2px 10px;")
            head.setFixedHeight(head.sizeHint().height())
            self.ev.addWidget(head)
            gen = self.s.gen
            for key, val in sk.params(ent).items():
                box = NumBox(val, 0 if key == "sides" else 4)
                if key == "sides":
                    box.setRange(3, 64)
                box.editingFinished.connect(partial(self.s.set_value, gen, key, box))
                self.boxes[key] = box
                r = QWidget()
                r.setObjectName("panelRow")
                hl = QHBoxLayout(r)
                hl.setContentsMargins(10, 2, 10, 2)
                hl.addWidget(QLabel(sk.LABELS[key]))
                hl.addStretch()
                hl.addWidget(box)
                r.setFixedHeight(r.sizeHint().height())
                self.ev.addWidget(r)
            # one line, no word wrap: a wrapping label reports a one-line height until the
            # layout has run, and fit() reading that is how the rows below got crushed
            tip = QLabel("Enter applies · Del removes")
            tip.setStyleSheet(f"color:{theme.FG3};padding:4px 10px 6px 10px;")
            tip.setFixedHeight(tip.sizeHint().height())
            self.ev.addWidget(tip)
        self.fit()

    def fit(self):
        """Overlay panels aren't in a layout, so size to the content by hand.

        A FIXED height, and every row above has a fixed height too. resize() to a size hint
        read before the rows had settled let the layout squeeze the FROM ORIGIN rows to a few
        pixels each (Shane's 200% laptop, 9/30/26: only the tops of X / Y / Diameter showed).
        Fixed rows cannot be squeezed, and a second fit after the event loop has laid the
        panel out corrects any hint that was still stale."""
        self._size_to_content()
        QTimer.singleShot(0, self._size_to_content)

    def _size_to_content(self):
        try:
            self.layout().activate()
            h = max(self.sizeHint().height(), self.minimumSizeHint().height())   # incl. the frame
            if h != self.height() or self.minimumHeight() != h:
                self.setFixedHeight(h)
        except RuntimeError:
            pass                            # the sketch closed before the deferred call ran

    def refresh_values(self, ent):
        for key, val in sk.params(ent).items():
            box = self.boxes.get(key)
            if box is not None and not box.hasFocus():
                box.blockSignals(True)
                box.setValue(val)
                box.blockSignals(False)


class PlanePickSession:
    """Sketch on the part: hover a flat face of the model and it is outlined, click it and the
    sketch opens on that face. Click empty space or press Enter for the XY plane. Esc cancels.
    Left drag still orbits, so a side or the bottom can be turned into view first."""
    captures_left = False

    def __init__(self, win):
        self.win, self.vp = win, win.viewport
        self.hover = None                    # (body, face, frame) under the cursor
        self.vp.show_banner(f"SKETCH · <span style='color:{theme.ACCENT}'>PICK A FACE</span>")
        win.message("Click a flat face of the part to sketch on it · click empty space or press Enter "
                    "for the XY plane · Esc cancels")

    def _face_at(self, ev):
        p = self.vp.pick_world(ev.position().toPoint())
        return planar_face_at(self.win.model.bodies, p) if p else None

    def on_move(self, w, ev):
        if ev.buttons():
            return
        hit = self._face_at(ev)
        if (hit is None) == (self.hover is None) and (hit is None or hit[2] == self.hover[2]):
            return
        self.hover = hit
        self.vp.clear("hover", render=False)
        if hit:
            self.vp.add_lines("hover", face_outline(hit[1]), color=theme.ACCENT, width=2.4)
        self.vp.plotter.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
        self.vp.render()

    def on_click(self, w, ev):
        hit = self._face_at(ev)
        self.win.start_sketch(plane=hit[2] if hit else pl.xy(0.0))

    def on_key(self, ev) -> bool:
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.win.start_sketch(plane=pl.xy(0.0))
            return True
        if ev.key() == Qt.Key_Escape:
            self.win.cancel_command()
            return True
        return False

    def ribbon_tool(self, label: str):
        if label == "Cancel":
            self.win.cancel_command()
            return
        self.win.start_sketch(plane=pl.xy(0.0))       # a drawing tool clicked now: XY, as before
        if label in TOOL_KEYS and self.win.session is not None:
            self.win.session.ribbon_tool(label)

    def close(self):
        self.vp.clear("hover", render=False)
        self.vp.plotter.setCursor(Qt.ArrowCursor)
        self.vp.show_banner(None)


class SketchSession:
    captures_left = True

    def __init__(self, win, name: str, plane_z: float = 0.0, ents=None, edit_id: str | None = None,
                 plane: dict | None = None):
        self.win, self.vp = win, win.viewport
        self.name = name
        self.plane_z = plane_z               # offset along the plane's normal from `base`
        # the sketch plane (core.plane): XY, or a face of the part. `base` is the picked face
        # itself; plane_z slides the sketch off it (the palette's Plane field), like Z on XY.
        self.base = pl.offset(plane, -plane_z) if plane is not None else pl.xy(0.0)
        self.frame = pl.offset(self.base, plane_z)
        self.snap_hit = None                 # (u, v, kind) the cursor is snapped to right now
        self.sketch_snaps: list = []         # ends / mids / centers of what is drawn
        self.model_edges: list = []          # the part's edges lying on the plane (kernel.plane_edges)
        self.model_snaps: list = []
        self.edit_id = edit_id               # set when editing a sketch that is already in the timeline
        self.ents: list = [dict(e) for e in ents or []]
        self.origin: list = list(range(len(self.ents)))   # old index of each entity; None = drawn now
        self.start = (list(self.ents), plane_z)
        self.hist: list = []                 # (ents, origin) before each change, for Ctrl+Z
        self.redo_stack: list = []
        self.pts: list = []
        self.tool = None
        self.sel: int | None = None          # entity whose exact values are in the palette
        self.gen = 0                         # bumps when the palette's fields are rebuilt
        self.palette = SketchPalette(self)
        self.editor = DimEditor(self.vp)     # right-click a dimension: type its value in place
        self._plane_changed()

    def changed(self) -> bool:
        return (self.ents, self.plane_z) != self.start

    def _push(self):
        self.hist.append((list(self.ents), list(self.origin)))
        self.redo_stack.clear()

    def select(self, i: int | None):
        i = i if i is not None and 0 <= i < len(self.ents) else None
        self.sel = i
        self.gen += 1
        self.palette.show_selected(self.ents[i] if i is not None else None)
        self.vp.set_side(self.palette)
        self.redraw()

    def set_value(self, gen: int, key: str, box):
        """A palette field was typed into (Enter / Tab / click away)."""
        if gen != self.gen or self.sel is None:
            return                          # field of an entity that is no longer selected
        e = self.ents[self.sel]
        if abs(sk.params(e)[key] - box.value()) < 1e-10:
            return
        try:
            new = sk.set_param(e, key, box.value())
        except ValueError as exc:
            self.vp.show_toast(str(exc), bad=True)
            self.palette.refresh_values(e)
            box.blockSignals(True)
            box.setValue(sk.params(e)[key])
            box.blockSignals(False)
            return
        self._push()
        self.ents[self.sel] = new
        self.palette.refresh_values(new)
        self.redraw()

    def delete_ent(self, i: int):
        if 0 <= i < len(self.ents):
            kind, _ = sk.entity_label(self.ents[i])
            self._push()
            del self.ents[i]
            del self.origin[i]
            if self.sel is not None:
                self.select(None if self.sel == i else self.sel - (self.sel > i))
            self.redraw()
            self.vp.show_toast(f"{kind} deleted")

    def set_plane(self, z):
        self.plane_z = float(z)
        self.pts = []
        self._plane_changed()

    def _plane_changed(self):
        """The plane moved: the viewport reads mouse rays on it, and the part's edges that lie on
        it are what the cursor can snap to (and are drawn, dimmed, so they can be seen)."""
        self.frame = pl.offset(self.base, self.plane_z)
        self.vp.set_frame(self.frame)
        try:
            self.model_edges = plane_edges(self.win.model.bodies, self.frame)
        except Exception:
            self.model_edges = []
        self.model_snaps = sk.edge_snap_points(self.model_edges)
        self.redraw()

    def set_tool(self, label: str | None):
        self.tool = TOOL_KEYS.get(label) if label else None
        self.pts = []
        self.vp.clear("preview")
        self.vp.dim.hide()
        self.win.ribbon.set_active(label)
        name = label.upper() if label else "SELECT"
        head = f"EDIT {self.name.upper()}" if self.edit_id else "SKETCH"
        where = "XY PLANE" if pl.is_xy(self.frame) else "FACE PLANE"
        self.vp.show_banner(f"{head} · {where} · <span style='color:{theme.ACCENT}'>{name}</span>")
        self.win.message(HINTS.get(self.tool, SELECT_HINT))

    def _snap(self, w, ev):
        """Where a click lands: a snap point (end / mid / center of the sketch or of the part's
        edges on this plane) within SNAP_PX of the cursor beats the grid."""
        if ev is not None:
            tol = SNAP_PX * self.vp.pixel_size(ev.position().toPoint())
            hit = sk.nearest_snap(self.sketch_snaps + self.model_snaps, w, tol)
            if hit is not None:
                self.snap_hit = hit
                return [hit[0], hit[1]]
        self.snap_hit = None
        step = self.palette.step()
        if ev is not None and ev.modifiers() & Qt.ShiftModifier:
            step /= 4
        return [sk.snap(w[0], step), sk.snap(w[1], step)]

    def _mark_snap(self, p, pos):
        """A small diamond on the snap point the cursor is held to (none: nothing drawn)."""
        self.vp.clear("snapmark", render=False)
        if self.snap_hit is None:
            return
        m = 5 * self.vp.pixel_size(pos)
        u, v = p
        ring = [(u + m, v), (u, v + m), (u - m, v), (u, v - m), (u + m, v)]
        self.vp.add_lines("snapmark", [[pl.to_world(self.frame, q, 0.008) for q in ring]],
                          color=theme.ACCENT, width=1.6)

    def _lines(self, ents, dz=0.004):
        return [[pl.to_world(self.frame, q, dz) for q in sk.entity_points(e)] for e in ents]

    def redraw(self):
        self.vp.clear("sketch", render=False)
        self.vp.clear("sel", render=False)
        self.vp.clear("plane_edges", render=False)
        self.sketch_snaps = sk.snap_points(self.ents)
        if self.model_edges:
            self.vp.add_lines("plane_edges", [[pl.to_world(self.frame, q, 0.003) for q in e["pts"]]
                                              for e in self.model_edges], color=theme.FG3, width=1.0)
        others = [e for i, e in enumerate(self.ents) if i != self.sel]
        self.vp.add_lines("sketch", self._lines(others))
        if self.sel is not None:
            self.vp.add_lines("sel", self._lines([self.ents[self.sel]], 0.005), color=theme.FG, width=2.6)
        self.palette.update_list(self.ents)
        self.draw_dims(render=False)
        self.win.refresh_tree()
        self.vp.render()

    def draw_dims(self, render=True):
        """Dimensions from the origin (and sizes) for the selected entity, or all with 'All'."""
        self.vp.clear("dims", render=False)
        show = range(len(self.ents)) if self.palette.all_dims.isChecked() else \
            ([self.sel] if self.sel is not None else [])
        lines, labels = [], []
        for i in show:
            for d in sk.dimensions(self.ents[i]):
                lines += [[pl.to_world(self.frame, q, 0.006) for q in ln] for ln in d["lines"]]
                labels.append((tuple(pl.to_world(self.frame, d["at"], 0.006)), d["text"]))
        self.vp.add_lines("dims", lines, color=theme.FG2, width=1.0)
        self.vp.add_labels("dims", labels)
        if render:
            self.vp.render()

    def on_move(self, w, ev):
        if not self.tool:
            return
        pos = ev.position().toPoint()
        p = self._snap(w, ev)
        self._mark_snap(p, pos)
        tag = f"  · {self.snap_hit[2].upper()}" if self.snap_hit else ""
        if not self.pts or self.tool == "point":
            self.vp.show_dim(f"X {sk.fmt(p[0])}  Y {sk.fmt(p[1])}{tag}", pos)
            self.vp.render()
            return
        ent = sk.build_entity(self.tool, self.pts[0], p, int(self.palette.sides.currentText()))
        self.vp.clear("preview", render=False)
        if ent:
            self.vp.add_lines("preview", self._lines([ent]), opacity=0.45)
        self.vp.show_dim(sk.preview_label(self.tool, self.pts[0], p, int(self.palette.sides.currentText())) + tag, pos)
        self.vp.render()

    def _add(self, ent):
        self._push()
        self.ents.append(ent)
        self.origin.append(None)
        self.select(len(self.ents) - 1)     # its exact values show right away

    def shown_dims(self):
        """(entity index, dimension dict) for every dimension drawn right now."""
        show = range(len(self.ents)) if self.palette.all_dims.isChecked() else \
            ([self.sel] if self.sel is not None else [])
        return [(i, d) for i in show for d in sk.dimensions(self.ents[i])]

    def on_right_click(self, w, ev) -> bool:
        """Right-click on a dimension opens its value box. Anywhere else is not ours: False,
        and the view pans as usual."""
        pos = ev.position().toPoint()
        tol = 10 * self.vp.pixel_size(pos)
        show = range(len(self.ents)) if self.palette.all_dims.isChecked() else \
            ([self.sel] if self.sel is not None else [])
        for i in show:
            d = sk.dimension_at(self.ents[i], w, tol)
            if d is not None:
                key = d["key"]
                self.editor.open(sk.LABELS[key], sk.params(self.ents[i])[key], 0 if key == "sides" else 4,
                                 pos, partial(self.apply_dim, i, key))
                return True
        return False

    def apply_dim(self, i: int, key: str, value: float):
        """A value typed into the right-click box (same rules as a palette field)."""
        if not 0 <= i < len(self.ents):
            return
        e = self.ents[i]
        if abs(sk.params(e)[key] - value) < 1e-10:
            return
        try:
            new = sk.set_param(e, key, value)
        except ValueError as exc:
            self.vp.show_toast(str(exc), bad=True)
            return
        self._push()
        self.ents[i] = new
        self.select(i)                       # palette fields follow, view redraws
        self.vp.plotter.setFocus()

    def on_click(self, w, ev):
        self.vp.plotter.setFocus()           # take keys back from a palette field
        if not self.tool:                    # select mode: pick what's under the cursor
            pos = ev.position().toPoint()
            self.select(sk.nearest(self.ents, w, 8 * self.vp.pixel_size(pos)))
            return
        p = self._snap(w, ev)
        if self.tool == "point":
            self._add(sk.point(p))
            return
        if not self.pts:
            self.pts = [p]
            return
        ent = sk.build_entity(self.tool, self.pts[0], p, int(self.palette.sides.currentText()))
        self.pts = [p] if self.tool == "line" else []
        self.vp.clear("preview", render=False)
        if ent:
            self._add(ent)
        else:
            self.redraw()

    def undo(self):
        """Undo the last change (shape, typed value, delete, clear). Also drops a half-drawn
        shape; with nothing drawn yet it just drops that."""
        had_pts, self.pts = bool(self.pts), []
        self.vp.clear("preview", render=False)
        self.vp.dim.hide()
        if self.hist:
            self.redo_stack.append((list(self.ents), list(self.origin)))
            self.ents, self.origin = self.hist.pop()
            self.select(None)
            self.vp.show_toast("Undo")
        elif not had_pts:
            self.vp.show_toast("Nothing to undo")
        self.vp.render()

    def redo(self):
        if not self.redo_stack:
            self.vp.show_toast("Nothing to redo")
            return
        self.hist.append((list(self.ents), list(self.origin)))
        self.ents, self.origin = self.redo_stack.pop()
        self.pts = []
        self.select(None)
        self.vp.show_toast("Redo")

    def on_key(self, ev) -> bool:
        k = ev.key()
        if k == Qt.Key_Escape:
            if self.pts:
                self.pts = []
                self.vp.clear("preview")
                self.vp.dim.hide()
            elif self.tool:
                self.set_tool(None)
            else:
                self.select(None)
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self.win.finish_sketch()
        elif k == Qt.Key_Z and ev.modifiers() & Qt.ControlModifier:
            self.undo()
        elif k == Qt.Key_Y and ev.modifiers() & Qt.ControlModifier:
            self.redo()
        elif k in (Qt.Key_Delete, Qt.Key_Backspace) and self.sel is not None:
            self.delete_ent(self.sel)
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
        elif label == "Select":
            self.set_tool(None)
        elif label == "Undo":
            self.undo()
        elif label == "Clear":
            if self.ents:
                self._push()
            self.ents, self.origin, self.pts = [], [], []
            self.vp.clear("preview", render=False)
            self.select(None)
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
        for g in ("sketch", "sel", "dims", "preview", "plane_edges", "snapmark"):
            self.vp.clear(g, render=False)
        self.vp.dim.hide()
        self.editor.hide()
        self.editor.deleteLater()
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
        self.planes = planes            # sketch id -> plane frame (core.plane)
        self.sel: list = []             # selected region keys, in pick order
        self.hover = None
        self.fill_actors = {}
        self.panel = ExtrudePanel(self)
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


def regions_for(doc):
    """Pickable regions from every applied sketch, plus each sketch's plane (core.plane frame)."""
    regions, planes = [], {}
    for f in doc.applied():
        if f["kind"] == "sketch" and f.get("show") is not False:     # a hidden sketch can't be picked
            rs = sketch_regions(f["id"], f["ents"])
            if rs:
                regions += rs
                planes[f["id"]] = doc.sketch_plane(f)
    return regions, planes
