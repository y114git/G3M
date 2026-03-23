import os
import platform
import sys
from unittest.mock import patch

from utils.path_utils import (
    _replace_svg_color_tokens,
    find_chapter_resource_dir,
    find_supported_game_data_file,
    get_user_data_root,
    get_user_mods_dir,
    get_user_plugins_dir,
    resolve_game_executable,
    resource_path,
)


class TestPathUtils:
    def test_get_user_data_root(self):
        root = get_user_data_root()
        assert isinstance(root, str)
        assert len(root) > 0
        assert "DELTAHUB" in root

    def test_get_user_mods_dir(self):
        mods_dir = get_user_mods_dir()
        assert isinstance(mods_dir, str)
        assert "mods" in mods_dir
        assert "DELTAHUB" in mods_dir

    def test_get_user_plugins_dir(self):
        plugins_dir = get_user_plugins_dir()
        assert isinstance(plugins_dir, str)
        assert "plugins" in plugins_dir
        assert "DELTAHUB" in plugins_dir

    def test_resource_path_frozen(self):
        bundle_root = os.path.join("bundle-root", "pyinstaller")
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", bundle_root, create=True),
        ):
            path = resource_path("assets/icons/icon.ico")
            assert bundle_root in path
            assert "assets/icons/icon.ico" in path

    def test_resource_path_development(self):
        frozen_attr = getattr(sys, "frozen", None)
        _meipass_attr = getattr(sys, "_MEIPASS", None)
        try:
            if hasattr(sys, "frozen"):
                delattr(sys, "frozen")
            if hasattr(sys, "_MEIPASS"):
                delattr(sys, "_MEIPASS")
            path = resource_path("assets/icons/icon.ico")
            assert "src" in path or "assets" in path
        finally:
            if frozen_attr is not None:
                sys.frozen = frozen_attr
            if _meipass_attr is not None:
                sys._MEIPASS = _meipass_attr

    def test_replace_svg_color_tokens_matches_root_fill_without_required_space(self):
        svg = '<svg fill="#000000"viewBox="0 0 16 16"></svg>'
        result = _replace_svg_color_tokens(svg, "#abcdef", [])
        assert 'fill="#abcdef"' in result

    def test_resolve_game_executable_deltarune(self, temp_dir):
        game_dir = os.path.join(temp_dir, "game")
        os.makedirs(game_dir, exist_ok=True)
        system = platform.system()
        if system == "Darwin":
            app_path = os.path.join(game_dir, "DELTARUNE.app")
            os.makedirs(app_path, exist_ok=True)
        elif system == "Windows":
            exe_path = os.path.join(game_dir, "DELTARUNE.exe")
            with open(exe_path, "w") as f:
                f.write("mock")
        else:
            exe_path = os.path.join(game_dir, "DELTARUNE")
            with open(exe_path, "w") as f:
                f.write("mock")
            os.chmod(exe_path, 0o700)
        resolved = resolve_game_executable(game_dir, "deltarune")
        assert resolved is not None

    def test_resolve_game_executable_undertale(self, temp_dir):
        game_dir = os.path.join(temp_dir, "game")
        os.makedirs(game_dir, exist_ok=True)
        system = platform.system()
        if system == "Darwin":
            app_path = os.path.join(game_dir, "UNDERTALE.app")
            os.makedirs(app_path, exist_ok=True)
        elif system == "Windows":
            exe_path = os.path.join(game_dir, "UNDERTALE.exe")
            with open(exe_path, "w") as f:
                f.write("mock")
        else:
            exe_path = os.path.join(game_dir, "UNDERTALE")
            with open(exe_path, "w") as f:
                f.write("mock")
            os.chmod(exe_path, 0o700)
        resolved = resolve_game_executable(game_dir, "undertale")
        assert resolved is not None

    def test_resolve_game_executable_pizzatower(self, temp_dir):
        game_dir = os.path.join(temp_dir, "game")
        os.makedirs(game_dir, exist_ok=True)
        system = platform.system()
        if system == "Darwin":
            app_path = os.path.join(game_dir, "PizzaTower.app")
            os.makedirs(app_path, exist_ok=True)
        elif system == "Windows":
            exe_path = os.path.join(game_dir, "PizzaTower.exe")
            with open(exe_path, "w") as f:
                f.write("mock")
        else:
            exe_path = os.path.join(game_dir, "PizzaTower")
            with open(exe_path, "w") as f:
                f.write("mock")
            os.chmod(exe_path, 0o700)
        resolved = resolve_game_executable(game_dir, "pizzatower")
        assert resolved is not None

    def test_resolve_game_executable_sugaryspire(self, temp_dir):
        game_dir = os.path.join(temp_dir, "game")
        os.makedirs(game_dir, exist_ok=True)
        system = platform.system()
        if system == "Darwin":
            app_path = os.path.join(game_dir, "SugarySpire_ExhibitionNight.app")
            os.makedirs(app_path, exist_ok=True)
        elif system == "Windows":
            exe_path = os.path.join(game_dir, "SugarySpire_ExhibitionNight.exe")
            with open(exe_path, "w") as f:
                f.write("mock")
        else:
            exe_path = os.path.join(game_dir, "SugarySpire_ExhibitionNight")
            with open(exe_path, "w") as f:
                f.write("mock")
            os.chmod(exe_path, 0o700)
        resolved = resolve_game_executable(game_dir, "sugaryspire")
        assert resolved is not None

    def test_resolve_game_executable_not_found(self, temp_dir):
        game_dir = os.path.join(temp_dir, "empty_game")
        os.makedirs(game_dir, exist_ok=True)
        resolved = resolve_game_executable(game_dir)
        assert resolved is None

    def test_find_chapter_resource_dir(self, temp_dir):
        game_dir = os.path.join(temp_dir, "game")
        system = platform.system()
        if system == "Darwin":
            app_path = os.path.join(game_dir, "DELTARUNE.app")
            os.makedirs(app_path, exist_ok=True)
            resources_path = os.path.join(app_path, "Contents", "Resources")
            os.makedirs(resources_path, exist_ok=True)
            chapter1_dir = os.path.join(resources_path, "chapter1_")
        else:
            chapter1_dir = os.path.join(game_dir, "chapter1_")
        os.makedirs(chapter1_dir, exist_ok=True)
        resource_dir = find_chapter_resource_dir(game_dir, "deltarune_1")
        assert resource_dir is not None
        assert "chapter1" in resource_dir.lower()

    def test_find_chapter_resource_dir_chapter0(self, temp_dir):
        game_dir = os.path.join(temp_dir, "game")
        system = platform.system()
        if system == "Darwin":
            app_path = os.path.join(game_dir, "DELTARUNE.app")
            os.makedirs(app_path, exist_ok=True)
            resources_path = os.path.join(app_path, "Contents", "Resources")
            os.makedirs(resources_path, exist_ok=True)
        os.makedirs(game_dir, exist_ok=True)
        resource_dir = find_chapter_resource_dir(game_dir, "deltarune_0")
        assert resource_dir is not None
        if system == "Darwin":
            assert "Resources" in resource_dir
        else:
            assert resource_dir == game_dir

    def test_find_chapter_resource_dir_not_found(self, temp_dir):
        game_dir = os.path.join(temp_dir, "game")
        os.makedirs(game_dir, exist_ok=True)
        resource_dir = find_chapter_resource_dir(game_dir, "deltarune_99")
        assert resource_dir is None

    def test_find_supported_game_data_file_prefers_exact_name(self, temp_dir):
        game_dir = os.path.join(temp_dir, "game")
        os.makedirs(game_dir, exist_ok=True)
        fallback = os.path.join(game_dir, "custom.win")
        preferred = os.path.join(game_dir, "game.unx")
        with open(fallback, "w") as f:
            f.write("fallback")
        with open(preferred, "w") as f:
            f.write("preferred")
        resolved = find_supported_game_data_file(game_dir, "game.unx")
        assert resolved == preferred

    def test_find_supported_game_data_file_falls_back_to_supported_extension(
        self, temp_dir
    ):
        game_dir = os.path.join(temp_dir, "game")
        os.makedirs(game_dir, exist_ok=True)
        fallback = os.path.join(game_dir, "modded.data")
        with open(fallback, "w") as f:
            f.write("fallback")
        resolved = find_supported_game_data_file(game_dir)
        assert resolved == fallback

    def test_path_handling_special_characters(self, temp_dir):
        special_dir = os.path.join(temp_dir, "test dir with spaces & symbols!")
        os.makedirs(special_dir, exist_ok=True)
        test_file = os.path.join(special_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("test")
        assert os.path.exists(test_file)
        assert os.path.exists(special_dir)

    def test_path_handling_unicode(self, temp_dir):
        unicode_dir = os.path.join(temp_dir, "тест_目录_テスト")
        os.makedirs(unicode_dir, exist_ok=True)
        assert os.path.exists(unicode_dir)
        test_file = os.path.join(unicode_dir, "файл.txt")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("test")
        assert os.path.exists(test_file)

    def test_pizzatower_path_validation_with_custom_executable(self, temp_dir):
        from services.game_detection_service import is_valid_game_path

        game_dir = os.path.join(temp_dir, "game")
        os.makedirs(game_dir, exist_ok=True)
        system = platform.system()
        if system == "Windows":
            exe_path = os.path.join(game_dir, "PizzaTower.exe")
            with open(exe_path, "w") as f:
                f.write("mock")
        elif system == "Darwin":
            app_path = os.path.join(game_dir, "PizzaTower.app")
            os.makedirs(app_path, exist_ok=True)
            contents_path = os.path.join(app_path, "Contents")
            macos_path = os.path.join(contents_path, "MacOS")
            resources_path = os.path.join(contents_path, "Resources")
            os.makedirs(macos_path, exist_ok=True)
            os.makedirs(resources_path, exist_ok=True)
            exe_path = os.path.join(macos_path, "PizzaTower")
            with open(exe_path, "w") as f:
                f.write("mock")
            os.chmod(exe_path, 0o700)
            data_path = os.path.join(resources_path, "game.ios")
            with open(data_path, "w") as f:
                f.write("mock")
        else:
            exe_path = os.path.join(game_dir, "PizzaTower")
            with open(exe_path, "w") as f:
                f.write("mock")
            os.chmod(exe_path, 0o700)
        is_valid = is_valid_game_path(
            game_dir, skip_data_check=False, game_type="pizzatower"
        )
        assert is_valid is True
        invalid_dir = os.path.join(temp_dir, "invalid")
        os.makedirs(invalid_dir, exist_ok=True)
        is_invalid = is_valid_game_path(
            invalid_dir, skip_data_check=False, game_type="pizzatower"
        )
        assert is_invalid is False

    def test_autodetect_pizzatower_variations(self, temp_dir):
        from utils.path_utils import autodetect_path

        system = platform.system()
        if system == "Windows":
            steam_common = os.path.join(temp_dir, "Steam", "steamapps", "common")
            os.makedirs(steam_common, exist_ok=True)
            pizzatower_dir = os.path.join(steam_common, "PizzaTower")
            os.makedirs(pizzatower_dir, exist_ok=True)
            exe_path = os.path.join(pizzatower_dir, "PizzaTower.exe")
            with open(exe_path, "w") as f:
                f.write("mock")
            result = autodetect_path("Pizza Tower")
            assert result is None or "Pizza" in result
