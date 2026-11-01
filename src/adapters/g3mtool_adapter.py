"""G3MTool CLI execution and management."""

import codecs
import contextlib
import json
import logging
import os
import platform
import re
import subprocess
import threading
import time
from collections.abc import Callable

import psutil

from services.background_operations import background_operations, terminate_process
from services.localization_service import tr
from utils.path_utils import get_g3mtool_cache_dir, get_user_data_root, resource_path
from utils.process_utils import bounded_output_preview, format_external_process_error

logger = logging.getLogger(__name__)


def _terminate_tree(process: subprocess.Popen) -> None:
    """Stop the tool and anything it started, so no child keeps a patch file open."""
    children: list[psutil.Process] = []
    suspended = False
    try:
        parent = psutil.Process(process.pid)
        # A frozen parent cannot start new children while the existing ones are collected.
        with contextlib.suppress(psutil.Error):
            parent.suspend()
            suspended = True
        children = parent.children(recursive=True)
    except psutil.Error:
        pass
    for child in children:
        with contextlib.suppress(psutil.Error):
            child.kill()
    if suspended:
        process.kill()  # a stopped process would leave a polite SIGTERM pending
    else:
        terminate_process(process)
    psutil.wait_procs(children, timeout=5)


class G3MToolManager:
    """Manages G3MTool CLI execution for patching operations."""

    _PROGRESS_RE = re.compile(r"^(?P<label>.+?):\s*(?P<percent>\d+)%")
    _cached_executable_paths: dict[str, str | None] = {}
    _logged_executable_paths: set[str] = set()

    def __init__(self, app_state=None) -> None:
        self.app_state = app_state
        self.platform = {"Windows": "windows", "Darwin": "macos"}.get(
            platform.system(), "linux"
        )
        self.g3mtool_path = None
        self.refresh_executable()
        self._active_processes: list[subprocess.Popen] = []
        self._active_processes_lock = threading.Lock()
        # Polled while a command runs; a true answer kills the process so cancel is immediate.
        self.is_cancelled: Callable[[], bool] | None = None

    def _get_local_config(self) -> dict:
        local_config = getattr(self.app_state, "local_config", None)
        if isinstance(local_config, dict):
            return local_config
        try:
            config_path = os.path.join(
                get_user_data_root(), "settings", "settings.json"
            )
            if os.path.isfile(config_path):
                with open(config_path, encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            logger.debug("Failed to load local config for G3MToolManager: %s", e)
        return {}

    def _get_configured_g3mtool_path(self) -> str | None:
        path = str(
            self._get_local_config().get("custom_g3mtool_path", "") or ""
        ).strip()
        return path or None

    def _get_configured_xdelta_path(self) -> str | None:
        path = str(self._get_local_config().get("custom_xdelta_path", "") or "").strip()
        return path or None

    def _find_executable(self) -> str | None:
        custom_path = self._get_configured_g3mtool_path()
        if custom_path:
            if os.path.isfile(custom_path):
                return custom_path
            logger.warning(
                f"Custom G3MTool path not found, falling back to bundled: {custom_path}"
            )
        if self.platform in self._cached_executable_paths:
            return self._cached_executable_paths[self.platform]
        base_path = resource_path(f"assets/bin/g3mtool_{self.platform}")
        exe_name = "G3MTool.exe" if self.platform == "windows" else "G3MTool"
        exe_path = os.path.join(base_path, exe_name)
        if os.path.isfile(exe_path):
            if self.platform != "windows":
                try:
                    os.chmod(exe_path, 0o700)
                except Exception as e:
                    logger.warning(
                        f"Could not set executable permission on {exe_path}: {e}"
                    )
            if exe_path not in self._logged_executable_paths:
                logger.info(f"Found G3MTool: {exe_path}")
                self._logged_executable_paths.add(exe_path)
            self._cached_executable_paths[self.platform] = exe_path
            return exe_path
        logger.warning(f"G3MTool not found at {exe_path}")
        self._cached_executable_paths[self.platform] = None
        return None

    def refresh_executable(self) -> str | None:
        self.g3mtool_path = self._find_executable()
        return self.g3mtool_path

    def is_available(self) -> bool:
        return self.refresh_executable() is not None

    def get_unavailable_reason(self) -> str:
        custom_path = self._get_configured_g3mtool_path()
        if custom_path and not os.path.isfile(custom_path):
            return tr("errors.custom_g3mtool_not_found", path=custom_path)
        return tr("errors.g3mtool_not_available")

    @staticmethod
    def _unavailable_result(message: str | None = None) -> tuple[int, str, str]:
        return (-1, "", message or tr("errors.g3mtool_not_available"))

    @staticmethod
    def _supports_cache(args: list[str]) -> bool:
        if not args:
            return False
        if args[0] in {"info", "diff"}:
            return True
        if len(args) >= 3 and args[0] == "patch" and args[1] == "batch":
            return args[2] in {"apply", "create", "merge"}
        return (
            len(args) >= 2
            and args[0] == "patch"
            and args[1]
            in {
                "apply",
                "create",
                "merge",
                "validate",
            }
        )

    def _run_command(
        self,
        args: list[str],
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        g3mtool_path = self.refresh_executable()
        if not g3mtool_path:
            return self._unavailable_result(self.get_unavailable_reason())
        full_args = [*args]
        if self._supports_cache(full_args):
            cache_dir = get_g3mtool_cache_dir()
            os.makedirs(cache_dir, exist_ok=True)
            full_args.extend(["--cache", cache_dir])
        xdelta_path = self._get_configured_xdelta_path()
        if xdelta_path:
            option_index = (
                full_args.index("--") if "--" in full_args else len(full_args)
            )
            full_args[option_index:option_index] = ["--xdelta-path", xdelta_path]
        return self._run(
            [g3mtool_path, *full_args],
            progress_callback=progress_callback,
        )

    def merge_patches(
        self,
        original_data_win: str,
        mod_patches: list[str],
        output_path: str,
        patch_output_path: str | None = None,
        report_path: str | None = None,
        log_path: str | None = None,
        merge_code: bool = False,
        merge_properties: bool = False,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool patch merge <original> <patch1> <patch2> ... --apply <output> [--out <patch>] [--report <path>] [--log <path>]"""
        cmd = ["patch", "merge", original_data_win, *mod_patches]
        cmd.extend(["--apply", output_path])
        if patch_output_path:
            cmd.extend(["--out", patch_output_path])
        for flag, enabled in [
            ("--code", merge_code),
            ("--properties", merge_properties),
        ]:
            if enabled:
                cmd.append(flag)
        if report_path:
            cmd.extend(["--report", report_path])
        if log_path:
            cmd.extend(["--log", log_path])
        return self._run_command(
            cmd,
            progress_callback=progress_callback,
        )

    def batch_apply_patches(
        self,
        original_data_win: str,
        patch_paths: list[str],
        output_dir: str,
        continue_on_error: bool = False,
        include_xdelta_fallback: bool = False,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool patch batch apply <original> <patches...> --out-dir <dir>."""
        return self._batch_patch_command(
            "apply",
            original_data_win,
            patch_paths,
            output_dir,
            continue_on_error,
            include_xdelta_fallback,
            progress_callback,
        )

    def batch_create_patches(
        self,
        original_data_win: str,
        modified_files: list[str],
        output_dir: str,
        continue_on_error: bool = False,
        include_xdelta_fallback: bool = False,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool patch batch create <original> <modified...> --out-dir <dir>."""
        return self._batch_patch_command(
            "create",
            original_data_win,
            modified_files,
            output_dir,
            continue_on_error,
            include_xdelta_fallback,
            progress_callback,
        )

    def _batch_patch_command(
        self,
        action: str,
        original_data_win: str,
        paths: list[str],
        output_dir: str,
        continue_on_error: bool,
        include_xdelta_fallback: bool,
        progress_callback: Callable[[int, str], None] | None,
    ) -> tuple[int, str, str]:
        cmd = ["patch", "batch", action, original_data_win, *paths]
        cmd.extend(["--out-dir", output_dir])
        if continue_on_error:
            cmd.append("--continue-on-error")
        if include_xdelta_fallback:
            cmd.append("--xdelta-fallback")
        return self._run_command(cmd, progress_callback=progress_callback)

    def batch_merge_patches(
        self,
        original_data_win: str,
        patch_sets: list[list[str]],
        output_dir: str,
        patch_output_dir: str | None = None,
        continue_on_error: bool = False,
        merge_code: bool = False,
        merge_properties: bool = False,
        write_report: bool = False,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool patch batch merge <original> <set...> --apply <dir> [--out <dir>]."""
        comma_paths = [path for paths in patch_sets for path in paths if "," in path]
        if comma_paths:
            return (
                2,
                "",
                "Batch merge patch paths cannot contain commas: "
                + ", ".join(comma_paths),
            )
        encoded_sets = [",".join(paths) for paths in patch_sets if paths]
        cmd = ["patch", "batch", "merge", original_data_win, *encoded_sets]
        cmd.extend(["--apply", output_dir])
        if patch_output_dir:
            cmd.extend(["--out", patch_output_dir])
        if continue_on_error:
            cmd.append("--continue-on-error")
        if merge_code:
            cmd.append("--code")
        if merge_properties:
            cmd.append("--properties")
        if write_report:
            cmd.append("--report")
        return self._run_command(cmd, progress_callback=progress_callback)

    def apply_patch(
        self,
        original_data_win: str,
        patch_path: str,
        output_path: str,
        log_path: str | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool patch apply <original> <patch> <output> [--log <path>]"""
        cmd = [
            "patch",
            "apply",
            original_data_win,
            patch_path,
            output_path,
        ]
        if log_path:
            cmd.extend(["--log", log_path])
        return self._run_command(
            cmd,
            progress_callback=progress_callback,
        )

    def xpatch_apply(
        self,
        original_file: str,
        patch_path: str,
        output_path: str,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool xpatch apply <original> <patch> <output> for xdelta/vcdiff patches."""
        return self._xpatch_command(
            "apply", original_file, patch_path, output_path, progress_callback
        )

    def xpatch_create(
        self,
        original_file: str,
        modified_file: str,
        output_path: str,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool xpatch create <original> <modified> <output>."""
        return self._xpatch_command(
            "create", original_file, modified_file, output_path, progress_callback
        )

    def _xpatch_command(
        self,
        action: str,
        original_file: str,
        input_path: str,
        output_path: str,
        progress_callback: Callable[[int, str], None] | None,
    ) -> tuple[int, str, str]:
        return self._run_command(
            ["xpatch", action, original_file, input_path, output_path],
            progress_callback=progress_callback,
        )

    def patch_create(
        self,
        original_file: str,
        modified_file: str,
        output_path: str,
        include_xdelta_fallback: bool = False,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool patch create <original> <modified> [output]."""
        cmd = ["patch", "create", original_file, modified_file, output_path]
        if include_xdelta_fallback:
            cmd.append("--xdelta-fallback")
        return self._run_command(
            cmd,
            progress_callback=progress_callback,
        )

    def info(
        self,
        target: str,
        verbose: bool = False,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool info <target> [--verbose]."""
        cmd = ["info", target]
        if verbose:
            cmd.append("--verbose")
        return self._run_command(cmd, progress_callback=progress_callback)

    def diff(
        self,
        file1: str,
        file2: str,
        output_dir: str | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
        *,
        full_report: bool = False,
    ) -> tuple[int, str, str]:
        """Call g3mtool diff <file1> <file2> [output-dir] [--full]."""
        cmd = ["diff", file1, file2]
        if output_dir:
            cmd.append(output_dir)
        if full_report:
            cmd.append("--full")
        return self._run_command(cmd, progress_callback=progress_callback)

    def execute(
        self,
        target: str,
        args: list[str] | None = None,
        data_file: str | None = None,
        output_path: str | None = None,
        input_path: str | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool execute <target> [args] [--data <file>] [--output <file>] [--input <dir>]."""
        cmd = ["execute", target]
        if data_file:
            cmd.extend(["--data", data_file])
        if output_path:
            cmd.extend(["--output", output_path])
        if input_path:
            cmd.extend(["--input", input_path])
        if args:
            cmd.extend(["--", *(str(arg) for arg in args)])
        return self._run_command(
            cmd,
            progress_callback=progress_callback,
        )

    def cancel_active_processes(self):
        with self._active_processes_lock:
            processes = list(self._active_processes)
            self._active_processes.clear()
        for process in processes:
            try:
                if process.poll() is None:
                    _terminate_tree(process)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            except Exception as e:
                logger.debug(
                    f"G3MToolManager.cancel_active_processes: failed to stop process: {e}",
                    exc_info=True,
                )

    @classmethod
    def _parse_progress(cls, text: str) -> tuple[int, str] | None:
        match = cls._PROGRESS_RE.match(text.strip())
        if not match:
            return None
        return int(match.group("percent")), match.group("label")

    def _stream_output(
        self,
        stream,
        chunks: list[str],
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> None:
        raw = getattr(stream, "buffer", None)
        if raw is not None and hasattr(raw, "read1"):
            self._stream_raw_output(raw, chunks, progress_callback)
            return
        for line in stream:
            chunks.append(line)
            for text in line.splitlines():
                progress_callback = self._report_progress(text, progress_callback)

    def _stream_raw_output(
        self,
        raw,
        chunks: list[str],
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Read as bytes arrive so a progress update is seen the moment its carriage return is.

        A text stream holds back a trailing carriage return until the next character shows up,
        which made every progress step arrive one update late.
        """
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pending = ""
        after_return = False
        while True:
            data = raw.read1(8192)
            text = decoder.decode(data, final=not data)
            if after_return and text.startswith("\n"):
                text = text[1:]
            if text:
                after_return = text.endswith("\r")
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            if text:
                chunks.append(text)
                pending += text
                *lines, pending = pending.split("\n")
                for line in lines:
                    progress_callback = self._report_progress(line, progress_callback)
            if not data:
                break
        if pending:
            self._report_progress(pending, progress_callback)

    def _report_progress(
        self, text: str, callback: Callable[[int, str], None] | None
    ) -> Callable[[int, str], None] | None:
        """Log and forward one progress line; a failing callback is dropped, not retried."""
        progress = self._parse_progress(text)
        if not progress:
            return callback
        percent, label = progress
        logger.debug("G3MTool progress: %s %d%%", label, percent)
        logged = self.__dict__.setdefault("_last_logged_percent", {})
        if percent % 25 == 0 and percent != logged.get(label):
            logged[label] = percent
            logger.info("G3MTool progress: %s %d%%", label, percent)
        if callback is None:
            return None
        try:
            callback(percent, label)
        except Exception:
            logger.exception("G3MTool progress callback failed")
            return None
        return callback

    def _cancel_requested(self) -> bool:
        if self.is_cancelled is None:
            return False
        try:
            return bool(self.is_cancelled())
        except Exception:
            # A broken callback must not leave the tool running with its files open.
            logger.warning("G3MToolManager: cancel check failed; stopping the tool", exc_info=True)
            return True

    def _run(
        self,
        cmd: list[str],
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        cmd = [str(c) for c in cmd if c is not None]
        logger.info(f"G3MTool command: {' '.join(cmd)}")
        startupinfo = None
        creationflags = 0
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                stdin=subprocess.DEVNULL,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
            with self._active_processes_lock:
                self._active_processes.append(process)
            background_operations.register_process(
                process,
                cancel=lambda process=process: (
                    _terminate_tree(process) if process.poll() is None else None
                ),
                owner=self,
            )
            stdout_chunks: list[str] = []
            stderr_chunks: list[str] = []
            stdout_thread = threading.Thread(
                target=self._stream_output,
                args=(process.stdout, stdout_chunks, progress_callback),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=self._stream_output,
                args=(process.stderr, stderr_chunks),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()
            try:
                cancelled_at = None
                while True:
                    try:
                        process.wait(timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        if cancelled_at is None:
                            if self._cancel_requested():
                                cancelled_at = time.monotonic()
                                _terminate_tree(process)
                        elif time.monotonic() - cancelled_at > 5:
                            process.kill()
                returncode = process.returncode
            finally:
                stdout_thread.join()
                stderr_thread.join()
                stdout = "".join(stdout_chunks)
                stderr = "".join(stderr_chunks)
                with self._active_processes_lock:
                    if process in self._active_processes:
                        self._active_processes.remove(process)
                background_operations.release_process(process)
            logger.info(f"G3MTool completed with return code {returncode}")
            stdout_text = stdout.strip()
            stderr_text = stderr.strip()
            stdout_preview = bounded_output_preview(stdout_text)
            stderr_preview = bounded_output_preview(stderr_text)
            if returncode != 0:
                if stdout_text:
                    logger.info("G3MTool stdout: %s", stdout_preview)
                if stderr_text:
                    logger.info("G3MTool stderr: %s", stderr_preview)
            else:
                if stdout_text:
                    logger.debug("G3MTool stdout: %s", stdout_preview)
                if stderr_text:
                    logger.debug("G3MTool stderr (non-fatal): %s", stderr_preview)
            return (returncode, stdout, stderr)
        except Exception as e:
            friendly_error = format_external_process_error(
                e, command=cmd, target_path=cmd[0] if cmd else ""
            )
            logger.error(
                "Error executing G3MTool: %s | raw=%s",
                friendly_error,
                e,
                exc_info=True,
            )
            return (-1, "", friendly_error)
