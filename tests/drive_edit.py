"""Drive Help → Documentation, Edit Sketch, Cancel and Hide / Show Sketch in the real window.

    xvfb-run -a -s "-screen 0 1600x1000x24" python tests/drive_edit.py OUTDIR
"""
import math
import os
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator

import gsend_cad
from gsend_cad.ui.commands import regions_for

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
app = QApplication(sys.argv[:1])
win = gsend_cad.launch(block=False)
win.move(0, 0)
vp = win.viewport
failures = []


def pump(ms=150):
    QTest.qWait(ms)


def shot(name, w=None):
    pump(300)
    w = w or win
    w.grab().save(os.path.join(OUT, name + ".png"))


def screen(x, y, z=0.0):
    ren = vp.plotter.renderer
    ren.SetWorldPoint(x, y, z, 1)
    ren.WorldToDisplay()
    dx, dy, _ = ren.GetDisplayPoint()
    r = vp.plotter.devicePixelRatioF()
    return QPoint(round(dx / r), round(vp.plotter.height() - dy / r))


def click(x, y, z=0.0):
    p = screen(x, y, z)
    QTest.mouseMove(vp.plotter, p)
    pump(30)
    QTest.mouseClick(vp.plotter, Qt.LeftButton, Qt.NoModifier, p)
    pump(60)


def key(k, mod=Qt.NoModifier):
    QTest.keyClick(vp.plotter, k, mod)
    pump(120)


def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def vol():
    return sum(b.volume for b in win.model.bodies)


def tree_item(nid):
    it = QTreeWidgetItemIterator(win.browser.tree)
    while it.value():
        if it.value().data(0, Qt.UserRole) == nid:
            return it.value()
        it += 1
    return None


# ---- Help menu
menu = win.topbar.help.menu()
check("help menu has Documentation", any(a.text().startswith("Documentation") for a in menu.actions()))
next(a for a in menu.actions() if a.text().startswith("Documentation")).trigger()
pump(300)
check("docs window open", win.docs is not None and win.docs.isVisible())
win.docs.toc.setCurrentRow(1)
shot("10_docs_sketch", win.docs)
win.docs.toc.setCurrentRow(2)
shot("11_docs_edit", win.docs)
win.docs.close()
QTest.keyClick(vp.plotter, Qt.Key_F1)
pump(300)
check("F1 opens docs", win.docs.isVisible())
win.docs.close()

# ---- the docs' pocket example: sketch on the plate top, cut down 0.25
base = vol()
key(Qt.Key_L)
win.session.palette.plane.setValue(0.5)
win.run_tool("Rectangle")
click(0.75, -0.75, 0.5)
click(1.75, 0.75, 0.5)
win.run_tool("Circle")
click(1.25, 0, 0.5)
click(1.5, 0, 0.5)
key(Qt.Key_Return)
sk_id = win.doc.features[-1]["id"]
key(Qt.Key_E)
vp.set_view("top")
pump()
click(0.9, 0.6, 0.5)
win.session.panel.op.setCurrentIndex(1)
win.session.panel.dist.setValue(-0.25)
key(Qt.Key_Return)
area = 1.5 - math.pi * 0.0625
check("docs pocket example cuts 0.25 deep", abs((base - vol()) - area * 0.25) < 1e-3 and not win.model.errors)
vp.set_view("home")

# ---- Edit Sketch from the timeline (real double-click) and move the plane down to 0.2
idx = win.doc.index(sk_id)
marker = win.doc.marker


def feature_button(i):
    from gsend_cad.ui.panels import FeatureButton
    return [w for w in win.timeline.body.findChildren(FeatureButton)][i]


QTest.mouseClick(feature_button(idx), Qt.LeftButton)
pump(20)
QTest.mouseDClick(feature_button(idx), Qt.LeftButton)       # Qt: press, release, dblclick, release
QTest.mouseRelease(feature_button(idx), Qt.LeftButton)
pump()
s = win.session
check("timeline double-click opens Edit Sketch", s is not None and s.edit_id == sk_id and len(s.ents) == 2)
check("double-click leaves the timeline where it was", win.doc.marker == marker)
check("palette titled EDIT SKETCH", s.palette.title.text() == "EDIT SKETCH")
shot("12_edit_sketch")
s.palette.plane.setValue(0.2)
key(Qt.Key_Return)
check("plane edit rebuilds the pocket (0.2 deep now)", abs((base - vol()) - area * 0.2) < 1e-3 and not win.model.errors)
check("edit is one feature, not a new sketch", sum(f["kind"] == "sketch" for f in win.doc.features) == 3)

# ---- Edit from the Browser (double-click), add a shape: extrude untouched
it = tree_item(sk_id)
win.browser.tree.itemDoubleClicked.emit(it, 0)
pump()
check("browser double-click opens Edit Sketch", win.session is not None and win.session.edit_id == sk_id)
win.run_tool("Circle")
click(-1.25, -0.9, 0.2)
click(-1.1, -0.9, 0.2)
key(Qt.Key_Return)
check("added shape keeps the pocket", abs((base - vol()) - area * 0.2) < 1e-3 and not win.model.errors)
check("sketch now has 3 shapes", len(win.doc.feature(sk_id)["ents"]) == 3)

# ---- Cancel throws an edit away
win.edit_sketch(sk_id)
pump()
win.session.delete_ent(0)
check("× deletes a shape in the palette", len(win.session.ents) == 2)
win.run_tool("Cancel")
pump()
check("Cancel keeps the sketch as it was", win.session is None and len(win.doc.feature(sk_id)["ents"]) == 3)

# ---- deleting a shape an extrude uses turns it red; Ctrl+Z restores
win.edit_sketch(sk_id)
pump()
win.session.palette.list.findChildren(type(win.topbar.help), "entDel")[1].click()   # × on the circle
pump()
key(Qt.Key_Return)
ex = next(f for f in win.doc.features if f["kind"] == "extrude" and f["profiles"][0]["sketch"] == sk_id)
check("deleting a used shape turns the extrude red", ex["id"] in win.model.errors)
shot("13_red_extrude")
key(Qt.Key_Z, Qt.ControlModifier)
check("Ctrl+Z restores the sketch", not win.model.errors and len(win.doc.feature(sk_id)["ents"]) == 3)

# ---- Hide / Show: a construction sketch on the plate top
key(Qt.Key_L)
win.session.palette.plane.setValue(0.5)
win.run_tool("Circle")
click(-1.0, 0.6, 0.5)
click(-0.7, 0.6, 0.5)
key(Qt.Key_Return)
cons = win.doc.features[-1]["id"]
check("new sketch shown", win.doc.sketch_shown(win.doc.feature(cons)))
it = tree_item(cons)
r = win.browser.tree.visualItemRect(it)
QTest.mouseClick(win.browser.tree.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(r.x() + 5, r.center().y()))
pump()
check("eye-dot click hides the sketch", not win.doc.sketch_shown(win.doc.feature(cons)))
regions, _ = regions_for(win.doc)
check("hidden sketch can't be picked by Extrude", all(rg.sketch != cons for rg in regions))
shot("14_hidden")
win.timeline.toggle.emit(win.doc.index(cons))
pump()
check("timeline Show Sketch shows it again", win.doc.sketch_shown(win.doc.feature(cons)))
win.browser.toggle.emit(sk_id)
pump()
check("a consumed sketch can be shown", win.doc.sketch_shown(win.doc.feature(sk_id)))
key(Qt.Key_Z, Qt.ControlModifier)
check("Ctrl+Z undoes a show/hide", not win.doc.sketch_shown(win.doc.feature(sk_id)))

# ---- Rename (F2 / right-click → Rename) and Delete (Del key) in the Browser
from PySide6.QtWidgets import QLineEdit, QMessageBox
from PySide6.QtCore import QTimer
tree = win.browser.tree


def rename(nid, text):
    win.browser.start_rename(nid)
    pump(100)
    ed = tree.findChild(QLineEdit)
    ed.selectAll()
    QTest.keyClicks(ed, text)
    QTest.keyClick(ed, Qt.Key_Return)
    pump(200)


rename("body1", "Base Plate")
check("rename a body", win.model.body("body1").name == "Base Plate" and tree_item("body1").text(0) == "Base Plate")
rename(cons, "Construction")
check("rename a sketch", win.doc.feature(cons)["name"] == "Construction")
rename(cons, "Sketch1")
check("duplicate sketch name refused", win.doc.feature(cons)["name"] == "Construction")
win.browser.start_rename(cons)
pump(100)
QTest.keyClick(tree.findChild(QLineEdit), Qt.Key_Escape)
pump(100)
check("Esc cancels a rename", win.doc.feature(cons)["name"] == "Construction")

# Delete key on a sketch nothing uses
tree.setCurrentItem(tree_item(cons))
win.browser.selected.emit(cons)
n = len(win.doc.features)
QTest.keyClick(tree, Qt.Key_Delete)
pump()
check("Del deletes a sketch", len(win.doc.features) == n - 1 and all(f["id"] != cons for f in win.doc.features))
key(Qt.Key_Z, Qt.ControlModifier)
check("Ctrl+Z brings the sketch back", any(f["id"] == cons for f in win.doc.features))

# Delete a sketch an extrude uses: asks, deletes both
def answer(button):
    def go():
        m = QApplication.activeModalWidget()
        if isinstance(m, QMessageBox):
            asked.append(m.text())
            m.button(button).click()
    QTimer.singleShot(300, go)


asked = []
answer(QMessageBox.Cancel)
win.delete_node(sk_id)
check("deleting a used sketch asks first; Cancel keeps it", asked and "Extrude" in asked[0]
      and any(f["id"] == sk_id for f in win.doc.features))
asked = []
answer(QMessageBox.Yes)
n = len(win.doc.features)
win.delete_node(sk_id)
check("Yes deletes the sketch and its extrude", len(win.doc.features) == n - 2 and not win.model.errors)
key(Qt.Key_Z, Qt.ControlModifier)

# Delete a body: selected in the Browser, Del pressed in the 3D view
win.run_tool("Sketch")
win.run_tool("Circle")
click(0, -2.5)
click(0.4, -2.5)
key(Qt.Key_Return)
key(Qt.Key_E)
win.session.panel.op.setCurrentIndex(2)
key(Qt.Key_Return)
check("second body made", len(win.model.bodies) == 2)
win.browser.selected.emit("body2")
vp.plotter.setFocus()
key(Qt.Key_Delete)
check("Del deletes the selected body", [b.id for b in win.model.bodies] == ["body1"]
      and win.doc.features[-1]["kind"] == "remove")
shot("15_body_deleted")
win.roll_to(len(win.doc.features) - 1)
check("rolling back before Remove shows the body again", len(win.model.bodies) == 2)
win.roll_to(len(win.doc.features))
key(Qt.Key_Z, Qt.ControlModifier)
check("Ctrl+Z brings the body back", len(win.model.bodies) == 2)

win.dirty = False
win.close()
print("FAILURES:", failures)
sys.exit(1 if failures else 0)
