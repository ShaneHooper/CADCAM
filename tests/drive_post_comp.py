"""Drive CAM > Post Process with cutter comp (Off / Machine / Computer) in the real window.

The Haas ST/TL workbook part (pages 55-56) is revolved, given a Turning setup and a Contour (finish), and posted
three ways. Computer comp must write the workbook's tip points; Machine comp the same points with G42 / G40.

    python tests/drive_post_comp.py
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GSEND_TOOL_LIBRARY"] = os.path.join(tempfile.mkdtemp(), "tool_library_test.json")   # never the user's

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import gsend_cad
from gsend_cad.core import cam, plane as pl, profiles as pf, sketch as sk
from gsend_cad.core.document import Document
from gsend_cad.ui.commands import PostDialog

app = QApplication(sys.argv[:1])
win = gsend_cad.launch(block=False)
fails = []


def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        fails.append(label)


# the workbook part, (z, radius), turned about the sketch X axis (x = Z, y = radius)
pts = [(0.0, 0.0), (0.0, 0.375), (-0.25, 0.625), (-1.0, 0.625), (-1.25, 0.875), (-1.25, 1.2), (-1.55, 1.5),
       (-2.375, 1.5), (-2.375, 0.0)]
ents = [sk.line(a, b) for a, b in zip(pts, pts[1:] + pts[:1])]
d = Document("Haas part")
sketch = d.add_sketch(ents, name="Profile")
region = max(pf.sketch_regions(sketch["id"], sketch["ents"]), key=lambda r: r.outer.area)
d.add_revolve([region], {"sketch": sketch["id"], "kind": "x"}, 360.0, op="join")
win._set_doc(d, None)
QTest.qWait(300)
setup = d.add_setup({**cam.new_setup(cam.TURNING), "axis": "x", "wcs": "part-face", "name": "Setup1"})
sid = setup["id"]
op = {**cam.new_op(setup, "finish"), "name": "Contour", "output": "lines", "tool": 3, "nose_r": 0.031}
d.add_op(sid, op)

dlg = PostDialog(win, sid)
dlg.show()
QTest.qWait(200)
off = dlg.text.toPlainText()
check("the dialog has a Cutter comp box, Off by default, enabled on a lathe setup",
      dlg.comp.isEnabled() and dlg.comp.currentData() == "off" and dlg.comp.count() == 3)
code = lambda g, w: [ln for ln in g.splitlines() if not ln.startswith("(") and w in ln.split()]
check("Off: no comp codes (only the header's G40) and no comp notes",
      not code(off, "G41") and not code(off, "G42") and len(code(off, "G40")) == 1 and "CUTTER COMP" not in off)

dlg.comp.setCurrentIndex(dlg.comp.findData("machine"))
QTest.qWait(200)
mach = dlg.text.toPlainText()
check("Machine: G42 on the approach, G40 on the way out, the same points as Off",
      sum(1 for ln in mach.splitlines() if "G42" in ln.split() and not ln.startswith("(")) == 1
      and any(ln.startswith("G00 G40 X") for ln in mach.splitlines()) and "CUTTER COMP G42 ON" in mach)
strip = lambda s: [ln.replace(" G42", "").replace(" G40", "") for ln in s.splitlines() if "CUTTER COMP" not in ln]
check("Machine posts exactly Off's coordinates", strip(mach) == strip(off))

dlg.comp.setCurrentIndex(dlg.comp.findData("computer"))
QTest.qWait(200)
comp = dlg.text.toPlainText()
check("Computer: no G41 / G42 / G40 in the contour, the tool nose radius named in a note",
      not code(comp, "G41") and not code(comp, "G42") and len(code(comp, "G40")) == 1
      and "CUTTER COMP IN THE CODE: NOSE R0.031" in comp)
check("Computer writes the Haas workbook's tip points (X0.7137, Z-0.2682, X1.7137, X2.3637, Z-1.5682)",
      all(w in comp for w in ("X0.7137", "Z-0.2682", "X1.7137", "X2.3637", "Z-1.5682")))
d.setups[0]["post"] = dlg.settings()        # what Save .nc stores with the setup
check("... as post.comp", d.setups[0]["post"]["comp"] == "computer")
dlg2 = PostDialog(win, sid)
check("reopening the dialog remembers it", dlg2.comp.currentData() == "computer")
dlg2.close()
dlg.close()

mill = d.add_setup({**cam.new_setup(cam.MILLING), "name": "Setup2"})
dm = PostDialog(win, mill["id"])
check("on a Milling setup the box is greyed out (not hidden) and posts nothing extra",
      dm.comp.isVisibleTo(dm) and not dm.comp.isEnabled() and dm.settings()["comp"] == "off")
dm.close()
win.dirty = False
win.close()
print("FAILED: " + ", ".join(fails) if fails else "ALL OK")
sys.exit(1 if fails else 0)