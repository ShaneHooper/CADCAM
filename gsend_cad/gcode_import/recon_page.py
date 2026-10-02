"""Step 4 RECONSTRUCT: the part the program cuts, exact and assumed edges, warnings and checks."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from ..ui import theme
from .preview import Preview
from .stock import stock_z_range
from .widgets import MONO_CSS, head, toggle


def profile_summary(rec, needs_type: int = 0) -> str:
    if not rec.ok:
        return f"NO PROFILE: {rec.error}"
    rows = [
        ("OUTLINE", f"{len(rec.edges)} segments  (fitted to lines and arcs in Step 5)"),
        ("EXACT / ASSUMED", f"{rec.count('EXACT')} exact, {rec.count('ASSUMED')} assumed in {rec.assumed_runs} "
                            f"stretch{'es' if rec.assumed_runs != 1 else ''}, {rec.count('STOCK')} uncut stock"),
        ("MAX Ø", f"{rec.max_dia:.4f}"),
        ("LENGTH", f"{rec.length:.4f}   (Z{rec.z_min:.4f} to Z{rec.z_max:.4f})"),
        ("BORE", f"Ø{rec.bore:.4f}" if rec.bore else "none (solid at the front)"),
        ("THREADS", rec.threads[0].callout if rec.threads else "none"),
    ]
    rows += [("", t.callout) for t in rec.threads[1:]]
    rows.append(("NEED A TYPE", f"{needs_type} operation{'s' if needs_type != 1 else ''}"))
    return "\n".join(f"{k:<16} {v}" for k, v in rows)


def notes_text(rec) -> str:
    lines = [f"LINE {f.line:<5} {f.text}" if f.line else f.text for f in rec.flags]
    lines += rec.checks
    return "\n\n".join(lines) if lines else "No warnings."


class ReconPage(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wiz = wizard
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.preview = Preview()
        row.addWidget(self.preview, 1)

        box = QFrame()
        box.setFixedWidth(430)
        box.setStyleSheet(f"QFrame{{background:{theme.PANEL};border:1px solid {theme.LINE};}} QLabel{{border:0;}}")
        col = QVBoxLayout(box)
        col.setContentsMargins(12, 6, 12, 10)
        col.setSpacing(6)
        col.addWidget(head("Programmed point"))
        prow = QHBoxLayout()
        self.tip_btn, self.centre_btn = toggle("IMAGINARY TIP"), toggle("NOSE CENTER")
        self.tip_btn.setChecked(True)
        self.tip_btn.clicked.connect(lambda: self.set_nose_center(False))
        self.centre_btn.clicked.connect(lambda: self.set_nose_center(True))
        prow.addWidget(self.tip_btn)
        prow.addWidget(self.centre_btn)
        prow.addStretch()
        col.addLayout(prow)
        hint = QLabel("What the program's X / Z point at when cutter comp is off. With G41 / G42 active the "
                      "programmed path is the finished contour either way.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{theme.FG3};font-size:11px;")
        col.addWidget(hint)
        self.show_path = QCheckBox("SHOW TOOLPATH")
        self.show_path.toggled.connect(self.set_toolpath)
        col.addWidget(self.show_path)

        col.addWidget(head("Profile"))
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(f"{MONO_CSS}font-size:11px;color:{theme.FG};")
        col.addWidget(self.summary)
        self.notes_head = head("Warnings and checks")
        col.addWidget(self.notes_head)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setStyleSheet(f"{MONO_CSS}font-size:11px;background:{theme.BG};color:{theme.FG};"
                                 f"border:1px solid {theme.LINE};")
        col.addWidget(self.notes, 1)
        nxt = QLabel("SKETCH + REVOLVED SOLID: NOT BUILT YET (PHASE 5)")
        nxt.setStyleSheet(f"color:{theme.FG3};font-family:'{theme.HEAD[0]}';letter-spacing:1px;")
        col.addWidget(nxt)
        row.addWidget(box)

    def set_nose_center(self, on: bool):
        self.tip_btn.setChecked(not on)
        self.centre_btn.setChecked(on)
        if self.wiz.nose_center != on:
            self.wiz.nose_center = on
            self.wiz.ops_page.reload()                  # re-runs the reconstruction and every preview

    def set_toolpath(self, on: bool):
        self.preview.show_toolpath = on
        self.preview.update()

    def reload(self):
        wiz = self.wiz
        rec = wiz.reconstruction()
        s = wiz.settings()
        zb, zf = stock_z_range(s["z0"], s["length"], s["front"])
        self.preview.show_toolpath = self.show_path.isChecked()
        self.preview.show_setup(wiz.program.moves, (zb, zf, s["od"], s["id"]),
                                "" if rec.ok else f"NO PROFILE\n{rec.error}", profile=rec.edges if rec.ok else None)
        needs = sum(1 for o in wiz.ops_page.ops if o.confidence == "NEEDS TYPE")
        self.summary.setText(profile_summary(rec, needs))
        self.notes.setPlainText(notes_text(rec) if rec.ok else rec.error)
        n = len(rec.flags) if rec.ok else 0
        self.notes_head.setText(f"WARNINGS AND CHECKS · {n} WARNING{'S' if n != 1 else ''}")
