"""CAM dialogs: the Tool Library and the Post Process (G-code) window.
"""
from __future__ import annotations


from PySide6.QtCore import Qt

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QPushButton, QSpinBox, QVBoxLayout)

from ..core import cam, post, tools
from . import theme
from .cam_cmds import op_moves
from .cmd_base import NumBox


# ------------------------------------------------------------------ post process (G-code)
class ToolLibraryDialog(QDialog):
    """CAM → Tool Library: the tools operations pick from (one list per machine). Every change
    is saved to the library file right away; operations copy the tool they use."""

    def __init__(self, win, machine: str = cam.MILLING, new_kind: str | None = None, select: str | None = None):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Tool Library")
        self.resize(640, 380)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        top = QHBoxLayout()
        self.machine = QComboBox()
        for k in (cam.MILLING, cam.TURNING):
            self.machine.addItem(cam.TYPES[k], k)
        self.machine.setCurrentIndex(self.machine.findData(machine))
        top.addWidget(QLabel("Machine"))
        top.addWidget(self.machine)
        top.addStretch()
        v.addLayout(top)
        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumWidth(260)
        body.addWidget(self.list, 1)
        form = QGridLayout()
        self.number = QSpinBox()
        self.number.setRange(1, 99)
        self.number.setPrefix("T")
        self.name = QLineEdit()
        self.kind = QComboBox()
        self.dia = NumBox(0.25, 4)
        self.dia.setRange(0, 100)
        self.nose = NumBox(0.0, 4)
        self.nose.setRange(0, 10)
        self.form, self._labels = form, {}
        for row, (label, w) in enumerate((("Number", self.number), ("Name", self.name), ("Type", self.kind),
                                          ("Diameter", self.dia), ("Nose radius", self.nose))):
            lb = QLabel(label)
            self._labels[id(w)] = [lb]
            form.addWidget(lb, row, 0)
            form.addWidget(w, row, 1)
        self.err = QLabel("")
        self.err.setStyleSheet(f"color:{theme.BAD};")
        self.err.setWordWrap(True)
        form.addWidget(self.err, 5, 0, 1, 2)
        form.setRowStretch(6, 1)
        body.addLayout(form, 1)
        v.addLayout(body, 1)
        foot = QHBoxLayout()
        self.add, self.delete, done = QPushButton("NEW TOOL"), QPushButton("DELETE"), QPushButton("CLOSE")
        for b in (self.add, self.delete, done):
            b.setObjectName("dlgBtn")
        foot.addWidget(self.add)
        foot.addWidget(self.delete)
        foot.addStretch()
        foot.addWidget(done)
        v.addLayout(foot)
        self.machine.currentIndexChanged.connect(lambda *_: self.fill())
        self.list.currentRowChanged.connect(self.show_tool)
        for sig in (self.number.valueChanged, self.name.editingFinished, self.kind.currentIndexChanged,
                    self.dia.valueChanged, self.nose.valueChanged):
            sig.connect(self.store)
        self.add.clicked.connect(lambda: self.new_tool())
        self.delete.clicked.connect(self.remove)
        done.clicked.connect(self.accept)
        self._busy = False
        self.fill(select=select)
        if new_kind:
            self.new_tool(new_kind)

    def tools_here(self):
        return sorted((t for t in self.win.tool_lib if t["machine"] == self.machine.currentData()),
                      key=lambda t: (t["number"], t["name"]))

    def fill(self, select: str | None = None):
        self._busy = True
        m = self.machine.currentData()
        self.kind.clear()
        for k in tools.MACHINE_KINDS[m]:
            self.kind.addItem(tools.KINDS[k], k)
        self.list.clear()
        for t in self.tools_here():
            it = QListWidgetItem(tools.describe(t))
            it.setData(Qt.UserRole, t["id"])
            self.list.addItem(it)
        self._busy = False
        ids = [t["id"] for t in self.tools_here()]
        self.list.setCurrentRow(ids.index(select) if select in ids else (0 if ids else -1))
        if not ids:
            self.show_tool(-1)

    def current(self):
        it = self.list.currentItem()
        tid = it.data(Qt.UserRole) if it else None
        return next((t for t in self.win.tool_lib if t["id"] == tid), None)

    def show_tool(self, _row):
        t = self.current()
        self._busy = True
        for w in (self.number, self.name, self.kind, self.dia, self.nose, self.delete):
            w.setEnabled(t is not None)
        if t:
            self.number.setValue(t["number"])
            self.name.setText(t["name"])
            self.kind.setCurrentIndex(max(0, self.kind.findData(t["kind"])))
            self.dia.setValue(t["dia"])
            self.nose.setValue(t["nose_r"])
        self.err.setText("")
        self._busy = False
        self.show_sizes()

    def store(self, *_):
        """A field changed: check the tool, put it in the library and save."""
        t = self.current()
        if self._busy or t is None:
            return
        try:
            new = tools.validate({**t, "number": self.number.value(), "name": self.name.text().strip(),
                                  "kind": self.kind.currentData(), "dia": self.dia.value(),
                                  "nose_r": self.nose.value()})
        except ValueError as exc:
            self.err.setText(str(exc))
            return
        self.err.setText("")
        renumbered = new["number"] != t["number"]
        t.update(new)
        self.win.save_tool_lib()
        self.list.currentItem().setText(tools.describe(t))
        self.show_sizes()
        if renumbered:
            self.fill(select=t["id"])              # keep the list in T-number order

    def show_sizes(self):
        """Diameter for mills / drills, nose radius for turning inserts."""
        insert = self.kind.currentData() == "od turn"
        for w, show in ((self.dia, not insert), (self.nose, insert)):
            w.setVisible(show)
            for lb in self._labels.get(id(w), []):
                lb.setVisible(show)
        self._labels[id(self.dia)][0].setText("Width" if self.kind.currentData() == "groove" else "Diameter")

    def new_tool(self, kind: str | None = None):
        m = self.machine.currentData()
        kind = kind or tools.MACHINE_KINDS[m][0]
        used = {t["number"] for t in self.tools_here()}
        n = next(k for k in range(1, 100) if k not in used) if len(used) < 99 else 1
        t = tools.validate({"id": tools.new_id(self.win.tool_lib), "number": n, "name": f"New {tools.KINDS[kind]}",
                            "kind": kind, "machine": m,
                            "dia": {"od turn": 0.0, "groove": 0.125}.get(kind, 0.25),
                            "nose_r": 0.031 if kind == "od turn" else 0.0})
        self.win.tool_lib.append(t)
        self.win.last_new_tool = t["id"]
        self.win.save_tool_lib()
        self.fill(select=t["id"])
        self.name.setFocus()
        self.name.selectAll()

    def remove(self):
        t = self.current()
        if t is None:
            return
        self.win.tool_lib.remove(t)
        self.win.save_tool_lib()
        self.fill()


class PostDialog(QDialog):
    """CAM → Post Process: a setup's operations as G-code. Preview, then Save .nc."""

    def __init__(self, win, setup_id: str | None = None):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Post Process · G-code")
        self.resize(720, 640)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        top = QHBoxLayout()
        self.setup = QComboBox()
        for st in win.doc.setups:
            n = len(st.get("ops", []))
            self.setup.addItem(f"{st['name']} · {cam.TYPES[st['type']]} · {n} op{'s' if n != 1 else ''}", st["id"])
        self.setup.setCurrentIndex(max(0, self.setup.findData(setup_id)))
        self.control = QComboBox()
        for k, label in post.CONTROLLERS.items():
            self.control.addItem(label, k)
        self.program = QSpinBox()
        self.program.setRange(1, 9999)
        self.program.setPrefix("O")
        self.program.setButtonSymbols(QSpinBox.NoButtons)
        self.offset = QComboBox()
        self.offset.addItems(post.OFFSETS)
        self.coolant = QCheckBox("Coolant (M08)")
        self.comp = QComboBox()                         # cutter comp for a lathe Contour: off / machine / computer
        for k, label in post.COMPS.items():
            self.comp.addItem(label, k)
        self.comp.setToolTip("Lathe Contour only.\nOff: the part line point to point.\nMachine: the same points with "
                             "G41 / G42 and G40, the control compensates.\nComputer: no G41 / G42 / G40; the points "
                             "carry the tool nose radius.")
        for label, w in (("Setup", self.setup), ("Control", self.control), ("Program", self.program),
                         ("Work offset", self.offset), ("Cutter comp", self.comp)):
            top.addWidget(QLabel(label))
            top.addWidget(w)
        top.addWidget(self.coolant)
        top.addStretch()
        v.addLayout(top)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setStyleSheet(f"font-family:'{theme.MONO[0]}','Consolas',monospace;font-size:12px;"
                                f"background:{theme.BG};color:{theme.FG};")
        v.addWidget(self.text, 1)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{theme.FG2};")
        self.status.setWordWrap(True)                   # a left-out op's reason can be long
        foot = QHBoxLayout()
        foot.addWidget(self.status, 1)
        close, save = QPushButton("CLOSE"), QPushButton("SAVE .NC…")
        for b in (close, save):
            b.setObjectName("dlgBtn")
            foot.addWidget(b)
        save.setProperty("ok", True)
        close.clicked.connect(self.reject)
        save.clicked.connect(self.save)
        v.addLayout(foot)
        self.setup.currentIndexChanged.connect(self.load_settings)
        for w in (self.control, self.offset, self.comp):
            w.currentIndexChanged.connect(self.refresh)
        self.program.valueChanged.connect(self.refresh)
        self.coolant.toggled.connect(self.refresh)
        self.load_settings()

    def current(self):
        return self.win.doc.setup(self.setup.currentData())

    def load_settings(self, *_):
        """Each setup remembers its post settings (saved in the .gcad file)."""
        st = self.current()
        i = self.win.doc.setups.index(st)
        ps = st.get("post", {"controller": "haas", "program": 1000 + i, "offset": "G54", "coolant": True})
        for w in (self.control, self.offset, self.program, self.coolant, self.comp):
            w.blockSignals(True)
        self.control.setCurrentIndex(max(0, self.control.findData(ps["controller"])))
        self.offset.setCurrentText(ps["offset"])
        self.program.setValue(int(ps["program"]))
        self.coolant.setChecked(bool(ps["coolant"]))
        self.comp.setCurrentIndex(max(0, self.comp.findData(ps.get("comp", "off"))))
        self.comp.setEnabled(st["type"] == cam.TURNING)       # a lathe thing: greyed out (not hidden) on a mill
        for w in (self.control, self.offset, self.program, self.coolant, self.comp):
            w.blockSignals(False)
        self.refresh()

    def settings(self) -> dict:
        return {"controller": self.control.currentData(), "program": self.program.value(),
                "offset": self.offset.currentText(), "coolant": self.coolant.isChecked(),
                "comp": self.comp.currentData() if self.comp.isEnabled() else "off"}

    def gcode(self) -> str:
        """The setup's program. An op that can't make a toolpath (a Groove with no groove on
        the part, a Drill with no hole...) is left out and named in self.skipped, instead of
        blanking the whole program (Shane 10/1/26)."""
        st = self.current()
        ops, self.skipped, self.minutes = [], [], 0.0
        for o in st.get("ops", []):
            try:
                mv = op_moves(self.win, st, o)[0]
            except ValueError as exc:
                self.skipped.append(f"{o.get('name', 'op')}: {exc}")
                continue
            if o.get("type") == "finish" and "nose_r" not in o:      # an older op: the library's nose radius
                t = tools.find(self.win.tool_lib, o, st["type"], "finish")
                o = {**o, "nose_r": t["nose_r"] if t else 0.0}
            ops.append((o, mv))
            self.minutes += cam.cycle_time(mv, st, o)
        if not ops:
            raise ValueError("Nothing to post · " + (" · ".join(self.skipped) if self.skipped else
                                                     "this setup has no toolpaths yet"))
        ps = self.settings()
        g = post.post_setup(st, ops, ps["controller"], ps["program"], ps["offset"], ps["coolant"],
                            self.win.doc.name, ps["comp"])
        if self.skipped:                              # say so at the top of the program too
            lines = g.splitlines()
            note = [post._comment("NOT POSTED - " + s) for s in self.skipped]
            g = "\n".join(lines[:2] + note + lines[2:]) + ("\n" if g.endswith("\n") else "")
        return g

    def refresh(self, *_):
        try:
            g = self.gcode()
        except ValueError as exc:
            self.text.setPlainText("")
            self.status.setText(str(exc))
            return
        self.text.setPlainText(g)
        n = len(g.splitlines())
        skipped = f" · LEFT OUT: {' · '.join(self.skipped)}" if self.skipped else ""
        self.status.setText(f"{n} lines · about {self.minutes:.1f} min cutting{skipped}")
        self.status.setStyleSheet(f"color:{theme.WARN if self.skipped else theme.FG2};")

    def save(self):
        try:
            g = self.gcode()
        except ValueError as exc:
            self.win.viewport.show_toast(str(exc), bad=True)
            return
        st = self.current()
        name = f"O{self.program.value():04d} {self.win.doc.name} {st['name']}.nc"
        base = str(self.win.path.parent / name) if getattr(self.win, "path", None) else name
        path, _ = QFileDialog.getSaveFileName(self, "Save G-code", base, "G-code (*.nc *.tap *.txt);;All files (*)")
        if not path:
            return
        with open(path, "w", newline="\r\n") as fh:      # CRLF: what Windows DNC / USB loaders expect
            fh.write(g)
        if st.get("post") != self.settings():
            st["post"] = self.settings()
            self.win.dirty = True
            self.win.topbar.set_doc(self.win.doc.name, True)
        self.win.viewport.show_toast(f"G-code saved · {path.replace(chr(92), '/').split('/')[-1]}")
        self.status.setText(f"Saved {path}")
