"""Helpers for discovering and reading mod README files."""

from __future__ import annotations

from pathlib import Path

from config.config import MOD_README_ENCODINGS, MOD_README_EXTENSIONS


def find_mod_readme_files(mod_folder: str | None) -> list[str]:
    """Return sorted top-level README/text files from the mod folder."""
    if not mod_folder:
        return []
    folder = Path(mod_folder)
    if not folder.is_dir():
        return []
    files = [
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in MOD_README_EXTENSIONS
    ]
    files.sort(key=lambda path: path.name.lower())
    return [str(path) for path in files]


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
    return Path(file_path).suffix.lower() == ".md"
