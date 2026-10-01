"""F12 / Print Screen: a screenshot taken by the app itself, menus and all.

Windows' Snipping Tool takes focus away from the app, and a Qt drop-down / right-click menu closes
the moment its window loses focus, so a snip of an open menu comes out empty. This filter sits on
the whole application (it sees keys even while a menu has the keyboard), grabs the screen the
mouse is on before anything closes, copies the picture to the clipboard (paste it straight into a
chat) and saves a PNG in Pictures / G-SEND Screenshots.
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QEvent, QObject, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication

KEYS = (Qt.Key_F12, Qt.Key_Print)


def folder() -> str:
    pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or os.path.expanduser("~")
    return os.path.join(pics, "G-SEND Screenshots")


class Snapshot(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self._last = 0.0
        self.last_path = None

    def eventFilter(self, obj, ev):
        # Print Screen often reaches an app only as a key *release*, so take either (once)
        if ev.type() in (QEvent.KeyPress, QEvent.KeyRelease) and ev.key() in KEYS and not ev.isAutoRepeat():
            if time.monotonic() - self._last > 0.6:
                self._last = time.monotonic()
                self.take()
            return True
        return False

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
