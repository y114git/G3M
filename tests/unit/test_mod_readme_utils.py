import os

from utils.mod_readme_utils import (
    find_mod_readme_files,
    is_markdown_file,
    read_mod_readme,
)


def test_find_mod_readme_files_prioritizes_readme_names(temp_dir):
    """Checks that finding mod readme files prioritizes readme names."""
    for name in ("notes.txt", "README.md", "guide.md", "README.txt"):
        with open(os.path.join(temp_dir, name), "w", encoding="utf-8") as handle:
            handle.write(name)

    found = [os.path.basename(path) for path in find_mod_readme_files(temp_dir)]

    assert found == ["guide.md", "notes.txt", "README.md", "README.txt"]


def test_find_mod_readme_files_only_uses_top_level_files(temp_dir):
    """Checks that finding mod readme files only uses top level files."""
    nested_dir = os.path.join(temp_dir, "chapter_1")
    os.makedirs(nested_dir, exist_ok=True)
    with open(os.path.join(temp_dir, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("top")
    with open(os.path.join(nested_dir, "nested.txt"), "w", encoding="utf-8") as handle:
        handle.write("nested")

    found = [os.path.basename(path) for path in find_mod_readme_files(temp_dir)]

    assert found == ["README.md"]


def test_read_mod_readme_supports_utf8_sig(temp_dir):
    """Checks that reading mod readme supports utf8 sig."""
    file_path = os.path.join(temp_dir, "README.txt")
    with open(file_path, "w", encoding="utf-8-sig") as handle:
        handle.write("Hello README")

    assert read_mod_readme(file_path) == "Hello README"
    assert is_markdown_file(file_path) is False
    assert is_markdown_file(os.path.join(temp_dir, "README.md")) is True
