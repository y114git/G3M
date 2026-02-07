"""Data models for mod information and metadata."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ModExtraFile:
    """Represents an extra file associated with a mod."""
    key: str
    version: str
    url: str


@dataclass
class ModChapterData:
    """Represents chapter-specific data for a mod."""
    description: Optional[str] = None
    data_file_url: Optional[str] = None
    data_file_version: Optional[str] = None
    extra_files: List[ModExtraFile] = field(default_factory=list)

    def is_valid(self) -> bool:
        return bool(self.data_file_url or self.extra_files)


@dataclass
class ModInfo:
    """Complete information about a mod including metadata and files."""
    _CHAPTER_MAP = {0: '0', 1: '1', 2: '2', 3: '3', 4: '4', -1: 'demo'}
    key: str
    name: str
    version: str
    author: str
    tagline: str
    game_version: str
    description_url: str
    downloads: int
    game: str
    is_verified: bool
    icon_url: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    hide_mod: bool = False
    ban_status: bool = False
    files: Dict[str, ModChapterData] = field(default_factory=dict)
    demo_url: Optional[str] = None
    demo_version: Optional[str] = None
    created_date: Optional[str] = None
    last_updated: Optional[str] = None
    external_url: Optional[str] = None
    screenshots_url: List[str] = field(default_factory=list)
    full_description: Optional[str] = None
    gamebanana_has_compatible_file: Optional[bool] = None
    gamebanana_category: Optional[str] = None
    gamebanana_is_tool_compatible: bool = False
    gamebanana_supported_files: List[Dict[str, Any]] = field(default_factory=list)
    gamebanana_supported_tool_ids: List[int] = field(default_factory=list)
    gamebanana_preferred_format: Optional[str] = None
    gamebanana_has_deltahub_file: bool = False
    gamebanana_has_deltamod_file: bool = False
    gamebanana_compatibility_checked: bool = False
    has_full_metadata: bool = False

    def get_chapter_data(self, chapter_id: int) -> Optional[ModChapterData]:
        if self.game == 'undertale' and chapter_id == 0:
            return self.files.get('undertale')
        return self.files.get(self._CHAPTER_MAP.get(chapter_id))

    def is_valid_for_demo(self) -> bool:
        return self.game == 'deltarunedemo' and bool((self.files and self.files.get('demo')) or (self.demo_url and self.demo_version))

    def is_gamebanana_mod(self) -> bool:
        return bool(self.key and isinstance(self.key, str) and self.key.startswith('gb_'))

    def get_gamebanana_mod_id(self) -> Optional[str]:
        return self.key[3:] if self.is_gamebanana_mod() and self.key else None

    @classmethod
    def from_dict(cls, data_dict: Dict[str, Any]) -> 'ModInfo':
        from services.localization_service import tr
        files_dict = {}
        if 'files' in data_dict and isinstance(data_dict['files'], dict):
            for key, value in data_dict['files'].items():
                if isinstance(value, dict):
                    extra_files = value.get('extra_files', [])
                    if extra_files and isinstance(extra_files, list) and isinstance(extra_files[0], dict):
                        value = value.copy()
                        value['extra_files'] = [ModExtraFile(**ef) if isinstance(ef, dict) else ef for ef in extra_files]
                    files_dict[key] = ModChapterData(**value)
                elif isinstance(value, ModChapterData):
                    files_dict[key] = value
        key = data_dict.get('key') or data_dict.get('mod_key', '')
        game = data_dict.get('game') or data_dict.get('modgame', 'deltarune')
        kwargs = {'key': key, 'name': data_dict.get('name', 'Unknown Mod'), 'version': data_dict.get('version', '1.0.0'), 'author': data_dict.get('author', tr('defaults.unknown')), 'tagline': data_dict.get('tagline', tr('status.no_description_status')), 'game_version': data_dict.get('game_version', tr('defaults.not_specified')), 'description_url': data_dict.get('description_url', ''), 'downloads': data_dict.get('downloads', 0), 'game': game, 'is_verified': data_dict.get('is_verified', False), 'icon_url': data_dict.get('icon_url'), 'tags': data_dict.get('tags', []), 'hide_mod': data_dict.get('hide_mod', False), 'ban_status': data_dict.get('ban_status', False), 'files': files_dict, 'demo_url': data_dict.get('demo_url'), 'demo_version': data_dict.get('demo_version'), 'created_date': data_dict.get('created_date'), 'last_updated': data_dict.get('last_updated'), 'external_url': data_dict.get('external_url'), 'screenshots_url': data_dict.get('screenshots_url', []), 'full_description': data_dict.get('full_description'), 'gamebanana_has_compatible_file': data_dict.get('gamebanana_has_compatible_file'), 'gamebanana_category': data_dict.get('gamebanana_category'), 'gamebanana_is_tool_compatible': data_dict.get('gamebanana_is_tool_compatible', False), 'gamebanana_supported_files': data_dict.get('gamebanana_supported_files', []), 'gamebanana_supported_tool_ids': data_dict.get('gamebanana_supported_tool_ids', []), 'gamebanana_preferred_format': data_dict.get('gamebanana_preferred_format'), 'gamebanana_has_deltahub_file': data_dict.get('gamebanana_has_deltahub_file', False), 'gamebanana_has_deltamod_file': data_dict.get('gamebanana_has_deltamod_file', False), 'gamebanana_compatibility_checked': data_dict.get('gamebanana_compatibility_checked', False), 'has_full_metadata': data_dict.get('has_full_metadata', True)}
        return cls(**kwargs)
