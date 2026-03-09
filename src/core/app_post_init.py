"""Post-show initialization logic extracted from AppWindow."""
import os
import logging
from config.constants import UI_COLORS, CLOUD_FUNCTIONS_BASE_URL
from services.localization_service import tr
from services.game_detection_service import is_game_running
from utils.network_utils import get_session, check_internet_connection


def post_show_initialization(app):
    """Run post-show init: internet check, global settings, config restore, mod scan."""
    is_first_launch = not app.app_state.local_config.get('first_launch_splash_shown', False)
    if is_first_launch and getattr(app, '_splash_was_shown', False):
        app.app_state.local_config['first_launch_splash_shown'] = True
        app.app_state.local_config['disable_splash'] = True
        app.settings_service.write_local_config()
    app.app_state.has_internet = check_internet_connection()
    if not app.app_state.has_internet:
        logging.info('No internet connection detected, running in offline mode')
        app.app_state.global_settings = {}
    else:
        app._init_session()
        try:
            import requests
            response = get_session(app.app_state).get(f'{CLOUD_FUNCTIONS_BASE_URL}/getGlobalSettings', timeout=5)
            if response.status_code == 200:
                app.app_state.global_settings = response.json() or {}
        except requests.RequestException:
            app.feedback_service.update_status(tr('status.global_settings_load_failed'), UI_COLORS['status_warning'])
            app.app_state.has_internet = False
    if app.app_state.has_internet:
        app.app_state.pending_announce_check = True
    if is_game_running():
        app.feedback_service.update_status(tr('status.deltarune_already_running'), UI_COLORS['status_error'])
        return
    app._load_local_data()
    app.app_state.game_path = app.app_state.local_config.get('game_path', '')
    app.app_state.demo_game_path = app.app_state.local_config.get('demo_game_path', '')
    app.app_state.undertale_game_path = app.app_state.local_config.get('undertale_game_path', '')
    _restore_ui_state_from_config(app)
    try:
        from workers.mod_scan_worker import ModScanThread
        from utils.path_utils import get_user_data_root
        cache_dir = os.path.join(get_user_data_root(), 'cache')
        app._mod_scan_thread = ModScanThread(app.app_state.mods_dir, app, cache_dir=cache_dir)
        app._mod_scan_thread.scan_completed.connect(app._on_mod_scan_finished)
        app._mod_scan_thread.start()
        app.status_label.setText(tr('status.scanning_mods'))
    except Exception as e:
        logging.error(f'AppWindow: Failed to start mod scan thread: {e}', exc_info=True)
        app.feedback_service.update_status(tr('status.mod_scan_init_error', details=str(e)), UI_COLORS['status_error'])
        try:
            app._on_mod_scan_finished({})
        except Exception as scan_error:
            logging.error(f'AppWindow: Failed to handle mod scan error: {scan_error}', exc_info=True)
    if not app.game_launcher._find_and_validate_game_path(is_initial=True):
        app.action_button.setEnabled(False)


def _restore_ui_state_from_config(app):
    """Restore checkbox and combo states from local_config."""
    config = app.app_state.local_config
    saved_demo_mode = config.get('demo_mode_enabled', False)
    saved_chapter_mode = config.get('chapter_mode_enabled', False)
    if hasattr(app, 'game_type_combo') and saved_demo_mode:
        app.game_type_combo.blockSignals(True)
        for i in range(app.game_type_combo.count()):
            if app.game_type_combo.itemData(i) == 'deltarunedemo':
                app.game_type_combo.setCurrentIndex(i)
                break
        app.game_type_combo.blockSignals(False)
    if hasattr(app, 'chapter_mode_checkbox'):
        app._set_checkbox_checked_silently(app.chapter_mode_checkbox, saved_chapter_mode)
    app._set_checkbox_checked_silently(app.disable_background_checkbox, config.get('background_disabled', False))
    app._set_checkbox_checked_silently(app.disable_splash_checkbox, config.get('disable_splash', False))
    app.beta_updates_checkbox.setChecked(config.get('beta_updates_enabled', False))
    app.fullscreen_checkbox.setChecked(config.get('fullscreen_enabled', False))
    if hasattr(app, 'hide_library_filters_checkbox'):
        app.hide_library_filters_checkbox.setChecked(config.get('hide_library_filters', False))
    app._update_change_path_button_text()
    app.theme.update_background_button_state()
    app.skip_patching_warnings_checkbox.setChecked(config.get('skip_patching_warnings', False))
    app.launch_via_steam_checkbox.setChecked(config.get('launch_via_steam', False))
    app.dont_hide_window_checkbox.setChecked(config.get('dont_hide_window_on_launch', False))
    if app.use_portproton_checkbox:
        app.use_portproton_checkbox.setChecked(config.get('use_portproton', False))
        app._update_portproton_ui()
    for key in ('merge_properties', 'merge_code'):
        if (w := getattr(app, f'{key}_checkbox', None)):
            w.setChecked(config.get(key, False))
    app._initialize_mutual_exclusions()
    app.settings_ui.on_toggle_steam_launch()
    app.theme.apply_theme()
