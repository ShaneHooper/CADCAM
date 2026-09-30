"""Drive CAM → Setup (Milling and Turning) in the real window and save screenshots.

    xvfb-run -a -s "-screen 0 1600x1000x24" python tests/drive_cam_setup.py OUTDIR
"""
import os
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import gsend_cad
from gsend_cad.ui.commands import op_moves
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

# Fixed size stock: switching fills in part + per-side stock, rounded up to 1/8
win.run_tool("Setup")
s = win.session
s.panel.mode.setCurrentIndex(s.panel.mode.findData("size"))
pump()
check("Fixed size shows size fields, hides per-side ones",
      s.panel.sx.isVisible() and not s.panel.side.isVisible() and s.panel.top.isVisible())
check("sizes filled from the 4 x 3 x 1.25 part + stock, 1/8 up",
      (s.panel.sx.value(), s.panel.sy.value(), s.panel.sz.value()) == (4.25, 3.25, 1.375))
shot("cam_01b_fixed")
s.panel.sx.setValue(3.9)
key(Qt.Key_Return)
check("stock smaller than the part is refused", win.session is s and len(win.doc.setups) == 1)
s.panel.sx.setValue(4.5)
key(Qt.Key_Return)
check("fixed-size setup saved", len(win.doc.setups) == 2 and win.doc.setups[1]["stock"] ==
      {"mode": "size", "x": 4.5, "y": 3.25, "z": 1.375, "top": 0.05})
win.delete_node("setup2")

# pick the WCS origin in the view (hover lights up a point, click sets it) and turn X
win.run_tool("Setup")
s = win.session
s.panel.pick.setChecked(True)
check("PICK IN VIEW turns picking on", s.picking)
target = (-2.0, 0.0, 0.5)                          # middle of the plate's left top edge
from gsend_cad.core import cam as _cam
pts = s.snaps()
check("snap list has model ends/mids/centers and stock corners",
      {k for _p, k in pts} >= {"end", "mid", "center", "stock corner", "stock face center"})
q = vp.project([target])[0]
pos = QPoint(round(q[0]), round(q[1]))
QTest.mouseMove(vp.plotter, pos)
pump(100)
check("hovering lights up the midpoint", s.hover is not None and s.hover[1] == "mid"
      and all(abs(a - b) < 1e-6 for a, b in zip(s.hover[0], target)))
shot("cam_01c_pick")
QTest.mouseClick(vp.plotter, Qt.LeftButton, Qt.NoModifier, pos)
pump(100)
check("click puts the origin there", s.wcs_point == [-2.0, 0.0, 0.5] and s.panel.mwcs.currentData() == "point"
      and not s.picking)
s.panel.xdir.setCurrentIndex(s.panel.xdir.findData("-y"))
key(Qt.Key_Return)
ps = win.doc.setups[-1]
check("picked point + X along -Y saved", ps["wcs"] == "point" and ps["wcs_point"] == [-2.0, 0.0, 0.5]
      and ps["x_dir"] == "-y")
w = _cam.wcs(((-2, -1.5, 0), (2, 1.5, 1.25)), ps)
check("WCS X axis now points along model -Y", w["x"] == [0.0, -1.0, 0.0])
win.delete_node(ps["id"])

from gsend_cad.core import sketch as _sk
win.doc.add_sketch([_sk.point((1.25, 0.75))], plane_z=0.5)      # a point drawn in CAD, on the plate top
win.rebuild()
win.run_tool("Setup")
check("a CAD sketch point is pickable", any(k == "point" and all(abs(a - b) < 1e-9 for a, b in zip(p, (1.25, 0.75, 0.5)))
                                             for p, k in win.session.snaps()))
key(Qt.Key_Escape)
win.undo_stack.clear()

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
win.run_tool("Setup")
s = win.session
s.panel.mode.setCurrentIndex(s.panel.mode.findData("size"))
pump()
check("turning Fixed size: bar Ø and length filled (Ø1.6 -> 1.625)",
      s.panel.dia.isVisible() and s.panel.dia.value() == 1.625 and not s.panel.od.isVisible())
key(Qt.Key_Escape)
check("turning setup saved", t["type"] == "turning" and t["axis"] == "x" and t["wcs"] == "stock-face")
from gsend_cad.core import cam
from gsend_cad.kernel import bodies_bbox, max_radius
bb = bodies_bbox(win.model.bodies)
r = max_radius(win.model.bodies, (0, 0, 0), (1, 0, 0))
c = cam.stock_cylinder(bb, r, t)
check("bar stock Ø = part Ø1.5 + 2 × 0.05", abs(c["r"] * 2 - 1.6) < 5e-3)
check("WCS Z0 on the front face of the stock", abs(cam.wcs(bb, t, r)["origin"][0] - 3.05) < 1e-6)
shot("cam_03_turning_saved")

# ---- Face: turning setup (tab = Turning), then a milling one
win.run_tool("Face")
o = win.session
check("Face opens on the turning setup with turning fields",
      o.__class__.__name__ == "OpSession" and o.current_setup()["type"] == "turning"
      and o.panel.groups["turning"].isVisible() and not o.panel.groups["milling"].isVisible())
o.panel.boxes[("turning", "stepdown")].setValue(0.02)
o.panel.output.setCurrentIndex(o.panel.output.findData("cycle"))
check("turning Face has the Output choice (G94 cycle)", o.panel.output.isVisible() and o.op()["output"] == "cycle")
check("preview says 3 passes (0.05 face stock / 0.02)", o.panel.info.text().startswith("3 depth passes"))
shot("cam_04_face_turning")
key(Qt.Key_Return)
st = win.doc.setups[-1]
check("Face1 saved in the turning setup, listed in the Browser",
      [x["name"] for x in st.get("ops", [])] == ["Face1"] and st["ops"][0]["id"] in win.browser.setup_ids)
check("Face1 keeps the canned cycle output", st["ops"][0]["output"] == "cycle")

# ---- OD Rough on the turning setup (Ø1.5 x 2 then Ø1 x 1, front at +X)
win.select_tab("turning")
win.run_tool("OD Rough")
o = win.session
check("OD Rough opens on the turning setup", o.__class__.__name__ == "OpSession" and o.kind == "rough"
      and o.current_setup()["type"] == "turning")
mv, _w = op_moves(win, o.current_setup(), o.op())
feeds = [p for k, p in mv if k == "feed"]
check("rough stops at the shoulder + leave Z, never below the part + leave X",
      min(p[0] for p in feeds) >= 0.5 + 0.01 - 1e-6
      and all(p[0] >= 0.75 + 0.01 - 1e-6 for p in feeds if p[2] < -1.05 - 0.005 - 1e-6))
check("rough preview counts passes", "roughing pass" in o.panel.info.text())
o.panel.output.setCurrentIndex(o.panel.output.findData("cycle"))
shot("cam_04b_rough")
key(Qt.Key_Return)
st = win.doc.setups[-1]
check("OD Rough1 saved after Face1", [x["name"] for x in st["ops"]] == ["Face1", "OD Rough1"])
win.run_tool("Contour")
o = win.session
check("turning Contour opens with the G70 box", o.kind == "finish" and o.panel.g70.isVisible()
      and o.panel.title.text() == "CONTOUR")
o.panel.g70.setChecked(True)
shot("cam_04c_contour")
key(Qt.Key_Return)
check("Contour1 saved after the rough", [x["name"] for x in st["ops"]] == ["Face1", "OD Rough1", "Contour1"])
from gsend_cad.core import post
g = post.post_setup(st, [(cam.validate_op(st, x), op_moves(win, st, x)[0]) for x in st["ops"]], "haas", 1)
check("post writes G94 face + G71 rough with its contour", "G94 " in g and "G71 P200 Q201" in g and "N200 G00 X1.\n" in g and "X1.5\n" in g
      and "G70 P200 Q201" in g)

win.select_tab("milling")
win.run_tool("Setup")
key(Qt.Key_Return)                               # a milling setup on the same part
win.run_tool("Face")
o = win.session
check("Face from the Milling tab picks the milling setup", o.current_setup()["type"] == "milling"
      and o.panel.groups["milling"].isVisible())
o.panel.boxes[("milling", "tool_dia")].setValue(1.0)
shot("cam_05_face_milling")
key(Qt.Key_Return)
ms = win.doc.setups[-1]
oid = ms["ops"][0]["id"]
check("milling Face saved with the Ø1 tool", ms["ops"][0]["tool_dia"] == 1.0)
win.browser.edit.emit(oid)
pump()
check("double-click reopens the Face op", win.session.edit_id == oid and
      win.session.panel.boxes[("milling", "tool_dia")].value() == 1.0)
key(Qt.Key_Escape)
win.delete_node(oid)
check("Delete removes the op", not win.doc.setup(ms["id"]).get("ops"))
win.undo()
check("Ctrl+Z restores it", len(win.doc.setup(ms["id"])["ops"]) == 1)

# ---- Post Process: G-code for the milling setup, saved to a file
win.cam_setup = ms["id"]
win.run_tool("Post Process")
pump()
dlg = win.post_dialog
g = dlg.text.toPlainText()
check("Post dialog shows G-code for the milling setup", g.startswith("%\nO") and "T1 M06" in g and "M30" in g)
dlg.control.setCurrentIndex(dlg.control.findData("fanuc"))
check("switching to Fanuc updates the code", "G28 G91 X0. Y0." in dlg.text.toPlainText())
from PySide6.QtWidgets import QFileDialog
out = os.path.join(OUT, "post_test.nc")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out, ""))
dlg.save()
check(".nc file written with CRLF line ends", open(out, "rb").read().count(b"\r\n") == len(g.splitlines()))
check("post settings remembered on the setup", win.doc.setup(ms["id"])["post"]["controller"] == "fanuc")
shot("cam_06_post")
dlg.close()

# ---- 2D Contour on the milling setup, then Simulate / Post Process from the right-click menu
win.cam_setup = ms["id"]
win.run_tool("2D Contour")
o = win.session
check("2D Contour opens on the milling setup", o.__class__.__name__ == "OpSession" and o.kind == "contour"
      and o.current_setup()["id"] == ms["id"])
check("contour preview has passes", "depth pass" in o.panel.info.text())
shot("cam_07_contour")
key(Qt.Key_Return)
cop = win.doc.setup(ms["id"])["ops"][-1]
check("Contour1 saved", cop["type"] == "contour" and cop["name"] == "Contour1")
win.browser.simulate.emit(cop["id"])
pump()
sim = win.session
check("right-click Simulate opens the simulator on that op", sim.__class__.__name__ == "SimSession"
      and len(sim.world) > 10 and sim.panel.step.text().endswith("Contour1"))
sim.seek(sim.total / 2)
mid = tuple(sim.tool.GetPosition())
check("scrubbing moves the tool along the path", mid != (0.0, 0.0, 0.0) and "/" in sim.panel.time.text())
sim.panel.speed.setCurrentIndex(sim.panel.speed.count() - 1)
sim.toggle()
pump(600)
check("Play advances the tool", sim.t > sim.total / 2)
shot("cam_08_simulate")
key(Qt.Key_Escape)
check("Esc closes the simulator", win.session is None)
win.browser.simulate.emit(ms["id"])
pump()
check("Simulate on a setup plays all its ops", len({id(x) for x in win.session.op_of}) == 2)
key(Qt.Key_Escape)
win.browser.post.emit(cop["id"])
pump()
g = win.post_dialog.text.toPlainText()
check("right-click Post Process posts that op's setup (face + contour)", "FACE MILL" in g and "2D CONTOUR" in g
      and "T2 M06" in g)
win.post_dialog.close()
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
