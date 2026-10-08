# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Pure Python/NumPy parser for ASPRS LAS 1.2 / 1.4 LiDAR point clouds."""
from __future__ import annotations

import logging
from pathlib import Path
import struct
from typing import Union
import numpy as np

from ..data_models import PointCloudDataset

log = logging.getLogger("ingetrazo.plugins.pointcloud_splat")


def read_las(path: Union[str, Path]) -> PointCloudDataset:
    """Read an ASPRS LAS file (formats 0 through 10) into a PointCloudDataset."""
    path = Path(path)
    with open(path, 'rb') as f:
        header = f.read(375)
        if len(header) < 227 or header[0:4] != b"LASF":
            raise ValueError(f"Invalid LAS file signature: expected b'LASF', got {header[0:4]!r}")

        # Unpack header values
        offset_to_points = struct.unpack_from("<I", header, 96)[0]
        raw_format_byte = struct.unpack_from("<B", header, 104)[0]
        if raw_format_byte & 0xC0 or path.suffix.lower() == ".laz":
            # Bits 6/7 flag LASzip compression — raw decoding would produce garbage points.
            raise ValueError(
                "Compressed LAZ files are not supported yet. "
                "Please decompress to .las first (e.g. with laszip, PDAL or CloudCompare)."
            )
        point_format = raw_format_byte & 0x0F  # Lower 4 bits for format ID
        record_len = struct.unpack_from("<H", header, 105)[0]
        n_points = struct.unpack_from("<I", header, 107)[0]

        # In LAS 1.4, check for 64-bit point count if n_points is 0 or 0xFFFFFFFF
        if (n_points == 0 or n_points == 0xFFFFFFFF) and len(header) >= 255:
            try:
                legacy_n = n_points
                n_points = struct.unpack_from("<Q", header, 247)[0]
                if n_points == 0:
                    n_points = legacy_n
            except Exception:
                pass

        # Scale factors (double, 8 bytes each)
        sx, sy, sz = struct.unpack_from("<ddd", header, 131)
        # Offsets (double, 8 bytes each)
        ox, oy, oz = struct.unpack_from("<ddd", header, 155)

        if n_points <= 0:
            raise ValueError("No point records found in LAS file")

        f.seek(offset_to_points)
        raw_bytes = f.read(n_points * record_len)
        actual_points = len(raw_bytes) // record_len

        if actual_points <= 0:
            raise ValueError("Point data section is empty")

        # Determine RGB offset according to ASPRS LAS specifications:
        # Format 2: offset 20 (len 26)
        # Formats 3, 5: offset 28 (len 34, 63)
        # Formats 7, 8, 10: offset 30 (len 36, 38, 67)
        if point_format == 2:
            rgb_offset = 20
        elif point_format in (3, 5):
            rgb_offset = 28
        elif point_format in (7, 8, 10):
            rgb_offset = 30
        else:
            rgb_offset = 0

        has_rgb = (rgb_offset > 0 and record_len >= rgb_offset + 6)
        pad_before = rgb_offset - 14 if has_rgb else 0
        pad_after = record_len - (rgb_offset + 6) if has_rgb else max(0, record_len - 14)

        dt_spec = [
            ('x', '<i4'),
            ('y', '<i4'),
            ('z', '<i4'),
            ('intensity', '<u2'),
        ]
        if has_rgb:
            if pad_before > 0:
                dt_spec.append(('_pad_before', f'V{pad_before}'))
            dt_spec.extend([
                ('red', '<u2'),
                ('green', '<u2'),
                ('blue', '<u2'),
            ])
            if pad_after > 0:
                dt_spec.append(('_pad_after', f'V{pad_after}'))
        else:
            if pad_after > 0:
                dt_spec.append(('_pad', f'V{pad_after}'))

        struct_dtype = np.dtype(dt_spec)
        raw_arr = np.frombuffer(raw_bytes[:actual_points * record_len], dtype=struct_dtype)

        # Compute coordinates in metres
        x = raw_arr['x'].astype(np.float64) * sx + ox
        y = raw_arr['y'].astype(np.float64) * sy + oy
        z = raw_arr['z'].astype(np.float64) * sz + oz
        coords = np.column_stack([x, y, z]).astype(np.float32)

        intensities = raw_arr['intensity'].astype(np.float32)

        # Colors extraction & auto-detection of 8-bit vs 16-bit
        colors = None
        has_genuine_rgb = False

        if 'red' in raw_arr.dtype.names:
            r_raw = raw_arr['red']
            g_raw = raw_arr['green']
            b_raw = raw_arr['blue']
            max_val = max(int(np.max(r_raw)), int(np.max(g_raw)), int(np.max(b_raw)))

            if max_val > 255:
                # 16-bit RGB (ASPRS LAS standard 0..65535) -> scale to 8-bit
                r = (r_raw >> 8).astype(np.uint8)
                g = (g_raw >> 8).astype(np.uint8)
                b = (b_raw >> 8).astype(np.uint8)
                has_genuine_rgb = True
            elif max_val > 0:
                # 8-bit RGB (stored directly in uint16 0..255 by DJI, Pix4D, Metashape, etc.)
                r = r_raw.astype(np.uint8)
                g = g_raw.astype(np.uint8)
                b = b_raw.astype(np.uint8)
                has_genuine_rgb = True

            if has_genuine_rgb:
                a = np.full(actual_points, 255, dtype=np.uint8)
                colors = np.column_stack([r, g, b, a])

        min_i = float(np.min(intensities)) if len(intensities) > 0 else 0.0
        max_i = float(np.max(intensities)) if len(intensities) > 0 else 0.0

        if colors is None:
            # Generate false-color / grayscale from intensity
            rng = max_i - min_i
            if rng > 0:
                norm_i = ((intensities - min_i) / rng) * 255.0
            else:
                norm_i = np.full(actual_points, 200, dtype=np.float32)
            c = np.clip(norm_i, 0, 255).astype(np.uint8)
            colors = np.column_stack([c, c, c, np.full(actual_points, 255, dtype=np.uint8)])

    name = path.stem.replace('_', ' ').title()

    return PointCloudDataset(
        name=name,
        filepath=str(path),
        coords=coords,
        colors=colors,
        intensities=intensities,
        color_mode="rgb" if has_genuine_rgb else ("intensity" if (max_i > min_i) else "elevation")
    )
