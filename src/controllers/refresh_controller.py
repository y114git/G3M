import logging
from PyQt6.QtCore import QTimer
from managers.localization_manager import localization_manager, tr
from workers.fetch_mods import FetchModsThread
from config.constants import UI_COLORS
from utils.game_utils import is_game_running
from utils.thread_utils import safe_stop_thread


class RefreshController:

    def __init__(self, app_state, feedback_manager, mod_manager, slot_manager, game_launch_controller, update_checker, settings_manager=None):
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.mod_manager = mod_manager
        self.slot_manager = slot_manager
        self.game_launch_controller = game_launch_controller
        self.update_checker = update_checker
        self.settings_manager = settings_manager
        self.fetch_thread = None

    def _set_combo_silently(self, combo, operation):
        combo.blockSignals(True)
        try:
            operation()
        finally:
            combo.blockSignals(False)

    def refresh_mods_list(self, is_initial=False, language_combo=None, retranslate_callback=None, on_fetch_finished_kwargs=None):
        try:
            if language_combo is not None:
                current_lang_code = localization_manager.get_current_language()
                localization_manager.rescan_languages()

                def _populate_combo():
                    language_combo.clear()
                    for code, name in localization_manager.get_available_languages().items():
                        language_combo.addItem(name, code)
                    index = language_combo.findData(current_lang_code)
                    if index != -1:
                        language_combo.setCurrentIndex(index)
                self._set_combo_silently(language_combo, _populate_combo)
            if not is_initial and retranslate_callback:
                retranslate_callback()
            if is_game_running():
                self.feedback_manager.update_status(tr('status.cant_update_while_running'), UI_COLORS['status_warning'])
                return
            self._stop_fetch_thread()
            QTimer.singleShot(0, self.update_checker.check_for_updates)

            class FetchContext:

                def __init__(self, app_state, mod_manager, settings_manager):
                    self.app_state = app_state
                    self.mod_manager = mod_manager
                    self.settings_manager = settings_manager
            fetch_context = FetchContext(self.app_state, self.mod_manager, self.settings_manager)
            self.fetch_thread = FetchModsThread(fetch_context, force_update=True, parent=None)
            self.fetch_thread.status.connect(self.feedback_manager.update_status)
            finished_kwargs = on_fetch_finished_kwargs or {}
            self.fetch_thread.result.connect(lambda success: self._on_fetch_finished(success, retranslate_callback=retranslate_callback, **finished_kwargs))
            self.fetch_thread.start()
        except Exception as e:
            error_msg = f'Failed to refresh mods list: {e}'
            logging.error(f'RefreshController.refresh_mods_list: {error_msg}', exc_info=True)
            self.feedback_manager.update_status(f"{tr('errors.update_list_failed')}: {str(e)}", UI_COLORS['status_error'])

    def _stop_fetch_thread(self):
        if self.fetch_thread:
            safe_stop_thread(self.fetch_thread)
            if not (self.fetch_thread and self.fetch_thread.isRunning()):
                self.fetch_thread = None

    def _on_fetch_finished(self, success: bool, retranslate_callback=None, update_filtered_mods_callback=None, update_installed_mods_callback=None, update_action_button_callback=None, update_plugin_tabs_callback=None, mods_loaded_signal=None):
        try:
            self.mod_manager.load_local_mods()
            if update_filtered_mods_callback:
                update_filtered_mods_callback()
            if not self.app_state.mods_loaded:
                self.app_state.mods_loaded = True
                if mods_loaded_signal:
                    mods_loaded_signal.emit()
            if update_installed_mods_callback:
                update_installed_mods_callback()
            self.game_launch_controller.refresh_mods_in_use()
            if update_action_button_callback:
                update_action_button_callback()
            if success:
                self.feedback_manager.update_status(tr('status.mod_list_updated'), UI_COLORS['status_success'])
            else:
                fallback_msg = tr('ui.network_fallback_message') if self.app_state.all_mods else tr('ui.network_update_failed')
                self.feedback_manager.update_status(fallback_msg, UI_COLORS['status_error'])
            QTimer.singleShot(100, self.slot_manager.load_used_mods_state)
            if update_plugin_tabs_callback:
                update_plugin_tabs_callback()
        except Exception as e:
            error_msg = f'Error processing mod list: {e}'
            logging.error(f'RefreshController._on_fetch_finished: {error_msg}', exc_info=True)
            self.feedback_manager.update_status(tr('errors.mod_list_processing_error', error=str(e)), UI_COLORS['status_error'])
