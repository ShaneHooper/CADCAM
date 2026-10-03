"""While sketching, Shift + left drag (or Alt + left drag) turns the view; a plain left drag still draws / selects, and a
Shift + click that never moves is still a click. Uses real mouse events on the viewport.

    python tests/drive_sketch_orbit.py      (needs a screen: it clicks the real window)
"""
import sys
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import gsend_cad
from gsend_cad.core.document import Document

app = QApplication(sys.argv[:1])
win = gsend_cad.launch(Document("orbit"), block=False)
win.show()
vp = win.viewport
pw = vp.plotter
fails = []
def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond: fails.append(label)
QTest.qWait(500)
cam = pw.camera
look = lambda: tuple(round(a - b, 3) for a, b in zip(cam.GetPosition(), cam.GetFocalPoint()))
def drag(button, mods=Qt.NoModifier, dx=120, dy=60):
    c = pw.rect().center()
    before = look()
    QTest.mousePress(pw, button, mods, c)
    for i in range(1, 7):
        QTest.mouseMove(pw, c + QPoint(dx * i // 6, dy * i // 6)); QTest.qWait(10)
    QTest.mouseRelease(pw, button, mods, c + QPoint(dx, dy)); QTest.qWait(50)
    return look() != before

class Ev:
    def __init__(s, x=0, y=0): s.p = QPointF(x, y)
    def position(s): return s.p
    def modifiers(s): return Qt.NoModifier

win.start_sketch(); QTest.qWait(300)
s = win.session
s.set_tool("Line")
for pt in ((0, 0), (2, 0), (2, 1), (0, 1), (0, 0)): s.on_click(pt, Ev())
n = len(s.ents)
check("lines are drawn", n == 4)
check("after drawing, Shift + left drag turns the view", drag(Qt.LeftButton, Qt.ShiftModifier))
check("...and so does Alt + left drag", drag(Qt.LeftButton, Qt.AltModifier))
check("...again and again (nothing gets stuck)", drag(Qt.LeftButton, Qt.ShiftModifier) and drag(Qt.LeftButton, Qt.ShiftModifier))
check("a plain left drag still does not turn it (it draws)", not drag(Qt.LeftButton))
check("orbiting added no geometry", len(s.ents) == n)
s.set_tool("Line"); s.pts = []
c = pw.rect().center()
QTest.mouseClick(pw, Qt.LeftButton, Qt.NoModifier, c)
QTest.mouseClick(pw, Qt.LeftButton, Qt.ShiftModifier, c + QPoint(80, 0)); QTest.qWait(50)
check("a Shift + click with no drag is still a click (ends the line)", len(s.ents) == n + 1)
s.set_tool(None)
check("in Select mode Alt + left drag turns the view too (no selection box)", drag(Qt.LeftButton, Qt.AltModifier))
win.dirty = False; win.close()
print("FAILED: " + ", ".join(fails) if fails else "ALL OK")
sys.exit(1 if fails else 0)
