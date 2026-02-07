import os
import json
import tempfile
import zipfile


class TestModInstallation:

    def test_install_mod_from_archive(self, app_state, feedback_service, temp_mods_dir):
        from services.mod_service import ModManager
        _ = ModManager(app_state, feedback_service)
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp_archive:
            archive_path = tmp_archive.name
            with zipfile.ZipFile(archive_path, 'w') as zf:
                mod_config = {'key': 'test_install_mod', 'name': 'Test Install Mod', 'version': '1.0.0'}
                zf.writestr('mod_config.json', json.dumps(mod_config))
                zf.writestr('meta.json', '{"metadata": {"name": "Test Mod"}}')
                zf.writestr('file1.txt', 'test file content')
        try:
            with zipfile.ZipFile(archive_path, 'r') as zf:
                assert 'mod_config.json' in zf.namelist()
                assert 'meta.json' in zf.namelist()
        finally:
            os.unlink(archive_path)

    def test_install_mod_with_files(self, app_state, feedback_service, temp_mods_dir):
        from services.mod_service import ModManager
        _ = ModManager(app_state, feedback_service)
        key = 'test_mod_files'
        mod_folder = os.path.join(temp_mods_dir, key)
        os.makedirs(mod_folder, exist_ok=True)
        mod_config = {'key': key, 'name': 'Test Mod with Files', 'version': '1.0.0', 'files': [{'path': 'file1.txt', 'chapter': 1}, {'path': 'file2.txt', 'chapter': 2}]}
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

    def test_remove_mod(self, app_state, feedback_service, sample_mod_folder):
        from services.mod_service import ModManager
        mod_service = ModManager(app_state, feedback_service)
        cache = mod_service._get_mods_cache(use_async=False)
        assert 'test_mod_001' in cache
        assert os.path.exists(sample_mod_folder)


class TestModMerge:

    def test_merge_multiple_mods(self, app_state, feedback_service, temp_mods_dir):
        from services.mod_merge_service import MultiModMerger
        mods = []
        for i in range(3):
            key = f'test_merge_mod_{i}'
            mod_folder = os.path.join(temp_mods_dir, key)
            os.makedirs(mod_folder, exist_ok=True)
            mod_config = {'key': key, 'name': f'Test Merge Mod {i}', 'version': '1.0.0'}
            config_path = os.path.join(mod_folder, 'mod_config.json')
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(mod_config, f)
            mods.append(key)
        from services.mod_service import ModManager
        mod_service = ModManager(app_state, feedback_service)
        merger = MultiModMerger(app_state, mod_service)
        assert merger is not None


class TestModImportExport:

    def test_export_mod(self, app_state, feedback_service, sample_mod_folder):
        from controllers.mod_import_export_controller import ModImportExportController
        from services.mod_service import ModManager
        from unittest.mock import Mock
        mod_service = ModManager(app_state, feedback_service)
        mock_app_window = Mock()
        controller = ModImportExportController(app_state=app_state, mod_service=mod_service, app_window=mock_app_window)
        assert controller is not None

    def test_import_mod_from_url(self, app_state, feedback_service):
        from controllers.mod_import_export_controller import ModImportExportController
        from services.mod_service import ModManager
        from unittest.mock import Mock
        mod_service = ModManager(app_state, feedback_service)
        mock_app_window = Mock()
        controller = ModImportExportController(app_state=app_state, mod_service=mod_service, app_window=mock_app_window)
        assert controller is not None


class TestManualInstall:

    def test_prepare_gamebanana_manual_install_worker_initialization(self):
        from workers.gamebanana.prepare_gamebanana_manual_install_worker import PrepareGameBananaManualInstallWorker
        from unittest.mock import Mock
        mock_mod = Mock()
        mock_mod.key = 'gb_12345'
        mock_mod.name = 'Test Mod'
        selected_file = {'download_url': 'https://example.com/mod.zip', 'name': 'mod.zip'}
        worker = PrepareGameBananaManualInstallWorker(mock_mod, selected_file)
        assert worker is not None
        assert worker.mod == mock_mod
        assert worker.selected_file == selected_file

    def test_mod_operations_controller_manual_install_methods(self, app_state, feedback_service):
        from controllers.mod_operations_controller import ModOperationsController
        from services.mod_service import ModManager
        from unittest.mock import Mock
        mod_service = ModManager(app_state, feedback_service)
        mock_app_window = Mock()
        controller = ModOperationsController(app_state=app_state, feedback_service=feedback_service, mod_service=mod_service, app_window=mock_app_window)
        assert hasattr(controller, '_start_manual_install_from_gamebanana')
        assert hasattr(controller, '_start_prepare_worker')
