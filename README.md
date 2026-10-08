# Point Cloud & 3D Gaussian Splatting for IngeTrazo

[![IngeTrazo](https://img.shields.io/badge/IngeTrazo-v0.5.7+-007ACC.svg)](https://ingetrazo.com)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-green.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Version](https://img.shields.io/badge/Version-1.0.0-orange.svg)](https://github.com/archimades27/ingetrazo-pointcloud-splat/releases/tag/v1.0.0)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9+-yellow.svg)]()
[![Platform: macOS | Linux | Windows](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)]()

> **The definitive high-performance Point Cloud (LiDAR, Photogrammetry) and 3D Gaussian Splatting (3DGS) extension for [IngeTrazo](https://ingetrazo.com) CAD/BIM modeler.**

![Point Cloud & Gaussian Splatting Preview](screenshots/pointcloud_splat.png)

---

## 📖 Ringkasan (Overview)

Ekstensi ini mengintegrasikan pemrosesan dan visualisasi data pemindaian 3D secara native ke dalam **IngeTrazo**. Anda dapat mengimpor file hasil pemindaian drone, pemindai LiDAR darat, model fotogrametri, dan model radiansi volumetrik modern (*3D Gaussian Splats*), lalu melakukan **CAD snapping** presisi tinggi untuk menggambar as-built drawings (*Scan-to-BIM*) dengan kecepatan hingga **60+ FPS**.

---

## 📊 Format Berkas yang Didukung (Supported Formats)

| Format | Ekstensi | Deskripsi & Kemampuan |
| :--- | :--- | :--- |
| **Polygon File Format** | `.ply` | ASCII & Binary Little-Endian. Mendukung point cloud standar (XYZ + RGB + Normal) dan model volumetrik **3D Gaussian Splatting** (Spherical Harmonics orde 0–3, skala kovarian, kuaternion rotasi). |
| **LiDAR ASPRS** | `.las`, `.laz` | Standar industri LiDAR penerbangan dan terestrial (ASPRS LAS 1.1 – 1.4). Mendukung koordinat XYZ floating-point, warna RGB 16-bit/8-bit, dan intensitas reflektansi sensor. |
| **Raw WebGL Splats** | `.splat` | Format terkompresi mentah 32-byte chunk (kompatibel dengan antimatter15, Luma, SuperSplat, Polycam, dan WebGL viewers). |
| **ASCII Table / Points** | `.xyz`, `.pts`, `.txt`, `.csv` | Deteksi otomatis delimiter (koma, spasi, tab). Mengurai koordinat XYZ, RGB (0–255 atau 0.0–1.0), serta kolom intensitas. |

---

## 🌟 Fitur Utama & Kemampuan (Key Features)

### 🚀 1. Engine Rendering Viewport Berkecepatan Tinggi (Up to 60+ FPS)
* **Kernel Akselerasi C / GCD**: Dilengkapi modul C teroptimasi (`fast_splat.c`) dengan SIMD dan multithreading (Apple Grand Central Dispatch / parallel sorting) untuk proyeksi splat dan rasterisasi piksel sub-milidetik.
* **Adaptive Dynamic LOD (Level of Detail)**: Mengatur kepadatan titik dan anggaran memori secara cerdas selama manipulasi viewport (orbit, pan, zoom) sehingga navigasi tetap halus tanpa jeda (lag), bahkan pada awan titik dengan puluhan juta koordinat.
* **Dukungan MultiView / Quad Viewports**: Tersinkronisasi mulus pada tata letak multi-viewport IngeTrazo (Tampak Atas/Top, Tampak Depan/Front, Tampak Samping/Right, dan Perspektif/ISO).

### 🎨 2. Ragam Skema Pewarnaan (Colormaps & Shaders)
* **True Color (RGB / SH)**: Menampilkan warna alami asli dari kamera fotogrametri atau pemindai LiDAR.
* **Elevation Colormaps**: Menghasilkan gradien warna topografi berdasarkan ketinggian sumbu Z (*Turbo, Viridis, Jet, Terrain*). Sangat ideal untuk analisis kontur tanah dan grading tapak.
* **LiDAR Intensity**: Memvisualisasikan daya reflektansi permukaan material untuk membedakan jalan aspal, vegetasi, air, dan dinding bangunan.
* **Surface Normals**: Menampilkan orientasi arah bidang permukaan titik dalam warna RGB vektor normal.

### ✂️ 3. 3D Section Box / Clipping Interaktif
* Kotak potong 3D (*Section Box*) yang dapat disesuaikan secara dinamis menggunakan slider batas sumbu X, Y, Z.
* Memotong awan titik secara instan untuk menampilkan irisan denah lantai (*floor plan slices*) atau potongan dinding/fasad (*elevation sections*).

### 🧲 4. Native CAD Snapping (Snap-to-Cloud)
* Mengintegrasikan awan titik dengan alat-alat gambar bawaan IngeTrazo (**Line Tool, Tape Measure, Push/Pull**).
* Kursor CAD akan otomatis mengunci (*snap*) ke titik awan terdekat (*Nearest Point* atau *Vertex Point*) dengan indikator visual kursor berwarna hijau.
* Memungkinkan tracing denah dan penarikan garis as-built 3D langsung di atas model scan lapangan.

### 🏛️ 5. Alat Scan-to-BIM Otomatis
* **RANSAC Dominant Plane Extraction**: Algoritma RANSAC bawaan untuk mendeteksi bidang dominan (dinding, lantai, pelat atap) dari awan titik yang dipilih dan mengonversinya menjadi grup bidang CAD IngeTrazo.
* **3D Oriented Bounding Box (OBB)**: Menghasilkan kotak batas volume 3D yang membungkus objek secara akurat.
* **Convert to Guide Points**: Mengekspor titik-titik sampel kunci menjadi *Guide Points* (titik bantu konstruksi) native di model IngeTrazo.

### 🧪 6. Sampel Prosedural Bawaan (Built-in Demos)
* Jika Anda belum memiliki file scan, ekstensi ini menyediakan generator sampel langsung dari antarmuka:
  - **🏛️ Classic Facade**: Fasad bangunan klasik dengan kolom dan bukaan jendela.
  - **🌐 Geodesic Dome**: Struktur kubah parametrik 3D Gaussian Splatting.
  - **⛰️ Mountain Terrain**: Model kontur topografi bergradasi elevasi Turbo.

---

## 🖥️ Antarmuka & Panel Pengaturan (UI Overview)

Panel **Point Clouds & Splats** terletak di side dock kanan IngeTrazo dan dibagi menjadi beberapa bagian rapi:

| Seksi Panel | Fungsi & Kontrol |
| :--- | :--- |
| **Datasets Manager** | Menampilkan daftar file yang sedang aktif, tombol toggle mata (visibilitas), tombol fokus kamera, dan tombol hapus (*trash*). |
| **Display & Shading** | Pilihan mode warna (*RGB, Turbo, Viridis, Jet, Terrain, Intensity, Normals*), ukuran titik (*Point Size*: 1–12 px), dan tingkat transparansi (*Opacity*). |
| **3D Transform & Gizmo** | Menggeser (*Offset X, Y, Z*), memutar (*Rotation Yaw/Pitch/Roll*), dan mengubah skala (*Scale Factor*) model scan agar tepat sejajar dengan sumbu proyek. |
| **3D Section Box** | Mengaktifkan kotak pembatas potongan 3D dengan batas Min/Max X, Y, Z untuk inspeksi internal struktur. |
| **CAD Snapping** | Mengaktifkan/menonaktifkan snap kursor serta mengatur radius toleransi penangkapan titik (10–50 px). |
| **Scan-to-BIM Tools** | Tombol eksekusi RANSAC Plane Detection, Bounding Box, dan Guide Points. |

---

## 🚀 Panduan Pemasangan (Installation)

### Metode 1: Melalui Katalog Resmi IngeTrazo (Rekomendasi)
1. Buka katalog web resmi di [ingetrazo.com/extensiones](https://ingetrazo.com/extensiones).
2. Temukan **Point Cloud & 3D Gaussian Splatting**, lalu klik **Download**.
3. Ekstrak file zip yang diunduh sehingga menghasilkan folder `pointcloud_splat`.
4. Di dalam IngeTrazo, buka menu:
   **Extensiones ▸ Abrir carpeta de plugins** *(atau Extensions ▸ Open plugins folder)*.
5. Salin folder `pointcloud_splat` ke direktori plugin tersebut.
6. Mulai ulang (*restart*) IngeTrazo.

### Metode 2: Pemasangan Manual dari Repositori Ini
Salin folder `pointcloud_splat` ke direktori plugin sesuai sistem operasi Anda:

* **macOS**:
  ```bash
  cp -r pointcloud_splat/ "$HOME/Library/Application Support/IngeTrazo/plugins/"
  ```
* **Linux**:
  ```bash
  cp -r pointcloud_splat/ "$HOME/.local/share/ingetrazo/plugins/"
  ```
* **Windows**:
  Salin folder `pointcloud_splat` ke direktori `%APPDATA%\IngeTrazo\plugins\`.

---

## 🎯 Panduan Penggunaan Singkat

1. Buka aplikasi **IngeTrazo**.
2. Buka menu **Extensions > Point Cloud & Gaussian Splatting…** atau tekan tombol pintas **`Ctrl+Shift+P`**.
3. Panel samping akan terbuka otomatis.
4. **Cara Impor File**:
   * Klik tombol **Import File...** lalu pilih berkas scan Anda, atau
   * Cukup **seret dan lepas (*drag & drop*)** file `.ply`, `.las`, `.splat`, atau `.xyz` langsung ke area gambar viewport 3D.
5. Gunakan tombol **Line Tool** bawaan IngeTrazo untuk mulai menggambar denah atau dinding mengikuti titik-titik hasil scan.

---

## 📦 Pembangunan Paket Distribusi (Building the Package)

Jika Anda ingin memodifikasi kode atau membangun ulang arsip distribusi `.zip`:
```bash
python3 tools/build_package.py
```
Skrip ini akan:
1. Membersihkan berkas sementara (`.DS_Store`, `__pycache__`).
2. Mengemas direktori `pointcloud_splat/` ke dalam file distribusi `dist/pointcloud_splat.zip`.
3. Menghitung nilai hash SHA-256 berkas zip secara otomatis.
4. Memperbarui checksum pada berkas katalog `pointcloud_splat.toml`.

---

## 📄 Lisensi (License)

Proyek ini merupakan perangkat lunak bebas yang dilisensikan di bawah **[GNU General Public License v3.0 (GPL-3.0-or-later)](LICENSE)**.

```text
Copyright (C) 2026 Archimades (archimades27) and IngeTrazo contributors.
```
Anda bebas menggunakan, memodifikasi, dan mendistribusikan perangkat lunak ini sesuai ketentuan GPLv3.
