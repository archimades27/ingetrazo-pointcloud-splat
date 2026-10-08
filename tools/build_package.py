#!/usr/bin/env python3
"""Build and package Point Cloud & Gaussian Splatting extension for IngeTrazo.

Creates a clean .zip package containing ONE root directory 'pointcloud_splat/'
as required by the official IngeTrazo extension catalog specification:
https://github.com/ingelibre/ingetrazo-extensions
"""

import hashlib
import os
import re
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "pointcloud_splat"
DIST_DIR = PROJECT_ROOT / "dist"
TOML_FILE = PROJECT_ROOT / "pointcloud_splat.toml"
ZIP_NAME = "pointcloud_splat.zip"
ZIP_PATH = DIST_DIR / ZIP_NAME

EXCLUDE_PATTERNS = {
    ".DS_Store",
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".gitignore",
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".swp",
}


def should_exclude(rel_path: Path) -> bool:
    for part in rel_path.parts:
        if part in EXCLUDE_PATTERNS:
            return True
        if part.startswith(".") and part != ".":
            return True
    if rel_path.suffix in EXCLUDE_EXTENSIONS:
        return True
    return False


def build_zip() -> Path:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    print(f"📦 Packaging {SOURCE_DIR.name}/ into {ZIP_PATH}...")
    file_count = 0
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(SOURCE_DIR):
            dirs[:] = [d for d in dirs if not should_exclude(Path(d))]
            for file in sorted(files):
                file_path = Path(root) / file
                rel_path = file_path.relative_to(PROJECT_ROOT)
                if should_exclude(rel_path):
                    continue
                # Store relative to project root so the zip has pointcloud_splat/... as root
                zf.write(file_path, rel_path)
                file_count += 1
                print(f"  + {rel_path}")

    print(f"✅ Packaged {file_count} files successfully.")
    return ZIP_PATH


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def update_toml(sha256: str) -> None:
    if not TOML_FILE.exists():
        print(f"⚠️  {TOML_FILE} does not exist yet. Run create_toml first.")
        return

    content = TOML_FILE.read_text(encoding="utf-8")
    new_content = re.sub(
        r'sha256\s*=\s*"[a-fA-F0-9]*"',
        f'sha256 = "{sha256}"',
        content
    )
    TOML_FILE.write_text(new_content, encoding="utf-8")
    print(f"📝 Updated sha256 in {TOML_FILE.name}")


def main():
    zip_path = build_zip()
    sha256 = compute_sha256(zip_path)
    file_size_kb = zip_path.stat().st_size / 1024

    print("\n" + "=" * 60)
    print(f"  Archive: {zip_path.name} ({file_size_kb:.1f} KB)")
    print(f"  SHA-256: {sha256}")
    print("=" * 60 + "\n")

    update_toml(sha256)


if __name__ == "__main__":
    main()
