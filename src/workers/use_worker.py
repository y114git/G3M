"""Worker thread for the Use phase of the Downloads system."""

import contextlib
import logging
import os
import shutil
import tempfile
from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from models.download_models import USE_DECLINED, TargetKind
from ui.dialogs.mod.version_choice_dialog import WorkerVersionChoice
from ui.dialogs.unknown_game_dialog import (
    GAME_READY,
    MANUAL_INSTALL,
    WorkerGameResolver,
)
from ui.utils.thread_lifetime import ManagedQThread
from utils.mod.utils import is_gamebanana_id
from utils.mod.version_package import resolve_package_versions
from utils.path_utils import get_user_themes_dir
from utils.process_utils import format_filesystem_error, format_plugin_error

logger = logging.getLogger(__name__)


class UseWorker(ManagedQThread):
    use_finished = pyqtSignal(str, bool, bool, str)

    def __init__(
        self,
        record_id: str,
        file_path: str,
        target_kind: TargetKind,
        mods_dir: str,
        metadata: dict,
        plugin_install_service=None,
        themes_dir: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._record_id = record_id
        self._file_path = file_path
        self._target_kind = target_kind
        self._mods_dir = mods_dir
        self._metadata = metadata or {}
        self._plugin_install_service = plugin_install_service
        self._themes_dir = themes_dir or get_user_themes_dir()
        self._cancelled = False
        self._declined = False
        self._version_choice = WorkerVersionChoice(parent)
        self._game_resolver = WorkerGameResolver(parent)

    def _safe_finish(self, success: bool, needs_manual: bool, message: str) -> None:
        try:
            self.use_finished.emit(
                self._record_id,
                success,
                needs_manual,
                message,
            )
        except Exception as e:
            logger.warning(
                "UseWorker: failed to emit use_finished: %s", e, exc_info=True
            )

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            if self._target_kind == TargetKind.MOD:
                self._use_mod()
            elif self._target_kind == TargetKind.PLUGIN:
                self._use_plugin()
            elif self._target_kind == TargetKind.THEME:
                self._use_theme()
            else:
                self._safe_finish(
                    False, False, f"Unsupported target_kind: {self._target_kind}"
                )
        except Exception as e:
            logger.error("UseWorker: %s", e, exc_info=True)
            self._safe_finish(
                False, False, format_filesystem_error(e, path=self._file_path)
            )

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
            from utils.archive_utils import extract_archive_content_root

            content_path = extract_archive_content_root(
                self._file_path,
                extract_dir,
                is_cancelled=lambda: self._cancelled,
            )
            if self._cancelled:
                self._safe_finish(False, False, "cancelled")
                return
            self._snapshot_current_mod()
            if self._cancelled:
                self._safe_finish(False, False, "cancelled")
                return
            gb_metadata = self._build_gb_metadata()
            if self._cancelled:
                self._safe_finish(False, False, "cancelled")
                return

            from utils.file_utils import has_deltamod_info_file

            files_in_root = os.listdir(content_path)

            from workers.install.helpers_install import find_mod_config

            if has_deltamod_info_file(files_in_root):
                success = (
                    self._install_via_gamebanana_converter(gb_metadata)
                    if gb_metadata
                    else self._install_via_deltamod(content_path, gb_metadata)
                )
            elif find_mod_config(content_path):
                success = self._install_g3m_mod(content_path, gb_metadata)
            elif self._is_afom_archive(extract_dir, gb_metadata):
                success = self._install_afom_archive(extract_dir, gb_metadata)
            elif self._is_frickbears3_addon_archive(extract_dir, gb_metadata):
                success = self._install_frickbears3_addon_archive(
                    extract_dir, gb_metadata
                )
            elif gb_metadata:
                success = self._install_via_gamebanana_converter(gb_metadata)
            else:
                success = False

            if not success:
                if self._declined:
                    self._safe_finish(False, False, USE_DECLINED)
                else:
                    self._safe_finish(False, True, "")
                return
            self._safe_finish(True, False, "")
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

    def _snapshot_current_mod(self) -> None:
        if not self._metadata.get("snapshot_version"):
            return
        from utils.mod.version_utils import create_version_zip, get_unique_version_name
        from workers.install.helpers_install import load_mod_config

        folder = Path(str(self._metadata.get("snapshot_mod_folder") or "")).resolve()
        if not folder.is_dir() or not folder.is_relative_to(Path(self._mods_dir).resolve()):
            raise ValueError("Update snapshot folder is unavailable")
        config = load_mod_config(str(folder / "mod_config.json"))
        if not config or config.get("id") != self._metadata.get("update_mod_id"):
            raise ValueError("Update snapshot mod does not match")
        version = str(self._metadata["snapshot_version"])
        snapshot = create_version_zip(str(folder), str(folder), get_unique_version_name(str(folder), version), ignore_versions_dir=True)
        if not snapshot or not os.path.isfile(snapshot):
            raise OSError("Could not create the previous mod version")

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
                catalog_plugin_version=str(self._metadata.get("catalog_plugin_version", "")),
            )
            with contextlib.suppress(OSError):
                os.remove(self._file_path)
            self._safe_finish(True, False, "")
        except Exception as error:
            logger.error("UseWorker: plugin install failed: %s", error, exc_info=True)
            self._safe_finish(False, False, format_plugin_error(error, plugin_id=str(self._metadata.get("plugin_id", "") or ""), details=self._file_path))

    def _use_theme(self):
        from services.settings_themes import (
            theme_archive_contains_config,
            theme_archive_path,
        )

        if self._cancelled:
            self._safe_finish(False, False, "cancelled")
            return
        if not os.path.exists(self._file_path):
            self._safe_finish(False, False, format_filesystem_error(FileNotFoundError(self._file_path), path=self._file_path))
            return
        if not theme_archive_contains_config(self._file_path):
            self._safe_finish(False, False, "Theme archive is invalid")
            return
        os.makedirs(self._themes_dir, exist_ok=True)
        theme_id = str(self._metadata.get("theme_id", "")).strip()
        destination = theme_archive_path(self._themes_dir, theme_id or os.path.splitext(os.path.basename(self._file_path))[0])
        if self._cancelled:
            self._safe_finish(False, False, "cancelled")
            return
        if os.path.realpath(self._file_path) == os.path.realpath(destination):
            self._safe_finish(True, False, "")
            return
        with tempfile.NamedTemporaryFile(dir=self._themes_dir, suffix=".zip", delete=False) as handle:
            staged_path = handle.name
        try:
            shutil.copy2(self._file_path, staged_path)
            if self._cancelled:
                self._safe_finish(False, False, "cancelled")
                return
            os.replace(staged_path, destination)
        finally:
            with contextlib.suppress(OSError):
                os.remove(staged_path)
        with contextlib.suppress(OSError):
            os.remove(self._file_path)
        self._safe_finish(True, False, "")

    def _build_gb_metadata(self) -> dict:
        if not self._metadata.get("gb_mod_id"):
            return {}
        from adapters.gamebanana_adapter import GameBananaAPI

        metadata = {
            "mod_id": self._metadata["gb_mod_id"],
            "item_type": self._metadata.get("item_type", "mod"),
            "name": self._metadata.get("name"),
            "authors": self._metadata.get("authors") or [],
            "version": self._metadata.get("version"),
            "description": self._metadata.get("description"),
            "file_name": self._metadata.get("file_name"),
            "homepage": self._metadata.get("homepage")
            or self._metadata.get("profile_url"),
            "icon": self._metadata.get("icon"),
            "tags": self._metadata.get("tags") or [],
            "category": self._metadata.get("category"),
            "game": self._metadata.get("game") or self._gamebanana_game(),
        }
        metadata.update(GameBananaAPI().get_install_metadata(metadata))
        return metadata

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
        staging_root = ""
        previous_mod_dir = ""
        target_mod_dir = ""
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

            if not self._metadata.get("update_mod_id"):
                if (outcome := self._settle_game(mod_config_path)) is None:
                    self._declined = True
                    return False
                if outcome == MANUAL_INSTALL:
                    return False

            if not self._metadata.get("update_mod_id") and not resolve_package_versions(
                content_path,
                lambda name, label, versions: self._version_choice.ask(
                    name, label, versions, lambda: self._cancelled
                ),
            ):
                self._declined = True
                return False

            config_data = load_mod_config(mod_config_path)
            if not config_data:
                return False

            normalize_mod_id(config_data)
            if gb_metadata and gb_metadata.get("mod_id"):
                self._apply_gb_metadata(config_data, gb_metadata)
            mod_name = config_data.get("name", "imported_mod")
            folder_name = sanitize_filename(mod_name)
            target_mod_dir = ""
            mod_id = config_data.get("id")
            if is_gamebanana_id(mod_id):
                for entry in os.listdir(self._mods_dir):
                    if entry.startswith("."):
                        continue
                    candidate = os.path.join(self._mods_dir, entry)
                    candidate_config = os.path.join(candidate, MOD_CONFIG_FILENAME)
                    if not os.path.isfile(candidate_config):
                        continue
                    existing = load_mod_config(candidate_config)
                    if existing and existing.get("id") == mod_id:
                        target_mod_dir = candidate
                        break
            if not target_mod_dir:
                target_mod_dir = os.path.join(self._mods_dir, folder_name)
                counter = 1
                while os.path.exists(target_mod_dir):
                    target_mod_dir = os.path.join(
                        self._mods_dir, f"{folder_name}_{counter}"
                    )
                    counter += 1
            staging_root = tempfile.mkdtemp(prefix=".g3m-install-", dir=self._mods_dir)
            staging_mod_dir = os.path.join(staging_root, "mod")
            os.makedirs(staging_mod_dir)
            for item in os.listdir(content_path):
                src = os.path.join(content_path, item)
                dst = os.path.join(staging_mod_dir, item)
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

            existing_versions = os.path.join(target_mod_dir, "mod_versions")
            if os.path.isdir(existing_versions):
                shutil.copytree(
                    existing_versions,
                    os.path.join(staging_mod_dir, "mod_versions"),
                    dirs_exist_ok=True,
                )
            target_config_path = os.path.join(staging_mod_dir, MOD_CONFIG_FILENAME)
            save_mod_config(target_config_path, config_data, indent=4)
            if os.path.exists(target_mod_dir):
                previous_mod_dir = os.path.join(staging_root, "previous")
                os.replace(target_mod_dir, previous_mod_dir)
            os.replace(staging_mod_dir, target_mod_dir)
            return True
        except Exception as e:
            logger.error("UseWorker: g3m mod install failed: %s", e, exc_info=True)
            if previous_mod_dir and os.path.exists(previous_mod_dir):
                try:
                    if os.path.exists(target_mod_dir):
                        shutil.rmtree(target_mod_dir)
                    os.replace(previous_mod_dir, target_mod_dir)
                except OSError as restore_error:
                    logger.critical(
                        "UseWorker: failed to restore previous mod after update failure: %s; "
                        "backup retained at %s",
                        restore_error,
                        previous_mod_dir,
                    )
                    staging_root = ""
            return False
        finally:
            if staging_root:
                shutil.rmtree(staging_root, ignore_errors=True)

    def _settle_game(self, mod_config_path: str) -> str | None:
        """Make sure the game the mod is for exists; see ``resolve_unknown_game``."""
        from workers.install.helpers_install import load_mod_config

        config_data = load_mod_config(mod_config_path) or {}
        game_id = config_data.get("game")
        if not isinstance(game_id, str) or not game_id:
            return GAME_READY
        return self._game_resolver.resolve(
            game_id,
            str(config_data.get("name") or game_id),
            self._gamebanana_game_id,
            lambda: self._cancelled,
        )

    def _gamebanana_game(self) -> str:
        """The game id of the GameBanana game this download is listed under."""
        from models.game_modes import get_gamebanana_reverse_map

        try:
            game_id = self._gamebanana_game_id()
        except Exception:
            logger.warning("UseWorker: could not look up the GameBanana game of the download", exc_info=True)
            game_id = None
        return get_gamebanana_reverse_map().get(game_id or 0, "deltarune")

    def _gamebanana_game_id(self) -> int | None:
        """The GameBanana game this download came from, when it came from GameBanana."""
        if not (mod_id := self._metadata.get("gb_mod_id")):
            return None
        from adapters.gamebanana_adapter import GameBananaAPI

        is_wip = str(self._metadata.get("item_type", "mod")).strip().casefold() == "wip"
        return GameBananaAPI().get_mod_game_id(mod_id, "Wip" if is_wip else "Mod")

    def _is_afom_archive(self, extract_dir: str, gb_metadata: dict) -> bool:
        game = (
            str((gb_metadata or {}).get("game") or self._metadata.get("game") or "")
            .strip()
            .lower()
        )
        if game and game != "pizzatower":
            return False
        try:
            from services.pizza_tower_afom_service import PizzaTowerAFOMService

            inspection = PizzaTowerAFOMService().inspect_extracted_archive(extract_dir)
            return inspection.eligible
        except Exception as e:
            logger.debug("UseWorker: AFOM inspection failed: %s", e, exc_info=True)
            return False

    def _is_frickbears3_addon_archive(
        self, extract_dir: str, gb_metadata: dict
    ) -> bool:
        game = (
            str((gb_metadata or {}).get("game") or self._metadata.get("game") or "")
            .strip()
            .lower()
        )
        if game and game != "frickbears3":
            return False
        try:
            from services.frickbears3_addons_service import Frickbears3AddonsService

            inspection = Frickbears3AddonsService().inspect_extracted_archive(
                extract_dir
            )
            return inspection.eligible
        except Exception as e:
            logger.debug(
                "UseWorker: FRICKBEARS3 addon inspection failed: %s", e, exc_info=True
            )
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

    def _install_frickbears3_addon_archive(
        self, extract_dir: str, gb_metadata: dict
    ) -> bool:
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
            logger.error(
                "UseWorker: FRICKBEARS3 addon conversion failed: %s", e, exc_info=True
            )
            return False

    @staticmethod
    def _apply_gb_metadata(config_data: dict, gb_metadata: dict) -> None:
        from utils.mod.tags import normalize_tags

        mod_id = gb_metadata.get("mod_id")
        if mod_id:
            item_type = gb_metadata.get("item_type", "mod")
            config_data["id"] = f"gb_{item_type}_{mod_id}"
        if gb_metadata.get("homepage") and not config_data.get("homepage"):
            config_data["homepage"] = gb_metadata["homepage"]
        if gb_metadata.get("icon") and not config_data.get("icon"):
            config_data["icon"] = gb_metadata["icon"]
        if gb_metadata.get("version"):
            config_data["version"] = str(gb_metadata["version"])
        existing = config_data.get("tags")
        if not isinstance(existing, list):
            existing = [existing] if existing else []
        tags = normalize_tags(
            [*existing, *(gb_metadata.get("tags") or []), gb_metadata.get("category")]
        )
        if tags:
            config_data["tags"] = tags

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
