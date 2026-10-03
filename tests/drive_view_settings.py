"""Drive Settings → View projection in the real window.

    xvfb-run -a -s "-screen 0 1600x1000x24" python tests/drive_view_settings.py OUTDIR
"""
import os
import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

QSettings("G-SEND", "CADCAM").remove("view/projection")      # start from the default
import gsend_cad

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
app = QApplication(sys.argv[:1])
win = gsend_cad.launch(block=False)
win.move(0, 0)
vp = win.viewport
cam = vp.plotter.camera
failures = []


def pump(ms=150):
    QTest.qWait(ms)


def shot(name):
    pump(300)
    from PIL import ImageGrab
    g = win.frameGeometry()
    ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).crop((g.x(), g.y(), g.x() + 1400, g.y() + 820)).save(
        os.path.join(OUT, name + ".png"))


def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


check("default is orthographic (straight)", vp.projection == "ortho" and cam.parallel_projection
      and win.topbar.proj_actions["ortho"].isChecked())
check("ortho framing matches the old view (not tiny / huge)", 1.0 < cam.parallel_scale < 10)
vp.set_view("right")
shot("view_right_ortho")
win.topbar.proj_actions["persp"].trigger()
pump()
check("Perspective turns parallel off, even on RIGHT", not cam.parallel_projection and vp.projection == "persp")
shot("view_right_persp")
win.topbar.proj_actions["persp-ortho-faces"].trigger()
pump()
check("ortho faces: RIGHT is straight", cam.parallel_projection)
vp.set_view("home")
check("ortho faces: HOME is perspective", not cam.parallel_projection)
vp.set_view("front")
check("ortho faces: FRONT is straight", cam.parallel_projection)
check("choice is remembered", QSettings("G-SEND", "CADCAM").value("view/projection") == "persp-ortho-faces")
QTest.keyClick(vp.plotter, Qt.Key_L)
pump()
if win.session.__class__.__name__ == "PlanePickSession":
    QTest.keyClick(vp.plotter, Qt.Key_Return)
    pump()
check("sketch looks straight down", cam.parallel_projection)
win.run_tool("Cancel")
pump()
check("leaving the sketch hands back to the setting (HOME = perspective)", not cam.parallel_projection)
win.topbar.proj_actions["ortho"].trigger()
QSettings("G-SEND", "CADCAM").setValue("view/projection", "ortho")

# ---- right-click (no drag) → Direct View: snap to the nearest straight view, same zoom
import numpy as np
from PySide6.QtCore import QPoint
vp.set_view("front")
cam.Azimuth(25)
cam.Elevation(-18)                              # tilted off FRONT
vp.plotter.render()
d0 = cam.distance
c = QPoint(vp.plotter.width() // 2, vp.plotter.height() // 2)
QTest.mousePress(vp.plotter, Qt.RightButton, Qt.NoModifier, c)
QTest.mouseRelease(vp.plotter, Qt.RightButton, Qt.NoModifier, c)
pump(200)
m = getattr(vp, "_menu", None)
acts = m.actions() if m else []
check("right-click shows Direct View (nearest: FRONT)", len(acts) == 3 and acts[0].text().startswith("Direct View")
      and "FRONT" in acts[0].text())
if m:
    m.close()
acts and acts[0].trigger()
pump()
v = np.subtract(cam.position, cam.focal_point)
check("Direct View looks straight at the front, same distance, ortho",
      np.allclose(v / np.linalg.norm(v), (0, -1, 0)) and abs(cam.distance - d0) < 1e-6 and cam.parallel_projection
      and vp.hud_view.text() == "FRONT")
check("menu also has Rotate View Clockwise / Counterclockwise",
      [x.text() for x in acts[1:]] == ["Rotate View Clockwise", "Rotate View Counterclockwise"])
vp.set_view("top")
x0 = vp.project([(1, 0, 0)])[0]
o0 = vp.project([(0, 0, 0)])[0]
acts[1].trigger()
pump()
x1, o1 = vp.project([(1, 0, 0)])[0], vp.project([(0, 0, 0)])[0]
check("clockwise: +X (was to the right) is now below on screen", x0[0] > o0[0] + 5 and x1[1] > o1[1] + 5
      and abs(x1[0] - o1[0]) < 2)
acts[2].trigger()
pump()
x2, o2 = vp.project([(1, 0, 0)])[0], vp.project([(0, 0, 0)])[0]
check("counterclockwise turns it back", x2[0] > o2[0] + 5 and abs(x2[1] - o2[1]) < 2)
vp.set_view("front")
cam.Elevation(70)
vp.plotter.render()
check("tilted mostly from above → TOP", vp.nearest_view() == "top")
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
