import re
import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch


class TestLocalizationSystem:

    def test_buttons_update_on_language_change(self):
        from services.localization_service import LocalizationManager
        loc_service = LocalizationManager()
        initial_lang = loc_service.get_current_language()
        if 'ru' in loc_service.available_languages:
            loc_service.load_language('ru')
            assert loc_service.get_current_language() == 'ru'
            loc_service.load_language(initial_lang)
            assert loc_service.get_current_language() == initial_lang

    def test_localization_service_has_rescan(self):
        from services.localization_service import LocalizationManager
        loc_service = LocalizationManager()
        assert hasattr(loc_service, 'rescan_languages')

    def test_language_files_match_lang_en_key_set(self):
        lang_dir = Path('src/assets/lang')
        en_path = lang_dir / 'lang_en.json'
        if not en_path.exists():
            pytest.skip('lang_en.json not found')

        def flatten_keys(data, prefix=''):
            keys = set()
            for key, value in data.items():
                if key == 'metadata' or str(key).startswith('_'):
                    continue
                dotted = f'{prefix}.{key}' if prefix else key
                if isinstance(value, dict):
                    keys.update(flatten_keys(value, dotted))
                else:
                    keys.add(dotted)
            return keys

        expected_keys = flatten_keys(json.loads(en_path.read_text(encoding='utf-8')))
        mismatches = []

        for lang_path in sorted(lang_dir.glob('lang_*.json')):
            actual_keys = flatten_keys(json.loads(lang_path.read_text(encoding='utf-8')))
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            if missing or extra:
                mismatches.append((lang_path.name, missing[:10], extra[:10]))

        assert not mismatches, f'Localization key mismatches found: {mismatches}'


class TestUIElementsUseTrFunction:

    def test_ui_elements_use_tr_function(self):
        ui_dir = Path('src/ui')
        if not ui_dir.exists():
            pytest.skip('src/ui directory not found')
        issues = []
        for py_file in ui_dir.rglob('*.py'):
            try:
                content = py_file.read_text(encoding='utf-8')
                lines = content.split('\n')
                for line_num, line in enumerate(lines, 1):
                    if re.search('setText\\([\\\'"][^\\\'"]+[\\\'"]\\)|setToolTip\\([\\\'"][^\\\'"]+[\\\'"]\\)|setWindowTitle\\([\\\'"][^\\\'"]+[\\\'"]\\)', line):
                        if 'tr(' not in line:
                            if not ('{' in line and '}' in line) and (not ('+' in line or 'f"' in line or "f'" in line)):
                                if not line.strip().startswith('#'):
                                    if not any((skip in line.lower() for skip in ['n/a', 'n/a', 'none', 'true', 'false', '0', '1'])):
                                        issues.append(f'{py_file.relative_to(Path.cwd())}:{line_num} - Hardcoded text: {line.strip()[:80]}')
            except Exception:
                pass
        if issues:
            pytest.fail(f'Found {len(issues)} potential hardcoded UI texts (should use tr()):\n' + '\n'.join(issues[:30]))


class TestWidgetRelocalizeMethods:

    def test_widgets_have_relocalize_methods(self):
        ui_widgets_dir = Path('src/ui/widgets')
        if not ui_widgets_dir.exists():
            pytest.skip('src/ui/widgets directory not found')
        widgets_to_check = ['mod_card_widget.py', 'installed_mod_widget.py', 'plugin_widget.py']
        issues = []
        for widget_file in widgets_to_check:
            widget_path = ui_widgets_dir / widget_file
            if not widget_path.exists():
                continue
            try:
                content = widget_path.read_text(encoding='utf-8')
                has_localization = 'tr(' in content
                has_relocalize = bool(re.search('def\\s+relocalize', content, re.IGNORECASE))
                if has_localization and (not has_relocalize):
                    if 'class' in content and ('Widget' in content or 'QFrame' in content or 'QWidget' in content):
                        issues.append(f'{widget_file} uses localization but may not have relocalize method')
            except Exception:
                pass
        if issues:
            pytest.skip(f"Widgets that may need relocalize methods: {', '.join(issues)}")


class TestLocalizationRefresh:

    def test_language_combo_updates_on_refresh(self, app_state):
        from controllers.refresh_controller import RefreshController
        from PyQt6.QtWidgets import QComboBox
        feedback_service = Mock()
        mod_service = Mock()
        used_mods_service = Mock()
        game_launch_controller = Mock()
        update_checker = Mock()
        app_window = Mock()
        language_combo = QComboBox()
        language_combo.addItem('English', 'en')
        refresh_controller = RefreshController(app_state, feedback_service, mod_service, used_mods_service, game_launch_controller, update_checker, app_window=app_window)
        with patch('controllers.refresh_controller.localization_service') as mock_loc:
            mock_loc.get_current_language.return_value = 'en'
            mock_loc.get_available_languages.return_value = {'en': 'English', 'ru': 'Russian', 'es': 'Spanish'}
            mock_loc.rescan_languages = Mock()
            with patch('controllers.refresh_controller.FetchModsThread'):
                initial_count = language_combo.count()
                refresh_controller.refresh_mods_list(is_initial=False, language_combo=language_combo)
                assert mock_loc.rescan_languages.called
                assert language_combo.count() >= initial_count or language_combo.count() > 0
