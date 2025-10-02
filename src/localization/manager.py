import json
import locale
import os
import shutil
from typing import Dict, Optional
from utils.path_utils import get_user_lang_dir, resource_path


class LocalizationManager:

    def __init__(self, lang_dir: Optional[str] = None):
        self.internal_lang_dir = resource_path('localization/lang')
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
                internal_version = self._get_lang_version(internal_path)
                external_version = self._get_lang_version(external_path)
                if not external_version or (internal_version and internal_version >= external_version):
                    try:
                        shutil.copy2(internal_path, external_path)
                    except Exception as e:
                        print(f"Could not copy internal file '{filename}' to external directory: {e}")
            elif not os.path.exists(external_path):
                try:
                    if os.path.isdir(internal_path):
                        shutil.copytree(internal_path, external_path)
                    else:
                        shutil.copy2(internal_path, external_path)
                except Exception as e:
                    print(f"Could not copy internal file '{filename}' to external directory: {e}")

    def _get_lang_version(self, file_path: str) -> Optional[str]:
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('metadata', {}).get('version')
        except (json.JSONDecodeError, IOError):
            return None

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
                    langs[lang_code] = {'name': metadata.get('language_name', lang_code.upper()), 'qt_translation': metadata.get('qt_translation', f'qtbase_{lang_code}'), 'font': metadata.get('font'), 'path': lang_path}
                except (json.JSONDecodeError, IOError) as e:
                    print(f'Error loading or parsing language file {filename}: {e}')
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
            system_locale = locale.getdefaultlocale()[0]
            if system_locale:
                lang_code = system_locale[:2].lower()
                if lang_code in self.available_languages:
                    return lang_code
        except Exception as e:
            print(f'Error detecting system language: {e}')
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
            print(f'Error loading language {language_code}: {e}')
            return False

    def get_text(self, key: str, **kwargs) -> str:
        keys = key.split('.')
        value = self.translations
        try:
            for k in keys:
                value = value[k]
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
            value = value[k]
        if isinstance(value, str):
            return value.format(**kwargs) if kwargs else value
    except Exception:
        pass
    return f'[{key}]'


def tr(key: str, **kwargs) -> str:
    return localization_manager.get_text(key, **kwargs)
