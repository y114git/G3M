"""Game Versions coordinator. Created once in AppWindow."""

import contextlib
import logging
import os

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QFileDialog

from models.game_modes import get_game
from models.game_version_models import GameVersionRecord
from services.game_versions_store import GameVersionsStore
from utils.game_version_utils import (
    get_base_game_folder,
    get_protected_exe_paths_with_config,
    unique_archive_path,
)
from utils.time_utils import utc_now_iso

logger = logging.getLogger(__name__)


class GameVersionsManager(QObject):
    """Coordinator for all game version operations."""

    record_added = pyqtSignal(object)
    record_removed = pyqtSignal(str)
    record_updated = pyqtSignal(object)
    progress_updated = pyqtSignal(str, int)
    operation_error = pyqtSignal(str)
    operation_finished = pyqtSignal()

    def __init__(self, base_dir: str, settings_getter, parent=None) -> None:
        super().__init__(parent)
        self._store = GameVersionsStore(base_dir)
        self._settings = settings_getter
        self._workers = {}
        self._applying = set()

    @property
    def store(self) -> GameVersionsStore:
        return self._store

    def startup(self):
        self._store.load()
        self._store.startup_recovery()

    def records_for_game(self, game_id: str):
        return self._store.records_for_game(game_id)

    def cancel_operation(self, archive_path: str):
        if archive_path in self._applying:
            return
        worker = self._workers.get(archive_path)
        if worker and worker.isRunning():
            worker.requestInterruption()

    def _get_game_context(self, game_id: str):
        game_def = get_game(game_id)
        if not game_def:
            self.operation_error.emit(f"Unknown game: {game_id}")
            return None
        config = self._settings()
        game_path = game_def.get_game_path(config)
        if not game_path or not os.path.exists(game_path):
            self.operation_error.emit("Game path not set or invalid")
            return None
        base_folder = get_base_game_folder(game_path)
        if not base_folder:
            self.operation_error.emit("Could not resolve base game folder")
            return None
        protected = get_protected_exe_paths_with_config(
            base_folder, game_path, game_def, config
        )
        return game_def, game_path, base_folder, protected, config

    def create_version(
        self,
        game_id: str,
        version_name: str,
        profile_name=None,
        chapter_mods=None,
        app_state=None,
        mod_service=None,
    ):
        ctx = self._get_game_context(game_id)
        if not ctx:
            return
        _game_def, game_path, base_folder, protected, _config = ctx
        archive_path = unique_archive_path(self._store.versions_dir, version_name)
        record = GameVersionRecord(
            archive_path=archive_path,
            game=game_id,
            source_game_path=game_path,
            archive_exists=False,
            profile_name=profile_name,
        )
        self._store.add(record)

        use_patched = profile_name and chapter_mods and app_state and mod_service
        if use_patched:
            from workers.game_version_archive_worker import CreatePatchedVersionWorker

            worker = CreatePatchedVersionWorker(
                archive_path,
                base_folder,
                protected,
                app_state,
                mod_service,
                chapter_mods,
                parent=self,
            )
        else:
            from workers.game_version_archive_worker import CreateVersionWorker

            worker = CreateVersionWorker(
                archive_path, base_folder, protected, parent=self
            )
        self._workers[archive_path] = worker
        worker.progress.connect(lambda p: self.progress_updated.emit(archive_path, p))

        def on_finished(*args):
            self._workers.pop(archive_path, None)
            worker.deleteLater()
            success, error, size_bytes, file_count = args[0], args[1], args[2], args[3]
            patching_error = args[4] if len(args) > 4 else None
            if not success:
                self._store.remove(archive_path)
                self.record_removed.emit(archive_path)
                if error != "cancelled":
                    self.operation_error.emit(error or "Create version failed")
                return
            record.archive_exists = True
            record.size_bytes = size_bytes
            record.file_count = file_count
            if patching_error:
                record.patching_error = patching_error
            self._store.update(record)
            self.record_updated.emit(record)
            self.operation_finished.emit()

        worker.finished.connect(on_finished)
        worker.start()
        self.record_added.emit(record)

    def apply_version(self, archive_path: str):
        record = self._store.find(archive_path)
        if not record:
            self.operation_error.emit("Version record not found")
            return
        if not record.archive_exists:
            self.operation_error.emit("Archive file missing")
            return
        ctx = self._get_game_context(record.game)
        if not ctx:
            return
        _game_def, _game_path, base_folder, protected, config = ctx
        full_replace = config.get("versions_full_replace_files", False)

        from workers.game_version_archive_worker import ApplyVersionWorker

        worker = ApplyVersionWorker(
            archive_path, base_folder, protected, full_replace, parent=self
        )
        self._workers[archive_path] = worker
        self._applying.add(archive_path)
        worker.progress.connect(lambda p: self.progress_updated.emit(archive_path, p))

        def on_finished(success, error):
            self._workers.pop(archive_path, None)
            self._applying.discard(archive_path)
            worker.deleteLater()
            if not success:
                if error != "cancelled":
                    self.operation_error.emit(error or "Apply version failed")
                self.record_updated.emit(record)
                return
            self.record_updated.emit(record)
            self.operation_finished.emit()

        worker.finished.connect(on_finished)
        worker.start()

    def delete_version(self, archive_path: str):
        worker = self._workers.get(archive_path)
        if worker and worker.isRunning():
            worker.requestInterruption()
            worker.finished.connect(lambda *_: self._finalize_delete(archive_path))
            return
        self._finalize_delete(archive_path)

    def _finalize_delete(self, archive_path: str):
        self._workers.pop(archive_path, None)
        record = self._store.find(archive_path)
        if record and record.archive_exists and os.path.isfile(archive_path):
            try:
                os.remove(archive_path)
            except OSError as e:
                logger.warning(
                    "GameVersionsManager: could not delete archive %s: %s",
                    archive_path,
                    e,
                )
        self._store.remove(archive_path)
        self.record_removed.emit(archive_path)

    def export_game_version(self, archive_path: str, parent_widget=None):
        record = self._store.find(archive_path)
        if not record:
            self.operation_error.emit("Version record not found")
            return
        if not record.archive_exists:
            self.operation_error.emit("Archive file missing")
            return
        from services.localization_service import tr

        dest, _ = QFileDialog.getSaveFileName(
            parent_widget,
            tr("game_versions.export_title"),
            record.display_name + ".zip",
            "ZIP (*.zip)",
        )
        if not dest:
            return
        manifest = {
            "manifest_version": 1,
            "display_name": record.display_name,
            "game": record.game,
            "created_at": record.created_at,
            "exported_at": utc_now_iso(),
            "source_app": "DELTAHUB",
            "source_game_path": record.source_game_path,
            "file_count": record.file_count,
            "size_bytes": record.size_bytes,
        }
        from workers.game_version_archive_worker import GameExportVersionWorker

        worker = GameExportVersionWorker(archive_path, dest, manifest, parent=self)
        key = f"export_{archive_path}"
        self._workers[key] = worker
        worker.progress.connect(lambda p: self.progress_updated.emit(archive_path, p))

        def on_finished(success, error):
            self._workers.pop(key, None)
            worker.deleteLater()
            if not success:
                if error != "cancelled":
                    self.operation_error.emit(error or "Export failed")
                self.record_updated.emit(record)
                return
            self.record_updated.emit(record)
            self.operation_finished.emit()

        worker.finished.connect(on_finished)
        worker.start()

    def import_game_version_from_file(
        self, game_id: str, source: str, cleanup_source_path=None
    ):
        temp_name = os.path.splitext(os.path.basename(source))[0]
        dest_path = unique_archive_path(self._store.versions_dir, temp_name)
        record = GameVersionRecord(
            archive_path=dest_path,
            game=game_id,
            imported=True,
            archive_exists=False,
        )
        self._store.add(record)

        from workers.game_version_archive_worker import GameImportVersionWorker

        worker = GameImportVersionWorker(source, dest_path, parent=self)
        self._workers[dest_path] = worker
        worker.progress.connect(lambda p: self.progress_updated.emit(dest_path, p))

        def on_finished(success, error, manifest):
            self._workers.pop(dest_path, None)
            worker.deleteLater()
            try:
                if not success:
                    self._store.remove(dest_path)
                    self.record_removed.emit(dest_path)
                    if error != "cancelled":
                        self.operation_error.emit(error or "Import failed")
                    return
                manifest_game = manifest.get("game", "")
                if manifest_game and manifest_game != game_id:
                    self.operation_error.emit(
                        f"Version is for {manifest_game}, but current game is {game_id}"
                    )
                    self._store.remove(dest_path)
                    self.record_removed.emit(dest_path)
                    with contextlib.suppress(OSError):
                        os.remove(dest_path)
                    return
                display_name = manifest.get("display_name", temp_name)
                final_path = unique_archive_path(self._store.versions_dir, display_name)
                if final_path != dest_path:
                    try:
                        os.rename(dest_path, final_path)
                        self._store.remove(dest_path)
                    except OSError:
                        final_path = dest_path
                size = os.path.getsize(final_path) if os.path.isfile(final_path) else 0
                if final_path != dest_path:
                    new_record = GameVersionRecord(
                        archive_path=final_path,
                        game=game_id,
                        source_game_path=manifest.get("source_game_path"),
                        size_bytes=size,
                        file_count=manifest.get("file_count", 0),
                        imported=True,
                        archive_exists=True,
                        created_at=manifest.get("created_at", utc_now_iso()),
                    )
                    self._store.add(new_record)
                    self.record_removed.emit(dest_path)
                    self.record_added.emit(new_record)
                else:
                    record.archive_exists = True
                    record.size_bytes = size
                    record.file_count = manifest.get("file_count", 0)
                    record.source_game_path = manifest.get("source_game_path")
                    record.created_at = manifest.get("created_at", record.created_at)
                    self._store.update(record)
                    self.record_updated.emit(record)
                self.operation_finished.emit()
            finally:
                if cleanup_source_path and cleanup_source_path != dest_path:
                    try:
                        os.remove(cleanup_source_path)
                    except OSError as e:
                        logger.warning(
                            "GameVersionsManager: could not delete import source %s: %s",
                            cleanup_source_path,
                            e,
                        )

        worker.finished.connect(on_finished)
        worker.start()
        self.record_added.emit(record)

    def import_game_version_from_url(self, game_id: str, url: str):
        import tempfile

        from workers.game_version_archive_worker import UrlDownloadWorker

        filename = os.path.basename(url.split("?")[0]) or "version.zip"
        dest = os.path.join(tempfile.gettempdir(), filename)
        worker = UrlDownloadWorker(url, dest, parent=self)
        key = f"url_{url}"
        self._workers[key] = worker

        def on_finished(success, error):
            self._workers.pop(key, None)
            worker.deleteLater()
            if not success:
                self.operation_error.emit(error or "URL download failed")
                return
            self.import_game_version_from_file(game_id, dest, cleanup_source_path=dest)

        worker.finished.connect(on_finished)
        worker.start()

    def is_busy(self, archive_path: str) -> bool:
        w = self._workers.get(archive_path)
        return bool(w and w.isRunning())

    def is_applying(self, archive_path: str) -> bool:
        return archive_path in self._applying
