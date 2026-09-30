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
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
