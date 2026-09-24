"""Drive the real window under a display (xvfb-run) and save screenshots.

    xvfb-run -a -s "-screen 0 1600x1000x24" python tests/drive_ui.py OUTDIR

Draws a rect + circle sketch, cuts the ring through the plate, adds a joined boss and a
new body, rolls the timeline back, and checks volumes along the way.
"""
import math
import os
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import gsend_cad

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
app = QApplication(sys.argv[:1])
win = gsend_cad.launch(block=False)
win.move(0, 0)
vp = win.viewport
failures = []


def pump(ms=150):
    QTest.qWait(ms)


def shot(name):
    pump(300)
    from PIL import ImageGrab
    g = win.frameGeometry()
    ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).crop((g.x(), g.y(), g.x() + 1400, g.y() + 820)).save(
        os.path.join(OUT, name + ".png"))


def screen(x, y, z=0.0):
    ren = vp.plotter.renderer
    ren.SetWorldPoint(x, y, z, 1)
    ren.WorldToDisplay()
    dx, dy, _ = ren.GetDisplayPoint()
    r = vp.plotter.devicePixelRatioF()
    return QPoint(round(dx / r), round(vp.plotter.height() - dy / r))


def click(x, y, z=0.0):
    p = screen(x, y, z)
    QTest.mouseMove(vp.plotter, p)
    pump(30)
    QTest.mouseClick(vp.plotter, Qt.LeftButton, Qt.NoModifier, p)
    pump(60)


def key(k, mod=Qt.NoModifier):
    QTest.keyClick(vp.plotter, k, mod)
    pump(120)


def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def vol():
    return win.model.bodies[0].volume


print("WINDOW", win.width(), win.height(), win.minimumSizeHint())
shot("01_main")
base = vol()
check("demo part builds with one body", len(win.model.bodies) == 1 and not win.model.errors)

# Sketch: rect with a circle inside
key(Qt.Key_L)
win.run_tool("Rectangle")
click(0.75, -0.75)
click(1.75, 0.75)
win.run_tool("Circle")
click(1.25, 0)
QTest.mouseMove(vp.plotter, screen(1.5, 0))
pump(100)
shot("02_sketch")
click(1.5, 0)
check("sketch has 2 entities", len(win.session.ents) == 2)
key(Qt.Key_Return)
check("Sketch3 added", win.doc.features[-1]["name"] == "Sketch3")

# Extrude: pick the ring region, cut through
key(Qt.Key_E)
vp.set_view("top")
pump()
click(0.9, 0.6)
s = win.session
check("ring selected", len(s.sel) == 1)
s.panel.op.setCurrentIndex(1)
s.panel.dist.setValue(0.5)
vp.set_view("home")
shot("03_extrude_preview")
key(Qt.Key_Return)
removed = (1.5 - math.pi * 0.0625) * 0.5
check(f"cut removed {removed:.4f} in³", abs((base - vol()) - removed) < 1e-3)

# Sketch on the plate top, join a boss
key(Qt.Key_L)
win.session.palette.plane.setValue(0.5)
win.run_tool("Circle")
click(-1.25, 0, 0.5)
click(-1.0, 0, 0.5)
key(Qt.Key_Return)
key(Qt.Key_E)
win.session.panel.dist.setValue(0.75)
key(Qt.Key_Return)
check("join boss added", abs(vol() - (base - removed + math.pi * 0.0625 * 0.75)) < 1e-3)

# New body: hex off the plate, symmetric
key(Qt.Key_L)
win.run_tool("Polygon")
click(0, -2.5)
click(0.5, -2.5)
key(Qt.Key_Return)
key(Qt.Key_E)
win.session.panel.op.setCurrentIndex(2)
win.session.panel.dist.setValue(0.75)
key(Qt.Key_Return)
check("two bodies", [b.name for b in win.model.bodies] == ["Body1", "Body2"])
shot("04_result")

# Roll back to just after the cut
win.roll_to(8)
pump()
check("rollback hides Body2", len(win.model.bodies) == 1)
shot("05_rolled_back")
win.roll_to(len(win.doc.features))

# Undo the last extrude
key(Qt.Key_Z, Qt.ControlModifier)
check("undo removes Body2", len(win.model.bodies) == 1)

win.dirty = False
win.close()
print("FAILURES:", failures)
sys.exit(1 if failures else 0)
