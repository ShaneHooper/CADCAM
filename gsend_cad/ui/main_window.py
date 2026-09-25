"""Main window: wires the Document, the Kernel and the panels together."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QGridLayout, QMainWindow, QMessageBox, QWidget

from .. import APP_NAME
from ..core import Document, bracket_plate
from ..kernel import Kernel
from . import theme
from .commands import ExtrudeSession, SketchSession, regions_for
from .panels import Browser, Ribbon, StatusBar, Timeline, TopBar

FILE_FILTER = f"{APP_NAME} (*.gcad);;All files (*)"
DEFAULT_MSG = "Left drag: orbit · Right drag: pan · Wheel: zoom · Click a feature in the timeline to roll back"


class MainWindow(QMainWindow):
    document_changed = Signal()      # for a host app (G-SEND.IO) that wants to follow edits

    def __init__(self, doc: Document | None = None, fonts=None):
        super().__init__()
        from .viewport import Viewport   # imported late so core/kernel users never need Qt/VTK
        self.doc = doc or bracket_plate()
        self.kernel = Kernel()
        self.model = None
        self.path: Path | None = None
        self.dirty = False
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self.selected = "body1"
        self.paint_sel = False           # like the prototype: highlight only after a click
        self.session = None
        fonts = fonts or {"g": "DejaVu Sans", "wm": "DejaVu Sans"}

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(theme.app_icon())
        self.resize(1400, 820)
        central = QWidget()
        central.setObjectName("central")
        g = QGridLayout(central)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(0)
        self.topbar = TopBar(fonts)
        self.ribbon = Ribbon()
        self.browser = Browser()
        self.viewport = Viewport()
        self.status = StatusBar()
        self.timeline = Timeline()
        g.addWidget(self.topbar, 0, 0, 1, 2)
        g.addWidget(self.ribbon, 1, 0, 1, 2)
        g.addWidget(self.browser, 2, 0)
        g.addWidget(self.viewport, 2, 1)
        g.addWidget(self.status, 3, 0, 1, 2)
        g.addWidget(self.timeline, 4, 0, 1, 2)
        g.setRowStretch(2, 1)
        g.setColumnStretch(1, 1)
        self.setCentralWidget(central)

        self.ribbon.tool.connect(self.run_tool)
        self.ribbon.tab_changed.connect(self.select_tab)
        self.browser.selected.connect(self.select_node)
        self.timeline.roll.connect(self.roll_to)
        self.timeline.play.connect(self.play)
        self.timeline.delete.connect(self.delete_feature)
        self.timeline.edit.connect(lambda i: self.edit_sketch(self.doc.features[i]["id"]))
        self.timeline.toggle.connect(lambda i: self.toggle_sketch(self.doc.features[i]["id"]))
        self.browser.edit.connect(self.edit_sketch)
        self.browser.toggle.connect(self.toggle_sketch)
        self.topbar.docs.connect(self.show_docs)
        self.topbar.about.connect(self.show_about)
        docs = QAction("Documentation", self, shortcut=QKeySequence(Qt.Key_F1),
                       shortcutContext=Qt.ApplicationShortcut, triggered=self.show_docs)
        self.addAction(docs)
        self.docs = None
        self.topbar.save.connect(self.save)
        self.topbar.open.connect(self.open)
        self.topbar.undo.connect(self.undo)
        self.topbar.redo.connect(self.redo)
        self.viewport.cursor.connect(self.status.set_coord)
        self.viewport.key_cb = self.handle_key
        nb = self.viewport.nav_buttons
        nb["fit"].clicked.connect(lambda: self.viewport.set_view("home"))
        nb["disp"].clicked.connect(self.cycle_display)
        for k in ("orbit", "view", "pan", "zoom"):
            nb[k].clicked.connect(lambda _=False, k=k: self.message(f"{k.upper()}: left drag orbits, right drag pans, wheel zooms"))
        self.message(DEFAULT_MSG)
        self.rebuild()

    # ---------------------------------------------------------- model / view sync
    def rebuild(self, fit=False):
        self.model = self.kernel.build(self.doc)
        sel = self.selected if self.paint_sel else None
        self.viewport.show_bodies(self.model.bodies, sel)
        self.draw_sketches()
        self.refresh_tree()
        self.refresh_props()
        idx = {f["id"]: i for i, f in enumerate(self.doc.features)}
        errs = {idx[k]: v for k, v in self.model.errors.items() if k in idx}
        consumed = self.doc.consumed_sketches()
        hidden = [i for i, f in enumerate(self.doc.features)
                  if f["kind"] == "sketch" and not self.doc.sketch_shown(f, consumed)]
        self.timeline.set_features([(f["name"], f["kind"], self.doc.describe(f)) for f in self.doc.features],
                                   self.doc.marker, errs, hidden)
        self.topbar.set_doc(self.doc.name, self.dirty)
        if fit:
            self.viewport.set_view("home")

    def draw_sketches(self):
        vp = self.viewport
        vp.clear("sketches", render=False)
        consumed = self.doc.consumed_sketches()
        show_all = isinstance(self.session, ExtrudeSession)
        editing = getattr(self.session, "edit_id", None)    # that sketch is drawn by the session
        from ..core import sketch as sk
        for f in self.doc.applied():
            if f["kind"] == "sketch" and f["id"] != editing and f.get("show") is not False \
                    and (show_all or self.doc.sketch_shown(f, consumed)):
                z = f["plane_z"] + 0.004
                vp.add_lines("sketches", [[(x, y, z) for x, y in sk.entity_points(e)] for e in f["ents"]])
        vp.render()

    def refresh_tree(self):
        n = self.doc.marker
        have = {b.id for b in self.model.bodies}
        full = self.kernel.build(self.doc, upto=len(self.doc.features))   # cached; lists bodies made later too
        names = {b.id: b.name for b in full.bodies}
        names.update({b.id: b.name for b in self.model.bodies})
        bodies = [(bid, name, bid in have) for bid, name in sorted(names.items(), key=lambda kv: int(kv[0][4:]))]
        if not bodies:
            bodies = [("body1", "Body1", False)]
        consumed = self.doc.consumed_sketches()
        sketches = [(f["id"], f["name"], i < n and self.doc.sketch_shown(f, consumed), len(f["ents"]),
                     self.doc.sketch_shown(f, consumed))
                    for i, f in enumerate(self.doc.features) if f["kind"] == "sketch"]
        editing = None
        if isinstance(self.session, SketchSession):
            editing = (self.session.name, len(self.session.ents), self.session.edit_id)
        self.browser.set_rows(self.doc.name, bodies, sketches, self.selected, editing)

    def refresh_props(self):
        b = self.model.body(self.selected) or (self.model.bodies[0] if self.model.bodies else None)
        n, tot = self.doc.marker, len(self.doc.features)
        if b is None:
            rows = {"BODY": "—", "MATERIAL": self.doc.material, "BBOX X": "0.000 in", "BBOX Y": "0.000 in",
                    "BBOX Z": "0.000 in", "VOLUME": "0.000 in³", "MASS": "0.000 lb"}
        else:
            sx, sy, sz = b.size()
            rows = {"BODY": b.name, "MATERIAL": self.doc.material, "BBOX X": f"{sx:.3f} in", "BBOX Y": f"{sy:.3f} in",
                    "BBOX Z": f"{sz:.3f} in", "VOLUME": f"{b.volume:.3f} in³", "MASS": f"{b.mass(self.doc.material):.3f} lb"}
        rows["FEATURES"] = f"{n} / {tot}"
        self.browser.set_props(rows)

    def message(self, text: str):
        self.status.msg.setText(text)

    def not_built(self, label: str):
        self.viewport.show_toast(f"{label} · not in this build yet")
        self.message(f"{label} is on the list. Working now: Sketch (L), Extrude (E), timeline rollback, "
                     "Export STEP / STL (Utilities).")

    # ---------------------------------------------------------- edits (undoable)
    def _snapshot(self):
        self.undo_stack.append(self.doc.to_dict())
        self.redo_stack.clear()
        self.dirty = True

    def _restore(self, d: dict):
        self.doc = Document.from_dict(d)
        self.dirty = True
        self.rebuild()
        self.document_changed.emit()

    def undo(self):
        if self.session:
            if isinstance(self.session, SketchSession):
                self.session.undo()
            return
        if not self.undo_stack:
            self.viewport.show_toast("Nothing to undo")
            return
        self.redo_stack.append(self.doc.to_dict())
        self._restore(self.undo_stack.pop())
        self.message("Undo")

    def redo(self):
        if self.session or not self.redo_stack:
            return
        self.undo_stack.append(self.doc.to_dict())
        self._restore(self.redo_stack.pop())
        self.message("Redo")

    def delete_feature(self, i: int):
        self.cancel_command()
        f = self.doc.features[i]
        self._snapshot()
        del self.doc.features[i]
        if self.doc.marker > i:
            self.doc.marker -= 1
        self.rebuild()
        self.document_changed.emit()
        self.message(f"{f['name']} deleted. Ctrl+Z brings it back.")

    # ---------------------------------------------------------- timeline
    def roll_to(self, n: int):
        self.cancel_command()
        self.doc.set_marker(n)
        self.rebuild()
        if 0 < self.doc.marker <= len(self.doc.features):
            f = self.doc.features[self.doc.marker - 1]
            self.message(f"Rolled to {f['name']}: {self.doc.describe(f)}")

    def play(self):
        self.cancel_command()
        steps = iter(range(len(self.doc.features) + 1))

        def tick():
            try:
                self.doc.set_marker(next(steps))
                self.rebuild()
            except StopIteration:
                t.stop()
        t = QTimer(self, interval=450, timeout=tick)
        tick()
        t.start()

    # ---------------------------------------------------------- tools
    def select_tab(self, key):
        if isinstance(self.session, SketchSession) and key != "sketch":
            self.viewport.show_toast("Finish the sketch first")
            return
        self.ribbon.show_tab(key)

    def run_tool(self, label: str):
        if self.session is not None:
            self.session.ribbon_tool(label)
            return
        self.ribbon.set_active(None)
        if label == "Sketch":
            self.start_sketch()
        elif label == "Extrude":
            self.start_extrude()
        elif label == "Export":
            self.export("step")
        elif label == "3D Print":
            self.export("stl")
        else:
            self.not_built(label)

    def cancel_command(self):
        s, self.session = self.session, None
        if s is None:
            return
        s.close()
        self.viewport.handler = None
        self.viewport.set_side(None)
        self.ribbon.set_active(None)
        if isinstance(s, SketchSession):
            self.ribbon.show_sketch_tab(False)
            self.viewport.set_parallel(False)
            self.viewport.plane_z = 0.0
            self.viewport.set_view("home")
        self.status.sel.setText("SEL: —")
        self.message(DEFAULT_MSG)
        self.rebuild()

    # sketch
    def start_sketch(self, edit_id: str | None = None):
        if edit_id:
            f = self.doc.feature(edit_id)
            self.session = SketchSession(self, f["name"], f["plane_z"], f["ents"], edit_id)
        else:
            n = sum(1 for f in self.doc.features if f["kind"] == "sketch") + 1
            self.session = SketchSession(self, f"Sketch{n}")
        vp = self.viewport
        vp.handler = self.session
        vp.set_view("top")
        vp.set_parallel(True)
        vp.hud_view.setText("TOP · SKETCH")
        self.ribbon.show_sketch_tab(True)
        vp.set_side(self.session.palette)
        self.session.set_tool("Line")
        self.draw_sketches()
        self.refresh_tree()
        if edit_id:
            self.message(f"Editing {self.session.name}: draw to add, × in the palette deletes a shape, "
                         "Plane moves it. Enter / Finish Sketch saves, Cancel throws the changes away.")

    def toggle_sketch(self, fid: str):
        """Hide or show a sketch (Browser eye dot, or right-click → Hide / Show Sketch)."""
        f = self.doc.feature(fid)
        if isinstance(self.session, SketchSession) and self.session.edit_id == fid:
            self.viewport.show_toast("Finish editing the sketch first")
            return
        self._snapshot()
        f["show"] = not self.doc.sketch_shown(f)
        if isinstance(self.session, ExtrudeSession):   # hidden sketches can't be picked; close the picker
            self.cancel_command()
        self.rebuild()
        self.document_changed.emit()
        self.message(f"{f['name']} {'shown' if f['show'] else 'hidden'}. "
                     + ("" if f["show"] else "Show it again from the Browser or the timeline (right-click)."))

    def edit_sketch(self, fid: str):
        """Reopen a sketch that is already in the timeline (right-click it → Edit Sketch)."""
        try:
            f = self.doc.feature(fid)
        except KeyError:
            return
        if f["kind"] != "sketch":
            return
        self.cancel_command()
        self.ribbon.set_active(None)
        self.start_sketch(edit_id=fid)

    def finish_sketch(self):
        s = self.session
        if not isinstance(s, SketchSession):
            return
        ents, z = list(s.ents), s.plane_z
        if s.edit_id:
            if not ents:
                self.viewport.show_toast("A sketch needs at least one shape", bad=True)
                self.message("To remove the whole sketch, finish or cancel, then right-click it in the timeline → Delete.")
                return
            self.cancel_command()
            if s.changed():
                self._snapshot()
                self.doc.update_sketch(s.edit_id, ents, z, s.origin)
                self.rebuild()
                self.document_changed.emit()
                self._report_edit(s.edit_id)
            else:
                self.message(f"{s.name}: no changes")
            return
        self.cancel_command()
        if not ents:
            self.viewport.show_toast("Empty sketch discarded")
            return
        self._snapshot()
        f = self.doc.add_sketch(ents, plane_z=z)
        self.rebuild()
        self.document_changed.emit()
        self.viewport.show_toast(f"{f['name']} added · {len(ents)} entities")
        self.message(f"{f['name']} saved to the timeline. Press E to extrude its closed profiles.")

    def _report_edit(self, fid: str):
        name = self.doc.feature(fid)["name"]
        users = [g for g in self.doc.features if g["kind"] == "extrude" and any(p["sketch"] == fid for p in g["profiles"])]
        broken = [g["name"] for g in users if g["id"] in self.kernel.build(self.doc, len(self.doc.features)).errors]
        if broken:
            self.viewport.show_toast(f"{name} updated · {', '.join(broken)} lost its profile", bad=True)
            self.message(f"{', '.join(broken)} used a shape you deleted (red in the timeline). "
                         "Ctrl+Z undoes the edit, or delete that extrude and extrude again.")
        else:
            rebuilt = f" · {', '.join(g['name'] for g in users)} rebuilt" if users else ""
            self.viewport.show_toast(f"{name} updated{rebuilt}")
            self.message(f"{name} updated{rebuilt}. New closed shapes can be extruded with E.")

    # extrude
    def start_extrude(self):
        regions, planes = regions_for(self.doc)
        if not regions:
            self.viewport.show_toast("No closed profiles · press L to sketch", bad=True)
            self.message("Extrude needs a closed profile: rectangle, circle, polygon, or a line chain that closes.")
            return
        self.session = ExtrudeSession(self, regions, planes)
        self.viewport.handler = self.session
        self.viewport.set_side(self.session.panel)
        self.ribbon.set_active("Extrude")
        self.draw_sketches()

    def commit_extrude(self, f: dict):
        self.cancel_command()
        self._snapshot()
        feat = self.doc.add_extrude(f["profiles"], f["distance"], op=f["op"], direction=f["direction"])
        self.rebuild()
        self.document_changed.emit()
        err = self.model.errors.get(feat["id"])
        if err:
            self.viewport.show_toast(err, bad=True)
            self.message(err + " · Ctrl+Z to undo")
        else:
            self.viewport.show_toast(f"{feat['name']} · {self.doc.describe(feat)}")
            self.message(f"{feat['name']} added to the timeline. Roll back to compare.")

    # ---------------------------------------------------------- help
    def show_docs(self):
        from .docs import DocsWindow
        if self.docs is None:
            self.docs = DocsWindow(self)
        self.docs.show()
        self.docs.raise_()
        self.docs.activateWindow()

    def show_about(self):
        from .. import __version__
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<b>{APP_NAME}</b> {__version__}<br>Test build (Rev 1).<br><br>"
                          "Sketch, extrude and export parts for G-SEND.IO.<br>Help → Documentation (F1) explains how.")

    # ---------------------------------------------------------- misc actions
    def select_node(self, nid: str):
        if nid.startswith("body"):
            self.selected = nid
            self.paint_sel = True
            self.viewport.show_bodies(self.model.bodies, nid)
            self.refresh_props()
        self.status.sel.setText("SEL: " + (nid.upper() if nid else "—"))

    def cycle_display(self):
        self.viewport.cycle_display()
        self.viewport.show_bodies(self.model.bodies, self.selected if self.paint_sel else None)

    def export(self, kind: str):
        if not self.model.bodies:
            self.viewport.show_toast("Nothing to export", bad=True)
            return
        ext = {"step": "STEP (*.step *.stp)", "stl": "STL (*.stl)"}[kind]
        path, _ = QFileDialog.getSaveFileName(self, f"Export {kind.upper()}", f"{self.doc.name}.{kind}", ext)
        if not path:
            return
        if kind == "step":
            self.model.export_step(path)
        else:
            from build123d import export_stl
            shape = self.model.bodies[0].shape
            for b in self.model.bodies[1:]:
                shape = shape + b.shape
            export_stl(shape, path)
        self.viewport.show_toast(f"Exported {Path(path).name}")

    def save(self):
        path = self.path
        if path is None:
            p, _ = QFileDialog.getSaveFileName(self, "Save", f"{self.doc.name}.gcad", FILE_FILTER)
            if not p:
                return
            path = Path(p)
        self.doc.save(path)
        self.path, self.dirty = path, False
        self.topbar.set_doc(self.doc.name, False)
        self.viewport.show_toast(f"Saved {path.name}")

    def open(self, path=None):
        if path is None:
            p, _ = QFileDialog.getOpenFileName(self, "Open", "", FILE_FILTER)
            if not p:
                return
            path = p
        try:
            doc = Document.load(path)
        except Exception as exc:
            QMessageBox.warning(self, "Open", f"Could not open {path}:\n{exc}")
            return
        self.cancel_command()
        self.doc, self.path, self.dirty = doc, Path(path), False
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.rebuild(fit=True)
        self.document_changed.emit()

    # ---------------------------------------------------------- keys (like Fusion)
    def handle_key(self, ev):
        if self.session is not None and self.session.on_key(ev):
            return
        k, mod = ev.key(), ev.modifiers()
        ctrl = bool(mod & Qt.ControlModifier)
        if ctrl and k == Qt.Key_S:
            self.save()
        elif ctrl and k == Qt.Key_O:
            self.open()
        elif ctrl and k == Qt.Key_Z:
            self.undo()
        elif ctrl and k == Qt.Key_Y:
            self.redo()
        elif k == Qt.Key_F1:
            self.show_docs()
        elif self.session is not None:
            return
        elif k == Qt.Key_L:
            self.start_sketch()
        elif k == Qt.Key_E:
            self.start_extrude()
        elif k == Qt.Key_Home:
            self.viewport.set_view("home")
        elif k in (Qt.Key_H, Qt.Key_F, Qt.Key_I):
            self.not_built({Qt.Key_H: "Hole", Qt.Key_F: "Fillet", Qt.Key_I: "Measure"}[k])

    def keyPressEvent(self, ev):
        self.handle_key(ev)

    def closeEvent(self, ev):
        if self.dirty and self.isVisible():
            r = QMessageBox.question(self, APP_NAME, "Save changes before closing?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                ev.ignore()
                return
            if r == QMessageBox.Save:
                self.save()
        self.viewport.plotter.close()
        super().closeEvent(ev)
