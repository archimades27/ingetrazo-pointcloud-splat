# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Synthetic sample generator for Point Clouds and 3D Gaussian Splats."""
from __future__ import annotations

import math
import numpy as np

from ..data_models import PointCloudDataset, GaussianSplatDataset


def generate_demo_pointcloud() -> PointCloudDataset:
    """Generate a realistic architectural pavilion LiDAR scan (~45,000 points).
    
    Includes ground slab, 4 circular columns, perimeter walls with door/window openings,
    a vaulted canopy roof, and realistic LiDAR sensor noise (+/- 2mm).
    """
    pts_list = []
    col_list = []
    
    # 1. Ground floor slab (12m x 8m with tile grid)
    gx = np.linspace(-6.0, 6.0, 110)
    gy = np.linspace(-4.0, 4.0, 80)
    g_grid_x, g_grid_y = np.meshgrid(gx, gy)
    g_pts = np.column_stack([
        g_grid_x.ravel(),
        g_grid_y.ravel(),
        np.zeros(g_grid_x.size, dtype=np.float32) + np.random.normal(0, 0.003, g_grid_x.size)
    ])
    # Granite floor with grid lines
    is_tile_edge = (np.abs(np.sin(g_pts[:, 0] * math.pi)) < 0.08) | (np.abs(np.sin(g_pts[:, 1] * math.pi)) < 0.08)
    g_cols = np.full((len(g_pts), 4), [180, 185, 190, 255], dtype=np.uint8)
    g_cols[is_tile_edge] = [110, 115, 120, 255]
    pts_list.append(g_pts)
    col_list.append(g_cols)

    # 2. Four circular columns (r = 0.35m, height = 3.6m)
    col_positions = [(-4.5, -2.5), (-4.5, 2.5), (4.5, -2.5), (4.5, 2.5)]
    for cx, cy in col_positions:
        angles = np.linspace(0, 2 * math.pi, 48, endpoint=False)
        heights = np.linspace(0.0, 3.6, 60)
        a_grid, h_grid = np.meshgrid(angles, heights)
        r = 0.35 + np.random.normal(0, 0.002, a_grid.size)
        px = cx + r * np.cos(a_grid.ravel())
        py = cy + r * np.sin(a_grid.ravel())
        pz = h_grid.ravel()
        col_pts = np.column_stack([px, py, pz])
        # White/marble travertine color
        col_c = np.full((len(col_pts), 4), [235, 230, 225, 255], dtype=np.uint8)
        pts_list.append(col_pts)
        col_list.append(col_c)

    # 3. South and North walls with openings
    for y_wall, is_north in [(-3.8, False), (3.8, True)]:
        wx = np.linspace(-5.5, 5.5, 90)
        wz = np.linspace(0.0, 3.2, 50)
        wx_grid, wz_grid = np.meshgrid(wx, wz)
        wx_flat = wx_grid.ravel()
        wz_flat = wz_grid.ravel()
        
        # Cutout door at center (-1.0 to 1.0, z < 2.2)
        is_door = (wx_flat >= -1.0) & (wx_flat <= 1.0) & (wz_flat <= 2.2)
        # Cutout windows
        is_win1 = (wx_flat >= -4.5) & (wx_flat <= -3.0) & (wz_flat >= 1.0) & (wz_flat <= 2.2)
        is_win2 = (wx_flat >= 3.0) & (wx_flat <= 4.5) & (wz_flat >= 1.0) & (wz_flat <= 2.2)
        mask = ~(is_door | is_win1 | is_win2)
        
        w_pts = np.column_stack([
            wx_flat[mask],
            np.full(np.sum(mask), y_wall) + np.random.normal(0, 0.004, np.sum(mask)),
            wz_flat[mask]
        ])
        # Sandstone brick color
        w_cols = np.full((len(w_pts), 4), [215, 195, 170, 255], dtype=np.uint8)
        pts_list.append(w_pts)
        col_list.append(w_cols)

    # 4. Vaulted canopy roof
    rx = np.linspace(-6.2, 6.2, 80)
    ry = np.linspace(-4.2, 4.2, 60)
    rx_grid, ry_grid = np.meshgrid(rx, ry)
    # Barrel vault: z = 3.6 + 0.9 * cos(pi * y / 8.4)
    rz = 3.6 + 0.9 * np.cos(math.pi * ry_grid.ravel() / 8.4)
    r_pts = np.column_stack([
        rx_grid.ravel(),
        ry_grid.ravel(),
        rz + np.random.normal(0, 0.003, rz.size)
    ])
    # Terracotta copper-green / teal roof
    r_cols = np.full((len(r_pts), 4), [75, 140, 130, 255], dtype=np.uint8)
    pts_list.append(r_pts)
    col_list.append(r_cols)

    all_coords = np.vstack(pts_list).astype(np.float32)
    all_colors = np.vstack(col_list).astype(np.uint8)

    return PointCloudDataset(
        name="Demo Architectural LiDAR Scan",
        filepath=None,
        coords=all_coords,
        colors=all_colors,
        point_size=3,
        color_mode="rgb",
    )


def generate_demo_splats() -> GaussianSplatDataset:
    """Generate a vibrant 3D Gaussian Splatting scene (~25,000 splats).
    
    Includes an organic biometric pavilion sculpture with glowing gradient
    splats, varying scales, 3D covariance, and alpha transparencies.
    """
    np.random.seed(42)
    n_splats = 24000

    # Parametric trefoil knot / torus structure
    t = np.linspace(0, 4 * math.pi, n_splats)
    r_knot = 2.5 + 0.8 * np.cos(3 * t)
    cx = r_knot * np.cos(2 * t)
    cy = r_knot * np.sin(2 * t)
    cz = 1.8 + 1.2 * np.sin(3 * t)

    # Add radial volumetric cloud dispersion
    disp = np.random.normal(0, 0.22, (n_splats, 3))
    coords = (np.column_stack([cx, cy, cz]) + disp).astype(np.float32)

    # Scales: anisotropic splats aligned with tube
    s_tangent = np.random.uniform(0.08, 0.16, n_splats)
    s_normal = np.random.uniform(0.03, 0.07, n_splats)
    s_binormal = np.random.uniform(0.03, 0.07, n_splats)
    scales = np.column_stack([s_tangent, s_normal, s_binormal]).astype(np.float32)

    # Rotations (quaternions)
    rots = np.zeros((n_splats, 4), dtype=np.float32)
    rots[:, 0] = np.cos(t / 2)
    rots[:, 3] = np.sin(t / 2)
    norm = np.linalg.norm(rots, axis=1, keepdims=True)
    rots = rots / norm

    # Opacities
    opacities = np.random.uniform(0.5, 0.95, n_splats).astype(np.float32)

    # Rich radiant colors (cyan to magenta / sunset gradient along knot)
    hue = (t / (4 * math.pi)) % 1.0
    r = np.clip(np.sin(hue * 2 * math.pi) * 127 + 128, 0, 255)
    g = np.clip(np.sin((hue + 0.33) * 2 * math.pi) * 127 + 128, 0, 255)
    b = np.clip(np.sin((hue + 0.66) * 2 * math.pi) * 127 + 128, 0, 255)
    a = (opacities * 255.0).astype(np.uint8)
    colors = np.column_stack([r, g, b, a]).astype(np.uint8)

    return GaussianSplatDataset(
        name="Demo 3D Gaussian Splatting Scene",
        filepath=None,
        coords=coords,
        scales=scales,
        rotations=rots,
        opacities=opacities,
        colors=colors,
        splat_scale=1.2,
    )
