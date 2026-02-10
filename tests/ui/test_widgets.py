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

    def test_outlined_label_creation(self, qapp):
        from ui.widgets.shared.outlined_label import OutlinedTextLabel
        label = OutlinedTextLabel('Test', None)
        assert label is not None
        assert isinstance(label, QWidget)
        label.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_screenshots_carousel_creation(self, qapp):
        from ui.widgets.shared.screenshots_carousel import ScreenshotsCarousel
        urls = []
        carousel = ScreenshotsCarousel(urls, parent=None)
        assert carousel is not None
        assert isinstance(carousel, QWidget)
        carousel.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)
