"""Game mode definitions and mod filtering logic."""
from config.constants import STEAM_APP_ID_FULL, STEAM_APP_ID_DEMO, STEAM_APP_ID_UNDERTALE, STEAM_APP_ID_PIZZA_TOWER


def tr(key: str) -> str:
    from services.localization_service import tr as _tr
    return _tr(key)


class GameMode:
    """Base class for game mode definitions."""

    def __init__(self, path_key, custom_exec_key, steam_id, btn_key, tab_keys, direct_launch=True):
        self._path_key, self._custom_exec_key, self.steam_id = path_key, custom_exec_key, steam_id
        self._path_change_button_key, self._tab_name_keys, self.direct_launch_allowed = btn_key, tab_keys, direct_launch

    @property
    def path_change_button_text(self): return tr(self._path_change_button_key)
    @property
    def tab_names(self): return [tr(k) for k in self._tab_name_keys]
    def get_game_path(self, config): return config.get(self._path_key, '')
    def set_game_path(self, config, path): config[self._path_key] = path
    def get_custom_exec_config_key(self): return self._custom_exec_key
    def _is_visible_mod(self, mod): return not mod.hide_mod and not mod.ban_status
    def _filter_visible_mods(self, all_mods, predicate): return [m for m in all_mods if self._is_visible_mod(m) and predicate(m)]
    def get_chapter_id(self, ui_index): raise NotImplementedError
    def filter_mods_for_ui(self, all_mods): raise NotImplementedError


class FullGameMode(GameMode):
    def __init__(self):
        super().__init__('game_path', 'custom_executable_path', STEAM_APP_ID_FULL, 'buttons.change_path', ['tabs.main_menu', 'tabs.chapter_1', 'tabs.chapter_2', 'tabs.chapter_3', 'tabs.chapter_4'])

    def get_chapter_id(self, ui_index): return ui_index
    def filter_mods_for_ui(self, all_mods): return {i: self._filter_visible_mods(all_mods, lambda mod, i=i: mod.game == 'deltarune' and mod.get_chapter_data(i)) for i in range(5)}


class _SingleTabGameMode(GameMode):
    """Base for single-tab game modes."""
    _chapter_id = 0
    _game_key = ''
    _files_key = 'undertale'

    def get_chapter_id(self, ui_index): return self._chapter_id
    def filter_mods_for_ui(self, all_mods): return {0: self._filter_visible_mods(all_mods, self._mod_predicate)}
    def _mod_predicate(self, mod): return mod.game == self._game_key and mod.files.get(self._files_key)


class DemoGameMode(_SingleTabGameMode):
    _chapter_id = -1

    def __init__(self):
        super().__init__('demo_game_path', 'demo_custom_executable_path', STEAM_APP_ID_DEMO, 'buttons.change_demo_path', ['tabs.demo'], direct_launch=False)

    def _mod_predicate(self, mod): return mod.is_valid_for_demo()


class UndertaleGameMode(_SingleTabGameMode):
    _game_key, _files_key = 'undertale', 'undertale'

    def __init__(self):
        super().__init__('undertale_game_path', 'undertale_custom_executable_path', STEAM_APP_ID_UNDERTALE, 'buttons.change_undertale_path', ['tabs.undertale'])


class UndertaleYellowGameMode(_SingleTabGameMode):
    _game_key, _files_key = 'undertaleyellow', 'undertale'

    def __init__(self):
        super().__init__('undertaleyellow_game_path', 'undertaleyellow_custom_executable_path', '', 'buttons.change_undertaleyellow_path', ['tabs.undertaleyellow'])


class PizzaTowerGameMode(_SingleTabGameMode):
    _game_key = 'pizzatower'

    def __init__(self):
        super().__init__('pizzatower_game_path', 'pizzatower_custom_executable_path', STEAM_APP_ID_PIZZA_TOWER, 'buttons.change_pizzatower_path', ['tabs.pizzatower'])

    def _mod_predicate(self, mod): return mod.game == 'pizzatower' and (mod.files.get('0') or mod.files.get('pizzatower'))


class SugarySpireGameMode(_SingleTabGameMode):
    _game_key, _files_key = 'sugaryspire', 'undertale'

    def __init__(self):
        super().__init__('sugaryspire_game_path', 'sugaryspire_custom_executable_path', '', 'buttons.change_sugaryspire_path', ['tabs.sugaryspire'])
