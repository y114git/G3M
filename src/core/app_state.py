from typing import Dict, Any, List, Optional, Tuple
from models.mod_models import ModInfo
from models.game_modes import GameMode, FullGameMode


class AppState:
    def __init__(self):
        self.local_config: Dict[str, Any] = {}
        self.game_path: str = ''
        self.demo_game_path: str = ''
        self.undertale_game_path: str = ''
        self.config_dir: str = ''
        self.mods_dir: str = ''
        self.plugins_dir: str = ''
        self.mods_metadata_path: str = ''
        self.config_path: str = ''
        self.save_path: str = ''
        self.all_mods: List[ModInfo] = []
        self.mods_loaded: bool = False
        self.is_settings_view: bool = False
        self.is_save_manager_view: bool = False
        self.is_changelog_view: bool = False
        self.is_help_view: bool = False
        self.current_settings_page: Optional[Any] = None
        self.settings_nav_stack: List[Any] = []
        self.current_mode: str = 'normal'
        self.selected_chapter_id: Optional[int] = None
        self.is_installing: bool = False
        self.update_in_progress: bool = False
        self.initialization_completed: bool = False
        self.is_shown_to_user: bool = False
        self.game_mode: GameMode = FullGameMode()
        self.slots: Dict[int, Any] = {}
        self.current_collection_idx: Dict[int, int] = {}
        self.selected_slot: Optional[Tuple[int, int]] = None
        self.global_settings: Dict[str, Any] = {}
        self.plugins: List[Dict[str, Any]] = []
        self.translations_by_chapter: Dict[int, List] = {i: [] for i in range(5)}
        self.is_full_install: bool = False
