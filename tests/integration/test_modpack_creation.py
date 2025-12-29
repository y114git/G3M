import os
import json
from unittest.mock import Mock, MagicMock, patch
from models.game_modes import UndertaleGameMode, DemoGameMode, FullGameMode, UndertaleYellowGameMode, PizzaTowerGameMode
from managers.multi_mod_merger import MultiModMerger


class TestModpackCreation:

    def _create_mock_mod(self, game: str, chapter_id: int, mod_name: str, temp_mods_dir: str) -> Mock:
        from utils.file_utils import get_chapter_folder_name
        mod_key = f'test_mod_{game}_{chapter_id}_{mod_name}'
        mod_folder = os.path.join(temp_mods_dir, mod_key)
        os.makedirs(mod_folder, exist_ok=True)

        chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
        chapter_dir = os.path.join(mod_folder, chapter_folder_name)
        os.makedirs(chapter_dir, exist_ok=True)

        test_file = os.path.join(chapter_dir, 'test_file.txt')
        with open(test_file, 'w') as f:
            f.write(f'Test content from {mod_name}')

        config_data = {
            'key': mod_key,
            'name': mod_name,
            'version': '1.0.0',
            'game': game,
            'files': {str(chapter_id): {}}
        }
        config_path = os.path.join(mod_folder, 'mod_config.json')
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2)

        mod = Mock()
        mod.name = mod_name
        mod.game = game
        mod.modgame = game
        mod.config_data = config_data
        mod.key = mod_key
        mod.folder_path = mod_folder

        return mod

    def _setup_game_paths(self, app_state, temp_dir, game_type: str):
        game_base_dir = os.path.join(temp_dir, f'game_{game_type}')
        os.makedirs(game_base_dir, exist_ok=True)
        if game_type == 'deltarune':
            for chapter_id in [0, 1, 2]:
                chapter_dir = os.path.join(game_base_dir, f'chapter{chapter_id}_menu' if chapter_id == 0 else f'chapter{chapter_id}_')
                os.makedirs(chapter_dir, exist_ok=True)
                data_win = os.path.join(chapter_dir, 'data.win')
                with open(data_win, 'wb') as f:
                    f.write(b'fake data.win content')
        elif game_type == 'undertale':
            data_win = os.path.join(game_base_dir, 'data.win')
            with open(data_win, 'wb') as f:
                f.write(b'fake data.win content')
        elif game_type == 'deltarune_demo':
            data_win = os.path.join(game_base_dir, 'data.win')
            with open(data_win, 'wb') as f:
                f.write(b'fake data.win content')

        if game_type == 'deltarune':
            app_state.game_path = game_base_dir
            app_state.local_config['game_path'] = game_base_dir
        elif game_type == 'undertale':
            app_state.undertale_game_path = game_base_dir
            app_state.local_config['undertale_game_path'] = game_base_dir
        elif game_type == 'deltarune_demo':
            app_state.demo_game_path = game_base_dir
            app_state.local_config['demo_game_path'] = game_base_dir

        return game_base_dir

    @patch('managers.multi_mod_merger.UtmtWrapper')
    def test_modpack_creation_undertale_mode_deltarune_mods(self, mock_utmt_class, app_state, feedback_manager, temp_mods_dir, temp_dir):
        mock_utmt = MagicMock()
        mock_utmt.is_available.return_value = True
        mock_utmt.get_platform.return_value = 'windows'
        mock_utmt.get_script_path.return_value = '/fake/script/path'
        mock_utmt.execute_scripts.return_value = (0, '', '')
        mock_utmt_class.return_value = mock_utmt

        app_state.game_mode = UndertaleGameMode()
        self._setup_game_paths(app_state, temp_dir, 'undertale')
        self._setup_game_paths(app_state, temp_dir, 'deltarune')

        mod1 = self._create_mock_mod('deltarune', 1, 'Deltarune Mod 1', temp_mods_dir)
        mod2 = self._create_mock_mod('deltarune', 1, 'Deltarune Mod 2', temp_mods_dir)

        mod_manager = Mock()
        merger = MultiModMerger(app_state, mod_manager)

        modpack_dir = os.path.join(temp_dir, 'test_modpack')
        os.makedirs(modpack_dir, exist_ok=True)

        chapter_mods = {1: [mod1, mod2]}

        success = merger.process_mod_merge(chapter_mods, is_modpack=True, modpack_dir=modpack_dir, fast_merge=True)

        assert success, "Modpack creation should succeed even with mismatched game mode"
        assert os.path.exists(modpack_dir), "Modpack directory should exist"
        for root, dirs, files in os.walk(modpack_dir):
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.isfile(file_path):
                    file_size = os.path.getsize(file_path)
                    assert file_size > 0, f"File {file_path} should not be empty (size: {file_size})"

    @patch('managers.multi_mod_merger.UtmtWrapper')
    def test_modpack_creation_deltarune_mode_undertale_mods(self, mock_utmt_class, app_state, feedback_manager, temp_mods_dir, temp_dir):
        mock_utmt = MagicMock()
        mock_utmt.is_available.return_value = True
        mock_utmt.get_platform.return_value = 'windows'
        mock_utmt.get_script_path.return_value = '/fake/script/path'
        mock_utmt.execute_scripts.return_value = (0, '', '')
        mock_utmt_class.return_value = mock_utmt

        app_state.game_mode = FullGameMode()
        self._setup_game_paths(app_state, temp_dir, 'deltarune')
        self._setup_game_paths(app_state, temp_dir, 'undertale')

        mod1 = self._create_mock_mod('undertale', 0, 'Undertale Mod 1', temp_mods_dir)

        mod_manager = Mock()
        merger = MultiModMerger(app_state, mod_manager)

        modpack_dir = os.path.join(temp_dir, 'test_modpack_ut')
        os.makedirs(modpack_dir, exist_ok=True)

        chapter_mods = {0: [mod1]}

        success = merger.process_mod_merge(chapter_mods, is_modpack=True, modpack_dir=modpack_dir, fast_merge=True)

        assert success, "Modpack creation should succeed even with mismatched game mode"
        assert os.path.exists(modpack_dir), "Modpack directory should exist"
        for root, dirs, files in os.walk(modpack_dir):
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.isfile(file_path):
                    file_size = os.path.getsize(file_path)
                    assert file_size > 0, f"File {file_path} should not be empty"

    @patch('managers.multi_mod_merger.UtmtWrapper')
    def test_modpack_creation_all_game_types(self, mock_utmt_class, app_state, feedback_manager, temp_mods_dir, temp_dir):
        mock_utmt = MagicMock()
        mock_utmt.is_available.return_value = True
        mock_utmt.get_platform.return_value = 'windows'
        mock_utmt.get_script_path.return_value = '/fake/script/path'
        mock_utmt.execute_scripts.return_value = (0, '', '')
        mock_utmt_class.return_value = mock_utmt

        game_types = [
            ('deltarune', FullGameMode()),
            ('deltarune_demo', DemoGameMode()),
            ('undertale', UndertaleGameMode()),
            ('undertaleyellow', UndertaleYellowGameMode()),
            ('pizzatower', PizzaTowerGameMode())
        ]

        for game_type, game_mode in game_types:
            app_state.game_mode = game_mode
            self._setup_game_paths(app_state, temp_dir, game_type.replace('_', ''))

            mod = self._create_mock_mod(game_type, 0 if game_type in ('undertale', 'undertaleyellow', 'pizzatower') else 1, f'{game_type} Mod', temp_mods_dir)

            mod_manager = Mock()
            merger = MultiModMerger(app_state, mod_manager)

            modpack_dir = os.path.join(temp_dir, f'test_modpack_{game_type}')
            os.makedirs(modpack_dir, exist_ok=True)

            chapter_id = 0 if game_type in ('undertale', 'undertaleyellow', 'pizzatower') else 1
            chapter_mods = {chapter_id: [mod]}

            success = merger.process_mod_merge(chapter_mods, is_modpack=True, modpack_dir=modpack_dir, fast_merge=True)

            assert success, f"Modpack creation should succeed for {game_type}"
            assert os.path.exists(modpack_dir), f"Modpack directory should exist for {game_type}"

    @patch('managers.multi_mod_merger.UtmtWrapper')
    def test_modpack_creation_with_conflicts(self, mock_utmt_class, app_state, feedback_manager, temp_mods_dir, temp_dir):
        mock_utmt = MagicMock()
        mock_utmt.is_available.return_value = True
        mock_utmt.get_platform.return_value = 'windows'
        mock_utmt.get_script_path.return_value = '/fake/script/path'
        mock_utmt.execute_scripts.return_value = (0, '', '')
        mock_utmt_class.return_value = mock_utmt

        app_state.game_mode = FullGameMode()
        self._setup_game_paths(app_state, temp_dir, 'deltarune')

        mod1 = self._create_mock_mod('deltarune', 1, 'Conflicting Mod 1', temp_mods_dir)
        mod2 = self._create_mock_mod('deltarune', 1, 'Conflicting Mod 2', temp_mods_dir)

        from utils.file_utils import get_chapter_folder_name
        for mod in [mod1, mod2]:
            chapter_folder_name = get_chapter_folder_name(1, game='deltarune')
            chapter_dir = os.path.join(mod.folder_path, chapter_folder_name)
            conflict_file = os.path.join(chapter_dir, 'conflict.txt')
            with open(conflict_file, 'w') as f:
                f.write(f'Content from {mod.name}')

        mod_manager = Mock()
        merger = MultiModMerger(app_state, mod_manager)

        modpack_dir = os.path.join(temp_dir, 'test_modpack_conflicts')
        os.makedirs(modpack_dir, exist_ok=True)

        chapter_mods = {1: [mod1, mod2]}

        success = merger.process_mod_merge(chapter_mods, is_modpack=True, modpack_dir=modpack_dir, fast_merge=True)

        assert success, "Modpack creation should succeed even with conflicts"

        empty_files = []
        for root, dirs, files in os.walk(modpack_dir):
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.isfile(file_path):
                    file_size = os.path.getsize(file_path)
                    if file_size == 0:
                        empty_files.append(file_path)

        assert len(empty_files) == 0, f"Found empty files in modpack: {empty_files}"

    @patch('managers.multi_mod_merger.UtmtWrapper')
    def test_modpack_config_json_game_type(self, mock_utmt_class, app_state, feedback_manager, temp_mods_dir, temp_dir):
        mock_utmt = MagicMock()
        mock_utmt.is_available.return_value = True
        mock_utmt.get_platform.return_value = 'windows'
        mock_utmt.get_script_path.return_value = '/fake/script/path'
        mock_utmt.execute_scripts.return_value = (0, '', '')
        mock_utmt_class.return_value = mock_utmt

        app_state.game_mode = UndertaleGameMode()
        self._setup_game_paths(app_state, temp_dir, 'undertale')
        self._setup_game_paths(app_state, temp_dir, 'deltarune')

        mod1 = self._create_mock_mod('deltarune', 1, 'Deltarune Mod', temp_mods_dir)

        mod_manager = Mock()
        merger = MultiModMerger(app_state, mod_manager)

        modpack_dir = os.path.join(temp_dir, 'test_modpack_config')
        os.makedirs(modpack_dir, exist_ok=True)

        chapter_mods = {1: [mod1]}

        success = merger.process_mod_merge(chapter_mods, is_modpack=True, modpack_dir=modpack_dir, fast_merge=True)
        assert success, "Modpack creation should succeed"
        assert os.path.exists(modpack_dir), "Modpack directory should exist"

    @patch('managers.multi_mod_merger.UtmtWrapper')
    def test_modpack_creation_multiple_chapters(self, mock_utmt_class, app_state, feedback_manager, temp_mods_dir, temp_dir):
        mock_utmt = MagicMock()
        mock_utmt.is_available.return_value = True
        mock_utmt.get_platform.return_value = 'windows'
        mock_utmt.get_script_path.return_value = '/fake/script/path'
        mock_utmt.execute_scripts.return_value = (0, '', '')
        mock_utmt_class.return_value = mock_utmt

        app_state.game_mode = FullGameMode()
        self._setup_game_paths(app_state, temp_dir, 'deltarune')

        mod1_ch1 = self._create_mock_mod('deltarune', 1, 'Mod Chapter 1', temp_mods_dir)
        mod1_ch2 = self._create_mock_mod('deltarune', 2, 'Mod Chapter 2', temp_mods_dir)

        mod_manager = Mock()
        merger = MultiModMerger(app_state, mod_manager)

        modpack_dir = os.path.join(temp_dir, 'test_modpack_multi')
        os.makedirs(modpack_dir, exist_ok=True)

        chapter_mods = {1: [mod1_ch1], 2: [mod1_ch2]}

        success = merger.process_mod_merge(chapter_mods, is_modpack=True, modpack_dir=modpack_dir, fast_merge=True)

        assert success, "Modpack creation should succeed with multiple chapters"
        assert os.path.exists(modpack_dir), "Modpack directory should exist"

        for root, dirs, files in os.walk(modpack_dir):
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.isfile(file_path):
                    file_size = os.path.getsize(file_path)
                    assert file_size > 0, f"File {file_path} should not be empty"

    def test_get_target_dir_with_game_parameter(self, app_state, temp_dir):
        app_state.game_mode = UndertaleGameMode()
        self._setup_game_paths(app_state, temp_dir, 'undertale')
        self._setup_game_paths(app_state, temp_dir, 'deltarune')

        mod_manager = Mock()
        merger = MultiModMerger(app_state, mod_manager)

        target_dir = merger._get_target_dir(1, game='deltarune')

        assert target_dir is not None, "Should find target directory for deltarune chapter 1"
        assert 'deltarune' in target_dir.lower() or 'chapter1' in target_dir.lower(), f"Target dir should be for deltarune: {target_dir}"
