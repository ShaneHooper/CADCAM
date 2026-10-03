"""Settings > Keywords: the editable keyword table, with a box to test a comment against it."""
from __future__ import annotations

from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)
from PySide6.QtGui import QColor

from ..ui import theme
from . import keywords as kw
from . import tooling
from .widgets import MONO_CSS, STATUS_COLOUR, TABLE_CSS, button, head

DASH = "-"          # "leave it to motion detection"


def _combo(options, value) -> QComboBox:
    c = QComboBox()
    c.addItems([DASH] + list(options))
    c.setCurrentText(value or DASH)
    return c


def _pick(combo: QComboBox) -> str | None:
    return None if combo.currentText() == DASH else combo.currentText()


def reading_text(comment: str, table: list[dict]) -> str:
    """What the importer makes of one comment (the 'test a comment' box)."""
    r = tooling.read_comment(comment, table)
    ins = r.insert
    rows = (
        ("KEYWORDS", ", ".join(m.keyword for m in r.matches) or "none matched"),
        ("INSERT", f"{ins.code} · {ins.system} · {ins.shape_name}" if ins else "no insert code"),
        ("TOOL TYPE", r.tool_type or "- (left to motion detection)"),
        ("OPERATIONS", ", ".join(r.ops) or "- (left to motion detection)"),
        ("NOSE RADIUS", f"{r.nose_radius:.4f}" if r.nose_radius is not None else "not given"),
        ("SIZE", f"{r.size.text} = {r.size.value:.4f}"
                 + (f", pitch {r.size.pitch:.4f}" if r.size.pitch else "") if r.size else "none"),
    )
    return "\n".join(f"{k:<12} {v}" for k, v in rows)


class KeywordsDialog(QDialog):
    def __init__(self, parent, path, table: list[dict]):
        super().__init__(parent)
        self.path = path
        self.rows = [dict(r) for r in table]
        self.setWindowTitle("Settings · Keywords")
        self.resize(760, 640)
        self.setStyleSheet(f"QDialog{{background:{theme.BG};}} QLabel{{color:{theme.FG};}}")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 10)
        v.setSpacing(8)
        v.addWidget(head("Keywords · longest match wins · whole words · any case"))

        add = QHBoxLayout()
        self.new_key = QLineEdit()
        self.new_key.setPlaceholderText("new keyword")
        self.new_tool, self.new_op = _combo(kw.all_tool_types(), None), _combo(kw.KEYWORD_OPS, None)
        self.add_btn = button("ADD", ok=True)
        for label, w in (("KEYWORD", self.new_key), ("TOOL TYPE", self.new_tool), ("OPERATION", self.new_op)):
            add.addWidget(QLabel(label))
            add.addWidget(w, 1 if w is self.new_key else 0)
        add.addWidget(self.add_btn)
        v.addLayout(add)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(("KEYWORD", "TOOL TYPE IT SETS", "OPERATION IT SETS", "SOURCE", ""))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setStyleSheet(TABLE_CSS)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        v.addWidget(self.table, 1)

        v.addWidget(head("Test a comment"))
        self.test = QLineEdit()
        self.test.setPlaceholderText("paste a comment, e.g.  OD ROUGH CNMG 432")
        v.addWidget(self.test)
        self.result = QLabel("")
        self.result.setStyleSheet(f"{MONO_CSS}font-size:12px;color:{theme.FG};border:1px solid {theme.LINE};"
                                  f"padding:6px;background:{theme.PANEL};")
        v.addWidget(self.result)

        foot = QHBoxLayout()
        self.where = QLabel(str(path))
        self.where.setStyleSheet(f"color:{theme.FG3};font-size:10px;")
        foot.addWidget(self.where, 1)
        restore, close = button("RESTORE DEFAULTS"), button("CLOSE")
        foot.addWidget(restore)
        foot.addWidget(close)
        v.addLayout(foot)

        self.add_btn.clicked.connect(self.add_row)
        self.new_key.returnPressed.connect(self.add_row)
        self.test.textChanged.connect(self.run_test)
        restore.clicked.connect(self.restore)
        close.clicked.connect(self.accept)
        self.fill()
        self.run_test()

    def fill(self):
        self.table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            self.table.setItem(r, 0, QTableWidgetItem(row["keyword"]))
            tool, op = _combo(kw.all_tool_types(), row["tool"]), _combo(kw.KEYWORD_OPS, row["op"])
            tool.currentTextChanged.connect(lambda _t, r=r, c=tool: self.edit(r, "tool", _pick(c)))
            op.currentTextChanged.connect(lambda _t, r=r, c=op: self.edit(r, "op", _pick(c)))
            self.table.setCellWidget(r, 1, tool)
            self.table.setCellWidget(r, 2, op)
            src = QTableWidgetItem(row["source"])
            src.setForeground(QColor(STATUS_COLOUR[row["source"]]))
            self.table.setItem(r, 3, src)
            rm = button("DELETE")
            rm.clicked.connect(lambda _=False, key=row["keyword"]: self.delete(key))
            self.table.setCellWidget(r, 4, rm)

    def commit(self):
        kw.save(self.path, self.rows)
        self.run_test()

    def add_row(self):
        key = kw.clean(self.new_key.text())
        if not key:
            return
        self.rows = kw.add(self.rows, key, _pick(self.new_tool), _pick(self.new_op), "USER")
        self.new_key.clear()
        self.fill()
        self.commit()

    def edit(self, r: int, field: str, value):
        self.rows[r][field] = value
        self.rows[r]["source"] = "USER"             # an edited default is now the user's
        item = self.table.item(r, 3)
        item.setText("USER")
        item.setForeground(QColor(STATUS_COLOUR["USER"]))
        self.commit()

    def delete(self, keyword: str):
        self.rows = [r for r in self.rows if r["keyword"] != keyword]
        self.fill()
        self.commit()

    def restore(self):
        """Put back any default that was deleted or edited; user keywords stay."""
        mine = [r for r in self.rows if r["source"] == "USER"]
        names = {d["keyword"] for d in kw.defaults()}
        self.rows = [r for r in mine if r["keyword"] not in names] + kw.defaults()
        self.fill()
        self.commit()

    def run_test(self):
        text = self.test.text().strip()
        self.result.setText(reading_text(text, self.rows) if text else "Type a comment above to see how it is read.")
