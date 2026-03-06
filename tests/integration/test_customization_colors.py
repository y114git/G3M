import re
import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from ui.common.styling import get_theme_color, rgba_from_color


def _collect_color_issues(customizable_patterns, special_patterns, allow_line):
    ui_dir = Path('src/ui').resolve()
    if not ui_dir.exists():
        pytest.skip('src/ui directory not found')
    issues = []
    for py_file in ui_dir.rglob('*.py'):
        try:
            for line_num, line in enumerate(py_file.read_text(encoding='utf-8').split('\n'), 1):
                stripped = line.strip()
                if stripped.startswith('#') or '"""' in line or "'''" in line:
                    continue
                if any(re.search(pattern, line, re.IGNORECASE) for pattern in special_patterns) or allow_line(line):
                    continue
                for pattern, desc in customizable_patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        issues.append(f'{py_file.relative_to(ui_dir.parent.parent)}:{line_num} - {desc}: {line.strip()[:80]}')
                        break
        except (FileNotFoundError, UnicodeDecodeError) as e:
            pytest.fail(f'Failed to read UI file {py_file}: {e}')
    return issues


def _build_theme_test_window():
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
    return app_window


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

    def test_get_theme_color_with_custom_alpha(self):
        config = {'custom_color_text': '#80FF0000'}
        result = get_theme_color(config, 'text', '#FFFFFF')
        assert result == '#80FF0000'

    def test_customizable_color_keys(self):
        config = {'custom_color_text': '#AAAAAA', 'custom_color_background': '#BBBBBB', 'custom_color_button': '#CCCCCC', 'custom_color_border': '#DDDDDD', 'custom_color_button_hover': '#EEEEEE', 'custom_color_secondary_text': '#FF00FF'}
        assert get_theme_color(config, 'text', '#FFFFFF') == '#AAAAAA'
        assert get_theme_color(config, 'background', '#000000') == '#BBBBBB'
        assert get_theme_color(config, 'button', '#000000') == '#CCCCCC'
        assert get_theme_color(config, 'border', '#FFFFFF') == '#DDDDDD'
        assert get_theme_color(config, 'button_hover', '#333333') == '#EEEEEE'
        assert get_theme_color(config, 'secondary_text', '#888888') == '#FF00FF'

    def test_rgba_from_color_preserves_explicit_alpha(self):
        assert rgba_from_color('#8000FF00') == 'rgba(0, 255, 0, 128)'


class TestColorHexDisplayConversion:

    def test_qt_hex_to_display_hex_moves_alpha_to_end(self):
        from ui.common.styling import qt_hex_to_display_hex
        assert qt_hex_to_display_hex('#8000FF00') == '#00FF0080'

    def test_display_hex_to_qt_hex_moves_alpha_to_start(self):
        from ui.common.styling import display_hex_to_qt_hex
        assert display_hex_to_qt_hex('#00FF0080') == '#8000FF00'


class TestColorValidation:

    def test_settings_service_accepts_argb_hex_color(self, app_state):
        from services.settings_service import SettingsManager
        from unittest.mock import Mock
        manager = SettingsManager(app_state, Mock(), Mock())
        assert manager.is_valid_hex_color('#80FF0000')
        assert manager.is_valid_hex_color('#FF0000')
        assert not manager.is_valid_hex_color('#FFF')
        assert not manager.is_valid_hex_color('#GG0000')

    def test_settings_service_saves_display_hex_as_qt_hex(self, app_state):
        from services.settings_service import SettingsManager
        from unittest.mock import Mock
        manager = SettingsManager(app_state, Mock(), Mock())
        color_widget = Mock()
        color_widget.text.return_value = '#00FF0080'
        manager.on_custom_style_edited({'background': color_widget})
        assert app_state.local_config['custom_color_background'] == '#8000FF00'


class TestColorWidgetLoading:

    def test_customization_service_loads_qt_hex_as_display_hex(self, app_state):
        from services.customization_service import CustomizationManager
        from unittest.mock import Mock
        manager = CustomizationManager(app_state)
        app_state.local_config['custom_color_background'] = '#8000FF00'
        widget = Mock()
        manager.load_custom_style_settings({'background': widget})
        widget.setText.assert_called_once_with('#00FF0080')

    def test_background_placeholder_uses_theme_background_default(self, app_state):
        from services.customization_service import CustomizationManager
        from unittest.mock import Mock
        manager = CustomizationManager(app_state)
        widget = Mock()
        manager.load_custom_style_settings({'background': widget})
        widget.setPlaceholderText.assert_called_once_with('#282828')


class TestColorDialogBlackHandling:

    def test_black_color_picker_seed_preserves_alpha(self):
        from core.app_window import _get_black_color_picker_seed
        from PyQt6.QtGui import QColor
        seeded = _get_black_color_picker_seed(QColor(0, 0, 0, 128))
        assert seeded.red() == 255
        assert seeded.green() == 255
        assert seeded.blue() == 255
        assert seeded.alpha() == 128

    def test_black_color_picker_filter_promotes_black_before_picker_click(self, qapp):
        from core.app_window import _BlackColorPickerEventFilter
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QColor
        from PyQt6.QtWidgets import QColorDialog
        dialog = QColorDialog()
        dialog.setCurrentColor(QColor(0, 0, 0, 255))
        event_filter = _BlackColorPickerEventFilter(dialog)
        assert event_filter.eventFilter(None, QEvent(QEvent.Type.MouseButtonPress)) is False
        promoted = dialog.currentColor()
        assert promoted.red() == 255
        assert promoted.green() == 255
        assert promoted.blue() == 255
        assert promoted.alpha() == 255


class TestNoHardcodedWhiteColors:

    def test_no_hardcoded_white_colors_in_ui(self):
        customizable_patterns = [('#[Ff]{6}\\b', 'hex color like #FFFFFF'), ('\\bwhite\\b', 'white keyword'), ('#[Ff]{3}\\b', 'short hex like #FFF'), ('rgba\\(255,\\s*255,\\s*255', 'rgba white'), ('rgb\\(255,\\s*255,\\s*255\\)', 'rgb white')]
        special_patterns = ['#00BFFF', '#8A2BE2', '\\byellow\\b', '\\bgreen\\b', '\\bred\\b', '\\borange\\b', '\\bblue\\b', 'lightgreen', '#4CAF50', '#F44336', '#da190b', '#FFD700', 'white-space', 'white-space:', 'WhiteColor', 'message_bg_color']
        issues = _collect_color_issues(
            customizable_patterns,
            special_patterns,
            lambda line: 'get_theme_color' in line or any(word in line.lower() for word in ('white-space', 'whitelist', 'whiteout')),
        )
        if issues:
            pytest.fail(f'Found {len(issues)} potential hardcoded white colors that should use get_theme_color:\n' + '\n'.join(issues[:30]))


class TestNoHardcodedBlackColors:

    def test_no_hardcoded_black_colors_in_ui(self):
        customizable_patterns = [('#[0]{6}\\b', 'hex black #000000'), ('#[0]{3}\\b', 'short hex #000'), ('\\bblack\\b', 'black keyword'), ('rgba\\(0,\\s*0,\\s*0[,\\s]', 'rgba black'), ('rgb\\(0,\\s*0,\\s*0\\)', 'rgb black')]
        special_patterns = ['background-color:\\s*black', 'fill\\(QColor\\([\\\'"]black', 'outline_color.*black']
        issues = _collect_color_issues(customizable_patterns, special_patterns, lambda line: 'get_theme_color' in line)
        if issues:
            pytest.fail(f'Found {len(issues)} potential hardcoded black colors:\n' + '\n'.join(issues[:30]))


class TestNoHardcodedGrayColors:

    def test_no_hardcoded_gray_colors_in_ui(self):
        customizable_patterns = [('#[8]{6}\\b', 'hex gray #888888'), ('#[8]{3}\\b', 'short hex #888'), ('\\bgray\\b|\\bgrey\\b', 'gray/grey keyword'), ('rgba\\(128,\\s*128,\\s*128', 'rgba gray'), ('rgba\\(255,\\s*255,\\s*255,\\s*178\\)', 'rgba version text'), ('#[5]{6}\\b', 'hex dark gray #555555'), ('#[4]{6}\\b', 'hex medium gray #444444'), ('#[3]{6}\\b', 'hex light gray #333333')]
        special_patterns = ['status_info', '#444', '#555', '#333', '#888']
        issues = _collect_color_issues(
            customizable_patterns,
            special_patterns,
            lambda line: 'get_theme_color' in line or 'secondary_text' in line,
        )
        if issues:
            pytest.fail(f'Found {len(issues)} potential hardcoded gray colors:\n' + '\n'.join(issues[:30]))


class TestBorderRadius:

    def test_default_border_radius_defaults_to_seven(self, app_state):
        from ui.common.styling import get_border_radius
        assert get_border_radius(app_state.local_config) == 7

    def test_clamp_border_radius_caps_to_half_of_minimum_side(self):
        from ui.common.styling import clamp_border_radius
        assert clamp_border_radius(10, width=22, height=22) == 10
        assert clamp_border_radius(11, width=22, height=22) == 11
        assert clamp_border_radius(12, width=22, height=22) == 11
        assert clamp_border_radius(100, width=22, height=22) == 11
        assert clamp_border_radius(12, width=18, height=18, border_width=2) == 11

    def test_settings_migration_persists_default_border_radius(self, app_state):
        from services.settings_service import SettingsManager
        from unittest.mock import Mock
        manager = SettingsManager(app_state, Mock(), Mock())
        manager.migrate_config_if_needed()
        assert app_state.local_config['custom_border_radius'] == 7

    def test_border_radius_in_stylesheet(self):
        from ui.styles import build_stylesheet, invalidate_stylesheet_cache
        invalidate_stylesheet_cache()
        sheet = build_stylesheet(
            frame_bg_color='rgba(40,40,40,150)', button_color='#222',
            border_color='#039d5b', button_hover_color='#616b78',
            main_text_color='#e8e9eb', font_family_main='Arial',
            font_size_main=16, font_size_small=12,
            checkbox_checked_color='#fff', scroll_handle_color='#e8e9eb',
            custom_border_radius='7px',
        )
        assert 'border-radius: 7px' in sheet

    def test_button_radii_in_stylesheet_saturate_to_control_geometry(self):
        from ui.styles import build_stylesheet, invalidate_stylesheet_cache
        invalidate_stylesheet_cache()
        sheet = build_stylesheet(
            frame_bg_color='rgba(40,40,40,150)', button_color='#222',
            border_color='#039d5b', button_hover_color='#616b78',
            main_text_color='#e8e9eb', font_family_main='Arial',
            font_size_main=16, font_size_small=12,
            checkbox_checked_color='#fff', scroll_handle_color='#e8e9eb',
            custom_border_radius='50px',
        )
        button_section = re.search(r'\nQPushButton \{(?P<section>.*?)\n\}', sheet, re.DOTALL).group('section')
        top_refresh_section = re.search(r'\nQPushButton#topRefreshBtn \{(?P<section>.*?)\n\}', sheet, re.DOTALL).group('section')
        field_section = re.search(r'\nQLineEdit \{(?P<section>.*?)\n\}', sheet, re.DOTALL).group('section')
        assert 'border-radius: 17px;' in button_section
        assert 'border-radius: 22px;' in top_refresh_section
        assert 'border-radius: 17px;' in field_section

    def test_checkbox_indicator_radius_saturates_at_safe_circle_value(self):
        from ui.styles import build_stylesheet, invalidate_stylesheet_cache
        invalidate_stylesheet_cache()
        sheet = build_stylesheet(
            frame_bg_color='rgba(40,40,40,150)', button_color='#222',
            border_color='#039d5b', button_hover_color='#616b78',
            main_text_color='#e8e9eb', font_family_main='Arial',
            font_size_main=16, font_size_small=12,
            checkbox_checked_color='#fff', scroll_handle_color='#e8e9eb',
            custom_border_radius='15px',
        )
        checkbox_section = sheet.split('QCheckBox::indicator {', 1)[1].split('}', 1)[0]
        assert 'border-radius: 11px;' in checkbox_section
        assert 'width: 18px;' in checkbox_section
        assert 'height: 18px;' in checkbox_section

    def test_scrollbar_styles_use_custom_radius_and_hide_arrows(self):
        from ui.styles import build_stylesheet, invalidate_stylesheet_cache
        invalidate_stylesheet_cache()
        sheet = build_stylesheet(
            frame_bg_color='rgba(40,40,40,150)', button_color='#222',
            border_color='#039d5b', button_hover_color='#616b78',
            main_text_color='#e8e9eb', font_family_main='Arial',
            font_size_main=16, font_size_small=12,
            checkbox_checked_color='#fff', scroll_handle_color='#e8e9eb',
            custom_border_radius='15px',
        )
        scrollbar_handle_section = sheet.split('QScrollBar::handle:vertical {', 1)[1].split('}', 1)[0]
        assert 'border-radius: 7px;' in scrollbar_handle_section
        assert 'border: none;' in scrollbar_handle_section
        assert 'QScrollBar:vertical {' in sheet
        assert 'width: 16px;' in sheet
        assert 'height: 16px;' in sheet
        assert 'QScrollBar::add-line:vertical' in sheet
        assert 'QScrollBar::sub-line:vertical' in sheet
        assert 'width: 0px;' in sheet
        assert 'height: 0px;' in sheet

    def test_border_radius_in_theme_export(self, app_state):
        app_state.local_config['custom_border_radius'] = 12
        settings = {'custom_border_radius': app_state.local_config.get('custom_border_radius', 0)}
        assert settings['custom_border_radius'] == 12

    def test_border_radius_config_persistence(self, app_state):
        app_state.local_config['custom_border_radius'] = 5
        assert app_state.local_config.get('custom_border_radius', 0) == 5
        app_state.local_config['custom_border_radius'] = 0
        assert app_state.local_config.get('custom_border_radius', 0) == 0

    def test_border_radius_translucent_backgrounds(self, app_state):
        from services.customization_service import CustomizationManager
        from unittest.mock import Mock
        cs = CustomizationManager(app_state)
        container = Mock()
        container.objectName.return_value = 'search_mods_background'
        app_state.local_config['custom_border_radius'] = 15
        cs.update_translucent_backgrounds(container)
        call_args = container.setStyleSheet.call_args[0][0]
        assert 'border-radius: 15px' in call_args

    def test_translucent_backgrounds_clamp_to_widget_geometry(self, app_state, qapp):
        from services.customization_service import CustomizationManager
        from PyQt6.QtWidgets import QWidget
        cs = CustomizationManager(app_state)
        container = QWidget()
        container.setObjectName('search_mods_background')
        container.resize(40, 20)
        app_state.local_config['custom_border_radius'] = 100
        cs.update_translucent_backgrounds(container)
        assert 'border-radius: 10px' in container.styleSheet()

    def test_translucent_backgrounds_preserve_custom_alpha(self, app_state):
        from services.customization_service import CustomizationManager
        from unittest.mock import Mock
        cs = CustomizationManager(app_state)
        container = Mock()
        container.objectName.return_value = 'search_mods_background'
        app_state.local_config['custom_color_background'] = '#8000FF00'
        cs.update_translucent_backgrounds(container)
        call_args = container.setStyleSheet.call_args[0][0]
        assert 'background-color: rgba(0, 255, 0, 128);' in call_args


class TestThemeApplication:

    def test_theme_applies_customization(self, app_state):
        from controllers.theme_controller import ThemeController
        feedback_service = Mock()
        settings_service = Mock()
        settings_service.is_valid_hex_color = lambda x: bool(x and x.startswith('#'))
        customization_service = Mock()
        app_window = _build_theme_test_window()
        app_state.local_config = {'custom_color_text': '#FF0000', 'custom_color_background': '#00FF00', 'custom_color_button': '#0000FF', 'custom_color_border': '#FFFF00'}
        with patch('controllers.theme_controller.THEMES', {'default': {'background': 'images/background.png', 'colors': {'text': '#FFFFFF', 'background': '#000000', 'button': '#333333', 'border': '#444444', 'button_hover': '#555555'}, 'font_family': 'Arial', 'font_size_main': 12, 'font_size_small': 10}}), patch('controllers.theme_controller.BgLoader'):
            theme_controller = ThemeController(app_state, feedback_service, settings_service, customization_service, app_window)
            from PyQt6.QtWidgets import QApplication as RealQApplication
            with patch.object(RealQApplication, 'instance', return_value=None), patch('controllers.theme_controller.QApplication', RealQApplication):
                app_window.setStyleSheet = Mock()
                theme_controller.apply_theme()
                assert app_window.setStyleSheet.called
                assert customization_service.update_translucent_backgrounds.called

    def test_theme_preserves_custom_background_alpha(self, app_state):
        from controllers.theme_controller import ThemeController
        feedback_service = Mock()
        settings_service = Mock()
        settings_service.is_valid_hex_color = lambda x: bool(x and x.startswith('#'))
        customization_service = Mock()
        app_window = _build_theme_test_window()
        app_state.local_config = {'custom_color_background': '#8000FF00'}
        with patch('controllers.theme_controller.THEMES', {'default': {'background': 'images/background.png', 'colors': {'text': '#FFFFFF', 'background': '#000000', 'button': '#333333', 'border': '#444444', 'button_hover': '#555555'}, 'font_family': 'Arial', 'font_size_main': 12, 'font_size_small': 10}}), patch('controllers.theme_controller.BgLoader'), patch('controllers.theme_controller.build_stylesheet', return_value='') as build_stylesheet_mock:
            theme_controller = ThemeController(app_state, feedback_service, settings_service, customization_service, app_window)
            from PyQt6.QtWidgets import QApplication as RealQApplication
            with patch.object(RealQApplication, 'instance', return_value=None), patch('controllers.theme_controller.QApplication', RealQApplication):
                app_window.setStyleSheet = Mock()
                theme_controller.apply_theme()
                kwargs = build_stylesheet_mock.call_args.kwargs
                assert kwargs['frame_bg_color'] == 'rgba(0, 255, 0, 128)'
                assert kwargs['tooltip_bg_color'] == 'rgba(0, 255, 0, 128)'
