"""Backup management for mod installation and restoration."""

import json
import logging
import os
import shutil

from utils.file_utils import safe_remove, safe_rmtree

logger = logging.getLogger(__name__)


class BackupManager:
    """Manages file and directory backups for safe mod operations."""

    def __init__(self, backup_dir: str, patching_logger=None) -> None:
        self.backup_dir = backup_dir
        self.patching_logger = patching_logger or logging.getLogger(__name__)
        self.original_files: dict[str, dict[str, str | None]] = {}
        self.added_files: dict[str, dict[str, bool]] = {}
        self._session_manifest_path: str | None = None
        self._modification_order: dict[str, list] = {}
        if backup_dir:
            os.makedirs(backup_dir, exist_ok=True)

    def backup_file(self, chapter_id: str, file_path: str) -> bool:
        self.original_files.setdefault(chapter_id, {})
        self._modification_order.setdefault(chapter_id, [])
        if file_path in self.original_files[chapter_id]:
            return True
        if not os.path.exists(file_path):
            self.original_files[chapter_id][file_path] = None
            self._modification_order[chapter_id].append(file_path)
            self.patching_logger.debug(
                f"[BACKUP] File does not exist, will be removed on restore: {file_path} (chapter {chapter_id})"
            )
            return True
        try:
            backup_filename = os.path.basename(file_path)
            backup_path = os.path.join(
                self.backup_dir, f"chapter_{chapter_id}_{backup_filename}"
            )
            counter = 1
            while os.path.exists(backup_path):
                name, ext = os.path.splitext(backup_filename)
                backup_path = os.path.join(
                    self.backup_dir, f"chapter_{chapter_id}_{name}_{counter}{ext}"
                )
                counter += 1
            shutil.copyfile(file_path, backup_path)
            self.original_files[chapter_id][file_path] = backup_path
            self._modification_order[chapter_id].append(file_path)
            self.patching_logger.info(
                f"[BACKUP] Backed up file: {file_path} -> {backup_path} (chapter {chapter_id})"
            )
            return True
        except Exception as e:
            self.patching_logger.error(
                f"[BACKUP] Failed to backup file {file_path} (chapter {chapter_id}): {e}",
                exc_info=True,
            )
            return False

    def mark_file_added(self, chapter_id: str, file_path: str):
        self.added_files.setdefault(chapter_id, {})[file_path] = True

    def save_backups_to_manifest(self, manifest_path: str):
        self._session_manifest_path = manifest_path
        try:
            manifest_data = {
                "backup_dir": self.backup_dir,
                "original_files": {},
                "added_files": {},
                "modification_order": {},
            }
            for chapter_id, files_dict in self.original_files.items():
                manifest_data["original_files"][str(chapter_id)] = files_dict
            for chapter_id, files_dict in self.added_files.items():
                manifest_data["added_files"][str(chapter_id)] = list(files_dict.keys())
            for chapter_id, file_order in self._modification_order.items():
                manifest_data["modification_order"][str(chapter_id)] = file_order
            os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, indent=2, ensure_ascii=False)
            self.patching_logger.info(
                f"[BACKUP] Saved backup manifest to {manifest_path}"
            )
        except Exception as e:
            self.patching_logger.warning(
                f"[BACKUP] Failed to save backup manifest: {e}"
            )

    @classmethod
    def load_from_manifest(
        cls, manifest_path: str, patching_logger=None
    ) -> BackupManager:
        """Reconstruct a BackupManager from a previously saved manifest (for crash recovery)."""
        logger = patching_logger or logging.getLogger(__name__)
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
        backup_dir = data.get("backup_dir", "")
        mgr = cls(backup_dir, patching_logger=logger)
        mgr._session_manifest_path = manifest_path
        for chapter_id, files_dict in data.get("original_files", {}).items():
            mgr.original_files[chapter_id] = files_dict
        for chapter_id, file_list in data.get("added_files", {}).items():
            mgr.added_files[chapter_id] = dict.fromkeys(file_list, True)
        for chapter_id, file_order in data.get("modification_order", {}).items():
            mgr._modification_order[chapter_id] = file_order
        logger.info(
            f"[BACKUP] Loaded backup manifest from {manifest_path} "
            f"({sum(len(v) for v in mgr.original_files.values())} files tracked)"
        )
        return mgr

    def clear_backup_dir(self):
        """Remove the persistent backup directory and session manifest."""
        if self.backup_dir and os.path.isdir(self.backup_dir):
            safe_rmtree(self.backup_dir)
            self.patching_logger.info(
                f"[BACKUP] Cleared backup directory: {self.backup_dir}"
            )
        if self._session_manifest_path and os.path.isfile(self._session_manifest_path):
            safe_remove(self._session_manifest_path)
            self.patching_logger.info(
                f"[BACKUP] Removed session manifest: {self._session_manifest_path}"
            )
        self.original_files.clear()
        self.added_files.clear()
        self._modification_order.clear()

    def restore_backups(self, chapter_id: str) -> None:
        if chapter_id in self.original_files:
            self.patching_logger.info(
                f"[RESTORE] Restoring backups for chapter {chapter_id}"
            )
            file_order = self._modification_order.get(
                chapter_id, list(self.original_files[chapter_id].keys())
            )
            file_order = list(reversed(file_order))
            restored_files = []
            failed_files = []
            for file_path in file_order:
                if file_path not in self.original_files[chapter_id]:
                    continue
                backup_path = self.original_files[chapter_id][file_path]
                if backup_path is None:
                    if os.path.exists(file_path):
                        if safe_remove(file_path):
                            self.patching_logger.info(
                                f"[RESTORE] Removed file created by mod: {file_path} (chapter {chapter_id})"
                            )
                            restored_files.append(file_path)
                        else:
                            self.patching_logger.error(
                                f"[RESTORE] Failed to remove file created by mod {file_path} (chapter {chapter_id})"
                            )
                            failed_files.append(file_path)
                    else:
                        self.patching_logger.debug(
                            f"[RESTORE] File created by mod already removed: {file_path} (chapter {chapter_id})"
                        )
                        restored_files.append(file_path)
                    continue
                if not os.path.exists(backup_path):
                    self.patching_logger.warning(
                        f"[RESTORE] Backup file not found: {backup_path} (original: {file_path}, chapter {chapter_id})"
                    )
                    failed_files.append(file_path)
                    continue
                try:
                    target_dir = os.path.dirname(file_path)
                    if target_dir and (not os.path.exists(target_dir)):
                        os.makedirs(target_dir, exist_ok=True)
                        self.patching_logger.debug(
                            f"[RESTORE] Created target directory: {target_dir}"
                        )
                    shutil.copyfile(backup_path, file_path)
                    if os.path.exists(file_path):
                        backup_size = os.path.getsize(backup_path)
                        restored_size = os.path.getsize(file_path)
                        if backup_size == restored_size:
                            self.patching_logger.info(
                                f"[RESTORE] Restored backup: {file_path} <- {backup_path} (chapter {chapter_id}, size: {restored_size} bytes)"
                            )
                            restored_files.append(file_path)
                        else:
                            self.patching_logger.error(
                                f"[RESTORE] File size mismatch after restoration: {file_path} (backup: {backup_size} bytes, restored: {restored_size} bytes, chapter {chapter_id})"
                            )
                            failed_files.append(file_path)
                    else:
                        self.patching_logger.error(
                            f"[RESTORE] File does not exist after restoration attempt: {file_path} (chapter {chapter_id})"
                        )
                        failed_files.append(file_path)
                except Exception as e:
                    self.patching_logger.error(
                        f"[RESTORE] Failed to restore backup {backup_path} to {file_path} (chapter {chapter_id}): {e}",
                        exc_info=True,
                    )
                    failed_files.append(file_path)
            if failed_files:
                self.patching_logger.warning(
                    f"[RESTORE] Restoration completed with {len(failed_files)} failure(s) for chapter {chapter_id}: {failed_files}"
                )
            else:
                self.patching_logger.info(
                    f"[RESTORE] Successfully restored {len(restored_files)} file(s) for chapter {chapter_id}"
                )
        if chapter_id in self.added_files:
            self.patching_logger.info(
                f"[RESTORE] Removing added files for chapter {chapter_id}"
            )
            added_paths = sorted(
                self.added_files[chapter_id].keys(),
                key=lambda p: p.count(os.sep),
                reverse=True,
            )
            removed_dirs = set()
            for file_path in added_paths:
                if not os.path.exists(file_path):
                    self.patching_logger.debug(
                        f"[RESTORE] Added file/directory already removed: {file_path} (chapter {chapter_id})"
                    )
                    continue
                try:
                    if os.path.isdir(file_path):
                        if safe_rmtree(file_path):
                            self.patching_logger.info(
                                f"[RESTORE] Removed directory added by mod: {file_path} (chapter {chapter_id})"
                            )
                            removed_dirs.add(file_path)
                        else:
                            self.patching_logger.error(
                                f"[RESTORE] Failed to remove directory added by mod: {file_path} (chapter {chapter_id})"
                            )
                    elif safe_remove(file_path):
                        self.patching_logger.info(
                            f"[RESTORE] Removed file added by mod: {file_path} (chapter {chapter_id})"
                        )
                        self._remove_empty_parent_dirs(
                            file_path, chapter_id, removed_dirs
                        )
                    else:
                        self.patching_logger.error(
                            f"[RESTORE] Failed to remove file added by mod: {file_path} (chapter {chapter_id})"
                        )
                except Exception as e:
                    self.patching_logger.error(
                        f"[RESTORE] Failed to remove added file/directory {file_path} (chapter {chapter_id}): {e}",
                        exc_info=True,
                    )

    def restore_all_backups(self) -> bool:
        if not self.original_files and (not self.added_files):
            return True
        try:
            all_chapter_ids = set(self.original_files.keys()) | set(
                self.added_files.keys()
            )
            for chapter_id in all_chapter_ids:
                self.restore_backups(chapter_id)
            return True
        except Exception as e:
            self.patching_logger.error(
                f"[RESTORE] Critical error during restore_all_backups: {e}",
                exc_info=True,
            )
            return False

    def _remove_empty_parent_dirs(
        self, file_path: str, chapter_id: str, removed_dirs: set
    ):
        try:
            parent_dir = os.path.dirname(file_path)
            if not parent_dir or parent_dir == file_path or parent_dir in removed_dirs:
                return
            if os.path.exists(parent_dir) and os.path.isdir(parent_dir):
                try:
                    if not os.listdir(parent_dir) and safe_rmtree(parent_dir):
                        self.patching_logger.debug(
                            f"[RESTORE] Removed empty parent directory: {parent_dir} (chapter {chapter_id})"
                        )
                        removed_dirs.add(parent_dir)
                        self._remove_empty_parent_dirs(
                            parent_dir, chapter_id, removed_dirs
                        )
                except OSError:
                    pass
        except Exception as e:
            self.patching_logger.debug(
                f"[RESTORE] Could not remove parent directory for {file_path}: {e}"
            )
