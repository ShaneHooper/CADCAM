"""The prototype's inline icon set, rendered to QIcons in any color."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    "sketch": '<path d="M4 20 20 4M4 4h4v4H4zM16 16h4v4h-4z"/>',
    "box": '<path d="M4 8l8-4 8 4v8l-8 4-8-4zM4 8l8 4 8-4M12 12v8"/>',
    "cyl": '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/>',
    "extrude": '<path d="M5 17h14M8 17l4-4 4 4M12 13V4M5 20h14"/>',
    "revolve": '<path d="M12 3v18M12 6c5 0 8 2 8 5s-3 5-8 5"/><path d="m16 18 4-2-1-4"/>',
    "hole": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
    "fillet": '<path d="M4 20V10a6 6 0 0 1 6-6h10"/>',
    "chamfer": '<path d="M4 20V10l6-6h10"/>',
    "shell": '<path d="M4 6h16v14H4zM8 6v10h8V6"/>',
    "thread": '<path d="M7 3v18M17 3v18M7 7l10-2M7 12l10-2M7 17l10-2"/>',
    "move": '<path d="M12 3v18M3 12h18M8 7l4-4 4 4M8 17l4 4 4-4"/>',
    "combine": '<circle cx="9" cy="12" r="6"/><circle cx="15" cy="12" r="6"/>',
    "press": '<path d="M4 12h16M12 4v16M8 8l4-4 4 4M8 16l4 4 4-4"/>',
    "plane": '<path d="M3 17 9 5h12l-6 12z"/>',
    "axis": '<path d="M12 3v18M9 6l3-3 3 3"/>',
    "pt": '<circle cx="12" cy="12" r="2"/><path d="M12 3v5M12 16v5M3 12h5M16 12h5"/>',
    "measure": '<path d="M3 17 17 3l4 4L7 21zM8 12l2 2M11 9l2 2M14 6l2 2"/>',
    "section": '<path d="M4 6h16v12H4zM12 6v12"/><path d="M4 12h8" stroke-dasharray="2 2"/>',
    "insert": '<path d="M12 5v14M5 12h14"/>',
    "select": '<path d="M5 3l14 9-6 1 3 6-2 1-3-6-4 4z"/>',
    "line": '<path d="M4 20 20 4"/><circle cx="4" cy="20" r="1.5"/><circle cx="20" cy="4" r="1.5"/>',
    "rect": '<rect x="4" y="6" width="16" height="12"/>',
    "crect": '<rect x="4" y="6" width="16" height="12"/><path d="M12 9v6M9 12h6"/>',
    "circle": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="1"/>',
    "poly": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/>',
    "undo": '<path d="M9 14 4 9l5-5 M4 9h10a6 6 0 0 1 0 12h-3"/>',
    "redo": '<path d="m15 14 5-5-5-5 M20 9H10a6 6 0 0 0 0 12h3"/>',
    "save": '<path d="M5 3h11l3 3v15H5z M8 3v6h8V3 M8 21v-7h8v7"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
    "finish": '<path d="M4 12l5 5L20 6"/>',
    "cancel": '<path d="M6 6l12 12M18 6 6 18"/>',
    "joint": '<circle cx="7" cy="12" r="3"/><circle cx="17" cy="12" r="3"/><path d="M10 12h4"/>',
    "body": '<path d="M4 8l8-4 8 4v8l-8 4-8-4zM4 8l8 4 8-4M12 12v8"/>',
    "folder": '<path d="M3 6h6l2 2h10v11H3z"/>',
    "comp": '<path d="M4 8l8-4 8 4-8 4zM4 8v8l8 4 8-4V8"/>',
    "origin": '<path d="M12 12V4M12 12h8M12 12l-6 6"/>',
    "view": '<circle cx="12" cy="12" r="3"/><path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6S2 12 2 12z"/>',
    "orbit": '<circle cx="12" cy="12" r="8"/><path d="M4 12h16"/>',
    "pan": '<path d="M12 3v18M3 12h18M8 7l4-4 4 4M8 17l4 4 4-4M7 8 3 12l4 4M17 8l4 4-4 4"/>',
    "zoom": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4M8 11h6M11 8v6"/>',
    "fit": '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
    "disp": '<path d="M12 3 3 8l9 5 9-5-9-5zM3 16l9 5 9-5"/>',
    "open": '<path d="M3 6h6l2 2h10v11H3z M3 10h18"/>',
    # timeline transport (filled)
    "tl_start": '<path fill="C" stroke="none" d="M4 4h4v16H4zM20 4 10 12l10 8z"/>',
    "tl_prev": '<path fill="C" stroke="none" d="M18 4 6 12l12 8z"/>',
    "tl_play": '<path fill="C" stroke="none" d="M6 4l14 8-14 8z"/>',
    "tl_next": '<path fill="C" stroke="none" d="M6 4l12 8-12 8z"/>',
    "tl_end": '<path fill="C" stroke="none" d="M16 4h4v16h-4zM4 4l10 8-10 8z"/>',
}


def svg(name: str, color: str, width: float = 1.5) -> bytes:
    body = PATHS[name].replace('fill="C"', f'fill="{color}"')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


@lru_cache(maxsize=None)
def pixmap(name: str, color: str, size: int = 18, dpr: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    QSvgRenderer(QByteArray(svg(name, color))).render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str, active: str | None = None, size: int = 18) -> QIcon:
    ic = QIcon(pixmap(name, color, size))
    if active:
        ic.addPixmap(pixmap(name, active, size), QIcon.Active)
        ic.addPixmap(pixmap(name, active, size), QIcon.Normal, QIcon.On)
    return ic
