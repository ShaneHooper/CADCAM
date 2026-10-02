"""Drive the Parallel to Axis tool in the real window: click an axis, the line follows the cursor, click or type a distance.

    python tests/drive_parallel_line.py
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import gsend_cad
from gsend_cad.core import sketch as sk
from gsend_cad.core.document import Document

app = QApplication(sys.argv[:1])
win = gsend_cad.launch(Document("parallel"), block=False)
vp = win.viewport
fails = []
def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond: fails.append(label)

class Ev:                                   # a mouse event: only where it is
    def __init__(self, x=0, y=0): self.p = QPointF(x, y)
    def position(self): return self.p
    def modifiers(self): return Qt.NoModifier
def key(ch):
    k = {"-": Qt.Key_Minus, ".": Qt.Key_Period}.get(ch, Qt.Key_0 + int(ch) if ch.isdigit() else Qt.Key_unknown)
    return QKeyEvent(QKeyEvent.KeyPress, k, Qt.NoModifier, ch)

win.start_sketch(); QTest.qWait(200)
s = win.session
vp.pixel_size = lambda pos: 0.01            # 8 px = 0.08 in: deterministic picking
s.palette.snap.setChecked(True)
s.set_tool("Parallel to Axis")
check("the tool is on, nothing picked", s.tool == "xline" and s.xref is None)

s.on_move((2.0, 0.5), Ev())                 # far from both axes: nothing to run parallel to
s.on_click((2.0, 0.5), Ev())
check("clicking away from an axis picks nothing (and says so)", s.xref is None and not s.ents)

s.on_click((2.0, 0.03), Ev())               # on the red X axis
check("clicking the X axis picks it", s.xref is not None and s.xref[2] == "X AXIS")
s.on_move((3.0, 1.0), Ev(50, 50))
check("the line follows the cursor", s.xref is not None and vp._groups.get("preview"))
s.on_key(key("4")); QTest.qWait(50)
check("typing a digit opens the distance box with it", s.editor.isVisible() and s.editor.box.lineEdit().text() == "4")
s.editor.box.lineEdit().setText("4.25"); s.editor._done(); QTest.qWait(50)
e = s.ents[-1] if s.ents else None
check("4.25 puts a level parallel line 4.25 above the axis (the cursor's side)",
      e is not None and e["type"] == "xline" and abs(e["p"][1] - 4.25) < 1e-9 and abs(e["d"][0] - 1) < 1e-9)
check("it is placed and the tool is ready for the next one", s.xref is None and len(s.ents) == 1)

s.on_click((2.0, 0.03), Ev()); s.on_move((3.0, -1.0), Ev(50, 50)); s.on_key(key("2"))
s.editor.box.lineEdit().setText("2"); s.editor._done()
check("with the cursor below the axis the same typing goes below it (Y -2)", abs(s.ents[-1]["p"][1] + 2.0) < 1e-9)

s.on_click((2.0, 0.03), Ev()); s.on_move((3.0, 1.0), Ev(50, 50)); s.on_key(key("3"))
s.editor.box.lineEdit().setText("-3"); s.editor._done()
check("a minus sign takes it to the other side (cursor above, Y -3)", abs(s.ents[-1]["p"][1] + 3.0) < 1e-9)

s.on_click((0.02, 2.0), Ev())               # the green Y axis, then a click
check("the Y axis can be picked", s.xref is not None and s.xref[2] == "Y AXIS")
s.on_move((1.51, 2.0), Ev(60, 60)); s.on_click((1.51, 2.0), Ev(60, 60))
l = s.ents[-1]
check("a click places it on the grid, plumb (X 1.5)", abs(l["p"][0] - 1.5) < 1e-9 and abs(l["d"][1] - 1) < 1e-9)
check("the snap points now include where it crosses the level line",
      any(k == "cross" and abs(u - 1.5) < 1e-9 and abs(v - 4.25) < 1e-9 for u, v, k in s.sketch_snaps))

s.on_click((1.5, 7.0), Ev())                # a parallel line is itself something to run parallel to
check("a parallel line can be the reference", s.xref is not None and s.xref[2] == "PARALLEL LINE")
s.on_key(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
check("Esc drops the reference first, the tool second", s.xref is None and s.tool == "xline")

s.set_tool("Line")
s.on_click((0.0, 0.0), Ev()); s.on_click((2.0, 0.0), Ev()); s.on_click((2.0, 1.0), Ev()); s.on_click((0.0, 1.0), Ev())
s.on_click((0.0, 0.0), Ev()); s.set_tool(None)
n = len(s.ents)
from gsend_cad.core.profiles import sketch_loops
check("drawing a closed shape beside them: only it is a profile", len(sketch_loops(s.ents)) == 1)

s.set_tool("Trim"); s.on_click((6.0, 4.25), Ev()); s.set_tool(None)
check("Trim leaves a parallel line alone", len(s.ents) == n)

xi = next(i for i, e in enumerate(s.ents) if e["type"] == "xline" and abs(e["p"][1] - 4.25) < 1e-9)
s.select(xi)
check("selected, the palette shows just its Y", list(s.palette.boxes) == ["y"])
s.palette.boxes["y"].setValue(5.0); s.palette.boxes["y"].editingFinished.emit(); QTest.qWait(50)
xs = [e for e in s.ents if e["type"] == "xline" and abs(e["p"][1] - 5.0) < 1e-9]
check("typing a new Y in the palette moves it (and only it)", len(xs) == 1 and
      not any(e["type"] == "xline" and abs(e["p"][1] - 4.25) < 1e-9 for e in s.ents))

before = len(s.ents)
s.undo()
check("Ctrl+Z takes back the last change (Y 5 is Y 4.25 again)", any(e["type"] == "xline" and abs(e["p"][1] - 4.25) < 1e-9 for e in s.ents))

# ---- the plain Line tool: its first click on an axis starts a parallel line too ----
s = win.session
s.ents, s.origin = [], []
s.set_tool("Line"); s.palette.snap.setChecked(True)
s.on_click((3.0, 0.03), Ev())
check("Line tool, first click on the X axis: a parallel line follows the cursor (no line started)",
      s.tool == "line" and s.xref is not None and s.xref[2] == "X AXIS" and not s.pts)
s.on_move((3.0, 2.0), Ev(70, 70)); s.on_key(key("1")); s.editor.box.lineEdit().setText("1.5"); s.editor._done()
check("typing 1.5 places it at Y 1.5 and the Line tool carries on",
      len(s.ents) == 1 and s.ents[0]["type"] == "xline" and abs(s.ents[0]["p"][1] - 1.5) < 1e-9 and s.tool == "line")
s.on_click((0.02, 3.0), Ev()); s.on_move((2.0, 3.0), Ev(80, 80)); s.on_click((2.0, 3.0), Ev(80, 80))
check("clicking the Y axis then a spot places a plumb one there", len(s.ents) == 2 and abs(s.ents[1]["p"][0] - 2.0) < 1e-9)
s.on_click((1.0, 1.0), Ev())
check("a first click anywhere else still starts an ordinary line", s.xref is None and s.pts == [[1.0, 1.0]])
s.on_click((0.0, 0.0), Ev())
check("...and the origin (a snap point) is not mistaken for an axis click", s.xref is None and len(s.ents) == 3 and s.ents[2]["type"] == "line")
s.on_click((0.02, 4.0), Ev()); s.on_click((0.02, 4.0), Ev())
s.set_tool(None)

win.finish_sketch(); QTest.qWait(200)
f = win.doc.features[-1]
check("Finish Sketch keeps them in the sketch", sum(e["type"] == "xline" for e in f["ents"]) >= 2)
vp_groups = vp._groups.get("sketches", [])
check("...but the finished sketch is drawn without the parallel lines (one actor: the rectangle's lines)",
      all(max(abs(c) for c in a.GetBounds()) < 50 for a in vp_groups))
win.dirty = False; win.close()
print("FAILED: " + ", ".join(fails) if fails else "ALL OK")
sys.exit(1 if fails else 0)
