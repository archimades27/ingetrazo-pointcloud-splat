# Point Cloud & 3D Gaussian Splatting for IngeTrazo

[![IngeTrazo](https://img.shields.io/badge/IngeTrazo-v0.5.7+-blue.svg)](https://ingetrazo.com)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-green.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Version](https://img.shields.io/badge/Version-1.0.0-orange.svg)]()

Ekstensi komprehensif untuk **IngeTrazo** yang menghadirkan visualisasi, inspeksi, dan interaksi interaktif dengan data **Point Cloud (LiDAR & Fotogrametri)** serta **3D Gaussian Splatting (3DGS)** berkecepatan tinggi langsung di dalam viewport 3D.

![Point Cloud & Gaussian Splatting Preview](screenshots/pointcloud_splat.png)

---

## 🌟 Fitur Utama (Key Features)

### 1. Dukungan Format Luas (Multi-Format Support)
* **Point Clouds**: `.ply`, `.las`, `.laz`, `.xyz`, `.pts`, `.txt`, `.csv` (termasuk deteksi otomatis header, koordinat, warna RGB, intensitas, dan normal).
* **3D Gaussian Splatting**: `.ply` (3DGS standar) dan `.splat` (format mentah antarmuka WebGL/web).
* **Synthetic Generator**: Sampel prosedural bawaan (Facade, Dome, Terrain) untuk pengujian tanpa perlu file eksternal.

### 2. Kinerja Tinggi & Akselerasi Native (High-Speed Viewport Engine)
* **Adaptive Dynamic LOD**: Mempertahankan fluiditas rendering (hingga 60+ FPS) bahkan pada dataset puluhan juta titik.
* **Akselerasi C / GCD**: Dilengkapi modul native C (`fast_splat.c`) untuk proyeksi rasterisasi matriks dan pengurutan kedalaman (depth-sorting) secara paralel.
* **Dukungan MultiView / Quad View**: Rendering tersinkronisasi mulus pada split viewport (Top, Front, Right, 3D Isometric).

### 3. Pewarnaan & Visualisasi Lanjutan (Colormaps & Shading)
* **True Color**: Menampilkan warna asli RGB dan spherical harmonics.
* **Elevation Colormaps**: Turbo, Viridis, Jet, dan Terrain colormap untuk analisis elevasi topografi dan kontur.
* **Intensity & Normals**: Visualisasi tingkat reflektansi sensor LiDAR dan orientasi permukaan.

### 4. 3D Section Box / Clipping
* Memotong awan titik secara presisi dengan kotak potong 3D (*Section Box*).
* Memungkinkan visualisasi irisan lantai arsitektural (*floor plan slices*) dan potongan fasad (*elevation sections*).

### 5. CAD Snapping Presisi (Snap-to-Cloud)
* Mengunci kursor alat bawaan IngeTrazo (**Line, Tape Measure, Push/Pull**) langsung ke titik-titik point cloud.
* Memudahkan rekonstruksi as-built drawing langsung di atas hasil scan lapangan.

### 6. Scan-to-BIM & Ekstraksi Geometri
* **RANSAC Dominant Plane Detection**: Ekstraksi bidang dominan (dinding, lantai, plafon) menjadi grup permukaan CAD otomatis.
* **3D Oriented Bounding Box**: Pembuatan volume batas geometris otomatis.
* **Convert to Guide Points**: Mengubah titik-titik kunci menjadi titik bantu CAD native.

---

## 📁 Struktur Direktori

```text
ingetrazo-pointcloud-splat/
├── README.md                      # Dokumentasi & panduan teknis
├── LICENSE                        # Lisensi GPL-3.0-or-later
├── pointcloud_splat.toml          # File katalog resmi untuk IngeTrazo Extensions
├── PANDUAN_SUBMIT.md              # Panduan langkah submit ke website IngeTrazo
├── screenshots/
│   └── pointcloud_splat.png       # Kartu banner katalog (1200x750)
├── dist/
│   └── pointcloud_splat.zip       # Paket installer siap rilis
├── tools/
│   └── build_package.py           # Otomasi build zip & kalkulasi SHA-256
└── pointcloud_splat/              # Source code ekstensi
    ├── __init__.py                # Hook setup(app), overlay & snap provider
    ├── data_models.py             # Struktur data PointCloudDataset & GaussianSplatDataset
    ├── renderer.py                # Pipeline rendering 3D, LOD & shader
    ├── snap_engine.py             # Mesin snapping ke point cloud
    ├── cad_tools.py               # Algoritma Scan-to-BIM (RANSAC plane, bbox, guide)
    ├── gizmo.py                   # Manipulator transform 3D & box interaktif
    ├── scene_proxy.py             # Manajemen proxy scene
    ├── fast_splat.c               # Kernel C rasterizer & parallel depth sorter
    ├── fast_splat.dylib           # Library binary compiled untuk macOS
    ├── parsers/                   # Parser berbagai format file
    │   ├── __init__.py
    │   ├── ply_parser.py
    │   ├── las_parser.py
    │   ├── splat_parser.py
    │   ├── xyz_parser.py
    │   └── synthetic_samples.py
    └── ui/                        # Antarmuka panel pengguna
        ├── __init__.py
        ├── manager_panel.py       # Sidebar dock & kontrol inspektur
        └── icons.py               # Ikon SVG terintegrasi (HiDPI & theme-aware)
```

---

## 🚀 Cara Pemasangan (Installation)

### Cara 1: Unduh dari Katalog Resmi IngeTrazo (Setelah Submit)
1. Buka [ingetrazo.com/extensiones](https://ingetrazo.com/extensiones).
2. Cari **Point Cloud & 3D Gaussian Splatting**, lalu klik **Download**.
3. Ekstrak file zip sehingga menghasilkan folder `pointcloud_splat`.
4. Di IngeTrazo, buka menu: **Extensiones ▸ Abrir carpeta de plugins** (atau *Extensions ▸ Open plugins folder*).
5. Salin folder `pointcloud_splat` ke direktori tersebut.
6. Mulai ulang (*restart*) IngeTrazo.

### Cara 2: Pemasangan Manual dari Repositori Ini
```bash
# Salin folder pointcloud_splat ke folder plugin IngeTrazo
# macOS:
cp -r pointcloud_splat/ "$HOME/Library/Application Support/IngeTrazo/plugins/"

# Linux:
cp -r pointcloud_splat/ "$HOME/.local/share/ingetrazo/plugins/"

# Windows:
# Salin folder pointcloud_splat ke %APPDATA%\IngeTrazo\plugins\
```

---

## 🛠️ Petunjuk Penggunaan

1. Buka **IngeTrazo**.
2. Buka menu: **Extensions > Point Cloud & Gaussian Splatting…** (atau tekan shortcut `Ctrl+Shift+P`).
3. Panel **Point Clouds & Splats** akan muncul di tray samping (*side dock*).
4. Klik **Import File...** dan pilih file scan Anda (`.ply`, `.las`, `.laz`, `.splat`, `.xyz`). Anda juga bisa langsung menyeret (*drag-and-drop*) file ke viewport IngeTrazo.
5. Gunakan kontrol di panel untuk:
   * Mengatur skema warna (*RGB, Elevation, Intensity*).
   * Mengaktifkan kotak potong 3D (*Section Box*).
   * Mengaktifkan *Snap to Points* saat menggambar garis (*Line Tool*).
   * Menjalankan ekstraksi bidang otomatis (*Scan-to-BIM*).

---

## 📦 Pembangunan Paket Distribusi (Build & Release)

Gunakan script otomasi yang telah disediakan:
```bash
python3 tools/build_package.py
```
Script ini akan:
1. Memindai seluruh berkas di `pointcloud_splat/` dan mengabaikan file sementara (`.DS_Store`, `__pycache__`).
2. Membuat arsip distribusi bersih di `dist/pointcloud_splat.zip`.
3. Menghitung nilai hash SHA-256 secara presisi.
4. Memperbarui checksum `sha256` di berkas `pointcloud_splat.toml`.

---

## 📄 Lisensi

Proyek ini dilisensikan di bawah **GNU General Public License v3.0 (GPL-3.0-or-later)**.
Copyright (C) 2026 Marco Sumari Tellez, Archimades, and IngeTrazo contributors.
