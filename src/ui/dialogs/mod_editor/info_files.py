"""Pure info-file helpers for ModEditorDialog."""

from __future__ import annotations

import os


def normalize_info_file_state(value) -> str:
    state = str(value or "").strip().lower()
    return state if state in {"show", "hide", "remove"} else "show"


def normalize_info_file_name(path: str) -> str:
    return os.path.basename(str(path or "").replace("\\", "/").strip())


def merge_info_file_entry(
    entries: list[dict],
    *,
    file_path: str,
    visible: bool = True,
    custom: bool = True,
    source_path: str | None = None,
) -> list[dict]:
    normalized_path = normalize_info_file_name(file_path)
    if not normalized_path:
        return entries
    source = source_path or file_path
    merged = [dict(entry) for entry in entries]
    for entry in merged:
        if entry.get("path") == normalized_path:
            entry["state"] = "show" if visible else "hide"
            entry["custom"] = custom or entry.get("custom", False)
            entry["source_path"] = source
            return merged
    merged.append(
        {
            "path": normalized_path,
            "state": "show" if visible else "hide",
            "custom": custom,
            "source_path": source,
        }
    )
    return merged


def reset_info_file_entry(entries: list[dict], index: int) -> tuple[list[dict], int]:
    updated = [dict(entry) for entry in entries]
    entry = updated[index]
    if entry.get("custom"):
        fallback_entry = {
            "path": entry["path"],
            "state": "show",
            "custom": False,
            "source_path": entry.get("source_path"),
            "missing": False,
        }
        updated.pop(index)
        inserted = False
        for candidate_index, candidate in enumerate(updated):
            if not candidate.get("custom") and candidate["path"].lower() > entry["path"].lower():
                updated.insert(candidate_index, fallback_entry)
                inserted = True
                index = candidate_index
                break
        if not inserted:
            updated.append(fallback_entry)
            index = len(updated) - 1
    return updated, index


def collect_info_files(entries: list[dict], removed_paths: set[str]) -> dict[str, str]:
    info_files: dict[str, str] = {}
    for entry in entries:
        if entry.get("custom"):
            info_files[entry["path"]] = normalize_info_file_state(entry.get("state"))
    for path in removed_paths:
        info_files[path] = "remove"
    return info_files
