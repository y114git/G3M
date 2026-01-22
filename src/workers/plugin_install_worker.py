import os
import shutil
import logging
import tempfile
from managers.localization_manager import tr
from utils.network_utils import get_session, download_file
from config.constants import UI_COLORS
from workers.base_install_worker import BaseInstallWorker


class PluginInstallWorker(BaseInstallWorker):

    def __init__(self, archive_path: str, plugins_dir: str, plugin_manager, parent=None):
        super().__init__(parent)
        self.archive_path = archive_path
        self.plugins_dir = plugins_dir
        self.plugin_manager = plugin_manager
        self._cancelled = False
        self._session = None

    def cancel(self):
        self._cancelled = True
        if self._session:
            self._safe_close(self._session, 'session')

    def _check_archive_has_plugin_init_py(self, archive_path: str) -> bool:
        from utils.archive_utils import ArchiveExtractor, UnrarMissingError
        try:
            return ArchiveExtractor.check_archive_has_file(archive_path, 'plugin_init.py')
        except Exception as e:
            if 'File is not a zip file' in str(e) or isinstance(e, UnrarMissingError):
                if not self.wait_for_unrar_install():
                    logging.error('PluginInstallWorker: User declined UnRAR installation')
                    return False
                try:
                    return ArchiveExtractor.check_archive_has_file(archive_path, 'plugin_init.py')
                except Exception as retry_e:
                    logging.error(f'PluginInstallWorker: Error checking archive: {retry_e}')
                    return False
            else:
                logging.error(f'PluginInstallWorker: Error checking archive: {e}')
                return False

    def _download_archive(self, url: str, target_path: str) -> bool:
        try:
            self.status.emit(tr('plugins.downloading_plugin'), UI_COLORS['status_warning'])
            session = get_session()
            self._session = session
            total_size = self._get_content_length(session, url)
            downloaded_ref = [0]
            progress_callback = self._make_download_progress_callback(tr('plugins.downloading_plugin'), total_size, downloaded_ref)
            download_file(session, url, target_path, progress_callback=progress_callback, total_size=total_size, downloaded_ref=downloaded_ref, cancel_check=lambda: self._cancelled)
            self.progress.emit(100)
            return True
        except Exception as e:
            logging.error(f'PluginInstallWorker: Download failed: {e}', exc_info=True)
            return False

    def run(self):
        try:
            archive_is_url = self.archive_path.startswith('http://') or self.archive_path.startswith('https://')
            if archive_is_url:
                url = self.archive_path
                with tempfile.TemporaryDirectory(prefix='dh-plugin-check-') as temp_dir:
                    from utils.archive_utils import get_file_extension_from_url
                    file_ext = get_file_extension_from_url(url)
                    temp_archive_name = f'temp_plugin_{os.getpid()}{file_ext}'
                    temp_archive_path = os.path.join(temp_dir, temp_archive_name)
                    try:
                        if not self._download_archive(url, temp_archive_path):
                            self.finished.emit(False, tr('plugins.download_failed'))
                            return
                    except Exception as e:
                        self.finished.emit(False, tr('plugins.download_error', error=str(e)))
                        return
                    self.status.emit(tr('plugins.validating_plugin'), UI_COLORS['status_warning'])
                    if not self._check_archive_has_plugin_init_py(temp_archive_path):
                        self.finished.emit(False, tr('plugins.invalid_plugin_archive'))
                        return
                    archive_name = os.path.basename(url.split('?')[0].split('/')[-1])
                    if not archive_name or '.' not in archive_name:
                        archive_name = 'plugin.zip'
                    target_archive_path = os.path.join(self.plugins_dir, archive_name)
                    try:
                        shutil.copy2(temp_archive_path, target_archive_path)
                    except Exception as e:
                        self.finished.emit(False, tr('plugins.copy_error', error=str(e)))
                        return
            else:
                if not os.path.exists(self.archive_path):
                    self.finished.emit(False, tr('plugins.archive_not_found'))
                    return
                self.status.emit(tr('plugins.validating_plugin'), UI_COLORS['status_warning'])
                if not self._check_archive_has_plugin_init_py(self.archive_path):
                    self.finished.emit(False, tr('plugins.invalid_plugin_archive'))
                    return
                archive_name = os.path.basename(self.archive_path)
                target_archive_path = os.path.join(self.plugins_dir, archive_name)
                if os.path.abspath(self.archive_path) == os.path.abspath(target_archive_path):
                    self.status.emit(tr('plugins.plugin_installed'), 'success')
                    self.finished.emit(True, tr('plugins.plugin_installed_success'))
                    return
                try:
                    shutil.copy2(self.archive_path, target_archive_path)
                except Exception as e:
                    self.finished.emit(False, tr('plugins.copy_error', error=str(e)))
                    return
            self.status.emit(tr('plugins.plugin_installed'), 'success')
            self.finished.emit(True, tr('plugins.plugin_installed_success'))
        except Exception as e:
            logging.error(f'PluginInstallWorker: Installation failed: {e}', exc_info=True)
            self.finished.emit(False, tr('plugins.installation_error', error=str(e)))
