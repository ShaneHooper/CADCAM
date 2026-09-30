"""Drive 2D corner fillet / chamfer, Revolve and 3D edge fillet / chamfer in the real window.

    xvfb-run -a -s "-screen 0 1600x1000x24" python tests/drive_fillet_revolve.py OUTDIR
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
    q = vp.project([(x, y, z)])[0]
    return QPoint(round(q[0]), round(q[1]))


def click(x, y, z=0.0):
    p = screen(x, y, z)
    QTest.mouseMove(vp.plotter, p)
    pump(40)
    QTest.mouseClick(vp.plotter, Qt.LeftButton, Qt.NoModifier, p)
    pump(80)


def key(k, mod=Qt.NoModifier):
    QTest.keyClick(vp.plotter, k, mod)
    pump(150)


def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def vol():
    return sum(b.volume for b in win.model.bodies)


def sketch_xy():
    key(Qt.Key_L)
    if win.session.__class__.__name__ == "PlanePickSession":
        key(Qt.Key_Return)                     # XY plane
    return win.session


win.new_doc()
pump()

# ---- 2D: rectangle, round one corner, bevel another, extrude
s = sketch_xy()
win.run_tool("Rectangle")
click(0, 0)
click(2, 1)
s.palette.corner.setValue(0.25)
win.run_tool("Fillet")
click(2, 1)
check("sketch fillet makes an arc", any(e["type"] == "arc" and abs(e["r"] - 0.25) < 1e-9 for e in s.ents))
s.palette.corner.setValue(0.2)
win.run_tool("Chamfer")
click(0, 0)
check("sketch chamfer adds a bevel line", len(s.ents) == 6)
win.run_tool("Chamfer")
click(1, 0.5)
check("click away from a corner changes nothing", len(s.ents) == 6)
shot("fr_01_sketch")
key(Qt.Key_Return)
key(Qt.Key_E)
win.session.panel.dist.setValue(1.0)
key(Qt.Key_Return)
area = 2 - 0.25 ** 2 * (1 - math.pi / 4) - 0.02
check("filleted + chamfered profile extrudes exactly", abs(vol() - area) < 1e-6 and not win.model.errors)

# ---- 3D: fillet two vertical edges of the block
vp.set_view("home")
pump()
win.run_tool("Fillet")
es = win.session
check("Fillet opens the edge picker", es.__class__.__name__ == "EdgeSession")
for x, y in ((0, 1), (2, 0)):
    click(x, y, 0.5)
check("clicking two vertical edges selects them", len(es.sel) == 2)
es.panel.size.setValue(0.125)
shot("fr_02_edges")
key(Qt.Key_Return)
f = win.doc.features[-1]
cut = 2 * 0.125 ** 2 * (1 - math.pi / 4) * 1.0
check("3D fillet rounds both edges", f["kind"] == "fillet" and abs(vol() - (area - cut)) < 1e-6 and not win.model.errors)
before = vol()
win.run_tool("Chamfer")
click(1, 1, 1.0)                               # top back edge: flows into the rounded corners
win.session.panel.size.setValue(0.05)          # (must stay under their 0.125 radius)
key(Qt.Key_Return)
check("3D chamfer runs along the smooth top edge chain", win.doc.features[-1]["name"].startswith("Chamfer") and vol() < before - 1e-4
      and not win.model.errors)
shot("fr_03_solid")

# ---- Revolve: a half cross-section above the X axis -> a turned part
win.dirty = False                              # skip the save question
win.new_doc()
pump()
s = sketch_xy()
win.run_tool("Rectangle")
click(0, 0.5)
click(2, 1)
win.run_tool("Rectangle")
click(2, 0.5)
click(3, 0.75)
key(Qt.Key_Return)
win.run_tool("Revolve")
rs = win.session
click(1, 0.75)
click(2.5, 0.6)
check("Revolve picks 2 profiles, axis defaults to sketch X", len(rs.sel) == 2 and rs.panel.axis.currentData()[0] == "x")
shot("fr_04_revolve")
key(Qt.Key_Return)
want = math.pi * (1 - 0.25) * 2 + math.pi * (0.75 ** 2 - 0.25) * 1
check("revolve makes the turned part (bore Ø1)", abs(vol() - want) < 1e-6 and not win.model.errors)
vp.set_view("home")
shot("fr_05_turned")
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
