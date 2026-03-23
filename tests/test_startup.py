#!/usr/bin/env python3
"""
Startup test script for DELTAHUB builds.
Extracts archive and verifies the binary can start successfully.
Can be used both as a standalone script and as pytest tests.
"""

import os
import pathlib
import subprocess
import sys
import tempfile
import zipfile

import pytest

TEST_TIMEOUT = 10


def _contains_startup_errors(output: str) -> bool:
    """Check if output contains any startup error markers."""
    error_markers = ["STARTUP ERROR", "CRITICAL ERROR", "Fatal error"]
    return any(marker in output for marker in error_markers)


def test_startup_from_environment():
    """Test startup using environment variables (CI) or local main.py (dev)."""
    if "ARCHIVE_PATH" not in os.environ or "STARTUP_TARGET" not in os.environ:
        project_root = pathlib.Path(__file__).parent.parent
        main_py = project_root / "src" / "main.py"
        if not main_py.exists():
            pytest.skip("Neither CI env vars nor local main.py available")
        result = subprocess.run(
            [sys.executable, str(main_py), "--help"],
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT,
            cwd=str(project_root),
        )
        output = (result.stdout or "") + (result.stderr or "")
        assert not _contains_startup_errors(output), (
            "Application startup failed with startup error(s)"
        )
        return

    archive_path = pathlib.Path(os.environ["ARCHIVE_PATH"])
    startup_target = os.environ["STARTUP_TARGET"]

    success = _test_startup_with_archive(archive_path, startup_target)
    assert success, f"Startup test failed for {startup_target}"


def test_startup_with_sample_archive(tmp_path):
    """Test startup with a sample archive (for local testing)."""

    project_root = pathlib.Path(__file__).parent.parent
    main_py_path = project_root / "src" / "main.py"

    if not main_py_path.exists():
        pytest.skip(f"main.py not found at {main_py_path}")

    sample_archive_path = tmp_path / "sample_app.zip"

    with zipfile.ZipFile(sample_archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(main_py_path, "main.py")

        src_dir = project_root / "src"
        if src_dir.exists():
            for file_path in src_dir.rglob("*.py"):
                if file_path.is_file():
                    arc_path = file_path.relative_to(project_root)
                    if file_path.samefile(main_py_path):
                        continue
                    archive.write(file_path, arc_path)

    success = _test_startup_with_archive(sample_archive_path, "main.py")
    assert success, "Sample archive startup test failed"


def test_local_startup():
    """Test local application startup by running main.py initialization."""

    project_root = pathlib.Path(__file__).parent.parent
    main_py_path = project_root / "src" / "main.py"

    if not main_py_path.exists():
        pytest.skip(f"main.py not found at {main_py_path}")

    try:
        result = subprocess.run(
            [sys.executable, str(main_py_path), "--help"],
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT,
            cwd=str(project_root),
        )

        output = (result.stdout or "") + (result.stderr or "")
        assert not _contains_startup_errors(output), (
            "Application startup failed with startup error(s)"
        )

    except subprocess.TimeoutExpired:
        pytest.fail(f"Application startup timed out after {TEST_TIMEOUT} seconds")
    except Exception as e:
        pytest.fail(f"Unexpected error during startup test: {e}")


def _test_startup_with_archive(archive_path: pathlib.Path, startup_target: str) -> bool:
    """Core startup testing logic."""
    try:
        with tempfile.TemporaryDirectory() as extract_dir:
            extract_path = pathlib.Path(extract_dir)
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extract_path)

            target = extract_path / startup_target
            if not target.exists():
                return False

            target.chmod(target.stat().st_mode | 0o111)
            cwd = str(extract_path)

            if startup_target.endswith(".py"):
                result = subprocess.run(
                    [sys.executable, str(target), "--help"],
                    capture_output=True,
                    text=True,
                    timeout=TEST_TIMEOUT,
                    cwd=cwd,
                )
            else:
                result = subprocess.run(
                    [str(target), "--help"],
                    capture_output=True,
                    text=True,
                    timeout=TEST_TIMEOUT,
                    cwd=cwd,
                )
            output = (result.stdout or "") + (result.stderr or "")
            return not _contains_startup_errors(output)

    except subprocess.TimeoutExpired:
        print(f"Startup test timed out after 10 seconds for {startup_target}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Startup test failed with exception for {startup_target}: {e}", file=sys.stderr)
        return False


def main():
    """Main function for standalone script usage."""
    if "ARCHIVE_PATH" not in os.environ or "STARTUP_TARGET" not in os.environ:
        raise SystemExit(1)

    archive_path = pathlib.Path(os.environ["ARCHIVE_PATH"])
    startup_target = os.environ["STARTUP_TARGET"]

    success = _test_startup_with_archive(archive_path, startup_target)
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
