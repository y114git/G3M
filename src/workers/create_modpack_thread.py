import logging
import os
import json
import uuid
import time
import platform
import shutil
from typing import Dict, List, Any
from PyQt6.QtCore import QThread, pyqtSignal
from managers.multi_mod_merger import MultiModMerger
from managers.localization_manager import tr


class CreateModpackThread(QThread):
    progress_update = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str)
    finished = pyqtSignal(bool)

    def __init__(self, chapter_mods: Dict[int, List[Any]], modpack_name: str, modpack_dir: str, app_state, mod_manager, parent=None, fast_merge: bool = False):
        super().__init__(parent)
        self.chapter_mods = chapter_mods
        self.modpack_name = modpack_name
        self.modpack_dir = modpack_dir
        self.app_state = app_state
        self.mod_manager = mod_manager
        self.fast_merge = fast_merge
        self.merger = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()
        if self.merger:
            self.merger._cancelled = True
        self.status_update.emit('Operation cancelled', 'error')

    def run(self):
        try:
            if self.isInterruptionRequested() or self._cancelled:
                self.finished.emit(False)
                return
            self.merger = MultiModMerger(self.app_state, self.mod_manager, None)
            self.merger.progress_update.connect(self.progress_update.emit)
            self.merger.status_update.connect(self.status_update.emit)
            self.merger._cancelled = False
            if self.isInterruptionRequested() or self._cancelled:
                self.finished.emit(False)
                return
            success = self.merger.process_mod_merge(self.chapter_mods, is_modpack=True, modpack_dir=self.modpack_dir, fast_merge=self.fast_merge)
            if self.isInterruptionRequested() or self._cancelled:
                self.merger._cancelled = True
                success = False
                if os.path.exists(self.modpack_dir):
                    try:
                        shutil.rmtree(self.modpack_dir, ignore_errors=True)
                        logging.info(f'Cancelled modpack creation, removed directory: {self.modpack_dir}')
                    except Exception as e:
                        logging.error(f'Failed to remove cancelled modpack directory: {e}')
            if success and (not (self.isInterruptionRequested() or self._cancelled)):
                self._create_config_json()
            self.finished.emit(success)
        except Exception as e:
            logging.error(f'CreateModpackThread failed: {e}', exc_info=True)
            self.status_update.emit(f'Modpack creation failed: {str(e)}', 'error')
            self.finished.emit(False)
        finally:
            if self.merger:
                self.merger.cleanup(force=True)

    def _create_config_json(self):
        try:
            files_data = {}
            for chapter_id, mods_list in self.chapter_mods.items():
                if chapter_id == -1:
                    chapter_key = 'demo'
                elif chapter_id == 0:
                    chapter_key = '0'
                else:
                    chapter_key = str(chapter_id)
                chapter_folder_name = {-1: 'demo', 0: 'chapter_0'}.get(chapter_id, f'chapter_{chapter_id}')
                chapter_modpack_dir = os.path.join(self.modpack_dir, chapter_folder_name)
                if not os.path.exists(chapter_modpack_dir):
                    continue
                file_info = {}
                system = platform.system()
                if system == 'Darwin':
                    data_file = os.path.join(chapter_modpack_dir, 'game.ios')
                    if os.path.exists(data_file):
                        file_info['data_file_url'] = 'game.ios'
                else:
                    data_file = os.path.join(chapter_modpack_dir, 'data.win')
                    if os.path.exists(data_file):
                        file_info['data_file_url'] = 'data.win'
                if file_info:
                    file_info['data_file_version'] = '1.0.0'
                    files_data[chapter_key] = file_info
            mod_key = f'local_{uuid.uuid4().hex[:12]}'
            config_data = {'is_local_mod': True, 'mod_key': mod_key, 'name': self.modpack_name, 'author': tr('defaults.multiple_authors'), 'version': '1.0.0', 'tagline': tr('defaults.no_short_description'), 'game_version': tr('defaults.not_specified'), 'modgame': 'deltarune', 'files': files_data, 'tags': [], 'created_date': time.strftime('%d.%m.%y %H:%M'), 'is_available_on_server': False}
            config_path = os.path.join(self.modpack_dir, 'mod_config.json')
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
            logging.info(f'Created mod_config.json for modpack: {self.modpack_name}')
        except Exception as e:
            logging.error(f'Failed to create mod_config.json: {e}', exc_info=True)
            raise
