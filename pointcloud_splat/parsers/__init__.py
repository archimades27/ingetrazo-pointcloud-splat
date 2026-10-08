# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Parsers for various point cloud and Gaussian Splatting file formats."""
from __future__ import annotations

from .ply_parser import read_ply
from .splat_parser import read_splat
from .xyz_parser import read_xyz
from .las_parser import read_las
from .synthetic_samples import generate_demo_pointcloud, generate_demo_splats

__all__ = [
    "read_ply",
    "read_splat",
    "read_xyz",
    "read_las",
    "generate_demo_pointcloud",
    "generate_demo_splats",
]
