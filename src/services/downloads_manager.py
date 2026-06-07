"""Downloads system coordinator."""

import contextlib
import logging
import os
import re
import shutil
import time
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
from services.localization_service import tr
from utils.process_utils import format_filesystem_error
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
        self._plugin_install_service = None
        self._progress_emit_state: dict[str, tuple[int, int, int, float]] = {}

    def set_app_context(self, *, mods_dir: str, plugin_install_service=None):
        self._mods_dir = mods_dir
        self._plugin_install_service = plugin_install_service

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
                if (
                    target_kind == TargetKind.PLUGIN
                    and not existing.is_active
                ):
                    self._replace_existing_plugin_record(existing.id)
                else:
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

    def _replace_existing_plugin_record(self, record_id: str) -> None:
        record = self._store.find(record_id)
        if not record:
            return
        worker = self._workers.pop(record_id, None)
        if worker and hasattr(worker, "cancel"):
            worker.cancel()
            with contextlib.suppress(Exception):
                worker.requestInterruption()
            with contextlib.suppress(Exception):
                worker.finished.connect(worker.deleteLater)
        _cleanup_worker(worker)
        self._store.delete_file_for_record(record)
        self._store.remove(record_id)
        self.record_removed.emit(record_id)

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
        now = time.monotonic()
        previous = self._progress_emit_state.get(record_id)
        if previous is not None:
            prev_pct, prev_recv, prev_total, prev_ts = previous
            unchanged = (
                pct == prev_pct
                and bytes_recv == prev_recv
                and bytes_total == prev_total
            )
            if unchanged:
                return
            if (
                pct != 100
                and bytes_total == prev_total
                and pct == prev_pct
                and (bytes_recv - prev_recv) < 256 * 1024
                and (now - prev_ts) < 0.075
            ):
                return
        self._progress_emit_state[record_id] = (pct, bytes_recv, bytes_total, now)
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
        self._progress_emit_state.pop(record_id, None)
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
        if record.target_kind == TargetKind.PLUGIN and not self._plugin_install_service:
            logger.warning("DownloadsManager: plugin_install_service not set")
            record.use_status = UseStatus.FAILED
            record.error_message = "Plugin installer not available"
            self._store.update(record)
            self.record_updated.emit(record)
            self._emit_badge()
            return
        if record.target_kind == TargetKind.MOD and not self._mods_dir:
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
            mods_dir=self._mods_dir or "",
            metadata=record.metadata,
            plugin_install_service=self._plugin_install_service,
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
            record.use_status = UseStatus.READY
            self.record_updated.emit(record)
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
            with contextlib.suppress(Exception):
                worker.requestInterruption()
            with contextlib.suppress(Exception):
                worker.finished.connect(worker.deleteLater)
        _cleanup_worker(worker)
        self._progress_emit_state.pop(record_id, None)
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
            with contextlib.suppress(Exception):
                worker.requestInterruption()
            with contextlib.suppress(Exception):
                worker.finished.connect(worker.deleteLater)
        _cleanup_worker(worker)
        self._progress_emit_state.pop(record_id, None)
        self._store.delete_file_for_record(record)
        self._store.remove(record_id)
        self.record_removed.emit(record_id)
        self._emit_badge()

    def action_continue_setup(self, record_id: str, parent_widget=None):
        record = self._store.find(record_id)
        if (
            not record
            or record.target_kind != TargetKind.MOD
            or record.use_status != UseStatus.NEEDS_MANUAL
        ):
            return
        self._open_manual_install_dialog(record, parent_widget)

    def _resolve_presenter_parent(self, parent_widget=None):
        current = parent_widget or self.parent()
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            presenter = getattr(current, "pizza_oven_conversion_presenter", None)
            if presenter is not None:
                return current, presenter
            next_parent = None
            for attr_name in ("parentWidget", "parent"):
                parent_getter = getattr(current, attr_name, None)
                if not callable(parent_getter):
                    continue
                try:
                    next_parent = parent_getter()
                except Exception:
                    next_parent = None
                if next_parent is not None:
                    break
            current = next_parent
        return parent_widget or self.parent(), None

    def _open_manual_install_dialog(self, record: DownloadRecord, parent_widget=None):
        temp_dir = None
        try:
            import tempfile

            from utils.archive_utils import (
                extract_archive,
                unwrap_single_directory_chain,
            )

            parent = parent_widget or self.parent()
            temp_dir = tempfile.mkdtemp(prefix="g3m_manual_")
            extract_archive(record.file_path, temp_dir)
            content_path = unwrap_single_directory_chain(temp_dir)
            gb_metadata = self._build_dialog_metadata(record)
            initial_game_type = (
                (record.metadata.get("game") or "deltarune")
                if record.metadata
                else None
            )
            parent, presenter = self._resolve_presenter_parent(parent)
            if presenter is None:
                logger.warning(
                    "DownloadsManager: pizza_oven_conversion_presenter not found for Continue Setup"
                )
                shutil.rmtree(temp_dir, ignore_errors=True)
                return

            def _on_success():
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

            presenter.prompt_with_manual_options(
                parent,
                error_title=tr("errors.mod_not_compatible_title"),
                error_text=tr("errors.mod_requires_manual_installation"),
                informative_text=tr("dialogs.manual_install_available"),
                prepared_path=content_path,
                source_file_path=record.file_path,
                temp_dir=temp_dir,
                initial_game_type=initial_game_type,
                gamebanana_metadata=gb_metadata,
                on_success=_on_success,
            )
        except Exception as e:
            logger.error(
                "DownloadsManager: manual install dialog failed: %s", e, exc_info=True
            )
            with contextlib.suppress(Exception):
                shutil.rmtree(temp_dir, ignore_errors=True)
            record.use_status = UseStatus.NEEDS_MANUAL
            record.error_message = format_filesystem_error(e, path=record.file_path)
            self._store.update(record)
            self.record_updated.emit(record)

    def _build_dialog_metadata(self, record: DownloadRecord) -> dict:
        m = record.metadata or {}
        if not m.get("gb_mod_id"):
            return {}
        return {
            "mod_id": m["gb_mod_id"],
            "item_type": m.get("item_type", "mod"),
            "name": m.get("name") or record.display_name,
            "author": m.get("author"),
            "version": m.get("version"),
            "description": m.get("description"),
            "file_name": m.get("file_name"),
            "homepage": m.get("homepage") or m.get("profile_url"),
            "icon": m.get("icon"),
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
