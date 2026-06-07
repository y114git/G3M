import io
import json
import logging
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from adapters.g3mtool_adapter import G3MToolManager
from services.backup_service import BackupManager
from services.g3mtool_patching_service import (
    MOD_TYPE_CSX,
    MOD_TYPE_DATAFILE,
    MOD_TYPE_G3MPATCH,
    MOD_TYPE_OVERRIDES_ONLY,
    MOD_TYPE_XDELTA,
    G3MToolPatchingService,
)


class TestG3MToolAdapter:
    """Tests for patching and merging."""
    class _FakeProcess:
        def __init__(self, stdout="", stderr="") -> None:
            self.stdout = io.StringIO(stdout)
            self.stderr = io.StringIO(stderr)
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -1

    def test_adapter_initialization(self):
        """Checks that adaptering initialization."""
        g3mtool = G3MToolManager()
        assert g3mtool.platform in ("windows", "linux", "macos")

    def test_adapter_availability(self):
        """Checks that adaptering availability."""
        g3mtool = G3MToolManager()
        if g3mtool.g3mtool_path:
            assert os.path.exists(g3mtool.g3mtool_path)
            assert g3mtool.is_available()
        else:
            assert not g3mtool.is_available()

    def test_adapter_logs_found_executable_only_once_per_platform(self, monkeypatch):
        """Checks that repeated manager creation does not duplicate startup discovery logs."""
        monkeypatch.setattr(
            "adapters.g3mtool_adapter.resource_path",
            lambda relative_path: f"C:/bundle/{relative_path}",
        )
        monkeypatch.setattr("adapters.g3mtool_adapter.os.path.exists", lambda _path: True)
        info = Mock()
        monkeypatch.setattr("adapters.g3mtool_adapter.logging.info", info)
        G3MToolManager._cached_executable_paths = {}
        G3MToolManager._logged_executable_paths = set()

        first = G3MToolManager()
        second = G3MToolManager()

        assert first.g3mtool_path == second.g3mtool_path
        assert info.call_count == 1

    def test_cancel_active_processes(self):
        """Checks that canceling active processes."""
        g3mtool = G3MToolManager()
        g3mtool.cancel_active_processes()
        assert len(g3mtool._active_processes) == 0

    def test_parse_progress(self):
        """Checks that parsing progress."""
        assert G3MToolManager._parse_progress("Applying patch: 67%") == (
            67,
            "Applying patch",
        )
        assert G3MToolManager._parse_progress("not progress") is None

    def test_run_returns_stdout_stderr_and_progress(self, monkeypatch):
        """Checks that running returns stdout stderr and progress."""
        g3mtool = G3MToolManager()
        g3mtool.g3mtool_path = "g3mtool"
        progress = []
        monkeypatch.setattr("adapters.g3mtool_adapter.platform.system", lambda: "Linux")
        monkeypatch.setattr(
            "adapters.g3mtool_adapter.subprocess.Popen",
            lambda *_args, **_kwargs: self._FakeProcess(
                "Applying patch: 25%\nok\n", "warn\n"
            ),
        )

        result = g3mtool._run(
            ["g3mtool", "info", "target"],
            progress_callback=lambda percent, label: progress.append((percent, label)),
        )

        assert result == (0, "Applying patch: 25%\nok\n", "warn\n")
        assert progress == [(25, "Applying patch")]
        assert g3mtool._active_processes == []

    def test_run_parses_multiple_carriage_return_progress_updates(self, monkeypatch):
        """Checks that carriage-return progress updates are surfaced incrementally."""
        g3mtool = G3MToolManager()
        g3mtool.g3mtool_path = "g3mtool"
        progress = []
        monkeypatch.setattr("adapters.g3mtool_adapter.platform.system", lambda: "Linux")
        monkeypatch.setattr(
            "adapters.g3mtool_adapter.subprocess.Popen",
            lambda *_args, **_kwargs: self._FakeProcess(
                "Applying patch: 1%\rApplying patch: 2%\rApplying patch: 4%\r",
                "",
            ),
        )

        result = g3mtool._run(
            ["g3mtool", "info", "target"],
            progress_callback=lambda percent, label: progress.append((percent, label)),
        )

        assert result == (
            0,
            "Applying patch: 1%\rApplying patch: 2%\rApplying patch: 4%\r",
            "",
        )
        assert progress == [
            (1, "Applying patch"),
            (2, "Applying patch"),
            (4, "Applying patch"),
        ]

    def test_get_version_uses_version_flag(self, monkeypatch):
        """Checks that version lookup uses the exact CLI contract."""
        g3mtool = G3MToolManager()
        g3mtool.g3mtool_path = "g3mtool"
        calls = []
        monkeypatch.setattr(g3mtool, "_find_executable", lambda: "g3mtool")
        monkeypatch.setattr("adapters.g3mtool_adapter.platform.system", lambda: "Linux")
        monkeypatch.setattr(
            "adapters.g3mtool_adapter.subprocess.Popen",
            lambda cmd, **kwargs: calls.append(cmd) or self._FakeProcess("1.0.2\n"),
        )

        assert g3mtool.get_version() == "1.0.2"
        assert calls == [["g3mtool", "--version"]]

    def test_run_returns_localized_message_when_g3mtool_binary_missing(self, monkeypatch):
        from services.localization_service import tr

        g3mtool = G3MToolManager()
        g3mtool.g3mtool_path = "g3mtool"
        monkeypatch.setattr("adapters.g3mtool_adapter.platform.system", lambda: "Linux")
        monkeypatch.setattr(
            "adapters.g3mtool_adapter.subprocess.Popen",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                FileNotFoundError(2, "No such file or directory", "g3mtool")
            ),
        )

        result = g3mtool._run(["g3mtool", "info", "target"])

        assert result == (-1, "", tr("errors.g3mtool_command_not_found"))

    def test_unavailable_reason_reports_missing_custom_g3mtool_path(self, monkeypatch):
        from services.localization_service import tr

        g3mtool = G3MToolManager()
        monkeypatch.setattr(
            g3mtool,
            "_get_local_config",
            lambda: {"custom_g3mtool_path": "/tools/G3MTool.exe"},
        )
        monkeypatch.setattr("adapters.g3mtool_adapter.os.path.exists", lambda _path: False)

        assert (
            g3mtool.get_unavailable_reason()
            == tr("errors.custom_g3mtool_not_found", path="/tools/G3MTool.exe")
        )

    @pytest.mark.parametrize(
        ("caller", "expected_args"),
        [
            (
                lambda g3mtool: g3mtool.merge_patches(
                    "original.win",
                    ["a.g3mpatch", "b.g3mpatch"],
                    "out.win",
                    report_path="report.md",
                    log_path="g3mtool.log",
                    merge_code=True,
                    merge_properties=True,
                ),
                [
                    "g3mtool",
                    "patch",
                    "merge",
                    "original.win",
                    "a.g3mpatch",
                    "b.g3mpatch",
                    "--apply",
                    "out.win",
                    "--code",
                    "--properties",
                    "--report",
                    "report.md",
                    "--log",
                    "g3mtool.log",
                ],
            ),
            (
                lambda g3mtool: g3mtool.apply_patch(
                    "original.win", "patch.g3mpatch", "out.win", log_path="g3mtool.log"
                ),
                [
                    "g3mtool",
                    "patch",
                    "apply",
                    "original.win",
                    "patch.g3mpatch",
                    "out.win",
                    "--log",
                    "g3mtool.log",
                ],
            ),
            (
                lambda g3mtool: g3mtool.xpatch_apply("original.win", "patch.xdelta", "out.win"),
                ["g3mtool", "xpatch", "apply", "original.win", "patch.xdelta", "out.win"],
            ),
            (
                lambda g3mtool: g3mtool.xpatch_create("original.win", "modified.win", "out.xdelta"),
                ["g3mtool", "xpatch", "create", "original.win", "modified.win", "out.xdelta"],
            ),
            (
                lambda g3mtool: g3mtool.patch_create("original.win", "modified.win", "out.g3mpatch"),
                ["g3mtool", "patch", "create", "original.win", "modified.win", "out.g3mpatch"],
            ),
            (
                lambda g3mtool: g3mtool.validate_patch(
                    "patch.g3mpatch",
                    data_file="original.win",
                ),
                [
                    "g3mtool",
                    "patch",
                    "validate",
                    "patch.g3mpatch",
                    "--data",
                    "original.win",
                ],
            ),
            (
                lambda g3mtool: g3mtool.info("target.win", verbose=True),
                ["g3mtool", "info", "target.win", "--verbose"],
            ),
            (
                lambda g3mtool: g3mtool.diff("left.win", "right.win", "diff-out"),
                ["g3mtool", "diff", "left.win", "right.win", "diff-out"],
            ),
            (
                lambda g3mtool: g3mtool.execute(
                    "script.csx",
                    data_file="original.win",
                    output_path="out.win",
                ),
                [
                    "g3mtool",
                    "execute",
                    "script.csx",
                    "--data",
                    "original.win",
                    "--output",
                    "out.win",
                ],
            ),
        ],
    )
    def test_public_commands_forward_expected_contract(
        self, monkeypatch, tmp_path, caller, expected_args
    ):
        """Checks that public commands forward expected contract."""
        g3mtool = G3MToolManager()
        g3mtool.g3mtool_path = "g3mtool"
        run = Mock(return_value=(7, "stdout", "stderr"))
        monkeypatch.setattr(g3mtool, "_find_executable", lambda: "g3mtool")
        monkeypatch.setattr(g3mtool, "_run", run)
        monkeypatch.setattr(
            "adapters.g3mtool_adapter.get_g3mtool_cache_dir",
            lambda: str(tmp_path / "cache" / "G3MTool"),
        )

        assert caller(g3mtool) == (7, "stdout", "stderr")
        actual_cmd = run.call_args.args[0]
        expected_cmd = expected_args[:]
        if expected_args[1:3] in (
            ["patch", "merge"],
            ["patch", "apply"],
            ["patch", "create"],
            ["patch", "validate"],
        ) or expected_args[1] in ("info", "diff"):
            expected_cmd.extend(["--cache", str(tmp_path / "cache" / "G3MTool")])
        assert actual_cmd == expected_cmd

    def test_patch_create_with_xdelta_fallback_uses_flag(self, monkeypatch, tmp_path):
        """Checks that patch creation forwards the fallback flag exactly."""
        g3mtool = G3MToolManager()
        g3mtool.g3mtool_path = "g3mtool"
        calls = []
        monkeypatch.setattr(g3mtool, "_find_executable", lambda: "g3mtool")
        monkeypatch.setattr(
            "adapters.g3mtool_adapter.get_g3mtool_cache_dir",
            lambda: str(tmp_path / "cache" / "G3MTool"),
        )
        monkeypatch.setattr("adapters.g3mtool_adapter.platform.system", lambda: "Linux")
        monkeypatch.setattr(
            "adapters.g3mtool_adapter.subprocess.Popen",
            lambda cmd, **kwargs: calls.append(cmd) or self._FakeProcess(),
        )

        assert (
            g3mtool.patch_create(
                "original.win",
                "modified.win",
                "out.g3mpatch",
                include_xdelta_fallback=True,
            )
            == (0, "", "")
        )
        assert calls == [
            [
                "g3mtool",
                "patch",
                "create",
                "original.win",
                "modified.win",
                "out.g3mpatch",
                "--xdelta-fallback",
                "--cache",
                str(tmp_path / "cache" / "G3MTool"),
            ]
        ]

    def test_run_command_uses_custom_xdelta_path_from_app_state(
        self, monkeypatch, tmp_path
    ):
        """Checks that the configured xdelta binary is forwarded to G3MTool."""
        app_state = SimpleNamespace(
            local_config={"custom_xdelta_path": "/tools/xdelta-custom"}
        )
        g3mtool = G3MToolManager(app_state)
        g3mtool.g3mtool_path = "g3mtool"
        run = Mock(return_value=(0, "", ""))
        monkeypatch.setattr(g3mtool, "_find_executable", lambda: "g3mtool")
        monkeypatch.setattr(g3mtool, "_run", run)
        monkeypatch.setattr(
            "adapters.g3mtool_adapter.get_g3mtool_cache_dir",
            lambda: str(tmp_path / "cache" / "G3MTool"),
        )

        assert g3mtool.apply_patch("original.win", "patch.xdelta", "out.win") == (
            0,
            "",
            "",
        )
        assert run.call_args.args[0] == [
            "g3mtool",
            "patch",
            "apply",
            "original.win",
            "patch.xdelta",
            "out.win",
            "--cache",
            str(tmp_path / "cache" / "G3MTool"),
            "--xdelta-path",
            "/tools/xdelta-custom",
        ]

    def test_run_command_uses_custom_g3mtool_path_from_app_state(
        self, monkeypatch, tmp_path
    ):
        """Checks that the configured G3MTool binary replaces the bundled one."""
        app_state = SimpleNamespace(
            local_config={"custom_g3mtool_path": "/tools/G3MTool-custom"}
        )
        monkeypatch.setattr(
            "adapters.g3mtool_adapter.os.path.exists",
            lambda path: path == "/tools/G3MTool-custom",
        )
        g3mtool = G3MToolManager(app_state)
        run = Mock(return_value=(0, "", ""))
        monkeypatch.setattr(g3mtool, "_run", run)
        monkeypatch.setattr(
            "adapters.g3mtool_adapter.get_g3mtool_cache_dir",
            lambda: str(tmp_path / "cache" / "G3MTool"),
        )

        assert g3mtool.info("target.win") == (0, "", "")
        assert run.call_args.args[0] == [
            "/tools/G3MTool-custom",
            "info",
            "target.win",
            "--cache",
            str(tmp_path / "cache" / "G3MTool"),
        ]

    @pytest.mark.parametrize(
        "caller",
        [
            lambda g3mtool: g3mtool.merge_patches("original.win", ["a.g3mpatch"], "out.win"),
            lambda g3mtool: g3mtool.apply_patch("original.win", "patch.g3mpatch", "out.win"),
            lambda g3mtool: g3mtool.xpatch_apply("original.win", "patch.xdelta", "out.win"),
            lambda g3mtool: g3mtool.xpatch_create("original.win", "modified.win", "out.xdelta"),
            lambda g3mtool: g3mtool.patch_create("original.win", "modified.win", "out.g3mpatch"),
            lambda g3mtool: g3mtool.validate_patch("patch.g3mpatch", "original.win"),
            lambda g3mtool: g3mtool.execute(
                "script.csx",
                data_file="original.win",
                output_path="out.win",
            ),
            lambda g3mtool: g3mtool.info("target.win"),
            lambda g3mtool: g3mtool.diff("left.win", "right.win"),
        ],
    )
    def test_public_commands_share_unavailable_contract(self, caller):
        """Checks that public commands share unavailable contract."""
        from services.localization_service import tr

        g3mtool = G3MToolManager()
        g3mtool.g3mtool_path = None
        g3mtool._find_executable = lambda: None

        assert caller(g3mtool) == (-1, "", tr("errors.g3mtool_not_available"))


class TestModClassification:
    """Tests for patching and merging."""
    def test_classify_g3mpatch(self, tmp_path):
        """Checks that classifying g3mpatch."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "patch.g3mpatch").write_bytes(b"fake")
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_G3MPATCH
        assert patch_file.endswith(".g3mpatch")

    def test_classify_xdelta(self, tmp_path):
        """Checks that classifying xdelta."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "data.xdelta").write_bytes(b"fake")
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_XDELTA
        assert patch_file.endswith(".xdelta")

    def test_classify_vcdiff(self, tmp_path):
        """Checks that classifying vcdiff."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "data.vcdiff").write_bytes(b"fake")
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_XDELTA
        assert patch_file.endswith(".vcdiff")

    def test_classify_datafile(self, tmp_path):
        """Checks that classifying datafile."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "data.win").write_bytes(b"FORM" + b"\x00" * 100)
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_DATAFILE
        assert patch_file.endswith("data.win")

    def test_collect_mod_infos_uses_configured_root_data_file_for_menu_chapter(
        self, tmp_path
    ):
        """Checks that root-level configured menu data files are not skipped."""
        mod_dir = tmp_path / "sigma"
        mod_dir.mkdir()
        data_file = mod_dir / "BOSSRUSH.win"
        data_file.write_text("patched", encoding="utf-8")
        (mod_dir / "mod_config.json").write_text(
            json.dumps(
                {
                    "id": "sigma",
                    "name": "sigma",
                    "author": "Local author",
                    "version": "1.0.0",
                    "game": "deltarune",
                    "files": {
                        "deltarune_0": {
                            "data_file_path": "BOSSRUSH.win",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        app_state = Mock()
        app_state.local_config = {}
        app_state.mods_dir = str(tmp_path)
        mod_service = Mock()
        mod_service.get_mod_folder_path.return_value = str(mod_dir)
        patcher = G3MToolPatchingService(app_state, mod_service)
        mod_data = SimpleNamespace(
            id="sigma",
            name="sigma",
            game="deltarune",
            get_chapter_data=lambda chapter_id: SimpleNamespace(
                data_file_path="BOSSRUSH.win" if chapter_id == "deltarune_0" else None
            ),
        )

        mod_infos = patcher._collect_mod_infos([mod_data], "deltarune_0")

        assert mod_infos == [(str(data_file), MOD_TYPE_DATAFILE, str(mod_dir))]

    def test_get_mod_source_dir_uses_configured_root_files_when_chapter_folder_missing(
        self, tmp_path
    ):
        """Checks that root overrides still resolve to the mod root without chapter_0 folder."""
        mod_dir = tmp_path / "cozy_root"
        mod_dir.mkdir()
        (mod_dir / "data.g3mpatch").write_bytes(b"patch")
        (mod_dir / "ru_data.json").write_text("{}", encoding="utf-8")
        (mod_dir / "mod_config.json").write_text(
            json.dumps(
                {
                    "id": "cozy_root",
                    "name": "cozy_root",
                    "author": "Local author",
                    "version": "1.0.0",
                    "game": "deltarune",
                    "files": {
                        "deltarune_0": {
                            "data_file_path": "data.g3mpatch",
                            "extra_files": ["ru_data.json"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        app_state = Mock()
        app_state.local_config = {}
        app_state.mods_dir = str(tmp_path)
        mod_service = Mock()
        mod_service.get_mod_folder_path.return_value = str(mod_dir)
        patcher = G3MToolPatchingService(app_state, mod_service)
        mod_data = SimpleNamespace(id="cozy_root", name="cozy_root", game="deltarune")

        assert patcher._get_mod_source_dir(mod_data, "deltarune_0") == str(mod_dir)

    def test_get_mod_source_dir_uses_configured_chapter_directory_without_legacy_name(
        self, tmp_path
    ):
        """Checks that chapter3/ chapter4 style folders still resolve for overrides."""
        mod_dir = tmp_path / "cozy_ch3"
        chapter_dir = mod_dir / "chapter3" / "lang"
        chapter_dir.mkdir(parents=True)
        (mod_dir / "chapter3" / "data.g3mpatch").write_bytes(b"patch")
        (chapter_dir / "lang_en.json").write_text("{}", encoding="utf-8")
        (mod_dir / "mod_config.json").write_text(
            json.dumps(
                {
                    "id": "cozy_ch3",
                    "name": "cozy_ch3",
                    "author": "Local author",
                    "version": "1.0.0",
                    "game": "deltarune",
                    "files": {
                        "deltarune_3": {
                            "data_file_path": "chapter3/data.g3mpatch",
                            "extra_files": ["chapter3/lang/lang_en.json"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        app_state = Mock()
        app_state.local_config = {}
        app_state.mods_dir = str(tmp_path)
        mod_service = Mock()
        mod_service.get_mod_folder_path.return_value = str(mod_dir)
        patcher = G3MToolPatchingService(app_state, mod_service)
        mod_data = SimpleNamespace(id="cozy_ch3", name="cozy_ch3", game="deltarune")

        assert patcher._get_mod_source_dir(mod_data, "deltarune_3") == str(
            mod_dir / "chapter3"
        )

    def test_classify_csx(self, tmp_path):
        """Checks that classifying csx scripts."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "patch.csx").write_text("// fake", encoding="utf-8")
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_CSX
        assert patch_file.endswith(".csx")

    def test_classify_overrides_only(self, tmp_path):
        """Checks that classifying overrides only."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "sound.ogg").write_bytes(b"fake")
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_OVERRIDES_ONLY
        assert patch_file is None

    def test_classify_g3mpatch_priority_over_xdelta(self, tmp_path):
        """Checks that classifying g3mpatch priority over xdelta."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "patch.g3mpatch").write_bytes(b"fake")
        (mod_dir / "data.xdelta").write_bytes(b"fake")
        patcher = G3MToolPatchingService(Mock(), Mock())
        _patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_G3MPATCH

    def test_classify_plain_zip_is_not_g3mpatch(self, tmp_path):
        """Checks that classifying plain zip is not g3mpatch."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "random.zip").write_bytes(b"fake")
        patcher = G3MToolPatchingService(Mock(), Mock())
        _patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_OVERRIDES_ONLY

    def test_classify_g3mpatch_zip(self, tmp_path):
        """Checks that classifying g3mpatch zip."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        patch_zip = mod_dir / "patch.zip"
        with zipfile.ZipFile(patch_zip, "w") as zf:
            zf.writestr("g3mpatch.json", json.dumps({"original": {"md5": "abc"}}))
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_G3MPATCH
        assert patch_file.endswith(".zip")

    def test_classify_empty_dir(self, tmp_path):
        """Checks that classifying empty dir."""
        mod_dir = tmp_path / "empty"
        mod_dir.mkdir()
        patcher = G3MToolPatchingService(Mock(), Mock())
        _patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_OVERRIDES_ONLY

    def test_classify_nonexistent(self, tmp_path):
        """Checks that classifying nonexistent."""
        patcher = G3MToolPatchingService(Mock(), Mock())
        _patch_file, mod_type = patcher._classify_mod(str(tmp_path / "nope"))
        assert mod_type == MOD_TYPE_OVERRIDES_ONLY


class TestServiceInitialization:
    """Tests for patching and merging."""
    def test_service_has_g3mtool(self):
        """Checks that serviceing has g3mtool."""
        patcher = G3MToolPatchingService(Mock(), Mock())
        assert hasattr(patcher, "g3mtool")
        assert isinstance(patcher.g3mtool, G3MToolManager)

    def test_service_has_patching_logger(self):
        """Checks that serviceing has patching logger."""
        patcher = G3MToolPatchingService(Mock(), Mock())
        assert patcher.patching_logger is not None
        assert patcher.patching_logger.name == "patching"

    def test_cleanup_processes_method_exists(self):
        """Checks that cleanuping processes method exists."""
        patcher = G3MToolPatchingService(Mock(), Mock())
        assert hasattr(patcher, "cleanup_processes_and_temp_files")
        patcher.cleanup_processes_and_temp_files()

    def test_cancel(self):
        """Checks that canceling works."""
        patcher = G3MToolPatchingService(Mock(), Mock())
        patcher.cancel()
        assert patcher._cancelled is True

    def test_warning_handler_can_abort(self):
        """Checks that warning handler can abort."""
        app_state = Mock()
        app_state.local_config = {}
        patcher = G3MToolPatchingService(app_state, Mock())
        patcher.warning_handler = Mock(return_value=False)

        assert patcher._request_warning("warning text") is False
        patcher.warning_handler.assert_called_once()

    def test_skip_patching_warnings_bypasses_handler(self):
        """Checks that skipping patching warnings bypasses handler."""
        app_state = Mock()
        app_state.local_config = {"skip_patching_warnings": True}
        patcher = G3MToolPatchingService(app_state, Mock())
        patcher.warning_handler = Mock(return_value=False)

        assert patcher._request_warning("warning text") is True
        patcher.warning_handler.assert_not_called()

    def test_g3mpatch_newer_tool_version_warning_can_abort(self):
        """Checks that newer G3MTool patches can be rejected by the user."""
        app_state = Mock()
        app_state.local_config = {}
        patcher = G3MToolPatchingService(app_state, Mock())
        patcher.g3mtool.get_version = Mock(return_value="1.0.2")
        patcher.warning_handler = Mock(return_value=False)

        result = patcher._check_g3mpatch_tool_version_warning(
            "newer_patch.g3mpatch",
            {"tool": {"name": "G3MTool", "version": "1.0.3"}},
        )

        assert result is False
        patcher.warning_handler.assert_called_once()

    def test_g3mpatch_equal_tool_version_with_extra_zero_does_not_warn(self):
        """Checks that equivalent version strings do not create false warnings."""
        app_state = Mock()
        app_state.local_config = {}
        patcher = G3MToolPatchingService(app_state, Mock())
        patcher.g3mtool.get_version = Mock(return_value="1.0.2")
        patcher.warning_handler = Mock(return_value=False)

        result = patcher._check_g3mpatch_tool_version_warning(
            "same_patch.g3mpatch",
            {"tool": {"name": "G3MTool", "version": "1.0.2.0"}},
        )

        assert result is True
        patcher.warning_handler.assert_not_called()

    def test_g3mpatch_missing_tool_version_is_allowed(self):
        """Checks that old manifests without tool version remain compatible."""
        app_state = Mock()
        app_state.local_config = {}
        patcher = G3MToolPatchingService(app_state, Mock())
        patcher.g3mtool.get_version = Mock(return_value="1.0.2")
        patcher.warning_handler = Mock(return_value=False)

        result = patcher._check_g3mpatch_tool_version_warning(
            "legacy_patch.g3mpatch",
            {},
        )

        assert result is True
        patcher.warning_handler.assert_not_called()


class TestBackupFlow:
    """Tests for patching and merging."""
    def test_backup_and_restore(self, tmp_path):
        """Checks that backup and restore."""
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        bm = BackupManager(str(backup_dir), patching_logger=logging.getLogger("test"))
        chapter_id = "deltarune_1"
        test_file = tmp_path / "data.win"
        test_file.write_bytes(b"ORIGINAL_CONTENT")
        bm.backup_file(chapter_id, str(test_file))
        assert chapter_id in bm.original_files
        assert str(test_file) in bm.original_files[chapter_id]
        backup_path = bm.original_files[chapter_id][str(test_file)]
        assert os.path.exists(backup_path)
        test_file.write_bytes(b"MODIFIED_CONTENT")
        bm.restore_backups(chapter_id)
        assert test_file.read_bytes() == b"ORIGINAL_CONTENT"

    def test_backup_manifest_tracking(self, tmp_path):
        """Checks that backup manifest tracking."""
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        bm = BackupManager(str(backup_dir), patching_logger=logging.getLogger("test"))
        chapter_id = "deltarune_1"
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")
        bm.backup_file(chapter_id, str(test_file))
        manifest_path = str(tmp_path / "manifest.json")
        bm.save_backups_to_manifest(manifest_path)
        with open(manifest_path) as f:
            manifest_data = json.load(f)
        assert "modification_order" in manifest_data
        assert chapter_id in manifest_data["modification_order"]
        assert str(test_file) in manifest_data["modification_order"][chapter_id]

    def test_multi_chapter_backup_restore(self, tmp_path):
        """Checks that multiing chapter backup restore."""
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        bm = BackupManager(str(backup_dir), patching_logger=logging.getLogger("test"))
        files = {}
        for ch in ["deltarune_1", "deltarune_2"]:
            f = tmp_path / f"{ch}_data.win"
            f.write_bytes(f"ORIGINAL_{ch}".encode())
            files[ch] = f
            bm.backup_file(ch, str(f))
        for _ch, f in files.items():
            f.write_bytes(b"MODIFIED")
        bm.restore_all_backups()
        for ch, f in files.items():
            assert f.read_bytes() == f"ORIGINAL_{ch}".encode()


class TestReportParsing:
    """Tests for patching and merging."""
    def test_no_report(self):
        """Checks that noing report."""
        patcher = G3MToolPatchingService(Mock(), Mock())
        assert patcher.get_report_path() is None
        assert patcher.report_has_conflicts() is False
        assert patcher.get_report_stats() == (0, 0)

    def test_report_with_conflicts(self, tmp_path):
        """Checks that reporting with conflicts."""
        report = tmp_path / "report.md"
        report.write_text("## Merge Report\n\nTotal conflicts: 3\nAuto-resolved: 1\n")
        patcher = G3MToolPatchingService(Mock(), Mock())
        patcher._last_report_path = str(report)
        assert patcher.report_has_conflicts() is True
        total, auto = patcher.get_report_stats()
        assert total == 3
        assert auto == 1

    def test_report_without_conflicts(self, tmp_path):
        """Checks that reporting without conflicts."""
        report = tmp_path / "report.md"
        report.write_text("## Merge Report\n\nAll patches applied cleanly.\n")
        patcher = G3MToolPatchingService(Mock(), Mock())
        patcher._last_report_path = str(report)
        assert patcher.report_has_conflicts() is False

    def test_persist_conflict_artifacts_writes_logs_without_markdown_in_logs(
        self, tmp_path
    ):
        """Checks that conflict artifacts create only log files in log folders."""
        report = tmp_path / "report.md"
        report.write_text("## Merge Report\n\nTotal conflicts: 2\n", encoding="utf-8")
        patcher = G3MToolPatchingService(Mock(), Mock())

        with patch(
            "services.g3mtool_patching_service.get_user_data_root",
            return_value=str(tmp_path),
        ):
            saved_path = patcher._persist_conflict_artifacts(
                str(report), "deltarune_1"
            )

        conflicts_log = tmp_path / "logs" / "conflicts.log"
        archived_conflicts = list((tmp_path / "logs" / "patching").glob("conflicts_*.log"))
        archived_reports = list((tmp_path / "logs" / "patching").glob("*.md"))

        assert saved_path is not None
        assert saved_path.endswith(".md")
        assert Path(saved_path).exists()
        assert conflicts_log.read_text(encoding="utf-8") == report.read_text(
            encoding="utf-8"
        )
        assert len(archived_conflicts) == 1
        assert archived_reports == []


class TestXdeltaPatchApplication:
    """Tests for patching and merging."""
    def test_xdelta_missing_output_uses_warning_fallback(self, tmp_path):
        """Checks that xdelta missing output uses warning fallback."""
        app_state = Mock()
        app_state.local_config = {}
        patcher = G3MToolPatchingService(app_state, Mock())
        data_win_path = tmp_path / "data.win"
        patch_file = tmp_path / "chapter4.xdelta"
        output_path = tmp_path / "patched_data.win"
        data_win_path.write_bytes(b"ORIGINAL")
        patch_file.write_bytes(b"PATCH")
        patcher.g3mtool.xpatch_apply = Mock(return_value=(0, "", ""))
        patcher.warning_handler = Mock(return_value=True)

        result = patcher._apply_single_mod(
            str(data_win_path),
            (str(patch_file), MOD_TYPE_XDELTA, str(tmp_path)),
            str(output_path),
            str(tmp_path / "g3mtool.log"),
            0,
            100,
            "Chapter 4",
        )

        assert result is True
        assert output_path.read_bytes() == b"ORIGINAL"
        patcher.warning_handler.assert_called_once()


class TestCsxPatchApplication:
    """Tests for csx patch execution."""

    def test_csx_patch_uses_execute_with_data_file(self, tmp_path):
        """Checks that csx execution writes a patched output file."""
        app_state = Mock()
        app_state.local_config = {}
        patcher = G3MToolPatchingService(app_state, Mock())
        data_win_path = tmp_path / "data.win"
        patch_file = tmp_path / "chapter4.csx"
        output_path = tmp_path / "patched_data.win"
        data_win_path.write_bytes(b"ORIGINAL")
        patch_file.write_text("// script", encoding="utf-8")

        def _execute(target, args=None, data_file=None, output_path=None, input_path=None):
            assert target == str(patch_file)
            assert data_file == str(data_win_path)
            assert output_path == str(output_path_arg)
            Path(output_path).write_bytes(b"PATCHED")
            return (0, "", "")

        output_path_arg = output_path
        patcher.g3mtool.execute = Mock(side_effect=_execute)

        result = patcher._apply_single_mod(
            str(data_win_path),
            (str(patch_file), MOD_TYPE_CSX, str(tmp_path)),
            str(output_path),
            str(tmp_path / "g3mtool.log"),
            0,
            100,
            "Chapter 4",
        )

        assert result is True
        assert output_path.read_bytes() == b"PATCHED"
        patcher.g3mtool.execute.assert_called_once()

    def test_csx_missing_output_uses_warning_fallback(self, tmp_path):
        """Checks that csx missing output uses warning fallback."""
        app_state = Mock()
        app_state.local_config = {}
        patcher = G3MToolPatchingService(app_state, Mock())
        data_win_path = tmp_path / "data.win"
        patch_file = tmp_path / "chapter4.csx"
        output_path = tmp_path / "patched_data.win"
        data_win_path.write_bytes(b"ORIGINAL")
        patch_file.write_text("// script", encoding="utf-8")
        patcher.g3mtool.execute = Mock(return_value=(0, "", ""))
        patcher.warning_handler = Mock(return_value=True)

        result = patcher._apply_single_mod(
            str(data_win_path),
            (str(patch_file), MOD_TYPE_CSX, str(tmp_path)),
            str(output_path),
            str(tmp_path / "g3mtool.log"),
            0,
            100,
            "Chapter 4",
        )

        assert result is True
        assert output_path.read_bytes() == b"ORIGINAL"
        patcher.warning_handler.assert_called_once()


class TestFileOverrideProgress:
    """Tests for patching and merging."""
    def test_apply_file_overrides_uses_only_configured_root_entries(self, tmp_path):
        """Checks that config-driven root overrides do not copy unrelated chapter folders."""
        from utils.patching.file_override_utils import apply_file_overrides

        mod_dir = tmp_path / "mod"
        target_dir = tmp_path / "target"
        mod_dir.mkdir()
        target_dir.mkdir()
        (mod_dir / "ru_data.json").write_text("{}", encoding="utf-8")
        (mod_dir / "chapter3").mkdir()
        (mod_dir / "chapter3" / "lang_en.json").write_text("broken", encoding="utf-8")

        patcher = Mock()
        patcher.xdelta_modpack = False
        patcher._backup_or_mark_file = Mock()
        patcher._request_warning = Mock(return_value=True)
        patcher.patching_logger = Mock()

        result = apply_file_overrides(
            patcher,
            str(mod_dir),
            str(target_dir),
            set(),
            False,
            chapter_id="deltarune_0",
            mod_name="Test Mod",
            game_id="deltarune",
            configured_paths=["ru_data.json"],
            mod_root_dir=str(mod_dir),
        )

        assert result is True
        assert (target_dir / "ru_data.json").read_text(encoding="utf-8") == "{}"
        assert not (target_dir / "chapter3").exists()

    def test_apply_file_overrides_strips_chapter_prefix_for_configured_entries(
        self, tmp_path
    ):
        """Checks that chapter-prefixed extra_files land inside the target chapter root."""
        from utils.patching.file_override_utils import apply_file_overrides

        mod_dir = tmp_path / "mod"
        target_dir = tmp_path / "target"
        (mod_dir / "chapter3" / "lang").mkdir(parents=True)
        (mod_dir / "chapter3" / "lang" / "lang_en.json").write_text(
            "hello", encoding="utf-8"
        )
        target_dir.mkdir()

        patcher = Mock()
        patcher.xdelta_modpack = False
        patcher._backup_or_mark_file = Mock()
        patcher._request_warning = Mock(return_value=True)
        patcher.patching_logger = Mock()

        result = apply_file_overrides(
            patcher,
            str(mod_dir / "chapter3"),
            str(target_dir),
            set(),
            False,
            chapter_id="deltarune_3",
            mod_name="Test Mod",
            game_id="deltarune",
            configured_paths=["chapter3/lang/"],
            mod_root_dir=str(mod_dir),
        )

        assert result is True
        assert (target_dir / "lang" / "lang_en.json").read_text(encoding="utf-8") == "hello"
        assert not (target_dir / "chapter3").exists()

    def test_apply_file_overrides_copies_configured_extra_data_files(self, tmp_path):
        """Checks that explicit extra .win files are copied instead of skipped."""
        from utils.patching.file_override_utils import apply_file_overrides

        mod_dir = tmp_path / "mod"
        target_dir = tmp_path / "target"
        (mod_dir / "chapter_1").mkdir(parents=True)
        (mod_dir / "chapter_1" / "data_30tbps.win").write_text(
            "patched data", encoding="utf-8"
        )
        target_dir.mkdir()

        patcher = Mock()
        patcher.xdelta_modpack = False
        patcher._backup_or_mark_file = Mock()
        patcher._request_warning = Mock(return_value=True)
        patcher.patching_logger = Mock()

        result = apply_file_overrides(
            patcher,
            str(mod_dir / "chapter_1"),
            str(target_dir),
            set(),
            False,
            chapter_id="deltarune_1",
            mod_name="Test Mod",
            game_id="deltarune",
            configured_paths=["chapter_1/data_30tbps.win"],
            mod_root_dir=str(mod_dir),
        )

        assert result is True
        assert (target_dir / "data_30tbps.win").read_text(encoding="utf-8") == "patched data"

    def test_apply_file_overrides_skips_legacy_walk_when_config_has_no_extra_files(
        self, tmp_path
    ):
        """Checks that config-driven chapters with no extra_files do not copy stray files."""
        from utils.patching.file_override_utils import apply_file_overrides

        mod_dir = tmp_path / "mod"
        target_dir = tmp_path / "target"
        mod_dir.mkdir()
        target_dir.mkdir()
        (mod_dir / "readme.txt").write_text("hello", encoding="utf-8")

        patcher = Mock()
        patcher.xdelta_modpack = False
        patcher._backup_or_mark_file = Mock()
        patcher._request_warning = Mock(return_value=True)
        patcher.patching_logger = Mock()

        result = apply_file_overrides(
            patcher,
            str(mod_dir),
            str(target_dir),
            set(),
            False,
            chapter_id="deltarune_4",
            mod_name="Test Mod",
            game_id="deltarune",
            configured_paths=[],
            mod_root_dir=str(mod_dir),
        )

        assert result is True
        assert not (target_dir / "readme.txt").exists()

    def test_apply_file_overrides_reports_incremental_progress(self, tmp_path):
        """Checks that applying file overrides reports incremental progress."""
        from utils.patching.file_override_utils import apply_file_overrides

        mod_dir = tmp_path / "mod"
        target_dir = tmp_path / "target"
        mod_dir.mkdir()
        target_dir.mkdir()
        (mod_dir / "readme.txt").write_text("hello", encoding="utf-8")
        (mod_dir / "notes.md").write_text("world", encoding="utf-8")
        patcher = Mock()
        patcher.xdelta_modpack = False
        patcher._backup_or_mark_file = Mock()
        patcher._request_warning = Mock(return_value=True)
        patcher.patching_logger = Mock()
        progress_updates = []

        result = apply_file_overrides(
            patcher,
            str(mod_dir),
            str(target_dir),
            set(),
            False,
            progress_callback=lambda fraction, message: progress_updates.append(
                (fraction, message)
            ),
            mod_name="Test Mod",
        )

        assert result is True
        assert len(progress_updates) >= 2
        assert progress_updates[-1][0] == 1

    def test_xdelta_without_matching_target_warns_and_continues(self, tmp_path):
        """Checks that unmatched extra xdelta patches warn but can be skipped."""
        from utils.patching.file_override_utils import apply_file_overrides

        mod_dir = tmp_path / "mod"
        target_dir = tmp_path / "target"
        mod_dir.mkdir()
        target_dir.mkdir()
        (mod_dir / "chapter1.xdelta").write_bytes(b"fake")
        patcher = Mock()
        patcher.xdelta_modpack = False
        patcher._request_warning = Mock(return_value=True)
        patcher.patching_logger = Mock()

        result = apply_file_overrides(
            patcher, str(mod_dir), str(target_dir), set(), False
        )

        assert result is True
        patcher._request_warning.assert_called_once()
        assert patcher._request_warning.call_args.kwargs["warning_id"] == (
            "extra_xdelta_no_target"
        )


class TestG3MPatchProgressText:
    """Tests for patching and merging."""
    def test_multi_patch_progress_uses_generic_patching_text(
        self, monkeypatch, tmp_path
    ):
        """Checks that multiing patch progress uses generic patching text."""
        app_state = Mock()
        app_state.local_config = {}
        patcher = G3MToolPatchingService(app_state, Mock())
        patcher._temp_dir = str(tmp_path)
        patcher._continue_without_data_patch = Mock(return_value=False)
        patcher.report_has_conflicts = Mock(return_value=False)
        progress_messages = []

        monkeypatch.setattr(
            "services.g3mtool_patching_service.tr",
            lambda key, **kwargs: f"{key}|{kwargs}",
        )
        patcher._emit_chapter_progress = Mock(
            side_effect=lambda start, end, fraction, message: progress_messages.append(
                message
            )
        )
        patcher.g3mtool.merge_patches = Mock(
            side_effect=lambda *args, **kwargs: (
                kwargs["progress_callback"](50, "merge"),
                tmp_path.joinpath("out.win").write_text("patched", encoding="utf-8"),
                (0, "", ""),
            )[-1]
        )

        assert patcher._apply_multi_mod(
            str(tmp_path / "data.win"),
            [
                ("a.g3mpatch", MOD_TYPE_G3MPATCH, "a"),
                ("b.g3mpatch", MOD_TYPE_G3MPATCH, "b"),
            ],
            str(tmp_path / "out.win"),
            str(tmp_path / "g3mtool.log"),
            "chapter1",
            0,
            100,
            "Chapter 1",
        )
        assert any(
            "status.patching_chapter" in message for message in progress_messages
        )
        assert all(
            "status.merging_patches" not in message for message in progress_messages
        )

    def test_multi_patch_passes_raw_inputs_directly_to_merge(self, tmp_path):
        """Checks that multi merge forwards xdelta/datafile inputs directly to G3MTool."""
        app_state = Mock()
        app_state.local_config = {}
        patcher = G3MToolPatchingService(app_state, Mock())
        patcher._temp_dir = str(tmp_path)
        patcher.report_has_conflicts = Mock(return_value=False)
        patcher.status_update = Mock()

        original = tmp_path / "data.win"
        original.write_text("original", encoding="utf-8")
        replacement = tmp_path / "replacement.win"
        replacement.write_text("replacement", encoding="utf-8")
        out = tmp_path / "out.win"

        captured = {}

        def fake_merge_patches(_original, patches, output, **_kwargs):
            captured["patches"] = list(patches)
            Path(output).write_text("merged", encoding="utf-8")
            return (0, "", "")

        patcher.g3mtool.merge_patches = Mock(side_effect=fake_merge_patches)

        assert patcher._apply_multi_mod(
            str(original),
            [
                ("raw_patch.xdelta", MOD_TYPE_XDELTA, "x"),
                (str(replacement), MOD_TYPE_DATAFILE, "y"),
                ("already.g3mpatch", MOD_TYPE_G3MPATCH, "z"),
            ],
            str(out),
            str(tmp_path / "g3mtool.log"),
            "chapter1",
            0,
            100,
            "Chapter 1",
        )

        assert out.read_text(encoding="utf-8") == "merged"
        assert len(captured["patches"]) == 3
        assert captured["patches"][0] == "raw_patch.xdelta"
        assert captured["patches"][1] == str(replacement)
        assert captured["patches"][2] == "already.g3mpatch"
        assert not getattr(patcher.g3mtool.xpatch_apply, "called", False)
        assert not getattr(patcher.g3mtool.patch_create, "called", False)

    def test_multi_patch_direct_merge_reports_progress(self, tmp_path):
        """Checks that direct merge progress advances chapter progress across the merge window."""
        app_state = Mock()
        app_state.local_config = {}
        patcher = G3MToolPatchingService(app_state, Mock())
        patcher._temp_dir = str(tmp_path)
        patcher.report_has_conflicts = Mock(return_value=False)
        patcher.status_update = Mock()
        progress_fractions = []

        original = tmp_path / "data.win"
        original.write_text("original", encoding="utf-8")
        replacement = tmp_path / "replacement.win"
        replacement.write_text("replacement", encoding="utf-8")
        out = tmp_path / "out.win"

        def fake_merge_patches(_original, _patches, output, **kwargs):
            kwargs["progress_callback"](10, "merge")
            kwargs["progress_callback"](50, "merge")
            kwargs["progress_callback"](100, "merge")
            Path(output).write_text("merged", encoding="utf-8")
            return (0, "", "")

        patcher.g3mtool.merge_patches = Mock(side_effect=fake_merge_patches)
        patcher._emit_chapter_progress = Mock(
            side_effect=lambda _start, _end, fraction, _message: progress_fractions.append(
                round(fraction, 4)
            )
        )

        assert patcher._apply_multi_mod(
            str(original),
            [
                ("raw_patch.xdelta", MOD_TYPE_XDELTA, "x"),
                (str(replacement), MOD_TYPE_DATAFILE, "y"),
            ],
            str(out),
            str(tmp_path / "g3mtool.log"),
            "chapter1",
            0,
            100,
            "Chapter 1",
        )

        assert out.read_text(encoding="utf-8") == "merged"
        assert any(0.20 < fraction < 0.35 for fraction in progress_fractions)
        assert any(0.45 < fraction < 0.60 for fraction in progress_fractions)
        assert any(0.70 <= fraction <= 0.72 for fraction in progress_fractions)

    def test_patch_chapter_excludes_override_only_mods_from_merge_but_applies_them(
        self, monkeypatch, tmp_path
    ):
        """Checks that override-only mods are skipped for merge and still applied as file overrides."""
        app_state = Mock()
        app_state.local_config = {}
        app_state.game_mode = SimpleNamespace(game_id="pizzatower")
        patcher = G3MToolPatchingService(app_state, Mock())
        patcher._temp_dir = str(tmp_path)
        patcher.backup_service = Mock()
        patcher.backup_service.backup_file.return_value = True
        patcher._emit_chapter_progress = Mock()
        patcher._check_g3mpatch_validate_warning = Mock(return_value=True)

        target_dir = tmp_path / "Pizza Tower"
        target_dir.mkdir()
        data_win = target_dir / "data.win"
        data_win.write_text("original", encoding="utf-8")

        captured = {"merged": None, "overrides": []}

        monkeypatch.setattr(
            "services.g3mtool_patching_service.get_target_dir",
            lambda *_args, **_kwargs: str(target_dir),
        )
        monkeypatch.setattr(
            "services.g3mtool_patching_service.mod_content.find_data_win",
            lambda *_args, **_kwargs: str(data_win),
        )
        monkeypatch.setattr(
            "services.g3mtool_patching_service.shutil.move",
            lambda src, dst: Path(dst).write_text(
                Path(src).read_text(encoding="utf-8"), encoding="utf-8"
            ),
        )

        patcher._collect_mod_infos = Mock(
            return_value=[
                ("mod_a.g3mpatch", MOD_TYPE_G3MPATCH, "mod_a_dir"),
                (None, MOD_TYPE_OVERRIDES_ONLY, "override_dir"),
                ("mod_b.xdelta", MOD_TYPE_XDELTA, "mod_b_dir"),
            ]
        )

        def fake_apply_multi_mod(
            _data_win_path,
            mod_infos,
            output_path,
            *_args,
            **_kwargs,
        ):
            captured["merged"] = list(mod_infos)
            Path(output_path).write_text("patched", encoding="utf-8")
            return True

        def fake_apply_file_overrides(
            mod_source_dir,
            *_args,
            **_kwargs,
        ):
            captured["overrides"].append(mod_source_dir)
            return True

        patcher._apply_multi_mod = Mock(side_effect=fake_apply_multi_mod)
        patcher._apply_file_overrides = Mock(side_effect=fake_apply_file_overrides)
        patcher._get_mod_source_dir = Mock(
            side_effect=lambda mod_data, _chapter_id: f"{mod_data}_dir"
        )

        assert patcher._patch_chapter(
            "pizzatower",
            ["mod_a", "override_only", "mod_b"],
            is_modpack=False,
            modpack_dir=None,
            chapter_start=0,
            chapter_end=100,
            display_name="Pizza Tower",
            chapter_index=1,
            total_chapters=1,
        )

        assert captured["merged"] == [
            ("mod_a.g3mpatch", MOD_TYPE_G3MPATCH, "mod_a_dir"),
            ("mod_b.xdelta", MOD_TYPE_XDELTA, "mod_b_dir"),
        ]
        assert captured["overrides"] == [
            "mod_a_dir",
            "override_only_dir",
            "mod_b_dir",
        ]
