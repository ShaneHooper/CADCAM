"""3D viewport: pyvista/VTK inside Qt, Z-up like Fusion, plus the prototype's overlays
(HUD, view cube, nav bar, toast, sketch banner, live dimension tag)."""
from __future__ import annotations

import math
from functools import partial

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton, QToolButton, QVBoxLayout,
                               QWidget)
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkCommonMath import vtkMatrix4x4
from vtkmodules.vtkRenderingCore import vtkBillboardTextActor3D, vtkCellPicker, vtkMapper, vtkRenderer

from ..core import plane as pl
from . import icons, theme

VIEWS = {"home": (6, -7, 5), "top": (0, 0, 10), "front": (0, -10, 0), "left": (-10, 0, 0), "right": (10, 0, 0),
         "iso-tl": (-6, -7, 5), "iso-tr": (6, -7, 5), "iso-bl": (-6, 7, 5), "iso-br": (6, 7, 5)}
DISPLAY_MODES = ["SHADED + EDGES", "SHADED", "WIREFRAME"]
# Settings → View projection (like Fusion's camera options)
PROJECTIONS = {"ortho": "Orthographic", "persp": "Perspective", "persp-ortho-faces": "Perspective with ortho faces"}
FACE_VIEWS = ("top", "front", "left", "right", "bottom", "back")
# Direct View: the straight view whose direction (camera -> model) is nearest the current one
STRAIGHT = {"top": ((0, 0, 1), (0, 1, 0)), "bottom": ((0, 0, -1), (0, -1, 0)), "front": ((0, -1, 0), (0, 0, 1)),
            "back": ((0, 1, 0), (0, 0, 1)), "left": ((-1, 0, 0), (0, 0, 1)), "right": ((1, 0, 0), (0, 0, 1))}


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
        self._rpress = None                  # right press spot: a release there (no pan) = context menu
        self._box0 = None                    # left press spot of a selection box (None = not boxing)
        self.box_cb = None                   # no command running: box / click selects bodies (main window)
        self.click_cb = None

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
        # left drag: selection box (Shift + left drag orbits), right drag pan, wheel zoom
        style = vtkInteractorStyleTrackballCamera()
        # wheel turned the other way round from VTK's (Shane, 10/1/26): toward you zooms in
        style.AddObserver("MouseWheelForwardEvent", lambda o, e: o.OnMouseWheelBackward())
        style.AddObserver("MouseWheelBackwardEvent", lambda o, e: o.OnMouseWheelForward())
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
        self._sync_grid()

    def set_frame(self, frame: dict):
        self.frame = frame
        self._sync_grid()

    def look_at(self, frame: dict, dist: float = 10.0):
        """Camera square on to a sketch plane: looking along -n with the plane's y up, so the
        sketch reads left-to-right and up the way core.plane laid its axes."""
        o, n, y = frame["origin"], frame["n"], frame["y"]
        self.plotter.camera_position = [tuple(a + b * dist for a, b in zip(o, n)), tuple(o), tuple(y)]
        self.plotter.camera.view_angle = 35
        self.plotter.renderer.ResetCameraClippingRange()
        self.plotter.render()

    def body_at(self, pos: QPoint):
        """Index (in show_bodies order) of the body under the mouse, or None."""
        picker = vtkCellPicker()
        picker.SetTolerance(0.0005)
        r = self.plotter.devicePixelRatioF()
        picker.Pick(pos.x() * r, (self.plotter.height() - pos.y()) * r, 0, self.plotter.renderer)
        a = picker.GetActor()
        return self._actor_body.get(id(a)) if a is not None else None

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
        """The grid is drawn once in the sketch plane's own axes (u, v, 0) and moved onto the plane being
        sketched on (`_place_grid`); it is only shown while a sketch is open (`_sync_grid`). The red / green /
        blue axes at the world origin are always there."""
        size, minor = 8, 0.25
        m1, m2 = [], []
        for i in np.arange(-size, size + 1e-9, minor):
            major = abs(i - round(i)) < 1e-6
            (m2 if major else m1).extend([[(i, -size, 0), (i, size, 0)], [(-size, i, 0), (size, i, 0)]])
        self._grid_actors = [
            self.plotter.add_mesh(polyline_mesh(m1), color="#1f1f1f", line_width=1, pickable=False, lighting=False),
            self.plotter.add_mesh(polyline_mesh(m2), color="#333333", line_width=1, pickable=False, lighting=False)]
        for d, c in (((1.5, 0, 0), theme.BAD), ((0, 1.5, 0), theme.OK), ((0, 0, 1.5), "#3b8cff")):
            self.plotter.add_mesh(polyline_mesh([[(0, 0, 0), d]]), color=c, line_width=1.5, lighting=False)
        # the sketch's own X (red) and Y (green) axes: 2 in each way from the sketch origin, thin, drawn over
        # everything (they ran "forever" and 2.5 px wide for a while; Shane found that too much)
        self._axis_actors = []
        for d, c in (((1, 0, 0), theme.BAD), ((0, 1, 0), theme.OK)):
            a = pv.Actor(mapper=pv.DataSetMapper(polyline_mesh([[tuple(-self.AXIS_REACH * x for x in d),
                                                                tuple(self.AXIS_REACH * x for x in d)]])))
            a.prop.color, a.prop.line_width, a.prop.lighting = c, 1.5, False
            a.SetPickable(False)
            self.top.AddActor(a)
            self._axis_actors.append(a)
        self._sync_grid(render=False)

    AXIS_REACH = 2.0                         # the sketch axes run this far (inches) each way from the origin
    GRID_LIFT = 0.003                        # the grid floats this far above the face it lies on (no flicker)

    @property
    def handler(self):
        return self._handler

    @handler.setter
    def handler(self, h):
        self._handler = h
        self._sync_grid()

    def _sync_grid(self, render: bool = True):
        """Show the grid on the sketch plane while a sketch is open, hide it otherwise (a plain 3D model needs
        no grid). Anything that sketches says so with `shows_grid`."""
        actors = getattr(self, "_grid_actors", None)
        if not actors:
            return                           # not built yet (the handler is first set before the scene exists)
        show = bool(getattr(self._handler, "shows_grid", False))
        for a in list(actors) + self._axis_actors:
            a.SetVisibility(show)
        if show:
            self._place_grid()
        if render:
            self.plotter.render()

    def _place_grid(self):
        """Lay the grid on the current sketch plane: its x / y axes, its normal, its origin, lifted a hair."""
        fr = self.frame
        m = vtkMatrix4x4()
        for r in range(3):
            m.SetElement(r, 0, fr["x"][r])
            m.SetElement(r, 1, fr["y"][r])
            m.SetElement(r, 2, fr["n"][r])
            m.SetElement(r, 3, fr["origin"][r] + fr["n"][r] * self.GRID_LIFT)
        for a in self._grid_actors + self._axis_actors:
            a.SetUserMatrix(m)

    def show_bodies(self, bodies, selected: str | None = None):
        """bodies: kernel Body objects. Rebuilds the solid actors."""
        for a in self._body_actors:
            self.plotter.remove_actor(a, render=False)
        self._body_actors = []
        self._actor_body = {}
        wire = self.display_mode == 2
        selected = selected if isinstance(selected, (set, list, tuple)) else {selected}
        for b in bodies:
            v, t = b.triangles()
            if not len(t):
                continue
            mesh = pv.PolyData(v, np.hstack([np.full((len(t), 1), 3), t]).ravel())
            sel = b.id in selected
            a = self.plotter.add_mesh(mesh, color=theme.ACCENT if sel else theme.BODY, smooth_shading=True,
                                      split_sharp_edges=True, feature_angle=30,
                                      style="wireframe" if wire else "surface", specular=0.3, specular_power=24,
                                      ambient=theme.BODY_AMBIENT if not sel else 0.3, diffuse=theme.BODY_DIFFUSE,
                                      render=False)
            self._body_actors.append(a)
            self._actor_body[id(a)] = b.id
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

    # ---------- selection box (left drag) ----------
    def _box_ok(self) -> bool:
        """Left drag draws a selection box: with no command running (bodies), or in a sketch
        session that wants one (Select, Rotate / Mirror / Pattern). Everything else orbits."""
        if self.handler is None:
            return True
        ok = getattr(self.handler, "box_ok", None)
        return bool(ok and ok())

    def _show_box(self, p0, p1):
        if not hasattr(self, "band"):
            self.band = QFrame(self)
            self.band.setAttribute(Qt.WA_TransparentForMouseEvents)
        crossing = p1.x() < p0.x()           # right to left: anything it touches (dashed, green)
        self.band.setStyleSheet(f"background: rgba(47,155,255,40); border: 1px {'dashed' if crossing else 'solid'} "
                                f"{theme.OK if crossing else theme.ACCENT};")
        r = QRect(self.plotter.mapTo(self, p0), self.plotter.mapTo(self, p1)).normalized()
        self.band.setGeometry(r)
        self.band.show()
        self.band.raise_()

    def box_hit(self, polylines, rect: QRect, crossing: bool) -> bool:
        """Does a shape (world polylines) fall in a screen box? Window (left to right): all of it
        inside. Crossing (right to left): any part inside or crossing the box's edge."""
        x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
        segs = [self.project(np.asarray(pl_, float))[:, :2] for pl_ in polylines if len(pl_)]
        if not segs:
            return False
        pts = np.vstack(segs)
        inside = (pts[:, 0] >= x0) & (pts[:, 0] <= x1) & (pts[:, 1] >= y0) & (pts[:, 1] <= y1)
        if not crossing:
            return bool(inside.all())
        if inside.any():
            return True
        for s in segs:                       # an edge passing through the box with no point in it
            for (ax, ay), (bx, by) in zip(s, s[1:]):
                t0, t1 = 0.0, 1.0
                dx, dy = bx - ax, by - ay
                for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0), (dy, y1 - ay)):
                    if abs(p) < 1e-12:
                        if q < 0:
                            break
                        continue
                    t = q / p
                    if p < 0:
                        t0 = max(t0, t)
                    else:
                        t1 = min(t1, t)
                else:
                    if t0 <= t1:
                        return True
        return False

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

    def nearest_view(self) -> str:
        """The straight view (top / front / ...) closest to where the camera looks from now."""
        cam = self.plotter.camera
        d = np.subtract(cam.position, cam.focal_point)
        d = d / (np.linalg.norm(d) or 1.0)
        return max(STRAIGHT, key=lambda k: float(np.dot(d, STRAIGHT[k][0])))

    def direct_view(self):
        """Right-click → Direct View: turn to the nearest straight view, keeping the zoom and the
        point the view is centred on."""
        key = self.nearest_view()
        cam = self.plotter.camera
        f, dist = np.array(cam.focal_point), cam.distance
        v, up = STRAIGHT[key]
        self.plotter.camera_position = [tuple(f + dist * np.array(v)), tuple(f), up]
        self._face_view = True
        self.apply_projection(render=False)
        self.plotter.renderer.ResetCameraClippingRange()
        self.hud_view.setText(key.upper())
        self.plotter.render()

    def rotate_view(self, deg: float):
        """Spin the view about the line of sight (the model turns on screen; -90 = clockwise)."""
        self.plotter.camera.Roll(deg)
        self.plotter.render()

    def context_menu(self, at):
        m = QMenu(self)
        key = self.nearest_view()
        act = m.addAction(f"Direct View  ·  {key.upper()}")
        act.setToolTip("Turn to the nearest straight view (top, front, side...), same zoom")
        act.triggered.connect(self.direct_view)
        m.addAction("Rotate View Clockwise").triggered.connect(lambda: self.rotate_view(-90))
        m.addAction("Rotate View Counterclockwise").triggered.connect(lambda: self.rotate_view(90))
        self._menu = m                        # kept for tests / so it isn't collected while open
        m.popup(at)

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
        if t == QEvent.MouseMove and self._box0 is not None and ev.buttons() & Qt.LeftButton:
            p = ev.position().toPoint()
            if (p - self._box0).manhattanLength() > 4:
                self._show_box(self._box0, p)
            if self.handler is None:
                return True                      # (no orbit while boxing)
        if t == QEvent.MouseMove:
            w = self.world_at(ev.position().toPoint())
            if w:
                self.cursor.emit(w[0], w[1], self.plane_z)
            if self.handler and (w or getattr(self.handler, "wants_any_click", False)):
                self.handler.on_move(w, ev)          # (toolpath panels pick on screen, any view)
            return False
        if t == QEvent.MouseButtonPress and ev.button() == Qt.RightButton:
            # a session may claim a right-click (a dimension under it); otherwise VTK pans
            if self.handler is not None and hasattr(self.handler, "on_right_click"):
                w = self.world_at(ev.position().toPoint())
                if w and self.handler.on_right_click(w, ev):
                    self._right_taken = True
                    return True
            self._rpress = ev.position().toPoint()
            return False
        if t == QEvent.MouseButtonRelease and ev.button() == Qt.RightButton and self._right_taken:
            self._right_taken = False
            return True                      # VTK saw no press, so it must not see the release
        if t == QEvent.MouseButtonRelease and ev.button() == Qt.RightButton and self._rpress is not None:
            p0, self._rpress = self._rpress, None
            if (ev.position().toPoint() - p0).manhattanLength() <= 4:
                g = ev.globalPosition().toPoint()
                if self.handler and hasattr(self.handler, "right_menu"):
                    QTimer.singleShot(0, lambda: self.handler and self.handler.right_menu(g))   # e.g. sketch: Done
                elif not (self.handler and getattr(self.handler, "captures_left", False)):
                    QTimer.singleShot(0, lambda: self.context_menu(g))
            return False
        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick) and ev.button() == Qt.LeftButton:
            # a fast second click arrives as DblClick: it must count as a click, and VTK must
            # never see it (it starts an orbit whose release we swallow = stuck rotating)
            self._press = ev.position().toPoint()
            boxing = self._box_ok() and not (ev.modifiers() & Qt.ShiftModifier)   # Shift+drag orbits
            self._box0 = self._press if boxing else None
            if boxing and self.handler is None:
                return True                          # VTK must not start an orbit
            if self._face_view and not (self.handler and self.handler.captures_left):
                self._face_view = False              # orbiting off TOP / FRONT / ...: not a face view now
                self.apply_projection(render=False)
            if self.handler and self.handler.captures_left:
                w = self.world_at(self._press)
                if w:
                    self.handler.on_click(w, ev)
                return True          # no orbit while sketching
            return False
        if t == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton and self._box0 is not None:
            p0, self._box0, self._press = self._box0, None, None
            p1 = ev.position().toPoint()
            if hasattr(self, "band"):
                self.band.hide()
            dragged = (p1 - p0).manhattanLength() > 4
            rect, crossing = QRect(p0, p1).normalized(), p1.x() < p0.x()
            if self.handler is None:
                if dragged and self.box_cb:
                    self.box_cb(rect, crossing, bool(ev.modifiers() & Qt.ControlModifier))
                elif not dragged and self.click_cb:
                    self.click_cb(p1, bool(ev.modifiers() & Qt.ControlModifier))
                return True
            self.plotter.iren.interactor.GetInteractorStyle().OnLeftButtonUp()
            if dragged:
                self.handler.on_box(rect, crossing)
            return True
        if t == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
            p0, self._press = self._press, None
            if self.handler and self.handler.captures_left:
                self.plotter.iren.interactor.GetInteractorStyle().OnLeftButtonUp()   # never leave VTK orbiting
                return True
            if self.handler and p0 is not None and (ev.position().toPoint() - p0).manhattanLength() <= 4:
                w = self.world_at(ev.position().toPoint())
                if w or getattr(self.handler, "wants_any_click", False):
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
                          ("zoom", "Zoom (wheel)"), ("fit", "Fit"), ("disp", "Display mode"),
                          ("trash", "Deselect: drop everything selected / picked")):
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
        for w in (self.hud, self.cube, self.navbar):
            w.raise_()
        if self.side is not None and getattr(self.side, "user_pos", None) is not None:
            up = self.side.user_pos                 # dragged by its title: stay there (kept on the view)
            self.side.move(min(max(up.x(), 0), max(W - self.side.width(), 0)), min(max(up.y(), 0), max(H - 40, 0)))
        elif self.side is not None:
            # below the view cube; a panel too tall for that moves up (over the cube) so its
            # OK / CANCEL never fall off the bottom
            y = 104 if self.side.height() <= H - 104 - 10 else max(8, H - self.side.height() - 10)
            self.side.move(W - self.side.width() - 14, y)
            if y < 104:
                self.side.raise_()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place()
