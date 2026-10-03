"""Shared pieces of the interactive commands: the right-hand Panel (draggable, Esc closes),
number boxes, the right-click helper, OK / Cancel footer and pickable sketch regions.
"""
from __future__ import annotations


import numpy as np
import pyvista as pv
from PySide6.QtCore import QEvent, QObject, QPoint, Qt

from PySide6.QtWidgets import (QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from ..core.profiles import sketch_regions
from ..kernel import (triangles)
from . import theme



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
