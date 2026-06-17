"""Regression tests for top-level package resolution."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO_SRC = Path(__file__).resolve().parents[2] / "src"
TOP_LEVEL_PACKAGES = [
    "adapters",
    "app",
    "app_context",
    "bootstrap",
    "config",
    "controllers",
    "models",
    "presentation",
    "services",
    "session",
    "ui",
    "utils",
    "workers",
]


def _clear_repo_packages() -> None:
    for name in list(sys.modules):
        if name in TOP_LEVEL_PACKAGES or any(
            name.startswith(f"{package}.") for package in TOP_LEVEL_PACKAGES
        ):
            del sys.modules[name]


def test_local_top_level_packages_beat_later_installed_packages(tmp_path):
    """Checks that local top-level imports stay stable when same-named packages exist later."""
    fake_site_packages = tmp_path / "fake_site_packages"
    for package_name in TOP_LEVEL_PACKAGES:
        fake_package = fake_site_packages / package_name
        fake_package.mkdir(parents=True, exist_ok=True)
        (fake_package / "__init__.py").write_text("# fake installed package\n")

    original_path = sys.path[:]
    original_modules = {
        name: module
        for name, module in sys.modules.items()
        if name in TOP_LEVEL_PACKAGES
        or any(name.startswith(f"{package}.") for package in TOP_LEVEL_PACKAGES)
    }
    try:
        sys.path[:] = [
            str(REPO_SRC),
            str(fake_site_packages),
            *[
                path
                for path in original_path
                if path not in {str(REPO_SRC), str(fake_site_packages)}
            ],
        ]
        _clear_repo_packages()

        for package_name in TOP_LEVEL_PACKAGES:
            module = importlib.import_module(package_name)
            package_root = Path(module.__file__).resolve().parent
            assert package_root == (REPO_SRC / package_name).resolve()
    finally:
        sys.path[:] = original_path
        _clear_repo_packages()
        sys.modules.update(original_modules)
