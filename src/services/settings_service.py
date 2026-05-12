"""Application settings management."""

import contextlib
import json
import logging
import os
import platform
import re
import shutil
import tempfile
import zipfile

from PyQt6 import sip
from PyQt6.QtCore import QObject, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFontDatabase, QGuiApplication
from PyQt6.QtWidgets import QFileDialog, QWidget

from config.config import (
    APP_VERSION,
    THEME_CONFIG_FILENAME,
    THEME_CONFIG_FILENAMES,
    THEME_CONFIG_VERSION,
    UI_COLORS,
)
from config.settings_schema import (
    get_theme_color_key,
)
from models.game_modes import get_all_games
from services.localization_service import LocalizationManager, localization_service, tr
from services.migration_service import (
    migrate_settings_payload,
    normalize_theme_settings,
)
from ui.common.styling import display_hex_to_qt_hex, get_border_radius
from utils.file_utils import get_file_filter
from utils.path_utils import find_theme_config_path


class SettingsManager(QObject):
    """Manages application settings and configuration."""

    settings_changed = pyqtSignal()
    language_changed = pyqtSignal(str)
    theme_changed = pyqtSignal()
    restart_required = pyqtSignal(str)
    status_changed = pyqtSignal(str, str)
    _THEME_COLOR_KEYS = (
        "custom_background_color",
        "custom_elements_color",
        "custom_border_color",
        "custom_hover_color",
        "custom_select_color",
        "custom_main_text_color",
        "custom_secondary_text_color",
    )
    _THEME_FLAG_KEYS = (
        "background_disabled",
        "disable_animations",
        "disable_startup_sound",
    )
    _IMAGE_EXTENSIONS = (
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",
        ".mp4",
        ".webm",
        ".avi",
        ".mkv",
        ".mov",
        ".m4v",
        ".3gp",
        ".mpg",
        ".mpeg",
        ".flv",
        ".wmv",
    )
    _FONT_EXTENSIONS = (".ttf", ".otf")
    _AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac")

    def __init__(
        self,
        app_state,
        feedback_service,
        localization_service: LocalizationManager,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.lang_service = localization_service
        self.parent_widget = parent

    def read_json(self, path: str):
        from utils.file_utils import load_json

        data = load_json(path)
        if not data and os.path.exists(path):
            backup_path = f"{path}.invalid.bak"
            if os.path.exists(backup_path):
                self.feedback_service.update_status(
                    tr("dialogs.corrupted_files_found"), UI_COLORS["status_warning"]
                )
        return data

    def write_json(self, path: str, data):
        try:
            from utils.file_utils import save_json

            save_json(path, data, indent=2)
        except (PermissionError, OSError):
            self._handle_permission_error(os.path.dirname(path))
        except (ValueError, TypeError) as e:
            logging.error(
                f"[SettingsManager] JSON serialization error for {path}: {e}",
                exc_info=True,
            )
            self.feedback_service.update_status(
                tr("errors.file_write_error", error=str(e)), UI_COLORS["status_error"]
            )
        except Exception as e:
            self.feedback_service.update_status(
                tr("errors.file_write_error", error=str(e)), UI_COLORS["status_error"]
            )

    def _handle_permission_error(self, directory: str):
        parent_handler = getattr(self.parent_widget, "_handle_permission_error", None)
        if callable(parent_handler):
            try:
                parent_handler(directory)
                return
            except Exception as e:
                logging.debug(f"Parent permission error handler failed: {e}")
        self.feedback_service.show_message(
            "error", "errors.no_write_permission_for", path=directory
        )

    def _get_audio_paths(self, base_name: str) -> list[str]:
        return [
            os.path.join(self.app_state.config_dir, f"custom_{base_name}{ext}")
            for ext in self._AUDIO_EXTENSIONS
        ]

    def _remove_files(self, paths) -> None:
        for file_path in paths:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logging.debug(
                    f"SettingsManager: failed to remove file {file_path}: {e}",
                    exc_info=True,
                )

    def write_local_config(self):
        ps = getattr(self, "profile_service", None)
        if ps:
            ps.write_local_config()
        else:
            self.write_json(self.app_state.config_path, self.app_state.local_config)

    def ensure_config_defaults(self):
        if migrate_settings_payload(self.app_state.local_config, APP_VERSION):
            self.write_local_config()

    def on_language_changed(self, language_code: str):
        current_language = self.app_state.local_config.get("language", "en")
        if language_code == current_language:
            return
        self.app_state.local_config["language"] = language_code
        self.write_local_config()
        self.language_changed.emit(language_code)

    def _toggle_setting(
        self, key: str, enabled: bool, signal: str = "settings_changed"
    ):
        self.app_state.local_config[key] = enabled
        self.write_local_config()
        if signal:
            getattr(self, signal).emit()

    def on_toggle_beta_updates(self, enabled: bool):
        self._toggle_setting("beta_updates_enabled", enabled)

    def on_toggle_fullscreen(self, enabled: bool):
        self._toggle_setting("fullscreen_enabled", enabled)

    def on_toggle_hide_library_filters(self, enabled: bool):
        self._toggle_setting("hide_library_filters", enabled)

    def on_toggle_steam_launch(self, enabled: bool):
        self._toggle_setting("launch_via_steam", enabled)

    def on_toggle_portproton(self, enabled: bool):
        self._toggle_setting("use_portproton", enabled)

    def on_toggle_dont_hide_window_on_launch(self, enabled: bool):
        self._toggle_setting("dont_hide_window_on_launch", enabled)

    def on_toggle_disable_animations(self, enabled: bool):
        self._toggle_setting("disable_animations", enabled, None)

    def on_toggle_disable_background(self, enabled: bool):
        self._toggle_setting("background_disabled", enabled, "theme_changed")

    def on_toggle_disable_startup_sound(self, enabled: bool):
        self._toggle_setting("disable_startup_sound", enabled, None)

    def on_toggle_pause_background_music_unfocused(self, enabled: bool):
        self._toggle_setting("pause_background_music_unfocused", enabled, None)

    def on_toggle_skip_patching_warnings(self, enabled: bool):
        self._toggle_setting("skip_patching_warnings", enabled)

    def on_toggle_hide_mods_browser_tab(self, enabled: bool):
        self._toggle_setting("hide_mods_browser_tab", enabled, None)

    def on_toggle_hide_library_tab(self, enabled: bool):
        self._toggle_setting("hide_library_tab", enabled, None)

    def on_toggle_show_reset_buttons(self, enabled: bool):
        self._toggle_setting("show_reset_buttons", enabled, None)

    def on_toggle_analytics_opt_in(self, enabled: bool):
        self._toggle_setting("analytics_opt_in_enabled", enabled, None)

    def on_toggle_downloads_no_auto_use(self, enabled: bool):
        self._toggle_setting("downloads_no_auto_use", enabled, None)

    def on_toggle_downloads_delete_after_use(self, enabled: bool):
        self._toggle_setting("downloads_delete_after_use", enabled, None)

    def on_toggle_downloads_save_local_imports(self, enabled: bool):
        self._toggle_setting("downloads_save_local_imports", enabled, None)

    def on_toggle_merge_properties(self, enabled: bool):
        self._toggle_setting("merge_properties", enabled, None)

    def on_toggle_merge_code(self, enabled: bool):
        self._toggle_setting("merge_code", enabled, None)

    def select_portproton_path(self) -> str | None:
        filepath, _ = QFileDialog.getOpenFileName(
            self.parent_widget, tr("ui.select_portproton_path")
        )
        if filepath:
            self._toggle_setting("portproton_path", filepath)
            return filepath
        return None

    def pick_directory(self, title: str, start_dir: str = "") -> str:
        return QFileDialog.getExistingDirectory(
            self.parent_widget,
            title,
            start_dir or os.path.expanduser("~"),
        )

    def prompt_for_game_path(self, is_initial=False) -> bool:
        game = self.app_state.game_mode
        title, message = (
            tr(game.path_select_dialog_key),
            tr(game.path_not_found_dialog_key),
        )
        if is_initial:
            self.feedback_service.show_message(
                "info",
                "dialogs.path_not_found",
                tr("dialogs.game_path_instruction", message=message),
            )
        if platform.system() == "Darwin":
            path, _ = QFileDialog.getOpenFileName(
                self.parent_widget,
                title,
                os.path.expanduser("~"),
                "Application bundle (*.app);;All files (*)",
            )
            if not path:
                path = QFileDialog.getExistingDirectory(
                    self.parent_widget, title, os.path.expanduser("~")
                )
        else:
            path = QFileDialog.getExistingDirectory(
                self.parent_widget, title, os.path.expanduser("~")
            )
        if path:
            corrected_path = path
            if platform.system() == "Darwin" and not path.endswith(".app"):
                app_names = game.macos_app_names
                for app_name in app_names:
                    candidate = os.path.join(path, app_name)
                    if os.path.isdir(candidate):
                        corrected_path = candidate
                        break
            self.app_state.game_mode.set_game_path(
                self.app_state.local_config, corrected_path
            )
            self.write_local_config()
            self.feedback_service.update_status(
                tr("status.game_path_set", path=corrected_path),
                UI_COLORS["status_success"],
            )
            self.settings_changed.emit()
            return True
        return False

    def on_background_button_click(self):
        if self.app_state.local_config.get("custom_background_path"):
            self._remove_custom_background_file()
            self.app_state.local_config["custom_background_path"] = ""
        else:
            filepath, _ = QFileDialog.getOpenFileName(
                self.parent_widget,
                tr("ui.select_background_image"),
                "",
                get_file_filter("background_images"),
            )
            if not filepath:
                return
            try:
                os.makedirs(self.app_state.config_dir, exist_ok=True)
                ext = os.path.splitext(filepath)[1].lower()
                if ext not in self._IMAGE_EXTENSIONS:
                    self.feedback_service.show_message(
                        "warning", "errors.error", tr("errors.invalid_image_format")
                    )
                    return
                self._remove_custom_background_file()
                dest = os.path.join(self.app_state.config_dir, f"custom_background{ext}")
                shutil.copy2(filepath, dest)
                self.app_state.local_config["custom_background_path"] = dest
            except Exception as e:
                logging.error(f"Failed to copy background: {e}", exc_info=True)
                self.feedback_service.show_message(
                    "warning", "errors.error", tr("errors.copy_logo_failed")
                )
                return
        self.write_local_config()
        self.theme_changed.emit()

    def _remove_custom_background_file(self):
        background_path = self.app_state.local_config.get("custom_background_path", "")
        if background_path:
            normalized_background_path = os.path.normcase(os.path.abspath(background_path))
            normalized_config_dir = os.path.normcase(
                os.path.abspath(self.app_state.config_dir)
            )
            background_name = os.path.basename(normalized_background_path)
            if (
                normalized_background_path.startswith(normalized_config_dir + os.sep)
                and background_name.startswith("custom_background.")
                and os.path.exists(normalized_background_path)
            ):
                with contextlib.suppress(OSError):
                    os.remove(normalized_background_path)

        self._remove_files(
            os.path.join(self.app_state.config_dir, f"custom_background{ext}")
            for ext in self._IMAGE_EXTENSIONS
        )

    def _handle_audio_file_click(
        self,
        base_name: str,
        select_dialog_key: str,
        removed_msg_key: str,
        remove_fail_key: str,
        copy_fail_key: str,
        custom_path_getter: str = "",
    ):
        paths = self._get_audio_paths(base_name)
        existing = ""
        if (
            custom_path_getter
            and self.parent_widget
            and hasattr(self.parent_widget, "customization_service")
        ):
            existing = (
                getattr(
                    self.parent_widget.customization_service,
                    custom_path_getter,
                    lambda: "",
                )()
                or ""
            )
        if not existing:
            existing = next((p for p in paths if os.path.exists(p)), "")
        if existing:
            try:
                self._remove_files(paths)
                self.feedback_service.show_message(
                    "info", "dialogs.success", tr(removed_msg_key)
                )
                self.theme_changed.emit()
            except Exception:
                self.feedback_service.show_message(
                    "warning", "errors.error", tr(remove_fail_key)
                )
        else:
            audio_filter = (
                "Audio Files (*.mp3 *.wav *.ogg *.flac *.m4a *.aac);;All Files (*)"
            )
            file_path, _ = QFileDialog.getOpenFileName(
                self.parent_widget, tr(select_dialog_key), "", audio_filter
            )
            if file_path:
                lower = file_path.lower()
                valid_exts = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac")
                if not lower.endswith(valid_exts):
                    self.feedback_service.show_message(
                        "warning",
                        "errors.error",
                        tr("errors.invalid_audio_format", "Unsupported audio format."),
                    )
                    return
                try:
                    os.makedirs(self.app_state.config_dir, exist_ok=True)
                    ext = os.path.splitext(lower)[1]
                    dest = os.path.join(
                        self.app_state.config_dir, f"custom_{base_name}{ext}"
                    )
                    shutil.copy2(file_path, dest)
                    self.theme_changed.emit()
                except Exception as e:
                    logging.error(
                        f"[SettingsManager] Failed to copy {base_name}: {e}",
                        exc_info=True,
                    )
                    self.feedback_service.show_message(
                        "warning", "errors.error", tr(copy_fail_key)
                    )

    def on_background_music_button_click(self):
        self._handle_audio_file_click(
            "background_music",
            "dialogs.select_background_music",
            "dialogs.background_music_removed",
            "errors.remove_background_music_failed",
            "errors.copy_background_music_failed",
        )

    def on_startup_sound_button_click(self):
        self._handle_audio_file_click(
            "startup_sound",
            "dialogs.select_startup_sound",
            "dialogs.startup_sound_removed",
            "errors.remove_startup_sound_failed",
            "errors.copy_startup_sound_failed",
            "get_startup_sound_path",
        )

    def _remove_logo_files(self):
        self._remove_files(
            os.path.join(self.app_state.config_dir, f"custom_logo{ext}")
            for ext in self._IMAGE_EXTENSIONS
        )

    def on_logo_button_click(self):
        existing_logo = ""
        if self.parent_widget and hasattr(self.parent_widget, "customization_service"):
            existing_logo = (
                self.parent_widget.customization_service.get_custom_logo_path()
            )
        if existing_logo:
            try:
                self._remove_logo_files()
                self.feedback_service.show_message(
                    "info", "dialogs.success", tr("dialogs.logo_removed")
                )
                self.theme_changed.emit()
            except Exception:
                self.feedback_service.show_message(
                    "warning", "errors.error", tr("errors.remove_logo_failed")
                )
        else:
            file_path, _ = QFileDialog.getOpenFileName(
                self.parent_widget,
                tr("dialogs.select_logo"),
                "",
                get_file_filter("background_images"),
            )
            if file_path:
                try:
                    os.makedirs(self.app_state.config_dir, exist_ok=True)
                    ext = os.path.splitext(file_path)[1].lower()
                    if ext not in self._IMAGE_EXTENSIONS:
                        self.feedback_service.show_message(
                            "warning", "errors.error", tr("errors.invalid_image_format")
                        )
                        return
                    self._remove_logo_files()
                    shutil.copy2(
                        file_path,
                        os.path.join(self.app_state.config_dir, f"custom_logo{ext}"),
                    )
                    self.theme_changed.emit()
                except Exception:
                    self.feedback_service.show_message(
                        "warning", "errors.error", tr("errors.copy_logo_failed")
                    )

    def _remove_font_files(self):
        self._remove_files(
            os.path.join(self.app_state.config_dir, f"custom_font{ext}")
            for ext in self._FONT_EXTENSIONS
        )

    def on_font_button_click(self):
        cs = getattr(self.parent_widget, "customization_service", None)
        if cs and cs.get_custom_font_path():
            try:
                self._remove_font_files()
                if hasattr(self.parent_widget, "custom_font_family"):
                    self.parent_widget.custom_font_family = (
                        self.lang_service.load_font()
                    )
                self._update_font_button_text()
                self.theme_changed.emit()
            except Exception:
                self.feedback_service.show_message(
                    "warning", "errors.error", tr("errors.remove_font_failed")
                )
        else:
            file_path, _ = QFileDialog.getOpenFileName(
                self.parent_widget,
                tr("dialogs.select_font_file"),
                "",
                f"{tr('file_descriptions.font_files')} (*.ttf *.otf)",
            )
            if not file_path:
                return
            ext = os.path.splitext(file_path)[1].lower()
            if ext not in self._FONT_EXTENSIONS:
                self.feedback_service.show_message(
                    "warning", "errors.error", tr("errors.invalid_font_file")
                )
                return
            try:
                os.makedirs(self.app_state.config_dir, exist_ok=True)
                self._remove_font_files()
                target_path = os.path.join(
                    self.app_state.config_dir, f"custom_font{ext}"
                )
                shutil.copy2(file_path, target_path)

                old_id = (
                    getattr(self.parent_widget, "_custom_font_id", None)
                    if self.parent_widget
                    else None
                )
                if old_id is not None and old_id != -1:
                    QFontDatabase.removeApplicationFont(old_id)

                font_id = QFontDatabase.addApplicationFont(target_path)
                if font_id == -1:
                    logging.error(f"Failed to load font from {target_path}")
                    self.feedback_service.show_message(
                        "warning", "errors.error", tr("errors.invalid_font_file")
                    )
                    with contextlib.suppress(OSError):
                        os.remove(target_path)
                    return

                if self.parent_widget:
                    self.parent_widget._custom_font_id = font_id
                    families = QFontDatabase.applicationFontFamilies(font_id)
                    if families:
                        self.parent_widget.custom_font_family = families[0]
                        logging.info(
                            f"Font loaded successfully: {families[0]} from {target_path}"
                        )
                    else:
                        logging.warning(f"No font families found in {target_path}")

                self._update_font_button_text()
                self.theme_changed.emit()
            except Exception as e:
                logging.error(f"Failed to copy font: {e}", exc_info=True)
                self.feedback_service.show_message(
                    "warning",
                    "errors.error",
                    tr("errors.copy_font_failed", "Failed to copy font"),
                )

    def _update_font_button_text(self):
        btn = getattr(self.parent_widget, "change_font_button", None)
        cs = getattr(self.parent_widget, "customization_service", None)
        if btn and cs:
            btn.setText(cs.get_font_button_text())

    def is_valid_hex_color(self, s: str) -> bool:
        return bool(re.fullmatch(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", s or ""))

    def on_custom_style_edited(self, color_widgets: dict):
        changed = False
        for key, widget in color_widgets.items():
            color = widget.text().strip().upper()
            default_display_hex = (
                (widget.property("default_display_hex") or "").strip().upper()
            )
            if color and self.is_valid_hex_color(color):
                stored_color = (
                    "" if color == default_display_hex else display_hex_to_qt_hex(color)
                )
                config_key = get_theme_color_key(key)
                if self.app_state.local_config.get(config_key, "") != stored_color:
                    self.app_state.local_config[config_key] = stored_color
                    changed = True
                widget.setProperty("last_valid_display_hex", color)
        if changed:
            self.write_local_config()
            self.theme_changed.emit()

    def build_theme_export_settings(self) -> dict:
        settings = {"config_version": THEME_CONFIG_VERSION}
        settings.update(
            {
                key: self.app_state.local_config.get(key, "")
                for key in self._THEME_COLOR_KEYS
            }
        )
        settings.update(
            {
                key: self.app_state.local_config.get(key, False)
                for key in self._THEME_FLAG_KEYS
            }
        )
        settings["custom_border_radius"] = get_border_radius(
            self.app_state.local_config
        )
        return settings

    def iter_theme_export_assets(self):
        assets = [
            (self.app_state.local_config.get("custom_background_path"), "background")
        ]
        if self.parent_widget and hasattr(self.parent_widget, "customization_service"):
            cs = self.parent_widget.customization_service
            assets.extend(
                [
                    (cs.get_background_music_path(), "background_music"),
                    (cs.get_startup_sound_path(), "startup_sound"),
                    (cs.get_custom_logo_path(), "custom_logo"),
                    (cs.get_custom_font_path(), "custom_font"),
                ]
            )
        for path, name in assets:
            if path and os.path.isfile(path):
                yield path, name

    def write_theme_archive(self, theme_file_path: str):
        with zipfile.ZipFile(theme_file_path, "w") as zipf:
            zipf.writestr(
                THEME_CONFIG_FILENAME,
                json.dumps(self.build_theme_export_settings(), indent=2),
            )
            for path, name in self.iter_theme_export_assets():
                zipf.write(path, f"{name}{os.path.splitext(path)[1]}")

    def export_theme(self):
        theme_file_path, _ = QFileDialog.getSaveFileName(
            self.parent_widget,
            tr("dialogs.export_theme_title"),
            "",
            f"{tr('file_descriptions.theme_files')} (*.zip)",
        )
        if not theme_file_path:
            return
        self.write_theme_archive(theme_file_path)
        self.feedback_service.show_message(
            "info", "dialogs.success", tr("dialogs.theme_exported_success")
        )

    def import_theme(self):
        from PyQt6.QtWidgets import QDialog

        from ui.dialogs.import_dialog import ImportDialog

        dialog = ImportDialog(
            self.parent_widget, self.feedback_service, "themes", "*.zip"
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.import_method == "file" and dialog.selected_file:
                self._install_theme_from_file(dialog.selected_file)
            elif dialog.import_method == "url" and dialog.selected_url:
                self._install_theme_from_url(dialog.selected_url)

    def _install_theme_from_file(self, theme_file_path: str):
        try:
            with zipfile.ZipFile(theme_file_path, "r") as zipf:
                archive_names = set(zipf.namelist())
                if not any(
                    name in archive_names or any(
                        archived_name.endswith(f"/{name}") for archived_name in archive_names
                    )
                    for name in THEME_CONFIG_FILENAMES
                ):
                    raise ValueError
        except Exception:
            self.feedback_service.show_message(
                "error", "dialogs.error", tr("dialogs.theme_invalid_archive")
            )
            return

        import shutil

        from utils.path_utils import get_user_themes_dir, resource_path

        theme_dir_abs = os.path.normcase(
            os.path.normpath(os.path.dirname(os.path.abspath(theme_file_path)))
        )

        if theme_dir_abs not in (
            os.path.normcase(os.path.normpath(os.path.abspath(d)))
            for d in (resource_path("assets/themes"), get_user_themes_dir())
        ):
            cb = getattr(self.parent_widget, "do_not_save_theme_checkbox", None)
            if not (cb and cb.isChecked()):
                dest = os.path.join(
                    get_user_themes_dir(), os.path.basename(theme_file_path)
                )
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(theme_file_path, dest)
                if hasattr(self.parent_widget, "theme"):
                    self.parent_widget.theme.init_theme_list()

        try:
            from utils.archive_utils import (
                extract_any_archive,
                unwrap_single_directory_chain,
            )

            with tempfile.TemporaryDirectory() as temp_dir:
                extract_any_archive(theme_file_path, temp_dir)
                content_root = unwrap_single_directory_chain(temp_dir)
                theme_json_path = find_theme_config_path(content_root)
                if not theme_json_path:
                    raise FileNotFoundError(
                        f"{THEME_CONFIG_FILENAME} not found in extracted archive"
                    )
                with open(theme_json_path, encoding="utf-8") as f:
                    theme_settings = normalize_theme_settings(json.load(f))
                for key, value in theme_settings.items():
                    if key != "config_version":
                        self.app_state.local_config[key] = value
                self.app_state.local_config["active_theme_name"] = os.path.splitext(
                    os.path.basename(theme_file_path)
                )[0]

                for base in ("background_music", "startup_sound"):
                    self._remove_files(self._get_audio_paths(base))
                self._remove_logo_files()
                self._remove_font_files()
                self.app_state.local_config["custom_background_path"] = ""

                asset_prefixes = {
                    "background.": "custom_background",
                    "background_music.": "custom_background_music",
                    "startup_sound.": "custom_startup_sound",
                    "custom_logo.": "custom_logo",
                    "custom_font.": "custom_font",
                }

                for filename in os.listdir(content_root):
                    for prefix, dest_name in asset_prefixes.items():
                        if filename.startswith(prefix):
                            ext = os.path.splitext(filename)[1]
                            dest_path = os.path.join(
                                self.app_state.config_dir, f"{dest_name}{ext}"
                            )
                            shutil.copy2(
                                os.path.join(content_root, filename), dest_path
                            )
                            if prefix == "background.":
                                self.app_state.local_config[
                                    "custom_background_path"
                                ] = dest_path
                            break

            self.write_local_config()
            self.theme_changed.emit()
            self.settings_changed.emit()
            self.feedback_service.show_message(
                "info", "dialogs.success", tr("dialogs.theme_imported_success")
            )
        except Exception as e:
            self.feedback_service.show_message(
                "error",
                "dialogs.error",
                tr("dialogs.theme_import_failed", error=str(e)),
            )

    def _install_theme_from_url(self, url: str):
        try:
            from workers.install.theme_install_worker import ThemeInstallWorker

            worker = ThemeInstallWorker(
                url, self.app_state.config_dir, self.app_state, self, self.parent_widget
            )
            worker.status.connect(
                lambda msg, color: self.feedback_service.update_status(msg, color)
            )
            worker.progress.connect(
                lambda p: setattr(self.app_state, "progress_bar_value", p)
            )
            worker.finished.connect(self._on_theme_install_finished)
            self.app_state.is_installing = True
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.current_task = worker
            worker.start()
        except Exception as e:
            logging.error(
                f"SettingsManager: Error installing theme from URL: {e}", exc_info=True
            )
            self.feedback_service.show_message(
                "error", "errors.error", tr("themes.installation_error", error=str(e))
            )

    def _on_theme_install_finished(self, success: bool, message: str):
        self.app_state.reset_install_state()
        if success:
            self.theme_changed.emit()
            self.settings_changed.emit()
            self.feedback_service.update_status(message, "green")
            self.feedback_service.show_message("info", "dialogs.success", message)
        else:
            logging.warning(f"Theme installation failed: {message}")
            self.feedback_service.update_status(message or tr("errors.error"), "red")
            self.feedback_service.show_message("error", "errors.error", message)

    def reset_section(
        self,
        section: str,
        config_keys: set[str],
        reset_actions: set[str],
        has_ui_reset: bool = False,
    ):
        if not (config_keys or reset_actions or has_ui_reset):
            return
        if not self.feedback_service.ask_question(
            "dialogs.reset_settings_confirm_title",
            "dialogs.reset_settings_confirm_text",
            "",
            False,
            section=section,
        ):
            return False
        for action in reset_actions:
            if action == "background":
                self.app_state.local_config.pop("custom_background_path", None)
            elif action == "background_music":
                self._remove_files(self._get_audio_paths("background_music"))
            elif action == "startup_sound":
                self._remove_files(self._get_audio_paths("startup_sound"))
            elif action == "logo":
                self._remove_logo_files()
            elif action == "font":
                self._remove_font_files()
                if hasattr(self.parent_widget, "_custom_font_id"):
                    old_id = self.parent_widget._custom_font_id
                    if old_id is not None and old_id != -1:
                        from PyQt6.QtGui import QFontDatabase

                        QFontDatabase.removeApplicationFont(old_id)
                    self.parent_widget._custom_font_id = None
                if hasattr(self.parent_widget, "custom_font_family"):
                    self.parent_widget.custom_font_family = (
                        self.lang_service.load_font()
                    )
                self._update_font_button_text()
            elif action == "game_paths":
                for game in get_all_games():
                    self.app_state.local_config.pop(game.path_config_key, None)
            elif action == "custom_executables":
                self.app_state.local_config.pop("use_custom_executable", None)
                for game in get_all_games():
                    self.app_state.local_config.pop(game.custom_exec_config_key, None)
            elif action == "portproton_path":
                self.app_state.local_config.pop("portproton_path", None)
        for key in config_keys:
            self.app_state.local_config.pop(key, None)
        language_code = None
        if "language" in config_keys:
            language_code = localization_service.initialize_localization(
                self.app_state.local_config,
                self.app_state.config_path,
                self.write_local_config,
                self.write_json,
            )
        self.ensure_config_defaults()
        self.theme_changed.emit()
        self.settings_changed.emit()
        if language_code:
            self.language_changed.emit(language_code)
        self.feedback_service.show_message(
            "info",
            "dialogs.success",
            tr("status.settings_reset_success", section=section),
        )
        return True

    def disable_direct_launch(self):
        self.app_state.local_config["direct_launch_chapter"] = ""
        self.write_local_config()
        self.settings_changed.emit()

    def _get_saved_window_geometry_state(self) -> dict | None:
        saved = self.app_state.local_config.get("window_geometry_state")
        return saved if isinstance(saved, dict) else None

    def was_window_maximized(self) -> bool:
        saved = self._get_saved_window_geometry_state()
        return bool(saved.get("maximized", False)) if saved else False

    def _get_screen_for_saved_geometry(self, x: int, y: int):
        point = QPoint(x, y)
        for screen in QGuiApplication.screens() or []:
            try:
                if screen.availableGeometry().contains(point):
                    return screen
            except AttributeError:
                continue
        screen_at_point = QGuiApplication.screenAt(point)
        if screen_at_point is not None:
            return screen_at_point
        return None

    def load_window_geometry(
        self, widget: QWidget, *, apply_maximized_state: bool = True
    ) -> bool:
        saved = self._get_saved_window_geometry_state()
        if not saved:
            return False
        try:
            width = int(saved.get("width", 0))
            height = int(saved.get("height", 0))
            x = int(saved.get("x", widget.x()))
            y = int(saved.get("y", widget.y()))
            is_maximized = bool(saved.get("maximized", False))
            screen = (
                self._get_screen_for_saved_geometry(x, y)
                or widget.screen()
                or QGuiApplication.primaryScreen()
            )
            if screen is not None:
                available = screen.availableGeometry()
                min_width = max(widget.minimumWidth(), 640)
                min_height = max(widget.minimumHeight(), 480)
                width = max(min_width, width or widget.width())
                height = max(min_height, height or widget.height())
                if apply_maximized_state or not is_maximized:
                    max_x = max(available.left(), available.right() - width + 1)
                    max_y = max(available.top(), available.bottom() - height + 1)
                    x = min(max(x, available.left()), max_x)
                    y = min(max(y, available.top()), max_y)
            if width > 0 and height > 0:
                widget.resize(width, height)
            widget.move(x, y)
            if apply_maximized_state and is_maximized:
                widget.setWindowState(
                    widget.windowState() | Qt.WindowState.WindowMaximized
                )
        except (TypeError, ValueError, AttributeError) as e:
            logging.debug(f"load_window_geometry: failed: {e}")
            return False
        else:
            return True

    def save_window_geometry(self, widget: QWidget):
        try:
            if widget is None or sip.isdeleted(widget):
                return
            if widget.isMinimized() or widget.isFullScreen():
                return
            geometry = (
                widget.normalGeometry() if widget.isMaximized() else widget.geometry()
            )
            if not geometry.isValid():
                geometry = widget.geometry()
            if not geometry.isValid():
                return
            self.app_state.local_config["window_geometry_state"] = {
                "x": geometry.x(),
                "y": geometry.y(),
                "width": geometry.width(),
                "height": geometry.height(),
                "maximized": widget.isMaximized(),
            }
            self.app_state.local_config.pop("window_geometry", None)
            self.write_local_config()
        except RuntimeError as e:
            logging.debug(f"save_window_geometry: skipped deleted widget: {e}")

    def schedule_geometry_save(self, widget: QWidget, timeout_ms: int = 500):
        self._geometry_save_widget = widget
        if not getattr(self, "_geometry_save_timer", None):
            self._geometry_save_timer = QTimer()
            self._geometry_save_timer.setSingleShot(True)
            self._geometry_save_timer.timeout.connect(self._save_scheduled_geometry)
        else:
            self._geometry_save_timer.stop()
        self._geometry_save_timer.start(timeout_ms)

    def _save_scheduled_geometry(self) -> None:
        self.save_window_geometry(getattr(self, "_geometry_save_widget", None))
        self._geometry_save_widget = None

    def lock_window_size(self, widget: QWidget):
        try:
            sz = widget.size()
            widget.setMinimumSize(sz)
            widget.setMaximumSize(sz)
        except (AttributeError, ValueError) as e:
            logging.debug(f"lock_window_size: failed: {e}")

    def unlock_window_size(self, widget: QWidget):
        try:
            widget.setMinimumSize(0, 0)
            widget.setMaximumSize(16777215, 16777215)
        except (AttributeError, ValueError) as e:
            logging.debug(f"unlock_window_size: failed: {e}")
