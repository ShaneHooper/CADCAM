"""Step 3 OPERATIONS: the program cut into operations, each with a type the user can change."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..ui import theme
from . import keywords as kw
from . import operations
from .preview import Preview
from .recon_page import profile_summary
from .stock import stock_z_range
from .widgets import MONO_CSS, STATUS_COLOUR, TABLE_CSS, head

COLUMNS = ("#", "TOOL", "COMMENT", "LINES", "FOUND BY", "TYPE", "CONFIDENCE")
NO_TYPE = "— pick a type —"


def summary_text(s: dict, rec=None) -> str:
    """Operations first, then the profile's own numbers once it has been reconstructed."""
    rows = [("OPERATIONS", f"{s['operations']}" + (f"  ({s['skipped']} skipped)" if s["skipped"] else ""))]
    text = "\n".join(f"{k:<16} {v}" for k, v in rows)
    if rec is not None:
        return text + "\n" + profile_summary(rec, s["needs_type"])
    z = s["cut_z"]
    rows = [
        ("NEED A TYPE", str(s["needs_type"])),
        ("STOCK Ø", f"{s['stock_od']:.4f}"),
        ("CUTS SPAN Z", f"{z[0]:.4f} to {z[1]:.4f}  ({z[1] - z[0]:.4f} long)" if z else "no cuts"),
        ("BORE", f"Ø{s['bore']:.4f}" if s["bore"] else "none (solid)"),
        ("THREADS", "none" if not s["threads"] else s["threads"][0]),
    ]
    rows += [("", t) for t in s["threads"][1:]]
    return text + "\n" + "\n".join(f"{k:<16} {v}" for k, v in rows)


class OpsPage(QWidget):
    changed = Signal()

    def __init__(self, wizard):
        super().__init__()
        self.wiz = wizard
        self.ops: list[operations.Operation] = []
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
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.currentCellChanged.connect(lambda r, *_: self.select(r))
        left.addWidget(self.table, 1)
        note = QLabel("The type is a label - it does not change the geometry. An operation with no type still "
                      "contributes its cuts; SKIP leaves them out.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{theme.FG3};font-size:11px;")
        left.addWidget(note)
        row.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.preview = Preview()
        self.preview.setMinimumSize(360, 260)
        right.addWidget(self.preview, 1)
        right.addWidget(head("Summary"))
        self.summary = QLabel("")
        self.summary.setStyleSheet(f"{MONO_CSS}font-size:11px;color:{theme.FG};border:1px solid {theme.LINE};"
                                   f"padding:6px;background:{theme.PANEL};")
        self.summary.setWordWrap(True)
        right.addWidget(self.summary)
        row.addLayout(right, 2)

    def reload(self):
        wiz = self.wiz
        stock = wiz.settings()
        keep = self.table.currentRow()
        self.ops = operations.build_operations(wiz.program, wiz.tools_page.tools, wiz.table, wiz.op_overrides,
                                               stock["id"])
        self._loading = True
        self.table.setRowCount(len(self.ops))
        for r, o in enumerate(self.ops):
            cells = (f"{o.index} · OP2" if o.part == 2 else str(o.index), f"T{o.tool}", o.comment or "—", o.lines,
                     o.found_by, "", o.confidence)
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 6:
                    item.setForeground(QColor(STATUS_COLOUR[o.confidence]))
                if c in (4, 6):
                    item.setToolTip(o.why)
                elif c == 2:
                    item.setToolTip(o.comment)
                self.table.setItem(r, c, item)
            combo = QComboBox()
            combo.addItems([NO_TYPE] + list(kw.OP_TYPES))
            combo.setCurrentText(o.type or NO_TYPE)
            combo.setToolTip(o.why)
            combo.currentTextChanged.connect(lambda text, key=o.key: self.set_type(key, text))
            self.table.setCellWidget(r, 5, combo)
        n = operations.counts(self.ops)
        self.counts.setText(
            f"<span style='color:{theme.FG2};letter-spacing:2px'>OPERATIONS · {len(self.ops)}</span>"
            "&nbsp;&nbsp;&nbsp;" + "&nbsp;&nbsp;&nbsp;".join(
                f"<span style='color:{STATUS_COLOUR[c]}'>{c} {n[c]}</span>" for c in operations.CONFIDENCES))
        zb, zf = stock_z_range(stock["z0"], stock["length"], stock["front"])
        wiz.invalidate()
        rec = wiz.reconstruction()                      # live: the profile follows every change
        self.preview.show_toolpath = False              # only the selected operation's moves, over the part
        self.preview.show_setup(wiz.model.moves, (zb, zf, stock["od"], stock["id"]),
                                profile=rec.edges if rec.ok else None)
        self.summary.setText(summary_text(operations.summary(wiz.model, self.ops, wiz.tools_page.tools, stock),
                                          rec))
        self._loading = False
        if self.ops:
            row = keep if 0 <= keep < len(self.ops) else 0
            self.table.setCurrentCell(row, 0)
            self.select(row)
        else:
            self.preview.show_highlight(None)
        self.changed.emit()

    def combo(self, row: int) -> QComboBox:
        return self.table.cellWidget(row, 5)

    def select(self, row: int):
        if self._loading or not (0 <= row < len(self.ops)):
            return
        o = self.ops[row]
        self.preview.show_highlight(o.moves, f"#{o.index}  T{o.tool}  {o.type or 'NEEDS TYPE'}  ·  {o.lines}")

    def set_type(self, key: str, text: str):
        if self._loading:
            return
        if text == NO_TYPE:
            self.wiz.op_overrides.pop(key, None)        # back to what the program says
        else:
            self.wiz.op_overrides[key] = text
        self.reload()
