"""Unit tests for test mod editor storage."""

from ui.dialogs.mod_editor.storage import (
    build_storage_path,
    collect_managed_file_paths,
    find_unconfigured_root_entries,
    resolve_managed_mod_path,
)


def test_resolve_managed_mod_path_rejects_absolute_paths(tmp_path):
    mod_dir = tmp_path / "mod"
    mod_dir.mkdir()

    assert resolve_managed_mod_path(str(mod_dir), "C:/outside/file.txt") is None


def test_collect_managed_file_paths_collects_data_and_extra_files(tmp_path):
    mod_dir = tmp_path / "mod"
    chapter_dir = mod_dir / "chapter_4"
    chapter_dir.mkdir(parents=True)
    data_file = chapter_dir / "data.win"
    extra_file = chapter_dir / "extra.zip"
    data_file.write_text("data", encoding="utf-8")
    extra_file.write_text("extra", encoding="utf-8")

    managed = collect_managed_file_paths(
        str(mod_dir),
        {
            "deltarune_4": {
                "data_file_path": "chapter_4/data.win",
                "extra_files": ["chapter_4/extra.zip"],
            }
        },
        "deltarune",
    )

    assert managed == {str(data_file), str(extra_file)}


def test_build_storage_path_places_external_chapter_files_under_chapter_folder(
    tmp_path,
):
    mod_dir = tmp_path / "mod"
    mod_dir.mkdir()
    external_dir = tmp_path / "external"
    external_dir.mkdir()
    patch_file = external_dir / "data.g3mpatch"
    patch_file.write_text("patch", encoding="utf-8")

    built = build_storage_path(
        mod_dir=str(mod_dir),
        file_key="deltarune_3",
        original_path=str(patch_file),
        resolved=str(patch_file),
        game="deltarune",
        format_config_path=lambda path, **_kwargs: path.replace("\\", "/"),
    )

    assert built == "chapter_3/data.g3mpatch"


def test_unconfigured_folder_is_one_dependency_without_hiding_active_child(tmp_path):
    mod_dir = tmp_path / "mod"
    resources = mod_dir / "resources"
    resources.mkdir(parents=True)
    active_child = resources / "active.txt"
    active_child.write_text("active", encoding="utf-8")
    (resources / "helper.txt").write_text("dependency", encoding="utf-8")
    standalone = mod_dir / "main.csx"
    standalone.write_text("script", encoding="utf-8")

    entries = find_unconfigured_root_entries(str(mod_dir), {str(active_child)})

    assert set(entries) == {str(resources), str(standalone)}
