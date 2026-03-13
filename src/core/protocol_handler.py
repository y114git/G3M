"""One-click install handler extracted from AppWindow."""
import logging
import os
import shutil
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QMessageBox
from services.localization_service import tr
from config.constants import UI_COLORS
from services.game_detection_service import is_game_running


def _parse_deltahub_url(url: str) -> str:
    """Extract the actual download URL from a deltahub:// protocol link."""
    content = url[len('deltahub://'):].split(',')[0].strip().rstrip('/')
    if not content.startswith(('http://', 'https://')):
        content = content.replace('https//', 'https://').replace('http//', 'http://')
    return content


def handle_one_click_install(w, url: str):
    """Handle one-click install from deltahub:// URL. `w` is the AppWindow instance."""
    if is_game_running():
        w.feedback_service.show_message('warning', 'ui.warning', tr('errors.game_running'))
        return
    w.activateWindow()
    w.raise_()

    if url.startswith('deltahub://'):
        downloads_manager = getattr(w, 'downloads_manager', None)
        if downloads_manager:
            _enqueue_deltahub_url(w, url)
            return
        _handle_one_click_install_legacy(w, url)
    else:
        w.mod_service.install_from_url(url)


def _enqueue_deltahub_url(w, url: str):
    """Route a deltahub:// URL through the Downloads system with confirmation."""
    from models.download_models import SourceKind, TargetKind
    from ui.dialogs.confirm_external_download_dialog import ConfirmExternalDownloadDialog
    download_url = _parse_deltahub_url(url)
    if not download_url or not download_url.startswith(('http://', 'https://')):
        w.feedback_service.show_message('error', 'errors.error', tr('errors.mod_not_found'))
        return
    dialog = ConfirmExternalDownloadDialog(download_url, getattr(w, 'app_state', None), w)
    if not dialog.exec():
        return
    display_name = os.path.basename(download_url.split('?')[0]) or 'deltahub:// mod'
    w.downloads_manager.enqueue_with_feedback(
        w.feedback_service,
        display_name=display_name,
        source_kind=SourceKind.DELTAHUB_PROTOCOL,
        target_kind=TargetKind.MOD,
        source_url=download_url,
    )


def _handle_one_click_install_legacy(w, url: str):
    """Legacy path: direct UrlInstallThread (fallback if downloads_manager unavailable)."""
    if w.app_state.is_installing:
        w.feedback_service.show_message('warning', 'dialogs.install_in_progress_title', tr('dialogs.install_in_progress_body'))
        return
    from workers.install.url_install_worker import UrlInstallThread
    worker = UrlInstallThread(w, url)
    worker.status.connect(lambda msg, color: w.feedback_service.update_status(msg, color))
    worker.progress.connect(lambda p: setattr(w.app_state, 'progress_bar_value', p))

    def on_manual_install_required(prepared_path, archive_path, temp_dir):
        w.app_state.reset_install_state()
        try:
            from ui.dialogs.manual_install_dialog import ManualModInstallDialog
            from services.game_detection_service import get_game_type_string
            initial_game_type = None
            if w.app_state and hasattr(w.app_state, 'game_mode'):
                initial_game_type = get_game_type_string(w.app_state.game_mode)
            dialog = ManualModInstallDialog(w, prepared_path, gamebanana_metadata=None, source_file_path=archive_path, initial_game_type=initial_game_type)
            dialog.temp_dir_to_cleanup = temp_dir
            if dialog.exec() == QDialog.DialogCode.Accepted:
                w.refresh_after_install()
                w.feedback_service.update_status(tr('dialogs.mod_created_successfully'), UI_COLORS['status_success'])
                QMessageBox.information(w, tr('dialogs.success'), tr('dialogs.mod_created_successfully'))
                QTimer.singleShot(1000, lambda: w.refresh(is_initial=False))
        except Exception as e:
            logging.error(f'Failed to open manual install dialog: {e}', exc_info=True)
            w.feedback_service.show_message('error', tr('errors.error'), tr('errors.manual_install_failed', error=str(e)))
            shutil.rmtree(temp_dir, ignore_errors=True)

    def on_finished(success, message):
        w.app_state.reset_install_state()
        if success:
            w.refresh_after_install()
            w.feedback_service.update_status(message, UI_COLORS['status_success'])
            QTimer.singleShot(1000, lambda: w.refresh(is_initial=False))
        else:
            logging.warning(f'Installation failed for deltahub:// URL: {message}')
            w.feedback_service.update_status(message or tr('errors.error'), UI_COLORS['status_error'])

    def on_unrar_needed():
        try:
            from utils.archive_utils import prompt_for_unrar_install
            if prompt_for_unrar_install(parent_widget=w):
                logging.info('UnRAR installed successfully from app_window worker request')
            else:
                logging.info('User declined UnRAR installation from app_window worker request')
        except Exception as e:
            logging.error(f'AppWindow: Error handling UnRAR installation request: {e}')
    worker.manual_install_required.connect(on_manual_install_required)
    worker.finished.connect(on_finished)
    worker.unrar_needed.connect(on_unrar_needed)
    w.app_state.is_installing = True
    w.app_state.progress_bar_visible = True
    w.app_state.progress_bar_value = 0
    w.app_state.current_task = worker
    worker.start()
