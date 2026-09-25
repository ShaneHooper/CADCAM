"""Start the CAD window, standalone or from a host app such as G-SEND.IO."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication

from .. import APP_NAME
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
        if sys.platform == "win32":     # own taskbar entry, so Windows shows the G00 logo, not Python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("G00.CAM")
        app = QApplication(sys.argv[:1])
        app.setApplicationName(APP_NAME)
    app.setWindowIcon(theme.app_icon())
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


def log_dir():
    import os
    from pathlib import Path
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".local", "state")
    d = Path(base) / "G00CAM"
    d.mkdir(parents=True, exist_ok=True)
    return d


def selftest(report: str) -> int:
    """Check a packaged build end to end without a screen: kernel, STEP export, and every UI
    module imports. The windowed .exe has no console, so results go to the `report` file."""
    import tempfile
    import traceback
    lines, ok = [], True
    try:
        from ..kernel import Kernel
        m = Kernel().build(bracket_plate())
        lines.append(f"kernel: {len(m.bodies)} body, volume {m.bodies[0].volume:.4f} in3")
        step = Path(tempfile.gettempdir()) / "g00cam_selftest.step"
        m.export_step(step)
        lines.append(f"step: {step.stat().st_size} bytes")
        import pyvista  # noqa: F401
        import pyvistaqt  # noqa: F401
        from . import commands, docs, main_window, panels, viewport  # noqa: F401
        lines.append("ui modules: imported")
        lines.append(f"logo: {theme.LOGO_PNG.exists()}  fonts: {len(list(theme.FONT_DIR.glob('*.ttf')))}")
        import os
        if os.environ.get("G00CAM_SELFTEST_WINDOW"):      # also open, render and close the real window
            from PySide6.QtTest import QTest
            win = launch(None, block=False)
            QTest.qWait(1500)
            shot = os.environ.get("G00CAM_SELFTEST_SHOT")
            if shot:
                win.grab().save(shot)
            lines.append(f"window: {win.width()}x{win.height()}, bodies shown {len(win.model.bodies)}")
            win.dirty = False
            win.close()
    except Exception:
        ok = False
        lines.append(traceback.format_exc())
    lines.append("G00 CAM selftest " + ("OK" if ok else "FAILED"))
    Path(report).write_text("\n".join(lines), encoding="utf-8")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="g00cam", description=APP_NAME)
    ap.add_argument("file", nargs="?", help=".gcad document to open")
    ap.add_argument("--selftest", metavar="REPORT", help="check the install, write results to REPORT, exit")
    args = ap.parse_args(argv)
    if args.selftest:
        sys.exit(selftest(args.selftest))
    try:
        launch(args.file, block=True)
    except Exception:
        # the windowed .exe has no console: keep the error and show where it went
        import traceback
        log = log_dir() / "crash.log"
        log.write_text(traceback.format_exc(), encoding="utf-8")
        try:
            from PySide6.QtWidgets import QMessageBox
            QApplication.instance() or QApplication(sys.argv[:1])
            QMessageBox.critical(None, APP_NAME, f"{APP_NAME} hit an error and has to close.\n\nDetails: {log}")
        except Exception:
            pass
        raise
