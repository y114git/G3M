"""Xdelta patching operations for applying .xdelta/.vcdiff patches."""
import os
import platform
import subprocess
from utils.file_utils import safe_move, safe_remove
from services.localization_service import tr
from config.patching_config import XDELTA_ERROR_MAP, XDELTA_EXCEPTION_ERROR_KEYS


def classify_xdelta_error(error_msg: str) -> str:
    """Classify an xdelta error message into a category."""
    lower = error_msg.lower()
    if 'checksum mismatch' in lower or 'XD3_INVALID_INPUT' in error_msg:
        return 'checksum'
    if any(k in lower for k in ('no such file', 'cannot find', 'file not found')):
        return 'not_found'
    if any(k in lower for k in ('permission denied', 'access denied')):
        return 'permission'
    if 'XD3_INTERNAL' in error_msg or any(k in lower for k in ('corrupt', 'invalid')):
        return 'corrupted'
    if any(k in lower for k in ('io error', 'input/output', 'disk')):
        return 'io'
    return 'unknown'


def run_xdelta_process(patcher, input_file: str, patch_path: str, output_file: str) -> tuple:
    cmd = [patcher.xdelta_path, '-d', '-s', input_file, patch_path, output_file]
    startupinfo = None
    creationflags = 0
    if platform.system() == 'Windows':
        import subprocess as sp
        startupinfo = sp.STARTUPINFO()
        startupinfo.dwFlags |= sp.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = sp.SW_HIDE
        creationflags = sp.CREATE_NO_WINDOW
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL, startupinfo=startupinfo, creationflags=creationflags)
    patcher._active_processes.append(process)
    try:
        stdout, stderr = process.communicate(timeout=300)
        returncode = process.returncode
    finally:
        if process in patcher._active_processes:
            patcher._active_processes.remove(process)
    return returncode, stdout, stderr


def ensure_xdelta_executable(patcher) -> bool:
    if not patcher.xdelta_path or not os.path.exists(patcher.xdelta_path):
        return False
    import stat
    if platform.system() != 'Windows':
        try:
            file_stat = os.stat(patcher.xdelta_path)
            if not bool(file_stat.st_mode & stat.S_IEXEC):
                os.chmod(patcher.xdelta_path, 493)
        except Exception as e:
            patcher.patching_logger.error(f'Failed to check/set xdelta permissions: {e}', exc_info=True)
    return True


def handle_xdelta_error(patcher, error_type: str, patch_name: str, patch_path: str, data_win_path: str, error_msg: str) -> bool:
    error_short = error_msg[:200]
    warn_type, warn_key, err_key, can_continue = XDELTA_ERROR_MAP.get(error_type, XDELTA_ERROR_MAP['unknown'])
    patcher.patching_logger.error(f'[XDELTA] Patch "{patch_name}" failed ({error_type}): {error_msg[:500]}')
    if can_continue and warn_type:
        warning_msg = tr(warn_key, patch_name=patch_name, patch_path=patch_path, data_win_path=data_win_path, error=error_short)
        if not patcher._show_patching_warning(warn_type, tr('dialogs.patching_warning.title'), warning_msg):
            patcher.patching_logger.info(f'[PATCHING_WARNING] User cancelled patching: {patch_name}')
            patcher.status_update.emit(tr(err_key, patch=patch_name, error=error_short), 'error')
            return False
        patcher.patching_logger.info(f'[PATCHING_WARNING] User chose to continue: {patch_name}')
        return True
    patcher.status_update.emit(tr(err_key, patch=patch_name, error=error_short), 'error')
    return False


def apply_xdelta_patches(patcher, data_win_path: str, data_patches: list, progress_callback=None) -> bool:
    if not ensure_xdelta_executable(patcher):
        patcher.patching_logger.error('xdelta executable not found or not available')
        patcher.status_update.emit(tr('errors.xdelta_not_found'), 'error')
        return False
    if not os.path.exists(data_win_path):
        patcher.patching_logger.error(f'Input file does not exist: {data_win_path}')
        patcher.status_update.emit(tr('errors.xdelta_patch_file_not_found', patch=os.path.basename(data_win_path) if data_win_path else 'data.win'), 'error')
        return False
    total_patches = len(data_patches)
    for idx, patch_path in enumerate(data_patches):
        if patcher._cancelled:
            return False
        patch_name = os.path.basename(patch_path)
        patcher.patching_logger.info(f'[XDELTA] Applying patch {idx + 1}/{total_patches}: {patch_name} to {os.path.basename(data_win_path)}')
        if progress_callback:
            progress_callback(idx / total_patches if total_patches > 0 else 0)
        if not os.path.exists(patch_path):
            patcher.patching_logger.error(f'Patch file does not exist: {patch_path}')
            patcher.status_update.emit(tr('errors.xdelta_patch_file_not_found', patch=patch_name), 'error')
            return False
        temp_output = None
        try:
            temp_output = data_win_path + '.tmp'
            patcher._temp_files_to_cleanup.append(temp_output)
            if not os.access(os.path.dirname(temp_output), os.W_OK):
                patcher.patching_logger.error(f'Temp directory is not writable: {os.path.dirname(temp_output)}')
                patcher.status_update.emit(tr('errors.xdelta_patch_permission_denied', patch=patch_name), 'error')
                return False
            returncode, stdout, stderr = run_xdelta_process(patcher, data_win_path, patch_path, temp_output)
            if progress_callback:
                progress_callback((idx + 1) / total_patches if total_patches > 0 else 1.0)
            if returncode != 0:
                error_msg = stderr.strip() if stderr else stdout.strip() if stdout else 'Unknown error'
                error_type = classify_xdelta_error(error_msg)
                user_continues = handle_xdelta_error(patcher, error_type, patch_name, patch_path, data_win_path, error_msg)
                if user_continues:
                    continue
                return False
            if not os.path.exists(temp_output):
                patcher.patching_logger.error(f'Temp output file was not created: {temp_output}')
                patcher.status_update.emit(tr('errors.xdelta_patch_io_error', patch=patch_name), 'error')
                return False
            if not safe_move(temp_output, data_win_path):
                raise OSError(f'Failed to move patched file from {temp_output} to {data_win_path}')
            if temp_output in patcher._temp_files_to_cleanup:
                patcher._temp_files_to_cleanup.remove(temp_output)
            patcher.patching_logger.info(f'Patch {idx + 1}/{total_patches} applied successfully')
        except subprocess.TimeoutExpired:
            patcher.patching_logger.error(f'xdelta patch timed out after 300 seconds: {patch_path}')
            patcher.status_update.emit(tr('errors.xdelta_patch_timeout_detailed', patch=patch_name), 'error')
            if temp_output and os.path.exists(temp_output):
                safe_remove(temp_output)
            return False
        except Exception as e:
            error_str = str(e)
            patcher.patching_logger.error(f'xdelta patch error: {e}', exc_info=True)
            error_type = classify_xdelta_error(error_str)
            err_key = XDELTA_EXCEPTION_ERROR_KEYS.get(error_type, 'errors.xdelta_patch_unknown_error')
            patcher.status_update.emit(tr(err_key, patch=patch_name, error=error_str[:200]), 'error')
            if temp_output and os.path.exists(temp_output):
                safe_remove(temp_output)
            return False
    patcher.patching_logger.info('All patches applied successfully')
    return True


def apply_xdelta_to_file(patcher, target_file: str, patch_path: str) -> bool:
    if not ensure_xdelta_executable(patcher):
        patcher.patching_logger.warning(f'xdelta executable not found, cannot apply patch to {os.path.basename(target_file)}')
        return False
    if not os.path.exists(target_file) or not os.path.exists(patch_path):
        patcher.patching_logger.warning(f'Target or patch file does not exist: {target_file}, {patch_path}')
        return False
    temp_output = None
    try:
        temp_output = target_file + '.tmp'
        patcher._temp_files_to_cleanup.append(temp_output)
        if not os.access(os.path.dirname(temp_output), os.W_OK):
            patcher.patching_logger.warning(f'Temp directory is not writable: {os.path.dirname(temp_output)}')
            return False
        returncode, stdout, stderr = run_xdelta_process(patcher, target_file, patch_path, temp_output)
        if returncode != 0:
            patcher.patching_logger.debug(f'Failed to apply xdelta patch to {os.path.basename(target_file)}: {stderr.strip() if stderr else "Unknown error"}')
            return False
        if not os.path.exists(temp_output):
            patcher.patching_logger.warning(f'Temp output file was not created: {temp_output}')
            return False
        if not safe_move(temp_output, target_file):
            raise OSError(f'Failed to move patched file from {temp_output} to {target_file}')
        if temp_output in patcher._temp_files_to_cleanup:
            patcher._temp_files_to_cleanup.remove(temp_output)
        patcher.patching_logger.info(f'Successfully applied xdelta patch to {os.path.basename(target_file)}')
        return True
    except Exception as e:
        patcher.patching_logger.error(f'Error applying xdelta patch to {os.path.basename(target_file)}: {e}', exc_info=True)
        if temp_output and os.path.exists(temp_output):
            safe_remove(temp_output)
        return False
