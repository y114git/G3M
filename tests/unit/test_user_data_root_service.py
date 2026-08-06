import json
import os
from pathlib import Path

import pytest

from services.user_data_root_service import (
    DataRootValidationError,
    prepare_data_root_change,
    validate_data_root_change,
)


def _require_symlink_support(tmp_path: Path) -> None:
    target = tmp_path / "symlink-probe-target"
    link = tmp_path / "symlink-probe-link"
    target.mkdir()
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Creating symlinks is unavailable: {error}")
    else:
        link.unlink()
        target.rmdir()


def test_validation_returns_destination_without_appending_g3m(tmp_path):
    source = tmp_path / "current"
    destination = tmp_path / "chosen-name"
    source.mkdir()

    assert validate_data_root_change(str(source), str(destination)) == os.path.normpath(
        os.path.abspath(destination)
    )


@pytest.mark.parametrize("relative", [".", "child", "child/deeper"])
def test_validation_rejects_same_or_nested_destination(tmp_path, relative):
    source = tmp_path / "current"
    source.mkdir()
    destination = source / relative

    with pytest.raises(DataRootValidationError) as error:
        validate_data_root_change(str(source), str(destination))

    expected_key = "already_active" if relative == "." else "directories_overlap"
    assert error.value.error_key == expected_key


def test_validation_rejects_destination_containing_source(tmp_path):
    destination = tmp_path / "parent"
    source = destination / "current"
    source.mkdir(parents=True)

    with pytest.raises(DataRootValidationError):
        validate_data_root_change(str(source), str(destination))


def test_clean_switch_creates_selected_directory_without_copying(tmp_path):
    source = tmp_path / "current"
    destination = tmp_path / "empty-root"
    source.mkdir()
    (source / "profiles").mkdir()

    result = prepare_data_root_change(str(source), str(destination), copy_data=False)

    assert result.status == "ready"
    assert result.selected_path == str(destination)
    assert destination.is_dir()
    assert not (destination / "profiles").exists()


def test_copy_preserves_tree_and_excludes_bootstrap_locator(tmp_path):
    source = tmp_path / "current"
    destination = tmp_path / "new-root"
    (source / "profiles" / "Default").mkdir(parents=True)
    (source / "profiles" / "Default" / "mod.json").write_text("{}", encoding="utf-8")
    (source / "data-root.json").write_text('{"path": "old"}', encoding="utf-8")

    result = prepare_data_root_change(str(source), str(destination), copy_data=True)

    assert result.status == "ready"
    assert (destination / "profiles" / "Default" / "mod.json").read_text(
        encoding="utf-8"
    ) == "{}"
    assert not (destination / "data-root.json").exists()
    assert (source / "profiles" / "Default" / "mod.json").exists()


def test_committed_migration_succeeds_when_old_backup_cleanup_fails(
    tmp_path, monkeypatch
):
    source = tmp_path / "current"
    destination = tmp_path / "new-root"
    source.mkdir()
    destination.mkdir()
    (source / "settings.json").write_text("new", encoding="utf-8")
    original_rmtree = __import__("shutil").rmtree

    def fail_old_backup(path, *args, **kwargs):
        if ".g3m-data-old-" in str(path):
            raise OSError("locked")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(
        "services.user_data_root_service.shutil.rmtree", fail_old_backup
    )

    result = prepare_data_root_change(str(source), str(destination), copy_data=True)

    assert result.status == "ready"
    assert (destination / "settings.json").read_text(encoding="utf-8") == "new"


def test_copy_rejects_existing_managed_entry_without_overwriting(tmp_path):
    source = tmp_path / "current"
    destination = tmp_path / "existing"
    (source / "profiles").mkdir(parents=True)
    (destination / "profiles").mkdir(parents=True)
    marker = destination / "profiles" / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    result = prepare_data_root_change(str(source), str(destination), copy_data=True)

    assert result.status == "conflict"
    assert result.error_key == "destination_conflict"
    assert result.error_args == {"entries": "profiles"}
    assert marker.read_text(encoding="utf-8") == "keep"


def test_cancelled_copy_does_not_copy_or_delete_source(tmp_path):
    source = tmp_path / "current"
    destination = tmp_path / "new-root"
    source.mkdir()
    marker = source / "settings.json"
    marker.write_text("keep", encoding="utf-8")

    result = prepare_data_root_change(
        str(source), str(destination), copy_data=True, cancelled=lambda: True
    )

    assert result.status == "cancelled"
    assert marker.exists()
    assert not (destination / "settings.json").exists()


def test_cancelled_partial_copy_leaves_existing_destination_unchanged(tmp_path):
    source = tmp_path / "current"
    destination = tmp_path / "new-root"
    source.mkdir()
    destination.mkdir()
    (source / "one.txt").write_text("one", encoding="utf-8")
    (source / "two.txt").write_text("two", encoding="utf-8")
    marker = destination / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    checks = iter((False, False, True))

    result = prepare_data_root_change(
        str(source),
        str(destination),
        copy_data=True,
        cancelled=lambda: next(checks, True),
    )

    assert result.status == "cancelled"
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (destination / "one.txt").exists()
    assert not (destination / "two.txt").exists()


def test_validation_resolves_symlink_aliases_before_overlap_check(tmp_path):
    _require_symlink_support(tmp_path)
    source = tmp_path / "current"
    source.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)

    with pytest.raises(DataRootValidationError) as error:
        validate_data_root_change(str(source), str(alias / "child"))

    assert error.value.error_key == "directories_overlap"


def test_file_destination_returns_validation_error(tmp_path):
    source = tmp_path / "current"
    destination = tmp_path / "file"
    source.mkdir()
    destination.write_text("x", encoding="utf-8")

    result = prepare_data_root_change(str(source), str(destination), copy_data=False)

    assert result.status == "invalid"
    assert result.error


def test_every_bundled_language_translates_data_root_errors():
    lang_dir = Path(__file__).parents[2] / "src" / "assets" / "lang"
    required = {
        "select_directory",
        "already_active",
        "directories_overlap",
        "not_directory",
        "destination_conflict",
        "io_error",
    }

    for path in lang_dir.glob("lang_*.json"):
        content = json.loads(path.read_text(encoding="utf-8"))
        assert required <= content["data_root"]["errors"].keys(), path.name


def test_copy_preserves_symlink_without_following_it(tmp_path):
    _require_symlink_support(tmp_path)
    source = tmp_path / "current"
    destination = tmp_path / "new-root"
    source.mkdir()
    target = source / "target.txt"
    target.write_text("target", encoding="utf-8")
    (source / "link.txt").symlink_to(Path("target.txt"))

    result = prepare_data_root_change(str(source), str(destination), copy_data=True)

    assert result.status == "ready"
    assert (destination / "link.txt").is_symlink()
    assert os.readlink(destination / "link.txt") == "target.txt"
