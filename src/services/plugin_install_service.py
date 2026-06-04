"""Plugin archive install/update/delete service."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile

from services.plugin_support import (
    PluginValidationError,
    load_manifest,
    safe_extract_zip,
)
from utils.archive_utils import unwrap_single_directory_chain

logger = logging.getLogger(__name__)


class PluginInstallService:
    """Validates and installs plugin zip archives into G3M/plugins."""

    def __init__(self, plugin_state_service, plugin_runtime_service, plugins_dir: str) -> None:
        self.plugin_state_service = plugin_state_service
        self.plugin_runtime_service = plugin_runtime_service
        self.plugins_dir = plugins_dir

    def install_archive(
        self,
        archive_path: str,
        *,
        source: str,
        catalog_plugin_version: str = "",
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="g3m_plugin_") as temp_dir:
            safe_extract_zip(archive_path, temp_dir)
            return self._install_from_source_dir(
                temp_dir, source=source, catalog_plugin_version=catalog_plugin_version
            )

    def install_path(
        self,
        source_path: str,
        *,
        source: str,
        catalog_plugin_version: str = "",
    ) -> str:
        if os.path.isdir(source_path):
            return self._install_from_source_dir(
                source_path, source=source, catalog_plugin_version=catalog_plugin_version
            )
        return self.install_archive(
            source_path,
            source=source,
            catalog_plugin_version=catalog_plugin_version,
        )

    def _install_from_source_dir(
        self,
        source_dir: str,
        *,
        source: str,
        catalog_plugin_version: str = "",
    ) -> str:
        source_dir = unwrap_single_directory_chain(source_dir)
        manifest_path = os.path.join(source_dir, "plugin_config.json")
        manifest = load_manifest(manifest_path)
        target_dir = os.path.join(self.plugins_dir, manifest.id)
        temp_target = f"{target_dir}.tmp"
        shutil.rmtree(temp_target, ignore_errors=True)
        os.makedirs(temp_target, exist_ok=True)
        backup_dir = f"{target_dir}.bak"
        shutil.rmtree(backup_dir, ignore_errors=True)
        try:
            if os.path.isdir(target_dir):
                os.replace(target_dir, backup_dir)
            shutil.copytree(source_dir, temp_target, dirs_exist_ok=True)
            os.replace(temp_target, target_dir)
        except Exception as e:
            if os.path.isdir(backup_dir) and not os.path.isdir(target_dir):
                try:
                    os.replace(backup_dir, target_dir)
                except OSError:
                    logger.error(
                        "PluginInstallService: failed to restore backup for %s",
                        target_dir,
                    )
            raise PluginValidationError(f"installation_failed: {e}") from e
        finally:
            shutil.rmtree(backup_dir, ignore_errors=True)
            shutil.rmtree(temp_target, ignore_errors=True)
        self.plugin_state_service.set_install_meta(
            manifest.id,
            source=source,
            installed_version=manifest.version,
            catalog_plugin_version=catalog_plugin_version,
            local=source == "manual",
        )
        self.plugin_state_service.set_enabled(manifest.id, False)
        return manifest.id

    def delete_plugin(self, plugin_id: str) -> None:
        shutil.rmtree(os.path.join(self.plugins_dir, plugin_id), ignore_errors=True)
        self.plugin_state_service.clear_plugin(plugin_id)
