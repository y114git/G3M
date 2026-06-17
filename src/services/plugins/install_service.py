"""Plugin archive install/update/delete service."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from contextlib import suppress

from services.plugins.support import (
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
        was_enabled = self.plugin_state_service.is_enabled(manifest.id)
        is_update = os.path.isdir(target_dir)
        temp_target = f"{target_dir}.tmp"
        try:
            if is_update and was_enabled:
                self.plugin_runtime_service.disable_plugin(manifest.id, persist=False)
            if is_update:
                self._merge_update(source_dir, target_dir)
            else:
                shutil.rmtree(temp_target, ignore_errors=True)
                shutil.copytree(source_dir, temp_target, dirs_exist_ok=True)
                os.replace(temp_target, target_dir)
        except Exception as e:
            raise PluginValidationError(f"installation_failed: {e}") from e
        finally:
            shutil.rmtree(temp_target, ignore_errors=True)
        self.plugin_state_service.set_install_meta(
            manifest.id,
            source=source,
            installed_version=manifest.version,
            catalog_plugin_version=catalog_plugin_version,
            local=source == "manual",
        )
        self.plugin_state_service.set_enabled(manifest.id, was_enabled)
        if is_update and was_enabled:
            self.plugin_runtime_service.scan_installed_plugins(resolve_catalog=False)
            enabled, error = self.plugin_runtime_service.enable_plugin(manifest.id)
            if not enabled:
                logger.warning(
                    "PluginInstallService: failed to re-enable %s after update: %s",
                    manifest.id,
                    error,
                )
        return manifest.id

    def delete_plugin(self, plugin_id: str) -> None:
        shutil.rmtree(os.path.join(self.plugins_dir, plugin_id), ignore_errors=True)
        self.plugin_state_service.clear_plugin(plugin_id)

    def _merge_update(self, source_dir: str, target_dir: str) -> None:
        """Replace packaged files while keeping files created by the plugin."""
        backup_root = tempfile.mkdtemp(prefix="g3m_plugin_update_backup_")
        replaced: list[tuple[str, str]] = []
        created_files: list[str] = []
        created_dirs: list[str] = []
        try:
            for root, dirs, files in os.walk(source_dir):
                relative_root = os.path.relpath(root, source_dir)
                target_root = (
                    target_dir
                    if relative_root == "."
                    else os.path.join(target_dir, relative_root)
                )
                if not os.path.isdir(target_root):
                    os.makedirs(target_root, exist_ok=True)
                    created_dirs.append(target_root)
                for dir_name in dirs:
                    target_child_dir = os.path.join(target_root, dir_name)
                    if not os.path.isdir(target_child_dir):
                        os.makedirs(target_child_dir, exist_ok=True)
                        created_dirs.append(target_child_dir)
                for file_name in files:
                    source_file = os.path.join(root, file_name)
                    target_file = os.path.join(target_root, file_name)
                    backup_file = os.path.join(
                        backup_root,
                        os.path.relpath(target_file, target_dir),
                    )
                    os.makedirs(os.path.dirname(target_file), exist_ok=True)
                    temp_file = f"{target_file}.g3m_update_tmp"
                    if os.path.exists(target_file):
                        os.makedirs(os.path.dirname(backup_file), exist_ok=True)
                        shutil.copy2(target_file, backup_file)
                        replaced.append((target_file, backup_file))
                    else:
                        created_files.append(target_file)
                    shutil.copy2(source_file, temp_file)
                    os.replace(temp_file, target_file)
        except Exception:
            self._rollback_merge_update(replaced, created_files, created_dirs)
            raise
        finally:
            shutil.rmtree(backup_root, ignore_errors=True)

    def _rollback_merge_update(
        self,
        replaced: list[tuple[str, str]],
        created_files: list[str],
        created_dirs: list[str],
    ) -> None:
        for path in reversed(created_files):
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                logger.warning("PluginInstallService: failed to remove new file %s", path)
        for target_file, backup_file in reversed(replaced):
            try:
                os.replace(backup_file, target_file)
            except OSError:
                logger.error(
                    "PluginInstallService: failed to restore plugin file %s",
                    target_file,
                    exc_info=True,
                )
        for path in reversed(created_dirs):
            with suppress(OSError):
                os.rmdir(path)
