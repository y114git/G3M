import time
from PyQt6.QtWidgets import QWidget


class TestModWidgets:

    def test_base_mod_widget_creation(self, qapp):
        from ui.widgets.mod.base_mod_widget import BaseModWidget
        from unittest.mock import patch
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = BaseModWidget(None)
            assert widget is not None
            assert isinstance(widget, QWidget)
        widget.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_installed_mod_widget_creation(self, qapp):
        from ui.widgets.mod.installed_mod_widget import InstalledModWidget
        from models.mod_models import ModInfo
        from unittest.mock import patch
        mod_data = ModInfo(key='test_mod', name='Test Mod', version='1.0.0', author='Test Author', tagline='Test tagline', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = InstalledModWidget(mod_data, parent=None)
            assert widget is not None
            assert isinstance(widget, QWidget)
        widget.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_card_widget_creation(self, qapp):
        from ui.widgets.mod.mod_card_widget import ModCardWidget
        from models.mod_models import ModInfo
        from unittest.mock import patch
        from ui.utils.ui_utils import safe_stop_thread
        mod_data = ModInfo(key='test_mod', name='Test Mod', version='1.0.0', author='Test Author', tagline='Test tagline', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        mod_data.is_gamebanana_mod = False
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = ModCardWidget(mod_data, parent=None)
            assert widget is not None
            assert isinstance(widget, QWidget)
        if hasattr(widget, '_compatibility_thread') and widget._compatibility_thread:
            thread = widget._compatibility_thread
            try:
                thread.blockSignals(True)
                try:
                    thread.compatibility_checked.disconnect()
                except (TypeError, RuntimeError):
                    pass
                try:
                    thread.finished.disconnect()
                except (TypeError, RuntimeError):
                    pass
                thread.blockSignals(False)
            except Exception:
                pass
            safe_stop_thread(thread, timeout=1000)
        widget.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)


class TestPluginWidgets:

    def test_plugin_widget_creation(self, qapp):
        from ui.widgets.plugin.plugin_widget import PluginWidget
        plugin_info = {'name': 'Test Plugin', 'version': '1.0.0', 'author': 'Test Author', 'description': 'Test description'}
        widget = PluginWidget(plugin_info, parent=None)
        assert widget is not None
        assert isinstance(widget, QWidget)
        widget.deleteLater()
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
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        from models.mod_models import ModInfo
        mod_data = ModInfo(key='test_mod', name='Test Mod', version='1.0.0', author='Test Author', tagline='Test tagline', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        overlay = ModDetailsOverlay(None, mod_data)
        assert overlay is not None
        assert isinstance(overlay, QWidget)
        assert hasattr(overlay, '_img_label')
        assert hasattr(overlay, '_prev_btn')
        assert hasattr(overlay, '_next_btn')
        assert hasattr(overlay, 'desc_text')
        overlay.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_details_overlay_update_screenshots(self, qapp):
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        from models.mod_models import ModInfo
        mod_data = ModInfo(key='test_mod', name='Test Mod', version='1.0.0', author='Test Author', tagline='', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        overlay = ModDetailsOverlay(None, mod_data)
        assert len(overlay._ss_urls) == 0
        overlay.update_screenshots(['https://example.com/1.png', 'https://example.com/2.png'])
        assert len(overlay._ss_urls) == 2
        assert overlay._ss_index == 0
        assert not overlay._prev_btn.isVisible() or len(overlay._ss_urls) > 1
        overlay.update_screenshots([])
        assert len(overlay._ss_urls) == 0
        overlay.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_details_overlay_nav(self, qapp):
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        from models.mod_models import ModInfo
        mod_data = ModInfo(key='test_mod', name='Test Mod', version='1.0.0', author='Test Author', tagline='', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
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
