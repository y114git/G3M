"""Pure path helpers for ManualModInstallDialog."""

from __future__ import annotations

import os


def normalize_path(path: str, *, trailing_slash: bool = False) -> str:
    normalized = str(path or "").replace("\\", "/").strip()
    normalized = normalized.strip("/")
    if not normalized:
        return ""
    return f"{normalized}/" if trailing_slash else normalized


def extract_chapter_prefixed_path(
    path: str,
    *,
    chapter_alias_map: dict[str, str],
    trailing_slash: bool | None = None,
) -> tuple[str | None, str]:
    if trailing_slash is None:
        trailing_slash = str(path or "").endswith(("/", "\\"))
    normalized = normalize_path(path, trailing_slash=trailing_slash)
    if not normalized:
        return None, ""
    preserve_trailing = normalized.endswith("/")
    working = normalized[:-1] if preserve_trailing else normalized
    if not working:
        return None, ""
    first_part, _, rest = working.partition("/")
    chapter_id = chapter_alias_map.get(first_part.lower())
    if not chapter_id:
        return None, normalized
    if not rest:
        return chapter_id, ""
    return chapter_id, f"{rest}/" if preserve_trailing else rest


def strip_chapter_prefix(
    normalized_path: str, chapter_id: str, *, chapter_aliases: set[str]
) -> str:
    if not normalized_path:
        return ""
    stripped = normalized_path
    lowered = stripped.lower()
    for alias in chapter_aliases:
        if lowered == alias:
            return ""
        prefix = f"{alias}/"
        if lowered.startswith(prefix):
            stripped = stripped[len(prefix) :]
            lowered = stripped.lower()
    return stripped


def normalize_relative_target_path(
    path: str,
    chapter_id: str,
    *,
    chapter_aliases: set[str],
    trailing_slash: bool = False,
) -> str:
    normalized = normalize_path(path, trailing_slash=trailing_slash)
    if not normalized:
        return ""
    preserve_trailing = normalized.endswith("/")
    working = normalized[:-1] if preserve_trailing else normalized
    working = strip_chapter_prefix(
        working, chapter_id, chapter_aliases=chapter_aliases
    )
    if not working:
        return ""
    return f"{working}/" if preserve_trailing else working


def default_extra_target_path(
    *,
    file_path: str,
    rel_path: str,
    chapter_alias_map: dict[str, str],
) -> tuple[str, str | None]:
    normalized = str(rel_path or "").replace("\\", "/").strip("/")
    chapter_id, stripped = extract_chapter_prefixed_path(
        normalized,
        chapter_alias_map=chapter_alias_map,
    )
    if chapter_id:
        normalized = stripped.strip("/")
    if not normalized:
        return "", chapter_id
    dir_part = os.path.dirname(normalized).replace("\\", "/").strip("/")
    return normalize_path(dir_part, trailing_slash=True), chapter_id
