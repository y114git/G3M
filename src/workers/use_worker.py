"""Worker thread for the Use phase of the Downloads system."""

import logging
import os
import shutil
import tempfile

from PyQt6.QtCore import QThread, pyqtSignal

from models.download_models import TargetKind
from utils.process_utils import format_filesystem_error, format_plugin_error

logger = logging.getLogger(__name__)


class UseWorker(QThread):
    use_finished = pyqtSignal(str, bool, bool, str)

    def __init__(
        self,
        record_id: str,
        file_path: str,
        target_kind: TargetKind,
        mods_dir: str,
        metadata: dict,
        plugin_install_service=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._record_id = record_id
        self._file_path = file_path
        self._target_kind = target_kind
        self._mods_dir = mods_dir
        self._metadata = metadata or {}
        self._plugin_install_service = plugin_install_service
        self._cancelled = False

    def _safe_finish(
        self, success: bool, needs_manual: bool, message: str
    ) -> None:
        try:
            self.use_finished.emit(
                self._record_id,
                success,
                needs_manual,
                message,
            )
        except Exception as e:
            logger.warning("UseWorker: failed to emit use_finished: %s", e, exc_info=True)

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            if self._target_kind == TargetKind.MOD:
                self._use_mod()
            elif self._target_kind == TargetKind.PLUGIN:
                self._use_plugin()
            else:
                self._safe_finish(False, False, f"Unsupported target_kind: {self._target_kind}")
        except Exception as e:
            logger.error("UseWorker: %s", e, exc_info=True)
            self._safe_finish(False, False, format_filesystem_error(e, path=self._file_path))

    def _use_mod(self):
        if not os.path.exists(self._file_path):
            self._safe_finish(
                False,
                False,
                format_filesystem_error(
                    FileNotFoundError(self._file_path), path=self._file_path
                ),
            )
            return

        extract_dir = tempfile.mkdtemp(prefix="g3m_use_")
        try:
            self._extract(extract_dir)
            if self._cancelled:
                self._safe_finish(False, False, "cancelled")
                return

            content_path = self._resolve_content_root(extract_dir)
            gb_metadata = self._build_gb_metadata()

            from utils.file_utils import has_deltamod_info_file

            files_in_root = os.listdir(content_path)

            from workers.install.helpers_install import find_mod_config

            if has_deltamod_info_file(files_in_root):
                success = self._install_via_deltamod(content_path, gb_metadata)
            elif find_mod_config(content_path):
                success = self._install_g3m_mod(content_path, gb_metadata)
            elif self._is_afom_archive(extract_dir, gb_metadata):
                success = self._install_afom_archive(extract_dir, gb_metadata)
            elif self._is_frickbears3_addon_archive(extract_dir, gb_metadata):
                success = self._install_frickbears3_addon_archive(extract_dir, gb_metadata)
            elif gb_metadata:
                success = self._install_via_gamebanana_converter(gb_metadata)
            else:
                success = False

            if not success:
                self._safe_finish(False, True, "")
                return
            self._safe_finish(True, False, "")
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

    def _use_plugin(self):
        if not self._plugin_install_service:
            self._safe_finish(False, False, "Plugin installer is not available")
            return
        if not os.path.exists(self._file_path):
            self._safe_finish(
                False,
                False,
                format_filesystem_error(
                    FileNotFoundError(self._file_path), path=self._file_path
                ),
            )
            return
        if self._cancelled:
            self._safe_finish(False, True, "")
            return
        try:
            self._plugin_install_service.install_archive(
                self._file_path,
                source=str(self._metadata.get("source", "catalog")),
                catalog_plugin_version=str(
                    self._metadata.get("catalog_plugin_version", "")
                ),
            )
            try:
                if os.path.exists(self._file_path):
                    os.remove(self._file_path)
            except Exception as cleanup_error:
                logger.debug(
                    "UseWorker: failed to remove consumed plugin archive %s: %s",
                    self._file_path,
                    cleanup_error,
                    exc_info=True,
                )
            self._safe_finish(True, False, "")
        except Exception as e:
            logger.error("UseWorker: plugin install failed: %s", e, exc_info=True)
            self._safe_finish(
                False,
                False,
                format_plugin_error(
                    e,
                    plugin_id=str(self._metadata.get("plugin_id", "") or ""),
                    details=self._file_path,
                ),
            )

    def _extract(self, target_dir: str):
        from utils.archive_utils import extract_archive

        extract_archive(self._file_path, target_dir)

    @staticmethod
    def _resolve_content_root(extract_dir: str) -> str:
        from utils.archive_utils import unwrap_single_directory_chain

        return unwrap_single_directory_chain(extract_dir)

    def _build_gb_metadata(self) -> dict:
        if not self._metadata.get("gb_mod_id"):
            return {}
        return {
            "mod_id": self._metadata["gb_mod_id"],
            "item_type": self._metadata.get("item_type", "mod"),
            "name": self._metadata.get("name"),
            "author": self._metadata.get("author"),
            "version": self._metadata.get("version"),
            "description": self._metadata.get("description"),
            "file_name": self._metadata.get("file_name"),
            "homepage": self._metadata.get("homepage") or self._metadata.get("profile_url"),
            "icon": self._metadata.get("icon"),
            "tags": self._metadata.get("tags") or [],
            "category": self._metadata.get("category"),
            "game": self._metadata.get("game", "deltarune"),
        }

    def _install_via_deltamod(self, content_path: str, gb_metadata: dict) -> bool:
        try:
            from adapters.deltamod_adapter import DeltamodConverter

            converter = DeltamodConverter(
                content_path, self._mods_dir, gb_metadata or None
            )
            result = converter.convert()
            if result and gb_metadata and gb_metadata.get("mod_id"):
                self._update_config_id(result, gb_metadata)
            return bool(result)
        except Exception as e:
            logger.error("UseWorker: deltamod conversion failed: %s", e, exc_info=True)
            return False

    def _install_via_gamebanana_converter(self, gb_metadata: dict) -> bool:
        try:
            from adapters.gamebanana_converter import GameBananaConverter

            converter = GameBananaConverter(
                self._file_path, self._mods_dir, gb_metadata
            )
            result = converter.convert()
            return bool(result)
        except Exception as e:
            logger.error("UseWorker: GB converter failed: %s", e, exc_info=True)
            return False

    def _install_g3m_mod(self, content_path: str, gb_metadata: dict) -> bool:
        try:
            from config.config import MOD_CONFIG_FILENAME
            from utils.file_utils import sanitize_filename
            from workers.install.helpers_install import (
                find_mod_config,
                load_mod_config,
                normalize_mod_id,
                save_mod_config,
            )

            mod_config_path = find_mod_config(content_path)
            if not mod_config_path:
                logger.warning(
                    "UseWorker: No mod_config.json found, treating as needs_manual"
                )
                return False

            config_data = load_mod_config(mod_config_path)
            if not config_data:
                return False

            normalize_mod_id(config_data)
            mod_name = config_data.get("name", "imported_mod")
            folder_name = sanitize_filename(mod_name)
            target_mod_dir = os.path.join(self._mods_dir, folder_name)
            counter = 1
            while os.path.exists(target_mod_dir):
                target_mod_dir = os.path.join(
                    self._mods_dir, f"{folder_name}_{counter}"
                )
                counter += 1
            os.makedirs(target_mod_dir, exist_ok=True)

            for item in os.listdir(content_path):
                src = os.path.join(content_path, item)
                dst = os.path.join(target_mod_dir, item)
                if os.path.islink(src):
                    link_target = os.path.realpath(src)
                    if not link_target.startswith(
                        os.path.realpath(content_path) + os.sep
                    ):
                        logger.warning(
                            "UseWorker: skipping symlink escaping extraction root: %s",
                            src,
                        )
                        continue
                    if os.path.exists(dst) or os.path.islink(dst):
                        os.remove(dst)
                    os.symlink(os.readlink(src), dst)
                elif os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst, symlinks=True)
                else:
                    shutil.copy2(src, dst)

            if gb_metadata and gb_metadata.get("mod_id"):
                self._apply_gb_metadata(config_data, gb_metadata)

            target_config_path = os.path.join(target_mod_dir, MOD_CONFIG_FILENAME)
            save_mod_config(target_config_path, config_data, indent=4)
            return True
        except Exception as e:
            logger.error("UseWorker: g3m mod install failed: %s", e, exc_info=True)
            return False

    def _is_afom_archive(self, extract_dir: str, gb_metadata: dict) -> bool:
        game = str((gb_metadata or {}).get("game") or self._metadata.get("game") or "").strip().lower()
        if game and game != "pizzatower":
            return False
        try:
            from services.pizza_tower_afom_service import PizzaTowerAFOMService

            inspection = PizzaTowerAFOMService().inspect_extracted_archive(extract_dir)
            return inspection.eligible
        except Exception as e:
            logger.debug("UseWorker: AFOM inspection failed: %s", e, exc_info=True)
            return False

    def _is_frickbears3_addon_archive(self, extract_dir: str, gb_metadata: dict) -> bool:
        game = str((gb_metadata or {}).get("game") or self._metadata.get("game") or "").strip().lower()
        if game and game != "frickbears3":
            return False
        try:
            from services.frickbears3_addons_service import Frickbears3AddonsService

            inspection = Frickbears3AddonsService().inspect_extracted_archive(extract_dir)
            return inspection.eligible
        except Exception as e:
            logger.debug("UseWorker: FRICKBEARS3 addon inspection failed: %s", e, exc_info=True)
            return False

    def _install_afom_archive(self, extract_dir: str, gb_metadata: dict) -> bool:
        try:
            from services.pizza_tower_afom_service import PizzaTowerAFOMService

            result = PizzaTowerAFOMService().convert_extracted_archive(
                extract_dir,
                self._mods_dir,
                source_file_path=self._file_path,
                gamebanana_metadata=gb_metadata or None,
            )
            return bool(result)
        except Exception as e:
            logger.error("UseWorker: AFOM conversion failed: %s", e, exc_info=True)
            return False

    def _install_frickbears3_addon_archive(self, extract_dir: str, gb_metadata: dict) -> bool:
        try:
            from services.frickbears3_addons_service import Frickbears3AddonsService

            result = Frickbears3AddonsService().convert_extracted_archive(
                extract_dir,
                self._mods_dir,
                source_file_path=self._file_path,
                gamebanana_metadata=gb_metadata or None,
            )
            return bool(result)
        except Exception as e:
            logger.error("UseWorker: FRICKBEARS3 addon conversion failed: %s", e, exc_info=True)
            return False

    @staticmethod
    def _apply_gb_metadata(config_data: dict, gb_metadata: dict) -> None:
        from adapters.gamebanana_adapter import GameBananaAPI

        mod_id = gb_metadata.get("mod_id")
        if mod_id:
            item_type = gb_metadata.get("item_type", "mod")
            config_data["id"] = f"gb_{item_type}_{mod_id}"
        if gb_metadata.get("homepage") and not config_data.get("homepage"):
            config_data["homepage"] = gb_metadata["homepage"]
        if gb_metadata.get("icon"):
            config_data["icon"] = gb_metadata["icon"]
        tags = gb_metadata.get("tags") or []
        if tags:
            existing = config_data.get("tags", [])
            if not isinstance(existing, list):
                existing = [existing] if existing else []
            for t in tags:
                if t and t not in existing:
                    existing.append(t)
            config_data["tags"] = existing
        category_tag = GameBananaAPI.category_to_tag(gb_metadata.get("category"))
        if category_tag:
            existing = config_data.get("tags", [])
            if not isinstance(existing, list):
                existing = [existing] if existing else []
            if category_tag not in existing:
                existing.append(category_tag)
            config_data["tags"] = existing

    @staticmethod
    def _update_config_id(mod_dir: str, gb_metadata: dict) -> None:
        from config.config import MOD_CONFIG_FILENAME
        from workers.install.helpers_install import load_mod_config, save_mod_config

        config_path = os.path.join(mod_dir, MOD_CONFIG_FILENAME)
        if not os.path.exists(config_path):
            return
        try:
            data = load_mod_config(config_path)
            if data:
                UseWorker._apply_gb_metadata(data, gb_metadata)
                save_mod_config(config_path, data, indent=4)
        except Exception as e:
            logger.warning("UseWorker: failed to update config id: %s", e)
