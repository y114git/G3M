"""Game launch and mod patching management."""

import contextlib
import errno
import logging
import os
import platform
import shutil
import subprocess
import time
from typing import Any

from PyQt6.QtCore import QObject, QProcess, QThread, QTimer, pyqtSignal

from config.config import UI_COLORS
from services.g3mtool_patching_service import G3MToolPatchingService
from services.game_detection_service import (
    get_game_name_string,
    get_game_type_string,
    get_matching_process_identities,
)
from services.localization_service import tr
from services.warning_service import create_warning_event, is_warning_enabled
from ui.common.styling import get_launch_status_color
from ui.utils.thread_lifetime import retire_qthread
from utils.file_utils import ensure_writable
from utils.native_integration import open_url_native
from utils.path_utils import (
    find_chapter_resource_dir,
    is_path_in_steam_common,
    resolve_game_executable,
)
from utils.process_utils import (
    build_external_process_env,
    resolve_portproton_command,
    resolve_wine_command,
)
from workers.game_monitor_worker import GameMonitorWorker
from workers.plugin_hook_worker import PluginHookThread

logger = logging.getLogger(__name__)


class GameLauncher(QObject):
    """Manages game launching, mod patching, and game monitoring."""

    status_changed = pyqtSignal(str, str)
    progress_updated = pyqtSignal(int)
    game_launch_started = pyqtSignal()
    game_launch_finished = pyqtSignal()
    mod_patching_finished = pyqtSignal(bool)

    def __init__(self, app_state, feedback_service, mod_service, parent=None) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.mod_service = mod_service
        self.monitor_thread = None
        self._direct_launch_cleanup_info = None
        self.mod_patcher = G3MToolPatchingService(app_state, mod_service, parent)
        self.mod_patcher.status_update.connect(self._on_patching_status)
        self.mod_patcher.progress_update.connect(self._on_patching_progress)
        self._patching_thread = None
        self._retiring_patching_threads: list[QThread] = []
        self._plugin_hook_thread = None
        self.restore_window_callback = None
        self._launch_started_at = None
        self._launch_mod_ids: list[str] = []
        self._launch_mod_refs: list[dict[str, str]] = []
        self._launch_mode = "unknown"
        self._launch_had_mods = False

    def _stop_monitor_thread(self):
        if not self.monitor_thread:
            return
        try:
            if self.monitor_thread.isRunning():
                self.monitor_thread.requestInterruption()
                self.monitor_thread.quit()
            self.monitor_thread.deleteLater()
            if hasattr(self, "monitor_worker") and self.monitor_worker is not None:
                self.monitor_worker.deleteLater()
        except Exception as e:
            logger.error(f"monitor thread cleanup failed: {e}", exc_info=True)

    def _launch_status_color(self) -> str:
        return get_launch_status_color(getattr(self.app_state, "local_config", None))

    def _safe_feedback_status(self, message: str, color: str) -> None:
        try:
            self.feedback_service.update_status(message, color)
        except Exception:
            logger.exception("GameLauncher: failed to update feedback status")

    @staticmethod
    def _is_path_like_command(command_name: str) -> bool:
        return bool(command_name) and (
            os.path.isabs(command_name)
            or "/" in command_name
            or "\\" in command_name
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
            if error_path and target_path and os.path.abspath(error_path) == os.path.abspath(target_path):
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
        return getattr(parent, "discord_rich_presence_service", None) if parent else None

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

    def launch_game_with_all_mods(self, restore_window_callback=None):
        self._launch_game_with_selections(
            self._get_used_mods_selections(), restore_window_callback
        )

    def _get_used_mods_selections(self) -> dict[str, Any]:
        try:
            parent_obj = self.parent()
        except (AttributeError, TypeError):
            parent_obj = None
        used_mods_service = (
            getattr(parent_obj, "used_mods_service", None) if parent_obj else None
        )
        if not used_mods_service or not hasattr(
            used_mods_service, "get_active_mod_selections"
        ):
            return {}
        return used_mods_service.get_active_mod_selections()

    def _get_used_mod_steps(self) -> dict[str, list[list[Any]]]:
        try:
            parent_obj = self.parent()
        except (AttributeError, TypeError):
            parent_obj = None
        used_mods_service = (
            getattr(parent_obj, "used_mods_service", None) if parent_obj else None
        )
        if not used_mods_service or not hasattr(
            used_mods_service, "get_active_mod_steps"
        ):
            return {}
        return used_mods_service.get_active_mod_steps()

    def _launch_game_with_selections(
        self,
        selections: dict[str, Any],
        restore_window_callback=None,
    ):
        self._launch_started_at = time.monotonic()
        self._launch_mod_ids = self._collect_launch_mod_ids(selections)
        self._launch_mod_refs = self._collect_launch_mod_refs(selections)
        self._launch_had_mods = self._has_selected_mods(selections)
        self._launch_mode = "unknown"
        self.restore_window_callback = restore_window_callback
        self.status_changed.emit(
            tr("status.launching_game"), self._launch_status_color()
        )
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
        if needs_multi_mod:
            logger.info("Using multi-mod patcher for game launch")
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.is_patching = True
            self.app_state.action_button_text = tr("ui.cancel_button")
            self.app_state.action_button_enabled = True
            if not self._prepare_game_files_multi_mod_async(
                selections, self._get_used_mod_steps()
            ):
                logger.error("Failed to start multi-mod patching")
                self.app_state.progress_bar_visible = False
                self.app_state.is_patching = False
                self._handle_launch_failure()
                return
        else:
            self._continue_after_patching(selections, True, needs_multi_mod)

    def _handle_launch_failure(self, reason: str = "unknown"):
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
            self._handle_launch_failure()
            return
        try:
            self._stop_monitor_thread()
            process_names = self._expected_process_names(target_path)
            baseline_processes = get_matching_process_identities(process_names)
            if launch_type == "url":
                self.monitor_thread = QThread(self)
                self.monitor_worker = GameMonitorWorker(
                    None, vanilla_mode, process_names, baseline_processes
                )
                self.monitor_worker.moveToThread(self.monitor_thread)
                self.monitor_worker.finished.connect(self._on_game_process_finished)
                self.monitor_thread.started.connect(self.monitor_worker.run)
                self.monitor_thread.start()
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
                parent = self.parent()
                runtime_service = (
                    getattr(parent, "plugin_runtime_service", None) if parent else None
                )
                if runtime_service:
                    runtime_service.execute_hook("after_game_started", vanilla_mode)
                self._safe_discord_rich_presence_call(
                    "on_after_game_started", vanilla_mode
                )
                return
            if not working_directory or not os.path.isdir(working_directory):
                msg = tr("errors.working_directory_not_found", path=working_directory)
                self.status_changed.emit(msg, "red")
                self._handle_launch_failure()
                return
            process = None
            system = platform.system()
            if system == "Darwin":
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
                if system == "Linux" and target_path.lower().endswith(".exe"):
                    is_steam_launch = self.app_state.local_config.get(
                        "launch_via_steam", False
                    )
                    use_portproton = self.app_state.local_config.get(
                        "use_portproton", False
                    )
                    if not is_steam_launch:
                        if use_portproton:
                            command = [
                                resolve_portproton_command(
                                    self.app_state.local_config
                                ),
                                "run",
                                target_path,
                            ]
                        else:
                            command.insert(
                                0, resolve_wine_command(self.app_state.local_config)
                            )
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
                    self._handle_launch_failure()
                    return
            self.status_changed.emit(
                tr("status.game_launched_waiting_for_exit"), self._launch_status_color()
            )
            self.monitor_thread = QThread(self)
            self.monitor_worker = GameMonitorWorker(
                process, vanilla_mode, process_names, baseline_processes
            )
            self.monitor_worker.moveToThread(self.monitor_thread)
            self.monitor_worker.finished.connect(self._on_game_process_finished)
            self.monitor_thread.started.connect(self.monitor_worker.run)
            self.monitor_thread.start()
            self._execute_plugin_hook("after_game_started", vanilla_mode)
            self._safe_discord_rich_presence_call(
                "on_after_game_started", vanilla_mode
            )
        except Exception as e:
            self.status_changed.emit(
                self._format_launch_error(
                    e, command=command, target_path=target_path
                ),
                "red",
            )
            self._handle_launch_failure()

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
                subprocess.Popen(
                    [program, *arguments],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return True
            except Exception:
                return False

    def _on_game_process_finished(self, vanilla_mode: bool):
        self._check_game_running(vanilla_mode)

    def _check_game_running(self, vanilla_mode):
        logger.info("[LAUNCH] Game is no longer running, starting cleanup")
        self.app_state.is_patching = True
        self.app_state.progress_bar_visible = True
        if self.restore_window_callback:
            self.restore_window_callback()
        self._record_launch_playtime()
        self._execute_plugin_hook("before_restore_after_exit", vanilla_mode)
        self._safe_discord_rich_presence_call(
            "on_before_restore_after_exit", vanilla_mode
        )
        self.status_changed.emit(
            tr("status.game_closed_restoring_files"), UI_COLORS["status_info"]
        )
        QTimer.singleShot(50, lambda: self._finish_game_cleanup(vanilla_mode))

    def _finish_game_cleanup(self, vanilla_mode: bool) -> None:
        self._cleanup_direct_launch_files()
        if self.monitor_thread:
            self._stop_monitor_thread()
            self.monitor_thread = None
            if hasattr(self, "monitor_worker"):
                self.monitor_worker = None
        self.game_launch_finished.emit()
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
        if self._launch_mod_ids and mod_service and hasattr(mod_service, "add_playtime_hours"):
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
                if not mod_id or mod_id in seen or mod_id.startswith("local_"):
                    continue
                seen.add(mod_id)
                result.append(mod_id)
        return result

    @staticmethod
    def _collect_launch_mod_refs(selections: dict[str, Any]) -> list[dict[str, str]]:
        from utils.mod.utils import get_mod_id, get_mod_name, parse_gamebanana_mod_id

        seen = set()
        result: list[dict[str, str]] = []
        for mods in selections.values():
            mod_list = mods if isinstance(mods, list) else [mods]
            for mod in mod_list:
                mod_id = get_mod_id(mod)
                gb_type, gb_id = parse_gamebanana_mod_id(str(mod_id or ""))
                if not gb_type or not gb_id or mod_id in seen:
                    continue
                seen.add(mod_id)
                payload = {"ref": f"gb_{gb_type}_{gb_id}"}
                mod_name = str(get_mod_name(mod, "") or "").strip()
                if mod_name:
                    payload["name"] = mod_name
                result.append(payload)
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
        custom_path = self.app_state.local_config.get(
            self.app_state.game_mode.get_custom_exec_config_key(), ""
        )
        if custom_path and os.path.isfile(custom_path):
            return custom_path
        current_game_path = self._get_current_game_path()
        if not current_game_path or not os.path.isdir(current_game_path):
            return None
        return resolve_game_executable(
            current_game_path, self.app_state.game_mode.executable_type
        )

    def _get_source_executable_path(self):
        cfg_key = self.app_state.game_mode.get_custom_exec_config_key()
        custom_path = self.app_state.local_config.get(cfg_key, "")
        if custom_path and os.path.isfile(custom_path):
            return custom_path
        return self._get_executable_path()

    def _get_current_game_path(self) -> str:
        return self.app_state.game_mode.get_game_path(self.app_state.local_config) or ""

    def _prepare_game_files_multi_mod_async(
        self,
        selections: dict[str, list[Any]],
        patch_steps: dict[str, list[list[Any]]] | None = None,
    ) -> bool:
        from models.execution_plan import PatchPlan
        from workers.mod.patching_worker import ModPatchingThread

        logger.info("Starting multi-mod patching in background thread")
        chapter_mods = {
            chapter_id: steps
            for chapter_id, steps in (patch_steps or {}).items()
            if steps
        } or {
            chapter_id: [mods_list]
            for chapter_id, mods_list in selections.items()
            if isinstance(mods_list, list) and mods_list
        }
        if not chapter_mods:
            self._continue_after_patching(selections, True, False)
            return True
        self.app_state.progress_bar_visible = True
        self.app_state.progress_bar_value = 0
        session_manifest_path = os.path.join(self.app_state.config_dir, "session.lock")
        patch_plan = PatchPlan.from_runtime(chapter_mods)
        plan_mods = [
            mod
            for steps in chapter_mods.values()
            for step in steps
            for mod in step
        ]
        self._patching_thread = ModPatchingThread(
            self.app_state,
            self.mod_service,
            patch_plan,
            session_manifest_path,
            self,
            plan_mods=plan_mods,
        )
        self._patching_thread.progress_update.connect(self._on_patching_progress)
        self._patching_thread.status_update.connect(self._on_patching_status)
        self._patching_thread.warning_confirmation_needed.connect(
            self._on_patching_warning_confirmation_needed
        )
        self._patching_thread.result_ready.connect(
            lambda success: self._on_patching_finished(selections, success)
        )
        self.app_state.current_task = self._patching_thread
        self._patching_thread.start()
        return True

    def _on_patching_warning_confirmation_needed(
        self, message: object, details: str, report_path: str | None
    ):
        patching_thread = self._patching_thread
        if not patching_thread:
            return
        should_continue = self.feedback_service.ask_patching_warning(
            message, details, report_path
        )
        patching_thread.confirm_warning(should_continue)

    def _on_patching_finished(self, selections: dict[str, Any], success: bool):
        patching_thread = self._patching_thread
        if patching_thread:
            try:
                if patching_thread.patcher:
                    self.mod_patcher = patching_thread.patcher
                self._retiring_patching_threads.append(patching_thread)
                cleaned_up = False

                def cleanup_patching_thread():
                    nonlocal cleaned_up
                    if cleaned_up:
                        return
                    cleaned_up = True
                    if patching_thread.patcher:
                        self.mod_patcher = patching_thread.patcher
                    with contextlib.suppress(ValueError):
                        self._retiring_patching_threads.remove(patching_thread)
                    patching_thread.deleteLater()

                patching_thread.finished.connect(cleanup_patching_thread)
                if not patching_thread.isRunning():
                    cleanup_patching_thread()
                else:
                    logger.debug(
                        "Patching thread still running, will clean up via finished signal"
                    )
            except Exception as e:
                logger.error(f"Error cleaning up patching thread: {e}", exc_info=True)
            finally:
                self._patching_thread = None
        if not success:
            self._finish_background_launch_operation()
            if patching_thread and (
                patching_thread.isInterruptionRequested()
                or getattr(patching_thread, "_cancelled", False)
            ):
                logger.info("Multi-mod patching was cancelled by user")
            else:
                self._handle_launch_failure()
            return
        logger.info("Multi-mod patching completed successfully")
        self._continue_after_patching(selections, True, True)

    def _try_restore_backups(self, context: str = "", emit_status: bool = True) -> bool:
        if not hasattr(self, "mod_patcher") or not self.mod_patcher:
            return False
        try:
            restored = self.mod_patcher.restore_all_backups()
            if restored and emit_status:
                logger.info(f"{context}: backups restored successfully")
                self.status_changed.emit(
                    tr("status.files_restored"), UI_COLORS["status_success"]
                )
            else:
                logger.debug(f"{context}: no backups to restore")
            return restored
        except Exception as e:
            logger.error(f"{context}: Failed to restore backups: {e}", exc_info=True)
            return False

    def _execute_plugin_hook(self, hook_name: str, *args):
        """Execute a plugin hook if the runtime service is available.

        Returns an iterable of hook results, or an empty iterable if no runtime service.
        """
        runtime_service = self._plugin_runtime_service()
        if runtime_service:
            return runtime_service.execute_hook(hook_name, *args)
        return []

    def _restore_host_backups_for_plugin_task(self) -> bool:
        if not self.mod_patcher:
            return False
        return bool(self.mod_patcher.restore_all_backups())

    def _start_plugin_hook_thread(
        self,
        hook_name: str,
        *hook_args,
        base_progress: int = 0,
        progress_span: int = 100,
    ) -> bool:
        runtime_service = self._plugin_runtime_service()
        if not runtime_service or not runtime_service.has_enabled_hook(hook_name):
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
            backup_manager_provider=lambda: getattr(self.mod_patcher, "backup_service", None),
            restore_backups_callback=self._restore_host_backups_for_plugin_task,
            parent=self,
        )
        thread.progress_update.connect(self._on_patching_progress)
        thread.status_update.connect(self._on_patching_status)
        thread.result_ready.connect(
            lambda success: self._on_plugin_hook_finished(hook_args, success)
        )
        self._plugin_hook_thread = thread
        self.app_state.current_task = thread
        thread.start()
        return True

    def _finish_background_launch_operation(self) -> None:
        self.app_state.progress_bar_visible = False
        self.app_state.is_patching = False
        self.app_state.clear_current_task()
        self.app_state.action_button_text = None

    def _on_plugin_hook_finished(self, hook_args: tuple[Any, ...], success: bool) -> None:
        thread = self._plugin_hook_thread
        self._plugin_hook_thread = None
        if thread:
            retire_qthread(thread)
        selections = hook_args[0] if hook_args else {}
        needs_multi_mod = bool(hook_args[1]) if len(hook_args) > 1 else False
        if not success:
            self._finish_background_launch_operation()
            if thread and (thread.isInterruptionRequested() or getattr(thread, "_cancelled", False)):
                logger.info("Plugin hook execution was cancelled by user")
            self._cleanup_direct_launch_files()
            self._handle_launch_failure("plugin")
            return
        self._finalize_launch_after_plugin_hooks(selections, needs_multi_mod)

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
    ) -> None:
        self._finish_background_launch_operation()
        if not needs_multi_mod and self.restore_window_callback:
            self.game_launch_started.emit()
        has_selected_mods = self._has_selected_mods(selections)
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
                        self._cleanup_direct_launch_files()
                        self._handle_launch_failure()
                        return
        launch_config = self._determine_launch_config(selections)
        if not launch_config:
            self._handle_launch_failure("config")
            return
        self._launch_mode = str(launch_config.get("type", "unknown"))
        if needs_multi_mod and self.restore_window_callback:
            self.game_launch_started.emit()
        self._execute_game(launch_config)

    def _on_patching_status(self, message: str, status_type: str):
        color = UI_COLORS.get(f"status_{status_type}", UI_COLORS["status_error"])
        self.status_changed.emit(message, color)

    def _on_patching_progress(self, progress: int, message: str):
        self.app_state.progress_bar_value = progress
        self.app_state.progress_bar_visible = True
        if message:
            self.status_changed.emit(message, UI_COLORS["status_info"])

    def _cleanup_direct_launch_files(self):
        restore_errors = []
        try:
            try:
                self._try_restore_backups("[CLEANUP]", emit_status=False)

                if hasattr(self, "mod_patcher") and self.mod_patcher:
                    self.mod_patcher.clear_session()
            except Exception as e:
                restore_errors.append(str(e))
            cleanup_info = self._direct_launch_cleanup_info
            if cleanup_info:
                for mus_folder_path in cleanup_info.get("mus_folders", []):
                    if os.path.isdir(mus_folder_path):
                        try:
                            shutil.rmtree(mus_folder_path)
                        except Exception as e:
                            restore_errors.append(
                                f"music folder {mus_folder_path}: {e}"
                            )
                target_exe = cleanup_info.get("target_exe")
                if target_exe and os.path.exists(target_exe):
                    try:
                        os.remove(target_exe)
                    except Exception as e:
                        restore_errors.append(f"direct launch exe: {e}")
                self._direct_launch_cleanup_info = None
            if restore_errors:
                logger.error(
                    f"[CLEANUP] {len(restore_errors)} error(s): {restore_errors[:3]}"
                )
                self.status_changed.emit(
                    tr("errors.files_restore_error", error=str(restore_errors[0])),
                    UI_COLORS["status_error"],
                )
            else:
                self.status_changed.emit(
                    tr("status.files_restored"), UI_COLORS["status_success"]
                )
        except Exception as e:
            logger.error(f"[CLEANUP] Critical error: {e}", exc_info=True)
            self.status_changed.emit(
                tr("errors.files_restore_error", error=str(e)),
                UI_COLORS["status_error"],
            )

    def recover_previous_session(self):
        """Check for stale session.lock and restore game files if a previous session crashed."""
        try:
            manifest_path = os.path.join(self.app_state.config_dir, "session.lock")
            if not os.path.isfile(manifest_path):
                return
            logger.warning(
                f"Found stale session manifest: {manifest_path} - previous session may have crashed"
            )
            self._safe_feedback_status(
                tr("status.recovering_previous_session"), UI_COLORS["status_warning"]
            )
            from services.backup_service import BackupManager

            try:
                backup_mgr = BackupManager.load_from_manifest(manifest_path)
                if not backup_mgr.original_files and not backup_mgr.added_files:
                    logger.info("Session manifest has no tracked files, cleaning up")
                    backup_mgr.clear_backup_dir()
                    return
                backup_mgr.restore_all_backups()
                backup_mgr.clear_backup_dir()
                logger.info(
                    "recover_previous_session: game files restored successfully"
                )
                self._safe_feedback_status(
                    tr("status.files_restored"), UI_COLORS["status_success"]
                )
            except Exception as e:
                logger.error(
                    f"recover_previous_session: Failed to restore from manifest: {e}",
                    exc_info=True,
                )
                self._safe_feedback_status(
                    tr("errors.files_restore_error", error=str(e)),
                    UI_COLORS["status_error"],
                )
        except Exception as e:
            logger.error(f"recover_previous_session: Failed: {e}", exc_info=True)

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
