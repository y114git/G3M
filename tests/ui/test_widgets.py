import time
from types import SimpleNamespace
from PyQt6.QtWidgets import QLabel, QWidget
import pytest


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

    @pytest.mark.parametrize(('downloads', 'expected'), [(0, '⤓ 0'), (None, '⤓ N/A')])
    def test_mod_card_widget_downloads_text_distinguishes_zero_and_missing(self, qapp, downloads, expected):
        from ui.widgets.mod.mod_card_widget import ModCardWidget
        from models.mod_models import ModInfo
        from unittest.mock import patch
        mod_data = ModInfo(key='test_mod', name='Test Mod', version='1.0.0', author='Test Author', tagline='Test tagline', game_version='', description_url='', downloads=downloads, game='deltarune', is_verified=False)
        mod_data.is_gamebanana_mod = False
        with patch('ui.widgets.mod.base_mod_widget.load_mod_icon_universal'):
            widget = ModCardWidget(mod_data, parent=None)
            assert widget.downloads_label.text() == expected
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
            except Exception as e:
                import logging
                logging.debug(f'Thread cleanup error in test: {e}')
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

    @pytest.mark.parametrize(('downloads', 'expected'), [(0, '0'), (None, 'N/A')])
    def test_mod_details_overlay_downloads_distinguishes_zero_and_missing(self, qapp, downloads, expected):
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        from models.mod_models import ModInfo
        mod_data = ModInfo(key='test_mod', name='Test Mod', version='1.0.0', author='Test Author', tagline='Test tagline', game_version='1.0', description_url='', downloads=downloads, game='deltarune', is_verified=False, created_date='2024-01-01', gamebanana_category='Category')
        overlay = ModDetailsOverlay(None, mod_data)
        meta_texts = [label.text() for label in overlay.findChildren(QLabel)]
        assert any(f'>{expected}</span>' in text for text in meta_texts)
        overlay.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)

    def test_mod_details_overlay_uses_custom_button_hover_color(self, qapp):
        from ui.widgets.mod_details_overlay import ModDetailsOverlay
        from models.mod_models import ModInfo
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={'custom_color_button_hover': '#123456'})
        mod_data = ModInfo(key='test_mod', name='Test Mod', version='1.0.0', author='Test Author', tagline='', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)
        overlay = ModDetailsOverlay(parent, mod_data)
        assert overlay._colors['btn_hover'] == '#123456'
        overlay.deleteLater()
        parent.deleteLater()
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
        assert overlay._prev_btn.isHidden() == (len(overlay._ss_urls) <= 1)
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

    def test_dr_save_manager_slot_labels_size_for_multiline_text_on_first_refresh(self, qapp, app_state, temp_dir):
        from unittest.mock import Mock
        from plugins_main.dr_save_manager.save_manager_view_builder import SaveManagerViewBuilder
        from plugins_main.dr_save_manager.save_ui_controller import SaveUiController
        builder = SaveManagerViewBuilder(app_state, None)
        save_manager_widget = builder.build()
        widgets = builder.get_widgets()
        app = SimpleNamespace(
            save_tabs=widgets['save_tabs'],
            _slot_labels=widgets['slot_labels'],
            switch_collection_btn=widgets['switch_collection_btn'],
            left_col_btn=widgets['left_col_btn'],
            right_col_btn=widgets['right_col_btn'],
            rename_collection_btn=widgets['rename_collection_btn'],
            delete_collection_btn=widgets['delete_collection_btn'],
            copy_from_main_btn=widgets['copy_from_main_btn'],
            copy_to_main_btn=widgets['copy_to_main_btn'],
            collection_name_lbl=widgets['collection_name_lbl'],
            change_save_path_btn=widgets['change_save_path_btn'],
            show_btn=widgets['show_btn'],
            erase_btn=widgets['erase_btn'],
            import_btn=widgets['import_btn'],
            export_btn=widgets['export_btn'],
        )
        save_manager = Mock()
        save_manager.save_path = temp_dir
        save_manager.refresh_save_slots_data.return_value = {
            0: (True, 'Susie - 4111 D$\nCompleted'),
            1: (True, 'Ralsei - 2321 D$\nIncomplete'),
            2: (False, '-------------- EMPTY --------------'),
        }
        save_manager.get_collection_ui_state.return_value = {
            'in_collection': False,
            'can_navigate_left': False,
            'can_navigate_right': False,
            'collection_name': '',
        }
        save_manager.current_collection_idx = -1
        save_manager.selected_slot = None
        controller = SaveUiController(app_state, Mock(), save_manager, Mock(), app)
        save_manager_widget.show()
        qapp.processEvents()
        controller.refresh_slots()
        qapp.processEvents()
        for slot_index in (0, 1):
            label = widgets['slot_labels'][(1, slot_index)]
            assert label.minimumHeight() >= label.sizeHint().height()
            assert '\n' in label.text()
        save_manager_widget.deleteLater()
        for _ in range(3):
            qapp.processEvents()
            time.sleep(0.05)
