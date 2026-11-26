"""Tests for shortcut creation, validation, config building, file writing, and runner parsing."""

import base64
import json
import os
import platform
import shutil
import tempfile
from pathlib import Path
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
from services.game_runner import (
    _execute_operation_plan,
    _find_mod_source_dir,
    _launch_game,
    _legacy_operation_is_selected,
    _parse_shortcut_arg,
    _restore_operation_session,
    _restore_shortcut_state,
    _shortcut_legacy_sections,
    _shortcut_merge_steps,
    _shortcut_mod_ids,
    _wait_for_game_exit,
    run_shortcut,
)
from services.plugins.shortcut_service import (
    ShortcutPluginContext,
    execute_shortcut_plugin_hook,
)
from utils.mod.archive import ArchiveVirtualPath


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
    config = {
        "config_version": "2.0.0",
        "id": "test_mod_001",
        "name": "Test Mod",
        "version": "1.0.0",
        "authors": [],
        "game": "deltarune",
        "files": [],
    }
    with open(os.path.join(mod_dir, "mod_config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    chapter_dir = os.path.join(mod_dir, "chapter_2")
    os.makedirs(chapter_dir, exist_ok=True)
    return mod_dir


class TestParseShortcutArg:
    """Tests for shortcut."""

    def test_parse_base64(self):
        """Checks that parsing base64."""
        cfg = {"game_id": "deltarune", "mod_ids": ["gb_mod_123"]}
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
        cfg = {"game_id": "deltarune", "mod_ids": ["test"]}
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
    def test_reads_mod_ids_from_legacy_shortcut_configs(self):
        assert _shortcut_mod_ids(
            {
                "launch_plan": {
                    "patch_plan": {
                        "sections": {
                            "chapter_2": [["chapter-two"]],
                            "chapter_1": [["base"], ["addon"]],
                        }
                    }
                }
            }
        ) == ("base", "addon", "chapter-two")
        assert _shortcut_mod_ids(
            {"chapter_mods": {"chapter_2": "chapter-two", "chapter_1": "base"}}
        ) == ("base", "chapter-two")
        assert _shortcut_legacy_sections(
            {"chapter_mods": {"chapter_2": "chapter-two", "chapter_1": "base"}}
        ) == {"chapter_2": ("chapter-two",), "chapter_1": ("base",)}

    def test_legacy_shortcut_filters_archive_targets_by_chapter(self, tmp_path):
        game_path = tmp_path / "game"
        operation = SimpleNamespace(
            mod_id="chapter-mod",
            target=ArchiveVirtualPath(
                game_path / "chapter2_windows" / "data.zip",
                "data.win",
                False,
                "zip",
            ),
        )

        assert not _legacy_operation_is_selected(
            operation, {"chapter-mod": {"deltarune_1"}}, game_path
        )
        assert _legacy_operation_is_selected(
            operation, {"chapter-mod": {"deltarune_2"}}, game_path
        )

    @pytest.mark.parametrize("missing_unselected_source", [False, True])
    @pytest.mark.parametrize("missing_selected_source", [False, True])
    @pytest.mark.parametrize("current_format", [False, True])
    def test_legacy_shortcut_only_applies_selected_chapter_operations(self, monkeypatch, tmp_path, missing_unselected_source, missing_selected_source, current_format):
        monkeypatch.setattr("services.game_runner.platform.system", lambda: "Windows")
        mod_root = tmp_path / "mod"
        mod_root.mkdir()
        if not missing_selected_source:
            (mod_root / "one.xdelta").write_text("one", encoding="utf-8")
        if not missing_unselected_source:
            (mod_root / "two.xdelta").write_text("two", encoding="utf-8")
        (mod_root / "mod_config.json").write_text(
            json.dumps(
                {
                    "config_version": "2.0.0",
                    "id": "chapter-mod",
                    "name": "Chapter mod",
                    "version": "1.0.0",
                    "authors": [],
                    "game": "deltarune",
                    "files": [
                        {
                            "source": "${mod_path}/one.xdelta",
                            "target": "${game_path}/chapter1_windows/data.win",
                            "type": "patch",
                        },
                        {
                            "source": "${mod_path}/two.xdelta",
                            "target": "${game_path}/chapter2_windows/data.win",
                            "type": "patch",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        game_path = tmp_path / "game"
        game_path.mkdir()
        for chapter in ("chapter1_windows", "chapter2_windows"):
            chapter_path = game_path / chapter
            chapter_path.mkdir()
            (chapter_path / "data.win").write_bytes(b"base")
        captured = {}

        def execute(_executor, plan):
            captured["plan"] = plan
            captured["merger"] = _executor.merger
            return MagicMock()

        game = SimpleNamespace(
            game_id="deltarune",
            executable_type="deltarune",
            get_data_path=lambda _config: None,
            get_custom_exec_config_key=lambda: "",
        )
        monkeypatch.setattr("services.game_runner._find_mod_source_dir", lambda *_args: str(mod_root))
        monkeypatch.setattr("services.game_runner.get_user_data_root", lambda: str(tmp_path))
        monkeypatch.setattr("services.mod_operation_executor.ModOperationExecutor.execute", execute)

        if current_format:
            state = SimpleNamespace(
                current_mode="chapter",
                game_mode=SimpleNamespace(game_id="deltarune", steam_app_id=None),
                local_config={},
            )
            config = _build_shortcut_config(
                state, ["chapter-mod"],
                section_mod_objects={"deltarune_1": [{"id": "chapter-mod"}], "deltarune_2": []},
            )
            selections = _shortcut_legacy_sections(config)
            assert config["section_mod_ids"] == {"deltarune_1": ["chapter-mod"], "deltarune_2": []}
        else:
            selections = {"chapter_1": ("chapter-mod",)}
        journal = _execute_operation_plan(
            ("chapter-mod",),
            str(game_path),
            game,
            {},
            legacy_sections=selections,
        )

        if missing_selected_source:
            assert journal is None
            assert "plan" not in captured
            return
        assert [operation.target for operation in captured["plan"].operations] == [
            game_path / "chapter1_windows" / "data.win"
        ]
        assert captured["merger"] is not None
        assert not captured["plan"].has_errors

    @pytest.mark.parametrize("sections", [{}, {"chapter_1": ["other-mod"]}, {"unknown": ["selected"]}])
    def test_current_shortcut_rejects_invalid_section_assignments(self, sections):
        with pytest.raises(ValueError):
            _shortcut_legacy_sections({"game_id": "deltarune", "mod_ids": ["selected"], "section_mod_ids": sections})

    def test_keeps_saved_merge_steps(self):
        assert _shortcut_merge_steps(
            {"merge_steps": [["base", "addon"]]}, ("base", "addon")
        ) == (("base", "addon"),)

    def test_runner_passes_saved_merge_steps_to_operations(self, monkeypatch, tmp_path):
        game = SimpleNamespace(
            get_game_path=lambda _config: str(tmp_path),
            get_data_path=lambda _config: str(tmp_path),
        )
        journal = MagicMock()
        execute = MagicMock(return_value=journal)
        monkeypatch.setattr("services.game_runner._configure_logging", lambda: None)
        monkeypatch.setattr("services.game_runner.get_game", lambda _game_id: game)
        monkeypatch.setattr("services.game_runner._load_config", lambda: {"active_profile": "Other"})
        monkeypatch.setattr(
            "services.game_runner.get_profile_mods_root", lambda _profile: str(tmp_path)
        )
        monkeypatch.setattr(
            "services.mod_config_migration_service.migrate_managed_mods",
            lambda _root: SimpleNamespace(issues=()),
        )
        monkeypatch.setattr("services.game_runner.execute_shortcut_plugin_hook", lambda *_args: True)
        monkeypatch.setattr("services.game_runner._execute_operation_plan", execute)
        monkeypatch.setattr("services.game_runner._launch_game", lambda *_args: None)
        monkeypatch.setattr("services.game_runner._restore_operation_session", lambda _journal: None)

        run_shortcut(
            json.dumps(
                {
                    "game_id": "deltarune",
                    "active_profile": "Captured",
                    "mod_ids": ["base", "addon"],
                    "merge_steps": [["base", "addon"]],
                    "section_mod_ids": {"deltarune_1": ["base", "addon"]},
                }
            )
        )

        assert execute.call_args.kwargs["merge_steps"] == (("base", "addon"),)
        assert execute.call_args.kwargs["legacy_sections"] == {"deltarune_1": ("base", "addon")}
        assert execute.call_args.args[3]["active_profile"] == "Captured"

    def test_runner_restores_plugin_state_when_plan_fails(self, monkeypatch, tmp_path):
        game = SimpleNamespace(get_game_path=lambda _config: str(tmp_path))
        hooks = []
        monkeypatch.setattr("services.game_runner._configure_logging", lambda: None)
        monkeypatch.setattr("services.game_runner.get_game", lambda _game_id: game)
        monkeypatch.setattr("services.game_runner._load_config", lambda: {})
        monkeypatch.setattr(
            "services.game_runner.get_profile_mods_root", lambda _profile: str(tmp_path)
        )
        monkeypatch.setattr(
            "services.mod_config_migration_service.migrate_managed_mods",
            lambda _root: SimpleNamespace(issues=()),
        )
        monkeypatch.setattr(
            "services.game_runner.execute_shortcut_plugin_hook",
            lambda _runtime, hook, *_args: hooks.append(hook) or True,
        )
        monkeypatch.setattr("services.game_runner._execute_operation_plan", lambda *_args, **_kwargs: None)
        monkeypatch.setattr("services.game_runner._restore_operation_session", lambda _journal: hooks.append("restore"))

        with pytest.raises(SystemExit):
            run_shortcut(json.dumps({"game_id": "deltarune", "mod_ids": ["base"]}))

        assert hooks == [
            "before_mod_apply_shortcut",
            "before_restore_after_exit_shortcut",
            "restore",
            "after_restore_after_exit_shortcut",
        ]

    def test_runner_restores_state_when_checkpoint_fails(self, monkeypatch, tmp_path):
        game = SimpleNamespace(get_game_path=lambda _config: str(tmp_path))
        journal = MagicMock()
        journal.checkpoint.side_effect = OSError("journal write failed")
        hooks = []
        monkeypatch.setattr("services.game_runner._configure_logging", lambda: None)
        monkeypatch.setattr("services.game_runner.get_game", lambda _game_id: game)
        monkeypatch.setattr("services.game_runner._load_config", lambda: {})
        monkeypatch.setattr(
            "services.game_runner.get_profile_mods_root", lambda _profile: str(tmp_path)
        )
        monkeypatch.setattr(
            "services.mod_config_migration_service.migrate_managed_mods",
            lambda _root: SimpleNamespace(issues=()),
        )
        monkeypatch.setattr(
            "services.game_runner.execute_shortcut_plugin_hook",
            lambda _runtime, hook, *_args: hooks.append(hook) or True,
        )
        monkeypatch.setattr(
            "services.game_runner._execute_operation_plan",
            lambda *_args, **_kwargs: journal,
        )
        monkeypatch.setattr(
            "services.game_runner._restore_operation_session",
            lambda _journal: hooks.append("restore"),
        )

        with pytest.raises(SystemExit):
            run_shortcut(json.dumps({"game_id": "deltarune", "mod_ids": ["base"]}))

        journal.checkpoint.assert_called_once_with()
        assert hooks == [
            "before_mod_apply_shortcut",
            "after_mod_apply_before_launch_shortcut",
            "before_restore_after_exit_shortcut",
            "restore",
            "after_restore_after_exit_shortcut",
        ]

    def test_wait_for_game_exit_does_not_stop_after_ten_minutes(self):
        tracker = MagicMock()
        tracker.refresh.side_effect = [True] * 301 + [False] * 4
        with (
            patch("services.game_runner.GameProcessTracker", return_value=tracker),
            patch("services.game_runner.time.sleep"),
        ):
            _wait_for_game_exit(None, ("DELTARUNE.exe",), set())

        assert tracker.refresh.call_count == 305

    def test_wait_for_game_exit_keeps_polling_after_launcher_exits(self):
        tracker = MagicMock()
        tracker.refresh.side_effect = [False, False, True, False, False, False, False]
        process = MagicMock()
        process.poll.return_value = 0
        with (
            patch("services.game_runner.GameProcessTracker", return_value=tracker),
            patch("services.game_runner.platform.system", return_value="Windows"),
            patch("services.game_runner.time.sleep"),
        ):
            _wait_for_game_exit(process, ("DELTARUNE.exe",), set())

        assert tracker.refresh.call_count == 7

    def test_launch_game_sanitizes_linux_env_for_wine(
        self, game_mode, shortcut_temp_dir
    ):
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
            patch(
                "services.game_runner.subprocess.Popen", return_value=fake_process
            ) as popen,
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
        assert popen.call_args.args[0] == [
            "wine",
            os.path.join(game_path, "DELTARUNE.exe"),
        ]
        assert popen.call_args.kwargs["cwd"] == game_path
        assert (
            popen.call_args.kwargs["env"]["LD_LIBRARY_PATH"]
            == "/usr/lib:/usr/local/lib"
        )

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
            patch(
                "services.game_runner.subprocess.Popen", return_value=fake_process
            ) as popen,
            patch("services.game_runner._wait_for_game_exit"),
        ):
            process = _launch_game(shortcut_config, game_mode, local_config, game_path)

        assert process is fake_process
        assert popen.call_args.args[0] == [
            "/opt/wine-staging/bin/wine",
            os.path.join(game_path, "DELTARUNE.exe"),
        ]

    def test_launch_game_uses_wine64_when_wine_missing(
        self, game_mode, shortcut_temp_dir
    ):
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
            patch(
                "services.game_runner.subprocess.Popen", return_value=fake_process
            ) as popen,
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
        cfg = {"game_id": "deltarune", "mod_ids": ["мод_тест"]}
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

    def test_rejects_mod_folder_without_a_current_config(self, shortcut_temp_dir):
        """A folder name alone never grants a shortcut mod identity."""
        profile_dir = os.path.join(shortcut_temp_dir, "profiles", "Default")
        folder = os.path.join(profile_dir, "my_cool_mod")
        os.makedirs(folder, exist_ok=True)
        with patch(self.PATCH_TARGET, return_value=profile_dir):
            result = _find_mod_source_dir("my_cool_mod", {})
            assert result is None


class TestCollectChapterData:
    """Tests for shortcut."""

    def test_chapter_mode_all_vanilla(
        self, mock_used_mods_service_empty, mock_app_state
    ):
        """Checks that chaptering mode all vanilla."""
        result = _collect_section_data(mock_used_mods_service_empty, mock_app_state)
        assert result is not None
        mod_ids, chapter_objs = result
        assert not mod_ids
        assert all(not v for v in chapter_objs.values())
        assert len(chapter_objs) > 1

    def test_chapter_mode_single_mod_per_chapter(
        self, mock_used_mods_service, mock_app_state
    ):
        """Checks that chaptering mode single mod per chapter."""
        result = _collect_section_data(mock_used_mods_service, mock_app_state)
        assert result is not None
        mod_ids, _chapter_objs = result
        assert mod_ids == ["test_mod_001"]

    def test_chapter_mode_keeps_multiple_mods_in_one_step(self, mock_app_state):
        svc = MagicMock()
        svc.get_mod_steps.return_value = None
        svc.get_used_mods_list.return_value = [
            MagicMock(id="base"),
            MagicMock(id="addon"),
        ]
        mod_ids, _, merge_steps = _collect_section_data(
            svc, mock_app_state, include_merge_steps=True
        )
        assert mod_ids == ["base", "addon"]
        assert merge_steps == [["base", "addon"]]

    def test_chapter_mode_allows_multiple_single_mod_steps(self, mock_app_state):
        """Sequential shortcut patching remains available for dependent mods."""
        svc = MagicMock()
        svc.get_mod_steps.return_value = [
            [MagicMock(id="base")],
            [MagicMock(id="addon")],
        ]

        result = _collect_section_data(svc, mock_app_state)

        assert result is not None
        mod_ids, _ = result
        assert mod_ids == ["base", "addon"]

    def test_non_chapter_mode_vanilla(
        self, mock_used_mods_service_empty, mock_app_state
    ):
        """Checks that noning chapter mode vanilla."""
        mock_app_state.current_mode = "full"
        result = _collect_section_data(mock_used_mods_service_empty, mock_app_state)
        assert result is not None
        mod_ids, chapter_objs = result
        assert not mod_ids
        assert len(chapter_objs) == len(mock_app_state.game_mode.tabs)

    def test_non_chapter_mode_expands_to_chapters_with_data(self, mock_app_state):
        """Checks that noning chapter mode expands to chapters with data."""
        mock_app_state.current_mode = "full"
        mod = MagicMock()
        mod.id = "test_mod_001"
        mod.name = "Test Mod"
        mod.supports_section = lambda tab_id: tab_id in ("deltarune_1", "deltarune_2")
        svc = MagicMock()
        svc.get_used_mods_list.return_value = [mod]
        result = _collect_section_data(svc, mock_app_state)
        assert result is not None
        mod_ids, _ = result
        assert mod_ids == ["test_mod_001"]


def test_shortcut_rejects_unresolved_mod_without_legacy_patcher(monkeypatch, game_mode, tmp_path):
    monkeypatch.setattr("services.game_runner.get_profile_mods_root", lambda _profile: str(tmp_path))
    assert _execute_operation_plan(("base", "addon"), str(tmp_path), game_mode, {}) is None


def test_shortcut_executes_and_restores_a_operation_operation_plan(
    monkeypatch, game_mode, tmp_path
):
    from utils.mod.config import write_mod_config

    mods_dir = tmp_path / "mods"
    mod_dir = mods_dir / "Operation Mod"
    mod_dir.mkdir(parents=True)
    (mod_dir / "replacement.txt").write_text("replacement", encoding="utf-8")
    write_mod_config(
        mod_dir / "mod_config.json",
        {
            "config_version": "2.0.0",
            "id": "operation_mod",
            "name": "Operation Mod",
            "version": "1.0.0",
            "authors": ["Author"],
            "game": "deltarune",
            "files": [
                {
                    "source": "${mod_path}/replacement.txt",
                    "target": "${game_path}/target.txt",
                    "type": "overwrite",
                }
            ],
        },
    )
    game_path = tmp_path / "game"
    game_path.mkdir()
    target = game_path / "target.txt"
    target.write_text("original", encoding="utf-8")
    monkeypatch.setattr("services.game_runner.get_profile_mods_root", lambda _profile: str(mods_dir))
    monkeypatch.setattr("services.game_runner.get_user_data_root", lambda: str(tmp_path))
    journal = _execute_operation_plan(("operation_mod",), str(game_path), game_mode, {})

    assert journal is not None
    assert target.read_text(encoding="utf-8") == "replacement"
    retry_journal = _execute_operation_plan(
        ("operation_mod",), str(game_path), game_mode, {}
    )
    assert retry_journal is not None
    _restore_operation_session(retry_journal)
    assert target.read_text(encoding="utf-8") == "original"


def test_shortcut_requires_explicit_direct_path_approval(
    monkeypatch, game_mode, tmp_path
):
    from utils.mod.config import write_mod_config

    mods_dir = tmp_path / "mods"
    mod_dir = mods_dir / "Direct Paths"
    mod_dir.mkdir(parents=True)
    source = mod_dir / "replacement.txt"
    source.write_text("replacement", encoding="utf-8")
    game_path = tmp_path / "game"
    game_path.mkdir()
    outside = tmp_path / "outside"  # a folder the user did not choose as the game or data folder
    outside.mkdir()
    target = outside / "target.txt"
    target.write_text("original", encoding="utf-8")
    write_mod_config(
        mod_dir / "mod_config.json",
        {
            "config_version": "2.0.0",
            "id": "direct_paths",
            "name": "Direct Paths",
            "version": "1.0.0",
            "authors": [],
            "game": "deltarune",
            "files": [
                {
                    "source": source.as_posix(),
                    "target": target.as_posix(),
                    "type": "overwrite",
                }
            ],
        },
    )
    monkeypatch.setattr("services.game_runner.get_profile_mods_root", lambda _profile: str(mods_dir))
    monkeypatch.setattr("services.game_runner.get_user_data_root", lambda: str(tmp_path))
    config: dict[str, dict[str, object]] = {"warning_preferences": {"skip_all": True}}

    assert _execute_operation_plan(("direct_paths",), str(game_path), game_mode, config) is None
    assert target.read_text(encoding="utf-8") == "original"

    config["warning_preferences"]["warning_overrides"] = {
        "direct_absolute_operation_paths": False
    }
    journal = _execute_operation_plan(("direct_paths",), str(game_path), game_mode, config)

    assert journal is not None
    _restore_operation_session(journal)


def test_shortcut_uses_xdelta_backend_for_a_operation_patch(monkeypatch, game_mode, tmp_path):
    from utils.mod.config import write_mod_config

    monkeypatch.setattr("services.game_runner.platform.system", lambda: "Windows")

    class _G3MTool:
        def is_available(self):
            return True

        def get_unavailable_reason(self):
            return "unavailable"

        def xpatch_apply(self, original, patch, output):
            assert Path(original).read_text(encoding="utf-8") == "original"
            assert Path(patch).name == "data.xdelta"
            Path(output).write_text("patched", encoding="utf-8")
            return 0, "", ""

        def apply_patch(self, *_args):
            raise AssertionError("xdelta must use xpatch_apply")

    mods_dir = tmp_path / "mods"
    mod_dir = mods_dir / "Operation Patch"
    mod_dir.mkdir(parents=True)
    (mod_dir / "data.xdelta").write_bytes(b"patch")
    write_mod_config(
        mod_dir / "mod_config.json",
        {
            "config_version": "2.0.0",
            "id": "operation_patch",
            "name": "Operation Patch",
            "version": "1.0.0",
            "authors": [],
            "game": "deltarune",
            "files": [
                {
                    "source": "${mod_path}/data.xdelta",
                    "target": "${game_path}/data.win",
                    "type": "patch",
                }
            ],
        },
    )
    game_path = tmp_path / "game"
    game_path.mkdir()
    target = game_path / "data.win"
    target.write_text("original", encoding="utf-8")
    monkeypatch.setattr("services.game_runner.get_profile_mods_root", lambda _profile: str(mods_dir))
    monkeypatch.setattr("services.game_runner.get_user_data_root", lambda: str(tmp_path))
    monkeypatch.setattr("adapters.g3mtool_adapter.G3MToolManager", _G3MTool)

    journal = _execute_operation_plan(
        ("operation_patch",),
        str(game_path),
        game_mode,
        {},
    )

    assert journal is not None
    assert target.read_text(encoding="utf-8") == "patched"
    _restore_operation_session(journal)
    assert target.read_text(encoding="utf-8") == "original"


def test_restore_operation_session_uses_the_journal() -> None:
    journal = MagicMock()

    _restore_operation_session(journal)

    journal.restore.assert_called_once_with()


@pytest.mark.parametrize("external_change", [False, True])
def test_shortcut_plugin_restoration_checkpoints_only_verified_changes(tmp_path, external_change):
    from services.mod_operation_executor import ModOperationExecutor
    from utils.mod.operation_plan import ModPathContext, build_mod_operation_plan

    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    target = game_root / "data.win"
    target.write_bytes(b"original")
    (mod_root / "data.win").write_bytes(b"deployed")
    plan = build_mod_operation_plan(
        {"config_version": "2.0.0", "id": "mod", "name": "Mod", "version": "1.0.0", "authors": [], "game": "deltarune", "files": [
            {"source": "${mod_path}/data.win", "target": "${game_path}/data.win", "type": "overwrite"},
        ]},
        ModPathContext.create(mod_path=mod_root, game_path=game_root, game_data_path=None, user_path=tmp_path, runtime="windows"),
    )
    journal = ModOperationExecutor(tmp_path / "journal").execute(plan)
    if external_change:
        target.write_bytes(b"external")
    runtime = MagicMock()
    runtime.has_enabled_hook.return_value = True

    def restore_plugin(hook, *_args, **_kwargs):
        if hook == "before_restore_after_exit_shortcut":
            target.write_bytes(b"plugin-restored")
        return [True]

    runtime.execute_hook_with_runtime.side_effect = restore_plugin
    restored = _restore_shortcut_state(runtime, ShortcutPluginContext({}), {}, journal)

    assert restored is (not external_change)
    assert target.read_bytes() == (b"external" if external_change else b"original")
    if external_change:
        runtime.execute_hook_with_runtime.assert_not_called()


class TestBuildShortcutConfig:
    """Tests for shortcut."""

    def test_basic_config(self, mock_app_state):
        """Checks that basicing config."""
        mock_app_state.local_config["active_profile"] = "Captured"
        cfg = _build_shortcut_config(mock_app_state, ["test_mod"])
        assert cfg["game_id"] == "deltarune"
        assert cfg["chapter_mode"] is True
        assert cfg["mod_ids"] == ["test_mod"]
        assert cfg["active_profile"] == "Captured"
        assert "launch_via_steam" in cfg

    def test_config_includes_merge_steps(self, mock_app_state):
        cfg = _build_shortcut_config(
            mock_app_state, ["base", "addon"], merge_steps=[["base", "addon"]]
        )

        assert cfg["merge_steps"] == [["base", "addon"]]

    def test_steam_launch(self, mock_app_state):
        """Checks that steaming launch."""
        mock_app_state.local_config["launch_via_steam"] = True
        cfg = _build_shortcut_config(mock_app_state, [])
        assert cfg["launch_via_steam"] is True

    def test_steam_launch_is_ignored_without_steam_app_id(self, mock_app_state):
        mock_app_state.local_config["launch_via_steam"] = True
        mock_app_state.game_mode.steam_app_id = ""

        cfg = _build_shortcut_config(mock_app_state, [])

        assert cfg["launch_via_steam"] is False

    def test_non_chapter_mode(self, mock_app_state):
        """Checks that noning chapter mode."""
        mock_app_state.current_mode = "full"
        cfg = _build_shortcut_config(mock_app_state, [])
        assert cfg["chapter_mode"] is False

    def test_includes_plugin_state_when_present(self, mock_app_state):
        plugin_context = ShortcutPluginContext({"game_id": "deltarune"})
        plugin_context.set_plugin_state("custom_saves_folders", {"folder": "SOJ"})
        plugin_context.add_summary_line("Save Folder", "SOJ")
        cfg = _build_shortcut_config(mock_app_state, ["test_mod"], plugin_context)

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
            "mod_ids": ["test"],
            "chapter_mode": True,
        }
        filepath = os.path.join(shortcut_temp_dir, f"test{_get_platform_extension()}")
        result = _write_shortcut_file(filepath, cfg)
        assert os.path.isfile(result)

    def test_write_embeds_base64_config(self, shortcut_temp_dir):
        """Checks that writing embeds base64 config."""
        cfg = {"game_id": "deltarune", "mod_ids": ["test_mod"]}
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
            "mod_ids": ["gb_mod_12345"],
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
    def test_summary_includes_plugin_toggle_and_summary_lines(
        self, qapp, mock_app_state
    ):
        plugin_context = MagicMock()
        plugin_context.enabled = True
        plugin_context.summary_lines = [("Save Folder", "SOJ")]
        dialog = ShortcutDialog(
            mock_app_state.game_mode,
            {"deltarune_2": None},
            {
                "chapter_mode": True,
                "launch_via_steam": False,
                "direct_launch_chapter": "",
            },
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
            {
                "chapter_mode": True,
                "launch_via_steam": False,
                "direct_launch_chapter": "",
            },
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

    def test_dialog_uses_larger_size_and_checkbox_starts_unchecked(
        self, qapp, mock_app_state
    ):
        dialog = ShortcutDialog(
            mock_app_state.game_mode,
            {"deltarune_2": None},
            {
                "chapter_mode": True,
                "launch_via_steam": False,
                "direct_launch_chapter": "",
            },
            ShortcutPluginContext({"game_id": "deltarune"}),
            [],
        )
        try:
            assert dialog.minimumWidth() >= 540
            assert dialog.minimumHeight() >= 220
            assert dialog.plugin_actions_checkbox.isChecked() is False
        finally:
            dialog.close()

    def test_disable_plugin_actions_hides_plugin_section(
        self, qapp, qtbot, mock_app_state
    ):
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
            {
                "chapter_mode": True,
                "launch_via_steam": False,
                "direct_launch_chapter": "",
            },
            plugin_context,
            plugin_blocks,
        )
        try:
            dialog.show()
            qtbot.waitExposed(dialog)
            qtbot.waitUntil(lambda: dialog.height() == dialog.sizeHint().height())
            height_before = dialog.height()
            assert dialog.plugin_section_widget.isHidden() is False
            assert "Save Folder: SOJ" in dialog.summary_label.text()
            dialog.plugin_actions_checkbox.setChecked(True)
            qapp.processEvents()
            assert dialog.plugin_section_widget.isHidden() is True
            assert "Save Folder: SOJ" not in dialog.summary_label.text()
            qtbot.waitUntil(lambda: dialog.height() < height_before)
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
            {
                "chapter_mode": True,
                "launch_via_steam": False,
                "direct_launch_chapter": "",
            },
            plugin_context,
            plugin_blocks,
        )
        try:
            payload = dialog.collect_plugin_values()
            assert payload == {"deltarune_save_manager": {"collection_idx": 0}}
        finally:
            dialog.close()


class TestShortcutPluginHooks:
    def test_shortcut_configure_logging_installs_process_exit_logging(
        self, monkeypatch, tmp_path
    ):
        from services import game_runner

        registered = []
        monkeypatch.setattr(game_runner, "get_user_data_root", lambda: str(tmp_path))
        monkeypatch.setattr(
            game_runner.atexit, "register", lambda callback: registered.append(callback)
        )

        game_runner._configure_logging()
        registered[0]()

        assert registered
        log_text = (tmp_path / "logs" / "shortcut.log").read_text(encoding="utf-8")
        assert "Shortcut runner process exiting after" in log_text

    def test_execute_shortcut_plugin_hook_returns_false_when_plugin_blocks(self):
        runtime = MagicMock()
        runtime.execute_hook_with_runtime.return_value = [True, False]

        result = execute_shortcut_plugin_hook(
            runtime,
            "before_mod_apply_shortcut",
            MagicMock(),
        )

        assert result is False

    def test_execute_shortcut_plugin_hook_blocks_on_plugin_exception(self):
        runtime = MagicMock()
        runtime.execute_hook_with_runtime.side_effect = OSError("save backup failed")
        context = ShortcutPluginContext({"game_id": "deltarune"})

        assert not execute_shortcut_plugin_hook(runtime, "before_mod_apply_shortcut", context)
        runtime.execute_hook_with_runtime.assert_called_once_with(
            "before_mod_apply_shortcut", None, context, raise_errors=True
        )

    def test_shortcut_retains_journal_when_plugin_restoration_fails(self):
        runtime = MagicMock()
        runtime.execute_hook_with_runtime.return_value = [False]
        journal = MagicMock()

        assert not _restore_shortcut_state(
            runtime, ShortcutPluginContext({"game_id": "deltarune"}), {}, journal
        )
        journal.restore.assert_not_called()
        assert runtime.execute_hook_with_runtime.call_count == 1

    def test_shortcut_skips_after_restore_hook_when_journal_restore_fails(self):
        runtime = MagicMock()
        runtime.execute_hook_with_runtime.return_value = [True]
        journal = MagicMock()
        journal.restore.side_effect = OSError("restore failed")

        assert not _restore_shortcut_state(
            runtime, ShortcutPluginContext({"game_id": "deltarune"}), {}, journal
        )
        assert runtime.execute_hook_with_runtime.call_count == 1

    def test_execute_shortcut_plugin_hook_defaults_true_without_runtime(self):
        assert (
            execute_shortcut_plugin_hook(None, "before_mod_apply_shortcut", MagicMock())
            is True
        )


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
            patch(
                "controllers.shortcut_controller._write_shortcut_file"
            ) as write_shortcut,
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
            patch(
                "controllers.shortcut_controller._write_shortcut_file"
            ) as write_shortcut,
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
