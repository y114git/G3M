"""One-click install handler extracted from AppWindow."""

import os

from services.game_detection_service import is_game_running
from services.localization_service import tr


def _parse_deltahub_url(url: str) -> str:
    """Extract the actual download URL from a deltahub:// protocol link."""
    content = url[len("deltahub://") :].split(",")[0].strip().rstrip("/")
    if not content.startswith(("http://", "https://")):
        content = content.replace("https//", "https://").replace("http//", "http://")
    return content


def handle_one_click_install(w, url: str):
    """Handle one-click install from deltahub:// URL. `w` is the AppWindow instance."""
    if is_game_running():
        w.feedback_service.show_message(
            "warning", "ui.warning", tr("errors.game_running")
        )
        return
    w.activateWindow()
    w.raise_()

    if url.startswith("deltahub://"):
        _enqueue_deltahub_url(w, url)
    else:
        w.mod_service.install_from_url(url)


def _enqueue_deltahub_url(w, url: str):
    """Route a deltahub:// URL through the Downloads system with confirmation."""
    from models.download_models import SourceKind, TargetKind
    from ui.dialogs.confirm_external_download_dialog import (
        ConfirmExternalDownloadDialog,
    )

    download_url = _parse_deltahub_url(url)
    if not download_url or not download_url.startswith(("http://", "https://")):
        w.feedback_service.show_message(
            "error", "errors.error", tr("errors.mod_not_found")
        )
        return
    dialog = ConfirmExternalDownloadDialog(
        download_url, getattr(w, "app_state", None), w
    )
    if not dialog.exec():
        return
    display_name = os.path.basename(download_url.split("?")[0]) or "deltahub:// mod"
    w.downloads_manager.enqueue_with_feedback(
        w.feedback_service,
        display_name=display_name,
        source_kind=SourceKind.DELTAHUB_PROTOCOL,
        target_kind=TargetKind.MOD,
        source_url=download_url,
    )
