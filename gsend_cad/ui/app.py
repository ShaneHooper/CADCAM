"""Start the CAD window, standalone or from a host app such as G-SEND.IO."""
from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication

from ..core import Document, bracket_plate
from . import theme


def _style(app: QApplication) -> dict:
    theme.load_fonts()
    head, mono = theme.pick(theme.HEAD), theme.pick(theme.MONO)
    app.setStyleSheet(theme.qss(head, mono))
    return {"head": head, "mono": mono, "g": theme.pick(theme.BRAND_G), "wm": theme.pick(theme.BRAND_WM)}


def launch(document: Document | str | None = None, block: bool | None = None):
    """Open a CAD window and return it.

    document: a Document, a path to a .gcad file, or None for the demo Bracket Plate.
    block:    run the Qt event loop until the window closes. Defaults to True only when this
              call had to create the QApplication (standalone use); a host app that already
              runs Qt gets the window back immediately.
    """
    from .main_window import MainWindow
    app = QApplication.instance()
    created = app is None
    if created:
        app = QApplication(sys.argv[:1])
        app.setApplicationName("G-SEND.IO CAD")
    fonts = _style(app)
    path = None
    if isinstance(document, str):
        path, document = document, Document.load(document)
    win = MainWindow(document or bracket_plate(), fonts)
    if path:
        from pathlib import Path
        win.path = Path(path)
    win.show()
    if block if block is not None else created:
        app.exec()
    return win


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gsend_cad", description="G-SEND.IO CAD")
    ap.add_argument("file", nargs="?", help=".gcad document to open")
    args = ap.parse_args(argv)
    launch(args.file, block=True)
