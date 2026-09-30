"""Drive CAM → Setup (Milling and Turning) in the real window and save screenshots.

    xvfb-run -a -s "-screen 0 1600x1000x24" python tests/drive_cam_setup.py OUTDIR
"""
import os
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import gsend_cad
from gsend_cad.core import sketch as sk
from gsend_cad.core import sketch_regions

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


def key(k):
    QTest.keyClick(vp.plotter, k)
    pump(150)


def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


# ---- milling setup on the demo plate
QTest.mouseClick(win.ribbon.switch, Qt.LeftButton, Qt.NoModifier, QPoint(80, 10))
pump()
check("CAM mode on", win.ribbon.switch.mode == "cam")
win.run_tool("Setup")
s = win.session
check("Setup from the Milling tab starts as Milling", s.__class__.__name__ == "SetupSession" and s.kind == "milling"
      and s.panel.mill.isVisible() and not s.panel.turn.isVisible())
s.panel.side.setValue(0.25)
shot("cam_01_milling")
key(Qt.Key_Return)
d = win.doc
check("Setup1 saved as milling with 0.25 side stock",
      len(d.setups) == 1 and d.setups[0]["type"] == "milling" and d.setups[0]["stock"]["side"] == 0.25)
check("Setup1 listed in the Browser", "setup1" in win.browser.setup_ids)

# the Milling / Turning choice inside the panel
win.run_tool("Setup")
s = win.session
QTest.mouseClick(s.panel.type_btn["turning"], Qt.LeftButton)
pump()
check("TURNING button switches the fields", s.kind == "turning" and s.panel.turn.isVisible()
      and not s.panel.mill.isVisible() and s.panel.type_btn["turning"].isChecked())
key(Qt.Key_Escape)
check("Esc cancels without a new setup", len(d.setups) == 1 and win.session is None)

# edit from the Browser, delete, undo
win.browser.edit.emit("setup1")
pump()
s = win.session
check("double-click opens Setup1 for editing", s is not None and s.edit_id == "setup1" and abs(s.panel.side.value() - 0.25) < 1e-9)
s.panel.top.setValue(0.1)
key(Qt.Key_Return)
check("edit saved in place", len(d.setups) == 1 and d.setups[0]["stock"]["top"] == 0.1)
win.delete_node("setup1")
check("Delete removes it", not win.doc.setups)
win.undo()
check("Ctrl+Z brings it back", len(win.doc.setups) == 1)

# ---- turning setup on a revolved part (axis = model X)
win.dirty = False
win.new_doc()
doc = win.doc
sid = doc.add_sketch([sk.rect((0, 0), (2, 0.75)), sk.rect((2, 0), (3, 0.5))])
regs = sketch_regions(sid["id"], sid["ents"])
doc.add_revolve([r.to_data() for r in regs], {"sketch": sid["id"], "kind": "x"})
win.rebuild(fit=True)
win.ribbon.show_mode("cam")
win.select_tab("turning")
win.run_tool("Setup")
s = win.session
check("Setup from the Turning tab starts as Turning, axis guessed X",
      s.kind == "turning" and s.panel.axis.currentData() == "x")
shot("cam_02_turning")
key(Qt.Key_Return)
t = win.doc.setups[-1]
check("turning setup saved", t["type"] == "turning" and t["axis"] == "x" and t["wcs"] == "stock-face")
from gsend_cad.core import cam
from gsend_cad.kernel import bodies_bbox, max_radius
bb = bodies_bbox(win.model.bodies)
r = max_radius(win.model.bodies, (0, 0, 0), (1, 0, 0))
c = cam.stock_cylinder(bb, r, t)
check("bar stock Ø = part Ø1.5 + 2 × 0.05", abs(c["r"] * 2 - 1.6) < 5e-3)
check("WCS Z0 on the front face of the stock", abs(cam.wcs(bb, t, r)["origin"][0] - 3.05) < 1e-6)
shot("cam_03_turning_saved")
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
