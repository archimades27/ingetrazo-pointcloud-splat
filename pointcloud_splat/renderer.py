# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""High-performance viewport overlay renderer for Point Clouds and 3D Gaussian Splats."""
from __future__ import annotations

import concurrent.futures
import ctypes
import logging
import math
from pathlib import Path
import subprocess
import time
from typing import Dict, List, Optional, Tuple, Union
import numpy as np

from PySide6.QtCore import QObject, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen

from .data_models import PointCloudDataset, GaussianSplatDataset

log = logging.getLogger("ingetrazo.plugins.pointcloud_splat")

_fast_splat_lib = None


class RefineBridge(QObject):
    """Thread bridge to safely deliver refined QImages back to the Qt main GUI thread."""
    refine_done = Signal(object, object, object, object)  # v_id (object), token (object), QImage (object), view_hash (object)


def _get_fast_splat_lib():
    """Lazily load or compile the accelerated C/GCD rasterizer library."""
    global _fast_splat_lib
    if _fast_splat_lib is not None:
        return _fast_splat_lib if _fast_splat_lib is not False else None

    plugin_dir = Path(__file__).resolve().parent

    # Check standard or versioned shared library
    candidates = [
        plugin_dir / "fast_splat.dylib",
        plugin_dir / "fast_splat_v9.dylib",
        plugin_dir / "fast_splat.so",
        plugin_dir / "fast_splat.dll",
    ]
    dylib_path = None
    for c in candidates:
        if c.exists():
            dylib_path = c
            break

    c_path = plugin_dir / "fast_splat.c"

    if dylib_path is None and c_path.exists():
        ext = ".dylib" if sys.platform == "darwin" else ".so"
        target = plugin_dir / f"fast_splat{ext}"
        try:
            log.info(f"Compiling native fast_splat{ext} with clang/gcc...")
            compiler = "clang" if sys.platform == "darwin" else "gcc"
            subprocess.run([
                compiler, "-O3", "-shared", "-fPIC", "-march=native", "-ffast-math",
                "-o", str(target), str(c_path)
            ], check=True, capture_output=True)
            dylib_path = target
        except Exception as e:
            log.warning(f"Could not auto-compile fast_splat: {e}")

    if dylib_path is not None and dylib_path.exists():
        try:
            lib = ctypes.CDLL(str(dylib_path))
            if hasattr(lib, "rasterize_splats_auto"):
                lib.rasterize_splats_auto.argtypes = [
                    ctypes.c_void_p,                                   # buf
                    ctypes.c_int, ctypes.c_int,                        # width, height
                    ctypes.c_int, ctypes.c_int,                        # n_total, max_draw
                    ctypes.POINTER(ctypes.c_float),                    # coords
                    ctypes.POINTER(ctypes.c_float),                    # scales
                    ctypes.POINTER(ctypes.c_float),                    # rotations
                    ctypes.c_void_p,                                   # colors
                    ctypes.POINTER(ctypes.c_float),                    # obj_mat
                    ctypes.POINTER(ctypes.c_float),                    # view_mat
                    ctypes.POINTER(ctypes.c_float),                    # cam_eye
                    ctypes.c_float, ctypes.c_float, ctypes.c_float,    # fwd_x, fwd_y, fwd_z
                    ctypes.c_float, ctypes.c_float,                    # fx, fy
                    ctypes.c_float, ctypes.c_float,                    # cx, cy
                    ctypes.c_float, ctypes.c_float,                    # splat_scale, opacity_mul
                    ctypes.c_int,                                      # clear_buf
                    ctypes.POINTER(ctypes.c_float)                     # clip_plane
                ]
                lib.rasterize_splats_auto.restype = ctypes.c_int

            if hasattr(lib, "sort_splats_depth_c"):
                lib.sort_splats_depth_c.argtypes = [
                    ctypes.POINTER(ctypes.c_float),                    # pts
                    ctypes.c_int,                                      # n
                    ctypes.POINTER(ctypes.c_float),                    # obj_mat
                    ctypes.c_float, ctypes.c_float, ctypes.c_float,    # eye_x, eye_y, eye_z
                    ctypes.c_float, ctypes.c_float, ctypes.c_float,    # fwd_x, fwd_y, fwd_z
                    ctypes.POINTER(ctypes.c_int32),                    # out_order
                    ctypes.c_int,                                      # max_draw
                    ctypes.POINTER(ctypes.c_int)                       # out_count
                ]

            if hasattr(lib, "rasterize_splats_direct"):
                lib.rasterize_splats_direct.argtypes = [
                    ctypes.c_void_p,                                   # buf
                    ctypes.c_int, ctypes.c_int, ctypes.c_int,          # width, height, n_draw
                    ctypes.POINTER(ctypes.c_int32),                    # order
                    ctypes.POINTER(ctypes.c_float),                    # coords
                    ctypes.POINTER(ctypes.c_float),                    # scales
                    ctypes.POINTER(ctypes.c_float),                    # rotations
                    ctypes.c_void_p,                                   # colors
                    ctypes.POINTER(ctypes.c_float),                    # obj_mat
                    ctypes.POINTER(ctypes.c_float),                    # view_mat
                    ctypes.POINTER(ctypes.c_float),                    # cam_eye
                    ctypes.c_float, ctypes.c_float,                    # fx, fy
                    ctypes.c_float, ctypes.c_float,                    # cx, cy
                    ctypes.c_float, ctypes.c_float,                    # splat_scale, opacity_mul
                    ctypes.POINTER(ctypes.c_float)                     # clip_plane
                ]
            if hasattr(lib, "rasterize_points"):
                lib.rasterize_points.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_int, ctypes.c_int, ctypes.c_int,
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.c_void_p,
                    ctypes.c_int
                ]
            if hasattr(lib, "rasterize_point_cloud_auto"):
                lib.rasterize_point_cloud_auto.argtypes = [
                    ctypes.c_void_p,                                   # buf
                    ctypes.c_int, ctypes.c_int,                        # width, height
                    ctypes.c_int,                                      # n_points
                    ctypes.POINTER(ctypes.c_float),                    # coords
                    ctypes.c_void_p,                                   # colors
                    ctypes.POINTER(ctypes.c_float),                    # obj_mat
                    ctypes.POINTER(ctypes.c_float),                    # view_mat
                    ctypes.POINTER(ctypes.c_float),                    # cam_eye
                    ctypes.c_float, ctypes.c_float,                    # fx, fy
                    ctypes.c_float, ctypes.c_float,                    # cx, cy
                    ctypes.c_int,                                      # point_size
                    ctypes.c_float,                                    # opacity_mul
                    ctypes.c_int,                                      # clear_buf
                    ctypes.c_int,                                      # is_ortho
                    ctypes.POINTER(ctypes.c_float)                     # clip_plane
                ]
                lib.rasterize_point_cloud_auto.restype = None
            _fast_splat_lib = lib
            log.info("Initialized native accelerated Gaussian Splat rasterizer.")
            return lib
        except Exception as e:
            log.warning(f"Failed to load fast_splat dylib: {e}")

    _fast_splat_lib = False
    return None


def _make_lut(stops: list[Tuple[float, Tuple[int, int, int]]]) -> np.ndarray:
    """Build a 256x3 uint8 RGB lookup table from color stops."""
    t_vals = [s[0] for s in stops]
    r_vals = [s[1][0] for s in stops]
    g_vals = [s[1][1] for s in stops]
    b_vals = [s[1][2] for s in stops]
    t = np.linspace(0.0, 1.0, 256)
    r = np.interp(t, t_vals, r_vals)
    g = np.interp(t, t_vals, g_vals)
    b = np.interp(t, t_vals, b_vals)
    return np.column_stack([r, g, b]).astype(np.uint8)


# Precomputed colormaps
COLORMAPS: Dict[str, np.ndarray] = {
    "turbo": _make_lut([
        (0.0, (48, 18, 59)), (0.15, (70, 134, 251)), (0.35, (27, 229, 181)),
        (0.55, (164, 252, 60)), (0.75, (251, 185, 56)), (0.9, (227, 73, 24)), (1.0, (122, 4, 3))
    ]),
    "viridis": _make_lut([
        (0.0, (68, 1, 84)), (0.25, (59, 82, 139)), (0.5, (33, 145, 140)),
        (0.75, (94, 201, 98)), (1.0, (253, 231, 37))
    ]),
    "jet": _make_lut([
        (0.0, (0, 0, 140)), (0.15, (0, 0, 255)), (0.4, (0, 255, 255)),
        (0.65, (255, 255, 0)), (0.85, (255, 0, 0)), (1.0, (128, 0, 0))
    ]),
    "terrain": _make_lut([
        (0.0, (50, 95, 150)), (0.18, (0, 150, 100)), (0.42, (200, 200, 100)),
        (0.72, (150, 100, 50)), (0.9, (190, 190, 190)), (1.0, (255, 255, 255))
    ]),
}


class ViewportState:
    """Independent rendering and interaction cache for each viewport in multi-view layouts."""
    def __init__(self, vp_id: int) -> None:
        self.vp_id: int = vp_id
        self.last_cam_hash: Optional[int] = None
        self.last_cam_time: float = 0.0
        self.is_interacting: bool = False
        self.refine_scheduled: bool = False
        self.cached_qimg: Optional[QImage] = None
        self.cached_cam_hash: Optional[int] = None
        self.last_draft_qimg: Optional[QImage] = None
        self.last_draft_hash: Optional[int] = None
        self.current_token: int = 0
        self.refining_hash: Optional[int] = None


class CloudRenderer:
    """Manages viewport rendering of point clouds and 3D Gaussian Splats."""

    def __init__(self, app) -> None:
        self.app = app
        self.clipping_enabled: bool = False
        self.clip_min: np.ndarray = np.array([-1000.0, -1000.0, -1000.0], dtype=np.float32)
        self.clip_max: np.ndarray = np.array([1000.0, 1000.0, 1000.0], dtype=np.float32)

        # Performance & interaction tracking
        self.max_point_budget: int = 1500000

        # Per-viewport states (supports multi-view: Perspective, Top, Front, Right simultaneously)
        self._vp_states: Dict[int, ViewportState] = {}

        # Asynchronous background refine worker (zero UI lag)
        self._bg_executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        self._bridge = RefineBridge()
        self._bridge.refine_done.connect(self._on_refine_done)

    def _get_state(self, viewport) -> ViewportState:
        v_id = id(viewport)
        state = self._vp_states.get(v_id)
        if state is None:
            state = ViewportState(v_id)
            self._vp_states[v_id] = state
        return state

    def _find_viewport_by_id(self, v_id: int):
        from views.viewport import Viewport
        win = getattr(self.app, 'window', None)
        if win is not None:
            try:
                for vp in win.findChildren(Viewport):
                    if id(vp) == v_id:
                        return vp
            except Exception:
                pass
        main_vp = getattr(self.app, 'viewport', None)
        if main_vp is not None and id(main_vp) == v_id:
            return main_vp
        return None

    def _on_refine_done(self, v_id, token, qimg: QImage, view_hash) -> None:
        """Called on Qt main GUI thread when background refine completes for a viewport."""
        state = self._vp_states.get(v_id)
        if state is not None and token == state.current_token and qimg is not None:
            state.cached_qimg = qimg
            state.cached_cam_hash = view_hash
            state.refining_hash = None
            vp = self._find_viewport_by_id(v_id)
            if vp is not None:
                try:
                    vp.update()
                except Exception:
                    pass

    def _get_section_clip_plane(self, viewport) -> Optional[np.ndarray]:
        """Return 4-element plane vector [nx, ny, nz, d] if an active section cut applies."""
        scene = getattr(viewport, 'scene', None)
        if scene is None or not getattr(scene, 'show_section_cuts', True):
            return None

        active_sec = getattr(scene, 'active_section', lambda: None)()
        if active_sec is None:
            active_list = [sp for sp in getattr(scene, 'section_planes', ()) if getattr(sp, 'active', False)]
            if active_list:
                active_sec = active_list[0]
            else:
                return None

        clip_vec = getattr(viewport, '_clip_vec', None)
        if clip_vec is not None:
            return np.array([clip_vec.x(), clip_vec.y(), clip_vec.z(), clip_vec.w()], dtype=np.float32)

        norm = active_sec.normal
        pt = active_sec.point
        nx = float(-norm.x())
        ny = float(-norm.y())
        nz = float(-norm.z())
        d = float(-(nx * pt.x() + ny * pt.y() + nz * pt.z()))
        return np.array([nx, ny, nz, d], dtype=np.float32)

    def get_view_hash(self, viewport, datasets) -> int:
        """Hash camera, projection mode, section plane, and dataset display parameters."""
        cam = getattr(viewport, 'camera', None)
        if cam is None:
            return 0
        target = getattr(cam, 'target', None)
        tx = getattr(target, 'x', lambda: 0.0)() if target else 0.0
        ty = getattr(target, 'y', lambda: 0.0)() if target else 0.0
        tz = getattr(target, 'z', lambda: 0.0)() if target else 0.0

        clip_p = self._get_section_clip_plane(viewport)
        clip_hash = tuple(np.round(clip_p, 3)) if clip_p is not None else None
        is_ortho = not getattr(cam, 'perspective', True)

        ds_tokens = []
        for ds in datasets:
            if ds.visible and len(ds.coords) > 0:
                ds_tokens.append((
                    ds.name,
                    getattr(ds, 'splat_scale', 1.0),
                    getattr(ds, 'point_size', 2),
                    getattr(ds, 'opacity', 1.0),
                    getattr(ds, 'color_mode', ''),
                    getattr(ds, 'colormap', ''),
                    getattr(ds, 'solid_color', ''),
                    ds.offset.tobytes() if hasattr(ds.offset, 'tobytes') else str(ds.offset),
                    round(float(getattr(ds, 'rotation_x_deg', 0.0)), 4),
                    round(float(getattr(ds, 'rotation_y_deg', 0.0)), 4),
                    round(float(getattr(ds, 'rotation_z_deg', 0.0)), 4),
                    float(getattr(ds, 'scale', 1.0)),
                ))

        clip_box = (
            (self.clip_min.tobytes(), self.clip_max.tobytes()) if self.clipping_enabled else None
        )

        return hash((
            round(getattr(cam, 'yaw', 0.0), 3),
            round(getattr(cam, 'pitch', 0.0), 3),
            round(getattr(cam, 'distance', 0.0), 2),
            round(tx, 2), round(ty, 2), round(tz, 2),
            is_ortho,
            clip_hash,
            clip_box,
            self.max_point_budget,
            viewport.width(),
            viewport.height(),
            tuple(ds_tokens)
        ))

    def check_interaction(self, viewport) -> bool:
        """True if the camera of this viewport is actively orbiting / panning / zooming."""
        cam = getattr(viewport, 'camera', None)
        if cam is None:
            return False

        state = self._get_state(viewport)
        now = time.perf_counter()
        target = getattr(cam, 'target', None)
        tx = getattr(target, 'x', lambda: 0.0)() if target else 0.0
        ty = getattr(target, 'y', lambda: 0.0)() if target else 0.0
        tz = getattr(target, 'z', lambda: 0.0)() if target else 0.0
        clip_p = self._get_section_clip_plane(viewport)
        clip_hash = tuple(np.round(clip_p, 3)) if clip_p is not None else None
        cam_tuple = (
            round(getattr(cam, 'yaw', 0.0), 3),
            round(getattr(cam, 'pitch', 0.0), 3),
            round(getattr(cam, 'distance', 0.0), 2),
            round(tx, 2), round(ty, 2), round(tz, 2),
            getattr(cam, 'perspective', True),
            clip_hash
        )
        cam_hash = hash(cam_tuple)

        if state.last_cam_hash != cam_hash:
            state.last_cam_hash = cam_hash
            state.last_cam_time = now
            state.is_interacting = True
            state.current_token += 1
            state.cached_qimg = None
            state.last_draft_qimg = None
            state.refining_hash = None
        else:
            if now - state.last_cam_time > 0.15:
                if state.is_interacting:
                    state.is_interacting = False
                    if not state.refine_scheduled:
                        state.refine_scheduled = True
                        vp_ref = viewport
                        def _trigger_refine():
                            state.refine_scheduled = False
                            try:
                                vp_ref.update()
                            except Exception:
                                pass
                        QTimer.singleShot(10, _trigger_refine)

        return state.is_interacting

    def render(
        self,
        viewport,
        painter: QPainter,
        datasets: List[Union[PointCloudDataset, GaussianSplatDataset]]
    ) -> None:
        """Render all visible datasets onto the active viewport."""
        visible_ds = [d for d in datasets if d.visible and len(d.coords) > 0]
        state = self._get_state(viewport)
        if not visible_ds:
            state.cached_qimg = None
            state.last_draft_qimg = None
            return

        dev = painter.device()
        w = dev.width() if dev is not None else viewport.width()
        h = dev.height() if dev is not None else viewport.height()
        if w <= 0 or h <= 0:
            return

        is_moving = self.check_interaction(viewport)
        view_hash = self.get_view_hash(viewport, visible_ds)

        # 1. Serve from stationary cache if available (0ms overhead on hover / CAD tools)
        if not is_moving and state.cached_qimg is not None and state.cached_cam_hash == view_hash:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, False)
            painter.drawImage(0, 0, state.cached_qimg)
            painter.restore()
            self._render_selection_bounds(viewport, painter, visible_ds)
            return

        if state.last_draft_hash != view_hash:
            state.last_draft_qimg = None
            state.last_draft_hash = view_hash

        # 2. Stationary state without final cache: display draft & dispatch background refine
        if not is_moving:
            if state.last_draft_qimg is None:
                # Generate initial draft preview immediately (~15ms)
                buf = np.zeros((h, w, 4), dtype=np.uint8)
                rendered_any = False
                for ds in visible_ds:
                    ds_type = type(ds).__name__
                    if ds_type == "PointCloudDataset" or isinstance(ds, PointCloudDataset):
                        rendered = self._render_point_cloud(ds, viewport, buf, w, h, is_moving=True)
                    elif ds_type == "GaussianSplatDataset" or isinstance(ds, GaussianSplatDataset):
                        rendered = self._render_gaussian_splat(ds, viewport, buf, w, h, is_moving=True)
                    else:
                        rendered = False
                    rendered_any = rendered_any or rendered

                if rendered_any:
                    qimg = QImage(buf.data, w, h, w * 4, QImage.Format_ARGB32).copy()
                    state.last_draft_qimg = qimg

            if state.last_draft_qimg is not None:
                painter.save()
                painter.setRenderHint(QPainter.Antialiasing, False)
                painter.drawImage(0, 0, state.last_draft_qimg)
                painter.restore()

            if state.refining_hash != view_hash:
                state.refining_hash = view_hash
                self._submit_background_refine(viewport, visible_ds, view_hash, w, h)

            self._render_selection_bounds(viewport, painter, visible_ds)
            return

        # 3. Interactive moving mode: render fast draft preview (~15ms)
        buf = np.zeros((h, w, 4), dtype=np.uint8)
        rendered_any = False

        for ds in visible_ds:
            ds_type = type(ds).__name__
            if ds_type == "PointCloudDataset" or isinstance(ds, PointCloudDataset):
                rendered = self._render_point_cloud(ds, viewport, buf, w, h, is_moving=True)
            elif ds_type == "GaussianSplatDataset" or isinstance(ds, GaussianSplatDataset):
                rendered = self._render_gaussian_splat(ds, viewport, buf, w, h, is_moving=True)
            else:
                rendered = False
            rendered_any = rendered_any or rendered

        if rendered_any:
            qimg = QImage(buf.data, w, h, w * 4, QImage.Format_ARGB32).copy()
            state.last_draft_qimg = qimg

            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, False)
            painter.drawImage(0, 0, qimg)
            painter.restore()

        self._render_selection_bounds(viewport, painter, visible_ds)

    def _submit_background_refine(
        self,
        viewport,
        visible_ds: List[Union[PointCloudDataset, GaussianSplatDataset]],
        view_hash: int,
        w: int,
        h: int
    ) -> None:
        """Launch high-resolution final pass in a background thread."""
        cam = getattr(viewport, 'camera', None)
        if cam is None:
            return

        v_id = id(viewport)
        state = self._get_state(viewport)
        state.current_token += 1
        token = state.current_token

        try:
            eye = cam.eye()
            fwd = cam.forward()
            eye_v = np.array([eye.x(), eye.y(), eye.z()], dtype=np.float32)
            fwd_v = np.array([fwd.x(), fwd.y(), fwd.z()], dtype=np.float32)

            vm = cam.view_matrix()
            W_flat = np.array([
                vm(0, 0), vm(0, 1), vm(0, 2),
                vm(1, 0), vm(1, 1), vm(1, 2),
                vm(2, 0), vm(2, 1), vm(2, 2)
            ], dtype=np.float32)

            pm_data = cam.projection_matrix().data()
            fx = float(pm_data[0] * w * 0.5)
            fy = float(pm_data[5] * h * 0.5)
            cx = float(w * 0.5)
            cy = float(h * 0.5)
            is_ortho = 1 if (not getattr(cam, 'perspective', True) or abs(pm_data[15] - 1.0) < 0.1) else 0
            clip_p = self._get_section_clip_plane(viewport)
        except Exception as e:
            log.debug(f"Background refine camera extract error: {e}")
            return

        clip_p_c = clip_p.ctypes.data_as(ctypes.POINTER(ctypes.c_float)) if clip_p is not None else None
        clip_box = (self.clip_min.copy(), self.clip_max.copy()) if self.clipping_enabled else None

        # Snapshot datasets
        snapshots = []
        for ds in visible_ds:
            ds_type = type(ds).__name__
            if ds_type == "GaussianSplatDataset" or isinstance(ds, GaussianSplatDataset):
                obj_mat = self._get_obj_matrix(ds)
                snapshots.append({
                    "type": "gs",
                    "coords": ds.coords,
                    "scales": ds.scales,
                    "rotations": ds.rotations,
                    "colors": ds.colors,
                    "obj_mat": obj_mat,
                    "splat_scale": float(ds.splat_scale),
                    "opacity": float(ds.opacity),
                    "max_splats": min(getattr(ds, 'max_splats', 1500000), self.max_point_budget)
                })
            elif ds_type == "PointCloudDataset" or isinstance(ds, PointCloudDataset):
                obj_mat = self._get_obj_matrix(ds)
                # Pass references to worker thread so 162M slicing never blocks the GUI thread
                snapshots.append({
                    "type": "pc",
                    "coords": ds.coords,
                    "colors": ds.colors,
                    "color_mode": ds.color_mode,
                    "colormap": getattr(ds, 'colormap', 'turbo'),
                    "elevation_range": getattr(ds, 'elevation_range', None),
                    "intensities": getattr(ds, 'intensities', None),
                    "normals": getattr(ds, 'normals', None),
                    "solid_color": getattr(ds, 'solid_color', (0, 200, 255)),
                    "obj_mat": obj_mat,
                    "point_size": max(1, min(14, int(ds.point_size))),
                    "opacity": float(ds.opacity),
                    "budget": getattr(self, 'max_point_budget', 3000000)
                })

        def _bg_task():
            if token != state.current_token:
                return

            fast_lib = _get_fast_splat_lib()
            buf = np.zeros((h, w, 4), dtype=np.uint8)

            rendered_any = False
            for s in snapshots:
                if s["type"] == "gs" and fast_lib and hasattr(fast_lib, "rasterize_splats_auto"):
                    n_splats = len(s["coords"])
                    n_drawn = fast_lib.rasterize_splats_auto(
                        buf.ctypes.data, w, h, n_splats, s["max_splats"],
                        s["coords"].ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                        s["scales"].ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                        s["rotations"].ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                        s["colors"].ctypes.data,
                        s["obj_mat"].ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                        W_flat.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                        eye_v.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                        fwd_v[0], fwd_v[1], fwd_v[2],
                        fx, fy, cx, cy,
                        s["splat_scale"], s["opacity"],
                        0,
                        clip_p_c
                    )
                    if n_drawn > 0:
                        rendered_any = True
                elif s["type"] == "pc" and fast_lib and hasattr(fast_lib, "rasterize_point_cloud_auto"):
                    raw_coords = s["coords"]
                    n_total = len(raw_coords)
                    budget = max(1000000, min(s["budget"], 12000000))
                    step = max(1, n_total // budget)
                    sub_coords = np.ascontiguousarray(raw_coords[::step])
                    sub_colors = self._extract_colors_raw(
                        sub_coords, step, s["colors"], s["color_mode"],
                        s["colormap"], s["elevation_range"], s["intensities"],
                        s["normals"], s["solid_color"]
                    )
                    if clip_box is not None:
                        mask = self._clip_box_mask(sub_coords, s["obj_mat"], clip_box[0], clip_box[1])
                        sub_coords = np.ascontiguousarray(sub_coords[mask])
                        sub_colors = np.ascontiguousarray(sub_colors[mask])
                    n_pts = len(sub_coords)
                    if n_pts > 0:
                        fast_lib.rasterize_point_cloud_auto(
                            buf.ctypes.data, w, h, n_pts,
                            sub_coords.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                            sub_colors.ctypes.data,
                            s["obj_mat"].ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                            W_flat.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                            eye_v.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                            fx, fy, cx, cy,
                            s["point_size"], s["opacity"],
                            0,
                            is_ortho,
                            clip_p_c
                        )
                        rendered_any = True

            if rendered_any and token == state.current_token:
                qimg = QImage(buf.data, w, h, w * 4, QImage.Format_ARGB32).copy()
                self._bridge.refine_done.emit(v_id, token, qimg, view_hash)

        self._bg_executor.submit(_bg_task)

    def _get_obj_matrix(self, ds) -> np.ndarray:
        """Compute 3x4 object transform matrix."""
        obj_mat = np.array([
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0
        ], dtype=np.float32)

        rx = math.radians(getattr(ds, 'rotation_x_deg', 0.0))
        ry = math.radians(getattr(ds, 'rotation_y_deg', 0.0))
        rz = math.radians(getattr(ds, 'rotation_z_deg', 0.0))
        has_rot = (abs(rx) > 1e-4 or abs(ry) > 1e-4 or abs(rz) > 1e-4)
        has_off = np.any(ds.offset != 0)
        has_scale = (getattr(ds, 'scale', 1.0) != 1.0)

        if has_rot or has_off or has_scale:
            cx_r, sx_r = math.cos(rx), math.sin(rx)
            cy_r, sy_r = math.cos(ry), math.sin(ry)
            cz_r, sz_r = math.cos(rz), math.sin(rz)
            R_obj = np.array([
                [cz_r * cy_r, cz_r * sy_r * sx_r - sz_r * cx_r, cz_r * sy_r * cx_r + sz_r * sx_r],
                [sz_r * cy_r, sz_r * sy_r * sx_r + cz_r * cx_r, sz_r * sy_r * cx_r - cz_r * sx_r],
                [-sy_r, cy_r * sx_r, cy_r * cx_r]
            ], dtype=np.float32) * float(getattr(ds, 'scale', 1.0))

            piv = ds.pivot if ds.pivot is not None else np.zeros(3, dtype=np.float32)
            T = ds.offset + piv - (piv @ R_obj.T)

            obj_mat = np.array([
                R_obj[0, 0], R_obj[0, 1], R_obj[0, 2], T[0],
                R_obj[1, 0], R_obj[1, 1], R_obj[1, 2], T[1],
                R_obj[2, 0], R_obj[2, 1], R_obj[2, 2], T[2]
            ], dtype=np.float32)

        return obj_mat

    @staticmethod
    def _clip_box_mask(coords: np.ndarray, obj_mat: np.ndarray,
                       clip_min: np.ndarray, clip_max: np.ndarray,
                       chunk: int = 2_000_000) -> np.ndarray:
        """Boolean mask of local-space points whose WORLD position lies inside the section box."""
        M = np.asarray(obj_mat, dtype=np.float32).reshape(3, 4)
        R, T = M[:, :3], M[:, 3]
        n = len(coords)
        mask = np.empty(n, dtype=bool)
        for s in range(0, n, chunk):  # chunked to bound temporary memory on huge scans
            world = coords[s:s + chunk] @ R.T + T
            mask[s:s + chunk] = np.all((world >= clip_min) & (world <= clip_max), axis=1)
        return mask

    def _render_selection_bounds(self, viewport, painter: QPainter, datasets) -> None:
        """Draw bounding box if dataset proxy group is selected."""
        sel = getattr(viewport.scene, "selection", ())
        for ds in datasets:
            grp = getattr(ds, "proxy_group", None)
            if grp is not None and grp in sel:
                self._draw_selection_bounds(viewport, painter, ds, grp)

    def _draw_selection_bounds(self, viewport, painter: QPainter, ds, grp) -> None:
        """Draw an informative, clean bounding box around the selected dataset."""
        vertices = getattr(getattr(grp, 'mesh', None), 'vertices', None)
        if not vertices or len(vertices) < 8:
            return

        mat = getattr(viewport, '_preview_matrix', None)
        off = getattr(viewport, '_preview_offset', None)

        corners = np.array(
            [[v.position.x(), v.position.y(), v.position.z()] for v in vertices[:8]],
            dtype=np.float32
        )
        if mat is not None:
            corners = np.array(
                [[mat.map(v.position).x(), mat.map(v.position).y(), mat.map(v.position).z()] for v in vertices[:8]],
                dtype=np.float32
            )
        elif off is not None:
            corners = corners + np.array([off.x(), off.y(), off.z()], dtype=np.float32)

        try:
            if hasattr(viewport, "world_to_pixels"):
                px, py, in_front = viewport.world_to_pixels(corners)
            elif hasattr(self.app, "world_to_pixels"):
                px, py, in_front = self.app.world_to_pixels(corners)
            else:
                return
        except Exception:
            return

        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ]

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(14, 165, 233, 230), 1.5, Qt.DashLine)
        painter.setPen(pen)

        for i1, i2 in edges:
            if in_front[i1] and in_front[i2]:
                if np.isfinite(px[i1]) and np.isfinite(py[i1]) and np.isfinite(px[i2]) and np.isfinite(py[i2]):
                    painter.drawLine(int(px[i1]), int(py[i1]), int(px[i2]), int(py[i2]))

        dot_pen = QPen(QColor(56, 189, 248, 255), 1.0)
        dot_brush = QBrush(QColor(255, 255, 255, 240))
        painter.setPen(dot_pen)
        painter.setBrush(dot_brush)
        for i in range(8):
            if in_front[i] and np.isfinite(px[i]) and np.isfinite(py[i]):
                painter.drawRect(int(px[i]) - 3, int(py[i]) - 3, 6, 6)

        painter.restore()

    def _render_gaussian_splat(
        self,
        ds: GaussianSplatDataset,
        viewport,
        buf: np.ndarray,
        w: int,
        h: int,
        is_moving: bool
    ) -> bool:
        """Render a GaussianSplatDataset with direct zero-copy multithreaded rasterization."""
        pts = ds.coords
        n_splats = len(pts)
        if n_splats == 0:
            return False

        # Camera parameters & view matrix
        cam = getattr(viewport, 'camera', None)
        eye_v = np.zeros(3, dtype=np.float32)
        fwd_v = np.array([0.0, 0.0, -1.0], dtype=np.float32)
        W = np.eye(3, dtype=np.float32)
        fx = float(w)
        fy = float(h)
        cx = float(w * 0.5)
        cy = float(h * 0.5)

        if cam is not None:
            try:
                eye = cam.eye()
                fwd = cam.forward()
                eye_v = np.array([eye.x(), eye.y(), eye.z()], dtype=np.float32)
                fwd_v = np.array([fwd.x(), fwd.y(), fwd.z()], dtype=np.float32)
                vm = cam.view_matrix()
                W = np.array([
                    [vm(0, 0), vm(0, 1), vm(0, 2)],
                    [vm(1, 0), vm(1, 1), vm(1, 2)],
                    [vm(2, 0), vm(2, 1), vm(2, 2)]
                ], dtype=np.float32)
                W_flat = np.array([
                    vm(0, 0), vm(0, 1), vm(0, 2),
                    vm(1, 0), vm(1, 1), vm(1, 2),
                    vm(2, 0), vm(2, 1), vm(2, 2)
                ], dtype=np.float32)

                pm_data = cam.projection_matrix().data()
                fx = float(pm_data[0] * w * 0.5)
                fy = float(pm_data[5] * h * 0.5)
            except Exception as e:
                log.debug(f"Camera matrix extraction error: {e}")
                W_flat = np.eye(3, dtype=np.float32).flatten()

        # Compute dataset object transform matrix (3x4)
        obj_mat = np.array([
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0
        ], dtype=np.float32)

        rx = math.radians(ds.rotation_x_deg)
        ry = math.radians(ds.rotation_y_deg)
        rz = math.radians(ds.rotation_z_deg)
        has_rot = (abs(rx) > 1e-4 or abs(ry) > 1e-4 or abs(rz) > 1e-4)
        has_off = np.any(ds.offset != 0)
        has_scale = (ds.scale != 1.0)

        if has_rot or has_off or has_scale:
            cx_r, sx_r = math.cos(rx), math.sin(rx)
            cy_r, sy_r = math.cos(ry), math.sin(ry)
            cz_r, sz_r = math.cos(rz), math.sin(rz)
            R_obj = np.array([
                [cz_r * cy_r, cz_r * sy_r * sx_r - sz_r * cx_r, cz_r * sy_r * cx_r + sz_r * sx_r],
                [sz_r * cy_r, sz_r * sy_r * sx_r + cz_r * cx_r, sz_r * sy_r * cx_r - cz_r * sx_r],
                [-sy_r, cy_r * sx_r, cy_r * cx_r]
            ], dtype=np.float32) * float(ds.scale)

            piv = ds.pivot if ds.pivot is not None else np.zeros(3, dtype=np.float32)
            # T = offset + pivot - R * pivot
            T = ds.offset + piv - (piv @ R_obj.T)

            obj_mat = np.array([
                R_obj[0, 0], R_obj[0, 1], R_obj[0, 2], T[0],
                R_obj[1, 0], R_obj[1, 1], R_obj[1, 2], T[1],
                R_obj[2, 0], R_obj[2, 1], R_obj[2, 2], T[2]
            ], dtype=np.float32)

        fast_lib = _get_fast_splat_lib()
        budget = 80000 if is_moving else min(getattr(ds, 'max_splats', 1500000), self.max_point_budget)

        clip_p = self._get_section_clip_plane(viewport)
        clip_p_c = clip_p.ctypes.data_as(ctypes.POINTER(ctypes.c_float)) if clip_p is not None else None

        if fast_lib and hasattr(fast_lib, "rasterize_splats_auto"):
            n_drawn = fast_lib.rasterize_splats_auto(
                buf.ctypes.data, w, h, n_splats, budget,
                pts.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ds.scales.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ds.rotations.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ds.colors.ctypes.data,
                obj_mat.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                W_flat.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                eye_v.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                fwd_v[0], fwd_v[1], fwd_v[2],
                fx, fy, cx, cy,
                float(ds.splat_scale), float(ds.opacity),
                0,
                clip_p_c
            )
            return n_drawn > 0

        # Fast camera depth calculation & uint16 stable radix sort fallback
        depths = np.dot(pts - eye_v, fwd_v)
        d_min = float(np.min(depths))
        d_max = float(np.max(depths))
        span = max(1e-4, d_max - d_min)
        q_depths = ((depths - d_min) * (65535.0 / span)).astype(np.uint16)
        order = np.argsort(q_depths, kind='stable')[::-1].astype(np.int32)

        if len(order) > budget:
            stride = max(2, len(order) // budget)
            order = order[::stride].copy()

        n_draw = len(order)
        if n_draw == 0:
            return False

        if fast_lib and hasattr(fast_lib, "rasterize_splats_direct"):
            fast_lib.rasterize_splats_direct(
                buf.ctypes.data,
                w, h, n_draw,
                order.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                pts.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ds.scales.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ds.rotations.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ds.colors.ctypes.data,
                obj_mat.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                W_flat.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                eye_v.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                fx, fy, cx, cy,
                float(ds.splat_scale),
                float(ds.opacity),
                clip_p_c
            )
            return True
        else:
            return self._render_gaussian_splat_fallback(
                buf, w, h, ds, order, eye_v, W, fx, fy, cx, cy
            )

    def _render_gaussian_splat_fallback(
        self,
        buf: np.ndarray,
        w: int,
        h: int,
        ds: GaussianSplatDataset,
        order: np.ndarray,
        eye_v: np.ndarray,
        W: np.ndarray,
        fx: float,
        fy: float,
        cx: float,
        cy: float
    ) -> bool:
        """High-speed Python fallback with perspective scaling and alpha blending."""
        # Cap fallback to 100k splats for responsiveness
        if len(order) > 100000:
            order = order[::(len(order) // 80000)]

        pts = ds.coords[order]
        cam_pts = (pts - eye_v) @ W.T
        z = -cam_pts[:, 2]
        valid = z > 0.1
        if not np.any(valid):
            return False

        px = fx * (cam_pts[valid, 0] / z[valid]) + cx
        py = -fy * (cam_pts[valid, 1] / z[valid]) + cy

        scales = ds.scales[order][valid]
        colors = ds.colors[order][valid]
        mean_scale = np.mean(scales, axis=1) * ds.splat_scale
        radii = np.clip((fx * mean_scale / np.maximum(0.1, z[valid])) * 1.5, 1.0, 32.0).astype(np.int32)

        n_pts = len(px)
        ipx = px.astype(np.int32)
        ipy = py.astype(np.int32)
        opacity_mul = ds.opacity

        for i in range(n_pts):
            r = radii[i]
            x_c, y_c = ipx[i], ipy[i]
            if x_c < -r or x_c >= w + r or y_c < -r or y_c >= h + r:
                continue

            col = colors[i]
            base_alpha = (col[3] / 255.0) * opacity_mul
            if base_alpha < 0.01:
                continue

            r_src, g_src, b_src = col[0], col[1], col[2]
            y0 = max(0, y_c - r)
            y1 = min(h - 1, y_c + r)
            x0 = max(0, x_c - r)
            x1 = min(w - 1, x_c + r)
            if x0 > x1 or y0 > y1:
                continue

            r_sq = (r + 0.5) ** 2
            inv_r_sq = 2.0 / max(1.0, r_sq)

            for y in range(y0, y1 + 1):
                dy = y - y_c
                dy_sq = dy * dy
                for x in range(x0, x1 + 1):
                    dx = x - x_c
                    d_sq = dx * dx + dy_sq
                    if d_sq <= r_sq:
                        alpha = base_alpha * math.exp(-d_sq * inv_r_sq)
                        if alpha < 0.01:
                            continue
                        a_int = int(alpha * 255.0 + 0.5)
                        inv_a = 255 - a_int
                        pix = buf[y, x]
                        pix[0] = (b_src * a_int + pix[0] * inv_a + 127) // 255
                        pix[1] = (g_src * a_int + pix[1] * inv_a + 127) // 255
                        pix[2] = (r_src * a_int + pix[2] * inv_a + 127) // 255
                        pix[3] = (255 * a_int + pix[3] * inv_a + 127) // 255

        return True

    def _extract_colors_raw(
        self,
        coords: np.ndarray,
        stride: int,
        raw_colors: Optional[np.ndarray],
        color_mode: str,
        colormap: str,
        elevation_range: Optional[Tuple[float, float]],
        intensities: Optional[np.ndarray],
        normals: Optional[np.ndarray],
        solid_color: Tuple[int, int, int]
    ) -> np.ndarray:
        """Compute (N, 4) uint8 RGBA point colors in worker thread without accessing dataset properties."""
        n = len(coords)
        mode = color_mode.lower()

        if mode == "rgb" and raw_colors is not None:
            if stride > 1:
                src_cols = raw_colors[::stride]
            else:
                src_cols = raw_colors

            if src_cols.ndim == 2 and src_cols.shape[1] == 4:
                return np.ascontiguousarray(src_cols, dtype=np.uint8)
            elif src_cols.ndim == 2 and src_cols.shape[1] == 3:
                a = np.full((len(src_cols), 1), 255, dtype=np.uint8)
                return np.ascontiguousarray(np.hstack([src_cols, a]), dtype=np.uint8)

        elif mode == "elevation":
            z = coords[:, 2]
            z_min, z_max = elevation_range if elevation_range else (float(np.min(z)), float(np.max(z)))
            span = max(1e-4, z_max - z_min)
            t = np.clip((z - z_min) / span, 0.0, 1.0)
            lut = COLORMAPS.get(colormap, COLORMAPS["turbo"])
            rgb = lut[(t * 255.0).astype(np.int32)]
            a = np.full((n, 1), 255, dtype=np.uint8)
            return np.ascontiguousarray(np.hstack([rgb, a]), dtype=np.uint8)

        elif mode == "intensity" and intensities is not None:
            if stride > 1:
                ints = intensities[::stride]
            else:
                ints = intensities
            i_min, i_max = float(np.min(ints)), float(np.max(ints))
            span = max(1e-4, i_max - i_min)
            t = np.clip((ints - i_min) / span, 0.0, 1.0)
            lut = COLORMAPS.get(colormap, COLORMAPS["turbo"])
            rgb = lut[(t * 255.0).astype(np.int32)]
            a = np.full((n, 1), 255, dtype=np.uint8)
            return np.ascontiguousarray(np.hstack([rgb, a]), dtype=np.uint8)

        elif mode == "normals" and normals is not None:
            if stride > 1:
                norms = normals[::stride]
            else:
                norms = normals
            rgb = np.clip((norms * 0.5 + 0.5) * 255.0, 0, 255).astype(np.uint8)
            a = np.full((n, 1), 255, dtype=np.uint8)
            return np.ascontiguousarray(np.hstack([rgb, a]), dtype=np.uint8)

        sr, sg, sb = solid_color
        return np.ascontiguousarray(np.full((n, 4), [sr, sg, sb, 255], dtype=np.uint8))

    def _extract_colors_for_points(
        self,
        ds: PointCloudDataset,
        coords: np.ndarray,
        stride: int = 1,
        indices: Optional[np.ndarray] = None
    ) -> np.ndarray:
        """Compute (N, 4) uint8 RGBA point colors based on color_mode."""
        raw_colors = ds.colors if indices is None else (ds.colors[indices] if ds.colors is not None else None)
        return self._extract_colors_raw(
            coords, stride if indices is None else 1, raw_colors,
            ds.color_mode, getattr(ds, 'colormap', 'turbo'),
            getattr(ds, 'elevation_range', None),
            ds.intensities if indices is None else (ds.intensities[indices] if ds.intensities is not None else None),
            ds.normals if indices is None else (ds.normals[indices] if ds.normals is not None else None),
            getattr(ds, 'solid_color', (0, 200, 255))
        )

    def _get_interactive_lod(self, ds: PointCloudDataset, target_count: int = 800000) -> Tuple[np.ndarray, np.ndarray]:
        """Retrieve or build cached low-latency LOD arrays for interactive navigation."""
        n_total = len(ds.coords)
        if n_total <= target_count:
            coords = ds.coords
            colors = self._extract_colors_for_points(ds, coords, stride=1)
            return coords, colors

        cache = getattr(ds, '_interactive_lod_cache', None)
        cache_ver = getattr(ds, '_interactive_lod_cache_ver', None)
        current_ver = (n_total, ds.color_mode, getattr(ds, 'colormap', None), target_count)

        if cache is None or cache_ver != current_ver:
            step = max(1, n_total // target_count)
            lod_coords = np.ascontiguousarray(ds.coords[::step])
            lod_colors = self._extract_colors_for_points(ds, lod_coords, stride=step)
            ds._interactive_lod_cache = (lod_coords, lod_colors)
            ds._interactive_lod_cache_ver = current_ver

        return ds._interactive_lod_cache

    def _render_point_cloud(
        self,
        ds: PointCloudDataset,
        viewport,
        buf: np.ndarray,
        w: int,
        h: int,
        is_moving: bool
    ) -> bool:
        """Render a PointCloudDataset into buf."""
        n_pts = len(ds.coords)
        if n_pts == 0:
            return False

        cam = getattr(viewport, 'camera', None)
        if cam is None:
            return False

        try:
            eye = cam.eye()
            eye_v = np.array([eye.x(), eye.y(), eye.z()], dtype=np.float32)
            vm = cam.view_matrix()
            W_flat = np.array([
                vm(0, 0), vm(0, 1), vm(0, 2),
                vm(1, 0), vm(1, 1), vm(1, 2),
                vm(2, 0), vm(2, 1), vm(2, 2)
            ], dtype=np.float32)

            pm_data = cam.projection_matrix().data()
            fx = float(pm_data[0] * w * 0.5)
            fy = float(pm_data[5] * h * 0.5)
            cx = float(w * 0.5)
            cy = float(h * 0.5)
            is_ortho = 1 if (not getattr(cam, 'perspective', True) or abs(pm_data[15] - 1.0) < 0.1) else 0
            clip_p = self._get_section_clip_plane(viewport)
        except Exception as e:
            log.debug(f"Camera extract error in _render_point_cloud: {e}")
            return False

        obj_mat = self._get_obj_matrix(ds)

        # Select points & colors based on movement state
        if is_moving or n_pts > self.max_point_budget:
            sub_coords, sub_colors = self._get_interactive_lod(ds, target_count=800000 if is_moving else 1500000)
        else:
            sub_coords = ds.coords
            sub_colors = self._extract_colors_for_points(ds, sub_coords, stride=1)

        if self.clipping_enabled:
            mask = self._clip_box_mask(sub_coords, obj_mat, self.clip_min, self.clip_max)
            if not np.any(mask):
                return False
            sub_coords = np.ascontiguousarray(sub_coords[mask])
            sub_colors = np.ascontiguousarray(sub_colors[mask])

        fast_lib = _get_fast_splat_lib()
        if fast_lib and hasattr(fast_lib, "rasterize_point_cloud_auto"):
            pt_size = max(1, min(14, int(ds.point_size)))
            clip_p_c = clip_p.ctypes.data_as(ctypes.POINTER(ctypes.c_float)) if clip_p is not None else None
            fast_lib.rasterize_point_cloud_auto(
                buf.ctypes.data,
                w, h, len(sub_coords),
                sub_coords.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                sub_colors.ctypes.data,
                obj_mat.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                W_flat.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                eye_v.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                fx, fy, cx, cy,
                pt_size,
                float(ds.opacity),
                0,
                is_ortho,
                clip_p_c
            )
            return True

        # Fallback pure-Python / CPU projection
        world_pts = ds.apply_transform(sub_coords, viewport)
        if clip_p is not None:
            dist = clip_p[0] * world_pts[:, 0] + clip_p[1] * world_pts[:, 1] + clip_p[2] * world_pts[:, 2] + clip_p[3]
            c_mask = dist >= 0
            if not np.any(c_mask):
                return False
            world_pts = world_pts[c_mask]
            sub_colors = sub_colors[c_mask]
        try:
            if hasattr(viewport, "world_to_pixels"):
                px, py, in_front = viewport.world_to_pixels(world_pts)
            elif hasattr(self.app, "world_to_pixels"):
                px, py, in_front = self.app.world_to_pixels(world_pts)
            else:
                return False
        except Exception as e:
            log.debug(f"world_to_pixels projection error: {e}")
            return False

        pt_size = max(1, min(14, int(ds.point_size)))
        pad = pt_size + 2
        valid = in_front & (px >= pad) & (px < w - pad) & (py >= pad) & (py < h - pad)
        if not np.any(valid):
            return False

        valid_px = px[valid].astype(np.int32)
        valid_py = py[valid].astype(np.int32)
        valid_colors = sub_colors[valid]

        bgra = np.empty_like(valid_colors)
        bgra[:, 0] = valid_colors[:, 2]  # B
        bgra[:, 1] = valid_colors[:, 1]  # G
        bgra[:, 2] = valid_colors[:, 0]  # R
        bgra[:, 3] = (valid_colors[:, 3].astype(np.float32) * ds.opacity).astype(np.uint8)  # A

        if fast_lib and hasattr(fast_lib, "rasterize_points"):
            fast_lib.rasterize_points(
                buf.ctypes.data,
                w, h, len(valid_px),
                valid_px.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
                valid_py.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
                bgra.ctypes.data,
                pt_size
            )
        else:
            self._stamp_points(buf, valid_px, valid_py, bgra, pt_size, w, h)

        return True

    def _stamp_points(
        self,
        buf: np.ndarray,
        px: np.ndarray,
        py: np.ndarray,
        bgra: np.ndarray,
        size: int,
        w: int,
        h: int
    ) -> None:
        """Fallback footprint stamp of points into frame buffer with alpha blending."""
        if size <= 1:
            buf[py, px] = bgra
        elif size == 2:
            py1 = np.clip(py + 1, 0, h - 1)
            px1 = np.clip(px + 1, 0, w - 1)
            buf[py, px] = bgra
            buf[py1, px] = bgra
            buf[py, px1] = bgra
            buf[py1, px1] = bgra
        else:
            r = size // 2
            r_sq = (r + 0.5) ** 2
            for dy in range(-r, r + 1):
                yy = np.clip(py + dy, 0, h - 1)
                for dx in range(-r, r + 1):
                    if dx * dx + dy * dy <= r_sq:
                        xx = np.clip(px + dx, 0, w - 1)
                        buf[yy, xx] = bgra
