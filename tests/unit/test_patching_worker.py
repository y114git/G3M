"""Unit tests for mod patching worker crash handling."""

from __future__ import annotations

from unittest.mock import Mock

from models.execution_plan import PatchPlan
from workers.mod.patching_worker import ModPatchingThread


class _FailingSignal:
    def emit(self, *_args, **_kwargs):
        raise RuntimeError("receiver deleted")


def test_mod_patching_worker_suppresses_emit_failure_after_error(monkeypatch, caplog):
    """Checks that patching errors cannot crash while notifying a dead UI."""
    worker = ModPatchingThread(
        app_state=Mock(),
        mod_service=Mock(),
        patch_plan=PatchPlan(),
        session_manifest_path="session.json",
    )
    worker.status_update = _FailingSignal()
    worker.result_ready = _FailingSignal()

    class _BrokenPatcher:
        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("patcher failed")

    monkeypatch.setattr("workers.mod.patching_worker.G3MToolPatchingService", _BrokenPatcher)

    worker.run()

    assert "ModPatchingThread failed" in caplog.text
    assert "ModPatchingThread: failed to emit" in caplog.text


def test_mod_patching_worker_preserves_native_qthread_finished_signal():
    """Result notification must not shadow QThread.finished lifetime signal."""
    worker = ModPatchingThread(Mock(), Mock(), PatchPlan(), "session.json")

    assert worker.finished.signal == "2finished()"
    assert worker.result_ready.signal == "2result_ready(bool)"


def test_mod_patching_worker_passes_nested_steps_to_patcher(monkeypatch):
    main = Mock(id="main")
    addon = Mock(id="addon")
    plans = {"chapter": [[main], [addon]]}
    received = []

    class _Patcher:
        backup_service = None

        def __init__(self, *_args, **_kwargs) -> None:
            self.progress_update = Mock()
            self.status_update = Mock()

        def process_patch_plan(self, plan, resolver, is_modpack=False):
            received.append((plan.resolve(resolver), is_modpack))
            return True

        def cleanup(self, force=False):
            pass

    monkeypatch.setattr("workers.mod.patching_worker.G3MToolPatchingService", _Patcher)
    worker = ModPatchingThread(
        Mock(all_mods=[main, addon]),
        Mock(),
        PatchPlan.from_runtime(plans),
        "session.json",
    )

    worker.run()

    assert received == [(plans, False)]


def test_mod_patching_worker_reports_cancellation_after_restoring_backups(monkeypatch):
    calls = []

    class _Patcher:
        backup_service = Mock(original_files={"game": {}}, added_files={})

        def __init__(self, *_args) -> None:
            self.progress_update = Mock()
            self.status_update = Mock()

        def process_patch_plan(self, *_args, **_kwargs):
            worker._cancelled = True
            return False

        def cancel(self):
            calls.append("cancel")

        def restore_all_backups(self):
            calls.append("restore")

        def cleanup(self, force=False):
            calls.append("cleanup")

    monkeypatch.setattr("workers.mod.patching_worker.G3MToolPatchingService", _Patcher)
    worker = ModPatchingThread(Mock(all_mods=[]), Mock(), PatchPlan(), "session.json")
    results = []
    worker.result_ready.connect(lambda success: (calls.append("result"), results.append(success)))

    worker.run()

    assert results == [False]
    assert calls == ["cancel", "restore", "cleanup", "result"]


def test_mod_patching_worker_resolves_selected_mod_not_yet_in_global_catalog(
    monkeypatch,
):
    selected = Mock(id="gb_mod_679091")
    plan = PatchPlan.from_runtime({"frickbears3": [[selected]]})
    received = []

    class _Patcher:
        backup_service = None

        def __init__(self, *_args, **_kwargs) -> None:
            self.progress_update = Mock()
            self.status_update = Mock()

        def process_patch_plan(self, patch_plan, resolver, is_modpack=False):
            received.append(patch_plan.resolve(resolver))
            return True

        def cleanup(self, force=False):
            pass

    monkeypatch.setattr("workers.mod.patching_worker.G3MToolPatchingService", _Patcher)
    worker = ModPatchingThread(
        Mock(all_mods=[]),
        Mock(),
        plan,
        "session.json",
        plan_mods=[selected],
    )

    worker.run()

    assert received == [{"frickbears3": [[selected]]}]
