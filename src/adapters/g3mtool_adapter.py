"""G3MTool CLI execution and management."""

import json
import logging
import os
import platform
import re
import subprocess
import threading
from collections.abc import Callable

from utils.path_utils import get_g3mtool_cache_dir, get_user_data_root, resource_path


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

    def _get_local_config(self) -> dict:
        local_config = getattr(self.app_state, "local_config", None)
        if isinstance(local_config, dict):
            return local_config
        try:
            config_path = os.path.join(get_user_data_root(), "settings", "settings.json")
            if os.path.isfile(config_path):
                with open(config_path, encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            logging.debug("Failed to load local config for G3MToolManager: %s", e)
        return {}

    def _get_configured_g3mtool_path(self) -> str | None:
        path = str(self._get_local_config().get("custom_g3mtool_path", "") or "").strip()
        return path or None

    def _get_configured_xdelta_path(self) -> str | None:
        path = str(self._get_local_config().get("custom_xdelta_path", "") or "").strip()
        return path or None

    def _find_executable(self) -> str | None:
        custom_path = self._get_configured_g3mtool_path()
        if custom_path:
            if os.path.exists(custom_path):
                return custom_path
            logging.warning(
                f"Custom G3MTool path not found, falling back to bundled: {custom_path}"
            )
        if self.platform in self._cached_executable_paths:
            return self._cached_executable_paths[self.platform]
        base_path = resource_path(f"assets/bin/g3mtool_{self.platform}")
        exe_name = "G3MTool.exe" if self.platform == "windows" else "G3MTool"
        exe_path = os.path.join(base_path, exe_name)
        if os.path.exists(exe_path):
            if self.platform != "windows":
                try:
                    os.chmod(exe_path, 0o700)
                except Exception as e:
                    logging.warning(
                        f"Could not set executable permission on {exe_path}: {e}"
                    )
            if exe_path not in self._logged_executable_paths:
                logging.info(f"Found G3MTool: {exe_path}")
                self._logged_executable_paths.add(exe_path)
            self._cached_executable_paths[self.platform] = exe_path
            return exe_path
        logging.warning(f"G3MTool not found at {exe_path}")
        self._cached_executable_paths[self.platform] = None
        return None

    def refresh_executable(self) -> str | None:
        self.g3mtool_path = self._find_executable()
        return self.g3mtool_path

    def is_available(self) -> bool:
        return self.refresh_executable() is not None

    def get_version(self) -> str | None:
        """Return the bundled G3MTool version string."""
        g3mtool_path = self.refresh_executable()
        if not g3mtool_path:
            return None
        returncode, stdout, stderr = self._run([g3mtool_path, "--version"])
        if returncode != 0:
            if stderr:
                logging.debug("G3MTool version command failed: %s", stderr.strip())
            return None
        version = (stdout or "").strip().splitlines()
        return version[0].strip() if version else None

    @staticmethod
    def _unavailable_result() -> tuple[int, str, str]:
        return (-1, "", "G3MTool is not available")

    @staticmethod
    def _supports_cache(args: list[str]) -> bool:
        if not args:
            return False
        if args[0] in {"info", "diff"}:
            return True
        return len(args) >= 2 and args[0] == "patch" and args[1] in {
            "apply",
            "create",
            "merge",
            "validate",
        }

    def _run_command(
        self,
        args: list[str],
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        g3mtool_path = self.refresh_executable()
        if not g3mtool_path:
            return self._unavailable_result()
        full_args = [*args]
        if self._supports_cache(full_args):
            cache_dir = get_g3mtool_cache_dir()
            os.makedirs(cache_dir, exist_ok=True)
            full_args.extend(["--cache", cache_dir])
        xdelta_path = self._get_configured_xdelta_path()
        if xdelta_path:
            full_args.extend(["--xdelta-path", xdelta_path])
        return self._run(
            [g3mtool_path, *full_args],
            progress_callback=progress_callback,
        )

    def merge_patches(
        self,
        original_data_win: str,
        mod_patches: list[str],
        output_path: str,
        report_path: str | None = None,
        log_path: str | None = None,
        merge_code: bool = False,
        merge_properties: bool = False,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool patch merge <original> <patch1> <patch2> ... --apply <output> [--report <path>] [--log <path>]"""
        cmd = ["patch", "merge", original_data_win, *mod_patches]
        cmd.extend(["--apply", output_path])
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
        cmd = [
            "xpatch",
            "apply",
            original_file,
            patch_path,
            output_path,
        ]
        return self._run_command(
            cmd,
            progress_callback=progress_callback,
        )

    def xpatch_create(
        self,
        original_file: str,
        modified_file: str,
        output_path: str,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool xpatch create <original> <modified> <output>."""
        cmd = [
            "xpatch",
            "create",
            original_file,
            modified_file,
            output_path,
        ]
        return self._run_command(
            cmd,
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

    def validate_patch(
        self,
        patch_path: str,
        data_file: str | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool patch validate <patch> [--data <file>]."""
        cmd = ["patch", "validate", patch_path]
        if data_file:
            cmd.extend(["--data", data_file])
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
    ) -> tuple[int, str, str]:
        """Call g3mtool diff <file1> <file2> [output-dir]."""
        cmd = ["diff", file1, file2]
        if output_dir:
            cmd.append(output_dir)
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
        if args:
            cmd.extend(str(arg) for arg in args)
        if data_file:
            cmd.extend(["--data", data_file])
        if output_path:
            cmd.extend(["--output", output_path])
        if input_path:
            cmd.extend(["--input", input_path])
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
                    process.kill()
                    process.wait()
            except Exception as e:
                logging.debug(
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
        progress_buffer = ""
        while True:
            char = stream.read(1)
            if not char:
                break
            chunks.append(char)
            if not progress_callback:
                continue
            if char in "\r\n":
                progress = self._parse_progress(progress_buffer)
                if progress:
                    progress_callback(*progress)
                progress_buffer = ""
            else:
                progress_buffer += char
        progress = self._parse_progress(progress_buffer)
        if progress:
            progress_callback(*progress)

    def _run(
        self,
        cmd: list[str],
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> tuple[int, str, str]:
        cmd = [str(c) for c in cmd if c is not None]
        logging.info(f"G3MTool command: {' '.join(cmd)}")
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
                process.wait()
                returncode = process.returncode
            finally:
                stdout_thread.join()
                stderr_thread.join()
                stdout = "".join(stdout_chunks)
                stderr = "".join(stderr_chunks)
                with self._active_processes_lock:
                    if process in self._active_processes:
                        self._active_processes.remove(process)
            logging.info(f"G3MTool completed with return code {returncode}")
            stderr_text = stderr.strip()
            if returncode != 0:
                if stderr_text:
                    logging.warning(f"G3MTool stderr: {stderr_text[:500]}")
            elif stderr_text:
                logging.debug(f"G3MTool stderr (non-fatal): {stderr_text[:500]}")
            return (returncode, stdout, stderr)
        except Exception as e:
            logging.error(f"Error executing G3MTool: {e}", exc_info=True)
            return (-1, "", str(e))
