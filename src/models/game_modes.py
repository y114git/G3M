"""Game definitions, tab configuration, and mod filtering logic.

Each supported game is defined as a GameDefinition subclass with its own
tab layout and mod filtering rules. Games are registered in GAME_REGISTRY
for lookup by game_id.
"""

from dataclasses import dataclass

from config.constants import (
    STEAM_APP_ID_DEMO,
    STEAM_APP_ID_FULL,
    STEAM_APP_ID_PIZZA_TOWER,
    STEAM_APP_ID_UNDERTALE,
)


def tr(key: str) -> str:
    from services.localization_service import tr as _tr

    return _tr(key)


@dataclass(frozen=True)
class GameTab:
    """A tab in the UI representing a section of game content."""

    tab_id: str
    files_key: str
    name_key: str
    folder_name: str = ""
    direct_launch: bool = True


class GameDefinition:
    """Universal game configuration.

    Subclass to add game-specific mod filtering or launch behaviour.
    Standard mod filtering: mod.game == game_id AND mod.files[tab.files_key] exists.
    """

    game_id: str = ""
    display_name: str = "DELTARUNE"
    steam_app_id: str = ""
    path_config_key: str = ""
    custom_exec_config_key: str = ""
    path_button_key: str = ""
    gamebanana_id: int = 0
    tabs: list[GameTab] = []
    executable_type: str = "deltarune"

    supports_full_install: bool = False
    block_steam_with_direct_launch: bool = False

    macos_app_names: tuple = ("DELTARUNE.app", "DELTARUNEdemo.app")
    path_select_dialog_key: str = "dialogs.select_deltarune_folder"
    path_not_found_dialog_key: str = "dialogs.deltarune_not_found"
    used_mods_config_key: str = ""
    default_tab_id: str = ""

    def __init__(self) -> None:
        pass

    @property
    def is_multi_tab(self) -> bool:
        return len(self.tabs) > 1

    @property
    def direct_launch_allowed(self) -> bool:
        return any(t.direct_launch for t in self.tabs)

    @property
    def path_change_button_text(self) -> str:
        return tr(self.path_button_key)

    @property
    def tab_names(self) -> list[str]:
        return [tr(t.name_key) for t in self.tabs]

    def get_game_path(self, config: dict) -> str:
        return config.get(self.path_config_key, "")

    def set_game_path(self, config: dict, path: str) -> None:
        config[self.path_config_key] = path

    def get_custom_exec_config_key(self) -> str:
        return self.custom_exec_config_key

    @property
    def default_tab(self) -> str:
        """Return the default tab ID (game_id if not explicitly set)."""
        return self.default_tab_id or self.game_id

    def get_tab(self, tab_id: str) -> GameTab | None:
        return next((t for t in self.tabs if t.tab_id == tab_id), None)

    def get_tab_display_name(self, tab_id: str) -> str:
        """Human-readable name like 'DELTARUNE Chapter 1' or 'Pizza Tower'."""
        tab = self.get_tab(tab_id)
        if not tab:
            return self.display_name
        if self.is_multi_tab:
            return f"{self.display_name} {tr(tab.name_key)}"
        return self.display_name

    def get_folder_name(self, tab_id: str) -> str:
        """Mod storage folder name for a given tab."""
        tab = self.get_tab(tab_id)
        if tab and tab.folder_name:
            return tab.folder_name
        if tab:
            return self.game_id
        return tab_id

    def get_tab_by_index(self, ui_index: int) -> GameTab | None:
        return self.tabs[ui_index] if 0 <= ui_index < len(self.tabs) else None

    def get_chapter_id(self, ui_index: int) -> str:
        """Return the tab_id for a given UI tab index."""
        tab = self.get_tab_by_index(ui_index)
        return tab.tab_id if tab else self.default_tab

    @staticmethod
    def _is_visible_mod(mod) -> bool:
        return not mod.hide_mod and not mod.ban_status

    def _filter_visible_mods(self, all_mods, predicate):
        return [m for m in all_mods if self._is_visible_mod(m) and predicate(m)]

    def filter_mods_for_tab(self, tab: GameTab, all_mods: list) -> list:
        """Standard filter: game matches and tab files exist."""
        return self._filter_visible_mods(
            all_mods, lambda m: m.game == self.game_id and m.files.get(tab.files_key)
        )

    def filter_mods_for_ui(self, all_mods: list) -> dict[str, list]:
        """Return {tab_index: [visible_mods]} for UI display."""
        return {
            i: self.filter_mods_for_tab(tab, all_mods)
            for i, tab in enumerate(self.tabs)
        }


class DeltaruneGame(GameDefinition):
    """DELTARUNE (full version) — 5 tabs: menu + 4 chapters."""

    game_id = "deltarune"
    steam_app_id = STEAM_APP_ID_FULL
    path_config_key = "game_path"
    custom_exec_config_key = "custom_executable_path"
    path_button_key = "buttons.change_path"
    gamebanana_id = 6755
    block_steam_with_direct_launch = True
    tabs = [
        GameTab(
            tab_id="deltarune_0",
            files_key="0",
            name_key="tabs.main_menu",
            folder_name="chapter_0",
        ),
        GameTab(
            tab_id="deltarune_1",
            files_key="1",
            name_key="tabs.chapter_1",
            folder_name="chapter_1",
        ),
        GameTab(
            tab_id="deltarune_2",
            files_key="2",
            name_key="tabs.chapter_2",
            folder_name="chapter_2",
        ),
        GameTab(
            tab_id="deltarune_3",
            files_key="3",
            name_key="tabs.chapter_3",
            folder_name="chapter_3",
        ),
        GameTab(
            tab_id="deltarune_4",
            files_key="4",
            name_key="tabs.chapter_4",
            folder_name="chapter_4",
        ),
    ]

    def filter_mods_for_tab(self, tab, all_mods):
        return self._filter_visible_mods(
            all_mods,
            lambda m, t=tab: m.game == "deltarune" and m.get_chapter_data(t.tab_id),
        )


class DeltaruneDemoGame(GameDefinition):
    """DELTARUNE Demo — single tab, special mod predicate."""

    game_id = "deltarunedemo"
    display_name = "DELTARUNEdemo"
    steam_app_id = STEAM_APP_ID_DEMO
    path_config_key = "demo_game_path"
    custom_exec_config_key = "demo_custom_executable_path"
    path_button_key = "buttons.change_demo_path"
    gamebanana_id = 6755
    supports_full_install = True
    tabs = [
        GameTab(
            tab_id="deltarunedemo",
            files_key="demo",
            name_key="tabs.demo",
            folder_name="demo",
            direct_launch=False,
        )
    ]
    path_select_dialog_key = "dialogs.select_demo_folder"
    path_not_found_dialog_key = "dialogs.demo_not_found"
    used_mods_config_key = "used_mods_deltarunedemo"

    def filter_mods_for_tab(self, tab, all_mods):
        return self._filter_visible_mods(all_mods, lambda m: m.is_valid_for_demo())


class UndertaleGame(GameDefinition):
    """UNDERTALE — single tab."""

    game_id = "undertale"
    display_name = "UNDERTALE"
    steam_app_id = STEAM_APP_ID_UNDERTALE
    path_config_key = "undertale_game_path"
    custom_exec_config_key = "undertale_custom_executable_path"
    path_button_key = "buttons.change_undertale_path"
    gamebanana_id = 5506
    executable_type = "undertale"
    tabs = [
        GameTab(
            tab_id="undertale",
            files_key="undertale",
            name_key="tabs.undertale",
            folder_name="chapter_0",
        )
    ]
    macos_app_names = ("UNDERTALE.app",)
    path_select_dialog_key = "dialogs.select_undertale_folder"
    path_not_found_dialog_key = "dialogs.undertale_not_found"
    used_mods_config_key = "used_mods_undertale"


class UndertaleYellowGame(GameDefinition):
    """Undertale Yellow — single tab, supports full install."""

    game_id = "undertaleyellow"
    display_name = "UNDERTALE Yellow"
    path_config_key = "undertaleyellow_game_path"
    custom_exec_config_key = "undertaleyellow_custom_executable_path"
    path_button_key = "buttons.change_undertaleyellow_path"
    gamebanana_id = 19606
    executable_type = "undertaleyellow"
    supports_full_install = True
    tabs = [
        GameTab(
            tab_id="undertaleyellow",
            files_key="undertale",
            name_key="tabs.undertaleyellow",
            folder_name="chapter_0",
        )
    ]
    macos_app_names = ("UNDERTALE.app",)
    path_select_dialog_key = "dialogs.select_undertaleyellow_folder"
    path_not_found_dialog_key = "dialogs.undertaleyellow_not_found"
    used_mods_config_key = "used_mods_undertaleyellow"


class PizzaTowerGame(GameDefinition):
    """Pizza Tower — single tab, accepts legacy '0' files key."""

    game_id = "pizzatower"
    display_name = "Pizza Tower"
    steam_app_id = STEAM_APP_ID_PIZZA_TOWER
    path_config_key = "pizzatower_game_path"
    custom_exec_config_key = "pizzatower_custom_executable_path"
    path_button_key = "buttons.change_pizzatower_path"
    gamebanana_id = 7692
    executable_type = "pizzatower"
    tabs = [
        GameTab(
            tab_id="pizzatower",
            files_key="pizzatower",
            name_key="tabs.pizzatower",
            folder_name="pizzatower",
        )
    ]
    macos_app_names = ("PizzaTower.app",)
    path_select_dialog_key = "dialogs.select_pizzatower_folder"
    path_not_found_dialog_key = "dialogs.pizzatower_not_found"
    used_mods_config_key = "used_mods_pizzatower"

    def filter_mods_for_tab(self, tab, all_mods):
        return self._filter_visible_mods(
            all_mods,
            lambda m: (
                m.game == "pizzatower"
                and (m.files.get("0") or m.files.get("pizzatower"))
            ),
        )


class SugarySpireGame(GameDefinition):
    """Sugary Spire — single tab, supports full install."""

    game_id = "sugaryspire"
    display_name = "Sugary Spire"
    path_config_key = "sugaryspire_game_path"
    custom_exec_config_key = "sugaryspire_custom_executable_path"
    path_button_key = "buttons.change_sugaryspire_path"
    gamebanana_id = 18218
    executable_type = "sugaryspire"
    supports_full_install = True
    tabs = [
        GameTab(
            tab_id="sugaryspire", files_key="undertale", name_key="tabs.sugaryspire"
        )
    ]
    macos_app_names = ("SugarySpire_ExhibitionNight.app",)
    used_mods_config_key = "used_mods_sugaryspire"


GAME_REGISTRY: dict[str, GameDefinition] = {}


def register_game(game: GameDefinition) -> None:
    """Register a game definition in the global registry."""
    GAME_REGISTRY[game.game_id] = game


def get_game(game_id: str) -> GameDefinition | None:
    """Look up a registered game by its game_id."""
    return GAME_REGISTRY.get(game_id)


def get_all_games() -> list[GameDefinition]:
    """Return all registered games."""
    return list(GAME_REGISTRY.values())


register_game(DeltaruneGame())
register_game(DeltaruneDemoGame())
register_game(UndertaleGame())
register_game(UndertaleYellowGame())
register_game(PizzaTowerGame())
register_game(SugarySpireGame())
