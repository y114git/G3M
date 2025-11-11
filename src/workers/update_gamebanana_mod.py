import os
import json
import shutil
import logging
from PyQt6.QtCore import QThread, pyqtSignal
from config.constants import UI_COLORS
from managers.localization_manager import tr
from models.mod_models import ModInfo
logger = logging.getLogger(__name__)


class UpdateGameBananaModThread(QThread):
    status = pyqtSignal(str, str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)

    def __init__(self, main_window, mod_info: ModInfo, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.mod_info = mod_info
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        try:
            self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])
        except Exception as e:
            logger.warning(f'UpdateGameBananaModThread.cancel: emit failed: {e}')

    def run(self):
        try:
            mod_key = self.mod_info.key
            mods_dir = self.main_window.app_state.mods_dir
            mod_manager = getattr(self.main_window, 'mod_manager', None)
            if mod_manager:
                mod_dir = mod_manager.get_mod_folder_path(mod_key)
            else:
                mod_dir = None
                if os.path.exists(mods_dir):
                    for folder_name in os.listdir(mods_dir):
                        folder_path = os.path.join(mods_dir, folder_name)
                        if os.path.isdir(folder_path):
                            config_path = os.path.join(folder_path, 'mod_config.json')
                            old_config_path = os.path.join(folder_path, 'config.json')
                            if os.path.exists(config_path):
                                try:
                                    with open(config_path, 'r', encoding='utf-8') as f:
                                        config_data = json.load(f)
                                    if config_data.get('mod_key') == mod_key:
                                        mod_dir = folder_path
                                        break
                                except Exception:
                                    continue
                            elif os.path.exists(old_config_path):
                                try:
                                    import shutil
                                    shutil.move(old_config_path, config_path)
                                    logger.info(f'Migrated mod config.json to mod_config.json in {folder_name}')
                                    with open(config_path, 'r', encoding='utf-8') as f:
                                        config_data = json.load(f)
                                    if config_data.get('mod_key') == mod_key:
                                        mod_dir = folder_path
                                        break
                                except Exception:
                                    continue
            if not mod_dir or not os.path.exists(mod_dir):
                raise ValueError(tr('errors.mod_not_installed', mod_name=self.mod_info.name))
            backup_dir = None
            try:
                backup_dir = f'{mod_dir}.backup'
                if os.path.exists(backup_dir):
                    shutil.rmtree(backup_dir)
                shutil.copytree(mod_dir, backup_dir)
            except Exception as e:
                logger.warning(f'Failed to create backup: {e}')
            try:
                shutil.rmtree(mod_dir)
            except Exception as e:
                logger.error(f'Failed to remove old mod directory: {e}')
                raise
            self.status.emit(tr('status.downloading_update'), UI_COLORS['status_info'])
            from workers.install_gamebanana_mod import InstallGameBananaModThread
            installer = InstallGameBananaModThread(self.main_window, self.mod_info)
            install_result = [False, '']

            def on_install_finished(success, message):
                install_result[0] = success
                install_result[1] = message
            installer.finished.connect(on_install_finished)
            installer.run()
            if install_result[0]:
                if mod_manager:
                    mod_dir_new = mod_manager.get_mod_folder_path(mod_key)
                else:
                    mod_dir_new = None
                    if os.path.exists(mods_dir):
                        for folder_name in os.listdir(mods_dir):
                            folder_path = os.path.join(mods_dir, folder_name)
                            if os.path.isdir(folder_path):
                                config_path = os.path.join(folder_path, 'mod_config.json')
                                old_config_path = os.path.join(folder_path, 'config.json')
                                if os.path.exists(config_path):
                                    try:
                                        with open(config_path, 'r', encoding='utf-8') as f:
                                            config_data = json.load(f)
                                        if config_data.get('mod_key') == mod_key:
                                            mod_dir_new = folder_path
                                            break
                                    except Exception:
                                        continue
                                elif os.path.exists(old_config_path):
                                    try:
                                        import shutil
                                        shutil.move(old_config_path, config_path)
                                        logger.info(f'Migrated mod config.json to mod_config.json in {folder_name}')
                                        with open(config_path, 'r', encoding='utf-8') as f:
                                            config_data = json.load(f)
                                        if config_data.get('mod_key') == mod_key:
                                            mod_dir_new = folder_path
                                            break
                                    except Exception:
                                        continue
                if mod_dir_new and os.path.exists(mod_dir_new):
                    if backup_dir and os.path.exists(backup_dir):
                        try:
                            shutil.rmtree(backup_dir)
                        except Exception as e:
                            logger.debug(f'Failed to cleanup backup: {e}')
                    mod_name = os.path.basename(mod_dir_new)
                    self.finished.emit(True, tr('status.update_complete_success', mod_name=mod_name))
                else:
                    if backup_dir and os.path.exists(backup_dir):
                        try:
                            shutil.move(backup_dir, mod_dir)
                        except Exception as e:
                            logger.error(f'Failed to restore backup: {e}')
                    raise ValueError(tr('errors.update_failed'))
            elif backup_dir and os.path.exists(backup_dir):
                try:
                    shutil.move(backup_dir, mod_dir)
                    raise ValueError(f"{tr('errors.update_failed_restored')}: {install_result[1]}")
                except Exception as e:
                    logger.error(f'Failed to restore backup: {e}')
                    raise ValueError(f"{tr('errors.update_failed')}: {install_result[1]}")
            else:
                raise ValueError(f"{tr('errors.update_failed')}: {install_result[1]}")
        except Exception as e:
            logger.error(f'Error updating GameBanana mod: {e}', exc_info=True)
            self.finished.emit(False, str(e))
