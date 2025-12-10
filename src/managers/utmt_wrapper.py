from typing import Optional, Tuple, List, Dict
from managers.utmtcli_manager import UTMTCLIManager
from utils.patching_logger import get_patching_logger


class UtmtWrapper:

    def __init__(self, patching_logger=None):
        self.utmtcli = UTMTCLIManager()
        self.patching_logger = patching_logger or get_patching_logger()

    def is_available(self) -> bool:
        return self.utmtcli.is_available()

    def get_platform(self) -> str:
        return self.utmtcli.get_platform()

    def get_script_path(self, script_name: str) -> Optional[str]:
        return self.utmtcli.get_script_path(script_name)

    def execute_script(self, data_win_path: str, script_name: str, output_path: Optional[str] = None, cwd: Optional[str] = None, env: Optional[Dict] = None) -> Tuple[int, str, str]:
        import os
        if output_path is None:
            output_path = data_win_path
        if env is None:
            env = {}
        else:
            env = env.copy()
        if 'DELTAHUB_ROOT' not in env:
            from utils.path_utils import get_launcher_dir
            launcher_dir = get_launcher_dir()
            if os.path.exists(os.path.join(launcher_dir, 'output')):
                env['DELTAHUB_ROOT'] = launcher_dir
            else:
                parent_dir = os.path.dirname(launcher_dir)
                if os.path.exists(os.path.join(parent_dir, 'output')):
                    env['DELTAHUB_ROOT'] = parent_dir
                else:
                    env['DELTAHUB_ROOT'] = launcher_dir
        self.patching_logger.info(f'[UTMT] Executing script: {script_name}')
        returncode, stdout, stderr = self.utmtcli.execute_with_scripts(data_win_path, [script_name], output_path=output_path, cwd=cwd, env=env)
        if returncode != 0:
            error_msg = stderr[:300] if len(stderr) > 300 else stderr
            self.patching_logger.warning(f'[UTMT] Script {script_name} failed: {error_msg}')
        return (returncode, stdout, stderr)

    def execute_scripts(self, data_win_path: str, script_names: List[str], output_path: Optional[str] = None, cwd: Optional[str] = None, env: Optional[Dict] = None) -> Tuple[int, str, str]:
        if output_path is None:
            output_path = data_win_path
        if env is None:
            env = {}
        else:
            env = env.copy()
        if 'DELTAHUB_ROOT' not in env:
            from utils.path_utils import get_launcher_dir
            launcher_dir = get_launcher_dir()
            import os
            if os.path.exists(os.path.join(launcher_dir, 'output')):
                env['DELTAHUB_ROOT'] = launcher_dir
            else:
                parent_dir = os.path.dirname(launcher_dir)
                if os.path.exists(os.path.join(parent_dir, 'output')):
                    env['DELTAHUB_ROOT'] = parent_dir
                else:
                    env['DELTAHUB_ROOT'] = launcher_dir
        self.patching_logger.info(f"[UTMT] Executing scripts: {', '.join(script_names)} on {data_win_path}")
        returncode, stdout, stderr = self.utmtcli.execute_with_scripts(data_win_path, script_names, output_path=output_path, cwd=cwd, env=env)
        if returncode != 0:
            error_msg = stderr[:300] if len(stderr) > 300 else stderr
            self.patching_logger.warning(f"[UTMT] Scripts {', '.join(script_names)} failed: {error_msg}")
        else:
            self.patching_logger.debug(f"[UTMT] Scripts {', '.join(script_names)} completed successfully")
        return (returncode, stdout, stderr)

    def merge_assets(self, data_win_path: str, mod_source_dir: str) -> bool:
        success = True
        script_path = self.get_script_path('ImportGraphics')
        if script_path:
            returncode, _, stderr = self.execute_script(data_win_path, 'ImportGraphics', cwd=mod_source_dir)
            if returncode != 0:
                self.patching_logger.warning(f'[UTMT] ImportGraphics failed: {stderr[:200]}')
                success = False
        script_path = self.get_script_path('ImportGML')
        if script_path:
            returncode, _, stderr = self.execute_script(data_win_path, 'ImportGML', cwd=mod_source_dir)
            if returncode != 0:
                self.patching_logger.warning(f'[UTMT] ImportGML failed: {stderr[:200]}')
                success = False
        return success
