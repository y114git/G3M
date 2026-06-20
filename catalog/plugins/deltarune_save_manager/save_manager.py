import logging
import os
import platform
import re
import shutil
import tempfile
import time

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLineEdit,
    QVBoxLayout,
)

from config.config import UI_COLORS
from utils.native_integration import get_open_file_name, open_path_native

logger = logging.getLogger(__name__)

def tr(k, **kw):
    return k

def _load_save_utils():
    """Helper function to load save_utils module dynamically."""
    import importlib.util
    save_utils_path = os.path.join(os.path.dirname(__file__), 'save_utils.py')
    spec = importlib.util.spec_from_file_location("save_utils", save_utils_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load save_utils module from: {save_utils_path}")
    save_utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(save_utils)
    return save_utils

class SaveManager(QObject):
    slots_updated = pyqtSignal()
    status_changed = pyqtSignal(str, str)
    collection_ui_update_needed = pyqtSignal()

    def __init__(
        self, app_state, feedback_manager, settings_manager, plugin_api, parent=None
    ) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.settings_manager = settings_manager
        self.plugin_api = plugin_api
        self.parent_widget = parent
        self._last_browse_dir = os.path.expanduser('~')
        self._save_path = None
        self._current_collection_idx = -1
        self._selected_slot = None
        self._backup_info = {}

    @staticmethod
    def _has_save_data(path: str) -> bool:
        try:
            return os.path.getsize(path) > 0
        except OSError:
            return False

    @staticmethod
    def _has_collection_dirs(path: str) -> bool:
        if not path or not os.path.isdir(path):
            return False
        rx = re.compile(r"(.+?)_(\d+)$")
        try:
            return any(
                rx.match(entry) and os.path.isdir(os.path.join(path, entry))
                for entry in os.listdir(path)
            )
        except OSError:
            return False

    def _is_usable_save_path(self, path: str) -> bool:
        save_utils = _load_save_utils()
        return bool(path) and os.path.isdir(path) and (
            save_utils.is_valid_save_path(path) or self._has_collection_dirs(path)
        )

    def _clear_save_path(self) -> None:
        self.save_path = ''
        self.current_collection_idx = -1
        self.selected_slot = None

    @property
    def save_path(self):
        if self._save_path is None:
            self._save_path = self.plugin_api.get_config('save_path', '')
            if not self._save_path:
                self._save_path = self.app_state.local_config.get('save_path', '')
                if self._save_path:
                    self.plugin_api.set_config('save_path', self._save_path)
        return self._save_path

    @save_path.setter
    def save_path(self, value):
        self._save_path = value
        self.plugin_api.set_config('save_path', value)

    @property
    def current_collection_idx(self):
        if self._current_collection_idx == -1:
            self._current_collection_idx = self.plugin_api.get_config('current_collection_idx', -1)
        return self._current_collection_idx

    @current_collection_idx.setter
    def current_collection_idx(self, value):
        self._current_collection_idx = value
        self.plugin_api.set_config('current_collection_idx', value)

    @property
    def selected_slot(self):
        return self._selected_slot

    @selected_slot.setter
    def selected_slot(self, value):
        self._selected_slot = value

    def collection_regex(self):
        return re.compile(r'(.+?)_(\d+)$')

    def old_collection_regex(self):
        return re.compile(r'(.+?)_(\d+)_(\d+)$')

    def list_collections(self) -> list[str]:
        cols = []
        rx = self.collection_regex()
        if not (self.save_path and os.path.isdir(self.save_path)):
            return cols
        for entry in os.listdir(self.save_path):
            m = rx.match(entry)
            if m and os.path.isdir(os.path.join(self.save_path, entry)):
                cols.append(entry)

        def _index(name: str) -> int:
            m = rx.match(name)
            return int(m.group(2)) if m else 10000
        cols.sort(key=_index)
        return cols

    def get_collection_path(self, idx: int) -> str:
        if idx == -1:
            return self.save_path
        cols = self.list_collections()
        if 0 <= idx < len(cols):
            return os.path.join(self.save_path, cols[idx])
        return ''

    def find_and_validate_save_path(self) -> bool:
        if self._is_usable_save_path(self.save_path):
            self.migrate_old_collections()
            return True
        if self.save_path and not os.path.isdir(self.save_path):
            self._clear_save_path()

        candidates = []
        system = platform.system()
        home = os.path.expanduser('~')

        if system == 'Windows':
            local_appdata = os.getenv('LOCALAPPDATA', '')
            appdata = os.getenv('APPDATA', '')
            if local_appdata:
                candidates.append(os.path.join(local_appdata, 'DELTARUNE'))
            if appdata:
                candidates.append(os.path.join(appdata, 'DELTARUNE'))
        elif system == 'Darwin':
            candidates.append(os.path.join(home, 'Library', 'Application Support', 'DELTARUNE'))
        else:
            proton_full = os.path.join(home, '.steam', 'steam', 'steamapps', 'compatdata', '1671210', 'pfx', 'drive_c', 'users', 'steamuser', 'AppData', 'Local', 'DELTARUNE')
            proton_demo = os.path.join(home, '.steam', 'steam', 'steamapps', 'compatdata', '1690940', 'pfx', 'drive_c', 'users', 'steamuser', 'AppData', 'Local', 'DELTARUNE')
            native_cfg = os.path.join(home, '.config', 'DELTARUNE')
            candidates.extend([proton_full, proton_demo, native_cfg])

        for path in candidates:
            if self._is_usable_save_path(path):
                self.save_path = path
                self.migrate_old_collections()
                return True

        return False

    def prompt_for_save_path(self) -> bool:
        path = self.settings_manager.pick_directory(
            tr('ui.select_deltarune_saves_folder'),
            self._last_browse_dir,
        )

        if not path:
            return False
        self._last_browse_dir = path

        if not os.path.isdir(path):
            self.feedback_manager.show_message('warning', 'errors.empty_folder_title', tr('errors.empty_folder_message'))
            return False

        self.save_path = path
        self.current_collection_idx = -1
        self.selected_slot = None
        self.migrate_old_collections()
        return True

    def migrate_old_collections(self):
        if not (self.save_path and os.path.isdir(self.save_path)):
            return
        old_rx = self.old_collection_regex()
        old_collections = {}
        for entry in os.listdir(self.save_path):
            m = old_rx.match(entry)
            if m and os.path.isdir(os.path.join(self.save_path, entry)):
                name, idx, chapter = m.groups()
                key = (name, int(idx))
                if key not in old_collections:
                    old_collections[key] = {}
                old_collections[key][int(chapter)] = entry
        if not old_collections:
            return
        migrated_count = 0
        for (name, idx), chapters in old_collections.items():
            new_folder_name = f'{name}_{idx}'
            new_folder_path = os.path.join(self.save_path, new_folder_name)
            if os.path.exists(new_folder_path):
                continue
            try:
                os.makedirs(new_folder_path, exist_ok=True)
                for chapter, old_folder in chapters.items():
                    old_path = os.path.join(self.save_path, old_folder)
                    for file in os.listdir(old_path):
                        if file.startswith(f'filech{chapter}_'):
                            src = os.path.join(old_path, file)
                            dst = os.path.join(new_folder_path, file)
                            if os.path.exists(src):
                                shutil.copy2(src, dst)
                for old_folder in chapters.values():
                    old_path = os.path.join(self.save_path, old_folder)
                    shutil.rmtree(old_path)
                migrated_count += 1
            except Exception as e:
                logger.warning('SaveManager._migrate_old_collections: migration failed for %s: %s', name, e)
        if migrated_count > 0:
            self._reindex_collections()

    def manage_steam_deck_saves(self) -> None:
        if platform.system() != 'Linux':
            return
        try:
            home_dir = os.path.expanduser('~')
            if self.app_state.game_mode.game_id == 'undertale':
                game_name = 'UNDERTALE'
            else:
                game_name = 'DELTARUNE'
            steam_app_id = self.app_state.game_mode.steam_app_id
            native_save_path = os.path.join(home_dir, '.config', game_name)
            proton_save_path = os.path.join(home_dir, '.steam', 'steam', 'steamapps', 'compatdata', steam_app_id, 'pfx', 'drive_c', 'users', 'steamuser', 'AppData', 'Local', game_name)
            if not os.path.isdir(proton_save_path):
                return
            if os.path.lexists(native_save_path):
                if os.path.islink(native_save_path) and os.readlink(native_save_path) == proton_save_path:
                    return
                if os.path.isdir(native_save_path) and (not os.listdir(native_save_path)):
                    os.rmdir(native_save_path)
                else:
                    backup_path = f'{native_save_path}_backup_{int(time.time())}'
                    os.rename(native_save_path, backup_path)
                    self.feedback_manager.show_message('info', 'dialogs.backup', tr('dialogs.backup_created_for_steam_deck', backup_path=backup_path))
            os.symlink(proton_save_path, native_save_path)
            self.feedback_manager.show_message('info', 'dialogs.steam_deck_setup', tr('dialogs.steam_deck_compatibility_configured'))
        except Exception as e:
            logger.error(f'Steam Deck setup error: {e}')

    def _reindex_collections(self):
        cols = []
        rx = self.collection_regex()
        if not (self.save_path and os.path.isdir(self.save_path)):
            return
        for entry in os.listdir(self.save_path):
            m = rx.match(entry)
            if m and os.path.isdir(os.path.join(self.save_path, entry)):
                name = m.group(1)
                cols.append((entry, name))
        cols.sort(key=lambda x: x[0])
        for new_idx, (old_folder, name) in enumerate(cols):
            new_folder = f'{name}_{new_idx}'
            if old_folder != new_folder:
                try:
                    old_path = os.path.join(self.save_path, old_folder)
                    new_path = os.path.join(self.save_path, new_folder)
                    os.rename(old_path, new_path)
                except Exception as e:
                    logger.debug(f'SaveManager._reindex_collections: rename {old_folder} to {new_folder} failed: {e}')

    def get_slot_data(self, chapter: int, slot: int, base_path: str) -> tuple[bool, str]:
        save_utils = _load_save_utils()
        save_slot_finish_map = save_utils.SAVE_SLOT_FINISH_MAP

        fp = os.path.join(base_path, f'filech{chapter}_{slot}')
        active = os.path.exists(fp) and os.path.getsize(fp) > 0
        if active:
            try:
                with open(fp, encoding='utf-8', errors='replace') as f:
                    lines = f.read().splitlines()
                nickname = lines[0] if len(lines) > 0 else '???'
                currency = lines[10] if len(lines) > 10 else '0'
            except Exception as e:
                logger.debug(f'SaveManager.get_slot_data: failed to read {fp}: {e}')
                nickname, currency = ('???', '0')
            fin_idx = save_slot_finish_map.get(slot, -1)
            fin_fp = os.path.join(base_path, f'filech{chapter}_{fin_idx}')
            finished = os.path.exists(fin_fp) and os.path.getsize(fin_fp) > 0
            status = tr('status.completed_save') if finished else tr('status.incomplete_save')
            text = tr('ui.save_info', nickname=nickname, currency=currency, status=status)
        else:
            text = tr('status.empty_save_slot')
        return (active, text)

    def refresh_save_slots_data(self, chapter: int) -> dict[int, tuple[bool, str]]:
        if not (self.save_path and os.path.isdir(self.save_path)):
            return {}
        idx = self.current_collection_idx
        base_path = self.get_collection_path(idx) or self.save_path
        result = {}
        for s in range(3):
            result[s] = self.get_slot_data(chapter, s, base_path)
        return result

    def create_new_collection(self) -> bool:
        if (name := self.prompt_collection_name()) is None:
            return False
        idx = len(self.list_collections())
        folder = f'{name}_{idx}'
        try:
            os.makedirs(os.path.join(self.save_path, folder), exist_ok=False)
            return True
        except Exception as e:
            self.feedback_manager.show_message('error', 'errors.folder_creation_failed', error=str(e))
            return False

    def prompt_collection_name(self, default: str = 'Collection') -> str | None:
        dlg = QDialog(self.parent_widget)
        dlg.setWindowTitle(tr('dialogs.new_collection'))
        layout = QVBoxLayout(dlg)
        name_input = QLineEdit()
        name_input.setMaxLength(20)
        name_input.setText(default)
        name_input.selectAll()
        layout.addWidget(name_input)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        layout.addWidget(bb)
        name_input.setFocus()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return name_input.text().strip() or default
        return None

    def rename_current_collection(self, idx: int) -> bool:
        if idx == -1:
            return False
        cols = self.list_collections()
        if idx >= len(cols):
            return False
        old_folder = cols[idx]
        old_name = old_folder.rsplit('_', 1)[0]
        new_name, ok = QInputDialog.getText(self.parent_widget, tr('dialogs.change_collection_name'), tr('dialogs.new_name'), text=old_name)
        if not ok or not new_name.strip():
            return False
        new_folder = f'{new_name.strip()}_{idx}'
        try:
            os.rename(os.path.join(self.save_path, old_folder), os.path.join(self.save_path, new_folder))
            self.slots_updated.emit()
            return True
        except Exception as e:
            self.feedback_manager.show_message('error', 'errors.rename_failed', error=str(e))
            return False

    def delete_current_collection(self, idx: int) -> bool:
        if idx == -1:
            return False
        cols = self.list_collections()
        if idx >= len(cols):
            return False
        folder = cols[idx]
        if not self.feedback_manager.ask_question('dialogs.delete_collection', 'dialogs.delete_collection_confirmation', '', False):
            return False
        try:
            shutil.rmtree(os.path.join(self.save_path, folder))
            self._reindex_collections()
            self.current_collection_idx = -1
            self.slots_updated.emit()
            return True
        except Exception as e:
            self.feedback_manager.show_message('error', 'errors.deletion_failed', error=str(e))
            return False

    def copy_between_storages(self, chapter: int, to_collection: bool, selected_slot: tuple[int, int] | None = None):
        save_utils = _load_save_utils()
        save_slot_finish_map = save_utils.SAVE_SLOT_FINISH_MAP

        idx = self.current_collection_idx
        if idx == -1:
            return
        copy_all_chapters = False
        if selected_slot is None or selected_slot[0] != chapter:
            options = [tr('dialogs.copy_current_chapter'), tr('dialogs.copy_all_chapters')]
            choice, ok = QInputDialog.getItem(self.parent_widget, tr('dialogs.copy_scope_title'), tr('dialogs.copy_scope_question'), options, 0, False)
            if not ok:
                return
            copy_all_chapters = options.index(choice) == 1
        src_dir = self.save_path if to_collection else self.get_collection_path(idx)
        dst_dir = self.get_collection_path(idx) if to_collection else self.save_path
        if not src_dir or not dst_dir:
            return
        if selected_slot is None or selected_slot[0] != chapter:
            slot_indices = range(3)
        else:
            slot_indices = [selected_slot[1]]
        if copy_all_chapters:
            chapters_to_copy = range(1, 6)
            if selected_slot is None:
                prompt = tr('dialogs.overwrite_all_3_slots_all_chapters_collection') if to_collection else tr('dialogs.overwrite_all_3_slots_all_chapters_main')
            else:
                prompt = tr('dialogs.overwrite_selected_slot_all_chapters_collection') if to_collection else tr('dialogs.overwrite_selected_slot_all_chapters_main')
        else:
            chapters_to_copy = [chapter]
            if selected_slot is None:
                prompt = tr('dialogs.overwrite_all_3_slots_collection') if to_collection else tr('dialogs.overwrite_all_3_main_slots')
            else:
                prompt = tr('dialogs.overwrite_selected_slot_collection') if to_collection else tr('dialogs.overwrite_selected_main_slot')
        if not self.feedback_manager.ask_question('dialogs.copy_confirmation', 'dialogs.copy_confirmation', prompt, False):
            return
        try:
            for ch in chapters_to_copy:
                for slot_idx in slot_indices:
                    finish_idx = save_slot_finish_map.get(slot_idx, -1)
                    names = [f'filech{ch}_{slot_idx}', f'filech{ch}_{finish_idx}']
                    for name in names:
                        src = os.path.join(src_dir, name)
                        dst = os.path.join(dst_dir, name)
                        if os.path.exists(src):
                            shutil.copy2(src, dst)
                        elif os.path.exists(dst):
                            os.remove(dst)
            self.slots_updated.emit()
            self.status_changed.emit(tr('status.copying_completed'), UI_COLORS['status_success'])
        except Exception as e:
            self.feedback_manager.show_message('error', 'errors.copy_failed', error=str(e))
            self.status_changed.emit(tr('status.copying_error'), UI_COLORS['status_error'])

    def action_show_save(self, chapter: int, slot: int):
        idx = self.current_collection_idx
        path = self.get_collection_path(idx)
        open_path_native(path)

    def action_delete_save(self, chapter: int, slot: int) -> bool:
        idx = self.current_collection_idx
        base = self.get_collection_path(idx)
        fp = os.path.join(base, f'filech{chapter}_{slot}')
        if not os.path.exists(fp):
            return False
        if not self.feedback_manager.ask_question('dialogs.delete_save', 'dialogs.delete_save_confirmation', '', False):
            return False
        try:
            os.remove(fp)
            self.slots_updated.emit()
            return True
        except Exception as e:
            self.feedback_manager.show_message('error', 'errors.error', str(e))
            return False

    def action_import_export(self, chapter: int, slot: int, is_import: bool) -> bool:
        save_utils = _load_save_utils()
        save_slot_finish_map = save_utils.SAVE_SLOT_FINISH_MAP

        idx = self.current_collection_idx
        base_cur = self.get_collection_path(idx)
        src_fp = os.path.join(base_cur, f'filech{chapter}_{slot}')
        choice, ok = QInputDialog.getItem(self.parent_widget, tr('dialogs.where_to') if not is_import else tr('dialogs.where_from'), tr('ui.select_storage'), [tr('dialogs.external_file') if is_import else tr('dialogs.external_folder'), tr('dialogs.additional_collection') if idx == -1 else tr('dialogs.main_slots')], 0, False)
        if not ok:
            return False
        if choice in [tr('dialogs.external_file'), tr('dialogs.external_folder')]:
            if is_import:
                fp, _ = get_open_file_name(self.parent_widget, tr('ui.select_save_file'), self._last_browse_dir, f'Save Files (filech{chapter}_*)')
                if not fp:
                    return False
                self._last_browse_dir = os.path.dirname(fp)
                if not re.fullmatch(f'filech{chapter}_[0-2]', os.path.basename(fp)):
                    self.feedback_manager.show_message('warning', 'errors.invalid_file', tr('errors.wrong_save_file'))
                    return False
                shutil.copy2(fp, src_fp)
                fin_idx = save_slot_finish_map.get(slot, -1)
                fin_name = f'filech{chapter}_{fin_idx}'
                fin_src = os.path.join(os.path.dirname(fp), fin_name)
                fin_dst = os.path.join(base_cur, fin_name)
                if os.path.exists(fin_src):
                    shutil.copy2(fin_src, fin_dst)
            else:
                dir_ = self.settings_manager.pick_directory(
                    tr('dialogs.export_save_location'),
                    self._last_browse_dir,
                )
                if not dir_:
                    return False
                self._last_browse_dir = dir_
                if not os.path.exists(src_fp):
                    self.feedback_manager.show_message('warning', 'errors.no_save', tr('errors.empty_slot'))
                    return False
                shutil.copy2(src_fp, dir_)
                fin_idx = save_slot_finish_map.get(slot, -1)
                fin_src = os.path.join(base_cur, f'filech{chapter}_{fin_idx}')
                if os.path.exists(src_fp) and os.path.exists(fin_src):
                    shutil.copy2(fin_src, dir_)
        else:
            if idx == -1:
                cols = self.list_collections()
                if not cols:
                    if not self.feedback_manager.ask_question('dialogs.no_collections', 'dialogs.create_new_collection_question', '', False):
                        return False
                    if not self.create_new_collection():
                        return False
                    cols = self.list_collections()
                sel, ok = QInputDialog.getItem(self.parent_widget, tr('ui.collections'), tr('ui.select'), cols, 0, False)
                if not ok:
                    return False
                target_base = os.path.join(self.save_path, sel)
            else:
                target_base = self.save_path
            src_main_fp = os.path.join(base_cur, f'filech{chapter}_{slot}')
            target_main_fp = os.path.join(target_base, f'filech{chapter}_{slot}')
            fin_idx = save_slot_finish_map.get(slot, -1)
            fin_name = f'filech{chapter}_{fin_idx}'
            src_fin_fp = os.path.join(base_cur, fin_name)
            target_fin_fp = os.path.join(target_base, fin_name)
            if is_import:
                if not os.path.exists(target_main_fp):
                    self.feedback_manager.show_message('warning', 'errors.no_save', tr('errors.no_import_save'))
                    return False
                shutil.copy2(target_main_fp, src_main_fp)
                if os.path.exists(target_fin_fp):
                    shutil.copy2(target_fin_fp, src_fin_fp)
                elif os.path.exists(src_fin_fp):
                    os.remove(src_fin_fp)
            else:
                if not os.path.exists(src_main_fp):
                    self.feedback_manager.show_message('warning', 'errors.no_save', tr('errors.empty_slot'))
                    return False
                shutil.copy2(src_main_fp, target_main_fp)
                if os.path.exists(src_fin_fp):
                    shutil.copy2(src_fin_fp, target_fin_fp)
                elif os.path.exists(target_fin_fp):
                    os.remove(target_fin_fp)
        self.slots_updated.emit()
        return True

    def toggle_collection_view(self) -> bool:
        idx = self.current_collection_idx
        if idx == -1:
            cols = self.list_collections()
            if not cols and (not self.create_new_collection()):
                return False
            self.current_collection_idx = 0
        else:
            self.current_collection_idx = -1
        self.slots_updated.emit()
        return True

    def navigate_collection(self, direction: int):
        cols = self.list_collections()
        if not cols and direction > 0:
            if not self.create_new_collection():
                return
            cols = self.list_collections()
        if not cols:
            return
        idx = self.current_collection_idx
        if idx == -1:
            idx = 0
        else:
            idx += direction
        if idx < 0:
            idx = 0
        elif idx >= len(cols):
            if direction > 0 and self.create_new_collection():
                idx = len(cols)
            else:
                idx = len(cols) - 1
        self.current_collection_idx = idx
        self.selected_slot = None
        self.slots_updated.emit()

    def get_collection_ui_state(self) -> dict:
        idx = self.current_collection_idx
        in_col = idx != -1
        cols = self.list_collections()
        collection_name = ''
        if in_col and 0 <= idx < len(cols):
            collection_name = cols[idx].rsplit('_', 1)[0]
        return {'in_collection': in_col, 'collection_name': collection_name, 'can_navigate_left': in_col and idx > 0, 'can_navigate_right': in_col, 'has_collections': len(cols) > 0}

    def prompt_for_save_collection_on_launch(self) -> int | None:
        if not self.save_path:
            self.find_and_validate_save_path()
        if not self._is_usable_save_path(self.save_path):
            return -1
        cols = self.list_collections()
        if not cols:
            return -1
        choices = [tr('dialogs.main_slots')]
        for col_folder in cols:
            col_name = col_folder.rsplit('_', 1)[0]
            choices.append(col_name)
        choice, ok = QInputDialog.getItem(self.parent_widget, tr('dialogs.select_save_collection'), tr('dialogs.select_save_collection_question'), choices, 0, False)
        if not ok:
            return None
        if choice == tr('dialogs.main_slots'):
            return -1
        for idx, col_folder in enumerate(cols):
            col_name = col_folder.rsplit('_', 1)[0]
            if col_name == choice:
                return idx
        return -1

    def apply_collection_saves_for_launch(self, collection_idx: int) -> dict:
        save_utils = _load_save_utils()
        save_slot_finish_map = save_utils.SAVE_SLOT_FINISH_MAP

        if collection_idx == -1 or not self._is_usable_save_path(self.save_path):
            return {}
        collection_path = self.get_collection_path(collection_idx)
        if not collection_path or not os.path.isdir(collection_path):
            return {}
        backup_info = {}
        empty_slots = {}
        main_save_path = self.save_path
        process_logger = getattr(self, 'processLogger', logging.getLogger(__name__))

        def _cleanup_path(path: str) -> None:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as exc:
                process_logger.warning(
                    'SaveManager.apply_collection_saves_for_launch: cleanup failed for %s: %s',
                    path,
                    exc,
                )

        def _backup_file(path: str) -> None:
            if not os.path.exists(path):
                return
            backup_path = path + '.g3m_backup'
            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix=os.path.basename(backup_path) + '.',
                suffix='.tmp',
                dir=os.path.dirname(backup_path) or None,
            )
            os.close(tmp_fd)
            try:
                shutil.copy2(path, tmp_path)
                os.replace(tmp_path, backup_path)
            except OSError as exc:
                _cleanup_path(tmp_path)
                process_logger.error(
                    'SaveManager.apply_collection_saves_for_launch: backup failed for %s: %s',
                    path,
                    exc,
                )
                raise
            backup_info[path] = backup_path

        def _rollback() -> None:
            for target in empty_slots:
                _cleanup_path(target)
            for original_file, backup_file in backup_info.items():
                if os.path.exists(backup_file):
                    try:
                        if os.path.exists(original_file):
                            os.remove(original_file)
                        os.replace(backup_file, original_file)
                    except OSError as exc:
                        process_logger.error(
                            'SaveManager.apply_collection_saves_for_launch: rollback failed for %s from %s: %s',
                            original_file,
                            backup_file,
                            exc,
                        )

        for chapter in range(1, 6):
            for slot in range(3):
                main_file = os.path.join(main_save_path, f'filech{chapter}_{slot}')
                col_file = os.path.join(collection_path, f'filech{chapter}_{slot}')
                try:
                    _backup_file(main_file)
                    if self._has_save_data(col_file):
                        shutil.copy2(col_file, main_file)
                    elif os.path.exists(main_file):
                        os.remove(main_file)
                        empty_slots[main_file] = col_file
                    else:
                        empty_slots[main_file] = col_file
                except OSError as exc:
                    process_logger.error(
                        'SaveManager.apply_collection_saves_for_launch: failed to apply %s -> %s: %s',
                        col_file,
                        main_file,
                        exc,
                    )
                    _rollback()
                    return {}
                fin_idx = save_slot_finish_map.get(slot, -1)
                if fin_idx != -1:
                    main_fin = os.path.join(main_save_path, f'filech{chapter}_{fin_idx}')
                    col_fin = os.path.join(collection_path, f'filech{chapter}_{fin_idx}')
                    try:
                        _backup_file(main_fin)
                        if self._has_save_data(col_fin):
                            shutil.copy2(col_fin, main_fin)
                        elif os.path.exists(main_fin):
                            os.remove(main_fin)
                            empty_slots[main_fin] = col_fin
                        else:
                            empty_slots[main_fin] = col_fin
                    except OSError as exc:
                        process_logger.error(
                            'SaveManager.apply_collection_saves_for_launch: failed to apply %s -> %s: %s',
                            col_fin,
                            main_fin,
                            exc,
                        )
                        _rollback()
                        return {}
        backup_info['__empty_slots__'] = empty_slots
        return backup_info

    def restore_original_saves_after_launch(self, backup_info: dict):
        if not backup_info:
            return
        empty_slots = backup_info.pop('__empty_slots__', {})
        for main_file, col_file in empty_slots.items():
            if os.path.exists(main_file):
                try:
                    shutil.copy2(main_file, col_file)
                    os.remove(main_file)
                except Exception as e:
                    logger.warning(f'SaveManager: failed to capture new save {main_file} to collection: {e}')
        for original_file, backup_file in backup_info.items():
            if os.path.exists(backup_file):
                if os.path.exists(original_file):
                    os.remove(original_file)
                shutil.move(backup_file, original_file)
        for backup_file in backup_info.values():
            if os.path.exists(backup_file):
                os.remove(backup_file)
