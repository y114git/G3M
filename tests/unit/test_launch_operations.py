"""Tests for selecting and recovering the operation launch path."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6.QtCore import QObject

from models.launch_modes import LaunchMode
from services.launch_service import GameLauncher
from services.mod_operation_executor import ModOperationExecutor
from utils.mod.operation_plan import ModPathContext, build_mod_operation_plan


class _GameMode:
    game_id = "deltarune"

    def __init__(self, game_path, data_path=None) -> None:
        self._game_path = str(game_path)
        self._data_path = str(data_path) if data_path else ""

    def get_game_path(self, _config):
        return self._game_path

    def get_data_path(self, _config):
        return self._data_path


class _ModService:
    def __init__(self, config, folder) -> None:
        self._config = config
        self._folder = str(folder)

    def get_mod_config(self, _mod_id):
        return self._config.copy()

    def get_mod_folder_path(self, _mod_id):
        return self._folder


def _config(files):
    return {
        "config_version": "2.0.0",
        "id": "mod",
        "name": "Mod",
        "version": "1.0.0",
        "authors": [],
        "game": "deltarune",
        "files": files,
    }


def _app_state(tmp_path, game_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return SimpleNamespace(
        config_dir=str(config_dir),
        local_config={},
        game_mode=_GameMode(game_path),
    )


def test_launch_builds_one_ordered_operation_plan_from_profile_steps(qapp, tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    (mod_root / "replacement.txt").write_text("replacement", encoding="utf-8")
    config = _config(
        [
            {
                "source": "${mod_path}/replacement.txt",
                "target": "${game_path}/replacement.txt",
                "type": "overwrite",
            }
        ]
    )
    launcher = GameLauncher(
        _app_state(tmp_path, game_root), Mock(), _ModService(config, mod_root)
    )
    mod = SimpleNamespace(id="mod")

    plan = launcher._build_operation_profile_plan(
        {"any": [mod]}, {"any": [[mod], [mod]]}
    )

    assert plan is not None
    assert [operation.index for operation in plan.operations] == [1]
    assert plan.findings[0].code == "target_missing"


def test_launch_preserves_simultaneous_mod_steps_for_merging():
    assert GameLauncher._operation_merge_steps(
        {"deltarune_1": [SimpleNamespace(id="first"), SimpleNamespace(id="second")]},
        None,
    ) == (("first", "second"),)


def test_launch_notifies_plugins_when_the_game_starts(qapp, tmp_path):
    game_root = tmp_path / "game"
    game_root.mkdir()
    parent = QObject()
    vars(parent)["plugin_runtime_service"] = Mock()
    launcher = GameLauncher(_app_state(tmp_path, game_root), Mock(), Mock(), parent)
    launcher._commit_permanent_operation = Mock()

    launcher._on_game_process_detected(False)

    vars(parent)["plugin_runtime_service"].execute_hook.assert_called_once_with(
        "after_game_started", False
    )


def test_collect_selected_mod_ids_preserves_step_order_and_deduplicates():
    from services.mod_operation_support import collect_selected_mod_ids

    assert collect_selected_mod_ids(
        {
            "first": [[SimpleNamespace(id="a"), {"id": "b"}]],
            "second": [SimpleNamespace(id="b"), SimpleNamespace(id="c")],
        }
    ) == ("a", "b", "c")


def test_launch_rejects_mixed_config_versions_instead_of_using_legacy_runtime(qapp, tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    (mod_root / "replacement.txt").write_text("replacement", encoding="utf-8")
    config = _config(
        [
            {
                "source": "${mod_path}/replacement.txt",
                "target": "${game_path}/replacement.txt",
                "type": "overwrite",
            }
        ]
    )
    service = Mock()
    service.get_mod_config.side_effect = lambda mod_id: config if mod_id == "mod" else {}
    service.get_mod_folder_path.return_value = str(mod_root)
    launcher = GameLauncher(_app_state(tmp_path, game_root), Mock(), service)
    operation_mod = SimpleNamespace(id="mod")
    legacy_mod = SimpleNamespace(id="legacy")

    plan = launcher._build_operation_profile_plan(
        {"any": [operation_mod, legacy_mod]}, {"any": [[operation_mod, legacy_mod]]}
    )

    assert plan is not None
    assert plan.has_errors
    assert any(finding.code == "config_version" for finding in plan.findings)


def test_launch_reports_installed_but_inactive_operation_dependency(qapp, tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    main = _config([])
    main["dependencies"] = ["base:before"]
    base = _config([])
    service = Mock()
    service.get_mod_config.side_effect = lambda mod_id: {
        "main": main,
        "base": base,
    }.get(mod_id, {})
    service.get_mod_folder_path.return_value = str(mod_root)
    app_state = _app_state(tmp_path, game_root)
    app_state.all_mods = [SimpleNamespace(id="main"), SimpleNamespace(id="base")]
    launcher = GameLauncher(app_state, Mock(), service)
    main_mod = SimpleNamespace(id="main")

    plan = launcher._build_operation_profile_plan({"any": [main_mod]}, {"any": [[main_mod]]})

    assert plan is not None
    assert any(finding.code == "dependency_inactive" for finding in plan.findings)


def test_launch_can_skip_only_missing_operation_operation_after_confirmation(qapp, tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    config = _config(
        [
            {
                "source": "${mod_path}/missing.txt",
                "target": "${game_path}/target.txt",
                "type": "overwrite",
            }
        ]
    )
    feedback = Mock()
    feedback.ask_patching_warning.return_value = True
    launcher = GameLauncher(
        _app_state(tmp_path, game_root), feedback, _ModService(config, mod_root)
    )
    mod = SimpleNamespace(id="mod")
    plan = launcher._build_operation_profile_plan({"any": [mod]}, {"any": [[mod]]})

    confirmed = launcher._confirm_operation_plan(plan)

    assert confirmed is not None
    assert confirmed.operations == ()
    assert not confirmed.has_errors
    assert any(finding.code == "source_missing_skipped" for finding in confirmed.findings)
    feedback.ask_patching_warning.assert_called_once()


def test_launch_confirms_direct_absolute_operation_paths(qapp, tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    source = mod_root / "replacement.txt"
    source.write_text("replacement", encoding="utf-8")
    target = game_root / "target.txt"
    target.write_text("original", encoding="utf-8")
    feedback = Mock()
    feedback.ask_patching_warning.return_value = True
    launcher = GameLauncher(
        _app_state(tmp_path, game_root), feedback,
        _ModService(
            _config(
                [{"source": source.as_posix(), "target": target.as_posix(), "type": "overwrite"}]
            ),
            mod_root,
        ),
    )
    mod = SimpleNamespace(id="mod")

    plan = launcher._build_operation_profile_plan({"any": [mod]}, {"any": [[mod]]})
    assert launcher._confirm_operation_plan(plan) is not None

    event = feedback.ask_patching_warning.call_args.args[0]
    assert event.warning_id == "direct_absolute_operation_paths"


def test_launch_can_apply_a_checked_dependency_arrangement(qapp, tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    main = _config([])
    main["dependencies"] = ["base:before"]
    base = _config([])
    service = Mock()
    service.get_mod_config.side_effect = lambda mod_id: {
        "main": main,
        "base": base,
    }.get(mod_id, {})
    feedback = Mock()
    feedback.ask_relation_arrangement.return_value = "apply"
    parent = QObject()
    vars(parent)["used_mods_service"] = Mock()
    main_mod = SimpleNamespace(id="main")
    base_mod = SimpleNamespace(id="base")
    vars(parent)["used_mods_service"].get_mod_steps.return_value = [[main_mod, base_mod]]
    launcher = GameLauncher(_app_state(tmp_path, game_root), feedback, service, parent)

    assert launcher._offer_operation_relation_recommendations(
        {"deltarune": [main_mod, base_mod]}, {"deltarune": [[main_mod, base_mod]]}
    )
    vars(parent)["used_mods_service"].set_mod_steps.assert_called_once_with(
        "deltarune", [[base_mod, main_mod]], save_state=False
    )
    vars(parent)["used_mods_service"].save_used_mods_state.assert_called_once()


def test_launch_can_activate_an_installed_operation_dependency(qapp, tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    main = _config([])
    main["dependencies"] = ["base"]
    base = _config([])
    service = Mock()
    service.get_mod_config.side_effect = lambda mod_id: {
        "main": main,
        "base": base,
    }.get(mod_id, {})
    service.get_mod_folder_path.return_value = str(mod_root)
    feedback = Mock()
    feedback.ask_dependency_activation.return_value = "activate"
    parent = QObject()
    vars(parent)["used_mods_service"] = Mock()
    main_mod = SimpleNamespace(id="main")
    base_mod = SimpleNamespace(id="base")
    vars(parent)["used_mods_service"].get_mod_steps.return_value = [[main_mod]]
    app_state = _app_state(tmp_path, game_root)
    app_state.all_mods = [main_mod, base_mod]
    launcher = GameLauncher(app_state, feedback, service, parent)

    assert launcher._offer_dependency_activation(
        {"deltarune": [main_mod]}, {"deltarune": [[main_mod]]}
    )
    vars(parent)["used_mods_service"].set_mod_steps.assert_called_once_with(
        "deltarune", [[main_mod, base_mod]], save_state=False
    )
    vars(parent)["used_mods_service"].save_used_mods_state.assert_called_once()


def test_launch_resolves_missing_gamebanana_and_inactive_dependencies_together(
    qapp, tmp_path
):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    main = _config([])
    main["dependencies"] = ["base", "gb_mod_123"]
    base = _config([])
    service = Mock()
    service.get_mod_config.side_effect = lambda mod_id: {
        "main": main,
        "base": base,
    }.get(mod_id, {})
    service.get_mod_folder_path.return_value = str(mod_root)
    feedback = Mock()
    feedback.ask_dependency_resolution.return_value = "resolve"
    parent = QObject()
    vars(parent)["used_mods_service"] = Mock()
    main_mod = SimpleNamespace(id="main")
    base_mod = SimpleNamespace(id="base")
    vars(parent)["used_mods_service"].get_mod_steps.return_value = [[main_mod]]
    app_state = _app_state(tmp_path, game_root)
    app_state.all_mods = [main_mod, base_mod]
    launcher = GameLauncher(app_state, feedback, service, parent)
    launcher._selected_launch_mode = LaunchMode.KEEP_CHANGES
    launcher._before_mod_apply_completed = True
    launcher._start_dependency_resolution = Mock()

    assert not launcher._offer_dependency_activation(
        {"deltarune": [main_mod]}, {"deltarune": [[main_mod]]}
    )
    vars(parent)["used_mods_service"].set_mod_steps.assert_called_once_with(
        "deltarune", [[main_mod, base_mod]], save_state=False
    )
    launcher._start_dependency_resolution.assert_called_once_with(
        {"gb_mod_123"}, "deltarune"
    )
    assert launcher._pending_dependency_launch is not None
    assert launcher._pending_dependency_launch["mode"] is LaunchMode.KEEP_CHANGES
    assert launcher._pending_dependency_launch is not None
    assert launcher._pending_dependency_launch["pre_hooks_done"] is True
    assert launcher._pending_dependency_launch is not None
    assert launcher._pending_dependency_launch["download_scopes"] == {
        "deltarune": {"gb_mod_123"}
    }


def test_dependency_download_resume_preserves_the_requested_launch_mode(qapp, tmp_path):
    game_root = tmp_path / "game"
    game_root.mkdir()
    parent = QObject()
    launcher = GameLauncher(_app_state(tmp_path, game_root), Mock(), Mock(), parent)
    selections = {"deltarune": [SimpleNamespace(id="main")]}
    launcher._pending_dependency_launch = {
        "selections": selections,
        "mode": LaunchMode.PATCHING_ONLY,
        "pre_hooks_done": True,
    }
    launcher._finish_background_launch_operation = Mock()
    launcher._launch_game_with_selections = Mock()

    launcher._resume_pending_dependency_launch()

    launcher._launch_game_with_selections.assert_called_once_with(
        selections,
        None,
        LaunchMode.PATCHING_ONLY,
        True,
    )


def test_launch_reports_manual_dependency_installation_before_continuing(
    qapp, tmp_path
):
    game_root = tmp_path / "game"
    game_root.mkdir()
    main = _config([])
    main["dependencies"] = ["manual_dependency"]
    service = Mock()
    service.get_mod_config.side_effect = lambda mod_id: main if mod_id == "main" else {}
    service.get_mod_folder_path.return_value = None
    feedback = Mock()
    feedback.ask_dependency_resolution.return_value = "resolve"
    feedback.ask_patching_warning.return_value = True
    parent = QObject()
    launcher = GameLauncher(_app_state(tmp_path, game_root), feedback, service, parent)
    main_mod = SimpleNamespace(id="main")

    assert launcher._offer_dependency_activation(
        {"deltarune": [main_mod]}, {"deltarune": [[main_mod]]}
    )
    feedback.ask_patching_warning.assert_called_once()
    assert "manual installation" in feedback.ask_patching_warning.call_args.args[0]


def test_launch_restarts_duplicate_dependency_download_install(
    qapp, tmp_path, monkeypatch
):
    game_root = tmp_path / "game"
    game_root.mkdir()
    parent = QObject()
    manager = Mock()
    manager.enqueue.return_value = ("record-id", True)
    vars(parent)["downloads_manager"] = manager
    launcher = GameLauncher(_app_state(tmp_path, game_root), Mock(), Mock(), parent)
    source_thread = object()
    vars(launcher)["_dependency_resolution_thread"] = source_thread
    launcher._pending_dependency_launch = {
        "selections": {},
        "failures": {},
        "manual_ids": set(),
        "download_ids": {"gb_mod_123"},
        "scopes": {},
    }
    monkeypatch.setattr("services.launch_service.retire_qthread", Mock())

    launcher._on_dependency_downloads_resolved(
        source_thread,
        {
            "gb_mod_123": {
                "display_name": "Dependency",
                "source_url": "https://example.invalid/mod.zip",
                "canonical_key": "gb_mod_123_file_1",
                "metadata": {},
            }
        },
        {},
    )

    manager.action_install.assert_called_once_with("record-id")


def test_dependency_downloads_pin_the_originating_profile_mod_root(
    qapp, tmp_path, monkeypatch
):
    game_root = tmp_path / "game"
    profile_root = tmp_path / "profiles" / "Default"
    game_root.mkdir()
    profile_root.mkdir(parents=True)
    parent = QObject()
    manager = Mock()
    manager.enqueue.return_value = ("record-id", True)
    vars(parent)["downloads_manager"] = manager
    app_state = _app_state(tmp_path, game_root)
    app_state.mods_dir = str(profile_root)
    launcher = GameLauncher(app_state, Mock(), Mock(), parent)
    source_thread = object()
    vars(launcher)["_dependency_resolution_thread"] = source_thread
    launcher._pending_dependency_launch = {
        "selections": {},
        "failures": {},
        "manual_ids": set(),
        "download_ids": {"gb_mod_123"},
        "scopes": {},
        "profile_name": "Default",
        "target_mods_dir": str(profile_root.resolve()),
    }
    monkeypatch.setattr("services.launch_service.retire_qthread", Mock())

    launcher._on_dependency_downloads_resolved(
        source_thread,
        {
            "gb_mod_123": {
                "display_name": "Dependency",
                "source_url": "https://example.invalid/mod.zip",
                "canonical_key": "gb_mod_123_file_1",
                "metadata": {},
            }
        },
        {},
    )

    assert manager.enqueue.call_args.kwargs["metadata"]["target_mods_dir"] == str(
        profile_root.resolve()
    )


def test_pending_dependency_launch_is_cancelled_after_profile_switch(qapp, tmp_path):
    game_root = tmp_path / "game"
    game_root.mkdir()
    launcher = GameLauncher(_app_state(tmp_path, game_root), Mock(), Mock())
    launcher._pending_dependency_launch = {
        "profile_name": "Default",
        "target_mods_dir": None,
    }
    launcher.cancel_pending_launch = Mock()

    launcher._on_profile_switched("Other")

    launcher.cancel_pending_launch.assert_called_once_with("profile-changed")


def test_launch_keeps_manual_dependency_visible_after_automatic_downloads(
    qapp, tmp_path
):
    game_root = tmp_path / "game"
    game_root.mkdir()
    service = Mock()
    service.get_mod_folder_path.side_effect = lambda mod_id: (
        str(tmp_path / "installed") if mod_id == "gb_mod_123" else None
    )
    parent = QObject()
    vars(parent)["used_mods_service"] = Mock()
    main_mod = SimpleNamespace(id="main")
    other_mod = SimpleNamespace(id="other")
    downloaded_mod = SimpleNamespace(id="gb_mod_123")
    app_state = _app_state(tmp_path, game_root)
    app_state.all_mods = [downloaded_mod]
    launcher = GameLauncher(app_state, Mock(), service, parent)
    record = SimpleNamespace(is_active=False, effective_status_key="installed", progress=100)
    launcher._dependency_download_manager = SimpleNamespace(
        store=SimpleNamespace(find=lambda _record_id: record)
    )
    launcher._dependency_download_records = {"record-id": "gb_mod_123"}
    launcher._pending_dependency_launch = {
        "selections": {"deltarune": [main_mod]},
        "failures": {},
        "manual_ids": {"manual_dependency"},
        "download_ids": {"gb_mod_123"},
        "download_scopes": {"deltarune": {"gb_mod_123"}},
        "scopes": {"deltarune": [[main_mod]], "other": [[other_mod]]},
    }
    launcher._resume_pending_dependency_launch = Mock()

    launcher._check_dependency_downloads()

    assert launcher._pending_dependency_launch["manual_ids"] == {"manual_dependency"}
    assert "manual_dependency" in launcher._resume_pending_dependency_launch.call_args.args[0]
    vars(parent)["used_mods_service"].set_mod_steps.assert_called_once_with(
        "deltarune", [[main_mod, downloaded_mod]], save_state=False
    )


def test_launch_recovers_operation_journal_after_an_interrupted_session(qtbot, tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    source = mod_root / "replacement.txt"
    target = game_root / "target.txt"
    source.write_text("replacement", encoding="utf-8")
    target.write_text("original", encoding="utf-8")
    app_state = _app_state(tmp_path, game_root)
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/replacement.txt",
                    "target": "${game_path}/target.txt",
                    "type": "overwrite",
                }
            ]
        ),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
        ),
    )
    ModOperationExecutor(tmp_path / "config" / "operation-session").execute(plan)
    launcher = GameLauncher(app_state, Mock(), Mock())

    launcher.recover_previous_session()
    qtbot.waitUntil(lambda: launcher.launch_transaction.state.value == "completed")
    assert target.read_text(encoding="utf-8") == "original"


def test_launch_can_keep_external_changes_when_recovery_conflicts(qapp, tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    source = mod_root / "replacement.txt"
    target = game_root / "target.txt"
    source.write_text("replacement", encoding="utf-8")
    target.write_text("original", encoding="utf-8")
    app_state = _app_state(tmp_path, game_root)
    plan = build_mod_operation_plan(
        _config(
            [{"source": "${mod_path}/replacement.txt", "target": "${game_path}/target.txt", "type": "overwrite"}]
        ),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
        ),
    )
    ModOperationExecutor(tmp_path / "config" / "operation-session").execute(plan)
    target.write_text("external", encoding="utf-8")
    feedback = Mock()
    feedback.ask_operation_recovery_conflict.return_value = "keep"
    launcher = GameLauncher(app_state, feedback, Mock())

    assert launcher._recover_operation_session() is True
    assert target.read_text(encoding="utf-8") == "external"


def test_declining_the_forced_restore_keeps_files_and_unblocks_the_next_launch(qapp, tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    (mod_root / "replacement.txt").write_text("replacement", encoding="utf-8")
    target = game_root / "target.txt"
    target.write_text("original", encoding="utf-8")
    app_state = _app_state(tmp_path, game_root)
    plan = build_mod_operation_plan(
        _config(
            [{"source": "${mod_path}/replacement.txt", "target": "${game_path}/target.txt", "type": "overwrite"}]
        ),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
        ),
    )
    session = tmp_path / "config" / "operation-session"
    ModOperationExecutor(session).execute(plan)
    target.write_text("external", encoding="utf-8")
    feedback = Mock()
    feedback.ask_operation_recovery_conflict.return_value = "cancel"
    launcher = GameLauncher(app_state, feedback, Mock())

    assert launcher._recover_operation_session() is True

    assert target.read_text(encoding="utf-8") == "external"
    ModOperationExecutor(session).execute(plan)


def test_launch_checkpoints_plugin_changes_before_starting_game(qtbot, tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    launcher = GameLauncher(
        _app_state(tmp_path, game_root), Mock(), _ModService(_config([]), mod_root)
    )
    journal = Mock()
    launcher._operation_journal = journal
    launcher._finalize_launch_after_plugin_hooks = Mock()

    launcher._on_plugin_hook_finished(({}, False), True)

    qtbot.waitUntil(lambda: journal.checkpoint.called)
    journal.checkpoint.assert_called_once_with()
    launcher._finalize_launch_after_plugin_hooks.assert_called_once_with(
        {}, False, journal_checkpointed=True
    )


def _relation_launcher(tmp_path, dependencies, installed, disabled_warning):
    game_root = tmp_path / "game"
    game_root.mkdir()
    main = _config([])
    main["dependencies"] = dependencies
    service = Mock()
    service.get_mod_config.side_effect = lambda mod_id: {"main": main, "base": _config([])}.get(mod_id, {})
    service.get_mod_folder_path.return_value = str(tmp_path)
    feedback = Mock()
    parent = QObject()
    vars(parent)["used_mods_service"] = Mock()
    main_mod, base_mod = SimpleNamespace(id="main"), SimpleNamespace(id="base")
    vars(parent)["used_mods_service"].get_mod_steps.return_value = [[main_mod, base_mod] if installed == "ordered" else [main_mod]]
    app_state = _app_state(tmp_path, game_root)
    app_state.all_mods = [main_mod, base_mod]
    app_state.local_config = {"warning_preferences": {"warning_overrides": {disabled_warning: False}}}
    launcher = GameLauncher(app_state, feedback, service, parent)
    return launcher, feedback, main_mod, base_mod, parent


def test_the_order_suggestion_can_be_turned_off(qapp, tmp_path):
    launcher, feedback, main_mod, base_mod, _parent = _relation_launcher(tmp_path, ["base:before"], "ordered", "mod_order_suggestion")

    assert launcher._offer_operation_relation_recommendations(
        {"deltarune": [main_mod, base_mod]}, {"deltarune": [[main_mod, base_mod]]}
    )
    feedback.ask_relation_arrangement.assert_not_called()


def test_the_inactive_dependency_prompt_can_be_turned_off(qapp, tmp_path):
    launcher, feedback, main_mod, _base_mod, _parent = _relation_launcher(tmp_path, ["base"], "single", "inactive_dependencies")

    assert launcher._offer_dependency_activation({"deltarune": [main_mod]}, {"deltarune": [[main_mod]]})
    feedback.ask_dependency_activation.assert_not_called()


def test_the_missing_dependency_prompt_can_be_turned_off_on_its_own(qapp, tmp_path):
    launcher, feedback, main_mod, _base_mod, _parent = _relation_launcher(tmp_path, ["gb_mod_123"], "single", "missing_dependencies")

    assert launcher._offer_dependency_activation({"deltarune": [main_mod]}, {"deltarune": [[main_mod]]})
    feedback.ask_dependency_resolution.assert_not_called()


def test_every_warning_has_a_section_and_text_in_every_language():
    import json
    from pathlib import Path

    from services.warning_service import WarningSeverity, iter_warning_definitions

    definitions = iter_warning_definitions()
    assert {item.severity for item in definitions} == set(WarningSeverity)
    for path in sorted(Path("src/assets/lang").glob("lang_*.json")):
        warnings = json.loads(path.read_text(encoding="utf-8"))["warnings"]
        for item in definitions:
            assert item.warning_id in warnings["items"], (path.name, item.warning_id)
            assert item.warning_id in warnings["tooltips"], (path.name, item.warning_id)


def test_turning_off_missing_dependencies_still_offers_to_activate_inactive_ones(qapp, tmp_path):
    launcher, feedback, main_mod, _base_mod, _parent = _relation_launcher(
        tmp_path, ["base", "gb_mod_123"], "single", "missing_dependencies"
    )
    feedback.ask_dependency_activation.return_value = "continue"

    assert launcher._offer_dependency_activation({"deltarune": [main_mod]}, {"deltarune": [[main_mod]]})
    feedback.ask_dependency_resolution.assert_not_called()
    feedback.ask_dependency_activation.assert_called_once()
