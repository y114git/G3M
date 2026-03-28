"""Data models for local mod configs and browser-only mod metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.migration_service import LEGACY_DESCRIPTION_KEY, LEGACY_ICON_KEY


@dataclass
class ModExtraFile:
    """Represents an extra file associated with a mod."""

    key: str
    url: str


@dataclass
class ModFileData:
    """File data for a game content section (chapter, whole game, etc.)."""

    description: str | None = None
    data_file_url: str | None = None
    extra_files: list[ModExtraFile] = field(default_factory=list)

    def is_valid(self) -> bool:
        return bool(self.data_file_url or self.extra_files)


def _parse_files_dict(data_dict: dict[str, Any]) -> dict[str, ModFileData]:
    files_dict: dict[str, ModFileData] = {}
    raw_files = data_dict.get("files")
    if not isinstance(raw_files, dict):
        return files_dict
    for key, value in raw_files.items():
        if isinstance(value, dict):
            extra_files = value.get("extra_files", [])
            if extra_files and isinstance(extra_files, list):
                value = value.copy()
                value.pop("data_file_version", None)
                value["extra_files"] = [
                    ModExtraFile(key=ef.get("key", ""), url=ef.get("url", ""))
                    if isinstance(ef, dict)
                    else ef
                    for ef in extra_files
                ]
            files_dict[key] = ModFileData(
                description=value.get("description"),
                data_file_url=value.get("data_file_url"),
                extra_files=value.get("extra_files", []),
            )
        elif isinstance(value, ModFileData):
            files_dict[key] = value
    return files_dict


@dataclass
class BaseModInfo:
    """Shared mod data used by both installed mods and browser results."""

    id: str
    name: str
    version: str
    author: str
    description: str
    game: str
    game_version: str = ""
    icon: str | None = None
    tags: list[str] = field(default_factory=list)
    homepage: str | None = None
    files: dict[str, ModFileData] = field(default_factory=dict)

    def get_file_data(self, chapter_id: str) -> ModFileData | None:
        """Get file data by the normalized content section id."""
        return self.files.get(chapter_id)

    def get_chapter_data(self, chapter_id: str) -> ModFileData | None:
        """Get file data by tab_id. Uses game registry for correct key lookup."""
        from models.game_modes import get_game
        from utils.file_utils import normalize_chapter_id

        game_def = get_game(self.game)
        if game_def:
            tab = game_def.get_tab(chapter_id)
            if tab:
                result = self.files.get(tab.tab_id) or self.files.get(tab.files_key)
                if result:
                    return result
        normalized_id = normalize_chapter_id(chapter_id, self.game)
        result = self.files.get(normalized_id) or self.files.get(chapter_id)
        if not result and game_def and len(game_def.tabs) == 1:
            result = self.files.get("0")
        return result

    def is_gamebanana_mod(self) -> bool:
        return bool(
            self.id
            and isinstance(self.id, str)
            and (self.id.startswith("gb_mod_") or self.id.startswith("gb_wip_"))
        )

    def get_gamebanana_mod_id(self) -> str | None:
        from utils.mod_utils import parse_gamebanana_mod_id

        _, mod_id = parse_gamebanana_mod_id(self.id)
        return mod_id


@dataclass
class LocalModInfo(BaseModInfo):
    """Installed/local mod representation built from local config plus local metadata."""

    playtime_hours: float = 0.0
    added_date: str | None = None
    last_updated: str | None = None

    def is_valid_for_demo(self) -> bool:
        return self.game == "deltarunedemo" and bool(
            self.files and (self.files.get("deltarunedemo") or self.files.get("demo"))
        )

    @classmethod
    def from_dict(cls, data_dict: dict[str, Any]) -> LocalModInfo:
        from services.localization_service import tr

        game = data_dict.get("game", "deltarune")
        return cls(
            id=data_dict.get("id", ""),
            name=data_dict.get("name", "Unknown Mod"),
            version=data_dict.get("version", "1.0.0"),
            author=data_dict.get("author", tr("defaults.unknown")),
            description=data_dict.get(
                "description",
                data_dict.get(LEGACY_DESCRIPTION_KEY, tr("status.no_description_status")),
            ),
            game=game,
            game_version=data_dict.get("game_version", tr("defaults.not_specified")),
            icon=data_dict.get("icon", data_dict.get(LEGACY_ICON_KEY)),
            tags=data_dict.get("tags", []),
            homepage=data_dict.get("homepage"),
            files=_parse_files_dict(data_dict),
            playtime_hours=data_dict.get("playtime_hours", 0.0),
            added_date=data_dict.get("added_date"),
            last_updated=data_dict.get("last_updated"),
        )


@dataclass
class BrowserModInfo(BaseModInfo):
    """Mods Browser representation with remote catalog metadata."""

    description_url: str = ""
    downloads: int | None = None
    like_count: int | None = None
    hide_mod: bool = False
    ban_status: bool = False
    is_nsfw: bool = False
    has_files: bool = True
    is_wip: bool = False
    demo_url: str | None = None
    demo_version: str | None = None
    created_date: str | None = None
    last_updated: str | None = None
    screenshots_url: list[str] = field(default_factory=list)
    full_description: str | None = None
    gamebanana_category: str | None = None
    gamebanana_supported_files: list[dict[str, Any]] = field(default_factory=list)
    gamebanana_compatibility_checked: bool = False
    has_full_metadata: bool = False

    def is_valid_for_demo(self) -> bool:
        return self.game == "deltarunedemo" and bool(
            (self.files and (self.files.get("deltarunedemo") or self.files.get("demo")))
            or (self.demo_url and self.demo_version)
        )

    @classmethod
    def from_dict(cls, data_dict: dict[str, Any]) -> BrowserModInfo:
        from services.localization_service import tr

        game = data_dict.get("game", "deltarune")
        return cls(
            id=data_dict.get("id", ""),
            name=data_dict.get("name", "Unknown Mod"),
            version=data_dict.get("version", "1.0.0"),
            author=data_dict.get("author", tr("defaults.unknown")),
            description=data_dict.get(
                "description",
                data_dict.get(LEGACY_DESCRIPTION_KEY, tr("status.no_description_status")),
            ),
            game=game,
            game_version=data_dict.get("game_version", tr("defaults.not_specified")),
            icon=data_dict.get("icon", data_dict.get(LEGACY_ICON_KEY)),
            tags=data_dict.get("tags", []),
            homepage=data_dict.get("homepage"),
            files=_parse_files_dict(data_dict),
            description_url=data_dict.get("description_url", ""),
            downloads=data_dict.get("downloads"),
            like_count=data_dict.get("like_count"),
            hide_mod=data_dict.get("hide_mod", False),
            ban_status=data_dict.get("ban_status", False),
            is_nsfw=data_dict.get("is_nsfw", False),
            has_files=data_dict.get("has_files", True),
            is_wip=data_dict.get("is_wip", False),
            demo_url=data_dict.get("demo_url"),
            demo_version=data_dict.get("demo_version"),
            created_date=data_dict.get("created_date"),
            last_updated=data_dict.get("last_updated"),
            screenshots_url=data_dict.get("screenshots_url", []),
            full_description=data_dict.get("full_description"),
            gamebanana_category=data_dict.get("gamebanana_category"),
            gamebanana_supported_files=data_dict.get("gamebanana_supported_files", []),
            gamebanana_compatibility_checked=data_dict.get(
                "gamebanana_compatibility_checked", False
            ),
            has_full_metadata=data_dict.get("has_full_metadata", False),
        )


type AnyModInfo = LocalModInfo | BrowserModInfo
ModInfo = BrowserModInfo
