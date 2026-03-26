import contextlib
import time
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QLabel, QWidget


class TestModWidgets:

    def test_base_mod_widget_creation(self, qapp):
        from unittest.mock import patch

        from ui.widgets.mod.base_mod_widget import BaseModWidget
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = BaseModWidget(None)
            assert widget is not None
            assert isinstance(widget, QWidget)
        widget.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_search_mod_card_widget_recalculates_metrics_when_ui_scale_changes(self, qapp):
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.search_mod_card_widget import SearchModCardWidget
        host = QWidget()
        host.app_state = SimpleNamespace(local_config={'ui_scale': 1.0})
        mod_data = ModInfo(id='test_mod', name='Scaled Search Mod', version='1.0.0', author='Test Author', description='Search card scaling should remain stable across repeated UI scale changes.', game_version='', description_url='', downloads=42, game='deltarune', is_verified=False, last_updated='2024-05-01')
        mod_data.is_gamebanana_mod = False
        with patch('ui.widgets.mod.search_mod_card_widget.load_mod_icon_universal'):
            widget = SearchModCardWidget(mod_data, parent=host)
            base_width = widget.maximumWidth()
            host.app_state.local_config['ui_scale'] = 0.5
            widget._update_style()
            qapp.processEvents()
            small_width = widget.maximumWidth()
            assert small_width < base_width
            assert 'font-size: 15px;' in widget.name_label.styleSheet()
            host.app_state.local_config['ui_scale'] = 1.5
            widget._update_style()
            qapp.processEvents()
            large_width = widget.maximumWidth()
            assert large_width > base_width
            assert widget.name_label.maximumWidth() < widget.maximumWidth()
        widget.deleteLater()
        host.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_installed_mod_widget_scales_with_ui_scale(self, qapp):
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.installed_mod_widget import InstalledModWidget
        host = QWidget()
        host.app_state = SimpleNamespace(local_config={'ui_scale': 1.5})
        mod_data = ModInfo(id='test_mod', name='Scaled Installed Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = InstalledModWidget(mod_data, parent=host, parent_app=host)
            assert widget.height() > 120
            assert widget.icon_label.width() > 80
        widget.deleteLater()
        host.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_card_widget_scales_with_ui_scale(self, qapp):
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.mod_card_widget import ModCardWidget
        host = QWidget()
        host.app_state = SimpleNamespace(local_config={'ui_scale': 1.5})
        mod_data = ModInfo(id='test_mod', name='Scaled Mod', version='1.0.0', author='Test Author', description='Scaled description', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        mod_data.is_gamebanana_mod = False
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = ModCardWidget(mod_data, parent=host)
            assert widget.height() > 120
            assert widget.icon_label.width() > 80
        widget.deleteLater()
        host.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_search_mod_card_widget_expands_on_selection_and_hides_on_focus_loss(self, qapp):
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.search_mod_card_widget import SearchModCardWidget
        host = QWidget()
        other = QWidget(host)
        mod_data = ModInfo(id='test_mod', name='Very Long Mod Name That Should Wrap Across Two Lines And Then Get Ellipsized At The End', version='1.0.0', author='Test Author', description='Test description for the search card.', game_version='', description_url='', downloads=42, game='deltarune', is_verified=False, last_updated='2024-05-01')
        mod_data.is_gamebanana_mod = False
        with patch('ui.widgets.mod.search_mod_card_widget.load_mod_icon_universal'):
            widget = SearchModCardWidget(mod_data, parent=host)
            host.show()
            widget.show()
            other.show()
            qapp.processEvents()
            assert not widget.expanded_widget.isVisible()
            widget.set_selected(True)
            widget.setFocus()
            qapp.processEvents()
            assert widget.expanded_widget.isVisible()
            assert hasattr(widget, 'likes_label')
            assert widget.updated_label.text() == '2024-05-01'
            assert widget.name_label.text()
            assert len(widget.name_label.text().splitlines()) <= 2
            assert not hasattr(widget, 'gb_status_label')
            other.setFocus()
            qapp.processEvents()
            time.sleep(0.05)
            qapp.processEvents()
            assert not widget.expanded_widget.isVisible()
        widget.deleteLater()
        host.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_search_mod_card_widget_metadata_icons_keep_padding_when_scaled(self, qapp):
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.search_mod_card_widget import SearchModCardWidget

        host = QWidget()
        host.app_state = SimpleNamespace(local_config={"ui_scale": 1.5})
        mod_data = ModInfo(id='test_mod', name='Scaled Search Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=42, game='deltarune', is_verified=False, last_updated='2024-05-01')
        mod_data.is_gamebanana_mod = False
        with patch('ui.widgets.mod.search_mod_card_widget.load_mod_icon_universal'):
            widget = SearchModCardWidget(mod_data, parent=host)
            widget._update_style()
            assert widget.updated_icon_label.width() > widget.updated_icon_label.pixmap().width()
            assert widget.likes_icon_label.width() > widget.likes_icon_label.pixmap().width()
        widget.deleteLater()
        host.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_search_display_controller_does_not_reselect_already_selected_card(self):
        from unittest.mock import Mock

        from controllers.search_display_controller import SearchDisplayController
        mod = SimpleNamespace(name='Test Mod')
        card = SimpleNamespace(mod_data=mod, is_selected=True, set_selected=Mock())
        controller = SearchDisplayController.__new__(SearchDisplayController)
        controller._iter_layout_cards = lambda: iter([card])
        controller.clear_all_selections = Mock()
        SearchDisplayController.on_mod_clicked(controller, mod)
        controller.clear_all_selections.assert_not_called()
        card.set_selected.assert_not_called()

    def test_mod_card_widget_has_likes_label(self, qapp):
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.mod_card_widget import ModCardWidget
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=42, like_count=123, game='deltarune', is_verified=False)
        mod_data.is_gamebanana_mod = False
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = ModCardWidget(mod_data, parent=None)
            assert hasattr(widget, 'likes_label')
            assert '123' in widget.likes_label.text()
        widget.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_installed_mod_widget_creation(self, qapp):
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.installed_mod_widget import InstalledModWidget
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = InstalledModWidget(mod_data, parent=None)
            assert widget is not None
            assert isinstance(widget, QWidget)
        widget.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_card_widget_creation(self, qapp):
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.utils.ui_utils import safe_stop_thread
        from ui.widgets.mod.mod_card_widget import ModCardWidget
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        mod_data.is_gamebanana_mod = False
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = ModCardWidget(mod_data, parent=None)
            assert widget is not None
            assert isinstance(widget, QWidget)
        if hasattr(widget, '_compatibility_thread') and widget._compatibility_thread:
            thread = widget._compatibility_thread
            try:
                thread.blockSignals(True)
                with contextlib.suppress(TypeError, RuntimeError):
                    thread.compatibility_checked.disconnect()
                with contextlib.suppress(TypeError, RuntimeError):
                    thread.finished.disconnect()
                thread.blockSignals(False)
            except Exception as e:
                import logging
                logging.debug(f'Thread cleanup error in test: {e}')
            safe_stop_thread(thread, timeout=1000)
        widget.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_selected_mod_card_keeps_select_border_on_hover(self, qapp):
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.mod_card_widget import ModCardWidget

        host = QWidget()
        host.app_state = SimpleNamespace(
            local_config={"custom_hover_color": "#111111", "custom_select_color": "#ABCDEF"}
        )
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        mod_data.is_gamebanana_mod = False
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = ModCardWidget(mod_data, parent=host)
            widget.set_selected(True)
            assert 'QFrame#modCard:hover {' in widget.styleSheet()
            assert 'border-color: #ABCDEF;' in widget.styleSheet()
            assert '#111111' not in widget.styleSheet()
        widget.deleteLater()
        host.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)


class TestCommonWidgets:

    def test_custom_controls_creation(self, qapp):
        from ui.widgets.shared.custom_controls import NoScrollComboBox
        combo = NoScrollComboBox()
        assert combo is not None
        assert isinstance(combo, QWidget)
        combo.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_details_overlay_creation(self, qapp):
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        overlay = ModDetailsOverlay(None, mod_data)
        assert overlay is not None
        assert isinstance(overlay, QWidget)
        assert hasattr(overlay, '_img_label')
        assert hasattr(overlay, '_prev_btn')
        assert hasattr(overlay, '_next_btn')
        assert hasattr(overlay, 'desc_text')
        assert not hasattr(overlay, 'compat_status_label')
        overlay.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_details_overlay_hidden_during_construction(self, qapp):
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        host = QWidget()
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=42, game='deltarune', is_verified=False, created_date='2024-01-01', tags=['gameplay'])
        overlay = ModDetailsOverlay(host, mod_data)
        assert not overlay.isVisible(), 'Overlay must be hidden after construction to prevent child widgets flashing'
        overlay.deleteLater()
        host.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_details_overlay_preloaded_screenshot_displays_on_navigate(self, qapp):
        from PyQt6.QtGui import QImage

        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        overlay = ModDetailsOverlay(None, mod_data)
        overlay._ss_urls = ['https://a.com/1.png', 'https://a.com/2.png', 'https://a.com/3.png']
        overlay._ss_images = [None, None, None]
        overlay._ss_loading = [False, True, False]
        overlay._ss_index = 0
        test_img = QImage(4, 4, QImage.Format.Format_ARGB32)
        test_img.fill(0xFFFF0000)
        overlay._ss_on_preloaded(1, test_img)
        assert overlay._ss_images[1] is test_img
        assert not overlay._ss_loading[1]
        overlay._ss_index = 1
        overlay._ss_on_preloaded(1, test_img)
        assert overlay._img_label.pixmap() is not None and not overlay._img_label.pixmap().isNull(), 'Preloaded screenshot should display when user is viewing that index'
        overlay.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_details_overlay_metadata_order(self, qapp):
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='1.0', description_url='', downloads=42, game='deltarune', is_verified=False, created_date='2024-01-01', gamebanana_category='Category')
        overlay = ModDetailsOverlay(None, mod_data)
        meta_texts = [label.text() for label in overlay.findChildren(QLabel)]

        version_pos = None
        author_pos = None
        for i, text in enumerate(meta_texts):
            if '>1.0.0</span>' in text:
                version_pos = i
            if '>Test Author</span>' in text:
                author_pos = i

        assert version_pos is not None, "Version not found in metadata"
        assert author_pos is not None, "Author not found in metadata"
        assert version_pos < author_pos, f"Version should come before author, but version is at position {version_pos} and author is at position {author_pos}"

        overlay.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    @pytest.mark.parametrize(('downloads', 'expected'), [(0, '0'), (None, '0')])
    def test_mod_details_overlay_shows_downloads(self, qapp, downloads, expected):
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='1.0', description_url='', downloads=downloads, game='deltarune', is_verified=False, created_date='2024-01-01', gamebanana_category='Category')
        overlay = ModDetailsOverlay(None, mod_data)
        meta_texts = [label.text() for label in overlay.findChildren(QLabel)]
        assert any(f'>{expected}</span>' in text for text in meta_texts)
        overlay.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_details_overlay_uses_custom_hover_color(self, qapp):
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={'custom_hover_color': '#123456'})
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        overlay = ModDetailsOverlay(parent, mod_data)
        assert overlay._colors['btn_hover'] == '#123456'
        overlay.deleteLater()
        parent.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_details_overlay_uses_custom_select_color(self, qapp):
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={'custom_select_color': '#654321'})
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        overlay = ModDetailsOverlay(parent, mod_data)
        assert overlay._colors['btn_select'] == '#654321'
        overlay.deleteLater()
        parent.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_details_overlay_update_screenshots(self, qapp):
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        overlay = ModDetailsOverlay(None, mod_data)
        assert len(overlay._ss_urls) == 0
        overlay.update_screenshots(['https://example.com/1.png', 'https://example.com/2.png'])
        assert len(overlay._ss_urls) == 2
        assert overlay._ss_index == 0
        assert overlay._prev_btn.isHidden() == (len(overlay._ss_urls) <= 1)
        overlay.update_screenshots([])
        assert len(overlay._ss_urls) == 0
        overlay.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_details_overlay_initializes_screenshots_from_mod_data(self, qapp):
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False, screenshots_url=['https://example.com/1.png', 'https://example.com/2.png'])
        overlay = ModDetailsOverlay(None, mod_data)
        assert overlay._ss_urls == ['https://example.com/1.png', 'https://example.com/2.png']
        overlay.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_details_overlay_nav(self, qapp):
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        overlay = ModDetailsOverlay(None, mod_data)
        overlay._ss_urls = ['https://a.com/1.png', 'https://a.com/2.png', 'https://a.com/3.png']
        overlay._ss_images = [None, None, None]
        overlay._ss_loading = [False, False, False]
        overlay._ss_index = 0
        overlay._ss_next()
        assert overlay._ss_index == 1
        overlay._ss_next()
        assert overlay._ss_index == 2
        overlay._ss_next()
        assert overlay._ss_index == 0
        overlay._ss_prev()
        assert overlay._ss_index == 2
        overlay.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_details_overlay_reuses_dot_labels_during_navigation(self, qapp):
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        overlay = ModDetailsOverlay(None, mod_data)
        overlay.update_screenshots(['https://a.com/1.png', 'https://a.com/2.png', 'https://a.com/3.png'])
        original_dot_labels = list(overlay._dot_labels)
        overlay._ss_next()
        assert overlay._dot_labels == original_dot_labels
        assert overlay._dot_labels[1].text() == '●'
        overlay.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_summary_panel_keeps_zero_playtime_visible(self, qapp):
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from services.localization_service import tr
        from ui.widgets.mod.mod_summary_panel import ModSummaryPanel

        host = QWidget()
        host.local_config = {}
        mod_data = ModInfo(
            id='test_mod',
            name='Test Mod',
            version='1.0.0',
            author='Test Author',
            description='Test description',
            game_version='1.0',
            description_url='',
            downloads=0,
            game='deltarune',
            is_verified=False,
            playtime_hours=0,
        )
        with patch('ui.widgets.mod.mod_summary_panel.load_mod_icon_universal'):
            panel = ModSummaryPanel(host)
            panel.show_mod(mod_data, is_active=False)
            assert not panel._playtime_widget.isHidden()
            assert panel._playtime_value.text() == f"0 {tr('ui.playtime_hours_suffix')}"
        panel.deleteLater()
        host.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_rich_html_reserves_safe_width_for_inline_media(self):
        from ui.common.rich_html import (
            _build_img_tag,
            _placeholder_resource_width,
            _safe_inline_media_width,
        )
        safe_width = _safe_inline_media_width(300)
        assert safe_width == 290
        assert _placeholder_resource_width(290) == 270
        img_tag = _build_img_tag({'src': 'https://example.com/test.png', 'width': '300'}, 300)
        assert 'width="290"' in img_tag

    def test_rich_html_loading_placeholder_keeps_outer_edges_transparent(self):
        from ui.common.rich_html import _create_loading_placeholder
        placeholder = _create_loading_placeholder(300, 120, 'Loading image...')
        center_y = placeholder.height() // 2
        assert placeholder.pixelColor(0, center_y).alpha() == 0
        assert placeholder.pixelColor(placeholder.width() - 1, center_y).alpha() == 0
        assert placeholder.pixelColor(placeholder.width() - 8, center_y).alpha() == 0
        assert placeholder.pixelColor(placeholder.width() - 16, center_y).alpha() == 0
        assert placeholder.pixelColor(placeholder.width() // 2, center_y).alpha() > 0
