import os
import json
import pytest
from pathlib import Path


class TestModStructure:

    def test_mod_config_parsing(self, mods_dir, full_mod_structure_dir):
        config_path = Path(full_mod_structure_dir) / 'mod_config.json'
        if not config_path.exists():
            pytest.skip('mod_config.json not found. Please create test mod structure.')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        assert 'key' in config or 'mod_key' in config
        assert 'name' in config
        assert 'version' in config
        assert 'files' in config
        assert isinstance(config['files'], dict)

    def test_mod_structure_validation(self, full_mod_structure_dir):
        mod_path = Path(full_mod_structure_dir)
        config_path = mod_path / 'mod_config.json'
        if not config_path.exists():
            pytest.skip('mod_config.json not found.')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        files = config.get('files', {})
        for chapter_key in files.keys():
            if chapter_key == '0':
                chapter_dir = mod_path / 'chapter_0'
            elif chapter_key == 'demo':
                chapter_dir = mod_path / 'demo'
            else:
                chapter_dir = mod_path / f'chapter_{chapter_key}'
            if files[chapter_key].get('data_file_url'):
                if chapter_dir.exists():
                    assert chapter_dir.is_dir()

    def test_mod_file_discovery(self, full_mod_structure_dir):
        mod_path = Path(full_mod_structure_dir)
        if not mod_path.exists():
            pytest.skip(f'Test mod structure not found at {full_mod_structure_dir}. Please create test mod structure.')
        chapter_dirs = [d for d in mod_path.iterdir() if d.is_dir() and d.name.startswith('chapter_')]
        assert len(chapter_dirs) > 0, 'No chapter directories found'
        for chapter_dir in chapter_dirs:
            files = list(chapter_dir.glob('*'))
            _ = [f for f in files if f.suffix in ['.win', '.xdelta', '.vcdiff']]
            assert chapter_dir.is_dir()


class TestModManagerIntegration:

    def test_mod_scanning(self, app_state, feedback_manager, mods_dir):
        from managers.mod_manager import ModManager
        app_state.mods_dir = mods_dir
        mod_manager = ModManager(app_state, feedback_manager)
        cache = mod_manager._get_mods_cache(use_async=False)
        assert isinstance(cache, dict)

    def test_mod_scanning_all_types(self, app_state, feedback_manager, all_test_mods_dirs):
        from managers.mod_manager import ModManager
        import tempfile
        import shutil
        temp_mods_dir = tempfile.mkdtemp()
        try:
            for mod_name, mod_path in all_test_mods_dirs.items():
                if os.path.exists(mod_path):
                    config_path = os.path.join(mod_path, 'mod_config.json')
                    if os.path.exists(config_path):
                        target_path = os.path.join(temp_mods_dir, os.path.basename(mod_path))
                        shutil.copytree(mod_path, target_path, dirs_exist_ok=True)
            app_state.mods_dir = temp_mods_dir
            mod_manager = ModManager(app_state, feedback_manager)
            cache = mod_manager._get_mods_cache(use_async=False)
            assert isinstance(cache, dict)
        finally:
            shutil.rmtree(temp_mods_dir, ignore_errors=True)

    def test_mod_loading(self, app_state, feedback_manager, full_mod_structure_dir):
        from managers.mod_manager import ModManager
        import shutil
        import tempfile
        temp_mods_dir = tempfile.mkdtemp()
        mod_name = Path(full_mod_structure_dir).name
        target_mod_dir = os.path.join(temp_mods_dir, mod_name)
        try:
            if os.path.exists(full_mod_structure_dir):
                shutil.copytree(full_mod_structure_dir, target_mod_dir)
                app_state.mods_dir = temp_mods_dir
                mod_manager = ModManager(app_state, feedback_manager)
                cache = mod_manager._get_mods_cache(use_async=False)
                config_path = os.path.join(target_mod_dir, 'mod_config.json')
                if os.path.exists(config_path):
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    key = config.get('key') or config.get('mod_key')
                    if key:
                        assert key in cache or any((info.key == key for info in cache.values()))
        finally:
            shutil.rmtree(temp_mods_dir, ignore_errors=True)


class TestModInstallation:

    def test_mod_installation_structure(self, app_state, feedback_manager, full_mod_structure_dir):
        from managers.mod_manager import ModManager
        _ = ModManager(app_state, feedback_manager)
        mod_path = Path(full_mod_structure_dir)
        config_path = mod_path / 'mod_config.json'
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            assert 'files' in config
            assert isinstance(config['files'], dict)


class TestModProcessing:

    def test_mod_file_resolution(self, full_mod_structure_dir):
        mod_path = Path(full_mod_structure_dir)
        config_path = mod_path / 'mod_config.json'
        if not config_path.exists():
            pytest.skip('mod_config.json not found.')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        files = config.get('files', {})
        for chapter_key, chapter_data in files.items():
            data_file_url = chapter_data.get('data_file_url')
            if data_file_url:
                if chapter_key == '0':
                    chapter_dir = mod_path / 'chapter_0'
                elif chapter_key == 'demo':
                    chapter_dir = mod_path / 'demo'
                else:
                    chapter_dir = mod_path / f'chapter_{chapter_key}'
                if chapter_dir.exists():
                    file_path = chapter_dir / data_file_url
                    assert file_path.parent == chapter_dir

    def test_mod_chapter_mapping(self, full_mod_structure_dir):
        mod_path = Path(full_mod_structure_dir)
        config_path = mod_path / 'mod_config.json'
        if not config_path.exists():
            pytest.skip('mod_config.json not found.')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        files = config.get('files', {})
        chapter_map = {'0': 'chapter_0', '1': 'chapter_1', '2': 'chapter_2', '3': 'chapter_3', '4': 'chapter_4', 'demo': 'demo'}
        for chapter_key in files.keys():
            expected_dir_name = chapter_map.get(chapter_key)
            if expected_dir_name:
                expected_dir = mod_path / expected_dir_name
                if expected_dir.exists():
                    assert expected_dir.is_dir()


class TestModMergingWithStructure:

    def test_multiple_mods_merging(self, app_state, feedback_manager, mods_dir):
        from managers.multi_mod_merger import MultiModMerger
        from unittest.mock import Mock
        mod_manager = Mock()
        merger = MultiModMerger(app_state, mod_manager)
        assert merger is not None
        assert hasattr(merger, 'utmt_wrapper')
        assert hasattr(merger, 'xdelta_path')

    def test_mod_priority_with_structure(self, app_state, feedback_manager):
        from managers.multi_mod_merger import MultiModMerger
        from unittest.mock import Mock
        mod_manager = Mock()
        merger = MultiModMerger(app_state, mod_manager)
        assert merger is not None


class TestModMetadata:

    def test_metadata_read_write(self, app_state, feedback_manager):
        from managers.mod_manager import ModManager
        import time
        mod_manager = ModManager(app_state, feedback_manager)
        metadata = mod_manager._read_metadata()
        assert isinstance(metadata, dict), "_read_metadata should return a dict, even if file doesn't exist"
        if not os.path.exists(app_state.mods_metadata_path):
            assert metadata == {}, 'Empty metadata should return empty dict'
        test_metadata = {'test_mod_001': {'installed_date': time.strftime('%Y-%m-%d %H:%M:%S'), 'is_available_on_server': True}, 'test_mod_002': {'installed_date': '2024-01-01 00:00:00', 'is_available_on_server': False}}
        mod_manager._write_metadata(test_metadata)
        assert os.path.exists(app_state.mods_metadata_path), 'Metadata file should be created after write'
        written_metadata = mod_manager._read_metadata()
        assert isinstance(written_metadata, dict), 'Should read metadata as dict'
        assert 'test_mod_001' in written_metadata, 'Written mod should be in read metadata'
        assert 'test_mod_002' in written_metadata, 'All written mods should be in read metadata'
        assert written_metadata['test_mod_001']['is_available_on_server'], 'Metadata values should be preserved'
        assert written_metadata['test_mod_002']['is_available_on_server'] is False, 'All metadata values should be preserved'
        assert written_metadata['test_mod_002']['installed_date'] == '2024-01-01 00:00:00', 'Dates should be preserved'
        mod_manager._write_metadata({})

    def test_metadata_file_creation(self, app_state, feedback_manager):
        from managers.mod_manager import ModManager
        import os
        import json
        mod_manager = ModManager(app_state, feedback_manager)
        if os.path.exists(app_state.mods_metadata_path):
            os.remove(app_state.mods_metadata_path)
        assert not os.path.exists(app_state.mods_metadata_path), 'Metadata file should not exist initially'
        test_metadata = {'test_mod': {'installed_date': '2024-01-01 00:00:00'}}
        mod_manager._write_metadata(test_metadata)
        assert os.path.exists(app_state.mods_metadata_path), 'Metadata file should be created after write'
        with open(app_state.mods_metadata_path, 'r', encoding='utf-8') as f:
            file_content = json.load(f)
        assert isinstance(file_content, dict), 'Metadata file should contain valid JSON dict'
        assert 'test_mod' in file_content, 'Written mod should be in file'
        assert file_content['test_mod']['installed_date'] == '2024-01-01 00:00:00', 'Data in file should match written data'
        if os.path.exists(app_state.mods_metadata_path):
            os.remove(app_state.mods_metadata_path)

    def test_metadata_with_installed_mods(self, app_state, feedback_manager, full_mod_structure_dir):
        from managers.mod_manager import ModManager
        import shutil
        import tempfile
        import json
        temp_mods_dir = tempfile.mkdtemp()
        mod_name = Path(full_mod_structure_dir).name
        target_mod_dir = os.path.join(temp_mods_dir, mod_name)
        try:
            if os.path.exists(full_mod_structure_dir):
                shutil.copytree(full_mod_structure_dir, target_mod_dir)
                app_state.mods_dir = temp_mods_dir
                mod_manager = ModManager(app_state, feedback_manager)
                _ = mod_manager._get_mods_cache(use_async=False)
                installed_mods = mod_manager.get_installed_mods_list()
                assert isinstance(installed_mods, list)
                config_path = os.path.join(target_mod_dir, 'mod_config.json')
                if os.path.exists(config_path):
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    key = config.get('key') or config.get('mod_key')
                    if key:
                        metadata = mod_manager._read_metadata()
                        assert isinstance(metadata, dict)
        finally:
            shutil.rmtree(temp_mods_dir, ignore_errors=True)
