"""Open a data file in G3MStudio through its g3mstudio:// link."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox, QWidget

from services.localization_service import tr

DATA_EXTENSIONS = (".win", ".ios", ".unx", ".droid")
STUDIO_PAGE = "https://github.com/y114git/G3MStudio"


def is_data_file(path: str) -> bool:
    return path.lower().endswith(DATA_EXTENSIONS) and os.path.isfile(path)


def studio_button_enabled(app_state) -> bool:
    config = getattr(app_state, "local_config", None) or {}
    return bool(config.get("show_open_in_studio", True))


def studio_link(path: str) -> str:
    # The same shape G3MStudio builds for a file: the scheme followed by the file URI.
    return "g3mstudio://" + Path(path).resolve().as_uri()


def _scheme_registered() -> bool:
    """Asks the system whether something handles g3mstudio://; true when it cannot be told."""
    if sys.platform == "win32":
        import winreg

        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "g3mstudio"))
        except OSError:
            return False
        return True
    xdg_mime = shutil.which("xdg-mime") if sys.platform.startswith("linux") else None
    if xdg_mime is None:
        return True
    try:
        result = subprocess.run(
            [xdg_mime, "query", "default", "x-scheme-handler/g3mstudio"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return bool(result.stdout.strip())


def open_in_studio(path: str, parent: QWidget | None = None) -> bool:
    """Opens the file in G3MStudio; on failure explains why and offers the download page."""
    if not is_data_file(path):
        reason = tr("studio_link.reason_missing", path=path)
    elif not _scheme_registered():
        reason = tr("studio_link.reason_not_registered")
    elif not QDesktopServices.openUrl(QUrl.fromEncoded(studio_link(path).encode())):
        reason = tr("studio_link.reason_failed")
    else:
        return True
    _warn(reason, parent)
    return False


def _warn(reason: str, parent: QWidget | None) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("studio_link.title"))
    box.setText(reason)
    box.setInformativeText(tr("studio_link.help"))
    ok = box.addButton(tr("studio_link.ok"), QMessageBox.ButtonRole.AcceptRole)
    download = box.addButton(
        tr("studio_link.download"), QMessageBox.ButtonRole.ActionRole
    )
    box.setDefaultButton(ok)
    box.exec()
    if box.clickedButton() is download:
        QDesktopServices.openUrl(QUrl(STUDIO_PAGE))
