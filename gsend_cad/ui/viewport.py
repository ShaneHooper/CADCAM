"""3D viewport: pyvista/VTK inside Qt, Z-up like Fusion, plus the prototype's overlays
(HUD, view cube, nav bar, toast, sketch banner, live dimension tag)."""
from __future__ import annotations

import math
from functools import partial

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkRenderingCore import vtkBillboardTextActor3D, vtkCellPicker, vtkMapper, vtkRenderer

from ..core import plane as pl
from . import icons, theme

VIEWS = {"home": (6, -7, 5), "top": (0, 0, 10), "front": (0, -10, 0), "left": (-10, 0, 0), "right": (10, 0, 0),
         "iso-tl": (-6, -7, 5), "iso-tr": (6, -7, 5), "iso-bl": (-6, 7, 5), "iso-br": (6, 7, 5)}
DISPLAY_MODES = ["SHADED + EDGES", "SHADED", "WIREFRAME"]
# Settings → View projection (like Fusion's camera options)
PROJECTIONS = {"ortho": "Orthographic", "persp": "Perspective", "persp-ortho-faces": "Perspective with ortho faces"}
FACE_VIEWS = ("top", "front", "left", "right")


def polyline_mesh(lines) -> pv.PolyData:
    """Many polylines (each an Nx3 array) as one PolyData."""
    pts, cells, off = [], [], 0
    for ln in lines:
        ln = np.asarray(ln, float)
        if len(ln) < 2:
            continue
        pts.append(ln)
        cells.append(np.r_[len(ln), np.arange(off, off + len(ln))])
        off += len(ln)
    if not pts:
        return pv.PolyData()
    return pv.PolyData(np.vstack(pts), lines=np.concatenate(cells))


class Viewport(QWidget):
    cursor = Signal(float, float, float)     # world XY on the active plane

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("view")
        self.handler = None                  # sketch / extrude session receiving mouse events
        self.key_cb = None                   # the main window's key handler
        self.frame = pl.xy(0.0)              # the sketch plane mouse rays are read on (core.plane)
        self.display_mode = 0
        self.projection = "ortho"            # Settings → View projection
        self._face_view = False              # looking straight at TOP / FRONT / LEFT / RIGHT
        self._forced_parallel = False        # sketch mode always looks straight down
        self._groups: dict[str, list] = {}
        self._body_actors: list = []
        self._press = None
        self._right_taken = False            # a right-click a session handled: swallow its release too

        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.plotter = QtInteractor(self)
        lay.addWidget(self.plotter, 0, 0)
        p = self.plotter
        p.set_background(theme.BG)
        p.enable_anti_aliasing("ssaa") if hasattr(p, "enable_anti_aliasing") else None
        vtkMapper.SetResolveCoincidentTopologyToPolygonOffset()
        p.renderer.remove_all_lights()
        p.add_light(pv.Light(light_type="headlight", intensity=0.55))
        p.add_light(pv.Light(position=(5, 8, 6), focal_point=(0, 0, 0), intensity=0.55))
        p.add_light(pv.Light(position=(-6, 2, -4), focal_point=(0, 0, 0), color=theme.ACCENT, intensity=0.15))
        p.camera.view_angle = 35
        # overlay layer: sketches, profile fills and previews draw on top of the solid
        rw = p.render_window
        rw.SetNumberOfLayers(2)
        self.top = vtkRenderer()
        self.top.SetLayer(1)
        self.top.SetActiveCamera(p.renderer.GetActiveCamera())
        self.top.InteractiveOff()
        rw.AddRenderer(self.top)
        # left drag orbit, right drag pan, wheel zoom (the prototype's controls)
        style = vtkInteractorStyleTrackballCamera()
        style.AddObserver("RightButtonPressEvent", lambda o, e: o.StartPan())
        style.AddObserver("RightButtonReleaseEvent", lambda o, e: o.EndPan())
        # wheel button: drag pans; Shift + wheel button drag rotates freely (trackball, any direction)
        style.AddObserver("MiddleButtonPressEvent", self._middle_down)
        style.AddObserver("MiddleButtonReleaseEvent", self._middle_up)
        p.iren.interactor.SetInteractorStyle(style)
        self._build_grid()
        self.plotter.installEventFilter(self)
        self.plotter.setMouseTracking(True)
        self._build_overlays()
        self.set_view("home")

    # ---------- the sketch plane ----------
    @property
    def plane_z(self) -> float:
        """Height of the plane along its normal; setting it selects the XY plane at that height
        (how every caller spoke before a plane could be picked on the part)."""
        return pl.height(self.frame)

    @plane_z.setter
    def plane_z(self, z: float):
        self.frame = pl.xy(float(z))

    def set_frame(self, frame: dict):
        self.frame = frame

    def look_at(self, frame: dict, dist: float = 10.0):
        """Camera square on to a sketch plane: looking along -n with the plane's y up, so the
        sketch reads left-to-right and up the way core.plane laid its axes."""
        o, n, y = frame["origin"], frame["n"], frame["y"]
        self.plotter.camera_position = [tuple(a + b * dist for a, b in zip(o, n)), tuple(o), tuple(y)]
        self.plotter.camera.view_angle = 35
        self.plotter.renderer.ResetCameraClippingRange()
        self.plotter.render()

    def pick_world(self, pos: QPoint):
        """World point on a body under the mouse, or None (the grid is not pickable)."""
        picker = vtkCellPicker()
        picker.SetTolerance(0.0005)
        r = self.plotter.devicePixelRatioF()
        picker.Pick(pos.x() * r, (self.plotter.height() - pos.y()) * r, 0, self.plotter.renderer)
        if picker.GetActor() is None:
            return None
        return tuple(float(c) for c in picker.GetPickPosition())

    def _middle_down(self, style, _e):
        if style.GetInteractor().GetShiftKey():
            style.StartRotate()
        else:
            style.StartPan()

    @staticmethod
    def _middle_up(style, _e):
        style.EndRotate() if style.GetState() == 1 else style.EndPan()   # 1 = VTKIS_ROTATE

    # ---------- scene ----------
    def _build_grid(self):
        size, minor = 8, 0.25
        m1, m2 = [], []
        for i in np.arange(-size, size + 1e-9, minor):
            major = abs(i - round(i)) < 1e-6
            (m2 if major else m1).extend([[(i, -size, 0), (i, size, 0)], [(-size, i, 0), (size, i, 0)]])
        self.plotter.add_mesh(polyline_mesh(m1), color="#1f1f1f", line_width=1, pickable=False, lighting=False)
        self.plotter.add_mesh(polyline_mesh(m2), color="#333333", line_width=1, pickable=False, lighting=False)
        for d, c in (((1.5, 0, 0), theme.BAD), ((0, 1.5, 0), theme.OK), ((0, 0, 1.5), "#3b8cff")):
            self.plotter.add_mesh(polyline_mesh([[(0, 0, 0), d]]), color=c, line_width=1.5, lighting=False)

    def show_bodies(self, bodies, selected: str | None = None):
        """bodies: kernel Body objects. Rebuilds the solid actors."""
        for a in self._body_actors:
            self.plotter.remove_actor(a, render=False)
        self._body_actors = []
        wire = self.display_mode == 2
        for b in bodies:
            v, t = b.triangles()
            if not len(t):
                continue
            mesh = pv.PolyData(v, np.hstack([np.full((len(t), 1), 3), t]).ravel())
            sel = b.id == selected
            a = self.plotter.add_mesh(mesh, color=theme.ACCENT if sel else theme.BODY, smooth_shading=True,
                                      split_sharp_edges=True, feature_angle=30,
                                      style="wireframe" if wire else "surface", specular=0.3, specular_power=24,
                                      ambient=0.1 if not sel else 0.3, diffuse=0.6, render=False)
            self._body_actors.append(a)
            if self.display_mode != 1:
                e = self.plotter.add_mesh(polyline_mesh(b.edge_polylines()), color="#0a0a0a" if not wire else theme.BODY,
                                          line_width=1.2, lighting=False, render=False)
                self._body_actors.append(e)
        self.plotter.render()

    def clear(self, group: str, render=True):
        for a in self._groups.pop(group, []):
            self.top.RemoveActor(a)
        if render:
            self.plotter.render()

    def add_lines(self, group: str, lines, color=theme.ACCENT, width=1.6, opacity=1.0):
        mesh = polyline_mesh(lines)
        if mesh.n_points == 0:
            return
        actor = pv.Actor(mapper=pv.DataSetMapper(mesh))
        actor.prop.color = color
        actor.prop.line_width = width
        actor.prop.opacity = opacity
        actor.prop.lighting = False
        self.top.AddActor(actor)
        self._groups.setdefault(group, []).append(actor)

    def add_labels(self, group: str, items, color=theme.FG):
        """Screen-facing text at world points: items = [((x, y, z), text)]. Dimension values."""
        rgb = pv.Color(color).float_rgb
        bg = pv.Color(theme.BG).float_rgb
        for pos, text in items:
            a = vtkBillboardTextActor3D()
            a.SetInput(text)
            a.SetPosition(*pos)
            tp = a.GetTextProperty()
            tp.SetFontSize(13)
            tp.SetColor(*rgb)
            tp.SetBackgroundColor(*bg)
            tp.SetBackgroundOpacity(0.85)
            tp.SetJustificationToCentered()
            tp.SetVerticalJustificationToCentered()
            self.top.AddActor(a)
            self._groups.setdefault(group, []).append(a)

    def project(self, pts) -> np.ndarray:
        """World points (Nx3) -> Nx3 of (widget x px, widget y px, depth 0..1), all at once."""
        pts = np.asarray(pts, float).reshape(-1, 3)
        ren = self.plotter.renderer
        w, h = self.plotter.width(), self.plotter.height()
        m = ren.GetActiveCamera().GetCompositeProjectionTransformMatrix(w / max(h, 1), -1, 1)
        M = np.array([[m.GetElement(i, j) for j in range(4)] for i in range(4)])
        q = np.c_[pts, np.ones(len(pts))] @ M.T
        q = q[:, :3] / q[:, 3:4]
        return np.c_[(q[:, 0] + 1) / 2 * w, (1 - q[:, 1]) / 2 * h, (q[:, 2] + 1) / 2]

    def pixel_size(self, pos: QPoint) -> float:
        """World inches covered by one screen pixel on the active plane near `pos` (for picking)."""
        a, b = self.world_at(pos), self.world_at(pos + QPoint(10, 0))
        return float(np.hypot(b[0] - a[0], b[1] - a[1])) / 10 if a and b else 0.01

    def add_surface(self, group: str, mesh: pv.PolyData, color=theme.ACCENT, opacity=0.35, lit=True):
        actor = pv.Actor(mapper=pv.DataSetMapper(mesh))
        actor.prop.color = color
        actor.prop.opacity = opacity
        actor.prop.lighting = lit
        actor.prop.ambient = 0.4
        self.top.AddActor(actor)
        self._groups.setdefault(group, []).append(actor)
        return actor

    def render(self):
        self.plotter.render()

    # ---------- camera ----------
    def set_view(self, key: str, target=(0, 0, 0.25)):
        v = VIEWS.get(key, VIEWS["home"])
        up = (0, 1, 0) if key == "top" else (0, 0, 1)
        self.plotter.camera_position = [tuple(t + d for t, d in zip(target, v)), target, up]
        self.plotter.camera.view_angle = 35
        self._face_view = key in FACE_VIEWS
        self.apply_projection(render=False)
        self.plotter.renderer.ResetCameraClippingRange()   # tight near/far keeps depth precise
        self.hud_view.setText(key.upper().replace("-", " "))
        self.plotter.render()

    def set_projection(self, mode: str):
        """Settings → View projection: 'ortho', 'persp' or 'persp-ortho-faces'."""
        if mode in PROJECTIONS:
            self.projection = mode
            self.apply_projection()

    def apply_projection(self, render=True):
        cam = self.plotter.camera
        want = (self._forced_parallel or self.projection == "ortho"
                or (self.projection == "persp-ortho-faces" and self._face_view))
        if want and not cam.parallel_projection:
            # same framing as the perspective view: half-height = distance * tan(half the view angle)
            cam.parallel_scale = cam.distance * math.tan(math.radians(cam.view_angle / 2))
            self.plotter.enable_parallel_projection()
        elif not want and cam.parallel_projection:
            self.plotter.disable_parallel_projection()
        if render:
            self.plotter.render()

    def set_parallel(self, on: bool):
        """Sketch mode forces a straight (orthographic) look; off hands back to the setting."""
        self._forced_parallel = on
        self.apply_projection()

    def cycle_display(self):
        self.display_mode = (self.display_mode + 1) % 3
        self.hud_disp.setText(DISPLAY_MODES[self.display_mode])
        return self.display_mode

    def world_at(self, pos: QPoint, z: float | None = None, frame: dict | None = None):
        """Sketch (u, v) where the mouse ray meets the sketch plane: `frame`, else the XY plane
        at `z`, else the viewport's current plane. On the XY plane (u, v) is world (x, y)."""
        fr = pl.xy(z) if z is not None else (frame or self.frame)
        ren = self.plotter.renderer
        r = self.plotter.devicePixelRatioF()
        x, y = pos.x() * r, (self.plotter.height() - pos.y()) * r
        pts = []
        for d in (0.0, 1.0):
            ren.SetDisplayPoint(x, y, d)
            ren.DisplayToWorld()
            w = ren.GetWorldPoint()
            pts.append(np.array(w[:3]) / w[3])
        p0, p1 = pts
        n, o = np.array(fr["n"], float), np.array(fr["origin"], float)
        denom = float(np.dot(n, p1 - p0))
        if abs(denom) < 1e-12:
            return None
        t = float(np.dot(n, o - p0)) / denom
        if t < 0:
            return None
        hit = p0 + t * (p1 - p0)
        u, v = pl.to_local(fr, (float(hit[0]), float(hit[1]), float(hit[2])))
        return u, v

    # ---------- mouse routing ----------
    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.MouseMove:
            w = self.world_at(ev.position().toPoint())
            if w:
                self.cursor.emit(w[0], w[1], self.plane_z)
            if self.handler and w:
                self.handler.on_move(w, ev)
            return False
        if t == QEvent.MouseButtonPress and ev.button() == Qt.RightButton:
            # a session may claim a right-click (a dimension under it); otherwise VTK pans
            if self.handler is not None and hasattr(self.handler, "on_right_click"):
                w = self.world_at(ev.position().toPoint())
                if w and self.handler.on_right_click(w, ev):
                    self._right_taken = True
                    return True
            return False
        if t == QEvent.MouseButtonRelease and ev.button() == Qt.RightButton and self._right_taken:
            self._right_taken = False
            return True                      # VTK saw no press, so it must not see the release
        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick) and ev.button() == Qt.LeftButton:
            # a fast second click arrives as DblClick: it must count as a click, and VTK must
            # never see it (it starts an orbit whose release we swallow = stuck rotating)
            self._press = ev.position().toPoint()
            if self._face_view and not (self.handler and self.handler.captures_left):
                self._face_view = False              # orbiting off TOP / FRONT / ...: not a face view now
                self.apply_projection(render=False)
            if self.handler and self.handler.captures_left:
                w = self.world_at(self._press)
                if w:
                    self.handler.on_click(w, ev)
                return True          # no orbit while sketching
            return False
        if t == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
            p0, self._press = self._press, None
            if self.handler and self.handler.captures_left:
                self.plotter.iren.interactor.GetInteractorStyle().OnLeftButtonUp()   # never leave VTK orbiting
                return True
            if self.handler and p0 is not None and (ev.position().toPoint() - p0).manhattanLength() <= 4:
                w = self.world_at(ev.position().toPoint())
                if w:
                    self.handler.on_click(w, ev)   # a click, not an orbit drag
            return False
        if t in (QEvent.KeyPress, QEvent.ShortcutOverride):
            if t == QEvent.KeyPress and self.key_cb:
                self.key_cb(ev)
            return True              # VTK's own keys (q/e quit, w/s wireframe) stay off
        if t == QEvent.KeyRelease:
            return True
        if t == QEvent.Leave:
            self.dim.hide()
        return False

    # ---------- overlays ----------
    def _build_overlays(self):
        self.hud = QWidget(self)
        self.hud.setObjectName("hud")
        hl = QVBoxLayout(self.hud)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(3)
        self.hud_view, self.hud_grid, self.hud_disp = QLabel("HOME"), QLabel("0.250 in"), QLabel(DISPLAY_MODES[0])
        for k, v in (("VIEW", self.hud_view), ("GRID", self.hud_grid), ("DISPLAY", self.hud_disp)):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(6)
            kl = QLabel(k)
            kl.setStyleSheet(f"color:{theme.FG3}")
            v.setStyleSheet(f"color:{theme.FG}")
            rl.addWidget(kl)
            rl.addWidget(v)
            rl.addStretch()
            hl.addWidget(row)
        self.hud.move(10, 8)
        self.hud.resize(220, 56)

        self.cube = QWidget(self)
        self.cube.setObjectName("cube")
        cl = QGridLayout(self.cube)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        for i, (txt, key) in enumerate((("◤", "iso-tl"), ("TOP", "top"), ("◥", "iso-tr"), ("L", "left"), ("⌂", "home"),
                                        ("R", "right"), ("◣", "iso-bl"), ("FRT", "front"), ("◢", "iso-br"))):
            b = QPushButton(txt)
            b.setFixedSize(24, 24)
            if key == "home":
                b.setObjectName("home")
            b.clicked.connect(partial(self.cube_clicked, key))
            cl.addWidget(b, i // 3, i % 3)
        self.cube.resize(78, 78)

        self.navbar = QWidget(self)
        self.navbar.setObjectName("navbar")
        nl = QHBoxLayout(self.navbar)
        nl.setContentsMargins(2, 2, 2, 2)
        nl.setSpacing(2)
        self.nav_buttons = {}
        for name, tip in (("orbit", "Orbit (left drag)"), ("view", "Look at"), ("pan", "Pan (right drag)"),
                          ("zoom", "Zoom (wheel)"), ("fit", "Fit"), ("disp", "Display mode")):
            b = QToolButton()
            b.setToolTip(tip)
            b.setIcon(icons.icon(name, theme.FG2, theme.ACCENT, 15))
            b.setFixedSize(32, 26)
            nl.addWidget(b)
            self.nav_buttons[name] = b
        self.navbar.adjustSize()

        self.toast = QLabel(self)
        self.toast.setObjectName("toast")
        self.toast.hide()
        self._toast_t = QTimer(self, singleShot=True, timeout=self.toast.hide)
        self.banner = QLabel(self)
        self.banner.setObjectName("skbanner")
        self.banner.hide()
        self.dim = QLabel(self)
        self.dim.setObjectName("dim")
        self.dim.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.dim.hide()
        self.side = None                     # right-hand panel (sketch palette or command dialog)

    def cube_clicked(self, key):
        self.set_view(key)

    def show_toast(self, text: str, bad=False):
        self.toast.setText(text.upper())
        self.toast.setProperty("bad", bad)
        self.toast.style().polish(self.toast)
        self.toast.adjustSize()
        self._place()
        self.toast.show()
        self.toast.raise_()
        self._toast_t.start(1800)

    def show_banner(self, html: str | None):
        if html is None:
            self.banner.hide()
            return
        self.banner.setText(html)
        self.banner.adjustSize()
        self._place()
        self.banner.show()
        self.banner.raise_()

    def show_dim(self, text: str, pos: QPoint):
        self.dim.setText(text)
        self.dim.adjustSize()
        self.dim.move(pos + QPoint(14, 14))
        self.dim.show()
        self.dim.raise_()

    def set_side(self, w: QWidget | None):
        if self.side is not None and self.side is not w:
            self.side.hide()
        self.side = w
        if w is not None:
            w.setParent(self)
            w.adjustSize()
            self._place()
            w.show()
            w.raise_()

    def _place(self):
        W, H = self.width(), self.height()
        self.cube.move(W - 78 - 14, 12)
        self.navbar.move((W - self.navbar.width()) // 2, H - self.navbar.height() - 10)
        self.toast.move((W - self.toast.width()) // 2, 10)
        self.banner.move((W - self.banner.width()) // 2, 8)
        if self.side is not None:
            self.side.move(W - self.side.width() - 14, 104)
        for w in (self.hud, self.cube, self.navbar):
            w.raise_()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place()
