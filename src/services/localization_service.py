"""Localization management."""

import contextlib
import html
import json
import locale
import logging
import os
import shutil
import tempfile
from collections.abc import Callable

from PyQt6.QtCore import QLibraryInfo
from PyQt6.QtGui import QFontDatabase

from utils.path_utils import get_user_lang_dir, resource_path


class LocalizationManager:
    """Manages application localization."""

    def __init__(self) -> None:
        self.internal_lang_dir = resource_path("assets/lang")
        self.external_lang_dir: str | None = None
        self.strings = {}
        self.fallback_strings = {}
        self.available_languages = {}
        self.current_language = "en"
        self._plugin_strings: dict[str, dict[str, dict]] = {}
        self._external_lang_dir_initialized = False
        self._load_available_languages()
        self._load_fallback_strings()

    def initialize_external_language_dir(self) -> None:
        if self._external_lang_dir_initialized:
            return
        self.external_lang_dir = get_user_lang_dir()
        self._ensure_external_lang_dir()
        self._sync_internal_languages()
        self._load_available_languages()
        self._load_fallback_strings()
        self._external_lang_dir_initialized = True

    def _ensure_external_lang_dir(self) -> None:
        if not self.external_lang_dir:
            self.external_lang_dir = get_user_lang_dir()
        if os.path.isdir(self.external_lang_dir):
            return
        if os.path.exists(self.external_lang_dir):
            backup_path = f"{self.external_lang_dir}.bak"
            try:
                if os.path.exists(backup_path):
                    if os.path.isdir(backup_path):
                        shutil.rmtree(backup_path)
                    else:
                        os.remove(backup_path)
                shutil.move(self.external_lang_dir, backup_path)
            except Exception as e:
                logging.warning(
                    f"Could not move invalid language path {self.external_lang_dir}: {e}"
                )
                with contextlib.suppress(OSError):
                    os.remove(self.external_lang_dir)
        try:
            os.makedirs(self.external_lang_dir, exist_ok=True)
        except FileExistsError:
            self.external_lang_dir = os.path.join(
                tempfile.gettempdir(), "g3m-lang"
            )
            os.makedirs(self.external_lang_dir, exist_ok=True)

    def _load_fallback_strings(self):
        """Preload English strings as fallback to avoid disk reads."""
        en_path = None
        if self.external_lang_dir:
            en_path = os.path.join(self.external_lang_dir, "lang_en.json")
        if not en_path or not os.path.exists(en_path):
            en_path = os.path.join(self.internal_lang_dir, "lang_en.json")
        if os.path.exists(en_path):
            try:
                with open(en_path, encoding="utf-8") as f:
                    self.fallback_strings = json.load(f)
            except Exception as e:
                logging.debug(f"Could not load fallback strings: {e}")

    def _sync_internal_languages(self):
        if not os.path.exists(self.internal_lang_dir):
            return
        for filename in os.listdir(self.internal_lang_dir):
            internal_path = os.path.join(self.internal_lang_dir, filename)
            external_path = os.path.join(self.external_lang_dir, filename)
            if filename.startswith("lang_") and filename.endswith(".json"):
                if not os.path.exists(external_path):
                    try:
                        shutil.copy2(internal_path, external_path)
                    except Exception as e:
                        logging.error(f"Could not copy {filename}: {e}")
                else:
                    try:
                        self._merge_lang_files(internal_path, external_path)
                    except Exception as e:
                        logging.error(f"Could not merge {filename}: {e}")
            else:
                if not os.path.exists(external_path) or (
                    os.path.isfile(internal_path)
                    and os.path.isfile(external_path)
                    and os.path.getsize(internal_path) != os.path.getsize(external_path)
                ):
                    try:
                        if os.path.isdir(internal_path):
                            if os.path.exists(external_path):
                                shutil.rmtree(external_path)
                            shutil.copytree(internal_path, external_path)
                        else:
                            shutil.copy2(internal_path, external_path)
                    except Exception as e:
                        logging.error(f"Could not copy {filename}: {e}")

    def _merge_lang_files(self, internal_path: str, external_path: str):
        with open(internal_path, encoding="utf-8") as f:
            internal_data = json.load(f)
        with open(external_path, encoding="utf-8") as f:
            external_data = json.load(f)
        needs_update = False

        def should_skip_key(key: str) -> bool:
            return key == "metadata" or key.startswith("_")

        def sync_dicts(internal_dict, external_dict):
            nonlocal needs_update
            keys_to_remove = []
            for key in list(external_dict.keys()):
                if should_skip_key(key):
                    continue
                if key not in internal_dict:
                    keys_to_remove.append(key)
                    needs_update = True
            for key in keys_to_remove:
                del external_dict[key]
            for key, internal_value in internal_dict.items():
                if should_skip_key(key):
                    continue
                custom_key = f"_{key}"
                if custom_key in external_dict:
                    continue
                if isinstance(internal_value, dict):
                    if key not in external_dict or not isinstance(
                        external_dict[key], dict
                    ):
                        external_dict[key] = {}
                        needs_update = True
                    sync_dicts(internal_value, external_dict[key])
                elif key not in external_dict or external_dict[key] != internal_value:
                    external_dict[key] = internal_value
                    needs_update = True

        sync_dicts(internal_data, external_data)
        internal_metadata = internal_data.get("metadata", {})
        needs_update = (
            needs_update or external_data.get("metadata", {}) != internal_metadata
        )
        external_data["metadata"] = internal_metadata
        if needs_update:
            with open(external_path, "w", encoding="utf-8") as f:
                json.dump(external_data, f, ensure_ascii=False, indent=2)

    def _load_available_languages(self):
        languages = self._scan_lang_dir(self.internal_lang_dir)
        if self.external_lang_dir and os.path.isdir(self.external_lang_dir):
            languages.update(self._scan_lang_dir(self.external_lang_dir))
        self.available_languages = languages

    def rescan_languages(self):
        self.available_languages.clear()
        self.initialize_external_language_dir()
        self._sync_internal_languages()
        self._load_available_languages()

    def _scan_lang_dir(self, directory: str) -> dict:
        langs = {}
        if not os.path.isdir(directory):
            return langs
        for filename in os.listdir(directory):
            if filename.startswith("lang_") and filename.endswith(".json"):
                lang_code = filename[5:-5]
                lang_path = os.path.join(directory, filename)
                try:
                    with open(lang_path, encoding="utf-8") as f:
                        data = json.load(f)
                    metadata = data.get("metadata", {})
                    font = metadata.get("_font") or metadata.get("font")
                    qt_trans = metadata.get("_qt_translation") or metadata.get(
                        "qt_translation", f"qtbase_{lang_code}"
                    )
                    lang_name = metadata.get("_language_name") or metadata.get(
                        "language_name", lang_code.upper()
                    )
                    langs[lang_code] = {
                        "name": lang_name,
                        "qt_translation": qt_trans,
                        "font": font,
                        "path": lang_path,
                    }
                except (OSError, json.JSONDecodeError) as e:
                    logging.error(
                        f"Error loading or parsing language file {filename}: {e}"
                    )
        return langs

    def get_available_languages(self) -> dict[str, str]:
        return {code: info["name"] for code, info in self.available_languages.items()}

    def get_qt_locale_name(self, language_code: str) -> str:
        return self.available_languages.get(language_code, {}).get(
            "qt_translation", "qtbase_en"
        )

    def get_font_path(self, language_code: str) -> str | None:
        lang_info = self.available_languages.get(language_code)
        if not lang_info or not lang_info.get("font"):
            return None
        font_filename = lang_info["font"]
        lang_file_path = lang_info["path"]
        return os.path.join(os.path.dirname(lang_file_path), font_filename)

    def detect_system_language(self) -> str:
        try:
            system_locale = None
            for getter in (lambda: locale.getlocale(locale.LC_CTYPE), locale.getlocale):
                try:
                    system_locale, _ = getter()
                    if system_locale:
                        break
                except (AttributeError, TypeError, ValueError):
                    pass
            if not system_locale:
                lang_env = (
                    os.environ.get("LANG")
                    or os.environ.get("LC_ALL")
                    or os.environ.get("LC_CTYPE")
                )
                if lang_env:
                    system_locale = lang_env.split(".")[0]
            if system_locale:
                full_code = system_locale.lower().replace("-", "_")
                if full_code in self.available_languages:
                    return full_code
                lang_code = full_code.split("_")[0]
                if lang_code in self.available_languages:
                    return lang_code
        except Exception as e:
            logging.warning(f"Error detecting system language: {e}")
        return "en"

    def load_language(self, language_code: str) -> bool:
        lang_info = self.available_languages.get(language_code)
        if not lang_info:
            internal_path = os.path.join(
                self.internal_lang_dir, f"lang_{language_code}.json"
            )
            if not os.path.exists(internal_path):
                return False
            lang_info = {"path": internal_path}
        lang_file = lang_info["path"]
        try:
            with open(lang_file, encoding="utf-8") as f:
                self.strings = json.load(f)
                self.current_language = language_code
                return True
        except Exception as e:
            logging.error(f"Error loading language {language_code}: {e}")
            return False

    def _resolve_key(self, source: dict, key: str, **kwargs) -> str | None:
        """Traverse nested dict by dotted key, process and format. Returns None on miss."""
        value = source
        try:
            for k in key.split("."):
                value = value[k] if k in value else value[f"_{k}"]
            if not isinstance(value, str):
                return None
            value = self._process_escape_sequences(value)
            if kwargs:
                return value.format(**self._normalize_format_kwargs(kwargs))
            return value
        except (KeyError, TypeError, AttributeError):
            return None

    def _normalize_format_kwargs(self, kwargs: dict) -> dict:
        normalized = {}
        for key, value in kwargs.items():
            if isinstance(value, str):
                normalized[key] = html.unescape(value)
            else:
                normalized[key] = value
        return normalized

    def get_text(self, key: str, **kwargs) -> str:
        plugin_result = self._resolve_plugin_text(key, **kwargs)
        if plugin_result is not None:
            return plugin_result
        result = self._resolve_key(self.strings, key, **kwargs)
        if result is not None:
            return result
        return self._get_fallback_text(key, **kwargs)

    def _get_fallback_text(self, key: str, **kwargs) -> str:
        """Get text from preloaded fallback strings."""
        return self._resolve_key(self.fallback_strings, key, **kwargs) or f"[{key}]"

    _ESCAPE_MAP = {
        "\\n": "\n",
        "\\t": "\t",
        "\\r": "\r",
        '\\"': '"',
        "\\'": "'",
        "\\\\": "\\",
    }

    def _process_escape_sequences(self, text: str) -> str:
        if not text or "\\" not in text:
            return text
        for esc, rep in self._ESCAPE_MAP.items():
            text = text.replace(esc, rep)
        return text

    def get_current_language(self) -> str:
        return self.current_language

    def merge_plugin_strings(
        self, plugin_id: str, language_code: str, strings: dict | None
    ) -> None:
        if not plugin_id or not isinstance(strings, dict):
            return
        self._plugin_strings.setdefault(plugin_id, {})[language_code] = strings

    def clear_plugin_strings(self, plugin_id: str | None = None) -> None:
        if plugin_id:
            self._plugin_strings.pop(plugin_id, None)
            return
        self._plugin_strings.clear()

    def get_plugin_tr(self, plugin_id: str):
        prefix = f"plugins.{plugin_id}."

        def _tr(key: str, **kwargs):
            return self.get_text(
                key if key.startswith(prefix) else f"{prefix}{key}",
                **kwargs,
            )

        return _tr

    def _resolve_plugin_text(self, key: str, **kwargs) -> str | None:
        if not key.startswith("plugins."):
            return None
        parts = key.split(".", 2)
        if len(parts) < 3:
            return None
        plugin_id = parts[1]
        nested_key = parts[2]
        localized = self._plugin_strings.get(plugin_id, {}).get(self.current_language)
        result = self._resolve_key(localized or {}, nested_key, **kwargs)
        if result is not None:
            return result
        fallback = self._plugin_strings.get(plugin_id, {}).get("en")
        return self._resolve_key(fallback or {}, nested_key, **kwargs)

    def load_font(self) -> str | None:
        language = self.get_current_language()
        font_path = self.get_font_path(language)
        if font_path and os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    family_name = families[0]
                    logging.debug(f"Loaded font {font_path} as family: {family_name}")
                    return family_name
                else:
                    logging.warning(f"No font families found for {font_path}")
            else:
                logging.warning(f"Failed to load font {font_path}, addApplicationFont returned -1")
        else:
            logging.debug(f"Font path not found or doesn't exist: {font_path}")
        return None

    def update_qt_locale(self, language_code: str, qt_translator_holder: dict) -> bool:
        from PyQt6.QtCore import QTranslator
        from PyQt6.QtWidgets import QApplication

        qt_locale_name = self.get_qt_locale_name(language_code)
        if not qt_locale_name:
            return False
        app = QApplication.instance()
        if app is None:
            return False
        if qt_translator_holder.get("_qt_translator"):
            app.removeTranslator(qt_translator_holder["_qt_translator"])
        qt_translator_holder["_qt_translator"] = QTranslator()
        if qt_translator_holder["_qt_translator"].load(
            qt_locale_name, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        ):
            app.installTranslator(qt_translator_holder["_qt_translator"])
            return True
        return False

    def initialize_localization(
        self,
        local_config: dict,
        config_path: str,
        write_config_callback: Callable,
        write_json_callback: Callable,
    ) -> str:
        self.initialize_external_language_dir()
        saved_language = local_config.get("language")
        if not saved_language or saved_language not in self.get_available_languages():
            saved_language = self.detect_system_language()
            local_config["language"] = saved_language
            write_json_callback(config_path, local_config)
        if not self.load_language(saved_language):
            saved_language = self.detect_system_language()
            self.load_language(saved_language)
            local_config["language"] = saved_language
            write_config_callback()
        return saved_language


localization_service = LocalizationManager()


def tr(key: str, **kwargs) -> str:
    return localization_service.get_text(key, **kwargs)
