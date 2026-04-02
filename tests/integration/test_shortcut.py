"""Tests for shortcut creation, validation, config building, file writing, and runner parsing."""

import base64
import json
import os
import platform
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from controllers.shortcut_controller import (
    _build_shortcut_config,
    _collect_chapter_data,
    _generate_shortcut_filename,
    _get_platform_extension,
    _validate_shortcut_prerequisites,
    _write_shortcut_file,
)
from services.game_runner import (
    _find_mod_source_dir,
    _parse_shortcut_arg,
    _resolve_chapter_source_dir,
)


@pytest.fixture
def game_mode():
    from models.game_modes import get_game

    return get_game("deltarune")


@pytest.fixture
def mock_app_state(game_mode, temp_dir):
    state = MagicMock()
    state.game_mode = game_mode
    state.current_mode = "chapter"
    state.selected_chapter_id = "deltarune_2"
    state.initialization_completed = True
    game_path = os.path.join(temp_dir, "game")
    os.makedirs(game_path, exist_ok=True)
    state.local_config = {
        game_mode.path_config_key: game_path,
        "launch_via_steam": False,
        "use_portproton": False,
        "direct_launch_chapter": "",
    }
    return state


@pytest.fixture
def mock_mod_data():
    mod = MagicMock()
    mod.id = "test_mod_001"
    mod.name = "Test Mod"
    mod.game = "deltarune"
    return mod


@pytest.fixture
def mock_used_mods_service(mock_mod_data):
    svc = MagicMock()
    svc.get_used_mods_list.return_value = [mock_mod_data]
    return svc


@pytest.fixture
def mock_used_mods_service_empty():
    svc = MagicMock()
    svc.get_used_mods_list.return_value = []
    return svc


@pytest.fixture
def shortcut_temp_dir():
    d = tempfile.mkdtemp(prefix="shortcut_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def mod_on_disk(shortcut_temp_dir):
    mod_dir = os.path.join(shortcut_temp_dir, "profiles", "Default", "test_mod_001")
    os.makedirs(mod_dir, exist_ok=True)
    config = {"id": "test_mod_001", "name": "Test Mod", "game": "deltarune"}
    with open(os.path.join(mod_dir, "mod_config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    chapter_dir = os.path.join(mod_dir, "chapter_2")
    os.makedirs(chapter_dir, exist_ok=True)
    return mod_dir


class TestParseShortcutArg:
    """Tests for shortcut."""
    def test_parse_base64(self):
        """Checks that parsing base64."""
        cfg = {"game_id": "deltarune", "chapter_mods": {"deltarune_2": "gb_mod_123"}}
        b64 = base64.b64encode(json.dumps(cfg).encode()).decode()
        result = _parse_shortcut_arg(b64)
        assert result == cfg

    def test_parse_inline_json(self):
        """Checks that parsing inline json."""
        cfg = {"game_id": "undertale", "chapter_mode": False}
        result = _parse_shortcut_arg(json.dumps(cfg))
        assert result == cfg

    def test_parse_file_path(self, shortcut_temp_dir):
        """Checks that parsing file path."""
        cfg = {"game_id": "deltarune", "chapter_mods": {"deltarune_2": "test"}}
        path = os.path.join(shortcut_temp_dir, "cfg.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        result = _parse_shortcut_arg(path)
        assert result == cfg

    def test_parse_invalid_raises(self):
        """Checks that parsing invalid raises."""
        with pytest.raises((ValueError, TypeError, json.JSONDecodeError)):
            _parse_shortcut_arg("not_valid_anything_!!!")

    def test_base64_roundtrip_unicode(self):
        """Checks that base64ing roundtrip unicode."""
        cfg = {"game_id": "deltarune", "chapter_mods": {"deltarune_2": "мод_тест"}}
        b64 = base64.b64encode(
            json.dumps(cfg, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")
        result = _parse_shortcut_arg(b64)
        assert result == cfg


class TestFindModSourceDir:
    """Tests for shortcut."""
    PATCH_TARGET = "services.game_runner.get_profile_mods_root"

    def test_find_existing_mod(self, mod_on_disk, shortcut_temp_dir):
        """Checks that finding existing mod."""
        profile_dir = os.path.join(shortcut_temp_dir, "profiles", "Default")
        with patch(self.PATCH_TARGET, return_value=profile_dir):
            result = _find_mod_source_dir("test_mod_001", {})
            assert result is not None
            assert os.path.isdir(result)

    def test_find_nonexistent_mod(self, shortcut_temp_dir):
        """Checks that finding nonexistent mod."""
        profile_dir = os.path.join(shortcut_temp_dir, "profiles", "Default")
        os.makedirs(profile_dir, exist_ok=True)
        with patch(self.PATCH_TARGET, return_value=profile_dir):
            result = _find_mod_source_dir("nonexistent_mod", {})
            assert result is None

    def test_find_mod_no_mods_dir(self, shortcut_temp_dir):
        """Checks that finding mod no mods dir."""
        fake_dir = os.path.join(shortcut_temp_dir, "does_not_exist")
        with patch(self.PATCH_TARGET, return_value=fake_dir):
            result = _find_mod_source_dir("test_mod_001", {})
            assert result is None

    def test_find_mod_folder_name_fallback(self, shortcut_temp_dir):
        """Checks that finding mod folder name fallback."""
        profile_dir = os.path.join(shortcut_temp_dir, "profiles", "Default")
        folder = os.path.join(profile_dir, "my_cool_mod")
        os.makedirs(folder, exist_ok=True)
        with patch(self.PATCH_TARGET, return_value=profile_dir):
            result = _find_mod_source_dir("my_cool_mod", {})
            assert result == folder


class TestResolveChapterSourceDir:
    """Tests for shortcut."""
    def test_chapter_subfolder(self, mod_on_disk):
        """Checks that chaptering subfolder."""
        result = _resolve_chapter_source_dir(mod_on_disk, "deltarune_2")
        assert result is not None
        assert result.endswith("chapter_2")

    def test_universal_fallback(self, shortcut_temp_dir):
        """Checks that universaling fallback."""
        mod_dir = os.path.join(shortcut_temp_dir, "mod_universal")
        os.makedirs(os.path.join(mod_dir, "universal"), exist_ok=True)
        result = _resolve_chapter_source_dir(mod_dir, "deltarune_2")
        assert result.endswith("universal")

    def test_root_fallback(self, shortcut_temp_dir):
        """Checks that rooting fallback."""
        mod_dir = os.path.join(shortcut_temp_dir, "mod_root")
        os.makedirs(mod_dir, exist_ok=True)
        result = _resolve_chapter_source_dir(mod_dir, "deltarune_2")
        assert result == mod_dir

    def test_none_for_missing_dir(self):
        """Checks that noneing for missing dir."""
        result = _resolve_chapter_source_dir("/nonexistent/path", "deltarune_2")
        assert result is None

    def test_none_for_empty_input(self):
        """Checks that noneing for empty input."""
        result = _resolve_chapter_source_dir("", "deltarune_2")
        assert result is None


class TestCollectChapterData:
    """Tests for shortcut."""
    def test_chapter_mode_all_vanilla(
        self, mock_used_mods_service_empty, mock_app_state
    ):
        """Checks that chaptering mode all vanilla."""
        result = _collect_chapter_data(mock_used_mods_service_empty, mock_app_state)
        assert result is not None
        chapter_mods, chapter_objs = result
        assert all(v is None for v in chapter_mods.values())
        assert all(v is None for v in chapter_objs.values())
        assert len(chapter_mods) > 1

    def test_chapter_mode_single_mod_per_chapter(
        self, mock_used_mods_service, mock_app_state
    ):
        """Checks that chaptering mode single mod per chapter."""
        result = _collect_chapter_data(mock_used_mods_service, mock_app_state)
        assert result is not None
        chapter_mods, _chapter_objs = result
        for v in chapter_mods.values():
            assert v == "test_mod_001"

    def test_chapter_mode_too_many_mods(self, mock_app_state):
        """Checks that chaptering mode too many mods."""
        svc = MagicMock()
        svc.get_used_mods_list.return_value = [MagicMock(), MagicMock()]
        result = _collect_chapter_data(svc, mock_app_state)
        assert result is None

    def test_non_chapter_mode_vanilla(
        self, mock_used_mods_service_empty, mock_app_state
    ):
        """Checks that noning chapter mode vanilla."""
        mock_app_state.current_mode = "full"
        result = _collect_chapter_data(mock_used_mods_service_empty, mock_app_state)
        assert result is not None
        chapter_mods, _chapter_objs = result
        assert all(v is None for v in chapter_mods.values())
        assert len(chapter_mods) == len(mock_app_state.game_mode.tabs)

    def test_non_chapter_mode_expands_to_chapters_with_data(self, mock_app_state):
        """Checks that noning chapter mode expands to chapters with data."""
        mock_app_state.current_mode = "full"
        mod = MagicMock()
        mod.id = "test_mod_001"
        mod.name = "Test Mod"
        mod.get_chapter_data = lambda tab_id: tab_id in ("deltarune_1", "deltarune_2")
        svc = MagicMock()
        svc.get_used_mods_list.return_value = [mod]
        result = _collect_chapter_data(svc, mock_app_state)
        assert result is not None
        chapter_mods, _ = result
        assert chapter_mods.get("deltarune_1") == "test_mod_001"
        assert chapter_mods.get("deltarune_2") == "test_mod_001"
        assert chapter_mods.get("deltarune_0") is None
        assert chapter_mods.get("deltarune_3") is None


class TestBuildShortcutConfig:
    """Tests for shortcut."""
    def test_basic_config(self, mock_app_state):
        """Checks that basicing config."""
        chapter_mods = {"deltarune_0": None, "deltarune_2": "test_mod"}
        cfg = _build_shortcut_config(mock_app_state, chapter_mods)
        assert cfg["game_id"] == "deltarune"
        assert cfg["chapter_mode"] is True
        assert cfg["chapter_mods"] == chapter_mods
        assert "launch_via_steam" in cfg

    def test_steam_launch(self, mock_app_state):
        """Checks that steaming launch."""
        mock_app_state.local_config["launch_via_steam"] = True
        cfg = _build_shortcut_config(mock_app_state, {})
        assert cfg["launch_via_steam"] is True

    def test_non_chapter_mode(self, mock_app_state):
        """Checks that noning chapter mode."""
        mock_app_state.current_mode = "full"
        cfg = _build_shortcut_config(mock_app_state, {"deltarune": None})
        assert cfg["chapter_mode"] is False


class TestValidatePrerequisites:
    """Tests for shortcut."""
    def test_valid_vanilla(self, mock_app_state):
        """Checks that validing vanilla."""
        error = _validate_shortcut_prerequisites(mock_app_state, False)
        assert error is None

    def test_missing_game_path(self, mock_app_state):
        """Checks that missinging game path."""
        mock_app_state.local_config[mock_app_state.game_mode.path_config_key] = ""
        error = _validate_shortcut_prerequisites(mock_app_state, False)
        assert error is not None
        assert "Game path" in error and "not set" in error

    def test_nonexistent_game_path(self, mock_app_state):
        """Checks that nonexistenting game path."""
        mock_app_state.local_config[mock_app_state.game_mode.path_config_key] = (
            "/nonexistent/path"
        )
        error = _validate_shortcut_prerequisites(mock_app_state, False)
        assert error is not None

    def test_mod_with_g3mtool_available(self, mock_app_state):
        """Checks that moding  with g3mtool available."""
        with patch("adapters.g3mtool_adapter.G3MToolManager") as mock_g3m:
            mock_g3m.return_value.is_available.return_value = True
            error = _validate_shortcut_prerequisites(mock_app_state, True)
            assert error is None

    def test_mod_with_g3mtool_unavailable(self, mock_app_state):
        """Checks that moding  with g3mtool unavailable."""
        with patch("adapters.g3mtool_adapter.G3MToolManager") as mock_g3m:
            mock_g3m.return_value.is_available.return_value = False
            error = _validate_shortcut_prerequisites(mock_app_state, True)
            assert error is not None
            assert "g3mtool" in error.lower()

    def test_no_mod_skips_g3mtool_check(self, mock_app_state):
        """Checks that noing mod skips g3mtool check."""
        error = _validate_shortcut_prerequisites(mock_app_state, False)
        assert error is None


class TestGenerateShortcutFilename:
    """Tests for shortcut."""
    def test_with_mod(self, game_mode, mock_mod_data):
        """Checks that withing  with mod."""
        name = _generate_shortcut_filename(game_mode, {"deltarune_2": mock_mod_data})
        assert "G3M" in name
        assert "Test_Mod" in name

    def test_vanilla(self, game_mode):
        """Checks that vanillaing works."""
        name = _generate_shortcut_filename(game_mode, {"deltarune_2": None})
        assert "G3M" in name
        assert "Vanilla" in name

    def test_safe_characters(self, game_mode, mock_mod_data):
        """Checks that safeing characters."""
        mock_mod_data.name = "Mod With Spaces & Symbols!"
        name = _generate_shortcut_filename(game_mode, {"deltarune_2": mock_mod_data})
        assert all(c.isalnum() or c in ("_", "-") for c in name)


class TestGetPlatformExtension:
    """Tests for shortcut."""
    def test_returns_valid_extension(self):
        """Checks that returnsing valid extension."""
        ext = _get_platform_extension()
        assert ext.startswith(".")
        assert ext in (".vbs", ".sh", ".command")


class TestWriteShortcutFile:
    """Tests for shortcut."""
    def test_write_creates_file(self, shortcut_temp_dir):
        """Checks that writing creates file."""
        cfg = {
            "game_id": "deltarune",
            "chapter_mods": {"deltarune_2": "test"},
            "chapter_mode": True,
        }
        filepath = os.path.join(shortcut_temp_dir, f"test{_get_platform_extension()}")
        result = _write_shortcut_file(filepath, cfg)
        assert os.path.isfile(result)

    def test_write_embeds_base64_config(self, shortcut_temp_dir):
        """Checks that writing embeds base64 config."""
        cfg = {"game_id": "deltarune", "chapter_mods": {"deltarune_2": "test_mod"}}
        filepath = os.path.join(shortcut_temp_dir, f"test{_get_platform_extension()}")
        _write_shortcut_file(filepath, cfg)
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        expected_b64 = base64.b64encode(
            json.dumps(cfg, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")
        assert expected_b64 in content

    def test_write_contains_shortcut_flag(self, shortcut_temp_dir):
        """Checks that writing contains shortcut flag."""
        filepath = os.path.join(shortcut_temp_dir, f"test{_get_platform_extension()}")
        _write_shortcut_file(filepath, {"game_id": "deltarune"})
        with open(filepath, encoding="utf-8") as f:
            assert "--shortcut" in f.read()

    @pytest.mark.skipif(platform.system() != "Windows", reason="VBS specific")
    def test_windows_vbs_no_console(self, shortcut_temp_dir):
        """Checks that windowsing vbs no console."""
        filepath = os.path.join(shortcut_temp_dir, "test.vbs")
        _write_shortcut_file(filepath, {"game_id": "deltarune"})
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        assert "WScript.Shell" in content and ", 0, False" in content

    @pytest.mark.skipif(platform.system() == "Windows", reason="Unix specific")
    def test_unix_executable(self, shortcut_temp_dir):
        """Checks that unixing executable."""
        filepath = os.path.join(shortcut_temp_dir, f"test{_get_platform_extension()}")
        _write_shortcut_file(filepath, {"game_id": "deltarune"})
        assert os.access(filepath, os.X_OK)

    def test_config_roundtrip_via_base64(self, shortcut_temp_dir):
        """Checks that configing roundtrip via base64."""
        cfg = {
            "game_id": "deltarune",
            "chapter_mods": {"deltarune_0": None, "deltarune_2": "gb_mod_12345"},
            "chapter_mode": True,
            "launch_via_steam": True,
        }
        filepath = os.path.join(shortcut_temp_dir, f"test{_get_platform_extension()}")
        _write_shortcut_file(filepath, cfg)
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        b64 = base64.b64encode(
            json.dumps(cfg, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")
        assert b64 in content
        assert json.loads(base64.b64decode(b64).decode("utf-8")) == cfg
