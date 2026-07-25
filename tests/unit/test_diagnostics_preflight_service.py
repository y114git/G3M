from __future__ import annotations

import json
from types import SimpleNamespace

from models.execution_plan import PatchPlan
from services.diagnostics.preflight_service import (
    DiagnosticsPreflightService,
    PreflightFileChange,
    PreflightReport,
    PreflightResourceChange,
    PreflightStepResult,
    export_preflight_report,
)
from services.warning_service import create_warning_event


def _report() -> PreflightReport:
    return PreflightReport(
        success=True,
        cancelled=False,
        duration_seconds=1.25,
        steps=(
            PreflightStepResult(
                section_id="section_1",
                step_index=1,
                mod_ids=("mod_a",),
                success=True,
                duration_seconds=0.5,
            ),
        ),
        resources=(
            PreflightResourceChange(
                section_id="section_1",
                step_index=1,
                resource_type="Code",
                operation="changed",
                name="<script>",
                mod_ids=("mod_a",),
                files=("code.gml",),
            ),
        ),
        files=(
            PreflightFileChange(
                relative_path="data.win",
                operation="modified",
                before_size=10,
                after_size=12,
                before_hash="before",
                after_hash="after",
            ),
        ),
        issues=("warning <details>",),
    )


def test_preflight_report_serialization_is_deterministic():
    report = _report()

    assert report.to_dict() == report.to_dict()
    assert report.to_dict()["resources"][0]["name"] == "<script>"


def test_preflight_export_writes_equivalent_json_and_safe_html(tmp_path):
    report = _report()
    target = tmp_path / "diagnostics.html"

    html_path, json_path = export_preflight_report(report, str(target))

    payload = json.loads((tmp_path / "diagnostics.json").read_text("utf-8"))
    html = (tmp_path / "diagnostics.html").read_text("utf-8")
    assert payload == report.to_dict()
    assert html_path == str(target)
    assert json_path == str(tmp_path / "diagnostics.json")
    assert "&lt;script&gt;" in html
    assert "warning &lt;details&gt;" in html
    assert "<script>" not in html


def test_preflight_executes_steps_in_order_without_changing_source_game(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    (game / "data.win").write_text("base", encoding="utf-8")
    (game / "original.txt").write_text("original", encoding="utf-8")
    mods = [SimpleNamespace(id="base_mod"), SimpleNamespace(id="addon_mod")]
    calls = []

    class FakePatcher:
        def __init__(self, *_args) -> None:
            self.root = ""

        def set_override_game_path(self, path):
            self.root = path

        def set_backup_root_override(self, path):
            calls.append(("backup", path))

        def process_patch_plan(self, plan, resolver, **_kwargs):
            resolved = plan.resolve(resolver)
            mod = next(iter(resolved.values()))[0][0]
            calls.append(mod.id)
            data = tmp_path.__class__(self.root) / "data.win"
            data.write_text(data.read_text("utf-8") + f"|{mod.id}", encoding="utf-8")
            return True

        def cleanup(self, *, force=False):
            calls.append(("cleanup", force))

        def cancel(self):
            calls.append("cancel")

    service = DiagnosticsPreflightService(
        SimpleNamespace(game_mode=SimpleNamespace(game_id="test"), local_config={}),
        SimpleNamespace(),
        patcher_factory=FakePatcher,
        data_file_locator=lambda root, _section: str(tmp_path.__class__(root) / "data.win"),
        resource_diff_builder=lambda *_args, **_kwargs: (),
    )
    plan = PatchPlan.from_runtime({"section": [[mods[0]], [mods[1]]]})

    report = service.run(plan, lambda mod_id: next((m for m in mods if m.id == mod_id), None), str(game))

    assert report.success is True
    assert [step.mod_ids for step in report.steps] == [("base_mod",), ("addon_mod",)]
    assert calls[1:3] == ["base_mod", "addon_mod"]
    assert calls[-1] == ("cleanup", True)
    assert (game / "data.win").read_text("utf-8") == "base"
    assert (game / "original.txt").read_text("utf-8") == "original"
    assert any(change.relative_path == "data.win" for change in report.files)


def test_preflight_cancellation_stops_before_next_step_and_cleans_up(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    (game / "data.win").write_text("base", encoding="utf-8")
    mods = [SimpleNamespace(id="first"), SimpleNamespace(id="second")]
    calls = []
    service = None

    class FakePatcher:
        def __init__(self, *_args) -> None:
            pass

        def set_override_game_path(self, _path):
            pass

        def set_backup_root_override(self, _path):
            pass

        def process_patch_plan(self, plan, resolver, **_kwargs):
            mod = next(iter(plan.resolve(resolver).values()))[0][0]
            calls.append(mod.id)
            service.cancel()
            return True

        def cancel(self):
            calls.append("cancel")

        def cleanup(self, *, force=False):
            calls.append(("cleanup", force))

    service = DiagnosticsPreflightService(
        SimpleNamespace(game_mode=SimpleNamespace(game_id="test"), local_config={}),
        SimpleNamespace(),
        patcher_factory=FakePatcher,
        data_file_locator=lambda root, _section: str(tmp_path.__class__(root) / "data.win"),
        resource_diff_builder=lambda *_args, **_kwargs: (),
    )
    plan = PatchPlan.from_runtime({"section": [[mods[0]], [mods[1]]]})

    report = service.run(plan, lambda mod_id: next((m for m in mods if m.id == mod_id), None), str(game))

    assert report.cancelled is True
    assert "second" not in calls
    assert calls[-1] == ("cleanup", True)


def test_preflight_cancelled_before_run_does_not_stage_or_create_patcher(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    created = []
    service = DiagnosticsPreflightService(
        SimpleNamespace(),
        SimpleNamespace(),
        patcher_factory=lambda *_args: created.append(True),
    )
    service.cancel()

    report = service.run(PatchPlan(), lambda _mod_id: None, str(game))

    assert report.cancelled is True
    assert report.success is False
    assert created == []


def test_preflight_rejects_patch_fallback_and_reports_exact_tool_error(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    (game / "data.win").write_text("base", encoding="utf-8")
    mod = SimpleNamespace(id="broken_xdelta")

    class FailingPatcher:
        strict_warning_handler = None

        def __init__(self, *_args) -> None:
            pass

        def set_override_game_path(self, _path):
            pass

        def set_backup_root_override(self, _path):
            pass

        def process_patch_plan(self, _plan, _resolver, **_kwargs):
            event = create_warning_event(
                "xdelta_apply_failed",
                fallback_message="xdelta failed",
            )
            return self.strict_warning_handler(
                event,
                "xdelta3: target window checksum mismatch: XD3_INVALID_INPUT",
                None,
            )

        def cleanup(self, *, force=False):
            pass

        def cancel(self):
            pass

    service = DiagnosticsPreflightService(
        SimpleNamespace(game_mode=SimpleNamespace(game_id="test"), local_config={}),
        SimpleNamespace(),
        patcher_factory=FailingPatcher,
        data_file_locator=lambda root, _section: str(tmp_path.__class__(root) / "data.win"),
    )

    report = service.run(
        PatchPlan.from_runtime({"section": [[mod]]}),
        lambda _mod_id: mod,
        str(game),
    )

    assert report.success is False
    assert report.steps[0].success is False
    assert "XD3_INVALID_INPUT" in report.steps[0].error
    assert "XD3_INVALID_INPUT" in report.issues[0]


def test_preflight_reports_real_target_permission_failure(tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    data = game / "data.win"
    data.write_text("base", encoding="utf-8")
    created = []
    service = DiagnosticsPreflightService(
        SimpleNamespace(game_mode=SimpleNamespace(game_id="test"), local_config={}),
        SimpleNamespace(),
        patcher_factory=lambda *_args: created.append(True),
        data_file_locator=lambda _root, _section: str(data),
    )
    monkeypatch.setattr(
        "services.diagnostics.preflight_service.tempfile.mkstemp",
        lambda **_kwargs: (_ for _ in ()).throw(PermissionError("access denied")),
    )

    report = service.run(
        PatchPlan.from_runtime({"section": [[SimpleNamespace(id="mod")]]}),
        lambda _mod_id: SimpleNamespace(id="mod"),
        str(game),
    )

    assert report.success is False
    assert "access denied" in report.issues[0]
    assert str(game) in report.issues[0]
    assert created == []
