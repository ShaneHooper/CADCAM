"""Drive exact 2D sketch values in the real window (xvfb-run) and save screenshots.

    xvfb-run -a -s "-screen 0 1600x1000x24" python tests/drive_sketch_dims.py OUTDIR

Draws a rectangle, a circle and a point, types exact sizes and positions from the origin,
picks by clicking in the view, deletes, undoes, and checks the finished sketch.
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


def click(x, y):
    p = screen(x, y)
    QTest.mouseMove(vp.plotter, p)
    pump(30)
    QTest.mouseClick(vp.plotter, Qt.LeftButton, Qt.NoModifier, p)
    pump(60)


def key(k, mod=Qt.NoModifier):
    QTest.keyClick(vp.plotter, k, mod)
    pump(120)


def type_value(field, text):
    """Click into a palette field, replace its text, press Enter (what a user does)."""
    box = win.session.palette.boxes[field]
    box.setFocus()
    box.selectAll()
    QTest.keyClicks(box, text)
    QTest.keyClick(box, Qt.Key_Return)
    pump(120)


def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def close(a, b):
    return all(abs(p - q) < 1e-9 for p, q in zip(a, b))


key(Qt.Key_L)
s = win.session
win.run_tool("Rectangle")
click(1, 1)
click(3, 2)
check("new rectangle is selected with its fields", s.sel == 0 and {"x", "y", "w", "h"} <= set(s.palette.boxes))
type_value("w", "2.5")
type_value("h", "1.25")
type_value("x", "0.5")
type_value("y", "-0.25")
r = s.ents[0]
check("rectangle typed to 2.5 x 1.25 at X0.5 Y-0.25",
      close(r["pts"][0], (0.5, -0.25)) and close(r["pts"][2], (3.0, 1.0)))
shot("dims_01_rect")

win.run_tool("Circle")
click(0, 0)
click(0.5, 0)
type_value("dia", "0.75")
type_value("x", "1.75")
type_value("y", "0.375")
c = s.ents[1]
check("circle typed to Ø0.75 at X1.75 Y0.375", close(c["c"], (1.75, 0.375)) and abs(c["r"] - 0.375) < 1e-9)
type_value("dia", "0")
check("zero diameter is refused", abs(s.ents[1]["r"] - 0.375) < 1e-9)

win.run_tool("Point")
click(4, 2)
check("point placed and selected", s.ents[2] == {"type": "point", "p": [4.0, 2.0]} and s.sel == 2)

win.run_tool("Line")
click(0, 2)
click(1, 2)
key(Qt.Key_Escape)
type_value("len", "2")
type_value("ang", "45")
ln = s.ents[3]
check("line length 2 at 45°", close(ln["pts"][1], (math.sqrt(2), 2 + math.sqrt(2))))

key(Qt.Key_Escape)                 # select mode
click(3.0, 0.4)                    # right edge of the rectangle
check("clicking the rectangle's edge selects it", s.sel == 0)
win.session.palette.all_dims.setChecked(True)
shot("dims_02_all")
key(Qt.Key_Delete)
check("Delete removes the selected rectangle", len(s.ents) == 3 and s.ents[0]["type"] == "circle")
key(Qt.Key_Z, Qt.ControlModifier)
check("Ctrl+Z brings it back", len(s.ents) == 4 and s.ents[0]["type"] == "rect")
key(Qt.Key_Z, Qt.ControlModifier)  # undoes the line's 45° edit
check("Ctrl+Z also undoes a typed value", close(s.ents[3]["pts"][1], (2, 2)))

key(Qt.Key_Return)
f = win.doc.features[-1]
check("finished sketch keeps 4 entities incl. the point",
      f["kind"] == "sketch" and [e["type"] for e in f["ents"]] == ["rect", "circle", "point", "line"])
shot("dims_03_done")
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
