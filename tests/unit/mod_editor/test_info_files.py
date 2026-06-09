"""Unit tests for test info files."""

from ui.dialogs.mod_editor.info_files import (
    collect_info_files,
    merge_info_file_entry,
    reset_info_file_entry,
)


def test_merge_info_file_entry_updates_existing_entry():
    entries = [
        {"path": "README.md", "state": "show", "custom": False, "source_path": "a"}
    ]

    merged = merge_info_file_entry(
        entries,
        file_path="README.md",
        visible=False,
        custom=True,
        source_path="b",
    )

    assert merged == [
        {"path": "README.md", "state": "hide", "custom": True, "source_path": "b"}
    ]


def test_reset_info_file_entry_restores_non_custom_sorted_entry():
    entries = [
        {"path": "B.txt", "state": "hide", "custom": True, "source_path": "b"},
        {"path": "Z.txt", "state": "show", "custom": False, "source_path": "z"},
    ]

    updated, index = reset_info_file_entry(entries, 0)

    assert updated[0] == {
        "path": "B.txt",
        "state": "show",
        "custom": False,
        "source_path": "b",
        "missing": False,
    }
    assert index == 0


def test_collect_info_files_includes_removed_entries():
    entries = [{"path": "A.txt", "state": "hide", "custom": True}]

    collected = collect_info_files(entries, {"B.txt"})

    assert collected == {"A.txt": "hide", "B.txt": "remove"}
