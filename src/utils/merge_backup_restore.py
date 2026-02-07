"""Backup restoration from session manifests for multi-mod merging."""
import json
import os
from typing import Optional

from services.backup_service import BackupManager
from utils.file_utils import safe_remove


def load_backup_files_from_dict(backup_service, files_dict_by_chapter: dict) -> None:
    """Populate backup_service.original_files from a {chapter_key: {path: backup_path}} dict."""
    for chapter_key, files_dict in files_dict_by_chapter.items():
        chapter_id = int(chapter_key)
        for file_path, backup_path in files_dict.items():
            if backup_path is None or backup_path == 'null':
                backup_service.original_files.setdefault(chapter_id, {})[file_path] = None
            else:
                backup_service.original_files.setdefault(chapter_id, {})[file_path] = backup_path


def cleanup_stale_manifest(session_manifest_path: Optional[str], logger, backup_dir: Optional[str] = None) -> bool:
    """Log stale backup dir and remove manifest. Returns False (for early return)."""
    if backup_dir:
        logger.debug(f'Backup directory from manifest does not exist: {backup_dir}')
    logger.debug('Backups were already restored in previous session, cleaning up manifest')
    if session_manifest_path and os.path.exists(session_manifest_path):
        if safe_remove(session_manifest_path):
            logger.debug('Removed stale session manifest')
        else:
            logger.debug('Failed to remove stale manifest')
    return False


def restore_backups_from_manifest(session_manifest_path: str, temp_merge_dir: Optional[str],
                                  cleanup_temp_dir_fn, logger) -> bool:
    """Restore backups from a session manifest file.

    Args:
        session_manifest_path: Path to the session manifest JSON.
        temp_merge_dir: Temp merge directory (for fallback backup_dir).
        cleanup_temp_dir_fn: Callable to clean up temp dir on success.
        logger: Logger instance.
    Returns:
        True if restoration succeeded, False otherwise.
    """
    try:
        with open(session_manifest_path, 'r', encoding='utf-8') as f:
            manifest_data = json.load(f)
        backup_dir = manifest_data.get('multimod_backup_dir')
        original_files_data = manifest_data.get('original_files', {})
        added_files_data = manifest_data.get('added_files', {})
        multimod_backups = manifest_data.get('multimod_backups', {})
        if original_files_data or added_files_data:
            if not backup_dir:
                if temp_merge_dir:
                    backup_dir = os.path.join(temp_merge_dir, 'backups')
            if backup_dir and os.path.exists(backup_dir):
                logger.info(f'Loading backup info from session manifest (new format): {len(original_files_data)} chapter(s) with original files, {len(added_files_data)} chapter(s) with added files')
                backup_service = BackupManager(backup_dir, patching_logger=logger)
                load_backup_files_from_dict(backup_service, original_files_data)
                modification_order_data = manifest_data.get('modification_order', {})
                for chapter_key in original_files_data:
                    if chapter_key in modification_order_data:
                        backup_service._modification_order[int(chapter_key)] = modification_order_data[chapter_key]
                for chapter_key, file_list in added_files_data.items():
                    chapter_id = int(chapter_key)
                    if not isinstance(file_list, list):
                        continue
                    for file_path in file_list:
                        backup_service.added_files.setdefault(chapter_id, {})[file_path] = True
                        if chapter_id not in backup_service.original_files or file_path not in backup_service.original_files[chapter_id]:
                            backup_service.original_files.setdefault(chapter_id, {})[file_path] = None
                result = backup_service.restore_all_backups()
            else:
                return cleanup_stale_manifest(session_manifest_path, logger, backup_dir)
        elif multimod_backups and backup_dir:
            logger.info(f'Loading backup info from session manifest (old format): {len(multimod_backups)} chapter(s)')
            if not os.path.exists(backup_dir):
                return cleanup_stale_manifest(session_manifest_path, logger, backup_dir)
            backup_service = BackupManager(backup_dir, patching_logger=logger)
            load_backup_files_from_dict(backup_service, multimod_backups)
            result = backup_service.restore_all_backups()
        else:
            logger.debug('No valid backup data found in manifest')
            return False
        if result:
            cleanup_temp_dir_fn(keep_backups=False)
            if session_manifest_path and os.path.exists(session_manifest_path):
                if safe_remove(session_manifest_path):
                    logger.debug('Removed session manifest after backup restoration')
                else:
                    logger.debug('Failed to remove session manifest')
        else:
            logger.warning('Restoration failed or incomplete - keeping temp directories for manual recovery')
        return result
    except Exception as e:
        logger.warning(f'Failed to load backups from manifest: {e}')
    return False
