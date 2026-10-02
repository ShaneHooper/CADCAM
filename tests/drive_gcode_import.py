"""Drive File > Import G-code... (Steps 1-4, BUILD PART, Settings > Keywords) in the real window.

    python tests/drive_gcode_import.py OUTDIR
    (Linux: xvfb-run -a -s "-screen 0 1600x1000x24" python tests/drive_gcode_import.py OUTDIR)
"""
import os
import sys
from pathlib import Path

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import gsend_cad
from gsend_cad.gcode_import.wizard import ImportWizard

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
KEYWORDS = os.path.join(OUT, "gcode_import_keywords.json")      # never the user's real table
if os.path.exists(KEYWORDS):
    os.remove(KEYWORDS)
os.environ["GSEND_GCODE_KEYWORDS"] = KEYWORDS
FIXTURE = Path(__file__).parent / "fixtures" / "gcode" / "stepped_shaft.nc"
app = QApplication(sys.argv[:1])
win = gsend_cad.launch(block=False)
failures = []


def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def shot(widget, name):
    QTest.qWait(300)
    widget.grab().save(os.path.join(OUT, name + ".png"))


names = [a.text() for a in win.topbar.file.menu().actions()]
check("File menu has Import G-code… above the exports",
      "Import G-code…" in names and names.index("Import G-code…") < names.index("Export STEP…"))

dlg = ImportWizard(win, str(FIXTURE), FIXTURE.read_text())
dlg.show()
QTest.qWait(300)
mg = win.geometry()
check("opens large, about 98% x 94% of the main window, centred on it",
      abs(dlg.width() - 0.98 * mg.width()) <= 2 and abs(dlg.height() - 0.94 * mg.height()) <= 2
      and abs((dlg.x() + dlg.width() / 2) - (mg.x() + mg.width() / 2)) <= 3)
check("auto-detected a lathe, with the reasons shown",
      dlg.machine == "lathe" and dlg.lathe_btn.isChecked() and "point to lathe" in dlg.reason.text())
check("stock prefilled from the program and tagged AUTO",
      dlg.od.value() == 2.0 and dlg.length.value() == 2.25 and dlg.tags["od"].text() == "AUTO"
      and dlg.tags["length"].text() == "AUTO")        # faces from X2.1 -> a 2.000 bar; 1.05 of cuts + 1.000 -> 2.25
check("AUTO tags say where the value came from", "largest diameter the program works at" in dlg.tags["od"].toolTip()
      and "plus 1.000 more" in dlg.tags["length"].toolTip())
check("Z0 prefilled as the finished front face, 0.05 of stock in front",
      dlg.z0.currentData() == "finished" and abs(dlg.front.value() - 0.05) < 1e-9)
check("the G50 line is listed in the flags with its line number", "LINE 6" in dlg.flags.toPlainText())
check("preview holds the stock and the toolpath",
      dlg.preview.stock == (-2.2, 0.05, 2.0, 0.0) and len(dlg.preview.moves) == len(dlg.program.moves))
shot(dlg, "gcode_import_setup")

dlg.od.setValue(2.5)
check("typing a stock OD flips its tag to SET BY YOU and redraws",
      dlg.tags["od"].text() == "SET BY YOU" and dlg.preview.stock[2] == 2.5 and dlg.tags["length"].text() == "AUTO")
dlg.od.setValue(2.0)                                    # back to the 2.000 bar the later checks are built on
dlg.tube_btn.click()
dlg.bore.setValue(0.5)
check("TUBE shows the ID field and the bore reaches the preview",
      dlg.bore.isVisible() and dlg.preview.stock[3] == 0.5 and dlg.settings()["id"] == 0.5)
dlg.z0.setCurrentIndex(1)
check("Z0 = STOCK FACE puts the bar behind Z0 and locks stock-in-front",
      dlg.preview.stock[:2] == (-2.25, 0.0) and not dlg.front.isEnabled())
shot(dlg, "gcode_import_setup_edited")

dlg.mill_btn.click()
check("choosing MILL says mill import is not built, and blocks NEXT",
      dlg.mill_note.isVisible() and not dlg.next.isEnabled() and dlg.preview.note == "MILL IMPORT NOT BUILT YET"
      and dlg.machine_tag.text() == "SET BY YOU")
shot(dlg, "gcode_import_mill")
dlg.lathe_btn.click()
dlg.next.click()
check("NEXT goes to step 2 TOOLS, BACK returns",
      dlg.pages.currentIndex() == 1 and dlg.step_btns[1].isChecked())
dlg.back.click()
check("back on Setup", dlg.pages.currentIndex() == 0)
dlg.close()

# ---- Step 2 TOOLS + Settings > Keywords ----
from gsend_cad.gcode_import.keywords_page import KeywordsDialog

MULTI = FIXTURE.with_name("multi_tool.nc")
dlg = ImportWizard(win, str(MULTI), MULTI.read_text())
dlg.show()
dlg.go(1)
tp = dlg.tools_page
QTest.qWait(300)
cell = lambda r, c: tp.table.item(r, c).text()
check("one row per tool with its status", tp.table.rowCount() == 6
      and [cell(r, 7) for r in range(6)] == ["READ", "READ", "READ", "GUESSED", "GUESSED", "UNKNOWN"])
check("the header counts each status", all(x in tp.counts.text() for x in ("READ 3", "GUESSED 2", "UNKNOWN 1",
                                                                            "DEFINED 0")))
check("T01 row: keyword, type, insert, nose radius, side",
      [cell(0, c) for c in (0, 2, 3, 4, 5, 6)] == ["T01", "OD ROUGH", "OD TURN", "CNMG 432", "0.0312", "OD"])
check("opens on the first unresolved tool (T03: nose radius ASSUMED)",
      tp.current() == 2 and tp.nose_tag.text() == "ASSUMED" and "default" in tp.assumed.text())
shot(dlg, "gcode_import_tools")
tp.insert.setText("CCMT 32.51")
tp.insert.textEdited.emit("CCMT 32.51")
check("typing an insert code fills in the shape and the nose radius",
      abs(tp.nose.value() - 1 / 64) < 1e-4 and "80° diamond" in tp.shape.text() and tp.nose_tag.text() == "READ")
tp.apply_btn.click()
check("APPLY marks it DEFINED and moves to the next unresolved (T04)",
      cell(2, 7) == "DEFINED" and cell(2, 4) == "CCMT 32.51" and tp.current() == 3)
tp.apply_btn.click()
check("a groove tool cannot be applied without its width", "width" in tp.note.text() and cell(3, 7) == "GUESSED")
tp.size.setValue(0.125)
tp.apply_btn.click()
check("with the width typed it is DEFINED", cell(3, 7) == "DEFINED" and tp.current() == 4)
tp.table.setCurrentCell(5, 0)
check("a groove plunging inward cuts on the OD", cell(3, 6) == "OD")
check("the UNKNOWN tool says it is a sharp point", "sharp point" in tp.assumed.text()
      and tp.kw_text.text() == "PARTING BLADE")
tp.type.setCurrentText("CUTOFF")
tp.size.setValue(0.118)
tp.save_kw.setChecked(True)
check("with a type and width typed the panel says nothing is assumed",
      tp.assumed.text() == "Nothing assumed." and tp.nose_tag.text() != "ASSUMED")
shot(dlg, "gcode_import_tool_define")
tp.apply_btn.click()
check("defining it with 'save as keyword' adds a USER keyword to the settings file",
      cell(5, 7) == "DEFINED" and dlg.table[0] == {"keyword": "PARTING BLADE", "tool": "CUTOFF", "op": None,
                                                    "source": "USER"} and os.path.exists(KEYWORDS))
check("the header counts follow", "DEFINED 3" in tp.counts.text() and "UNKNOWN 0" in tp.counts.text())

# ---- Step 3 OPERATIONS ----
dlg.go(2)
op = dlg.ops_page
QTest.qWait(300)
ocell = lambda r, c: op.table.item(r, c).text()
types = lambda: [op.combo(r).currentText() for r in range(op.table.rowCount())]
check("the program is cut into operations with a type each",
      types() == ["FACE", "OD ROUGH", "DRILL", "ID ROUGH", "OD GROOVE", "THREAD"])
check("each row says how it was found and how sure",
      [ocell(r, 4) for r in range(6)] == ["MOTION", "KEYWORD", "KEYWORD", "MOTION", "MOTION", "G76"]
      and [ocell(r, 6) for r in range(6)] == ["MED", "HIGH", "HIGH", "MED", "MED", "HIGH"])
check("the header counts each confidence", all(x in op.counts.text() for x in ("HIGH 3", "MED 3", "NEEDS TYPE 0",
                                                                               "SET BY YOU 0")))
check("the summary lists the bore and the thread callout",
      "Ø0.7500" in op.summary.text() and "16 TPI" in op.summary.text() and "MAX Ø" in op.summary.text())
check("the preview shows the reconstructed profile, exact and uncut edges",
      op.preview.profile and {e.tag for e in op.preview.profile} >= {"EXACT", "STOCK"})
op.table.setCurrentCell(3, 0)
check("selecting a row lights up its moves in the preview",
      op.preview.highlight == set(op.ops[3].moves) and "#4" in op.preview.caption)
shot(dlg, "gcode_import_operations")
op.combo(0).setCurrentText("SKIP")
check("picking a type marks it SET BY YOU / found by YOU",
      types()[0] == "SKIP" and ocell(0, 4) == "YOU" and ocell(0, 6) == "SET BY YOU" and "SET BY YOU 1" in op.counts.text()
      and "1 skipped" in op.summary.text())
op.combo(0).setCurrentIndex(0)
check("picking nothing goes back to what the program says", types()[0] == "FACE" and ocell(0, 4) == "MOTION")
dlg.go(0)
dlg.tube_btn.click()
dlg.bore.setValue(1.6)
dlg.go(2)
check("operations follow Setup: with a 1.6 tube ID the 1.5 turn is inside the bore", types()[1] == "OD ROUGH"
      and op.ops[3].side == "ID" and op.preview.stock[3] == 1.6)
dlg.go(0)
dlg.round_btn.click()
dlg.go(2)

# ---- Step 4 RECONSTRUCT ----
dlg.go(3)
rp = dlg.recon_page
QTest.qWait(300)
rec = dlg.reconstruction()
check("the reconstruction ran: a 1.5 turned diameter, a 0.75 bore, a thread callout",
      rec.ok and abs(rec.diameter_at(-0.2) - 1.5) < 0.005 and abs(rec.bore - 0.75) < 0.005 and len(rec.threads) == 1)
check("the page shows the profile and its numbers",
      rp.preview.profile == rec.edges and "MAX Ø" in rp.summary.text() and "16 TPI" in rp.summary.text())
shot(dlg, "gcode_import_reconstruct")
area = rec.area
rp.centre_btn.click()
check("NOSE CENTER re-runs the reconstruction", dlg.nose_center and dlg.reconstruction().area != area)
rp.tip_btn.click()
check("back to IMAGINARY TIP gives the first result again", abs(dlg.reconstruction().area - area) < 1e-9)
rp.show_path.setChecked(True)
check("SHOW TOOLPATH draws the moves over the profile", rp.preview.show_toolpath)
shot(dlg, "gcode_import_reconstruct_toolpath")
rp.show_path.setChecked(False)
dlg.go(1)
tp.table.setCurrentCell(3, 0)
tp.size.setValue(0.25)
tp.apply_btn.click()
check("changing a tool definition re-runs the reconstruction (wider groove blade)",
      abs(dlg.reconstruction().area - area) > 1e-4)
tp.table.setCurrentCell(3, 0)
tp.size.setValue(0.125)
tp.apply_btn.click()
dlg.go(2)

kd = KeywordsDialog(dlg, dlg.keywords_file, dlg.table)
kd.show()
kd.test.setText("FACE GROOVE CNMG 120408")
out = kd.result.text()
check("test box: longest keyword, ISO insert, tool type, operation, nose radius",
      "FACE GROOVE" in out and "FACE," not in out and "ISO" in out and "0.0315" in out)
kd.new_key.setText("wiper")
kd.new_tool.setCurrentText("OD TURN")
kd.add_btn.click()
check("ADD puts a USER keyword at the top of the table",
      kd.table.item(0, 0).text() == "WIPER" and kd.table.item(0, 3).text() == "USER")
shot(kd, "gcode_import_keywords")
n = len(kd.rows)
kd.delete("WIPER")
check("DELETE removes it", len(kd.rows) == n - 1 and kd.table.item(0, 0).text() == "PARTING BLADE")
kd.close()

# ---- Step 4 BUILD PART (Phase 5) ----
dlg.go(3)
QTest.qWait(300)
check("the page says how the outline was fitted", "fitted to" in rp.summary.text() and "arc" in rp.summary.text())
check("BUILD PART is on once there is a profile", rp.build_btn.isEnabled())
shot(dlg, "gcode_import_build")
win.dirty = False                                       # nothing to save in the app: no prompt over the build
dlg.build_part()
kinds = [f["kind"] for f in win.doc.features]
check("BUILD PART replaced the part with a Profile sketch and a Revolve1", kinds == ["sketch", "revolve"]
      and win.doc.features[0]["name"] == "Profile" and win.doc.features[1]["name"] == "Revolve1")
check("the profile is lines and arcs, tagged for Phase 6", {e["type"] for e in win.doc.features[0]["ents"]} == {"line", "arc"}
      and all("src" in e for e in win.doc.features[0]["ents"]))
check("the app made one solid from it, no errors", len(win.model.bodies) == 1 and not win.model.errors)
check("it is unsaved work, named for the program, and the window closed", win.dirty and win.doc.name == MULTI.stem
      and not dlg.isVisible())
shot(win, "gcode_import_built_part")

# ---- flip programs: OP1 and OP2 in one file ----
from PySide6.QtWidgets import QLabel
from gsend_cad.gcode_import.wizard import FlipDialog

FLIP = FIXTURE.with_name("flip_part.nc")
fd = ImportWizard(win, str(FLIP), FLIP.read_text())
fd.show()
QTest.qWait(300)
check("a flip comment is found (line 20) and Setup shows the length row, off until a length is typed",
      fd.flip_marker is not None and fd.flip_marker.line == 20 and fd.flip_row.isVisible() and fd.flip_tag.text() == "OFF"
      and fd.program.flip is None)
check("an ordinary program shows no flip row", not dlg.flip_row.isVisible() and dlg.flip_marker is None)
box = FlipDialog(win, fd.flip_marker, 1.25)
check("the little box names the comment and offers a first guess of the length",
      abs(box.length.value() - 1.25) < 1e-9 and any("FLIP PART" in lab.text() for lab in box.findChildren(QLabel)))
box.close()
fd.flip_len.setValue(2.0)
check("typing the overall length flips the program: OP2's Z0 is that far from OP1's",
      fd.program.flip is not None and fd.program.flip.length == 2.0 and fd.flip_tag.text() == "SET BY YOU"
      and abs(fd.model.moves[-1].z1 - (-2.0 - fd.program.moves[-1].z1)) < 1e-9)
check("the stock length follows the flip (a guess, still AUTO)", abs(fd.length.value() - 2.25) < 1e-9
      and fd.tags["length"].text() == "AUTO" and "flip program" in fd.tags["length"].toolTip())
check("the flags list says the program was split", "starts OP2" in fd.flags.toPlainText())
fd.go(2)
QTest.qWait(300)
rows = [fd.ops_page.table.item(r, 0).text() for r in range(fd.ops_page.table.rowCount())]
check("Step 3 lists OP1's operations and then OP2's, marked", rows == ["1", "2", "3 · OP2", "4 · OP2"])
fd.go(3)
QTest.qWait(300)
frec = fd.reconstruction()
check("Step 4 makes one 2.000 long part from the two ops (dia 1.5 front, bar, dia 1.0 at the far end)",
      frec.ok and abs(frec.z_min + 2.0) < 1e-4 and abs(frec.diameter_at(-0.5) - 1.5) < 0.005
      and abs(frec.diameter_at(-1.35) - 2.0) < 0.005 and abs(frec.diameter_at(-1.75) - 1.0) < 0.005)
shot(fd, "gcode_import_flip")
fd.flip_len.setValue(0.0)
check("a length of 0 turns the flip off", fd.program.flip is None and fd.flip_tag.text() == "OFF")
fd.flip_len.setValue(2.0)
win.dirty = False
fd.build_part()
bb = win.model.bodies[0].shape.bounding_box()
check("BUILD PART makes the 2.000 long part", len(win.model.bodies) == 1 and not win.model.errors
      and abs(bb.min.X + 2.0) < 1e-3 and abs(bb.max.Y - 1.0) < 1e-3)

print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
win.dirty = False
win.close()
sys.exit(1 if failures else 0)
