from unittest.mock import Mock, patch

try:
    from typing import override
except ImportError:
    from typing import override

from PyQt6.QtCore import QMimeData, Qt, QUrl
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton, QWidget


class TestImportDialog:
    """Tests for dialogs."""
    def test_import_dialog_creation(self, qapp, feedback_service):
        """Checks that importing dialog creation."""
        from ui.dialogs.import_dialog import ImportDialog
        dialog = ImportDialog(None, feedback_service, 'mods')
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestGameBananaFilePickerDialog:
    """Tests for dialogs."""
    def test_file_picker_dialog_creation(self, qapp):
        """Checks that fileing picker dialog creation."""
        from ui.dialogs.file_picker_dialog import GameBananaFilePickerDialog
        dialog = GameBananaFilePickerDialog(None, [], 'Test Mod')
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestCreateModpackDialog:
    """Tests for dialogs."""
    def test_create_modpack_dialog_creation(self, qapp, app_state):
        """Checks that creating modpack dialog creation."""
        from ui.dialogs.modpack_create_dialog import CreateModpackDialog
        dialog = CreateModpackDialog(app_state, None)
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestConflictsDialog:
    """Tests for dialogs."""
    def test_conflicts_dialog_creation(self, qapp, temp_dir):
        """Checks that conflictsing dialog creation."""
        import os

        from ui.dialogs.conflicts_dialog import ConflictsDialog
        report_path = os.path.join(temp_dir, 'test_report.md')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('## Merge Report\n\nTotal conflicts: 2\nAuto-resolved: 1\n')
        dialog = ConflictsDialog(report_path, None)
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestModPriorityDialog:
    """Tests for dialogs."""
    def test_mod_priority_dialog_creation(self, qapp, app_state):
        """Checks that moding priority dialog creation."""
        from models.mod_models import ModInfo
        from ui.dialogs.mod_priority_dialog import ModPriorityDialog
        mods_list = [ModInfo(id='test_mod_1', name='Test Mod 1', version='1.0.0', author='Author', description='', game_version='', description_url='', downloads=0, game='deltarune')]
        dialog = ModPriorityDialog(mods_list, 1, app_state, None)
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestAboutDialog:
    """Tests for dialogs."""
    def test_about_dialog_creation(self, qapp, app_state, temp_dir):
        """Checks that abouting dialog creation."""
        from models.plugin_models import PLUGIN_API_VERSION
        from ui.dialogs.about_dialog import AboutDialog
        app_state.global_settings = {"reportform_url": "https://example.com/form"}
        dialog = AboutDialog(None, app_state)
        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert dialog.title_label.text() == 'G3M'
        assert dialog.data_path_edit.text() == temp_dir
        assert dialog.plugin_api_value.text() == PLUGIN_API_VERSION
        assert dialog.report_issue_button.isEnabled()
        assert dialog.os_value.text()
        assert dialog.python_value.text()
        dialog.close()

    def test_about_dialog_actions(self, qapp, app_state):
        """Checks that abouting dialog actions."""
        from ui.dialogs.about_dialog import AboutDialog
        app_state.global_settings = {"reportform_url": "https://example.com/form"}
        dialog = AboutDialog(None, app_state)
        with patch('ui.dialogs.about_dialog.QDesktopServices.openUrl') as open_url:
            dialog.wiki_button.click()
            dialog.open_folder_button.click()
            assert open_url.call_count == 2
            dialog.report_issue_button.click()
            assert open_url.call_count == 3
        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_about_dialog_disables_report_issue_without_url(self, qapp, app_state):
        """Checks that abouting dialog disables report issue without url."""
        from ui.dialogs.about_dialog import AboutDialog
        dialog = AboutDialog(None, app_state)
        assert not dialog.report_issue_button.isEnabled()
        dialog.close()


class TestChangelogDialog:
    """Tests for dialogs."""
    def test_changelog_dialog_creation_without_source(self, qapp):
        """Checks that changeloging dialog creation without source."""
        from ui.dialogs.changelog_dialog import ChangelogDialog
        dialog = ChangelogDialog(None, '')
        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert hasattr(dialog, 'text_browser')
        assert hasattr(dialog, 'close_button')
        dialog.close()


class TestPizzaOvenConversionDialog:
    """Tests for dialogs."""
    def test_dialog_creation(self, qapp):
        """Checks that dialoging creation."""
        from services.localization_service import tr
        from ui.dialogs.pizza_oven_conversion_dialog import PizzaOvenConversionDialog

        dialog = PizzaOvenConversionDialog(None)

        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert dialog.windowTitle() == tr("dialogs.po_convert_title")
        assert dialog.start_button.text() == tr("buttons.start_po_convert")
        assert dialog.cancel_button.text() == tr("dialogs.cancel")
        dialog.close()


class TestReadmeUi:
    """Tests for dialogs."""
    def test_mod_readme_dialog_creation(self, qapp, app_state, tmp_path):
        """Checks that moding readme dialog creation."""
        from ui.dialogs.mod_readme_dialog import ModReadmeDialog

        readme_path = tmp_path / "README.md"
        readme_path.write_text("# Guide\n\n[Link](https://example.com)", encoding="utf-8")

        dialog = ModReadmeDialog(app_state, "Test Mod", [str(readme_path)])

        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert dialog._tabs.count() == 1
        assert "QTabWidget::pane" in dialog.styleSheet()
        assert "padding-top: 10px;" in dialog.styleSheet()
        dialog.close()

    def test_mod_summary_panel_uses_localized_info_button(self, qapp, app_state):
        """Checks that moding summary panel uses localized info button."""
        from services.localization_service import tr
        from ui.widgets.mod.mod_summary_panel import ModSummaryPanel

        panel = ModSummaryPanel(app_state)

        assert panel._readme_button.text() == tr("dialogs.info")
        panel.update_labels_text()
        assert panel._readme_button.text() == tr("dialogs.info")
        panel.apply_theme()
        assert panel.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        assert panel._scroll.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        assert panel._scroll.viewport().testAttribute(
            Qt.WidgetAttribute.WA_StyledBackground
        )
        panel.deleteLater()

    def test_profile_manager_metadata_uses_new_format(self, qapp, app_state):
        """Checks that profileing manager metadata uses new format."""
        from unittest.mock import Mock

        from PyQt6.QtWidgets import QLabel

        from ui.dialogs.profile_manager_dialog import ProfileManagerDialog

        profile_service = Mock()
        profile_service.active_name = "Default"
        profile_service.list_profiles.return_value = ["Default"]
        profile_service.get_profile_summary.return_value = {
            "name": "Default",
            "game": "deltarune",
            "game_display_name": "DELTARUNE",
            "game_mod_count": 3,
            "total_mod_count": 7,
            "chapter_mode": False,
            "direct_launch": "",
        }

        dialog = ProfileManagerDialog(profile_service, app_state)
        item_widget = dialog.list_widget.itemWidget(dialog.list_widget.item(0))
        detail_label = item_widget.findChild(QLabel, "profileDetailLabel")

        assert "3 mods for DELTARUNE" in detail_label.text()
        assert "7 mods in profile" in detail_label.text()
        dialog.close()

    def test_profile_manager_external_drop_imports_multiple_archives(self, qapp, app_state, temp_dir):
        """Checks that profile manager external drop imports multiple archives."""
        import os

        from ui.dialogs.profile_manager_dialog import ProfileManagerDialog

        first = os.path.join(temp_dir, "one.zip")
        second = os.path.join(temp_dir, "two.zip")
        open(first, "wb").close()
        open(second, "wb").close()

        profile_service = Mock()
        profile_service.active_name = "Default"
        profile_service.list_profiles.return_value = ["Default"]
        profile_service.get_profile_summary.return_value = {
            "name": "Default",
            "game": "deltarune",
            "game_display_name": "DELTARUNE",
            "game_mod_count": 1,
            "total_mod_count": 1,
            "chapter_mode": False,
            "direct_launch": "",
        }
        profile_service.import_profile.side_effect = ["ImportedOne", "ImportedTwo"]

        dialog = ProfileManagerDialog(profile_service, app_state)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(first), QUrl.fromLocalFile(second)])

        class _Event:
            def __init__(self) -> None:
                self.accepted = False

            @override
            def mimeData(self):
                return mime

            def source(self):
                return None

            @override
            def acceptProposedAction(self):
                self.accepted = True

        event = _Event()
        with patch("ui.dialogs.profile_manager_dialog.QMessageBox.information"):
            dialog.list_widget.dropEvent(event)
        assert event.accepted is True
        assert os.path.normpath(profile_service.import_profile.call_args_list[0].args[0]) == os.path.normpath(first)
        assert os.path.normpath(profile_service.import_profile.call_args_list[1].args[0]) == os.path.normpath(second)
        dialog.close()

    def test_game_versions_dialog_drop_imports_multiple_files_and_urls(self, qapp, app_state, temp_dir):
        """Checks that game versions dialog drop imports multiple files and urls."""
        import os

        from ui.dialogs.game_versions_dialog import GameVersionsDialog

        first = os.path.join(temp_dir, "one.zip")
        second = os.path.join(temp_dir, "two.zip")
        open(first, "wb").close()
        open(second, "wb").close()

        manager = Mock()
        manager.records_for_game.return_value = []
        manager.record_added.connect = Mock()
        manager.record_removed.connect = Mock()
        manager.record_updated.connect = Mock()
        manager.progress_updated.connect = Mock()
        manager.operation_error.connect = Mock()

        dialog = GameVersionsDialog(manager, app_state)
        mime = QMimeData()
        mime.setUrls(
            [
                QUrl.fromLocalFile(first),
                QUrl.fromLocalFile(second),
                QUrl("https://example.com/one.zip"),
                QUrl("https://example.com/two.zip"),
            ]
        )

        class _Event:
            def __init__(self) -> None:
                self.accepted = False

            @override
            def mimeData(self):
                return mime

            def source(self):
                return None

            @override
            def acceptProposedAction(self):
                self.accepted = True

            def ignore(self):
                self.accepted = False

        event = _Event()
        dialog.dropEvent(event)
        game_id = dialog._current_game()
        assert event.accepted is True
        actual_first_path = manager.import_game_version_from_file.call_args_list[0].args[1]
        actual_second_path = manager.import_game_version_from_file.call_args_list[1].args[1]
        assert os.path.normpath(actual_first_path) == os.path.normpath(first)
        assert os.path.normpath(actual_second_path) == os.path.normpath(second)
        assert manager.import_game_version_from_url.call_args_list[0].args == (game_id, "https://example.com/one.zip")
        assert manager.import_game_version_from_url.call_args_list[1].args == (game_id, "https://example.com/two.zip")
        dialog.close()

    def test_mod_versions_dialog_drop_queues_multiple_imports(self, qapp, app_state, tmp_path):
        """Checks that mod versions dialog drop queues multiple imports."""
        import os

        from ui.dialogs.mod_versions_dialog import ModVersionsDialog

        mod_folder = tmp_path / "mod"
        mod_folder.mkdir()
        (mod_folder / "mod_config.json").write_text('{"name":"Mod"}', encoding="utf-8")
        first = tmp_path / "one.zip"
        second = tmp_path / "two.zip"
        first.write_bytes(b"1")
        second.write_bytes(b"2")

        dialog = ModVersionsDialog(
            str(mod_folder),
            {"id": "mod", "name": "Mod"},
            app_state,
            parent=None,
        )
        imported_files = []
        imported_urls = []
        dialog._import_from_path = lambda path, version_name=None, prompt_for_name=True: imported_files.append((path, prompt_for_name)) or dialog._process_next_import()
        dialog._start_url_worker = lambda url, version_name=None, prompt_for_name=True: imported_urls.append((url, prompt_for_name)) or dialog._process_next_import()

        mime = QMimeData()
        mime.setUrls(
            [
                QUrl.fromLocalFile(str(first)),
                QUrl.fromLocalFile(str(second)),
                QUrl("https://example.com/modA.zip"),
                QUrl("https://example.com/modB.zip"),
            ]
        )

        class _Event:
            def __init__(self) -> None:
                self.accepted = False

            @override
            def mimeData(self):
                return mime

            def source(self):
                return None

            @override
            def acceptProposedAction(self):
                self.accepted = True

            def ignore(self):
                self.accepted = False

        event = _Event()
        dialog.dropEvent(event)
        assert event.accepted is True
        assert [(os.path.normpath(path), flag) for path, flag in imported_files] == [(os.path.normpath(str(first)), False), (os.path.normpath(str(second)), False)]
        assert imported_urls == [
            ("https://example.com/modA.zip", False),
            ("https://example.com/modB.zip", False),
        ]
        dialog.close()


class TestThemeManagementDialog:
    """Tests for dialogs."""
    def test_theme_management_dialog_creation(self, qapp, app_state):
        """Checks that themeing management dialog creation."""
        from unittest.mock import Mock

        from services.customization_service import CustomizationManager
        from services.localization_service import tr
        from ui.dialogs.theme_dialog import ThemeManagementDialog

        class FakeThemeController:
            def __init__(self, state) -> None:
                self.app_state = state
                self.customization_service = CustomizationManager(state)
                self.settings_service = Mock()

        theme_controller = FakeThemeController(app_state)
        dialog = ThemeManagementDialog(None, theme_controller)
        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert dialog.findChildren(QPushButton)[0].toolTip() == tr("tooltips.import_theme")

        settings_text = dialog._build_settings_text()
        assert isinstance(settings_text, str)
        assert 'themes.no_customizations' in settings_text or len(settings_text) > 0
        dialog.close()

    def test_theme_management_dialog_hides_default_border_radius(
        self, qapp, app_state
    ):
        """Checks that themeing management dialog hides default border radius."""
        from unittest.mock import Mock

        from services.customization_service import CustomizationManager
        from ui.dialogs.theme_dialog import ThemeManagementDialog

        class FakeThemeController:
            def __init__(self, state) -> None:
                self.app_state = state
                self.customization_service = CustomizationManager(state)
                self.settings_service = Mock()

        app_state.local_config["custom_border_radius"] = 7
        theme_controller = FakeThemeController(app_state)
        dialog = ThemeManagementDialog(None, theme_controller)

        settings_text = dialog._build_settings_text()

        assert "Border Radius" not in settings_text
        dialog.close()


class TestModdingToolsDialog:
    """Tests for dialogs."""
    def test_dialog_uses_raised_tab_styling(self, qapp, app_state):
        """Checks that dialoging uses raised tab styling."""
        from ui.dialogs.modding_tools_dialog import ModdingToolsDialog

        dialog = ModdingToolsDialog(Mock(), app_state)

        assert dialog._tabs.documentMode() is True
        assert "QTabWidget::pane" in dialog.styleSheet()
        assert "padding-top: 10px;" in dialog.styleSheet()
        dialog.close()


class TestDialogTheme:
    """Tests for dialogs."""
    def test_dialog_theme_uses_hover_color_for_selection(self, app_state):
        """Checks that dialoging theme uses hover color for selection."""
        from ui.common.dialog_theme import build_dialog_theme_stylesheet

        app_state.local_config = {
            'custom_hover_color': '#112233',
            'custom_select_color': '#445566',
        }
        stylesheet = build_dialog_theme_stylesheet(app_state)

        assert 'background-color: #112233;' in stylesheet
        assert 'selection-background-color: #112233;' in stylesheet
        assert '#445566' not in stylesheet


class TestModEditorDialog:
    """Tests for dialogs."""
    def test_mod_editor_populates_saved_files_as_relative_paths(self, qapp, tmp_path):
        """Checks that moding editor populates saved files as relative paths."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor_dialog import ModEditorDialog

        mod_folder = tmp_path / 'bossrush_mod'
        chapter_folder = mod_folder / 'chapter_4'
        chapter_folder.mkdir(parents=True)
        (chapter_folder / 'BOSSRUSH.win').write_text('data', encoding='utf-8')
        (chapter_folder / 'bonus.zip').write_text('extra', encoding='utf-8')
        (mod_folder / 'icon.png').write_text('icon', encoding='utf-8')
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_folder)))
        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                'id': 'local_manual_bossrush',
                'name': 'BOSSRUSH',
                'author': 'Unknown',
                'description': 'Desc',
                'version': '1.0.0',
                'game': 'deltarune',
                'icon': 'icon.png',
                'files': {
                    'deltarune_4': {
                        'data_file_path': 'BOSSRUSH.win',
                        'extra_files': ['bonus.zip'],
                    }
                },
            },
        )

        collected = dialog._collect_files()

        assert dialog.icon_edit.text() == 'icon.png'
        assert dialog.findChild(QWidget, 'modEditorIntroCard') is None
        assert collected['deltarune_4']['data_file_path'] == 'BOSSRUSH.win'
        assert collected['deltarune_4']['extra_files'] == ['bonus.zip']
        assert dialog._resolve_file_path('BOSSRUSH.win') == str(
            chapter_folder / 'BOSSRUSH.win'
        )
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_hides_add_data_button_per_tab_until_data_frame_removed(
        self, qapp, tmp_path
    ):
        """Checks that moding editor hides add data button per tab until data frame removed."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QPushButton

        from ui.dialogs.mod_editor_dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        first_tab = dialog.file_tabs.widget(0)
        second_tab = dialog.file_tabs.widget(1)
        first_layout = first_tab._file_layout
        first_button = first_tab._data_button
        second_button = second_tab._data_button

        assert not first_button.isHidden()
        assert not second_button.isHidden()

        dialog._on_add_data(first_tab, first_layout)

        file_cards = [
            first_layout.itemAt(i).widget()
            for i in range(first_layout.count())
            if first_layout.itemAt(i) and first_layout.itemAt(i).widget()
        ]
        data_frame = next(
            (
                widget
                for widget in file_cards
                if widget is not None
                and widget.findChild(QPushButton) is not None
                and any(
                    child.property("file_type") == "data"
                    for child in widget.findChildren(QWidget)
                )
            ),
            None,
        )

        assert data_frame is not None
        assert first_button.isHidden()
        assert not second_button.isHidden()

        dialog._remove_file_frame(first_layout, data_frame, "data")

        assert not first_button.isHidden()
        assert not second_button.isHidden()
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_file_container_has_larger_minimum_height(self, qapp, tmp_path):
        """Checks that moding editor file container has larger minimum height."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor_dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        first_tab = dialog.file_tabs.widget(0)
        scroll = first_tab._file_scroll

        assert scroll.minimumHeight() >= 300
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_saves_folder_targets_with_trailing_slash(self, qapp, tmp_path):
        """Checks that moding editor saves folder targets with trailing slash."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor_dialog import ModEditorDialog

        folder_source = tmp_path / "sprites"
        folder_source.mkdir()
        (folder_source / "sprite.png").write_text("img", encoding="utf-8")

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        first_tab = dialog.file_tabs.widget(0)
        layout = first_tab._file_layout
        dialog._create_file_frame(layout, "extra")
        extra_inputs = [
            w
            for w in first_tab.findChildren(type(dialog.icon_edit))
            if w.property("is_local_extra_path")
        ]
        extra_inputs[0].setText(str(folder_source).replace("\\", "/") + "/")

        files = dialog._collect_files()

        first_tab_key = "deltarune_0"
        assert files[first_tab_key]["extra_files"] == [
            str(folder_source).replace("\\", "/") + "/"
        ]
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_extra_path_fields_are_editable(self, qapp, tmp_path):
        """Checks that moding editor extra path fields are editable."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor_dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        first_tab = dialog.file_tabs.widget(0)
        layout = first_tab._file_layout
        dialog._create_file_frame(layout, "extra")
        extra_inputs = [
            w
            for w in first_tab.findChildren(type(dialog.icon_edit))
            if w.property("is_local_extra_path")
        ]

        assert extra_inputs
        assert not extra_inputs[0].isReadOnly()
        extra_inputs[0].setText("nested/path/")

        files = dialog._collect_files()

        assert files["deltarune_0"]["extra_files"] == ["nested/path/"]
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_populates_extra_file_paths_in_visible_inputs(self, qapp, tmp_path):
        """Checks that moding editor populates extra file paths in visible inputs."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor_dialog import ModEditorDialog

        mod_folder = tmp_path / "bossrush_mod"
        chapter_folder = mod_folder / "chapter_4"
        chapter_folder.mkdir(parents=True)
        (chapter_folder / "extras").mkdir()
        (chapter_folder / "extras" / "bonus.zip").write_text("extra", encoding="utf-8")
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_folder)))
        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                'id': 'local_manual_bossrush',
                'name': 'BOSSRUSH',
                'author': 'Unknown',
                'description': 'Desc',
                'version': '1.0.0',
                'game': 'deltarune',
                'files': {
                    'deltarune_4': {
                        'extra_files': ['extras/bonus.zip'],
                    }
                },
            },
        )

        extra_inputs = [
            w
            for w in dialog.findChildren(type(dialog.icon_edit))
            if w.property("is_local_extra_path") and w.text()
        ]
        extra_labels = [
            w
            for w in dialog.findChildren(QLabel)
            if w.text().strip() == "bonus.zip"
        ]

        assert any(inp.text() == 'extras/bonus.zip' for inp in extra_inputs)
        assert not extra_labels
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_removes_stale_managed_files_after_replace_or_delete(
        self, qapp, tmp_path
    ):
        """Checks that moding editor removes stale managed files after replace or delete."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor_dialog import ModEditorDialog

        mod_folder = tmp_path / "managed_mod"
        chapter_folder = mod_folder / "chapter_4"
        chapter_folder.mkdir(parents=True)
        stale_data = chapter_folder / "old.win"
        stale_extra = chapter_folder / "old_extra.zip"
        fresh_data = chapter_folder / "new.win"
        stale_data.write_text("old-data", encoding="utf-8")
        stale_extra.write_text("old-extra", encoding="utf-8")
        fresh_data.write_text("new-data", encoding="utf-8")

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        dialog._remove_stale_managed_files(
            str(mod_folder),
            {
                "deltarune_4": {
                    "data_file_url": "old.win",
                    "extra_files": {"extras": ["old_extra.zip"]},
                }
            },
            {
                "deltarune_4": {
                    "data_file_url": "new.win",
                }
            },
            "deltarune",
        )

        assert not stale_data.exists()
        assert not stale_extra.exists()
        assert fresh_data.exists()
        dialog.close()
        parent.deleteLater()


class TestManualInstallDialog:
    """Tests for dialogs."""
    def test_manual_install_dialog_shows_summary_for_found_files(self, qapp, tmp_path):
        """Checks that manualing install dialog shows summary for found files."""
        from services.localization_service import tr
        from ui.dialogs.manual_install_dialog import ManualModInstallDialog

        prepared = tmp_path / 'prepared'
        prepared.mkdir()
        (prepared / 'README.md').write_text('# guide', encoding='utf-8')
        (prepared / 'mod.win').write_text('data', encoding='utf-8')

        dialog = ManualModInstallDialog(None, str(prepared))

        assert hasattr(dialog, 'files_summary_label')
        assert dialog.files_summary_label.text()
        assert dialog.game_combo.toolTip() == tr("tooltips.manual_install_game")
        assert dialog.files_summary_label.toolTip() == tr("tooltips.manual_install_summary")
        dialog.close()

    def test_manual_install_dialog_ignores_gamebanana_game_for_default_selection(
        self, qapp, tmp_path
    ):
        """Checks that manualing install dialog ignores gamebanana game for default selection."""
        from ui.dialogs.manual_install_dialog import ManualModInstallDialog

        prepared = tmp_path / "prepared"
        prepared.mkdir()
        (prepared / "README.md").write_text("# guide", encoding="utf-8")

        dialog = ManualModInstallDialog(
            None,
            str(prepared),
            gamebanana_metadata={"game": "pizzatower"},
        )

        assert dialog.game_combo.currentData() != "pizzatower"
        dialog.close()
