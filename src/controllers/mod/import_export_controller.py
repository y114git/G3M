"""Controller for mod import and export operations."""

import contextlib
import json
import logging
import os
import shutil
import tempfile
import uuid
from collections.abc import Collection
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout

from config.config import MOD_CONFIG_FILENAME
from services.localization_service import tr
from services.mod_operation_support import confirm_direct_operation_paths
from ui.dialogs.unknown_game_dialog import MANUAL_INSTALL, resolve_unknown_game
from utils.archive_utils import extract_archive, unwrap_single_directory_chain
from utils.file_utils import find_deltamod_info_file, flatten_single_child_directories
from utils.mod.config import (
    read_mod_config_bytes,
    write_mod_config,
)
from utils.mod.legacy_config_migration import (
    migrate_legacy_config_bytes,
    migrate_legacy_config_file,
)
from utils.mod.utils import get_mod_id

logger = logging.getLogger(__name__)


class ModImportExportController:
    """Manages mod import and export functionality."""

    def __init__(self, app_state, mod_service, app_window) -> None:
        self.app_state = app_state
        self.mod_service = mod_service
        self.app_window = app_window
        self._import_queue: list = []
        self._manual_import_batches: list[list[str]] = []
        self._importing = False

    def _refresh_mod_list(self) -> None:
        self.mod_service.invalidate_mods_cache()
        self.mod_service.load_local_mods()
        self.mod_service.mod_list_updated.emit()

    def _safe_show_critical(self, title: str, message: str) -> None:
        try:
            QMessageBox.critical(self.app_window, title, message)
        except Exception as e:
            logger.debug(
                "ModImportExportController: critical dialog failed: %s",
                e,
                exc_info=True,
            )

    def _safe_show_information(self, title: str, message: str) -> None:
        try:
            QMessageBox.information(self.app_window, title, message)
        except Exception as e:
            logger.debug(
                "ModImportExportController: information dialog failed: %s",
                e,
                exc_info=True,
            )

    def _safe_feedback_status(self, message: str, color: str) -> None:
        try:
            self.app_window.feedback_service.update_status(message, color)
        except Exception as e:
            logger.debug(
                "ModImportExportController: feedback status failed: %s",
                e,
                exc_info=True,
            )

    def _safe_feedback_message(self, level: str, title: str, message: str) -> None:
        try:
            self.app_window.feedback_service.show_message(level, title, message)
        except Exception as e:
            logger.debug(
                "ModImportExportController: feedback message failed: %s",
                e,
                exc_info=True,
            )

    @staticmethod
    def _format_import_exception(exc: Exception, *, file_path: str = "") -> str:
        if isinstance(exc, FileNotFoundError):
            return tr("errors.archive_not_found")
        if isinstance(exc, PermissionError):
            return tr("errors.permission_denied", path=file_path or getattr(exc, "filename", "") or "?")
        return str(exc)

    def show_add_mod_dialog(self):
        """Show dialog with Import Mod / Create Mod options."""
        dialog = QDialog(self.app_window)
        dialog.setWindowTitle(tr("ui.add_mod"))
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        btn_layout = QHBoxLayout()
        import_btn = QPushButton(tr("ui.import_mod"))
        import_btn.clicked.connect(
            lambda: (dialog.accept(), self._show_import_dialog())
        )
        btn_layout.addWidget(import_btn)
        create_btn = QPushButton(tr("ui.create_mod"))
        create_btn.clicked.connect(
            lambda: (dialog.accept(), self._show_create_mod_dialog())
        )
        btn_layout.addWidget(create_btn)
        layout.addLayout(btn_layout)
        dialog.exec()

    def _show_create_mod_dialog(self):
        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        editor = ModEditorDialog(self.app_window, is_creating=True)
        editor.exec()

    def show_mod_details_dialog(self, mod_data):
        """Open the mod editor dialog in edit mode for the given mod."""
        mod_id = get_mod_id(mod_data)
        if not mod_id:
            return
        mod_folder = self.mod_service.get_mod_folder_path(mod_id)
        if not mod_folder or not os.path.exists(mod_folder):
            mod_folder = self._find_mod_dir_by_config(mod_data)
        config_data = {}
        if mod_folder:
            config_path = os.path.join(mod_folder, MOD_CONFIG_FILENAME)
            if os.path.exists(config_path):
                try:
                    config_data = migrate_legacy_config_file(config_path)
                except Exception as e:
                    logger.error(
                        "Failed to load %s from %s: %s",
                        MOD_CONFIG_FILENAME,
                        config_path,
                        e,
                        exc_info=True,
                    )
                    self._safe_show_critical(
                        tr("ui.error"),
                        f"Failed to load mod config: Failed to load {MOD_CONFIG_FILENAME}: {e}",
                    )
                    return

        if not config_data:
            self._safe_show_critical(
                tr("ui.error"),
                f"Failed to load mod config: No valid config found in mod folder: {mod_folder}",
            )
            return

        config_data["id"] = mod_id
        if mod_folder:
            config_data["folder_path"] = mod_folder
            config_data["folder_name"] = os.path.basename(mod_folder)

        try:
            from ui.dialogs.mod_editor.dialog import ModEditorDialog

            editor = ModEditorDialog(
                self.app_window, is_creating=False, mod_data=config_data
            )
            editor.exec()
        except RuntimeError as e:
            self._safe_show_critical(
                tr("ui.error"), f"Failed to load mod config: {e}"
            )

    def _show_import_dialog(self):
        from ui.dialogs.import_dialog import ImportDialog

        dialog = ImportDialog(self.app_window, self.app_window.feedback_service, "mods")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.import_method == "file" and dialog.selected_file:
                self._install_mod_from_file(dialog.selected_file)
            elif dialog.import_method == "url" and dialog.selected_url:
                self._install_mod_from_url(dialog.selected_url)

    def _install_mod_from_file(self, file_path: str):
        from utils.file_utils import (
            managed_temporary_directory,
            remove_archive_extension,
            sanitize_filename,
        )

        try:
            with managed_temporary_directory(prefix="g3m_import_") as temp_dir:
                content_path = self._materialize_local_import(file_path, temp_dir)
                if find_deltamod_info_file(content_path):
                    from adapters.deltamod_adapter import DeltamodConverter

                    converter = DeltamodConverter(content_path, self.app_state.mods_dir)
                    new_mod_path = converter.convert()
                    if new_mod_path:
                        self._refresh_mod_list()
                        self._safe_show_information(
                            tr("dialogs.success"),
                            tr("status.mod_imported_success"),
                        )
                    else:
                        self._safe_show_critical(
                            tr("errors.error"),
                            tr("errors.mod_import_failed", error="Conversion failed"),
                        )
                    return
                config_path_to_read = os.path.join(content_path, MOD_CONFIG_FILENAME)
                if os.path.exists(config_path_to_read):
                    raw_bytes = read_mod_config_bytes(config_path_to_read)
                    config = migrate_legacy_config_bytes(
                        raw_bytes, mod_root_path=content_path
                    )
                    raw_config = json.loads(raw_bytes)
                    source_id = raw_config.get("id") if isinstance(raw_config, dict) else None
                    if not source_id and isinstance(raw_config, dict):
                        metadata = raw_config.get("metadata")
                        source_id = metadata.get("id") if isinstance(metadata, dict) else None
                    mod_id = config.get("id")
                    mod_name_value = config.get("name", "Unknown")
                    mod_name = (
                        mod_name_value
                        if isinstance(mod_name_value, str) and mod_name_value
                        else "Unknown"
                    )

                    if not source_id:
                        mod_id = f"local_{uuid.uuid4().hex[:12]}"
                        config["id"] = mod_id
                    mod_id = str(mod_id)
                    if not confirm_direct_operation_paths(
                        getattr(self.app_window, "feedback_service", None),
                        getattr(self.app_state, "local_config", None),
                        config,
                        mod_id=mod_id,
                    ):
                        return

                    self._apply_icon_fallback(content_path, config)
                    existing_mod_folder = self.mod_service.get_mod_folder_path(mod_id)
                    if not isinstance(existing_mod_folder, (str, os.PathLike)) or not os.path.isdir(
                        existing_mod_folder
                    ):
                        existing_mod_folder = self._find_mod_dir_by_id(
                            mod_id, exclude_path=content_path
                        )
                    if existing_mod_folder:
                        self._merge_into_existing_mod(
                            mod_id, content_path, file_path, mod_name, config
                        )
                        return

                    if game_id := config.get("game"):
                        outcome = resolve_unknown_game(self.app_window, str(game_id), mod_name)
                        if outcome is None:
                            return
                        if outcome == MANUAL_INSTALL:
                            self._show_import_error_with_manual_install(
                                file_path, tr("games.mod_unknown_manual_note")
                            )
                            return
                    if not self._resolve_package_versions(content_path):
                        return
                    if (chosen_bytes := read_mod_config_bytes(config_path_to_read)) != raw_bytes:
                        # Another version became the active one, so its paths need confirming too.
                        config = migrate_legacy_config_bytes(chosen_bytes, mod_root_path=content_path)
                        config["id"] = mod_id
                        if not confirm_direct_operation_paths(
                            getattr(self.app_window, "feedback_service", None),
                            getattr(self.app_state, "local_config", None),
                            config,
                            mod_id=mod_id,
                        ):
                            return
                        self._apply_icon_fallback(content_path, config)
                        mod_name = str(config.get("name") or mod_name)
                    folder_name = sanitize_filename(mod_name) or remove_archive_extension(
                        os.path.basename(file_path)
                    )
                    target_mod_dir = os.path.join(self.app_state.mods_dir, folder_name)
                    counter = 1
                    while os.path.exists(target_mod_dir):
                        folder_name_with_counter = f"{folder_name}_{counter}"
                        target_mod_dir = os.path.join(
                            self.app_state.mods_dir, folder_name_with_counter
                        )
                        counter += 1
                    shutil.copytree(content_path, target_mod_dir)
                    try:
                        target_config_path = os.path.join(
                            target_mod_dir, MOD_CONFIG_FILENAME
                        )
                        write_mod_config(target_config_path, config)
                        self._refresh_mod_list()
                        self._safe_show_information(
                            tr("dialogs.success"),
                            tr("status.mod_imported_success"),
                        )
                    except Exception as e:
                        logger.error(
                            f"[IMPORT] Post-copy import failed, cleaning up {target_mod_dir}: {e}",
                            exc_info=True,
                        )
                        from utils.file_utils import safe_rmtree

                        safe_rmtree(target_mod_dir)
                        raise
                else:
                    self._show_import_error_with_manual_install(
                        file_path, tr("errors.invalid_mod_format")
                    )
        except Exception as e:
            logger.error(f"[IMPORT] Mod import failed: {e}", exc_info=True)
            self._show_import_error_with_manual_install(
                file_path,
                tr(
                    "errors.mod_import_failed",
                    error=self._format_import_exception(e, file_path=file_path),
                ),
            )

    @staticmethod
    def _apply_icon_fallback(content_path: str, config: dict) -> None:
        icon_path = os.path.join(content_path, "_icon.png")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(content_path, "icon.png")
        if os.path.exists(icon_path) and not config.get("icon"):
            config["icon"] = (
                "${mod_path}/_icon.png"
                if os.path.basename(icon_path) == "_icon.png"
                else "${mod_path}/icon.png"
            )

    def _resolve_package_versions(self, content_path: str) -> bool:
        """Let the user pick which saved versions of an imported mod to install."""
        from ui.dialogs.mod.version_choice_dialog import choose_install_versions
        from utils.mod.version_package import resolve_package_versions

        return resolve_package_versions(
            content_path,
            lambda name, label, versions: choose_install_versions(
                self.app_window, name, label, versions
            ),
        )

    def _merge_into_existing_mod(
        self, mod_id: str, content_path: str, file_path: str, mod_name: str, config: dict
    ):
        """Merge imported mod into mod_versions of existing mod with the same id."""
        try:
            existing_mod_folder = self.mod_service.get_mod_folder_path(mod_id)
            if not existing_mod_folder or not os.path.isdir(existing_mod_folder):
                existing_mod_folder = self._find_mod_dir_by_id(mod_id)
            if not existing_mod_folder or not os.path.isdir(existing_mod_folder):
                logger.error(
                    f"[IMPORT MERGE] Could not find folder for existing mod id={mod_id}"
                )
                self._safe_show_critical(
                    tr("errors.error"),
                    tr(
                        "errors.mod_import_failed",
                        error="Existing mod folder not found",
                    ),
                )
                return
            from utils.mod.version_utils import (
                create_version_zip,
                ensure_versions_dir,
            )

            archive_base = os.path.splitext(os.path.basename(file_path))[0]
            version_name = archive_base or mod_name or "imported"
            ensure_versions_dir(existing_mod_folder)
            with tempfile.TemporaryDirectory(prefix="g3m_version_import_") as temporary:
                staged = os.path.join(temporary, "mod")
                shutil.copytree(content_path, staged)
                write_mod_config(os.path.join(staged, MOD_CONFIG_FILENAME), config)
                create_version_zip(
                    staged,
                    existing_mod_folder,
                    version_name,
                    ignore_versions_dir=True,
                )
            self._refresh_mod_list()
            self._safe_show_information(
                tr("dialogs.success"),
                tr(
                    "status.mod_merged_as_version",
                    mod_name=mod_name,
                    version_name=version_name,
                ),
            )
        except Exception as e:
            logger.error(
                f"[IMPORT MERGE] Failed to merge mod into versions: {e}", exc_info=True
            )
            self._safe_show_critical(
                tr("errors.error"),
                tr(
                    "errors.mod_import_failed",
                    error=self._format_import_exception(e, file_path=file_path),
                ),
            )

    def _find_mod_dir_by_id(self, mod_id: str, exclude_path: str | None = None):
        """Find mod directory by id in mods_dir."""
        if not os.path.exists(self.app_state.mods_dir):
            return None
        excluded = os.path.normcase(os.path.abspath(exclude_path)) if exclude_path else None
        for entry in os.scandir(self.app_state.mods_dir):
            if not entry.is_dir():
                continue
            if excluded and os.path.normcase(os.path.abspath(entry.path)) == excluded:
                continue
            config_path = os.path.join(entry.path, MOD_CONFIG_FILENAME)
            if not os.path.exists(config_path):
                continue
            try:
                raw_bytes = read_mod_config_bytes(config_path)
                config = migrate_legacy_config_bytes(raw_bytes, mod_root_path=entry.path)
                if config.get("id") == mod_id:
                    return entry.path
            except Exception as e:
                logger.debug(
                    f"_find_mod_dir_by_id: failed to read {config_path}: {e}",
                    exc_info=True,
                )
        return None

    def _install_mod_from_url(self, url: str):
        try:
            from workers.install.url_install_worker import UrlInstallThread

            worker = UrlInstallThread(self.app_window, url)
            worker.status.connect(
                lambda msg, color: self._safe_feedback_status(msg, color)
            )
            worker.progress.connect(
                lambda p: setattr(self.app_state, "progress_bar_value", p)
            )
            worker.result_ready.connect(self._on_mod_install_finished)
            worker.manual_install_required.connect(self._on_manual_install_required)
            self.app_state.is_installing = True
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.current_task = worker
            worker.start()
        except Exception as e:
            logger.error(
                f"ModImportExportController: Error installing mod from URL: {e}",
                exc_info=True,
            )
            self._safe_feedback_message(
                "error",
                tr("errors.error") or "Error",
                tr(
                    "mods.installation_error",
                    error=self._format_import_exception(e, file_path=url),
                ) or self._format_import_exception(e, file_path=url),
            )

    def _on_manual_install_required(
        self, prepared_path: str, archive_path: str, temp_dir: str
    ):
        try:
            self.app_state.reset_install_state()
            def _on_accept():
                from ui.utils.ui_utils import refresh_ui_after_mod_install

                refresh_ui_after_mod_install(self.app_window, self.mod_service)

            presenter = getattr(self.app_window, "pizza_oven_conversion_presenter", None)
            if presenter is None:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return
            presenter.prompt_with_manual_options(
                self.app_window,
                error_title=tr("errors.mod_not_compatible_title"),
                error_text=tr("errors.mod_requires_manual_installation"),
                informative_text=tr("dialogs.manual_install_available"),
                prepared_path=prepared_path,
                source_file_path=archive_path,
                temp_dir=temp_dir,
                on_success=_on_accept,
            )
        except Exception as e:
            logger.error(
                f"Failed to open manual install dialog from URL: {e}", exc_info=True
            )
            self._safe_feedback_message(
                "error",
                tr("errors.error"),
                tr(
                    "errors.manual_install_failed",
                    error=self._format_import_exception(e, file_path=archive_path),
                ),
            )
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _show_import_error_with_manual_install(
        self, file_path: str, error_message: str
    ):
        try:
            prepared_path, temp_dir = self._prepare_local_files_for_manual_install(
                file_path
            )
            if not prepared_path:
                if temp_dir:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                return
            presenter = getattr(self.app_window, "pizza_oven_conversion_presenter", None)
            if presenter is None:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return
            presenter.prompt_with_manual_options(
                self.app_window,
                error_title=tr("errors.error"),
                error_text=error_message,
                informative_text=tr("dialogs.manual_install_available"),
                prepared_path=prepared_path,
                source_file_path=file_path,
                temp_dir=temp_dir,
            )
        except Exception as e:
            logger.error(f"Manual install from file failed: {e}", exc_info=True)
            self._safe_show_critical(
                tr("errors.error"),
                tr(
                    "errors.manual_install_failed",
                    error=self._format_import_exception(e, file_path=file_path),
                ),
            )

    def _prepare_local_files_for_manual_install(
        self, file_path: str
    ) -> tuple[str, str]:
        temp_dir = tempfile.mkdtemp(prefix="g3m_manual_install_")
        try:
            return (self._materialize_local_import(file_path, temp_dir), temp_dir)
        except Exception as e:
            logger.error(f"Failed to prepare local files: {e}", exc_info=True)
            with contextlib.suppress(Exception):
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def _materialize_local_import(self, file_path: str, temp_dir: str) -> str:
        if os.path.isdir(file_path):
            destination = Path(temp_dir).resolve()

            def ignore_links(directory, names):
                return [
                    name for name in names
                    if (path := Path(directory) / name).is_symlink()
                    or path.is_junction()
                    or path.resolve().is_relative_to(destination)
                ]

            shutil.copytree(file_path, temp_dir, dirs_exist_ok=True, ignore=ignore_links)
            return unwrap_single_directory_chain(temp_dir)
        try:
            extract_archive(file_path, temp_dir)
        except shutil.ReadError:
            return file_path
        except Exception as exc:
            raise ValueError(self._format_import_exception(exc, file_path=file_path)) from exc
        return unwrap_single_directory_chain(temp_dir)

    def _is_automatic_mod_source(self, file_path: str) -> bool:
        if (
            os.path.isfile(file_path)
            and os.path.basename(file_path).casefold() == MOD_CONFIG_FILENAME.casefold()
        ):
            return False
        try:
            with tempfile.TemporaryDirectory(prefix="g3m_import_probe_") as temp_dir:
                content_path = self._materialize_local_import(file_path, temp_dir)
                return os.path.isdir(content_path) and (
                    bool(find_deltamod_info_file(content_path))
                    or os.path.isfile(os.path.join(content_path, MOD_CONFIG_FILENAME))
                )
        except Exception:
            return False

    def _show_manual_import_batch(self, file_paths: list[str]) -> None:
        temp_dir = tempfile.mkdtemp(prefix="g3m_manual_import_")
        try:
            for index, file_path in enumerate(file_paths, start=1):
                destination = os.path.join(temp_dir, f"{index:04d}")
                os.makedirs(destination)
                content_path = self._materialize_local_import(file_path, destination)
                if os.path.isdir(content_path) and os.path.normcase(content_path) != os.path.normcase(destination):
                    destination_root = os.path.realpath(destination)
                    content_root = os.path.realpath(content_path)
                    try:
                        inside_destination = (
                            os.path.commonpath((destination_root, content_root))
                            == destination_root
                        )
                    except ValueError:
                        inside_destination = False
                    if inside_destination:
                        flatten_single_child_directories(destination)
                    else:
                        shutil.copytree(content_path, destination, dirs_exist_ok=True)
                elif os.path.isfile(content_path):
                    shutil.copy2(content_path, os.path.join(destination, os.path.basename(content_path)))
            presenter = getattr(self.app_window, "pizza_oven_conversion_presenter", None)
            if presenter is None:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return
            presenter.prompt_with_manual_options(
                self.app_window,
                error_title=tr("errors.error"),
                error_text=tr("errors.invalid_mod_format"),
                informative_text=tr("dialogs.manual_install_available"),
                prepared_path=temp_dir,
                source_file_path=None,
                temp_dir=temp_dir,
            )
        except Exception as error:
            shutil.rmtree(temp_dir, ignore_errors=True)
            self._safe_show_critical(
                tr("errors.error"),
                tr("errors.manual_install_failed", error=self._format_import_exception(error)),
            )

    def _on_mod_install_finished(self, success: bool, message: str):
        self.app_state.reset_install_state()
        if success:
            self._refresh_mod_list()
            self._safe_feedback_status(message, "green")
            self._safe_show_information(tr("dialogs.success"), message)
        else:
            logger.warning(f"Mod installation failed: {message}")
            self._safe_feedback_status(message or tr("errors.error"), "red")
            self._safe_feedback_message(
                "error",
                tr("errors.error") or "Error",
                message or tr("mods.installation_error", error="Unknown error") or "Installation failed",
            )

    def _find_mod_dir_by_config(self, mod) -> str | None:
        if not os.path.exists(self.app_state.mods_dir):
            return None
        mod_id_attr = get_mod_id(mod)
        for entry in os.scandir(self.app_state.mods_dir):
            if not entry.is_dir():
                continue
            config_path = os.path.join(entry.path, MOD_CONFIG_FILENAME)
            if not os.path.exists(config_path):
                continue
            try:
                raw_bytes = read_mod_config_bytes(config_path)
                config = migrate_legacy_config_bytes(raw_bytes, mod_root_path=entry.path)
                config_mod_id = config.get("id")
                if config_mod_id == mod_id_attr:
                    return entry.path
                if not config_mod_id and config.get("name", "") == mod.name:
                    return entry.path
            except Exception as e:
                logger.warning(f"Error reading config {config_path}: {e}")
        return None

    def import_files_sequentially(self, file_paths: list):
        """Import recognized mods first, then open one manual session for the rest."""
        if not file_paths:
            return
        automatic, manual = [], []
        for file_path in file_paths:
            if (
                os.path.isfile(file_path)
                and os.path.basename(file_path).casefold() == MOD_CONFIG_FILENAME.casefold()
            ):
                self._safe_show_critical(tr("errors.error"), tr("errors.invalid_mod_format"))
            elif self._is_automatic_mod_source(file_path):
                automatic.append(file_path)
            else:
                manual.append(file_path)
        self._import_queue.extend(automatic)
        if manual:
            self._manual_import_batches.append(manual)
        if not self._importing:
            self._process_next_import()

    def _process_next_import(self):
        self._importing = True
        if self._import_queue:
            file_path = self._import_queue.pop(0)
            try:
                self._install_mod_from_file(file_path)
            except Exception as error:
                logger.error(
                    "[DND IMPORT] Failed to import %s: %s", file_path, error, exc_info=True
                )
            QTimer.singleShot(100, self._process_next_import)
            return
        if self._manual_import_batches:
            try:
                self._show_manual_import_batch(self._manual_import_batches.pop(0))
            except Exception as error:
                logger.error("[DND IMPORT] Manual import batch failed: %s", error, exc_info=True)
            QTimer.singleShot(0, self._process_next_import)
            return
        self._importing = False

    def _find_export_dir(self, mod_data) -> str | None:
        mod_dir = self.mod_service.get_mod_folder_path(get_mod_id(mod_data))
        if not mod_dir or not os.path.exists(mod_dir):
            mod_dir = self._find_mod_dir_by_config(mod_data)
        return mod_dir if mod_dir and os.path.exists(mod_dir) else None

    def choose_export_versions(self, mod_data) -> frozenset[str] | None:
        """Ask which saved versions to export along with the active one; None when cancelled."""
        from ui.dialogs.mod.version_choice_dialog import choose_export_versions
        from utils.mod.version_package import describe_active_version
        from utils.mod.version_utils import list_local_versions

        mod_dir = self._find_export_dir(mod_data)
        if not mod_dir or not (versions := list_local_versions(mod_dir)):
            return frozenset()
        name, label = describe_active_version(mod_dir)
        return choose_export_versions(self.app_window, name, label, versions)

    def export_mod_to_path(
        self, mod_data, export_path: str, versions: Collection[str] = ()
    ) -> bool:
        """Export a mod to a zip: its active files and only the named saved versions."""
        try:
            mod_dir = self._find_export_dir(mod_data)
            if not mod_dir:
                logger.error(
                    f"[EXPORT] Mod folder not found for: {getattr(mod_data, 'name', get_mod_id(mod_data))}"
                )
                return False
            if Path(export_path).resolve().is_relative_to(Path(mod_dir).resolve()):
                logger.error(f"[EXPORT] Export path {export_path!r} is inside the source mod folder {mod_dir!r}")
                return False
            from utils.mod.version_package import export_mod_archive

            export_mod_archive(mod_dir, export_path, versions)
            return True
        except Exception as e:
            logger.error(f"[EXPORT] Mod export failed: {e}", exc_info=True)
            return False
