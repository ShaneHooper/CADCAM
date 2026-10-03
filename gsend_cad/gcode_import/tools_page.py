"""Step 2 TOOLS: one row per tool, and a side panel to define the ones the program did not."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..ui import theme
from . import keywords as kw
from . import tooling
from .inserts import parse_insert
from .widgets import STATUS_COLOUR, TABLE_CSS, Num, Tag, button, head, toggle

COLUMNS = ("T", "COMMENT", "KEYWORD(S)", "TYPE", "INSERT / SIZE", "NOSE R", "SIDE", "STATUS")
ADD_TYPE = "+ ADD TOOL TYPE…"


def type_items() -> list[str]:
    """What the tool-type dropdown offers: built-ins, the user's own types, UNKNOWN, then the add entry."""
    return list(kw.all_tool_types()) + [kw.UNKNOWN, ADD_TYPE]


class AddTypeDialog(QDialog):
    """Name a new tool type and say which built-in it cuts like (that decides its shape and its fields)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Add tool type")
        self.setStyleSheet(f"QDialog{{background:{theme.BG};}} QLabel{{color:{theme.FG};}}")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(8)
        v.addWidget(head("New tool type"))
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. THREAD MILL, BACK BORE, WIPER")
        self.like = QComboBox()
        self.like.addItems(list(kw.TOOL_TYPES))
        g.addWidget(QLabel("NAME"), 0, 0)
        g.addWidget(self.name, 0, 1)
        g.addWidget(QLabel("CUTS LIKE"), 1, 0)
        g.addWidget(self.like, 1, 1)
        g.setColumnStretch(1, 1)
        v.addLayout(g)
        hint = QLabel("The type is yours to name; CUTS LIKE picks the built-in shape the reconstruction uses for it "
                      "(an OD TURN insert, a drill, a groove blade, a thread that removes nothing...). It is saved "
                      "with your keywords and offered next time.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{theme.FG3};font-size:11px;")
        v.addWidget(hint)
        self.note = QLabel("")
        self.note.setStyleSheet(f"color:{theme.BAD};font-size:11px;")
        v.addWidget(self.note)
        foot = QHBoxLayout()
        foot.addStretch()
        cancel, ok = button("CANCEL"), button("ADD", ok=True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept_if_named)
        ok.setDefault(True)
        foot.addWidget(cancel)
        foot.addWidget(ok)
        v.addLayout(foot)
        self.name.setFocus()

    def accept_if_named(self):
        if not kw.clean(self.name.text()):
            self.note.setText("Give the type a name.")
            return
        if kw.clean(self.name.text()) in (kw.UNKNOWN, ADD_TYPE):
            self.note.setText("That name is taken.")
            return
        self.accept()

    def result_type(self) -> tuple[str, str]:
        return kw.clean(self.name.text()), self.like.currentText()


def insert_or_size(t: tooling.Tool) -> str:
    if t.insert:
        return t.insert
    if t.size is not None:
        return f"{t.size_text}  ({t.size:.4f})" if t.size_text else f"{t.size:.4f}"
    return "—"


class ToolsPage(QWidget):
    changed = Signal()              # the tool list changed (Phase 4 re-runs the reconstruction on this)

    def __init__(self, wizard):
        super().__init__()
        self.wiz = wizard
        self.tools: list[tooling.Tool] = []
        self._loading = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(6)
        self.counts = QLabel("")
        self.counts.setTextFormat(Qt.RichText)
        left.addWidget(self.counts)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setStyleSheet(TABLE_CSS)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.currentCellChanged.connect(lambda r, *_: self.show_tool(r))
        left.addWidget(self.table, 1)
        row.addLayout(left, 1)
        row.addWidget(self._panel())

    # ---- side panel ----
    def _panel(self) -> QWidget:
        box = QFrame()
        box.setFixedWidth(360)
        box.setStyleSheet(f"QFrame{{background:{theme.PANEL};border:1px solid {theme.LINE};}} QLabel{{border:0;}}")
        col = QVBoxLayout(box)
        col.setContentsMargins(12, 6, 12, 10)
        col.setSpacing(6)
        self.title = head("Tool")
        col.addWidget(self.title)
        self.status = Tag("UNKNOWN", 96)
        self.why = QLabel("")
        self.why.setWordWrap(True)
        self.why.setStyleSheet(f"color:{theme.FG2};font-size:11px;")
        top = QHBoxLayout()
        top.addWidget(self.status)
        top.addWidget(self.why, 1)
        col.addLayout(top)

        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        self.type = QComboBox()
        self.type.addItems(type_items())
        self.insert = QLineEdit()
        self.insert.setPlaceholderText("CNMG 432 / CNMG 120408")
        self.shape = QLabel("")
        self.shape.setStyleSheet(f"color:{theme.FG2};font-size:11px;")
        self.nose = Num(0.0, 1.0, 1.0 / 64.0)
        self.nose_tag = Tag("ASSUMED")
        self.size = Num(0.0, 100.0, 1.0 / 64.0)
        self.size_label = QLabel("SIZE")
        self.rh, self.lh = toggle("RH"), toggle("LH")
        self.sides = {s: toggle(s) for s in tooling.SIDES}
        hand = QHBoxLayout()
        hand.addWidget(self.rh)
        hand.addWidget(self.lh)
        hand.addStretch()
        side = QHBoxLayout()
        for b in self.sides.values():
            side.addWidget(b)
        side.addStretch()
        nose = QHBoxLayout()
        nose.addWidget(self.nose)
        nose.addWidget(self.nose_tag)
        nose.addStretch()
        for r, (label, w) in enumerate((("TOOL TYPE", self.type), ("INSERT CODE", self.insert), ("", self.shape),
                                        ("NOSE RADIUS", nose), (self.size_label, self.size), ("HAND", hand),
                                        ("CUTS ON", side))):
            g.addWidget(QLabel(label) if isinstance(label, str) else label, r, 0)
            if isinstance(w, QWidget):
                g.addWidget(w, r, 1)
            else:
                g.addLayout(w, r, 1)
        g.setColumnStretch(1, 1)
        col.addLayout(g)

        self.save_kw = QCheckBox("SAVE AS KEYWORD FOR NEXT TIME")
        self.kw_text = QLineEdit()
        self.kw_text.setPlaceholderText("keyword text")
        col.addWidget(self.save_kw)
        col.addWidget(self.kw_text)
        self.assumed = QLabel("")
        self.assumed.setWordWrap(True)
        col.addWidget(self.assumed)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{theme.BAD};font-size:11px;")
        col.addWidget(self.note)
        col.addStretch()
        self.apply_btn = button("APPLY · NEXT UNRESOLVED", ok=True)
        col.addWidget(self.apply_btn)

        self.type.currentTextChanged.connect(self._type_changed)
        self.insert.textEdited.connect(self._insert_typed)
        self.nose.valueChanged.connect(self._nose_typed)
        self.size.valueChanged.connect(self._size_typed)
        self.rh.clicked.connect(lambda: self._set_hand("RH"))
        self.lh.clicked.connect(lambda: self._set_hand("LH"))
        for s, b in self.sides.items():
            b.clicked.connect(lambda _=False, s=s: self._set_side(s))
        self.save_kw.toggled.connect(self.kw_text.setEnabled)
        self.apply_btn.clicked.connect(self.apply)
        return box

    # ---- list ----
    def reload(self, keep_row: int | None = None):
        self.tools = tooling.build_tools(self.wiz.program, self.wiz.table, self.wiz.overrides)
        self._loading = True
        self.table.setRowCount(len(self.tools))
        for r, t in enumerate(self.tools):
            cells = (f"T{t.number}", t.comment or "—", ", ".join(t.keywords) or "—", t.type, insert_or_size(t),
                     f"{t.nose_radius:.4f}" + (" ASSUMED" if t.nose_assumed and t.type != "DRILL" else ""),
                     t.side, t.status)
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 7:
                    item.setForeground(QColor(STATUS_COLOUR[t.status]))
                elif c == 5 and "ASSUMED" in text or c == 3 and t.type == kw.UNKNOWN:
                    item.setForeground(QColor(STATUS_COLOUR["ASSUMED" if c == 5 else "UNKNOWN"]))
                item.setToolTip(t.why if c in (3, 7) else t.comment if c == 1 else "")
                self.table.setItem(r, c, item)
        n = tooling.counts(self.tools)
        self.counts.setText(
            f"<span style='color:{theme.FG2};letter-spacing:2px'>TOOLS · {len(self.tools)}</span>&nbsp;&nbsp;&nbsp;"
            + "&nbsp;&nbsp;&nbsp;".join(f"<span style='color:{STATUS_COLOUR[s]}'>{s} {n[s]}</span>"
                                        for s in tooling.STATUSES))
        self._loading = False
        if self.tools:
            row = keep_row if keep_row is not None and keep_row < len(self.tools) else (
                tooling.next_unresolved(self.tools) or 0)
            self.table.setCurrentCell(row, 0)
            self.show_tool(row)
        self.changed.emit()

    def current(self) -> int:
        return self.table.currentRow()

    def show_tool(self, row: int):
        if self._loading or not (0 <= row < len(self.tools)):
            return
        t = self.tools[row]
        self._loading = True
        self.draft = t
        self.title.setText(f"T{t.number}" + (f" · {t.comment}" if t.comment else ""))
        self.status.set(t.status, tip=t.why)
        self.why.setText(f"Found by: {t.why}." if t.status != tooling.DEFINED else "Set by you.")
        self.type.setCurrentText(t.type)
        self.insert.setText(t.insert)
        self.nose.setValue(t.nose_radius)
        self.size.setValue(t.size or 0.0)
        self.save_kw.setChecked(False)
        self.kw_text.setEnabled(False)
        self.kw_text.setText(tooling.keyword_suggestion(t.comment))
        self.note.setText("")
        self._loading = False
        self._sync()

    def _sync(self):
        """Panel widgets that follow the draft tool."""
        d = self.draft
        self.rh.setChecked(d.hand == "RH")
        self.lh.setChecked(d.hand == "LH")
        for s, b in self.sides.items():
            b.setChecked(d.side == s)
        ins = parse_insert(d.insert)
        self.shape.setText(f"{ins.system} · {ins.shape_name} · nose {ins.nose_radius:.4f}" if ins else
                           ("not an insert code I can read" if d.insert else ""))
        sized = d.type in tooling.SIZED
        self.size_label.setText(tooling.SIZED.get(d.base, "SIZE"))
        self.size.setEnabled(sized)
        drilling = d.base in ("DRILL", "SPOT DRILL", "TAP")
        self.nose.setEnabled(not drilling)
        if drilling:
            self.nose_tag.set("—", theme.FG3)
        elif d.nose_assumed:
            self.nose_tag.set("ASSUMED", tip="a default - type the radius or an insert code")
        else:
            self.nose_tag.set("READ" if ins and abs(ins.nose_radius - d.nose_radius) < 1e-6 else "SET BY YOU")
        text = d.assumed
        self.assumed.setText(text)
        self.assumed.setStyleSheet(f"color:{theme.FG2 if text == 'Nothing assumed.' else theme.WARN};font-size:11px;")

    # ---- edits (to the draft; nothing is kept until APPLY) ----
    def _type_changed(self, text: str):
        if self._loading:
            return
        if text == ADD_TYPE:
            text = self.add_type()                      # a new type (and it is selected), or the old one again
            if text is None:
                self._loading = True
                self.type.setCurrentText(self.draft.type)
                self._loading = False
                return
        base = kw.base_of(text)
        d = replace(self.draft, type=text, side=tooling.default_side(text))
        if base in tooling.NOSED and not d.insert and d.nose_radius == 0.0:
            d = replace(d, nose_radius=tooling.DEFAULT_NOSE, nose_assumed=True)
            self._loading = True
            self.nose.setValue(d.nose_radius)
            self._loading = False
        elif base not in tooling.NOSED:             # no nose radius to assume on a drill / groove tool
            d = replace(d, nose_assumed=text == kw.UNKNOWN)
        self.draft = d
        self._sync()

    def add_type(self) -> str | None:
        """The '+ ADD TOOL TYPE...' entry: ask, register, save with the keywords, refill the dropdown."""
        dlg = AddTypeDialog(self)
        self.add_dialog = dlg
        if dlg.exec() != QDialog.Accepted:
            return None
        name, like = dlg.result_type()
        name = kw.add_tool_type(name, like)
        if name is None:
            return None
        kw.save(self.wiz.keywords_file, self.wiz.table)
        self.refill_types(name)
        return name

    def refill_types(self, select: str | None = None):
        self._loading = True
        self.type.clear()
        self.type.addItems(type_items())
        self.type.setCurrentText(select or self.draft.type)
        self._loading = False

    def _insert_typed(self, text: str):
        if self._loading:
            return
        self.draft = tooling.apply_insert(self.draft, text)
        if parse_insert(text):                      # a code fills in the shape and the nose radius
            self._loading = True
            self.nose.setValue(self.draft.nose_radius)
            self._loading = False
        self._sync()

    def _nose_typed(self, value: float):
        if self._loading:
            return
        self.draft = replace(self.draft, nose_radius=value, nose_assumed=False)
        self._sync()

    def _size_typed(self, value: float):
        if self._loading:
            return
        self.draft = replace(self.draft, size=value if value > 0 else None, size_text="")
        self._sync()

    def _set_hand(self, hand: str):
        self.draft = replace(self.draft, hand=hand)
        self._sync()

    def _set_side(self, side: str):
        self.draft = replace(self.draft, side=side)
        self._sync()

    def apply(self):
        row = self.current()
        if not (0 <= row < len(self.tools)):
            return
        d = self.draft
        if d.type == kw.UNKNOWN:
            self.note.setText("Pick a tool type first - UNKNOWN stays a sharp point.")
            return
        size = d.size if d.type in tooling.SIZED else None
        d = replace(d, nose_assumed=False, size=size, size_text=d.size_text if size else "",
                    status=tooling.DEFINED)
        if d.type in tooling.SIZED and size is None:
            self.note.setText(f"Type the {tooling.SIZED[d.base].lower()} - without it the cut is ASSUMED.")
            return
        self.wiz.overrides[d.number] = d
        if self.save_kw.isChecked() and kw.clean(self.kw_text.text()):
            self.wiz.save_keyword(self.kw_text.text(), d.type)
        self.reload(keep_row=row)
        nxt = tooling.next_unresolved(self.tools, row)
        if nxt is not None:
            self.table.setCurrentCell(nxt, 0)
