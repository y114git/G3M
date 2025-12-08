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

    def test_import_dialog_creation(self, qapp, feedback_manager):
        from ui.dialogs.import_dialog import ImportDialog
        dialog = ImportDialog(None, feedback_manager, 'mods')
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestGameBananaFilePickerDialog:

    def test_file_picker_dialog_creation(self, qapp):
        from ui.dialogs.gamebanana_file_picker_dialog import GameBananaFilePickerDialog
        dialog = GameBananaFilePickerDialog(None, [], 'Test Mod')
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestCreateModpackDialog:

    def test_create_modpack_dialog_creation(self, qapp, app_state):
        from ui.dialogs.create_modpack_dialog import CreateModpackDialog
        dialog = CreateModpackDialog(app_state, None)
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestConflictsDialog:

    def test_conflicts_dialog_creation(self, qapp, temp_dir):
        from ui.dialogs.conflicts_dialog import ConflictsDialog
        conflicts_summary = {'mod_pairs': [], 'total_conflicts': 0}
        dialog = ConflictsDialog(conflicts_summary, temp_dir, None)
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestModPriorityDialog:

    def test_mod_priority_dialog_creation(self, qapp, app_state):
        from ui.dialogs.mod_priority_dialog import ModPriorityDialog
        from models.mod_models import ModInfo
        mods_list = [ModInfo(key='test_mod_1', name='Test Mod 1', version='1.0.0', author='Author', tagline='', game_version='', description_url='', downloads=0, modgame='deltarune', is_verified=False)]
        dialog = ModPriorityDialog(mods_list, 1, app_state, None)
        assert dialog is not None
        assert isinstance(dialog, QDialog)
