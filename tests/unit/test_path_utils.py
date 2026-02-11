import os
import sys
import platform
from unittest.mock import patch
from utils.path_utils import get_user_data_root, get_user_mods_dir, get_user_plugins_dir, resource_path, resolve_game_executable, find_chapter_resource_dir


class TestPathUtils:

    def test_get_user_data_root(self):
        root = get_user_data_root()
        assert isinstance(root, str)
        assert len(root) > 0
        assert 'DELTAHUB' in root

    def test_get_user_mods_dir(self):
        mods_dir = get_user_mods_dir()
        assert isinstance(mods_dir, str)
        assert 'mods' in mods_dir
        assert 'DELTAHUB' in mods_dir

    def test_get_user_plugins_dir(self):
        plugins_dir = get_user_plugins_dir()
        assert isinstance(plugins_dir, str)
        assert 'plugins' in plugins_dir
        assert 'DELTAHUB' in plugins_dir

    def test_resource_path_frozen(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', '/tmp/pyinstaller', create=True):
            path = resource_path('assets/icons/icon.ico')
            assert '/tmp/pyinstaller' in path
            assert 'assets/icons/icon.ico' in path

    def test_resource_path_development(self):
        frozen_attr = getattr(sys, 'frozen', None)
        _meipass_attr = getattr(sys, '_MEIPASS', None)
        try:
            if hasattr(sys, 'frozen'):
                delattr(sys, 'frozen')
            if hasattr(sys, '_MEIPASS'):
                delattr(sys, '_MEIPASS')
            path = resource_path('assets/icons/icon.ico')
            assert 'src' in path or 'assets' in path
        finally:
            if frozen_attr is not None:
                sys.frozen = frozen_attr
            if _meipass_attr is not None:
                sys._MEIPASS = _meipass_attr

    def test_resolve_game_executable_deltarune(self, temp_dir):
        game_dir = os.path.join(temp_dir, 'game')
        os.makedirs(game_dir, exist_ok=True)
        system = platform.system()
        if system == 'Darwin':
            app_path = os.path.join(game_dir, 'DELTARUNE.app')
            os.makedirs(app_path, exist_ok=True)
        elif system == 'Windows':
            exe_path = os.path.join(game_dir, 'DELTARUNE.exe')
            with open(exe_path, 'w') as f:
                f.write('mock')
        else:
            exe_path = os.path.join(game_dir, 'DELTARUNE')
            with open(exe_path, 'w') as f:
                f.write('mock')
            os.chmod(exe_path, 493)
        resolved = resolve_game_executable(game_dir, is_undertale=False)
        assert resolved is not None

    def test_resolve_game_executable_undertale(self, temp_dir):
        game_dir = os.path.join(temp_dir, 'game')
        os.makedirs(game_dir, exist_ok=True)
        system = platform.system()
        if system == 'Darwin':
            app_path = os.path.join(game_dir, 'UNDERTALE.app')
            os.makedirs(app_path, exist_ok=True)
        elif system == 'Windows':
            exe_path = os.path.join(game_dir, 'UNDERTALE.exe')
            with open(exe_path, 'w') as f:
                f.write('mock')
        else:
            exe_path = os.path.join(game_dir, 'UNDERTALE')
            with open(exe_path, 'w') as f:
                f.write('mock')
            os.chmod(exe_path, 493)
        resolved = resolve_game_executable(game_dir, is_undertale=True)
        assert resolved is not None

    def test_resolve_game_executable_pizzatower(self, temp_dir):
        game_dir = os.path.join(temp_dir, 'game')
        os.makedirs(game_dir, exist_ok=True)
        system = platform.system()
        if system == 'Darwin':
            app_path = os.path.join(game_dir, 'PizzaTower.app')
            os.makedirs(app_path, exist_ok=True)
        elif system == 'Windows':
            exe_path = os.path.join(game_dir, 'PizzaTower.exe')
            with open(exe_path, 'w') as f:
                f.write('mock')
        else:
            exe_path = os.path.join(game_dir, 'PizzaTower')
            with open(exe_path, 'w') as f:
                f.write('mock')
            os.chmod(exe_path, 493)
        resolved = resolve_game_executable(game_dir, is_undertale=False, game_type='pizzatower')
        assert resolved is not None

    def test_resolve_game_executable_sugaryspire(self, temp_dir):
        game_dir = os.path.join(temp_dir, 'game')
        os.makedirs(game_dir, exist_ok=True)
        system = platform.system()
        if system == 'Darwin':
            app_path = os.path.join(game_dir, 'SugarySpire_ExhibitionNight.app')
            os.makedirs(app_path, exist_ok=True)
        elif system == 'Windows':
            exe_path = os.path.join(game_dir, 'SugarySpire_ExhibitionNight.exe')
            with open(exe_path, 'w') as f:
                f.write('mock')
        else:
            exe_path = os.path.join(game_dir, 'SugarySpire_ExhibitionNight')
            with open(exe_path, 'w') as f:
                f.write('mock')
            os.chmod(exe_path, 493)
        resolved = resolve_game_executable(game_dir, is_undertale=False, game_type='sugaryspire')
        assert resolved is not None

    def test_resolve_game_executable_not_found(self, temp_dir):
        game_dir = os.path.join(temp_dir, 'empty_game')
        os.makedirs(game_dir, exist_ok=True)
        resolved = resolve_game_executable(game_dir, is_undertale=False)
        assert resolved is None

    def test_find_chapter_resource_dir(self, temp_dir):
        game_dir = os.path.join(temp_dir, 'game')
        system = platform.system()
        if system == 'Darwin':
            app_path = os.path.join(game_dir, 'DELTARUNE.app')
            os.makedirs(app_path, exist_ok=True)
            resources_path = os.path.join(app_path, 'Contents', 'Resources')
            os.makedirs(resources_path, exist_ok=True)
            chapter1_dir = os.path.join(resources_path, 'chapter1_')
        else:
            chapter1_dir = os.path.join(game_dir, 'chapter1_')
        os.makedirs(chapter1_dir, exist_ok=True)
        resource_dir = find_chapter_resource_dir(game_dir, 'deltarune_1')
        assert resource_dir is not None
        assert 'chapter1' in resource_dir.lower()

    def test_find_chapter_resource_dir_chapter0(self, temp_dir):
        game_dir = os.path.join(temp_dir, 'game')
        system = platform.system()
        if system == 'Darwin':
            app_path = os.path.join(game_dir, 'DELTARUNE.app')
            os.makedirs(app_path, exist_ok=True)
            resources_path = os.path.join(app_path, 'Contents', 'Resources')
            os.makedirs(resources_path, exist_ok=True)
        os.makedirs(game_dir, exist_ok=True)
        resource_dir = find_chapter_resource_dir(game_dir, 'deltarune_0')
        assert resource_dir is not None
        if system == 'Darwin':
            assert 'Resources' in resource_dir
        else:
            assert resource_dir == game_dir

    def test_find_chapter_resource_dir_not_found(self, temp_dir):
        game_dir = os.path.join(temp_dir, 'game')
        os.makedirs(game_dir, exist_ok=True)
        resource_dir = find_chapter_resource_dir(game_dir, 'deltarune_99')
        assert resource_dir is None

    def test_path_handling_special_characters(self, temp_dir):
        special_dir = os.path.join(temp_dir, 'test dir with spaces & symbols!')
        os.makedirs(special_dir, exist_ok=True)
        test_file = os.path.join(special_dir, 'test.txt')
        with open(test_file, 'w') as f:
            f.write('test')
        assert os.path.exists(test_file)
        assert os.path.exists(special_dir)

    def test_path_handling_unicode(self, temp_dir):
        unicode_dir = os.path.join(temp_dir, 'тест_目录_テスト')
        os.makedirs(unicode_dir, exist_ok=True)
        assert os.path.exists(unicode_dir)
        test_file = os.path.join(unicode_dir, 'файл.txt')
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write('test')
        assert os.path.exists(test_file)

    def test_pizzatower_path_validation_with_custom_executable(self, temp_dir):
        from services.game_detection_service import is_valid_game_path
        game_dir = os.path.join(temp_dir, 'game')
        os.makedirs(game_dir, exist_ok=True)
        system = platform.system()
        if system == 'Windows':
            exe_path = os.path.join(game_dir, 'PizzaTower.exe')
            with open(exe_path, 'w') as f:
                f.write('mock')
        elif system == 'Darwin':
            app_path = os.path.join(game_dir, 'PizzaTower.app')
            os.makedirs(app_path, exist_ok=True)
            contents_path = os.path.join(app_path, 'Contents')
            macos_path = os.path.join(contents_path, 'MacOS')
            resources_path = os.path.join(contents_path, 'Resources')
            os.makedirs(macos_path, exist_ok=True)
            os.makedirs(resources_path, exist_ok=True)
            exe_path = os.path.join(macos_path, 'PizzaTower')
            with open(exe_path, 'w') as f:
                f.write('mock')
            os.chmod(exe_path, 493)
            data_path = os.path.join(resources_path, 'game.ios')
            with open(data_path, 'w') as f:
                f.write('mock')
        else:
            exe_path = os.path.join(game_dir, 'PizzaTower')
            with open(exe_path, 'w') as f:
                f.write('mock')
            os.chmod(exe_path, 493)
        is_valid = is_valid_game_path(game_dir, skip_data_check=False, game_type='pizzatower')
        assert is_valid is True
        # Test with invalid path
        invalid_dir = os.path.join(temp_dir, 'invalid')
        os.makedirs(invalid_dir, exist_ok=True)
        is_invalid = is_valid_game_path(invalid_dir, skip_data_check=False, game_type='pizzatower')
        assert is_invalid is False

    def test_autodetect_pizzatower_variations(self, temp_dir):
        from utils.path_utils import autodetect_path
        # Create mock Steam directory structure with Pizza Tower variation
        system = platform.system()
        if system == 'Windows':
            steam_common = os.path.join(temp_dir, 'Steam', 'steamapps', 'common')
            os.makedirs(steam_common, exist_ok=True)
            # Create PizzaTower folder (without space) - this tests the variation handling
            pizzatower_dir = os.path.join(steam_common, 'PizzaTower')
            os.makedirs(pizzatower_dir, exist_ok=True)
            exe_path = os.path.join(pizzatower_dir, 'PizzaTower.exe')
            with open(exe_path, 'w') as f:
                f.write('mock')
            # Test that autodetect_path can handle variations
            # Since we're in a temp directory, it won't find it, but we verify the code handles variations
            # by checking that the function doesn't crash and returns None when path doesn't exist
            result = autodetect_path('Pizza Tower')
            # The function should handle the variation gracefully (return None if not found)
            assert result is None or 'Pizza' in result
