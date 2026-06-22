"""Unit tests for test pizza oven conversion service."""

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from models.game_modes import get_game
from presentation.pizza_oven_conversion_presenter import PizzaOvenConversionPresenter
from services.g3mtool_patching_service import G3MToolPatchingService
from services.pizza_oven_conversion_service import PizzaOvenConversionService


class FakePizzaOvenG3MTool:
    _PATCH_PREFIX = b"G3MTOOL_PATCH\n"

    def is_available(self) -> bool:
        return True

    def xpatch_apply(
        self,
        original_file: str,
        patch_path: str,
        output_path: str,
        progress_callback=None,
    ) -> tuple[int, str, str]:
        if progress_callback:
            progress_callback(100, "done")
        source = Path(original_file)
        patch_name = Path(patch_path).name.lower()
        if patch_name.endswith((".xdelta", ".vcdiff")) and source.name.lower() == "data.win":
            Path(output_path).write_bytes(source.read_bytes() + b"|po-patched|")
            return (0, "", "")
        return (1, "", "unsupported patch target")

    def patch_create(
        self, original_file: str, modified_file: str, output_path: str
    ) -> tuple[int, str, str]:
        Path(output_path).write_bytes(self._PATCH_PREFIX + Path(modified_file).read_bytes())
        return (0, "", "")

    def apply_patch(
        self,
        original_data_win: str,
        patch_path: str,
        output_path: str,
        log_path: str | None = None,
        progress_callback=None,
    ) -> tuple[int, str, str]:
        payload = Path(patch_path).read_bytes()
        if not payload.startswith(self._PATCH_PREFIX):
            return (1, "", "invalid fake g3mpatch payload")
        if progress_callback:
            progress_callback(100, "done")
        Path(output_path).write_bytes(payload[len(self._PATCH_PREFIX) :])
        return (0, "", "")

    def xpatch_create(
        self,
        original_file: str,
        modified_file: str,
        output_path: str,
        progress_callback=None,
    ) -> tuple[int, str, str]:
        Path(output_path).write_bytes(b"unused")
        return (0, "", "")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _create_fake_pizzatower_game(game_dir: Path) -> None:
    _write_bytes(game_dir / "data.win", b"ORIGINAL_DATA")
    _write_bytes(game_dir / "PizzaTower.exe", b"ORIGINAL_EXE")
    _write_text(game_dir / "lang" / "base.txt", 'lang = "base"\n')
    _write_bytes(game_dir / "sound" / "Desktop" / "vanilla.bank", b"VANILLA_BANK")


def _create_fake_pizzaoven_mod(mod_dir: Path) -> None:
    _write_text(
        mod_dir / "mod.json",
        json.dumps(
            {
                "title": "Fake PO Mod",
                "submitter": "Tests",
                "description": "PizzaOven conversion test",
            }
        ),
    )
    _write_bytes(mod_dir / "test_patch.xdelta", b"patch")
    _write_text(mod_dir / "english.txt", 'lang = "english"\n')
    _write_text(mod_dir / "noisecredits.txt", "Credits go here\n")
    _write_bytes(mod_dir / "helper.dll", b"DLL_PAYLOAD")
    _write_text(mod_dir / "Install Instructions.txt", "Read me\n")
    _write_text(mod_dir / "english.json", '{"font":"english"}')
    _write_bytes(mod_dir / "english.png", b"PNG_GRAPHICS")
    _write_bytes(mod_dir / "tutorial_english.png", b"PNG_FONT")
    _write_text(mod_dir / "custom.def", "font definition\n")
    _write_bytes(mod_dir / "music" / "custom.bank", b"CUSTOM_BANK")


def _extra_files_to_map(extra_files: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for file_path in extra_files:
        group = os.path.dirname(file_path).replace("\\", "/") or "root"
        result.setdefault(group, []).append(file_path)
    return result


def test_inspect_source_disables_conversion_with_disable_gb1click(tmp_path):
    """Checks that inspecting source disables conversion with disable gb1click."""
    service = PizzaOvenConversionService(FakePizzaOvenG3MTool())
    mod_dir = tmp_path / "mod"
    _create_fake_pizzaoven_mod(mod_dir)
    _write_text(mod_dir / "nested" / ".disable_gb1click", "")

    inspection = service.inspect_source(str(mod_dir))

    assert inspection.eligible is False
    assert inspection.disable_all is True


def test_inspect_source_disables_conversion_with_both_pizzaoven_flags(tmp_path):
    """Checks that inspecting source disables conversion with both pizzaoven flags."""
    service = PizzaOvenConversionService(FakePizzaOvenG3MTool())
    mod_dir = tmp_path / "mod"
    _create_fake_pizzaoven_mod(mod_dir)
    _write_text(mod_dir / "a" / ".disable_gb1click_pizzaoven", "")
    _write_text(mod_dir / "b" / ".disable_gb1click_pizzaovenplus", "")

    inspection = service.inspect_source(str(mod_dir))

    assert inspection.eligible is False
    assert inspection.disable_pizzaoven is True
    assert inspection.disable_pizzaovenplus is True


def test_inspect_source_allows_conversion_with_only_one_pizzaoven_disable_flag(tmp_path):
    """Checks that inspecting source allows conversion with only one pizzaoven disable flag."""
    service = PizzaOvenConversionService(FakePizzaOvenG3MTool())
    mod_dir = tmp_path / "mod"
    _create_fake_pizzaoven_mod(mod_dir)
    _write_text(mod_dir / ".disable_gb1click_pizzaoven", "")

    inspection = service.inspect_source(str(mod_dir))

    assert inspection.eligible is True
    assert inspection.disable_pizzaoven is True
    assert inspection.disable_pizzaovenplus is False


def test_inspect_source_rejects_non_normal_pizzaoven_mods(tmp_path):
    """Checks that inspecting source rejects non normal pizzaoven mods."""
    service = PizzaOvenConversionService(FakePizzaOvenG3MTool())

    gmloader_dir = tmp_path / "gmloader"
    _write_text(gmloader_dir / "mod.json", json.dumps({"cat": "GMLoader"}))
    _write_text(gmloader_dir / "code" / "script.gml", "show_debug_message('x');")

    afom_dir = tmp_path / "afom"
    _write_text(afom_dir / "levels" / "test.json", "{}")
    _write_text(afom_dir / "levels" / "test.ini", "[level]\n")

    gmloader_inspection = service.inspect_source(str(gmloader_dir))
    afom_inspection = service.inspect_source(str(afom_dir))

    assert gmloader_inspection.eligible is False
    assert gmloader_inspection.mod_type == "GMLOADER"
    assert afom_inspection.eligible is False
    assert afom_inspection.mod_type == "AFOM"


def test_presenter_should_offer_conversion_hides_non_pizzatower_game(tmp_path):
    """Checks that presentering should offer conversion hides non pizzatower game."""
    conversion_service = Mock()
    conversion_service.inspect_source.return_value = SimpleNamespace(eligible=True)
    presenter = PizzaOvenConversionPresenter(
        app_state=Mock(),
        feedback_service=Mock(),
        settings_service=Mock(),
        mod_service=Mock(),
        conversion_service=conversion_service,
    )

    assert presenter.should_offer_conversion(str(tmp_path), {"game": "undertale"}) is False
    assert presenter.should_offer_conversion(str(tmp_path), {"game": "pizzatower"}) is True


def test_presenter_reuses_existing_valid_pizzatower_path_without_prompt(tmp_path):
    """Checks that presenter reuses existing valid pizzatower path without prompt."""
    game = get_game("pizzatower")
    app_state = Mock()
    app_state.local_config = {}
    app_state.game_mode = get_game("deltarune")
    game.set_game_path(app_state.local_config, str(tmp_path))
    conversion_service = Mock()
    conversion_service.validate_game_path.return_value = None
    settings_service = Mock()
    presenter = PizzaOvenConversionPresenter(
        app_state=app_state,
        feedback_service=Mock(),
        settings_service=settings_service,
        mod_service=Mock(),
        conversion_service=conversion_service,
    )

    from presentation import pizza_oven_conversion_presenter as presenter_module

    original_is_valid = presenter_module.is_valid_game_path
    presenter_module.is_valid_game_path = lambda *args, **kwargs: True
    try:
        resolved = presenter._ensure_valid_pizzatower_path(parent=None)
    finally:
        presenter_module.is_valid_game_path = original_is_valid

    assert resolved == str(tmp_path)
    conversion_service.validate_game_path.assert_called_once_with(str(tmp_path))
    settings_service.prompt_for_game_path.assert_not_called()


def test_presenter_conversion_finished_suppresses_broken_feedback(tmp_path, monkeypatch):
    """Checks conversion completion cannot crash when feedback UI is gone."""
    app_state = Mock()
    app_state.reset_install_state = Mock()
    feedback_service = Mock()
    feedback_service.update_status.side_effect = RuntimeError("status deleted")
    feedback_service.show_message.side_effect = RuntimeError("toast deleted")
    mod_service = Mock()
    worker = Mock()
    result = SimpleNamespace(mod_dir=str(tmp_path / "Converted Mod"))
    presenter = PizzaOvenConversionPresenter(
        app_state=app_state,
        feedback_service=feedback_service,
        settings_service=Mock(),
        mod_service=mod_service,
        conversion_service=Mock(),
    )
    presenter._active_workers.add(worker)
    monkeypatch.setattr(
        "presentation.pizza_oven_conversion_presenter.QMessageBox.information",
        Mock(side_effect=RuntimeError("dialog deleted")),
    )

    presenter._on_conversion_finished(
        parent=None,
        success=True,
        payload=result.mod_dir,
        result=result,
        temp_dir=None,
        on_success=None,
        worker=worker,
    )


def test_presenter_run_conversion_flow_starts_worker_without_manual_status_push(
    tmp_path, monkeypatch
):
    """Checks conversion start relies on worker wiring without manual status push."""
    app_state = Mock()
    app_state.mods_dir = str(tmp_path / "mods")
    feedback_service = Mock()
    presenter = PizzaOvenConversionPresenter(
        app_state=app_state,
        feedback_service=feedback_service,
        settings_service=Mock(),
        mod_service=Mock(),
        conversion_service=Mock(),
    )
    monkeypatch.setattr(
        presenter,
        "_ensure_valid_pizzatower_path",
        lambda parent: str(tmp_path / "game"),
    )

    class _Dialog:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def exec(self):
            from PyQt6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

    class _Worker:
        def __init__(self, *_args, **_kwargs) -> None:
            self.progress = SimpleNamespace(connect=lambda _fn: None)
            self.status = SimpleNamespace(connect=lambda _fn: None)
            self.conversion_finished = SimpleNamespace(connect=lambda _fn: None)

        def start(self):
            return None

    monkeypatch.setattr(
        "ui.dialogs.pizza_oven_conversion_dialog.PizzaOvenConversionDialog",
        _Dialog,
    )
    monkeypatch.setattr(
        "presentation.pizza_oven_conversion_presenter.PizzaOvenConversionWorker",
        _Worker,
    )

    result = presenter._run_conversion_flow(
        parent=None,
        prepared_path=str(tmp_path / "prepared"),
        source_file_path=None,
        temp_dir=None,
        gamebanana_metadata={},
        on_success=None,
    )

    assert result is True
    feedback_service.update_status.assert_not_called()


def test_presenter_worker_status_suppresses_broken_feedback(tmp_path, monkeypatch):
    """Checks worker status signals cannot crash when feedback UI is gone."""
    from PyQt6.QtWidgets import QDialog

    from presentation import pizza_oven_conversion_presenter as presenter_module

    class _Signal:
        def __init__(self) -> None:
            self.callback = None

        def connect(self, callback):
            self.callback = callback

        def emit(self, *args):
            self.callback(*args)

    class _FakeWorker:
        last = None

        def __init__(self, *_args, **_kwargs) -> None:
            self.progress = _Signal()
            self.status = _Signal()
            self.conversion_finished = _Signal()
            _FakeWorker.last = self

        def start(self):
            return None

    class _AcceptedDialog:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

    app_state = Mock()
    app_state.mods_dir = str(tmp_path / "mods")
    app_state.local_config = {}
    app_state.game_mode = get_game("deltarune")
    feedback_service = Mock()
    feedback_service.update_status.side_effect = RuntimeError("status deleted")
    presenter = PizzaOvenConversionPresenter(
        app_state=app_state,
        feedback_service=feedback_service,
        settings_service=Mock(),
        mod_service=Mock(),
        conversion_service=Mock(),
    )
    monkeypatch.setattr(
        "ui.dialogs.pizza_oven_conversion_dialog.PizzaOvenConversionDialog",
        _AcceptedDialog,
    )
    monkeypatch.setattr(presenter, "_ensure_valid_pizzatower_path", lambda _parent: "game")
    monkeypatch.setattr(presenter_module, "PizzaOvenConversionWorker", _FakeWorker)

    assert presenter._run_conversion_flow(
        parent=None,
        prepared_path=str(tmp_path / "prepared"),
        source_file_path=None,
        temp_dir=None,
        gamebanana_metadata={},
    )
    _FakeWorker.last.status.emit("working", "status_info")

    feedback_service.update_status.assert_any_call("working", "status_info")


def test_pizza_oven_worker_suppresses_emit_failure_after_conversion_error(caplog):
    """Checks that conversion errors cannot crash while notifying a dead UI."""
    from services.pizza_oven_conversion_service import PizzaOvenConversionError
    from workers.install.pizza_oven_conversion_worker import PizzaOvenConversionWorker

    class _Service:
        def convert(self, *_args, **_kwargs):
            raise PizzaOvenConversionError("conversion failed")

    class _FailingSignal:
        def emit(self, *_args, **_kwargs):
            raise RuntimeError("receiver deleted")

    worker = PizzaOvenConversionWorker(
        _Service(),
        source_dir="source",
        mods_dir="mods",
        game_path="game",
    )
    worker.conversion_finished = _FailingSignal()

    worker.run()

    assert "PizzaOvenConversionWorker: failed to emit" in caplog.text


def test_convert_builds_canonical_g3m_mod_from_pizzaoven_result(tmp_path):
    """Checks that converting builds canonical g3m mod from pizzaoven result."""
    game_dir = tmp_path / "game"
    mod_dir = tmp_path / "mod"
    mods_dir = tmp_path / "mods"
    _create_fake_pizzatower_game(game_dir)
    _create_fake_pizzaoven_mod(mod_dir)

    service = PizzaOvenConversionService(FakePizzaOvenG3MTool())

    result = service.convert(
        str(mod_dir),
        str(mods_dir),
        str(game_dir),
        source_file_path=str(mod_dir),
    )

    target_mod_dir = Path(result.mod_dir)
    config = json.loads((target_mod_dir / "mod_config.json").read_text("utf-8"))
    chapter_data = config["files"]["pizzatower"]
    extra_files = _extra_files_to_map(chapter_data["extra_files"])

    assert chapter_data["data_file_path"] == "data.g3mpatch"
    assert (target_mod_dir / "data.g3mpatch").exists()
    assert extra_files["root"] == ["helper.dll", "noisecredits.txt"]
    assert set(extra_files["lang"]) == {"lang/english.txt", "lang/custom.def"}
    assert extra_files["lang/graphics"] == [
        "lang/graphics/english.json",
        "lang/graphics/english.png",
    ]
    assert extra_files["lang/fonts"] == ["lang/fonts/tutorial_english.png"]
    assert extra_files["sound/Desktop/music"] == ["sound/Desktop/music/custom.bank"]
    assert (target_mod_dir / "Install Instructions.txt").exists()


def test_converted_mod_applies_expected_files_to_clean_game(
    tmp_path, app_state, monkeypatch
):
    """Checks that converteding mod applies expected files to clean game."""
    game_dir = tmp_path / "game"
    mod_dir = tmp_path / "mod"
    mods_dir = tmp_path / "mods"
    user_data_dir = tmp_path / "user_data"
    _create_fake_pizzatower_game(game_dir)
    _create_fake_pizzaoven_mod(mod_dir)

    fake_tool = FakePizzaOvenG3MTool()
    service = PizzaOvenConversionService(fake_tool)
    result = service.convert(
        str(mod_dir),
        str(mods_dir),
        str(game_dir),
        source_file_path=str(mod_dir),
    )

    apply_game_dir = tmp_path / "apply_game"
    os.makedirs(apply_game_dir, exist_ok=True)
    for item in game_dir.iterdir():
        target = apply_game_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            target.write_bytes(item.read_bytes())

    app_state.game_mode = get_game("pizzatower")
    app_state.local_config = {}
    app_state.mods_dir = str(mods_dir)
    monkeypatch.setattr(
        "services.g3mtool_patching_service.get_user_data_root",
        lambda: str(user_data_dir),
    )
    mod_service = Mock()
    mod_service.get_mod_folder_path.return_value = str(result.mod_dir)
    patcher = G3MToolPatchingService(app_state, mod_service)
    patcher.g3mtool = fake_tool
    patcher.warning_handler = Mock(return_value=False)
    patcher.set_override_game_path(str(apply_game_dir))

    mod_config = json.loads((Path(result.mod_dir) / "mod_config.json").read_text("utf-8"))
    mod_data = SimpleNamespace(
        id=mod_config["metadata"]["id"],
        name=mod_config["metadata"]["name"],
        game="pizzatower",
    )

    success = patcher.process_mod_patch({"pizzatower": [mod_data]})

    assert success is True
    assert (apply_game_dir / "data.win").read_bytes() == b"ORIGINAL_DATA|po-patched|"
    assert (apply_game_dir / "helper.dll").read_bytes() == b"DLL_PAYLOAD"
    assert (apply_game_dir / "noisecredits.txt").read_text("utf-8") == "Credits go here\n"
    assert (apply_game_dir / "lang" / "english.txt").read_text("utf-8") == 'lang = "english"\n'
    assert (apply_game_dir / "lang" / "custom.def").read_text("utf-8") == "font definition\n"
    assert (apply_game_dir / "lang" / "graphics" / "english.json").read_text("utf-8") == '{"font":"english"}'
    assert (apply_game_dir / "lang" / "graphics" / "english.png").read_bytes() == b"PNG_GRAPHICS"
    assert (apply_game_dir / "lang" / "fonts" / "tutorial_english.png").read_bytes() == b"PNG_FONT"
    assert (apply_game_dir / "sound" / "Desktop" / "music" / "custom.bank").read_bytes() == b"CUSTOM_BANK"
