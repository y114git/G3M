from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QDialog, QPushButton, QWidget


class TestImportDialog:

    def test_import_dialog_creation(self, qapp, feedback_service):
        from ui.dialogs.import_dialog import ImportDialog
        dialog = ImportDialog(None, feedback_service, 'mods')
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestGameBananaFilePickerDialog:

    def test_file_picker_dialog_creation(self, qapp):
        from ui.dialogs.file_picker_dialog import GameBananaFilePickerDialog
        dialog = GameBananaFilePickerDialog(None, [], 'Test Mod')
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestCreateModpackDialog:

    def test_create_modpack_dialog_creation(self, qapp, app_state):
        from ui.dialogs.modpack_create_dialog import CreateModpackDialog
        dialog = CreateModpackDialog(app_state, None)
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestConflictsDialog:

    def test_conflicts_dialog_creation(self, qapp, temp_dir):
        import os

        from ui.dialogs.conflicts_dialog import ConflictsDialog
        report_path = os.path.join(temp_dir, 'test_report.md')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('## Merge Report\n\nTotal conflicts: 2\nAuto-resolved: 1\n')
        dialog = ConflictsDialog(report_path, None)
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestModPriorityDialog:

    def test_mod_priority_dialog_creation(self, qapp, app_state):
        from models.mod_models import ModInfo
        from ui.dialogs.mod_priority_dialog import ModPriorityDialog
        mods_list = [ModInfo(id='test_mod_1', name='Test Mod 1', version='1.0.0', author='Author', description='', game_version='', description_url='', downloads=0, game='deltarune')]
        dialog = ModPriorityDialog(mods_list, 1, app_state, None)
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestReportBugDialog:

    def test_report_bug_dialog_creation(self, qapp, app_state):
        from services.localization_service import tr
        from ui.dialogs.report_bug_dialog import ReportBugDialog
        dialog = ReportBugDialog(None, app_state)
        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert hasattr(dialog, 'text_edit')
        assert hasattr(dialog, 'file_list')
        assert hasattr(dialog, 'attach_logs_checkbox')
        assert hasattr(dialog, 'send_button')
        assert dialog.max_total_size == 10 * 1024 * 1024
        assert dialog.text_edit.toolTip() == tr("tooltips.report_bug_text")
        assert dialog.file_list.toolTip() == tr("tooltips.report_bug_files")
        assert dialog.attach_logs_checkbox.toolTip() == tr("tooltips.report_bug_attach_logs")
        assert dialog.send_button.toolTip() == tr("tooltips.report_bug_send")
        dialog.close()


class TestAboutDialog:

    def test_about_dialog_creation(self, qapp, app_state, temp_dir):
        from models.plugin_models import PLUGIN_API_VERSION
        from ui.dialogs.about_dialog import AboutDialog
        callback = Mock()
        dialog = AboutDialog(None, app_state, on_report_bug=callback)
        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert dialog.title_label.text() == 'DELTAHUB'
        assert dialog.data_path_edit.text() == temp_dir
        assert dialog.plugin_api_value.text() == PLUGIN_API_VERSION
        assert dialog.report_bug_button.isEnabled()
        assert dialog.os_value.text()
        assert dialog.python_value.text()
        dialog.close()

    def test_about_dialog_actions(self, qapp, app_state):
        from ui.dialogs.about_dialog import AboutDialog
        callback = Mock()
        dialog = AboutDialog(None, app_state, on_report_bug=callback)
        with patch('ui.dialogs.about_dialog.QDesktopServices.openUrl') as open_url:
            dialog.wiki_button.click()
            dialog.open_folder_button.click()
        assert open_url.call_count == 2
        dialog.report_bug_button.click()
        callback.assert_called_once()
        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_about_dialog_disables_report_bug_without_callback(self, qapp, app_state):
        from ui.dialogs.about_dialog import AboutDialog
        dialog = AboutDialog(None, app_state)
        assert not dialog.report_bug_button.isEnabled()
        dialog.close()


class TestChangelogDialog:

    def test_changelog_dialog_creation_without_source(self, qapp):
        from ui.dialogs.changelog_dialog import ChangelogDialog
        dialog = ChangelogDialog(None, '')
        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert hasattr(dialog, 'text_browser')
        assert hasattr(dialog, 'close_button')
        dialog.close()


class TestThemeManagementDialog:

    def test_theme_management_dialog_creation(self, qapp, app_state):
        from unittest.mock import Mock

        from services.localization_service import tr
        from services.customization_service import CustomizationManager
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


class TestDialogTheme:

    def test_dialog_theme_uses_hover_color_for_selection(self, app_state):
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

    def test_mod_editor_populates_saved_files_as_relative_paths(self, qapp, tmp_path):
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
                        'data_file_url': 'BOSSRUSH.win',
                        'extra_files': {'extras': ['bonus.zip']},
                    }
                },
            },
        )

        collected = dialog._collect_files()

        assert dialog.icon_edit.text() == 'icon.png'
        assert dialog.findChild(QWidget, 'modEditorIntroCard') is None
        assert collected['deltarune_4']['data_file_url'] == 'BOSSRUSH.win'
        assert collected['deltarune_4']['extra_files']['extras'] == ['bonus.zip']
        assert dialog._resolve_file_path('BOSSRUSH.win') == str(
            chapter_folder / 'BOSSRUSH.win'
        )
        dialog.close()
        parent.deleteLater()


class TestManualInstallDialog:

    def test_manual_install_dialog_shows_summary_for_found_files(self, qapp, tmp_path):
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


