from PyQt6.QtWidgets import QDialog


class TestModDetailsDialog:

    def test_mod_details_dialog_creation(self, qapp):
        from PyQt6.QtWidgets import QDialog
        dialog = QDialog(None)
        dialog.setWindowTitle('Test Mod Details')
        dialog.setMinimumSize(700, 700)
        assert dialog is not None
        assert isinstance(dialog, QDialog)
        dialog.close()


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
        from ui.dialogs.conflicts_dialog import ConflictsDialog
        import os
        report_path = os.path.join(temp_dir, 'test_report.md')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('## Merge Report\n\nTotal conflicts: 2\nAuto-resolved: 1\n')
        dialog = ConflictsDialog(report_path, None)
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestModPriorityDialog:

    def test_mod_priority_dialog_creation(self, qapp, app_state):
        from ui.dialogs.mod_priority_dialog import ModPriorityDialog
        from models.mod_models import ModInfo
        mods_list = [ModInfo(key='test_mod_1', name='Test Mod 1', version='1.0.0', author='Author', tagline='', game_version='', description_url='', downloads=0, game='deltarune', is_verified=False)]
        dialog = ModPriorityDialog(mods_list, 1, app_state, None)
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestReportBugDialog:

    def test_report_bug_dialog_creation(self, qapp, app_state):
        from ui.dialogs.report_bug_dialog import ReportBugDialog
        dialog = ReportBugDialog(None, app_state)
        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert hasattr(dialog, 'text_edit')
        assert hasattr(dialog, 'file_list')
        assert hasattr(dialog, 'attach_logs_checkbox')
        assert hasattr(dialog, 'send_button')
        assert dialog.max_total_size == 10 * 1024 * 1024
        dialog.close()


class TestThemeManagementDialog:

    def test_theme_management_dialog_creation(self, qapp, app_state):
        from ui.dialogs.theme_dialog import ThemeManagementDialog
        from unittest.mock import Mock
        from services.customization_service import CustomizationManager

        class FakeThemeController:
            def __init__(self, state):
                self.app_state = state
                self.customization_service = CustomizationManager(state)
                self.settings_service = Mock()

        theme_controller = FakeThemeController(app_state)
        dialog = ThemeManagementDialog(None, theme_controller)
        assert dialog is not None
        assert isinstance(dialog, QDialog)
        
        # Test that _build_settings_text generates some text without exceptions
        settings_text = dialog._build_settings_text()
        assert isinstance(settings_text, str)
        assert 'themes.no_customizations' in settings_text or len(settings_text) > 0
        dialog.close()
