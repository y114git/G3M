"""Controller for mod installation and operation management."""

import contextlib
import logging
import os
import shutil

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog

from adapters.gamebanana_adapter import GameBananaAPI
from config.config import UI_COLORS
from services.localization_service import tr
from ui.dialogs.file_picker_dialog import GameBananaFilePickerDialog
from ui.widgets.mod.installed_mod_widget import InstalledModWidget
from utils.mod_utils import (
    get_gamebanana_item_type,
    get_gamebanana_mod_id,
    get_mod_id,
    get_mod_name,
    sort_gamebanana_files_by_priority,
)
from workers.install.batch_install_worker import InstallModsThread


class ModOperationsController:
    """Manages mod installation operations and related workflows."""

    def __init__(self, app_state, feedback_service, mod_service, app_window) -> None:
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.mod_service = mod_service
        self.app = app_window
        from ui.utils.ui_utils import DebounceTimer

        self._update_debounce_short = DebounceTimer(delay_ms=200)
        self._update_debounce_long = DebounceTimer(delay_ms=1000)

    def _safe_execute(self, func, error_msg_prefix="", default_return=None):
        try:
            return func()
        except (AttributeError, RuntimeError) as e:
            logging.debug(f"{error_msg_prefix}: {e}", exc_info=True)
            return default_return
        except Exception as e:
            logging.debug(f"{error_msg_prefix}: {e}")
            return default_return

    @staticmethod
    def _disconnect_task_signals(task) -> None:
        for sig_name in ("progress", "status", "finished"):
            if hasattr(task, sig_name):
                with contextlib.suppress(TypeError, RuntimeError):
                    getattr(task, sig_name).disconnect()

    def _pick_gamebanana_file(self, available_files, mod_name, homepage):
        available_files = sort_gamebanana_files_by_priority(available_files)
        if len(available_files) <= 1:
            return available_files[0] if available_files else None
        dialog = GameBananaFilePickerDialog(
            self.app, available_files, mod_name, homepage
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.feedback_service.update_status(
                tr("status.operation_cancelled"), UI_COLORS["status_warning"]
            )
            return None
        return dialog.get_selected_file() or available_files[0]

    def _handle_install_start_error(self, error: Exception) -> None:
        self.app_state.is_installing = False
        self.set_install_buttons_enabled(True)
        self.app_state.clear_current_task()
        self._safe_execute(
            lambda: self.app.game_launch.update_button_state(),
            "Failed to update button state",
        )
        self.feedback_service.show_message(
            "error", "errors.gamebanana_install_failed", error=str(error)
        )

    def on_mod_download_requested(self, mod):
        if self.app_state.is_installing:
            logging.debug(
                "ModOperationsController: Installation already in progress, ignoring request"
            )
            return
        if self.app_state.current_task and self.app_state.current_task.isRunning():
            logging.debug(
                "ModOperationsController: Previous task still running, ignoring request"
            )
            return
        self.install_mod(mod)

    def _install_gamebanana_mod(
        self, mod, force=False, is_update=False, selected_file=None
    ):
        try:
            self._enqueue_gamebanana_download(mod, selected_file)
        except Exception as e:
            logging.error(
                f"Error starting GameBanana mod installation: {e}", exc_info=True
            )
            self._handle_install_start_error(e)

    def _enqueue_gamebanana_download(self, mod, selected_file=None):
        """Route a GameBanana mod install through the Downloads system."""
        from models.download_models import SourceKind, TargetKind

        mod_id_str = get_gamebanana_mod_id(mod)
        if not mod_id_str:
            self.feedback_service.show_message(
                "error", "errors.invalid_gamebanana_mod_id"
            )
            return
        mod_id = int(mod_id_str)
        itemtype = get_gamebanana_item_type(mod)
        item_type_lower = "wip" if itemtype == "Wip" else "mod"
        download_url = None
        file_id = None
        file_name = None
        compatibility = None
        if selected_file:
            download_url = selected_file.get("download_url") or selected_file.get(
                "_sDownloadUrl"
            )
            file_id = selected_file.get("id") or selected_file.get("_idRow")
            file_name = selected_file.get("name") or selected_file.get("_sFile")
            compatibility = selected_file.get("compatibility")
        if not download_url:
            self.feedback_service.show_message("error", "errors.no_download_url")
            return
        canonical_key = (
            f"gb_{item_type_lower}_{mod_id}_{file_id}"
            if file_id
            else f"gb_{item_type_lower}_{mod_id}"
        )
        metadata = {
            "gb_mod_id": mod_id,
            "item_type": item_type_lower,
            "gb_file_id": file_id,
            "file_name": file_name,
            "compatibility": compatibility,
            "name": getattr(mod, "name", None),
            "author": getattr(mod, "author", None),
            "version": getattr(mod, "version", None),
            "description": getattr(mod, "description", None),
            "homepage": getattr(mod, "homepage", None),
            "icon": getattr(mod, "icon", None),
            "tags": getattr(mod, "tags", None) or [],
            "category": getattr(mod, "gamebanana_category", None),
            "game": getattr(mod, "game", "deltarune"),
        }
        display_name = get_mod_name(mod, file_name or f"GameBanana mod {mod_id}")
        self.app.downloads_manager.enqueue_with_feedback(
            self.feedback_service,
            display_name=display_name,
            source_kind=SourceKind.GAMEBANANA,
            target_kind=TargetKind.MOD,
            source_url=download_url,
            canonical_key=canonical_key,
            metadata=metadata,
        )
        self._safe_execute(
            lambda: self.app.search_display.update_search_cards(),
            "Failed to refresh cards",
        )

    def _start_install_thread(self, install_thread, op_id: int):
        try:
            self.app_state.is_installing = True
            self.app_state._scan_blocked = True
            self.set_install_buttons_enabled(False)
            self.app.action_button.setText(tr("ui.cancel_button"))
            install_thread.progress.connect(
                lambda v, oid=op_id: self.on_install_progress_token(v, oid)
            )
            install_thread.status.connect(
                lambda msg, col, oid=op_id: self.on_install_status_token(msg, col, oid)
            )
            install_thread.finished.connect(
                lambda ok, oid=op_id: self._on_install_task_finished(ok, oid)
            )
            self.app.progress_bar.setVisible(True)
            self.app.progress_bar.setValue(0)
            self._safe_execute(
                lambda: self.feedback_service.update_status(
                    tr("status.preparing_download"), UI_COLORS["status_warning"]
                ),
                "Feedback manager update failed",
            )
            self.app_state.current_task = install_thread
            self.app.game_launch.update_button_state()
            install_thread.start()
            logging.info(
                f"ModOperationsController: Started mod installation thread (op_id={op_id})"
            )
        except Exception as e:
            logging.error(f"Error starting install thread: {e}", exc_info=True)
            self._handle_install_start_error(e)

    def _get_available_gamebanana_files(self, mod) -> list[dict]:
        files = getattr(mod, "gamebanana_supported_files", []) or []
        if files:
            files = sort_gamebanana_files_by_priority(files)
            mod.gamebanana_supported_files = files
            self._notify_gamebanana_card_refresh()
            return files
        mod_id_str = get_gamebanana_mod_id(mod)
        if not mod_id_str:
            return []
        mod_id = int(mod_id_str)
        try:
            api = GameBananaAPI()
            itemtype = get_gamebanana_item_type(mod)
            compat = api.get_supported_files_for_mod(mod_id, itemtype=itemtype)
            files = sort_gamebanana_files_by_priority(
                compat.get("supported_files") or []
            )
            if files:
                mod.gamebanana_supported_files = files
                mod.gamebanana_compatibility_checked = compat.get(
                    "compatibility_checked", False
                )
                self._notify_gamebanana_card_refresh()
            return files
        except Exception as e:
            logging.warning(
                f"ModOperationsController: Failed to refresh GameBanana files for {mod_id}: {e}"
            )
            return []

    def _get_all_gamebanana_files(self, mod) -> list[dict]:
        mod_id_str = get_gamebanana_mod_id(mod)
        if not mod_id_str:
            return []
        mod_id = int(mod_id_str)
        try:
            api = GameBananaAPI()
            itemtype = get_gamebanana_item_type(mod)
            all_files = api.get_mod_files(mod_id, itemtype=itemtype)
            if not all_files:
                return []
            formatted_files = []
            for file_data in all_files:
                file_id = file_data.get("_idRow")
                if not file_id:
                    for key in file_data:
                        if key.isdigit():
                            file_id = int(key)
                            break
                if not file_id:
                    logging.warning(
                        f"ModOperationsController: Could not extract file_id from file_data: {file_data}"
                    )
                    continue
                has_contents = file_data.get("_bHasContents", True)
                if not has_contents:
                    continue
                file_name = (
                    file_data.get("_sFile")
                    or file_data.get("_sName")
                    or file_data.get("name")
                    or f"file_{file_id}"
                )
                download_url = file_data.get("_sDownloadUrl") or file_data.get(
                    "download_url"
                )
                if not download_url:
                    download_url = f"https://gamebanana.com/dl/{file_id}"
                    logging.debug(
                        f"ModOperationsController: Constructed download URL for file {file_id}: {download_url}"
                    )
                formatted_file = {
                    "id": file_id,
                    "name": file_name,
                    "download_url": download_url,
                    "_sDownloadUrl": download_url,
                    "_sFile": file_name,
                    "_idRow": file_id,
                    "_bHasContents": True,
                    "version": file_data.get("_sVersion")
                    or file_data.get("version", "1.0.0"),
                    "size_bytes": file_data.get("_nFilesize")
                    or file_data.get("size_bytes", 0),
                    "download_count": file_data.get("_nDownloadCount")
                    or file_data.get("download_count", 0),
                }
                formatted_files.append(formatted_file)
            return formatted_files
        except Exception as e:
            logging.error(
                f"ModOperationsController: Failed to get all GameBanana files for {mod_id}: {e}",
                exc_info=True,
            )
            return []

    def _notify_gamebanana_card_refresh(self):
        try:
            if hasattr(self.app, "search_display"):
                self.app.search_display.update_search_cards()
        except Exception as e:
            logging.debug("_notify_gamebanana_card_refresh failed", exc_info=e)

    def install_mod(self, mod, force=False, is_update=False):
        try:
            if self.app_state.is_installing and (not force):
                return
            if analytics := getattr(self.app, "analytics_service", None):
                analytics.record_mod_install_requested(
                    mod,
                    mode="update" if is_update else "install",
                )
            if (
                hasattr(mod, "is_gamebanana_mod")
                and callable(mod.is_gamebanana_mod)
                and mod.is_gamebanana_mod()
            ):
                available_files = self._get_available_gamebanana_files(
                    mod
                ) or self._get_all_gamebanana_files(mod)
                if not available_files:
                    self.feedback_service.show_message(
                        "warning", "errors.mod_no_files", mod_name=mod.name
                    )
                    return
                selected_file = self._pick_gamebanana_file(
                    available_files, mod.name, getattr(mod, "homepage", None)
                )
                if selected_file is None:
                    return
                self._install_gamebanana_mod(
                    mod, force, is_update, selected_file=selected_file
                )
                return
            available_chapters = []
            from models.game_modes import get_game

            game_def = get_game(mod.game)
            tab_ids = [tab.tab_id for tab in game_def.tabs] if game_def else [mod.game]
            for chapter_id in tab_ids:
                if mod.get_chapter_data(chapter_id):
                    available_chapters.append(chapter_id)
            if not available_chapters:
                self.feedback_service.show_message(
                    "warning", "errors.mod_no_files", mod_name=mod.name
                )
                return
            was_installed_before = (
                self.mod_service.is_mod_installed(mod.id) or is_update
            )
            install_tasks = [(mod, chapter_id) for chapter_id in available_chapters]
            self._safe_execute(
                lambda: setattr(self.app_state, "operation_cancelled", False),
                "Failed to set operation_cancelled",
            )
            if self.app_state.current_task:
                try:
                    self._disconnect_task_signals(self.app_state.current_task)
                except (TypeError, RuntimeError) as e:
                    logging.debug(
                        f"Failed to disconnect signals from previous task: {e}"
                    )
            self.app._install_op_id += 1
            op_id = self.app._install_op_id
            install_thread = InstallModsThread(
                self.app, install_tasks, was_installed_before
            )
            self._start_install_thread(install_thread, op_id)
        except (OSError, KeyError, Exception) as e:
            from models.exceptions import ModInstallationError

            mod_id = get_mod_id(mod)
            mod_name_str = get_mod_name(mod, "Unknown Mod")
            reason_map = {
                IOError: "io_error",
                OSError: "io_error",
                KeyError: "missing_data",
            }
            reason = reason_map.get(type(e), "unknown")
            raise ModInstallationError(
                f"{reason}: {e}",
                mod_id=mod_id,
                mod_name=mod_name_str,
                reason=reason,
            ) from e

    def on_install_progress_token(self, value: int, op_id: int):
        current_op_id = getattr(self.app, "_install_op_id", 0)
        if current_op_id == op_id and self.app_state.is_installing:
            self.app.progress_bar.setValue(value)

    def on_install_status_token(self, message: str, color: str, op_id: int):
        current_op_id = getattr(self.app, "_install_op_id", 0)
        if current_op_id == op_id and self.app_state.is_installing:
            self.app._update_status(message, color)

    def _on_install_task_finished(self, success: bool, op_id: int):
        current_op_id = getattr(self.app, "_install_op_id", 0)
        if current_op_id != op_id:
            return
        was_installed_before = False
        if self.app_state.current_task:
            was_installed_before = getattr(
                self.app_state.current_task, "was_installed_before", False
            )
        self._on_install_complete(success, "", was_installed_before)

    def _on_install_complete(
        self, success: bool, message: str = "", was_installed_before: bool = False
    ):
        current_task = self.app_state.current_task
        installed_mod_info = None
        if current_task and hasattr(current_task, "mod_info"):
            installed_mod_info = current_task.mod_info
        self.app.progress_bar.setValue(0)
        self.app.progress_bar.setVisible(False)
        self.app_state.clear_current_task()
        self.app_state.is_installing = False
        self.set_install_buttons_enabled(True)
        self._safe_execute(
            lambda: self.app.game_launch.update_button_state(),
            "Failed to update button state",
        )
        if not success:
            analytics_mod = installed_mod_info
            if analytics_mod is None and current_task:
                install_tasks = getattr(current_task, "install_tasks", []) or []
                if install_tasks:
                    analytics_mod = install_tasks[0][0]
            analytics_mode = "update" if was_installed_before else "install"
            is_cancelled = (
                message == tr("status.operation_cancelled")
                or "cancelled" in message.lower()
                or self.app_state.operation_cancelled
            )
            if is_cancelled:
                if analytics := getattr(self.app, "analytics_service", None):
                    analytics.record_mod_install_cancelled(
                        analytics_mod,
                        mode=analytics_mode,
                    )
                logging.info("ModOperationsController: Installation was cancelled")
                self._safe_execute(
                    lambda: setattr(self.app_state, "operation_cancelled", False),
                    "Failed to set operation_cancelled",
                )
                self.feedback_service.update_status(
                    tr("status.operation_cancelled"), UI_COLORS["status_warning"]
                )
            else:
                if analytics := getattr(self.app, "analytics_service", None):
                    analytics.record_mod_install_failed(
                        analytics_mod,
                        mode=analytics_mode,
                    )
                self.feedback_service.update_status(
                    tr("status.mod_install_error"), UI_COLORS["status_error"]
                )
            try:
                if current_task:
                    temp_root = getattr(current_task, "temp_root", None)
                    if temp_root and os.path.isdir(temp_root):
                        shutil.rmtree(temp_root, ignore_errors=True)
            except (AttributeError, OSError, shutil.Error) as e:
                logging.debug(f"Failed to clean temp root: {e}", exc_info=True)
            self.app.game_launch.update_button_state()
            self.app_state._scan_blocked = False
            return
        self.app_state._scan_blocked = False
        self._safe_execute(
            lambda: self.mod_service.invalidate_mods_cache(),
            "invalidate_mods_cache failed",
            default_return=None,
        )
        try:
            self.mod_service.load_local_mods()
            self.mod_service.mod_list_updated.emit()
            self._safe_execute(
                lambda: (
                    self.app.search_display.update_search_cards()
                    if hasattr(self.app, "search_display")
                    else None
                ),
                "Failed to update search cards",
            )
            if installed_mod_info and hasattr(self.app_state, "all_mods"):
                mod_id = get_mod_id(installed_mod_info)
                if mod_id:
                    self._sync_installed_mod_to_all_mods(mod_id)
        except Exception as e:
            logging.warning(
                f"ModOperationsController: Failed to reload local mods: {e}",
                exc_info=True,
            )

        def update_filtered_mods():
            try:
                if not hasattr(self.app, "search_display"):
                    return
                self.app.search_display.update_filtered_mods(preserve_page=True)
                if not (installed_mod_info and self.app_state.filtered_mods):
                    return
                mod_id = get_mod_id(installed_mod_info)
                if not mod_id:
                    return
                for mod in self.app_state.filtered_mods:
                    if get_mod_id(mod) == mod_id:
                        self._safe_execute(
                            lambda: self.app.search_display.update_display(),
                            "Failed to update display",
                        )
                        return
                logging.debug(
                    f"ModOperationsController: Installed mod {mod_id} not found in filtered_mods"
                )
            except Exception as e:
                logging.warning(
                    f"ModOperationsController: Failed to update filtered mods: {e}",
                    exc_info=True,
                )

        def check_cache_and_update():
            try:
                self.mod_service._get_mods_cache()
            except Exception as e:
                logging.warning(f"ModOperationsController: Failed to check cache: {e}")

        def update_cards_with_retry():
            try:
                self.mod_service.invalidate_mods_cache()
                self.app.search_display.update_search_cards()
            except Exception as e:
                logging.warning(
                    f"ModOperationsController: Failed to update search cards: {e}",
                    exc_info=True,
                )

        def update_library_with_retry():
            try:
                if hasattr(self.app, "library_display"):
                    self.app.library_display.update_display()
            except Exception as e:
                logging.warning(
                    f"ModOperationsController: Failed to update library display: {e}",
                    exc_info=True,
                )

        if current_task and installed_mod_info:
            self.refresh_specific_mod_widget_after_update(installed_mod_info)
        elif current_task and not installed_mod_info:
            logging.debug("ModOperationsController: current_task.mod_info was missing")
        if installed_mod_info and (
            analytics := getattr(self.app, "analytics_service", None)
        ):
            analytics.record_mod_install_completed(
                installed_mod_info,
                mode="update" if was_installed_before else "install",
            )
        self._update_debounce_short.call(check_cache_and_update)
        self._update_debounce_short.call(update_filtered_mods)
        self._update_debounce_short.call(update_cards_with_retry)
        self._update_debounce_short.call(update_library_with_retry)
        self._update_debounce_long.call(check_cache_and_update)
        if message:
            self.feedback_service.update_status(message, UI_COLORS["status_success"])
        else:
            self.feedback_service.update_status(
                tr("status.mod_installed_success"), UI_COLORS["status_success"]
            )
        if not was_installed_before:
            self._safe_execute(
                lambda: QTimer.singleShot(
                    0,
                    lambda: self.feedback_service.show_message(
                        "info", "dialogs.mod_installed_apply_info"
                    ),
                ),
                "Failed to show mod installed info",
            )
        if getattr(self.app, "pending_updates", None):
            next_mod = self.app.pending_updates.pop(0)
            QTimer.singleShot(0, lambda: self.mod_service.update_mod(next_mod))
        self.app.game_launch.update_button_state()

    def _sync_installed_mod_to_all_mods(self, mod_id: str):
        try:
            if not self.app_state.all_mods:
                self.app_state.all_mods = []
            existing_mod = next(
                (m for m in self.app_state.all_mods if get_mod_id(m) == mod_id), None
            )
            cache = self.mod_service._get_mods_cache()
            if mod_id not in cache:
                return
            config_data = cache[mod_id].config_data
            if not existing_mod:
                mod_to_add = self.mod_service.create_mod_object_from_info(
                    config_data, self.app_state.all_mods
                )
                if mod_to_add:
                    self.app_state.append_mod(mod_to_add)
            elif config_data.get("files") and (
                not hasattr(existing_mod, "files") or not existing_mod.files
            ):
                temp_mod = self.mod_service.create_mod_object_from_info(
                    config_data, self.app_state.all_mods
                )
                if hasattr(temp_mod, "files") and temp_mod.files:
                    existing_mod.files = temp_mod.files
        except Exception as e:
            logging.debug(
                f"ModOperationsController: _sync_installed_mod_to_all_mods failed for {mod_id}: {e}"
            )

    def refresh_specific_mod_widget_after_update(self, mod_info=None):
        mod_to_update = mod_info
        if mod_to_update is None:
            if not self.app_state.current_task:
                return
            install_tasks = getattr(self.app_state.current_task, "install_tasks", [])
            if not install_tasks:
                return
            mod_to_update = install_tasks[0][0]
        mod_id_to_find = get_mod_id(mod_to_update)
        if not mod_id_to_find:
            return
        if hasattr(self.app, "installed_mods_layout"):
            for i in range(self.app.installed_mods_layout.count()):
                item = self.app.installed_mods_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, InstalledModWidget):
                        widget_key = get_mod_id(widget.mod_data)
                        if widget_key == mod_id_to_find:
                            widget.update_status()
                            break
        if hasattr(self.app, "search_display"):
            for card in self.app.search_display.card_widget_cache.values():
                if get_mod_id(card.mod_data) == mod_id_to_find:
                    card.update_installation_status()

    def on_mod_uninstall_requested(self, mod):
        if self.app_state.is_installing:
            return
        if self.feedback_service.ask_question(
            "dialogs.delete_confirmation",
            "dialogs.delete_mod_confirmation",
            "",
            False,
            mod_name=mod.name,
        ):
            self.uninstall_mod(mod)

    def uninstall_mod(self, mod):
        try:
            self.mod_service.delete_mod_files(mod)
            if used_mods_service := getattr(self.app, "used_mods_service", None):
                used_mods_service.remove_mod_from_all_chapters(mod)
            if analytics := getattr(self.app, "analytics_service", None):
                analytics.record_mod_removed(mod, action="uninstall")
            if hasattr(self.app, "search_display"):
                self.app.search_display.update_search_cards()
                self.app.search_display.update_filtered_mods(preserve_page=True)
            if hasattr(self.app, "library_display"):
                self.app.library_display.update_display()
        except Exception as e:
            logging.error(
                f"ModOperationsController: Failed to uninstall mod: {e}", exc_info=True
            )
            self.feedback_service.show_message(
                "error",
                tr("errors.error"),
                tr("errors.mod_uninstall_failed", error=str(e)),
            )
            return

    def set_install_buttons_enabled(self, enabled: bool):
        button_enabled = self.app_state.is_installing or enabled
        self._safe_execute(
            lambda: self.app.action_button.setEnabled(button_enabled),
            "Failed to set install buttons enabled",
        )
