"""Unit tests for test files."""

from PyQt6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from ui.dialogs.mod_editor.files import (
    collect_files,
    extract_frame_data,
    validate_local_files,
)


def _build_frame(file_type: str, *values: tuple[str, bool]):
    frame = QWidget()
    layout = QVBoxLayout(frame)
    title = QLabel(file_type)
    title.setProperty("file_type", file_type)
    layout.addWidget(title)
    for text, is_extra in values:
        edit = QLineEdit()
        edit.setText(text)
        edit.setProperty("is_local_extra_path" if is_extra else "is_local_path", True)
        layout.addWidget(edit)
    return frame


class _Tabs:
    def __init__(self, tabs) -> None:
        self._tabs = tabs

    def count(self):
        return len(self._tabs)

    def widget(self, index):
        return self._tabs[index]

    def tabText(self, index):  # noqa: N802
        return self._tabs[index].objectName()


def _tab(name: str, *frames: QWidget):
    tab = QWidget()
    tab.setObjectName(name)
    layout = QVBoxLayout(tab)
    for frame in frames:
        layout.addWidget(frame)
    tab._file_layout = layout
    return tab


def test_extract_frame_data_reads_extra_paths_with_formatting(qapp):
    frame = _build_frame("extra", ("C:\\mods\\a.txt", True), ("nested/path/", True))

    extracted = extract_frame_data(frame.layout(), format_config_path=lambda path: path.replace("\\", "/"))

    assert extracted == {"type": "extra", "paths": ["C:/mods/a.txt", "nested/path/"]}


def test_collect_files_deduplicates_extra_paths(qapp):
    tabs = _Tabs(
        [
            _tab(
                "Chapter 1",
                _build_frame("data", ("data.win", False)),
                _build_frame("extra", ("bonus.zip", True), ("bonus.zip", True)),
            )
        ]
    )

    collected = collect_files(
        tabs,
        tab_keys=["deltarune_1"],
        get_tab_file_layout=lambda tab: tab._file_layout,
        extract_frame_data_fn=lambda layout: extract_frame_data(
            layout, format_config_path=lambda path: path
        ),
    )

    assert collected == {
        "deltarune_1": {
            "data_file_path": "data.win",
            "extra_files": ["bonus.zip"],
        }
    }


def test_validate_local_files_reports_first_missing_path(qapp):
    tabs = _Tabs([_tab("Chapter 2", _build_frame("data", ("missing.win", False)))])

    missing = validate_local_files(
        tabs,
        get_tab_file_layout=lambda tab: tab._file_layout,
        extract_frame_data_fn=lambda layout: extract_frame_data(
            layout, format_config_path=lambda path: path
        ),
        resolve_file_path=lambda path: path,
        path_exists=lambda path: False,
    )

    assert missing == ("data", "Chapter 2", "missing.win")
