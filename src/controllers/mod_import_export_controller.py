"""Controller for mod import and export operations."""

import contextlib
import json
import logging
import os
import shutil
import tempfile
import zipfile

from PyQt6.QtWidgets import QDialog, QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout

from config.constants import LEGACY_MOD_CONFIG_FILENAME, MOD_CONFIG_FILENAME
from services.localization_service import tr
from utils.archive_utils import extract_archive
from utils.file_utils import find_deltamod_info_file, save_json
from utils.mod_utils import get_mod_key


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
        self.mod_service.load_local_mods(_skip_conversion=True)
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

        key = get_mod_key(mod_data)
        if not key:
            return
        mod_folder = self.mod_service.get_mod_folder_path(key)
        if not mod_folder or not os.path.exists(mod_folder):
            mod_folder = self._find_mod_dir_by_config(mod_data)
        config_data = {}
        if mod_folder:
            config_path = os.path.join(mod_folder, MOD_CONFIG_FILENAME)
            legacy_config_path = os.path.join(mod_folder, LEGACY_MOD_CONFIG_FILENAME)

            if os.path.exists(config_path):
                try:
                    with open(config_path, encoding="utf-8") as f:
                        config_data = json.load(f)
                except Exception as e:
                    if os.path.exists(legacy_config_path):
                        try:
                            with open(legacy_config_path, encoding="utf-8") as f:
                                config_data = json.load(f)
                        except Exception as legacy_e:
                            raise RuntimeError(
                                f"Failed to load both {MOD_CONFIG_FILENAME} and {LEGACY_MOD_CONFIG_FILENAME}: {e}, {legacy_e}"
                            ) from legacy_e
                    else:
                        raise RuntimeError(
                            f"Failed to load {MOD_CONFIG_FILENAME}: {e}"
                        ) from e
            elif os.path.exists(legacy_config_path):
                try:
                    with open(legacy_config_path, encoding="utf-8") as f:
                        config_data = json.load(f)
                except Exception as e:
                    raise RuntimeError(
                        f"Failed to load {LEGACY_MOD_CONFIG_FILENAME}: {e}"
                    ) from e

        if not config_data:
            raise RuntimeError(f"No valid config found in mod folder: {mod_folder}")

        config_data["key"] = key
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
                extract_archive(file_path, temp_dir)
                content_path = temp_dir
                contents = os.listdir(temp_dir)
                if len(contents) == 1 and os.path.isdir(
                    os.path.join(temp_dir, contents[0])
                ):
                    content_path = os.path.join(temp_dir, contents[0])
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
                if not os.path.exists(config_path_to_read):
                    legacy_config_path = os.path.join(
                        content_path, LEGACY_MOD_CONFIG_FILENAME
                    )
                    if os.path.exists(legacy_config_path):
                        config_path_to_read = legacy_config_path
                if os.path.exists(config_path_to_read):
                    with open(config_path_to_read, encoding="utf-8") as f:
                        config = json.load(f)
                    key = config.get("key") or config.get("mod_key")
                    mod_name = config.get("name", "Unknown")

                    if not key:
                        key = f"local_{sanitize_filename(mod_name).lower().replace(' ', '_')}"
                        config["key"] = key
                        config.pop("mod_key", None)
                        save_json(config_path_to_read, config, indent=2)

                    existing_keys = {
                        get_mod_key(m)
                        for m in self.app_state.all_mods
                        if get_mod_key(m)
                    }
                    if key in existing_keys:
                        self._merge_into_existing_mod(
                            key, content_path, file_path, mod_name
                        )
                        return

                    archive_name = remove_archive_extension(os.path.basename(file_path))
                    folder_name = sanitize_filename(archive_name)
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
                        target_old_config_path = os.path.join(
                            target_mod_dir, LEGACY_MOD_CONFIG_FILENAME
                        )
                        if os.path.exists(target_old_config_path) and (
                            not os.path.exists(target_config_path)
                        ):
                            try:
                                shutil.move(target_old_config_path, target_config_path)
                            except Exception as e:
                                logging.warning(
                                    f"Failed to migrate config during import: {e}"
                                )
                        config_path = target_config_path
                        config_updated = False
                        if "files" in config:
                            for chapter_key, chapter_data in config["files"].items():
                                if chapter_key == "demo":
                                    chapter_folder = os.path.join(
                                        target_mod_dir, "demo"
                                    )
                                elif chapter_key == "undertale":
                                    chapter_folder = os.path.join(
                                        target_mod_dir, "undertale"
                                    )
                                elif chapter_key in ["0", "1", "2", "3", "4"]:
                                    chapter_id = int(chapter_key)
                                    from utils.file_utils import get_chapter_folder_name

                                    folder_name = get_chapter_folder_name(
                                        chapter_id,
                                        game=config.get("game")
                                        or config.get("modgame"),
                                    )
                                    chapter_folder = os.path.join(
                                        target_mod_dir, folder_name
                                    )
                                else:
                                    continue
                                if os.path.exists(
                                    chapter_folder
                                ) and not chapter_data.get("data_file_url"):
                                    from utils.patching.mod_content_utils import (
                                        find_ready_data_win_files,
                                    )

                                    if files := find_ready_data_win_files(
                                        chapter_folder
                                    ):
                                        chapter_data["data_file_url"] = (
                                            os.path.basename(files[0])
                                        )
                                        config_updated = True
                        icon_path = os.path.join(target_mod_dir, "_icon.png")
                        if not os.path.exists(icon_path):
                            icon_path = os.path.join(target_mod_dir, "icon.png")
                        if os.path.exists(icon_path) and (not config.get("icon_url")):
                            config["icon_url"] = (
                                "_icon.png"
                                if os.path.basename(icon_path) == "_icon.png"
                                else "icon.png"
                            )
                            config_updated = True
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
        self, key: str, content_path: str, file_path: str, mod_name: str
    ):
        """Merge imported mod into mod_versions of existing mod with the same key."""
        try:
            existing_mod_folder = self.mod_service.get_mod_folder_path(key)
            if not existing_mod_folder or not os.path.isdir(existing_mod_folder):
                existing_mod_folder = self._find_mod_dir_by_key(key)
            if not existing_mod_folder or not os.path.isdir(existing_mod_folder):
                logging.error(
                    f"[IMPORT MERGE] Could not find folder for existing mod key={key}"
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

    def _find_mod_dir_by_key(self, key: str):
        """Find mod directory by key in mods_dir."""
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
                if (config.get("key") or config.get("mod_key")) == key:
                    return entry.path
            except Exception as e:
                logging.debug(
                    f"_find_mod_dir_by_key: failed to read {config_path}: {e}",
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

    def _open_manual_install_dialog(
        self, prepared_path, source_file_path, temp_dir, on_accept=None
    ):
        from services.game_detection_service import get_game_type_string
        from ui.dialogs.manual_install_dialog import ManualModInstallDialog

        initial_game_type = None
        if self.app_state and hasattr(self.app_state, "game_mode"):
            initial_game_type = get_game_type_string(self.app_state.game_mode)
        dialog = ManualModInstallDialog(
            self.app_window,
            prepared_path,
            gamebanana_metadata=None,
            source_file_path=source_file_path,
            initial_game_type=initial_game_type,
        )
        dialog.temp_dir_to_cleanup = temp_dir
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if on_accept:
                on_accept()
            else:
                self._refresh_mod_list()
            QMessageBox.information(
                self.app_window,
                tr("dialogs.success"),
                tr("dialogs.mod_created_successfully"),
            )
            return True
        return False

    def _on_manual_install_required(
        self, prepared_path: str, archive_path: str, temp_dir: str
    ):
        try:
            self.app_state.reset_install_state()

            def _on_accept():
                from ui.utils.ui_utils import refresh_ui_after_mod_install

                refresh_ui_after_mod_install(self.app_window, self.mod_service)

            self._open_manual_install_dialog(
                prepared_path, archive_path, temp_dir, on_accept=_on_accept
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
        msg_box = QMessageBox(self.app_window)
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle(tr("errors.error"))
        msg_box.setText(error_message)
        msg_box.setInformativeText(tr("dialogs.manual_install_available"))
        manual_install_btn = msg_box.addButton(
            tr("ui.manual_install"), QMessageBox.ButtonRole.AcceptRole
        )
        ok_btn = msg_box.addButton(tr("buttons.ok"), QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(ok_btn)
        msg_box.exec()
        if msg_box.clickedButton() == manual_install_btn:
            self._start_manual_install_from_file(file_path)

    def _start_manual_install_from_file(self, file_path: str):
        try:
            prepared_path, temp_dir = self._prepare_local_files_for_manual_install(
                file_path
            )
            if prepared_path:
                self._open_manual_install_dialog(prepared_path, file_path, temp_dir)
        except Exception as e:
            logging.error(f"Manual install from file failed: {e}", exc_info=True)
            QMessageBox.critical(
                self.app_window,
                tr("errors.error"),
                tr("errors.manual_install_failed", error=str(e)),
            )

    def _prepare_local_files_for_manual_install(self, file_path: str) -> str:
        temp_dir = tempfile.mkdtemp(prefix="deltahub_manual_install_")
        try:
            extract_archive(file_path, temp_dir)
            content_path = temp_dir
            contents = os.listdir(temp_dir)
            if len(contents) == 1 and os.path.isdir(
                os.path.join(temp_dir, contents[0])
            ):
                content_path = os.path.join(temp_dir, contents[0])
            return (content_path, temp_dir)
        except Exception as e:
            logging.error(f"Failed to prepare local files: {e}", exc_info=True)
            with contextlib.suppress(Exception):
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise

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
        mod_key_attr = get_mod_key(mod)
        for entry in os.scandir(self.app_state.mods_dir):
            if not entry.is_dir():
                continue
            config_path = os.path.join(entry.path, MOD_CONFIG_FILENAME)
            if not os.path.exists(config_path):
                old_config_path = os.path.join(entry.path, LEGACY_MOD_CONFIG_FILENAME)
                if os.path.exists(old_config_path):
                    try:
                        shutil.move(old_config_path, config_path)
                    except Exception as e:
                        logging.warning(f"Error migrating config in {entry.path}: {e}")
                        continue
            if not os.path.exists(config_path):
                continue
            try:
                with open(config_path, encoding="utf-8") as f:
                    config = json.load(f)
                config_key = config.get("key") or config.get("mod_key")
                if config_key == mod_key_attr:
                    return entry.path
                if not config_key and config.get("name", "") == mod.name:
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
            key = get_mod_key(mod_data)
            mod_dir = self.mod_service.get_mod_folder_path(key)
            if not mod_dir or not os.path.exists(mod_dir):
                mod_dir = self._find_mod_dir_by_config(mod_data)
            if not mod_dir or not os.path.exists(mod_dir):
                logging.error(
                    f"[DND EXPORT] Mod folder not found for: {getattr(mod_data, 'name', key)}"
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
