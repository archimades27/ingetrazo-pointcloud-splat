# Panduan Submit Ekstensi Point Cloud & Gaussian Splatting ke Katalog IngeTrazo

Panduan lengkap ini menjelaskan langkah-langkah praktis untuk mempublikasikan ekstensi Anda ke katalog resmi website [ingetrazo.com/extensiones](https://ingetrazo.com/extensiones).

---

## 📋 Ringkasan Berkas yang Telah Disiapkan

Semua berkas persiapan telah siap di folder:
`/Users/archimades/.gemini/antigravity/scratch/ingetrazo-pointcloud-splat/`

1. **`dist/pointcloud_splat.zip`**: Arsip zip bersih berisi folder tunggal `pointcloud_splat/` dengan `__init__.py`.
2. **`pointcloud_splat.toml`**: Berkas manifest katalog resmi yang sudah terisi lengkap dengan hash SHA-256 (`ae95b72a90c06bf8ea894083db9f4a6ae24cd5ffe42de4415fb2d44921c22422`).
3. **`screenshots/pointcloud_splat.png`**: Gambar banner resolusi 1200×750 (<600 KB) untuk tampilan kartu di website.
4. **`README.md` & `LICENSE`**: Dokumentasi lengkap dan lisensi GPL-3.0.
5. **`tools/build_package.py`**: Skrip otomatis jika Anda melakukan perubahan kode dan ingin membuat zip + hash baru.

---

## 🚀 Langkah 1: Buat Repositori Publik di GitHub

1. Buka [github.com/new](https://github.com/new).
2. Buat repositori baru bernama: **`ingetrazo-pointcloud-splat`** (atur visibilitas ke **Public**).
3. Di terminal komputer Anda, inisialisasi git dan upload kode ini:
   ```bash
   cd /Users/archimades/.gemini/antigravity/scratch/ingetrazo-pointcloud-splat
   git init
   git add .
   git commit -m "feat: initial release of point cloud & gaussian splatting extension v1.0.0"
   git branch -M main
   git remote add origin https://github.com/archimades27/ingetrazo-pointcloud-splat.git
   git push -u origin main
   ```
   *(Ganti `<USERNAME-ANDA>` dengan username akun GitHub Anda).*

---

## 🏷️ Langkah 2: Buat Release `v1.0.0` di GitHub

Katalog IngeTrazo mewajibkan tautan unduhan permanen yang diikat ke Release/Tag tertentu (bukan link branch `main`):

1. Di repositori GitHub Anda, buka tab **Releases** di kolom kanan, lalu klik **Create a new release** (atau buka `https://github.com/<USERNAME-ANDA>/ingetrazo-pointcloud-splat/releases/new`).
2. Masukkan tag: **`v1.0.0`** (buat tag baru saat publikasi).
3. Beri judul rilis: `v1.0.0 - Point Cloud & 3D Gaussian Splatting`.
4. Unggah berkas **`dist/pointcloud_splat.zip`** ke bagian aset rilis (*Attach binaries by dropping them here*).
5. Klik **Publish release**.

> **Verifikasi Link Download**:
> URL download Anda akan menjadi:
> `https://github.com/<USERNAME-ANDA>/ingetrazo-pointcloud-splat/releases/download/v1.0.0/pointcloud_splat.zip`

---

## 📝 Langkah 3: Sesuaikan Username di `pointcloud_splat.toml`

Buka berkas `pointcloud_splat.toml` di teks editor, pastikan nama dan URL mengarah ke akun GitHub Anda:
```toml
id = "pointcloud_splat"
version = "1.0.0"
author = "Nama atau Handle Anda"
author_url = "https://github.com/<USERNAME-ANDA>"

license = "GPL-3.0-or-later"

repository = "https://github.com/<USERNAME-ANDA>/ingetrazo-pointcloud-splat"
download = "https://github.com/<USERNAME-ANDA>/ingetrazo-pointcloud-splat/releases/download/v1.0.0/pointcloud_splat.zip"
sha256 = "ae95b72a90c06bf8ea894083db9f4a6ae24cd5ffe42de4415fb2d44921c22422"

ingetrazo = "0.5.7"
tags = ["bim", "productivity", "drawing"]
screenshot = "pointcloud_splat.png"

[name]
en = "Point Cloud & 3D Gaussian Splatting"
es = "Nube de Puntos y Gaussian Splatting 3D"
pt = "Nuvem de Pontos e Gaussian Splatting 3D"

[summary]
en = "Import, inspect, and snap to LiDAR/photogrammetry point clouds (.ply, .las, .laz, .xyz) and 3D Gaussian Splats (.splat) with accelerated viewport rendering, section box clipping, and Scan-to-BIM tools."
es = "Importación, inspección y ajuste (snap) a nubes de puntos LiDAR/fotogrametría (.ply, .las, .laz, .xyz) y Gaussian Splats 3D (.splat) con renderizado acelerado, caja de sección y herramientas Scan-to-BIM."
pt = "Importação, inspeção e snap em nuvens de pontos LiDAR/fotogrametria (.ply, .las, .laz, .xyz) e Gaussian Splats 3D (.splat) com renderização acelerada, caixa de corte e ferramentas Scan-to-BIM."
```

*(Jika Anda melakukan perubahan isi file zip, jalankan `python3 tools/build_package.py` untuk mengupdate nilai sha256).*

---

## 🌐 Langkah 4: Submit ke Repositori Resmi IngeTrazo

1. Kunjungi repositori resmi: **[github.com/ingelibre/ingetrazo-extensions](https://github.com/ingelibre/ingetrazo-extensions)**.
2. **Tambah Berkas TOML**:
   * Buka folder **`extensions/`**.
   * Klik **Add file ▸ Create new file**.
   * Beri nama file: `pointcloud_splat.toml`.
   * Salin seluruh isi dari `pointcloud_splat.toml` lokal ke editor GitHub tersebut.
   * Pilih opsi **Create a new branch for this commit and start a pull request**.
3. **Tambah Screenshot (Opsional tapi Sangat Direkomendasikan)**:
   * Di PR branch yang sama (atau commit tambahan), unggah file `screenshots/pointcloud_splat.png` ke dalam folder **`screenshots/`** di repositori tersebut.
4. **Buka Pull Request**:
   * Klik tombol **Create pull request**.
   * Beri judul: `Add Point Cloud & 3D Gaussian Splatting extension`.

---

## 🤖 Langkah 5: Otomasi Bot & Verifikasi

* Dalam kurun waktu sekitar 1 menit setelah PR dibuka, bot GitHub Actions IngeTrazo akan membaca file `pointcloud_splat.toml`.
* Bot akan mengunduh `pointcloud_splat.zip` dari Release Anda, memverifikasi bahwa checksum SHA-256 cocok 100%, memeriksa fungsi `setup(app)`, dan mengecek lisensi bebas.
* Setelah lolos dan diapprove, katalog di **[ingetrazo.com/extensiones](https://ingetrazo.com/extensiones)** akan otomatis terbarui dan menampilkan ekstensi Anda secara publik!
