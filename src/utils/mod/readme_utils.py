"""Helpers for discovering and reading mod README files."""

from __future__ import annotations

import json
from pathlib import Path

from config.config import (
    MOD_CONFIG_FILENAME,
    MOD_DOCUMENTATION_EXTENSIONS,
    MOD_HTML_EXTENSIONS,
    MOD_MARKDOWN_EXTENSIONS,
    MOD_PDF_EXTENSIONS,
    MOD_README_ENCODINGS,
)
from utils.mod.config_parser import _sanitize_info_files


def _load_info_files_config(folder: Path) -> dict[str, str]:
    config_path = folder / MOD_CONFIG_FILENAME
    if not config_path.is_file():
        return {}
    try:
        with config_path.open(encoding="utf-8") as handle:
            config_data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return _sanitize_info_files(config_data.get("info_files"))


def find_mod_info_candidates(mod_folder: str | None) -> list[str]:
    """Return sorted top-level documentation file names from the mod folder."""
    if not mod_folder:
        return []
    folder = Path(mod_folder)
    if not folder.is_dir():
        return []
    return sorted(
        [
            path.name
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in MOD_DOCUMENTATION_EXTENSIONS
        ],
        key=str.lower,
    )


def find_mod_readme_files(mod_folder: str | None) -> list[str]:
    """Return ordered top-level README/text files from the mod folder."""
    if not mod_folder:
        return []
    folder = Path(mod_folder)
    if not folder.is_dir():
        return []
    files = [
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in MOD_DOCUMENTATION_EXTENSIONS
    ]
    files_by_name = {path.name: path for path in files}
    ordered: list[str] = []
    seen: set[str] = set()
    for rel_path, visibility in _load_info_files_config(folder).items():
        path = files_by_name.get(Path(rel_path).name)
        if not path or path.name in seen:
            continue
        seen.add(path.name)
        if visibility == "show":
            ordered.append(str(path))
    for path in sorted(files, key=lambda item: item.name.lower()):
        if path.name not in seen:
            ordered.append(str(path))
    return ordered


def read_mod_readme(file_path: str) -> str:
    """Read a README file with a few safe encoding fallbacks."""
    path = Path(file_path)
    for encoding in MOD_README_ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def is_markdown_file(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in MOD_MARKDOWN_EXTENSIONS


def is_html_file(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in MOD_HTML_EXTENSIONS


def is_pdf_file(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in MOD_PDF_EXTENSIONS
