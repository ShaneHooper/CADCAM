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
from PySide6.QtWidgets import QApplication, QWidget

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


def start_xy_sketch():
    """L. With a body on screen it asks for a face first (PlanePickSession); Enter = the XY plane."""
    key(Qt.Key_L)
    if type(win.session).__name__ == "PlanePickSession":
        key(Qt.Key_Return)

start_xy_sketch()
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

# ---- the palette shows the whole FROM ORIGIN section (9/30/26: rows were crushed to a few px)
pal = s.palette
pump()
rows = [w for w in pal.edit.findChildren(QWidget) if w.parent() is pal.edit and w.isVisible()]
check("every FROM ORIGIN row keeps its height", rows and all(w.height() >= 18 for w in rows))
check("the FROM ORIGIN section ends inside the palette", pal.edit.geometry().bottom() <= pal.height())
shot("dims_01b_palette")

# ---- right-click a dimension, type its value
def rclick(x, y):
    p = screen(x, y)
    QTest.mouseMove(vp.plotter, p)
    pump(30)
    QTest.mouseClick(vp.plotter, Qt.RightButton, Qt.NoModifier, p)
    pump(60)

c = s.ents[1]
rclick(c["c"][0], c["c"][1] + min(c["r"] * .35, .15))      # the Ø label of the circle
check("right-click on the Ø label opens the value box", s.editor.isVisible() and s.editor.label.text() == "Diameter")
shot("dims_01c_rclick")
QTest.keyClicks(s.editor.box, "1.5")
QTest.keyClick(s.editor.box, Qt.Key_Return)
pump(120)
check("Enter applies the typed diameter", abs(s.ents[1]["r"] - 0.75) < 1e-9 and not s.editor.isVisible())
check("the palette field follows", abs(s.palette.boxes["dia"].value() - 1.5) < 1e-9)
from gsend_cad.core import sketch as sk
xd = next(d for d in sk.dimensions(s.ents[1]) if d["key"] == "x")
(a, b) = xd["lines"][0]                                     # the X dimension line under the circle
rclick(a[0] + (b[0] - a[0]) * 0.25, a[1] + (b[1] - a[1]) * 0.25)   # on the line, away from its label
check("right-click on the X dimension line opens X", s.editor.isVisible() and s.editor.label.text() == "X")
QTest.keyClick(s.editor.box, Qt.Key_Escape)
pump(60)
check("Esc closes it and changes nothing", not s.editor.isVisible() and abs(s.ents[1]["c"][0] - 1.75) < 1e-9)
rclick(4, 4)                                               # empty space: not ours
check("right-click on nothing opens nothing", not s.editor.isVisible())
check("and the view is not left panning", vp.plotter.iren.interactor.GetInteractorStyle().GetState() == 0)
key(Qt.Key_Z, Qt.ControlModifier)
check("Ctrl+Z undoes the right-click edit", abs(s.ents[1]["r"] - 0.375) < 1e-9)

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

# ---- fast clicks must draw, never leave the view stuck orbiting; Undo button with Line armed
start_xy_sketch()
s = win.session
win.run_tool("Line")
a, b = screen(0, 0), screen(1, 0)
QTest.mouseClick(vp.plotter, Qt.LeftButton, Qt.NoModifier, a)
QTest.mouseDClick(vp.plotter, Qt.LeftButton, Qt.NoModifier, b)     # second click comes as a double-click
QTest.mouseRelease(vp.plotter, Qt.LeftButton, Qt.NoModifier, b)
pump()
check("fast second click draws the line", len(s.ents) == 1)
check("view is not left orbiting", vp.plotter.iren.interactor.GetInteractorStyle().GetState() == 0)
click(1, 1)
check("line chain has 2 lines, next start still armed", len(s.ents) == 2 and s.pts)
win.undo()                                          # the top bar's Undo button
check("Undo button removes the last line even with the chain armed", len(s.ents) == 1)
win.run_tool("Undo")                                # the ribbon's Undo
check("ribbon Undo removes the first line", len(s.ents) == 0)
win.redo()
check("Redo brings a line back", len(s.ents) == 1)
key(Qt.Key_Escape)
key(Qt.Key_Escape)
win.run_tool("Cancel")
pump()

# ---- a line started off the grid (on another line's end) stays level / plumb when drawn near it
start_xy_sketch()
s = win.session
s.ents.append(sk.line((0, 0), (0, 1.13)))            # a vertical line ending at y 1.13 (not on the grid)
s.origin.append(None)
s.redraw()
win.run_tool("Line")
click(0, 1.13)                                        # snaps to that end
click(2.0, 1.25)                                      # ~3.4° up: near level, and y 1.25 IS a grid point
e = s.ents[-1]
check("a nearly level line is held level from an off-grid start", e["type"] == "line"
      and abs(e["pts"][1][1] - 1.13) < 1e-9 and abs(e["pts"][1][0] - 2.0) < 1e-9)
click(2.12, 0.0)                                      # ~5.4° off plumb from (2, 1.13): held plumb
e = s.ents[-1]
check("a nearly plumb line is held plumb", abs(e["pts"][1][0] - 2.0) < 1e-9 and abs(e["pts"][1][1]) < 1e-9)
p = screen(3.0, 0.25)
QTest.mouseMove(vp.plotter, p, )
pump(30)
QTest.mouseClick(vp.plotter, Qt.LeftButton, Qt.ControlModifier, p)
pump(60)
e = s.ents[-1]
check("Ctrl draws at any angle", abs(e["pts"][1][1] - 0.25) < 1e-9)
key(Qt.Key_Escape)
key(Qt.Key_Escape)
win.run_tool("Cancel")

# ---- Trim: a cross of two lines, click the right arm: it goes back to the crossing
start_xy_sketch()
s = win.session
s.ents += [sk.line((0, 0), (2, 0)), sk.line((1, -1), (1, 1))]
s.origin += [None, None]
s.redraw()
win.run_tool("Trim")
check("Trim is a sketch tool", s.tool == "trim")
QTest.mouseMove(vp.plotter, screen(1.6, 0.0))
pump(60)
check("hovering shows the piece to cut away", vp.dim.isVisible() and "Trim" in vp.dim.text())
shot("sketch_trim_hover")
click(1.6, 0.0)
check("Trim cut the right arm back to the crossing",
      len(s.ents) == 2 and any(e["pts"] == [[0, 0], [1, 0]] for e in s.ents))
key(Qt.Key_Z, Qt.ControlModifier)
check("Ctrl+Z brings it back", len(s.ents) == 2 and any(e["pts"] == [[0, 0], [2, 0]] for e in s.ents))
key(Qt.Key_Escape)
win.run_tool("Cancel")
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
