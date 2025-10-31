import os
import re
import shutil
import time
import platform
import logging
from typing import Optional
from PyQt6.QtCore import QObject, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QInputDialog, QLineEdit, QVBoxLayout
from managers.localization_manager import tr
from models.game_modes import UndertaleGameMode
from config.constants import SAVE_SLOT_FINISH_MAP, UI_COLORS
from utils.game_utils import is_valid_save_path, get_default_save_path


class SaveManager(QObject):
    slots_updated = pyqtSignal()
    status_changed = pyqtSignal(str, str)
    collection_ui_update_needed = pyqtSignal()

    def __init__(self, app_state, feedback_manager, settings_manager, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.settings_manager = settings_manager
        self.parent_widget = parent

    def collection_regex(self):
        return re.compile('(.+?)_(\\d+)$')

    def old_collection_regex(self):
        return re.compile('(.+?)_(\\d+)_(\\d+)$')

    def list_collections(self) -> list[str]:
        cols = []
        rx = self.collection_regex()
        if not (self.app_state.save_path and os.path.isdir(self.app_state.save_path)):
            return cols
        for entry in os.listdir(self.app_state.save_path):
            m = rx.match(entry)
            if m and os.path.isdir(os.path.join(self.app_state.save_path, entry)):
                cols.append(entry)

        def _index(name: str) -> int:
            m = rx.match(name)
            return int(m.group(2)) if m else 10000
        cols.sort(key=_index)
        return cols

    def get_collection_path(self, idx: int) -> str:
        if idx == -1:
            return self.app_state.save_path
        cols = self.list_collections()
        if 0 <= idx < len(cols):
            return os.path.join(self.app_state.save_path, cols[idx])
        return ''

    def find_and_validate_save_path(self) -> bool:
        if is_valid_save_path(self.app_state.save_path):
            self.migrate_old_collections()
            return True
        default_path = get_default_save_path()
        if is_valid_save_path(default_path):
            self.app_state.save_path = default_path
            self.app_state.local_config['save_path'] = self.app_state.save_path
            self.settings_manager.write_local_config()
            self.migrate_old_collections()
            return True
        return self.prompt_for_save_path()

    def prompt_for_save_path(self) -> bool:
        if not (path := QFileDialog.getExistingDirectory(self.parent_widget, tr('ui.select_deltarune_saves_folder'))):
            return False
        if not is_valid_save_path(path):
            self.feedback_manager.show_warning('errors.empty_folder_title', tr('errors.empty_folder_message'))
            return False
        self.app_state.save_path = path
        self.app_state.local_config['save_path'] = self.app_state.save_path
        self.settings_manager.write_local_config()
        self.migrate_old_collections()
        return True

    def migrate_old_collections(self):
        if not (self.app_state.save_path and os.path.isdir(self.app_state.save_path)):
            return
        old_rx = self.old_collection_regex()
        old_collections = {}
        for entry in os.listdir(self.app_state.save_path):
            m = old_rx.match(entry)
            if m and os.path.isdir(os.path.join(self.app_state.save_path, entry)):
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
            new_folder_path = os.path.join(self.app_state.save_path, new_folder_name)
            if os.path.exists(new_folder_path):
                continue
            try:
                os.makedirs(new_folder_path, exist_ok=True)
                for chapter, old_folder in chapters.items():
                    old_path = os.path.join(self.app_state.save_path, old_folder)
                    for file in os.listdir(old_path):
                        if file.startswith(f'filech{chapter}_'):
                            src = os.path.join(old_path, file)
                            dst = os.path.join(new_folder_path, file)
                            if os.path.exists(src):
                                shutil.copy2(src, dst)
                for old_folder in chapters.values():
                    old_path = os.path.join(self.app_state.save_path, old_folder)
                    shutil.rmtree(old_path)
                migrated_count += 1
            except Exception:
                pass
        if migrated_count > 0:
            self._reindex_collections()

    def manage_steam_deck_saves(self) -> None:
        if platform.system() != 'Linux':
            return
        try:
            home_dir = os.path.expanduser('~')
            if isinstance(self.app_state.game_mode, UndertaleGameMode):
                game_name = 'UNDERTALE'
            else:
                game_name = 'DELTARUNE'
            steam_app_id = self.app_state.game_mode.steam_id
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
                    self.feedback_manager.show_info('dialogs.backup', tr('dialogs.backup_created_for_steam_deck', backup_path=backup_path))
            os.symlink(proton_save_path, native_save_path)
            self.feedback_manager.show_info('dialogs.steam_deck_setup', tr('dialogs.steam_deck_compatibility_configured'))
        except Exception as e:
            logging.error(f'Steam Deck setup error: {e}')

    def _reindex_collections(self):
        cols = []
        rx = self.collection_regex()
        if not (self.app_state.save_path and os.path.isdir(self.app_state.save_path)):
            return
        for entry in os.listdir(self.app_state.save_path):
            m = rx.match(entry)
            if m and os.path.isdir(os.path.join(self.app_state.save_path, entry)):
                name = m.group(1)
                cols.append((entry, name))
        cols.sort(key=lambda x: x[0])
        for new_idx, (old_folder, name) in enumerate(cols):
            new_folder = f'{name}_{new_idx}'
            if old_folder != new_folder:
                try:
                    old_path = os.path.join(self.app_state.save_path, old_folder)
                    new_path = os.path.join(self.app_state.save_path, new_folder)
                    os.rename(old_path, new_path)
                except Exception:
                    pass

    def get_slot_data(self, chapter: int, slot: int, base_path: str) -> tuple[bool, str]:
        fp = os.path.join(base_path, f'filech{chapter}_{slot}')
        active = os.path.exists(fp) and os.path.getsize(fp) > 0
        if active:
            try:
                with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.read().splitlines()
                nickname = lines[0] if len(lines) > 0 else '???'
                currency = lines[10] if len(lines) > 10 else '0'
            except Exception:
                nickname, currency = ('???', '0')
            fin_idx = SAVE_SLOT_FINISH_MAP.get(slot, -1)
            fin_fp = os.path.join(base_path, f'filech{chapter}_{fin_idx}')
            finished = os.path.exists(fin_fp) and os.path.getsize(fin_fp) > 0
            status = tr('status.completed_save') if finished else tr('status.incomplete_save')
            text = tr('ui.save_info', nickname=nickname, currency=currency, status=status)
        else:
            text = tr('status.empty_save_slot')
        return (active, text)

    def refresh_save_slots_data(self, chapter: int) -> dict[int, tuple[bool, str]]:
        if not (self.app_state.save_path and os.path.isdir(self.app_state.save_path)):
            return {}
        idx = self.app_state.current_collection_idx
        base_path = self.get_collection_path(idx) or self.app_state.save_path
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
            os.makedirs(os.path.join(self.app_state.save_path, folder), exist_ok=False)
            return True
        except Exception as e:
            self.feedback_manager.show_error('errors.folder_creation_failed', error=str(e))
            return False

    def prompt_collection_name(self, default: str = 'Collection') -> Optional[str]:
        dlg = QDialog(self.parent_widget)
        dlg.setWindowTitle(tr('dialogs.new_collection'))
        v, e = (QVBoxLayout(dlg), QLineEdit())
        e.setMaxLength(20)
        e.setText(default)
        e.selectAll()
        v.addWidget(e)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        e.setFocus()
        return e.text().strip() or default if dlg.exec() == QDialog.DialogCode.Accepted else None

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
            os.rename(os.path.join(self.app_state.save_path, old_folder), os.path.join(self.app_state.save_path, new_folder))
            self.slots_updated.emit()
            return True
        except Exception as e:
            self.feedback_manager.show_error('errors.rename_failed', error=str(e))
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
            shutil.rmtree(os.path.join(self.app_state.save_path, folder))
            remaining = self.list_collections()
            for new_idx, f in enumerate(remaining):
                parts = f.rsplit('_', 1)
                cur_idx = int(parts[1])
                if cur_idx != new_idx:
                    new_folder = f'{parts[0]}_{new_idx}'
                    os.rename(os.path.join(self.app_state.save_path, f), os.path.join(self.app_state.save_path, new_folder))
            self.app_state.current_collection_idx = -1
            self.slots_updated.emit()
            return True
        except Exception as e:
            self.feedback_manager.show_error('errors.deletion_failed', error=str(e))
            return False

    def copy_between_storages(self, chapter: int, to_collection: bool, selected_slot: Optional[tuple[int, int]] = None):
        idx = self.app_state.current_collection_idx
        if idx == -1:
            return
        copy_all_chapters = False
        if selected_slot is None or selected_slot[0] != chapter:
            choice, ok = QInputDialog.getItem(self.parent_widget, tr('dialogs.copy_scope_title'), tr('dialogs.copy_scope_question'), [tr('dialogs.copy_current_chapter'), tr('dialogs.copy_all_chapters')], 0, False)
            if not ok:
                return
            copy_all_chapters = choice == tr('dialogs.copy_all_chapters')
        src_dir = self.app_state.save_path if to_collection else self.get_collection_path(idx)
        dst_dir = self.get_collection_path(idx) if to_collection else self.app_state.save_path
        if not src_dir or not dst_dir:
            return
        if selected_slot is None or selected_slot[0] != chapter:
            slot_indices = range(3)
        else:
            slot_indices = [selected_slot[1]]
        if copy_all_chapters:
            chapters_to_copy = range(1, 5)
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
                    finish_idx = SAVE_SLOT_FINISH_MAP.get(slot_idx, -1)
                    names = [f'filech{ch}_{slot_idx}', f'filech{ch}_{finish_idx}']
                    for _name in names:
                        src = os.path.join(src_dir, _name)
                        dst = os.path.join(dst_dir, _name)
                        if os.path.exists(src):
                            shutil.copy2(src, dst)
                        elif os.path.exists(dst):
                            os.remove(dst)
            self.slots_updated.emit()
            self.status_changed.emit(tr('status.copying_completed'), UI_COLORS['status_success'])
        except Exception as e:
            self.feedback_manager.show_error('errors.copy_failed', error=str(e))
            self.status_changed.emit(tr('status.copying_error'), UI_COLORS['status_error'])

    def action_show_save(self, chapter: int, slot: int):
        idx = self.app_state.current_collection_idx
        path = self.get_collection_path(idx)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def action_delete_save(self, chapter: int, slot: int) -> bool:
        idx = self.app_state.current_collection_idx
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
            self.feedback_manager.show_error('errors.error', str(e))
            return False

    def action_import_export(self, chapter: int, slot: int, is_import: bool) -> bool:
        idx = self.app_state.current_collection_idx
        base_cur = self.get_collection_path(idx)
        src_fp = os.path.join(base_cur, f'filech{chapter}_{slot}')
        choice, ok = QInputDialog.getItem(self.parent_widget, tr('dialogs.where_to') if not is_import else tr('dialogs.where_from'), tr('ui.select_storage'), [tr('dialogs.external_file') if is_import else tr('dialogs.external_folder'), tr('dialogs.additional_collection') if idx == -1 else tr('dialogs.main_slots')], 0, False)
        if not ok:
            return False
        if choice in [tr('dialogs.external_file'), tr('dialogs.external_folder')]:
            if is_import:
                fp, _ = QFileDialog.getOpenFileName(self.parent_widget, tr('ui.select_save_file'), '', f'filech{chapter}_*. (*)')
                if not fp:
                    return False
                if not re.fullmatch(f'filech{chapter}_[0-2]', os.path.basename(fp)):
                    self.feedback_manager.show_warning('errors.invalid_file', tr('errors.wrong_save_file'))
                    return False
                shutil.copy2(fp, src_fp)
                fin_idx = SAVE_SLOT_FINISH_MAP.get(slot, -1)
                fin_name = f'filech{chapter}_{fin_idx}'
                fin_src = os.path.join(os.path.dirname(fp), fin_name)
                fin_dst = os.path.join(base_cur, fin_name)
                if os.path.exists(fin_src):
                    shutil.copy2(fin_src, fin_dst)
            else:
                dir_ = QFileDialog.getExistingDirectory(self.parent_widget, tr('dialogs.export_save_location'))
                if not dir_:
                    return False
                if not os.path.exists(src_fp):
                    self.feedback_manager.show_warning('errors.no_save', tr('errors.empty_slot'))
                    return False
                shutil.copy2(src_fp, dir_)
                fin_idx = SAVE_SLOT_FINISH_MAP.get(slot, -1)
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
                target_base = os.path.join(self.app_state.save_path, sel)
            else:
                target_base = self.app_state.save_path
            src_main_fp = os.path.join(base_cur, f'filech{chapter}_{slot}')
            target_main_fp = os.path.join(target_base, f'filech{chapter}_{slot}')
            fin_idx = SAVE_SLOT_FINISH_MAP.get(slot, -1)
            fin_name = f'filech{chapter}_{fin_idx}'
            src_fin_fp = os.path.join(base_cur, fin_name)
            target_fin_fp = os.path.join(target_base, fin_name)
            if is_import:
                if not os.path.exists(target_main_fp):
                    self.feedback_manager.show_warning('errors.no_save', tr('errors.no_import_save'))
                    return False
                shutil.copy2(target_main_fp, src_main_fp)
                if os.path.exists(target_fin_fp):
                    shutil.copy2(target_fin_fp, src_fin_fp)
                elif os.path.exists(src_fin_fp):
                    os.remove(src_fin_fp)
            else:
                if not os.path.exists(src_main_fp):
                    self.feedback_manager.show_warning('errors.no_save', tr('errors.empty_slot'))
                    return False
                shutil.copy2(src_main_fp, target_main_fp)
                if os.path.exists(src_fin_fp):
                    shutil.copy2(src_fin_fp, target_fin_fp)
                elif os.path.exists(target_fin_fp):
                    os.remove(target_fin_fp)
        self.slots_updated.emit()
        return True

    def toggle_collection_view(self) -> bool:
        idx = self.app_state.current_collection_idx
        if idx == -1:
            cols = self.list_collections()
            if not cols and (not self.create_new_collection()):
                return False
            self.app_state.current_collection_idx = 0
        else:
            self.app_state.current_collection_idx = -1
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
        idx = self.app_state.current_collection_idx
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
        self.app_state.current_collection_idx = idx
        self.app_state.selected_slot = None
        self.slots_updated.emit()

    def get_collection_ui_state(self) -> dict:
        idx = self.app_state.current_collection_idx
        in_col = idx != -1
        cols = self.list_collections()
        collection_name = ''
        if in_col and 0 <= idx < len(cols):
            collection_name = cols[idx].rsplit('_', 1)[0]
        return {'in_collection': in_col, 'collection_name': collection_name, 'can_navigate_left': in_col and idx > 0, 'can_navigate_right': in_col, 'has_collections': len(cols) > 0}

    def prompt_for_save_collection_on_launch(self) -> Optional[int]:
        if not self.app_state.save_path:
            self.find_and_validate_save_path()
        if not is_valid_save_path(self.app_state.save_path):
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
        if collection_idx == -1 or not is_valid_save_path(self.app_state.save_path):
            return {}
        collection_path = self.get_collection_path(collection_idx)
        if not collection_path or not os.path.isdir(collection_path):
            return {}
        backup_info = {}
        main_save_path = self.app_state.save_path
        for chapter in range(1, 5):
            for slot in range(3):
                main_file = os.path.join(main_save_path, f'filech{chapter}_{slot}')
                col_file = os.path.join(collection_path, f'filech{chapter}_{slot}')
                if os.path.exists(main_file):
                    backup_file = main_file + '.deltahub_backup'
                    shutil.copy2(main_file, backup_file)
                    backup_info[main_file] = backup_file
                if os.path.exists(col_file):
                    shutil.copy2(col_file, main_file)
                elif os.path.exists(main_file):
                    os.remove(main_file)
                fin_idx = SAVE_SLOT_FINISH_MAP.get(slot, -1)
                if fin_idx != -1:
                    main_fin = os.path.join(main_save_path, f'filech{chapter}_{fin_idx}')
                    col_fin = os.path.join(collection_path, f'filech{chapter}_{fin_idx}')
                    if os.path.exists(main_fin):
                        backup_fin = main_fin + '.deltahub_backup'
                        shutil.copy2(main_fin, backup_fin)
                        backup_info[main_fin] = backup_fin
                    if os.path.exists(col_fin):
                        shutil.copy2(col_fin, main_fin)
                    elif os.path.exists(main_fin):
                        os.remove(main_fin)
        return backup_info

    def restore_original_saves_after_launch(self, backup_info: dict):
        if not backup_info:
            return
        for original_file, backup_file in backup_info.items():
            if os.path.exists(backup_file):
                if os.path.exists(original_file):
                    os.remove(original_file)
                shutil.move(backup_file, original_file)
        for backup_file in backup_info.values():
            if os.path.exists(backup_file):
                os.remove(backup_file)
