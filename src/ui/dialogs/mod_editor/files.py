"""File collection helpers for the mod editor dialog."""

import os

from PyQt6.QtWidgets import QLabel, QLineEdit


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
        for i in range(layout.count()):
            w = layout.itemAt(i).widget() if layout.itemAt(i) else None
            if isinstance(w, QLineEdit) and w.property("is_local_extra_path") and w.text():
                paths.append(format_config_path(w.text()))
        if paths:
            return {"type": "extra", "paths": paths}
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
                existing_paths = {
                    extra_file for extra_file in extra_files if isinstance(extra_file, str)
                }
                for path in data["paths"]:
                    if path not in existing_paths:
                        extra_files.append(path)
                        existing_paths.add(path)
        if tab_files:
            files[tab_keys[idx]] = tab_files
    return files
