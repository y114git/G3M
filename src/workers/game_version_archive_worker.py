"""Workers for Game Versions file operations (create/apply/export/import/download)."""

import json
import logging
import os
import shutil
import zipfile

from PyQt6.QtCore import pyqtSignal

from config.config import GAME_VERSION_MANIFEST_FILENAME
from services.localization_service import tr
from ui.utils.thread_lifetime import ManagedQThread
from utils.network_utils import get_session
from utils.process_utils import format_filesystem_error, format_network_error

logger = logging.getLogger(__name__)


def _safe_emit(owner: str, signal, *args, emitter=None) -> None:
    try:
        (emitter or signal.emit)(*args)
    except Exception as e:
        logger.warning("%s: failed to emit signal: %s", owner, e, exc_info=True)


class CreateVersionWorker(ManagedQThread):
    """Archive the base game folder into a zip, excluding protected exe files."""

    progress = pyqtSignal(int)
    result_ready = pyqtSignal(bool, str, int, int)

    def __init__(
        self, archive_path: str, base_folder: str, protected: set[str], parent=None
    ) -> None:
        super().__init__(parent)
        self._archive_path = archive_path
        self._base_folder = base_folder
        self._protected = {p.replace("\\", "/") for p in protected}

    def run(self):
        try:
            all_files = []
            for root, _, files in os.walk(self._base_folder):
                for fname in files:
                    full = os.path.join(root, fname)
                    rel = os.path.relpath(full, self._base_folder).replace("\\", "/")
                    if rel not in self._protected:
                        all_files.append((full, rel))
            total = len(all_files) or 1
            file_count = 0
            with zipfile.ZipFile(
                self._archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9
            ) as zf:
                for i, (full, rel) in enumerate(all_files):
                    if self.isInterruptionRequested():
                        raise InterruptedError("Cancelled")
                    zf.write(full, rel)
                    file_count += 1
                    _safe_emit(self.__class__.__name__, self.progress, int((i + 1) * 100 / total))
            size = os.path.getsize(self._archive_path)
            _safe_emit(self.__class__.__name__, self.result_ready, True, "", size, file_count)
        except InterruptedError:
            self._cleanup()
            _safe_emit(self.__class__.__name__, self.result_ready, False, "cancelled", 0, 0)
        except Exception as e:
            logger.error("CreateVersionWorker failed: %s", e, exc_info=True)
            self._cleanup()
            _safe_emit(self.__class__.__name__, self.result_ready,
                False,
                format_filesystem_error(e, path=self._archive_path),
                0,
                0,
            )

    def _cleanup(self):
        try:
            if os.path.exists(self._archive_path):
                os.remove(self._archive_path)
        except OSError as e:
            logger.debug(f"Failed to cleanup archive {self._archive_path}: {e}")


class CreatePatchedVersionWorker(ManagedQThread):
    """Copy game folder to temp, apply mods via G3MToolPatchingService, then archive."""

    progress = pyqtSignal(int)
    result_ready = pyqtSignal(bool, str, int, int, str)

    def __init__(
        self,
        archive_path: str,
        base_folder: str,
        protected: set[str],
        app_state,
        mod_service,
        chapter_mods: dict,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._archive_path = archive_path
        self._base_folder = base_folder
        self._protected = {p.replace("\\", "/") for p in protected}
        self._app_state = app_state
        self._mod_service = mod_service
        self._chapter_mods = chapter_mods
        self._temp_copy = None

    def run(self):
        import tempfile

        patching_error = ""
        try:
            self._temp_copy = tempfile.mkdtemp(prefix="g3m_gv_patch_")
            temp_game = os.path.join(self._temp_copy, "game")

            all_files = []
            for root, _, files in os.walk(self._base_folder):
                for fname in files:
                    full = os.path.join(root, fname)
                    rel = os.path.relpath(full, self._base_folder).replace("\\", "/")
                    all_files.append((full, rel))
            total_copy = len(all_files) or 1
            for i, (full, rel) in enumerate(all_files):
                if self.isInterruptionRequested():
                    raise InterruptedError("Cancelled")
                dest = os.path.join(temp_game, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(full, dest)
                _safe_emit(self.__class__.__name__, self.progress, int((i + 1) * 40 / total_copy))

            try:
                from services.g3mtool_patching_service import G3MToolPatchingService

                patcher = G3MToolPatchingService(
                    self._app_state, self._mod_service, None
                )
                patcher.progress_update.connect(
                    lambda p, _msg: _safe_emit(self.__class__.__name__, self.progress, 40 + int(p * 0.4))
                )
                patcher.set_override_game_path(temp_game)
                success = patcher.process_sections(
                    self._chapter_mods, is_modpack=False
                )
                if not success:
                    patching_error = "Mod patching failed"
                patcher.cleanup(force=True)
            except Exception as e:
                logger.error(
                    "CreatePatchedVersionWorker: patching failed: %s", e, exc_info=True
                )
                patching_error = str(e)

            archive_files = []
            for root, _, files in os.walk(temp_game):
                for fname in files:
                    full = os.path.join(root, fname)
                    rel = os.path.relpath(full, temp_game).replace("\\", "/")
                    if rel not in self._protected:
                        archive_files.append((full, rel))
            total_archive = len(archive_files) or 1
            file_count = 0
            with zipfile.ZipFile(
                self._archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9
            ) as zf:
                for i, (full, rel) in enumerate(archive_files):
                    if self.isInterruptionRequested():
                        raise InterruptedError("Cancelled")
                    zf.write(full, rel)
                    file_count += 1
                    _safe_emit(self.__class__.__name__, self.progress, 80 + int((i + 1) * 20 / total_archive))
            size = os.path.getsize(self._archive_path)
            _safe_emit(self.__class__.__name__, self.result_ready, True, "", size, file_count, patching_error)
        except InterruptedError:
            self._cleanup()
            _safe_emit(self.__class__.__name__, self.result_ready, False, "cancelled", 0, 0, "")
        except Exception as e:
            logger.error("CreatePatchedVersionWorker failed: %s", e, exc_info=True)
            self._cleanup()
            _safe_emit(self.__class__.__name__, self.result_ready,
                False,
                format_filesystem_error(e, path=self._archive_path),
                0,
                0,
                "",
            )
        finally:
            if self._temp_copy and os.path.isdir(self._temp_copy):
                shutil.rmtree(self._temp_copy, ignore_errors=True)

    def _cleanup(self):
        try:
            if os.path.exists(self._archive_path):
                os.remove(self._archive_path)
        except OSError as e:
            logger.debug(f"Failed to cleanup archive {self._archive_path}: {e}")


class ApplyVersionWorker(ManagedQThread):
    """Extract a version zip into the base game folder."""

    progress = pyqtSignal(int)
    result_ready = pyqtSignal(bool, str)

    def __init__(
        self,
        archive_path: str,
        base_folder: str,
        protected: set[str],
        full_replace: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._archive_path = archive_path
        self._base_folder = base_folder
        self._protected = {p.replace("\\", "/") for p in protected}
        self._full_replace = full_replace

    def run(self):
        try:
            if not os.path.isfile(self._archive_path):
                _safe_emit(self.__class__.__name__, self.result_ready,
                    False, tr("errors.file_not_found", path=self._archive_path)
                )
                return
            with zipfile.ZipFile(self._archive_path, "r") as zf:
                bad = zf.testzip()
                if bad is not None:
                    _safe_emit(self.__class__.__name__, self.result_ready, False, f"Corrupt archive entry: {bad}")
                    return
                if self.isInterruptionRequested():
                    _safe_emit(self.__class__.__name__, self.result_ready, False, "cancelled")
                    return
                entries = [info.filename for info in zf.infolist() if not info.is_dir()]
                archive_set = set(entries)
                if self._full_replace:
                    if self.isInterruptionRequested():
                        _safe_emit(self.__class__.__name__, self.result_ready, False, "cancelled")
                        return
                    self._delete_extra_files(archive_set)
                total = len(entries) or 1
                for i, entry in enumerate(entries):
                    if self.isInterruptionRequested():
                        _safe_emit(self.__class__.__name__, self.result_ready, False, "cancelled")
                        return
                    if entry.replace("\\", "/") in self._protected:
                        continue
                    target = os.path.join(self._base_folder, entry)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with zf.open(entry) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    _safe_emit(self.__class__.__name__, self.progress, int((i + 1) * 100 / total))
            _safe_emit(self.__class__.__name__, self.result_ready, True, "")
        except Exception as e:
            logger.error("ApplyVersionWorker failed: %s", e, exc_info=True)
            _safe_emit(self.__class__.__name__, self.result_ready,
                False, format_filesystem_error(e, path=self._archive_path)
            )

    def _delete_extra_files(self, archive_entries: set[str]):
        archive_norm = {e.replace("\\", "/") for e in archive_entries}
        for root, dirs, files in os.walk(self._base_folder, topdown=False):
            for fname in files:
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, self._base_folder).replace("\\", "/")
                if rel in self._protected:
                    continue
                if rel not in archive_norm:
                    try:
                        os.remove(full)
                    except OSError as e:
                        logger.debug(f"Failed to remove file {full}: {e}")
            for dname in dirs:
                full = os.path.join(root, dname)
                try:
                    if not os.listdir(full):
                        os.rmdir(full)
                except OSError as e:
                    logger.debug(f"Failed to remove empty directory {full}: {e}")


class GameExportVersionWorker(ManagedQThread):
    """Export internal game version as a standalone zip with game_version_data.json manifest."""

    progress = pyqtSignal(int)
    result_ready = pyqtSignal(bool, str)

    def __init__(
        self, source_archive: str, dest_path: str, manifest: dict, parent=None
    ) -> None:
        super().__init__(parent)
        self._source = source_archive
        self._dest = dest_path
        self._manifest = manifest

    def run(self):
        try:
            if not os.path.isfile(self._source):
                _safe_emit(self.__class__.__name__, self.result_ready,
                    False, tr("errors.file_not_found", path=self._source)
                )
                return
            with zipfile.ZipFile(self._source, "r") as src_zf:
                entries = [info for info in src_zf.infolist() if not info.is_dir()]
                total = len(entries) or 1
                with zipfile.ZipFile(
                    self._dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9
                ) as dst_zf:
                    for i, info in enumerate(entries):
                        if self.isInterruptionRequested():
                            raise InterruptedError("Cancelled")
                        dst_zf.writestr(info, src_zf.read(info.filename))
                        _safe_emit(self.__class__.__name__, self.progress, int((i + 1) * 100 / total))
                    dst_zf.writestr(
                        GAME_VERSION_MANIFEST_FILENAME,
                        json.dumps(self._manifest, ensure_ascii=False, indent=2),
                    )
            _safe_emit(self.__class__.__name__, self.result_ready, True, "")
        except InterruptedError:
            try:
                if os.path.exists(self._dest):
                    os.remove(self._dest)
            except OSError as error:
                logger.debug("Best-effort operation failed: %s", error, exc_info=True)
            _safe_emit(self.__class__.__name__, self.result_ready, False, "cancelled")
        except Exception as e:
            logger.error("GameExportVersionWorker failed: %s", e, exc_info=True)
            _safe_emit(self.__class__.__name__, self.result_ready, False, format_filesystem_error(e, path=self._dest))


class GameImportVersionWorker(ManagedQThread):
    """Import an external zip(with game_version_data.json) into internal game versions storage."""

    progress = pyqtSignal(int)
    result_ready = pyqtSignal(bool, str, dict)

    def __init__(self, source_path: str, dest_archive: str, parent=None) -> None:
        super().__init__(parent)
        self._source = source_path
        self._dest = dest_archive

    def run(self):
        try:
            if not os.path.isfile(self._source):
                _safe_emit(self.__class__.__name__, self.result_ready,
                    False, tr("errors.file_not_found", path=self._source), {}
                )
                return
            with zipfile.ZipFile(self._source, "r") as zf:
                if GAME_VERSION_MANIFEST_FILENAME not in zf.namelist():
                    _safe_emit(self.__class__.__name__, self.result_ready,
                        False, f"Missing {GAME_VERSION_MANIFEST_FILENAME} manifest", {}
                    )
                    return
                manifest = json.loads(zf.read(GAME_VERSION_MANIFEST_FILENAME))
                if not isinstance(manifest, dict):
                    _safe_emit(self.__class__.__name__, self.result_ready, False, "Invalid manifest type", {})
                    return
                entries = [
                    info
                    for info in zf.infolist()
                    if not info.is_dir()
                    and info.filename != GAME_VERSION_MANIFEST_FILENAME
                ]
                total = len(entries) or 1
                with zipfile.ZipFile(
                    self._dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9
                ) as dst:
                    for i, info in enumerate(entries):
                        if self.isInterruptionRequested():
                            raise InterruptedError("Cancelled")
                        dst.writestr(info, zf.read(info.filename))
                        _safe_emit(self.__class__.__name__, self.progress, int((i + 1) * 100 / total))
            _safe_emit(self.__class__.__name__, self.result_ready, True, "", manifest)
        except InterruptedError:
            try:
                if os.path.exists(self._dest):
                    os.remove(self._dest)
            except OSError as error:
                logger.debug("Best-effort operation failed: %s", error, exc_info=True)
            _safe_emit(self.__class__.__name__, self.result_ready, False, "cancelled", {})
        except json.JSONDecodeError as e:
            logger.error("GameImportVersionWorker: invalid manifest: %s", e)
            _safe_emit(self.__class__.__name__, self.result_ready, False, "Invalid game_version_data.json manifest", {})
        except Exception as e:
            logger.error("GameImportVersionWorker failed: %s", e, exc_info=True)
            _safe_emit(self.__class__.__name__, self.result_ready,
                False, format_filesystem_error(e, path=self._source), {}
            )


class UrlDownloadWorker(ManagedQThread):
    """Download a file from a URL in a background thread."""

    result_ready = pyqtSignal(bool, str)

    def __init__(self, url: str, dest_path: str, parent=None) -> None:
        super().__init__(parent)
        self._url = url
        self._dest = dest_path

    def run(self):
        try:
            session = get_session()
            with session.get(self._url, stream=True, timeout=60) as response:
                response.raise_for_status()
                with open(self._dest, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self.isInterruptionRequested():
                            raise InterruptedError("Cancelled")
                        if chunk:
                            f.write(chunk)
            _safe_emit(self.__class__.__name__, self.result_ready, True, "")
        except InterruptedError:
            try:
                if os.path.exists(self._dest):
                    os.remove(self._dest)
            except OSError as error:
                logger.debug("Best-effort operation failed: %s", error, exc_info=True)
            _safe_emit(self.__class__.__name__, self.result_ready, False, "cancelled")
        except Exception as e:
            logger.error("UrlDownloadWorker failed: %s", e, exc_info=True)
            try:
                if os.path.exists(self._dest):
                    os.remove(self._dest)
            except OSError as error:
                logger.debug("Best-effort operation failed: %s", error, exc_info=True)
            _safe_emit(self.__class__.__name__, self.result_ready, False, format_network_error(e, url=self._url))
