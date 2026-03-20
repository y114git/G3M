"""Tests for the library profiles system."""
import json
import os

import pytest


@pytest.fixture
def profiles_dir(temp_dir):
    d = os.path.join(temp_dir, 'profiles')
    os.makedirs(d, exist_ok=True)
    return d


@pytest.fixture
def profile_service(app_state, feedback_service, temp_dir, profiles_dir, monkeypatch):
    from services.settings_service import SettingsManager
    from services.profile_service import ProfileService

    monkeypatch.setattr('services.profile_service.get_user_data_root', lambda: temp_dir)
    settings_service = SettingsManager(app_state, feedback_service, None, parent=None)
    app_state.local_config = {
        'selected_game_type': 'deltarune',
        'chapter_mode_enabled': True,
        'full_install_enabled': False,
        'direct_launch_chapter': 'ch2',
        'used_mods_deltarune': {'mod_a': True},
        'some_other_setting': 'keep_me',
    }
    svc = ProfileService(app_state, settings_service, parent=None)
    return svc


class TestProfileMigration:

    def test_migrate_creates_default_json(self, profile_service, profiles_dir, app_state):
        profile_service.initialize()
        default_path = os.path.join(profiles_dir, 'Default.json')
        assert os.path.exists(default_path)
        with open(default_path, encoding='utf-8') as f:
            data = json.loads(f.read())
        assert data['selected_game_type'] == 'deltarune'
        assert data['chapter_mode_enabled'] is True
        assert data['used_mods_deltarune'] == {'mod_a': True}
        assert 'some_other_setting' not in data

    def test_migrate_removes_profile_keys_from_settings_json(self, profile_service, app_state):
        profile_service.initialize()
        profile_service.save_settings_only()
        settings = json.loads(open(app_state.config_path, encoding='utf-8').read())
        assert 'selected_game_type' not in settings
        assert 'used_mods_deltarune' not in settings
        assert settings['some_other_setting'] == 'keep_me'

    def test_migrate_is_idempotent(self, profile_service, profiles_dir):
        profile_service.initialize()
        default_path = os.path.join(profiles_dir, 'Default.json')
        data_before = open(default_path, encoding='utf-8').read()
        profile_service._migrate_from_settings()
        data_after = open(default_path, encoding='utf-8').read()
        assert data_before == data_after


class TestProfileCRUD:

    def test_create_profile(self, profile_service):
        profile_service.initialize()
        assert profile_service.create('gaming')
        assert 'gaming' in profile_service.list_profiles()

    def test_create_duplicate_name_fails(self, profile_service):
        profile_service.initialize()
        profile_service.create('gaming')
        assert not profile_service.create('gaming')

    def test_duplicate_profile(self, profile_service, profiles_dir):
        profile_service.initialize()
        assert profile_service.duplicate('Default', 'copy_of_default')
        copy_path = os.path.join(profiles_dir, 'copy_of_default.json')
        assert os.path.exists(copy_path)
        data = json.loads(open(copy_path, encoding='utf-8').read())
        assert data.get('selected_game_type') == 'deltarune'

    def test_rename_profile(self, profile_service, profiles_dir):
        profile_service.initialize()
        profile_service.create('old_name')
        assert profile_service.rename('old_name', 'new_name')
        assert not os.path.exists(os.path.join(profiles_dir, 'old_name.json'))
        assert os.path.exists(os.path.join(profiles_dir, 'new_name.json'))
        assert 'new_name' in profile_service.list_profiles()
        assert 'old_name' not in profile_service.list_profiles()

    def test_rename_default_fails(self, profile_service):
        profile_service.initialize()
        assert not profile_service.rename('Default', 'something')

    def test_delete_profile(self, profile_service, profiles_dir):
        profile_service.initialize()
        profile_service.create('deleteme')
        assert profile_service.delete('deleteme')
        assert not os.path.exists(os.path.join(profiles_dir, 'deleteme.json'))

    def test_delete_default_fails(self, profile_service):
        profile_service.initialize()
        assert not profile_service.delete('Default')

    def test_list_profiles_contains_default(self, profile_service):
        profile_service.initialize()
        profile_service.create('zzz')
        profile_service.create('aaa')
        profiles = profile_service.list_profiles()
        assert 'Default' in profiles


class TestProfileSwitching:

    def test_switch_loads_new_profile_data(self, profile_service, app_state):
        profile_service.initialize()
        profile_service.create('alt')
        alt_data = {'selected_game_type': 'undertale', 'chapter_mode_enabled': False}
        profile_service._write_profile('alt', alt_data)
        profile_service.switch('alt')
        assert app_state.local_config['selected_game_type'] == 'undertale'
        assert app_state.local_config.get('chapter_mode_enabled') is False
        assert profile_service.active_name == 'alt'

    def test_switch_saves_previous_profile(self, profile_service, app_state, profiles_dir):
        profile_service.initialize()
        profile_service.create('alt')
        app_state.local_config['selected_game_type'] = 'pizzatower'
        profile_service.switch('alt')
        default_data = json.loads(open(os.path.join(profiles_dir, 'Default.json'), encoding='utf-8').read())
        assert default_data['selected_game_type'] == 'pizzatower'

    def test_switch_preserves_non_profile_settings(self, profile_service, app_state):
        profile_service.initialize()
        app_state.local_config['some_other_setting'] = 'preserved'
        profile_service.create('alt')
        profile_service.switch('alt')
        assert app_state.local_config['some_other_setting'] == 'preserved'


class TestProfileSummary:

    def test_get_profile_summary(self, profile_service):
        profile_service.initialize()
        summary = profile_service.get_profile_summary('Default')
        assert summary['name'] == 'Default'
        assert summary['game'] == 'deltarune'
        assert summary['game_display_name'] == 'DELTARUNE'
        assert summary['chapter_mode'] is True
        assert summary['game_mod_count'] == 1
        assert summary['total_mod_count'] == 1

    def test_summary_counts_individual_mods(self, profile_service, profiles_dir):
        profile_service.initialize()
        profile_service.create('multi')
        profile_service._write_profile('multi', {
            'selected_game_type': 'deltarune',
            'used_mods_deltarune': {'ch1': 'mod_a', 'ch2': ['mod_b', 'mod_c', 'mod_d']},
            'used_mods_undertale': {'ut': ['mod_x', 'mod_y']},
        })
        summary = profile_service.get_profile_summary('multi')
        assert summary['game_mod_count'] == 4
        assert summary['total_mod_count'] == 6


class TestSaveActiveMerge:

    def test_save_active_preserves_keys_not_in_config(self, profile_service, app_state, profiles_dir):
        profile_service.initialize()
        profile_service._write_profile('Default', {
            'selected_game_type': 'deltarune',
            'used_mods_deltarune': {'ch1': 'mod_a'},
            'used_mods_undertale': {'ut': 'mod_b'},
        })
        for k in [k for k in app_state.local_config if k.startswith('used_mods_undertale')]:
            del app_state.local_config[k]
        profile_service.save_active()
        data = json.loads(open(os.path.join(profiles_dir, 'Default.json'), encoding='utf-8').read())
        assert data['used_mods_undertale'] == {'ut': 'mod_b'}


class TestWriteLocalConfig:

    def test_write_local_config_splits_data(self, profile_service, app_state, profiles_dir):
        profile_service.initialize()
        app_state.local_config['selected_game_type'] = 'undertale'
        app_state.local_config['some_other_setting'] = 'hello'
        profile_service.write_local_config()
        settings = json.loads(open(app_state.config_path, encoding='utf-8').read())
        assert 'selected_game_type' not in settings
        assert settings['some_other_setting'] == 'hello'
        default_data = json.loads(open(os.path.join(profiles_dir, 'Default.json'), encoding='utf-8').read())
        assert default_data['selected_game_type'] == 'undertale'


class TestReorder:

    def test_reorder_profiles(self, profile_service, app_state):
        profile_service.initialize()
        profile_service.create('b')
        profile_service.create('a')
        profile_service.reorder(['a', 'Default', 'b'])
        profiles = profile_service.list_profiles()
        assert profiles[0] == 'a'
        assert profiles[1] == 'Default'
        assert profiles[2] == 'b'
