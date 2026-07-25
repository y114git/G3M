"""Info-file action helpers for the mod editor dialog."""

import os
from collections.abc import Callable

from ui.dialogs.mod_editor.info_files import reset_info_file_entry


def toggle_selected_info_file(entries: list[dict], index: int) -> tuple[list[dict], int]:
    entry = dict(entries[index])
    entry["state"] = "hide" if entry.get("state") == "show" else "show"
    entry["custom"] = True
    updated = list(entries)
    updated[index] = entry
    return updated, index


def move_selected_info_file(entries: list[dict], index: int, step: int) -> tuple[list[dict], int]:
    updated = [dict(entry) for entry in entries]
    if not updated[index].get("custom"):
        updated[index]["custom"] = True
    new_index = max(0, min(len(updated) - 1, index + step))
    if new_index == index:
        return updated, index
    entry = updated.pop(index)
    updated.insert(new_index, entry)
    return updated, new_index


def reset_selected_info_file(
    entries: list[dict],
    index: int,
    *,
    is_file: Callable[[str], bool] = os.path.isfile,
) -> tuple[list[dict], int]:
    updated = [dict(entry) for entry in entries]
    entry = updated[index]
    if entry.get("missing"):
        source_path = str(entry.get("source_path") or "").strip()
        entry["missing"] = not bool(source_path and is_file(source_path))
        updated[index] = entry
        if entry["missing"]:
            return updated, index
    if entry.get("custom"):
        return reset_info_file_entry(updated, index)
    return updated, index


def delete_selected_info_file_entry(
    entries: list[dict],
    index: int,
    *,
    can_delete_file: bool,
    action: str,
    removed_info_files: set[str] | None = None,
) -> tuple[list[dict], int | None]:
    updated = [dict(entry) for entry in entries]
    entry = updated[index]
    if action == "entry" and can_delete_file:
        entry["state"] = "remove"
        entry["custom"] = True
        updated[index] = entry
        if removed_info_files is not None:
            removed_info_files.add(entry["path"])
    updated.pop(index)
    if not updated:
        return updated, None
    return updated, min(index, len(updated) - 1)
