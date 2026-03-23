import contextlib
import logging
import os
import shutil
import tempfile
import time
from urllib.parse import unquote, urlparse

from PyQt6.QtCore import QThread, pyqtSignal

from config.constants import (
    DATA_FILE_EXTENSIONS,
    MOD_CONFIG_FILENAME,
    NETWORK_TIMEOUT_HEAD,
    UI_COLORS,
)
from services.localization_service import tr
from ui.utils.ui_utils import format_size_mb
from utils.file_utils import chapter_id_to_file_key, get_unique_mod_dir
from utils.mod_utils import get_mod_key
from utils.network_utils import download_file, get_session


def is_valid_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https")
    except Exception:
        return False


class InstallModsThread(QThread):
    progress, status, finished = (
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

    def cancel(self):
        self._cancelled = True
        self.status.emit(tr("status.operation_cancelled"), UI_COLORS["status_error"])
        try:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception as e:
                    logging.warning(
                        f"InstallModsThread.cancel: session close error: {e}",
                        exc_info=True,
                    )
            if self._active_response is not None:
                try:
                    self._active_response.close()
                except Exception as e:
                    logging.warning(
                        f"InstallModsThread.cancel: response close error: {e}",
                        exc_info=True,
                    )
        except Exception as e:
            logging.warning(
                f"InstallModsThread.cancel: cleanup failed: {e}", exc_info=True
            )

    def _collect_remote_versions_for_chapter(self, mod, chapter_id: str) -> dict:
        versions: dict[str, str] = {}
        if chapter_id == "deltarunedemo":
            if mod.is_valid_for_demo() and mod.demo_version:
                versions["demo"] = mod.demo_version
            return versions
        chapter_data = mod.get_chapter_data(chapter_id)
        if not chapter_data:
            return versions
        if chapter_data.data_file_version:
            versions["data"] = chapter_data.data_file_version
        for extra_file in chapter_data.extra_files:
            if extra_file and extra_file.key and extra_file.version:
                versions[extra_file.key] = extra_file.version
        return versions

    def _should_update_component(
        self, mod, chapter_id: str, existing_folder: str
    ) -> dict:
        if not existing_folder:
            return {}
        config_path = os.path.join(
            self.main_window.app_state.mods_dir, existing_folder, MOD_CONFIG_FILENAME
        )
        if not os.path.exists(config_path):
            return {}
        try:
            config_data = self.main_window.settings_service.read_json(config_path)
            local_versions = (
                config_data.get("chapters", {}).get(chapter_id, {}).get("versions", {})
                or {}
            )
            remote_versions = self._collect_remote_versions_for_chapter(mod, chapter_id)
            from utils.path_utils import version_sort_key

            components_to_update: dict[str, dict] = {}
            chapter_data = (
                mod.get_chapter_data(chapter_id)
                if chapter_id != "deltarunedemo"
                else None
            )
            if (
                chapter_data
                and chapter_data.data_file_url
                and remote_versions.get("data")
            ):
                if not is_valid_url(chapter_data.data_file_url):
                    logging.warning(
                        f"_should_update_component: Invalid URL for data file: {chapter_data.data_file_url}"
                    )
                else:
                    local_data_v = local_versions.get("data")
                    remote_data_v = remote_versions.get("data")
                    if remote_data_v and version_sort_key(
                        remote_data_v
                    ) > version_sort_key(local_data_v or "0.0.0"):
                        components_to_update["data"] = {
                            "url": chapter_data.data_file_url,
                            "local_version": local_data_v,
                            "remote_version": remote_data_v,
                        }
            if chapter_data:
                for extra_file in chapter_data.extra_files:
                    if not is_valid_url(extra_file.url):
                        logging.warning(
                            f"_should_update_component: Invalid URL for extra file {extra_file.key}: {extra_file.url}"
                        )
                        continue
                    rv = remote_versions.get(extra_file.key)
                    lv = local_versions.get(extra_file.key)
                    if rv and version_sort_key(rv) > version_sort_key(lv or "0.0.0"):
                        components_to_update[extra_file.key] = {
                            "url": extra_file.url,
                            "local_version": lv,
                            "remote_version": rv,
                        }
                remote_extra_keys = {ef.key for ef in chapter_data.extra_files}
                for missing_key in [
                    k
                    for k in local_versions
                    if k != "data" and k not in remote_extra_keys
                ]:
                    components_to_update[missing_key] = {"delete": True}
            return components_to_update
        except Exception as e:
            logging.error(
                f"_should_update_component: failed to compute updates: {e}",
                exc_info=True,
            )
            return {}

    def _download_component_file(
        self,
        url: str,
        target_dir: str,
        component_type: str,
        progress_callback,
        total_size: int,
        downloaded_ref: list[int],
        session=None,
    ):
        import platform

        if session is None:
            session = get_session()
        parsed_url = urlparse(url)
        filename = unquote(os.path.basename(parsed_url.path))
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
            self.progress.emit(progress)
            if total_bytes > 0:
                downloaded_mb = format_size_mb(downloaded_ref[0])
                total_mb = format_size_mb(total_bytes)
                self.status.emit(
                    f"{mod_name} {current_index}/{total_items} ({downloaded_mb} / {total_mb})",
                    UI_COLORS["status_warning"],
                )

        return progress_callback

    def run(self):
        import requests

        try:
            self.temp_root = tempfile.mkdtemp(prefix="deltahub-install-")
            tasks = []
            total_bytes = 0
            mod_folders = {}
            for mod, chapter_id in self.install_tasks:
                key = get_mod_key(mod)
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
                mod_key = get_mod_key(mod)
                existing_folder = mod_folders.get(mod_key, "")
                chapter_data = (
                    mod.get_chapter_data(chapter_id)
                    if chapter_id != "deltarunedemo"
                    else None
                )
                if chapter_id == "deltarunedemo" and mod.is_valid_for_demo():
                    if is_valid_url(mod.demo_url):
                        tasks.append(
                            {
                                "mod": mod,
                                "url": mod.demo_url,
                                "chapter_id": "deltarunedemo",
                                "component": "demo",
                            }
                        )
                    else:
                        logging.warning(
                            f"InstallModsThread: Invalid URL for demo: {mod.demo_url}"
                        )
                elif chapter_data:
                    components_to_update = self._should_update_component(
                        mod, chapter_id, existing_folder
                    )
                    if not components_to_update:
                        if chapter_data.data_file_url and is_valid_url(
                            chapter_data.data_file_url
                        ):
                            tasks.append(
                                {
                                    "mod": mod,
                                    "url": chapter_data.data_file_url,
                                    "chapter_id": chapter_id,
                                    "component": "data",
                                }
                            )
                        for extra_file in chapter_data.extra_files:
                            if is_valid_url(extra_file.url):
                                tasks.append(
                                    {
                                        "mod": mod,
                                        "url": extra_file.url,
                                        "chapter_id": chapter_id,
                                        "component": extra_file.key,
                                    }
                                )
                            else:
                                logging.warning(
                                    f"InstallModsThread: Invalid URL for extra file {extra_file.key}: {extra_file.url}"
                                )
                    else:
                        for component, info in components_to_update.items():
                            if info.get("delete"):
                                tasks.append(
                                    {
                                        "mod": mod,
                                        "chapter_id": chapter_id,
                                        "component": component,
                                        "delete": True,
                                    }
                                )
                                continue
                            t = {
                                "mod": mod,
                                "url": info["url"],
                                "chapter_id": chapter_id,
                                "component": component,
                            }
                            tasks.append(t)
            if not tasks:
                self.finished.emit(True)
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
                self.finished.emit(False)
                return
            self.status.emit(
                tr("status.preparing_download"), UI_COLORS["status_warning"]
            )
            if self._cancelled:
                self.finished.emit(False)
                return
            downloaded_ref = [0]
            done_files = 0
            installed_mods = {}
            mod_configs = {}
            total_items = len(download_tasks)
            current_index = 0
            for task in tasks:
                if self._cancelled:
                    self.finished.emit(False)
                    return
                mod = task.get("mod")
                chapter_id = task.get("chapter_id")
                mod_folder_name = mod_folders[mod.key]
                mod_dir = os.path.join(self.temp_root, mod_folder_name)
                game_value = getattr(mod, "game", None) or getattr(mod, "modgame", None)
                from utils.file_utils import get_chapter_folder_name

                folder_name = get_chapter_folder_name(chapter_id, game=game_value)
                cache_dir = os.path.join(mod_dir, folder_name)
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
                                            logging.debug(
                                                f"InstallModsThread: Deleted cache file {fname}"
                                            )
                                    except Exception as e:
                                        logging.warning(
                                            f"InstallModsThread: Failed to delete cache file {fname}: {e}"
                                        )
                    except Exception as e:
                        logging.warning(
                            f"InstallModsThread: delete cleanup failed: {e}",
                            exc_info=True,
                        )
                    continue
                url = task.get("url")
                if not url:
                    continue
                current_index += 1
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
                self.status.emit(status_text, UI_COLORS["status_warning"])
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
                        )
                    else:
                        from utils.file_utils import download_and_extract_archive

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
                        if self._cancelled:
                            self.finished.emit(False)
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
                    )
                key = get_mod_key(mod)
                if key not in installed_mods:
                    installed_mods[key] = {"mod": mod, "chapters": set()}
                installed_mods[key]["chapters"].add(chapter_id)
                if url and total_bytes == 0:
                    done_files += 1
                    progress = int(done_files / max(1, len(download_tasks)) * 100)
                    self.progress.emit(progress)
                if self._cancelled:
                    self.status.emit(
                        tr("status.operation_cancelled"), UI_COLORS["status_error"]
                    )
                    self.finished.emit(False)
                    return
            for key, mod_data in installed_mods.items():
                mod = mod_data["mod"]
                mod_folder_name = mod_folders[key]
                mod_dir = os.path.join(
                    self.main_window.app_state.mods_dir, mod_folder_name
                )
                files_data = {}
                for chapter_id in mod_data["chapters"]:
                    chapter_data = (
                        mod.get_chapter_data(chapter_id)
                        if chapter_id != "deltarunedemo"
                        else None
                    )
                    versions_dict = {}
                    file_info = {}
                    if chapter_data:
                        if (
                            chapter_data.data_file_url
                            and chapter_data.data_file_version
                        ):
                            versions_dict["data"] = chapter_data.data_file_version
                        if chapter_data.data_file_url:
                            file_info["data_file_version"] = (
                                chapter_data.data_file_version
                            )
                        extra_files_dict = {}
                        for extra_file in chapter_data.extra_files:
                            versions_dict[extra_file.key] = extra_file.version
                            if extra_file.key not in extra_files_dict:
                                extra_files_dict[extra_file.key] = []
                            basename = os.path.basename(extra_file.url)
                            extra_files_dict[extra_file.key].append(basename)
                        if extra_files_dict:
                            file_info["extra_files"] = extra_files_dict
                        if versions_dict:
                            file_info["versions"] = versions_dict
                    elif chapter_id == "deltarunedemo" and mod.is_valid_for_demo():
                        file_info["data_file_version"] = mod.demo_version or "1.0.0"
                        file_info["versions"] = {"demo": mod.demo_version or "1.0.0"}
                    if file_info:
                        file_key = chapter_id_to_file_key(chapter_id)
                        files_data[file_key] = file_info
                config_data = {
                    "key": mod.key,
                    "name": mod.name,
                    "author": mod.author,
                    "version": mod.version,
                    "game_version": mod.game_version,
                    "game": mod.game,
                    "files": files_data,
                    "tags": mod.tags,
                }
                if hasattr(mod, "icon_url") and mod.icon_url:
                    config_data["icon_url"] = mod.icon_url
                mod_configs[mod.key] = {
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
                logging.warning(f"InstallModsThread: copy extracted files failed: {e}")
            if self._cancelled:
                self.status.emit(
                    tr("status.operation_cancelled"), UI_COLORS["status_error"]
                )
                self.finished.emit(False)
                return
            for _key, info in mod_configs.items():
                folder_name = info["folder_name"]
                config_data = info["config"]
                mod_dir = os.path.join(self.main_window.app_state.mods_dir, folder_name)
                config_path = os.path.join(mod_dir, MOD_CONFIG_FILENAME)
                self.main_window.settings_service.write_json(config_path, config_data)
            metadata = self.main_window.mod_service._read_metadata()
            for key in installed_mods:
                metadata[key] = {
                    "added_date": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "is_available_on_server": True,
                }
            self.main_window.mod_service._write_metadata(metadata)
            if self._cancelled:
                self.status.emit(
                    tr("status.operation_cancelled"), UI_COLORS["status_error"]
                )
                self.finished.emit(False)
            else:
                self.status.emit(
                    tr("status.installation_complete"), UI_COLORS["status_success"]
                )
                self.finished.emit(True)
        except PermissionError as e:
            logging.warning(f"InstallModsThread.run: permission error: {e}")
            try:
                self.status.emit(
                    tr("errors.permission_error_install"), UI_COLORS["status_error"]
                )
            except Exception as emit_e:
                logging.debug(
                    f"InstallModsThread: failed to emit permission error: {emit_e}"
                )
            self.finished.emit(False)
        except RuntimeError as e:
            if str(e) == "download_cancelled":
                logging.info("InstallModsThread.run: download cancelled by user")
                self.finished.emit(False)
            else:
                logging.error(
                    f"InstallModsThread.run: installation error: {e}", exc_info=True
                )
                self.status.emit(
                    tr("errors.installation_error", error=str(e)),
                    UI_COLORS["status_error"],
                )
                self.finished.emit(False)
        except Exception as e:
            logging.error(
                f"InstallModsThread.run: installation error: {e}", exc_info=True
            )
            self.status.emit(
                tr("errors.installation_error", error=str(e)), UI_COLORS["status_error"]
            )
            self.finished.emit(False)
        finally:
            try:
                if self.temp_root and os.path.isdir(self.temp_root):
                    shutil.rmtree(self.temp_root, ignore_errors=True)
            except Exception as cleanup_e:
                logging.debug(f"InstallModsThread: temp cleanup failed: {cleanup_e}")
            self._session = None
