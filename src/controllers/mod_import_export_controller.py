"""Controller for mod import and export operations."""

import contextlib
import json
import logging
import os
import shutil
import tempfile
import zipfile

from PyQt6.QtWidgets import QDialog, QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout

from config.config import MOD_CONFIG_FILENAME
from services.localization_service import tr
from utils.archive_utils import extract_archive, unwrap_single_directory_chain
from utils.file_utils import find_deltamod_info_file, save_json
from utils.mod_utils import get_mod_id


class ModImportExportController:
    """Manages mod import and export functionality."""

    def __init__(self, app_state, mod_service, app_window) -> None:
        self.app_state = app_state
        self.mod_service = mod_service
        self.app_window = app_window
        self._import_queue: list = []
        self._importing = False

    def _refresh_mod_list(self) -> None:
        self.mod_service.invalidate_mods_cache()
        self.mod_service.load_local_mods()
        self.mod_service.mod_list_updated.emit()

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
        from ui.dialogs.mod_editor_dialog import ModEditorDialog

        editor = ModEditorDialog(self.app_window, is_creating=True)
        editor.exec()

    def show_mod_details_dialog(self, mod_data):
        """Open the mod editor dialog in edit mode for the given mod."""
        import json

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
                    with open(config_path, encoding="utf-8") as f:
                        config_data = json.load(f)
                except Exception as e:
                    raise RuntimeError(f"Failed to load {MOD_CONFIG_FILENAME}: {e}") from e

        if not config_data:
            raise RuntimeError(f"No valid config found in mod folder: {mod_folder}")

        config_data["id"] = mod_id
        if mod_folder:
            config_data["folder_path"] = mod_folder
            config_data["folder_name"] = os.path.basename(mod_folder)

        try:
            from ui.dialogs.mod_editor_dialog import ModEditorDialog

            editor = ModEditorDialog(
                self.app_window, is_creating=False, mod_data=config_data
            )
            editor.exec()
        except RuntimeError as e:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.critical(
                self.app_window, tr("ui.error"), f"Failed to load mod config: {e}"
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
        from utils.file_utils import remove_archive_extension, sanitize_filename

        try:
            with tempfile.TemporaryDirectory(prefix="deltahub_import_") as temp_dir:
                content_path = self._materialize_local_import(file_path, temp_dir)
                if find_deltamod_info_file(content_path):
                    from adapters.deltamod_adapter import DeltamodConverter

                    converter = DeltamodConverter(content_path, self.app_state.mods_dir)
                    new_mod_path = converter.convert()
                    if new_mod_path:
                        self._refresh_mod_list()
                        QMessageBox.information(
                            self.app_window,
                            tr("dialogs.success"),
                            tr("status.mod_imported_success"),
                        )
                    else:
                        QMessageBox.critical(
                            self.app_window,
                            tr("errors.error"),
                            tr("errors.mod_import_failed", error="Conversion failed"),
                        )
                    return
                config_path_to_read = os.path.join(content_path, MOD_CONFIG_FILENAME)
                if os.path.exists(config_path_to_read):
                    with open(config_path_to_read, encoding="utf-8") as f:
                        config = json.load(f)
                    mod_id = config.get("id")
                    mod_name = config.get("name", "Unknown")

                    if not mod_id:
                        mod_id = f"local_{sanitize_filename(mod_name).lower().replace(' ', '_')}"
                        config["id"] = mod_id
                        save_json(config_path_to_read, config, indent=2)

                    existing_mod_ids = {
                        get_mod_id(m)
                        for m in self.app_state.all_mods
                        if get_mod_id(m)
                    }
                    if mod_id in existing_mod_ids:
                        self._merge_into_existing_mod(
                            mod_id, content_path, file_path, mod_name
                        )
                        return

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
                        config_path = target_config_path
                        config_updated = False
                        icon_path = os.path.join(target_mod_dir, "_icon.png")
                        if not os.path.exists(icon_path):
                            icon_path = os.path.join(target_mod_dir, "icon.png")
                        if os.path.exists(icon_path) and (not config.get("icon")):
                            config["icon"] = (
                                "_icon.png"
                                if os.path.basename(icon_path) == "_icon.png"
                                else "icon.png"
                            )
                            config_updated = True
                        from utils.mod_config_parser import normalize_mod_config_data

                        config_updated = normalize_mod_config_data(
                            config, mod_root_path=target_mod_dir
                        ) or config_updated
                        if config_updated:
                            save_json(config_path, config, indent=2)
                        self._refresh_mod_list()
                        QMessageBox.information(
                            self.app_window,
                            tr("dialogs.success"),
                            tr("status.mod_imported_success"),
                        )
                    except Exception as e:
                        logging.error(
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
            logging.error(f"[IMPORT] Mod import failed: {e}", exc_info=True)
            self._show_import_error_with_manual_install(
                file_path, tr("errors.mod_import_failed", error=str(e))
            )

    def _merge_into_existing_mod(
        self, mod_id: str, content_path: str, file_path: str, mod_name: str
    ):
        """Merge imported mod into mod_versions of existing mod with the same id."""
        try:
            existing_mod_folder = self.mod_service.get_mod_folder_path(mod_id)
            if not existing_mod_folder or not os.path.isdir(existing_mod_folder):
                existing_mod_folder = self._find_mod_dir_by_id(mod_id)
            if not existing_mod_folder or not os.path.isdir(existing_mod_folder):
                logging.error(
                    f"[IMPORT MERGE] Could not find folder for existing mod id={mod_id}"
                )
                QMessageBox.critical(
                    self.app_window,
                    tr("errors.error"),
                    tr(
                        "errors.mod_import_failed",
                        error="Existing mod folder not found",
                    ),
                )
                return
            from utils.mod_version_utils import (
                create_version_zip,
                ensure_versions_dir,
            )

            archive_base = os.path.splitext(os.path.basename(file_path))[0]
            version_name = archive_base or mod_name or "imported"
            ensure_versions_dir(existing_mod_folder)
            create_version_zip(
                content_path,
                existing_mod_folder,
                version_name,
                ignore_versions_dir=True,
            )
            self._refresh_mod_list()
            QMessageBox.information(
                self.app_window,
                tr("dialogs.success"),
                tr(
                    "status.mod_merged_as_version",
                    mod_name=mod_name,
                    version_name=version_name,
                ),
            )
        except Exception as e:
            logging.error(
                f"[IMPORT MERGE] Failed to merge mod into versions: {e}", exc_info=True
            )
            QMessageBox.critical(
                self.app_window,
                tr("errors.error"),
                tr("errors.mod_import_failed", error=str(e)),
            )

    def _find_mod_dir_by_id(self, mod_id: str):
        """Find mod directory by id in mods_dir."""
        if not os.path.exists(self.app_state.mods_dir):
            return None
        for entry in os.scandir(self.app_state.mods_dir):
            if not entry.is_dir():
                continue
            config_path = os.path.join(entry.path, MOD_CONFIG_FILENAME)
            if not os.path.exists(config_path):
                continue
            try:
                with open(config_path, encoding="utf-8") as f:
                    config = json.load(f)
                if config.get("id") == mod_id:
                    return entry.path
            except Exception as e:
                logging.debug(
                    f"_find_mod_dir_by_id: failed to read {config_path}: {e}",
                    exc_info=True,
                )
        return None

    def _install_mod_from_url(self, url: str):
        try:
            from workers.install.url_install_worker import UrlInstallThread

            worker = UrlInstallThread(self.app_window, url)
            worker.status.connect(
                lambda msg, color: self.app_window.feedback_service.update_status(
                    msg, color
                )
            )
            worker.progress.connect(
                lambda p: setattr(self.app_state, "progress_bar_value", p)
            )
            worker.finished.connect(self._on_mod_install_finished)
            worker.manual_install_required.connect(self._on_manual_install_required)
            self.app_state.is_installing = True
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.current_task = worker
            worker.start()
        except Exception as e:
            logging.error(
                f"ModImportExportController: Error installing mod from URL: {e}",
                exc_info=True,
            )
            self.app_window.feedback_service.show_message(
                "error", "errors.error", tr("mods.installation_error", error=str(e))
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
            logging.error(
                f"Failed to open manual install dialog from URL: {e}", exc_info=True
            )
            self.app_window.feedback_service.show_message(
                "error",
                tr("errors.error"),
                tr("errors.manual_install_failed", error=str(e)),
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
            logging.error(f"Manual install from file failed: {e}", exc_info=True)
            QMessageBox.critical(
                self.app_window,
                tr("errors.error"),
                tr("errors.manual_install_failed", error=str(e)),
            )

    def _prepare_local_files_for_manual_install(
        self, file_path: str
    ) -> tuple[str, str]:
        temp_dir = tempfile.mkdtemp(prefix="deltahub_manual_install_")
        try:
            return (self._materialize_local_import(file_path, temp_dir), temp_dir)
        except Exception as e:
            logging.error(f"Failed to prepare local files: {e}", exc_info=True)
            with contextlib.suppress(Exception):
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def _materialize_local_import(self, file_path: str, temp_dir: str) -> str:
        if os.path.isdir(file_path):
            return unwrap_single_directory_chain(file_path)
        try:
            extract_archive(file_path, temp_dir)
        except shutil.ReadError:
            return file_path
        except Exception as exc:
            raise ValueError(
                f"_materialize_local_import failed to extract archive '{file_path}': {exc}"
            ) from exc
        return unwrap_single_directory_chain(temp_dir)

    def _on_mod_install_finished(self, success: bool, message: str):
        self.app_state.reset_install_state()
        if success:
            self._refresh_mod_list()
            self.app_window.feedback_service.update_status(message, "green")
            QMessageBox.information(self.app_window, tr("dialogs.success"), message)
        else:
            logging.warning(f"Mod installation failed: {message}")
            self.app_window.feedback_service.update_status(
                message or tr("errors.error"), "red"
            )
            self.app_window.feedback_service.show_message(
                "error", "errors.error", message
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
                with open(config_path, encoding="utf-8") as f:
                    config = json.load(f)
                config_mod_id = config.get("id")
                if config_mod_id == mod_id_attr:
                    return entry.path
                if not config_mod_id and config.get("name", "") == mod.name:
                    return entry.path
            except Exception as e:
                logging.warning(f"Error reading config {config_path}: {e}")
        return None

    def import_files_sequentially(self, file_paths: list):
        """Queue archive files for sequential import (drag & drop)."""
        if not file_paths:
            return
        self._import_queue.extend(file_paths)
        if not self._importing:
            self._process_next_import()

    def _process_next_import(self):
        if not self._import_queue:
            self._importing = False
            return
        self._importing = True
        file_path = self._import_queue.pop(0)
        try:
            self._install_mod_from_file(file_path)
        except Exception as e:
            logging.error(
                f"[DND IMPORT] Failed to import {file_path}: {e}", exc_info=True
            )
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(100, self._process_next_import)

    def export_mod_to_path(self, mod_data, export_path: str) -> bool:
        """Export a mod to a specific zip path (for drag & drop export)."""
        try:
            mod_id = get_mod_id(mod_data)
            mod_dir = self.mod_service.get_mod_folder_path(mod_id)
            if not mod_dir or not os.path.exists(mod_dir):
                mod_dir = self._find_mod_dir_by_config(mod_data)
            if not mod_dir or not os.path.exists(mod_dir):
                logging.error(
                    f"[DND EXPORT] Mod folder not found for: {getattr(mod_data, 'name', mod_id)}"
                )
                return False
            with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, _dirs, files in os.walk(mod_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, mod_dir)
                        zipf.write(file_path, arcname)
            return True
        except Exception as e:
            logging.error(f"[DND EXPORT] Mod export failed: {e}", exc_info=True)
            return False
