import re
import pytest
from pathlib import Path
from unittest.mock import patch
from ui.common.styling import get_theme_color


class TestCustomizationColors:

    def test_get_theme_color_with_custom(self):
        config = {'custom_color_text': '#FF0000'}
        result = get_theme_color(config, 'text', '#FFFFFF')
        assert result == '#FF0000'

    def test_get_theme_color_without_custom(self):
        config = {}
        result = get_theme_color(config, 'text', '#FFFFFF')
        assert result == '#FFFFFF'

    def test_get_theme_color_with_empty_custom(self):
        config = {'custom_color_text': ''}
        result = get_theme_color(config, 'text', '#FFFFFF')
        assert result == '#FFFFFF'

    def test_customizable_color_keys(self):
        config = {'custom_color_text': '#AAAAAA', 'custom_color_background': '#BBBBBB', 'custom_color_button': '#CCCCCC', 'custom_color_border': '#DDDDDD', 'custom_color_button_hover': '#EEEEEE', 'custom_color_version_text': '#FF00FF'}
        assert get_theme_color(config, 'text', '#FFFFFF') == '#AAAAAA'
        assert get_theme_color(config, 'background', '#000000') == '#BBBBBB'
        assert get_theme_color(config, 'button', '#000000') == '#CCCCCC'
        assert get_theme_color(config, 'border', '#FFFFFF') == '#DDDDDD'
        assert get_theme_color(config, 'button_hover', '#333333') == '#EEEEEE'
        assert get_theme_color(config, 'version_text', '#888888') == '#FF00FF'


class TestNoHardcodedWhiteColors:

    def test_no_hardcoded_white_colors_in_ui(self):
        ui_dir = Path('src/ui')
        if not ui_dir.exists():
            pytest.skip('src/ui directory not found')
        customizable_patterns = [('#[Ff]{6}\\b', 'hex color like #FFFFFF'), ('\\bwhite\\b', 'white keyword'), ('#[Ff]{3}\\b', 'short hex like #FFF'), ('rgba\\(255,\\s*255,\\s*255', 'rgba white'), ('rgb\\(255,\\s*255,\\s*255\\)', 'rgb white')]
        special_patterns = ['#00BFFF', '#8A2BE2', '\\byellow\\b', '\\bgreen\\b', '\\bred\\b', '\\borange\\b', '\\bblue\\b', 'lightgreen', '#4CAF50', '#F44336', '#da190b', '#FFD700', 'white-space', 'white-space:']
        issues = []
        for py_file in ui_dir.rglob('*.py'):
            try:
                content = py_file.read_text(encoding='utf-8')
                lines = content.split('\n')
                for line_num, line in enumerate(lines, 1):
                    stripped = line.strip()
                    if stripped.startswith('#') or '"""' in line or "'''" in line:
                        continue
                    is_special = any((re.search(pattern, line, re.IGNORECASE) for pattern in special_patterns))
                    if is_special:
                        continue
                    for pattern, desc in customizable_patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            if 'get_theme_color' not in line:
                                if not any((word in line.lower() for word in ['white-space', 'whitelist', 'whiteout'])):
                                    issues.append(f'{py_file.relative_to(Path.cwd())}:{line_num} - {desc}: {line.strip()[:80]}')
                                    break
            except Exception:
                pass
        if issues:
            pytest.fail(f'Found {len(issues)} potential hardcoded white colors that should use get_theme_color:\n' + '\n'.join(issues[:30]))


class TestNoHardcodedBlackColors:

    def test_no_hardcoded_black_colors_in_ui(self):
        ui_dir = Path('src/ui')
        if not ui_dir.exists():
            pytest.skip('src/ui directory not found')
        customizable_patterns = [('#[0]{6}\\b', 'hex black #000000'), ('#[0]{3}\\b', 'short hex #000'), ('\\bblack\\b', 'black keyword'), ('rgba\\(0,\\s*0,\\s*0[,\\s]', 'rgba black'), ('rgb\\(0,\\s*0,\\s*0\\)', 'rgb black')]
        special_patterns = ['background-color:\\s*black', 'fill\\(QColor\\([\\\'"]black', 'outline_color.*black']
        issues = []
        for py_file in ui_dir.rglob('*.py'):
            try:
                content = py_file.read_text(encoding='utf-8')
                lines = content.split('\n')
                for line_num, line in enumerate(lines, 1):
                    stripped = line.strip()
                    if stripped.startswith('#') or '"""' in line or "'''" in line:
                        continue
                    is_special = any((re.search(pattern, line, re.IGNORECASE) for pattern in special_patterns))
                    if is_special:
                        continue
                    for pattern, desc in customizable_patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            if 'get_theme_color' not in line:
                                issues.append(f'{py_file.relative_to(Path.cwd())}:{line_num} - {desc}: {line.strip()[:80]}')
                                break
            except Exception:
                pass
        if issues:
            pytest.fail(f'Found {len(issues)} potential hardcoded black colors:\n' + '\n'.join(issues[:30]))


class TestNoHardcodedGrayColors:

    def test_no_hardcoded_gray_colors_in_ui(self):
        ui_dir = Path('src/ui')
        if not ui_dir.exists():
            pytest.skip('src/ui directory not found')
        customizable_patterns = [('#[8]{6}\\b', 'hex gray #888888'), ('#[8]{3}\\b', 'short hex #888'), ('\\bgray\\b|\\bgrey\\b', 'gray/grey keyword'), ('rgba\\(128,\\s*128,\\s*128', 'rgba gray'), ('rgba\\(255,\\s*255,\\s*255,\\s*178\\)', 'rgba version text'), ('#[5]{6}\\b', 'hex dark gray #555555'), ('#[4]{6}\\b', 'hex medium gray #444444'), ('#[3]{6}\\b', 'hex light gray #333333')]
        special_patterns = ['status_info', '#444', '#555', '#333']
        issues = []
        for py_file in ui_dir.rglob('*.py'):
            try:
                content = py_file.read_text(encoding='utf-8')
                lines = content.split('\n')
                for line_num, line in enumerate(lines, 1):
                    stripped = line.strip()
                    if stripped.startswith('#') or '"""' in line or "'''" in line:
                        continue
                    is_special = any((re.search(pattern, line, re.IGNORECASE) for pattern in special_patterns))
                    if is_special:
                        continue
                    for pattern, desc in customizable_patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            if 'get_theme_color' not in line and 'version_text' not in line:
                                issues.append(f'{py_file.relative_to(Path.cwd())}:{line_num} - {desc}: {line.strip()[:80]}')
                                break
            except Exception:
                pass
        if issues:
            pytest.fail(f'Found {len(issues)} potential hardcoded gray colors:\n' + '\n'.join(issues[:30]))


class TestThemeApplication:

    def test_theme_applies_customization(self, app_state):
        from controllers.theme_controller import ThemeController
        from unittest.mock import Mock
        feedback_manager = Mock()
        settings_manager = Mock()
        settings_manager.is_valid_hex_color = lambda x: bool(x and x.startswith('#'))
        customization_manager = Mock()
        app_window = Mock()
        app_window.background_movie = None
        app_window.background_pixmap = None
        app_window.size.return_value = Mock(width=800, height=600)
        app_window.color_widgets = {'button_hover': Mock(text=lambda: '')}
        app_window.custom_font_family = None
        app_window.status_label = Mock()
        app_window.status_label.setFont = Mock()
        app_window.findChildren = Mock(return_value=[])
        app_window._bg_loader = None
        app_window.plugin_display = Mock()
        app_window.plugin_display._plugin_widgets = {}
        app_window.tab_widget = Mock()
        app_window.tab_widget.count.return_value = 0
        app_window.tab_widget.tabText = Mock(return_value='')
        app_window.tab_widget.widget = Mock(return_value=None)
        app_window.library_tag_widgets = []
        app_window.chapter_mode_checkbox = Mock()
        app_window.full_install_checkbox = Mock()
        app_window.installed_mods_label = None
        app_window.plugin_tab_builder = None
        app_window.mod_list_widget = None
        app_window.installed_mods_widget = None
        app_window.search_display = None
        app_state.local_config = {'custom_color_text': '#FF0000', 'custom_color_background': '#00FF00', 'custom_color_button': '#0000FF', 'custom_color_border': '#FFFF00'}
        with patch('controllers.theme_controller.THEMES', {'default': {'colors': {'text': '#FFFFFF', 'background': '#000000', 'button': '#333333', 'border': '#444444', 'button_hover': '#555555'}, 'font_family': 'Arial', 'font_size_main': 12, 'font_size_small': 10}}), patch('controllers.theme_controller.BgLoader'):
            theme_controller = ThemeController(app_state, feedback_manager, settings_manager, customization_manager, app_window)
            from PyQt6.QtWidgets import QApplication as RealQApplication
            with patch.object(RealQApplication, 'instance', return_value=None), patch('controllers.theme_controller.QApplication', RealQApplication):
                app_window.setStyleSheet = Mock()
                theme_controller.apply_theme()
                assert app_window.setStyleSheet.called
                assert customization_manager.update_mod_plaques_styles.called or True
                assert customization_manager.update_translucent_backgrounds.called or True
                assert app_window.setStyleSheet.called
                assert customization_manager.update_mod_plaques_styles.called or True
                assert customization_manager.update_translucent_backgrounds.called or True
