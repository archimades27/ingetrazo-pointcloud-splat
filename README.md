# Point Cloud & 3D Gaussian Splatting for IngeTrazo

[![IngeTrazo](https://img.shields.io/badge/IngeTrazo-v0.5.7+-007ACC.svg)](https://ingetrazo.com)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-green.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Version](https://img.shields.io/badge/Version-1.0.2-orange.svg)](https://github.com/archimades27/ingetrazo-pointcloud-splat/releases/tag/v1.0.2)
[![YouTube Preview](https://img.shields.io/badge/YouTube-Video%20Demo-FF0000.svg?logo=youtube&logoColor=white)](https://youtu.be/XS2TN14EPjI)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9+-yellow.svg)]()
[![Platform: macOS | Linux | Windows](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)]()

> **The definitive high-performance Point Cloud (LiDAR, Photogrammetry) and 3D Gaussian Splatting (3DGS) extension for [IngeTrazo](https://ingetrazo.com) CAD/BIM modeler.**

[![Watch Video Preview on YouTube](screenshots/youtube_thumbnail.png)](https://youtu.be/XS2TN14EPjI)

*▶️ **Watch the live video demonstration on YouTube: [https://youtu.be/XS2TN14EPjI](https://youtu.be/XS2TN14EPjI)***

---

## 📖 Overview

The **Point Cloud & 3D Gaussian Splatting** extension brings native, interactive reality-capture workflows directly inside **IngeTrazo**. It enables architects, engineers, surveyors, and 3D designers to import aerial drone scans, terrestrial LiDAR datasets, photogrammetry models, and volumetric radiance fields (*3D Gaussian Splats*), providing **sub-millisecond viewport rendering (up to 60+ FPS)**, architectural 3D section slicing, and **native CAD snapping** for precision as-built modeling and Scan-to-BIM reconstruction.

![IngeTrazo Point Cloud & Gaussian Splatting UI](screenshots/pointcloud_splat.png)

---

## 🆕 What's New in v1.0.2 & v1.0.1

See [WHATSNEW.md](WHATSNEW.md) for the complete technical changelog. Highlights include:
* **Linux Native Library Auto-Build & OpenMP Multi-Threading (`v1.0.2`)**: Fixed platform library detection in `_get_fast_splat_lib()` so Linux systems no longer stop at `fast_splat.dylib` and instead compile and load `fast_splat.so` with `-fopenmp` multi-threading.
* **NumPy 2 Splat Fallback Fix & Frame Cap (`v1.0.2`)**: Vectorized `_render_splat_fallback` using `np.ogrid` and `int32` blending (fixing `OverflowError` under NumPy 2 when running without a C compiler) and capped fallback rendering to `FALLBACK_MAX_SPLATS = 4000` so the GUI never freezes.
* **Undoable Point Cloud Import & Clean `.igz` Reopen (`v1.0.2`)**: Importing and removing point clouds now records an undo step (`Ctrl+Z` / `Ctrl+Y`) and automatically reloads or cleans up proxy groups when reopening saved `.igz` files.
* **True 3D Depth Buffer Occlusion & Overlap (`v1.0.1`)**: Point clouds and 3D Gaussian Splats test against IngeTrazo's OpenGL depth buffer (`_depth_snap`) with float64 polygon-offset compensation so CAD geometry and large-scale drone scans (100m+) overlap and intersect accurately in 3D space.
* **Unobstructed CAD Selection & Editing Inside Scans (`v1.0.1`)**: Replaced the 6-face proxy box with a non-blocking 0-face proxy and updated viewport picking hooks (`pick_group`, `entity_visible`, `entity_selectable`, `begin_group_edit`) so loose faces, edges, Push/Pull, Move, and crossing-box selection work seamlessly inside both visible and hidden point clouds.

---

## 📊 Supported File Formats

| Format | Extension | Capabilities & Details |
| :--- | :--- | :--- |
| **Polygon File Format** | `.ply` | ASCII & Binary Little-Endian. Supports standard point clouds (XYZ + RGB + Normals) and full **3D Gaussian Splatting** datasets (Spherical Harmonics degrees 0–3, covariance scale factors, and rotation quaternions). |
| **LiDAR ASPRS Standard** | `.las`, `.laz` | Industry-standard airborne and terrestrial LiDAR format (ASPRS LAS 1.1 through 1.4). Supports double-precision georeferenced coordinates, 8-bit/16-bit RGB channels, and sensor reflectance intensity. |
| **Raw WebGL Splats** | `.splat` | Compact 32-byte chunk format commonly exported by modern photogrammetry pipelines and web viewers (antimatter15, Luma AI, Polycam, SuperSplat, KIRI Engine). |
| **ASCII Table Formats** | `.xyz`, `.pts`, `.txt`, `.csv` | Automatic delimiter detection (comma, space, tab). Automatically extracts XYZ coordinates, RGB color channels (0–255 or 0.0–1.0 floats), and intensity values. |

---

## 🌟 Key Features

### ⚡ 1. High-Performance Viewport Engine (Up to 60+ FPS)
* **Native C / SIMD Kernel**: Ships with an optimized C module (`fast_splat.c`) utilizing hardware acceleration and multi-threaded parallel depth-sorting (Apple Grand Central Dispatch / parallel bins) for instant splat projection and sub-millisecond rasterization.
* **Adaptive Dynamic LOD (Level of Detail)**: Dynamically adjusts render density and point budgets during rapid viewport navigation (orbit, pan, zoom) so interaction remains fluid without stutter, even on datasets exceeding tens of millions of points.
* **MultiView & Quad Viewport Integration**: Synchronizes rendering across all split viewports in IngeTrazo (Top Plan, Front Elevation, Right Elevation, and 3D Perspective/ISO).

### 🎨 2. Comprehensive Shading & Colormaps
* **True Color (RGB / SH)**: Renders natural surface colors captured by cameras or photogrammetric drones, including view-dependent spherical harmonics.
* **Elevation Colormaps**: Maps vertical height (Z-axis) into vibrant analytical gradients (**Turbo, Viridis, Jet, Terrain**)—ideal for site analysis, cut-and-fill grading, and topography visualization.
* **LiDAR Intensity**: Visualizes surface reflectivity to clearly distinguish asphalt roads, building facades, vegetation, and water bodies.
* **Surface Normals**: Colors points based on their normal vectors (RGB mapped to XYZ surface orientation).

### ✂️ 3. Interactive 3D Section Box / Clipping
* Real-time 3D clipping volume with independent Min/Max controls for the X, Y, and Z axes.
* Slice through dense point clouds instantly to inspect internal structural framing, isolate floor plan levels, or generate cross-section profiles.

### 🧲 4. Precision CAD Snapping (Snap-to-Cloud)
* Seamlessly connects point cloud geometry to IngeTrazo's native drafting tools (**Line Tool, Tape Measure, Push/Pull**).
* The cursor automatically snaps to the nearest cloud point with an interactive green snap circle, allowing users to trace as-built walls and measure true field dimensions without converting the point cloud into heavy meshes.

### 🏛️ 5. Automated Scan-to-BIM & Reverse Engineering
* **RANSAC Dominant Plane Detection**: Automatically extracts structural planar surfaces (walls, floors, ceiling slabs) from raw point clouds and generates native IngeTrazo face groups.
* **3D Bounding Box**: Computes and creates a native bounding volume group enclosing the active scan.
* **Convert to Guide Points**: Converts key cloud points into permanent IngeTrazo construction guide points.

### 🧪 6. Built-in Procedural Synthetic Demos
* Experiment immediately without downloading gigabyte-sized scan files using built-in procedural generators under **Import ▸ Sample Data**:
  - **🏛️ Architectural LiDAR Scan**: Realistic pavilion LiDAR scan (~45,000 points) with granite tile floor, 4 circular travertine columns, perimeter walls with door/window openings, vaulted roof, and simulated sensor noise.
  - **🌐 Gaussian Splat Scene**: Volumetric 3D Gaussian Splatting sculpture (~24,000 anisotropic splats) with full 3D covariance, quaternion orientations, and radiant gradient colors.

---

## 🖥️ User Interface Overview

The **Point Clouds & Splats** dock panel appears in IngeTrazo's right tray dock:

| Panel Section | Features & Controls |
| :--- | :--- |
| **Datasets List** | Lists active scans, toggle visibility (eye icon), zoom-to-fit, viewport selection, drag-and-drop import, and dataset removal. |
| **Display** | Choose shading mode (*True Color RGB/SH, Elevation Turbo/Viridis/Jet/Terrain, Intensity, Surface Normals, Solid Color*), point size (1–14 px), splat scale, opacity, and frame point budget. |
| **Section Box** | Toggle 3D section box slicing, adjust XYZ Min/Max bounds, and one-click fit to the active dataset. |
| **Transform** | Interactive viewport placement with native **Move (`M`)**, **Rotate (`Q`/`R`)**, and **Scale (`S`)** tools (with Undo/Redo), plus numeric Offset, Yaw/Tilt rotation, and unit conversion presets. |
| **Scan-to-BIM** | Toggle CAD point snapping, Fit Dominant Plane (RANSAC), Create Bounding Box, and Add Guide Points. |

---

## 🚀 Installation

### Method 1: Official IngeTrazo Extensions Catalog (Recommended)
1. Visit the official catalog at [ingetrazo.com/extensiones](https://ingetrazo.com/extensiones).
2. Locate **Point Cloud & 3D Gaussian Splatting** and click **Download**.
3. Extract the downloaded archive to obtain the `pointcloud_splat` folder.
4. In IngeTrazo, go to **Extensions ▸ Open plugins folder** (*Extensiones ▸ Abrir carpeta de plugins*).
5. Copy the `pointcloud_splat` folder into that directory.
6. Restart IngeTrazo.

### Method 2: Manual Installation from this Repository
Clone or copy the `pointcloud_splat` folder directly into your platform's IngeTrazo plugin directory:

* **macOS**:
  ```bash
  cp -r pointcloud_splat/ "$HOME/Library/Application Support/IngeTrazo/plugins/"
  ```
* **Linux**:
  ```bash
  cp -r pointcloud_splat/ "$HOME/.local/share/ingetrazo/plugins/"
  ```
* **Windows**:
  Copy the `pointcloud_splat` folder into `%APPDATA%\IngeTrazo\plugins\`.

---

## 🎯 Quick Start Workflow

1. Launch **IngeTrazo**.
2. Open the menu: **Extensions > Point Cloud & Gaussian Splatting…** or press **`Ctrl+Shift+P`**.
3. **Import a file**:
   * Click **Import File...** in the panel, OR
   * **Drag and drop** any `.ply`, `.las`, `.laz`, `.splat`, or `.xyz` file directly into the 3D viewport.
4. Select your preferred colormap (e.g., **Elevation - Turbo** for topography or **True Color RGB** for photogrammetry).
5. Select the native **Line Tool** or **Tape Measure** and start modeling directly over the scan with snapping enabled!

---

## 📦 Building Distribution Packages

To package the extension for distribution or verify checksums:
```bash
python3 tools/build_package.py
```
This utility:
1. Filters development artifacts (`.DS_Store`, `__pycache__`).
2. Bundles the root `pointcloud_splat/` folder into `dist/pointcloud_splat.zip`.
3. Calculates the SHA-256 cryptographic digest.
4. Synchronizes the hash into `pointcloud_splat.toml`.

---

## 📄 License

This project is free software licensed under the **[GNU General Public License v3.0 (GPL-3.0-or-later)](LICENSE)**.

```text
Copyright (C) 2026 Archimades (archimades27) and IngeTrazo contributors.
```
You are free to use, inspect, modify, and redistribute this software under the terms of the GNU GPLv3 license.
