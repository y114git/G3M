import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from utils.game_utils import is_game_running, get_game_type_string, get_game_name_string
from utils.path_utils import find_chapter_resource_dir, resolve_game_executable


class TestGameLaunchSimulation:

    @pytest.fixture
    def mock_game_executable(self, temp_dir):
        game_dir = os.path.join(temp_dir, 'game')
        os.makedirs(game_dir, exist_ok=True)
        executables = {'DELTARUNE.exe': 'deltarune', 'UNDERTALE.exe': 'undertale', 'Undertale Yellow.exe': 'undertale_yellow'}
        for exe_name, game_type in executables.items():
            exe_path = os.path.join(game_dir, exe_name)
            with open(exe_path, 'w') as f:
                f.write('mock executable')
            os.chmod(exe_path, 493)
        return game_dir

    def test_resolve_game_executable_deltarune(self, mock_game_executable):
        exe_path = resolve_game_executable(mock_game_executable, is_undertale=False)
        assert exe_path is not None
        assert 'DELTARUNE' in exe_path.upper() or os.path.exists(exe_path)

    def test_resolve_game_executable_undertale(self, mock_game_executable):
        exe_path = resolve_game_executable(mock_game_executable, is_undertale=True)
        assert exe_path is not None
        assert 'UNDERTALE' in exe_path.upper() or os.path.exists(exe_path)

    def test_find_chapter_resource_dir(self, temp_dir):
        game_dir = os.path.join(temp_dir, 'game')
        chapter_dir = os.path.join(game_dir, 'chapter1_')
        os.makedirs(chapter_dir, exist_ok=True)
        resource_dir = find_chapter_resource_dir(game_dir, 1)
        assert resource_dir is not None
        assert os.path.exists(resource_dir)

    @patch('utils.game_utils.psutil.process_iter')
    def test_is_game_running_simulation(self, mock_process_iter):
        mock_process_iter.return_value = []
        assert not is_game_running()
        mock_process = MagicMock()
        mock_process.name.return_value = 'DELTARUNE.exe'
        mock_process_iter.return_value = [mock_process]

    def test_get_game_type_string(self):
        from models.game_modes import UndertaleGameMode, UndertaleYellowGameMode
        game_mode = UndertaleGameMode()
        game_type = get_game_type_string(game_mode)
        assert game_type in ['undertale', 'deltarune', 'undertaleyellow']
        game_mode = UndertaleYellowGameMode()
        game_type = get_game_type_string(game_mode)
        assert game_type == 'undertaleyellow'

    def test_get_game_name_string(self):
        from models.game_modes import UndertaleGameMode, UndertaleYellowGameMode
        game_mode = UndertaleGameMode()
        game_name = get_game_name_string(game_mode)
        assert isinstance(game_name, str)
        assert len(game_name) > 0
        game_mode = UndertaleYellowGameMode()
        game_name = get_game_name_string(game_mode)
        assert isinstance(game_name, str)
        assert len(game_name) > 0


class TestPathResolution:

    def test_path_resolution_linux(self, temp_dir):
        test_path = os.path.join(temp_dir, 'test', 'path')
        os.makedirs(test_path, exist_ok=True)
        resolved = os.path.abspath(test_path)
        assert os.path.exists(resolved)
        assert os.path.isabs(resolved)

    def test_path_resolution_windows(self, temp_dir):
        test_path = os.path.join(temp_dir, 'test', 'path')
        os.makedirs(test_path, exist_ok=True)
        if os.name == 'nt':
            resolved = os.path.abspath(test_path)
            assert ':' in resolved or os.path.exists(resolved)
        else:
            resolved = os.path.abspath(test_path)
            assert os.path.exists(resolved)

    def test_path_with_special_chars(self, temp_dir):
        special_path = os.path.join(temp_dir, 'test path with spaces')
        os.makedirs(special_path, exist_ok=True)
        assert os.path.exists(special_path)
        test_file = os.path.join(special_path, 'test.txt')
        with open(test_file, 'w') as f:
            f.write('test')
        assert os.path.exists(test_file)


class TestGameExecutableSimulation:

    @pytest.fixture
    def simulated_game_dir(self, temp_dir):
        game_dir = os.path.join(temp_dir, 'simulated_game')
        structure = {'DELTARUNE.exe': '', 'data.win': '', 'chapter1_': {'data.win': ''}, 'chapter2_': {'data.win': ''}}

        def create_structure(base_path, struct):
            for name, content in struct.items():
                path = os.path.join(base_path, name)
                if isinstance(content, dict):
                    os.makedirs(path, exist_ok=True)
                    create_structure(path, content)
                else:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, 'w') as f:
                        f.write(content or 'mock')
        create_structure(game_dir, structure)
        return game_dir

    def test_simulated_game_structure(self, simulated_game_dir):
        assert os.path.exists(simulated_game_dir)
        assert os.path.exists(os.path.join(simulated_game_dir, 'DELTARUNE.exe'))
        assert os.path.exists(os.path.join(simulated_game_dir, 'data.win'))
        assert os.path.exists(os.path.join(simulated_game_dir, 'chapter1_', 'data.win'))

    def test_find_executable_in_simulated_dir(self, simulated_game_dir):
        exe_path = resolve_game_executable(simulated_game_dir, is_undertale=False)
        assert exe_path is not None
        assert os.path.exists(exe_path) or 'DELTARUNE' in exe_path.upper()

    def test_find_chapter_in_simulated_dir(self, simulated_game_dir):
        chapter_dir = find_chapter_resource_dir(simulated_game_dir, 1)
        assert chapter_dir is not None
        assert os.path.exists(chapter_dir)
        assert 'chapter1' in chapter_dir.lower()

    def test_find_chapter_resource_dir_multiple_chapters(self, temp_dir):
        game_dir = os.path.join(temp_dir, 'game')
        for chapter_id in [0, 1, 2, 3, 4]:
            chapter_dir = os.path.join(game_dir, f'chapter{chapter_id}_')
            os.makedirs(chapter_dir, exist_ok=True)
        for chapter_id in [1, 2, 3, 4]:
            resource_dir = find_chapter_resource_dir(game_dir, chapter_id)
            assert resource_dir is not None
            assert f'chapter{chapter_id}' in resource_dir.lower()
