"""F12 / Print Screen: a screenshot taken by the app itself, menus and all.

Windows' Snipping Tool takes focus away from the app, and a Qt drop-down / right-click menu closes
the moment its window loses focus, so a snip of an open menu comes out empty. This filter sits on
the whole application (it sees keys even while a menu has the keyboard), grabs the screen the
mouse is on before anything closes, copies the picture to the clipboard (paste it straight into a
chat) and saves a PNG in Pictures / G-SEND Screenshots.

It also keeps an open drop-down / menu up when the app loses focus (Print Screen → Snipping Tool,
Win+Shift+S): a popup that closes while another program has the focus, without a click or key
from the user, is held for HOLD_S seconds,
so the snip still has it. A click or Escape back in the app closes it as usual.
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QEvent, QObject, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QWidget

KEYS = (Qt.Key_F12, Qt.Key_Print)
HOLD_S = 30
INPUT = (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick, QEvent.KeyPress,
         QEvent.KeyRelease, QEvent.Wheel, QEvent.ShortcutOverride)


def folder() -> str:
    pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or os.path.expanduser("~")
    return os.path.join(pics, "G-SEND Screenshots")


class Snapshot(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self._last = 0.0
        self._input = 0.0                   # when the user last clicked / pressed a key in the app
        self._release = False
        self.last_path = None

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in INPUT:
            self._input = time.monotonic()
        elif t == QEvent.Close and not self._release and self.held(obj):
            ev.ignore()                     # closing on its own = focus went to the snipping tool
            QTimer.singleShot(HOLD_S * 1000, lambda w=obj: self.let_go(w))
            return True
        # Print Screen often reaches an app only as a key *release*, so take either (once)
        if ev.type() in (QEvent.KeyPress, QEvent.KeyRelease) and ev.key() in KEYS and not ev.isAutoRepeat():
            if time.monotonic() - self._last > 0.6:
                self._last = time.monotonic()
                self.take()
            return True
        return False

    def held(self, w) -> bool:
        """Only while another program has the focus (the snipping tool) and the user didn't
        just click / press a key: picking an item or clicking away always closes it."""
        return (isinstance(w, QWidget) and w.isWindow() and w.windowType() == Qt.Popup and w.isVisible()
                and QGuiApplication.applicationState() != Qt.ApplicationActive
                and time.monotonic() - self._input > 0.3)

    def let_go(self, w):
        try:
            if w.isVisible():
                self._release = True
                w.close()
        except RuntimeError:                # already gone
            pass
        finally:
            self._release = False

    def take(self):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        pix = screen.grabWindow(0)                  # the whole screen: open menus included
        QGuiApplication.clipboard().setPixmap(pix)
        path = None
        try:
            os.makedirs(folder(), exist_ok=True)
            path = os.path.join(folder(), time.strftime("G-SEND %Y-%m-%d %H.%M.%S.png"))
            if not pix.save(path):
                path = None
        except OSError:
            path = None
        self.last_path = path
        msg = "Screenshot copied — paste it anywhere" + (f" · saved in {folder()}" if path else "")
        QTimer.singleShot(150, lambda: self.win.viewport.show_toast(msg))   # after the grab, not in it
        return path
