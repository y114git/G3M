from typing import TYPE_CHECKING
from config.constants import STEAM_APP_ID_FULL, STEAM_APP_ID_DEMO, STEAM_APP_ID_UNDERTALE
if TYPE_CHECKING:
    from models.mod_models import ModInfo


def tr(key: str) -> str:
    from localization.manager import tr as _tr
    return _tr(key)


class GameMode:
    _path_key: str
    _custom_exec_key: str
    steam_id: str
    _tab_name_keys: list[str]
    _path_change_button_key: str
    direct_launch_allowed: bool

    @property
    def path_change_button_text(self) -> str:
        return tr(self._path_change_button_key)

    @property
    def tab_names(self) -> list[str]:
        return [tr(key) for key in self._tab_name_keys]

    def get_game_path(self, config: dict) -> str:
        return config.get(self._path_key, '')

    def set_game_path(self, config: dict, path: str):
        config[self._path_key] = path

    def get_custom_exec_config_key(self) -> str:
        return self._custom_exec_key

    def get_chapter_id(self, ui_index: int) -> int:
        raise NotImplementedError

    def filter_mods_for_ui(self, all_mods: list['ModInfo']) -> dict[int, list['ModInfo']]:
        raise NotImplementedError


class FullGameMode(GameMode):

    def __init__(self):
        self._path_key = 'game_path'
        self._custom_exec_key = 'custom_executable_path'
        self.steam_id = STEAM_APP_ID_FULL
        self._path_change_button_key = 'buttons.change_path'
        self._tab_name_keys = ['tabs.main_menu', 'tabs.chapter_1',
                               'tabs.chapter_2', 'tabs.chapter_3', 'tabs.chapter_4']
        self.direct_launch_allowed = True

    def get_chapter_id(self, ui_index: int) -> int:
        return ui_index

    def filter_mods_for_ui(self, all_mods: list['ModInfo']) -> dict[int, list['ModInfo']]:
        return {i: [mod for mod in all_mods if mod.modgame == 'deltarune' and (not mod.hide_mod) and (not mod.ban_status) and mod.get_chapter_data(i)] for i in range(5)}


class DemoGameMode(GameMode):

    def __init__(self):
        self._path_key = 'demo_game_path'
        self._custom_exec_key = 'demo_custom_executable_path'
        self.steam_id = STEAM_APP_ID_DEMO
        self._path_change_button_key = 'buttons.change_demo_path'
        self._tab_name_keys = ['tabs.demo']
        self.direct_launch_allowed = False

    def get_chapter_id(self, ui_index: int) -> int:
        return -1

    def filter_mods_for_ui(self, all_mods: list['ModInfo']) -> dict[int, list['ModInfo']]:
        return {0: [mod for mod in all_mods if mod.is_valid_for_demo() and (not mod.hide_mod) and (not mod.ban_status)]}


class UndertaleGameMode(GameMode):

    def __init__(self):
        self._path_key = 'undertale_game_path'
        self._custom_exec_key = 'undertale_custom_executable_path'
        self.steam_id = STEAM_APP_ID_UNDERTALE
        self._path_change_button_key = 'buttons.change_undertale_path'
        self._tab_name_keys = ['tabs.undertale']
        self.direct_launch_allowed = True

    def get_chapter_id(self, ui_index: int) -> int:
        return 0

    def filter_mods_for_ui(self, all_mods: list['ModInfo']) -> dict[int, list['ModInfo']]:
        return {0: [mod for mod in all_mods if mod.modgame == 'undertale' and (not mod.hide_mod) and (not mod.ban_status) and mod.files.get('undertale')]}
