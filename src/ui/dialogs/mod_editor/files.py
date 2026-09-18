"""File collection helpers for the mod editor dialog."""

import os

from PyQt6.QtWidgets import QCheckBox, QLabel, QLineEdit

from services.migration_service import (
    EXTRA_FILE_TARGET_CUSTOM,
    EXTRA_FILE_TARGET_GAME_DATA_FOLDER,
    EXTRA_FILE_TARGET_GAME_FOLDER,
    EXTRA_FILE_TARGET_NONE,
    build_extra_file_entry,
    normalize_extra_file_target,
)


def extract_frame_data(layout, *, format_config_path):
    if layout.count() == 0:
        return None
    title_w = layout.itemAt(0).widget() if layout.itemAt(0) else None
    if not isinstance(title_w, QLabel):
        return None
    ftype = title_w.property("file_type")
    if ftype == "data":
        path_edit = None
        for i in range(layout.count()):
            w = layout.itemAt(i).widget() if layout.itemAt(i) else None
            if isinstance(w, QLineEdit) and w.property("is_local_path"):
                path_edit = w
        if path_edit and path_edit.text():
            return {
                "type": "data",
                "path": format_config_path(path_edit.text()),
            }
    elif ftype == "extra":
        paths = []
        target = EXTRA_FILE_TARGET_GAME_FOLDER
        target_path = ""
        for i in range(layout.count()):
            w = layout.itemAt(i).widget() if layout.itemAt(i) else None
            if (
                isinstance(w, QLineEdit)
                and w.property("is_local_extra_path")
                and w.text()
            ):
                paths.append(format_config_path(w.text()))
            elif isinstance(w, QCheckBox) and w.property("is_none_target_file"):
                target = EXTRA_FILE_TARGET_NONE if w.isChecked() else target
            elif isinstance(w, QCheckBox) and w.property("is_data_folder_file"):
                target = EXTRA_FILE_TARGET_GAME_DATA_FOLDER if w.isChecked() else target
            elif isinstance(w, QCheckBox) and w.property("is_custom_target_file"):
                target = EXTRA_FILE_TARGET_CUSTOM if w.isChecked() else target
            elif isinstance(w, QLineEdit) and w.property("is_custom_target_path"):
                target_path = w.text().strip()
        if paths:
            return {
                "type": "extra",
                "paths": paths,
                "target": target,
                "target_path": target_path,
            }
    return None


def iter_tab_frames(file_tabs, *, get_tab_file_layout, extract_frame_data_fn):
    for i in range(file_tabs.count()):
        tab = file_tabs.widget(i)
        layout = get_tab_file_layout(tab)
        if not tab or not layout:
            continue
        for j in range(layout.count()):
            item = layout.itemAt(j)
            w = item.widget() if item else None
            if not w or not hasattr(w, "layout") or not (frame_layout := w.layout()):
                continue
            data = extract_frame_data_fn(frame_layout)
            if data:
                yield i, file_tabs.tabText(i), data


def has_any_mod_files(file_tabs, *, get_tab_file_layout, extract_frame_data_fn) -> bool:
    return any(
        d.get("path") or d.get("paths")
        for _, _, d in iter_tab_frames(
            file_tabs,
            get_tab_file_layout=get_tab_file_layout,
            extract_frame_data_fn=extract_frame_data_fn,
        )
    )


def validate_local_files(
    file_tabs,
    *,
    get_tab_file_layout,
    extract_frame_data_fn,
    resolve_file_path,
    path_exists=os.path.exists,
):
    for _, tab_name, data in iter_tab_frames(
        file_tabs,
        get_tab_file_layout=get_tab_file_layout,
        extract_frame_data_fn=extract_frame_data_fn,
    ):
        if (p := data.get("path")) and not path_exists(resolve_file_path(p)):
            return ("data", tab_name, p)
        for p in data.get("paths", []):
            if not path_exists(resolve_file_path(p)):
                return ("extra", tab_name, p)
    return None


def collect_files(
    file_tabs,
    *,
    tab_keys: list[str],
    get_tab_file_layout,
    extract_frame_data_fn,
):
    files = {}
    for idx in range(file_tabs.count()):
        if idx >= len(tab_keys):
            break
        tab = file_tabs.widget(idx)
        layout = get_tab_file_layout(tab)
        if not tab or not layout:
            continue
        tab_files = {}
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget() if item else None
            if not w or not hasattr(w, "layout") or not (frame_layout := w.layout()):
                continue
            data = extract_frame_data_fn(frame_layout)
            if not data:
                continue
            if data["type"] == "data" and data.get("path"):
                tab_files["data_file_path"] = data["path"]
            elif data["type"] == "extra" and data.get("paths"):
                extra_files = tab_files.setdefault("extra_files", [])
                target = normalize_extra_file_target(
                    data.get("target", EXTRA_FILE_TARGET_GAME_FOLDER)
                )
                target_path = data.get("target_path", "").strip()
                existing_paths = {
                    (
                        extra_file.get("file_path"),
                        normalize_extra_file_target(
                            extra_file.get("target")
                            or extra_file.get("status")
                            or EXTRA_FILE_TARGET_GAME_FOLDER
                        ),
                        extra_file.get("target_path", "").strip(),
                    )
                    if isinstance(extra_file, dict)
                    else (extra_file, EXTRA_FILE_TARGET_GAME_FOLDER, "")
                    for extra_file in extra_files
                    if isinstance(extra_file, (str, dict))
                }
                for path in data["paths"]:
                    entry_key = (
                        path,
                        target,
                        target_path if target == EXTRA_FILE_TARGET_CUSTOM else "",
                    )
                    if entry_key not in existing_paths:
                        extra_files.append(
                            build_extra_file_entry(
                                path,
                                target,
                                target_path,
                            )
                        )
                        existing_paths.add(entry_key)
        if tab_files:
            files[tab_keys[idx]] = tab_files
    return files
