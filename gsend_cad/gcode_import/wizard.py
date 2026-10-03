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
from . import flip as fl
from .build import build_document
from .detect import detect_machine
from .fit import GRID_INCH, GRID_MM
from .keywords_page import KeywordsDialog
from .ops_page import OpsPage
from .parser import Flag, parse_program
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
OPEN_WIDTH, OPEN_HEIGHT = 0.98, 0.94                # the import window's size as a share of the main window's


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
        if dlg.flip_marker is not None:                 # OP1 and OP2 in one program: ask for the overall length
            dlg.prompt_flip()
        dlg.exec()
        return dlg
    except Exception as exc:                            # never take the app down with the importer
        QMessageBox.warning(win, "Import G-code", f"The G-code import stopped:\n{exc}\n\n{traceback.format_exc(limit=3)}")
        return None


class FlipDialog(QDialog):
    """The little box a flip program (OP1 and OP2 in one file) opens with: the part's overall length."""

    def __init__(self, parent, marker, default: float):
        super().__init__(parent)
        self.setWindowTitle("Flip program")
        self.setStyleSheet(f"QDialog{{background:{theme.BG};}} QLabel{{color:{theme.FG};}}")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(10)
        v.addWidget(_head("Flip program found"))
        text = QLabel(f'Line {marker.line}: "{marker.text}" starts OP2 in the same program.\n\n'
                      "Enter the overall length of the part. OP2 runs from the other end: its Z0 sits that far from "
                      "OP1's Z0, and its tools are turned end for end.")
        text.setWordWrap(True)
        text.setMinimumWidth(420)
        v.addWidget(text)
        row = QHBoxLayout()
        row.addWidget(QLabel("OVERALL LENGTH"))
        self.length = Num(0.001)
        self.length.setValue(default)
        self.length.selectAll()
        row.addWidget(self.length)
        row.addWidget(QLabel("in"))
        row.addStretch()
        v.addLayout(row)
        hint = QLabel(f"A first guess from how deep OP1 cuts ({default:.4f}); type the real one.")
        hint.setStyleSheet(f"color:{theme.FG3};font-size:11px;")
        v.addWidget(hint)
        foot = QHBoxLayout()
        foot.addStretch()
        no, ok = button("NO FLIP"), button("OK", ok=True)
        no.setToolTip("Read the whole program as one operation")
        no.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        ok.setDefault(True)
        foot.addWidget(no)
        foot.addWidget(ok)
        v.addLayout(foot)


class ImportWizard(QDialog):
    def __init__(self, win, path: str, text: str):
        super().__init__(win)
        self.win = win
        self.path = path
        self.base_program = parse_program(text)         # as written: each half in its own frame
        self.program = self.base_program                # ... plus the flip, once the user gives the length
        self.model = self.program                       # one part in OP1's frame (OP2 mirrored): what Step 4 sees
        self.flip_marker = fl.find_marker(self.base_program)
        self.detection = detect_machine(self.program.lines)
        self.guess = guess_stock(self.model)
        self.machine = self.detection.machine
        self.keywords_file = keywords_path(win)
        self.table = kw.load(self.keywords_file)        # keyword table (Settings > Keywords)
        self.overrides = {}                             # tool number -> Tool the user defined in Step 2
        self.op_overrides = {}                          # operation key -> type the user picked in Step 3
        self.nose_center = False                        # per-import: X / Z point at the nose centre, not the tip
        self._recon = None                              # cached reconstruction (cleared on any change)
        self._loading = True
        self.setWindowTitle(f"Import G-code · {Path(path).name}")
        self._open_large()
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

    def _open_large(self):
        """Open at WIDTH x HEIGHT of the main window it was opened over, centred on it (the backplot and the
        tables need the room). A main window too small to say falls back to a fixed size."""
        g = self.win.geometry()
        if g.width() < 800 or g.height() < 500:
            self.resize(1200, 720)
            return
        w, h = int(g.width() * OPEN_WIDTH), int(g.height() * OPEN_HEIGHT)
        self.resize(w, h)
        self.move(g.x() + (g.width() - w) // 2, g.y() + (g.height() - h) // 2)

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

        # a flip program (OP1 and OP2 in one file): shown only when a flip comment was found
        self.flip_head = _head("Flip program · OP2")
        col.addWidget(self.flip_head)
        self.flip_note = QLabel("")
        self.flip_note.setWordWrap(True)
        self.flip_note.setStyleSheet(f"color:{theme.FG2};font-size:11px;")
        col.addWidget(self.flip_note)
        self.flip_len, self.flip_tag = Num(0.0), Tag("OFF")
        self.flip_row = QWidget()
        fg = QGridLayout(self.flip_row)
        fg.setContentsMargins(0, 0, 0, 0)
        fg.setHorizontalSpacing(8)
        fg.addWidget(QLabel("OVERALL LENGTH"), 0, 0)
        fg.addWidget(self.flip_len, 0, 1)
        fg.addWidget(self.flip_tag, 0, 2)
        fg.setColumnStretch(3, 1)
        col.addWidget(self.flip_row)
        for w in (self.flip_head, self.flip_note, self.flip_row):
            w.setVisible(self.flip_marker is not None)

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
        self.flip_len.valueChanged.connect(lambda v: self.set_flip_length(v))
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
        self._show_flags()
        self._show_flip()

    def _show_flags(self):
        flags = list(self.program.flags)
        if self.program.flip is not None:
            f = self.program.flip
            flags.insert(0, Flag(f.line, "info", f'flip program: "{f.text}" starts OP2. OP2\'s Z0 is {f.length:.4f} '
                                                 "from OP1's, on the other end of the part"))
        lines = [f"LINE {f.line:<5} {f.level.upper():<12} {f.text}" if f.line else f"{f.level.upper():<12} {f.text}"
                 for f in flags]
        self.flags.setPlainText("\n".join(lines) if lines else "Nothing flagged.")
        bad = sum(1 for f in flags if f.level == "unsupported")
        self.flags_head.setText(f"FLAGS · {len(flags)}" + (f" · {bad} NOT READ" if bad else ""))

    # ---- flip programs (OP1 + OP2 in one file) ----
    def _show_flip(self):
        m = self.flip_marker
        if m is None:
            return
        f = self.program.flip
        self.flip_note.setText(
            f'Line {m.line}: "{m.text}" starts OP2. Type the part\'s overall length and OP2 runs from the other end - '
            "its Z0 sits that far from OP1's, with the tools turned end for end. 0 = not a flip program."
            + ("" if f is None else f"  OP2 Z0 is at Z-{f.length:.4f} in OP1's frame."))
        self.flip_tag.set("SET BY YOU" if f is not None else "OFF", None, "")

    def prompt_flip(self) -> bool:
        """The little box: the overall length of the part. Cancel leaves the program as one (no flip)."""
        dlg = FlipDialog(self.win, self.flip_marker, fl.guess_length(self.base_program, self.flip_marker))
        if dlg.exec() != QDialog.Accepted:
            return False
        self._loading = True
        self.flip_len.setValue(dlg.length.value())
        self._loading = False
        self.set_flip_length(dlg.length.value())
        return True

    def set_flip_length(self, length: float | None):
        """Tell the program the part's overall length (None or 0: not a flip). OP2 is mirrored into OP1's frame
        for Step 4 and the previews; the stock length follows unless the user typed one."""
        if self._loading or self.flip_marker is None:
            return
        self.program = (fl.with_flip(self.base_program, self.flip_marker, length) if length and length > 0
                        else self.base_program)
        self.model = fl.model(self.program)
        self.invalidate()
        self.guess = guess_stock(self.model)
        self._loading = True
        if self.tags["length"].text() == "AUTO":
            self.length.setValue(self.guess.length)
            self.tags["length"].set("AUTO", C_GUESS, self.guess.reasons["length"])
        self._loading = False
        self._show_flags()
        self._show_flip()
        self.refresh()

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
        self.preview.show_setup(self.model.moves, (zb, zf, s["od"], s["id"]),
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
                self._recon = reconstruct(self.model, self.tools_page.tools, self.ops_page.ops, self.settings(),
                                          self.nose_center)
            except Exception as exc:                    # a bad program must not take the window down
                from .reconstruct import Reconstruction
                self._recon = Reconstruction(ok=False, error=f"{type(exc).__name__}: {exc}")
        return self._recon

    def grid(self) -> float:
        """The program's own resolution in inches: what the fitted profile's clean values snap to."""
        return GRID_INCH if self.program.units == "inch" else GRID_MM / 25.4

    # ---- the part: Phase 5 (sketch + revolve) and Phase 6 (clean values, ASSUMED marked) ----
    def build_part(self):
        """BUILD PART: the fitted outline as a sketch + a revolve, as a new part in the main window."""
        built = build_document(self.reconstruction(), Path(self.path).stem, self.grid())
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
        warn = (f" {f.assumed} piece{'s' if f.assumed != 1 else ''} only ASSUMED (yellow in the sketch): check "
                f"{'them' if f.assumed != 1 else 'it'} against the drawing.") if f.assumed else ""
        win.message(f"Built from {Path(self.path).name}: sketch Profile ({f.count('line')} lines, {f.count('arc')} arcs, "
                    "worst fit {:.5f}) + Revolve1.".format(f.max_dev) + warn
                    + " Switch to CAM and add a Turning setup to program it.")
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
