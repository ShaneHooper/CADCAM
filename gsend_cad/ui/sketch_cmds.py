"""Sketch mode: drawing tools, the palette, exact-value / dimension editing, trim, corner
fillet / chamfer, Rotate / Mirror / Pattern (XformPanel) and picking the sketch plane.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from functools import partial

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ..core import plane as pl
from ..core import sketch as sk
from ..kernel import (face_outline, planar_face_at, plane_edges)
from . import icons, theme
from .cmd_base import NumBox, Panel


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
