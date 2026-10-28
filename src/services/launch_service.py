"""Game launch and mod patching management."""

import contextlib
import errno
import logging
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal
from PyQt6.QtGui import QColor

from config.config import UI_COLORS
from models.launch_modes import LaunchMode
from services.background_operations import background_operations
from services.game_detection_service import (
    get_chapter_id_for_game_mode,
    get_game_name_string,
    get_game_type_string,
    get_matching_process_identities,
)
from services.launch_transaction import LaunchState, LaunchTransaction
from services.localization_service import tr
from services.mod_operation_executor import (
    ModOperationJournal,
    ModRecoveryConflictError,
)
from services.mod_operation_support import (
    collect_profile_operation_inputs,
    confirm_operation_plan,
)
from services.warning_service import create_warning_event, is_warning_enabled
from ui.common.styling import get_launch_status_color
from ui.utils.thread_lifetime import ManagedQThread, retire_qthread
from utils.file_utils import ensure_writable
from utils.mod.config import MOD_CONFIG_VERSION
from utils.mod.operation_plan import (
    ModOperationPlan,
    PlanFinding,
)
from utils.mod.relations import analyze_mod_relations, recommend_mod_arrangement
from utils.native_integration import open_url_native
from utils.path_utils import (
    find_chapter_resource_dir,
    is_path_in_steam_common,
    resolve_execution_runtime,
    resolve_game_executable,
)
from utils.process_utils import (
    build_external_process_env,
    join_limited,
    resolve_portproton_command,
    resolve_wine_command,
)
from workers.game_monitor_worker import GameMonitorWorker
from workers.mod.journal_worker import ModOperationJournalThread
from workers.plugin_hook_worker import PluginHookThread

logger = logging.getLogger(__name__)


class GameLauncher(QObject):
    """Manages game launching, mod patching, and game monitoring."""

    status_changed = pyqtSignal(str, str)
    progress_updated = pyqtSignal(int)
    game_launch_started = pyqtSignal()
    game_launch_finished = pyqtSignal()
    def __init__(self, app_state, feedback_service, mod_service, parent=None) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.mod_service = mod_service
        self.monitor_thread = None
        self.monitor_worker = None
        self._direct_launch_cleanup_info = None
        self._patching_thread = None
        self._plugin_hook_thread = None
        self.restore_window_callback = None
        self._launch_started_at = None
        self._launch_mod_ids: list[str] = []
        self._selected_launch_mode = LaunchMode.NORMAL
        self._permanent_committed = False
        self._before_mod_apply_completed = False
        self._plugin_cleanup_notified = False
        self._game_started = False
        self._launch_had_mods = False
        self._game_process = None
        self._operation_journal: ModOperationJournal | None = None
        self._operation_journal_thread = None
        self._session_recovery_thread = None
        self._cleanup_callbacks: list = []
        self._cleanup_pending = False
        self._dependency_resolution_thread = None
        self._pending_dependency_launch: dict[str, Any] | None = None
        self._dependency_download_manager = None
        self._dependency_download_records: dict[str, str] = {}
        self.launch_transaction = LaunchTransaction()
        profile_service = getattr(parent, "profile_service", None)
        profile_switched = getattr(profile_service, "profile_switched", None)
        if profile_switched is not None:
            profile_switched.connect(self._on_profile_switched)

    def _launch_profile_context(self) -> tuple[str, str | None]:
        """Return the profile and mod root that own a pending launch."""
        parent = self.parent()
        profile_service = getattr(parent, "profile_service", None) if parent else None
        profile_name = getattr(profile_service, "active_name", None)
        if not isinstance(profile_name, str) or not profile_name:
            profile_name = self.app_state.local_config.get("active_profile", "Default")
        mods_dir = getattr(self.app_state, "mods_dir", None)
        return str(profile_name), str(Path(mods_dir).resolve()) if mods_dir else None

    def _pending_dependency_context_matches(self) -> bool:
        pending = self._pending_dependency_launch
        if not pending:
            return True
        expected_profile = pending.get("profile_name")
        expected_mods_dir = pending.get("target_mods_dir")
        profile_name, mods_dir = self._launch_profile_context()
        return (
            not isinstance(expected_profile, str)
            or expected_profile == profile_name
        ) and (
            not isinstance(expected_mods_dir, str)
            or (mods_dir is not None and os.path.normcase(expected_mods_dir) == os.path.normcase(mods_dir))
        )

    def _on_profile_switched(self, _profile_name: str) -> None:
        if self._pending_dependency_launch is None:
            return
        logger.info("Cancelling pending launch after profile switch")
        self.cancel_pending_launch("profile-changed")

    def _stop_monitor_thread(self):
        thread = self.monitor_thread
        worker = self.monitor_worker
        if not thread:
            return
        self.monitor_thread = None
        self.monitor_worker = None
        try:
            if thread.isRunning():
                thread.requestInterruption()
                thread.quit()
            self._retire_monitor(thread, worker)
        except Exception as e:
            logger.error(f"monitor thread cleanup failed: {e}", exc_info=True)

    def _retire_monitor(self, thread, worker) -> None:
        if thread is None:
            return
        thread._g3m_worker = worker
        retire_qthread(thread)

    def _launch_status_color(self) -> str:
        return get_launch_status_color(getattr(self.app_state, "local_config", None))

    def _start_game_monitor(
        self,
        process,
        vanilla_mode: bool,
        process_names: tuple[str, ...],
        baseline_processes,
    ) -> None:
        thread = ManagedQThread(self)
        worker = GameMonitorWorker(
            process, vanilla_mode, process_names, baseline_processes
        )
        worker.moveToThread(thread)
        thread.finished.connect(worker.deleteLater)
        worker.game_detected.connect(self._on_game_process_detected)
        worker.finished.connect(thread.quit)
        worker.finished.connect(self._on_game_process_finished)
        thread.started.connect(worker.run)
        self.monitor_thread = thread
        self.monitor_worker = worker
        thread.start()

    def _safe_feedback_status(self, message: str, color: str) -> None:
        try:
            self.feedback_service.update_status(message, color)
        except Exception:
            logger.exception("GameLauncher: failed to update feedback status")

    def _run_journal_operation(
        self,
        action: str,
        callback,
        *,
        journal: ModOperationJournal | None = None,
        journal_root: Path | None = None,
        force: bool = False,
        cleanup_info: dict | None = None,
        blocking: bool = False,
        include_error: bool = False,
    ) -> bool:
        if self._operation_journal_thread is not None:
            logger.warning("operation journal work is already in progress")
            return False
        thread = ModOperationJournalThread(
            action,
            journal=journal,
            journal_root=journal_root,
            force=force,
            cleanup_info=cleanup_info,
            parent=self,
        )

        self._operation_journal_thread = thread
        if blocking:
            thread.start()
            thread.wait()
            self._operation_journal_thread = None
            retire_qthread(thread)
            if include_error:
                callback(*thread.result, thread.error)
            else:
                callback(*thread.result)
            return True

        def finished(result) -> None:
            self._operation_journal_thread = None
            retire_qthread(thread)
            if include_error:
                callback(*result, thread.error)
            else:
                callback(*result)
            if self._cleanup_pending:
                self._cleanup_pending = False
                self._cleanup_direct_launch_files()

        thread.result_ready.connect(finished)
        thread.start()
        return True

    @staticmethod
    def _is_path_like_command(command_name: str) -> bool:
        return bool(command_name) and (
            os.path.isabs(command_name) or "/" in command_name or "\\" in command_name
        )

    def _translate_missing_launch_command(self, command_name: str) -> str:
        base_name = os.path.basename(command_name).lower()
        if "portproton" in base_name:
            if self._is_path_like_command(command_name):
                return tr("errors.custom_portproton_not_found", path=command_name)
            return tr("errors.portproton_not_found")
        if base_name.startswith("wine"):
            if self._is_path_like_command(command_name):
                return tr("errors.custom_wine_not_found", path=command_name)
            return tr("errors.wine_not_found")
        if self._is_path_like_command(command_name):
            return tr("errors.launch_command_missing_path", path=command_name)
        return tr("errors.launch_command_not_found", command=command_name)

    def _format_launch_error(
        self,
        launch_error: Exception,
        *,
        command: list[str] | None,
        target_path: str,
    ) -> str:
        command = command or []
        command_name = str(command[0]) if command else ""
        error_path = str(getattr(launch_error, "filename", "") or "")
        error_errno = getattr(launch_error, "errno", None)
        error_text = str(launch_error).lower()

        if isinstance(launch_error, IsADirectoryError) or error_errno == errno.EISDIR:
            return tr(
                "errors.launch_target_is_directory",
                path=error_path or target_path or command_name,
            )

        if isinstance(launch_error, FileNotFoundError) or error_errno == errno.ENOENT:
            if (
                error_path
                and target_path
                and os.path.abspath(error_path) == os.path.abspath(target_path)
            ):
                return tr("errors.launch_target_missing", path=target_path)
            if error_path and command_name and error_path == command_name:
                return self._translate_missing_launch_command(command_name)
            if command_name:
                return self._translate_missing_launch_command(command_name)
            return tr("errors.launch_target_missing", path=target_path)

        if isinstance(launch_error, PermissionError) or error_errno in (
            errno.EACCES,
            errno.EPERM,
        ):
            return tr(
                "errors.launch_permission_denied",
                path=error_path or target_path or command_name,
            )

        invalid_exe_keywords = [
            "not a valid",
            "invalid",
            "cannot execute",
            "exec format error",
            "bad executable",
            "invalid executable",
        ]
        if error_errno == errno.ENOEXEC or any(
            keyword in error_text for keyword in invalid_exe_keywords
        ):
            return tr(
                "errors.invalid_executable_file",
                file=os.path.basename(target_path or command_name),
            )

        return tr("errors.game_launch_error", error=str(launch_error))

    def _plugin_runtime_service(self):
        parent = self.parent()
        return getattr(parent, "plugin_runtime_service", None) if parent else None

    def _discord_rich_presence_service(self):
        parent = self.parent()
        return (
            getattr(parent, "discord_rich_presence_service", None) if parent else None
        )

    def _safe_discord_rich_presence_call(self, method_name: str, *args) -> None:
        service = self._discord_rich_presence_service()
        if service is None:
            return
        try:
            getattr(service, method_name)(*args)
        except Exception:
            logger.exception("Discord Rich Presence callback failed: %s", method_name)

    def close_game(self):
        worker = getattr(self, "monitor_worker", None)
        process = getattr(worker, "process", None)
        if process:
            try:
                process.terminate()
                self.status_changed.emit(
                    tr("status.game_closed"), self._launch_status_color()
                )
            except Exception as e:
                logger.error(f"Failed to terminate game process: {e}", exc_info=True)

    def launch_game_with_all_mods(
        self,
        restore_window_callback=None,
        mode: LaunchMode = LaunchMode.NORMAL,
        pre_hooks_done: bool = False,
    ):
        self._launch_game_with_selections(
            self._get_used_mods_selections(),
            restore_window_callback,
            mode,
            pre_hooks_done,
        )

    def _get_used_mods_selections(self) -> dict[str, Any]:
        used_mods_service = self._used_mods_service()
        if not used_mods_service or not hasattr(
            used_mods_service, "get_active_mod_selections"
        ):
            return {}
        return used_mods_service.get_active_mod_selections()

    def _used_mods_service(self):
        try:
            parent_obj = self.parent()
        except (AttributeError, TypeError):
            parent_obj = None
        return getattr(parent_obj, "used_mods_service", None) if parent_obj else None

    def _get_used_mod_steps(self) -> dict[str, list[list[Any]]]:
        used_mods_service = self._used_mods_service()
        if not used_mods_service or not hasattr(
            used_mods_service, "get_active_mod_steps"
        ):
            return {}
        return used_mods_service.get_active_mod_steps()

    def _launch_game_with_selections(
        self,
        selections: dict[str, Any],
        restore_window_callback=None,
        mode: LaunchMode = LaunchMode.NORMAL,
        pre_hooks_done: bool = False,
    ):
        self.launch_transaction.begin()
        self._launch_started_at = time.monotonic()
        self._launch_mod_ids = self._collect_launch_mod_ids(selections)
        self._launch_had_mods = self._has_selected_mods(selections)
        self._selected_launch_mode = mode
        self._permanent_committed = False
        self._before_mod_apply_completed = pre_hooks_done
        self._plugin_cleanup_notified = False
        self._game_started = False
        self.restore_window_callback = restore_window_callback
        self.status_changed.emit(
            tr("status.launching_game"), self._launch_status_color()
        )
        if self._operation_journal is not None:
            self.launch_transaction.transition(LaunchState.RECOVERING)
            if self._operation_journal.state == "restored":
                self._operation_journal = None
                self.launch_transaction.transition(LaunchState.COMPLETED)
                self.launch_transaction.begin()
            elif self._run_journal_operation(
                "restore",
                lambda restored, errors, error: self._on_pending_restore_finished(
                    selections, restored, errors, error
                ),
                journal=self._operation_journal,
                include_error=True,
            ):
                return
            else:
                self.launch_transaction.fail("pending-restore")
                self.status_changed.emit(
                    tr("errors.pending_session_restore_failed"),
                    UI_COLORS["status_error"],
                )
                self._handle_launch_failure("restore")
                return
        self._continue_launch_with_selections(selections)

    def _on_pending_restore_finished(
        self,
        selections: dict[str, Any],
        restored: bool,
        errors: list[str],
        error: Exception | None,
    ) -> None:
        if isinstance(error, ModRecoveryConflictError):
            self._resolve_pending_restore_conflict(selections, error)
            return
        if not restored:
            self.launch_transaction.fail("pending-restore")
            self.status_changed.emit(
                tr("errors.pending_session_restore_failed"), UI_COLORS["status_error"]
            )
            self._handle_launch_failure("restore")
            return
        self._operation_journal = None
        self.launch_transaction.transition(LaunchState.COMPLETED)
        self.launch_transaction.begin()
        self._continue_launch_with_selections(selections)

    def _ask_recovery_conflict(self, error: ModRecoveryConflictError) -> str:
        """Ask whether to force the restore; any other answer leaves the game files as they are."""
        logger.info("Game files changed since G3M applied mods, asking how to proceed: %s", error)
        resolve = getattr(self.feedback_service, "ask_operation_recovery_conflict", None)
        return "force" if callable(resolve) and resolve(str(error)) == "force" else "keep"

    def _resolve_pending_restore_conflict(
        self, selections: dict[str, Any], error: ModRecoveryConflictError
    ) -> None:
        journal = self._operation_journal
        choice = self._ask_recovery_conflict(error)
        if (
            choice == "force"
            and journal is not None
            and self._run_journal_operation(
                "restore",
                lambda restored, errors, retry_error: self._on_pending_restore_finished(
                    selections, restored, errors, retry_error
                ),
                journal=journal,
                force=True,
                include_error=True,
            )
        ):
            return
        if (
            journal is not None
            and self._run_journal_operation(
                "retire",
                lambda retired, errors, retire_error: self._on_pending_restore_finished(
                    selections, retired, errors, retire_error
                ),
                journal=journal,
                include_error=True,
            )
        ):
            return
        self.launch_transaction.fail("pending-restore")
        self.status_changed.emit(
            tr("errors.pending_session_restore_failed"), UI_COLORS["status_error"]
        )
        self._handle_launch_failure("restore")

    def _continue_launch_with_selections(self, selections: dict[str, Any]) -> None:
        has_selected_mods = self._launch_had_mods
        current_path = self._get_current_game_path()
        if not current_path or not os.path.exists(current_path):
            if not self._find_and_validate_game_path(selections, is_initial=False):
                if has_selected_mods:
                    self.status_changed.emit(
                        tr("status.game_path_required_for_mods"),
                        UI_COLORS["status_error"],
                    )
                else:
                    self.status_changed.emit(
                        tr("status.no_game_path"), UI_COLORS["status_error"]
                    )
                self._handle_launch_failure()
                return
            current_path = self._get_current_game_path()
        if has_selected_mods and (not current_path or not os.path.exists(current_path)):
            self.status_changed.emit(
                tr("status.game_path_required_for_mods"), UI_COLORS["status_error"]
            )
            self._handle_launch_failure()
            return
        has_list_format = any(
            isinstance(mods_list, list) for mods_list in selections.values()
        )
        needs_multi_mod = has_list_format and any(
            len(mods_list) > 0
            for mods_list in selections.values()
            if isinstance(mods_list, list)
        )
        logger.info(
            f"Multi-mod check: needs_multi_mod={needs_multi_mod} (has_list_format={has_list_format})"
        )
        if not self._before_mod_apply_completed:
            if self._start_plugin_hook_thread(
                "before_mod_apply",
                selections,
                base_progress=0,
                progress_span=5,
                finished_callback=self._on_before_mod_apply_finished,
            ):
                return
            self._before_mod_apply_completed = True
            self._safe_discord_rich_presence_call("on_before_mod_apply")
        if has_selected_mods:
            logger.info("Using ordered mod operations for game launch")
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.is_patching = True
            self.app_state.action_button_text = tr("ui.cancel_button")
            self.app_state.action_button_enabled = True
            if not self._prepare_game_files_multi_mod_async(
                selections, self._get_used_mod_steps(), needs_multi_mod
            ):
                if self._pending_dependency_launch is not None:
                    return
                logger.error(f"Failed to start patching for {len(selections)} selected mod group(s); see earlier log lines for the reason")
                self.app_state.progress_bar_visible = False
                self.app_state.is_patching = False
                self._handle_launch_failure()
                return
        else:
            self._continue_after_patching(selections, True, needs_multi_mod)

    def _handle_launch_failure(self, reason: str = "unknown"):
        self._notify_pre_launch_plugin_cancellation(reason)
        if self.launch_transaction.state not in {
            LaunchState.COMPLETED,
            LaunchState.FAILED,
        }:
            self.launch_transaction.fail(reason)
        if self.restore_window_callback:
            self.restore_window_callback()
        parent = self.parent()
        controller = getattr(parent, "game_launch", None) if parent else None
        if controller and hasattr(controller, "update_button_state"):
            controller.update_button_state()

    def _notify_pre_launch_plugin_cancellation(self, reason: str) -> None:
        if (
            not self._before_mod_apply_completed
            or self._plugin_cleanup_notified
            or self._game_started
            or self._permanent_committed
        ):
            return
        self._plugin_cleanup_notified = True
        payload = {"hook": "launch", "reason": reason}
        try:
            self._execute_plugin_hook("mod_apply_cancelled", payload)
        except Exception:
            logger.warning("Pre-launch plugin cleanup failed", exc_info=True)
        self._safe_discord_rich_presence_call("on_mod_apply_cancelled", payload)

    def cancel_pending_launch(self, hook: str | None = None) -> None:
        """Restore any applied files after the user cancels before the game starts."""
        dependency_thread = self._dependency_resolution_thread
        if dependency_thread is not None:
            dependency_thread.cancel()
            dependency_thread.requestInterruption()
            self._dependency_resolution_thread = None
            retire_qthread(dependency_thread)
        self._pending_dependency_launch = None
        self._clear_pending_dependency_downloads()
        self.launch_transaction.cancel()
        self.app_state.progress_bar_visible = True
        self.app_state.is_patching = True
        self.app_state.action_button_enabled = False
        self._cleanup_direct_launch_files(
            lambda: self._finish_cancelled_launch(hook)
        )

    def _finish_cancelled_launch(self, hook: str | None) -> None:
        self._finish_background_launch_operation()
        if (
            hook
            and not self._plugin_cleanup_notified
            and not self._game_started
            and not self._permanent_committed
        ):
            self._plugin_cleanup_notified = True
            payload = {"hook": hook, "reason": "cancelled"}
            try:
                self._execute_plugin_hook("mod_apply_cancelled", payload)
            except Exception:
                logger.warning("Cancelled launch hook failed", exc_info=True)
            self._safe_discord_rich_presence_call("on_mod_apply_cancelled", payload)
        else:
            self._notify_pre_launch_plugin_cancellation(hook or "cancelled")
        if self.restore_window_callback:
            self.restore_window_callback()
        parent = self.parent()
        controller = getattr(parent, "game_launch", None) if parent else None
        if controller and hasattr(controller, "update_button_state"):
            controller.update_button_state()

    def _execute_game(self, launch_config: dict[str, Any], vanilla_mode: bool = False):
        target_path = launch_config.get("target")
        working_directory = launch_config.get("cwd")
        launch_type = launch_config.get("type")
        command: list[str] | None = None
        if not target_path:
            self.status_changed.emit(tr("errors.launch_target_not_defined"), "red")
            self._cleanup_direct_launch_files(
                lambda: self._handle_launch_failure("execute")
            )
            return
        try:
            if self.launch_transaction.state in {
                LaunchState.IDLE,
                LaunchState.COMPLETED,
                LaunchState.FAILED,
            }:
                self.launch_transaction.begin()
            self.launch_transaction.mark_launching()
            self._stop_monitor_thread()
            process_names = self._expected_process_names(target_path)
            baseline_processes = get_matching_process_identities(process_names)
            if launch_type == "url":
                self._start_game_monitor(
                    None, vanilla_mode, process_names, baseline_processes
                )
                system = platform.system()
                if system == "Linux":
                    if not self._start_detached_command("steam", [target_path]):
                        self._start_detached_command("xdg-open", [target_path])
                elif system == "Darwin":
                    self._start_detached_command("open", [target_path])
                else:
                    open_url_native(target_path)
                self.status_changed.emit(
                    tr("status.launching_via_steam"), self._launch_status_color()
                )
                self.launch_transaction.mark_running()
                self._game_started = True
                return
            if not working_directory or not os.path.isdir(working_directory):
                msg = tr("errors.working_directory_not_found", path=working_directory)
                self.status_changed.emit(msg, "red")
                self._cleanup_direct_launch_files(
                    lambda: self._handle_launch_failure("execute")
                )
                return
            process = None
            system = platform.system()
            execution_runtime = resolve_execution_runtime(target_path, system)
            if (
                system == "Darwin"
                and execution_runtime == "macos"
                and target_path.endswith(".app")
            ):
                custom_exec_key = self.app_state.game_mode.get_custom_exec_config_key()
                custom_path = self.app_state.local_config.get(custom_exec_key, "")
                use_custom_exe = (
                    custom_path
                    and os.path.isfile(custom_path)
                    and (os.path.abspath(custom_path) == os.path.abspath(target_path))
                )
                command = ["open", "-W", target_path]
                process = subprocess.Popen(command)
                if use_custom_exe:
                    self.status_changed.emit(
                        tr("status.macos_file_opened"), self._launch_status_color()
                    )
            else:
                command = [target_path]
                launch_env = build_external_process_env(system=system)
                if system != "Windows" and execution_runtime == "windows":
                    use_portproton = self.app_state.local_config.get(
                        "use_portproton", False
                    )
                    if use_portproton:
                        command = [
                            resolve_portproton_command(self.app_state.local_config),
                            "run",
                            target_path,
                        ]
                    else:
                        command.insert(0, resolve_wine_command(self.app_state.local_config))
                creationflags = 0
                if system == "Windows":
                    creationflags = 8
                try:
                    process = subprocess.Popen(
                        command,
                        cwd=working_directory,
                        creationflags=creationflags,
                        env=launch_env,
                    )
                except (
                    OSError,
                    ValueError,
                    subprocess.SubprocessError,
                ) as launch_error:
                    self.status_changed.emit(
                        self._format_launch_error(
                            launch_error, command=command, target_path=target_path
                        ),
                        UI_COLORS["status_error"],
                    )
                    self._cleanup_direct_launch_files(
                        lambda: self._handle_launch_failure("execute")
                    )
                    return
            self.status_changed.emit(
                tr("status.game_launched_waiting_for_exit"), self._launch_status_color()
            )
            self._start_game_monitor(
                process, vanilla_mode, process_names, baseline_processes
            )
            if process is not None:
                self._game_process = process
                background_operations.register_process(
                    process, cancel=lambda: None, owner=self
                )
            self.launch_transaction.mark_running()
            self._game_started = True
        except Exception as e:
            self.status_changed.emit(
                self._format_launch_error(e, command=command, target_path=target_path),
                "red",
            )
            self._cleanup_direct_launch_files(
                lambda: self._handle_launch_failure("execute")
            )

    def _expected_process_names(self, target_path: str) -> tuple[str, ...]:
        names = [
            name
            for name in self.app_state.game_mode.get_process_names()
            if name.casefold() != "runner"
        ]
        if target_path and "://" not in target_path:
            target_name = os.path.basename(target_path.rstrip("/\\"))
            target_stem, _ = os.path.splitext(target_name)
            names.extend((target_name, target_stem))
        return tuple(name for name in dict.fromkeys(names) if name)

    @staticmethod
    def _start_detached_command(program: str, arguments: list[str]) -> bool:
        try:
            started = QProcess.startDetached(program, arguments)
            if isinstance(started, tuple):
                return bool(started[0])
            return bool(started)
        except Exception:
            try:
                process = subprocess.Popen(
                    [program, *arguments],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                background_operations.track_process(process, cancel=lambda: None)
                return True
            except Exception:
                return False

    def _on_game_process_finished(self, vanilla_mode: bool):
        background_operations.release_process(self._game_process)
        self._game_process = None
        self._check_game_running(vanilla_mode)

    def _on_game_process_detected(self, vanilla_mode: bool) -> None:
        self._commit_permanent_operation()
        self._execute_plugin_hook("after_game_started", vanilla_mode)
        self._safe_discord_rich_presence_call("on_after_game_started", vanilla_mode)

    def _check_game_running(self, vanilla_mode):
        logger.info("[LAUNCH] Game is no longer running, starting cleanup")
        if self.restore_window_callback:
            self.restore_window_callback()
        self._record_launch_playtime()
        if not self._selected_launch_mode.restores_after_game:
            if self._operation_journal is not None and not self._permanent_committed:
                logger.warning("Game was not detected; restoring uncommitted changes")
                self._cleanup_direct_launch_files(
                    lambda: self._handle_launch_failure("game-not-detected")
                )
                return
            self.status_changed.emit(
                tr("status.game_closed"), self._launch_status_color()
            )
            self._complete_game_cleanup(vanilla_mode)
            return
        self.app_state.is_patching = True
        self.app_state.progress_bar_visible = True
        self.status_changed.emit(
            tr("status.game_closed_restoring_files"), UI_COLORS["status_info"]
        )
        if self._operation_journal is not None:
            self._run_journal_operation(
                "verify",
                lambda verified, errors, error: self._on_game_exit_verified(
                    vanilla_mode, verified, errors, error
                ),
                journal=self._operation_journal,
                include_error=True,
            )
            return
        self._restore_after_verified_game_exit(vanilla_mode)

    def _commit_permanent_operation(self) -> None:
        if self._selected_launch_mode.restores_after_game:
            return
        journal = self._operation_journal
        if journal is not None:
            try:
                journal.retire()
            except OSError as error:
                logger.error("Could not commit permanent operation journal: %s", error)
                self._run_journal_operation(
                    "retire",
                    self._on_permanent_journal_retired,
                    journal=journal,
                )
                return
        self._complete_permanent_commit(journal)

    def _on_permanent_journal_retired(
        self, retired: bool, errors: list[str]
    ) -> None:
        if retired:
            self._complete_permanent_commit(self._operation_journal)
            return
        logger.error("Could not commit permanent operation journal: %s", errors)
        if not self._selected_launch_mode.starts_game:
            self._cleanup_direct_launch_files(
                lambda: self._handle_launch_failure("permanent-commit")
            )

    def _complete_permanent_commit(
        self, journal: ModOperationJournal | None
    ) -> None:
        self._operation_journal = None
        self._permanent_committed = True
        self.launch_transaction.complete()
        self._execute_plugin_hook(
            "after_mod_apply_committed",
            {"mode": self._selected_launch_mode.value},
        )
        if journal is not None:
            self._run_journal_operation(
                "discard",
                self._on_permanent_journal_discarded,
                journal=journal,
            )
        if not self._selected_launch_mode.starts_game:
            self._complete_patch_only_operation()

    @staticmethod
    def _on_permanent_journal_discarded(discarded: bool, errors: list[str]) -> None:
        if not discarded:
            logger.warning("Could not delete committed operation backups: %s", errors)

    def _on_game_exit_verified(
        self,
        vanilla_mode: bool,
        verified: bool,
        errors: list[str],
        error: Exception | None,
    ) -> None:
        if verified:
            self._restore_after_verified_game_exit(vanilla_mode)
            return
        if isinstance(error, ModRecoveryConflictError):
            if self._ask_recovery_conflict(error) == "force":
                self._restore_after_verified_game_exit(vanilla_mode, force=True)
            else:
                self._retire_game_exit_journal(vanilla_mode)
            return
        logger.error("Could not verify game-exit changes: %s", errors)
        self._finish_game_exit_without_restore(vanilla_mode)

    def _restore_after_verified_game_exit(
        self, vanilla_mode: bool, *, force: bool = False
    ) -> None:
        runtime_service = self._plugin_runtime_service()
        try:
            results = (
                runtime_service.execute_hook_with_runtime(
                    "before_restore_after_exit",
                    None,
                    vanilla_mode,
                    raise_errors=True,
                )
                if runtime_service
                else []
            )
        except Exception:
            logger.exception("Plugin restoration hook failed")
            self._finish_game_exit_without_restore(vanilla_mode)
            return
        if any(result is False for result in results):
            logger.warning("Plugin restoration hook declined restoration")
            self._finish_game_exit_without_restore(vanilla_mode)
            return
        self._safe_discord_rich_presence_call(
            "on_before_restore_after_exit", vanilla_mode
        )
        if self._operation_journal is not None and not force:
            self._run_journal_operation(
                "checkpoint",
                lambda checkpointed, errors: self._on_game_exit_plugin_restore_finished(
                    vanilla_mode, checkpointed, errors
                ),
                journal=self._operation_journal,
            )
            return
        QTimer.singleShot(
            50, lambda: self._finish_game_cleanup(vanilla_mode, force=force)
        )

    def _on_game_exit_plugin_restore_finished(
        self, vanilla_mode: bool, checkpointed: bool, errors: list[str]
    ) -> None:
        if not checkpointed:
            logger.error("Could not checkpoint plugin restoration: %s", errors)
            self._finish_game_exit_without_restore(vanilla_mode)
            return
        QTimer.singleShot(50, lambda: self._finish_game_cleanup(vanilla_mode))

    def _retire_game_exit_journal(self, vanilla_mode: bool) -> None:
        journal = self._operation_journal
        if journal is None:
            self._finish_game_exit_without_restore(vanilla_mode)
            return
        self._run_journal_operation(
            "retire",
            lambda retired, errors: self._on_game_exit_journal_retired(
                vanilla_mode, journal, retired, errors
            ),
            journal=journal,
        )

    def _on_game_exit_journal_retired(
        self,
        vanilla_mode: bool,
        journal: ModOperationJournal,
        retired: bool,
        errors: list[str],
    ) -> None:
        if retired:
            self._operation_journal = None
            self.status_changed.emit(
                tr("status.restore_skipped_external_changes"),
                UI_COLORS["status_warning"],
            )
            self._finish_game_exit_without_restore(vanilla_mode, completed=True)
            return
        logger.error("Could not retire changed operation journal: %s", errors)
        self._finish_game_exit_without_restore(vanilla_mode)

    def _finish_game_exit_without_restore(
        self, vanilla_mode: bool, *, completed: bool = False
    ) -> None:
        if self.launch_transaction.state == LaunchState.RUNNING:
            self.launch_transaction.transition(LaunchState.RESTORING)
        if completed and self.launch_transaction.state == LaunchState.RESTORING:
            self.launch_transaction.transition(LaunchState.COMPLETED)
        elif not completed:
            self.launch_transaction.fail("external-changes")
        self._complete_game_cleanup(vanilla_mode, run_after_restore=False)

    def _finish_game_cleanup(self, vanilla_mode: bool, *, force: bool = False) -> None:
        self._cleanup_direct_launch_files(
            lambda: self._complete_game_cleanup(vanilla_mode), force=force
        )

    def _complete_game_cleanup(
        self, vanilla_mode: bool, *, run_after_restore: bool = True
    ) -> None:
        if self.launch_transaction.state == LaunchState.RUNNING:
            self.launch_transaction.complete()
        if self.monitor_thread:
            self._stop_monitor_thread()
        self.game_launch_finished.emit()
        if run_after_restore:
            self._execute_plugin_hook("after_restore_after_exit", vanilla_mode)
            self._safe_discord_rich_presence_call(
                "on_after_restore_after_exit", vanilla_mode
            )
        self.app_state.is_patching = False
        self.app_state.progress_bar_visible = False
        parent = self.parent()
        controller = getattr(parent, "game_launch", None) if parent else None
        if controller and hasattr(controller, "update_button_state"):
            controller.update_button_state()
        logger.info("[LAUNCH] Cleanup completed, game launch finished")

    def _record_launch_playtime(self) -> None:
        if self._launch_started_at is None:
            return
        elapsed = time.monotonic() - self._launch_started_at
        self._launch_started_at = None
        if elapsed <= 0:
            return
        parent = self.parent()
        mod_service = getattr(parent, "mod_service", None) if parent else None
        if (
            self._launch_mod_ids
            and mod_service
            and hasattr(mod_service, "add_playtime_hours")
        ):
            mod_service.add_playtime_hours(self._launch_mod_ids, elapsed / 3600.0)

    @staticmethod
    def _collect_launch_mod_ids(selections: dict[str, Any]) -> list[str]:
        from utils.mod.utils import get_mod_id

        seen = set()
        result = []
        for mods in selections.values():
            mod_list = mods if isinstance(mods, list) else [mods]
            for mod in mod_list:
                mod_id = get_mod_id(mod)
                if not mod_id or mod_id in seen:
                    continue
                seen.add(mod_id)
                result.append(mod_id)
        return result

    def _determine_launch_config(
        self, selections: dict[str, Any]
    ) -> dict[str, Any] | None:
        use_steam = self.app_state.local_config.get("launch_via_steam", False)
        direct_launch_id = self.app_state.local_config.get("direct_launch_chapter", "")
        is_chapter_mode = self.app_state.current_mode == "chapter"
        is_direct_chapter = (
            bool(direct_launch_id)
            and "_" in direct_launch_id
            and not direct_launch_id.endswith("_0")
        )
        direct_launch = (
            is_direct_chapter
            and is_chapter_mode
            and self.app_state.game_mode.direct_launch_allowed
            and (platform.system() != "Darwin")
        )
        should_block_steam = (
            self.app_state.game_mode.block_steam_with_direct_launch
            and is_chapter_mode
            and bool(direct_launch_id)
        )
        if (
            use_steam
            and self.app_state.game_mode.steam_app_id
            and (not should_block_steam)
        ):
            return {
                "target": f"steam://rungameid/{self.app_state.game_mode.steam_app_id}",
                "cwd": None,
                "type": "url",
            }
        if direct_launch:
            return self._handle_direct_launch(direct_launch_id)
        launch_target = self._get_executable_path()
        if not launch_target:
            self.status_changed.emit(
                tr("errors.executable_not_found"), UI_COLORS["status_error"]
            )
            return None
        return {
            "target": launch_target,
            "cwd": self._get_current_game_path(),
            "type": "subprocess",
        }

    def _handle_direct_launch(self, chapter_id: str) -> dict[str, Any] | None:
        if chapter_id.endswith("_0"):
            self.status_changed.emit(
                tr("ui.direct_launch_menu_not_allowed"), UI_COLORS["status_warning"]
            )
            return None
        chapter_folder = find_chapter_resource_dir(
            self._get_current_game_path(), chapter_id
        )
        source_exe = self._get_source_executable_path()
        custom_exec_key = self.app_state.game_mode.get_custom_exec_config_key()
        custom_path = self.app_state.local_config.get(custom_exec_key, "")
        use_custom_exe = (
            custom_path
            and source_exe
            and os.path.isfile(custom_path)
            and (os.path.abspath(custom_path) == os.path.abspath(source_exe))
        )
        if not chapter_folder or not source_exe:
            self.status_changed.emit(
                tr("errors.direct_launch_error"), UI_COLORS["status_error"]
            )
            return None
        try:
            if not ensure_writable(chapter_folder):
                raise PermissionError(
                    tr("errors.no_write_permission_for", path=chapter_folder)
                )
            if use_custom_exe:
                target_exe = os.path.join(chapter_folder, os.path.basename(source_exe))
            else:
                from services.game_detection_service import get_executable_name_for_game

                exe_name = (
                    get_executable_name_for_game(
                        self.app_state.game_mode.executable_type
                    )
                    or "DELTARUNE.exe"
                )
                target_exe = os.path.join(chapter_folder, exe_name)
            shutil.copy2(source_exe, target_exe)
            game_root = self._get_current_game_path()
            mus_folders_copied = []
            if game_root and os.path.isdir(game_root):
                for entry in os.listdir(game_root):
                    entry_path = os.path.join(game_root, entry)
                    if os.path.isdir(entry_path) and entry.startswith("mus"):
                        target_mus_path = os.path.join(chapter_folder, entry)
                        if not os.path.exists(target_mus_path):
                            try:
                                shutil.copytree(entry_path, target_mus_path)
                                mus_folders_copied.append(target_mus_path)
                                logger.info(
                                    f"[DIRECT_LAUNCH] Copied music folder: {entry} -> {target_mus_path}"
                                )
                            except Exception as e:
                                logger.warning(
                                    f"[DIRECT_LAUNCH] Failed to copy music folder {entry}: {e}"
                                )
            self._direct_launch_cleanup_info = {
                "target_exe": target_exe,
                "source_exe": source_exe,
                "chapter_folder": chapter_folder,
                "use_custom_exe": use_custom_exe,
                "mus_folders": mus_folders_copied,
            }
            return {"target": target_exe, "cwd": chapter_folder, "type": "subprocess"}
        except PermissionError:
            self.status_changed.emit(
                tr("errors.permission_denied"), UI_COLORS["status_error"]
            )
            return None

    def _get_executable_path(self):
        custom_key = getattr(self.app_state.game_mode, "get_custom_exec_config_key", lambda: "")()
        custom_path = self.app_state.local_config.get(custom_key, "") if custom_key else ""
        if custom_path and os.path.isfile(custom_path):
            return custom_path
        current_game_path = self._get_current_game_path()
        if not current_game_path or not os.path.isdir(current_game_path):
            return None
        return resolve_game_executable(
            current_game_path, getattr(self.app_state.game_mode, "executable_type", "deltarune")
        )

    def _get_source_executable_path(self):
        custom_key = getattr(self.app_state.game_mode, "get_custom_exec_config_key", lambda: "")()
        custom_path = self.app_state.local_config.get(custom_key, "") if custom_key else ""
        if custom_path and os.path.isfile(custom_path):
            return custom_path
        return self._get_executable_path()

    def _get_current_game_path(self) -> str:
        return self.app_state.game_mode.get_game_path(self.app_state.local_config) or ""

    def _operation_session_root(self) -> Path:
        return Path(self.app_state.config_dir) / "operation-session"

    @staticmethod
    def _ordered_selected_mod_ids(
        selections: dict[str, list[Any]],
        patch_steps: dict[str, list[list[Any]]] | None,
    ) -> list[str]:
        from utils.mod.utils import get_mod_id

        ordered: list[str] = []
        source = patch_steps.values() if patch_steps else ([mods] for mods in selections.values())
        for section_steps in source:
            for step in section_steps:
                for mod in step if isinstance(step, list) else [step]:
                    mod_id = get_mod_id(mod)
                    if isinstance(mod_id, str) and mod_id:
                        ordered.append(mod_id)
        return ordered

    @staticmethod
    def _operation_merge_steps(
        selections: dict[str, list[Any]],
        patch_steps: dict[str, list[list[Any]]] | None,
    ) -> tuple[tuple[str, ...], ...]:
        from utils.mod.utils import get_mod_id

        source = patch_steps.values() if patch_steps else ([mods] for mods in selections.values())
        steps: list[tuple[str, ...]] = []
        for section_steps in source:
            for step in section_steps:
                mod_ids = tuple(
                    mod_id
                    for mod in (step if isinstance(step, list) else [step])
                    if isinstance((mod_id := get_mod_id(mod)), str) and mod_id
                )
                if len(mod_ids) > 1:
                    steps.append(mod_ids)
        return tuple(steps)

    def _operation_relation_scopes(
        self,
        selections: dict[str, list[Any]],
        patch_steps: dict[str, list[list[Any]]] | None,
    ) -> dict[str, list[list[Any]]]:
        """Return the actual persisted profile rows used for relation decisions."""
        manager = self._used_mods_service()
        game_mode = getattr(self.app_state, "game_mode", None)
        get_steps = getattr(manager, "get_mod_steps", None)

        if callable(get_steps) and game_mode is not None:
            def current_steps(scope: str) -> list[list[Any]]:
                raw_steps = get_steps(scope)
                if not isinstance(raw_steps, list):
                    return []
                return [list(step) for step in raw_steps if isinstance(step, list) and step]

            if not getattr(game_mode, "is_multi_tab", False) or getattr(
                self.app_state, "current_mode", "normal"
            ) != "chapter":
                chapter_id = get_chapter_id_for_game_mode(game_mode)
                return {chapter_id: current_steps(chapter_id)}
            return {
                tab.tab_id: current_steps(tab.tab_id)
                for tab in getattr(game_mode, "tabs", ())
            }
        if patch_steps:
            return {
                str(scope): [list(step) for step in steps if isinstance(step, list) and step]
                for scope, steps in patch_steps.items()
            }
        return {
            str(scope): [list(mods)]
            for scope, mods in selections.items()
            if isinstance(mods, list) and mods
        }

    @staticmethod
    def _relation_ids(steps: list[list[Any]]) -> tuple[tuple[str, ...], ...]:
        from utils.mod.utils import get_mod_id

        return tuple(
            tuple(
                mod_id
                for mod in step
                if isinstance((mod_id := get_mod_id(mod)), str) and mod_id
            )
            for step in steps
            if step
        )

    def _installed_operation_configs(
        self, active_configs: dict[str, dict[str, object]], game_id: str
    ) -> dict[str, dict[str, object]]:
        """Include installed configs so dependencies can be inactive, not just missing."""
        from utils.mod.utils import get_mod_id

        configs = dict(active_configs)
        for mod in getattr(self.app_state, "all_mods", ()):
            mod_id = get_mod_id(mod)
            if not isinstance(mod_id, str) or not mod_id or mod_id in configs:
                continue
            config = self.mod_service.get_mod_config(mod_id)
            if (
                isinstance(config, dict)
                and config.get("config_version") == MOD_CONFIG_VERSION
                and (not game_id or config.get("game") == game_id)
            ):
                configs[mod_id] = config
        return configs

    @staticmethod
    def _relation_plan_findings(
        configs: dict[str, dict[str, object]],
        scopes: dict[str, tuple[tuple[str, ...], ...]],
    ) -> tuple[PlanFinding, ...]:
        findings: list[PlanFinding] = []
        seen: set[tuple[str, str, str, str | None]] = set()
        for scope, steps in scopes.items():
            for finding in analyze_mod_relations(configs, steps):
                key = (finding.code, finding.mod_id, finding.related_id, finding.mode)
                if key in seen:
                    continue
                seen.add(key)
                name = str(configs.get(finding.mod_id, {}).get("name") or finding.mod_id)
                findings.append(
                    PlanFinding(
                        finding.severity,
                        finding.code,
                        0,
                        f"{scope}: {name}: {finding.message} Related mod: {finding.related_id}.",
                    )
                )
        return tuple(findings)

    def _operation_relation_recommendations(
        self,
        selections: dict[str, list[Any]],
        patch_steps: dict[str, list[list[Any]]] | None,
        game_id: str,
    ) -> tuple[
        dict[str, list[list[Any]]],
        dict[str, dict[str, object]],
        dict[str, tuple[tuple[str, ...], ...]],
        dict[str, tuple[tuple[str, ...], ...]],
    ]:
        scopes = self._operation_relation_scopes(selections, patch_steps)
        active_ids = {
            mod_id
            for steps in scopes.values()
            for row in self._relation_ids(steps)
            for mod_id in row
        }
        configs: dict[str, dict[str, object]] = {}
        for mod_id in active_ids:
            config = self.mod_service.get_mod_config(mod_id)
            if (
                isinstance(config, dict)
                and config.get("config_version") == MOD_CONFIG_VERSION
                and (not game_id or config.get("game") == game_id)
            ):
                configs[mod_id] = config
        configs = self._installed_operation_configs(configs, game_id)
        source_steps = {
            scope: self._relation_ids(steps) for scope, steps in scopes.items()
        }
        recommendations = {
            scope: arrangement.steps
            for scope, steps in source_steps.items()
            if (arrangement := recommend_mod_arrangement(configs, steps)).feasible
            and arrangement.steps != steps
        }
        return scopes, configs, source_steps, recommendations

    def _offer_operation_relation_recommendations(
        self,
        selections: dict[str, list[Any]],
        patch_steps: dict[str, list[list[Any]]] | None,
    ) -> bool:
        from utils.mod.utils import get_mod_id

        if not is_warning_enabled("mod_order_suggestion", self.app_state.local_config):
            return True
        game_id = str(getattr(getattr(self.app_state, "game_mode", None), "game_id", "") or "")
        scopes, _configs, source_steps, recommendations = self._operation_relation_recommendations(
            selections, patch_steps, game_id
        )
        if not recommendations:
            return True
        lines = []
        for scope, steps in recommendations.items():
            previous = " / ".join(" > ".join(row) for row in source_steps[scope])
            suggested = " / ".join(" > ".join(row) for row in steps)
            lines.append(f"{scope}: {previous} → {suggested}")
        ask = getattr(self.feedback_service, "ask_relation_arrangement", None)
        choice = (
            ask(tr("dialogs.patching_warning.relation_review"), "\n".join(lines))
            if callable(ask)
            else "continue"
        )
        if choice == "cancel":
            return False
        if choice != "apply":
            return True
        manager = self._used_mods_service()
        set_steps = getattr(manager, "set_mod_steps", None)
        save_state = getattr(manager, "save_used_mods_state", None)
        if not callable(set_steps) or not callable(save_state):
            return True
        resolved: dict[str, list[list[Any]]] = {}
        for scope, recommended in recommendations.items():
            by_id = {
                mod_id: mod
                for row in scopes[scope]
                for mod in row
                if isinstance((mod_id := get_mod_id(mod)), str) and mod_id
            }
            if any(mod_id not in by_id for row in recommended for mod_id in row):
                return True
            resolved[scope] = [[by_id[mod_id] for mod_id in row] for row in recommended]
        for scope, steps in resolved.items():
            set_steps(scope, steps, save_state=False)
        save_state()
        return True

    def _activate_operation_dependencies(
        self, scopes: dict[str, list[list[Any]]], resolved: dict[str, dict[str, Any]]
    ) -> bool:
        """Activate already-installed dependencies once, preserving every row order."""
        manager = self._used_mods_service()
        set_steps = getattr(manager, "set_mod_steps", None)
        save_state = getattr(manager, "save_used_mods_state", None)
        if not callable(set_steps) or not callable(save_state):
            return False
        for scope, mods in resolved.items():
            rows = [list(row) for row in scopes[scope]]
            if rows:
                rows[0].extend(mods.values())
            else:
                rows.append(list(mods.values()))
            set_steps(scope, rows, save_state=False)
        save_state()
        return True

    @staticmethod
    def _gamebanana_dependency_ids(mod_ids: set[str]) -> set[str]:
        import re

        return {
            mod_id
            for mod_id in mod_ids
            if re.fullmatch(r"gb_(?:mod|wip)_[0-9]+", mod_id)
        }

    def _downloads_manager(self):
        parent = self.parent()
        return getattr(parent, "downloads_manager", None) if parent else None

    def _start_dependency_resolution(self, dependency_ids: set[str], game_id: str) -> None:
        from workers.gamebanana.dependency_worker import (
            ResolveGameBananaDependenciesThread,
        )

        thread = ResolveGameBananaDependenciesThread(dependency_ids, game_id, self)
        thread.resolved.connect(
            lambda resolved, failures, source=thread: self._on_dependency_downloads_resolved(
                source, resolved, failures
            )
        )
        thread.finished.connect(
            lambda source=thread: self._on_dependency_resolution_finished(source)
        )
        self._dependency_resolution_thread = thread
        self.app_state.current_task = thread
        thread.start()

    def _on_dependency_resolution_finished(self, source_thread) -> None:
        if source_thread is self._dependency_resolution_thread:
            self._dependency_resolution_thread = None
            retire_qthread(source_thread)

    def _clear_pending_dependency_downloads(self) -> None:
        manager = self._dependency_download_manager
        if manager is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                manager.record_updated.disconnect(
                    self._on_dependency_download_record_updated
                )
        self._dependency_download_manager = None
        self._dependency_download_records.clear()

    def _resume_pending_dependency_launch(self, details: str = "") -> None:
        pending = self._pending_dependency_launch
        if pending is not None and not self._pending_dependency_context_matches():
            self.cancel_pending_launch("profile-changed")
            return
        self._pending_dependency_launch = None
        self._clear_pending_dependency_downloads()
        self._finish_background_launch_operation()
        if details and is_warning_enabled("missing_dependencies", self.app_state.local_config):
            ask = getattr(self.feedback_service, "ask_patching_warning", None)
            warning_key = (
                "dialogs.patching_warning.dependency_manual_required"
                if pending and pending.get("manual_ids")
                else "dialogs.patching_warning.dependency_download_failed"
            )
            if callable(ask) and not ask(tr(warning_key), details):
                self.cancel_pending_launch()
                return
        if pending is not None:
            self._launch_game_with_selections(
                self._get_used_mods_selections() or pending["selections"],
                self.restore_window_callback,
                pending["mode"],
                pending["pre_hooks_done"],
            )

    def _on_dependency_downloads_resolved(
        self,
        source_thread,
        resolved: dict[str, dict[str, Any]],
        failures: dict[str, str],
    ) -> None:
        if source_thread is not self._dependency_resolution_thread:
            return
        if not self._pending_dependency_context_matches():
            self.cancel_pending_launch("profile-changed")
            return
        thread = source_thread
        self._dependency_resolution_thread = None
        if thread is not None:
            retire_qthread(thread)
        if self._pending_dependency_launch is None:
            return
        manager = self._downloads_manager()
        if manager is None or not resolved:
            pending = self._pending_dependency_launch or {}
            failure_ids = set(failures) | set(resolved)
            manual_ids = set(pending.get("manual_ids", set()))
            details = "\n".join(
                f"{mod_id}: {tr('downloads.status_needs_manual' if mod_id in manual_ids else 'downloads.status_failed')}"
                for mod_id in sorted(failure_ids | manual_ids)
            ) or tr("downloads.status_failed")
            self._resume_pending_dependency_launch(details)
            return
        from models.download_models import SourceKind, TargetKind

        self._dependency_download_manager = manager
        manager.record_updated.connect(self._on_dependency_download_record_updated)
        pending = self._pending_dependency_launch
        target_mods_dir = (
            pending.get("target_mods_dir") if isinstance(pending, dict) else None
        )
        for mod_id, spec in resolved.items():
            metadata = dict(spec.get("metadata") or {})
            if isinstance(target_mods_dir, str):
                metadata["target_mods_dir"] = target_mods_dir
            record_id, _is_duplicate = manager.enqueue(
                display_name=spec["display_name"],
                source_kind=SourceKind.GAMEBANANA,
                target_kind=TargetKind.MOD,
                source_url=spec["source_url"],
                canonical_key=spec["canonical_key"],
                metadata=metadata,
                auto_use=True,
            )
            if _is_duplicate:
                manager.action_install(record_id)
            self._dependency_download_records[record_id] = mod_id
        if failures:
            pending = self._pending_dependency_launch
            if pending is not None:
                pending["failures"] = dict(failures)
        QTimer.singleShot(0, self._check_dependency_downloads)

    def _on_dependency_download_record_updated(self, record) -> None:
        if getattr(record, "id", None) in self._dependency_download_records:
            QTimer.singleShot(0, self._check_dependency_downloads)

    def _check_dependency_downloads(self) -> None:
        pending = self._pending_dependency_launch
        manager = self._dependency_download_manager
        if pending is None or manager is None or not self._dependency_download_records:
            return
        records = [
            manager.store.find(record_id)
            for record_id in self._dependency_download_records
        ]
        if any(record is not None and record.is_active for record in records):
            return
        try:
            self.mod_service.invalidate_mods_cache()
            self.mod_service.load_local_mods()
        except Exception:
            logger.warning("Could not refresh installed dependencies", exc_info=True)
        download_ids = set(self._dependency_download_records.values())
        missing = {
            mod_id
            for mod_id in download_ids
            if not self.mod_service.get_mod_folder_path(mod_id)
        }
        failures = dict(pending.get("failures", {}))
        manual_ids = {
            mod_id
            for mod_id in pending.get("manual_ids", set())
            if not self.mod_service.get_mod_folder_path(mod_id)
        }
        for record, mod_id in zip(
            records, self._dependency_download_records.values(), strict=True
        ):
            if mod_id in missing and record is not None:
                status = record.effective_status_key
                if status == "needs_manual":
                    manual_ids.add(mod_id)
                failures.setdefault(
                    mod_id,
                    tr(
                        f"downloads.status_{status}"
                        if status in {
                            "cancelled",
                            "failed",
                            "installing",
                            "needs_manual",
                            "overwrite_pending",
                            "ready",
                        }
                        else "downloads.status_failed",
                        progress=getattr(record, "progress", 0),
                    ),
                )
        for mod_id in sorted(manual_ids):
            failures.setdefault(mod_id, tr("downloads.status_needs_manual"))
        pending["manual_ids"] = manual_ids
        scopes = pending.get("scopes")
        download_scopes = pending.get("download_scopes")
        if isinstance(scopes, dict) and isinstance(download_scopes, dict):
            from utils.mod.utils import get_mod_id

            installed = {
                mod_id: mod
                for mod in getattr(self.app_state, "all_mods", ()) or ()
                if isinstance((mod_id := get_mod_id(mod)), str)
                and self.mod_service.get_mod_folder_path(mod_id)
            }
            resolved = {
                scope: {
                    mod_id: installed[mod_id]
                    for mod_id in mod_ids
                    if mod_id in installed
                }
                for scope, mod_ids in download_scopes.items()
                if scope in scopes and isinstance(mod_ids, set)
            }
            resolved = {scope: mods for scope, mods in resolved.items() if mods}
            if resolved:
                self._activate_operation_dependencies(scopes, resolved)
        details = "\n".join(
            f"{mod_id}: {message}" for mod_id, message in sorted(failures.items())
        )
        self._resume_pending_dependency_launch(details)

    def _offer_dependency_activation(
        self,
        selections: dict[str, list[Any]],
        patch_steps: dict[str, list[list[Any]]] | None,
    ) -> bool:
        """Offer one explicit resolution for missing or inactive required mods."""
        from utils.mod.utils import get_mod_id

        game_id = str(
            getattr(getattr(self.app_state, "game_mode", None), "game_id", "") or ""
        )
        scopes, configs, source_steps, _recommendations = self._operation_relation_recommendations(
            selections, patch_steps, game_id
        )
        findings = {
            scope: analyze_mod_relations(configs, steps)
            for scope, steps in source_steps.items()
        }
        inactive = {
            scope: {
                finding.related_id
                for finding in scope_findings
                if finding.code == "dependency_inactive"
            }
            for scope, scope_findings in findings.items()
        }
        missing = {
            scope: {
                finding.related_id
                for finding in scope_findings
                if finding.code == "dependency_missing"
            }
            for scope, scope_findings in findings.items()
        }
        config = self.app_state.local_config
        inactive = {
            scope: ids
            for scope, ids in inactive.items()
            if ids and is_warning_enabled("inactive_dependencies", config)
        }
        missing = {
            scope: ids
            for scope, ids in missing.items()
            if ids and is_warning_enabled("missing_dependencies", config)
        }
        if not inactive and not missing:
            return True
        installed = {
            mod_id: mod
            for mod in getattr(self.app_state, "all_mods", ()) or ()
            if isinstance((mod_id := get_mod_id(mod)), str)
            and mod_id
            and self.mod_service.get_mod_folder_path(mod_id)
        }
        resolved = {
            scope: {mod_id: installed[mod_id] for mod_id in mod_ids if mod_id in installed}
            for scope, mod_ids in inactive.items()
        }
        resolved = {scope: mods for scope, mods in resolved.items() if mods}
        missing_ids = set().union(*missing.values()) if missing else set()
        installable_ids = self._gamebanana_dependency_ids(missing_ids)
        details = []
        for scope, mods in sorted(resolved.items()):
            details.append(
                tr(
                    "dialogs.patching_warning.dependency_activate_details",
                    scope=scope,
                    mods=", ".join(sorted(mods)),
                )
            )
        for scope, mod_ids in sorted(missing.items()):
            automatic = sorted(mod_ids & installable_ids)
            manual = sorted(mod_ids - installable_ids)
            if automatic:
                details.append(
                    tr(
                        "dialogs.patching_warning.dependency_download_details",
                        scope=scope,
                        mods=", ".join(automatic),
                    )
                )
            if manual:
                details.append(
                    tr(
                        "dialogs.patching_warning.dependency_manual_details",
                        scope=scope,
                        mods=", ".join(manual),
                    )
                )
        if missing:
            ask = getattr(self.feedback_service, "ask_dependency_resolution", None)
            choice = (
                ask(
                    tr(
                        "dialogs.patching_warning.dependency_resolution",
                        count=len(set().union(*inactive.values(), *missing.values())),
                    ),
                    "\n".join(details),
                    bool(installable_ids),
                    bool(resolved),
                )
                if callable(ask)
                else "continue"
            )
            if choice == "cancel":
                return False
            if choice != "resolve":
                return True
            if resolved and not self._activate_operation_dependencies(scopes, resolved):
                return True
            manual_ids = set().union(*(ids - installable_ids for ids in missing.values()))
            if installable_ids:
                profile_name, target_mods_dir = self._launch_profile_context()
                self._pending_dependency_launch = {
                    "selections": selections,
                    "mode": self._selected_launch_mode,
                    "pre_hooks_done": self._before_mod_apply_completed,
                    "failures": {},
                    "manual_ids": manual_ids,
                    "download_ids": set(installable_ids),
                    "download_scopes": {
                        scope: mod_ids & installable_ids
                        for scope, mod_ids in missing.items()
                        if mod_ids & installable_ids
                    },
                    "scopes": scopes,
                    "profile_name": profile_name,
                    "target_mods_dir": target_mods_dir,
                }
                self._start_dependency_resolution(installable_ids, game_id)
                return False
            if manual_ids:
                ask_manual = getattr(self.feedback_service, "ask_patching_warning", None)
                if callable(ask_manual) and not ask_manual(
                    tr("dialogs.patching_warning.dependency_manual_required"),
                    "\n".join(details),
                ):
                    return False
            return True
        details_text = "\n".join(details)
        ask = getattr(self.feedback_service, "ask_dependency_activation", None)
        choice = (
            ask(
                tr(
                    "dialogs.patching_warning.dependency_activation",
                    count=sum(map(len, resolved.values())),
                ),
                details_text,
            )
            if callable(ask)
            else "continue"
        )
        if choice == "cancel":
            return False
        if choice != "activate" or not resolved:
            return True
        return self._activate_operation_dependencies(scopes, resolved)

    def _confirm_operation_plan(self, plan: ModOperationPlan) -> ModOperationPlan | None:
        return confirm_operation_plan(plan, self.feedback_service, self.app_state.local_config)

    def _build_operation_profile_plan(
        self,
        selections: dict[str, list[Any]],
        patch_steps: dict[str, list[list[Any]]] | None,
    ) -> ModOperationPlan:
        ordered_ids = self._ordered_selected_mod_ids(selections, patch_steps)
        game_mode = getattr(self.app_state, "game_mode", None)
        game_id = str(getattr(game_mode, "game_id", "") or "")
        game_data_path = (
            game_mode.get_data_path(self.app_state.local_config)
            if game_mode is not None and hasattr(game_mode, "get_data_path")
            else None
        )
        execution_runtime = resolve_execution_runtime(
            self._get_source_executable_path(), platform.system()
        )
        inputs = collect_profile_operation_inputs(
            self.mod_service,
            ordered_ids,
            game_id=game_id,
            game_path=self._get_current_game_path(),
            game_data_path=game_data_path,
            runtime=execution_runtime,
        )
        configs = inputs.configs
        plan = inputs.build_plan(
            tuple(configs), merge_steps=self._operation_merge_steps(selections, patch_steps)
        )
        relation_scopes = {
            scope: self._relation_ids(steps)
            for scope, steps in self._operation_relation_scopes(selections, patch_steps).items()
        }
        relation_configs = self._installed_operation_configs(configs, game_id)
        relation_findings = self._relation_plan_findings(relation_configs, relation_scopes)
        return ModOperationPlan(
            plan.operations, (*plan.findings, *relation_findings)
        )

    def _prepare_game_files_multi_mod_async(
        self,
        selections: dict[str, list[Any]],
        patch_steps: dict[str, list[list[Any]]] | None = None,
        needs_multi_mod: bool = False,
    ) -> bool:
        from workers.mod.operation_worker import ModOperationThread

        logger.info("Starting ordered mod operations in background thread")
        if not self._has_selected_mods(selections):
            self._continue_after_patching(selections, True, False)
            return True
        self.app_state.progress_bar_visible = True
        self.app_state.progress_bar_value = 0
        if not self._offer_dependency_activation(selections, patch_steps):
            return False
        selections = self._get_used_mods_selections() or selections
        patch_steps = self._get_used_mod_steps() or patch_steps
        if not self._offer_operation_relation_recommendations(selections, patch_steps):
            return False
        selections = self._get_used_mods_selections() or selections
        patch_steps = self._get_used_mod_steps() or patch_steps
        operation_plan = self._build_operation_profile_plan(selections, patch_steps)
        operation_plan = self._confirm_operation_plan(operation_plan)
        if operation_plan is None:
            return False
        if operation_plan.has_errors:
            message = operation_plan.findings[0].message
            self.status_changed.emit(message, UI_COLORS["status_error"])
            return False
        if not operation_plan.operations:
            self._continue_after_patching(selections, True, needs_multi_mod)
            return True
        self.launch_transaction.begin_apply()
        self._patching_thread = ModOperationThread(
            self.app_state, operation_plan, self._operation_session_root(), self
        )
        self._patching_thread.progress_update.connect(self._on_patching_progress)
        self._patching_thread.status_update.connect(self._on_patching_status)
        self._patching_thread.result_ready.connect(
            lambda success: self._on_patching_finished(selections, success, needs_multi_mod)
        )
        self.app_state.current_task = self._patching_thread
        self._patching_thread.start()
        return True

    def _on_patching_finished(
        self, selections: dict[str, Any], success: bool, needs_multi_mod: bool = False
    ):
        patching_thread = self._patching_thread
        if patching_thread:
            try:
                operation_journal = getattr(patching_thread, "journal", None)
                if isinstance(operation_journal, ModOperationJournal):
                    self._operation_journal = operation_journal
                retire_qthread(patching_thread)
                if patching_thread.isRunning():
                    logger.debug(
                        "Patching thread still running, will clean up via finished signal"
                    )
            except Exception as e:
                logger.error(f"Error cleaning up patching thread: {e}", exc_info=True)
            finally:
                self._patching_thread = None
        if not success:
            if patching_thread and (
                patching_thread.isInterruptionRequested()
                or getattr(patching_thread, "_cancelled", False)
            ):
                logger.info("Multi-mod patching was cancelled by user")
                self.cancel_pending_launch("patching")
            else:
                self._finish_background_launch_operation()
                self._handle_launch_failure()
            return
        logger.info("Ordered mod operations completed successfully")
        self._continue_after_patching(selections, True, needs_multi_mod)

    def _execute_plugin_hook(self, hook_name: str, *args):
        """Execute a plugin hook if the runtime service is available.

        Returns an iterable of hook results, or an empty iterable if no runtime service.
        """
        runtime_service = self._plugin_runtime_service()
        if runtime_service:
            return runtime_service.execute_hook(hook_name, *args)
        return []

    def _start_plugin_hook_thread(
        self,
        hook_name: str,
        *hook_args,
        base_progress: int = 0,
        progress_span: int = 100,
        finished_callback=None,
        target_plugin_id: str | None = None,
        cancel_hook: str = "mod_apply_cancelled",
    ) -> bool:
        runtime_service = self._plugin_runtime_service()
        if not runtime_service or not runtime_service.has_enabled_hook(
            hook_name, target_plugin_id=target_plugin_id
        ):
            return False
        self.app_state.progress_bar_visible = True
        self.app_state.is_patching = True
        self.app_state.action_button_text = tr("ui.cancel_button")
        self.app_state.action_button_enabled = True
        thread = PluginHookThread(
            runtime_service,
            hook_name,
            hook_args,
            base_progress=base_progress,
            progress_span=progress_span,
            target_plugin_id=target_plugin_id,
            cancel_hook=cancel_hook,
            parent=self,
        )
        thread.progress_update.connect(self._on_patching_progress)
        thread.status_update.connect(self._on_patching_status)
        thread.result_ready.connect(
            finished_callback
            if finished_callback is not None
            else lambda success: self._on_plugin_hook_finished(hook_args, success)
        )
        self._plugin_hook_thread = thread
        self.app_state.current_task = thread
        thread.start()
        return True

    def run_plugin_launch_action(self, action) -> bool:
        """Run one selected plugin action with the standard cancellable task UI."""
        self._active_plugin_launch_action = action
        started = self._start_plugin_hook_thread(
            "launch_action",
            action.id.rpartition(":")[2],
            base_progress=0,
            progress_span=100,
            finished_callback=self._on_plugin_launch_action_finished,
            target_plugin_id=action.plugin_id,
            cancel_hook="launch_action_cancelled",
        )
        if not started:
            self._active_plugin_launch_action = None
        return started

    def _on_plugin_launch_action_finished(self, success: bool) -> None:
        thread = self._plugin_hook_thread
        self._plugin_hook_thread = None
        if thread:
            retire_qthread(thread)
        action = getattr(self, "_active_plugin_launch_action", None)
        self._active_plugin_launch_action = None
        self._finish_background_launch_operation()
        if success and action is not None:
            self.status_changed.emit(action.label, UI_COLORS["status_success"])
        parent = self.parent()
        controller = getattr(parent, "game_launch", None) if parent else None
        if controller and hasattr(controller, "update_button_state"):
            controller.update_button_state()

    def _on_before_mod_apply_finished(self, success: bool) -> None:
        thread = self._plugin_hook_thread
        self._plugin_hook_thread = None
        if thread:
            retire_qthread(thread)
        if not success:
            self._before_mod_apply_completed = True
            if thread and (
                thread.isInterruptionRequested() or getattr(thread, "_cancelled", False)
            ):
                self.cancel_pending_launch()
            else:
                self._finish_background_launch_operation()
                self._handle_launch_failure("plugin")
            return
        self._before_mod_apply_completed = True
        self._safe_discord_rich_presence_call("on_before_mod_apply")
        self._continue_launch_with_selections(self._get_used_mods_selections())

    def _finish_background_launch_operation(self) -> None:
        self.app_state.progress_bar_visible = False
        self.app_state.is_patching = False
        self.app_state.clear_current_task()
        self.app_state.action_button_text = None

    def _on_plugin_hook_finished(
        self, hook_args: tuple[Any, ...], success: bool
    ) -> None:
        thread = self._plugin_hook_thread
        self._plugin_hook_thread = None
        if thread:
            retire_qthread(thread)
        selections = hook_args[0] if hook_args else {}
        needs_multi_mod = bool(hook_args[1]) if len(hook_args) > 1 else False
        was_cancelled = bool(
            thread
            and (
                thread.isInterruptionRequested()
                or getattr(thread, "_cancelled", False)
            )
        )
        if self._operation_journal is not None:
            self._run_journal_operation(
                "checkpoint",
                lambda checkpointed, errors: self._on_plugin_checkpoint_finished(
                    selections,
                    needs_multi_mod,
                    success,
                    was_cancelled,
                    checkpointed,
                    errors,
                ),
                journal=self._operation_journal,
            )
            return
        self._on_plugin_checkpoint_finished(
            selections, needs_multi_mod, success, was_cancelled, True, []
        )

    def _on_plugin_checkpoint_finished(
        self,
        selections: dict[str, Any],
        needs_multi_mod: bool,
        success: bool,
        was_cancelled: bool,
        checkpointed: bool,
        errors: list[str],
    ) -> None:
        if self.launch_transaction.state in {
            LaunchState.CANCELLED,
            LaunchState.RESTORING,
        }:
            return
        if not checkpointed:
            logger.error("Could not checkpoint plugin changes: %s", errors)
            self._finish_background_launch_operation()
            self._cleanup_direct_launch_files(
                lambda: self._handle_launch_failure("plugin-checkpoint")
            )
            return
        if not success:
            if was_cancelled:
                logger.info("Plugin hook execution was cancelled by user")
                self.cancel_pending_launch()
            else:
                self._finish_background_launch_operation()
                self._cleanup_direct_launch_files(
                    lambda: self._handle_launch_failure("plugin")
                )
            return
        self._finalize_launch_after_plugin_hooks(
            selections, needs_multi_mod, journal_checkpointed=True
        )

    def _continue_after_patching(
        self,
        selections: dict[str, Any],
        patching_success: bool,
        needs_multi_mod: bool = False,
    ):
        if not patching_success:
            return
        if self._start_plugin_hook_thread(
            "after_mod_apply_before_launch",
            selections,
            needs_multi_mod,
            base_progress=96 if needs_multi_mod else 0,
            progress_span=4 if needs_multi_mod else 100,
        ):
            return
        self._safe_discord_rich_presence_call(
            "on_after_mod_apply_before_launch", selections, needs_multi_mod
        )
        self._finalize_launch_after_plugin_hooks(selections, needs_multi_mod)

    def _finalize_launch_after_plugin_hooks(
        self,
        selections: dict[str, Any],
        needs_multi_mod: bool = False,
        journal_checkpointed: bool = False,
    ) -> None:
        if self._operation_journal is not None and not journal_checkpointed:
            self._run_journal_operation(
                "checkpoint",
                lambda checkpointed, errors: self._on_finalize_checkpoint_finished(
                    selections, needs_multi_mod, checkpointed, errors
                ),
                journal=self._operation_journal,
            )
            return
        self._complete_launch_after_journal_checkpoint(selections, needs_multi_mod)

    def _on_finalize_checkpoint_finished(
        self,
        selections: dict[str, Any],
        needs_multi_mod: bool,
        checkpointed: bool,
        errors: list[str],
    ) -> None:
        if self.launch_transaction.state in {
            LaunchState.CANCELLED,
            LaunchState.RESTORING,
        }:
            return
        if not checkpointed:
            logger.error("Could not checkpoint operation journal before launch: %s", errors)
            self._finish_background_launch_operation()
            self._cleanup_direct_launch_files(
                lambda: self._handle_launch_failure("journal-checkpoint")
            )
            return
        self._complete_launch_after_journal_checkpoint(selections, needs_multi_mod)

    def _complete_launch_after_journal_checkpoint(
        self, selections: dict[str, Any], needs_multi_mod: bool
    ) -> None:
        self._finish_background_launch_operation()
        if (
            self._selected_launch_mode.starts_game
            and not needs_multi_mod
            and self.restore_window_callback
        ):
            self.game_launch_started.emit()
        has_selected_mods = self._has_selected_mods(selections)
        if not self._selected_launch_mode.starts_game:
            if self._operation_journal is not None:
                deployed = self.launch_transaction.mark_deployed(
                    lambda: self._operation_journal is not None
                    and self._operation_journal.state == "applied"
                )
                if not deployed:
                    self._cleanup_direct_launch_files(
                        lambda: self._handle_launch_failure("recovery-state")
                    )
                    return
            self._commit_permanent_operation()
            return
        use_steam = self.app_state.local_config.get("launch_via_steam", False)
        if has_selected_mods and use_steam and self.app_state.game_mode.steam_app_id:
            current_path = self._get_current_game_path()
            if current_path:
                game_name = get_game_name_string(self.app_state.game_mode)
                is_steam_path = is_path_in_steam_common(current_path, game_name)
                if not is_steam_path:
                    should_continue = True
                    if is_warning_enabled(
                        "steam_launch_with_mods", self.app_state.local_config
                    ):
                        should_continue = self.feedback_service.ask_patching_warning(
                            create_warning_event(
                                "steam_launch_with_mods",
                                context={"game_path": current_path},
                                fallback_message=tr(
                                    "ui.steam_launch_mods_warning_body",
                                    game_path=current_path,
                                ),
                            )
                        )
                    if not should_continue:
                        logger.info(
                            "Game launch cancelled: user declined Steam launch with mods warning"
                        )
                        self._cleanup_direct_launch_files(self._handle_launch_failure)
                        return
        launch_config = self._determine_launch_config(selections)
        if not launch_config:
            self._cleanup_direct_launch_files(
                lambda: self._handle_launch_failure("config")
            )
            return
        if self._operation_journal is not None:
            deployed = self.launch_transaction.mark_deployed(
                lambda: self._operation_journal is not None and self._operation_journal.state == "applied"
            )
        else:
            deployed = True
        if not deployed:
            self.status_changed.emit(
                tr("errors.pending_session_restore_failed"),
                UI_COLORS["status_error"],
            )
            self._cleanup_direct_launch_files()
            self._handle_launch_failure("recovery-state")
            return
        if needs_multi_mod and self.restore_window_callback:
            self.game_launch_started.emit()
        self._execute_game(launch_config)

    def _complete_patch_only_operation(self) -> None:
        self._finish_background_launch_operation()
        self.status_changed.emit(
            tr("status.patching_completed"), UI_COLORS["status_success"]
        )
        parent = self.parent()
        controller = getattr(parent, "game_launch", None) if parent else None
        if controller and hasattr(controller, "update_button_state"):
            controller.update_button_state()

    def _on_patching_status(self, message: str, status_type: str):
        color = (
            status_type
            if QColor(status_type).isValid()
            else UI_COLORS.get(f"status_{status_type}", UI_COLORS["status_error"])
        )
        self.status_changed.emit(message, color)

    def _on_patching_progress(self, progress: int, message: str):
        self.app_state.progress_bar_value = progress
        self.app_state.progress_bar_visible = True
        if message:
            self.status_changed.emit(message, UI_COLORS["status_info"])

    def _cleanup_direct_launch_files(
        self, callback=None, *, blocking: bool = False, force: bool = False
    ) -> None:
        if callback is not None:
            self._cleanup_callbacks.append(callback)
        if self._operation_journal_thread is not None:
            self._cleanup_pending = True
            return
        self._cleanup_pending = False
        operation_journal = self._operation_journal
        restore_transaction = operation_journal is not None and self.launch_transaction.state in {
            LaunchState.PREPARING,
            LaunchState.BACKING_UP,
            LaunchState.APPLYING,
            LaunchState.DEPLOYED,
            LaunchState.LAUNCHING,
            LaunchState.RUNNING,
            LaunchState.CANCELLED,
            LaunchState.FAILED,
        }
        if restore_transaction:
            self.launch_transaction.transition(LaunchState.RESTORING)
        cleanup_info = self._direct_launch_cleanup_info
        self._direct_launch_cleanup_info = None
        self._run_journal_operation(
            "restore",
            lambda restored, errors, error: self._on_direct_cleanup_finished(
                operation_journal,
                restore_transaction,
                cleanup_info,
                restored,
                errors,
                error,
            ),
            journal=operation_journal,
            cleanup_info=cleanup_info,
            blocking=blocking,
            include_error=True,
            force=force,
        )

    def _on_direct_cleanup_finished(
        self,
        operation_journal: ModOperationJournal | None,
        restore_transaction: bool,
        cleanup_info: dict | None,
        restored: bool,
        errors: list[str],
        error: Exception | None,
    ) -> None:
        if isinstance(error, ModRecoveryConflictError):
            self._resolve_direct_cleanup_conflict(
                operation_journal, restore_transaction, cleanup_info, error
            )
            return
        self._complete_direct_cleanup(
            operation_journal, restore_transaction, restored, errors
        )

    def _resolve_direct_cleanup_conflict(
        self,
        operation_journal: ModOperationJournal | None,
        restore_transaction: bool,
        cleanup_info: dict | None,
        error: ModRecoveryConflictError,
    ) -> None:
        choice = self._ask_recovery_conflict(error)
        if choice == "force" and operation_journal is not None:
            self._run_journal_operation(
                "restore",
                lambda restored, errors, retry_error: self._on_direct_cleanup_finished(
                    operation_journal,
                    restore_transaction,
                    None,
                    restored,
                    errors,
                    retry_error,
                ),
                journal=operation_journal,
                cleanup_info=cleanup_info,
                force=True,
                include_error=True,
            )
            return
        if operation_journal is not None:
            self._run_journal_operation(
                "retire",
                lambda retired, errors, retire_error: self._on_direct_cleanup_retired(
                    operation_journal,
                    restore_transaction,
                    retired,
                    errors,
                    retire_error,
                ),
                journal=operation_journal,
                cleanup_info=cleanup_info,
                include_error=True,
            )
            return
        self._complete_direct_cleanup(
            operation_journal,
            restore_transaction,
            False,
            [],
            skipped=True,
        )

    def _on_direct_cleanup_retired(
        self,
        operation_journal: ModOperationJournal,
        restore_transaction: bool,
        retired: bool,
        errors: list[str],
        error: Exception | None,
    ) -> None:
        self._complete_direct_cleanup(
            operation_journal,
            restore_transaction,
            retired,
            errors,
            skipped=retired,
        )

    def _complete_direct_cleanup(
        self,
        operation_journal: ModOperationJournal | None,
        restore_transaction: bool,
        restored: bool,
        errors: list[str],
        *,
        skipped: bool = False,
    ) -> None:
        if operation_journal is not None and restored:
            self._operation_journal = None
        if restore_transaction:
            if restored:
                self.launch_transaction.transition(LaunchState.COMPLETED)
            else:
                self.launch_transaction.fail("restore")
        if skipped:
            self.status_changed.emit(
                tr("status.restore_skipped_external_changes"),
                UI_COLORS["status_warning"],
            )
        elif errors:
            logger.error("[CLEANUP] %s", "; ".join(errors))
            self.status_changed.emit(
                tr("errors.files_restore_error", error=join_limited(errors, "; ")),
                UI_COLORS["status_error"],
            )
        else:
            self.status_changed.emit(
                tr("status.files_restored"), UI_COLORS["status_success"]
            )
        callbacks, self._cleanup_callbacks = self._cleanup_callbacks, []
        for callback in callbacks:
            callback()

    def _recover_operation_session(self) -> bool | None:
        journal_root = self._operation_session_root()
        if not (journal_root / "manifest.json").is_file():
            return None
        self.launch_transaction = LaunchTransaction()
        self.launch_transaction.transition(LaunchState.RECOVERING)
        journal = None
        try:
            journal = ModOperationJournal.load(journal_root)
            if journal.state not in {"restored", "retired"}:
                journal.restore()
            self.launch_transaction.transition(LaunchState.COMPLETED)
            self._safe_feedback_status(
                tr("status.files_restored"), UI_COLORS["status_success"]
            )
            return True
        except ModRecoveryConflictError as error:
            choice = self._ask_recovery_conflict(error)
            try:
                if choice == "force" and journal is not None:
                    journal.restore(force=True)
                    self.launch_transaction.transition(LaunchState.COMPLETED)
                    self._safe_feedback_status(
                        tr("status.files_restored"), UI_COLORS["status_success"]
                    )
                    return True
                if journal is not None:
                    journal.retire()
                    self.launch_transaction.transition(LaunchState.COMPLETED)
                    self._safe_feedback_status(
                        tr("status.restore_skipped_external_changes"), UI_COLORS["status_warning"]
                    )
                    return True
            except Exception as recovery_error:
                self.launch_transaction.fail("operation-recovery")
                logger.error("operation session recovery failed: %s", recovery_error, exc_info=True)
                self._safe_feedback_status(
                    tr("errors.files_restore_error", error=str(recovery_error)),
                    UI_COLORS["status_error"],
                )
                return False
            return False
        except Exception as error:
            self.launch_transaction.fail("operation-recovery")
            logger.error("operation session recovery failed: %s", error, exc_info=True)
            self._safe_feedback_status(
                tr("errors.files_restore_error", error=str(error)),
                UI_COLORS["status_error"],
            )
            return False

    def recover_previous_session(self):
        """Restore the one durable operation journal left by an interrupted launch."""
        if self.is_recovering_session:
            return
        journal_root = self._operation_session_root()
        if not (journal_root / "manifest.json").is_file():
            return
        self.launch_transaction = LaunchTransaction()
        self.launch_transaction.transition(LaunchState.RECOVERING)
        self._start_session_recovery(journal_root, "recover")

    @property
    def is_recovering_session(self) -> bool:
        return self._session_recovery_thread is not None

    def _start_session_recovery(
        self, journal_root: Path, action: str, *, force: bool = False
    ) -> None:
        thread = ModOperationJournalThread(
            action, journal_root=journal_root, force=force, parent=self
        )

        def finished(result) -> None:
            self._session_recovery_thread = None
            retire_qthread(thread)
            self._on_session_recovery_finished(journal_root, thread, *result)

        thread.result_ready.connect(finished)
        self._session_recovery_thread = thread
        thread.start()

    def _finish_session_recovery(self) -> None:
        parent = self.parent()
        controller = getattr(parent, "game_launch", None) if parent else None
        if controller and hasattr(controller, "update_button_state"):
            controller.update_button_state()

    def _on_session_recovery_finished(
        self,
        journal_root: Path,
        thread: ModOperationJournalThread,
        recovered: bool,
        errors: list[str],
    ) -> None:
        if recovered:
            self.launch_transaction.transition(LaunchState.COMPLETED)
            self._safe_feedback_status(
                tr("status.files_restored"), UI_COLORS["status_success"]
            )
            self._finish_session_recovery()
            return
        if isinstance(thread.error, ModRecoveryConflictError):
            if self._ask_recovery_conflict(thread.error) == "force":
                self._start_session_recovery(journal_root, "restore", force=True)
            else:
                self._start_session_recovery(journal_root, "retire")
            return
        self.launch_transaction.fail("operation-recovery")
        logger.error("operation session recovery failed: %s", "; ".join(errors))
        self._safe_feedback_status(
            tr("errors.files_restore_error", error=join_limited(errors, "; ")),
            UI_COLORS["status_error"],
        )
        self._finish_session_recovery()

    def _find_and_validate_game_path(
        self, selections: dict[str, Any] | None = None, is_initial: bool = False
    ):
        from services.game_detection_service import is_valid_game_path
        from utils.path_utils import autodetect_path

        path_from_config = self._get_current_game_path()
        game_name = get_game_name_string(self.app_state.game_mode)
        game_type = get_game_type_string(self.app_state.game_mode)
        if path_from_config and os.path.exists(path_from_config):
            if is_valid_game_path(
                path_from_config, skip_data_check=False, game_type=game_type
            ):
                self.status_changed.emit(
                    tr("status.game_path", path=path_from_config),
                    UI_COLORS["status_info"],
                )
                return True
            parent_path = os.path.dirname(path_from_config)
            if (
                parent_path
                and os.path.exists(parent_path)
                and is_valid_game_path(
                    parent_path, skip_data_check=False, game_type=game_type
                )
            ):
                self.app_state.game_mode.set_game_path(
                    self.app_state.local_config, parent_path
                )
                self.status_changed.emit(
                    tr("status.game_folder_found", path=parent_path),
                    UI_COLORS["status_success"],
                )
                return True
        custom_exec_key = self.app_state.game_mode.get_custom_exec_config_key()
        custom_path = self.app_state.local_config.get(custom_exec_key, "")
        if custom_path and os.path.isfile(custom_path):
            if path_from_config and os.path.isdir(path_from_config):
                self.status_changed.emit(
                    tr("status.game_path", path=path_from_config),
                    UI_COLORS["status_info"],
                )
                return True
            custom_dir = os.path.dirname(custom_path)
            if custom_dir and os.path.exists(custom_dir):
                self.app_state.game_mode.set_game_path(
                    self.app_state.local_config, custom_dir
                )
                self.status_changed.emit(
                    tr("status.game_folder_found", path=custom_dir),
                    UI_COLORS["status_success"],
                )
                return True
        self.status_changed.emit(
            tr("status.autodetecting_path"), UI_COLORS["status_info"]
        )
        autodetected_path = autodetect_path(game_name)
        if (
            autodetected_path
            and os.path.exists(autodetected_path)
            and is_valid_game_path(
                autodetected_path, skip_data_check=False, game_type=game_type
            )
        ):
            self.app_state.game_mode.set_game_path(
                self.app_state.local_config, autodetected_path
            )
            self.status_changed.emit(
                tr("status.game_folder_found", path=autodetected_path),
                UI_COLORS["status_success"],
            )
            return True
        if is_initial:
            self.status_changed.emit(
                tr("status.no_game_path"), UI_COLORS["status_error"]
            )
        return False

    def _has_selected_mods(self, selections: dict[str, Any]) -> bool:
        return any(
            (
                mod_data
                if isinstance(mod_data, list)
                else (mod_data and mod_data != "no_change")
            )
            for mod_data in selections.values()
        )
