# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Scan-to-CAD and Scan-to-BIM tools for IngeTrazo models."""
from __future__ import annotations

import logging
import math
from typing import Optional, Tuple, Union
import numpy as np

from PySide6.QtGui import QVector3D
from core.group import Group
from core.mesh import Mesh
from core.guide import Guide

from .data_models import PointCloudDataset, GaussianSplatDataset

log = logging.getLogger("ingetrazo.plugins.pointcloud_splat")


def fit_plane_ransac(
    points: np.ndarray,
    max_dist: float = 0.05,
    iterations: int = 80
) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """RANSAC plane fitting on 3D points.
    
    Returns:
        (normal, point_on_plane, inlier_points) or None
    """
    n = len(points)
    if n < 3:
        return None

    best_inliers = None
    best_plane = None
    best_count = 0

    for _ in range(iterations):
        # Pick 3 random points
        idx = np.random.choice(n, 3, replace=False)
        p1, p2, p3 = points[idx[0]], points[idx[1]], points[idx[2]]
        
        v1 = p2 - p1
        v2 = p3 - p1
        normal = np.cross(v1, v2)
        norm_len = np.linalg.norm(normal)
        if norm_len < 1e-6:
            continue
        normal = normal / norm_len

        # Distance from points to plane: |(p - p1) . normal|
        dists = np.abs(np.dot(points - p1, normal))
        inliers = dists <= max_dist
        count = np.sum(inliers)

        if count > best_count:
            best_count = count
            best_inliers = inliers
            best_plane = (normal, p1)

    if best_plane is None or best_count < 10:
        return None

    inlier_pts = points[best_inliers]
    # Refine plane normal via PCA on inliers
    centroid = np.mean(inlier_pts, axis=0)
    cov = np.cov((inlier_pts - centroid).T)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    refined_normal = eigenvectors[:, 0]  # smallest variance axis

    return refined_normal, centroid, inlier_pts


def create_plane_surface_group(
    dataset: Union[PointCloudDataset, GaussianSplatDataset],
    scene,
    name: Optional[str] = None
) -> Optional[Group]:
    """Fit a dominant plane to the dataset points and add it as a native IngeTrazo Group."""
    pts = dataset.coords
    if len(pts) < 10:
        return None

    # Downsample in local space first, then transform only the sample (fast + memory-safe)
    if len(pts) > 20000:
        local_sample = pts[np.random.choice(len(pts), 20000, replace=False)]
    else:
        local_sample = pts
    sample = dataset.apply_transform(local_sample)

    result = fit_plane_ransac(sample, max_dist=0.06, iterations=75)
    if result is None:
        return None

    normal, centroid, inliers = result

    # Find 2D basis on plane
    # Choose arbitrary vector not collinear with normal
    cand = np.array([0, 0, 1], dtype=np.float32) if abs(normal[2]) < 0.9 else np.array([1, 0, 0], dtype=np.float32)
    u_axis = np.cross(normal, cand)
    u_axis = u_axis / np.linalg.norm(u_axis)
    v_axis = np.cross(normal, u_axis)
    v_axis = v_axis / np.linalg.norm(v_axis)

    # Project inliers onto (u, v)
    rel_pts = inliers - centroid
    u_coords = np.dot(rel_pts, u_axis)
    v_coords = np.dot(rel_pts, v_axis)

    u_min, u_max = float(np.percentile(u_coords, 2)), float(np.percentile(u_coords, 98))
    v_min, v_max = float(np.percentile(v_coords, 2)), float(np.percentile(v_coords, 98))

    # 4 corners in 3D
    c0 = centroid + u_min * u_axis + v_min * v_axis
    c1 = centroid + u_max * u_axis + v_min * v_axis
    c2 = centroid + u_max * u_axis + v_max * v_axis
    c3 = centroid + u_min * u_axis + v_max * v_axis

    # Create IngeTrazo Mesh and Face
    m = Mesh()
    f = m.add_face([
        QVector3D(float(c0[0]), float(c0[1]), float(c0[2])),
        QVector3D(float(c1[0]), float(c1[1]), float(c1[2])),
        QVector3D(float(c2[0]), float(c2[1]), float(c2[2])),
        QVector3D(float(c3[0]), float(c3[1]), float(c3[2])),
    ])
    f.attrs["color"] = (0.2, 0.7, 0.9, 0.8)

    grp_name = name or f"Fitted Plane ({dataset.name})"
    grp = Group(m, name=grp_name)
    grp.material = {"color": (0.2, 0.7, 0.9), "opacity": 0.8}
    scene.groups.append(grp)
    return grp


def create_bounding_box_group(
    dataset: Union[PointCloudDataset, GaussianSplatDataset],
    scene,
    name: Optional[str] = None
) -> Group:
    """Create a 3D bounding box wireframe/volume group in IngeTrazo."""
    min_pt, max_pt = dataset.bounds
    x0, y0, z0 = float(min_pt[0]), float(min_pt[1]), float(min_pt[2])
    x1, y1, z1 = float(max_pt[0]), float(max_pt[1]), float(max_pt[2])

    m = Mesh()
    # Bottom face
    f_bottom = m.add_face([
        QVector3D(x0, y0, z0), QVector3D(x1, y0, z0),
        QVector3D(x1, y1, z0), QVector3D(x0, y1, z0)
    ])
    # Top face
    f_top = m.add_face([
        QVector3D(x0, y1, z1), QVector3D(x1, y1, z1),
        QVector3D(x1, y0, z1), QVector3D(x0, y0, z1)
    ])
    # Sides
    m.add_face([QVector3D(x0, y0, z0), QVector3D(x0, y0, z1), QVector3D(x1, y0, z1), QVector3D(x1, y0, z0)])
    m.add_face([QVector3D(x1, y0, z0), QVector3D(x1, y0, z1), QVector3D(x1, y1, z1), QVector3D(x1, y1, z0)])
    m.add_face([QVector3D(x1, y1, z0), QVector3D(x1, y1, z1), QVector3D(x0, y1, z1), QVector3D(x0, y1, z0)])
    m.add_face([QVector3D(x0, y1, z0), QVector3D(x0, y1, z1), QVector3D(x0, y0, z1), QVector3D(x0, y0, z0)])

    grp_name = name or f"Bounds ({dataset.name})"
    grp = Group(m, name=grp_name)
    grp.material = {"color": (0.3, 0.8, 0.4), "opacity": 0.4}
    scene.groups.append(grp)
    return grp


def convert_to_guide_points(
    dataset: Union[PointCloudDataset, GaussianSplatDataset],
    scene,
    max_points: int = 120
) -> int:
    """Downsample point cloud and convert to native IngeTrazo Guide Points."""
    pts = dataset.coords
    if len(pts) == 0:
        return 0

    count = min(len(pts), max_points)
    step = max(1, len(pts) // count)
    sub_pts = dataset.apply_transform(pts[::step][:count])

    for p in sub_pts:
        g = Guide(QVector3D(float(p[0]), float(p[1]), float(p[2])))
        scene.guides.append(g)

    return len(sub_pts)
