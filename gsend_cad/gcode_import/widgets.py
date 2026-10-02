"""Small Qt pieces the import window's pages share."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox, QLabel, QPushButton

from ..ui import theme

# state colours, always shown with their word
C_READ, C_GUESS, C_UNKNOWN, C_YOU = theme.OK, theme.WARN, theme.BAD, theme.ACCENT
STATUS_COLOUR = {"READ": C_READ, "HIGH": C_READ, "GUESSED": C_GUESS, "MED": C_GUESS, "ASSUMED": C_GUESS,
                 "AUTO": C_GUESS, "UNKNOWN": C_UNKNOWN, "NEEDS TYPE": C_UNKNOWN, "DEFINED": C_YOU,
                 "SET BY YOU": C_YOU, "DEFAULT": theme.FG2, "USER": C_YOU}
MONO_CSS = f"font-family:'{theme.MONO[0]}','Consolas',monospace;"
TABLE_CSS = (f"QTableWidget{{background:{theme.BG};color:{theme.FG};border:1px solid {theme.LINE};"
             f"gridline-color:{theme.LINE};{MONO_CSS}font-size:12px;}}"
             f"QTableWidget::item:selected{{background:{theme.ACCENT_DIM};color:{theme.FG};}}"
             f"QHeaderView::section{{background:{theme.PANEL};color:{theme.FG2};border:0;"
             f"border-bottom:1px solid {theme.LINE};padding:4px 6px;font-family:'{theme.HEAD[0]}';"
             f"font-weight:600;letter-spacing:1px;}}")


def head(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setStyleSheet(f"color:{theme.FG2};font-family:'{theme.HEAD[0]}';font-weight:600;letter-spacing:2px;"
                      f"font-size:12px;border:0;border-bottom:1px solid {theme.LINE};padding:6px 0 3px 0;")
    return lab


class Tag(QLabel):
    """A state chip: a word in its colour, with the reason as its tooltip."""

    def __init__(self, word: str = "AUTO", width: int = 84):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setFixedWidth(width)
        self.set(word)

    def set(self, word: str, colour: str | None = None, tip: str = ""):
        colour = colour or STATUS_COLOUR.get(word, theme.FG2)
        self.setText(word)
        self.setToolTip(tip)
        self.setStyleSheet(f"color:{colour};border:1px solid {colour};font-size:10px;padding:1px 4px;{MONO_CSS}")


class Num(QDoubleSpinBox):
    def __init__(self, lo=0.0, hi=1000.0, step=0.125):
        super().__init__()
        self.setDecimals(4)
        self.setRange(lo, hi)
        self.setSingleStep(step)
        self.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.setFixedWidth(96)


def toggle(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setCheckable(True)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{border:1px solid {theme.LINE2};background:transparent;color:{theme.FG2};padding:4px 10px;"
        f"font-family:'{theme.HEAD[0]}';font-weight:600;letter-spacing:1px;}}"
        f"QPushButton:checked{{border-color:{theme.ACCENT};color:{theme.ACCENT};background:{theme.ACCENT_DIM};}}"
        f"QPushButton:disabled{{color:{theme.FG3};border-color:{theme.LINE};}}")
    return b


def button(text: str, ok: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("dlgBtn")
    if ok:
        b.setProperty("ok", True)
    return b
