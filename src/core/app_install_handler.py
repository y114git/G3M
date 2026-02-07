"""One-click install handler extracted from AppWindow."""
import logging
import shutil
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QMessageBox
from services.localization_service import tr
from config.constants import UI_COLORS
from services.game_detection_service import is_game_running


def handle_one_click_install(w, url: str):
    """Handle one-click install from deltahub:// URL. `w` is the AppWindow instance."""
    if is_game_running():
        return
    w.activateWindow()
    w.raise_()
    if w.app_state.is_installing:
        w.feedback_service.show_message('warning', 'dialogs.install_in_progress_title', tr('dialogs.install_in_progress_body'))
        return
    if url.startswith('deltahub://'):
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
                    w._refresh_after_install()
                    w.feedback_service.update_status(tr('dialogs.mod_created_successfully'), UI_COLORS['status_success'])
                    QMessageBox.information(w, tr('dialogs.success'), tr('dialogs.mod_created_successfully'))
                    QTimer.singleShot(1000, lambda: w._on_refresh_clicked(is_initial=False))
            except Exception as e:
                logging.error(f'Failed to open manual install dialog: {e}', exc_info=True)
                w.feedback_service.show_message('error', tr('errors.error'), tr('errors.manual_install_failed', error=str(e)))
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass

        def on_finished(success, message):
            w.app_state.reset_install_state()
            if success:
                w._refresh_after_install()
                w.feedback_service.update_status(message, UI_COLORS['status_success'])
                QTimer.singleShot(1000, lambda: w._on_refresh_clicked(is_initial=False))
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
    else:
        w.mod_service.install_from_url(url)
