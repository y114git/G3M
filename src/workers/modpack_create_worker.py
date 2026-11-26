"""Create one portable mod from the current operations selected in a profile."""

from __future__ import annotations

import filecmp
import logging
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from PyQt6.QtCore import pyqtSignal

from adapters.g3mtool_adapter import G3MToolManager
from services.localization_service import tr
from services.mod_operation_executor import (
    ModOperationExecutionError,
    ModOperationExecutor,
)
from services.mod_operation_support import (
    collect_selected_mod_ids,
    create_g3mtool_merger,
    create_g3mtool_patcher,
    format_direct_operation_paths,
)
from services.mod_usage import hold_mods
from ui.utils.thread_lifetime import ManagedQThread
from ui.utils.thread_lifetime import safe_emit as _safe_emit
from utils.mod.archive import ArchiveVirtualPath
from utils.mod.config import (
    MOD_CONFIG_VERSION,
    iter_mod_config_leaves,
    parse_mod_config,
    write_mod_config,
)
from utils.mod.operation_plan import (
    ModOperationPlan,
    ModPathContext,
    build_mod_operation_plan,
)
from utils.path_utils import resolve_execution_runtime, resolve_game_executable
from utils.problem_text import describe_finding
from workers.mod.operation_worker import describe_step

logger = logging.getLogger(__name__)
_CUSTOM_PLACEHOLDER_ROOT_RE = re.compile(
    r"^\$\{(?P<name>[A-Za-z][A-Za-z0-9_]*)\}"
)
_DATA_FILENAMES = frozenset({"data.win", "game.unx", "game.ios"})


class CreateModpackThread(ManagedQThread):
    progress_update = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str)
    warning_confirmation_needed = pyqtSignal(object, str, object)
    result_ready = pyqtSignal(bool)

    def __init__(
        self,
        chapter_mods: dict[str, list[Any]],
        modpack_name: str,
        modpack_dir: str,
        app_state,
        mod_service,
        parent=None,
        xdelta_modpack: bool = False,
    ) -> None:
        super().__init__(parent)
        self.chapter_mods = chapter_mods
        self.modpack_name = modpack_name
        self.modpack_dir = Path(modpack_dir)
        self.app_state = app_state
        self.mod_service = mod_service
        self.xdelta_modpack = xdelta_modpack
        self._cancelled = False
        self._patcher = create_g3mtool_patcher(app_state, is_cancelled=self._is_cancelled)
        self._merger = create_g3mtool_merger(app_state, is_cancelled=self._is_cancelled)

    def cancel(self) -> None:
        self._cancelled = True
        self.requestInterruption()
        _safe_emit(
            self.__class__.__name__,
            self.status_update,
            tr("status.operation_cancelled"),
            "error",
        )

    def confirm_warning(self, _accepted: bool) -> None:
        return

    def _is_cancelled(self) -> bool:
        return self._cancelled or self.isInterruptionRequested()

    def _selected_mod_ids(self) -> tuple[str, ...]:
        return collect_selected_mod_ids(self.chapter_mods)

    def _merge_details(self) -> dict[str, tuple[int, int]]:
        details: dict[str, tuple[int, int]] = {}
        group = 0
        for values in self.chapter_mods.values():
            steps = values if values and isinstance(values[0], list) else [values]
            for step in steps:
                mod_ids = tuple(
                    str(getattr(mod, "id", "") or (mod.get("id") if isinstance(mod, dict) else ""))
                    for mod in step
                )
                if len(mod_ids) < 2:
                    continue
                for priority, mod_id in enumerate(reversed(mod_ids)):
                    if mod_id:
                        details.setdefault(mod_id, (group, priority))
                group += 1
        return details

    def direct_operation_path_details(self) -> str:
        details: list[str] = []
        for mod_id in self._selected_mod_ids():
            config = self.mod_service.get_mod_config(mod_id)
            if isinstance(config, dict):
                detail = format_direct_operation_paths(config, mod_id=mod_id)
                if detail:
                    details.append(detail)
        return "\n".join(details)

    @staticmethod
    def _target_path(operation) -> Path | None:
        target = operation.target
        if target is None:
            return None
        return target.archive if isinstance(target, ArchiveVirtualPath) else target

    @staticmethod
    def _source_path(operation) -> Path:
        source = operation.source
        return source.archive if isinstance(source, ArchiveVirtualPath) else source

    @staticmethod
    def _copy(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)

    def _copy_operation_source(self, operation, number: int) -> str:
        source = self._source_path(operation)
        if not source.exists():
            raise ModOperationExecutionError(f"source does not exist: {source}")
        name = source.name or "source"
        destination = self.modpack_dir / "payload" / "operations" / f"{number:04d}" / name
        self._copy(source, destination)
        stored = f"${{mod_path}}/{destination.relative_to(self.modpack_dir).as_posix()}"
        if isinstance(operation.source, ArchiveVirtualPath):
            member = operation.source.member.strip("/")
            stored = f"{stored}/{member}" if member else stored
        if operation.source_is_directory:
            stored = f"{stored.rstrip('/')}/"
        return stored

    @staticmethod
    def _rename_target_placeholder(
        value: str,
        placeholders: dict[str, str],
        source_placeholders: dict[str, str],
        mod_number: int,
    ) -> str:
        match = _CUSTOM_PLACEHOLDER_ROOT_RE.match(value)
        if not match:
            return value
        name = match.group("name")
        if name not in source_placeholders:
            return value
        renamed = f"m{mod_number}_{name}"
        placeholders[renamed] = source_placeholders[name]
        return f"${{{renamed}}}{value[match.end():]}"

    @staticmethod
    def _changed_files(base: Path, staged: Path) -> list[Path]:
        changed: list[Path] = []
        for current, _directories, files in os.walk(staged):
            for name in files:
                candidate = Path(current) / name
                relative = candidate.relative_to(staged)
                original = base / relative
                if not original.is_file() or not filecmp.cmp(original, candidate, shallow=False):
                    changed.append(relative)
        return changed

    @staticmethod
    def _hard_roots(operations, game_root: Path) -> list[Path]:
        roots: list[Path] = []
        resolved_game_root = game_root.resolve(strict=False)
        for operation in operations:
            if operation.type not in {"hard-overwrite", "hard-extract"}:
                continue
            target = operation.target
            if not isinstance(target, Path) or not target.resolve(strict=False).is_relative_to(resolved_game_root):
                continue
            if operation.type == "hard-overwrite" and not operation.target_is_directory:
                target = target.parent
            elif (
                operation.type == "hard-overwrite"
                and operation.source_is_directory
                and operation.target_is_directory
            ):
                source = operation.source
                source_name = Path(source.member).name if isinstance(source, ArchiveVirtualPath) else source.name
                target = target / source_name
            if target.is_dir():
                roots.append(target)
        roots.sort(key=lambda item: len(item.parts))
        compact: list[Path] = []
        for root in roots:
            resolved_root = root.resolve(strict=False)
            if not any(resolved_root.is_relative_to(previous.resolve(strict=False)) for previous in compact):
                compact.append(root)
        return compact

    def _write_data_patch(self, base: Path, staged: Path, source: Path) -> Path:
        patch = source.with_suffix(f"{source.suffix}.xdelta")
        tool = G3MToolManager(self.app_state)
        if not tool.is_available():
            raise ModOperationExecutionError(tool.get_unavailable_reason())
        returncode, stdout, stderr = tool.xpatch_create(str(base), str(staged), str(patch))
        if returncode:
            raise ModOperationExecutionError(stderr or stdout or "cannot create xdelta patch")
        source.unlink()
        return patch

    def _materialize_game_changes(self, base: Path, staged: Path, operations) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        roots = self._hard_roots(operations, staged)
        for number, root in enumerate(roots, start=1):
            relative = root.relative_to(staged)
            destination = self.modpack_dir / "payload" / "game-directories" / f"{number:04d}"
            self._copy(root, destination)
            target = "${game_path}/"
            if relative != Path("."):
                target = f"${{game_path}}/{relative.as_posix()}/"
            entries.append(
                {
                    "source": f"${{mod_path}}/{destination.relative_to(self.modpack_dir).as_posix()}/",
                    "target": target,
                    "type": "hard-extract",
                }
            )
        changed_files = self._changed_files(base, staged)
        for number, relative in enumerate(changed_files, start=1):
            source = staged / relative
            resolved_source = source.resolve(strict=False)
            if any(resolved_source.is_relative_to(root.resolve(strict=False)) for root in roots):
                continue
            destination = self.modpack_dir / "payload" / "game-files" / relative
            self._copy(source, destination)
            stored = f"${{mod_path}}/{destination.relative_to(self.modpack_dir).as_posix()}"
            operation_type = "overwrite"
            original = base / relative
            if self.xdelta_modpack and original.is_file() and source.name.casefold() in _DATA_FILENAMES:
                patch = self._write_data_patch(original, source, destination)
                stored = f"${{mod_path}}/{patch.relative_to(self.modpack_dir).as_posix()}"
                operation_type = "patch"
            entries.append(
                {
                    "source": stored,
                    "target": f"${{game_path}}/{relative.as_posix()}",
                    "type": operation_type,
                }
            )
            _safe_emit(
                self.__class__.__name__,
                self.progress_update,
                75 + int(number * 20 / max(1, len(changed_files))),
                tr("status.bundling_files"),
            )
        return entries

    def _build_bundle(self) -> None:
        selected_ids = self._selected_mod_ids()
        if not selected_ids:
            raise ModOperationExecutionError("no mods are selected")
        game_mode = self.app_state.game_mode
        config = self.app_state.local_config
        game_path = Path(game_mode.get_game_path(config)).resolve(strict=False)
        if not game_path.is_dir():
            raise ModOperationExecutionError("game folder is unavailable")
        custom_key = game_mode.get_custom_exec_config_key()
        custom_executable = config.get(custom_key, "") if custom_key else ""
        executable = (
            custom_executable
            if isinstance(custom_executable, str) and os.path.isfile(custom_executable)
            else resolve_game_executable(str(game_path), game_mode.executable_type)
        )
        runtime = resolve_execution_runtime(executable)
        self.modpack_dir.mkdir(parents=True, exist_ok=True)
        placeholders: dict[str, str] = {}
        direct_entries: list[dict[str, str]] = []
        game_operations = []
        authors: list[str] = []
        game = ""
        merge_details = self._merge_details()

        with tempfile.TemporaryDirectory(prefix="g3m_modpack_") as temporary_name:
            staged_game = (Path(temporary_name) / "game").resolve(strict=False)
            shutil.copytree(game_path, staged_game)
            for mod_number, mod_id in enumerate(selected_ids, start=1):
                if self._is_cancelled():
                    raise InterruptedError("cancelled")
                mod_config = self.mod_service.get_mod_config(mod_id)
                mod_root = self.mod_service.get_mod_folder_path(mod_id)
                if not isinstance(mod_config, dict) or not mod_root:
                    raise ModOperationExecutionError(f"selected mod is unavailable: {mod_id}")
                parsed = parse_mod_config(mod_config)
                if game and parsed["game"] != game:
                    raise ModOperationExecutionError("selected mods must target one game")
                game = str(parsed["game"])
                parsed_authors = parsed["authors"]
                if isinstance(parsed_authors, list):
                    for author_name in parsed_authors:
                        if isinstance(author_name, str) and author_name not in authors:
                            authors.append(author_name)
                context = ModPathContext.create(
                    mod_path=mod_root,
                    game_path=staged_game,
                    game_data_path=game_mode.get_data_path(config),
                    user_path=Path.home(),
                    runtime=runtime,
                )
                plan = build_mod_operation_plan(parsed, context)
                if plan.has_errors:
                    raise ModOperationExecutionError(plan.findings[0].message, describe_finding(plan.findings[0]))
                parsed_files = parsed["files"]
                if not isinstance(parsed_files, list):
                    raise ModOperationExecutionError("mod files are invalid")
                leaves = [leaf for _path, leaf in iter_mod_config_leaves(parsed_files)]
                raw_placeholders = parsed.get("placeholders")
                source_placeholders = {
                    str(name): str(value)
                    for name, value in cast(Mapping[object, object], raw_placeholders or {}).items()
                    if isinstance(name, str) and isinstance(value, str)
                }
                for operation, leaf in zip(plan.operations, leaves, strict=True):
                    target = self._target_path(operation)
                    resolved_target = target.resolve(strict=False) if target is not None else None
                    if resolved_target is not None and resolved_target.is_relative_to(staged_game):
                        merge_group, merge_priority = merge_details.get(mod_id, (None, 0))
                        game_operations.append(
                            replace(
                                operation,
                                mod_id=mod_id,
                                merge_group=merge_group,
                                merge_priority=merge_priority,
                            )
                        )
                        continue
                    entry: dict[str, str] = {
                        "source": self._copy_operation_source(operation, len(direct_entries) + 1),
                        "type": str(leaf["type"]),
                    }
                    if "target" in leaf:
                        entry["target"] = self._rename_target_placeholder(
                            str(leaf["target"]),
                            placeholders,
                            source_placeholders,
                            mod_number,
                        )
                    for hash_name in ("source_hash", "target_hash"):
                        if isinstance(leaf.get(hash_name), str):
                            entry[hash_name] = str(leaf[hash_name])
                    direct_entries.append(entry)

            executor = ModOperationExecutor(
                Path(temporary_name) / "journal",
                patcher=self._patcher,
                merger=self._merger,
            )
            plan = ModOperationPlan(tuple(game_operations), ())
            executor.execute(
                plan,
                is_cancelled=self._is_cancelled,
                step_progress=lambda overall, done, count, operation, percent: _safe_emit(
                    self.__class__.__name__,
                    self.progress_update,
                    5 + int(overall * 70),
                    describe_step(
                        plan.operations,
                        operation,
                        done + (len(ModOperationExecutor.merge_operations(plan.operations, operation)) or 1),
                        count,
                        percent,
                    ),
                ),
            )
            entries = [*direct_entries, *self._materialize_game_changes(game_path, staged_game, game_operations)]

        config_data: dict[str, object] = {
            "config_version": MOD_CONFIG_VERSION,
            "id": f"local_{uuid.uuid4().hex[:12]}",
            "name": self.modpack_name,
            "version": "1.0.0",
            "authors": authors or ["Multiple authors"],
            "game": game,
            "files": entries,
        }
        if placeholders:
            config_data["placeholders"] = placeholders
        write_mod_config(self.modpack_dir / "mod_config.json", config_data, indent=4)

    def run(self) -> None:
        with hold_mods(self._selected_mod_ids()):
            self._run()

    def _run(self) -> None:
        success = False
        try:
            self._build_bundle()
            success = not self._is_cancelled()
            if success:
                _safe_emit(
                    self.__class__.__name__,
                    self.progress_update,
                    100,
                    tr("status.modpack_created"),
                )
        except InterruptedError:
            pass
        except Exception as error:
            logger.error("CreateModpackThread failed: %s", error, exc_info=True)
            _safe_emit(
                self.__class__.__name__,
                self.status_update,
                tr("errors.modpack_creation_failed"),
                "error",
            )
        finally:
            if not success and self.modpack_dir.exists():
                shutil.rmtree(self.modpack_dir, ignore_errors=True)
            _safe_emit(self.__class__.__name__, self.result_ready, success)
