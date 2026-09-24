"""Look of the app: the HTML prototype's tokens, fonts and flat dark style as Qt."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase

# Same tokens as the prototype's :root. The accent is a placeholder until the exact
# G-SEND blue is chosen; change ACCENT/ACCENT_DIM here and nowhere else.
BG = "#0a0a0a"
PANEL = "#111111"
PANEL2 = "#161616"
LINE = "#2a2a2a"
LINE2 = "#3a3a3a"
FG = "#e6e6e6"
FG2 = "#9a9a9a"
FG3 = "#5e5e5e"
ACCENT = "#2f9bff"
ACCENT_DIM = "#0c3457"
OK = "#3ddc84"
WARN = "#ffb300"
BAD = "#ff3b3b"
BODY = "#b4b9c0"

FONT_DIR = Path(__file__).with_name("fonts")
# First family that is installed wins. Drop the Google Fonts TTFs (Rajdhani, Share Tech Mono,
# Squada One, Anton; all OFL) into ui/fonts/ to get the exact prototype look.
HEAD = ["Rajdhani", "Bahnschrift", "DejaVu Sans Condensed", "DejaVu Sans"]
MONO = ["Share Tech Mono", "Consolas", "DejaVu Sans Mono", "Liberation Mono"]
BRAND_G = ["Squada One", "Bahnschrift", "DejaVu Sans"]
BRAND_WM = ["Anton", "Impact", "Bahnschrift", "DejaVu Sans"]


def load_fonts():
    if FONT_DIR.is_dir():
        for f in sorted(FONT_DIR.glob("*.[ot]tf")):
            QFontDatabase.addApplicationFont(str(f))


def pick(families) -> str:
    have = set(QFontDatabase.families())
    return next((f for f in families if f in have), families[-1])


def qss(head: str, mono: str) -> str:
    return f"""
* {{ font-family: '{mono}'; font-size: 12px; color: {FG}; }}
QMainWindow, #central {{ background: {BG}; }}
QToolTip {{ background: {PANEL}; color: {FG}; border: 1px solid {LINE2}; }}

#topbar {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
#brandG {{ background: {ACCENT}; color: {BG}; font-size: 22px; }}
#brandCad {{ font-family: '{head}'; font-weight: 600; font-size: 11px; letter-spacing: 3px; color: {FG3};
            border-left: 1px solid {LINE2}; padding-left: 8px; margin-left: 6px; }}
#doctab {{ border: 1px solid {LINE2}; border-bottom-color: {PANEL}; background: {PANEL2}; padding: 0 12px;
          font-family: '{head}'; font-weight: 600; font-size: 13px; letter-spacing: 1px; }}
#units {{ border: 1px solid {LINE2}; padding: 1px 8px; }}
#user {{ color: {FG2}; }}
QToolButton#ico {{ border: 1px solid transparent; }}
QToolButton#ico:hover {{ border-color: {LINE2}; }}
#sep {{ background: {LINE}; }}

#ribbon {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
#ribbonTabs {{ border-bottom: 1px solid {LINE}; }}
#ws {{ font-family: '{head}'; font-weight: 700; font-size: 13px; letter-spacing: 1px; border-right: 1px solid {LINE};
      padding: 0 10px; }}
QPushButton#rtab {{ font-family: '{head}'; font-weight: 600; font-size: 12px; letter-spacing: 1px; color: {FG2};
                   border: 0; border-bottom: 2px solid transparent; padding: 0 12px; background: transparent; }}
QPushButton#rtab:hover {{ color: {FG}; }}
QPushButton#rtab:checked {{ color: {ACCENT}; border-bottom-color: {ACCENT}; }}
#ribbon QAbstractScrollArea, #ribbon QStackedWidget, #ribbon QStackedWidget > QWidget {{ background: {PANEL}; }}
#group {{ border-right: 1px solid {LINE}; }}
#glabel {{ font-family: '{head}'; font-weight: 600; font-size: 10px; letter-spacing: 2px; color: {FG3}; }}
QToolButton#tool {{ border: 1px solid transparent; color: {FG2}; font-size: 9px; padding: 1px 4px; background: transparent; }}
QToolButton#tool:hover {{ border-color: {LINE2}; color: {FG}; background: {PANEL2}; }}
QToolButton#tool:checked {{ border-color: {ACCENT}; color: {ACCENT}; }}
QToolButton#tool[finish="true"] {{ border-color: {ACCENT}; color: {ACCENT}; padding: 1px 10px; }}

#browser {{ background: {PANEL}; border-right: 1px solid {LINE}; }}
#ph {{ font-family: '{head}'; font-weight: 600; font-size: 11px; letter-spacing: 3px; color: {FG2};
      border-bottom: 1px solid {LINE}; padding: 0 10px; }}
QTreeWidget {{ background: {PANEL}; border: 0; outline: 0; }}
QTreeWidget::item {{ height: 22px; border: 1px solid transparent; }}
QTreeWidget::item:hover {{ background: {PANEL2}; }}
QTreeWidget::item:selected {{ background: {ACCENT_DIM}; border-top: 1px solid {ACCENT}; border-bottom: 1px solid {ACCENT}; color: {FG}; }}
#props {{ border-top: 1px solid {LINE}; }}
#propK {{ color: {FG3}; border-bottom: 1px solid {LINE}; padding: 3px 10px; }}
#propV {{ border-bottom: 1px solid {LINE}; padding: 3px 10px; }}

#status {{ background: {PANEL}; border-top: 1px solid {LINE}; border-bottom: 1px solid {LINE}; }}
#status QLabel {{ color: {FG2}; font-size: 11px; }}
#status QLabel#coord {{ color: {FG}; }}
#status QLabel#msg {{ color: {FG3}; }}

#timeline {{ background: {PANEL}; }}
#tlHead {{ border-bottom: 1px solid {LINE}; }}
#tlTitle {{ font-family: '{head}'; font-weight: 600; font-size: 11px; letter-spacing: 3px; color: {FG2}; }}
QToolButton#tlctl {{ border: 1px solid transparent; color: {FG2}; }}
QToolButton#tlctl:hover {{ border-color: {LINE2}; color: {ACCENT}; }}
#tlPos {{ color: {FG3}; }}
QScrollArea {{ border: 0; background: transparent; }}
#tlBody {{ background: {PANEL}; }}
#featName {{ font-size: 9px; color: {FG3}; }}

#hud QLabel {{ color: {FG2}; font-size: 11px; background: transparent; }}
#cube QPushButton {{ border: 1px solid {LINE2}; background: {PANEL}; color: {FG2}; font-family: '{head}';
                    font-weight: 600; font-size: 10px; }}
#cube QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
#cube QPushButton#home {{ color: {ACCENT}; }}
#navbar {{ background: {PANEL}; border: 1px solid {LINE2}; }}
#navbar QToolButton {{ border: 0; background: transparent; }}
#toast {{ border: 1px solid {ACCENT}; background: {PANEL}; color: {ACCENT}; font-family: '{head}'; font-weight: 600;
         letter-spacing: 2px; font-size: 11px; padding: 4px 12px; }}
#toast[bad="true"] {{ border-color: {BAD}; color: {BAD}; }}
#skbanner {{ border: 1px solid {ACCENT}; background: {ACCENT_DIM}; font-family: '{head}'; font-weight: 600;
            letter-spacing: 2px; font-size: 11px; padding: 3px 12px; }}
#dim {{ background: {PANEL}; border: 1px solid {ACCENT}; color: {ACCENT}; font-size: 11px; padding: 2px 6px; }}

#panel {{ background: {PANEL}; border: 1px solid {LINE2}; }}
#panelHead {{ font-family: '{head}'; font-weight: 700; letter-spacing: 2px; font-size: 12px; color: {ACCENT};
             border-bottom: 1px solid {LINE}; padding: 5px 10px; }}
#panelRow {{ border-bottom: 1px solid {LINE}; }}
#panelRow QLabel {{ color: {FG2}; }}
#panelRow QLabel#val {{ color: {FG}; border: 1px solid {LINE2}; padding: 1px 6px; }}
#panelRow QLabel#val[none="true"] {{ color: {FG3}; }}
#panel QAbstractScrollArea, #panel QAbstractScrollArea > QWidget, #entList {{ background: {PANEL}; }}
#entList QLabel {{ font-size: 11px; }}
QComboBox, QDoubleSpinBox {{ background: {PANEL2}; border: 1px solid {LINE2}; padding: 1px 4px; min-width: 84px; }}
QComboBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QDoubleSpinBox {{ color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {PANEL2}; border: 1px solid {LINE2}; selection-background-color: {ACCENT_DIM}; }}
QCheckBox::indicator {{ width: 12px; height: 12px; border: 1px solid {LINE2}; background: {PANEL2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QPushButton#dlgBtn {{ border: 1px solid {LINE2}; background: transparent; padding: 3px 12px; font-family: '{head}';
                     font-weight: 600; letter-spacing: 1px; font-size: 11px; color: {FG2}; }}
QPushButton#dlgBtn[ok="true"] {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton#dlgBtn:hover {{ background: {PANEL2}; }}
QMenu {{ background: {PANEL}; border: 1px solid {LINE2}; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QScrollBar:horizontal {{ height: 6px; background: {PANEL}; }}
QScrollBar::handle:horizontal {{ background: {LINE2}; }}
QScrollBar:vertical {{ width: 6px; background: {PANEL}; }}
QScrollBar::handle:vertical {{ background: {LINE2}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
"""
