"""G3MTool CLI execution and management."""

import logging
import os
import platform
import subprocess

from utils.path_utils import resource_path


class G3MToolManager:
    """Manages G3MTool CLI execution for patching operations."""

    def __init__(self) -> None:
        self.platform = {"Windows": "windows", "Darwin": "macos"}.get(
            platform.system(), "linux"
        )
        self.g3mtool_path = self._find_executable()
        self._active_processes: list[subprocess.Popen] = []

    def _find_executable(self) -> str | None:
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
            logging.info(f"Found G3MTool: {exe_path}")
            return exe_path
        logging.warning(f"G3MTool not found at {exe_path}")
        return None

    def is_available(self) -> bool:
        return self.g3mtool_path is not None

    def merge_patches(
        self,
        original_data_win: str,
        mod_patches: list[str],
        output_path: str,
        report_path: str | None = None,
        log_path: str | None = None,
        merge_code: bool = False,
        merge_properties: bool = False,
    ) -> tuple[int, str, str]:
        """Call g3mtool patch merge <original> <patch1> <patch2> ... --apply <output> [--report <path>] [--log <path>]"""
        cmd = [self.g3mtool_path, "patch", "merge", original_data_win, *mod_patches]
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
        return self._run(cmd)

    def apply_patch(
        self,
        original_data_win: str,
        patch_path: str,
        output_path: str,
        log_path: str | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool patch apply <original> <patch> <output> [--log <path>]"""
        cmd = [
            self.g3mtool_path,
            "patch",
            "apply",
            original_data_win,
            patch_path,
            output_path,
        ]
        if log_path:
            cmd.extend(["--log", log_path])
        return self._run(cmd)

    def xpatch_apply(
        self,
        original_file: str,
        patch_path: str,
        output_path: str,
    ) -> tuple[int, str, str]:
        """Call g3mtool xpatch apply <original> <patch> <output> for xdelta/vcdiff patches."""
        cmd = [
            self.g3mtool_path,
            "xpatch",
            "apply",
            original_file,
            patch_path,
            output_path,
        ]
        return self._run(cmd)

    def xpatch_create(
        self,
        original_file: str,
        modified_file: str,
        output_path: str,
    ) -> tuple[int, str, str]:
        """Call g3mtool xpatch create <original> <modified> <output>."""
        cmd = [
            self.g3mtool_path,
            "xpatch",
            "create",
            original_file,
            modified_file,
            output_path,
        ]
        return self._run(cmd)

    def patch_create(
        self,
        original_file: str,
        modified_file: str,
        output_path: str,
    ) -> tuple[int, str, str]:
        """Call g3mtool patch create <original> <modified> [output]."""
        if not self.g3mtool_path:
            return (-1, "", "G3MTool is not available")
        cmd = [
            self.g3mtool_path,
            "patch",
            "create",
            original_file,
            modified_file,
            output_path,
        ]
        return self._run(cmd)

    def info(
        self,
        target: str,
        verbose: bool = False,
    ) -> tuple[int, str, str]:
        """Call g3mtool info <target> [--verbose]."""
        if not self.g3mtool_path:
            return (-1, "", "G3MTool is not available")
        cmd = [self.g3mtool_path, "info", target]
        if verbose:
            cmd.append("--verbose")
        return self._run(cmd)

    def diff(
        self,
        file1: str,
        file2: str,
        output_dir: str | None = None,
    ) -> tuple[int, str, str]:
        """Call g3mtool diff <file1> <file2> [output-dir]."""
        if not self.g3mtool_path:
            return (-1, "", "G3MTool is not available")
        cmd = [self.g3mtool_path, "diff", file1, file2]
        if output_dir:
            cmd.append(output_dir)
        return self._run(cmd)

    def cancel_active_processes(self):
        for process in list(self._active_processes):
            try:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            except Exception as e:
                logging.debug(
                    f"G3MToolManager.cancel_active_processes: failed to stop process: {e}",
                    exc_info=True,
                )
        self._active_processes.clear()

    def _run(self, cmd: list[str], timeout: int = 600) -> tuple[int, str, str]:
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
                stdin=subprocess.DEVNULL,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
            self._active_processes.append(process)
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                returncode = process.returncode
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                returncode = -1
                logging.warning(f"G3MTool command timed out after {timeout}s")
            finally:
                if process in self._active_processes:
                    self._active_processes.remove(process)
            logging.info(f"G3MTool completed with return code {returncode}")
            if returncode != 0:
                logging.warning(f"G3MTool stderr: {stderr[:500]}")
            return (returncode, stdout, stderr)
        except Exception as e:
            logging.error(f"Error executing G3MTool: {e}", exc_info=True)
            return (-1, "", str(e))
