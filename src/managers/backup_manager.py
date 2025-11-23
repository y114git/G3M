import os
import shutil
import json
import logging
from typing import Dict, Optional
from utils.patching_logger import get_patching_logger
from utils.file_utils import safe_move, safe_remove


class BackupManager:

    def __init__(self, backup_dir: str, patching_logger=None):
        self.backup_dir = backup_dir
        self.patching_logger = patching_logger or get_patching_logger()
        self.original_files: Dict[int, Dict[str, Optional[str]]] = {}
        self.added_files: Dict[int, Dict[str, bool]] = {}
        self._session_manifest_path: Optional[str] = None
        if backup_dir:
            os.makedirs(backup_dir, exist_ok=True)

    def backup_file(self, chapter_id: int, file_path: str) -> bool:
        if chapter_id not in self.original_files:
            self.original_files[chapter_id] = {}
        if file_path in self.original_files[chapter_id]:
            return True
        if not os.path.exists(file_path):
            self.original_files[chapter_id][file_path] = None
            self.patching_logger.debug(f'[BACKUP] File does not exist, will be removed on restore: {file_path} (chapter {chapter_id})')
            return True
        try:
            backup_filename = os.path.basename(file_path)
            backup_path = os.path.join(self.backup_dir, f'chapter_{chapter_id}_{backup_filename}')
            counter = 1
            while os.path.exists(backup_path):
                name, ext = os.path.splitext(backup_filename)
                backup_path = os.path.join(self.backup_dir, f'chapter_{chapter_id}_{name}_{counter}{ext}')
                counter += 1
            shutil.copy2(file_path, backup_path)
            self.original_files[chapter_id][file_path] = backup_path
            self.patching_logger.info(f'[BACKUP] Backed up file: {file_path} -> {backup_path} (chapter {chapter_id})')
            return True
        except Exception as e:
            self.patching_logger.error(f'[BACKUP] Failed to backup file {file_path} (chapter {chapter_id}): {e}', exc_info=True)
            return False

    def backup_directory_atomic(self, chapter_id: int, dir_path: str) -> Optional[str]:
        if not os.path.exists(dir_path) or not os.path.isdir(dir_path):
            self.patching_logger.warning(f'[BACKUP] Directory does not exist or is not a directory: {dir_path}')
            return None
        try:
            dir_name = os.path.basename(dir_path.rstrip(os.sep))
            backup_dir_name = f'chapter_{chapter_id}_{dir_name}'
            backup_path = os.path.join(self.backup_dir, backup_dir_name)
            counter = 1
            while os.path.exists(backup_path):
                backup_path = os.path.join(self.backup_dir, f'{backup_dir_name}_{counter}')
                counter += 1
            if safe_move(dir_path, backup_path):
                self.patching_logger.info(f'[BACKUP] Atomically backed up directory: {dir_path} -> {backup_path} (chapter {chapter_id})')
                return backup_path
            else:
                self.patching_logger.error(f'[BACKUP] Failed to atomically backup directory {dir_path} (chapter {chapter_id})')
                return None
        except Exception as e:
            self.patching_logger.error(f'[BACKUP] Failed to backup directory {dir_path} (chapter {chapter_id}): {e}', exc_info=True)
            return None

    def mark_file_added(self, chapter_id: int, file_path: str):
        if chapter_id not in self.added_files:
            self.added_files[chapter_id] = {}
        self.added_files[chapter_id][file_path] = True

    def save_backups_to_manifest(self, manifest_path: str):
        self._session_manifest_path = manifest_path
        try:
            manifest_data = {'original_files': {}, 'added_files': {}}
            for chapter_id, files_dict in self.original_files.items():
                manifest_data['original_files'][str(chapter_id)] = files_dict
            for chapter_id, files_dict in self.added_files.items():
                manifest_data['added_files'][str(chapter_id)] = list(files_dict.keys())
            os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest_data, f, indent=2, ensure_ascii=False)
            self.patching_logger.info(f'[BACKUP] Saved backup manifest to {manifest_path}')
        except Exception as e:
            self.patching_logger.warning(f'[BACKUP] Failed to save backup manifest: {e}')

    def restore_backups(self, chapter_id: int) -> None:
        if chapter_id not in self.original_files:
            return
        self.patching_logger.info(f'[RESTORE] Restoring backups for chapter {chapter_id}')
        for file_path, backup_path in self.original_files[chapter_id].items():
            if backup_path is None:
                if os.path.exists(file_path):
                    if safe_remove(file_path):
                        self.patching_logger.info(f'[RESTORE] Removed file created by mod: {file_path} (chapter {chapter_id})')
                    else:
                        self.patching_logger.error(f'[RESTORE] Failed to remove file created by mod {file_path} (chapter {chapter_id})')
                else:
                    self.patching_logger.debug(f'[RESTORE] File created by mod already removed: {file_path} (chapter {chapter_id})')
                continue
            if not os.path.exists(backup_path):
                self.patching_logger.warning(f'[RESTORE] Backup file not found: {backup_path} (original: {file_path}, chapter {chapter_id})')
                continue
            try:
                target_dir = os.path.dirname(file_path)
                if target_dir and (not os.path.exists(target_dir)):
                    os.makedirs(target_dir, exist_ok=True)
                    self.patching_logger.debug(f'[RESTORE] Created target directory: {target_dir}')
                shutil.copy2(backup_path, file_path)
                self.patching_logger.info(f'[RESTORE] Restored backup: {file_path} <- {backup_path} (chapter {chapter_id})')
            except Exception as e:
                self.patching_logger.error(f'[RESTORE] Failed to restore backup {backup_path} to {file_path} (chapter {chapter_id}): {e}', exc_info=True)

    def restore_all_backups(self) -> bool:
        if not self.original_files:
            return True
        try:
            for chapter_id in list(self.original_files.keys()):
                self.restore_backups(chapter_id)
            return True
        except Exception as e:
            self.patching_logger.error(f'[RESTORE] Critical error during restore_all_backups: {e}', exc_info=True)
            return False

    def clear_backups(self):
        self.original_files.clear()
        self.added_files.clear()
        self._session_manifest_path = None
