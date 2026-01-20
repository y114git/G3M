import os
import platform
import subprocess
import logging
from typing import Optional
from utils.path_utils import resource_path


class UTMTCLIManager:

    def __init__(self):
        self.platform = self._detect_platform()
        self.utmtcli_path = None
        self.utmtcli_exe = None
        self._active_processes_ref = None
        self._initialize_paths()

    def _detect_platform(self) -> str:
        system = platform.system()
        if system == 'Windows':
            return 'windows'
        elif system == 'Darwin':
            return 'macos'
        else:
            return 'linux'

    def _initialize_paths(self) -> None:
        base_path = resource_path(f'assets/bin/utmtcli_{self.platform}')
        logging.info(f'Looking for UTMTCLI at: {base_path}')
        if not os.path.exists(base_path):
            logging.warning(f'UTMTCLI not found at {base_path}')
            return
        logging.info(f'UTMTCLI found at: {base_path}')
        self.utmtcli_path = base_path
        if self.platform == 'windows':
            exe_path = os.path.join(base_path, 'UndertaleModCli.exe')
            if os.path.exists(exe_path):
                self.utmtcli_exe = exe_path
                logging.info(f'Found UTMTCLI executable: {exe_path}')
            else:
                logging.warning(f'UndertaleModCli.exe not found in {base_path}')
                return
        else:
            dll_path = os.path.join(base_path, 'UndertaleModCli.dll')
            if os.path.exists(dll_path):
                self.utmtcli_exe = dll_path
                logging.info(f'Found UTMTCLI executable: {dll_path}')
            else:
                logging.warning(f'UndertaleModCli.dll not found in {base_path}')
                return

    def is_available(self) -> bool:
        return self.utmtcli_path is not None and self.utmtcli_exe is not None

    def set_active_processes_list(self, proc_list):
        self._active_processes_ref = proc_list

    def get_script_path(self, script_name: str) -> Optional[str]:
        scripts_path = resource_path('assets/scripts')
        if not script_name.endswith('.csx'):
            script_name = f'{script_name}.csx'
        script_path = os.path.join(scripts_path, script_name)
        if os.path.exists(script_path):
            return script_path
        logging.warning(f'Script {script_name} not found at {script_path}')
        return None

    def execute_command(self, args: list, cwd: Optional[str] = None, timeout: Optional[int] = None, env: Optional[dict] = None) -> tuple[int, str, str]:
        if not self.is_available():
            logging.error('UTMTCLI is not available for command execution')
            raise RuntimeError('UTMTCLI is not available')
        if timeout is None:
            timeout = 600
        if self.platform == 'windows':
            command = [self.utmtcli_exe] + args
        else:
            command = ['dotnet', self.utmtcli_exe] + args
        command = [str(cmd) for cmd in command if cmd is not None]
        logging.info(f"Executing UTMTCLI command: {' '.join(command)} (cwd={cwd}, timeout={timeout}s)")
        try:
            startupinfo = None
            creationflags = 0
            if platform.system() == 'Windows':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW
            exec_env = os.environ.copy()
            if env:
                exec_env.update(env)
            exec_env['DOTNET_CLI_TELEMETRY_OPTOUT'] = '1'
            exec_env['DOTNET_SKIP_FIRST_TIME_EXPERIENCE'] = '1'
            exec_env['DOTNET_NOLOGO'] = '1'
            process = None
            stdout = ''
            stderr = ''
            returncode = -1
            try:
                process = subprocess.Popen(command, cwd=cwd, env=exec_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL, startupinfo=startupinfo, creationflags=creationflags)
                if self._active_processes_ref is not None:
                    self._active_processes_ref.append(process)
                try:
                    stdout, stderr = process.communicate(timeout=timeout)
                    returncode = process.returncode
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                    returncode = -1
                    logging.warning(f"UTMTCLI command timed out: {' '.join(command)}")
                finally:
                    if process and self._active_processes_ref is not None and (process in self._active_processes_ref):
                        self._active_processes_ref.remove(process)
                logging.info(f'UTMTCLI command completed with return code {returncode}')
                if returncode != 0:
                    stderr_preview = stderr[:500] if stderr else ''
                    if 'CompilationErrorException' in stderr_preview or 'CS8098' in stderr_preview or '#load' in stderr_preview:
                        logging.debug(f'UTMTCLI script compilation issue (may be non-critical): {stderr_preview}')
                    else:
                        logging.warning(f'UTMTCLI command failed: {stderr_preview}')
                return (returncode, stdout, stderr)
            except Exception as _:
                if process and self._active_processes_ref is not None and (process in self._active_processes_ref):
                    self._active_processes_ref.remove(process)
                if process:
                    try:
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                    except Exception:
                        pass
                raise
        except Exception as e:
            logging.error(f'Error executing UTMTCLI command: {e}', exc_info=True)
            return (-1, '', str(e))

    def execute_with_scripts(self, data_win_path: str, scripts: list[str], output_path: Optional[str] = None, additional_args: Optional[list[str]] = None, cwd: Optional[str] = None, env: Optional[dict] = None) -> tuple[int, str, str]:
        args = ['load', data_win_path]
        for script in scripts:
            script_path = self.get_script_path(script)
            if not script_path:
                if os.path.exists(script):
                    script_path = script
                else:
                    raise ValueError(f'Script not found: {script}')
            args.extend(['--scripts', script_path])
        if output_path:
            args.extend(['--output', output_path])
        args.append('--verbose')
        if additional_args:
            args.extend(additional_args)
        return self.execute_command(args, cwd=cwd, env=env)

    def get_utmtcli_path(self) -> Optional[str]:
        return self.utmtcli_path

    def get_platform(self) -> str:
        return self.platform
