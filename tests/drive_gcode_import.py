"""Drive File > Import G-code... (Steps 1-3, Settings > Keywords) in the real window.

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
check("auto-detected a lathe, with the reasons shown",
      dlg.machine == "lathe" and dlg.lathe_btn.isChecked() and "point to lathe" in dlg.reason.text())
check("stock prefilled from the program and tagged AUTO",
      dlg.od.value() == 2.25 and dlg.length.value() == 1.25 and dlg.tags["od"].text() == "AUTO"
      and dlg.tags["length"].text() == "AUTO")
check("AUTO tags say where the value came from", "largest cut diameter" in dlg.tags["od"].toolTip())
check("Z0 prefilled as the finished front face, 0.05 of stock in front",
      dlg.z0.currentData() == "finished" and abs(dlg.front.value() - 0.05) < 1e-9)
check("the G50 line is listed in the flags with its line number", "LINE 6" in dlg.flags.toPlainText())
check("preview holds the stock and the toolpath",
      dlg.preview.stock == (-1.2, 0.05, 2.25, 0.0) and len(dlg.preview.moves) == len(dlg.program.moves))
shot(dlg, "gcode_import_setup")

dlg.od.setValue(2.0)
check("typing a stock OD flips its tag to SET BY YOU and redraws",
      dlg.tags["od"].text() == "SET BY YOU" and dlg.preview.stock[2] == 2.0 and dlg.tags["length"].text() == "AUTO")
dlg.tube_btn.click()
dlg.bore.setValue(0.5)
check("TUBE shows the ID field and the bore reaches the preview",
      dlg.bore.isVisible() and dlg.preview.stock[3] == 0.5 and dlg.settings()["id"] == 0.5)
dlg.z0.setCurrentIndex(1)
check("Z0 = STOCK FACE puts the bar behind Z0 and locks stock-in-front",
      dlg.preview.stock[:2] == (-1.25, 0.0) and not dlg.front.isEnabled())
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
      "Ø0.7500" in op.summary.text() and "16 TPI" in op.summary.text() and "after Step 4" in op.summary.text())
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
dlg.close()

print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
win.dirty = False
win.close()
sys.exit(1 if failures else 0)
