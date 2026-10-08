# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""ASCII parser for .xyz, .pts, .txt, .csv point cloud files."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Union
import numpy as np

from ..data_models import PointCloudDataset

log = logging.getLogger("ingetrazo.plugins.pointcloud_splat")


def read_xyz(path: Union[str, Path]) -> PointCloudDataset:
    """Read an ASCII coordinate file (XYZ, PTS, TXT, CSV) into a PointCloudDataset."""
    path = Path(path)
    lines_read = []
    
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        # Check first line: for .pts files, first line is often point count
        first_line = f.readline().strip()
        tokens = first_line.split()
        if len(tokens) == 1 and tokens[0].isdigit():
            # First line is point count, skip it
            pass
        elif not first_line.startswith(('#', '//', ';')):
            lines_read.append(first_line)

        # Read remaining lines
        for line in f:
            line_str = line.strip()
            if not line_str or line_str.startswith(('#', '//', ';')):
                continue
            lines_read.append(line_str)

    if not lines_read:
        raise ValueError("No valid point data found in coordinate file")

    # Detect delimiter
    sample = lines_read[0]
    delimiter = None
    if ',' in sample:
        delimiter = ','
    elif ';' in sample:
        delimiter = ';'
    elif '\t' in sample:
        delimiter = '\t'

    # Convert to array
    raw = np.genfromtxt(lines_read, delimiter=delimiter, dtype=np.float32)
    if raw.ndim == 1:
        raw = raw.reshape(1, -1)

    ncols = raw.shape[1]
    if ncols < 3:
        raise ValueError(f"Need at least 3 coordinates (X, Y, Z), found {ncols}")

    coords = raw[:, :3]
    colors = None
    intensities = None

    if ncols >= 6:
        # Check if cols 3, 4, 5 are RGB (0-255 or 0-1)
        c345 = raw[:, 3:6]
        if np.max(c345) <= 1.0:
            c345 = c345 * 255.0
        r = np.clip(c345[:, 0], 0, 255)
        g = np.clip(c345[:, 1], 0, 255)
        b = np.clip(c345[:, 2], 0, 255)
        a = np.full(len(coords), 255, dtype=np.float32)
        if ncols >= 7:
            intensities = raw[:, 6]
        colors = np.column_stack([r, g, b, a]).astype(np.uint8)
    elif ncols == 4:
        # Col 3 is intensity
        intensities = raw[:, 3]
        # Generate grayscale color from intensity
        norm_i = intensities - np.min(intensities)
        rng = np.max(norm_i)
        if rng > 0:
            norm_i = (norm_i / rng) * 255.0
        else:
            norm_i = np.full(len(coords), 200, dtype=np.float32)
        c = np.clip(norm_i, 0, 255)
        colors = np.column_stack([c, c, c, np.full(len(coords), 255, dtype=np.float32)]).astype(np.uint8)
    else:
        # Default neutral light gray
        colors = np.full((len(coords), 4), [210, 215, 220, 255], dtype=np.uint8)

    name = path.stem.replace('_', ' ').title()

    return PointCloudDataset(
        name=name,
        filepath=str(path),
        coords=coords,
        colors=colors,
        intensities=intensities,
    )
