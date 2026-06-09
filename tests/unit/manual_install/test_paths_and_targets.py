"""Unit tests for test paths and targets."""

from types import SimpleNamespace

from ui.dialogs.manual_install.paths import (
    default_extra_target_path,
    normalize_relative_target_path,
)
from ui.dialogs.manual_install.targets import (
    get_or_prompt_game_folder,
    read_configured_game_root,
    resolve_target_root_for_chapter,
)


def test_manual_install_default_extra_target_path_extracts_chapter_prefix():
    path_value, chapter_id = default_extra_target_path(
        file_path="C:/mods/file.txt",
        rel_path="chapter_1/lang/bonus/file.txt",
        chapter_alias_map={"chapter_1": "deltarune_1"},
    )

    assert path_value == "lang/bonus/"
    assert chapter_id == "deltarune_1"


def test_manual_install_normalize_relative_target_path_strips_alias_prefixes():
    assert (
        normalize_relative_target_path(
            "chapter1_windows/lang_es/file.txt",
            "deltarune_1",
            chapter_aliases={"chapter1_windows", "chapter_1"},
        )
        == "lang_es/file.txt"
    )


def test_resolve_target_root_for_chapter_uses_chapter_root_for_multi_tab():
    game_def = SimpleNamespace(
        is_multi_tab=True,
        macos_app_names=("DELTARUNE.app",),
    )
    calls = []

    resolved = resolve_target_root_for_chapter(
        "C:/games/deltarune",
        "deltarune_2",
        game_def,
        find_chapter_resource_dir_fn=lambda root, chapter, app_names: calls.append(
            (root, chapter, app_names)
        )
        or "C:/games/deltarune/chapter_2",
    )

    assert resolved == "C:/games/deltarune/chapter_2"
    assert calls == [("C:/games/deltarune", "deltarune_2", ("DELTARUNE.app",))]


def test_read_configured_game_root_returns_none_on_failed_lookup():
    game_def = SimpleNamespace(
        get_game_path=lambda _config: (_ for _ in ()).throw(ValueError("bad"))
    )

    assert read_configured_game_root(game_def, {"game_path": "x"}) is None


def test_get_or_prompt_game_folder_returns_existing_configured_path():
    game_def = SimpleNamespace(get_game_path=lambda config: config.get("game_path"))
    app_state = SimpleNamespace(
        local_config={"game_path": "C:/games/deltarune"},
        game_mode="previous",
    )
    settings_service = SimpleNamespace(prompt_for_game_path=lambda **_kwargs: True)

    resolved = get_or_prompt_game_folder(
        app_state=app_state,
        game_def=game_def,
        settings_service=settings_service,
        path_exists=lambda path: path == "C:/games/deltarune",
    )

    assert resolved == "C:/games/deltarune"
    assert app_state.game_mode == "previous"


def test_get_or_prompt_game_folder_prompts_and_restores_game_mode():
    calls = []

    def prompt_for_game_path(*, is_initial):
        calls.append(("prompt", is_initial))
        app_state.local_config["game_path"] = "C:/games/deltarune"
        return True

    game_def = SimpleNamespace(get_game_path=lambda config: config.get("game_path"))
    app_state = SimpleNamespace(local_config={"game_path": ""}, game_mode="previous")
    settings_service = SimpleNamespace(prompt_for_game_path=prompt_for_game_path)

    resolved = get_or_prompt_game_folder(
        app_state=app_state,
        game_def=game_def,
        settings_service=settings_service,
        path_exists=lambda path: path == "C:/games/deltarune",
    )

    assert resolved == "C:/games/deltarune"
    assert calls == [("prompt", False)]
    assert app_state.game_mode == "previous"
