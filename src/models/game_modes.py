"""Game definitions and runtime registry state."""

from __future__ import annotations

from dataclasses import dataclass

from config.config import (
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


@dataclass(frozen=True)
class CustomGameRecord:
    """Persisted custom game definition."""

    id: str
    display_name: str
    primary_executable: str
    data_file_name: str
    steam_app_id: str | None = None
    gamebanana_id: int | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class GameEntry:
    """Runtime game entry used by UI lists and services."""

    id: str
    is_builtin: bool
    is_visible: bool
    sort_index: int
    game_definition: GameDefinition

    @property
    def display_name(self) -> str:
        return self.game_definition.display_label

    @property
    def steam_app_id(self) -> str:
        return self.game_definition.steam_app_id

    @property
    def gamebanana_id(self) -> int:
        return self.game_definition.gamebanana_id

    @property
    def supports_search(self) -> bool:
        return bool(self.gamebanana_id)

    @property
    def supports_chapter_mode(self) -> bool:
        return self.game_definition.is_multi_tab

    @property
    def supports_full_install(self) -> bool:
        return self.game_definition.supports_full_install

    @property
    def supports_direct_launch(self) -> bool:
        return self.game_definition.direct_launch_allowed

    @property
    def path_config_key(self) -> str:
        return self.game_definition.path_config_key

    @property
    def custom_exec_config_key(self) -> str:
        return self.game_definition.custom_exec_config_key

    @property
    def used_mods_config_key(self) -> str:
        return self.game_definition.used_mods_config_key


class GameDefinition:
    """Universal game configuration."""

    game_id: str = ""
    display_name: str = "DELTARUNE"
    display_name_key: str = ""
    steam_app_id: str = ""
    path_config_key: str = ""
    custom_exec_config_key: str = ""
    path_button_key: str = ""
    gamebanana_id: int = 0
    tabs: list[GameTab] = []
    executables: dict[str, tuple[str, ...]] = {}
    process_names: tuple[str, ...] = ()
    data_file_name: str = ""
    supports_full_install: bool = False
    block_steam_with_direct_launch: bool = False
    macos_app_names: tuple[str, ...] = ("DELTARUNE.app", "DELTARUNEdemo.app")
    path_select_dialog_key: str = "dialogs.select_deltarune_folder"
    path_not_found_dialog_key: str = "dialogs.deltarune_not_found"
    used_mods_config_key: str = ""
    default_tab_id: str = ""

    @property
    def is_multi_tab(self) -> bool:
        return len(self.tabs) > 1

    @property
    def direct_launch_allowed(self) -> bool:
        return any(t.direct_launch for t in self.tabs)

    @property
    def executable_type(self) -> str:
        return self.game_id

    @property
    def display_label(self) -> str:
        if not self.display_name_key:
            return self.display_name
        translated = tr(self.display_name_key)
        return (
            self.display_name
            if translated in ("", self.display_name_key, f"[{self.display_name_key}]")
            else translated
        )

    @property
    def path_change_button_text(self) -> str:
        return tr(self.path_button_key)

    @property
    def tab_names(self) -> list[str]:
        return [
            tr(t.name_key) if t.name_key else self.get_tab_display_name(t.tab_id)
            for t in self.tabs
        ]

    def get_game_path(self, config: dict) -> str:
        return config.get(self.path_config_key, "")

    def set_game_path(self, config: dict, path: str) -> None:
        config[self.path_config_key] = path

    def get_custom_exec_config_key(self) -> str:
        return self.custom_exec_config_key

    @property
    def default_tab(self) -> str:
        return self.default_tab_id or self.game_id

    def get_tab(self, tab_id: str) -> GameTab | None:
        return next(
            (t for t in self.tabs if t.tab_id == tab_id or t.files_key == tab_id),
            None,
        )

    def get_tab_display_name(self, tab_id: str) -> str:
        tab = self.get_tab(tab_id)
        if not tab:
            return self.display_label
        if not tab.name_key:
            return self.display_label
        if self.is_multi_tab:
            return f"{self.display_label} {tr(tab.name_key)}"
        return self.display_label

    def get_folder_name(self, tab_id: str) -> str:
        tab = self.get_tab(tab_id)
        if tab and tab.folder_name:
            return tab.folder_name
        if tab:
            return self.game_id
        return tab_id

    def get_tab_by_index(self, ui_index: int) -> GameTab | None:
        return self.tabs[ui_index] if 0 <= ui_index < len(self.tabs) else None

    def get_chapter_id(self, ui_index: int) -> str:
        tab = self.get_tab_by_index(ui_index)
        return tab.tab_id if tab else self.default_tab

    def get_executable_candidates(self, os_type: str) -> tuple[str, ...]:
        return self.executables.get(os_type, ())

    def get_process_names(self) -> tuple[str, ...]:
        return self.process_names

    @staticmethod
    def _is_visible_mod(mod) -> bool:
        return not mod.hide_mod and not mod.ban_status

    def _filter_visible_mods(self, all_mods, predicate):
        return [m for m in all_mods if self._is_visible_mod(m) and predicate(m)]

    def filter_mods_for_tab(self, tab: GameTab, all_mods: list) -> list:
        return self._filter_visible_mods(
            all_mods, lambda m: m.game == self.game_id and m.get_chapter_data(tab.tab_id)
        )

    def filter_mods_for_ui(self, all_mods: list) -> dict[str, list]:
        return {
            i: self.filter_mods_for_tab(tab, all_mods)
            for i, tab in enumerate(self.tabs)
        }


class DeltaruneGame(GameDefinition):
    game_id = "deltarune"
    display_name_key = "ui.deltarune"
    steam_app_id = STEAM_APP_ID_FULL
    path_config_key = "game_path"
    custom_exec_config_key = "custom_executable_path"
    path_button_key = "buttons.change_path"
    gamebanana_id = 6755
    block_steam_with_direct_launch = True
    tabs = [
        GameTab("deltarune_0", "0", "tabs.main_menu", "chapter_0"),
        GameTab("deltarune_1", "1", "tabs.chapter_1", "chapter_1"),
        GameTab("deltarune_2", "2", "tabs.chapter_2", "chapter_2"),
        GameTab("deltarune_3", "3", "tabs.chapter_3", "chapter_3"),
        GameTab("deltarune_4", "4", "tabs.chapter_4", "chapter_4"),
    ]
    executables = {
        "windows": ("DELTARUNE.exe", "DELTARUNE"),
        "linux": ("DELTARUNE", "DELTARUNE.exe"),
        "mac": ("DELTARUNE.app", "DELTARUNEdemo.app"),
    }
    process_names = ("DELTARUNE.exe", "DELTARUNE", "runner")

    def filter_mods_for_tab(self, tab, all_mods):
        return self._filter_visible_mods(
            all_mods,
            lambda m, t=tab: m.game == "deltarune" and m.get_chapter_data(t.tab_id),
        )


class DeltaruneDemoGame(GameDefinition):
    game_id = "deltarunedemo"
    display_name = "DELTARUNEdemo"
    display_name_key = "ui.deltarunedemo"
    steam_app_id = STEAM_APP_ID_DEMO
    path_config_key = "demo_game_path"
    custom_exec_config_key = "demo_custom_executable_path"
    path_button_key = "buttons.change_demo_path"
    gamebanana_id = 0
    supports_full_install = True
    tabs = [GameTab("deltarunedemo", "demo", "tabs.demo", "demo", False)]
    executables = {
        "windows": ("DELTARUNE.exe", "DELTARUNE"),
        "linux": ("DELTARUNE", "DELTARUNE.exe"),
        "mac": ("DELTARUNEdemo.app", "DELTARUNE.app"),
    }
    process_names = ("DELTARUNE.exe", "DELTARUNE", "runner")
    path_select_dialog_key = "dialogs.select_demo_folder"
    path_not_found_dialog_key = "dialogs.demo_not_found"
    used_mods_config_key = "used_mods_deltarunedemo"

    def filter_mods_for_tab(self, tab, all_mods):
        return self._filter_visible_mods(all_mods, lambda m: m.is_valid_for_demo())


class UndertaleGame(GameDefinition):
    game_id = "undertale"
    display_name = "UNDERTALE"
    display_name_key = "ui.undertale"
    steam_app_id = STEAM_APP_ID_UNDERTALE
    path_config_key = "undertale_game_path"
    custom_exec_config_key = "undertale_custom_executable_path"
    path_button_key = "buttons.change_undertale_path"
    gamebanana_id = 5506
    tabs = [GameTab("undertale", "undertale", "tabs.undertale", "undertale")]
    executables = {
        "windows": ("UNDERTALE.exe", "UNDERTALE"),
        "linux": ("UNDERTALE", "UNDERTALE.exe"),
        "mac": ("UNDERTALE.app",),
    }
    process_names = ("UNDERTALE.exe", "UNDERTALE", "runner")
    macos_app_names = ("UNDERTALE.app",)
    path_select_dialog_key = "dialogs.select_undertale_folder"
    path_not_found_dialog_key = "dialogs.undertale_not_found"
    used_mods_config_key = "used_mods_undertale"


class UndertaleYellowGame(GameDefinition):
    game_id = "undertaleyellow"
    display_name = "UNDERTALE Yellow"
    display_name_key = "ui.undertaleyellow"
    path_config_key = "undertaleyellow_game_path"
    custom_exec_config_key = "undertaleyellow_custom_executable_path"
    path_button_key = "buttons.change_undertaleyellow_path"
    gamebanana_id = 19606
    supports_full_install = True
    tabs = [
        GameTab("undertaleyellow", "undertale", "tabs.undertaleyellow", "undertale")
    ]
    executables = {
        "windows": (
            "Undertale Yellow.exe",
            "Undertale Yellow",
            "UNDERTALE.exe",
            "UNDERTALE",
        ),
        "linux": (
            "Undertale Yellow",
            "UNDERTALE",
            "Undertale Yellow.exe",
            "UNDERTALE.exe",
        ),
        "mac": ("UNDERTALE.app",),
    }
    process_names = (
        "Undertale Yellow.exe",
        "Undertale Yellow",
        "UNDERTALE.exe",
        "UNDERTALE",
        "runner",
    )
    macos_app_names = ("UNDERTALE.app",)
    path_select_dialog_key = "dialogs.select_undertaleyellow_folder"
    path_not_found_dialog_key = "dialogs.undertaleyellow_not_found"
    used_mods_config_key = "used_mods_undertaleyellow"


class PizzaTowerGame(GameDefinition):
    game_id = "pizzatower"
    display_name = "Pizza Tower"
    display_name_key = "ui.pizzatower"
    steam_app_id = STEAM_APP_ID_PIZZA_TOWER
    path_config_key = "pizzatower_game_path"
    custom_exec_config_key = "pizzatower_custom_executable_path"
    path_button_key = "buttons.change_pizzatower_path"
    gamebanana_id = 7692
    tabs = [GameTab("pizzatower", "pizzatower", "tabs.pizzatower", "pizzatower")]
    executables = {
        "windows": ("PizzaTower.exe", "PizzaTower"),
        "linux": ("PizzaTower", "PizzaTower.exe"),
        "mac": ("PizzaTower.app",),
    }
    process_names = ("PizzaTower.exe", "PizzaTower", "runner")
    macos_app_names = ("PizzaTower.app",)
    path_select_dialog_key = "dialogs.select_pizzatower_folder"
    path_not_found_dialog_key = "dialogs.pizzatower_not_found"
    used_mods_config_key = "used_mods_pizzatower"

    def filter_mods_for_tab(self, tab, all_mods):
        return self._filter_visible_mods(
            all_mods, lambda m, t=tab: m.game == "pizzatower" and m.get_chapter_data(t.tab_id)
        )


class SugarySpireGame(GameDefinition):
    game_id = "sugaryspire"
    display_name = "Sugary Spire"
    display_name_key = "ui.sugaryspire"
    path_config_key = "sugaryspire_game_path"
    custom_exec_config_key = "sugaryspire_custom_executable_path"
    path_button_key = "buttons.change_sugaryspire_path"
    gamebanana_id = 18218
    supports_full_install = True
    tabs = [GameTab("sugaryspire", "undertale", "tabs.sugaryspire", "sugaryspire")]
    executables = {
        "windows": ("SugarySpire_ExhibitionNight.exe", "SugarySpire_ExhibitionNight"),
        "linux": ("SugarySpire_ExhibitionNight", "SugarySpire_ExhibitionNight.exe"),
        "mac": ("SugarySpire_ExhibitionNight.app",),
    }
    process_names = (
        "SugarySpire_ExhibitionNight.exe",
        "SugarySpire_ExhibitionNight",
        "runner",
    )
    macos_app_names = ("SugarySpire_ExhibitionNight.app",)
    used_mods_config_key = "used_mods_sugaryspire"


class CustomSingleTabGame(GameDefinition):
    """Generated runtime game definition for a custom single-tab game."""

    display_name_key = ""
    supports_full_install = False
    path_button_key = "buttons.change_custom_game_path"
    path_select_dialog_key = "dialogs.select_custom_game_folder"
    path_not_found_dialog_key = "dialogs.custom_game_not_found"

    def __init__(self, record: CustomGameRecord) -> None:
        exe_name = record.primary_executable.strip()
        exe_stem = exe_name.rsplit(".", 1)[0] if "." in exe_name else exe_name
        self.game_id = record.id
        self.display_name = record.display_name
        self.primary_executable = exe_name
        self.data_file_name = record.data_file_name.strip()
        self.steam_app_id = record.steam_app_id or ""
        self.path_config_key = f"custom_game_path_{record.id}"
        self.custom_exec_config_key = f"custom_game_exec_{record.id}"
        self.gamebanana_id = int(record.gamebanana_id or 0)
        self.tabs = [GameTab(record.id, record.id, "", record.id, False)]
        self.executables = {
            "windows": (exe_name,),
            "linux": (exe_name,),
            "mac": (exe_name,),
        }
        self.process_names = tuple(n for n in dict.fromkeys((exe_name, exe_stem)) if n)
        self.macos_app_names = (exe_name,) if exe_name.lower().endswith(".app") else ()
        self.used_mods_config_key = f"used_mods_{record.id}"
        self.default_tab_id = record.id


BUILTIN_GAME_REGISTRY: dict[str, GameDefinition] = {
    game.game_id: game
    for game in (
        DeltaruneGame(),
        DeltaruneDemoGame(),
        UndertaleGame(),
        UndertaleYellowGame(),
        PizzaTowerGame(),
        SugarySpireGame(),
    )
}
DEFAULT_GAME_ORDER = tuple(BUILTIN_GAME_REGISTRY)
GAME_REGISTRY: dict[str, GameDefinition] = dict(BUILTIN_GAME_REGISTRY)
GAME_ENTRIES: dict[str, GameEntry] = {
    game_id: GameEntry(
        id=game_id,
        is_builtin=True,
        is_visible=True,
        sort_index=index,
        game_definition=game,
    )
    for index, (game_id, game) in enumerate(BUILTIN_GAME_REGISTRY.items())
}


def replace_game_entries(entries: list[GameEntry]) -> None:
    """Replace the runtime registry with the provided entries."""

    global GAME_REGISTRY, GAME_ENTRIES
    GAME_ENTRIES = {
        entry.id: entry for entry in sorted(entries, key=lambda e: e.sort_index)
    }
    GAME_REGISTRY = {entry.id: entry.game_definition for entry in GAME_ENTRIES.values()}


def get_game(game_id: str) -> GameDefinition | None:
    return GAME_REGISTRY.get(game_id)


def get_game_entry(game_id: str) -> GameEntry | None:
    return GAME_ENTRIES.get(game_id)


def get_all_games() -> list[GameDefinition]:
    return [
        entry.game_definition
        for entry in sorted(GAME_ENTRIES.values(), key=lambda e: e.sort_index)
    ]


def get_all_game_entries() -> list[GameEntry]:
    return sorted(GAME_ENTRIES.values(), key=lambda e: e.sort_index)


def get_visible_game_entries() -> list[GameEntry]:
    return [entry for entry in get_all_game_entries() if entry.is_visible]


def get_manager_game_entries() -> list[GameEntry]:
    return get_all_game_entries()


def get_search_game_entries() -> list[GameEntry]:
    builtins = [
        entry
        for entry in get_visible_game_entries()
        if entry.is_builtin and entry.supports_search
    ]
    customs = [
        entry
        for entry in get_visible_game_entries()
        if not entry.is_builtin and entry.supports_search
    ]
    return builtins + customs


def get_gamebanana_game_ids() -> dict[str, int]:
    return {
        entry.id: entry.gamebanana_id
        for entry in get_search_game_entries()
        if entry.gamebanana_id
    }


def get_gamebanana_reverse_map() -> dict[int, str]:
    return {
        gamebanana_id: game_id
        for game_id, gamebanana_id in get_gamebanana_game_ids().items()
    }


def get_first_visible_game_id(default: str = "deltarune") -> str:
    visible = get_visible_game_entries()
    return visible[0].id if visible else default


def get_all_process_names() -> tuple[str, ...]:
    return tuple(
        name
        for name in dict.fromkeys(
            proc for game in get_all_games() for proc in game.get_process_names()
        )
        if name
    )
