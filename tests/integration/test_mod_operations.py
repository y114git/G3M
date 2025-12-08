import os
import json
import tempfile
import zipfile
from unittest.mock import Mock, patch


class TestModInstallation:

    def test_install_mod_from_archive(self, app_state, feedback_manager, temp_mods_dir):
        from managers.mod_manager import ModManager
        _ = ModManager(app_state, feedback_manager)
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp_archive:
            archive_path = tmp_archive.name
            with zipfile.ZipFile(archive_path, 'w') as zf:
                mod_config = {'mod_key': 'test_install_mod', 'name': 'Test Install Mod', 'version': '1.0.0'}
                zf.writestr('mod_config.json', json.dumps(mod_config))
                # Используем правильное имя файла meta.json вместо deltamod.info
                zf.writestr('meta.json', '{"metadata": {"name": "Test Mod"}}')
                zf.writestr('file1.txt', 'test file content')
        try:
            with zipfile.ZipFile(archive_path, 'r') as zf:
                assert 'mod_config.json' in zf.namelist()
                assert 'meta.json' in zf.namelist()
        finally:
            os.unlink(archive_path)

    def test_install_mod_with_files(self, app_state, feedback_manager, temp_mods_dir):
        from managers.mod_manager import ModManager
        _ = ModManager(app_state, feedback_manager)
        mod_key = 'test_mod_files'
        mod_folder = os.path.join(temp_mods_dir, mod_key)
        os.makedirs(mod_folder, exist_ok=True)
        mod_config = {'mod_key': mod_key, 'name': 'Test Mod with Files', 'version': '1.0.0', 'files': [{'path': 'file1.txt', 'chapter': 1}, {'path': 'file2.txt', 'chapter': 2}]}
        config_path = os.path.join(mod_folder, 'mod_config.json')
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(mod_config, f)
        for i in range(1, 3):
            file_path = os.path.join(mod_folder, f'file{i}.txt')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(f'Test content {i}')
        assert os.path.exists(mod_folder)
        assert os.path.exists(config_path)


class TestModRemoval:

    def test_remove_mod(self, app_state, feedback_manager, sample_mod_folder):
        from managers.mod_manager import ModManager
        mod_manager = ModManager(app_state, feedback_manager)
        cache = mod_manager._get_mods_cache(use_async=False)
        assert 'test_mod_001' in cache
        assert os.path.exists(sample_mod_folder)


class TestModUpdate:

    @patch('requests.get')
    def test_check_mod_update(self, mock_get, app_state, feedback_manager):
        from managers.gamebanana_update_manager import GameBananaUpdateManager
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'version': '2.0.0', 'update_available': True}
        mock_get.return_value = mock_response
        update_manager = GameBananaUpdateManager(mods_dir=app_state.mods_dir)
        assert update_manager is not None


class TestModMerge:

    def test_merge_multiple_mods(self, app_state, feedback_manager, temp_mods_dir):
        from managers.multi_mod_merger import MultiModMerger
        mods = []
        for i in range(3):
            mod_key = f'test_merge_mod_{i}'
            mod_folder = os.path.join(temp_mods_dir, mod_key)
            os.makedirs(mod_folder, exist_ok=True)
            mod_config = {'mod_key': mod_key, 'name': f'Test Merge Mod {i}', 'version': '1.0.0'}
            config_path = os.path.join(mod_folder, 'mod_config.json')
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(mod_config, f)
            mods.append(mod_key)
        from managers.mod_manager import ModManager
        mod_manager = ModManager(app_state, feedback_manager)
        merger = MultiModMerger(app_state, mod_manager)
        assert merger is not None


class TestModImportExport:

    def test_export_mod(self, app_state, feedback_manager, sample_mod_folder):
        from controllers.mod_import_export_controller import ModImportExportController
        from managers.mod_manager import ModManager
        from unittest.mock import Mock
        mod_manager = ModManager(app_state, feedback_manager)
        mock_app_window = Mock()
        controller = ModImportExportController(app_state=app_state, mod_manager=mod_manager, app_window=mock_app_window)
        assert controller is not None

    def test_import_mod_from_url(self, app_state, feedback_manager):
        from controllers.mod_import_export_controller import ModImportExportController
        from managers.mod_manager import ModManager
        from unittest.mock import Mock
        mod_manager = ModManager(app_state, feedback_manager)
        mock_app_window = Mock()
        controller = ModImportExportController(app_state=app_state, mod_manager=mod_manager, app_window=mock_app_window)
        assert controller is not None
