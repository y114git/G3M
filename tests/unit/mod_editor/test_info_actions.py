"""Unit tests for test info actions."""

from ui.dialogs.mod_editor.info_actions import (
    delete_selected_info_file_entry,
    move_selected_info_file,
    reset_selected_info_file,
    toggle_selected_info_file,
)


def test_toggle_selected_info_file_marks_entry_custom():
    entries = [{"path": "README.md", "state": "show", "custom": False}]

    updated, index = toggle_selected_info_file(entries, 0)

    assert index == 0
    assert updated == [{"path": "README.md", "state": "hide", "custom": True}]


def test_move_selected_info_file_reorders_and_marks_custom():
    entries = [
        {"path": "A.txt", "state": "show", "custom": False},
        {"path": "B.txt", "state": "show", "custom": False},
    ]

    updated, index = move_selected_info_file(entries, 0, 1)

    assert index == 1
    assert updated == [
        {"path": "B.txt", "state": "show", "custom": False},
        {"path": "A.txt", "state": "show", "custom": True},
    ]


def test_reset_selected_info_file_rechecks_missing_source():
    entries = [
        {
            "path": "Guide.md",
            "state": "hide",
            "custom": True,
            "source_path": "Guide.md",
            "missing": True,
        }
    ]

    updated, index = reset_selected_info_file(entries, 0, is_file=lambda path: path == "Guide.md")

    assert index == 0
    assert updated[0]["missing"] is False
    assert updated[0]["state"] == "show"
    assert updated[0]["custom"] is False


def test_delete_selected_info_file_entry_marks_removed_when_file_kept():
    removed = set()
    entries = [{"path": "Guide.md", "state": "show", "custom": False}]

    updated, next_index = delete_selected_info_file_entry(
        entries,
        0,
        can_delete_file=True,
        action="entry",
        removed_info_files=removed,
    )

    assert updated == []
    assert next_index is None
    assert removed == {"Guide.md"}
