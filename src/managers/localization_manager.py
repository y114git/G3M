import json
import locale
import logging
import os
import shutil
from typing import Dict, Optional, Callable
from utils.path_utils import get_user_lang_dir, resource_path
from PyQt6.QtCore import QLibraryInfo
from PyQt6.QtGui import QFontDatabase


class LocalizationManager:

    def __init__(self):
        self.internal_lang_dir = resource_path('assets/lang')
        self.external_lang_dir = get_user_lang_dir()
        os.makedirs(self.external_lang_dir, exist_ok=True)
        self._sync_internal_languages()
        self.current_language = 'en'
        self.translations = {}
        self.available_languages = {}
        self._load_available_languages()

    def _sync_internal_languages(self):
        if not os.path.exists(self.internal_lang_dir):
            return
        for filename in os.listdir(self.internal_lang_dir):
            internal_path = os.path.join(self.internal_lang_dir, filename)
            external_path = os.path.join(self.external_lang_dir, filename)
            if filename.startswith('lang_') and filename.endswith('.json'):
                if not os.path.exists(external_path):
                    try:
                        shutil.copy2(internal_path, external_path)
                    except Exception as e:
                        logging.error(f"Could not copy internal file '{filename}' to external directory: {e}")
                else:
                    try:
                        self._merge_lang_files(internal_path, external_path)
                    except Exception as e:
                        logging.error(f"Could not merge file '{filename}': {e}")
            elif not os.path.exists(external_path):
                try:
                    if os.path.isdir(internal_path):
                        shutil.copytree(internal_path, external_path)
                    else:
                        shutil.copy2(internal_path, external_path)
                except Exception as e:
                    logging.error(f"Could not copy internal file '{filename}' to external directory: {e}")

    def _merge_lang_files(self, internal_path: str, external_path: str):
        with open(internal_path, 'r', encoding='utf-8') as f:
            internal_data = json.load(f)
        with open(external_path, 'r', encoding='utf-8') as f:
            external_data = json.load(f)
        needs_update = False

        def should_skip_key(key: str) -> bool:
            return key == 'metadata' or key.startswith('_')

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
                custom_key = f'_{key}'
                if custom_key in external_dict:
                    continue
                if isinstance(internal_value, dict):
                    if key not in external_dict or not isinstance(external_dict[key], dict):
                        external_dict[key] = {}
                        needs_update = True
                    sync_dicts(internal_value, external_dict[key])
                elif key not in external_dict or external_dict[key] != internal_value:
                    external_dict[key] = internal_value
                    needs_update = True
        sync_dicts(internal_data, external_data)
        external_data['metadata'] = internal_data.get('metadata', {})
        if needs_update:
            with open(external_path, 'w', encoding='utf-8') as f:
                json.dump(external_data, f, ensure_ascii=False, indent=2)

    def _load_available_languages(self):
        self.available_languages = self._scan_lang_dir(self.external_lang_dir)

    def rescan_languages(self):
        self.available_languages.clear()
        self._sync_internal_languages()
        self._load_available_languages()

    def _scan_lang_dir(self, directory: str) -> Dict:
        langs = {}
        if not os.path.isdir(directory):
            return langs
        for filename in os.listdir(directory):
            if filename.startswith('lang_') and filename.endswith('.json'):
                lang_code = filename[5:-5]
                lang_path = os.path.join(directory, filename)
                try:
                    with open(lang_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    metadata = data.get('metadata', {})
                    font = metadata.get('_font') or metadata.get('font')
                    qt_trans = metadata.get('_qt_translation') or metadata.get('qt_translation', f'qtbase_{lang_code}')
                    lang_name = metadata.get('_language_name') or metadata.get('language_name', lang_code.upper())
                    langs[lang_code] = {'name': lang_name, 'qt_translation': qt_trans, 'font': font, 'path': lang_path}
                except (json.JSONDecodeError, IOError) as e:
                    logging.error(f'Error loading or parsing language file {filename}: {e}')
        return langs

    def get_available_languages(self) -> Dict[str, str]:
        return {code: info['name'] for code, info in self.available_languages.items()}

    def get_qt_translation_name(self, language_code: str) -> str:
        return self.available_languages.get(language_code, {}).get('qt_translation', 'qtbase_en')

    def get_font_path(self, language_code: str) -> Optional[str]:
        lang_info = self.available_languages.get(language_code)
        if not lang_info or not lang_info.get('font'):
            return None
        font_filename = lang_info['font']
        lang_file_path = lang_info['path']
        return os.path.join(os.path.dirname(lang_file_path), font_filename)

    def detect_system_language(self) -> str:
        try:
            system_locale = None
            try:
                system_locale, _ = locale.getlocale(locale.LC_CTYPE)
            except (AttributeError, TypeError, ValueError):
                try:
                    system_locale, _ = locale.getlocale()
                except (AttributeError, TypeError, ValueError):
                    pass
            if not system_locale:
                lang_env = os.environ.get('LANG') or os.environ.get('LC_ALL') or os.environ.get('LC_CTYPE')
                if lang_env:
                    system_locale = lang_env.split('.')[0].split('_')[0]
            if not system_locale:
                try:
                    import locale as locale_module
                    old_locale = locale_module.getlocale()
                    try:
                        locale_module.setlocale(locale_module.LC_ALL, '')
                        system_locale, _ = locale_module.getlocale()
                    finally:
                        if old_locale:
                            locale_module.setlocale(locale_module.LC_ALL, old_locale)
                except Exception:
                    pass
            if system_locale:
                lang_code = system_locale.split('_')[0].lower()
                if lang_code in self.available_languages:
                    return lang_code
        except Exception as e:
            logging.warning(f'Error detecting system language: {e}')
        return 'en'

    def load_language(self, language_code: str) -> bool:
        lang_info = self.available_languages.get(language_code)
        if not lang_info:
            internal_path = os.path.join(self.internal_lang_dir, f'lang_{language_code}.json')
            if not os.path.exists(internal_path):
                return False
            lang_info = {'path': internal_path}
        lang_file = lang_info['path']
        try:
            with open(lang_file, 'r', encoding='utf-8') as f:
                self.translations = json.load(f)
                self.current_language = language_code
                return True
        except Exception as e:
            logging.error(f'Error loading language {language_code}: {e}')
            return False

    def merge_translations(self, new_translations: dict):

        def _update_dict(d, u):
            for k, v in u.items():
                if isinstance(v, dict):
                    d[k] = _update_dict(d.get(k, {}), v)
                else:
                    d[k] = v
            return d
        _update_dict(self.translations, new_translations)

    def merge_plugin_translations(self, plugin_id: str, plugin_translations: dict):
        if plugin_id not in self.translations:
            self.translations[plugin_id] = {}

        def _merge_nested(target: dict, source: dict):
            for key, value in source.items():
                if isinstance(value, dict):
                    if key not in target:
                        target[key] = {}
                    _merge_nested(target[key], value)
                else:
                    target[key] = value
        _merge_nested(self.translations[plugin_id], plugin_translations)

    def get_plugin_tr(self, plugin_id: str):

        def plugin_tr(key: str, **kwargs) -> str:
            prefixed_key = f'{plugin_id}.{key}'
            result = self.get_text(prefixed_key, **kwargs)
            if result == f'[{prefixed_key}]':
                result = self.get_text(key, **kwargs)
            return result
        return plugin_tr

    def get_text(self, key: str, **kwargs) -> str:
        keys = key.split('.')
        value = self.translations
        try:
            for k in keys:
                if k in value:
                    value = value[k]
                elif f'_{k}' in value:
                    value = value[f'_{k}']
                else:
                    raise KeyError(k)
            if not isinstance(value, str):
                return f'[{key}]'
            value = self._process_escape_sequences(value)
            if kwargs:
                return value.format(**kwargs)
            return value
        except (KeyError, TypeError, AttributeError):
            if self.current_language != 'en':
                return _fallback_tr(key, **kwargs)
            return f'[{key}]'

    def _process_escape_sequences(self, text: str) -> str:
        if not text:
            return text
        escape_sequences = {'\\n': '\n', '\\t': '\t', '\\r': '\r', '\\"': '"', "\\'": "'", '\\\\': '\\'}
        result = text
        for escape_seq, replacement in escape_sequences.items():
            result = result.replace(escape_seq, replacement)
        return result

    def get_current_language(self) -> str:
        return self.current_language

    def get_current_language_name(self) -> str:
        return self.available_languages.get(self.current_language, {}).get('name', self.current_language.upper())

    def load_font(self) -> Optional[str]:
        language = self.get_current_language()
        font_path = self.get_font_path(language)
        if font_path and os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    return families[0]
        return None

    def update_qt_translations(self, language_code: str, qt_translator_holder: dict) -> bool:
        from PyQt6.QtCore import QTranslator
        from PyQt6.QtWidgets import QApplication
        qt_translation = self.get_qt_translation_name(language_code)
        if not qt_translation:
            return False
        app = QApplication.instance()
        if app is None:
            return False
        if '_qt_translator' in qt_translator_holder and qt_translator_holder['_qt_translator']:
            app.removeTranslator(qt_translator_holder['_qt_translator'])
        qt_translator_holder['_qt_translator'] = QTranslator()
        if qt_translator_holder['_qt_translator'].load(qt_translation, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(qt_translator_holder['_qt_translator'])
            return True
        return False

    def initialize_localization(self, local_config: dict, config_path: str, write_config_callback: Callable, write_json_callback: Callable) -> str:
        saved_language = local_config.get('language')
        if not saved_language or saved_language not in self.get_available_languages():
            saved_language = self.detect_system_language()
            local_config['language'] = saved_language
            write_json_callback(config_path, local_config)
        if not self.load_language(saved_language):
            saved_language = self.detect_system_language()
            self.load_language(saved_language)
            local_config['language'] = saved_language
            write_config_callback()
        return saved_language


localization_manager = LocalizationManager()


def _fallback_tr(key: str, **kwargs) -> str:
    try:
        en_path = os.path.join(localization_manager.external_lang_dir, 'lang_en.json')
        if not os.path.exists(en_path):
            en_path = os.path.join(localization_manager.internal_lang_dir, 'lang_en.json')
        with open(en_path, 'r', encoding='utf-8') as f:
            en_translations = json.load(f)
        keys = key.split('.')
        value = en_translations
        for k in keys:
            if k in value:
                value = value[k]
            elif f'_{k}' in value:
                value = value[f'_{k}']
            else:
                raise KeyError(k)
        if isinstance(value, str):
            return value.format(**kwargs) if kwargs else value
    except Exception:
        pass
    return f'[{key}]'


def tr(key: str, **kwargs) -> str:
    return localization_manager.get_text(key, **kwargs)
