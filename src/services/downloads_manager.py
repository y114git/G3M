"""Downloads system coordinator."""

import contextlib
import logging
import os
import re
import shutil
import uuid

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from models.download_models import (
    DownloadRecord,
    DownloadStatus,
    SourceKind,
    TargetKind,
    UseStatus,
)
from services.downloads_store import DownloadsStore
from utils.time_utils import utc_now_iso

logger = logging.getLogger(__name__)

_SAFE_RE = re.compile(r"[^\w\-. ]+")


def _safe_filename(name: str) -> str:
    return _SAFE_RE.sub("_", name)[:80] or "file"


def _cleanup_worker(worker):
    if not worker:
        return
    try:
        if worker.isFinished():
            worker.deleteLater()
        else:
            worker.finished.connect(worker.deleteLater)
    except Exception as e:
        logger.debug(
            f"_cleanup_worker: failed to clean up worker {type(worker).__name__}: {e}",
            exc_info=True,
        )


class DownloadsManager(QObject):
    """Coordinator for all download/use operations. Created once in AppWindow."""

    record_added = pyqtSignal(object)
    record_updated = pyqtSignal(object)
    record_removed = pyqtSignal(str)
    badge_changed = pyqtSignal(int, bool)
    use_completed = pyqtSignal()

    def __init__(self, base_dir: str, settings_getter, parent=None) -> None:
        super().__init__(parent)
        self._store = DownloadsStore(base_dir)
        self._settings = settings_getter
        self._workers = {}
        self._mods_dir: str | None = None

    def set_app_context(self, *, mods_dir: str):
        self._mods_dir = mods_dir

    @property
    def store(self) -> DownloadsStore:
        return self._store

    @property
    def records(self):
        return self._store.records

    @property
    def mods_dir(self) -> str | None:
        return self._mods_dir

    def startup(self):
        self._store.load()
        self._store.startup_recovery()
        self._emit_badge()

    def enqueue(
        self,
        display_name: str,
        source_kind: str = SourceKind.EXTERNAL_URL,
        target_kind: str = TargetKind.MOD,
        source_url: str | None = None,
        source_file_path: str | None = None,
        canonical_key: str | None = None,
        metadata: dict | None = None,
    ) -> tuple[str, bool]:
        if canonical_key:
            existing = self._store.find_by_canonical_key(canonical_key)
            if existing:
                return existing.id, True

        settings = self._settings()
        record = DownloadRecord(
            id=uuid.uuid4().hex[:12],
            display_name=display_name,
            source_kind=source_kind,
            target_kind=target_kind,
            source_url=source_url,
            source_file_path=source_file_path,
            canonical_key=canonical_key,
            auto_use=not settings.get("downloads_no_auto_use", False),
            delete_after_use=settings.get("downloads_delete_after_use", False),
            metadata=metadata or {},
        )
        self._store.add(record)
        self.record_added.emit(record)
        self._start_download(record)
        self._emit_badge()
        return record.id, False

    def _start_download(self, record: DownloadRecord):
        record.download_status = DownloadStatus.DOWNLOADING
        self._store.update(record)
        self.record_updated.emit(record)

        safe_name = _safe_filename(record.display_name)
        ext = ""
        for src in (
            record.metadata.get("file_name", ""),
            record.source_url or "",
            record.source_file_path or "",
        ):
            base = src.split("?")[0].split("#")[0]
            _, e = os.path.splitext(base)
            if e:
                ext = e
                break
        target_path = os.path.join(
            self._store.downloads_dir, f"{record.id}__{safe_name}{ext}"
        )

        if record.source_file_path and os.path.exists(record.source_file_path):
            from workers.download_worker import LocalFileCopyWorker

            worker = LocalFileCopyWorker(
                record.id, record.source_file_path, target_path, parent=self
            )
            worker.download_finished.connect(self._on_download_finished)
            self._workers[record.id] = worker
            worker.start()
            return

        if not record.source_url:
            self._on_download_finished(record.id, False, "No download URL", "")
            return

        from workers.download_worker import DownloadWorker

        worker = DownloadWorker(record.id, record.source_url, target_path, parent=self)
        worker.progress_updated.connect(self._on_download_progress)
        worker.download_finished.connect(self._on_download_finished)
        self._workers[record.id] = worker
        worker.start()

    def _on_download_progress(
        self, record_id: str, pct: int, bytes_recv: int, bytes_total: int
    ):
        record = self._store.find(record_id)
        if not record:
            return
        record.progress = pct
        record.bytes_received = bytes_recv
        record.bytes_total = bytes_total
        self.record_updated.emit(record)

    def _on_download_finished(
        self, record_id: str, success: bool, error: str, saved_path: str
    ):
        record = self._store.find(record_id)
        if not record:
            return
        worker = self._workers.pop(record_id, None)
        _cleanup_worker(worker)

        if not success:
            is_cancel = error == "cancelled"
            record.download_status = (
                DownloadStatus.CANCELLED if is_cancel else DownloadStatus.FAILED
            )
            record.use_status = UseStatus.CANCELLED if is_cancel else UseStatus.FAILED
            record.error_message = None if is_cancel else error
            record.finished_at = utc_now_iso()
            record.file_exists = False
            self._store.update(record)
            self.record_updated.emit(record)
            self._emit_badge()
            return

        record.download_status = DownloadStatus.DOWNLOADED
        record.progress = 100
        record.file_path = saved_path
        record.file_exists = True
        record.finished_at = utc_now_iso()

        if record.auto_use:
            record.use_status = UseStatus.PENDING_AUTO
            self._store.update(record)
            self.record_updated.emit(record)
            QTimer.singleShot(200, lambda rid=record_id: self._start_use(rid))
        else:
            record.use_status = UseStatus.READY
            self._store.update(record)
            self.record_updated.emit(record)
        self._emit_badge()

    def _start_use(self, record_id: str):
        record = self._store.find(record_id)
        if not record or not record.file_exists or not record.file_path:
            return
        if not self._mods_dir:
            logger.warning("DownloadsManager: mods_dir not set, cannot run Use")
            record.use_status = UseStatus.FAILED
            record.error_message = "Application context not ready"
            self._store.update(record)
            self.record_updated.emit(record)
            self._emit_badge()
            return

        record.use_status = UseStatus.USING
        self._store.update(record)
        self.record_updated.emit(record)

        from workers.use_worker import UseWorker

        worker = UseWorker(
            record_id=record.id,
            file_path=record.file_path,
            target_kind=record.target_kind,
            mods_dir=self._mods_dir,
            metadata=record.metadata,
            parent=self,
        )
        worker.use_finished.connect(self._on_use_finished)
        self._workers[record.id] = worker
        worker.start()

    def _on_use_finished(
        self, record_id: str, success: bool, needs_manual: bool, error: str
    ):
        record = self._store.find(record_id)
        if not record:
            return
        worker = self._workers.pop(record_id, None)
        _cleanup_worker(worker)

        if not success and not needs_manual:
            record.use_status = UseStatus.FAILED
            record.error_message = error or "Use failed"
            self._store.update(record)
            self.record_updated.emit(record)
            self._emit_badge()
            return
        if needs_manual:
            record.use_status = UseStatus.NEEDS_MANUAL
            self._store.update(record)
            self.record_updated.emit(record)
            self._emit_badge()
            return
        record.ever_installed = True
        if record.delete_after_use:
            self._store.delete_file_for_record(record)
            self._store.remove(record.id)
            self.record_removed.emit(record.id)
        else:
            record.use_status = UseStatus.READY
            self._store.update(record)
            self.record_updated.emit(record)
        self._emit_badge()
        self.use_completed.emit()

    def action_install(self, record_id: str):
        record = self._store.find(record_id)
        if not record or not record.file_exists or record.use_status != UseStatus.READY:
            return
        self._start_use(record_id)

    def action_overwrite(self, record_id: str):
        record = self._store.find(record_id)
        if record and record.use_status == UseStatus.OVERWRITE_PENDING:
            self._start_use(record_id)

    def action_cancel_install(self, record_id: str):
        record = self._store.find(record_id)
        if record and record.use_status == UseStatus.OVERWRITE_PENDING:
            record.use_status = UseStatus.READY
            self._store.update(record)
            self.record_updated.emit(record)
            self._emit_badge()

    def action_cancel_download(self, record_id: str):
        record = self._store.find(record_id)
        if not record:
            return
        worker = self._workers.pop(record_id, None)
        if worker and hasattr(worker, "cancel"):
            worker.cancel()
            worker.requestInterruption()
            worker.finished.connect(worker.deleteLater)
        record.download_status = DownloadStatus.CANCELLED
        record.use_status = UseStatus.CANCELLED
        record.file_exists = False
        record.finished_at = utc_now_iso()
        self._store.update(record)
        self.record_updated.emit(record)
        self._emit_badge()

    def action_retry(self, record_id: str):
        record = self._store.find(record_id)
        if not record or record.download_status not in (
            DownloadStatus.FAILED,
            DownloadStatus.CANCELLED,
        ):
            return
        record.download_status = DownloadStatus.QUEUED
        record.use_status = UseStatus.NOT_STARTED
        record.progress = 0
        record.bytes_received = 0
        record.error_code = None
        record.error_message = None
        record.finished_at = None
        self._store.update(record)
        self.record_updated.emit(record)
        self._start_download(record)
        self._emit_badge()

    def action_delete(self, record_id: str):
        record = self._store.find(record_id)
        if not record:
            return
        worker = self._workers.pop(record_id, None)
        if worker and hasattr(worker, "cancel"):
            worker.cancel()
        self._store.delete_file_for_record(record)
        self._store.remove(record_id)
        self.record_removed.emit(record_id)
        self._emit_badge()

    def action_continue_setup(self, record_id: str, parent_widget=None):
        record = self._store.find(record_id)
        if not record or record.use_status != UseStatus.NEEDS_MANUAL:
            return
        self._open_manual_install_dialog(record, parent_widget)

    def _open_manual_install_dialog(self, record: DownloadRecord, parent_widget=None):
        try:
            import tempfile

            from PyQt6.QtWidgets import QDialog

            from ui.dialogs.manual_install_dialog import ManualModInstallDialog
            from utils.archive_utils import extract_archive

            temp_dir = tempfile.mkdtemp(prefix="dh_manual_")
            extract_archive(record.file_path, temp_dir)
            contents = os.listdir(temp_dir)
            content_path = temp_dir
            if len(contents) == 1 and os.path.isdir(
                os.path.join(temp_dir, contents[0])
            ):
                content_path = os.path.join(temp_dir, contents[0])
            gb_metadata = self._build_dialog_metadata(record)
            initial_game_type = (
                (record.metadata.get("game") or "deltarune")
                if record.metadata
                else None
            )
            dialog = ManualModInstallDialog(
                parent_widget or self.parent(),
                content_path,
                gamebanana_metadata=gb_metadata,
                source_file_path=record.file_path,
                initial_game_type=initial_game_type,
            )
            dialog.temp_dir_to_cleanup = temp_dir
            if dialog.exec() == QDialog.DialogCode.Accepted:
                record.ever_installed = True
                record.use_status = UseStatus.READY
                if record.delete_after_use:
                    self._store.delete_file_for_record(record)
                    self._store.remove(record.id)
                    self.record_removed.emit(record.id)
                else:
                    self._store.update(record)
                    self.record_updated.emit(record)
                self._emit_badge()
                self.use_completed.emit()
            else:
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            logger.error(
                "DownloadsManager: manual install dialog failed: %s", e, exc_info=True
            )
            with contextlib.suppress(Exception):
                shutil.rmtree(temp_dir, ignore_errors=True)
            record.use_status = UseStatus.NEEDS_MANUAL
            record.error_message = str(e)
            self._store.update(record)
            self.record_updated.emit(record)

    def _build_dialog_metadata(self, record: DownloadRecord) -> dict:
        m = record.metadata or {}
        if not m.get("gb_mod_id"):
            return {}
        return {
            "mod_id": m["gb_mod_id"],
            "item_type": m.get("item_type", "mod"),
            "name": record.display_name,
            "author": m.get("author"),
            "profile_url": m.get("profile_url"),
            "external_url": m.get("profile_url"),
            "icon_url": m.get("icon_url"),
            "tags": m.get("tags") or [],
            "category": m.get("category"),
            "game": m.get("game", "deltarune"),
        }

    def enqueue_with_feedback(self, feedback_service, **kwargs) -> tuple[str, bool]:
        """Enqueue and show appropriate status feedback. Returns (record_id, is_duplicate)."""
        from config.config import UI_COLORS
        from services.localization_service import tr

        record_id, is_dup = self.enqueue(**kwargs)
        if is_dup:
            feedback_service.update_status(
                tr("downloads.already_downloading"), UI_COLORS["status_warning"]
            )
        else:
            feedback_service.update_status(
                tr("downloads.enqueued", name=kwargs.get("display_name", "")),
                UI_COLORS["status_info"],
            )
        return record_id, is_dup

    def clear_downloads(self):
        for r in [r for r in self._store.records if not r.is_active]:
            self._store.delete_file_for_record(r)
            self._store.remove(r.id)
            self.record_removed.emit(r.id)
        self._emit_badge()

    def _emit_badge(self):
        count = sum(
            1
            for r in self._store.records
            if r.effective_status_key
            in ("downloading", "ready", "installing", "needs_manual")
        )
        attention = any(r.needs_attention for r in self._store.records)
        self.badge_changed.emit(count, attention)
