import json
import locale
import os
from typing import Dict, Optional

class LocalizationManager:

    def __init__(self, lang_dir: Optional[str]=None):
        self.lang_dir = lang_dir or os.path.join(os.path.dirname(__file__), 'lang')
        self.current_language = 'en'
        self.translations = {}
        self.available_languages = {}
        self._load_available_languages()

    def _load_available_languages(self):
        if not os.path.exists(self.lang_dir):
            return
        for filename in os.listdir(self.lang_dir):
            if filename.startswith('lang_') and filename.endswith('.json'):
                lang_code = filename[5:-5]
                lang_path = os.path.join(self.lang_dir, filename)
                try:
                    with open(lang_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        metadata = data.get('metadata', {})
                        self.available_languages[lang_code] = {'name': metadata.get('language_name', lang_code.upper()), 'qt_translation': metadata.get('qt_translation', f'qtbase_{lang_code}'), 'language': metadata.get('language', lang_code)}
                except Exception as e:
                    print(f'Error loading language file {filename}: {e}')

    def get_available_languages(self) -> Dict[str, str]:
        return {code: info['name'] for code, info in self.available_languages.items()}

    def get_qt_translation_name(self, language_code: str) -> str:
        return self.available_languages.get(language_code, {}).get('qt_translation', 'qtbase_en')

    def detect_system_language(self) -> str:
        try:
            system_locale = locale.getdefaultlocale()[0]
            if system_locale:
                lang_code = system_locale[:2].lower()
                if lang_code == 'ru' and 'ru' in self.available_languages:
                    return 'ru'
                elif lang_code == 'en' and 'en' in self.available_languages:
                    return 'en'
        except Exception as e:
            print(f'Error detecting system language: {e}')
        return 'en'

    def load_language(self, language_code: str) -> bool:
        if language_code not in self.available_languages:
            return False
        lang_file = os.path.join(self.lang_dir, f'lang_{language_code}.json')
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
_localization_manager = None

def get_localization_manager() -> LocalizationManager:
    global _localization_manager
    if _localization_manager is None:
        _localization_manager = LocalizationManager()
        if 'ru' in _localization_manager.available_languages:
            _localization_manager.load_language('ru')
        elif 'en' in _localization_manager.available_languages:
            _localization_manager.load_language('en')
    return _localization_manager

def tr(key: str, **kwargs) -> str:
    return get_localization_manager().get_text(key, **kwargs)

def init_localization(language_code: Optional[str]=None) -> bool:
    manager = get_localization_manager()
    if language_code is None:
        language_code = 'en'
    return manager.load_language(language_code)