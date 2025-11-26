from typing import Dict, Any, List, Optional
import threading
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from models.mod_models import ModInfo
from models.game_modes import GameMode, FullGameMode


class AppState(QObject):
    is_installing_changed = pyqtSignal(bool)
    is_merging_changed = pyqtSignal(bool)
    game_mode_changed = pyqtSignal(object)
    current_mode_changed = pyqtSignal(str)
    selected_chapter_changed = pyqtSignal(object)
    operation_cancelled_changed = pyqtSignal(bool)
    filtered_mods_changed = pyqtSignal(list)
    current_page_changed = pyqtSignal(int)
    search_text_changed = pyqtSignal(str)
    library_search_text_changed = pyqtSignal(str)
    mods_per_page_changed = pyqtSignal(int)
    current_task_changed = pyqtSignal(object)
    action_button_text_changed = pyqtSignal(str)
    action_button_enabled_changed = pyqtSignal(bool)
    saves_button_enabled_changed = pyqtSignal(bool)
    progress_bar_visible_changed = pyqtSignal(bool)
    progress_bar_value_changed = pyqtSignal(int)
    all_mods_updated = pyqtSignal(list)
    _reactive_attrs = {'_is_installing': 'is_installing_changed', '_is_merging': 'is_merging_changed', '_game_mode': 'game_mode_changed', '_current_mode': 'current_mode_changed', '_selected_chapter_id': 'selected_chapter_changed', '_operation_cancelled': 'operation_cancelled_changed', '_filtered_mods': 'filtered_mods_changed', '_current_page': 'current_page_changed', '_search_text': 'search_text_changed', '_library_search_text': 'library_search_text_changed', '_mods_per_page': 'mods_per_page_changed', '_current_task': 'current_task_changed', '_action_button_text': 'action_button_text_changed', '_action_button_enabled': 'action_button_enabled_changed', '_progress_bar_visible': 'progress_bar_visible_changed', '_progress_bar_value': 'progress_bar_value_changed'}

    def __init__(self):
        super().__init__()
        self._mods_metadata_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self.local_config: Dict[str, Any] = {}
        self.game_path: str = ''
        self.demo_game_path: str = ''
        self.undertale_game_path: str = ''
        self.config_dir: str = ''
        self.mods_dir: str = ''
        self.plugins_dir: str = ''
        self.mods_metadata_path: str = ''
        self.plugins_metadata_path: str = ''
        self.config_path: str = ''
        self._all_mods: List[ModInfo] = []
        self.mods_loaded: bool = False
        self.is_settings_view: bool = False
        self.is_changelog_view: bool = False
        self.is_help_view: bool = False
        self.current_settings_page: Optional[Any] = None
        self.settings_nav_stack: List[Any] = []
        self._current_mode: str = 'normal'
        self._selected_chapter_id: Optional[int] = None
        self._is_installing: bool = False
        self._is_merging: bool = False
        self.update_in_progress: bool = False
        self.initialization_completed: bool = False
        self.is_shown_to_user: bool = False
        self._game_mode: GameMode = FullGameMode()
        self.slots: Dict[int, Any] = {}
        self.global_settings: Dict[str, Any] = {}
        self.plugins: List[Dict[str, Any]] = []
        self.translations_by_chapter: Dict[int, List] = {i: [] for i in range(5)}
        self.is_full_install: bool = False
        self.game_is_running: bool = False
        self.pending_dialogs: List[Any] = []
        self._operation_cancelled: bool = False
        self._filtered_mods: List[ModInfo] = []
        self._current_page: int = 1
        self._search_text: str = ''
        self._library_search_text: str = ''
        self._mods_per_page: int = 20
        self._current_task: Optional[QThread] = None
        self._action_button_text: str = ''
        self._action_button_enabled: bool = True
        self._progress_bar_visible: bool = False
        self._progress_bar_value: int = 0
        self.gamebanana_loaded_pages: Dict[int, int] = {}
        self.gamebanana_loading: bool = False
        self.gamebanana_sort: str = 'default'
        self.gamebanana_mods_needing_metadata: List[str] = []
        self.has_internet: bool = True
        self.pending_announce_check: bool = False
        self.current_install_mod_identifier: Optional[str] = None
        self.current_install_is_gamebanana: bool = False
        self.current_install_progress: int = 0
        self.network_session: Optional[Any] = None

    def __setattr__(self, name: str, value: Any) -> None:
        reactive_attrs = getattr(type(self), '_reactive_attrs', None)
        if reactive_attrs and name in reactive_attrs:
            old_value = getattr(self, name, None) if hasattr(self, name) else None
            super().__setattr__(name, value)
            if old_value != value:
                signal_name = reactive_attrs[name]
                signal = getattr(self, signal_name, None)
                if signal:
                    signal.emit(value)
        else:
            super().__setattr__(name, value)

    def get_all_mods(self) -> List[ModInfo]:
        with self._mods_metadata_lock:
            return list(self._all_mods)

    def set_all_mods(self, mods: List[ModInfo]) -> None:
        with self._mods_metadata_lock:
            self._all_mods = list(mods) if mods else []

    def append_mod(self, mod: ModInfo) -> None:
        with self._mods_metadata_lock:
            if mod not in self._all_mods:
                self._all_mods.append(mod)

    def remove_mod(self, mod: ModInfo) -> None:
        with self._mods_metadata_lock:
            if mod in self._all_mods:
                self._all_mods.remove(mod)

    def clear_all_mods(self) -> None:
        with self._mods_metadata_lock:
            self._all_mods.clear()

    def extend_all_mods(self, mods: List[ModInfo]) -> None:
        with self._mods_metadata_lock:
            existing_keys = {getattr(m, 'key', None) for m in self._all_mods}
            for mod in mods:
                mod_key = getattr(mod, 'key', None)
                if mod_key and mod_key not in existing_keys:
                    self._all_mods.append(mod)
                    existing_keys.add(mod_key)

    @property
    def all_mods(self) -> List[ModInfo]:
        return self.get_all_mods()

    @all_mods.setter
    def all_mods(self, value: List[ModInfo]) -> None:
        self.set_all_mods(value)

    @property
    def is_installing(self) -> bool:
        return self._is_installing

    @is_installing.setter
    def is_installing(self, value: bool) -> None:
        self._is_installing = value

    @property
    def is_merging(self) -> bool:
        return self._is_merging

    @is_merging.setter
    def is_merging(self, value: bool) -> None:
        self._is_merging = value

    @property
    def game_mode(self) -> GameMode:
        return self._game_mode

    @game_mode.setter
    def game_mode(self, mode: GameMode) -> None:
        self._game_mode = mode

    @property
    def current_mode(self) -> str:
        return self._current_mode

    @current_mode.setter
    def current_mode(self, mode: str) -> None:
        self._current_mode = mode

    @property
    def selected_chapter_id(self) -> Optional[int]:
        return self._selected_chapter_id

    @selected_chapter_id.setter
    def selected_chapter_id(self, chapter_id: Optional[int]) -> None:
        self._selected_chapter_id = chapter_id

    @property
    def operation_cancelled(self) -> bool:
        return self._operation_cancelled

    @operation_cancelled.setter
    def operation_cancelled(self, value: bool) -> None:
        self._operation_cancelled = value

    @property
    def filtered_mods(self) -> List[ModInfo]:
        return self._filtered_mods

    @filtered_mods.setter
    def filtered_mods(self, value: List[ModInfo]) -> None:
        self._filtered_mods = value

    @property
    def current_page(self) -> int:
        return self._current_page

    @current_page.setter
    def current_page(self, value: int) -> None:
        self._current_page = value

    @property
    def search_text(self) -> str:
        return self._search_text

    @search_text.setter
    def search_text(self, value: str) -> None:
        self._search_text = value

    @property
    def library_search_text(self) -> str:
        return self._library_search_text

    @library_search_text.setter
    def library_search_text(self, value: str) -> None:
        self._library_search_text = value

    @property
    def mods_per_page(self) -> int:
        return self._mods_per_page

    @mods_per_page.setter
    def mods_per_page(self, value: int) -> None:
        self._mods_per_page = value

    @property
    def current_task(self) -> Optional[QThread]:
        return self._current_task

    @current_task.setter
    def current_task(self, task: Optional[QThread]) -> None:
        self._current_task = task

    def clear_current_task(self) -> None:
        self.current_task = None

    def cancel_current_operation(self):
        import logging
        self.operation_cancelled = True
        logging.info('AppState: Cancel button clicked')
        if self.current_task:
            if hasattr(self.current_task, 'cancel') and callable(getattr(self.current_task, 'cancel', None)):
                logging.info(f'AppState: Calling cancel() on current_task: {type(self.current_task).__name__}')
                try:
                    cancel_method = getattr(self.current_task, 'cancel')
                    cancel_method()
                except Exception as e:
                    logging.error(f'AppState: Error calling cancel() on task: {e}', exc_info=True)
            else:
                logging.warning(f'AppState: current_task {type(self.current_task).__name__} does not have cancel() method')
        else:
            logging.warning('AppState: No current_task to cancel')

    @property
    def action_button_text(self) -> str:
        return self._action_button_text

    @action_button_text.setter
    def action_button_text(self, value: str) -> None:
        self._action_button_text = value

    @property
    def action_button_enabled(self) -> bool:
        return self._action_button_enabled

    @action_button_enabled.setter
    def action_button_enabled(self, value: bool) -> None:
        self._action_button_enabled = value

    @property
    def progress_bar_visible(self) -> bool:
        return self._progress_bar_visible

    @progress_bar_visible.setter
    def progress_bar_visible(self, value: bool) -> None:
        self._progress_bar_visible = value

    @property
    def progress_bar_value(self) -> int:
        return self._progress_bar_value

    @progress_bar_value.setter
    def progress_bar_value(self, value: int) -> None:
        self._progress_bar_value = value
