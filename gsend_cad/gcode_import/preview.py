"""The XZ half-section view the import window's pages share."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..ui import theme


class Preview(QWidget):
    """XZ half-section: stock (dashed), centerline, Z0 marker, toolpath (feeds solid, rapids dashed)."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(420, 320)
        self.moves = []
        self.stock = None           # (z_back, z_front, od, id) or None
        self.note = ""
        self.highlight = None       # move indices drawn bright (the rest dim), or None = all bright
        self.caption = ""
        self.profile = None         # reconstructed outline edges (EXACT / ASSUMED / STOCK / AXIS), or None
        self.show_toolpath = True

    def show_highlight(self, indices, caption=""):
        self.highlight = None if indices is None else set(indices)
        self.caption = caption
        self.update()

    def show_setup(self, moves, stock, note="", profile=None):
        self.moves, self.stock, self.note, self.profile = moves, stock, note, profile
        self.update()

    def _bounds(self):
        zs, rs = [0.0], [0.0]
        if self.stock:
            zb, zf, od, _ = self.stock
            zs += [zb, zf]
            rs.append(od / 2.0)
        for m in self.moves:
            if m.kind != "rapid":
                zs += [p[0] for p in m.points]
                rs += [p[1] / 2.0 for p in m.points]
        z0, z1, r1 = min(zs), max(zs), max(rs)
        pad = 0.12 * max(z1 - z0, r1, 0.25)
        return z0 - pad, z1 + pad, -pad, r1 + pad

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.BG))
        p.setPen(QPen(QColor(theme.LINE), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        mono = QFont(theme.MONO[0])
        mono.setPixelSize(11)
        p.setFont(mono)
        if self.note:
            p.setPen(QColor(theme.BAD))
            p.drawText(self.rect(), Qt.AlignCenter, self.note)
            return
        z0, z1, r0, r1 = self._bounds()
        w, h = self.width() - 24, self.height() - 24
        s = min(w / max(z1 - z0, 1e-6), h / max(r1 - r0, 1e-6))
        ox = 12 + (w - (z1 - z0) * s) / 2.0
        oy = 12 + (h - (r1 - r0) * s) / 2.0

        def pt(z, dia):
            return QPointF(ox + (z - z0) * s, oy + (r1 - dia / 2.0) * s)

        dash = QPen(QColor(theme.FG3), 1, Qt.DashLine)
        if self.stock:
            zb, zf, od, bore = self.stock
            p.setPen(dash)
            p.drawRect(QRectF(pt(zb, od), pt(zf, 0.0)))
            if bore > 0:
                p.drawLine(pt(zb, bore), pt(zf, bore))
        # centerline and Z0
        p.setPen(QPen(QColor(theme.FG3), 1, Qt.DashDotLine))
        p.drawLine(pt(z0, 0.0), pt(z1, 0.0))
        p.setPen(QColor(theme.FG3))
        p.drawText(pt(z0, 0.0) + QPointF(4, -4), "CL  X0")
        p.setPen(QPen(QColor(theme.OK), 1))
        p.drawLine(pt(0.0, r1 * 2.0), pt(0.0, r0 * 2.0))
        p.drawText(pt(0.0, r1 * 2.0) + QPointF(4, 12), "Z0")
        clip = QRectF(1, 1, self.width() - 2, self.height() - 2)
        p.setClipRect(clip)
        if self.profile:
            # the part: exact edges solid accent, assumed edges dashed orange, uncut stock dashed gray
            pens = {"EXACT": QPen(QColor(theme.ACCENT), 2.0), "ASSUMED": QPen(QColor(theme.WARN), 2.0, Qt.DashLine),
                    "STOCK": QPen(QColor(theme.FG2), 1.4, Qt.DashLine)}
            for tag in ("STOCK", "EXACT", "ASSUMED"):
                p.setPen(pens[tag])
                for e in self.profile:
                    if e.tag == tag:
                        p.drawLine(pt(e.z0, e.x0), pt(e.z1, e.x1))
        # toolpath: rapids under, feeds over. Over a profile it is drawn thin, so the part reads first.
        rapid = QPen(QColor(theme.FG3), 1, Qt.DashLine)
        feed = QPen(QColor(theme.OK if self.profile else theme.ACCENT), 1.0 if self.profile else 1.4)
        dim = QPen(QColor(theme.LINE2), 1)
        lit = self.highlight if self.show_toolpath else set()
        if self.profile and not self.show_toolpath and self.highlight is not None:
            lit = self.highlight                        # a selected operation still shows over the profile
        # rapids under, then the dimmed feeds, then the bright ones on top
        for layer in ("rapid", "dim", "feed"):
            p.setPen({"rapid": rapid, "dim": dim, "feed": feed}[layer])
            for i, m in enumerate(self.moves):
                bright = lit is None or i in lit
                if self.profile and not bright:
                    continue                            # over a profile, only the lit moves are drawn
                if m.kind == "rapid":
                    if layer != "rapid" or not bright:
                        continue
                elif layer != ("feed" if bright else "dim"):
                    continue
                pts = [pt(z, d) for z, d in m.points]
                for a, b in zip(pts, pts[1:]):
                    p.drawLine(a, b)
        p.setClipping(False)
        if self.caption:
            p.setPen(QColor(theme.ACCENT))
            p.drawText(self.rect().adjusted(10, 8, -8, 0), Qt.AlignTop | Qt.AlignLeft, self.caption)
        p.setPen(QColor(theme.FG3))
        legend = ("EXACT ——   ASSUMED - - -   STOCK - - -   +Z →   +X ↑" if self.profile else
                  "FEED ——   RAPID - - -   STOCK - - -   +Z →   +X ↑")
        p.drawText(self.rect().adjusted(8, 0, -8, -6), Qt.AlignBottom | Qt.AlignRight, legend)
