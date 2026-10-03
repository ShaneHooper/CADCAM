"""Interactive commands: Sketch mode and Extrude (with their right-hand panels).

Each session receives mouse events from the Viewport (`on_move`, `on_click`) and keys
from the main window (`on_key`). They edit the Document only when committed.
"""
from __future__ import annotations

import math

import numpy as np
import pyvista as pv
from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer
from functools import partial

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit,
                               QPushButton, QScrollArea, QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ..core import cam, post, tools
from ..core import plane as pl
from ..core import sketch as sk
from ..core.profiles import region_at, sketch_regions
from ..kernel import (bodies_bbox, edge_list, max_radius, model_snap_points, outline_loops, turn_profile, turn_bore, turn_section, find_holes, slice_chains, chain_face, grown_chain, clearing_passes, extrude_tool, face_outline, planar_face_at, plane_edges, region_face, revolve_axis,
                      revolve_tool, triangles)
from . import icons, theme

TOOL_KEYS = {"Line": "line", "Rectangle": "rect", "Center Rect": "center_rect", "Circle": "circle",
             "Polygon": "polygon", "Point": "point", "Parallel to Axis": "xline", "Fillet": "fillet", "Chamfer": "chamfer",
             "Trim": "trim", "Rotate": "rotate", "Mirror": "mirror", "Pattern": "pattern"}
XFORM_TOOLS = ("rotate", "mirror", "pattern")
CORNER_TOOLS = ("fillet", "chamfer")
HINTS = {"line": "Click start, click end. Keep clicking to chain. Esc ends the chain.",
         "rect": "Click two opposite corners.", "center_rect": "Click center, then a corner.",
         "circle": "Click center, then a point on the circle.", "polygon": "Click center, then a vertex.",
         "point": "Click to place a point.",
         "xline": "Click an axis or a line, then click where the parallel line goes, or type the distance from it.",
         "fillet": "Click a sharp corner to round it (radius: Fillet R in the palette).",
         "chamfer": "Click a sharp corner to bevel it (Chamfer H × V in the palette).",
         "trim": "Click the piece to cut away: it goes back to the nearest crossing on each side (T).",
         "rotate": "Click the shapes to turn (click again to drop one), set the angle and center, OK.",
         "mirror": "Click the shapes to mirror, pick the mirror line (Y / X axis or a line), OK.",
         "pattern": "Click the shapes to copy, set circular (count, angle, center) or rectangular, OK."}
SNAP_PX = 8         # how close (screen px) the cursor must come to an end / mid / center to snap
ORTHO_DEG = 10      # a line within this many degrees of level / plumb is held straight (Ctrl: free)
SELECT_HINT = ("Click a line or shape (or its row in the palette) to type exact values; right-click a "
               "dimension to change it. Delete removes it. L line · R rectangle · C circle · P polygon · "
               "Enter finishes")


def mesh_of(shape) -> pv.PolyData:
    v, t = triangles(shape, 0.001, 0.2)
    return pv.PolyData(v, np.hstack([np.full((len(t), 1), 3), t]).ravel()) if len(t) else pv.PolyData()


class Panel(QFrame):
    """The prototype's right-hand panel: blue header, label/value rows, optional footer. Drag its
    blue title to move it; that spot is kept for panels of the same name while the app runs."""
    spots: dict = {}

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
        head.setCursor(Qt.SizeAllCursor)          # drag the blue title to move the panel
        head.setToolTip("Drag to move this panel")
        head.installEventFilter(self)
        self._drag = None
        self.user_pos = Panel.spots.get(title.upper())   # where it was dragged to (kept, also next time)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.pos()
            return True
        if t == QEvent.MouseMove and self._drag is not None and ev.buttons() & Qt.LeftButton:
            p = self.parentWidget()
            q = ev.globalPosition().toPoint() - self._drag
            if p is not None:                     # stays on the view
                q = QPoint(min(max(q.x(), 0), max(p.width() - self.width(), 0)),
                           min(max(q.y(), 0), max(p.height() - 40, 0)))
            self.move(q)
            self.user_pos = Panel.spots[self.title.text()] = q
            return True
        if t == QEvent.MouseButtonRelease and self._drag is not None:
            self._drag = None
            return True
        return super().eventFilter(obj, ev)

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

    def keyPressEvent(self, ev):
        """Esc from a checkbox / list / button in the panel closes it like Esc in the view."""
        if ev.key() == Qt.Key_Escape:
            _escape_to_window(self, ev)
            ev.accept()
            return
        super().keyPressEvent(ev)


def _escape_to_window(w, ev):
    """Esc in a panel (not undoing a half-typed value): the main window handles it as if pressed
    in the view - Rotate / a toolpath / Extrude... closes (Shane 10/2/26)."""
    win = w.window()
    if hasattr(win, "handle_key"):
        win.viewport.plotter.setFocus()
        win.handle_key(ev)


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
            typed = self.lineEdit().text() != self.textFromValue(self.value()) + self.suffix() and \
                self.lineEdit().text() != self.prefix() + self.textFromValue(self.value()) + self.suffix()
            self.setValue(self.value())     # drops the half-typed text
            self.clearFocus()
            if not typed:                   # nothing typed: Esc closes the panel / ends the command
                _escape_to_window(self, ev)
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


class _RightClick(QObject):
    """A combo box's open list: a right-click calls on_right(pos) instead of picking the item
    (Qt's list takes any button's release as a pick and closes). Left-click picks as usual."""

    def __init__(self, viewport, on_right):
        super().__init__(viewport)
        self.on_right = on_right
        viewport.installEventFilter(self)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick) \
                and ev.button() == Qt.RightButton:
            if t == QEvent.MouseButtonRelease:
                self.on_right(ev.position().toPoint())
            return True
        return t == QEvent.ContextMenu


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
        self.sides = QSpinBox()
        self.sides.setRange(3, 64)
        self.sides.setValue(6)
        self.sides.setButtonSymbols(QSpinBox.NoButtons)
        self.sides.setAlignment(Qt.AlignRight)
        self.sides.setFixedWidth(60)
        self.row("Polygon sides", self.sides)
        self.poly_size = QComboBox()             # how the drag sizes it: to a flat or to a corner
        self.poly_size.addItem("Across flats", True)
        self.poly_size.addItem("Across corners", False)
        self.poly_size.setToolTip("Drawing a polygon: the second click is the middle of a flat (across "
                                  "flats) or a corner (across corners). Both sizes can be typed after.")
        self.row("Polygon size", self.poly_size)
        self.corner = NumBox(0.125)
        self.corner.setRange(0.0001, 1000)
        self.corner.setToolTip("Radius for Fillet")
        self.row("Fillet R", self.corner)
        self.cham_h = NumBox(0.125)
        self.cham_h.setRange(0.0001, 1000)
        self.cham_h.setToolTip("Chamfer width along X (horizontal)")
        self.row("Chamfer H", self.cham_h)
        self.cham_v = NumBox(0.125)
        self.cham_v.setRange(0.0001, 1000)
        self.cham_v.setToolTip("Chamfer height along Y (vertical)")
        self.row("Chamfer V", self.cham_v)
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
            head = QLabel(f"{kind.upper()} · " + (("SIZE" if ent["type"] == "arc" else "LEGS") if ent.get("corner") else "FROM ORIGIN"))
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


class XformPanel(Panel):
    """Sketch Rotate / Mirror / Pattern: the values, and its own OK / CANCEL (cancel only puts
    the tool down; the sketch stays)."""

    def __init__(self, s: "SketchSession", kind: str):
        super().__init__({"rotate": "Rotate", "mirror": "Mirror", "pattern": "Pattern"}[kind], 270)
        self.kind = kind
        self.rows = {}

        def num(v, dec=4, lo=-100000.0, hi=100000.0):
            b = NumBox(v, dec)
            b.setRange(lo, hi)
            b.valueChanged.connect(lambda *_: s.xform_preview())
            return b

        def add(key, label, w):
            self.row(label, w)
            self.rows[key] = w.parentWidget()
            return w
        if kind == "pattern":
            self.type = add("type", "Pattern", QComboBox())
            self.type.addItem("Circular", "circular")
            self.type.addItem("Rectangular", "rect")
            self.type.currentIndexChanged.connect(lambda *_: (self.show_rows(), s.xform_preview()))
            self.count = add("count", "Count", num(6, 0, 2, 500))
            self.total = add("total", "Angle °", num(360.0, 3, -360, 360))
            self.total.setToolTip("360 = evenly all the way round · less = spread from the original to that angle")
            self.nx = add("nx", "Count X", num(3, 0, 1, 500))
            self.dx = add("dx", "Spacing X", num(1.0))
            self.ny = add("ny", "Count Y", num(1, 0, 1, 500))
            self.dy = add("dy", "Spacing Y", num(1.0))
        if kind == "rotate":
            self.angle = add("angle", "Angle °", num(90.0, 3, -360, 360))
        if kind == "mirror":
            self.about = add("about", "Mirror line", QComboBox())
            self.about.addItem("Y axis (vertical)", "y")
            self.about.addItem("X axis (horizontal)", "x")
            self.about.addItem("A line in the sketch", "line")
            self.about.currentIndexChanged.connect(lambda *_: s.mirror_about_changed())
            self.line_btn = QToolButton()
            self.line_btn.setObjectName("pickBtn")
            self.line_btn.setCheckable(True)
            self.line_btn.setIcon(icons.icon("cursor", theme.FG2))
            self.line_btn.setFixedSize(30, 24)
            self.line_btn.setToolTip("Click, then click the line to mirror across")
            self.line_btn.toggled.connect(lambda on: s.set_xpick("line" if on else None))
            add("line", "Pick the line", self.line_btn)
        if kind in ("rotate", "pattern"):
            self.center_btn = QToolButton()
            self.center_btn.setObjectName("pickBtn")
            self.center_btn.setCheckable(True)
            self.center_btn.setIcon(icons.icon("cursor", theme.FG2))
            self.center_btn.setFixedSize(30, 24)
            self.center_btn.setToolTip("Click, then click the center in the sketch (snaps to ends / centers)")
            self.center_btn.toggled.connect(lambda on: s.set_xpick("center" if on else None))
            add("center", "Center (pick)", self.center_btn)
            self.cx = add("cx", "Center X", num(0.0))
            self.cy = add("cy", "Center Y", num(0.0))
        if kind in ("rotate", "mirror"):
            self.copy = add("copy", "Keep original", QCheckBox("Copy"))
            self.copy.setChecked(kind == "mirror")
            self.copy.toggled.connect(lambda *_: (self.show_rows(), s.xform_preview()))
        if kind == "rotate":                     # Copy on: how many in all, equally spaced
            self.total_n = add("total_n", "Total (incl. original)", num(2, 0, 2, 500))
            self.total_n.setToolTip("4 = the original + 3 copies, 90° apart (the angle follows; type it to change)")
            self.total_n.valueChanged.connect(lambda v: self.angle.setValue(360.0 / max(int(v), 1)))
        self.info = QLabel("")                   # one line: a wrapping label sizes wrong (see SketchPalette.fit)
        self.info.setStyleSheet(f"color:{theme.FG2};padding:4px 10px;")
        self.v.addWidget(self.info)
        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(10, 6, 10, 6)
        fl.addStretch()
        cancel, ok = QPushButton("CANCEL"), QPushButton("OK")
        for b in (cancel, ok):
            b.setObjectName("dlgBtn")
            fl.addWidget(b)
        ok.setProperty("ok", True)
        cancel.clicked.connect(lambda: s.set_tool(None))
        ok.clicked.connect(s.xform_apply)
        self.v.addWidget(foot)
        self.show_rows()

    def show_rows(self):
        if self.kind == "pattern":
            circ = self.type.currentData() == "circular"
            for k in ("count", "total", "center", "cx", "cy"):
                self.rows[k].setVisible(circ)
            for k in ("nx", "dx", "ny", "dy"):
                self.rows[k].setVisible(not circ)
        if self.kind == "mirror":
            self.rows["line"].setVisible(self.about.currentData() == "line")
        if self.kind == "rotate":
            self.rows["total_n"].setVisible(self.copy.isChecked())
        self.adjustSize()
        self.setFixedHeight(self.sizeHint().height())


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
    shows_grid = True                        # the viewport draws its grid on this sketch's plane while it is open

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
        self.multi: list = []                # shapes picked with a selection box (Delete, Rotate / Mirror / Pattern)
        self.xpanel = None                   # Rotate / Mirror / Pattern panel while that tool is on
        self.picked: list = []               # entities those tools work on
        self.xpick = None                    # "center" / "line": the next click picks that
        self.xref = None                     # Parallel to Axis: (point, direction, name) of the line it runs parallel to
        self._xcur = None                    # ... and where the cursor last was: (u, v) and the screen spot
        self.mirror_line = None
        self.editor = DimEditor(self.vp)     # right-click a dimension: type its value in place
        self._plane_changed()

    def changed(self) -> bool:
        return (self.ents, self.plane_z) != self.start

    def _push(self):
        self.hist.append((list(self.ents), list(self.origin)))
        self.redo_stack.clear()

    def right_menu(self, gpos):
        """Right-click (no drag) while drawing: Done puts the drawing tool down (back to Select).
        In Select it stays as before (nothing; a right drag pans)."""
        if not self.tool or self.tool in XFORM_TOOLS:
            return
        m = QMenu(self.vp)
        m.addAction("Done", self._done_tool)    # ends a line chain and the tool, like Esc twice
        if self.pts:
            m.addAction("Cancel this shape", self._drop_shape)
        m.addSeparator()
        m.addAction("Finish Sketch", self.win.finish_sketch)
        m.exec(gpos)

    def _done_tool(self):
        self.set_tool(None)
        self.redraw()

    def _drop_shape(self):
        self.pts = []
        self.vp.clear("preview")
        self.vp.dim.hide()

    def box_ok(self) -> bool:
        """Left drag boxes shapes in Select and in Rotate / Mirror / Pattern (not while drawing)."""
        return (self.tool is None or self.tool in XFORM_TOOLS) and not self.xpick

    def on_box(self, rect, crossing: bool):
        """A selection box: left to right = shapes wholly inside, right to left = any it touches."""
        hits = [i for i, e in enumerate(self.ents)
                if self.vp.box_hit([[pl.to_world(self.frame, q, 0.0) for q in sk.entity_points(e)]], rect, crossing)]
        if self.tool in XFORM_TOOLS:
            self.picked += [i for i in hits if i not in self.picked]
            self.xform_preview()
            return
        if len(hits) == 1:
            self.select(hits[0])
            return
        self.select(None)
        self.multi = hits
        self.redraw()
        if hits:
            self.win.message(f"{len(hits)} shapes selected · Delete removes them · Rotate / Mirror / Pattern use them")

    def select(self, i: int | None):
        self.multi = []
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
            ents, origin, j = sk.edit(self.ents, self.origin, self.sel, key, box.value())
        except ValueError as exc:
            self.vp.show_toast(str(exc), bad=True)
            self.palette.refresh_values(e)
            box.blockSignals(True)
            box.setValue(sk.params(e)[key])
            box.blockSignals(False)
            return
        self._push()
        self.ents, self.origin = ents, origin
        if j != self.sel:                    # a chamfer re-cut: it is now the last entity
            self.select(j)
            return
        self.palette.refresh_values(ents[j])
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
        self._end_xform()
        self.tool = TOOL_KEYS.get(label) if label else None
        self.pts = []
        self.xref = None
        self.editor.hide()
        self.vp.clear("preview")
        self.vp.dim.hide()
        self.win.ribbon.set_active(label)
        name = label.upper() if label else "SELECT"
        head = f"EDIT {self.name.upper()}" if self.edit_id else "SKETCH"
        where = "XY PLANE" if pl.is_xy(self.frame) else "FACE PLANE"
        self.vp.show_banner(f"{head} · {where} · <span style='color:{theme.ACCENT}'>{name}</span>")
        self.win.message(HINTS.get(self.tool, SELECT_HINT))
        if self.tool in XFORM_TOOLS:
            self._start_xform()

    def _snap(self, w, ev):
        """Where a click lands: a snap point (end / mid / center of the sketch or of the part's
        edges on this plane) within SNAP_PX of the cursor beats the grid. The end of a line close
        to level / plumb is then held exactly straight from its start (Ctrl draws at any angle)."""
        p = self._snap_point(w, ev)
        self.ortho = None
        if self.tool == "line" and self.pts and not (ev is not None and ev.modifiers() & Qt.ControlModifier):
            s0 = self.pts[0]
            dx, dy = w[0] - s0[0], w[1] - s0[1]
            if math.hypot(dx, dy) > 1e-9:
                ang = abs(math.degrees(math.atan2(dy, dx))) % 180
                if min(ang, 180 - ang) <= ORTHO_DEG:
                    p, self.ortho = [p[0], s0[1]], "horizontal"
                elif abs(ang - 90) <= ORTHO_DEG:
                    p, self.ortho = [s0[0], p[1]], "vertical"
                if self.ortho and self.snap_hit and (abs(self.snap_hit[0] - p[0]) > 1e-9 or
                                                     abs(self.snap_hit[1] - p[1]) > 1e-9):
                    self.snap_hit = None          # held straight: lined up with the point, not on it
        return p

    def _snap_point(self, w, ev):
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
        others = [e for i, e in enumerate(self.ents) if i != self.sel and i not in self.multi]
        # a piece the G-code import only ASSUMED (a guessed nose radius or tool) is drawn in warning yellow
        solid = [e for e in others if e["type"] != "xline"]
        self.vp.add_lines("sketch", self._lines([e for e in solid if e.get("src") != "ASSUMED"]))
        self.vp.add_lines("sketch", self._lines([e for e in solid if e.get("src") == "ASSUMED"]), color=theme.WARN)
        # parallel lines are reference: thinner and quieter than the part line
        self.vp.add_lines("sketch", self._lines([e for e in others if e["type"] == "xline"], 0.002),
                          color=theme.FG2, width=1.0)
        if self.sel is not None:
            self.vp.add_lines("sel", self._lines([self.ents[self.sel]], 0.005), color=theme.FG, width=2.6)
        self.multi = [i for i in self.multi if 0 <= i < len(self.ents)]
        if self.multi:
            self.vp.add_lines("sel", self._lines([self.ents[i] for i in self.multi], 0.005), color=theme.FG, width=2.6)
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
        pal = self.palette
        size = sk.fmt(pal.corner.value()) if self.tool == "fillet" else \
            f"{sk.fmt(pal.cham_h.value())} H × {sk.fmt(pal.cham_v.value())} V"
        word = "R" if self.tool == "fillet" else "Chamfer"
        if hit:
            r = 6 * self.vp.pixel_size(pos)
            self.vp.add_lines("preview", self._lines([sk.circle(hit[0], r)]), color=theme.FG, width=2.0)
            self.vp.show_dim(f"{word} {size} · click to apply", pos)
        else:
            self.vp.show_dim(f"{word} {size} · move onto a sharp corner", pos)
        self.vp.render()

    def _trim_hover(self, w, pos):
        """Trim: the piece a click would cut away, in red."""
        self.vp.clear("preview", render=False)
        piece = sk.trim_preview(self.ents, w, 8 * self.vp.pixel_size(pos))
        if piece is not None:
            self.vp.add_lines("preview", self._lines([piece]), color=theme.BAD, width=3.0)
            self.vp.show_dim("Trim · click to cut this away", pos)
        else:
            self.vp.show_dim("Trim · move onto a line, arc or circle", pos)
        self.vp.render()

    def on_move(self, w, ev):
        if not self.tool:
            return
        pos = ev.position().toPoint()
        if self.tool in XFORM_TOOLS:
            if self.xpick == "center":
                p, what = self._center_pick(w, ev)
                self._mark_snap(p, pos)
                self.vp.show_dim(f"CENTER{what} X {sk.fmt(p[0])}  Y {sk.fmt(p[1])}", pos)
            else:
                self.vp.show_dim("click the mirror line" if self.xpick == "line" else
                                 f"{len(self.picked)} picked · click a shape to add / drop it", pos)
            self.vp.render()
            return
        if self.tool in CORNER_TOOLS:
            self._corner_hover(w, pos)
            return
        if self.tool == "trim":
            self._trim_hover(w, pos)
            return
        if self._xmode():
            self._xline_hover(w, ev)
            return
        p = self._snap(w, ev)
        self._mark_snap(p, pos)
        tag = f"  · {self.snap_hit[2].upper()}" if self.snap_hit else ""
        if getattr(self, "ortho", None):
            tag += f"  · {self.ortho.upper()}"
        if not self.pts or self.tool == "point":
            self.vp.show_dim(f"X {sk.fmt(p[0])}  Y {sk.fmt(p[1])}{tag}", pos)
            self.vp.render()
            return
        n, flats = self.palette.sides.value(), self.palette.poly_size.currentData()
        ent = sk.build_entity(self.tool, self.pts[0], p, n, flats)
        self.vp.clear("preview", render=False)
        if ent:
            self.vp.add_lines("preview", self._lines([ent]), opacity=0.45)
        self.vp.show_dim(sk.preview_label(self.tool, self.pts[0], p, n, flats) + tag, pos)
        self.vp.render()

    # ---- Parallel to Axis: click an axis (or a line), then the spot (or type the distance from it)
    def _xline_refs(self):
        """What a parallel line can run parallel to: (point, direction, name) for each axis, line and parallel line."""
        refs = [((0.0, 0.0), (1.0, 0.0), "X AXIS"), ((0.0, 0.0), (0.0, 1.0), "Y AXIS")]
        for e in self.ents:
            if e["type"] == "line" and not e.get("corner"):
                (x0, y0), (x1, y1) = e["pts"]
                if math.hypot(x1 - x0, y1 - y0) > 1e-9:
                    refs.append(((x0, y0), (x1 - x0, y1 - y0), "LINE"))
            elif e["type"] == "xline":
                refs.append((tuple(e["p"]), tuple(e["d"]), "PARALLEL LINE"))
        return refs

    def _xmode(self) -> bool:
        """Placing a parallel line: the Parallel to Axis tool, or the Line tool after a click on an axis."""
        return self.tool == "xline" or (self.tool == "line" and self.xref is not None)

    def _xline_ref_at(self, w, tol, axes_only=False):
        """The reference closest to the cursor within tol: axes and parallel lines are measured to their whole
        length, a line to the line itself."""
        best, hit = tol, None
        for p, d, name in self._xline_refs():
            if axes_only and not name.endswith("AXIS"):
                continue
            if name == "LINE":
                dist = sk.distance(sk.line(p, (p[0] + d[0], p[1] + d[1])), w)
            else:
                dist = abs(sk._cross2((d[0], d[1]), (w[0] - p[0], w[1] - p[1])))
            if dist <= best:
                best, hit = dist, (p, d, name)
        return hit

    def _xline_hover(self, w, ev):
        pos = ev.position().toPoint()
        self.vp.clear("preview", render=False)
        if self.xref is None:
            ref = self._xline_ref_at(w, 8 * self.vp.pixel_size(pos))
            if ref:
                p, d, _name = ref
                self.vp.add_lines("preview", self._lines([sk.xline(p, d)], 0.006), color=theme.ACCENT, width=2.0)
                self.vp.show_dim(f"Parallel to Axis · click to run parallel to the {ref[2]}", pos)
            else:
                self.vp.show_dim("Parallel to Axis · move onto an axis or a line", pos)
            self.vp.render()
            return
        p = self._snap_point(w, ev)
        self._xcur = (p, pos)
        ent, off = sk.xline_offset(self.xref[0], self.xref[1], p)
        self._mark_snap(p, pos)
        self.vp.add_lines("preview", self._lines([ent], 0.006), opacity=0.6)
        self.vp.show_dim(f"{sk.fmt(abs(off))} from the {self.xref[2]} · click to place · type a number", pos)
        self.vp.render()

    def _xline_click(self, w, ev):
        pos = ev.position().toPoint()
        if self.xref is None:
            ref = self._xline_ref_at(w, 8 * self.vp.pixel_size(pos), axes_only=self.tool == "line")
            if ref is None:
                self.vp.show_toast("Click an axis or a line to run a line parallel to it", bad=True)
                return
            self.xref = ref
            self.win.message(f"Parallel to the {ref[2]}: click where it goes, or type the distance from it "
                             "(on the side the cursor is) · Esc picks another")
            self._xline_hover(w, ev)
            return
        p = self._snap(w, ev)
        ent, _off = sk.xline_offset(self.xref[0], self.xref[1], p)
        self._place_xline(ent)

    def _place_xline(self, ent):
        self.xref = None
        self.vp.clear("preview", render=False)
        self.vp.clear("snapmark", render=False)
        self.vp.dim.hide()
        self._add(ent)
        self.win.message(HINTS[self.tool])

    def _xline_type(self, first: str):
        """A digit typed with a reference picked: the distance box opens at the cursor."""
        if self._xcur is None:
            return
        side, pos = self._xcur
        ref = self.xref

        def apply(value):
            if self.xref is not ref:
                return                                           # (0 is a distance too: right on the axis / line)
            _e, off = sk.xline_offset(ref[0], ref[1], side)
            n = (-ref[1][1], ref[1][0])
            n = (n[0] / math.hypot(*n), n[1] / math.hypot(*n))
            signed = value * (1.0 if off >= 0 else -1.0)         # a minus sign: the other side
            self._place_xline(sk.xline((ref[0][0] + signed * n[0] + 0.0, ref[0][1] + signed * n[1] + 0.0), ref[1]))
            self.vp.plotter.setFocus()
        self.editor.open("Distance", 0.0, 4, pos, apply)
        le = self.editor.box.lineEdit()
        le.setText(first)
        le.deselect()
        le.setCursorPosition(len(first))

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
            ents, origin, j = sk.edit(self.ents, self.origin, i, key, value)
        except ValueError as exc:
            self.vp.show_toast(str(exc), bad=True)
            return
        self._push()
        self.ents, self.origin = ents, origin
        self.select(j)                       # palette fields follow, view redraws
        self.vp.plotter.setFocus()

    def on_click(self, w, ev):
        self.vp.plotter.setFocus()           # take keys back from a palette field
        if not self.tool:                    # select mode: pick what's under the cursor
            pos = ev.position().toPoint()
            self.select(sk.nearest(self.ents, w, 8 * self.vp.pixel_size(pos)))
            return
        if self.tool in XFORM_TOOLS:
            self.xform_click(w, ev)
            return
        if self.tool in CORNER_TOOLS:
            pos = ev.position().toPoint()
            try:
                pal = self.palette
                size = pal.corner.value() if self.tool == "fillet" else (pal.cham_h.value(), pal.cham_v.value())
                ents, origin = sk.corner_op(self.ents, self.origin, w, size, self.tool,
                                            12 * self.vp.pixel_size(pos))
            except ValueError as exc:
                self.vp.show_toast(str(exc), bad=True)
                return
            self._push()
            self.ents, self.origin = ents, origin
            self.select(len(self.ents) - 1)  # the new arc / bevel line: its values show
            self._corner_hover(w, pos)
            return
        if self.tool == "trim":
            pos = ev.position().toPoint()
            try:
                ents, origin = sk.trim(self.ents, self.origin, w, 8 * self.vp.pixel_size(pos))
            except ValueError as exc:
                self.vp.show_toast(str(exc), bad=True)
                return
            self._push()
            self.ents, self.origin = ents, origin
            self.select(None)
            self._trim_hover(w, pos)
            return
        if self._xmode():
            self._xline_click(w, ev)
            return
        p = self._snap(w, ev)
        if self.tool == "line" and not self.pts and self.snap_hit is None:
            axis = self._xline_ref_at(w, 8 * self.vp.pixel_size(ev.position().toPoint()), axes_only=True)
            if axis:                                   # Line tool, first click on an axis: a line parallel to it
                self._xline_click(w, ev)               # follows the cursor until it is placed (or a number typed)
                return
        if self.tool == "point":
            self._add(sk.point(p))
            return
        if not self.pts:
            self.pts = [p]
            return
        ent = sk.build_entity(self.tool, self.pts[0], p, self.palette.sides.value(), self.palette.poly_size.currentData())
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
        if self._xmode() and ev.text() and ev.text() in "0123456789.-" \
                and not ev.modifiers() & Qt.ControlModifier:
            self._xline_type(ev.text())
            return True
        if k == Qt.Key_Escape:
            if self.pts:
                self.pts = []
                self.vp.clear("preview")
                self.vp.dim.hide()
            elif self.xref is not None:
                self.xref = None
                self.vp.clear("preview")
                self.vp.dim.hide()
                self.win.message(HINTS[self.tool])
            elif self.tool:
                self.set_tool(None)
            else:
                self.select(None)
        elif k in (Qt.Key_Return, Qt.Key_Enter) and self.tool in XFORM_TOOLS:
            self.xform_apply()
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self.win.finish_sketch()
        elif k == Qt.Key_Z and ev.modifiers() & Qt.ControlModifier:
            self.undo()
        elif k == Qt.Key_Y and ev.modifiers() & Qt.ControlModifier:
            self.redo()
        elif k in (Qt.Key_Delete, Qt.Key_Backspace) and self.multi:
            self._push()
            gone = set(self.multi)
            self.ents = [e for i, e in enumerate(self.ents) if i not in gone]
            self.origin = [o for i, o in enumerate(self.origin) if i not in gone]
            self.select(None)
            self.redraw()
            self.vp.show_toast(f"{len(gone)} shapes deleted · Ctrl+Z brings them back")
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
        elif k == Qt.Key_T:
            self.set_tool("Trim")
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

    # ---- Rotate / Mirror / Pattern: pick shapes, set values, OK
    def _start_xform(self):
        self.picked = list(self.multi) or ([self.sel] if self.sel is not None else [])
        self.xpick, self.mirror_line = None, None
        self.xpanel = XformPanel(self, self.tool)
        self.vp.set_side(self.xpanel)
        self.xform_preview()

    def _end_xform(self):
        if self.xpanel is None:
            return
        self.xpanel.hide()
        self.xpanel.deleteLater()
        self.xpanel, self.picked, self.xpick = None, [], None
        self.vp.clear("xform", render=False)
        self.vp.clear("snapmark", render=False)
        self.vp.dim.hide()
        self.vp.set_side(self.palette)
        self.redraw()

    def set_xpick(self, what):
        self.xpick = what

    def _center_pick(self, w, ev):
        """Where a center pick lands: on a circle / arc / polygon, ITS center (Shane: clicking the
        circle means turn about its middle, not the spot clicked); else the usual snap."""
        i = sk.nearest(self.ents, w, 8 * self.vp.pixel_size(ev.position().toPoint()))
        if i is not None and self.ents[i]["type"] in ("circle", "arc", "polygon"):
            e = self.ents[i]
            c = e["c"] if "c" in e else sk.params(e)
            c = [c["x"], c["y"]] if isinstance(c, dict) else list(c)
            return c, f" OF {sk.entity_label(e)[0].upper()}"
        return self._snap(w, ev), ""

    def clear_selection(self):
        """The view bar's trash button: drop what's selected / picked (shapes stay)."""
        self.multi = []
        if self.xpanel is not None:              # Rotate / Mirror / Pattern stays open, nothing picked
            self.picked = []
            self.sel = None
            self.redraw()
            self.xform_preview()
            return
        self.select(None)
        self.redraw()

    def mirror_about_changed(self):
        self.xpanel.show_rows()
        if self.xpanel.about.currentData() == "line" and self.mirror_line is None:
            self.xpanel.line_btn.setChecked(True)
        self.xform_preview()

    def xform_click(self, w, ev):
        pos = ev.position().toPoint()
        p = self.xpanel
        if self.xpick == "center":
            q, _what = self._center_pick(w, ev)
            p.cx.setValue(q[0])
            p.cy.setValue(q[1])
            p.center_btn.setChecked(False)
            self.vp.clear("snapmark", render=False)
        elif self.xpick == "line":
            i = sk.nearest(self.ents, w, 8 * self.vp.pixel_size(pos))
            if i is None or self.ents[i]["type"] != "line":
                self.vp.show_toast("Click a line to mirror across", bad=True)
                return
            self.mirror_line = list(self.ents[i]["pts"])
            if i in self.picked:
                self.picked.remove(i)
            p.line_btn.setChecked(False)
        else:
            i = sk.nearest(self.ents, w, 8 * self.vp.pixel_size(pos))
            if i is None:
                return
            if i in self.picked:
                self.picked.remove(i)
            else:
                self.picked.append(i)
        self.xform_preview()

    def _xform_result(self):
        """(ents, origin) after the tool, or raises ValueError (nothing picked, no line...)."""
        if not self.picked:
            raise ValueError("Click the shapes to " + self.tool + " first")
        p, kind = self.xpanel, self.tool
        src = [self.ents[i] for i in self.picked]
        if kind == "pattern":
            if p.type.currentData() == "circular":
                new = sk.circular_pattern(src, (p.cx.value(), p.cy.value()), int(p.count.value()), p.total.value())
            else:
                new = sk.rect_pattern(src, int(p.nx.value()), p.dx.value(), int(p.ny.value()), p.dy.value())
            return self.ents + new, self.origin + [None] * len(new)
        if kind == "rotate":
            def f(es):
                return sk.rotated(es, (p.cx.value(), p.cy.value()), p.angle.value())
        else:
            about = p.about.currentData()
            if about == "line" and self.mirror_line is None:
                raise ValueError("Pick the line to mirror across")
            a, b = {"y": ((0, 0), (0, 1)), "x": ((0, 0), (1, 0))}.get(about) or self.mirror_line

            def f(es):
                return sk.mirrored(es, a, b)
        if p.copy.isChecked():
            if kind == "rotate":                 # Total: the original + copies, each one more angle round
                c, a = (p.cx.value(), p.cy.value()), p.angle.value()
                new = [q for k in range(1, int(p.total_n.value())) for q in sk.rotated(src, c, a * k)]
            else:
                new = f(src)
            return self.ents + new, self.origin + [None] * len(new)
        ents, origin = [], []
        for i, e in enumerate(self.ents):
            if i in self.picked:
                moved = f([e])
                ents += moved
                origin += [self.origin[i]] * len(moved)
            else:
                ents.append(e)
                origin.append(self.origin[i])
        return ents, origin

    def xform_preview(self):
        if self.xpanel is None:
            return
        self.vp.clear("xform", render=False)
        picked = [self.ents[i] for i in self.picked if 0 <= i < len(self.ents)]
        if picked:
            self.vp.add_lines("xform", self._lines(picked, 0.005), color=theme.ACCENT, width=3.0)
        if self.tool == "mirror" and self.xpanel.about.currentData() == "line" and self.mirror_line:
            self.vp.add_lines("xform", self._lines([sk.line(*self.mirror_line)], 0.006), color=theme.WARN, width=2.0)
        try:
            ents, _o = self._xform_result()
            old = {id(e) for e in self.ents}
            new = [e for e in ents if id(e) not in old]
            self.vp.add_lines("xform", self._lines(new, 0.004), color=theme.ACCENT, width=1.6, opacity=0.55)
            self.xpanel.info.setText(f"{len(self.picked)} picked · {len(new)} new · Enter applies")
        except ValueError as exc:
            self.xpanel.info.setText(str(exc))
        self.xpanel.info.setToolTip(self.xpanel.info.text())
        self.vp.render()

    def xform_apply(self):
        try:
            ents, origin = self._xform_result()
        except ValueError as exc:
            self.vp.show_toast(str(exc), bad=True)
            return
        self._push()
        self.ents, self.origin = ents, origin
        self.set_tool(None)                  # back to Select, the palette back
        self.select(None)

    def close(self):
        if self.xpanel is not None:
            self.xpanel.hide()
            self.xpanel.deleteLater()
            self.xpanel = None
        for g in ("xform",):
            self.vp.clear(g, render=False)
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
def _point_segment(p, a, b) -> float:
    """Distance from point p to the segment a-b (sketch coordinates)."""
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


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
    key = ("holes", id(win.model), tuple(b.id for b in bodies))
    cache = win.__dict__.setdefault("_radius_cache", {})
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
    cache = win.__dict__.setdefault("_radius_cache", {})
    faces = []
    for c in o["islands"]:
        f = None if c.get("sketch") else chain_face(bodies, c)
        faces.append(f if f is not None else c["pts"])
    out = []
    for z, act in cam.mill_rough_layers(bbox, setup, o):
        key = ("rough", id(win.model), json.dumps([o["islands"][i] for i in act], sort_keys=True),
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
        key = ("outline", id(win.model), tuple(b.id for b in bodies), round(grow, 6))
        cache = win.__dict__.setdefault("_radius_cache", {})
        if key not in cache:
            cache[key] = outline_loops(bodies, grow)
        loops = cache[key]
    profile = None
    if op.get("type") in ("rough", "finish") and setup["type"] == cam.TURNING:   # OD (or ID: bore) silhouette
        i, center, _ = cam.turning_frame(bbox, setup)
        inner = bool(op.get("internal"))
        key = ("bore" if inner else "profile", id(win.model), tuple(b.id for b in bodies), setup["axis"])
        cache = win.__dict__.setdefault("_radius_cache", {})
        if key not in cache:
            cache[key] = (turn_bore if inner else turn_profile)(bodies, center, cam._unit(i))
        profile = cache[key]
    if op.get("type") == "groove":              # the part cut through the axis: grooves on OD / ID / face
        i, center, _ = cam.turning_frame(bbox, setup)
        key = ("section", id(win.model), tuple(b.id for b in bodies), setup["axis"])
        cache = win.__dict__.setdefault("_radius_cache", {})
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
        key = ("chains", id(self.win.model), tuple(b.id for b in bodies))
        cache = self.win.__dict__.setdefault("_radius_cache", {})
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


# ------------------------------------------------------------------ post process (G-code)
class ToolLibraryDialog(QDialog):
    """CAM → Tool Library: the tools operations pick from (one list per machine). Every change
    is saved to the library file right away; operations copy the tool they use."""

    def __init__(self, win, machine: str = cam.MILLING, new_kind: str | None = None, select: str | None = None):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Tool Library")
        self.resize(640, 380)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        top = QHBoxLayout()
        self.machine = QComboBox()
        for k in (cam.MILLING, cam.TURNING):
            self.machine.addItem(cam.TYPES[k], k)
        self.machine.setCurrentIndex(self.machine.findData(machine))
        top.addWidget(QLabel("Machine"))
        top.addWidget(self.machine)
        top.addStretch()
        v.addLayout(top)
        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumWidth(260)
        body.addWidget(self.list, 1)
        form = QGridLayout()
        self.number = QSpinBox()
        self.number.setRange(1, 99)
        self.number.setPrefix("T")
        self.name = QLineEdit()
        self.kind = QComboBox()
        self.dia = NumBox(0.25, 4)
        self.dia.setRange(0, 100)
        self.nose = NumBox(0.0, 4)
        self.nose.setRange(0, 10)
        self.form, self._labels = form, {}
        for row, (label, w) in enumerate((("Number", self.number), ("Name", self.name), ("Type", self.kind),
                                          ("Diameter", self.dia), ("Nose radius", self.nose))):
            lb = QLabel(label)
            self._labels[id(w)] = [lb]
            form.addWidget(lb, row, 0)
            form.addWidget(w, row, 1)
        self.err = QLabel("")
        self.err.setStyleSheet(f"color:{theme.BAD};")
        self.err.setWordWrap(True)
        form.addWidget(self.err, 5, 0, 1, 2)
        form.setRowStretch(6, 1)
        body.addLayout(form, 1)
        v.addLayout(body, 1)
        foot = QHBoxLayout()
        self.add, self.delete, done = QPushButton("NEW TOOL"), QPushButton("DELETE"), QPushButton("CLOSE")
        for b in (self.add, self.delete, done):
            b.setObjectName("dlgBtn")
        foot.addWidget(self.add)
        foot.addWidget(self.delete)
        foot.addStretch()
        foot.addWidget(done)
        v.addLayout(foot)
        self.machine.currentIndexChanged.connect(lambda *_: self.fill())
        self.list.currentRowChanged.connect(self.show_tool)
        for sig in (self.number.valueChanged, self.name.editingFinished, self.kind.currentIndexChanged,
                    self.dia.valueChanged, self.nose.valueChanged):
            sig.connect(self.store)
        self.add.clicked.connect(lambda: self.new_tool())
        self.delete.clicked.connect(self.remove)
        done.clicked.connect(self.accept)
        self._busy = False
        self.fill(select=select)
        if new_kind:
            self.new_tool(new_kind)

    def tools_here(self):
        return sorted((t for t in self.win.tool_lib if t["machine"] == self.machine.currentData()),
                      key=lambda t: (t["number"], t["name"]))

    def fill(self, select: str | None = None):
        self._busy = True
        m = self.machine.currentData()
        self.kind.clear()
        for k in tools.MACHINE_KINDS[m]:
            self.kind.addItem(tools.KINDS[k], k)
        self.list.clear()
        for t in self.tools_here():
            it = QListWidgetItem(tools.describe(t))
            it.setData(Qt.UserRole, t["id"])
            self.list.addItem(it)
        self._busy = False
        ids = [t["id"] for t in self.tools_here()]
        self.list.setCurrentRow(ids.index(select) if select in ids else (0 if ids else -1))
        if not ids:
            self.show_tool(-1)

    def current(self):
        it = self.list.currentItem()
        tid = it.data(Qt.UserRole) if it else None
        return next((t for t in self.win.tool_lib if t["id"] == tid), None)

    def show_tool(self, _row):
        t = self.current()
        self._busy = True
        for w in (self.number, self.name, self.kind, self.dia, self.nose, self.delete):
            w.setEnabled(t is not None)
        if t:
            self.number.setValue(t["number"])
            self.name.setText(t["name"])
            self.kind.setCurrentIndex(max(0, self.kind.findData(t["kind"])))
            self.dia.setValue(t["dia"])
            self.nose.setValue(t["nose_r"])
        self.err.setText("")
        self._busy = False
        self.show_sizes()

    def store(self, *_):
        """A field changed: check the tool, put it in the library and save."""
        t = self.current()
        if self._busy or t is None:
            return
        try:
            new = tools.validate({**t, "number": self.number.value(), "name": self.name.text().strip(),
                                  "kind": self.kind.currentData(), "dia": self.dia.value(),
                                  "nose_r": self.nose.value()})
        except ValueError as exc:
            self.err.setText(str(exc))
            return
        self.err.setText("")
        renumbered = new["number"] != t["number"]
        t.update(new)
        self.win.save_tool_lib()
        self.list.currentItem().setText(tools.describe(t))
        self.show_sizes()
        if renumbered:
            self.fill(select=t["id"])              # keep the list in T-number order

    def show_sizes(self):
        """Diameter for mills / drills, nose radius for turning inserts."""
        insert = self.kind.currentData() == "od turn"
        for w, show in ((self.dia, not insert), (self.nose, insert)):
            w.setVisible(show)
            for lb in self._labels.get(id(w), []):
                lb.setVisible(show)
        self._labels[id(self.dia)][0].setText("Width" if self.kind.currentData() == "groove" else "Diameter")

    def new_tool(self, kind: str | None = None):
        m = self.machine.currentData()
        kind = kind or tools.MACHINE_KINDS[m][0]
        used = {t["number"] for t in self.tools_here()}
        n = next(k for k in range(1, 100) if k not in used) if len(used) < 99 else 1
        t = tools.validate({"id": tools.new_id(self.win.tool_lib), "number": n, "name": f"New {tools.KINDS[kind]}",
                            "kind": kind, "machine": m,
                            "dia": {"od turn": 0.0, "groove": 0.125}.get(kind, 0.25),
                            "nose_r": 0.031 if kind == "od turn" else 0.0})
        self.win.tool_lib.append(t)
        self.win.last_new_tool = t["id"]
        self.win.save_tool_lib()
        self.fill(select=t["id"])
        self.name.setFocus()
        self.name.selectAll()

    def remove(self):
        t = self.current()
        if t is None:
            return
        self.win.tool_lib.remove(t)
        self.win.save_tool_lib()
        self.fill()


class PostDialog(QDialog):
    """CAM → Post Process: a setup's operations as G-code. Preview, then Save .nc."""

    def __init__(self, win, setup_id: str | None = None):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Post Process · G-code")
        self.resize(720, 640)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        top = QHBoxLayout()
        self.setup = QComboBox()
        for st in win.doc.setups:
            n = len(st.get("ops", []))
            self.setup.addItem(f"{st['name']} · {cam.TYPES[st['type']]} · {n} op{'s' if n != 1 else ''}", st["id"])
        self.setup.setCurrentIndex(max(0, self.setup.findData(setup_id)))
        self.control = QComboBox()
        for k, label in post.CONTROLLERS.items():
            self.control.addItem(label, k)
        self.program = QSpinBox()
        self.program.setRange(1, 9999)
        self.program.setPrefix("O")
        self.program.setButtonSymbols(QSpinBox.NoButtons)
        self.offset = QComboBox()
        self.offset.addItems(post.OFFSETS)
        self.coolant = QCheckBox("Coolant (M08)")
        self.comp = QComboBox()                         # cutter comp for a lathe Contour: off / machine / computer
        for k, label in post.COMPS.items():
            self.comp.addItem(label, k)
        self.comp.setToolTip("Lathe Contour only.\nOff: the part line point to point.\nMachine: the same points with "
                             "G41 / G42 and G40, the control compensates.\nComputer: no G41 / G42 / G40; the points "
                             "carry the tool nose radius.")
        for label, w in (("Setup", self.setup), ("Control", self.control), ("Program", self.program),
                         ("Work offset", self.offset), ("Cutter comp", self.comp)):
            top.addWidget(QLabel(label))
            top.addWidget(w)
        top.addWidget(self.coolant)
        top.addStretch()
        v.addLayout(top)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setStyleSheet(f"font-family:'{theme.MONO[0]}','Consolas',monospace;font-size:12px;"
                                f"background:{theme.BG};color:{theme.FG};")
        v.addWidget(self.text, 1)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{theme.FG2};")
        self.status.setWordWrap(True)                   # a left-out op's reason can be long
        foot = QHBoxLayout()
        foot.addWidget(self.status, 1)
        close, save = QPushButton("CLOSE"), QPushButton("SAVE .NC…")
        for b in (close, save):
            b.setObjectName("dlgBtn")
            foot.addWidget(b)
        save.setProperty("ok", True)
        close.clicked.connect(self.reject)
        save.clicked.connect(self.save)
        v.addLayout(foot)
        self.setup.currentIndexChanged.connect(self.load_settings)
        for w in (self.control, self.offset, self.comp):
            w.currentIndexChanged.connect(self.refresh)
        self.program.valueChanged.connect(self.refresh)
        self.coolant.toggled.connect(self.refresh)
        self.load_settings()

    def current(self):
        return self.win.doc.setup(self.setup.currentData())

    def load_settings(self, *_):
        """Each setup remembers its post settings (saved in the .gcad file)."""
        st = self.current()
        i = self.win.doc.setups.index(st)
        ps = st.get("post", {"controller": "haas", "program": 1000 + i, "offset": "G54", "coolant": True})
        for w in (self.control, self.offset, self.program, self.coolant, self.comp):
            w.blockSignals(True)
        self.control.setCurrentIndex(max(0, self.control.findData(ps["controller"])))
        self.offset.setCurrentText(ps["offset"])
        self.program.setValue(int(ps["program"]))
        self.coolant.setChecked(bool(ps["coolant"]))
        self.comp.setCurrentIndex(max(0, self.comp.findData(ps.get("comp", "off"))))
        self.comp.setEnabled(st["type"] == cam.TURNING)       # a lathe thing: greyed out (not hidden) on a mill
        for w in (self.control, self.offset, self.program, self.coolant, self.comp):
            w.blockSignals(False)
        self.refresh()

    def settings(self) -> dict:
        return {"controller": self.control.currentData(), "program": self.program.value(),
                "offset": self.offset.currentText(), "coolant": self.coolant.isChecked(),
                "comp": self.comp.currentData() if self.comp.isEnabled() else "off"}

    def gcode(self) -> str:
        """The setup's program. An op that can't make a toolpath (a Groove with no groove on
        the part, a Drill with no hole...) is left out and named in self.skipped, instead of
        blanking the whole program (Shane 10/1/26)."""
        st = self.current()
        ops, self.skipped, self.minutes = [], [], 0.0
        for o in st.get("ops", []):
            try:
                mv = op_moves(self.win, st, o)[0]
            except ValueError as exc:
                self.skipped.append(f"{o.get('name', 'op')}: {exc}")
                continue
            if o.get("type") == "finish" and "nose_r" not in o:      # an older op: the library's nose radius
                t = tools.find(self.win.tool_lib, o, st["type"], "finish")
                o = {**o, "nose_r": t["nose_r"] if t else 0.0}
            ops.append((o, mv))
            self.minutes += cam.cycle_time(mv, st, o)
        if not ops:
            raise ValueError("Nothing to post · " + (" · ".join(self.skipped) if self.skipped else
                                                     "this setup has no toolpaths yet"))
        ps = self.settings()
        g = post.post_setup(st, ops, ps["controller"], ps["program"], ps["offset"], ps["coolant"],
                            self.win.doc.name, ps["comp"])
        if self.skipped:                              # say so at the top of the program too
            lines = g.splitlines()
            note = [post._comment("NOT POSTED - " + s) for s in self.skipped]
            g = "\n".join(lines[:2] + note + lines[2:]) + ("\n" if g.endswith("\n") else "")
        return g

    def refresh(self, *_):
        try:
            g = self.gcode()
        except ValueError as exc:
            self.text.setPlainText("")
            self.status.setText(str(exc))
            return
        self.text.setPlainText(g)
        n = len(g.splitlines())
        skipped = f" · LEFT OUT: {' · '.join(self.skipped)}" if self.skipped else ""
        self.status.setText(f"{n} lines · about {self.minutes:.1f} min cutting{skipped}")
        self.status.setStyleSheet(f"color:{theme.WARN if self.skipped else theme.FG2};")

    def save(self):
        try:
            g = self.gcode()
        except ValueError as exc:
            self.win.viewport.show_toast(str(exc), bad=True)
            return
        st = self.current()
        name = f"O{self.program.value():04d} {self.win.doc.name} {st['name']}.nc"
        base = str(self.win.path.parent / name) if getattr(self.win, "path", None) else name
        path, _ = QFileDialog.getSaveFileName(self, "Save G-code", base, "G-code (*.nc *.tap *.txt);;All files (*)")
        if not path:
            return
        with open(path, "w", newline="\r\n") as fh:      # CRLF: what Windows DNC / USB loaders expect
            fh.write(g)
        if st.get("post") != self.settings():
            st["post"] = self.settings()
            self.win.dirty = True
            self.win.topbar.set_doc(self.win.doc.name, True)
        self.win.viewport.show_toast(f"G-code saved · {path.replace(chr(92), '/').split('/')[-1]}")
        self.status.setText(f"Saved {path}")


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
