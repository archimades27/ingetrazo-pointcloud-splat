# What's New in v1.0.1

**Release Date:** November 3, 2026  
**Compatible with:** IngeTrazo `0.5.7+`

---

## 🛠️ Summary of Fixes & Improvements in `v1.0.1`

### 1. 3D Depth Buffer Occlusion & Overlap (`pointcloud_splat/renderer.py`, `pointcloud_splat/fast_splat.c`)
- **True 3D CAD / Point Cloud Overlap**: Point clouds and 3D Gaussian Splats now read IngeTrazo's OpenGL hardware depth buffer (`viewport._depth_snap`) and linearize eye-space depth so CAD models and point clouds intersect and occlude each other accurately in 3D space instead of painting flat on top of the model.
- **Large-Scale Site Scan Precision (100m+ / Drone Photogrammetry)**: Compensates for OpenGL `glPolygonOffset(1.0, 1.0)` in `float64` window-depth space (`1.5e-6` window-depth bias) prior to hyperbolic inversion so faces drawn directly on the ground plane (`Z = 0`) at 150m+ camera distances are never buried underneath coplanar scan points.
- **Native Depth Buffer Activation**: Hooks `Viewport._annotations_need_depth` so IngeTrazo automatically captures `_depth_snap` whenever visible point clouds or Gaussian Splats are active in shaded/textured styles, while respecting **X-Ray** and **Wireframe** modes.
- **C Kernel & NumPy Depth Testing**: Added `const float* scene_depth` depth-occlusion culling to both `render_pointcloud_c` and `render_gaussian_splats_c` in `fast_splat.c` as well as the pure-NumPy fallback rasterizer.

### 2. Unobstructed CAD Selection, Editing & Modeling Inside Point Clouds (`pointcloud_splat/__init__.py`, `pointcloud_splat/scene_proxy.py`, `pointcloud_splat/ui/manager_panel.py`)
- **Non-Blocking Zero-Face Scene Proxy**: Replaced the 6-face proxy bounding box with a 12-hidden-edge (0-face) proxy wireframe (`create_pointcloud_proxy`) so point cloud volumes never intercept mouse raycasts, hover highlights, **Push/Pull**, or **Line/Rectangle** drawing inside the scan.
- **Loose Geometry Priority in `pick_group`**: Updated `_wrapped_pick_group` to yield (`return None`) whenever any native CAD entity (`pick_face`, `pick_visible_edge`/`pick_edge`, `pick_guide`, `pick_dimension`, `pick_text_label`, `pick_section_plane`, `pick_image_plane`) is under the cursor—allowing loose faces and edges inside a point cloud to be freely selected, moved, extruded, and edited.
- **Scene Visibility & Crossing-Box Selection Filtering**: Hooked `Scene.entity_visible`, `Scene.entity_selectable`, and `Viewport.begin_group_edit` for `is_pointcloud_proxy` groups so `Viewport._pick_block_part` and crossing-box selection (`SelectTool.on_box_select`) ignore proxy groups, and double-clicking never traps the user inside an empty group edit session.
- **Clean Hide/Show State Synchronization**: Toggling dataset visibility in the **Point Clouds & Splats** panel now synchronizes `proxy_group.hidden`, removes hidden proxies from `scene.selection`, and flushes viewport pick caches so hidden scans never interfere with modeling.
- **Direct Point Cloud Picking & Native Transform Tools**: Clicking directly on a visible point cloud (when no CAD entity is under the cursor) or selecting it in the panel still selects its proxy group for native **Move (`M`)**, **Rotate (`Q`)**, and **Scale (`S`)** transformations with full Undo/Redo support.

### 3. Scene Proxy & Transform Synchronization (`pointcloud_splat/scene_proxy.py`, `pointcloud_splat/data_models.py`)
- **Degenerate / Flat Scan Bounds Protection**: Enforced a minimum 1 cm half-thickness in `_proxy_raw_corners()` so flat/2D scans retain a full 8-vertex proxy and remain selectable/transformable.
- **Interactive Scale Recovery**: `compute_dataset_transform()` now recovers uniform scale changes made with IngeTrazo's native **Scale (`S`)** tool and synchronizes `dataset.scale`, `dataset.offset`, and Euler angles (`sync_dataset_from_proxy`).
- **Cached Rotated World Bounds**: Replaced the 8-corner loop in `PointCloudDataset.bounds` with vectorized matrix multiplication cached per `(offset, rotation, scale, raw_bounds)` state, eliminating redundant per-frame recomputation.

### 4. Renderer Stability, Multi-Viewport Caching & C Kernel Portability (`pointcloud_splat/renderer.py`, `pointcloud_splat/fast_splat.c`)
- **Multi-Viewport Framebuffer Cache Safety**: Stored `(width, height)` alongside `_cached_img_buf` so switching between viewports of different dimensions (e.g., Main 3D viewport and Quad/MultiView panels) never triggers a `ValueError` reshape crash.
- **Cross-Platform C Kernel Compilation**: Guarded `<dispatch/dispatch.h>` with `#ifdef __APPLE__` in `fast_splat.c` and added OpenMP `#pragma omp parallel for` fallback so the native C extension compiles cleanly on **macOS**, **Linux**, and **Windows**.

### 5. PLY Parser & Scan-to-BIM Command Layer Integration (`pointcloud_splat/parsers/ply_parser.py`, `pointcloud_splat/cad_tools.py`, `pointcloud_splat/ui/manager_panel.py`)
- **Robust Binary PLY Parsing**: Added support for `binary_big_endian` PLY files, validated vertex buffer lengths against truncated files, and skips trailing face/element blocks when reading ASCII PLY vertex tables.
- **Fast RANSAC Downsampling**: `create_plane_surface_group()` now downsamples in local space before applying the world transform, avoiding transforming millions of points for a 20,000-point RANSAC sample.
- **Undoable Scan-to-BIM Commands (`SnapshotImport`)**: Following the official [IngeTrazo Plugin Guide](https://github.com/ingelibre/ingetrazo/blob/main/docs/plugins.md), **Fit Dominant Plane**, **Create Bounding Box**, and **Add Guide Points** now execute through `SnapshotImport` + `viewport.notify_scene_changed()` so each operation is a single clean Undo/Redo step and registers `add_outliner_kind` metadata.
