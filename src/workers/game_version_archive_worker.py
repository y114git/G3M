"""Workers for Game Versions file operations (create/apply/export/import/download)."""

import json
import logging
import os
import shutil
import zipfile
from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from config.config import GAME_VERSION_MANIFEST_FILENAME
from services.localization_service import tr
from services.mod_operation_executor import (
    ModOperationExecutionError,
    ModOperationExecutor,
)
from services.mod_operation_support import (
    collect_profile_operation_inputs,
    collect_selected_merge_steps,
    collect_selected_mod_ids,
    create_g3mtool_merger,
    create_g3mtool_patcher,
    format_direct_operation_paths,
)
from services.mod_usage import hold_mods
from ui.utils.thread_lifetime import ManagedQThread
from ui.utils.thread_lifetime import safe_emit as _safe_emit
from utils.mod.archive import ArchiveVirtualPath, list_archive_members
from utils.network_utils import get_session
from utils.path_utils import resolve_execution_runtime, resolve_game_executable
from utils.problem_text import describe_finding
from utils.process_utils import format_filesystem_error, format_network_error

logger = logging.getLogger(__name__)


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
    """Copy a game, apply selected config operations, then archive the copy."""

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
        self._patcher = create_g3mtool_patcher(
            app_state, is_cancelled=self.isInterruptionRequested
        )
        self._merger = create_g3mtool_merger(
            app_state, is_cancelled=self.isInterruptionRequested
        )

    def _selected_mod_ids(self) -> tuple[str, ...]:
        return collect_selected_mod_ids(self._chapter_mods)

    def _build_operation_plan(self, game_copy: Path):
        game_mode = self._app_state.game_mode
        config = self._app_state.local_config
        custom_key = game_mode.get_custom_exec_config_key()
        custom_executable = config.get(custom_key, "") if custom_key else ""
        executable = (
            custom_executable
            if isinstance(custom_executable, str) and os.path.isfile(custom_executable)
            else resolve_game_executable(
                game_mode.get_game_path(config), game_mode.executable_type
            )
        )
        runtime = resolve_execution_runtime(executable)
        resolved_game_copy = game_copy.resolve(strict=False)
        inputs = collect_profile_operation_inputs(
            self._mod_service,
            self._selected_mod_ids(),
            game_id=str(getattr(game_mode, "game_id", "") or ""),
            game_path=resolved_game_copy,
            game_data_path=resolved_game_copy.parent / "game_data",
            runtime=runtime,
            user_path=resolved_game_copy.parent / "user",
        )
        plan = inputs.build_plan(
            tuple(inputs.configs),
            merge_steps=collect_selected_merge_steps(self._chapter_mods),
        )
        safe_operations = []
        skipped_indexes: set[int] = set()
        for operation in plan.operations:
            target = operation.target
            target_path = target.archive if isinstance(target, ArchiveVirtualPath) else target
            resolved_target = Path(target_path).resolve(strict=False) if target_path is not None else None
            if resolved_target is not None and not resolved_target.is_relative_to(resolved_game_copy):
                skipped_indexes.add(operation.index)
                continue
            safe_operations.append(operation)
        if skipped_indexes:
            logger.warning(
                "Skipped %s custom operation(s) while creating game version",
                len(skipped_indexes),
            )
        # Findings are indexed by the operation that produced them.  A target
        # outside the copied game is intentionally not applied here, so its
        # missing/hash/link diagnostics must not reject an otherwise valid
        # snapshot.  Keep findings for every retained operation and all
        # profile/configuration-level findings (which have no operation index).
        findings = tuple(
            finding
            for finding in plan.findings
            if finding.operation_index not in skipped_indexes
        )
        return plan.__class__(tuple(safe_operations), findings), len(skipped_indexes)

    def direct_operation_path_details(self) -> str:
        details: list[str] = []
        for mod_id in self._selected_mod_ids():
            config = self._mod_service.get_mod_config(mod_id)
            if isinstance(config, dict):
                detail = format_direct_operation_paths(config, mod_id=mod_id)
                if detail:
                    details.append(detail)
        return "\n".join(details)

    def run(self):
        with hold_mods(self._selected_mod_ids()):
            self._run()

    def _run(self):
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

            operation_plan, skipped = self._build_operation_plan(Path(temp_game).resolve(strict=False))
            if operation_plan.has_errors:
                raise ModOperationExecutionError(
                    operation_plan.findings[0].message, describe_finding(operation_plan.findings[0])
                )
            ModOperationExecutor(
                Path(self._temp_copy) / "journal", patcher=self._patcher, merger=self._merger
            ).execute(
                operation_plan,
                progress=lambda done, total, _operation: _safe_emit(
                    self.__class__.__name__,
                    self.progress,
                    40 + int(done * 40 / max(total, 1)),
                ),
                is_cancelled=self.isInterruptionRequested,
                step_progress=lambda overall, _done, _count, _operation, _percent: _safe_emit(
                    self.__class__.__name__, self.progress, 40 + int(overall * 40)
                ),
            )
            if skipped:
                patching_error = tr(
                    "status.skipped_operations_outside_game", count=skipped
                )

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
            list_archive_members(self._archive_path)
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
            if os.path.exists(self._dest) and os.path.samefile(self._source, self._dest):
                raise ValueError("Archive destination must differ from its source")
            list_archive_members(self._source)
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
            if os.path.exists(self._dest) and os.path.samefile(self._source, self._dest):
                raise ValueError("Archive destination must differ from its source")
            list_archive_members(self._source)
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
