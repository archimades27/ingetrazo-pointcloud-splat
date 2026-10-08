# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""High-speed binary and ASCII PLY parser for point clouds and 3D Gaussian Splatting."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Tuple, Union, Optional
import numpy as np

from ..data_models import PointCloudDataset, GaussianSplatDataset

log = logging.getLogger("ingetrazo.plugins.pointcloud_splat")

# Type map from PLY format to NumPy dtypes
_PLY_DTYPE_MAP = {
    'char': 'i1', 'int8': 'i1',
    'uchar': 'u1', 'uint8': 'u1',
    'short': 'i2', 'int16': 'i2',
    'ushort': 'u2', 'uint16': 'u2',
    'int': 'i4', 'int32': 'i4',
    'uint': 'u4', 'uint32': 'u4',
    'float': 'f4', 'float32': 'f4',
    'double': 'f8', 'float64': 'f8',
}


def read_ply(path: Union[str, Path]) -> Union[PointCloudDataset, GaussianSplatDataset]:
    """Read a PLY file (ASCII or Binary) and return PointCloudDataset or GaussianSplatDataset."""
    path = Path(path)
    file_size = path.stat().st_size
    with open(path, 'rb') as f:
        header_lines = []
        while True:
            line_b = f.readline()
            if not line_b:
                raise ValueError("Premature end of file while reading PLY header")
            line = line_b.decode('ascii', errors='ignore').strip()
            header_lines.append(line)
            if line == 'end_header':
                break

        # Parse header
        is_binary = False
        is_big_endian = False
        vertex_count = 0
        properties = []
        is_vertex_element = False

        for line in header_lines:
            tokens = line.split()
            if not tokens:
                continue
            if tokens[0] == 'format':
                fmt = tokens[1]
                if 'binary_little_endian' in fmt:
                    is_binary = True
                    is_big_endian = False
                elif 'binary_big_endian' in fmt:
                    is_binary = True
                    is_big_endian = True
                elif 'ascii' in fmt:
                    is_binary = False
                else:
                    raise ValueError(f"Unsupported PLY format: {fmt}")
            elif tokens[0] == 'element':
                if tokens[1] == 'vertex':
                    is_vertex_element = True
                    vertex_count = int(tokens[2])
                else:
                    is_vertex_element = False
            elif tokens[0] == 'property' and is_vertex_element:
                prop_type = tokens[1]
                prop_name = tokens[2]
                properties.append((prop_name, prop_type))

        if vertex_count <= 0:
            raise ValueError("No vertices found in PLY file")

        prop_names = [p[0] for p in properties]
        is_gaussian_splat = any(k in prop_names for k in ['f_dc_0', 'opacity', 'scale_0'])

        if is_binary:
            prefix = '>' if is_big_endian else '<'
            dt_list = []
            for name, ptype in properties:
                np_code = _PLY_DTYPE_MAP.get(ptype.lower(), 'f4')
                dt_list.append((name, f"{prefix}{np_code}"))
            struct_dtype = np.dtype(dt_list)
            
            raw_data = np.fromfile(f, dtype=struct_dtype, count=vertex_count)
        else:
            # ASCII format
            # Read remainder of file as lines
            raw_text = f.read().decode('ascii', errors='ignore')
            data_arr = np.loadtxt(raw_text.splitlines()[:vertex_count], dtype=np.float32)
            # Map columns to properties
            raw_data = {}
            for i, (name, _) in enumerate(properties):
                if i < data_arr.shape[1]:
                    raw_data[name] = data_arr[:, i]

    name = path.stem.replace('_', ' ').title()

    if is_gaussian_splat:
        return _build_gaussian_splat_dataset(name, str(path), raw_data, prop_names)
    else:
        return _build_point_cloud_dataset(name, str(path), raw_data, prop_names)


def _build_gaussian_splat_dataset(
    name: str, filepath: str, data, prop_names: list[str]
) -> GaussianSplatDataset:
    """Build a GaussianSplatDataset from extracted PLY fields."""
    coords = np.column_stack([
        data['x'].astype(np.float32),
        data['y'].astype(np.float32),
        data['z'].astype(np.float32),
    ])

    # Opacity (stored as logit -> sigmoid)
    if 'opacity' in prop_names:
        raw_op = data['opacity'].astype(np.float32)
        opacities = 1.0 / (1.0 + np.exp(-raw_op))
    else:
        opacities = np.ones(len(coords), dtype=np.float32)

    # Scales (stored as log scale -> exponential)
    if 'scale_0' in prop_names and 'scale_1' in prop_names and 'scale_2' in prop_names:
        s0 = np.exp(data['scale_0'].astype(np.float32))
        s1 = np.exp(data['scale_1'].astype(np.float32))
        s2 = np.exp(data['scale_2'].astype(np.float32))
        scales = np.column_stack([s0, s1, s2])
    else:
        scales = np.full((len(coords), 3), 0.05, dtype=np.float32)

    # Rotations (quaternions rot_0..3)
    if all(f'rot_{i}' in prop_names for i in range(4)):
        r0 = data['rot_0'].astype(np.float32)
        r1 = data['rot_1'].astype(np.float32)
        r2 = data['rot_2'].astype(np.float32)
        r3 = data['rot_3'].astype(np.float32)
        rots = np.column_stack([r0, r1, r2, r3])
        # Normalize
        norm = np.linalg.norm(rots, axis=1, keepdims=True)
        norm[norm == 0] = 1.0
        rots = rots / norm
    else:
        rots = np.zeros((len(coords), 4), dtype=np.float32)
        rots[:, 0] = 1.0  # identity quaternion

    # Colors: DC spherical harmonics (C0 = 0.28209479177387814)
    SH_C0 = 0.28209479177387814
    if 'f_dc_0' in prop_names and 'f_dc_1' in prop_names and 'f_dc_2' in prop_names:
        r = np.clip(data['f_dc_0'].astype(np.float32) * SH_C0 + 0.5, 0.0, 1.0) * 255.0
        g = np.clip(data['f_dc_1'].astype(np.float32) * SH_C0 + 0.5, 0.0, 1.0) * 255.0
        b = np.clip(data['f_dc_2'].astype(np.float32) * SH_C0 + 0.5, 0.0, 1.0) * 255.0
    elif 'red' in prop_names and 'green' in prop_names and 'blue' in prop_names:
        r = data['red'].astype(np.float32)
        g = data['green'].astype(np.float32)
        b = data['blue'].astype(np.float32)
        if np.max(r) <= 1.0:
            r *= 255.0
            g *= 255.0
            b *= 255.0
    else:
        r = np.full(len(coords), 220, dtype=np.float32)
        g = np.full(len(coords), 220, dtype=np.float32)
        b = np.full(len(coords), 220, dtype=np.float32)

    a = np.clip(opacities * 255.0, 0.0, 255.0)
    colors = np.column_stack([r, g, b, a]).astype(np.uint8)

    return GaussianSplatDataset(
        name=name,
        filepath=filepath,
        coords=coords,
        scales=scales,
        rotations=rots,
        opacities=opacities,
        colors=colors,
    )


def _build_point_cloud_dataset(
    name: str, filepath: str, data, prop_names: list[str]
) -> PointCloudDataset:
    """Build a PointCloudDataset from extracted PLY fields."""
    coords = np.column_stack([
        data['x'].astype(np.float32),
        data['y'].astype(np.float32),
        data['z'].astype(np.float32),
    ])

    # Colors
    color_keys = [
        ('red', 'green', 'blue'),
        ('r', 'g', 'b'),
        ('diffuse_red', 'diffuse_green', 'diffuse_blue'),
    ]
    r, g, b = None, None, None
    for rk, gk, bk in color_keys:
        if rk in prop_names and gk in prop_names and bk in prop_names:
            r = data[rk].astype(np.float32)
            g = data[gk].astype(np.float32)
            b = data[bk].astype(np.float32)
            if np.max(r) <= 1.0 and np.max(g) <= 1.0 and np.max(b) <= 1.0:
                r *= 255.0
                g *= 255.0
                b *= 255.0
            break

    if r is None:
        # Default neutral light gray
        r = np.full(len(coords), 200, dtype=np.float32)
        g = np.full(len(coords), 200, dtype=np.float32)
        b = np.full(len(coords), 200, dtype=np.float32)

    if 'alpha' in prop_names:
        a = data['alpha'].astype(np.float32)
        if np.max(a) <= 1.0:
            a *= 255.0
    else:
        a = np.full(len(coords), 255, dtype=np.float32)

    colors = np.column_stack([
        np.clip(r, 0, 255),
        np.clip(g, 0, 255),
        np.clip(b, 0, 255),
        np.clip(a, 0, 255),
    ]).astype(np.uint8)

    # Normals
    normals = None
    if all(k in prop_names for k in ['nx', 'ny', 'nz']):
        normals = np.column_stack([
            data['nx'].astype(np.float32),
            data['ny'].astype(np.float32),
            data['nz'].astype(np.float32),
        ])

    # Intensity / Scalar
    intensities = None
    for ik in ['intensity', 'scalar_intensity', 'intensity_float', 'scalar']:
        if ik in prop_names:
            intensities = data[ik].astype(np.float32)
            break

    return PointCloudDataset(
        name=name,
        filepath=filepath,
        coords=coords,
        colors=colors,
        normals=normals,
        intensities=intensities,
    )
