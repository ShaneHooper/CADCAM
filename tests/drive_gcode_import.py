"""Drive File > Import G-code... (Step 1 SETUP) in the real window.

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
check("NEXT goes to step 2 (placeholder until Phase 2), BACK returns",
      dlg.pages.currentIndex() == 1 and dlg.step_btns[1].isChecked())
dlg.back.click()
check("back on Setup", dlg.pages.currentIndex() == 0)
dlg.close()

print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
win.dirty = False
win.close()
sys.exit(1 if failures else 0)
