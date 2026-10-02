"""Step 4 RECONSTRUCT: the part the program cuts, exact and assumed edges, warnings and checks."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QVBoxLayout,
                               QWidget)

from ..core import Document
from ..ui import theme
from .build import BuildError, add_to_document
from .build import build as build_profile
from .fit import fit_outline
from .preview import Preview
from .stock import stock_z_range
from .widgets import MONO_CSS, button, head, toggle


def fit_text(fit) -> str:
    return (f"{len(fit.segs)} segments: {fit.lines} lines, {fit.arcs} arcs  "
            f"(fit within {fit.max_dev:.5f}, tolerance {fit.tol})")


def profile_summary(rec, needs_type: int = 0) -> str:
    if not rec.ok:
        return f"NO PROFILE: {rec.error}"
    fit = fit_outline(rec.edges)
    rows = [
        ("OUTLINE", f"{len(rec.edges)} raw edges -> {fit_text(fit)}"),
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
        col.addWidget(head("Build"))
        wrow = QHBoxLayout()
        self.new_btn, self.here_btn = toggle("NEW PART"), toggle("ADD TO THIS PART")
        self.new_btn.setChecked(True)
        self.new_btn.clicked.connect(lambda: self.set_target(True))
        self.here_btn.clicked.connect(lambda: self.set_target(False))
        wrow.addWidget(self.new_btn)
        wrow.addWidget(self.here_btn)
        wrow.addStretch()
        col.addLayout(wrow)
        bhint = QLabel("Makes a sketch of the fitted lines and arcs, a hidden locked copy of the raw outline, and "
                       "a 360 degree revolve about the spindle. The finished front face is Z0.")
        bhint.setWordWrap(True)
        bhint.setStyleSheet(f"color:{theme.FG3};font-size:11px;")
        col.addWidget(bhint)
        self.build_btn = button("BUILD SKETCH + REVOLVED SOLID", ok=True)
        self.build_btn.clicked.connect(self.build)
        col.addWidget(self.build_btn)
        row.addWidget(box)

    def set_target(self, new_part: bool):
        self.new_btn.setChecked(new_part)
        self.here_btn.setChecked(not new_part)

    def build(self):
        """Fit the profile, put the sketches and the revolve into the part, close the window."""
        wiz = self.wiz
        win = wiz.win
        rec = wiz.reconstruction()
        try:
            built = build_profile(rec)
            name = Path(wiz.path).stem
            if self.new_btn.isChecked():
                win.cancel_command()
                if not win._maybe_save():
                    return
                win._set_doc(Document(name), None)
            else:
                win._snapshot()
            ids = add_to_document(win.doc, built, name)
        except BuildError as exc:
            QMessageBox.warning(wiz, "Import G-code", f"The part could not be built:\n{exc}")
            return
        except Exception as exc:                        # never take the app down with the importer
            QMessageBox.warning(wiz, "Import G-code", f"The build stopped:\n{type(exc).__name__}: {exc}")
            return
        win.dirty = True
        win.rebuild(fit=True)
        win.document_changed.emit()
        errs = getattr(win, "model", None) and win.model.errors
        f = built.fit
        win.message(f"Imported {name}: {f.lines} lines and {f.arcs} arcs, {f.assumed} assumed, within "
                    f"{f.max_dev:.5f} of the program's cuts. The raw outline is kept hidden in "
                    f"'{name} reference'." + (f"  Kernel: {next(iter(errs.values()))}" if errs else ""))
        win.viewport.show_toast(f"Built {name}")
        wiz.accept()

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
        self.build_btn.setEnabled(bool(rec.ok))
        self.summary.setText(profile_summary(rec, needs))
        self.notes.setPlainText(notes_text(rec) if rec.ok else rec.error)
        n = len(rec.flags) if rec.ok else 0
        self.notes_head.setText(f"WARNINGS AND CHECKS · {n} WARNING{'S' if n != 1 else ''}")
