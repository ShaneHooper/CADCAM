"""Top bar, ribbon, browser + properties, status bar and timeline (the prototype's layout)."""
from __future__ import annotations

import getpass
from functools import partial

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QPolygon
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy,
                               QStackedWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import APP_NAME
from . import icons, theme

# ribbon: tab -> [(group, [(icon, label)])]. Mesh, Sheet Metal and Plastic are left out on purpose.
RIBBON = {
    "solid": [("Create", [("sketch", "Sketch"), ("box", "Box"), ("cyl", "Cylinder"), ("extrude", "Extrude"),
                          ("revolve", "Revolve"), ("hole", "Hole"), ("thread", "Thread")]),
              ("Modify", [("press", "Press Pull"), ("fillet", "Fillet"), ("chamfer", "Chamfer"), ("shell", "Shell"),
                          ("combine", "Combine"), ("move", "Move")]),
              ("Assemble", [("comp", "New Comp"), ("joint", "Joint")]),
              ("Construct", [("plane", "Plane"), ("axis", "Axis"), ("pt", "Point")]),
              ("Inspect", [("measure", "Measure"), ("section", "Section")]),
              ("Insert", [("insert", "Insert")]),
              ("Select", [("select", "Select")])],
    "surface": [("Create", [("sketch", "Sketch"), ("extrude", "Extrude"), ("revolve", "Revolve"), ("plane", "Patch")]),
                ("Modify", [("fillet", "Fillet"), ("combine", "Stitch"), ("section", "Trim")]),
                ("Select", [("select", "Select")])],
    "util": [("Make", [("insert", "3D Print"), ("box", "Export")]),
             ("Add-Ins", [("pt", "Scripts")]),
             ("Select", [("select", "Select")])],
    "sketch": [("Create", [("line", "Line"), ("rect", "Rectangle"), ("crect", "Center Rect"), ("circle", "Circle"),
                           ("poly", "Polygon")]),
               ("Modify", [("undo", "Undo"), ("trash", "Clear")]),
               ("Inspect", [("measure", "Measure")]),
               ("Finish", [("finish", "Finish Sketch")])],
}
TABS = [("solid", "Solid"), ("surface", "Surface"), ("util", "Utilities"), ("sketch", "Sketch")]


def hbox(w=None, margins=(0, 0, 0, 0), spacing=0):
    lay = QHBoxLayout(w)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


def vbox(w=None, margins=(0, 0, 0, 0), spacing=0):
    lay = QVBoxLayout(w)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


class TopBar(QFrame):
    save = Signal()
    open = Signal()
    undo = Signal()
    redo = Signal()

    def __init__(self, fonts):
        super().__init__()
        self.setObjectName("topbar")
        self.setFixedHeight(34)
        lay = hbox(self, (10, 0, 10, 0), 6)
        # the G00 logo (blue graffiti G, white 00) then the product label
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(30))
        logo.setToolTip(APP_NAME)
        cad = QLabel("CAM")
        cad.setObjectName("brandCad")
        lay.addWidget(logo)
        lay.addWidget(cad)
        lay.addSpacing(8)
        for name, sig, tip in (("open", self.open, "Open (Ctrl+O)"), ("save", self.save, "Save (Ctrl+S)"),
                               ("undo", self.undo, "Undo (Ctrl+Z)"), ("redo", self.redo, "Redo (Ctrl+Y)")):
            b = QToolButton()
            b.setObjectName("ico")
            b.setIcon(icons.icon(name, theme.FG2, theme.FG, 15))
            b.setFixedSize(26, 26)
            b.setToolTip(tip)
            b.clicked.connect(sig.emit)
            lay.addWidget(b)
        sep = QFrame()
        sep.setObjectName("sep")
        sep.setFixedSize(1, 18)
        lay.addSpacing(4)
        lay.addWidget(sep)
        lay.addSpacing(8)
        self.doctab = QLabel()
        self.doctab.setObjectName("doctab")
        self.doctab.setFixedHeight(26)
        lay.addWidget(self.doctab, 0, Qt.AlignBottom)
        lay.addStretch()
        units = QLabel(f"UNITS <span style='color:{theme.ACCENT}'>in</span>")
        units.setObjectName("units")
        user = QLabel(getpass.getuser().upper())
        user.setObjectName("user")
        lay.addWidget(units)
        lay.addWidget(user)

    def set_doc(self, name: str, dirty: bool):
        dot = f" <span style='color:{theme.ACCENT}'>●</span>" if dirty else ""
        self.doctab.setText(name.upper() + dot)


class Ribbon(QFrame):
    tool = Signal(str)        # tool label, e.g. "Extrude"
    tab_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("ribbon")
        self.setFixedHeight(78)
        v = vbox(self)
        tabs = QFrame()
        tabs.setObjectName("ribbonTabs")
        tabs.setFixedHeight(24)
        tl = hbox(tabs, (6, 0, 0, 0))
        ws = QLabel(f"DESIGN <span style='color:{theme.ACCENT};font-size:10px'>▼</span>")
        ws.setObjectName("ws")
        tl.addWidget(ws)
        tl.addSpacing(6)
        self.tab_buttons = {}
        for key, label in TABS:
            b = QPushButton(label.upper())
            b.setObjectName("rtab")
            b.setCheckable(True)
            b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            b.clicked.connect(partial(self.tab_changed.emit, key))
            tl.addWidget(b)
            self.tab_buttons[key] = b
        tl.addStretch()
        self.tab_buttons["sketch"].hide()
        v.addWidget(tabs)
        # every tab's tools are built once and switched with a stack; rebuilding buttons on each
        # switch leaves PySide slots pointing at deleted widgets
        self.stack = QStackedWidget()
        sc = QScrollArea()                 # like the prototype's overflow-x:auto: never widens the window
        sc.setWidget(self.stack)
        sc.setWidgetResizable(True)
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sc.setFrameShape(QFrame.NoFrame)
        v.addWidget(sc)
        self.pages: dict[str, dict[str, QToolButton]] = {}
        self.page_index = {}
        for key, _ in TABS:
            page, tools = self._build_page(key)
            self.page_index[key] = self.stack.addWidget(page)
            self.pages[key] = tools
        self.tools: dict[str, QToolButton] = {}
        self.current = None
        self.show_tab("solid")

    def _build_page(self, key):
        page = QWidget()
        lay = hbox(page, (6, 4, 6, 0), 4)
        tools = {}
        for gname, items in RIBBON[key]:
            grp = QFrame()
            grp.setObjectName("group")
            gl = vbox(grp, (4, 0, 8, 0))
            row = hbox(spacing=2)
            for ic, label in items:
                b = QToolButton()
                b.setObjectName("tool")
                b.setText(label.upper())
                if ic == "finish":
                    b.setIcon(icons.icon(ic, theme.ACCENT, None, 18))
                    b.setProperty("finish", True)
                else:
                    b.setIcon(icons.icon(ic, theme.FG2, theme.ACCENT, 18))
                b.setIconSize(QSize(18, 18))
                b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                b.setCheckable(True)
                b.setMinimumSize(44, 38)
                b.setMaximumHeight(38)
                b.clicked.connect(partial(self.tool.emit, label))
                row.addWidget(b)
                tools[label] = b
            gl.addLayout(row)
            gl.addStretch()
            lab = QLabel(gname.upper() + " ▾")
            lab.setObjectName("glabel")
            lab.setAlignment(Qt.AlignCenter)
            gl.addWidget(lab)
            lay.addWidget(grp)
        lay.addStretch()
        return page, tools

    def show_tab(self, key):
        self.current = key
        for k, b in self.tab_buttons.items():
            b.setChecked(k == key)
        self.stack.setCurrentIndex(self.page_index[key])
        self.tools = self.pages[key]
        self.set_active(None)

    def set_active(self, label: str | None):
        for k, b in self.tools.items():
            b.setChecked(k == label)

    def show_sketch_tab(self, on: bool):
        self.tab_buttons["sketch"].setVisible(on)
        self.show_tab("sketch" if on else "solid")


def eye_icon(on: bool, kind: str) -> QPixmap:
    """The browser's visibility dot plus the node's type icon, drawn as one pixmap."""
    dpr = 2
    pm = QPixmap(34 * dpr, 14 * dpr)
    pm.fill(Qt.transparent)
    pm.setDevicePixelRatio(dpr)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(theme.ACCENT if on else theme.FG3)
    if on:
        p.setBrush(c)
        p.setPen(Qt.NoPen)
    else:
        p.setPen(c)
        p.setBrush(Qt.NoBrush)
    p.drawEllipse(2, 4, 6, 6)
    p.drawPixmap(16, 1, icons.pixmap(kind, theme.FG2, 12))
    p.end()
    return pm


class Browser(QFrame):
    selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("browser")
        self.setFixedWidth(250)
        v = vbox(self)
        ph = QLabel("BROWSER")
        ph.setObjectName("ph")
        ph.setFixedHeight(26)
        v.addWidget(ph)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setIndentation(14)
        self.tree.setIconSize(QSize(34, 14))
        self.tree.setRootIsDecorated(True)
        self.tree.itemClicked.connect(lambda it, _c: self.selected.emit(it.data(0, Qt.UserRole) or ""))
        v.addWidget(self.tree, 1)
        self.props = QFrame()
        self.props.setObjectName("props")
        self.pgrid = QGridLayout(self.props)
        self.pgrid.setContentsMargins(0, 0, 0, 0)
        self.pgrid.setSpacing(0)
        self.pvals = {}
        for i, k in enumerate(("BODY", "MATERIAL", "BBOX X", "BBOX Y", "BBOX Z", "VOLUME", "MASS", "FEATURES")):
            a, b = QLabel(k), QLabel("—")
            a.setObjectName("propK")
            b.setObjectName("propV")
            b.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.pgrid.addWidget(a, i, 0)
            self.pgrid.addWidget(b, i, 1)
            self.pvals[k] = b
        v.addWidget(self.props)

    def set_rows(self, doc_name, bodies, sketches, selected, editing=None):
        """bodies: [(id, name, visible)], sketches: [(id, name, visible, n_ents)]"""
        t = self.tree
        t.clear()

        def node(parent, name, kind, on, nid=None, tag="", dim=False):
            it = QTreeWidgetItem(parent, [name, tag])
            it.setIcon(0, eye_icon(on, kind))
            it.setData(0, Qt.UserRole, nid)
            it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            it.setForeground(1, QColor(theme.FG3))
            f = it.font(1)
            f.setPointSizeF(7)
            it.setFont(1, f)
            if dim:
                it.setForeground(0, QColor(theme.FG3))
            if nid and nid == selected:
                t.setCurrentItem(it)
            return it

        root = node(t, doc_name, "comp", True, "root")
        node(root, "Document Settings", "folder", True, "ds", "in")
        node(root, "Named Views", "folder", True, "nv")
        origin = node(root, "Origin", "origin", False, "origin")
        for pl in ("XY", "XZ", "YZ"):
            node(origin, pl, "plane", False, pl.lower())
        bf = node(root, "Bodies", "folder", True, "bodies")
        for bid, name, vis in bodies:
            node(bf, name, "body", vis, bid, "SOLID" if vis else "—", dim=not vis)
        sf = node(root, "Sketches", "folder", True, "sketches")
        for sid, name, vis, n in sketches:
            node(sf, name, "sketch", vis, sid, f"{n} ENT")
        if editing:
            node(sf, editing[0] + " (editing)", "sketch", True, "skedit", f"{editing[1]} ENT")
        t.expandAll()
        for i in (1, 2):   # keep Document Settings / Named Views collapsed like the prototype
            root.child(i - 1).setExpanded(False)
        t.setColumnWidth(0, 204)
        t.setColumnWidth(1, 40)

    def set_props(self, rows: dict):
        for k, v in rows.items():
            self.pvals[k].setText(v)


class StatusBar(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("status")
        self.setFixedHeight(22)
        lay = hbox(self, (10, 0, 10, 0), 14)
        ready = QLabel(f"<span style='color:{theme.OK}'>■</span> READY")
        self.coord = QLabel()
        self.coord.setObjectName("coord")
        self.coord.setTextFormat(Qt.PlainText)
        self.sel = QLabel("SEL: —")
        self.msg = QLabel()
        self.msg.setObjectName("msg")
        self.msg.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.msg.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)   # long hints clip, never widen
        for w in (ready, self.coord, self.sel):
            lay.addWidget(w)
        lay.addWidget(self.msg, 1)
        self.set_coord(0, 0, 0)

    def set_coord(self, x, y, z):
        self.coord.setText(f"X {x:8.4f}  Y {y:8.4f}  Z {z:8.4f}".replace(" ", "\u00a0"))


class Marker(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(10, 52)

    def paintEvent(self, _):
        p = QPainter(self)
        c = QColor(theme.ACCENT)
        p.fillRect(4, 4, 2, 48, c)
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygon([QPoint(0, 0), QPoint(10, 0), QPoint(5, 6)]))


class FeatureButton(QWidget):
    clicked = Signal()
    context = Signal(QPoint)

    def __init__(self, name, kind, desc):
        super().__init__()
        self.setFixedWidth(54)
        self.kind = kind
        v = vbox(self, spacing=4)
        self.fi = QLabel()
        self.fi.setFixedSize(32, 32)
        self.fi.setAlignment(Qt.AlignCenter)
        self.fn = QLabel(name)
        self.fn.setObjectName("featName")
        self.fn.setAlignment(Qt.AlignCenter)
        v.addWidget(self.fi, 0, Qt.AlignHCenter)
        v.addWidget(self.fn, 0, Qt.AlignHCenter)
        self.setToolTip(desc)
        self.setCursor(Qt.PointingHandCursor)
        self.state("on", False, None)

    def state(self, on: str, cur: bool, error: str | None):
        col = theme.BAD if error else (theme.ACCENT if on == "on" else theme.FG2)
        border = theme.BAD if error else (theme.ACCENT if on == "on" else theme.LINE2)
        bg = theme.ACCENT_DIM if cur else theme.PANEL2
        op = "" if on == "on" else "opacity:0.35;"
        self.fi.setStyleSheet(f"border:1px solid {border};background:{bg};{op}")
        self.fi.setPixmap(icons.pixmap(self.kind, col, 18))
        self.fn.setStyleSheet(f"color:{theme.FG2 if on == 'on' else theme.FG3};")
        if error:
            self.setToolTip(error)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()

    def contextMenuEvent(self, ev):
        self.context.emit(ev.globalPos())


class Timeline(QFrame):
    roll = Signal(int)            # new marker position
    play = Signal()
    delete = Signal(int)          # feature index

    ICON = {"sketch": "sketch", "extrude": "extrude", "hole": "hole"}

    def __init__(self):
        super().__init__()
        self.setObjectName("timeline")
        self.setFixedHeight(92)
        v = vbox(self)
        head = QFrame()
        head.setObjectName("tlHead")
        head.setFixedHeight(24)
        hl = hbox(head, (10, 0, 10, 0), 8)
        title = QLabel("TIMELINE")
        title.setObjectName("tlTitle")
        hl.addWidget(title)
        hl.addSpacing(8)
        self.n = 0
        self.marker_pos = 0
        for name, tip, fn in (("tl_start", "Go to start", lambda: self.roll.emit(0)),
                              ("tl_prev", "Step back", lambda: self.roll.emit(max(0, self.marker_pos - 1))),
                              ("tl_play", "Play", lambda: self.play.emit()),
                              ("tl_next", "Step forward", lambda: self.roll.emit(min(self.n, self.marker_pos + 1))),
                              ("tl_end", "Go to end", lambda: self.roll.emit(self.n))):
            b = QToolButton()
            b.setObjectName("tlctl")
            b.setIcon(icons.icon(name, theme.FG2, theme.ACCENT, 11))
            b.setFixedSize(22, 18)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            hl.addWidget(b)
        hl.addStretch()
        self.pos = QLabel()
        self.pos.setObjectName("tlPos")
        hl.addWidget(self.pos)
        v.addWidget(head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("tlBody")
        self.scroll.setWidget(self.body)
        v.addWidget(self.scroll, 1)

    def set_features(self, feats, marker, errors):
        """feats: [(name, kind, desc)], errors: {index: message}"""
        self.n, self.marker_pos = len(feats), marker
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()        # may be the button being clicked right now
        self.body = QWidget()
        self.body.setObjectName("tlBody")
        self.scroll.setWidget(self.body)
        lay = hbox(self.body, (10, 0, 10, 0), 0)
        for i, (name, kind, desc) in enumerate(feats):
            if i == marker:
                lay.addWidget(Marker())
            fb = FeatureButton(name, self.ICON.get(kind, "sketch"), desc)
            fb.state("on" if i < marker else "off", i == marker - 1, errors.get(i))
            fb.clicked.connect(partial(self.roll.emit, i + 1))
            fb.context.connect(partial(self._menu, i))
            lay.addWidget(fb)
        if marker >= len(feats):
            lay.addWidget(Marker())
        lay.addStretch()
        self.pos.setText(f"FEATURE <span style='color:{theme.ACCENT}'>{marker}</span> / {len(feats)}")

    def _menu(self, i, gp):
        m = QMenu(self)
        m.addAction("Roll to here", partial(self.roll.emit, i + 1))
        m.addAction("Roll to before", partial(self.roll.emit, i))
        m.addSeparator()
        m.addAction("Delete", partial(self.delete.emit, i))
        m.exec(gp)
