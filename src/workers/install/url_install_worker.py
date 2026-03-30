"""URL-based mod installation worker."""

import json
import logging
import os
import shutil
import tempfile

from PyQt6.QtCore import pyqtSignal

from config.config import (
    MOD_CONFIG_FILENAME,
    THEME_CONFIG_FILENAME,
    THEME_CONFIG_FILENAMES,
    UI_COLORS,
    URL_PROTOCOL_PREFIXES,
)
from models.exceptions import AppError
from services.localization_service import tr
from services.migration_service import normalize_theme_settings
from utils.file_utils import check_filename_is_deltamod_info, has_deltamod_info_file
from utils.network_utils import download_file, get_session
from utils.path_utils import find_theme_config_path
from workers.base_install_worker import BaseInstallWorker
from workers.install.helpers_install import (
    find_mod_config,
    load_mod_config,
    normalize_mod_id,
    save_mod_config,
)


class UrlInstallThread(BaseInstallWorker):
    manual_install_required = pyqtSignal(str, str, str)

    @staticmethod
    def _unpack_content_path(
        archive_path: str, unpack_dir: str, use_shutil: bool = True
    ) -> str:
        from utils.archive_utils import unwrap_single_directory_chain

        if use_shutil:
            shutil.unpack_archive(archive_path, unpack_dir)
        else:
            from utils.archive_utils import extract_any_archive

            extract_any_archive(archive_path, unpack_dir)
        return unwrap_single_directory_chain(unpack_dir)

    def __init__(self, main_window, url: str) -> None:
        super().__init__(main_window)
        self.main_window = main_window
        self.url = url

    def run(self):
        try:
            if self.url.startswith(URL_PROTOCOL_PREFIXES):
                prefix = next(
                    candidate
                    for candidate in URL_PROTOCOL_PREFIXES
                    if self.url.startswith(candidate)
                )
                content = self.url[len(prefix) :].split(",")[0].strip().rstrip("/")
                if len(content) == 64 and all(
                    c in "0123456789abcdef" for c in content.lower()
                ):
                    self.finished.emit(False, tr("errors.mod_not_found"))
                    return
                if not content.startswith(("http://", "https://")):
                    content = content.replace("https//", "https://").replace(
                        "http//", "http://"
                    )
                download_url = content
            else:
                download_url = self.url
            with tempfile.TemporaryDirectory(prefix="g3m-url-install-") as temp_dir:
                self.status.emit(
                    tr("status.downloading_from_external"), UI_COLORS["status_warning"]
                )
                archive_path = self._download_archive(download_url, temp_dir)
                redirect_result = self._check_redirect(archive_path, temp_dir)
                if redirect_result:
                    return
                content_type = self._detect_content_type(archive_path)
                if content_type == "theme":
                    self._extract_and_install_theme(archive_path, temp_dir)
                elif content_type == "mod":
                    self._install_mod_from_archive(archive_path, temp_dir)
                else:
                    self._prepare_for_manual_install(archive_path)
        except Exception as e:
            self.finished.emit(False, str(e))

    def _process_deltamod_archive(self, url: str):
        with tempfile.TemporaryDirectory(prefix="g3m-redirect-dl-") as temp_dir:
            archive_path = self._download_archive(url, temp_dir)
            with tempfile.TemporaryDirectory(
                prefix="g3m-redirect-unpack-"
            ) as unpack_dir:
                content_path = self._unpack_content_path(archive_path, unpack_dir)
                files_in_root = os.listdir(content_path)
                if MOD_CONFIG_FILENAME in files_in_root:
                    mod_dir = self._install_g3m_mod_from_path(content_path)
                    if mod_dir:
                        mod_name = os.path.basename(mod_dir)
                        self.finished.emit(
                            True,
                            tr("status.install_complete_success", mod_name=mod_name),
                        )
                    else:
                        raise AppError("errors.mod_installation_failed")
                elif has_deltamod_info_file(files_in_root):
                    from adapters.deltamod_adapter import DeltamodConverter

                    converter = DeltamodConverter(
                        content_path, self.main_window.app_state.mods_dir
                    )
                    new_mod_path = converter.convert()
                    if new_mod_path:
                        mod_name = os.path.basename(new_mod_path)
                        self.finished.emit(
                            True,
                            tr("status.install_complete_success", mod_name=mod_name),
                        )
                    else:
                        raise AppError("errors.deltamod_conversion_failed_url")
                else:
                    raise AppError("errors.deltamod_archive_invalid_redirect")

    def _install_g3m_mod_from_path(self, content_path: str) -> str | None:
        mod_config_path = find_mod_config(content_path)
        if not mod_config_path:
            logging.error("mod_config.json not found in G3M mod archive")
            return None
        config_data = load_mod_config(mod_config_path)
        if not config_data:
            return None
        normalize_mod_id(config_data)
        mod_id = config_data.get("id")
        mod_name = config_data.get("name", "imported_mod")
        target_mod_dir = self._create_unique_mod_dir(
            self.main_window.app_state.mods_dir, mod_name
        )
        self._copy_directory_contents(content_path, target_mod_dir)
        target_config_path = os.path.join(target_mod_dir, MOD_CONFIG_FILENAME)
        try:
            save_mod_config(target_config_path, config_data)
            logging.info(
                f"Installed G3M mod from URL: {target_mod_dir}, mod_id={mod_id}"
            )
        except Exception as e:
            logging.error(f"Failed to save mod config: {e}", exc_info=True)
            return None
        return target_mod_dir

    def _download_archive(self, url: str, temp_dir: str) -> str:
        from urllib.parse import unquote, urlparse

        from utils.network_utils import get_filename_from_url

        parsed_url = urlparse(url)
        filename = unquote(os.path.basename(parsed_url.path))
        if not filename or "." not in filename:
            session = get_session()
            filename = get_filename_from_url(session, url)
        from utils.archive_utils import get_file_extension_from_url

        if not filename:
            file_ext = get_file_extension_from_url(url)
            filename = f"archive{file_ext}"
        supported_extensions = [".zip", ".rar", ".7z", ".tar.gz", ".lzma"]
        if not any(filename.lower().endswith(ext) for ext in supported_extensions):
            file_ext = get_file_extension_from_url(url)
            filename = f"archive{file_ext}"
        archive_path = os.path.join(temp_dir, filename)
        session = get_session()
        self._session = session
        downloaded_ref = [0]
        total_size = self._get_content_length(session, url)
        progress_callback = self._make_download_progress_callback(
            tr("status.downloading_mod"), total_size, downloaded_ref
        )

        def on_response(r):
            self._active_response = r

        download_file(
            session,
            url,
            archive_path,
            progress_callback=progress_callback,
            total_size=total_size,
            downloaded_ref=downloaded_ref,
            cancel_check=lambda: self._cancelled,
            on_response=on_response,
        )
        self.progress.emit(100)
        return archive_path

    @staticmethod
    def _classify_filename(name: str) -> str | None:
        n = name.replace("\\", "/").strip("/")
        if any(n == filename or n.endswith(f"/{filename}") for filename in THEME_CONFIG_FILENAMES):
            return "theme"
        if n == MOD_CONFIG_FILENAME or n.endswith(f"/{MOD_CONFIG_FILENAME}"):
            return "mod"
        if check_filename_is_deltamod_info(n):
            return "mod"
        return None

    def _detect_from_names(self, names) -> str | None:
        for name in names:
            result = self._classify_filename(name)
            if result:
                return result
        return None

    def _detect_content_type(self, archive_path: str) -> str:
        import tarfile
        import zipfile

        archive_lower = archive_path.lower()
        try:
            if archive_lower.endswith(".zip"):
                with zipfile.ZipFile(archive_path, "r") as zf:
                    result = self._detect_from_names(zf.namelist())
                    if result:
                        return result
            elif archive_lower.endswith(".tar.gz"):
                with tarfile.open(archive_path, "r:gz") as tf:
                    result = self._detect_from_names(m.name for m in tf.getmembers())
                    if result:
                        return result
            elif archive_lower.endswith(".rar"):
                try:
                    import rarfile

                    with rarfile.RarFile(archive_path, "r") as rf:
                        result = self._detect_from_names(rf.namelist())
                        if result:
                            return result
                except (OSError, ImportError) as e:
                    logging.debug(f"Could not open RAR: {e}")
            elif archive_lower.endswith(".7z"):
                try:
                    import py7zr

                    with py7zr.SevenZipFile(archive_path, mode="r") as zf:
                        result = self._detect_from_names(zf.getnames())
                        if result:
                            return result
                except (OSError, ImportError) as e:
                    logging.debug(f"Could not open 7z: {e}")
        except Exception as e:
            logging.error(f"Error detecting content type: {e}", exc_info=True)
        return self._detect_content_type_from_extracted(archive_path) or ""

    def _detect_content_type_from_extracted(self, archive_path: str) -> str | None:
        with tempfile.TemporaryDirectory(prefix="g3m-detect-type-") as unpack_dir:
            try:
                from utils.archive_utils import (
                    extract_any_archive,
                    unwrap_single_directory_chain,
                )

                extract_any_archive(archive_path, unpack_dir)
                content_path = unwrap_single_directory_chain(unpack_dir)
                for _root, _, files in os.walk(content_path):
                    for f in files:
                        if f in THEME_CONFIG_FILENAMES:
                            return "theme"
                        if f == MOD_CONFIG_FILENAME or check_filename_is_deltamod_info(
                            f
                        ):
                            return "mod"
                if has_deltamod_info_file(os.listdir(content_path)):
                    return "mod"
            except Exception as e:
                logging.error(f"Error detecting from extracted: {e}", exc_info=True)
        return None

    def _prepare_for_manual_install(self, archive_path: str):
        try:
            from utils.archive_utils import extract_archive

            persistent_temp_dir = tempfile.mkdtemp(
                prefix="g3m_url_manual_install_"
            )
            try:
                archive_filename = os.path.basename(archive_path)
                preserved_archive_path = os.path.join(
                    persistent_temp_dir, archive_filename
                )
                shutil.copy2(archive_path, preserved_archive_path)
                extract_dir = os.path.join(persistent_temp_dir, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                extract_archive(preserved_archive_path, extract_dir)
                from utils.archive_utils import unwrap_single_directory_chain

                content_path = unwrap_single_directory_chain(extract_dir)
                self.status.emit(
                    tr("status.manual_install_ready"), UI_COLORS["status_info"]
                )
                self.manual_install_required.emit(
                    content_path, preserved_archive_path, persistent_temp_dir
                )
            except Exception:
                try:
                    shutil.rmtree(persistent_temp_dir, ignore_errors=True)
                except Exception as e:
                    logging.debug(
                        f"UrlInstallThread: Failed to clean up {persistent_temp_dir}: {e}",
                        exc_info=True,
                    )
                raise
        except Exception as e:
            logging.error(
                f"UrlInstallThread: Error preparing for manual install: {e}",
                exc_info=True,
            )
            self.finished.emit(False, tr("errors.manual_install_failed", error=str(e)))

    def _install_theme_from_dir(self, theme_dir: str):
        try:
            self.status.emit(tr("themes.installing_theme"), UI_COLORS["status_warning"])
            config_dir = self.main_window.app_state.config_dir
            app_state = self.main_window.app_state
            settings_service = self.main_window.settings_service
            theme_json_path = find_theme_config_path(theme_dir)
            if not theme_json_path:
                raise ValueError(f"Missing {THEME_CONFIG_FILENAME}")
            with open(theme_json_path, encoding="utf-8") as f:
                theme_settings = normalize_theme_settings(json.load(f))
            for key, value in theme_settings.items():
                if key != "config_version":
                    app_state.local_config[key] = value
            for old_file in [
                "custom_background_music.mp3",
                "custom_background_music.wav",
                "custom_startup_sound.mp3",
                "custom_startup_sound.wav",
            ]:
                old_file_path = os.path.join(config_dir, old_file)
                if os.path.exists(old_file_path):
                    try:
                        os.remove(old_file_path)
                    except Exception as e:
                        logging.warning(f"Failed to remove old file {old_file}: {e}")
            settings_service.write_local_config()
            self.status.emit(tr("themes.theme_installed"), "success")
            self.finished.emit(True, tr("themes.theme_installed_success"))
        except Exception as e:
            logging.error(
                f"UrlInstallThread: Error installing theme from dir: {e}", exc_info=True
            )
            self.finished.emit(False, tr("themes.installation_error", error=str(e)))

    def _extract_and_install_theme(self, archive_path: str, temp_dir: str):
        with tempfile.TemporaryDirectory(prefix="g3m-theme-extract-") as unpack_dir:
            try:
                content_path = self._unpack_content_path(archive_path, unpack_dir)
                theme_json_path = find_theme_config_path(content_path)
                if not theme_json_path:
                    raise AppError("themes.archive_not_found")
                self._install_theme_from_dir(os.path.dirname(theme_json_path))
            except Exception as e:
                logging.error(
                    f"UrlInstallThread: Error extracting theme: {e}", exc_info=True
                )
                self.finished.emit(False, tr("themes.installation_error", error=str(e)))

    def _check_redirect(self, archive_path: str, temp_dir: str) -> bool:
        try:
            with tempfile.TemporaryDirectory(prefix="g3m-redirect-check-") as unpack_dir:
                content_path = self._unpack_content_path(
                    archive_path, unpack_dir, use_shutil=False
                )
                files_in_root = os.listdir(content_path)
                redirect_config_path = None
                if MOD_CONFIG_FILENAME in files_in_root and len(files_in_root) == 1:
                    redirect_config_path = os.path.join(
                        content_path, MOD_CONFIG_FILENAME
                    )
                if redirect_config_path:
                    try:
                        with open(redirect_config_path, encoding="utf-8") as f:
                            redirect_config = json.load(f)
                        redirect_url = (
                            redirect_config.get("dm_url")
                            or redirect_config.get("homepage")
                            or redirect_config.get("external_url")
                            or redirect_config.get("download_url")
                        )
                        if redirect_url:
                            self.status.emit(
                                tr("status.deltamod_redirect_found"),
                                UI_COLORS["status_info"],
                            )
                            self.progress.emit(0)
                            self._process_deltamod_archive(redirect_url)
                            return True
                    except Exception as e:
                        logging.warning(
                            f"UrlInstallThread: Error reading redirect config: {e}"
                        )
        except Exception as e:
            logging.warning(f"UrlInstallThread: Error checking redirect: {e}")
        return False

    @staticmethod
    def _try_remove_file(path: str) -> None:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logging.warning(f"UrlInstallThread: Failed to remove file {path}: {e}")

    def _install_mod_from_archive(self, archive_path: str, temp_dir: str):
        try:
            with tempfile.TemporaryDirectory(prefix="g3m-url-unpack-") as unpack_dir:
                content_path = self._unpack_content_path(archive_path, unpack_dir)
                files_in_root = os.listdir(content_path)
                mod_name = None
                if has_deltamod_info_file(files_in_root):
                    self.status.emit(
                        tr("status.deltamod_archive_detected_url"),
                        UI_COLORS["status_info"],
                    )
                    from adapters.deltamod_adapter import DeltamodConverter

                    new_mod_path = DeltamodConverter(
                        content_path, self.main_window.app_state.mods_dir
                    ).convert()
                    if not new_mod_path:
                        raise AppError("errors.deltamod_conversion_failed_url")
                    mod_name = os.path.basename(new_mod_path)
                elif MOD_CONFIG_FILENAME in files_in_root:
                    self.status.emit(
                        tr("status.installing_mod"), UI_COLORS["status_info"]
                    )
                    mod_dir = self._install_g3m_mod_from_path(content_path)
                    if not mod_dir:
                        raise AppError("errors.mod_installation_failed")
                    mod_name = os.path.basename(mod_dir)
                else:
                    raise AppError("errors.unsupported_mod_format_url")
                self._try_remove_file(archive_path)
                self.finished.emit(
                    True, tr("status.install_complete_success", mod_name=mod_name)
                )
        except Exception as e:
            logging.error(f"UrlInstallThread: Error installing mod: {e}", exc_info=True)
            self.finished.emit(False, str(e))
