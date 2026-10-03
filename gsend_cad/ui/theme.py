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
# How brightly the solid is lit (viewport). Shane 10/2/26: the grey read too dark on the black, "a little lighter,
# but keep it grey" - then "just a little bit more". Was ambient 0.10 / diffuse 0.60 (luminance 90); now 0.35 / 0.70
# (luminance 147, +64%, RGB ~143,148,154) with the shading between faces intact. Raise both to go lighter, lower
# to go darker; the colour above is unchanged. (0.25 / 0.65 was the first step: luminance 123.)
BODY_AMBIENT = 0.35
BODY_DIFFUSE = 0.70

FONT_DIR = Path(__file__).with_name("fonts")
ASSETS = Path(__file__).with_name("assets")
LOGO_PNG = ASSETS / "g00code_logo.png"      # the G00 logo from the G-SEND.IO repo
LOGO_ICO = ASSETS / "g00code_logo.ico"      # app / taskbar icon: square G00 in a blue border (so the CAD/CAM
ICON_PNG = ASSETS / "g00code_icon.png"      # one isn't mistaken for G-SEND.IO's); Windows ignores non-square icons
# First family that is installed wins. Drop the Google Fonts TTFs (Rajdhani, Share Tech Mono,
# Squada One, Anton; all OFL) into ui/fonts/ to get the exact prototype look.
HEAD = ["Rajdhani", "Bahnschrift", "DejaVu Sans Condensed", "DejaVu Sans"]
MONO = ["Share Tech Mono", "Consolas", "DejaVu Sans Mono", "Liberation Mono"]
BRAND_G = ["Squada One", "Bahnschrift", "DejaVu Sans"]
BRAND_WM = ["Anton", "Impact", "Bahnschrift", "DejaVu Sans"]
BRAND_INK = "#ece7db"        # G-SEND.IO wordmark colour: poster cream, not white (from rev4_theme)
BRAND_TEXT = ("G", "-SEND")  # square Squada One G + Anton rest, like the G-SEND.IO editor sidebar


def load_fonts():
    if FONT_DIR.is_dir():
        for f in sorted(FONT_DIR.glob("*.[ot]tf")):
            QFontDatabase.addApplicationFont(str(f))


def logo_pixmap(height: int, dpr: float = 2.0):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    pm = QPixmap(str(LOGO_PNG)).scaledToHeight(int(height * dpr), Qt.SmoothTransformation)
    pm.setDevicePixelRatio(dpr)
    return pm


def app_icon():
    from PySide6.QtGui import QIcon
    ic = QIcon(str(LOGO_ICO)) if LOGO_ICO.exists() else QIcon()
    ic.addFile(str(ICON_PNG))
    return ic


def palette():
    """A dark palette matching the stylesheet, for the widgets the stylesheet does not reach:
    the native style paints message boxes and dialog frames from the palette, and Windows 11's
    dark palette put near-black text on a dark box (9/29/26)."""
    from PySide6.QtGui import QColor, QPalette
    pal = QPalette()
    for role, col in ((QPalette.Window, PANEL), (QPalette.WindowText, FG), (QPalette.Base, PANEL2),
                      (QPalette.AlternateBase, PANEL), (QPalette.Text, FG), (QPalette.Button, PANEL2),
                      (QPalette.ButtonText, FG), (QPalette.ToolTipBase, PANEL), (QPalette.ToolTipText, FG),
                      (QPalette.Highlight, ACCENT), (QPalette.HighlightedText, "#ffffff"),
                      (QPalette.PlaceholderText, FG3), (QPalette.Link, ACCENT)):
        pal.setColor(role, QColor(col))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(FG3))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(FG3))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(FG3))
    return pal


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
QToolButton#menuBtn {{ border: 1px solid transparent; color: {FG2}; font-family: '{head}'; font-weight: 600;
                      font-size: 12px; letter-spacing: 1px; padding: 2px 8px; }}
QToolButton#menuBtn:hover, QToolButton#menuBtn:open {{ border-color: {LINE2}; color: {ACCENT}; }}
QToolButton#menuBtn::menu-indicator {{ image: none; width: 0; }}
QToolButton#entDel {{ border: 1px solid transparent; color: {FG3}; background: transparent; font-size: 13px; padding: 0; }}
QToolButton#entDel:hover {{ border-color: {BAD}; color: {BAD}; }}
QToolButton#pickBtn {{ border: 1px solid {LINE2}; background: {PANEL2}; padding: 0; }}
QToolButton#pickBtn:hover {{ border-color: {ACCENT}; }}
QToolButton#pickBtn:checked {{ border-color: {ACCENT}; background: {ACCENT_DIM}; }}
#docs, #docs QTextBrowser {{ background: {PANEL}; }}
#docs QTextBrowser {{ border: 0; border-left: 1px solid {LINE}; }}
#docs QListWidget {{ background: {PANEL}; border: 0; outline: 0; font-family: '{head}'; font-weight: 600;
                    font-size: 13px; letter-spacing: 1px; color: {FG2}; }}
#docs QListWidget::item {{ padding: 6px 12px; border-left: 2px solid transparent; }}
#docs QListWidget::item:hover {{ color: {FG}; background: {PANEL2}; }}
#docs QListWidget::item:selected {{ color: {ACCENT}; background: {ACCENT_DIM}; border-left-color: {ACCENT}; }}
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
/* Text boxes (tool names, T numbers, rename, post output): the Windows 11 native style drew them
   white with light-grey text (10/1/26, unreadable). Dark like the rest; typed text and the blinking
   cursor (Qt draws it in the text colour) in accent blue. */
QLineEdit, QSpinBox {{ background: {PANEL2}; border: 1px solid {LINE2}; color: {ACCENT}; padding: 2px 4px;
                      selection-background-color: {ACCENT_DIM}; selection-color: {FG}; }}
QLineEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QAbstractSpinBox QLineEdit {{ background: transparent; border: 0; padding: 0; }}  /* a number box's own edit */
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {FG3}; border-color: {LINE}; }}
QPlainTextEdit, QTextEdit {{ background: {PANEL2}; border: 1px solid {LINE2}; color: {FG};
                            selection-background-color: {ACCENT_DIM}; }}
QComboBox QAbstractItemView {{ background: {PANEL2}; border: 1px solid {LINE2}; selection-background-color: {ACCENT_DIM}; }}
QCheckBox::indicator {{ width: 12px; height: 12px; border: 1px solid {LINE2}; background: {PANEL2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QPushButton#dlgBtn {{ border: 1px solid {LINE2}; background: transparent; padding: 3px 12px; font-family: '{head}';
                     font-weight: 600; letter-spacing: 1px; font-size: 11px; color: {FG2}; }}
QPushButton#dlgBtn[ok="true"] {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton#dlgBtn:hover {{ background: {PANEL2}; }}
/* Message boxes (save changes?, delete?, startup warnings): on Windows 11 the native style drew
   the question in dark grey on a dark box (9/29/26, unreadable), so every part is spelled out. */
QMessageBox {{ background: {PANEL}; border: 1px solid {LINE2}; }}
QMessageBox QLabel {{ color: {FG}; background: transparent; font-size: 13px; padding: 4px 2px; }}
QMessageBox QPushButton {{ border: 1px solid {LINE2}; background: {PANEL2}; color: {FG}; padding: 5px 16px;
                          min-width: 72px; font-family: '{head}'; font-weight: 600; letter-spacing: 1px; }}
QMessageBox QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QMessageBox QPushButton:default {{ border-color: {ACCENT}; color: {ACCENT}; }}
QMenu {{ background: {PANEL}; border: 1px solid {LINE2}; }}
QMenu::item {{ padding: 4px 22px 4px 14px; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 3px 6px; }}
QScrollBar:horizontal {{ height: 6px; background: {PANEL}; }}
QScrollBar::handle:horizontal {{ background: {LINE2}; }}
QScrollBar:vertical {{ width: 6px; background: {PANEL}; }}
QScrollBar::handle:vertical {{ background: {LINE2}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
"""
