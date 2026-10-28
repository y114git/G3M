"""One-click install handler extracted from AppWindow."""

import os
import re
from urllib.parse import unquote, urlparse

from PyQt6.QtWidgets import QMessageBox

from config.config import (
    PRIMARY_URL_SCHEME,
    URL_PROTOCOL_PREFIXES,
    URL_PROTOCOL_SCHEMES,
)
from services.game_detection_service import is_game_running
from services.localization_service import tr
from ui.common.feedback import safe_show_message
from utils.mod.utils import parse_gamebanana_download_link, parse_gamebanana_mod_url

_PAIR_URL = re.compile(rf"(?:{'|'.join(URL_PROTOCOL_SCHEMES)})://gb_pair/([\w-]+)/([\w-]+)/?", re.ASCII | re.IGNORECASE)


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
    if pair := _PAIR_URL.fullmatch(url):
        _pair_remote_install(w, *pair.groups())
        return
    if is_game_running():
        safe_show_message(w.feedback_service, "warning", "ui.warning", tr("errors.game_running"))
        return
    w.activateWindow()
    w.raise_()

    if url.startswith(URL_PROTOCOL_PREFIXES):
        _enqueue_g3m_url(w, url)
    else:
        w.mod_service.install_from_url(url)


def _pair_remote_install(w, member_id: str, secret_key: str):
    """Store the GameBanana Remote Install key after the user agrees to receive its queue."""
    if QMessageBox.question(
        w, tr("downloads.remote_install_title"), tr("downloads.remote_install_pair")
    ) == QMessageBox.StandardButton.Yes:
        w.remote_install_service.pair(member_id, secret_key)


def _enqueue_g3m_url(w, url: str):
    """Route a supported protocol URL through the Downloads system with confirmation."""
    from models.download_models import SourceKind, TargetKind
    from ui.dialogs.confirm_external_download_dialog import (
        ConfirmExternalDownloadDialog,
    )

    download_url = _parse_g3m_url(url)
    local_path = _local_protocol_path(download_url)
    if not download_url or (
        not download_url.startswith(("http://", "https://")) and not local_path
    ):
        safe_show_message(w.feedback_service, "error", "errors.error", tr("errors.mod_not_found"))
        return
    dialog = ConfirmExternalDownloadDialog(
        download_url, getattr(w, "app_state", None), w
    )
    if not dialog.exec():
        return
    if parse_gamebanana_mod_url(download_url):
        w.mod_service.install_from_url(download_url)
        return
    link = parse_gamebanana_download_link(url.partition("://")[2])
    if link and link[1]:
        file_id, (item_type, mod_id) = link[0], link[1]
        w.downloads_manager.enqueue_with_feedback(
            w.feedback_service,
            display_name=f"GameBanana mod {mod_id}",
            source_kind=SourceKind.GAMEBANANA,
            target_kind=TargetKind.MOD,
            source_url=f"https://gamebanana.com/dl/{file_id}",
            canonical_key=f"gb_{item_type.lower()}_{mod_id}_{file_id}",
            metadata={"gb_mod_id": int(mod_id), "item_type": item_type.lower(), "gb_file_id": int(file_id)},
        )
        return
    if local_path:
        w.downloads_manager.enqueue_with_feedback(
            w.feedback_service,
            display_name=os.path.basename(local_path),
            source_kind=SourceKind.LOCAL_FILE,
            target_kind=TargetKind.MOD,
            source_file_path=local_path,
        )
        return
    display_name = os.path.basename(download_url.split("?")[0]) or f"{PRIMARY_URL_SCHEME}:// mod"
    w.downloads_manager.enqueue_with_feedback(
        w.feedback_service,
        display_name=display_name,
        source_kind=SourceKind.G3M_PROTOCOL,
        target_kind=TargetKind.MOD,
        source_url=download_url,
    )


def _local_protocol_path(url: str) -> str | None:
    """Resolve a local file URI while refusing network shares and directories."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        return None
    path = unquote(parsed.path)
    if os.name == "nt" and path.replace("/", "\\").startswith("\\\\"):
        return None
    if os.name == "nt" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    path = os.path.abspath(path)
    return path if os.path.isfile(path) else None
