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

from ..core import cam
from ..core import plane as pl
from ..core import sketch as sk
from ..core.profiles import region_at, sketch_regions
from ..kernel import (bodies_bbox, edge_list, max_radius, extrude_tool, face_outline, planar_face_at, plane_edges, region_face, revolve_axis,
                      revolve_tool, triangles)
from . import theme

TOOL_KEYS = {"Line": "line", "Rectangle": "rect", "Center Rect": "center_rect", "Circle": "circle",
             "Polygon": "polygon", "Point": "point", "Fillet": "fillet", "Chamfer": "chamfer"}
CORNER_TOOLS = ("fillet", "chamfer")
HINTS = {"line": "Click start, click end. Keep clicking to chain. Esc ends the chain.",
         "rect": "Click two opposite corners.", "center_rect": "Click center, then a corner.",
         "circle": "Click center, then a point on the circle.", "polygon": "Click center, then a vertex.",
         "point": "Click to place a point.",
         "fillet": "Click a sharp corner to round it (radius: Corner size in the palette).",
         "chamfer": "Click a sharp corner to bevel it (distance: Corner size in the palette)."}
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
        self.corner = NumBox(0.125)
        self.corner.setRange(0.0001, 1000)
        self.corner.setToolTip("Radius for Fillet, distance along each side for Chamfer")
        self.row("Corner size", self.corner)
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

    def _corner_hover(self, w, pos):
        """Fillet / Chamfer tool: ring the corner that a click would change."""
        self.vp.clear("preview", render=False)
        hit = sk.nearest_corner(self.ents, w, 12 * self.vp.pixel_size(pos))
        size = self.palette.corner.value()
        word = "R" if self.tool == "fillet" else "Chamfer"
        if hit:
            r = 6 * self.vp.pixel_size(pos)
            self.vp.add_lines("preview", self._lines([sk.circle(hit[0], r)]), color=theme.FG, width=2.0)
            self.vp.show_dim(f"{word} {sk.fmt(size)} · click to apply", pos)
        else:
            self.vp.show_dim(f"{word} {sk.fmt(size)} · move onto a sharp corner", pos)
        self.vp.render()

    def on_move(self, w, ev):
        if not self.tool:
            return
        pos = ev.position().toPoint()
        if self.tool in CORNER_TOOLS:
            self._corner_hover(w, pos)
            return
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
        if self.tool in CORNER_TOOLS:
            pos = ev.position().toPoint()
            try:
                ents, origin = sk.corner_op(self.ents, self.origin, w, self.palette.corner.value(), self.tool,
                                            12 * self.vp.pixel_size(pos))
            except ValueError as exc:
                self.vp.show_toast(str(exc), bad=True)
                return
            self._push()
            self.ents, self.origin = ents, origin
            self.select(len(self.ents) - 1)  # the new arc / bevel line: its values show
            self._corner_hover(w, pos)
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
def _dlg_footer(panel, session):
    foot = QWidget()
    fl = QHBoxLayout(foot)
    fl.setContentsMargins(10, 6, 10, 6)
    fl.addStretch()
    cancel, ok = QPushButton("CANCEL"), QPushButton("OK")
    for b in (cancel, ok):
        b.setObjectName("dlgBtn")
        fl.addWidget(b)
    ok.setProperty("ok", True)
    cancel.clicked.connect(session.win.cancel_command)
    ok.clicked.connect(session.commit)
    panel.v.addWidget(foot)


class RevolvePanel(Panel):
    def __init__(self, session: "RevolveSession"):
        super().__init__("Revolve")
        s = session
        self.prof = self.row("Profile", self.value("Select"))
        self.axis = QComboBox()
        self.axis.setMinimumWidth(110)
        self.row("Axis", self.axis)
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
        for w in (self.axis, self.op):
            w.currentIndexChanged.connect(s.update_preview)
        self.angle.valueChanged.connect(s.update_preview)

    set_count = ExtrudePanel.set_count


class RevolveSession(ExtrudeSession):
    """Pick closed profiles (like Extrude), pick the axis, spin them into a round body."""
    PANEL = RevolvePanel

    def __init__(self, win, regions, planes):
        self._axis_sketch = None
        super().__init__(win, regions, planes)

    def _sketch_id(self):
        if self.sel:
            return next(r for r in self.regions if r.key == self.sel[0]).sketch
        return self.regions[-1].sketch

    def _fill_axes(self):
        """Axis choices for the profiles' sketch: its X / Y axis, then its lines."""
        sid = self._sketch_id()
        if sid == self._axis_sketch:
            return
        self._axis_sketch = sid
        ents = self.win.doc.feature(sid)["ents"]
        box = self.panel.axis
        box.blockSignals(True)
        box.clear()
        box.addItem("Sketch X axis", ("x", None))
        box.addItem("Sketch Y axis", ("y", None))
        for i, e in enumerate(ents):
            if e["type"] == "line":
                box.addItem(f"Line {i + 1} · {sk.entity_label(e)[1]}", ("line", i))
        # a profile drawn above the X axis spins about X; one right of the Y axis about Y
        pts = [p for r in self.regions if r.key in self.sel for p in r.outer.pts] or [(0, 1)]
        box.setCurrentIndex(0 if min(p[1] for p in pts) >= -1e-9 else 1)
        box.blockSignals(False)

    def paint(self):
        if hasattr(self.panel, "axis"):
            self._fill_axes()
        super().paint()

    def feature(self) -> dict:
        regs = [next(r for r in self.regions if r.key == k) for k in self.sel]
        kind, ent = self.panel.axis.currentData() or ("x", None)
        axis = {"sketch": self._sketch_id(), "kind": kind}
        if kind == "line":
            axis["ent"] = ent
        return {"kind": "revolve", "name": "preview", "op": self.panel.op.currentData(),
                "angle": self.panel.angle.value(), "axis": axis,
                "profiles": [r.to_data() for r in regs if r.sketch == axis["sketch"]]}

    def update_preview(self, *_):
        if not hasattr(self.panel, "axis"):
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
        self.win.message(f"REVOLVE {self.panel.op.currentText().upper()} · {n} profile{'s' if n != 1 else ''} · "
                         "pick the axis in the panel (yellow line) · Enter = OK · Esc = cancel" if n else
                         "REVOLVE: click a profile (a half cross-section) · Esc = cancel")
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
        pos = ev.position()
        best, hit = None, None
        for i, e in enumerate(self.edges):
            q = self.vp.project(e["pts"])
            a, b = q[:-1], q[1:]
            d = b[:, :2] - a[:, :2]
            L = (d ** 2).sum(1)
            t = np.clip(((pos.x() - a[:, 0]) * d[:, 0] + (pos.y() - a[:, 1]) * d[:, 1]) / np.where(L, L, 1), 0, 1)
            px = a[:, 0] + t * d[:, 0] - pos.x()
            py = a[:, 1] + t * d[:, 1] - pos.y()
            dist = np.hypot(px, py)
            k = int(dist.argmin())
            if dist[k] <= self.PICK_PX:
                depth = a[k, 2] + t[k] * (b[k, 2] - a[k, 2])
                score = (round(dist[k] / 3), depth)
                if best is None or score < best:
                    best, hit = score, i
        return hit

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


# ------------------------------------------------------------------ CAM setup
def setup_bodies(win, setup):
    bodies = win.model.bodies
    return bodies if setup.get("body", "all") == "all" else [b for b in bodies if b.id == setup["body"]]


def turning_radius(win, setup, bodies):
    """The part's largest radius about the setup's spindle axis (cached per model + axis)."""
    i, center, _ = cam.turning_frame(bodies_bbox(bodies), setup)
    key = (id(win.model), tuple(b.id for b in bodies), setup["axis"])
    cache = win.__dict__.setdefault("_radius_cache", {})
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
        mr = rows(self.mill, [("Stock: sides", self.side), ("Stock width X", self.sx), ("Stock length Y", self.sy),
                              ("Stock height Z", self.sz), ("Stock: top", self.top), ("Stock: bottom", self.bottom),
                              ("WCS origin", self.mwcs)])
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
        for w in (self.body, self.mwcs, self.front, self.twcs):
            w.currentIndexChanged.connect(s.preview)
        self.axis.currentIndexChanged.connect(s.axis_changed)
        self.mode.currentIndexChanged.connect(s.mode_changed)

    def fit(self):
        self.layout().activate()
        self.resize(self.width(), self.sizeHint().height())


class SetupSession:
    """CAM → Setup: pick Milling or Turning, the part, stock and work zero. Also edits a setup."""
    captures_left = False

    def __init__(self, win, kind: str = cam.MILLING, edit: dict | None = None):
        self.win, self.vp = win, win.viewport
        self.edit_id = edit["id"] if edit else None
        self.panel = SetupPanel(self)
        p = self.panel
        self._loading = True
        n = len(win.doc.setups) + 1
        p.name.setText(edit["name"] if edit else f"Setup{n}")
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
            s.update(stock=stock, wcs=p.mwcs.currentData())
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
        ok = draw_setup(self.vp, self.win, self.setup(), "setup")
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
        problem = self.fit_problem()
        if problem:
            self.vp.show_toast(problem, bad=True)
            return
        self.win.commit_setup(self.setup(), self.edit_id)

    def on_move(self, w, ev):
        pass

    def on_click(self, w, ev):
        pass

    def on_key(self, ev) -> bool:
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.commit()
            return True
        if ev.key() == Qt.Key_Escape:
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


# ------------------------------------------------------------------ CAM operations (Face)
def op_moves(win, setup, op):
    """(WCS moves, world moves) for an operation; ([], []) when there's no part."""
    bodies = setup_bodies(win, setup)
    if not bodies:
        return [], []
    bbox = bodies_bbox(bodies)
    r = turning_radius(win, setup, bodies) if setup["type"] == cam.TURNING else 0.0
    moves = cam.face_toolpath(bbox, setup, op, r)
    return moves, cam.toolpath_world(bbox, setup, moves, r)


def draw_toolpath(vp, world, group="cam", dim=False):
    """Feeds blue, rapids yellow (thin), like Fusion."""
    feeds, rapids = [], []
    for (_k0, a), (k1, b) in zip(world, world[1:]):
        (feeds if k1 == "feed" else rapids).append([a, b])
    vp.add_lines(group, rapids, theme.WARN, 1.0, opacity=0.5 if dim else 0.8)
    vp.add_lines(group, feeds, theme.ACCENT, 1.4 if dim else 2.2, opacity=0.6 if dim else 1.0)


class OpPanel(Panel):
    FIELDS = {cam.MILLING: [("tool_dia", "Tool diameter", 4), ("stepover", "Stepover %", 1),
                            ("stepdown", "Max stepdown", 4), ("leave", "Stock to leave", 4),
                            ("rpm", "Spindle RPM", 0), ("feed", "Feed (in/min)", 2)],
              cam.TURNING: [("stepdown", "Max stepdown", 4), ("leave", "Stock to leave", 4),
                            ("past_center", "Past center (X)", 4), ("sfm", "Surface speed SFM", 0),
                            ("ipr", "Feed (in/rev)", 4), ("max_rpm", "Max RPM", 0)]}

    def __init__(self, session: "OpSession"):
        super().__init__("Face", 250)
        s = session
        self.setup = QComboBox()
        for st in s.win.doc.setups:
            self.setup.addItem(f"{st['name']} · {cam.TYPES[st['type']]}", st["id"])
        self.row("Setup", self.setup)
        self.name = self.row("Name", self.value(""))
        self.boxes = {}
        self.groups = {}
        for kind, fields in self.FIELDS.items():
            g = QWidget()
            lay = QVBoxLayout(g)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            items = []
            for key, label, dec in fields:
                nb = NumBox(0, dec)
                nb.setRange(0, 100000)
                nb.valueChanged.connect(s.preview)
                self.boxes[(kind, key)] = nb
                items.append((label, nb))
            if kind == cam.MILLING:
                self.direction = QComboBox()
                self.direction.addItem("Along X", "x")
                self.direction.addItem("Along Y", "y")
                self.direction.currentIndexChanged.connect(s.preview)
                items.insert(4, ("Cut direction", self.direction))
            for label, w in items:
                r = QWidget()
                r.setObjectName("panelRow")
                hl = QHBoxLayout(r)
                hl.setContentsMargins(10, 4, 10, 4)
                hl.addWidget(QLabel(label))
                hl.addStretch()
                hl.addWidget(w)
                lay.addWidget(r)
            self.v.addWidget(g)
            self.groups[kind] = g
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setStyleSheet(f"color:{theme.FG2};padding:4px 10px;")
        self.v.addWidget(self.info)
        _dlg_footer(self, s)
        self.setup.currentIndexChanged.connect(s.setup_changed)

    fit = SetupPanel.fit


class OpSession:
    """CAM → Face: pick the setup, set the cut, see the toolpath. Also edits an operation."""
    captures_left = False

    def __init__(self, win, setup_id: str | None, edit_id: str | None = None):
        self.win, self.vp = win, win.viewport
        self.edit_id = edit_id
        self.panel = OpPanel(self)
        p = self.panel
        self._loading = True
        if edit_id:
            st, op = win.doc.op(edit_id)
            setup_id = st["id"]
            p.setup.setEnabled(False)          # an op stays in its setup
        p.setup.setCurrentIndex(max(0, p.setup.findData(setup_id)))
        self._loading = False
        self.setup_changed(op=op if edit_id else None)

    def current_setup(self):
        return self.win.doc.setup(self.panel.setup.currentData())

    def setup_changed(self, *_, op=None):
        p = self.panel
        st = self.current_setup()
        op = op or cam.new_op(st)
        self._loading = True
        for (kind, key), box in p.boxes.items():
            if kind == st["type"] and key in op:
                box.setValue(op[key])
        if st["type"] == cam.MILLING:
            p.direction.setCurrentIndex(p.direction.findData(op.get("direction", "x")))
        names = {o["name"] for o in st.get("ops", [])}
        k = 1
        while f"Face{k}" in names:
            k += 1
        p.name.setText(op.get("name", f"Face{k}"))
        self._loading = False
        for kind, g in p.groups.items():
            g.setVisible(kind == st["type"])
        p.fit()
        self.vp.set_side(p)
        self.preview()

    def op(self) -> dict:
        p = self.panel
        st = self.current_setup()
        o = {"type": "face", "name": p.name.text()}
        for (kind, key), box in p.boxes.items():
            if kind == st["type"]:
                o[key] = box.value()
        if st["type"] == cam.MILLING:
            o["direction"] = p.direction.currentData()
        return o

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
            self.vp.render()
            return
        draw_toolpath(self.vp, world, "op")
        passes = sum(1 for (_a, p0), (k, p1) in zip(moves, moves[1:]) if k == "feed" and p0[2] != p1[2]) \
            if st["type"] == cam.MILLING else sum(1 for k, _p in moves if k == "feed")
        t = cam.cycle_time(moves, st, self.op())
        self.panel.info.setText(f"{passes} depth pass{'es' if passes != 1 else ''} · about {t:.1f} min cutting")
        self.win.message("FACE: blue = cutting, yellow = rapid · change values to update · Enter / OK saves · Esc cancels")
        self.vp.render()

    def commit(self):
        st = self.current_setup()
        try:
            cam.validate_op(st, self.op())
        except ValueError as exc:
            self.vp.show_toast(str(exc), bad=True)
            return
        self.win.commit_op(st["id"], self.op(), self.edit_id)

    def on_move(self, w, ev):
        pass

    def on_click(self, w, ev):
        pass

    def on_key(self, ev) -> bool:
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.commit()
            return True
        if ev.key() == Qt.Key_Escape:
            self.win.cancel_command()
            return True
        return False

    def ribbon_tool(self, label):
        if label == "Face":
            return
        self.win.cancel_command()
        self.win.run_tool(label)

    def close(self):
        self.vp.clear("op", render=False)


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
