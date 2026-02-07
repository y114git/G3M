"""Handles update prompts, announcements, and global settings reload for AppWindow."""
import logging
from PyQt6.QtCore import QTimer
from services.localization_service import tr
from config.constants import CLOUD_FUNCTIONS_BASE_URL
from utils.network_utils import get_session


def handle_update_info(app, update_info, retry_count=0):
    max_retries = 15
    init_completed = app.app_state.initialization_completed
    is_shown = app.app_state.is_shown_to_user
    is_visible = app.isVisible() if hasattr(app, 'isVisible') else False
    logging.info(f'_handle_update_info: retry_count={retry_count}, initialization_completed={init_completed}, is_shown_to_user={is_shown}, is_visible={is_visible}')
    if init_completed and (is_shown or is_visible):
        logging.info(f"_handle_update_info: Conditions met, showing update prompt for version {update_info.get('version', 'unknown')}")
        if is_visible and (not is_shown):
            app.app_state.is_shown_to_user = True
            logging.info('_handle_update_info: Set app_state.is_shown_to_user=True because window is visible')
        app.show_update_prompt.emit(update_info)
    elif retry_count < max_retries:
        logging.debug(f'_handle_update_info: Conditions not met, retrying in 1 second (retry {retry_count + 1}/{max_retries})')
        QTimer.singleShot(1000, lambda: handle_update_info(app, update_info, retry_count + 1))
    else:
        logging.warning(f'Update dialog: conditions not met after max retries (init_completed={init_completed}, is_shown={is_shown}, is_visible={is_visible}), showing dialog anyway')
        app.show_update_prompt.emit(update_info)


def reload_global_settings(app):
    if not app.app_state.has_internet:
        return
    try:
        import requests
        response = get_session(app.app_state).get(f'{CLOUD_FUNCTIONS_BASE_URL}/getGlobalSettings', timeout=5)
        if response.status_code == 200:
            app.app_state.global_settings = response.json() or {}
            logging.info('_reload_global_settings: Global settings reloaded successfully')
            return True
    except requests.RequestException as e:
        logging.warning(f'_reload_global_settings: Failed to reload global settings: {e}')
    return False


def check_and_show_announce(app, retry_count=0, force_check=False):
    max_retries = 15
    init_completed = app.app_state.initialization_completed
    is_shown = app.app_state.is_shown_to_user
    is_visible = app.isVisible() if hasattr(app, 'isVisible') else False
    logging.info(f'_check_and_show_announce: retry_count={retry_count}, initialization_completed={init_completed}, is_shown_to_user={is_shown}, is_visible={is_visible}, force_check={force_check}')
    if init_completed and (is_shown or is_visible or force_check):
        if not app.app_state.global_settings:
            return
        announce = app.app_state.global_settings.get('announce', {})
        announce_version = announce.get('version', 0)
        if announce_version == 0:
            logging.info('_check_and_show_announce: Announce version is 0, announcements disabled')
            return
        saved_version = app.app_state.local_config.get('announce_version', 0)
        if saved_version == -1:
            logging.info('_check_and_show_announce: User has disabled announcements (version -1)')
            return
        if announce_version != saved_version:
            announce_message = app._localized_value(announce, 'message_ru', 'message_en')
            if not announce_message:
                logging.info('_check_and_show_announce: No message for current language')
                save_announce(app, announce_version)
                return
            announce_link = announce.get('link', '')
            logging.info(f'_check_and_show_announce: Conditions met, showing announce dialog (version {announce_version}, saved {saved_version})')
            if is_visible and (not is_shown):
                app.app_state.is_shown_to_user = True
                logging.info('_check_and_show_announce: Set app_state.is_shown_to_user=True because window is visible')
            from ui.dialogs.announce_dialog import AnnounceDialog
            dialog = AnnounceDialog(announce_message, announce_link, app)
            dialog.accepted_with_ok.connect(lambda: save_announce(app, announce_version))
            dialog.exec()
            app.app_state.pending_announce_check = False
        else:
            logging.info(f'_check_and_show_announce: Announce version {announce_version} matches saved version, skipping')
    elif retry_count < max_retries:
        logging.debug(f'_check_and_show_announce: Conditions not met, retrying in 1 second (retry {retry_count + 1}/{max_retries})')
        QTimer.singleShot(1000, lambda: check_and_show_announce(app, retry_count + 1, force_check))
    else:
        logging.warning(f'Announce dialog: conditions not met after max retries (init_completed={init_completed}, is_shown={is_shown}, is_visible={is_visible}), skipping announce')


def save_announce(app, version: int):
    app.app_state.local_config['announce_version'] = version
    app.settings_service.write_local_config()
    logging.info(f'_save_announce: Saved announce version {version} to config')


def prompt_for_update(app, update_info):
    from config.constants import LAUNCHER_VERSION, UI_COLORS
    logging.info(f"_prompt_for_update called with version {update_info.get('version', 'unknown')}")
    if app.app_state.update_in_progress:
        logging.warning('_prompt_for_update: Update already in progress, ignoring')
        return
    if app.app_state.game_is_running:
        logging.info('_prompt_for_update: Game is running, adding to pending dialogs')
        app.app_state.pending_dialogs.append(('update', update_info))
        return
    logging.info('_prompt_for_update: Showing update dialog')
    app.app_state.update_in_progress = True
    update_message = f"<b>{tr('dialogs.new_version_banner', version=update_info['version']).replace('<br>', '')}</b><br>"
    update_message += tr('dialogs.current_version_banner', current_version=LAUNCHER_VERSION).replace('<br><br>', '') + '<br><br>'
    message_text = app._localized_value(update_info, 'message_ru', 'message_en', 'message')
    update_message += f"<b>{tr('dialogs.whats_new')}</b><br>{message_text}<br><br>"
    update_message += tr('dialogs.want_download_install_now') + tr('dialogs.app_will_restart')
    if app.feedback_service.ask_question('status.update_available', 'status.update_available', update_message, True):
        logging.info('_prompt_for_update: User accepted update')
        if hasattr(app, '_perform_update_ui_prep'):
            app._perform_update_ui_prep()
        app.update_checker.perform_update(update_info)
    else:
        logging.info('_prompt_for_update: User rejected update')
        app.app_state.update_in_progress = False
        app.feedback_service.update_status(tr('status.update_rejected'), UI_COLORS['status_info'])
        if hasattr(app.app_state, 'pending_announce_check') and app.app_state.pending_announce_check:
            QTimer.singleShot(500, lambda: check_and_show_announce(app))
