"""Helpers for validating generated patch artifacts before exposing them to users."""

from __future__ import annotations

import os
import shutil
import tempfile


def files_match(path_a: str, path_b: str) -> bool:
    """Return True when two files are byte-identical."""
    if os.path.getsize(path_a) != os.path.getsize(path_b):
        return False
    with open(path_a, "rb") as handle_a, open(path_b, "rb") as handle_b:
        while True:
            chunk_a = handle_a.read(1024 * 1024)
            chunk_b = handle_b.read(1024 * 1024)
            if chunk_a != chunk_b:
                return False
            if not chunk_a:
                return True


def verify_generated_patch(
    g3mtool,
    original_data: str,
    modified_data: str,
    patch_path: str,
    *,
    patch_type: str,
) -> tuple[bool, str]:
    """Apply a newly-created patch and confirm it reproduces the expected output."""
    temp_dir = tempfile.mkdtemp(prefix="g3m_patch_verify_")
    try:
        temp_output = os.path.join(temp_dir, os.path.basename(modified_data))
        if patch_type == "g3mpatch":
            returncode, stdout, stderr = g3mtool.apply_patch(
                original_data, patch_path, temp_output
            )
        elif patch_type == "xdelta":
            returncode, stdout, stderr = g3mtool.xpatch_apply(
                original_data, patch_path, temp_output
            )
        else:
            return False, f"Unsupported patch type for verification: {patch_type}"
        if returncode != 0:
            details = (stderr or stdout or "").strip()[:300]
            suffix = f": {details}" if details else ""
            return (
                False,
                f"Generated {patch_type} patch failed verification apply{suffix}",
            )
        if not os.path.isfile(temp_output):
            return (
                False,
                f"Generated {patch_type} patch failed verification: output file was not created",
            )
        if not files_match(temp_output, modified_data):
            return (
                False,
                f"Generated {patch_type} patch failed verification: reapplied data does not match expected output",
            )
        return True, ""
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
