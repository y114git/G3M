"""Data models for mod information and metadata."""

from dataclasses import dataclass, field
from typing import Any

from config.config import LEGACY_DESCRIPTION_KEY, LEGACY_ICON_KEY


@dataclass
class ModExtraFile:
    """Represents an extra file associated with a mod."""

    key: str
    version: str
    url: str


@dataclass
class ModFileData:
    """File data for a game content section (chapter, whole game, etc.)."""

    description: str | None = None
    data_file_url: str | None = None
    data_file_version: str | None = None
    extra_files: list[ModExtraFile] = field(default_factory=list)

    def is_valid(self) -> bool:
        return bool(self.data_file_url or self.extra_files)


@dataclass
class ModInfo:
    """Complete information about a mod including metadata and files."""

    id: str
    name: str
    version: str
    author: str
    description: str
    game_version: str
    description_url: str
    downloads: int | None
    game: str
    is_verified: bool
    like_count: int | None = None
    icon: str | None = None
    tags: list[str] = field(default_factory=list)
    hide_mod: bool = False
    ban_status: bool = False
    is_nsfw: bool = False
    has_files: bool = True
    is_wip: bool = False
    files: dict[str, ModFileData] = field(default_factory=dict)
    demo_url: str | None = None
    demo_version: str | None = None
    created_date: str | None = None
    last_updated: str | None = None
    external_url: str | None = None
    screenshots_url: list[str] = field(default_factory=list)
    full_description: str | None = None
    gamebanana_has_compatible_file: bool | None = None
    gamebanana_category: str | None = None
    gamebanana_is_tool_compatible: bool = False
    gamebanana_supported_files: list[dict[str, Any]] = field(default_factory=list)
    gamebanana_supported_tool_ids: list[int] = field(default_factory=list)
    gamebanana_preferred_format: str | None = None
    gamebanana_has_deltahub_file: bool = False
    gamebanana_has_deltamod_file: bool = False
    gamebanana_compatibility_checked: bool = False
    has_full_metadata: bool = False
    playtime_hours: float = 0.0

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

    def is_valid_for_demo(self) -> bool:
        return self.game == "deltarunedemo" and bool(
            (self.files and (self.files.get("deltarunedemo") or self.files.get("demo")))
            or (self.demo_url and self.demo_version)
        )

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

    @classmethod
    def from_dict(cls, data_dict: dict[str, Any]) -> ModInfo:
        from services.localization_service import tr

        files_dict = {}
        if "files" in data_dict and isinstance(data_dict["files"], dict):
            for key, value in data_dict["files"].items():
                if isinstance(value, dict):
                    extra_files = value.get("extra_files", [])
                    if (
                        extra_files
                        and isinstance(extra_files, list)
                        and isinstance(extra_files[0], dict)
                    ):
                        value = value.copy()
                        value["extra_files"] = [
                            ModExtraFile(**ef) if isinstance(ef, dict) else ef
                            for ef in extra_files
                        ]
                    files_dict[key] = ModFileData(**value)
                elif isinstance(value, ModFileData):
                    files_dict[key] = value
        mod_id = data_dict.get("id", "")
        game = data_dict.get("game", "deltarune")
        kwargs = {
            "id": mod_id,
            "name": data_dict.get("name", "Unknown Mod"),
            "version": data_dict.get("version", "1.0.0"),
            "author": data_dict.get("author", tr("defaults.unknown")),
            "description": data_dict.get(
                "description",
                data_dict.get(LEGACY_DESCRIPTION_KEY, tr("status.no_description_status")),
            ),
            "game_version": data_dict.get("game_version", tr("defaults.not_specified")),
            "description_url": data_dict.get("description_url", ""),
            "downloads": data_dict.get("downloads"),
            "like_count": data_dict.get(
                "like_count", data_dict.get("likes", data_dict.get("_nLikeCount"))
            ),
            "game": game,
            "is_verified": data_dict.get("is_verified", False),
            "icon": data_dict.get("icon", data_dict.get(LEGACY_ICON_KEY)),
            "tags": data_dict.get("tags", []),
            "hide_mod": data_dict.get("hide_mod", False),
            "ban_status": data_dict.get("ban_status", False),
            "is_nsfw": data_dict.get(
                "is_nsfw", data_dict.get("nsfw", data_dict.get("_bIsNsfw", False))
            ),
            "has_files": data_dict.get("has_files", data_dict.get("_bHasFiles", True)),
            "is_wip": data_dict.get("is_wip", False),
            "files": files_dict,
            "demo_url": data_dict.get("demo_url"),
            "demo_version": data_dict.get("demo_version"),
            "created_date": data_dict.get("created_date"),
            "last_updated": data_dict.get("last_updated"),
            "external_url": data_dict.get("external_url"),
            "screenshots_url": data_dict.get("screenshots_url", []),
            "full_description": data_dict.get("full_description"),
            "gamebanana_has_compatible_file": data_dict.get(
                "gamebanana_has_compatible_file"
            ),
            "gamebanana_category": data_dict.get("gamebanana_category"),
            "gamebanana_is_tool_compatible": data_dict.get(
                "gamebanana_is_tool_compatible", False
            ),
            "gamebanana_supported_files": data_dict.get(
                "gamebanana_supported_files", []
            ),
            "gamebanana_supported_tool_ids": data_dict.get(
                "gamebanana_supported_tool_ids", []
            ),
            "gamebanana_preferred_format": data_dict.get("gamebanana_preferred_format"),
            "gamebanana_has_deltahub_file": data_dict.get(
                "gamebanana_has_deltahub_file", False
            ),
            "gamebanana_has_deltamod_file": data_dict.get(
                "gamebanana_has_deltamod_file", False
            ),
            "gamebanana_compatibility_checked": data_dict.get(
                "gamebanana_compatibility_checked", False
            ),
            "has_full_metadata": data_dict.get("has_full_metadata", True),
            "playtime_hours": data_dict.get("playtime_hours", 0.0),
        }
        return cls(**kwargs)
