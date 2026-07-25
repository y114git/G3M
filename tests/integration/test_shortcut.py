"""Tests for shortcut creation, validation, config building, file writing, and runner parsing."""

import base64
import json
import os
import platform
import shutil
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QDialog

from controllers.shortcut_controller import (
    ShortcutDialog,
    _build_shortcut_config,
    _collect_section_data,
    _collect_shortcut_plugin_blocks,
    _generate_shortcut_filename,
    _get_platform_extension,
    _validate_shortcut_prerequisites,
    _write_shortcut_file,
)
from models.execution_plan import PatchPlan
from services.game_runner import (
    _execute_patch_plan,
    _find_mod_source_dir,
    _launch_game,
    _parse_shortcut_arg,
    _wait_for_game_exit,
)
from services.plugins.shortcut_service import (
    ShortcutPluginContext,
    execute_shortcut_plugin_hook,
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


class TestShortcutLaunch:
    def test_wait_for_game_exit_does_not_stop_after_ten_minutes(self):
        tracker = MagicMock()
        tracker.refresh.side_effect = [True] * 301 + [False] * 4
        with (
            patch("services.game_runner.GameProcessTracker", return_value=tracker),
            patch("services.game_runner.time.sleep"),
        ):
            _wait_for_game_exit(None, ("DELTARUNE.exe",), set())

        assert tracker.refresh.call_count == 305

    def test_launch_game_sanitizes_linux_env_for_wine(self, game_mode, shortcut_temp_dir):
        game_path = os.path.join(shortcut_temp_dir, "game")
        os.makedirs(game_path, exist_ok=True)

        shortcut_config = {
            "launch_via_steam": False,
            "use_portproton": False,
            "direct_launch_chapter": "",
            "chapter_mode": False,
        }
        local_config = {"portproton_path": ""}
        fake_process = MagicMock()

        with (
            patch("services.game_runner.platform.system", return_value="Linux"),
            patch(
                "services.game_runner._get_executable_path",
                return_value=os.path.join(game_path, "DELTARUNE.exe"),
            ),
            patch("services.game_runner.subprocess.Popen", return_value=fake_process) as popen,
            patch("services.game_runner._wait_for_game_exit"),
            patch.dict(
                "services.game_runner.os.environ",
                {
                    "LD_LIBRARY_PATH": "/opt/g3m-bundle",
                    "LD_LIBRARY_PATH_ORIG": "/usr/lib:/usr/local/lib",
                    "PATH": os.environ.get("PATH", ""),
                },
                clear=False,
            ),
        ):
            process = _launch_game(shortcut_config, game_mode, local_config, game_path)

        assert process is fake_process
        assert popen.call_args.args[0] == ["wine", os.path.join(game_path, "DELTARUNE.exe")]
        assert popen.call_args.kwargs["cwd"] == game_path
        assert popen.call_args.kwargs["env"]["LD_LIBRARY_PATH"] == "/usr/lib:/usr/local/lib"

    def test_launch_game_uses_custom_wine_path(self, game_mode, shortcut_temp_dir):
        game_path = os.path.join(shortcut_temp_dir, "game")
        os.makedirs(game_path, exist_ok=True)

        shortcut_config = {
            "launch_via_steam": False,
            "use_portproton": False,
            "direct_launch_chapter": "",
            "chapter_mode": False,
        }
        local_config = {
            "custom_wine_path": "/opt/wine-staging/bin/wine",
            "custom_portproton_path": "",
        }
        fake_process = MagicMock()

        with (
            patch("services.game_runner.platform.system", return_value="Linux"),
            patch(
                "services.game_runner._get_executable_path",
                return_value=os.path.join(game_path, "DELTARUNE.exe"),
            ),
            patch("services.game_runner.subprocess.Popen", return_value=fake_process) as popen,
            patch("services.game_runner._wait_for_game_exit"),
        ):
            process = _launch_game(shortcut_config, game_mode, local_config, game_path)

        assert process is fake_process
        assert popen.call_args.args[0] == [
            "/opt/wine-staging/bin/wine",
            os.path.join(game_path, "DELTARUNE.exe"),
        ]

    def test_launch_game_uses_wine64_when_wine_missing(self, game_mode, shortcut_temp_dir):
        game_path = os.path.join(shortcut_temp_dir, "game")
        os.makedirs(game_path, exist_ok=True)

        shortcut_config = {
            "launch_via_steam": False,
            "use_portproton": False,
            "direct_launch_chapter": "",
            "chapter_mode": False,
        }
        local_config = {"custom_wine_path": "", "custom_portproton_path": ""}
        fake_process = MagicMock()

        with (
            patch("services.game_runner.platform.system", return_value="Linux"),
            patch(
                "services.game_runner._get_executable_path",
                return_value=os.path.join(game_path, "DELTARUNE.exe"),
            ),
            patch(
                "utils.process_utils.shutil.which",
                side_effect=lambda name: None if name == "wine" else "/usr/bin/wine64",
            ),
            patch("services.game_runner.subprocess.Popen", return_value=fake_process) as popen,
            patch("services.game_runner._wait_for_game_exit"),
        ):
            process = _launch_game(shortcut_config, game_mode, local_config, game_path)

        assert process is fake_process
        assert popen.call_args.args[0] == [
            "wine64",
            os.path.join(game_path, "DELTARUNE.exe"),
        ]

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


class TestCollectChapterData:
    """Tests for shortcut."""
    def test_chapter_mode_all_vanilla(
        self, mock_used_mods_service_empty, mock_app_state
    ):
        """Checks that chaptering mode all vanilla."""
        result = _collect_section_data(mock_used_mods_service_empty, mock_app_state)
        assert result is not None
        patch_plan, chapter_objs = result
        assert not patch_plan.sections
        assert all(not v for v in chapter_objs.values())
        assert len(chapter_objs) > 1

    def test_chapter_mode_single_mod_per_chapter(
        self, mock_used_mods_service, mock_app_state
    ):
        """Checks that chaptering mode single mod per chapter."""
        result = _collect_section_data(mock_used_mods_service, mock_app_state)
        assert result is not None
        patch_plan, _chapter_objs = result
        for _section, steps in patch_plan.sections:
            assert steps == (("test_mod_001",),)

    def test_chapter_mode_rejects_multiple_mods_in_one_step(self, mock_app_state):
        """A shortcut step cannot contain mods that need merging."""
        svc = MagicMock()
        svc.get_mod_steps.return_value = None
        svc.get_used_mods_list.return_value = [
            MagicMock(id="base"),
            MagicMock(id="addon"),
        ]
        assert _collect_section_data(svc, mock_app_state) is None

    def test_chapter_mode_allows_multiple_single_mod_steps(self, mock_app_state):
        """Sequential shortcut patching remains available for dependent mods."""
        svc = MagicMock()
        svc.get_mod_steps.return_value = [
            [MagicMock(id="base")],
            [MagicMock(id="addon")],
        ]

        result = _collect_section_data(svc, mock_app_state)

        assert result is not None
        patch_plan, _ = result
        assert all(
            steps == (("base",), ("addon",))
            for _section, steps in patch_plan.sections
        )

    def test_non_chapter_mode_vanilla(
        self, mock_used_mods_service_empty, mock_app_state
    ):
        """Checks that noning chapter mode vanilla."""
        mock_app_state.current_mode = "full"
        result = _collect_section_data(mock_used_mods_service_empty, mock_app_state)
        assert result is not None
        patch_plan, chapter_objs = result
        assert not patch_plan.sections
        assert len(chapter_objs) == len(mock_app_state.game_mode.tabs)

    def test_non_chapter_mode_expands_to_chapters_with_data(self, mock_app_state):
        """Checks that noning chapter mode expands to chapters with data."""
        mock_app_state.current_mode = "full"
        mod = MagicMock()
        mod.id = "test_mod_001"
        mod.name = "Test Mod"
        mod.get_chapter_data = lambda tab_id: tab_id in ("deltarune_1", "deltarune_2")
        svc = MagicMock()
        svc.get_used_mods_list.return_value = [mod]
        result = _collect_section_data(svc, mock_app_state)
        assert result is not None
        patch_plan, _ = result
        sections = dict(patch_plan.sections)
        assert sections["deltarune_1"] == (("test_mod_001",),)
        assert sections["deltarune_2"] == (("test_mod_001",),)
        assert "deltarune_0" not in sections
        assert "deltarune_3" not in sections


def test_shortcut_executes_serialized_plan_through_canonical_patcher(
    monkeypatch, game_mode, tmp_path
):
    calls = []

    class Patcher:
        def __init__(self, app_state, mod_service, parent) -> None:
            del parent
            self.app_state = app_state
            self.mod_service = mod_service

        def set_override_game_path(self, path):
            calls.append(("path", path))

        def process_patch_plan(self, plan, resolver, is_modpack=False):
            calls.append(("plan", plan, resolver("base"), is_modpack))
            return True

    monkeypatch.setattr(
        "services.g3mtool_patching_service.G3MToolPatchingService", Patcher
    )
    monkeypatch.setattr(
        "services.game_runner._load_installed_mod", lambda mod_id, _cfg: mod_id
    )
    monkeypatch.setattr(
        "services.game_runner.get_user_data_root", lambda: str(tmp_path)
    )
    plan = PatchPlan.from_dict(
        {"sections": {"deltarune_2": [["base"], ["addon"]]}}
    )

    patcher = _execute_patch_plan(plan, str(tmp_path), game_mode, {})

    assert patcher is not None
    assert calls == [
        ("path", str(tmp_path)),
        ("plan", plan, "base", False),
    ]


def test_execute_patch_plan_restores_before_cleanup_on_failure(monkeypatch, tmp_path):
    calls = []

    class Patcher:
        def __init__(self, *_args) -> None:
            pass

        def set_override_game_path(self, _path):
            pass

        def process_patch_plan(self, *_args, **_kwargs):
            return False

        def restore_all_backups(self):
            calls.append("restore")

        def cleanup(self, *, force=False):
            calls.append(("cleanup", force))

    monkeypatch.setattr(
        "services.g3mtool_patching_service.G3MToolPatchingService", Patcher
    )
    monkeypatch.setattr("services.game_runner.get_user_data_root", lambda: str(tmp_path))
    plan = PatchPlan.from_dict({"sections": {}})

    assert _execute_patch_plan(plan, str(tmp_path), MagicMock(), {}) is None
    assert calls == ["restore", ("cleanup", True)]


class TestBuildShortcutConfig:
    """Tests for shortcut."""
    def test_basic_config(self, mock_app_state):
        """Checks that basicing config."""
        patch_plan = PatchPlan.from_dict(
            {"sections": {"deltarune_2": [["test_mod"]]}}
        )
        cfg = _build_shortcut_config(mock_app_state, patch_plan)
        assert cfg["game_id"] == "deltarune"
        assert cfg["chapter_mode"] is True
        assert cfg["chapter_mods"] == {"deltarune_2": "test_mod"}
        assert "launch_via_steam" in cfg

    def test_steam_launch(self, mock_app_state):
        """Checks that steaming launch."""
        mock_app_state.local_config["launch_via_steam"] = True
        cfg = _build_shortcut_config(mock_app_state, PatchPlan())
        assert cfg["launch_via_steam"] is True

    def test_non_chapter_mode(self, mock_app_state):
        """Checks that noning chapter mode."""
        mock_app_state.current_mode = "full"
        cfg = _build_shortcut_config(mock_app_state, PatchPlan())
        assert cfg["chapter_mode"] is False

    def test_includes_plugin_state_when_present(self, mock_app_state):
        patch_plan = PatchPlan.from_dict(
            {"sections": {"deltarune_2": [["test_mod"]]}}
        )
        plugin_context = ShortcutPluginContext({"game_id": "deltarune"})
        plugin_context.set_plugin_state("custom_saves_folders", {"folder": "SOJ"})
        plugin_context.add_summary_line("Save Folder", "SOJ")
        cfg = _build_shortcut_config(mock_app_state, patch_plan, plugin_context)

        assert cfg["plugin_states"] == {"custom_saves_folders": {"folder": "SOJ"}}
        assert cfg["plugin_summary"] == [{"label": "Save Folder", "value": "SOJ"}]


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
        """Checks that mod with g3mtool available."""
        with patch("adapters.g3mtool_adapter.G3MToolManager") as mock_g3m:
            mock_g3m.return_value.is_available.return_value = True
            error = _validate_shortcut_prerequisites(mock_app_state, True)
            assert error is None

    def test_mod_with_g3mtool_unavailable(self, mock_app_state):
        """Checks that mod with g3mtool unavailable."""
        with patch("adapters.g3mtool_adapter.G3MToolManager") as mock_g3m:
            mock_g3m.return_value.is_available.return_value = False
            mock_g3m.return_value.get_unavailable_reason.return_value = (
                "G3MTool executable was not found."
            )
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
        """Checks that withing with mod."""
        name = _generate_shortcut_filename(game_mode, {"deltarune_2": mock_mod_data})
        assert "G3M" in name
        assert "Test_Mod" in name

    def test_vanilla(self, game_mode):
        """Checks that vanillaing works."""
        name = _generate_shortcut_filename(game_mode, {"deltarune_2": None})
        assert "G3M" in name
        assert "Vanilla" in name

    def test_safe_characters(self, game_mode, mock_mod_data):
        """Checks that sanitizing characters."""
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

    def test_windows_vbs_no_console(self, shortcut_temp_dir):
        """Checks that windowsing vbs no console."""
        filepath = os.path.join(shortcut_temp_dir, f"test{_get_platform_extension()}")
        _write_shortcut_file(filepath, {"game_id": "deltarune"})
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        if platform.system() == "Windows":
            assert "WScript.Shell" in content and ", 0, False" in content
        else:
            assert content.startswith("#!/bin/bash") and "--shortcut" in content

    def test_unix_executable(self, shortcut_temp_dir):
        """Checks that unixing executable."""
        filepath = os.path.join(shortcut_temp_dir, f"test{_get_platform_extension()}")
        _write_shortcut_file(filepath, {"game_id": "deltarune"})
        if platform.system() == "Windows":
            assert os.path.isfile(filepath)
        else:
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


class TestShortcutDialog:
    def test_summary_includes_plugin_toggle_and_summary_lines(self, qapp, mock_app_state):
        plugin_context = MagicMock()
        plugin_context.enabled = True
        plugin_context.summary_lines = [("Save Folder", "SOJ")]
        dialog = ShortcutDialog(
            mock_app_state.game_mode,
            {"deltarune_2": None},
            {"chapter_mode": True, "launch_via_steam": False, "direct_launch_chapter": ""},
            plugin_context,
        )
        try:
            assert dialog.plugin_actions_checkbox.isChecked() is False
            assert "Save Folder: SOJ" in dialog.summary_label.text()
        finally:
            dialog.close()

    def test_relocalize_updates_header_text(self, qapp, mock_app_state):
        dialog = ShortcutDialog(
            mock_app_state.game_mode,
            {"deltarune_2": None},
            {"chapter_mode": True, "launch_via_steam": False, "direct_launch_chapter": ""},
            None,
        )
        try:
            original = dialog.header_label.text()
            dialog.header_label.setText("stale")
            dialog.relocalize_ui()
            assert dialog.header_label.text() == original
        finally:
            dialog.close()

    def test_summary_lists_sequential_mod_steps(self, qapp, mock_app_state):
        base = SimpleNamespace(id="base", name="Base Mod")
        addon = SimpleNamespace(id="addon", name="Addon Mod")
        dialog = ShortcutDialog(
            mock_app_state.game_mode,
            {"deltarune_2": [base, addon]},
            {
                "chapter_mode": True,
                "launch_via_steam": False,
                "direct_launch_chapter": "",
            },
        )
        try:
            assert "Base Mod → Addon Mod" in dialog.summary_label.text()
        finally:
            dialog.close()

    def test_dialog_uses_larger_size_and_checkbox_starts_unchecked(self, qapp, mock_app_state):
        dialog = ShortcutDialog(
            mock_app_state.game_mode,
            {"deltarune_2": None},
            {"chapter_mode": True, "launch_via_steam": False, "direct_launch_chapter": ""},
            ShortcutPluginContext({"game_id": "deltarune"}),
            [],
        )
        try:
            assert dialog.minimumWidth() >= 540
            assert dialog.minimumHeight() >= 220
            assert dialog.plugin_actions_checkbox.isChecked() is False
        finally:
            dialog.close()

    def test_disable_plugin_actions_hides_plugin_section(self, qapp, mock_app_state):
        plugin_context = ShortcutPluginContext({"game_id": "deltarune"})
        plugin_context.add_summary_line("Save Folder", "SOJ")
        plugin_blocks = [
            {
                "plugin_id": "deltarune_save_manager",
                "type": "select",
                "label": "Collection",
                "key": "collection_idx",
                "options": [
                    {"label": "Main slots", "value": -1},
                    {"label": "Test", "value": 0},
                ],
                "value": 0,
            }
        ]
        dialog = ShortcutDialog(
            mock_app_state.game_mode,
            {"deltarune_2": None},
            {"chapter_mode": True, "launch_via_steam": False, "direct_launch_chapter": ""},
            plugin_context,
            plugin_blocks,
        )
        try:
            dialog.show()
            qapp.processEvents()
            height_before = dialog.height()
            assert dialog.plugin_section_widget.isHidden() is False
            assert "Save Folder: SOJ" in dialog.summary_label.text()
            dialog.plugin_actions_checkbox.setChecked(True)
            qapp.processEvents()
            assert dialog.plugin_section_widget.isHidden() is True
            assert "Save Folder: SOJ" not in dialog.summary_label.text()
            assert dialog.height() < height_before
        finally:
            dialog.close()

    def test_collect_plugin_values_serializes_select_blocks(self, qapp, mock_app_state):
        plugin_context = ShortcutPluginContext({"game_id": "deltarune"})
        plugin_blocks = [
            {
                "plugin_id": "deltarune_save_manager",
                "type": "select",
                "label": "Collection",
                "key": "collection_idx",
                "options": [
                    {"label": "Main slots", "value": -1},
                    {"label": "Test", "value": 0},
                ],
                "value": 0,
            }
        ]
        dialog = ShortcutDialog(
            mock_app_state.game_mode,
            {"deltarune_2": None},
            {"chapter_mode": True, "launch_via_steam": False, "direct_launch_chapter": ""},
            plugin_context,
            plugin_blocks,
        )
        try:
            payload = dialog.collect_plugin_values()
            assert payload == {"deltarune_save_manager": {"collection_idx": 0}}
        finally:
            dialog.close()


class TestShortcutPluginHooks:
    def test_shortcut_configure_logging_installs_process_exit_logging(self, monkeypatch, tmp_path):
        from services import game_runner

        registered = []
        monkeypatch.setattr(game_runner, "get_user_data_root", lambda: str(tmp_path))
        monkeypatch.setattr(game_runner.atexit, "register", lambda callback: registered.append(callback))

        game_runner._configure_logging()
        registered[0]()

        assert registered
        log_text = (tmp_path / "logs" / "shortcut.log").read_text(encoding="utf-8")
        assert "Shortcut runner process exiting after" in log_text

    def test_execute_shortcut_plugin_hook_returns_false_when_plugin_blocks(self):
        runtime = MagicMock()
        runtime.execute_hook.return_value = [True, False]

        result = execute_shortcut_plugin_hook(
            runtime,
            "before_mod_apply_shortcut",
            MagicMock(),
        )

        assert result is False

    def test_execute_shortcut_plugin_hook_defaults_true_without_runtime(self):
        assert execute_shortcut_plugin_hook(None, "before_mod_apply_shortcut", MagicMock()) is True


class TestShortcutPluginContext:
    def test_matches_game_supports_allow_and_block_lists(self):
        context = ShortcutPluginContext({"game_id": "deltarune"})

        assert context.matches_game(allowed={"deltarune"}) is True
        assert context.matches_game(allowed={"undertale"}) is False
        assert context.matches_game(blocked={"undertale"}) is True
        assert context.matches_game(blocked={"deltarune"}) is False


class TestShortcutPluginBlocks:
    def test_collect_shortcut_plugin_blocks_uses_hook_results(self, mock_app_state):
        runtime = MagicMock()
        runtime.execute_hook.return_value = [
            [
                {
                    "plugin_id": "custom_saves_folders",
                    "type": "text",
                    "label": "Custom Save Folder",
                    "value": "SOJ",
                }
            ]
        ]
        plugin_context = ShortcutPluginContext({"game_id": "deltarune"})

        blocks = _collect_shortcut_plugin_blocks(runtime, plugin_context)

        assert blocks == [
            {
                "plugin_id": "custom_saves_folders",
                "type": "text",
                "label": "Custom Save Folder",
                "value": "SOJ",
            }
        ]


class TestShortcutButtonFlow:
    def test_shortcut_success_ignores_broken_feedback(self, mock_app_state):
        feedback_service = MagicMock()
        feedback_service.show_message.side_effect = RuntimeError("feedback deleted")
        used_mods_service = MagicMock()
        used_mods_service.get_used_mods_list.return_value = []
        parent_widget = MagicMock()
        parent_widget.plugin_runtime_service = None

        class _FakeDialog:
            def __init__(
                self,
                game_mode,
                section_mod_objects,
                shortcut_config,
                plugin_context=None,
                plugin_blocks=None,
                parent=None,
            ) -> None:
                pass

            def exec(self):
                return QDialog.DialogCode.Accepted

            def plugin_actions_enabled(self):
                return False

        with (
            patch("controllers.shortcut_controller.ShortcutDialog", _FakeDialog),
            patch(
                "controllers.shortcut_controller.get_save_file_name",
                return_value=("C:/tmp/test.vbs", "VBScript (*.vbs)"),
            ),
            patch("controllers.shortcut_controller._write_shortcut_file") as write_shortcut,
        ):
            from controllers.shortcut_controller import on_shortcut_button_click

            on_shortcut_button_click(
                mock_app_state,
                feedback_service,
                used_mods_service,
                parent_widget,
            )

        write_shortcut.assert_called_once()

    def test_shortcut_flow_collects_dialog_plugin_values(self, mock_app_state):
        feedback_service = MagicMock()
        used_mods_service = MagicMock()
        used_mods_service.get_used_mods_list.return_value = []
        parent_widget = MagicMock()
        parent_widget.plugin_runtime_service = MagicMock()
        dialogs = []

        class _FakeDialog:
            def __init__(
                self,
                game_mode,
                section_mod_objects,
                shortcut_config,
                plugin_context=None,
                plugin_blocks=None,
                parent=None,
            ) -> None:
                self.shortcut_config = shortcut_config
                self.plugin_context = plugin_context
                self.plugin_blocks = plugin_blocks or []
                self.plugin_actions_checkbox = MagicMock()
                dialogs.append(self)

            def exec(self):
                return QDialog.DialogCode.Accepted

            def plugin_actions_enabled(self):
                return True

            def collect_plugin_values(self):
                return {"deltarune_save_manager": {"collection_idx": 0}}

        with (
            patch("controllers.shortcut_controller.ShortcutDialog", _FakeDialog),
            patch(
                "controllers.shortcut_controller._collect_shortcut_plugin_blocks",
                return_value=[
                    {
                        "plugin_id": "deltarune_save_manager",
                        "type": "select",
                        "label": "Collection",
                        "key": "collection_idx",
                        "options": [{"label": "Test", "value": 0}],
                        "value": 0,
                    }
                ],
            ),
            patch(
                "controllers.shortcut_controller.get_save_file_name",
                return_value=("C:/tmp/test.vbs", "VBScript (*.vbs)"),
            ),
            patch("controllers.shortcut_controller._write_shortcut_file") as write_shortcut,
        ):
            from controllers.shortcut_controller import on_shortcut_button_click

            on_shortcut_button_click(
                mock_app_state,
                feedback_service,
                used_mods_service,
                parent_widget,
            )

        assert len(dialogs) == 1
        assert dialogs[0].plugin_context is not None
        assert dialogs[0].plugin_blocks[0]["plugin_id"] == "deltarune_save_manager"
        written_cfg = write_shortcut.call_args.args[1]
        assert written_cfg["plugin_states"] == {
            "deltarune_save_manager": {"collection_idx": 0}
        }
