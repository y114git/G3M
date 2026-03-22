"""Plugin installation worker.

This module provides a worker thread for installing plugins from files or URLs.
"""

import logging
import os
import shutil
import tempfile

from config.constants import UI_COLORS
from services.localization_service import tr
from workers.base_install_worker import BaseInstallWorker

logger = logging.getLogger(__name__)


class PluginInstallWorker(BaseInstallWorker):
    def __init__(
        self, archive_path: str, plugins_dir: str, plugin_service, parent=None
    ) -> None:
        super().__init__(parent)
        self.archive_path = archive_path
        self.plugins_dir = plugins_dir
        self.plugin_service = plugin_service

    def _check_archive_has_plugin_init_py(self, archive_path: str) -> bool:
        from utils.archive_utils import ArchiveExtractor

        try:
            return ArchiveExtractor.check_archive_has_file(
                archive_path, "plugin_init.py"
            )
        except Exception as e:
            logging.error(f"PluginInstallWorker: Error checking archive: {e}")
            return False

    def _download_archive(self, url: str, target_path: str) -> bool:
        return self._download_archive_base(
            url, target_path, tr("plugins.downloading_plugin")
        )

    def run(self):
        try:
            archive_is_url = self.archive_path.startswith(
                "http://"
            ) or self.archive_path.startswith("https://")
            if archive_is_url:
                url = self.archive_path
                with tempfile.TemporaryDirectory(prefix="dh-plugin-check-") as temp_dir:
                    from utils.archive_utils import get_file_extension_from_url

                    file_ext = get_file_extension_from_url(url)
                    temp_archive_name = f"temp_plugin_{os.getpid()}{file_ext}"
                    temp_archive_path = os.path.join(temp_dir, temp_archive_name)
                    try:
                        if not self._download_archive(url, temp_archive_path):
                            self.finished.emit(False, tr("plugins.download_failed"))
                            return
                    except Exception as e:
                        self.finished.emit(
                            False, tr("plugins.download_error", error=str(e))
                        )
                        return
                    self.status.emit(
                        tr("plugins.validating_plugin"), UI_COLORS["status_warning"]
                    )
                    if not self._check_archive_has_plugin_init_py(temp_archive_path):
                        self.finished.emit(False, tr("plugins.invalid_plugin_archive"))
                        return
                    archive_name = os.path.basename(url.split("?")[0].split("/")[-1])
                    if not archive_name or "." not in archive_name:
                        archive_name = "plugin.zip"
                    target_archive_path = os.path.join(self.plugins_dir, archive_name)
                    try:
                        shutil.copy2(temp_archive_path, target_archive_path)
                    except Exception as e:
                        self.finished.emit(
                            False, tr("plugins.copy_error", error=str(e))
                        )
                        return
            else:
                if not os.path.exists(self.archive_path):
                    self.finished.emit(False, tr("plugins.archive_not_found"))
                    return
                self.status.emit(
                    tr("plugins.validating_plugin"), UI_COLORS["status_warning"]
                )
                if not self._check_archive_has_plugin_init_py(self.archive_path):
                    self.finished.emit(False, tr("plugins.invalid_plugin_archive"))
                    return
                archive_name = os.path.basename(self.archive_path)
                target_archive_path = os.path.join(self.plugins_dir, archive_name)
                if os.path.abspath(self.archive_path) == os.path.abspath(
                    target_archive_path
                ):
                    self.status.emit(tr("plugins.plugin_installed"), "success")
                    self.finished.emit(True, tr("plugins.plugin_installed_success"))
                    return
                try:
                    shutil.copy2(self.archive_path, target_archive_path)
                except Exception as e:
                    self.finished.emit(False, tr("plugins.copy_error", error=str(e)))
                    return
            self.status.emit(tr("plugins.plugin_installed"), "success")
            self.finished.emit(True, tr("plugins.plugin_installed_success"))
        except Exception as e:
            logging.error(
                f"PluginInstallWorker: Installation failed: {e}", exc_info=True
            )
            self.finished.emit(False, tr("plugins.installation_error", error=str(e)))
