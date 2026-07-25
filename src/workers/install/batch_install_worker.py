"""Worker for batch mod installation flows."""

import contextlib
import logging
import os
import shutil
import tempfile
import time
from urllib.parse import unquote, urlparse

from PyQt6.QtCore import pyqtSignal

from config.config import (
    DATA_FILE_EXTENSIONS,
    MOD_CONFIG_FILENAME,
    NETWORK_TIMEOUT_HEAD,
    UI_COLORS,
)
from services.localization_service import tr
from ui.utils.thread_lifetime import ManagedQThread
from ui.utils.ui_utils import format_size_mb
from utils.file_utils import get_unique_mod_dir, normalize_chapter_id
from utils.mod.config_parser import build_mod_config_data
from utils.mod.utils import get_mod_id
from utils.network_utils import download_file, get_session

logger = logging.getLogger(__name__)


def is_valid_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https")
    except Exception:
        return False


class InstallModsThread(ManagedQThread):
    progress, status, result_ready = (
        pyqtSignal(int),
        pyqtSignal(str, str),
        pyqtSignal(bool),
    )

    def __init__(self, main_window, install_tasks, was_installed_before: bool) -> None:
        super().__init__(main_window)
        self.main_window = main_window
        self.install_tasks = install_tasks
        self.was_installed_before = was_installed_before
        self._cancelled = False
        self._installed_dirs = []
        self.temp_root = None
        self._session = None
        self._active_response = None

    def _safe_emit(self, signal, *args) -> None:
        try:
            signal.emit(*args)
        except Exception as e:
            logger.warning(
                "InstallModsThread: failed to emit %s: %s",
                getattr(signal, "signal", signal.__class__.__name__),
                e,
                exc_info=True,
            )

    def cancel(self):
        self._cancelled = True
        self._safe_emit(
            self.status, tr("status.operation_cancelled"), UI_COLORS["status_error"]
        )
        try:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception as e:
                    logger.warning(
                        f"InstallModsThread.cancel: session close error: {e}",
                        exc_info=True,
                    )
            if self._active_response is not None:
                try:
                    self._active_response.close()
                except Exception as e:
                    logger.warning(
                        f"InstallModsThread.cancel: response close error: {e}",
                        exc_info=True,
                    )
        except Exception as e:
            logger.warning(
                f"InstallModsThread.cancel: cleanup failed: {e}", exc_info=True
            )

    def _download_component_file(
        self,
        url: str,
        target_dir: str,
        component_type: str,
        progress_callback,
        total_size: int,
        downloaded_ref: list[int],
        session=None,
        output_name: str | None = None,
    ):
        import platform

        if session is None:
            session = get_session()
        parsed_url = urlparse(url)
        filename = output_name or unquote(os.path.basename(parsed_url.path))
        if component_type == "data":
            if not filename.lower().endswith(DATA_FILE_EXTENSIONS):
                if platform.system() == "Darwin":
                    filename = "game.ios.xdelta"
                else:
                    filename = "data.win.xdelta"
        elif not filename or "." not in filename:
            filename = f"extra_file_{hash(url) % 10000}.zip"
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, filename)
        try:

            def on_response(r):
                self._active_response = r

            download_file(
                session,
                url,
                target_path,
                progress_callback,
                total_size,
                downloaded_ref,
                cancel_check=lambda: self._cancelled,
                on_response=on_response,
            )
        except Exception:
            if os.path.exists(target_path):
                with contextlib.suppress(OSError):
                    os.remove(target_path)
            raise

    def _make_progress_callback(
        self,
        mod_name: str,
        current_index: int,
        total_items: int,
        total_bytes: int,
        downloaded_ref: list[int],
    ):

        def progress_callback(progress):
            self._safe_emit(self.progress, progress)
            if total_bytes > 0:
                downloaded_mb = format_size_mb(downloaded_ref[0])
                total_mb = format_size_mb(total_bytes)
                self._safe_emit(
                    self.status,
                    f"{mod_name} {current_index}/{total_items} ({downloaded_mb} / {total_mb})",
                    UI_COLORS["status_warning"],
                )

        return progress_callback

    def run(self):
        import requests

        try:
            self.temp_root = tempfile.mkdtemp(prefix="g3m-install-")
            tasks = []
            total_bytes = 0
            mod_folders = {}
            validated_files = {}
            reserved_relative_paths: dict[str, set[str]] = {}
            skipped_missing_ids = False

            def reserve_relative_path(
                mod_key: str, preferred_name: str, chapter_id: str
            ) -> str:
                clean_name = preferred_name.strip().replace("\\", "/").strip("/")
                if not clean_name:
                    clean_name = f"{chapter_id}_file"
                used = reserved_relative_paths.setdefault(mod_key, set())
                if clean_name not in used:
                    used.add(clean_name)
                    return clean_name
                base_name, ext = os.path.splitext(clean_name)
                candidate = f"{chapter_id}_{base_name}{ext}"
                suffix = 1
                while candidate in used:
                    candidate = f"{chapter_id}_{base_name}_{suffix}{ext}"
                    suffix += 1
                used.add(candidate)
                return candidate

            for mod, chapter_id in self.install_tasks:
                key = get_mod_id(mod)
                if not key:
                    logger.warning("InstallModsThread: skipping mod without an ID")
                    skipped_missing_ids = True
                    continue
                if key not in mod_folders:
                    mod_folder_path = self.main_window.mod_service.get_mod_folder_path(
                        key
                    )
                    if mod_folder_path:
                        existing_folder = os.path.basename(mod_folder_path)
                        mod_folders[key] = existing_folder
                    else:
                        mod_folders[key] = get_unique_mod_dir(
                            self.main_window.app_state.mods_dir, mod.name
                        )
                chapter_data = (
                    mod.get_chapter_data(chapter_id)
                    if chapter_id != "deltarunedemo"
                    else None
                )
                if chapter_id == "deltarunedemo" and mod.is_valid_for_demo():
                    if is_valid_url(mod.demo_url):
                        stored_relative_path = reserve_relative_path(
                            key,
                            os.path.basename(urlparse(mod.demo_url).path),
                            "deltarunedemo",
                        )
                        tasks.append(
                            {
                                "mod": mod,
                                "url": mod.demo_url,
                                "chapter_id": "deltarunedemo",
                                "component": "demo",
                                "stored_relative_path": stored_relative_path,
                            }
                        )
                    else:
                        logger.warning(
                            f"InstallModsThread: Invalid URL for demo: {mod.demo_url}"
                        )
                        continue
                    validated_files.setdefault(key, {})[chapter_id] = {
                        "data_file_path": stored_relative_path,
                    }
                elif chapter_data:
                    file_info = {}
                    if chapter_data.data_file_url and is_valid_url(
                        chapter_data.data_file_url
                    ):
                        stored_relative_path = reserve_relative_path(
                            key,
                            os.path.basename(urlparse(chapter_data.data_file_url).path),
                            chapter_id,
                        )
                        tasks.append(
                            {
                                "mod": mod,
                                "url": chapter_data.data_file_url,
                                "chapter_id": chapter_id,
                                "component": "data",
                                "stored_relative_path": stored_relative_path,
                            }
                        )
                        file_info["data_file_path"] = stored_relative_path
                    elif chapter_data.data_file_url:
                        logger.warning(
                            f"InstallModsThread: Invalid URL for data file: {chapter_data.data_file_url}"
                        )
                    extra_files_list = []
                    for extra_file in chapter_data.extra_files:
                        if is_valid_url(extra_file):
                            stored_relative_path = reserve_relative_path(
                                key,
                                os.path.basename(urlparse(extra_file).path),
                                chapter_id,
                            )
                            tasks.append(
                                {
                                    "mod": mod,
                                    "url": extra_file,
                                    "chapter_id": chapter_id,
                                    "component": "extra",
                                    "stored_relative_path": stored_relative_path,
                                }
                            )
                            extra_files_list.append(stored_relative_path)
                        else:
                            logger.warning(
                                f"InstallModsThread: Invalid URL for extra file: {extra_file}"
                            )
                    if file_info or extra_files_list:
                        if extra_files_list:
                            file_info["extra_files"] = extra_files_list
                        validated_files.setdefault(key, {})[chapter_id] = file_info
            if not tasks:
                self._safe_emit(self.result_ready, not skipped_missing_ids)
                return
            session = get_session()
            self._session = session
            download_tasks = [
                t for t in tasks if t.get("url") and is_valid_url(t.get("url"))
            ]
            file_sizes_cache = {}
            for task in download_tasks:
                u = task.get("url")
                try:
                    h = session.head(
                        u, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD
                    )
                    h.raise_for_status()
                    content_length = int(h.headers.get("content-length", 0))
                    file_sizes_cache[u] = content_length
                    total_bytes += content_length
                except (
                    requests.Timeout,
                    requests.HTTPError,
                    requests.RequestException,
                    Exception,
                ):
                    file_sizes_cache[u] = 0
                    total_bytes = 0
                    break
            if self._cancelled:
                self._safe_emit(self.result_ready, False)
                return
            self._safe_emit(
                self.status,
                tr("status.preparing_download"), UI_COLORS["status_warning"]
            )
            if self._cancelled:
                self._safe_emit(self.result_ready, False)
                return
            downloaded_ref = [0]
            done_files = 0
            installed_mods = {}
            mod_configs = {}
            total_items = len(download_tasks)
            current_index = 0
            for task in tasks:
                if self._cancelled:
                    self._safe_emit(self.result_ready, False)
                    return
                mod = task.get("mod")
                chapter_id = task.get("chapter_id")
                mod_folder_name = mod_folders[mod.id]
                mod_dir = os.path.join(self.temp_root, mod_folder_name)
                stored_relative_path = str(task.get("stored_relative_path", "")).replace(
                    "\\", "/"
                )
                cache_dir = (
                    os.path.join(
                        mod_dir,
                        os.path.dirname(stored_relative_path).replace("/", os.sep),
                    )
                    if os.path.dirname(stored_relative_path)
                    else mod_dir
                )
                if task.get("delete"):
                    try:
                        if os.path.exists(cache_dir):
                            for fname in os.listdir(cache_dir):
                                fl = fname.lower()
                                if fl.endswith(
                                    (
                                        ".zip",
                                        ".g3mpatch",
                                        ".rar",
                                        ".7z",
                                        ".tar.gz",
                                        ".lzma",
                                    )
                                ):
                                    file_path = os.path.join(cache_dir, fname)
                                    try:
                                        if os.path.isfile(file_path):
                                            os.remove(file_path)
                                            logger.debug(
                                                f"InstallModsThread: Deleted cache file {fname}"
                                            )
                                    except Exception as e:
                                        logger.warning(
                                            f"InstallModsThread: Failed to delete cache file {fname}: {e}"
                                        )
                    except Exception as e:
                        logger.warning(
                            f"InstallModsThread: delete cleanup failed: {e}",
                            exc_info=True,
                        )
                    continue
                url = task.get("url")
                if not url:
                    continue
                current_index += 1
                mod_key = get_mod_id(mod)
                file_size_mb = tr("status.unknown_size")
                file_size_bytes = file_sizes_cache.get(url, 0)
                if file_size_bytes > 0:
                    size_mb = file_size_bytes / (1024 * 1024)
                    file_size_mb = (
                        tr("status.unknown_size")
                        if size_mb < 0.05
                        else f"{size_mb:.1f} MB"
                    )
                status_text = (
                    f"{mod.name} {current_index}/{total_items} ({file_size_mb})"
                )
                self._safe_emit(self.status, status_text, UI_COLORS["status_warning"])
                self._installed_dirs.append(cache_dir)
                chapter_data = mod.get_chapter_data(chapter_id)
                is_data_file = (
                    chapter_data and url and (chapter_data.data_file_url == url)
                )
                is_xdelta = url.lower().endswith(DATA_FILE_EXTENSIONS) if url else False
                if is_data_file:
                    if is_xdelta:
                        progress_callback = self._make_progress_callback(
                            mod.name,
                            current_index,
                            total_items,
                            total_bytes,
                            downloaded_ref,
                        )
                        self._download_component_file(
                            url,
                            cache_dir,
                            "data",
                            progress_callback,
                            total_bytes,
                            downloaded_ref,
                            session,
                            output_name=os.path.basename(stored_relative_path) or None,
                        )
                    else:
                        from utils.file_utils import download_and_extract_archive

                        before_files = set()
                        for root, _dir_names, files in os.walk(mod_dir):
                            for file in files:
                                before_files.add(
                                    os.path.relpath(os.path.join(root, file), mod_dir).replace(
                                        "\\", "/"
                                    )
                                )
                        progress_callback = self._make_progress_callback(
                            mod.name,
                            current_index,
                            total_items,
                            total_bytes,
                            downloaded_ref,
                        )
                        download_and_extract_archive(
                            url,
                            cache_dir,
                            progress_callback,
                            total_bytes,
                            downloaded_ref,
                            session,
                            cancel_check=lambda: self._cancelled,
                        )
                        extracted_files = set()
                        for root, _dir_names, files in os.walk(mod_dir):
                            for file in files:
                                extracted_files.add(
                                    os.path.relpath(os.path.join(root, file), mod_dir).replace(
                                        "\\", "/"
                                    )
                                )
                        extracted_files -= before_files
                        extracted_data_files = sorted(
                            rel_path
                            for rel_path in extracted_files
                            if rel_path.lower().endswith(DATA_FILE_EXTENSIONS)
                        )
                        if extracted_data_files:
                            validated_files.setdefault(mod_key, {}).setdefault(
                                chapter_id, {}
                            )["data_file_path"] = extracted_data_files[0]
                        if self._cancelled:
                            self._safe_emit(self.result_ready, False)
                            return
                else:
                    progress_callback = self._make_progress_callback(
                        mod.name,
                        current_index,
                        total_items,
                        total_bytes,
                        downloaded_ref,
                    )
                    self._download_component_file(
                        url,
                        cache_dir,
                        "extra",
                        progress_callback,
                        total_bytes,
                        downloaded_ref,
                        session,
                        output_name=os.path.basename(stored_relative_path) or None,
                    )
                if mod_key not in installed_mods:
                    installed_mods[mod_key] = {"mod": mod, "chapters": set(), "files": {}}
                installed_mods[mod_key]["chapters"].add(chapter_id)
                if url and total_bytes == 0:
                    done_files += 1
                    progress = int(done_files / max(1, len(download_tasks)) * 100)
                    self._safe_emit(self.progress, progress)
                if self._cancelled:
                    self._safe_emit(
                        self.status,
                        tr("status.operation_cancelled"), UI_COLORS["status_error"]
                    )
                    self._safe_emit(self.result_ready, False)
                    return
            for key, mod_data in installed_mods.items():
                mod = mod_data["mod"]
                mod_folder_name = mod_folders[key]
                mod_dir = os.path.join(
                    self.main_window.app_state.mods_dir, mod_folder_name
                )
                files_data = {}
                for chapter_id in mod_data["chapters"]:
                    file_info = validated_files.get(key, {}).get(chapter_id, {})
                    if file_info:
                        files_data[normalize_chapter_id(chapter_id, mod.game)] = file_info
                config_data = {
                    "id": mod.id,
                    "name": mod.name,
                    "author": mod.author,
                    "version": mod.version,
                    "game_version": mod.game_version,
                    "game": mod.game,
                    "files": files_data,
                    "tags": mod.tags,
                }
                if hasattr(mod, "icon") and mod.icon:
                    config_data["icon"] = mod.icon
                mod_configs[mod.id] = {
                    "folder_name": mod_folder_name,
                    "config": config_data,
                }
            try:
                os.makedirs(self.main_window.app_state.mods_dir, exist_ok=True)
                for entry in os.listdir(self.temp_root or ""):
                    src = os.path.join(self.temp_root, entry)
                    dst = os.path.join(self.main_window.app_state.mods_dir, entry)
                    if os.path.isdir(src):
                        try:
                            shutil.copytree(src, dst, dirs_exist_ok=True)
                        except TypeError:
                            if not os.path.exists(dst):
                                shutil.move(src, dst)
                            else:
                                for root, dirs, files in os.walk(src):
                                    rel = os.path.relpath(root, src)
                                    target_root = os.path.join(dst, rel)
                                    os.makedirs(target_root, exist_ok=True)
                                    for d in dirs:
                                        os.makedirs(
                                            os.path.join(target_root, d), exist_ok=True
                                        )
                                    for f in files:
                                        shutil.copy2(
                                            os.path.join(root, f),
                                            os.path.join(target_root, f),
                                        )
                    else:
                        shutil.copy2(src, dst)
            except Exception as e:
                logger.warning(f"InstallModsThread: copy extracted files failed: {e}")
            if self._cancelled:
                self._safe_emit(
                    self.status,
                    tr("status.operation_cancelled"), UI_COLORS["status_error"]
                )
                self._safe_emit(self.result_ready, False)
                return
            for info in mod_configs.values():
                folder_name = info["folder_name"]
                config_data = info["config"]
                mod_dir = os.path.join(self.main_window.app_state.mods_dir, folder_name)
                config_path = os.path.join(mod_dir, MOD_CONFIG_FILENAME)
                self.main_window.settings_service.write_json(
                    config_path, build_mod_config_data(config_data)
                )
            metadata = self.main_window.mod_service._read_metadata()
            for key in installed_mods:
                metadata[key] = {
                    "added_date": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            self.main_window.mod_service._write_metadata(metadata)
            if self._cancelled:
                self._safe_emit(
                    self.status,
                    tr("status.operation_cancelled"), UI_COLORS["status_error"]
                )
                self._safe_emit(self.result_ready, False)
            else:
                self._safe_emit(
                    self.status,
                    tr("status.installation_complete"), UI_COLORS["status_success"]
                )
                self._safe_emit(self.result_ready, not skipped_missing_ids)
        except PermissionError as e:
            logger.warning(f"InstallModsThread.run: permission error: {e}")
            self._safe_emit(
                self.status, tr("errors.permission_error_install"), UI_COLORS["status_error"]
            )
            self._safe_emit(self.result_ready, False)
        except RuntimeError as e:
            if str(e) == "download_cancelled":
                logger.info("InstallModsThread.run: download cancelled by user")
                self._safe_emit(self.result_ready, False)
            else:
                logger.error(
                    f"InstallModsThread.run: installation error: {e}", exc_info=True
                )
                self._safe_emit(
                    self.status,
                    tr("errors.installation_error", error=str(e)),
                    UI_COLORS["status_error"],
                )
                self._safe_emit(self.result_ready, False)
        except Exception as e:
            logger.error(
                f"InstallModsThread.run: installation error: {e}", exc_info=True
            )
            self._safe_emit(
                self.status,
                tr("errors.installation_error", error=str(e)), UI_COLORS["status_error"]
            )
            self._safe_emit(self.result_ready, False)
        finally:
            try:
                if self.temp_root and os.path.isdir(self.temp_root):
                    shutil.rmtree(self.temp_root, ignore_errors=True)
            except Exception as cleanup_e:
                logger.debug(f"InstallModsThread: temp cleanup failed: {cleanup_e}")
            self._session = None
