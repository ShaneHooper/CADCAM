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
_lib = os.path.join(OUT, "tool_library_test.json")    # a fresh library (the defaults), not the user's
if os.path.exists(_lib):
    os.remove(_lib)
os.environ["GSEND_TOOL_LIBRARY"] = _lib
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
win.select_tab("milling")
win.run_tool("Setup")
QTest.mouseClick(win.session.panel.type_btn["turning"], Qt.LeftButton)
pump()
key(Qt.Key_Return)
check("a Turning setup made from the Milling tab switches the ribbon to the Turning toolpaths",
      win.ribbon.current == "turning" and win.doc.setups[-1]["type"] == "turning")
win.undo()
check("(undo removes that extra setup)", len(win.doc.setups) == 1)
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
check("turning Face has the Output choice (G72 cycle)", o.panel.output.isVisible() and o.op()["output"] == "cycle")
check("preview says 3 passes (0.05 face stock / 0.02)", o.panel.info.text().startswith("3 depth passes"))
shot("cam_04_face_turning")
key(Qt.Key_Return)
st = win.doc.setups[-1]
check("Face1 saved in the turning setup, listed in the Browser",
      [x["name"] for x in st.get("ops", [])] == ["Face"] and st["ops"][0]["id"] in win.browser.setup_ids)
check("Face1 keeps the canned cycle output", st["ops"][0]["output"] == "cycle")

# ---- Roughing on the turning setup (Ø1.5 x 2 then Ø1 x 1, front at +X)
win.select_tab("turning")
win.run_tool("Roughing")
o = win.session
check("Roughing opens on the turning setup", o.__class__.__name__ == "OpSession" and o.kind == "rough"
      and o.current_setup()["type"] == "turning")
mv, _w = op_moves(win, o.current_setup(), o.op())
feeds = [p for k, p in mv if k == "feed"]
check("rough stops at the shoulder + leave Z, never below the part + leave X",
      min(p[0] for p in feeds) >= 0.5 + 0.01 - 1e-6
      and all(p[0] >= 0.75 + 0.01 - 1e-6 for p in feeds if p[2] < -1.05 - 0.005 - 1e-6))
check("rough preview counts passes", "roughing pass" in o.panel.info.text())
check("rough panel: Tool from the library first, Start / End cursor buttons with Extend, no Setup / Name rows",
      o.panel.tools["turning"].currentText().startswith("T2 · CNMG Rough") and o.panel.ends["start"][1].isVisible()
      and not o.panel.setup.isVisible() and not o.panel.name.isVisible()
      and o.panel.boxes[("turning", "past_back")].isVisible())
bore_row = o.panel.boxes[("turning", "bore_dia")].parentWidget()
check("Roughing panel: Internal (ID) box, Drilled hole Ø row hidden while OD",
      o.panel.internal.isVisible() and not o.panel.internal.isChecked() and not bore_row.isVisible()
      and o.panel.title.text() == "ROUGHING")
o.panel.internal.setChecked(True)
pump()
check("Internal shows Drilled hole Ø; this bar has no bore, the panel says so",
      bore_row.isVisible() and o.op()["internal"] and "no bore" in o.panel.info.text())
o.panel.internal.setChecked(False)
pump()
o.panel.ends["end"][1].setChecked(True)
pump()
q = vp.project([(2.0, 0.0, 0.75)])[0]                  # the shoulder edge (Ø1.5 at x = 2)
from PySide6.QtCore import QPoint as _QP
QTest.mouseMove(vp.plotter, _QP(round(q[0]), round(q[1])))
pump(60)
QTest.mouseClick(vp.plotter, Qt.LeftButton, Qt.NoModifier, _QP(round(q[0]), round(q[1])))
pump(150)
check("picking the shoulder edge sets End there (Z-1.05)", abs(o.end_at - 2.0) < 1e-6
      and "Z-1.0500" in o.panel.ends["end"][1].toolTip() and not o.panel.ends["end"][1].isChecked())
mv, _w = op_moves(win, o.current_setup(), o.op())
check("rough now stops at the shoulder", min(p[2] for k, p in mv if k == "feed") >= -1.05 - 0.03)
o.panel.boxes[("turning", "past_back")].setValue(0.25)
mv, _w = op_moves(win, o.current_setup(), o.op())
check("End Extend 0.25 runs it further", min(p[2] for k, p in mv if k == "feed") < -1.05 - 0.2)
o.panel.boxes[("turning", "past_back")].setValue(0.0)
shot("cam_04a_rough_end")
o.clear_end("end")
check("right-click the End button puts End back to the part's back end", o.end_at is None
      and "back end" in o.panel.ends["end"][1].toolTip().splitlines()[0])
o.panel.output.setCurrentIndex(o.panel.output.findData("cycle"))
shot("cam_04b_rough")
key(Qt.Key_Return)
st = win.doc.setups[-1]
check("Roughing saved after Face", [x["name"] for x in st["ops"]] == ["Face", "Roughing"])
win.run_tool("Groove")
o = win.session
check("Groove opens: OD / ID / Face box, Start / End shown for OD", o.kind == "groove"
      and o.panel.title.text() == "GROOVE" and o.panel.side.isVisible() and o.panel.ends["start"][1].isVisible()
      and o.panel.tools["turning"].currentText().startswith("T6 · Groove"))
check("this bar has no groove: the panel says so", "no external groove" in o.panel.info.text())
o.panel.side.setCurrentIndex(o.panel.side.findData("face"))
pump()
check("Face groove hides Start / End", not o.panel.ends["start"][1].isVisible() and "no face groove" in o.panel.info.text())
key(Qt.Key_Escape)
pump()
win.run_tool("Contour")
o = win.session
check("turning Contour opens with the G70 box", o.kind == "finish" and o.panel.g70.isVisible()
      and o.panel.title.text() == "CONTOUR")
o.panel.g70.setChecked(True)
shot("cam_04c_contour")
key(Qt.Key_Return)
check("Contour1 saved after the rough", [x["name"] for x in st["ops"]] == ["Face", "Roughing", "Contour"])
from gsend_cad.core import post
g = post.post_setup(st, [(cam.validate_op(st, x), op_moves(win, st, x)[0]) for x in st["ops"]], "haas", 1)
check("post writes G72 face + G71 rough with its contour", "G72 P100 Q101" in g and "G71 P200 Q201" in g and "N200 G00 X1.\n" in g and "X1.5\n" in g
      and "G70 P200 Q201" in g)

win.select_tab("milling")
win.run_tool("Setup")
key(Qt.Key_Return)                               # a milling setup on the same part
win.run_tool("Face")
o = win.session
check("Face from the Milling tab picks the milling setup", o.current_setup()["type"] == "milling"
      and o.panel.groups["milling"].isVisible())
o.panel.tools["milling"].setCurrentIndex(o.panel.tools["milling"].findText("T2", Qt.MatchStartsWith))
rpm, sfm = o.panel.boxes[("milling", "rpm")], o.panel.sfm["milling"]
rpm.setValue(3000)
check("RPM 3000 on the Ø0.5 end mill shows SFM 393 (3000 x pi x 0.5 / 12)", round(sfm.value()) == 393)
sfm.setValue(600)
check("SFM 600 works out RPM 4584", rpm.value() == 4584 and o.op()["rpm"] == 4584)
o.panel.tools["milling"].setCurrentIndex(o.panel.tools["milling"].findText("T1", Qt.MatchStartsWith))
check("a Ø2 face mill keeps the RPM, SFM follows (2400)", rpm.value() == 4584 and round(sfm.value()) == 2400)
o.panel.tools["milling"].setCurrentIndex(o.panel.tools["milling"].findText("T2", Qt.MatchStartsWith))
shot("cam_05_face_milling")
key(Qt.Key_Return)
ms = win.doc.setups[-1]
oid = ms["ops"][0]["id"]
check("milling Face saved with the picked tool (T2 Ø0.5)", ms["ops"][0]["tool_dia"] == 0.5 and ms["ops"][0]["tool"] == 2)
win.browser.edit.emit(oid)
pump()
check("double-click reopens the Face op", win.session.edit_id == oid and
      win.session.panel.tools["milling"].currentText().startswith("T2 ·"))
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
check("Post dialog shows G-code for the milling setup", g.startswith("%\nO") and "T2 M06" in g and "M30" in g)
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
check("Contour1 saved", cop["type"] == "contour" and cop["name"] == "Contour")
win.browser.simulate.emit(cop["id"])
pump()
sim = win.session
check("right-click Simulate opens the simulator on that op", sim.__class__.__name__ == "SimSession"
      and len(sim.world) > 10 and sim.panel.step.text().endswith("Contour"))
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

# ---- Drill on a milling setup: plate with 2 x Ø0.25 through and 1 x Ø0.5 holes
win.dirty = False
win.new_doc()
doc = win.doc
p_ = doc.add_sketch([sk.rect((0, 0), (2, 2))])
doc.add_extrude([sketch_regions(p_["id"], p_["ents"])[0].to_data()], 0.5)
h_ = doc.add_sketch([sk.circle((0.5, 0.5), 0.125), sk.circle((1.5, 0.5), 0.125), sk.circle((1, 1.4), 0.25)])
doc.add_extrude([r.to_data() for r in sketch_regions(h_["id"], h_["ents"])], 0.5, op="cut")
win.rebuild(fit=True)
win.ribbon.show_mode("cam")
win.select_tab("milling")
win.run_tool("Setup")
key(Qt.Key_Return)
win.run_tool("Drill")
o = win.session
check("Drill opens with the hole sizes found in the model",
      o.kind == "drill" and [o.panel.holes.itemText(i) for i in range(o.panel.holes.count())]
      == ["All holes", "Ø0.2500", "Ø0.5000"] and o.panel.holes.currentData() == 0.25
      and o.panel.tools["milling"].currentText().startswith("T4 · 1/4 Drill"))
check("Drill preview: 2 holes", o.panel.info.text().startswith("2 holes"))
o.panel.holes.setCurrentIndex(0)
check("All holes: 3", o.panel.info.text().startswith("3 holes"))
# ---- Select holes: the cursor button, click a hole to pick it, again to drop it
from gsend_cad.ui.commands import setup_holes
from PySide6.QtCore import QPoint as _QP2
o.panel.hole_btn.setChecked(True)
pump()
hs = [h for h in setup_holes(win, o.current_setup()) if abs(h["dia"] - 0.25) < 1e-6 and h["axis"][2] > 0.99]


def click_hole(h):
    q = vp.project([h["p"]])[0]
    pt = _QP2(round(q[0]), round(q[1]))
    QTest.mouseMove(vp.plotter, pt)
    pump(40)
    QTest.mouseClick(vp.plotter, Qt.LeftButton, Qt.NoModifier, pt)
    pump(150)
click_hole(hs[0])
check("Select holes: one click picks that hole only", o.panel.holes.currentText() == "1 picked"
      and o.panel.info.text().startswith("1 hole") and len(o.op()["picked"]) == 1)
shot("cam_09a_pick_holes")
click_hole(hs[1])
check("a second hole adds to it", o.panel.holes.currentText() == "2 picked" and o.panel.info.text().startswith("2 holes"))
click_hole(hs[0])
check("clicking a picked hole again drops it", o.panel.holes.currentText() == "1 picked"
      and o.op()["picked"][0] == list(hs[1]["p"]))
key(Qt.Key_Escape)                                     # stops selecting, the panel stays
check("Esc stops selecting holes", not o.panel.hole_btn.isChecked() and win.session is o)
o.panel.holes.setCurrentIndex(o.panel.holes.findData(0.25))
check("choosing a size drops the picks", not o.op()["picked"] and o.panel.holes.findData("picked") < 0
      and o.panel.info.text().startswith("2 holes"))
o.panel.holes.setCurrentIndex(1)
shot("cam_09_drill")
key(Qt.Key_Return)
dst = win.doc.setups[-1]
g = post.post_setup(dst, [(cam.validate_op(dst, x), op_moves(win, dst, x)[0]) for x in dst["ops"]], "haas", 1)
check("Drill posts a G83 peck cycle over both holes", "G98 G83 X" in g and "Q0.1" in g and "G80" in g)

# ---- Tool Library: make a Ø0.5 drill, it shows in the Drill op's Tool box and is saved
from gsend_cad.ui.commands import ToolLibraryDialog
from gsend_cad.core import tools as _tools
dlg = ToolLibraryDialog(win, "milling")
dlg.show()
pump()
n0 = dlg.list.count()
dlg.new_tool("drill")
dlg.number.setValue(7)
dlg.name.setText("1/2 Drill")
dlg.name.editingFinished.emit()
dlg.dia.setValue(0.5)
pump()
check("Tool Library: NEW TOOL adds T7 1/2 Drill Ø0.5", dlg.list.count() == n0 + 1 and
      any(t["number"] == 7 and t["dia"] == 0.5 and t["name"] == "1/2 Drill" for t in win.tool_lib))
check("library saved to its file", any(t["number"] == 7 for t in _tools.load(_lib)))
shot("cam_10_tool_library")
dlg.accept()
win.run_tool("Drill")
o = win.session
o.panel.holes.setCurrentIndex(o.panel.holes.findData(0.5))
pump()
check("picking the Ø0.5 holes picks the Ø0.5 drill from the library",
      o.panel.tools["milling"].currentText().startswith("T7 · 1/2 Drill") and o.op()["tool_dia"] == 0.5)
key(Qt.Key_Escape)
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
