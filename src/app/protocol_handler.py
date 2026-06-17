"""One-click install handler extracted from AppWindow."""

import logging
import os

from config.config import PRIMARY_URL_SCHEME, URL_PROTOCOL_PREFIXES
from services.game_detection_service import is_game_running
from services.localization_service import tr

logger = logging.getLogger(__name__)


def _safe_show_message(w, level: str, title: str, message: str) -> None:
    try:
        w.feedback_service.show_message(level, title, message)
    except Exception:
        logger.warning("Protocol handler feedback message failed", exc_info=True)


def _parse_g3m_url(url: str) -> str:
    """Extract the actual download URL from a supported one-click protocol link."""
    prefix = next(
        (candidate for candidate in URL_PROTOCOL_PREFIXES if url.startswith(candidate)),
        f"{PRIMARY_URL_SCHEME}://",
    )
    content = url[len(prefix) :].split(",")[0].strip().rstrip("/")
    if not content.startswith(("http://", "https://")):
        content = content.replace("https//", "https://").replace("http//", "http://")
    return content


def handle_one_click_install(w, url: str):
    """Handle one-click install from a supported protocol URL. `w` is the AppWindow instance."""
    if is_game_running():
        _safe_show_message(w, "warning", "ui.warning", tr("errors.game_running"))
        return
    w.activateWindow()
    w.raise_()

    if url.startswith(URL_PROTOCOL_PREFIXES):
        _enqueue_g3m_url(w, url)
    else:
        w.mod_service.install_from_url(url)


def _enqueue_g3m_url(w, url: str):
    """Route a supported protocol URL through the Downloads system with confirmation."""
    from models.download_models import SourceKind, TargetKind
    from ui.dialogs.confirm_external_download_dialog import (
        ConfirmExternalDownloadDialog,
    )

    download_url = _parse_g3m_url(url)
    if not download_url or not download_url.startswith(("http://", "https://")):
        _safe_show_message(w, "error", "errors.error", tr("errors.mod_not_found"))
        return
    dialog = ConfirmExternalDownloadDialog(
        download_url, getattr(w, "app_state", None), w
    )
    if not dialog.exec():
        return
    display_name = (
        os.path.basename(download_url.split("?")[0]) or f"{PRIMARY_URL_SCHEME}:// mod"
    )
    w.downloads_manager.enqueue_with_feedback(
        w.feedback_service,
        display_name=display_name,
        source_kind=SourceKind.G3M_PROTOCOL,
        target_kind=TargetKind.MOD,
        source_url=download_url,
    )
