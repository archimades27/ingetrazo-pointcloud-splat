# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Point Cloud & 3D Gaussian Splatting extension for IngeTrazo.

Enables importing, visualizing, and interacting with:
- LiDAR / photogrammetry point clouds: .ply, .las, .laz, .xyz, .pts, .txt, .csv
- 3D Gaussian Splatting volumetric models: .ply, .splat
Features:
- High-speed adaptive viewport rendering (up to 60+ FPS with dynamic LOD).
- True Color (RGB / SH), Elevation Colormaps (Turbo, Viridis, Jet, Terrain), Intensity, and Normals.
- 3D Clipping / Section Box for architectural slicing.
- CAD Snapping: locks IngeTrazo's native tools (Line, Tape, Push/Pull) onto point cloud points.
- Scan-to-BIM: RANSAC dominant plane extraction, 3D bounding boxes, and CAD guide points.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import numpy as np

_this_dir = Path(__file__).resolve().parent
_plugins_dir = _this_dir.parent

if str(_plugins_dir) not in sys.path:
    sys.path.insert(0, str(_plugins_dir))
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from tools.base import Tool
from core.i18n import tr

from .renderer import CloudRenderer
from .snap_engine import CloudSnapEngine
from .ui.manager_panel import PointCloudManagerPanel, PointCloudDialog

log = logging.getLogger("ingetrazo.plugins.pointcloud_splat")

_panel_instance: Optional[PointCloudManagerPanel] = None
_dialog_instance: Optional[PointCloudDialog] = None


class PointCloudSplatTool(Tool):
    """Tool registered into IngeTrazo's Extensions menu."""
    name = "Point Cloud & Gaussian Splatting"
    shortcut = "Ctrl+Shift+P"
    description = "Import, inspect, and snap to point clouds (.ply, .las, .xyz) and 3D Gaussian Splats (.splat)."
    uses_snap = False

    def on_activate(self, viewport) -> None:
        global _panel_instance, _dialog_instance
        win = viewport.window() if hasattr(viewport, "window") else None
        
        # Initialize or reuse setup
        if not _panel_instance and win:
            app_handle = getattr(win, "_extension_app_handle", None)
            if app_handle:
                setup(app_handle)

        # If side tray dock exists, show it
        if win and hasattr(win, "_pointcloud_dock"):
            try:
                win._extension_app_handle.show_panel(win._pointcloud_dock)
                return
            except Exception:
                pass

        # Otherwise raise modeless dialog
        if _dialog_instance is None or not _dialog_instance.isVisible():
            if _panel_instance:
                _dialog_instance = PointCloudDialog(_panel_instance, parent=win)
                _dialog_instance.show()
        else:
            _dialog_instance.raise_()
            _dialog_instance.activateWindow()

    def on_deactivate(self, viewport) -> None:
        pass


def setup(app) -> None:
    """Plugin setup hook called at startup by IngeTrazo."""
    global _panel_instance
    try:
        panel = PointCloudManagerPanel(app)
        _panel_instance = panel
        
        # Add to side tray tab
        dock = app.add_panel(tr("Point Clouds & Splats"), panel, panel="pointcloud")
        app.window._pointcloud_dock = dock
        app.window._pointcloud_panel = panel

        # Initialize renderer & snap engine
        renderer = CloudRenderer(app)
        snap_engine = CloudSnapEngine(app)
        app._cloud_renderer = renderer
        app._cloud_snap_engine = snap_engine

        # Hook viewport overlay for point clouds & splats
        def draw_cloud_overlay(vp, painter):
            try:
                r = getattr(app, '_cloud_renderer', renderer)
                p = panel if panel else getattr(getattr(vp, 'window', lambda: None)(), "_pointcloud_panel", None)
                if r and p:
                    r.render(vp, painter, p.datasets)
            except Exception as exc:
                log.exception(f"Overlay draw exception: {exc}")

        draw_cloud_overlay._is_cloud_overlay = True
        app.add_overlay(draw_cloud_overlay)

        # Hook CAD snapping provider
        def snap_cloud_provider(vp, snap, px, py):
            try:
                se = getattr(app, '_cloud_snap_engine', snap_engine)
                p = panel if panel else getattr(getattr(vp, 'window', lambda: None)(), "_pointcloud_panel", None)
                if se and p:
                    return se.snap(vp, snap, px, py, p.datasets)
            except Exception:
                return None

        snap_cloud_provider._is_cloud_snap = True
        app.add_snap_provider(snap_cloud_provider)

        # Ensure Viewport class hooks all split/multi-viewports (Top, Front, Right, Quad, etc.)
        from views.viewport import Viewport
        from PySide6.QtGui import QPainter

        if not hasattr(Viewport, "_orig_draw_ext_pcsplat"):
            Viewport._orig_draw_ext_pcsplat = Viewport._draw_extension_overlays
            def _wrapped_draw_extension_overlays(self, painter):
                Viewport._orig_draw_ext_pcsplat(self, painter)
                if not any(getattr(fn, '_is_cloud_overlay', False) for fn in getattr(self, '_ext_overlays', ())):
                    draw_cloud_overlay(self, painter)
            Viewport._draw_extension_overlays = _wrapped_draw_extension_overlays

        if not hasattr(Viewport, "_orig_ext_snap_pcsplat"):
            Viewport._orig_ext_snap_pcsplat = Viewport._extension_snap
            def _wrapped_extension_snap(self, snap, px_x, px_y):
                res = Viewport._orig_ext_snap_pcsplat(self, snap, px_x, px_y)
                if res is not None:
                    return res
                if not any(getattr(fn, '_is_cloud_snap', False) for fn in getattr(self, '_ext_snap_providers', ())):
                    return snap_cloud_provider(self, snap, px_x, px_y)
                return None
            Viewport._extension_snap = _wrapped_extension_snap

        # Ensure switching to standard views (Top, Front, Right, etc.) frames point clouds
        import math
        from PySide6.QtGui import QVector3D
        from views.main_window import MainWindow

        if not hasattr(MainWindow, "_orig_on_standard_view_pcsplat"):
            MainWindow._orig_on_standard_view_pcsplat = MainWindow._on_standard_view
            def _pcsplat_on_standard_view(self, key):
                MainWindow._orig_on_standard_view_pcsplat(self, key)
                try:
                    if panel and panel.datasets:
                        vp = self.viewport
                        cam = getattr(vp, 'camera', None)
                        if cam is not None and key in ("top", "bottom", "front", "back", "right", "left"):
                            cam.perspective = False
                            all_min = [d.bounds[0] for d in panel.datasets if d.visible]
                            all_max = [d.bounds[1] for d in panel.datasets if d.visible]
                            if all_min and all_max:
                                min_pt = np.min(np.vstack(all_min), axis=0)
                                max_pt = np.max(np.vstack(all_max), axis=0)
                                p0 = QVector3D(float(min_pt[0]), float(min_pt[1]), float(min_pt[2]))
                                p1 = QVector3D(float(max_pt[0]), float(max_pt[1]), float(max_pt[2]))
                                center = QVector3D((p0.x() + p1.x()) * 0.5, (p0.y() + p1.y()) * 0.5, (p0.z() + p1.z()) * 0.5)
                                diag = math.sqrt(float((p1.x() - p0.x()) ** 2 + (p1.y() - p0.y()) ** 2 + (p1.z() - p0.z()) ** 2))
                                tx, ty, tz = cam.target.x(), cam.target.y(), cam.target.z()
                                if (abs(tx - center.x()) > 20 or abs(ty - center.y()) > 20 or abs(tz - center.z()) > 20 or
                                    cam.distance > diag * 2.5 or cam.distance < diag * 0.2):
                                    cam.target = center
                                    cam.distance = max(diag * 0.85, 10.0)
                            vp.update()
                except Exception:
                    pass
            MainWindow._on_standard_view = _pcsplat_on_standard_view

        try:
            import ingetrazo_plugin_ingetrazo_theme_plugin.ui.viewport_manager as vm
            if hasattr(vm, "ViewState") and not hasattr(vm.ViewState, "_orig_frame_scene_pcsplat"):
                vm.ViewState._orig_frame_scene_pcsplat = vm.ViewState._frame_scene
                def _pcsplat_frame_scene(self):
                    if panel and panel.datasets:
                        all_min = [d.bounds[0] for d in panel.datasets if d.visible]
                        all_max = [d.bounds[1] for d in panel.datasets if d.visible]
                        if all_min and all_max:
                            min_pt = np.min(np.vstack(all_min), axis=0)
                            max_pt = np.max(np.vstack(all_max), axis=0)
                            cam = getattr(self.vp, 'camera', None)
                            if cam:
                                p0 = QVector3D(float(min_pt[0]), float(min_pt[1]), float(min_pt[2]))
                                p1 = QVector3D(float(max_pt[0]), float(max_pt[1]), float(max_pt[2]))
                                center = QVector3D((p0.x() + p1.x()) * 0.5, (p0.y() + p1.y()) * 0.5, (p0.z() + p1.z()) * 0.5)
                                diag = math.sqrt(float((p1.x() - p0.x()) ** 2 + (p1.y() - p0.y()) ** 2 + (p1.z() - p0.z()) ** 2))
                                cam.target = center
                                cam.distance = max(diag * 0.85, 10.0)
                                return
                    vm.ViewState._orig_frame_scene_pcsplat(self)
                vm.ViewState._frame_scene = _pcsplat_frame_scene
        except Exception:
            pass

        # Attach to all currently active viewports in the window
        win = getattr(app, 'window', None)
        if win is not None:
            for vp in win.findChildren(Viewport):
                if not hasattr(vp, '_ext_overlays') or vp._ext_overlays is None:
                    vp._ext_overlays = []
                if not any(getattr(fn, '_is_cloud_overlay', False) for fn in vp._ext_overlays):
                    vp._ext_overlays.append(draw_cloud_overlay)
                if not hasattr(vp, '_ext_snap_providers') or vp._ext_snap_providers is None:
                    vp._ext_snap_providers = []
                if not any(getattr(fn, '_is_cloud_snap', False) for fn in vp._ext_snap_providers):
                    vp._ext_snap_providers.append(snap_cloud_provider)
                vp.update()

        # Ensure Viewport.render_image includes extension overlays
        if not hasattr(Viewport, "_orig_render_image_pcsplat"):
            Viewport._orig_render_image_pcsplat = Viewport.render_image
            def _ext_render_image(self, width=1024, height=768, *args, **kwargs):
                img = self._orig_render_image_pcsplat(width, height, *args, **kwargs)
                p = QPainter(img)
                try:
                    if hasattr(self, '_draw_extension_overlays'):
                        self._draw_extension_overlays(p)
                except Exception:
                    pass
                finally:
                    p.end()
                return img
            Viewport.render_image = _ext_render_image

        # File openers: register file extensions so dragging or opening files loads them automatically
        for ext in (".ply", ".splat", ".xyz", ".pts", ".las", ".laz"):
            try:
                app.add_file_opener(ext, panel.load_file)
            except Exception as e:
                log.debug(f"Could not register file opener for {ext}: {e}")

        # Add menu action in Extensions menu
        def summon() -> None:
            app.show_panel(dock)

        app.add_menu_action(
            tr("Point Cloud & Gaussian Splatting…"),
            summon,
            tip=tr("Import and manage point clouds and 3D Gaussian Splats.")
        )

        log.info("[PointCloudSplat] Extension initialized successfully.")
    except Exception as e:
        log.error(f"[PointCloudSplat] Setup failed: {e}", exc_info=True)
