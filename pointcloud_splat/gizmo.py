# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Interactive 3D Transform Gizmo and Viewport Manipulator for Point Clouds and Splats."""
from __future__ import annotations

import logging
import math
from typing import List, Optional, Tuple, Union
import numpy as np

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QVector3D,
)

from .data_models import PointCloudDataset, GaussianSplatDataset

log = logging.getLogger("ingetrazo.plugins.pointcloud_splat")


class TransformGizmo(QObject):
    """3D viewport manipulator allowing direct translation and rotation of point clouds."""

    def __init__(self, app, panel) -> None:
        super().__init__()
        self.app = app
        self.panel = panel
        self.enabled: bool = True
        self.mode: str = "both"  # "both", "translate", "rotate"
        
        # State
        self.hover_handle: Optional[str] = None      # "x", "y", "z", "plane_xy", "rot_z", "rot_x", "rot_y"
        self.active_handle: Optional[str] = None     # handle currently being dragged
        
        # Drag initial values
        self.drag_start_screen: Optional[Tuple[float, float]] = None
        self.drag_start_hit: Optional[QVector3D] = None
        self.drag_start_center: Optional[QVector3D] = None
        self.initial_offset: Optional[np.ndarray] = None
        self.initial_rot_x: float = 0.0
        self.initial_rot_y: float = 0.0
        self.initial_rot_z: float = 0.0
        self.start_angle_rad: float = 0.0
        self.start_screen_angle: float = 0.0

        # Screen geometry cache for hit-testing
        self._cache_center_px: Optional[QPointF] = None
        self._cache_x_tip: Optional[QPointF] = None
        self._cache_y_tip: Optional[QPointF] = None
        self._cache_z_tip: Optional[QPointF] = None
        self._cache_plane_poly: Optional[QPolygonF] = None
        self._cache_ring_pts: List[QPointF] = []
        self._cache_rot_x_pts: List[QPointF] = []
        self._cache_rot_y_pts: List[QPointF] = []

    @property
    def active_dataset(self) -> Optional[Union[PointCloudDataset, GaussianSplatDataset]]:
        idx = getattr(self.panel, "_active_idx", -1)
        if 0 <= idx < len(self.panel.datasets):
            ds = self.panel.datasets[idx]
            if ds.visible and len(ds.coords) > 0:
                return ds
        return None

    def get_centroid(self, ds) -> np.ndarray:
        """Returns the world-space center of the dataset."""
        piv = ds.pivot if getattr(ds, "pivot", None) is not None else np.zeros(3, dtype=np.float32)
        return (piv + ds.offset).astype(np.float32)

    # ---- Viewport Event Filter ----------------------------------------------

    def eventFilter(self, obj, event: QEvent) -> bool:
        if not self.enabled:
            return False

        ds = self.active_dataset
        if ds is None:
            return False

        ev_type = event.type()

        if ev_type == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            pos = event.position()
            handle = self.hit_test(obj, pos.x(), pos.y())
            if handle is not None:
                self._start_drag(obj, handle, pos.x(), pos.y(), ds)
                return True

        elif ev_type == QEvent.MouseMove:
            pos = event.position()
            if self.active_handle is not None:
                shift_held = bool(event.modifiers() & Qt.ShiftModifier)
                self._update_drag(obj, pos.x(), pos.y(), ds, shift_held)
                return True
            else:
                handle = self.hit_test(obj, pos.x(), pos.y())
                if handle != self.hover_handle:
                    self.hover_handle = handle
                    if handle is not None:
                        obj.setCursor(Qt.OpenHandCursor)
                    else:
                        obj.unsetCursor()
                    obj.update()

        elif ev_type == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self.active_handle is not None:
                self._end_drag(obj, ds)
                return True

        return False

    # ---- Drag Handlers ------------------------------------------------------

    def _start_drag(self, viewport, handle: str, px: float, py: float, ds) -> None:
        self.active_handle = handle
        self.drag_start_screen = (px, py)
        self.initial_offset = ds.offset.copy()
        self.initial_rot_x = ds.rotation_x_deg
        self.initial_rot_y = ds.rotation_y_deg
        self.initial_rot_z = ds.rotation_z_deg

        c_world = self.get_centroid(ds)
        self.drag_start_center = QVector3D(float(c_world[0]), float(c_world[1]), float(c_world[2]))

        cam = getattr(viewport, 'camera', None)
        cam_fwd = cam.forward() if cam and hasattr(cam, 'forward') else QVector3D(0, 0, -1)

        ray_orig, ray_dir = viewport._pixel_to_ray(px, py)
        if ray_orig and ray_dir:
            if handle in ("plane_xy", "rot_z"):
                hit = viewport._ray_plane(ray_orig, ray_dir, self.drag_start_center, QVector3D(0, 0, 1))
            elif handle == "rot_x":
                hit = viewport._ray_plane(ray_orig, ray_dir, self.drag_start_center, QVector3D(1, 0, 0))
            elif handle == "rot_y":
                hit = viewport._ray_plane(ray_orig, ray_dir, self.drag_start_center, QVector3D(0, 1, 0))
            else:
                hit = viewport._ray_plane(ray_orig, ray_dir, self.drag_start_center, cam_fwd)
            self.drag_start_hit = hit or self.drag_start_center
        else:
            self.drag_start_hit = self.drag_start_center

        if handle == "rot_z" and self.drag_start_hit:
            hx = self.drag_start_hit.x() - c_world[0]
            hy = self.drag_start_hit.y() - c_world[1]
            self.start_angle_rad = math.atan2(hy, hx)
        elif handle == "rot_x" and self.drag_start_hit:
            hy = self.drag_start_hit.y() - c_world[1]
            hz = self.drag_start_hit.z() - c_world[2]
            self.start_angle_rad = math.atan2(hz, hy)
        elif handle == "rot_y" and self.drag_start_hit:
            hx = self.drag_start_hit.x() - c_world[0]
            hz = self.drag_start_hit.z() - c_world[2]
            self.start_angle_rad = math.atan2(hz, hx)

        if self._cache_center_px is not None:
            self.start_screen_angle = math.atan2(py - self._cache_center_px.y(), px - self._cache_center_px.x())

        viewport.setCursor(Qt.ClosedHandCursor)
        viewport.update()

    def _update_drag(self, viewport, px: float, py: float, ds, shift_held: bool) -> None:
        cam = getattr(viewport, 'camera', None)
        cam_fwd = cam.forward() if cam and hasattr(cam, 'forward') else QVector3D(0, 0, -1)
        ray_orig, ray_dir = viewport._pixel_to_ray(px, py)
        if not (ray_orig and ray_dir and self.drag_start_center and self.drag_start_hit):
            return

        handle = self.active_handle
        c_world = self.get_centroid(ds)

        if handle in ("x", "y", "z"):
            hit = viewport._ray_plane(ray_orig, ray_dir, self.drag_start_center, cam_fwd)
            if hit is None:
                return
            delta_v = hit - self.drag_start_hit
            axis_vec = {
                "x": np.array([1.0, 0.0, 0.0], dtype=np.float32),
                "y": np.array([0.0, 1.0, 0.0], dtype=np.float32),
                "z": np.array([0.0, 0.0, 1.0], dtype=np.float32),
            }[handle]

            cam_fwd_np = np.array([cam_fwd.x(), cam_fwd.y(), cam_fwd.z()], dtype=np.float32)
            v_proj = axis_vec - np.dot(axis_vec, cam_fwd_np) * cam_fwd_np
            len_sq = float(np.dot(v_proj, v_proj))
            delta_np = np.array([delta_v.x(), delta_v.y(), delta_v.z()], dtype=np.float32)

            if len_sq > 0.03:
                disp = float(np.dot(delta_np, v_proj) / len_sq)
            else:
                disp = float(np.dot(delta_np, axis_vec))

            if shift_held:
                disp = round(disp * 4.0) / 4.0  # snap to 0.25m
            ds.offset = self.initial_offset + axis_vec * disp

        elif handle == "plane_xy":
            hit = viewport._ray_plane(ray_orig, ray_dir, self.drag_start_center, QVector3D(0, 0, 1))
            if hit is None:
                return
            dx = float(hit.x() - self.drag_start_hit.x())
            dy = float(hit.y() - self.drag_start_hit.y())
            if shift_held:
                dx = round(dx * 4.0) / 4.0
                dy = round(dy * 4.0) / 4.0
            ds.offset = self.initial_offset + np.array([dx, dy, 0.0], dtype=np.float32)

        elif handle == "rot_z":
            hit = viewport._ray_plane(ray_orig, ray_dir, self.drag_start_center, QVector3D(0, 0, 1))
            if hit is not None:
                hx = hit.x() - c_world[0]
                hy = hit.y() - c_world[1]
                curr_rad = math.atan2(hy, hx)
                delta_rad = curr_rad - self.start_angle_rad
                delta_deg = math.degrees(delta_rad)
            elif self._cache_center_px is not None:
                curr_screen = math.atan2(py - self._cache_center_px.y(), px - self._cache_center_px.x())
                delta_rad = curr_screen - self.start_screen_angle
                sign = -1.0 if (cam and hasattr(cam, 'pitch') and cam.pitch > 0) else 1.0
                delta_deg = math.degrees(delta_rad) * sign
            else:
                return

            if shift_held:
                delta_deg = round(delta_deg / 15.0) * 15.0
            ds.rotation_z_deg = (self.initial_rot_z + delta_deg) % 360.0

        elif handle == "rot_x":
            hit = viewport._ray_plane(ray_orig, ray_dir, self.drag_start_center, QVector3D(1, 0, 0))
            if hit is not None:
                hy = hit.y() - c_world[1]
                hz = hit.z() - c_world[2]
                curr_rad = math.atan2(hz, hy)
                delta_deg = math.degrees(curr_rad - self.start_angle_rad)
            elif self.drag_start_screen:
                dy_px = py - self.drag_start_screen[1]
                delta_deg = dy_px * 0.4
            else:
                return

            if shift_held:
                delta_deg = round(delta_deg / 15.0) * 15.0
            ds.rotation_x_deg = (self.initial_rot_x + delta_deg) % 360.0

        elif handle == "rot_y":
            hit = viewport._ray_plane(ray_orig, ray_dir, self.drag_start_center, QVector3D(0, 1, 0))
            if hit is not None:
                hx = hit.x() - c_world[0]
                hz = hit.z() - c_world[2]
                curr_rad = math.atan2(hz, hx)
                delta_deg = math.degrees(curr_rad - self.start_angle_rad)
            elif self.drag_start_screen:
                dy_px = py - self.drag_start_screen[1]
                delta_deg = dy_px * 0.4
            else:
                return

            if shift_held:
                delta_deg = round(delta_deg / 15.0) * 15.0
            ds.rotation_y_deg = (self.initial_rot_y + delta_deg) % 360.0

        # Update UI spinboxes smoothly without feedback loops
        self.panel._sync_ui_state()
        viewport.update()

    def _end_drag(self, viewport, ds) -> None:
        self.active_handle = None
        viewport.unsetCursor()
        viewport.update()
        if hasattr(viewport, "flash_status"):
            ox, oy, oz = ds.offset
            viewport.flash_status(
                f"Transformed {ds.name}: Offset ({ox:.2f}, {oy:.2f}, {oz:.2f} m) | Rot Z: {ds.rotation_z_deg:.1f}°"
            )

    # ---- Hit Testing --------------------------------------------------------

    def hit_test(self, viewport, mx: float, my: float) -> Optional[str]:
        """Returns the handle name under screen coordinates (mx, my) or None."""
        if self._cache_center_px is None or not (self.enabled and self.active_dataset):
            return None

        p_cursor = QPointF(mx, my)
        c = self._cache_center_px
        dist_c = math.hypot(mx - c.x(), my - c.y())

        # 1. Plane handle (inside XY ground quad or within 14 px of center)
        if self.mode in ("both", "translate"):
            if self._cache_plane_poly is not None and self._cache_plane_poly.containsPoint(p_cursor, Qt.OddEvenFill):
                return "plane_xy"
            if dist_c <= 12.0:
                return "plane_xy"

        # 2. Z Rotation ring (distance to projected 3D ring segments <= 9 px)
        if self.mode in ("both", "rotate") and len(self._cache_ring_pts) >= 12:
            d_ring = self._dist_to_polyline(p_cursor, self._cache_ring_pts, closed=True)
            if d_ring <= 8.5:
                return "rot_z"

        # 3. X & Y Rotation rings (in rotate mode)
        if self.mode == "rotate":
            if len(self._cache_rot_x_pts) >= 8:
                if self._dist_to_polyline(p_cursor, self._cache_rot_x_pts, closed=True) <= 8.0:
                    return "rot_x"
            if len(self._cache_rot_y_pts) >= 8:
                if self._dist_to_polyline(p_cursor, self._cache_rot_y_pts, closed=True) <= 8.0:
                    return "rot_y"

        # 4. Translation axes (X, Y, Z)
        if self.mode in ("both", "translate"):
            for name, tip in (("x", self._cache_x_tip), ("y", self._cache_y_tip), ("z", self._cache_z_tip)):
                if tip is not None:
                    d_seg = self._dist_to_segment(p_cursor, c, tip)
                    if d_seg <= 9.0:
                        return name

        return None

    @staticmethod
    def _dist_to_segment(p: QPointF, a: QPointF, b: QPointF) -> float:
        abx = b.x() - a.x()
        aby = b.y() - a.y()
        len_sq = abx * abx + aby * aby
        if len_sq < 1e-4:
            return math.hypot(p.x() - a.x(), p.y() - a.y())
        t = max(0.0, min(1.0, ((p.x() - a.x()) * abx + (p.y() - a.y()) * aby) / len_sq))
        proj_x = a.x() + t * abx
        proj_y = a.y() + t * aby
        return math.hypot(p.x() - proj_x, p.y() - proj_y)

    @staticmethod
    def _dist_to_polyline(p: QPointF, poly_pts: List[QPointF], closed: bool = True) -> float:
        min_d = 1e9
        n = len(poly_pts)
        count = n if closed else n - 1
        for i in range(count):
            p1 = poly_pts[i]
            p2 = poly_pts[(i + 1) % n]
            d = TransformGizmo._dist_to_segment(p, p1, p2)
            if d < min_d:
                min_d = d
        return min_d

    # ---- Drawing ------------------------------------------------------------

    def draw(self, viewport, painter: QPainter) -> None:
        """Draw the 3D Transform Gizmo over the viewport."""
        if not self.enabled:
            return

        ds = self.active_dataset
        if ds is None:
            self._cache_center_px = None
            return

        c_world = self.get_centroid(ds)
        cam = getattr(viewport, 'camera', None)
        if cam is None:
            return

        # Determine world arm length based on distance to camera
        eye = cam.eye()
        cam_dist = math.hypot(c_world[0] - eye.x(), c_world[1] - eye.y(), c_world[2] - eye.z())
        arm_world = max(0.3, cam_dist * 0.16)

        # 3D points for axes: center, X tip, Y tip, Z tip
        pts_3d = np.array([
            c_world,
            c_world + np.array([arm_world, 0.0, 0.0], dtype=np.float32),
            c_world + np.array([0.0, arm_world, 0.0], dtype=np.float32),
            c_world + np.array([0.0, 0.0, arm_world], dtype=np.float32),
        ], dtype=np.float32)

        try:
            px, py, in_front = self.app.world_to_pixels(pts_3d)
        except Exception:
            return

        if not in_front[0]:
            self._cache_center_px = None
            return

        c_px = QPointF(float(px[0]), float(py[0]))
        x_px = QPointF(float(px[1]), float(py[1])) if in_front[1] else None
        y_px = QPointF(float(px[2]), float(py[2])) if in_front[2] else None
        z_px = QPointF(float(px[3]), float(py[3])) if in_front[3] else None

        self._cache_center_px = c_px
        self._cache_x_tip = x_px
        self._cache_y_tip = y_px
        self._cache_z_tip = z_px

        # Compute 3D Z-rotation ring points
        r_ring = arm_world * 0.88
        t_samples = np.linspace(0, 2 * np.pi, 36, endpoint=False)
        ring_3d = np.column_stack([
            c_world[0] + r_ring * np.cos(t_samples),
            c_world[1] + r_ring * np.sin(t_samples),
            np.full_like(t_samples, c_world[2])
        ]).astype(np.float32)

        try:
            r_px, r_py, r_front = self.app.world_to_pixels(ring_3d)
            if np.all(r_front):
                self._cache_ring_pts = [QPointF(float(x), float(y)) for x, y in zip(r_px, r_py)]
            else:
                self._cache_ring_pts = []
        except Exception:
            self._cache_ring_pts = []

        # If in rotate mode, compute X and Y 3D rotation rings
        if self.mode == "rotate":
            rx_3d = np.column_stack([
                np.full_like(t_samples, c_world[0]),
                c_world[1] + r_ring * np.cos(t_samples),
                c_world[2] + r_ring * np.sin(t_samples),
            ]).astype(np.float32)
            ry_3d = np.column_stack([
                c_world[0] + r_ring * np.cos(t_samples),
                np.full_like(t_samples, c_world[1]),
                c_world[2] + r_ring * np.sin(t_samples),
            ]).astype(np.float32)
            try:
                rx_p, ry_p, f_x = self.app.world_to_pixels(rx_3d)
                self._cache_rot_x_pts = [QPointF(float(x), float(y)) for x, y in zip(rx_p, ry_p)] if np.all(f_x) else []
                rx_py, ry_py, f_y = self.app.world_to_pixels(ry_3d)
                self._cache_rot_y_pts = [QPointF(float(x), float(y)) for x, y in zip(rx_py, ry_py)] if np.all(f_y) else []
            except Exception:
                self._cache_rot_x_pts = []
                self._cache_rot_y_pts = []

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        active = self.active_handle or self.hover_handle

        # 1. Draw Rotation Rings
        if self.mode in ("both", "rotate") and len(self._cache_ring_pts) >= 12:
            is_ring_act = (active == "rot_z")
            ring_col = QColor("#facc15") if is_ring_act else QColor("#06b6d4")
            painter.setPen(QPen(ring_col, 3.2 if is_ring_act else 2.0, Qt.SolidLine))
            painter.setBrush(Qt.NoBrush)
            poly_ring = QPolygonF(self._cache_ring_pts)
            painter.drawPolygon(poly_ring)

            # Draw radial ticks around ring
            painter.setPen(QPen(ring_col, 1.4))
            for i in range(12):
                idx = (i * 3) % len(self._cache_ring_pts)
                pt = self._cache_ring_pts[idx]
                dx = pt.x() - c_px.x()
                dy = pt.y() - c_px.y()
                dist = math.hypot(dx, dy)
                if dist > 1e-3:
                    ux = dx / dist
                    uy = dy / dist
                    p_in = QPointF(pt.x() - 4 * ux, pt.y() - 4 * uy)
                    p_out = QPointF(pt.x() + 4 * ux, pt.y() + 4 * uy)
                    painter.drawLine(p_in, p_out)

        # Draw X and Y rings if in rotate mode
        if self.mode == "rotate":
            if len(self._cache_rot_x_pts) >= 12:
                is_x_act = (active == "rot_x")
                col_rx = QColor("#facc15") if is_x_act else QColor(239, 68, 68, 190)
                painter.setPen(QPen(col_rx, 2.8 if is_x_act else 1.8))
                painter.drawPolygon(QPolygonF(self._cache_rot_x_pts))

            if len(self._cache_rot_y_pts) >= 12:
                is_y_act = (active == "rot_y")
                col_ry = QColor("#facc15") if is_y_act else QColor(16, 185, 129, 190)
                painter.setPen(QPen(col_ry, 2.8 if is_y_act else 1.8))
                painter.drawPolygon(QPolygonF(self._cache_rot_y_pts))

        # 2. Draw Translation Plane Handle (XY ground quad)
        if self.mode in ("both", "translate") and x_px and y_px:
            is_plane_act = (active == "plane_xy")
            plane_fill = QColor(245, 158, 11, 220) if is_plane_act else QColor(245, 158, 11, 60)
            v_x = (x_px - c_px) * 0.32
            v_y = (y_px - c_px) * 0.32
            poly = QPolygonF([c_px, c_px + v_x, c_px + v_x + v_y, c_px + v_y])
            self._cache_plane_poly = poly
            painter.setPen(QPen(QColor(245, 158, 11), 2.0 if is_plane_act else 1.2))
            painter.setBrush(QBrush(plane_fill))
            painter.drawPolygon(poly)
        else:
            self._cache_plane_poly = None

        # 3. Draw Translation Axes (X, Y, Z)
        if self.mode in ("both", "translate"):
            axes = [
                ("x", x_px, QColor("#ef4444"), "X"),
                ("y", y_px, QColor("#10b981"), "Y"),
                ("z", z_px, QColor("#3b82f6"), "Z"),
            ]
            font = QFont("Helvetica", 9, QFont.Bold)
            painter.setFont(font)

            for name, tip, col, label in axes:
                if tip is None:
                    continue
                is_act = (active == name)
                draw_col = QColor("#facc15") if is_act else col
                width = 3.6 if is_act else 2.2
                painter.setPen(QPen(draw_col, width))
                painter.drawLine(c_px, tip)

                # Draw arrowhead cone
                dx = tip.x() - c_px.x()
                dy = tip.y() - c_px.y()
                ang = math.atan2(dy, dx)
                head_len = 12.0
                head_w = 5.0
                left = QPointF(tip.x() - head_len * math.cos(ang) + head_w * math.sin(ang),
                               tip.y() - head_len * math.sin(ang) - head_w * math.cos(ang))
                right = QPointF(tip.x() - head_len * math.cos(ang) - head_w * math.sin(ang),
                                tip.y() - head_len * math.sin(ang) + head_w * math.cos(ang))
                painter.setBrush(QBrush(draw_col))
                painter.drawPolygon(QPolygonF([tip, left, right]))

                # Label
                painter.setPen(QPen(draw_col))
                lbl_pos = QPointF(tip.x() + 8 * math.cos(ang), tip.y() + 8 * math.sin(ang) + 4)
                painter.drawText(lbl_pos, label)

        # 4. Center origin point
        painter.setPen(QPen(QColor("#ffffff"), 1.2))
        painter.setBrush(QBrush(QColor("#f59e0b") if active == "plane_xy" else QColor("#ffffff")))
        painter.drawEllipse(c_px, 4.0, 4.0)

        # 5. Live HUD tooltip when dragging
        if self.active_handle is not None and self.drag_start_screen:
            self._draw_hud_badge(painter, c_px, ds)

        painter.restore()

    def _draw_hud_badge(self, painter: QPainter, c_px: QPointF, ds) -> None:
        """Draw an informative HUD pill showing live coordinate / angle changes."""
        handle = self.active_handle
        if handle in ("x", "y", "z"):
            val = {"x": ds.offset[0], "y": ds.offset[1], "z": ds.offset[2]}[handle]
            text = f"Δ{handle.upper()}: {val:+.2f} m  (Shift: 0.25m snap)"
        elif handle == "plane_xy":
            text = f"X: {ds.offset[0]:+.2f} m, Y: {ds.offset[1]:+.2f} m  (Shift: 0.25m snap)"
        elif handle == "rot_z":
            text = f"Rot Z: {ds.rotation_z_deg:.1f}°  (Shift: 15° snap)"
        elif handle in ("rot_x", "rot_y"):
            val = ds.rotation_x_deg if handle == "rot_x" else ds.rotation_y_deg
            text = f"Rot {handle[-1].upper()}: {val:.1f}°  (Shift: 15° snap)"
        else:
            return

        box_x = c_px.x() + 20
        box_y = c_px.y() - 32
        rect = QRectF(box_x, box_y, len(text) * 7.5 + 20, 24)

        painter.setPen(QPen(QColor(14, 165, 233, 220), 1.0))
        painter.setBrush(QBrush(QColor(15, 23, 42, 230)))
        painter.drawRoundedRect(rect, 5, 5)

        painter.setPen(QPen(QColor("#f8fafc")))
        font = QFont("Monospace", 9, QFont.Bold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, text)
