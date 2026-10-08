# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Native IngeTrazo Scene Proxy for Point Clouds and Gaussian Splats.

Bridges PointCloudDataset and GaussianSplatDataset with native IngeTrazo scene
entities so that point clouds:
- Can be selected by clicking anywhere on them with IngeTrazo's Select Tool.
- Can be moved natively using IngeTrazo's Move Tool (shortcut M).
- Can be rotated natively using IngeTrazo's Rotate Tool (shortcut Q / R).
- Can be scaled natively using IngeTrazo's Scale Tool (shortcut S).
- Fully integrate with IngeTrazo's Undo/Redo history.
"""
from __future__ import annotations

import logging
import math
from typing import Optional, Tuple, Union
import numpy as np

from PySide6.QtGui import QVector3D
from core.mesh import Mesh
from core.group import Group

log = logging.getLogger("ingetrazo.plugins.pointcloud_splat.scene_proxy")


def create_pointcloud_proxy(dataset, scene) -> Group:
    """Create a native IngeTrazo Group representing the point cloud volume."""
    # Remove existing proxy if any
    old_grp = getattr(dataset, "proxy_group", None)
    if old_grp is not None and old_grp in scene.groups:
        try:
            scene.groups.remove(old_grp)
        except Exception:
            pass

    if dataset._raw_bounds is None:
        if len(dataset.coords) > 0:
            min_p = np.min(dataset.coords, axis=0)
            max_p = np.max(dataset.coords, axis=0)
            dataset._raw_bounds = (min_p, max_p)
        else:
            min_p = np.zeros(3, dtype=np.float32)
            max_p = np.ones(3, dtype=np.float32)
            dataset._raw_bounds = (min_p, max_p)

    min_p, max_p = dataset._raw_bounds
    x0, y0, z0 = float(min_p[0]), float(min_p[1]), float(min_p[2])
    x1, y1, z1 = float(max_p[0]), float(max_p[1]), float(max_p[2])

    # 8 corner vertices of the bounding volume
    c0 = QVector3D(x0, y0, z0)
    c1 = QVector3D(x1, y0, z0)
    c2 = QVector3D(x1, y1, z0)
    c3 = QVector3D(x0, y1, z0)
    c4 = QVector3D(x0, y0, z1)
    c5 = QVector3D(x1, y0, z1)
    c6 = QVector3D(x1, y1, z1)
    c7 = QVector3D(x0, y1, z1)

    m = Mesh()
    # 6 faces with transparent material so points inside are completely visible,
    # but ray-picking (pick_group) instantly hits any click over the point cloud volume.
    # Preserve exact vertex order c0..c7:
    m.add_face([c0, c1, c2, c3])  # Bottom: v0..v3
    m.add_face([c4, c5, c6, c7])  # Top:    v4..v7
    m.add_face([c0, c1, c5, c4])  # Front
    m.add_face([c2, c3, c7, c6])  # Back
    m.add_face([c3, c0, c4, c7])  # Left
    m.add_face([c1, c2, c6, c5])  # Right

    # Hide default OpenGL black wireframe edges so only the point cloud and custom selection outline show
    for e in m.edges:
        e.hidden = True
    m._chunk_dirty = True

    kind = "Gaussian Splat" if getattr(dataset, "is_gaussian_splat", False) else "Point Cloud"
    grp = Group(m, name=f"{kind}: {dataset.name}")
    # Fully transparent faces
    grp.material = {"color": (0.2, 0.6, 0.9), "opacity": 0.0}
    grp.ext = {"type": "pointcloud_proxy", "dataset_name": dataset.name}

    dataset.proxy_group = grp
    scene.groups.append(grp)
    return grp


def remove_pointcloud_proxy(dataset, scene) -> None:
    """Remove proxy group from scene when dataset is removed."""
    grp = getattr(dataset, "proxy_group", None)
    if grp is not None:
        if grp in scene.groups:
            try:
                scene.groups.remove(grp)
            except Exception:
                pass
        if grp in getattr(scene, "selection", ()):
            try:
                scene.selection.discard(grp)
            except Exception:
                pass
        dataset.proxy_group = None


def compute_dataset_transform(dataset, viewport=None) -> Tuple[np.ndarray, np.ndarray]:
    """Computes world rotation matrix R (3x3) and translation T (3,) from proxy group."""
    grp = getattr(dataset, "proxy_group", None)
    if grp is None or dataset._raw_bounds is None:
        # Fallback to manual offset & rotations
        rx = math.radians(dataset.rotation_x_deg)
        ry = math.radians(dataset.rotation_y_deg)
        rz = math.radians(dataset.rotation_z_deg)
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)
        R = np.array([
            [cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
            [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
            [-sy, cy * sx, cy * cx]
        ], dtype=np.float32)
        T = dataset.offset
        return R, T

    vertices = grp.mesh.vertices
    if len(vertices) < 8:
        return np.eye(3, dtype=np.float32), dataset.offset

    min_p, max_p = dataset._raw_bounds
    x0, y0, z0 = float(min_p[0]), float(min_p[1]), float(min_p[2])
    x1, y1, z1 = float(max_p[0]), float(max_p[1]), float(max_p[2])

    raw_corners = np.array([
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]
    ], dtype=np.float32)
    cA = (min_p + max_p) * 0.5

    curr_corners = np.array(
        [[v.position.x(), v.position.y(), v.position.z()] for v in vertices[:8]],
        dtype=np.float32
    )

    # Check live Move / Rotate interactive preview in viewport
    if viewport is not None and hasattr(viewport, 'scene') and grp in getattr(viewport.scene, 'selection', ()):
        mat = getattr(viewport, '_preview_matrix', None)
        off = getattr(viewport, '_preview_offset', None)
        if mat is not None:
            curr_corners = np.array(
                [[mat.map(v.position).x(), mat.map(v.position).y(), mat.map(v.position).z()] for v in vertices[:8]],
                dtype=np.float32
            )
        elif off is not None:
            delta = np.array([off.x(), off.y(), off.z()], dtype=np.float32)
            curr_corners = curr_corners + delta

    cB = np.mean(curr_corners, axis=0)

    P = raw_corners - cA
    Q = curr_corners - cB

    # Kabsch algorithm to find optimal rotation matrix R
    H = P.T @ Q
    try:
        U, S, Vt = np.linalg.svd(H)
        d = np.linalg.det(Vt.T @ U.T)
        R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    except Exception:
        R = np.eye(3, dtype=np.float32)

    T = cB - cA
    return R, T


def sync_proxy_from_dataset(dataset) -> None:
    """Updates proxy group vertices if offset or rotation was modified externally."""
    grp = getattr(dataset, "proxy_group", None)
    if grp is None or dataset._raw_bounds is None:
        return

    vertices = grp.mesh.vertices
    if len(vertices) < 8:
        return

    min_p, max_p = dataset._raw_bounds
    x0, y0, z0 = float(min_p[0]), float(min_p[1]), float(min_p[2])
    x1, y1, z1 = float(max_p[0]), float(max_p[1]), float(max_p[2])

    raw_corners = np.array([
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]
    ], dtype=np.float32)
    piv = dataset.pivot if dataset.pivot is not None else (min_p + max_p) * 0.5

    rx = math.radians(dataset.rotation_x_deg)
    ry = math.radians(dataset.rotation_y_deg)
    rz = math.radians(dataset.rotation_z_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    R = np.array([
        [cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
        [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
        [-sy, cy * sx, cy * cx]
    ], dtype=np.float32)

    target_corners = (raw_corners - piv) @ R.T + piv + dataset.offset
    m = grp.mesh
    for i in range(8):
        v = vertices[i]
        tgt = QVector3D(float(target_corners[i, 0]), float(target_corners[i, 1]), float(target_corners[i, 2]))
        delta = tgt - v.position
        if delta.lengthSquared() > 1e-8:
            m.move_vertex(v, delta)
