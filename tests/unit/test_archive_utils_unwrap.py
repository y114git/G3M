"""Unit tests for test archive utils unwrap."""

from utils.archive_utils import unwrap_single_directory_chain


def test_unwrap_single_directory_chain_descends_until_content_branches(tmp_path):
    """Checks that unwrapping single directory chain descends until content branches."""
    deepest = tmp_path / "outer" / "inner" / "payload"
    deepest.mkdir(parents=True)
    (deepest / "mod_config.json").write_text("{}", encoding="utf-8")
    (deepest / "data.win").write_text("patched", encoding="utf-8")

    resolved = unwrap_single_directory_chain(str(tmp_path))

    assert resolved == str(deepest)


def test_unwrap_single_directory_chain_stops_when_single_entry_is_not_directory(tmp_path):
    """Checks that unwrapping single directory chain stops when single entry is not directory."""
    marker = tmp_path / "archive.zip"
    marker.write_text("payload", encoding="utf-8")

    resolved = unwrap_single_directory_chain(str(tmp_path))

    assert resolved == str(tmp_path)
