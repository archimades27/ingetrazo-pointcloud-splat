# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Snapping engine that allows IngeTrazo CAD tools to snap to point clouds."""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple, Union
import numpy as np

from PySide6.QtGui import QVector3D
from core.snap import SnapResult

from .data_models import PointCloudDataset, GaussianSplatDataset

log = logging.getLogger("ingetrazo.plugins.pointcloud_splat")


class CloudSnapEngine:
    """Provides CAD snapping for points inside active point clouds."""

    def __init__(self, app) -> None:
        self.app = app
        self.enabled: bool = True
        self.snap_radius_px: float = 14.0
        self.last_hovered_pt: Optional[Tuple[float, float, float]] = None

        # Camera & projected points cache per viewport to eliminate mouse-move lag
        self._vp_cached_cam_hash: dict[int, int] = {}
        self._vp_cached_entries: dict[int, List[Tuple[np.ndarray, np.ndarray, np.ndarray]]] = {}

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

    def _get_cam_hash(self, viewport) -> int:
        cam = getattr(viewport, 'camera', None)
        if cam is None:
            return 0
        target = getattr(cam, 'target', None)
        tx = getattr(target, 'x', lambda: 0.0)() if target else 0.0
        ty = getattr(target, 'y', lambda: 0.0)() if target else 0.0
        tz = getattr(target, 'z', lambda: 0.0)() if target else 0.0

        clip_p = self._get_section_clip_plane(viewport)
        clip_hash = tuple(np.round(clip_p, 3)) if clip_p is not None else None

        return hash((
            round(getattr(cam, 'yaw', 0.0), 4),
            round(getattr(cam, 'pitch', 0.0), 4),
            round(getattr(cam, 'distance', 0.0), 3),
            round(tx, 3), round(ty, 3), round(tz, 3),
            getattr(cam, 'perspective', True),
            clip_hash,
            viewport.width(), viewport.height()
        ))

    @staticmethod
    def _datasets_token(datasets) -> tuple:
        """Cheap fingerprint of dataset transforms so moved clouds invalidate the snap cache."""
        tok = []
        for ds in datasets:
            grp = getattr(ds, "proxy_group", None)
            corner = None
            verts = getattr(getattr(grp, "mesh", None), "vertices", None) if grp is not None else None
            if verts:
                try:
                    p0, p6 = verts[0].position, verts[min(6, len(verts) - 1)].position
                    corner = (round(p0.x(), 4), round(p0.y(), 4), round(p0.z(), 4),
                              round(p6.x(), 4), round(p6.y(), 4), round(p6.z(), 4))
                except Exception:
                    corner = None
            off = getattr(ds, "offset", None)
            tok.append((
                id(ds), len(ds.coords),
                off.tobytes() if hasattr(off, "tobytes") else None,
                round(float(getattr(ds, "rotation_x_deg", 0.0)), 4),
                round(float(getattr(ds, "rotation_y_deg", 0.0)), 4),
                round(float(getattr(ds, "rotation_z_deg", 0.0)), 4),
                float(getattr(ds, "scale", 1.0)),
                corner,
            ))
        return tuple(tok)

    def snap(
        self,
        viewport,
        snap: Optional[SnapResult],
        px: int,
        py: int,
        datasets: List[Union[PointCloudDataset, GaussianSplatDataset]]
    ) -> Optional[SnapResult]:
        """Check if (px, py) is near any point cloud point; return SnapResult if so."""
        if not self.enabled:
            return None

        # Only snap to discrete LiDAR / point clouds, not continuous 3D Gaussian Splats
        visible_pc = [
            d for d in datasets
            if (type(d).__name__ == "PointCloudDataset" or isinstance(d, PointCloudDataset))
            and d.visible and len(d.coords) > 0
        ]
        if not visible_pc:
            return None

        w = viewport.width()
        h = viewport.height()
        if px < 0 or px >= w or py < 0 or py >= h:
            return None

        v_id = id(viewport)
        cam_hash = hash((self._get_cam_hash(viewport), self._datasets_token(visible_pc)))
        if cam_hash != self._vp_cached_cam_hash.get(v_id):
            self._vp_cached_cam_hash[v_id] = cam_hash
            entries = []
            clip_plane = self._get_section_clip_plane(viewport)

            for ds in visible_pc:
                pts = ds.coords
                if len(pts) == 0:
                    continue

                # Subsample candidates BEFORE applying transform to avoid memory exhaustion
                cand_sub = getattr(ds, '_snap_candidates', None)
                if cand_sub is None or len(cand_sub) == 0:
                    if len(pts) > 30000:
                        step = max(1, len(pts) // 25000)
                        cand_sub = np.ascontiguousarray(pts[::step])
                    else:
                        cand_sub = pts
                    ds._snap_candidates = cand_sub

                cand_pts = ds.apply_transform(cand_sub, viewport)

                try:
                    w2p = getattr(viewport, 'world_to_pixels', None) or getattr(self.app, 'world_to_pixels', None)
                    if w2p is None:
                        continue
                    screen_x, screen_y, in_front = w2p(cand_pts)
                    valid = in_front & (screen_x >= -20) & (screen_x < w + 20) & (screen_y >= -20) & (screen_y < h + 20)

                    # Do not snap to points hidden by the active section plane cut
                    if clip_plane is not None and np.any(valid):
                        nx, ny, nz, d = clip_plane
                        dist = nx * cand_pts[:, 0] + ny * cand_pts[:, 1] + nz * cand_pts[:, 2] + d
                        valid = valid & (dist >= 0.0)

                    if np.any(valid):
                        entries.append((
                            screen_x[valid], screen_y[valid], cand_pts[valid]
                        ))
                except Exception:
                    continue

            self._vp_cached_entries[v_id] = entries

        cached_entries = self._vp_cached_entries.get(v_id, [])
        if not cached_entries:
            return None

        best_dist_sq = self.snap_radius_px * self.snap_radius_px
        best_pt_world = None

        for screen_x, screen_y, cand_pts in cached_entries:
            dx = screen_x - px
            dy = screen_y - py
            dist_sq = dx * dx + dy * dy

            mask = dist_sq <= best_dist_sq
            if np.any(mask):
                valid_indices = np.nonzero(mask)[0]
                closest_idx = valid_indices[np.argmin(dist_sq[valid_indices])]
                best_dist_sq = float(dist_sq[closest_idx])
                best_pt_world = cand_pts[closest_idx]

        if best_pt_world is not None:
            wx, wy, wz = float(best_pt_world[0]), float(best_pt_world[1]), float(best_pt_world[2])
            self.last_hovered_pt = (wx, wy, wz)

            return SnapResult(
                point=QVector3D(wx, wy, wz),
                kind="pointcloud",
                color=(0.1, 0.8, 1.0),
                label=f"Point ({wx:.2f}, {wy:.2f}, {wz:.2f} m)"
            )

        return None
