"""Wrapper for UndertaleModTool (UTMT) operations."""
import os
from typing import Optional, Dict
from adapters.utmtcli_adapter import UTMTCLIManager
from services.patching_log_service import get_patching_logger


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

    def _prepare_env(self, env: Optional[Dict]) -> Dict:
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
        return env

    def _run_scripts(self, data_win_path, script_names, output_path=None, cwd=None, env=None):
        output_path = output_path or data_win_path
        env = self._prepare_env(env)
        label = ', '.join(script_names)
        self.patching_logger.info(f'[UTMT] Executing: {label}')
        rc, stdout, stderr = self.utmtcli.execute_with_scripts(data_win_path, script_names, output_path=output_path, cwd=cwd, env=env)
        if rc != 0:
            self.patching_logger.warning(f'[UTMT] {label} failed: {stderr[:300]}')
        return (rc, stdout, stderr)

    def execute_script(self, data_win_path, script_name, output_path=None, cwd=None, env=None):
        return self._run_scripts(data_win_path, [script_name], output_path, cwd, env)

    def execute_scripts(self, data_win_path, script_names, output_path=None, cwd=None, env=None):
        return self._run_scripts(data_win_path, script_names, output_path, cwd, env)

    def set_active_processes_list(self, proc_list):
        self.utmtcli.set_active_processes_list(proc_list)

    _MERGE_SCRIPTS = ['ImportSprites', 'ImportBackgrounds', 'ImportShaders', 'ImportFonts', 'ImportSounds', 'ImportAudioGroups', 'ImportPaths', 'ImportRooms', 'ImportGameObjects', 'ImportTimelines', 'ImportExtensions', 'ImportTilesets', 'ImportCodeEntries']

    def merge_assets(self, data_win_path: str, mod_source_dir: str) -> bool:
        success = True
        for name in self._MERGE_SCRIPTS:
            if self.get_script_path(name):
                rc, _, stderr = self.execute_script(data_win_path, name, cwd=mod_source_dir)
                if rc != 0:
                    self.patching_logger.warning(f'[UTMT] {name} failed: {stderr[:200]}')
                    success = False
        return success
