"""Drive the sketch grid in the real window: it lies on the plane being sketched on (a face, or slid off it) and is
hidden whenever no sketch is open (a plain 3D model, picking a face, after Finish / Cancel).

    python tests/drive_sketch_grid.py
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import gsend_cad
from gsend_cad.core import plane as pl
from gsend_cad.core.document import bracket_plate
from gsend_cad.ui.commands import PlanePickSession

app = QApplication(sys.argv[:1])
win = gsend_cad.launch(block=False)
vp = win.viewport
fails = []
def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond: fails.append(label)
vis = lambda: [bool(a.GetVisibility()) for a in vp._grid_actors]
mat = lambda: vp._grid_actors[0].GetUserMatrix()
win._set_doc(bracket_plate(), None)
QTest.qWait(300)
check("a plain 3D model: no grid", vis() == [False, False])
win.start_sketch()                                       # a part is on screen: first pick the face
check("picking a face to sketch on: still no grid", isinstance(win.session, PlanePickSession) and vis() == [False, False])
win.cancel_command()
top = pl.from_normal((0.0, 0.0, 1.25), (0.0, 0.0, 1.0))  # the top of the plate
win.start_sketch(plane=top)
QTest.qWait(300)
m = mat()
check("a sketch on the top face: the grid is on, lying on that face (Z 1.25, lifted 0.003)",
      vis() == [True, True] and m is not None and abs(m.GetElement(2, 3) - 1.253) < 1e-9
      and abs(m.GetElement(2, 2) - 1.0) < 1e-9)
side = pl.from_normal((2.0, 0.0, 0.0), (1.0, 0.0, 0.0))  # a side face: the grid stands up on it
win.session.base = side; win.session.plane_z = 0.0; win.session._plane_changed()
m = mat()
check("moving the sketch to a side face stands the grid up on it (normal +X, at X 2.0)",
      vis() == [True, True] and abs(m.GetElement(0, 3) - 2.003) < 1e-9 and abs(m.GetElement(0, 2) - 1.0) < 1e-9
      and abs(m.GetElement(2, 3)) < 1e-9)
win.session.base = top; win.session.set_plane(0.5)       # the palette's Plane field slides it off the face
check("sliding the sketch off the face (palette Plane field) takes the grid with it",
      abs(mat().GetElement(2, 3) - (1.25 + 0.5 + 0.003)) < 1e-9)
win.cancel_command()
check("finishing / cancelling the sketch hides the grid again", vis() == [False, False])
win.start_sketch(plane=top); QTest.qWait(100)
win.finish_sketch() if hasattr(win, "finish_sketch") else win.cancel_command()
check("Finish Sketch hides it too", vis() == [False, False])
check("the world axes (red / green / blue) are still drawn", len(vp.plotter.renderer.actors) > 2)

# ---- pieces the G-code import only ASSUMED are drawn in warning yellow ----
from gsend_cad.core import sketch as sk
from gsend_cad.core.document import Document
from gsend_cad.ui import theme

hexrgb = lambda h: tuple(round(int(h[i:i + 2], 16) / 255, 2) for i in (1, 3, 5))
colours = lambda group: [tuple(round(c, 2) for c in a.GetProperty().GetColor()) for a in vp._groups.get(group, [])]
d = Document("assumed")
good, guess = sk.line((0, 0), (1, 0)), sk.line((1, 0), (1, 1))
guess["src"] = "ASSUMED"
d.add_sketch([good, guess, sk.line((1, 1), (0, 0))], name="Profile")
win._set_doc(d, None)
win.draw_sketches()
check("in the normal view an ASSUMED piece is yellow and the rest keep the sketch colour",
      hexrgb(theme.WARN) in colours("sketches") and hexrgb(theme.ACCENT) in colours("sketches"))
win.start_sketch(edit_id=d.features[0]["id"])
QTest.qWait(100)
check("while the sketch is open for editing it is yellow too",
      hexrgb(theme.WARN) in colours("sketch") and hexrgb(theme.ACCENT) in colours("sketch"))
win.cancel_command()
win.dirty = False; win.close()
print("FAILED: " + ", ".join(fails) if fails else "ALL OK")
sys.exit(1 if fails else 0)
