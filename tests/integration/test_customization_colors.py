import re
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ui.common.styling import get_theme_color, rgba_from_color


def _collect_color_issues(customizable_patterns, special_patterns, allow_line):
    ui_dir = Path("src/ui").resolve()
    if not ui_dir.exists():
        pytest.skip("src/ui directory not found")
    issues = []
    for py_file in ui_dir.rglob("*.py"):
        if "mockup" in py_file.name.lower():
            continue
        try:
            for line_num, line in enumerate(
                py_file.read_text(encoding="utf-8").split("\n"), 1
            ):
                stripped = line.strip()
                if stripped.startswith("#") or '"""' in line or "'''" in line:
                    continue
                if any(
                    re.search(pattern, line, re.IGNORECASE)
                    for pattern in special_patterns
                ) or allow_line(line):
                    continue
                for pattern, desc in customizable_patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        issues.append(
                            f"{py_file.relative_to(ui_dir.parent.parent)}:{line_num} - {desc}: {line.strip()[:80]}"
                        )
                        break
        except (FileNotFoundError, UnicodeDecodeError) as e:
            pytest.fail(f"Failed to read UI file {py_file}: {e}")
    return issues


def _build_theme_test_window():
    app_window = Mock()
    app_window.background_movie = None
    app_window.background_pixmap = None
    app_window.size.return_value = Mock(width=800, height=600)
    app_window.color_widgets = {
        "hover": Mock(text=lambda: ""),
        "select": Mock(text=lambda: ""),
    }
    app_window.custom_font_family = None
    app_window.status_label = Mock()
    app_window.status_label.setFont = Mock()
    app_window.findChildren = Mock(return_value=[])
    app_window._bg_loader = None
    app_window.tab_widget = Mock()
    app_window.tab_widget.count.return_value = 0
    app_window.tab_widget.tabText = Mock(return_value="")
    app_window.tab_widget.widget = Mock(return_value=None)
    app_window.library_tag_widgets = []
    app_window.chapter_mode_checkbox = Mock()
    app_window.full_install_checkbox = Mock()
    app_window.installed_mods_label = None
    app_window.chapter_tab_buttons = []
    app_window.mod_list_widget = None
    app_window.installed_mods_widget = None
    app_window.search_display = None
    return app_window


class TestCustomizationColors:
    """Tests for customization colors."""
    def test_get_theme_color_with_custom(self):
        """Checks that getting theme color with custom."""
        config = {"custom_main_text_color": "#FF0000"}
        result = get_theme_color(config, "main_text", "#FFFFFF")
        assert result == "#FF0000"

    def test_get_theme_color_without_custom(self):
        """Checks that getting theme color without custom."""
        config = {}
        result = get_theme_color(config, "main_text", "#FFFFFF")
        assert result == "#FFFFFF"

    def test_get_theme_color_with_empty_custom(self):
        """Checks that getting theme color with empty custom."""
        config = {"custom_main_text_color": ""}
        result = get_theme_color(config, "main_text", "#FFFFFF")
        assert result == "#FFFFFF"

    def test_get_theme_color_with_custom_alpha(self):
        """Checks that getting theme color with custom alpha."""
        config = {"custom_main_text_color": "#80FF0000"}
        result = get_theme_color(config, "main_text", "#FFFFFF")
        assert result == "#80FF0000"

    def test_customizable_color_keys(self):
        """Checks that customizableing color keys."""
        config = {
            "custom_main_text_color": "#AAAAAA",
            "custom_background_color": "#BBBBBB",
            "custom_elements_color": "#CCCCCC",
            "custom_border_color": "#DDDDDD",
            "custom_hover_color": "#EEEEEE",
            "custom_select_color": "#ABABAB",
            "custom_secondary_text_color": "#FF00FF",
        }
        assert get_theme_color(config, "main_text", "#FFFFFF") == "#AAAAAA"
        assert get_theme_color(config, "background", "#000000") == "#BBBBBB"
        assert get_theme_color(config, "elements", "#000000") == "#CCCCCC"
        assert get_theme_color(config, "border", "#FFFFFF") == "#DDDDDD"
        assert get_theme_color(config, "hover", "#333333") == "#EEEEEE"
        assert get_theme_color(config, "select", "#444444") == "#ABABAB"
        assert get_theme_color(config, "secondary_text", "#888888") == "#FF00FF"

    def test_rgba_from_color_preserves_explicit_alpha(self):
        """Checks that rgbaing from color preserves explicit alpha."""
        assert rgba_from_color("#8000FF00") == "rgba(0, 255, 0, 128)"

    def test_generate_widget_style_uses_hover_for_hover_border_and_select_for_selected_border(
        self,
    ):
        """Checks that generateing widget style uses hover for hover border and select for selected border."""
        from ui.common.styling import generate_widget_style

        normal = generate_widget_style(
            "frame",
            "#111111",
            "#222222",
            "#333333",
            "#444444",
            "#EEEEEE",
            "#AAAAAA",
        )
        selected = generate_widget_style(
            "frame",
            "#111111",
            "#222222",
            "#333333",
            "#444444",
            "#EEEEEE",
            "#AAAAAA",
            is_selected=True,
        )

        assert "QFrame#frame:hover" in normal
        assert "border-color: #333333;" in normal
        assert "border: 2px solid #444444;" in selected


class TestColorHexDisplayConversion:
    """Tests for customization colors."""
    def test_qt_hex_to_display_hex_moves_alpha_to_end(self):
        """Checks that qting hex to display hex moves alpha to end."""
        from ui.common.styling import qt_hex_to_display_hex

        assert qt_hex_to_display_hex("#8000FF00") == "#00FF0080"

    def test_display_hex_to_qt_hex_moves_alpha_to_start(self):
        """Checks that displaying hex to qt hex moves alpha to start."""
        from ui.common.styling import display_hex_to_qt_hex

        assert display_hex_to_qt_hex("#00FF0080") == "#8000FF00"


class TestColorValidation:
    """Tests for customization colors."""
    def test_settings_service_accepts_argb_hex_color(self, app_state):
        """Checks that settings service accepts argb hex color."""
        from unittest.mock import Mock

        from services.settings_service import SettingsManager

        manager = SettingsManager(app_state, Mock(), Mock())
        assert manager.is_valid_hex_color("#80FF0000")
        assert manager.is_valid_hex_color("#FF0000")
        assert not manager.is_valid_hex_color("#FFF")
        assert not manager.is_valid_hex_color("#GG0000")

    def test_settings_service_saves_display_hex_as_qt_hex(self, app_state):
        """Checks that settings service saves display hex as qt hex."""
        from unittest.mock import Mock

        from services.settings_service import SettingsManager

        manager = SettingsManager(app_state, Mock(), Mock())
        color_widget = Mock()
        color_widget.text.return_value = "#00FF0080"
        manager.on_custom_style_edited({"background": color_widget})
        assert app_state.local_config["custom_background_color"] == "#8000FF00"


class TestColorWidgetLoading:
    """Tests for customization colors."""
    def test_customization_service_loads_qt_hex_as_display_hex(self, app_state):
        """Checks that customization service loads qt hex as display hex."""
        from unittest.mock import Mock

        from services.customization_service import CustomizationManager

        manager = CustomizationManager(app_state)
        app_state.local_config["custom_background_color"] = "#8000FF00"
        widget = Mock()
        manager.load_custom_style_settings({"background": widget})
        widget.setText.assert_called_once_with("#00FF0080")

    def test_background_default_is_loaded_into_text(self, app_state):
        """Checks that background default is loaded into text."""
        from unittest.mock import Mock

        from services.customization_service import CustomizationManager

        manager = CustomizationManager(app_state)
        widget = Mock()
        manager.load_custom_style_settings({"background": widget})
        widget.setText.assert_called_once_with("#282828")


class TestColorDialogBlackHandling:
    """Tests for customization colors."""
    def test_black_color_picker_seed_preserves_alpha(self):
        """Checks that blacking color picker seed preserves alpha."""
        from PyQt6.QtGui import QColor

        from ui.common.color_picker import (
            get_black_color_picker_seed as _get_black_color_picker_seed,
        )

        seeded = _get_black_color_picker_seed(QColor(0, 0, 0, 128))
        assert seeded.red() == 255
        assert seeded.green() == 255
        assert seeded.blue() == 255
        assert seeded.alpha() == 128

    def test_black_color_picker_filter_promotes_black_before_picker_click(self, qapp):
        """Checks that blacking color picker filter promotes black before picker click."""
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QColor
        from PyQt6.QtWidgets import QColorDialog

        from ui.common.color_picker import (
            BlackColorPickerEventFilter as _BlackColorPickerEventFilter,
        )

        dialog = QColorDialog()
        dialog.setCurrentColor(QColor(0, 0, 0, 255))
        event_filter = _BlackColorPickerEventFilter(dialog)
        assert (
            event_filter.eventFilter(None, QEvent(QEvent.Type.MouseButtonPress))
            is False
        )
        promoted = dialog.currentColor()
        assert promoted.red() == 255
        assert promoted.green() == 255
        assert promoted.blue() == 255
        assert promoted.alpha() == 255


class TestNoHardcodedWhiteColors:
    """Tests for customization colors."""
    def test_no_hardcoded_white_colors_in_ui(self):
        """Checks that noing hardcoded white colors in ui."""
        customizable_patterns = [
            ("#[Ff]{6}\\b", "hex color like #FFFFFF"),
            ("\\bwhite\\b", "white keyword"),
            ("#[Ff]{3}\\b", "short hex like #FFF"),
            ("rgba\\(255,\\s*255,\\s*255", "rgba white"),
            ("rgb\\(255,\\s*255,\\s*255\\)", "rgb white"),
        ]
        special_patterns = [
            "#00BFFF",
            "#8A2BE2",
            "\\byellow\\b",
            "\\bgreen\\b",
            "\\bred\\b",
            "\\borange\\b",
            "\\bblue\\b",
            "lightgreen",
            "#4CAF50",
            "#F44336",
            "#da190b",
            "#FFD700",
            "white-space",
            "white-space:",
            "WhiteColor",
            "message_bg_color",
        ]
        issues = _collect_color_issues(
            customizable_patterns,
            special_patterns,
            lambda line: (
                "get_theme_color" in line
                or "fallback=" in line
                or line.strip().startswith("else ")
                or any(
                    word in line.lower()
                    for word in ("white-space", "whitelist", "whiteout")
                )
            ),
        )
        assert not issues, (
            f"Found {len(issues)} potential hardcoded white colors that should use get_theme_color:\n"
            + "\n".join(issues[:30])
        )


class TestNoHardcodedBlackColors:
    """Tests for customization colors."""
    def test_no_hardcoded_black_colors_in_ui(self):
        """Checks that noing hardcoded black colors in ui."""
        customizable_patterns = [
            ("#[0]{6}\\b", "hex black #000000"),
            ("#[0]{3}\\b", "short hex #000"),
            ("\\bblack\\b", "black keyword"),
            ("rgba\\(0,\\s*0,\\s*0[,\\s]", "rgba black"),
            ("rgb\\(0,\\s*0,\\s*0\\)", "rgb black"),
        ]
        special_patterns = [
            "background-color:\\s*black",
            "fill\\(QColor\\([\\'\"]black",
            "outline_color.*black",
        ]
        issues = _collect_color_issues(
            customizable_patterns,
            special_patterns,
            lambda line: (
                "get_theme_color" in line
                or "fallback=" in line
                or line.strip().startswith("else ")
            ),
        )
        assert not issues, (
            f"Found {len(issues)} potential hardcoded black colors:\n"
            + "\n".join(issues[:30])
        )


class TestNoHardcodedGrayColors:
    """Tests for customization colors."""
    def test_no_hardcoded_gray_colors_in_ui(self):
        """Checks that noing hardcoded gray colors in ui."""
        customizable_patterns = [
            ("#[8]{6}\\b", "hex gray #888888"),
            ("#[8]{3}\\b", "short hex #888"),
            ("\\bgray\\b|\\bgrey\\b", "gray/grey keyword"),
            ("rgba\\(128,\\s*128,\\s*128", "rgba gray"),
            ("rgba\\(255,\\s*255,\\s*255,\\s*178\\)", "rgba version text"),
            ("#[5]{6}\\b", "hex dark gray #555555"),
            ("#[4]{6}\\b", "hex medium gray #444444"),
            ("#[3]{6}\\b", "hex light gray #333333"),
        ]
        special_patterns = ["status_info", "#444", "#555", "#333", "#888"]
        issues = _collect_color_issues(
            customizable_patterns,
            special_patterns,
            lambda line: (
                "get_theme_color" in line
                or "fallback=" in line
                or line.strip().startswith("else ")
                or "secondary_text" in line
            ),
        )
        assert not issues, (
            f"Found {len(issues)} potential hardcoded gray colors:\n"
            + "\n".join(issues[:30])
        )


def _build_test_stylesheet(custom_border_radius="7px", **extra):
    from config.style_loader import build_stylesheet, invalidate_stylesheet_cache

    invalidate_stylesheet_cache()
    return build_stylesheet(
        frame_bg_color="rgba(40,40,40,150)",
        elements_color="#222",
        border_color="#039d5b",
        hover_color="#616b78",
        select_color="#ecedef",
        main_text_color="#e8e9eb",
        font_family_main="Arial",
        font_size_main=16,
        font_size_small=12,
        scroll_handle_color="#e8e9eb",
        custom_border_radius=custom_border_radius,
        **extra,
    )


class TestBorderRadius:
    """Tests for customization colors."""
    def test_default_border_radius_defaults_to_seven(self, app_state):
        """Checks that defaulting border radius defaults to seven."""
        from ui.common.styling import get_border_radius

        assert get_border_radius(app_state.local_config) == 7

    def test_clamp_border_radius_caps_to_half_of_minimum_side(self):
        """Checks that clamping border radius caps to half of minimum side."""
        from ui.common.styling import clamp_border_radius

        assert clamp_border_radius(10, width=22, height=22) == 10
        assert clamp_border_radius(11, width=22, height=22) == 11
        assert clamp_border_radius(12, width=22, height=22) == 11
        assert clamp_border_radius(100, width=22, height=22) == 11
        assert clamp_border_radius(12, width=18, height=18, border_width=2) == 11

    def test_settings_defaults_persist_default_border_radius(self, app_state):
        """Checks that settings defaults persist default border radius."""
        from unittest.mock import Mock

        from services.settings_service import SettingsManager

        manager = SettingsManager(app_state, Mock(), Mock())
        manager.ensure_config_defaults()
        assert app_state.local_config["custom_border_radius"] == 7

    def test_border_radius_in_stylesheet(self):
        """Checks that bordering radius in stylesheet."""
        sheet = _build_test_stylesheet("7px")
        assert "border-radius: 7px" in sheet

    def test_button_radii_in_stylesheet_saturate_to_control_geometry(self):
        """Checks that buttoning radii in stylesheet saturate to control geometry."""
        sheet = _build_test_stylesheet("50px")
        button_section = re.search(
            r"\nQPushButton \{(?P<section>.*?)\n\}", sheet, re.DOTALL
        ).group("section")
        top_refresh_section = re.search(
            r"\nQPushButton#topRefreshBtn \{(?P<section>.*?)\n\}", sheet, re.DOTALL
        ).group("section")
        field_section = re.search(
            r"\nQLineEdit \{(?P<section>.*?)\n\}", sheet, re.DOTALL
        ).group("section")
        assert "border-radius: 17px;" in button_section
        assert "border-radius: 22px;" in top_refresh_section
        assert "border-radius: 17px;" in field_section

    def test_title_bar_window_button_radius_uses_safe_scaled_geometry(self):
        """Checks that titleing bar window button radius uses safe scaled geometry."""
        sheet = _build_test_stylesheet("50px", zoom_factor=1.5)
        title_bar_section = re.search(
            r"\nQPushButton#titleBarMinimizeButton, QPushButton#titleBarMaximizeButton, QPushButton#titleBarCloseButton \{(?P<section>.*?)\n\}",
            sheet,
            re.DOTALL,
        ).group("section")
        assert "min-width: 39px;" in title_bar_section
        assert "max-width: 39px;" in title_bar_section
        assert "border-radius: 22px;" in title_bar_section

    def test_checkbox_indicator_radius_saturates_at_safe_circle_value(self):
        """Checks that checkboxing indicator radius saturates at safe circle value."""
        sheet = _build_test_stylesheet("15px")
        checkbox_section = sheet.split("QCheckBox::indicator {", 1)[1].split("}", 1)[0]
        assert "border-radius: 11px;" in checkbox_section
        assert "width: 18px;" in checkbox_section
        assert "height: 18px;" in checkbox_section

    def test_scrollbar_styles_use_custom_radius_and_hide_arrows(self):
        """Checks that scrollbaring styles use custom radius and hide arrows."""
        sheet = _build_test_stylesheet("15px")
        scrollbar_handle_section = sheet.split("QScrollBar::handle:vertical {", 1)[
            1
        ].split("}", 1)[0]
        assert "border-radius: 7px;" in scrollbar_handle_section
        assert "border: none;" in scrollbar_handle_section
        assert "QScrollBar:vertical {" in sheet
        assert "width: 16px;" in sheet
        assert "height: 16px;" in sheet
        assert "QScrollBar::add-line:vertical" in sheet
        assert "QScrollBar::sub-line:vertical" in sheet
        assert "width: 0px;" in sheet
        assert "height: 0px;" in sheet

    def test_apply_scroll_area_chrome_only_reserves_extent_for_visible_vertical_scrollbar(
        self, qapp
    ):
        """Checks that applying scroll area chrome only reserves extent for visible vertical scrollbar."""
        from PyQt6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

        from ui.common.styling import apply_scroll_area_chrome

        container = QWidget()
        container.resize(240, 240)
        layout = QVBoxLayout(container)
        scroll = QScrollArea(container)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)
        content = QWidget()
        content.setMinimumHeight(20)
        scroll.setWidget(content)
        container.show()
        qapp.processEvents()
        assert not scroll.verticalScrollBar().isVisible()
        assert apply_scroll_area_chrome(scroll) == 0
        content.setMinimumHeight(1200)
        qapp.processEvents()
        assert scroll.verticalScrollBar().isVisible()
        assert apply_scroll_area_chrome(scroll) >= 16
        container.deleteLater()

    def test_border_radius_in_theme_export(self, app_state):
        """Checks that bordering radius in theme export."""
        app_state.local_config["custom_border_radius"] = 12
        settings = {
            "custom_border_radius": app_state.local_config.get(
                "custom_border_radius", 0
            )
        }
        assert settings["custom_border_radius"] == 12

    def test_border_radius_config_persistence(self, app_state):
        """Checks that bordering radius config persistence."""
        app_state.local_config["custom_border_radius"] = 5
        assert app_state.local_config.get("custom_border_radius", 0) == 5
        app_state.local_config["custom_border_radius"] = 0
        assert app_state.local_config.get("custom_border_radius", 0) == 0

    def test_border_radius_translucent_backgrounds(self, app_state):
        """Checks that bordering radius translucent backgrounds."""
        from unittest.mock import Mock

        from services.customization_service import CustomizationManager

        cs = CustomizationManager(app_state)
        container = Mock()
        container.objectName.return_value = "mods_browser_background"
        app_state.local_config["custom_border_radius"] = 15
        cs.update_translucent_backgrounds(container)
        call_args = container.setStyleSheet.call_args[0][0]
        assert "border-radius: 15px" in call_args

    def test_translucent_backgrounds_clamp_to_widget_geometry(self, app_state, qapp):
        """Checks that translucenting backgrounds clamp to widget geometry."""
        from PyQt6.QtWidgets import QWidget

        from services.customization_service import CustomizationManager

        cs = CustomizationManager(app_state)
        container = QWidget()
        container.setObjectName("search_mods_background")
        container.resize(40, 20)
        app_state.local_config["custom_border_radius"] = 100
        cs.update_translucent_backgrounds(container)
        assert "border-radius: 10px" in container.styleSheet()

    def test_translucent_backgrounds_preserve_custom_alpha(self, app_state):
        """Checks that translucenting backgrounds preserve custom alpha."""
        from unittest.mock import Mock

        from services.customization_service import CustomizationManager

        cs = CustomizationManager(app_state)
        container = Mock()
        container.objectName.return_value = "mods_browser_background"
        app_state.local_config["custom_background_color"] = "#8000FF00"
        cs.update_translucent_backgrounds(container)
        call_args = container.setStyleSheet.call_args[0][0]
        assert "background-color: rgba(0, 255, 0, 128);" in call_args

    def test_panel_style_handler_refreshes_alpha_and_radius_on_config_change(
        self, app_state, qapp
    ):
        """Checks that paneling style handler refreshes alpha and radius on config change."""
        from PyQt6.QtWidgets import QWidget

        from ui.common.styling import (
            install_panel_style_handler,
            refresh_panel_style,
        )

        container = QWidget()
        container.setObjectName("mods_browser_background")
        container.resize(40, 20)
        app_state.local_config["custom_background_color"] = "#8000FF00"
        app_state.local_config["custom_border_radius"] = 15

        install_panel_style_handler(container, app_state.local_config)
        initial_style = container.styleSheet()
        assert "rgba(0, 255, 0, 128)" in initial_style
        assert "border-radius: 10px" in initial_style

        app_state.local_config["custom_background_color"] = "#4000FF00"
        app_state.local_config["custom_border_radius"] = 6
        assert refresh_panel_style(container) is True
        updated_style = container.styleSheet()
        assert "rgba(0, 255, 0, 64)" in updated_style
        assert "border-radius: 6px" in updated_style
        container.deleteLater()


class TestThemeApplication:
    """Tests for customization colors."""
    def test_theme_applies_customization(self, app_state):
        """Checks that themeing applies customization."""
        from controllers.theme_controller import ThemeController

        feedback_service = Mock()
        settings_service = Mock()
        settings_service.is_valid_hex_color = lambda x: bool(x and x.startswith("#"))
        customization_service = Mock()
        app_window = _build_theme_test_window()
        app_window.app_state = app_state
        app_state.local_config = {
            "custom_main_text_color": "#FF0000",
            "custom_background_color": "#00FF00",
            "custom_elements_color": "#0000FF",
            "custom_border_color": "#FFFF00",
            "ui_scale": 1.0,
        }
        with (
            patch(
                "controllers.theme_controller.DEFAULT_THEME",
                {
                    "background": "images/background.png",
                    "colors": {
                        "main_text": "#FFFFFF",
                        "background": "#000000",
                        "elements": "#333333",
                        "border": "#444444",
                        "hover": "#555555",
                        "select": "#666666",
                    },
                    "font_family": "Arial",
                    "font_size_main": 12,
                    "font_size_small": 10,
                },
            ),
            patch("controllers.theme_controller.BgLoader"),
        ):
            theme_controller = ThemeController(
                app_state,
                feedback_service,
                settings_service,
                customization_service,
                app_window,
            )
            from PyQt6.QtWidgets import QApplication as RealQApplication

            with (
                patch.object(RealQApplication, "instance", return_value=None),
                patch("controllers.theme_controller.QApplication", RealQApplication),
            ):
                app_window.setStyleSheet = Mock()
                theme_controller.apply_theme()
                assert app_window.setStyleSheet.called
                assert customization_service.update_translucent_backgrounds.called

    def test_theme_preserves_custom_background_alpha(self, app_state):
        """Checks that themeing preserves custom background alpha."""
        from controllers.theme_controller import ThemeController

        feedback_service = Mock()
        settings_service = Mock()
        settings_service.is_valid_hex_color = lambda x: bool(x and x.startswith("#"))
        customization_service = Mock()
        app_window = _build_theme_test_window()
        app_window.app_state = app_state
        app_state.local_config = {
            "custom_background_color": "#8000FF00",
            "ui_scale": 1.0,
        }
        with (
            patch(
                "controllers.theme_controller.DEFAULT_THEME",
                {
                    "background": "images/background.png",
                    "colors": {
                        "main_text": "#FFFFFF",
                        "background": "#000000",
                        "elements": "#333333",
                        "border": "#444444",
                        "hover": "#555555",
                        "select": "#666666",
                    },
                    "font_family": "Arial",
                    "font_size_main": 12,
                    "font_size_small": 10,
                },
            ),
            patch("controllers.theme_controller.BgLoader"),
            patch(
                "controllers.theme_controller.build_stylesheet", return_value=""
            ) as build_stylesheet_mock,
        ):
            theme_controller = ThemeController(
                app_state,
                feedback_service,
                settings_service,
                customization_service,
                app_window,
            )
            from PyQt6.QtWidgets import QApplication as RealQApplication

            with (
                patch.object(RealQApplication, "instance", return_value=None),
                patch("controllers.theme_controller.QApplication", RealQApplication),
            ):
                app_window.setStyleSheet = Mock()
                theme_controller.apply_theme()
                kwargs = build_stylesheet_mock.call_args.kwargs
                assert kwargs["frame_bg_color"] == "rgba(0, 255, 0, 128)"
                assert kwargs["tooltip_bg_color"] == "rgba(0, 255, 0, 128)"

    def test_theme_repolishes_title_bar_widgets_on_live_update(self, app_state):
        """Checks that themeing repolishes title bar widgets on live update."""
        from controllers.theme_controller import ThemeController

        feedback_service = Mock()
        settings_service = Mock()
        settings_service.is_valid_hex_color = lambda x: bool(x and x.startswith("#"))
        customization_service = Mock()
        app_window = _build_theme_test_window()
        app_window.app_state = app_state
        app_state.local_config = {"custom_border_radius": 50, "ui_scale": 1.0}

        def _styled_widget():
            widget = Mock()
            widget_style = Mock()
            widget.style.return_value = widget_style
            return widget, widget_style

        title_bar, title_bar_style = _styled_widget()
        left_widget, left_widget_style = _styled_widget()
        right_widget, right_widget_style = _styled_widget()
        help_button, help_button_style = _styled_widget()
        minimize_button, minimize_button_style = _styled_widget()
        maximize_button, maximize_button_style = _styled_widget()
        close_button, close_button_style = _styled_widget()

        title_bar.left_widget = left_widget
        title_bar.right_widget = right_widget
        title_bar.help_button = help_button
        title_bar.minimize_button = minimize_button
        title_bar.maximize_button = maximize_button
        title_bar.close_button = close_button
        app_window.title_bar = title_bar

        with (
            patch(
                "controllers.theme_controller.DEFAULT_THEME",
                {
                    "background": "images/background.png",
                    "colors": {
                        "main_text": "#FFFFFF",
                        "background": "#000000",
                        "elements": "#333333",
                        "border": "#444444",
                        "hover": "#555555",
                        "select": "#666666",
                    },
                    "font_family": "Arial",
                    "font_size_main": 12,
                    "font_size_small": 10,
                },
            ),
            patch("controllers.theme_controller.BgLoader"),
        ):
            theme_controller = ThemeController(
                app_state,
                feedback_service,
                settings_service,
                customization_service,
                app_window,
            )
            from PyQt6.QtWidgets import QApplication as RealQApplication

            with (
                patch.object(RealQApplication, "instance", return_value=None),
                patch("controllers.theme_controller.QApplication", RealQApplication),
            ):
                app_window.setStyleSheet = Mock()
                theme_controller.apply_theme()

        title_bar.apply_metrics.assert_called_once()
        for style_mock in (
            title_bar_style,
            left_widget_style,
            right_widget_style,
            help_button_style,
            minimize_button_style,
            maximize_button_style,
            close_button_style,
        ):
            style_mock.unpolish.assert_called_once()
            style_mock.polish.assert_called_once()

    def test_mod_summary_panel_refreshes_translucent_background_and_radius(
        self, app_state, qapp
    ):
        """Checks that mod summary panel refreshes translucent background and radius."""
        from types import SimpleNamespace

        from ui.widgets.mod.mod_summary_panel import ModSummaryPanel

        app_state.local_config = {
            "custom_background_color": "#8000FF00",
            "custom_border_radius": 8,
            "ui_scale": 1.0,
            "custom_main_text_color": "#FFFFFF",
            "custom_secondary_text_color": "#CCCCCC",
            "custom_border_color": "#039d5b",
            "custom_hover_color": "#616b78",
            "custom_elements_color": "#222222",
        }
        host = SimpleNamespace(local_config=app_state.local_config)
        mod = SimpleNamespace(
            name="Test Mod",
            description="A mod description for theme refresh regression coverage.",
            author="Tester",
            version="1.0.0",
            game_version="1.0",
            added_date="2025-01-01",
            last_updated="2025-01-02",
            playtime_hours=2.5,
            files=None,
            homepage=None,
            description_url=None,
            folder_path=None,
        )

        with (
            patch(
                "ui.widgets.mod.mod_summary_panel.find_mod_readme_files",
                return_value=[],
            ),
            patch(
                "ui.widgets.mod.mod_summary_panel.load_mod_icon_universal"
            ) as load_icon_mock,
        ):
            panel = ModSummaryPanel(host)
            panel.resize(420, 280)
            panel.show_mod(mod)
            load_icon_mock.assert_called()
            initial_panel_style = panel.styleSheet()
            initial_meta_style = panel._meta_label.styleSheet()
            assert "rgba(0, 255, 0, 128)" in initial_panel_style
            assert "border-radius: 8px" in initial_panel_style
            assert "background-color: rgba(0, 255, 0, 128);" in initial_meta_style

            app_state.local_config["custom_background_color"] = "#4000FF00"
            app_state.local_config["custom_border_radius"] = 18
            panel.refresh_theme()

            updated_panel_style = panel.styleSheet()
            updated_meta_style = panel._meta_label.styleSheet()
            assert "rgba(0, 255, 0, 64)" in updated_panel_style
            assert "border-radius: 18px" in updated_panel_style
            assert "background-color: rgba(0, 255, 0, 64);" in updated_meta_style
            panel.deleteLater()
