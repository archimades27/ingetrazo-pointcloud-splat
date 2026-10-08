# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Binary parser for .splat 3D Gaussian Splatting files (AntiMatter15 format)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Union
import numpy as np

from ..data_models import GaussianSplatDataset

log = logging.getLogger("ingetrazo.plugins.pointcloud_splat")

# 32 bytes per splat:
# pos: 3 * float32 (12 bytes)
# scale: 3 * float32 (12 bytes)
# color: 4 * uint8 (4 bytes)
# rot: 4 * uint8 (4 bytes, mapped to [-1, 1])
SPLAT_DTYPE = np.dtype([
    ('pos', '<f4', (3,)),
    ('scale', '<f4', (3,)),
    ('color', 'u1', (4,)),
    ('rot', 'u1', (4,))
])


def read_splat(path: Union[str, Path]) -> GaussianSplatDataset:
    """Read a .splat file and return a GaussianSplatDataset."""
    path = Path(path)
    file_size = path.stat().st_size
    if file_size % 32 != 0:
        log.warning(f"File size {file_size} is not a multiple of 32 bytes; truncating extra bytes.")

    count = file_size // 32
    raw = np.fromfile(str(path), dtype=SPLAT_DTYPE, count=count)

    coords = raw['pos'].astype(np.float32)
    scales = raw['scale'].astype(np.float32)
    colors = raw['color'].copy()  # uint8 RGBA
    opacities = (colors[:, 3].astype(np.float32) / 255.0)

    # Quaternion rotation: map uint8 [0, 255] -> [-1.0, 1.0]
    rots = (raw['rot'].astype(np.float32) - 128.0) / 128.0
    norm = np.linalg.norm(rots, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    rots = rots / norm

    name = path.stem.replace('_', ' ').title()

    return GaussianSplatDataset(
        name=name,
        filepath=str(path),
        coords=coords,
        scales=scales,
        rotations=rots,
        opacities=opacities,
        colors=colors,
    )
