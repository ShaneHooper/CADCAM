"""The sketch's red X and green Y axes are always on screen while sketching: bold, all the way across, still there
after panning or zooming a long way.

    python tests/drive_sketch_axes.py
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import gsend_cad
from gsend_cad.core.document import Document
from gsend_cad.ui import theme

app = QApplication(sys.argv[:1])
win = gsend_cad.launch(Document("axes"), block=False)
vp = win.viewport
fails = []
def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond: fails.append(label)

check("no sketch open: the long axes are hidden", not any(a.GetVisibility() for a in vp._axis_actors))
win.start_sketch(); QTest.qWait(300)
check("sketching: they are on", all(a.GetVisibility() for a in vp._axis_actors))
ax = vp._axis_actors
check("two axes, drawn in the overlay layer (over the model), not pickable",
      len(ax) == 2 and all(a in list(vp.top.GetViewProps()) for a in ax) and not any(a.GetPickable() for a in ax))
x, y = ax[0].GetBounds(), ax[1].GetBounds()
check("each runs thousands of inches each way (X level, Y plumb), so no zoom or pan loses them",
      x[0] <= -1000 and x[1] >= 1000 and abs(x[3] - x[2]) < 1e-9 and y[2] <= -1000 and y[3] >= 1000 and abs(y[1] - y[0]) < 1e-9)
check("red for X, green for Y, bold (2.5 px, thicker than the 1.5 px 3D axes)",
      tuple(round(c, 2) for c in ax[0].prop.color.float_rgb) == tuple(round(int(theme.BAD[i:i + 2], 16) / 255, 2) for i in (1, 3, 5))
      and tuple(round(c, 2) for c in ax[1].prop.color.float_rgb) == tuple(round(int(theme.OK[i:i + 2], 16) / 255, 2) for i in (1, 3, 5))
      and ax[0].prop.line_width >= 2.5 and ax[1].prop.line_width >= 2.5)
from gsend_cad.core import plane as pl
top = pl.from_normal((0.0, 0.0, 1.25), (0.0, 0.0, 1.0))
win.cancel_command(); win.start_sketch(plane=top); QTest.qWait(200)
m = ax[0].GetUserMatrix()
check("on a sketch on a face they lie on that face, through the sketch's origin", m is not None and abs(m.GetElement(2, 3) - 1.253) < 1e-9)
win.cancel_command()
check("after Cancel they are hidden again", not any(a.GetVisibility() for a in vp._axis_actors))
win.dirty = False; win.close()
print("FAILED: " + ", ".join(fails) if fails else "ALL OK")
sys.exit(1 if fails else 0)
