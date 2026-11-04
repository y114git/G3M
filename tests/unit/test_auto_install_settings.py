from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import dialogs
from services.mod.service import ModManager


def test_only_mods_that_appear_after_the_first_scan_are_announced(qapp):
    manager = ModManager(SimpleNamespace(mods_dir=""), Mock())
    announced = []
    manager.mods_added.connect(announced.append)

    manager._announce_new_mods({"a"})
    manager._announce_new_mods({"a", "c", "b"})
    manager._announce_new_mods({"a", "c", "b"})

    assert announced == [["b", "c"]]


def _window(use_after_install: bool):
    library = Mock()
    library._current_game_type.return_value = "deltarune"
    library.used_mods_service.is_mod_used_for_chapter.return_value = False
    mods = [{"id": "new", "game": "deltarune"}, {"id": "other", "game": "undertale"}]
    return SimpleNamespace(
        app_state=SimpleNamespace(local_config={"use_mod_after_install": use_after_install}, game_mode=Mock()),
        library_display=library,
        mod_service=Mock(get_installed_mods_list=Mock(return_value=mods)),
    )


def test_a_new_mod_for_the_current_game_is_used_when_the_setting_is_on(qapp):
    window = _window(True)
    with patch.object(dialogs, "get_chapter_id_for_game_mode", return_value="chapter"):
        dialogs._use_new_mods(window, ["new", "other", "gone"])

    window.library_display.on_mod_use.assert_called_once_with({"id": "new", "game": "deltarune"})


def test_nothing_is_used_when_the_setting_is_off(qapp):
    window = _window(False)
    with patch.object(dialogs.QTimer, "singleShot") as later:
        dialogs.on_mods_added(window, ["new"])

    later.assert_not_called()


def test_scanning_another_profile_folder_announces_nothing(qapp):
    state = SimpleNamespace(mods_dir="profile_a")
    manager = ModManager(state, Mock())
    announced = []
    manager.mods_added.connect(announced.append)

    manager._announce_new_mods({"a"})
    state.mods_dir = "profile_b"
    manager._announce_new_mods({"b", "c"})
    manager._announce_new_mods({"b", "c", "d"})

    assert announced == [["d"]]
