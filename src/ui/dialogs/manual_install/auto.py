"""Install a mod through the manual-install pipeline without asking, when every file sets itself up."""

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QDialog

from ui.dialogs.manual_install.dialog import ManualModInstallDialog

GIVE_UP_AFTER_MS = 15 * 60 * 1000


def auto_manual_install(parent, prepared_path: str, **options) -> bool:
    """Run the dialog's detection and save steps hidden; False means the user has to install by hand."""
    dialog = ManualModInstallDialog(parent, prepared_path, auto_install=True, **options)
    dialog.temp_dir_to_cleanup = None
    loop = QEventLoop()
    dialog.finished.connect(loop.quit)
    dialog.destroyed.connect(loop.quit)
    # The dialog is never shown, so nothing else can end the wait: quit it with the app, and give up after a long while.
    app = QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(loop.quit)
    timeout = QTimer(dialog)
    timeout.setSingleShot(True)
    timeout.timeout.connect(dialog.reject)
    timeout.start(GIVE_UP_AFTER_MS)
    loop.exec()
    installed = dialog.result() == QDialog.DialogCode.Accepted
    dialog.deleteLater()
    return installed
