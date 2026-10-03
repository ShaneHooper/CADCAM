"""Drive sketching on a face of the part and snap points, in the real window (xvfb-run):

    xvfb-run -a -s "-screen 0 1600x1000x24" python tests/drive_sketch_plane.py OUTDIR

Starts a sketch with the bracket plate on screen (so a face is asked for), hovers and clicks
the plate's +X side, draws a circle there with a typed size, extrudes it and checks the part
grew along +X. Then a sketch on XY: a line, and the Circle tool snapping to the line's end,
its midpoint, and to a corner of the part's top face.
"""
import math
import os
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import gsend_cad
from gsend_cad.core import plane as pl
from gsend_cad.ui.commands import PlanePickSession, SketchSession

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


def screen_world(x, y, z):
    ren = vp.plotter.renderer
    ren.SetWorldPoint(x, y, z, 1)
    ren.WorldToDisplay()
    dx, dy, _ = ren.GetDisplayPoint()
    r = vp.plotter.devicePixelRatioF()
    return QPoint(round(dx / r), round(vp.plotter.height() - dy / r))


def screen_uv(u, v):
    """Screen point of sketch (u, v) on the current sketch plane."""
    return screen_world(*pl.to_world(vp.frame, (u, v)))


def move_to(p):
    QTest.mouseMove(vp.plotter, p)
    pump(60)


def click_at(p):
    move_to(p)
    QTest.mouseClick(vp.plotter, Qt.LeftButton, Qt.NoModifier, p)
    pump(80)


def click_uv(u, v):
    click_at(screen_uv(u, v))


def key(k, mod=Qt.NoModifier):
    QTest.keyClick(vp.plotter, k, mod)
    pump(120)


def type_value(field, text):
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


# ---- 1. with a part on screen, L asks for a face; hover outlines it; a click sketches on it
vol0 = win.model.bodies[0].volume
key(Qt.Key_L)
check("L with a body on screen asks for a face first", isinstance(win.session, PlanePickSession))
side = screen_world(2.0, 0.3, 0.25)           # the plate's +X side face (home view sees it)
move_to(side)
pick = win.session
check("hovering the +X face outlines it", pick.hover is not None and pick.hover[2]["n"] == [1, 0, 0])
shot("plane_01_hover")
click_at(side)
s = win.session
check("clicking the face opens a sketch on that plane",
      isinstance(s, SketchSession) and s.frame == pl.from_normal((2, 0, 0), (1, 0, 0)))
check("the view looks square on to the face", abs(vp.plotter.camera.position[0] - 12) < 1e-6
      and vp.plotter.camera.up == (0.0, 0.0, 1.0))
check("the palette says it is a face plane", s.palette.plane.prefix().startswith("Face"))
check("the part's edges on that face are there to snap to", len(s.model_edges) == 4 and s.model_snaps)
shot("plane_02_on_face")

win.run_tool("Circle")
click_uv(0.0, 0.25)                           # center, then a point on the circle (u = world Y, v = world Z)
click_uv(0.2, 0.25)
c = s.ents[0]
check("circle drawn in face coordinates", c["type"] == "circle" and c["c"] == [0.0, 0.25])
type_value("dia", "0.4")
check("typed diameter applies on a face plane", abs(s.ents[0]["r"] - 0.2) < 1e-9)
shot("plane_03_circle")
key(Qt.Key_Escape)
key(Qt.Key_Return)                            # finish
f = win.doc.features[-1]
check("the sketch feature carries the face plane", f["kind"] == "sketch" and f.get("plane") == s.frame)
check("the timeline describes the plane", "face plane · +X 2.000 in" in win.doc.describe(f))

key(Qt.Key_E)                                 # extrude: the newest sketch's one region is preselected
ext = win.session
check("extrude picks up the face sketch's profile", ext is not None and len(ext.sel) == 1)
ext.panel.dist.setValue(0.5)
ext.commit()
pump(300)
b = win.model.bodies[0]
check("extruding from the side grows the part along +X by the circle's area x 0.5",
      abs(b.volume - (vol0 + math.pi * 0.2 ** 2 * 0.5)) < 1e-3 and abs(b.bbox()[1][0] - 2.5) < 1e-6)
shot("plane_04_extruded")

# ---- 2. snap points on an XY sketch: a line end, its midpoint, a corner of the top face
key(Qt.Key_L)
pick = win.session
check("L asks for a face again", isinstance(pick, PlanePickSession))
key(Qt.Key_Return)                            # XY plane
s = win.session
check("Enter takes the XY plane", isinstance(s, SketchSession) and pl.is_xy(s.frame))
win.run_tool("Line")
click_uv(0.5, 1.0)                            # off the Y axis: a first click on an axis starts a Parallel to Axis line
click_uv(2.0, 1.0)
key(Qt.Key_Escape)                            # end the chain
check("a line is drawn", len(s.ents) == 1 and s.ents[0]["type"] == "line")
win.run_tool("Circle")
near_end = screen_uv(1.98, 1.03)              # 0.02" off the end: a few px at this zoom
move_to(near_end)
check("the cursor snaps to the line's END", s.snap_hit is not None and s.snap_hit[2] == "end")
check("and the tag says so", "END" in vp.dim.text())
shot("plane_05_snap_end")
click_at(near_end)
check("the circle's center landed exactly on the end", s.pts and s.pts[0] == [2.0, 1.0])
key(Qt.Key_Escape)
move_to(screen_uv(1.27, 0.98))
check("the midpoint snaps too", s.snap_hit is not None and s.snap_hit[2] == "mid" and s.snap_hit[:2] == (1.25, 1.0))
win.session.set_plane(0.5)                    # the plate's top face is at Z 0.5: its edges come in
check("raising the plane to the top face brings the part's edges in", len(s.model_edges) > 0)
corner = (2.0 - 0.25, 1.5)                    # where the top face's straight edge meets the corner radius
move_to(screen_uv(corner[0] + 0.01, corner[1] - 0.01))
check("a corner of the part's top face snaps as END",
      s.snap_hit is not None and s.snap_hit[2] == "end" and abs(s.snap_hit[0] - corner[0]) < 1e-6)
shot("plane_06_snap_part")
move_to(screen_uv(0.6, 0.6))
check("away from everything nothing snaps", s.snap_hit is None)
key(Qt.Key_Escape)
win.cancel_command()

print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
