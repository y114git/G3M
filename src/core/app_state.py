from typing import Dict, Any, List, Optional, Tuple
from PyQt6.QtCore import QObject, pyqtSignal
from models.mod_models import ModInfo
from models.game_modes import GameMode, FullGameMode


class AppState(QObject):
    is_installing_changed = pyqtSignal(bool)
    game_mode_changed = pyqtSignal(object)
    current_mode_changed = pyqtSignal(str)
    selected_chapter_changed = pyqtSignal(object)
    is_save_manager_view_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
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
        self._is_save_manager_view: bool = False
        self.is_changelog_view: bool = False
        self.is_help_view: bool = False
        self.current_settings_page: Optional[Any] = None
        self.settings_nav_stack: List[Any] = []
        self._current_mode: str = 'normal'
        self._selected_chapter_id: Optional[int] = None
        self._is_installing: bool = False
        self.update_in_progress: bool = False
        self.initialization_completed: bool = False
        self.is_shown_to_user: bool = False
        self._game_mode: GameMode = FullGameMode()
        self.slots: Dict[int, Any] = {}
        self.current_collection_idx: int = -1
        self.selected_slot: Optional[Tuple[int, int]] = None
        self.global_settings: Dict[str, Any] = {}
        self.plugins: List[Dict[str, Any]] = []
        self.translations_by_chapter: Dict[int, List] = {i: [] for i in range(5)}
        self.is_full_install: bool = False
        self.game_is_running: bool = False
        self.pending_dialogs: List[Any] = []

    @property
    def is_installing(self) -> bool:
        return self._is_installing

    @is_installing.setter
    def is_installing(self, value: bool) -> None:
        if self._is_installing != value:
            self._is_installing = value
            self.is_installing_changed.emit(value)

    @property
    def game_mode(self) -> GameMode:
        return self._game_mode

    @game_mode.setter
    def game_mode(self, mode: GameMode) -> None:
        if self._game_mode != mode:
            self._game_mode = mode
            self.game_mode_changed.emit(mode)

    @property
    def current_mode(self) -> str:
        return self._current_mode

    @current_mode.setter
    def current_mode(self, mode: str) -> None:
        if self._current_mode != mode:
            self._current_mode = mode
            self.current_mode_changed.emit(mode)

    @property
    def selected_chapter_id(self) -> Optional[int]:
        return self._selected_chapter_id

    @selected_chapter_id.setter
    def selected_chapter_id(self, chapter_id: Optional[int]) -> None:
        if self._selected_chapter_id != chapter_id:
            self._selected_chapter_id = chapter_id
            self.selected_chapter_changed.emit(chapter_id)

    @property
    def is_save_manager_view(self) -> bool:
        return self._is_save_manager_view

    @is_save_manager_view.setter
    def is_save_manager_view(self, value: bool) -> None:
        if self._is_save_manager_view != value:
            self._is_save_manager_view = value
            self.is_save_manager_view_changed.emit(value)
