"""The G-code import window (Qt). Step 1 SETUP is built; steps 2-4 are placeholders.

Only register() below touches the host app, and only through the main window's File menu.
Everything a handler does is guarded: an error in here shows a message box and leaves the
rest of the app running.
"""
from __future__ import annotations

import os
from pathlib import Path
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QStackedWidget, QVBoxLayout, QWidget)

from ..ui import theme
from . import keywords as kw
from .build import build_document
from .detect import detect_machine
from .keywords_page import KeywordsDialog
from .ops_page import OpsPage
from .parser import parse_program
from .preview import Preview
from .recon_page import ReconPage
from .reconstruct import reconstruct
from .stock import Z0_CHOICES, Z0_LABELS, guess_stock, stock_z_range
from .tools_page import ToolsPage
from .widgets import C_GUESS, C_YOU, Num, Tag, button
from .widgets import head as _head
from .widgets import toggle as _toggle

FILE_FILTER = "G-code (*.nc *.tap *.cnc *.ngc *.gcode *.eia *.min *.txt);;All files (*)"
STEPS = ("SETUP", "TOOLS", "OPERATIONS", "RECONSTRUCT")


def keywords_path(win) -> Path:
    """The keyword table sits beside the tool library (GSEND_GCODE_KEYWORDS overrides, for tests)."""
    env = os.environ.get("GSEND_GCODE_KEYWORDS")
    if env:
        return Path(env)
    lib = getattr(win, "tool_lib_path", None)
    return (Path(lib).parent if lib else Path.home() / ".gsend_cadcam") / "gcode_import_keywords.json"


def register(win) -> None:
    """File > Import G-code..., placed above the Export entries."""
    menu = win.topbar.file.menu()
    act = QAction("Import G-code…", menu)
    act.triggered.connect(lambda: open_import(win))
    before = next((a for a in menu.actions() if a.text().startswith("Export")), None)
    menu.insertAction(before, act)
    if before is not None:
        menu.insertSeparator(before)
    win._gcode_import_action = act


def open_import(win, path: str | None = None):
    try:
        if path is None:
            path, _ = QFileDialog.getOpenFileName(win, "Import G-code", "", FILE_FILTER)
            if not path:
                return None
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        dlg = ImportWizard(win, path, text)
        win._gcode_import = dlg
        dlg.exec()
        return dlg
    except Exception as exc:                            # never take the app down with the importer
        QMessageBox.warning(win, "Import G-code", f"The G-code import stopped:\n{exc}\n\n{traceback.format_exc(limit=3)}")
        return None


class ImportWizard(QDialog):
    def __init__(self, win, path: str, text: str):
        super().__init__(win)
        self.win = win
        self.path = path
        self.program = parse_program(text)
        self.detection = detect_machine(self.program.lines)
        self.guess = guess_stock(self.program)
        self.machine = self.detection.machine
        self.keywords_file = keywords_path(win)
        self.table = kw.load(self.keywords_file)        # keyword table (Settings > Keywords)
        self.overrides = {}                             # tool number -> Tool the user defined in Step 2
        self.op_overrides = {}                          # operation key -> type the user picked in Step 3
        self.nose_center = False                        # per-import: X / Z point at the nose centre, not the tip
        self._recon = None                              # cached reconstruction (cleared on any change)
        self._loading = True
        self.setWindowTitle(f"Import G-code · {Path(path).name}")
        self.resize(1200, 720)
        self.setStyleSheet(f"QDialog{{background:{theme.BG};}} QLabel{{color:{theme.FG};}}")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)

        steps = QHBoxLayout()
        steps.setSpacing(6)
        self.step_btns = []
        for i, name in enumerate(STEPS):
            b = _toggle(f"{i + 1}  {name}")
            b.clicked.connect(lambda _=False, i=i: self.go(i))
            steps.addWidget(b)
            self.step_btns.append(b)
        steps.addStretch()
        self.keywords_btn = button("SETTINGS · KEYWORDS…")
        self.keywords_btn.clicked.connect(self.open_keywords)
        steps.addWidget(self.keywords_btn)
        v.addLayout(steps)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._setup_page())
        self.tools_page = ToolsPage(self)
        self.pages.addWidget(self.tools_page)
        self.ops_page = OpsPage(self)
        self.pages.addWidget(self.ops_page)
        self.recon_page = ReconPage(self)
        self.pages.addWidget(self.recon_page)
        self.ops_page.changed.connect(self.recon_page.reload)       # any change re-runs the reconstruction
        self.tools_page.changed.connect(self.ops_page.reload)       # tools decide sides and drill types
        v.addWidget(self.pages, 1)

        foot = QHBoxLayout()
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{theme.FG2};")
        foot.addWidget(self.status, 1)
        self.back, self.next, close = button("BACK"), button("NEXT", ok=True), button("CLOSE")
        for b in (self.back, self.next, close):
            foot.addWidget(b)
        self.back.clicked.connect(lambda: self.go(self.pages.currentIndex() - 1))
        self.next.clicked.connect(lambda: self.go(self.pages.currentIndex() + 1))
        close.clicked.connect(self.reject)
        v.addLayout(foot)

        self._load_guess()
        self._loading = False
        self.tools_page.reload()
        self.go(0)
        self.refresh()

    # ---- pages ----
    def _setup_page(self) -> QWidget:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        left = QFrame()
        left.setFixedWidth(430)
        left.setStyleSheet(f"QFrame{{background:{theme.PANEL};border:1px solid {theme.LINE};}} QLabel{{border:0;}}")
        col = QVBoxLayout(left)
        col.setContentsMargins(12, 6, 12, 10)
        col.setSpacing(6)

        col.addWidget(_head("Machine type"))
        mrow = QHBoxLayout()
        self.lathe_btn, self.mill_btn = _toggle("LATHE"), _toggle("MILL")
        self.lathe_btn.clicked.connect(lambda: self.set_machine("lathe"))
        self.mill_btn.clicked.connect(lambda: self.set_machine("mill"))
        self.machine_tag = Tag()
        mrow.addWidget(self.lathe_btn)
        mrow.addWidget(self.mill_btn)
        mrow.addStretch()
        mrow.addWidget(self.machine_tag)
        col.addLayout(mrow)
        self.reason = QLabel(self.detection.summary)
        self.reason.setWordWrap(True)
        self.reason.setStyleSheet(f"color:{theme.FG2};font-size:11px;")
        col.addWidget(self.reason)
        self.mill_note = QLabel("MILL IMPORT NOT BUILT YET")
        self.mill_note.setStyleSheet(f"color:{theme.BAD};")
        col.addWidget(self.mill_note)

        col.addWidget(_head("Stock"))
        srow = QHBoxLayout()
        self.round_btn, self.tube_btn, hexb = _toggle("ROUND BAR"), _toggle("TUBE"), _toggle("HEX · LATER")
        hexb.setEnabled(False)
        self.round_btn.setChecked(True)
        self.round_btn.clicked.connect(lambda: self.set_shape("round"))
        self.tube_btn.clicked.connect(lambda: self.set_shape("tube"))
        for b in (self.round_btn, self.tube_btn, hexb):
            srow.addWidget(b)
        srow.addStretch()
        col.addLayout(srow)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)
        self.od, self.bore, self.length, self.front = Num(0.001), Num(0.0), Num(0.001), Num(0.0)
        self.z0 = QComboBox()
        for key in Z0_CHOICES:
            self.z0.addItem(Z0_LABELS[key], key)
        self.z0.setMinimumWidth(190)                    # "FINISHED FRONT FACE" in full
        self.tags = {k: Tag() for k in ("od", "length", "z0", "front")}
        self.bore_label = QLabel("ID")
        rows = (("OD", self.od, self.tags["od"]), (self.bore_label, self.bore, None),
                ("LENGTH", self.length, self.tags["length"]))
        for r, (label, field, tag) in enumerate(rows):
            grid.addWidget(QLabel(label) if isinstance(label, str) else label, r, 0)
            grid.addWidget(field, r, 1)
            if tag:
                grid.addWidget(tag, r, 2)
        grid.setColumnStretch(3, 1)
        col.addLayout(grid)

        col.addWidget(_head("Origin"))
        x0 = QLabel("X0   SPINDLE CENTERLINE (FIXED)")
        x0.setStyleSheet(f"color:{theme.FG2};")
        col.addWidget(x0)
        og = QGridLayout()
        og.setHorizontalSpacing(8)
        og.setVerticalSpacing(5)
        og.addWidget(QLabel("Z0"), 0, 0)
        og.addWidget(self.z0, 0, 1)
        og.addWidget(self.tags["z0"], 0, 2)
        og.addWidget(QLabel("STOCK IN FRONT"), 1, 0)
        og.addWidget(self.front, 1, 1)
        og.addWidget(self.tags["front"], 1, 2)
        og.setColumnStretch(3, 1)
        col.addLayout(og)

        self.flags_head = _head("Flags")
        col.addWidget(self.flags_head)
        self.flags = QPlainTextEdit()
        self.flags.setReadOnly(True)
        self.flags.setStyleSheet(f"font-family:'{theme.MONO[0]}','Consolas',monospace;font-size:11px;"
                                 f"background:{theme.BG};color:{theme.FG};border:1px solid {theme.LINE};")
        col.addWidget(self.flags, 1)
        row.addWidget(left)

        self.preview = Preview()
        row.addWidget(self.preview, 1)

        self.od.valueChanged.connect(lambda: self.edited("od"))
        self.length.valueChanged.connect(lambda: self.edited("length"))
        self.front.valueChanged.connect(lambda: self.edited("front"))
        self.bore.valueChanged.connect(lambda: self.edited(None))
        self.z0.currentIndexChanged.connect(lambda: self.edited("z0"))
        return page

    # ---- state ----
    def _load_guess(self):
        g = self.guess
        self.od.setValue(g.od)
        self.length.setValue(g.length)
        self.front.setValue(g.front)
        self.z0.setCurrentIndex(Z0_CHOICES.index(g.z0))
        for key, tag in self.tags.items():
            tag.set("AUTO", C_GUESS, g.reasons.get(key, ""))
        self.machine_tag.set("AUTO", C_GUESS, self.detection.summary)
        self.set_shape("round")
        lines = [f"LINE {f.line:<5} {f.level.upper():<12} {f.text}" if f.line else f"{f.level.upper():<12} {f.text}"
                 for f in self.program.flags]
        self.flags.setPlainText("\n".join(lines) if lines else "Nothing flagged.")
        bad = sum(1 for f in self.program.flags if f.level == "unsupported")
        self.flags_head.setText(f"FLAGS · {len(self.program.flags)}" + (f" · {bad} NOT READ" if bad else ""))

    def edited(self, key: str | None):
        if self._loading:
            return
        if key:
            self.tags[key].set("SET BY YOU", C_YOU)
        self.refresh()

    def set_machine(self, machine: str):
        self.machine = machine
        if machine != self.detection.machine:
            self.machine_tag.set("SET BY YOU", C_YOU)
        else:
            self.machine_tag.set("AUTO", C_GUESS, self.detection.summary)
        self.refresh()

    def set_shape(self, shape: str):
        self.shape = shape
        self.round_btn.setChecked(shape == "round")
        self.tube_btn.setChecked(shape == "tube")
        self.bore.setVisible(shape == "tube")
        self.bore_label.setVisible(shape == "tube")
        if not self._loading:
            self.refresh()

    def settings(self) -> dict:
        """What Step 1 decided - the input to the later steps."""
        return {"machine": self.machine, "shape": self.shape, "od": self.od.value(),
                "id": self.bore.value() if self.shape == "tube" else 0.0, "length": self.length.value(),
                "z0": self.z0.currentData(), "front": self.front.value() if self.z0.currentData() == "finished" else 0.0}

    def refresh(self):
        lathe = self.machine == "lathe"
        self.lathe_btn.setChecked(lathe)
        self.mill_btn.setChecked(not lathe)
        self.mill_note.setVisible(not lathe)
        self.front.setEnabled(self.z0.currentData() == "finished")
        s = self.settings()
        zb, zf = stock_z_range(s["z0"], s["length"], s["front"])
        self.preview.show_setup(self.program.moves, (zb, zf, s["od"], s["id"]),
                                "" if lathe else "MILL IMPORT NOT BUILT YET")
        if hasattr(self, "ops_page"):
            self.ops_page.reload()                      # stock (a tube's ID) and the preview follow Setup
        cuts = sum(1 for m in self.program.moves if m.kind != "rapid")
        metric = "  ·  PROGRAM IS METRIC, SHOWN IN INCHES" if self.program.units == "mm" else ""
        self.status.setText(f"{Path(self.path).name}  ·  {len(self.program.lines)} lines  ·  "
                            f"{len(self.program.moves)} moves ({cuts} cutting){metric}")
        self.next.setEnabled(lathe and self.pages.currentIndex() < len(STEPS) - 1)

    # ---- reconstruction ----
    def invalidate(self):
        self._recon = None

    def reconstruction(self):
        """The part as it stands now. Re-run whenever a tool, an operation or the stock changes."""
        if self._recon is None:
            try:
                self._recon = reconstruct(self.program, self.tools_page.tools, self.ops_page.ops, self.settings(),
                                          self.nose_center)
            except Exception as exc:                    # a bad program must not take the window down
                from .reconstruct import Reconstruction
                self._recon = Reconstruction(ok=False, error=f"{type(exc).__name__}: {exc}")
        return self._recon

    # ---- Phase 5: the part ----
    def build_part(self):
        """BUILD PART: the fitted outline as a sketch + a revolve, as a new part in the main window."""
        built = build_document(self.reconstruction(), Path(self.path).stem)
        if not built.ok:
            QMessageBox.warning(self, "Import G-code", built.error)
            return
        win = self.win
        win.cancel_command()
        if not win._maybe_save():                       # the user kept the current part
            return
        win._set_doc(built.doc, None)
        win.dirty = True                                # an import is unsaved work until it is saved
        f = built.fit
        win.viewport.show_toast(f"{built.doc.name} · {f.count('line')} lines + {f.count('arc')} arcs, revolved")
        win.message(f"Built from {Path(self.path).name}: sketch Profile ({f.count('line')} lines, {f.count('arc')} arcs, "
                    "worst fit {:.5f}) + Revolve1. Switch to CAM and add a Turning setup to program it.".format(f.max_dev))
        self.accept()

    # ---- keywords ----
    def open_keywords(self):
        dlg = KeywordsDialog(self, self.keywords_file, self.table)
        self.keywords_dialog = dlg
        dlg.exec()
        self.table = dlg.rows
        self.tools_page.reload(keep_row=self.tools_page.current())

    def save_keyword(self, text: str, tool_type: str):
        """Step 2's 'save as keyword for next time': added to the table as a USER row."""
        self.table = kw.add(self.table, text, tool_type, None, "USER")
        kw.save(self.keywords_file, self.table)

    def go(self, index: int):
        index = max(0, min(len(STEPS) - 1, index))
        if index > 0 and self.machine != "lathe":
            index = 0
        self.pages.setCurrentIndex(index)
        for i, b in enumerate(self.step_btns):
            b.setChecked(i == index)
        self.back.setEnabled(index > 0)
        self.next.setEnabled(self.machine == "lathe" and index < len(STEPS) - 1)
