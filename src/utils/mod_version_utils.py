"""Utilities for managing mod versions and snapshots."""

import os
import zipfile

MOD_VERSIONS_DIR = "mod_versions"


def ensure_versions_dir(mod_folder: str) -> str:
    """Ensure the versions directory exists in the mod folder."""
    d = os.path.join(mod_folder, MOD_VERSIONS_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def create_version_zip(
    source_dir: str,
    mod_folder: str,
    version_name: str,
    ignore_versions_dir: bool = False,
) -> str:
    """Create a version zip from source directory."""
    versions_dir = ensure_versions_dir(mod_folder)
    safe_name = sanitize_version_name(version_name)
    zip_path = os.path.join(versions_dir, f"{safe_name}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(source_dir):
            if ignore_versions_dir and MOD_VERSIONS_DIR in dirs:
                dirs.remove(MOD_VERSIONS_DIR)
            for fname in files:
                full = os.path.join(root, fname)
                arcname = os.path.relpath(full, source_dir)
                zf.write(full, arcname)
    return zip_path


def sanitize_version_name(name: str) -> str:
    """Sanitize version name for safe filename."""
    return (
        "".join(c if c.isalnum() or c in " _-." else "_" for c in name).strip()
        or "version"
    )
