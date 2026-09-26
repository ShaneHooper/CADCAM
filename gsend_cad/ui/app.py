"""Start the CAD window, standalone or from a host app such as G-SEND.IO."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

from PySide6.QtWidgets import QApplication

from .. import APP_NAME
from ..core import Document, bracket_plate
from . import theme


def _style(app: QApplication) -> dict:
    theme.load_fonts()
    head, mono = theme.pick(theme.HEAD), theme.pick(theme.MONO)
    app.setStyleSheet(theme.qss(head, mono))
    return {"head": head, "mono": mono, "g": theme.pick(theme.BRAND_G), "wm": theme.pick(theme.BRAND_WM)}


_TRACE: Path | None = None       # startup.log, only when G00 CAM runs as its own program
_NATIVE = None                    # open file faulthandler writes hard crashes to


def _trace(msg: str):
    """Breadcrumbs in %LOCALAPPDATA%\\G00CAM\\startup.log: when the windowed .exe dies without a
    word (a crash inside OpenGL / VTK), the last line says how far it got."""
    if _TRACE:
        try:
            with open(_TRACE, "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except OSError:
            pass


def _splash(app):
    """G00 logo right away: loading OpenCascade + VTK takes seconds (much longer on a first
    start while antivirus scans the files), and without this nothing shows at all."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap
    from PySide6.QtWidgets import QSplashScreen
    dpr = 2
    pm = QPixmap(420 * dpr, 190 * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(QColor(theme.PANEL))
    p = QPainter(pm)
    p.setPen(QColor(theme.ACCENT))
    p.drawRect(0, 0, 419, 189)
    logo = theme.logo_pixmap(84)
    p.drawPixmap(int((420 - logo.width() / logo.devicePixelRatio()) / 2), 30, logo)
    p.end()
    sp = QSplashScreen(pm)
    sp.showMessage(f"{APP_NAME}  ·  loading…", Qt.AlignHCenter | Qt.AlignBottom, QColor(theme.FG2))
    sp.show()
    app.processEvents()
    return sp


def opengl_info() -> dict:
    """What OpenGL this machine gives Qt. The 3D view (VTK) needs 3.2 or newer."""
    from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    info = {"ok": False, "version": "none", "renderer": "unknown"}
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 2)
    fmt.setProfile(QSurfaceFormat.CompatibilityProfile)
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    if not ctx.create():
        return info
    surf = QOffscreenSurface()
    surf.setFormat(ctx.format())
    surf.create()
    ver = tuple(ctx.format().version())
    info["version"] = "%d.%d" % ver
    if ctx.makeCurrent(surf):
        try:
            f = ctx.functions()
            info["renderer"] = f"{f.glGetString(0x1F01)} ({f.glGetString(0x1F00)})"   # GL_RENDERER, GL_VENDOR
        except Exception:
            pass
        ctx.doneCurrent()
    info["ok"] = ver >= (3, 2)
    return info


def _vtk_log_to_file():
    """VTK reports OpenGL trouble to its own output window; keep it in vtk.log instead."""
    try:
        from vtkmodules.vtkCommonCore import vtkFileOutputWindow, vtkOutputWindow
        w = vtkFileOutputWindow()
        w.SetFileName(str(log_dir() / "vtk.log"))
        w.FlushOn()
        vtkOutputWindow.SetInstance(w)
    except Exception:
        pass


def launch(document: Document | str | None = None, block: bool | None = None):
    """Open a CAD window and return it.

    document: a Document, a path to a .gcad file, or None for the demo Bracket Plate.
    block:    run the Qt event loop until the window closes. Defaults to True only when this
              call had to create the QApplication (standalone use); a host app that already
              runs Qt gets the window back immediately.
    """
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
    splash = _splash(app) if created else None
    _trace("qt started")
    if created:
        _report_last_crash(splash)
    from .main_window import MainWindow         # OpenCascade + VTK load here (the slow part)
    _trace("libraries loaded")
    if created:
        _vtk_log_to_file()
        gl = opengl_info()
        _trace(f"opengl {gl['version']} · {gl['renderer']}")
        if not gl["ok"] and not _gl_warning(gl, splash):
            sys.exit(3)
    path = None
    if isinstance(document, str):
        path, document = document, Document.load(document)
    win = MainWindow(document or bracket_plate(), fonts)
    if path:
        from pathlib import Path
        win.path = Path(path)
    win.show()
    if splash is not None:
        splash.finish(win)
    _trace("window shown")
    if block if block is not None else created:
        app.exec()
        _trace("closed")
    return win


def _gl_warning(gl, splash) -> bool:
    """OpenGL older than 3.2: say so plainly instead of dying inside VTK. True = try anyway."""
    from PySide6.QtWidgets import QMessageBox
    if splash is not None:
        splash.hide()
    m = QMessageBox(QMessageBox.Warning, APP_NAME,
                    f"This computer's graphics give OpenGL {gl['version']} ({gl['renderer']}).\n"
                    f"{APP_NAME}'s 3D view needs OpenGL 3.2 or newer.\n\n"
                    "Usually fixed by updating the graphics driver (Intel / AMD / NVIDIA website, "
                    "or Windows Update → Optional updates). Over Remote Desktop, run it on the "
                    "computer itself.")
    m.addButton("Try anyway", QMessageBox.AcceptRole)
    close = m.addButton("Close", QMessageBox.RejectRole)
    m.exec()
    if splash is not None:
        splash.show()
    return m.clickedButton() is not close


def _report_last_crash(splash):
    """If the previous start died before its window showed (a hard crash leaves no error box),
    show what the logs caught so it can be sent in."""
    prev = getattr(_report_last_crash, "prev", "")
    if not prev or "window shown" in prev:
        return
    parts = []
    for name in ("native_crash.log", "vtk.log"):
        f = log_dir() / f"{name}.prev"
        if f.exists() and f.stat().st_size:
            parts.append(f"--- {name} ---\n" + f.read_text(encoding="utf-8", errors="replace")[-1500:])
    if not parts:
        return
    from PySide6.QtWidgets import QMessageBox
    if splash is not None:
        splash.hide()
    last = prev.strip().splitlines()[-1] if prev.strip() else "?"
    QMessageBox.warning(None, APP_NAME,
                        f"{APP_NAME} closed while starting last time (last step: {last}).\n\n"
                        + "\n".join(parts)[-2500:]
                        + f"\n\nLogs: {log_dir()}\nIt will try again now.")
    if splash is not None:
        splash.show()


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
    import os
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
        if os.environ.get("G00CAM_SELFTEST_WINDOW") or sys.platform == "win32":
            app = QApplication.instance() or QApplication(sys.argv[:1])
            gl = opengl_info()
            lines.append(f"opengl: {gl['version']} {'OK' if gl['ok'] else 'TOO OLD (needs 3.2)'} · {gl['renderer']}")
        if os.environ.get("G00CAM_SELFTEST_WINDOW"):      # also open, render and close the real window
            from PySide6.QtTest import QTest
            win = launch(None, block=False)
            QTest.qWait(1500)
            shot = os.environ.get("G00CAM_SELFTEST_SHOT")
            if shot:
                win.grab().save(shot)
            lines.append(f"window: {win.width()}x{win.height()}, bodies shown {len(win.model.bodies)}")
            lines.append(_exercise(win))
            win.dirty = False
            win.close()
    except Exception:
        ok = False
        lines.append(traceback.format_exc())
    lines.append("G00 CAM selftest " + ("OK" if ok else "FAILED"))
    Path(report).write_text("\n".join(lines), encoding="utf-8")
    return 0 if ok else 1


def _exercise(win) -> str:
    """Drive the main paths once inside a packaged build (sketch, edit, extrude preview + cut,
    docs, STL export) so a module left out of the build fails the self-test, not Shane."""
    import tempfile
    from ..core import sketch as sk
    from .commands import ExtrudeSession
    v0 = win.model.bodies[0].volume
    win.start_sketch()
    s = win.session
    s.ents += [sk.rect((0.75, -0.75), (1.75, 0.75)), sk.circle((1.25, 0), 0.25)]
    s.origin += [None, None]
    s.redraw()
    win.finish_sketch()
    sid = win.doc.features[-1]["id"]
    win.edit_sketch(sid)
    win.run_tool("Cancel")
    win.start_extrude()
    ex = win.session
    assert isinstance(ex, ExtrudeSession), "extrude did not start"
    ex.sel = [r.key for r in ex.regions if r.sketch == sid and r.holes]
    ex.panel.op.setCurrentIndex(1)
    ex.panel.dist.setValue(0.5)
    ex.update_preview()
    ex.commit()
    cut = v0 - win.model.bodies[0].volume
    assert cut > 0.5 and not win.model.errors, f"cut failed ({cut:.4f}, {win.model.errors})"
    win.toggle_sketch(sid)
    win.show_docs()
    win.docs.close()
    stl = Path(tempfile.gettempdir()) / "g00cam_selftest.stl"
    from build123d import export_stl
    export_stl(win.model.bodies[0].shape, str(stl))
    return f"exercise: sketch, edit, extrude cut {cut:.4f} in3, hide, docs, stl {stl.stat().st_size} bytes"


def _start_logs():
    """Standalone start: keep the last run's logs as *.prev, then log this one (startup.log
    breadcrumbs, hard crashes via faulthandler, VTK messages)."""
    global _TRACE, _NATIVE
    import faulthandler
    d = log_dir()
    _TRACE = d / "startup.log"
    try:
        _report_last_crash.prev = _TRACE.read_text(encoding="utf-8") if _TRACE.exists() else ""
        for name in ("native_crash.log", "vtk.log"):
            f = d / name
            if f.exists():
                f.replace(d / f"{name}.prev")
            else:
                (d / f"{name}.prev").unlink(missing_ok=True)
        _TRACE.write_text("", encoding="utf-8")
        _NATIVE = open(d / "native_crash.log", "w", encoding="utf-8")
        faulthandler.enable(file=_NATIVE, all_threads=True)
    except OSError:
        pass
    _trace(f"start {APP_NAME} {sys.executable}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="g00cam", description=APP_NAME)
    ap.add_argument("file", nargs="?", help=".gcad document to open")
    ap.add_argument("--selftest", metavar="REPORT", help="check the install, write results to REPORT, exit")
    args = ap.parse_args(argv)
    if args.selftest:
        sys.exit(selftest(args.selftest))
    _start_logs()
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
