"""Worker thread for the Use phase of the Downloads system."""

import logging
import os
import shutil
import tempfile

from PyQt6.QtCore import QThread, pyqtSignal

from models.download_models import TargetKind

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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._record_id = record_id
        self._file_path = file_path
        self._target_kind = target_kind
        self._mods_dir = mods_dir
        self._metadata = metadata or {}
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            if self._target_kind == TargetKind.MOD:
                self._use_mod()
            else:
                self.use_finished.emit(
                    self._record_id,
                    False,
                    False,
                    f"Unsupported target_kind: {self._target_kind}",
                )
        except Exception as e:
            logger.error("UseWorker: %s", e, exc_info=True)
            self.use_finished.emit(self._record_id, False, False, str(e))

    def _use_mod(self):
        if not os.path.exists(self._file_path):
            self.use_finished.emit(self._record_id, False, False, "File not found")
            return

        extract_dir = tempfile.mkdtemp(prefix="dh_use_")
        try:
            self._extract(extract_dir)
            if self._cancelled:
                self.use_finished.emit(self._record_id, False, False, "cancelled")
                return

            content_path = self._resolve_content_root(extract_dir)
            gb_metadata = self._build_gb_metadata()

            from utils.file_utils import has_deltamod_info_file

            files_in_root = os.listdir(content_path)

            from workers.install.helpers_install import find_mod_config

            if has_deltamod_info_file(files_in_root):
                success = self._install_via_deltamod(content_path, gb_metadata)
            elif find_mod_config(content_path):
                success = self._install_deltahub_mod(content_path, gb_metadata)
            elif gb_metadata:
                success = self._install_via_gamebanana_converter(gb_metadata)
            else:
                success = False

            if not success:
                self.use_finished.emit(self._record_id, False, True, "")
                return
            self.use_finished.emit(self._record_id, True, False, "")
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

    def _extract(self, target_dir: str):
        from utils.archive_utils import extract_archive

        extract_archive(self._file_path, target_dir)

    @staticmethod
    def _resolve_content_root(extract_dir: str) -> str:
        contents = os.listdir(extract_dir)
        if len(contents) == 1:
            single = os.path.join(extract_dir, contents[0])
            if os.path.isdir(single):
                return single
        return extract_dir

    def _build_gb_metadata(self) -> dict:
        if not self._metadata.get("gb_mod_id"):
            return {}
        return {
            "mod_id": self._metadata["gb_mod_id"],
            "item_type": self._metadata.get("item_type", "mod"),
            "profile_url": self._metadata.get("profile_url"),
            "icon_url": self._metadata.get("icon_url"),
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
                self._update_config_key(result, gb_metadata)
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

    def _install_deltahub_mod(self, content_path: str, gb_metadata: dict) -> bool:
        try:
            from config.config import MOD_CONFIG_FILENAME
            from utils.file_utils import sanitize_filename
            from workers.install.helpers_install import (
                find_mod_config,
                load_mod_config,
                normalize_mod_key,
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

            normalize_mod_key(config_data)
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
            logger.error("UseWorker: deltahub mod install failed: %s", e, exc_info=True)
            return False

    @staticmethod
    def _apply_gb_metadata(config_data: dict, gb_metadata: dict) -> None:
        mod_id = gb_metadata.get("mod_id")
        if mod_id:
            item_type = gb_metadata.get("item_type", "mod")
            config_data["key"] = f"gb_{item_type}_{mod_id}"
            config_data.pop("mod_key", None)
        if gb_metadata.get("profile_url") and not config_data.get("external_url"):
            config_data["external_url"] = gb_metadata["profile_url"]
        if gb_metadata.get("icon_url"):
            config_data["icon_url"] = gb_metadata["icon_url"]
        tags = gb_metadata.get("tags") or []
        if tags:
            existing = config_data.get("tags", [])
            if not isinstance(existing, list):
                existing = [existing] if existing else []
            for t in tags:
                if t and t not in existing:
                    existing.append(t)
            config_data["tags"] = existing

    @staticmethod
    def _update_config_key(mod_dir: str, gb_metadata: dict) -> None:
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
            logger.warning("UseWorker: failed to update config key: %s", e)
