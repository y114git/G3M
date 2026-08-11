"""UI tests for test widgets."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest
from PyQt6.QtCore import QMimeData, QUrl
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


def _drain_events(qapp, cycles: int = 3) -> None:
    """Flush pending Qt events after widget cleanup (deleteLater).

    Multiple cycles with short waits ensure deferred deletions and
    signal/slot invocations are fully processed before test teardown.
    """
    wait = cast(Callable[[int], None], QTest.qWait)
    for _ in range(cycles):
        qapp.processEvents()
        wait(5)


def test_clear_layout_widgets_does_not_detach_visible_widgets_as_windows(qapp):
    """Checks that clearing a visible layout cannot flash removed widgets as windows."""
    from ui.common.styling import clear_layout_widgets

    host = QWidget()
    layout = QVBoxLayout(host)
    child = QLabel("Plugin card", host)
    layout.addWidget(child)
    layout.addStretch()
    host.show()
    qapp.processEvents()

    clear_layout_widgets(layout)

    assert child.isWindow() is False
    assert child.isVisible() is False
    host.deleteLater()
    _drain_events(qapp)


class TestModWidgets:
    """Tests for widgets."""
    def test_base_mod_widget_creation(self, qapp):
        """Checks that base mod widget creation."""
        from unittest.mock import patch

        from ui.widgets.mod.base_mod_widget import BaseModWidget
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = BaseModWidget(None)
            assert widget is not None
            assert isinstance(widget, QWidget)
        widget.deleteLater()
        _drain_events(qapp)

    def test_search_mod_card_widget_recalculates_metrics_when_ui_scale_changes(self, qapp):
        """Checks that searching mod card widget recalculates metrics when ui scale changes."""
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.search_mod_card_widget import SearchModCardWidget
        host = QWidget()
        host.app_state = SimpleNamespace(local_config={'ui_scale': 1.0})
        mod_data = ModInfo(id='test_mod', name='Scaled Search Mod', version='1.0.0', author='Test Author', description='Search card scaling should remain stable across repeated UI scale changes.', game_version='', description_url='', downloads=42, game='deltarune', last_updated='2024-05-01')
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
        _drain_events(qapp)

    def test_installed_mod_widget_scales_with_ui_scale(self, qapp):
        """Checks that installed mod widget scales with ui scale."""
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.installed_mod_widget import InstalledModWidget
        host = QWidget()
        host.app_state = SimpleNamespace(local_config={'ui_scale': 1.5})
        mod_data = ModInfo(id='test_mod', name='Scaled Installed Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=0, game='deltarune')
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = InstalledModWidget(mod_data, parent=host, parent_app=host)
            assert widget.height() > 120
            assert widget.icon_label.width() > 80
        widget.deleteLater()
        host.deleteLater()
        _drain_events(qapp)

    def test_mod_card_widget_scales_with_ui_scale(self, qapp):
        """Checks that mod card widget scales with ui scale."""
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.mod_card_widget import ModCardWidget
        host = QWidget()
        host.app_state = SimpleNamespace(local_config={'ui_scale': 1.5})
        mod_data = ModInfo(id='test_mod', name='Scaled Mod', version='1.0.0', author='Test Author', description='Scaled description', game_version='', description_url='', downloads=0, game='deltarune')
        mod_data.is_gamebanana_mod = False
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = ModCardWidget(mod_data, parent=host)
            assert widget.height() > 120
            assert widget.icon_label.width() > 80
        widget.deleteLater()
        host.deleteLater()
        _drain_events(qapp)

    def test_search_mod_card_widget_expands_on_selection_and_hides_on_focus_loss(self, qapp):
        """Checks that searching mod card widget expands on selection and hides on focus loss."""
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.search_mod_card_widget import SearchModCardWidget
        host = QWidget()
        other = QWidget(host)
        mod_data = ModInfo(id='test_mod', name='Very Long Mod Name That Should Wrap Across Two Lines And Then Get Ellipsized At The End', version='1.0.0', author='Test Author', description='Test description for the search card.', game_version='', description_url='', downloads=42, game='deltarune', last_updated='2024-05-01')
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
            assert widget.name_label.minimumHeight() == widget.name_label.maximumHeight()
            assert (
                widget.name_label.minimumHeight()
                >= widget.name_label.fontMetrics().lineSpacing() * 2
            )
            assert (
                widget.name_label.geometry().top()
                >= widget.icon_label.geometry().bottom()
            )
            assert not hasattr(widget, 'gb_status_label')
            other.setFocus()
            qapp.processEvents()
            _drain_events(qapp)
            assert not widget.expanded_widget.isVisible()
        widget.deleteLater()
        host.deleteLater()
        _drain_events(qapp)

    def test_search_mod_card_widget_metadata_icons_keep_padding_when_scaled(self, qapp):
        """Checks that searching mod card widget metadata icons keep padding when scaled."""
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.search_mod_card_widget import SearchModCardWidget

        host = QWidget()
        host.app_state = SimpleNamespace(local_config={"ui_scale": 1.5})
        mod_data = ModInfo(id='test_mod', name='Scaled Search Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=42, game='deltarune', last_updated='2024-05-01')
        mod_data.is_gamebanana_mod = False
        with patch('ui.widgets.mod.search_mod_card_widget.load_mod_icon_universal'):
            widget = SearchModCardWidget(mod_data, parent=host)
            widget._update_style()
            assert widget.updated_icon_label.width() > widget.updated_icon_label.pixmap().width()
            assert widget.likes_icon_label.width() > widget.likes_icon_label.pixmap().width()
        widget.deleteLater()
        host.deleteLater()
        _drain_events(qapp)

    def test_search_display_controller_does_not_reselect_already_selected_card(self):
        """Checks that searching display controller does not reselect already selected card."""
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

    def test_search_display_controller_selects_new_card(self):
        """Checks that searching display controller selects a newly clicked card."""
        from unittest.mock import Mock

        from controllers.search_display_controller import SearchDisplayController

        mod = SimpleNamespace(name="Test Mod")
        card = SimpleNamespace(mod_data=mod, is_selected=False, set_selected=Mock())
        controller = SearchDisplayController.__new__(SearchDisplayController)
        controller.app = SimpleNamespace()
        controller._iter_layout_cards = lambda: iter([card])
        controller.clear_all_selections = Mock()

        SearchDisplayController.on_mod_clicked(controller, mod)

        controller.clear_all_selections.assert_called_once_with(except_widget=card)
        card.set_selected.assert_called_once_with(True)

    def test_mod_summary_restores_local_actions_after_parent_was_hidden(
        self, qapp, tmp_path
    ):
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QWidget

        from ui.widgets.mod.mod_summary_panel import ModSummaryPanel

        host = QWidget()
        host.local_config = {}
        panel = ModSummaryPanel(host)
        host.show()
        qapp.processEvents()
        host.hide()
        panel._actions_widget.hide()

        panel._update_action_visibility(SimpleNamespace(homepage=""), str(tmp_path))

        assert not panel._actions_widget.isHidden()
        assert all(
            not panel._action_buttons[name].isHidden()
            for name in ("edit", "export", "folder", "filerestore", "delete")
        )
        panel.deleteLater()
        host.deleteLater()

    def test_mod_card_widget_has_likes_label(self, qapp):
        """Checks that mod card widget has likes label."""
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.mod_card_widget import ModCardWidget
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=42, like_count=123, game='deltarune')
        mod_data.is_gamebanana_mod = False
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = ModCardWidget(mod_data, parent=None)
            assert hasattr(widget, 'likes_label')
            assert '123' in widget.likes_label.text()
        widget.deleteLater()
        _drain_events(qapp)

    def test_installed_mod_widget_creation(self, qapp):
        """Checks that installed mod widget creation."""
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.installed_mod_widget import InstalledModWidget
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=0, game='deltarune')
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = InstalledModWidget(mod_data, parent=None)
            assert widget is not None
            assert isinstance(widget, QWidget)
        widget.deleteLater()
        _drain_events(qapp)

    def test_mod_card_widget_creation(self, qapp):
        """Checks that mod card widget creation."""
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.mod_card_widget import ModCardWidget
        mod_data = ModInfo(id='gb_mod_999', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=0, game='deltarune')
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'), patch(
            'ui.widgets.mod.mod_card_widget.QTimer.singleShot'
        ) as single_shot:
            widget = ModCardWidget(mod_data, parent=None)
            assert widget is not None
            assert isinstance(widget, QWidget)
        assert single_shot.call_args.args[0] == 350
        assert single_shot.call_args.args[1].__self__ is widget
        widget.deleteLater()
        _drain_events(qapp)

    def test_mod_card_widget_uses_cached_compatibility_without_job(self, qapp):
        from unittest.mock import patch

        from adapters.gamebanana_adapter import GameBananaAPI
        from models.mod_models import ModInfo
        from ui.widgets.mod.mod_card_widget import (
            ModCardWidget,
            _compatibility_job_pool,
        )

        mod_data = ModInfo(id="gb_mod_123", name="Test Mod", version="1.0.0", author="Test", description="Test", game_version="", description_url="", downloads=0, game="deltarune")
        cached = {"supported_files": [{"name": "data.win"}], "compatibility_checked": True}
        previous = GameBananaAPI._compatibility_cache.get(123)
        widget = None
        GameBananaAPI._compatibility_cache[123] = cached
        try:
            assert _compatibility_job_pool.maxThreadCount() == 3
            with patch("ui.widgets.mod.base_mod_widget.load_mod_icon_universal"), patch(
                "ui.widgets.mod.mod_card_widget.CompatibilityCheckJob"
            ) as job:
                widget = ModCardWidget(mod_data)
                widget._do_start_compatibility_check()

            job.assert_not_called()
            assert mod_data.gamebanana_supported_files == cached["supported_files"]
            assert mod_data.gamebanana_compatibility_checked is True
        finally:
            if previous is None:
                GameBananaAPI._compatibility_cache.pop(123, None)
            else:
                GameBananaAPI._compatibility_cache[123] = previous
            if widget is not None:
                widget.deleteLater()
            _drain_events(qapp)

    def test_mod_card_widget_retries_compatibility_after_start_failure(self, qapp):
        from unittest.mock import patch

        from adapters.gamebanana_adapter import GameBananaAPI
        from models.mod_models import ModInfo
        from ui.widgets.mod.mod_card_widget import ModCardWidget

        mod_data = ModInfo(id="gb_mod_124", name="Test Mod", version="1.0.0", author="Test", description="Test", game_version="", description_url="", downloads=0, game="deltarune")
        previous = GameBananaAPI._compatibility_cache.pop(124, None)
        widget = None
        try:
            with patch("ui.widgets.mod.base_mod_widget.load_mod_icon_universal"), patch(
                "ui.widgets.mod.mod_card_widget.QTimer.singleShot"
            ), patch(
                "ui.widgets.mod.mod_card_widget._compatibility_job_pool.start",
                side_effect=RuntimeError,
            ):
                widget = ModCardWidget(mod_data)
                widget._do_start_compatibility_check()

            assert widget._compatibility_job_queued is False
        finally:
            if previous is not None:
                GameBananaAPI._compatibility_cache[124] = previous
            if widget is not None:
                widget.deleteLater()
            _drain_events(qapp)

    def test_selected_mod_card_keeps_select_border_on_hover(self, qapp):
        """Checks that selected mod card keeps select border on hover."""
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.mod_card_widget import ModCardWidget

        host = QWidget()
        host.app_state = SimpleNamespace(
            local_config={"custom_hover_color": "#111111", "custom_select_color": "#ABCDEF"}
        )
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=0, game='deltarune')
        mod_data.is_gamebanana_mod = False
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = ModCardWidget(mod_data, parent=host)
            widget.set_selected(True)
            assert 'QFrame#modCard:hover {' in widget.styleSheet()
            assert 'border-color: #ABCDEF;' in widget.styleSheet()
            assert '#111111' not in widget.styleSheet()
        widget.deleteLater()
        host.deleteLater()
        _drain_events(qapp)


class TestCommonWidgets:
    """Tests for widgets."""
    def test_custom_controls_creation(self, qapp):
        """Checks that custom controls creation."""
        from ui.widgets.shared.custom_controls import NoScrollComboBox
        combo = NoScrollComboBox()
        assert combo is not None
        assert isinstance(combo, QWidget)
        combo.deleteLater()
        _drain_events(qapp)

    def test_mod_details_overlay_creation(self, qapp):
        """Checks that mod details overlay creation."""
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=0, game='deltarune')
        overlay = ModDetailsOverlay(None, mod_data)
        assert overlay is not None
        assert isinstance(overlay, QWidget)
        assert hasattr(overlay, '_img_label')
        assert hasattr(overlay, '_prev_btn')
        assert hasattr(overlay, '_next_btn')
        assert hasattr(overlay, 'desc_text')
        assert not hasattr(overlay, 'compat_status_label')
        overlay.deleteLater()
        _drain_events(qapp)

    def test_mod_details_overlay_hidden_during_construction(self, qapp):
        """Checks that mod details overlay hidden during construction."""
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        host = QWidget()
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='', description_url='', downloads=42, game='deltarune', created_date='2024-01-01', tags=['gameplay'])
        overlay = ModDetailsOverlay(host, mod_data)
        assert not overlay.isVisible(), 'Overlay must be hidden after construction to prevent child widgets flashing'
        overlay.deleteLater()
        host.deleteLater()
        _drain_events(qapp)

    def test_mod_details_overlay_preloaded_screenshot_displays_on_navigate(self, qapp):
        """Checks that mod details overlay preloaded screenshot displays on navigate."""
        from PyQt6.QtGui import QImage

        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='', game_version='', description_url='', downloads=0, game='deltarune')
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
        _drain_events(qapp)

    def test_mod_details_overlay_metadata_order(self, qapp):
        """Checks that mod details overlay metadata order."""
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='1.0', description_url='', downloads=42, game='deltarune', created_date='2024-01-01', gamebanana_category='Category')
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
        _drain_events(qapp)

    @pytest.mark.parametrize(('downloads', 'expected'), [(0, '0'), (None, '0')])
    def test_mod_details_overlay_shows_downloads(self, qapp, downloads, expected):
        """Checks that mod details overlay shows downloads."""
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='Test description', game_version='1.0', description_url='', downloads=downloads, game='deltarune', created_date='2024-01-01', gamebanana_category='Category')
        overlay = ModDetailsOverlay(None, mod_data)
        meta_texts = [label.text() for label in overlay.findChildren(QLabel)]
        assert any(f'>{expected}</span>' in text for text in meta_texts)
        overlay.deleteLater()
        _drain_events(qapp)

    def test_mod_details_overlay_uses_custom_hover_color(self, qapp):
        """Checks that mod details overlay uses custom hover color."""
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={'custom_hover_color': '#123456'})
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='', game_version='', description_url='', downloads=0, game='deltarune')
        overlay = ModDetailsOverlay(parent, mod_data)
        assert overlay._colors['btn_hover'] == '#123456'
        overlay.deleteLater()
        parent.deleteLater()
        _drain_events(qapp)

    def test_mod_details_overlay_uses_custom_select_color(self, qapp):
        """Checks that mod details overlay uses custom select color."""
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={'custom_select_color': '#654321'})
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='', game_version='', description_url='', downloads=0, game='deltarune')
        overlay = ModDetailsOverlay(parent, mod_data)
        assert overlay._colors['btn_select'] == '#654321'
        overlay.deleteLater()
        parent.deleteLater()
        _drain_events(qapp)

    def test_mod_details_overlay_update_screenshots(self, qapp):
        """Checks that mod details overlay update screenshots."""
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='', game_version='', description_url='', downloads=0, game='deltarune')
        overlay = ModDetailsOverlay(None, mod_data)
        assert len(overlay._ss_urls) == 0
        overlay.update_screenshots(['https://example.com/1.png', 'https://example.com/2.png'])
        assert len(overlay._ss_urls) == 2
        assert overlay._ss_index == 0
        assert overlay._prev_btn.isHidden() == (len(overlay._ss_urls) <= 1)
        overlay.update_screenshots([])
        assert len(overlay._ss_urls) == 0
        overlay.deleteLater()
        _drain_events(qapp)

    def test_mod_details_overlay_initializes_screenshots_from_mod_data(self, qapp):
        """Checks that mod details overlay initializes screenshots from mod data."""
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='', game_version='', description_url='', downloads=0, game='deltarune', screenshots_url=['https://example.com/1.png', 'https://example.com/2.png'])
        overlay = ModDetailsOverlay(None, mod_data)
        assert overlay._ss_urls == ['https://example.com/1.png', 'https://example.com/2.png']
        overlay.deleteLater()
        _drain_events(qapp)

    def test_mod_details_overlay_nav(self, qapp):
        """Checks that mod details overlay nav."""
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='', game_version='', description_url='', downloads=0, game='deltarune')
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
        _drain_events(qapp)

    def test_mod_details_overlay_reuses_dot_labels_during_navigation(self, qapp):
        """Checks that mod details overlay reuses dot labels during navigation."""
        from models.mod_models import ModInfo
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        mod_data = ModInfo(id='test_mod', name='Test Mod', version='1.0.0', author='Test Author', description='', game_version='', description_url='', downloads=0, game='deltarune')
        overlay = ModDetailsOverlay(None, mod_data)
        overlay.update_screenshots(['https://a.com/1.png', 'https://a.com/2.png', 'https://a.com/3.png'])
        original_dot_labels = list(overlay._dot_labels)
        overlay._ss_next()
        assert overlay._dot_labels == original_dot_labels
        assert overlay._dot_labels[1].text() == '●'
        overlay.deleteLater()
        _drain_events(qapp)

    def test_mod_summary_panel_keeps_zero_playtime_visible(self, qapp):
        """Checks that mod summary panel keeps zero playtime visible."""
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
            playtime_hours=0,
        )
        with patch('ui.widgets.mod.mod_summary_panel.load_mod_icon_universal'):
            panel = ModSummaryPanel(host)
            panel.show_mod(mod_data, is_active=False)
            assert not panel._playtime_widget.isHidden()
            assert panel._playtime_value.text() == f"0 {tr('ui.playtime_hours_suffix')}"
        panel.deleteLater()
        host.deleteLater()
        _drain_events(qapp)

    def test_mod_summary_panel_shows_only_final_file_and_folder_names(self, qapp):
        """Checks that mod summary panel shows only final file and folder names."""
        from unittest.mock import patch

        from models.mod_models import ModFileData, ModInfo
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
            files={
                'deltarune_1': ModFileData(
                    data_file_path='folder/something.thing',
                    extra_files=[
                        'older/somefolder/',
                        'nested/final.bin',
                    ],
                )
            },
        )
        with patch('ui.widgets.mod.mod_summary_panel.load_mod_icon_universal'):
            panel = ModSummaryPanel(host)
            panel.show_mod(mod_data, is_active=False)
            assert 'something.' in panel._data_label.text()
            assert 'thing' in panel._data_label.text()
            assert 'folder/something.thing' not in panel._data_label.text()
            assert 'somefolder/' in panel._extra_label.text()
            assert 'older/somefolder/' not in panel._extra_label.text()
            assert 'final.' in panel._extra_label.text()
            assert 'bin' in panel._extra_label.text()
            assert 'nested/final.bin' not in panel._extra_label.text()
        panel.deleteLater()
        host.deleteLater()
        _drain_events(qapp)

    def test_mod_summary_panel_keeps_full_description_visible(self, qapp):
        """Checks that mod summary panel keeps the full description text."""
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.mod_summary_panel import ModSummaryPanel

        host = QWidget()
        host.local_config = {}
        description = "A" * 420
        mod_data = ModInfo(
            id='test_mod',
            name='Test Mod',
            version='1.0.0',
            author='Test Author',
            description=description,
            game_version='1.0',
            description_url='',
            downloads=0,
            game='deltarune',
        )
        with patch('ui.widgets.mod.mod_summary_panel.load_mod_icon_universal'):
            panel = ModSummaryPanel(host)
            panel.show_mod(mod_data, is_active=False)
            assert panel._description_label.text() == description
        panel.deleteLater()
        host.deleteLater()
        _drain_events(qapp)

    def test_mod_summary_panel_inserts_wrap_opportunities_for_long_file_names(self, qapp):
        """Checks that mod summary panel can wrap long file names in popup layouts."""
        from unittest.mock import patch

        from models.mod_models import ModFileData, ModInfo
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
            files={
                'deltarune_4': ModFileData(
                    data_file_path='chapter4/Ch4_Dojo_allStar.xdelta',
                    extra_files=['audio/extra_file_mus_castle_town_ch4USDX.ogg.zip'],
                )
            },
        )
        with patch('ui.widgets.mod.mod_summary_panel.load_mod_icon_universal'):
            panel = ModSummaryPanel(host)
            panel.show_mod(mod_data, is_active=False)
            assert '&#8203;' in panel._data_label.text()
            assert '&#8203;' in panel._extra_label.text()
        panel.deleteLater()
        host.deleteLater()
        _drain_events(qapp)

    def test_library_drop_area_ignores_internal_file_drags_and_accepts_external_ones(self, qapp):
        """Checks that library drop area ignores internal file drags and accepts external ones."""
        from ui.builders.library_tab_builder import _DropAreaWidget

        drop_area = _DropAreaWidget()
        dropped_paths = []
        drop_area.files_dropped.connect(dropped_paths.extend)

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile('C:/Mods/test_mod.zip')])

        def _event(source):
            event = SimpleNamespace(_source=source, accepted=False, ignored=False)
            event.mimeData = lambda: mime
            event.source = lambda: event._source
            event.acceptProposedAction = lambda: setattr(event, 'accepted', True)
            event.ignore = lambda: setattr(event, 'ignored', True)
            return event

        internal_event = _event(source=object())
        drop_area.dragEnterEvent(internal_event)
        drop_area.dropEvent(internal_event)
        assert internal_event.accepted is False
        assert internal_event.ignored is True
        assert dropped_paths == []

        external_event = _event(source=None)
        drop_area.dragEnterEvent(external_event)
        drop_area.dropEvent(external_event)
        assert external_event.accepted is True
        assert dropped_paths == ['C:/Mods/test_mod.zip']
        drop_area.deleteLater()
        _drain_events(qapp)

    def test_installed_mod_drag_export_is_materialized_only_when_urls_are_requested(self, qapp):
        """Checks that installed mod drag export stays lazy until the drop target requests URLs."""
        from unittest.mock import Mock, patch

        from models.mod_models import ModInfo
        from presentation.drag_drop import LazyFileExportMimeData, normalize_local_path
        from ui.widgets.mod.installed_mod_widget import InstalledModWidget

        host = QWidget()
        host.app_state = SimpleNamespace(local_config={'ui_scale': 1.0})
        host.mod_import_export_controller = Mock()
        mod_data = ModInfo(
            id='test_mod',
            name='Lazy Export Mod',
            version='1.0.0',
            author='Test Author',
            description='Test description',
            game_version='',
            description_url='',
            downloads=0,
            game='deltarune',
        )
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = InstalledModWidget(mod_data, parent=host, parent_app=host)
        mime = LazyFileExportMimeData(
            lambda path: host.mod_import_export_controller.export_mod_to_path(mod_data, path),
            'Lazy Export Mod.zip',
            internal_format='application/x-g3m-installed-mod-export',
        )
        assert host.mod_import_export_controller.export_mod_to_path.call_count == 0
        assert mime.hasUrls() is True
        assert host.mod_import_export_controller.export_mod_to_path.call_count == 0
        with patch.object(mime, '_ensure_export_ready', return_value='C:/Temp/Lazy Export Mod.zip') as ensure_ready:
            urls = mime.urls()
            assert ensure_ready.call_count == 1
            assert [normalize_local_path(url.toLocalFile()) for url in urls] == ['C:/Temp/Lazy Export Mod.zip']
        assert host.mod_import_export_controller.export_mod_to_path.call_count == 0
        widget.deleteLater()
        host.deleteLater()
        _drain_events(qapp)

    def test_search_mod_card_widget_shows_wip_marker_after_updated_date(self, qapp):
        """Checks that search mod card widget shows WIP marker after updated date."""
        from unittest.mock import patch

        from models.mod_models import ModInfo
        from ui.widgets.mod.search_mod_card_widget import SearchModCardWidget

        host = QWidget()
        host.app_state = SimpleNamespace(local_config={"ui_scale": 1.0})
        mod_data = ModInfo(
            id="gb_wip_123",
            name="WIP Search Mod",
            version="1.0.0",
            author="Test Author",
            description="Test description",
            game_version="",
            description_url="",
            downloads=42,
            game="deltarune",
            last_updated="2024-05-01",
            is_wip=True,
        )
        mod_data.is_gamebanana_mod = True
        with patch("ui.widgets.mod.search_mod_card_widget.load_mod_icon_universal"):
            widget = SearchModCardWidget(mod_data, parent=host)
            assert widget.updated_label.text() == "2024-05-01 | WIP"
        widget.deleteLater()
        host.deleteLater()
        _drain_events(qapp)

    def test_rich_html_reserves_safe_width_for_inline_media(self):
        """Checks that rich HTML reserves safe width for inline media."""
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

    def test_rich_html_accepts_unquoted_image_dimensions(self):
        """Checks that browser-style unquoted image attrs are preserved."""
        from ui.common.rich_html import preprocess_html

        processed = preprocess_html('<img src="panel.png" width=620>', widget_width=700)

        assert 'width="620"' in processed

    def test_rich_html_inlines_embedded_css_classes(self):
        """Checks that embedded CSS classes are converted for QTextDocument."""
        from ui.common.rich_html import preprocess_html

        html = """
        <style>
        .notice { color: #ff99aa; background-color: #222; font-weight: bold; }
        div.ignored { display: flex; transform: scale(2); }
        </style>
        <p class="notice">Important</p>
        """

        processed = preprocess_html(html)

        assert "<style" not in processed
        assert "color:#ff99aa;" in processed
        assert "background-color:#222;" in processed
        assert "font-weight:bold;" in processed
        assert "display:flex" not in processed

    def test_rich_html_inlines_embedded_element_styles(self):
        """Checks that simple tag selectors from style blocks are preserved."""
        from ui.common.rich_html import preprocess_html

        html = """
        <style>
        h1 { color: #00dc78; font-size: 28px; margin: 0; }
        a { color: #ff40a0; text-decoration: underline; }
        code { background: #0b0d11; color: #6de985; padding: 2px; }
        </style>
        <h1>Title</h1><p><a href="https://example.com">Link</a> <code>Press J</code></p>
        """

        processed = preprocess_html(html)

        assert '<h1 style="color:#00dc78;font-size:28px;margin:0;">' in processed
        assert 'href="https://example.com" style="color:#ff40a0;text-decoration:underline;"' in processed
        assert 'background-color:#0b0d11;color:#6de985;padding:2px;' in processed

    def test_rich_html_escapes_inline_style_quotes(self):
        """Checks that quoted CSS values do not break generated attributes."""
        from ui.common.rich_html import preprocess_html

        processed = preprocess_html(
            '<style>body { font-family: "Segoe UI", "Verdana"; color: #eee; }</style><body>Text</body>'
        )

        assert 'font-family:&quot;Segoe UI&quot;, &quot;Verdana&quot;;color:#eee;' in processed

    def test_rich_html_turns_heading_border_into_rule(self):
        """Checks that heading underlines survive QTextDocument rendering."""
        from ui.common.rich_html import preprocess_html

        processed = preprocess_html(
            "<style>h2 { color: #6de985; border-bottom: 1px solid #039d5b; }</style><h2>Title</h2>"
        )

        assert "<h2" in processed
        assert "border-bottom" not in processed
        assert '<hr width="100%" color="#039d5b"' in processed

    def test_rich_html_drops_paint_from_layout_container_classes(self):
        """Checks that wrapper backgrounds do not create QTextDocument stripes."""
        from ui.common.rich_html import preprocess_html

        html = """
        <style>
        .page { background: #1f232b; border: 2px solid #039d5b; padding: 22px; color: #eee; }
        .note { background: #282828; border-left: 6px solid #9d391a; color: #ffd7c2; }
        </style>
        <div class="page"><div class="note">Warning</div></div>
        """

        processed = preprocess_html(html)

        assert 'style="color:#eee;"' in processed
        assert "background-color:#1f232b" not in processed
        assert "border:2px solid #039d5b" not in processed
        assert 'bgcolor="#282828"' in processed
        assert "border-left:4px solid #9d391a;" in processed

    def test_rich_html_converts_figures_and_float_blocks(self):
        """Checks that common web media wrappers become Qt-friendly blocks."""
        from ui.common.rich_html import preprocess_html

        html = """
        <figure class="floatright">
            <img src="images/panel.png" width="320">
            <figcaption>Panel caption</figcaption>
        </figure>
        """

        processed = preprocess_html(html, widget_width=260, base_path="C:/Mods/Sample")

        assert "<figure" not in processed
        assert "<figcaption" not in processed
        assert '<table align="right"' in processed
        assert "Panel caption" in processed
        assert "file:///C:/Mods/Sample/images/panel.png" in processed
        assert 'width="250"' in processed

    def test_rich_html_encodes_special_characters_in_windows_base_paths(self):
        """Checks that Windows file URLs encode spaces and reserved characters."""
        from ui.common.rich_html import preprocess_html

        processed = preprocess_html(
            '<img src="images/my #icon?.png" width="120">',
            widget_width=400,
            base_path="C:/My Documents/Sample Mod",
        )

        assert "file:///C:/My%20Documents/Sample%20Mod/images/my%20%23icon%3F.png" in processed

    def test_rich_html_uses_max_width_for_images(self):
        """Checks that max-width is honored when width is absent."""
        from ui.common.rich_html import preprocess_html

        processed = preprocess_html(
            '<img src="C:/Mods/image.png" style="max-width: 80%; height: 40">',
            widget_width=500,
        )

        assert 'width="392"' in processed
        assert 'height="40"' in processed

    def test_rich_html_strips_script_blocks_with_spaced_end_tag(self):
        """Checks that script blocks are removed even when end tag contains whitespace."""
        from ui.common.rich_html import preprocess_html

        processed = preprocess_html('<div>safe</div><script>alert("x")</script ><p>ok</p>')

        assert "<script" not in processed.lower()
        assert 'alert("x")' not in processed
        assert "<p>ok</p>" in processed

    def test_rich_html_loading_placeholder_keeps_outer_edges_transparent(self):
        """Checks that rich HTML loading placeholder keeps outer edges transparent."""
        from ui.common.rich_html import _create_loading_placeholder
        placeholder = _create_loading_placeholder(300, 120, 'Loading image...')
        center_y = placeholder.height() // 2
        assert placeholder.pixelColor(0, center_y).alpha() == 0
        assert placeholder.pixelColor(placeholder.width() - 1, center_y).alpha() == 0
        assert placeholder.pixelColor(placeholder.width() - 8, center_y).alpha() == 0
        assert placeholder.pixelColor(placeholder.width() - 16, center_y).alpha() == 0
        assert placeholder.pixelColor(placeholder.width() // 2, center_y).alpha() > 0
