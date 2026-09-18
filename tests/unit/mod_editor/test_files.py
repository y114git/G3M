"""Unit tests for test files."""

from PyQt6.QtWidgets import QCheckBox, QLabel, QLineEdit, QVBoxLayout, QWidget

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

    extracted = extract_frame_data(
        frame.layout(), format_config_path=lambda path: path.replace("\\", "/")
    )

    assert extracted == {
        "type": "extra",
        "paths": ["C:/mods/a.txt", "nested/path/"],
        "target": "game_folder",
        "target_path": "",
    }


def test_extract_frame_data_marks_none_target_extra_file(qapp):
    frame = _build_frame("extra", ("main.csx", True))
    checkbox = QCheckBox()
    checkbox.setProperty("is_none_target_file", True)
    checkbox.setChecked(True)
    frame.layout().addWidget(checkbox)

    extracted = extract_frame_data(frame.layout(), format_config_path=lambda path: path)

    assert extracted == {
        "type": "extra",
        "paths": ["main.csx"],
        "target": "none",
        "target_path": "",
    }


def test_extract_frame_data_marks_data_folder_extra_file(qapp):
    frame = _build_frame("extra", ("addons/", True))
    checkbox = QCheckBox()
    checkbox.setProperty("is_data_folder_file", True)
    checkbox.setChecked(True)
    frame.layout().addWidget(checkbox)

    extracted = extract_frame_data(frame.layout(), format_config_path=lambda path: path)

    assert extracted == {
        "type": "extra",
        "paths": ["addons/"],
        "target": "game_data_folder",
        "target_path": "",
    }


def test_extract_frame_data_preserves_custom_target_path(qapp):
    frame = _build_frame("extra", ("main.csx", True))
    checkbox = QCheckBox()
    checkbox.setProperty("is_custom_target_file", True)
    checkbox.setChecked(True)
    frame.layout().addWidget(checkbox)
    target_path = QLineEdit("C:/Tools")
    target_path.setProperty("is_custom_target_path", True)
    frame.layout().addWidget(target_path)

    extracted = extract_frame_data(frame.layout(), format_config_path=lambda path: path)

    assert extracted == {
        "type": "extra",
        "paths": ["main.csx"],
        "target": "custom",
        "target_path": "C:/Tools",
    }


def test_fill_extra_sets_target_checkboxes(qapp):
    from ui.dialogs.mod_editor.dialog import ModEditorDialog

    dialog = type(
        "Dialog",
        (),
        {"_set_extra_target_controls": ModEditorDialog._set_extra_target_controls},
    )()
    for target in ("game_folder", "game_data_folder", "none"):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        frame = _build_frame("extra", ("", True))
        dependency_check = QCheckBox()
        dependency_check.setProperty("is_none_target_file", True)
        data_check = QCheckBox()
        data_check.setProperty("is_data_folder_file", True)
        custom_check = QCheckBox()
        custom_check.setProperty("is_custom_target_file", True)
        frame.layout().addWidget(dependency_check)
        frame.layout().addWidget(data_check)
        frame.layout().addWidget(custom_check)
        tab_layout.addWidget(frame)

        ModEditorDialog._fill_extra_in_tab(dialog, tab_layout, "extras/", target)

        assert dependency_check.isChecked() is (target == "none")
        assert data_check.isChecked() is (target == "game_data_folder")
        assert custom_check.isChecked() is False


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
            "extra_files": [{"file_path": "bonus.zip", "target": "game_folder"}],
        }
    }


def test_collect_files_deduplicates_structured_extra_paths(qapp):
    frames = []
    for _index in range(2):
        dependency_frame = _build_frame("extra", ("main.csx", True))
        checkbox = QCheckBox()
        checkbox.setProperty("is_none_target_file", True)
        checkbox.setChecked(True)
        dependency_frame.layout().addWidget(checkbox)
        frames.append(dependency_frame)
    tabs = _Tabs([_tab("Chapter 1", *frames)])

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
            "extra_files": [{"file_path": "main.csx", "target": "none"}]
        }
    }


def test_collect_files_keeps_same_path_with_different_targets(qapp):
    game_frame = _build_frame("extra", ("settings.json", True))
    data_frame = _build_frame("extra", ("settings.json", True))
    data_check = QCheckBox()
    data_check.setProperty("is_data_folder_file", True)
    data_check.setChecked(True)
    data_frame.layout().addWidget(data_check)
    tabs = _Tabs([_tab("Chapter 1", game_frame, data_frame)])

    collected = collect_files(
        tabs,
        tab_keys=["deltarune_1"],
        get_tab_file_layout=lambda tab: tab._file_layout,
        extract_frame_data_fn=lambda layout: extract_frame_data(
            layout, format_config_path=lambda path: path
        ),
    )

    assert collected["deltarune_1"]["extra_files"] == [
        {"file_path": "settings.json", "target": "game_folder"},
        {"file_path": "settings.json", "target": "game_data_folder"},
    ]


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
