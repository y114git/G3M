"""Unit tests for test modding tools dialog."""

import json
import os
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6.QtWidgets import QApplication

from services.localization_service import tr
from ui.dialogs.modding_tools_dialog import (
    ModdingToolsDialog,
    _ConvertWorkerThread,
    _CreatePatchWorkerThread,
    _DataConvertTab,
    _DataConvertWorkerThread,
    _MergeTab,
    _PatchTab,
)


def test_patch_tab_warning_failure_does_not_start_worker(monkeypatch):
    """Checks validation warning failures do not start patch workers."""
    app = QApplication.instance() or QApplication([])
    tab = _PatchTab(_FakeG3M(), SimpleNamespace(local_config={}))
    monkeypatch.setattr(
        "ui.dialogs.modding_tools_dialog.QMessageBox.warning",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("dialog deleted")),
    )

    tab._on_run()

    assert tab._run_btn.isEnabled()
    assert getattr(tab, "_worker", None) is None
    app.processEvents()


def test_patch_tab_progress_ignores_deleted_status_label():
    """Checks progress updates cannot crash when the status label is deleted."""
    app = QApplication.instance() or QApplication([])
    tab = _PatchTab(_FakeG3M(), SimpleNamespace(local_config={}))
    tab._status_label.setText = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("status deleted")
    )

    tab._on_progress(25, "Working")

    app.processEvents()


def test_modding_tools_close_question_failure_keeps_dialog_open(monkeypatch):
    """Checks failed close confirmation keeps active tool state open."""
    app = QApplication.instance() or QApplication([])
    dialog = ModdingToolsDialog(_FakeG3M(), SimpleNamespace(local_config={}))
    event = SimpleNamespace(ignore=Mock(), accept=Mock())
    monkeypatch.setattr(dialog, "_has_any_interaction", lambda: True)
    stop_workers = Mock()
    monkeypatch.setattr(dialog, "_stop_all_workers", stop_workers)
    monkeypatch.setattr(
        "ui.dialogs.modding_tools_dialog.QMessageBox.question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("dialog deleted")),
    )

    dialog.closeEvent(event)

    event.ignore.assert_called_once_with()
    event.accept.assert_not_called()
    stop_workers.assert_not_called()
    dialog.deleteLater()
    app.processEvents()


class _FakeG3M:
    _PATCH_PREFIX = b"PATCH|"
    _XPATCH_PREFIX = b"XPATCH|"

    @staticmethod
    def _emit_progress(progress_callback, label) -> None:
        if progress_callback:
            progress_callback(1, label)
            progress_callback(2, label)
            progress_callback(4, label)
            progress_callback(100, label)

    def apply_patch(self, original, patch, output, progress_callback=None):
        self._emit_progress(progress_callback, "Applying patch")
        with open(patch, "rb") as handle:
            payload = handle.read()
        if payload.startswith(self._PATCH_PREFIX):
            with open(output, "wb") as f:
                f.write(payload[len(self._PATCH_PREFIX) :])
            return 0, "", ""
        with open(output, "w", encoding="utf-8") as f:
            f.write(f"{original}|{patch}")
        return 0, "", ""

    def xpatch_apply(self, original, patch, output, progress_callback=None):
        self._emit_progress(progress_callback, "Applying xdelta")
        with open(patch, "rb") as handle:
            payload = handle.read()
        if payload.startswith(self._XPATCH_PREFIX):
            with open(output, "wb") as f:
                f.write(payload[len(self._XPATCH_PREFIX) :])
            return 0, "", ""
        with open(output, "w", encoding="utf-8") as f:
            f.write(f"{original}|{patch}")
        return 0, "", ""

    def patch_create(
        self,
        original,
        modified,
        output,
        include_xdelta_fallback=False,
        progress_callback=None,
    ):
        self._emit_progress(progress_callback, "Creating patch")
        with open(modified, "rb") as handle:
            payload = handle.read()
        with open(output, "wb") as f:
            f.write(self._PATCH_PREFIX + payload)
        return 0, "", ""

    def xpatch_create(self, original, modified, output, progress_callback=None):
        self._emit_progress(progress_callback, "Creating xdelta")
        with open(modified, "rb") as handle:
            payload = handle.read()
        with open(output, "wb") as f:
            f.write(self._XPATCH_PREFIX + payload)
        return 0, "", ""

    def execute(
        self,
        target,
        args=None,
        data_file=None,
        output_path=None,
        input_path=None,
        progress_callback=None,
    ):
        self._emit_progress(progress_callback, "Executing")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"{target}|{data_file}|{input_path}|{args}")
        return 0, "", ""

    def merge_patches(
        self,
        original_data_win,
        mod_patches,
        output_path,
        report_path=None,
        log_path=None,
        merge_code=False,
        merge_properties=False,
        progress_callback=None,
    ):
        self._emit_progress(progress_callback, "Merging")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("|".join([original_data_win, *mod_patches]))
        return 0, "", ""

    def info(self, target, verbose=False, progress_callback=None):
        self._emit_progress(progress_callback, "Reading info")
        return 0, f"info:{target}:{verbose}", ""

    def diff(self, file1, file2, output_dir=None, progress_callback=None):
        self._emit_progress(progress_callback, "Diffing")
        return 0, f"diff:{file1}:{file2}:{output_dir}", ""

    def is_available(self):
        return True


class _LossyFakeG3M(_FakeG3M):
    def patch_create(self, original, modified, output):
        with open(output, "w", encoding="utf-8") as f:
            f.write("lossy patch")
        return 0, "", ""

    def apply_patch(self, original, patch, output):
        with open(output, "w", encoding="utf-8") as f:
            f.write("broken output")
        return 0, "", ""


def test_data_convert_tab_blocks_controls_while_busy(monkeypatch):
    """Checks that DATA conversion tab blocks controls while busy."""
    app = QApplication.instance() or QApplication([])

    monkeypatch.setattr(_DataConvertTab, "_populate_profiles", lambda self: None)
    tab = _DataConvertTab(_FakeG3M(), SimpleNamespace(local_config={}))
    monkeypatch.setattr(tab, "_scan_mods", lambda *_: tab._run_btn.setEnabled(True))

    assert tab._profile_combo.toolTip() == tr("tooltips.profile_combo")
    assert tab._fmt_combo.toolTip() == tr("tooltips.modding_tools_target_format")
    assert tab._mod_list.toolTip() == tr("tooltips.modding_tools_mod_list")
    assert tab._run_btn.toolTip() == tr("tooltips.run_tool")

    tab._set_busy(True)

    assert not tab._profile_combo.isEnabled()
    assert not tab._fmt_combo.isEnabled()
    assert not tab._mod_list.isEnabled()
    assert not tab._run_btn.isEnabled()

    tab._set_busy(False)

    assert tab._profile_combo.isEnabled()
    assert tab._fmt_combo.isEnabled()
    assert tab._mod_list.isEnabled()
    assert tab._run_btn.isEnabled()
    app.processEvents()


def test_data_convert_creates_new_version_without_overwriting_mod(
    tmp_path, monkeypatch
):
    """Checks that DATA conversion creates new version without overwriting mod."""
    mod_folder = tmp_path / "mod"
    versions_dir = mod_folder / "mod_versions"
    mod_folder.mkdir(parents=True)
    versions_dir.mkdir()
    patch_path = mod_folder / "data.xdelta"
    patch_path.write_text("old patch", encoding="utf-8")
    config_path = mod_folder / "mod_config.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "game": "deltarune",
                "files": {"deltarune_1": {"data_file_path": "data.xdelta"}},
            }
        ),
        encoding="utf-8",
    )
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    original_path = game_dir / "data.win"
    original_path.write_text("original", encoding="utf-8")

    monkeypatch.setattr(
        "models.game_modes.get_game",
        lambda game: SimpleNamespace(
            get_tab=lambda file_key: SimpleNamespace(tab_id=file_key)
        ),
    )
    monkeypatch.setattr(
        "utils.mod.config_parser.resolve_mod_file_path",
        lambda folder, stored_path: str(mod_folder / stored_path),
    )
    monkeypatch.setattr(
        "utils.path_utils.find_chapter_resource_dir",
        lambda game_path, chapter_id: str(game_dir),
    )

    worker = _DataConvertWorkerThread(
        _FakeG3M(),
        str(mod_folder),
        {
            "version": "1.2.3",
            "game": "deltarune",
            "files": {"deltarune_1": {"data_file_path": "data.xdelta"}},
        },
        str(tmp_path / "game_root"),
        "g3mpatch",
    )
    result = []
    worker.finished.connect(lambda success, message: result.append((success, message)))

    worker.run()

    assert len(result) == 1, "Expected exactly one finished signal emission"
    assert result[0][0] is True, f"Conversion failed: {result[0][1]}"
    assert patch_path.read_text(encoding="utf-8") == "old patch"
    assert (
        json.loads(config_path.read_text(encoding="utf-8"))["files"]["deltarune_1"][
            "data_file_path"
        ]
        == "data.xdelta"
    )

    version_zip = versions_dir / "1.2.3 - g3mpatch.zip"
    assert version_zip.is_file()
    with zipfile.ZipFile(version_zip) as zf:
        assert "data.g3mpatch" in zf.namelist()
        converted_config = json.loads(zf.read("mod_config.json").decode("utf-8"))
    assert converted_config["files"]["deltarune_1"]["data_file_path"] == "data.g3mpatch"


def test_data_convert_accepts_g3mpatch_zip_as_source(tmp_path, monkeypatch):
    """Checks that DATA conversion accepts g3mpatch zip as source."""
    mod_folder = tmp_path / "mod"
    versions_dir = mod_folder / "mod_versions"
    mod_folder.mkdir(parents=True)
    versions_dir.mkdir()
    patch_zip = mod_folder / "data.zip"
    with zipfile.ZipFile(patch_zip, "w") as zf:
        zf.writestr("g3mpatch.json", json.dumps({"original": {"md5": "abc"}}))
    config_path = mod_folder / "mod_config.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "game": "deltarune",
                "files": {"deltarune_1": {"data_file_path": "data.zip"}},
            }
        ),
        encoding="utf-8",
    )
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    original_path = game_dir / "data.win"
    original_path.write_text("original", encoding="utf-8")

    monkeypatch.setattr(
        "models.game_modes.get_game",
        lambda game: SimpleNamespace(
            get_tab=lambda file_key: SimpleNamespace(tab_id=file_key)
        ),
    )
    monkeypatch.setattr(
        "utils.mod.config_parser.resolve_mod_file_path",
        lambda folder, stored_path: str(mod_folder / stored_path),
    )
    monkeypatch.setattr(
        "utils.path_utils.find_chapter_resource_dir",
        lambda game_path, chapter_id: str(game_dir),
    )

    worker = _DataConvertWorkerThread(
        _FakeG3M(),
        str(mod_folder),
        {
            "version": "1.2.3",
            "game": "deltarune",
            "files": {"deltarune_1": {"data_file_path": "data.zip"}},
        },
        str(tmp_path / "game_root"),
        "xdelta",
    )
    result = []
    worker.finished.connect(lambda success, message: result.append((success, message)))

    worker.run()

    assert result == [
        (True, tr("modding_tools.convert_data_success", count=1, version="1.2.3 - xdelta"))
    ]
    version_zip = versions_dir / "1.2.3 - xdelta.zip"
    assert version_zip.is_file()
    with zipfile.ZipFile(version_zip) as zf:
        assert "data.xdelta" in zf.namelist()
        converted_config = json.loads(zf.read("mod_config.json").decode("utf-8"))
    assert converted_config["files"]["deltarune_1"]["data_file_path"] == "data.xdelta"


def test_data_convert_can_output_game_win(tmp_path, monkeypatch):
    """Checks that DATA conversion can write game.win as a ready DATA target."""
    mod_folder = tmp_path / "mod"
    versions_dir = mod_folder / "mod_versions"
    mod_folder.mkdir(parents=True)
    versions_dir.mkdir()
    patch_path = mod_folder / "data.xdelta"
    patch_path.write_text("old patch", encoding="utf-8")
    config_path = mod_folder / "mod_config.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "game": "deltarune",
                "files": {"deltarune_1": {"data_file_path": "data.xdelta"}},
            }
        ),
        encoding="utf-8",
    )
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "game.win").write_text("original", encoding="utf-8")

    monkeypatch.setattr(
        "models.game_modes.get_game",
        lambda game: SimpleNamespace(
            get_tab=lambda file_key: SimpleNamespace(tab_id=file_key)
        ),
    )
    monkeypatch.setattr(
        "utils.mod.config_parser.resolve_mod_file_path",
        lambda folder, stored_path: str(mod_folder / stored_path),
    )
    monkeypatch.setattr(
        "utils.path_utils.find_chapter_resource_dir",
        lambda game_path, chapter_id: str(game_dir),
    )

    worker = _DataConvertWorkerThread(
        _FakeG3M(),
        str(mod_folder),
        {
            "version": "1.2.3",
            "game": "deltarune",
            "files": {"deltarune_1": {"data_file_path": "data.xdelta"}},
        },
        str(tmp_path / "game_root"),
        "game.win",
    )
    result = []
    worker.finished.connect(lambda success, message: result.append((success, message)))

    worker.run()

    assert result == [
        (True, tr("modding_tools.convert_data_success", count=1, version="1.2.3 - game.win"))
    ]
    version_zip = versions_dir / "1.2.3 - game.win.zip"
    assert version_zip.is_file()
    with zipfile.ZipFile(version_zip) as zf:
        assert "game.win" in zf.namelist()
        converted_config = json.loads(zf.read("mod_config.json").decode("utf-8"))
    assert converted_config["files"]["deltarune_1"]["data_file_path"] == "game.win"


def test_data_convert_accepts_csx_source(tmp_path, monkeypatch):
    """Checks that data convert accepts csx script sources."""
    mod_folder = tmp_path / "mod"
    versions_dir = mod_folder / "mod_versions"
    mod_folder.mkdir(parents=True)
    versions_dir.mkdir()
    script_path = mod_folder / "data.csx"
    script_path.write_text("// fake script", encoding="utf-8")
    config_path = mod_folder / "mod_config.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "game": "deltarune",
                "files": {"deltarune_1": {"data_file_path": "data.csx"}},
            }
        ),
        encoding="utf-8",
    )
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "data.win").write_text("original", encoding="utf-8")

    monkeypatch.setattr(
        "models.game_modes.get_game",
        lambda game: SimpleNamespace(
            get_tab=lambda file_key: SimpleNamespace(tab_id=file_key)
        ),
    )
    monkeypatch.setattr(
        "utils.mod.config_parser.resolve_mod_file_path",
        lambda folder, stored_path: str(mod_folder / stored_path),
    )
    monkeypatch.setattr(
        "utils.path_utils.find_chapter_resource_dir",
        lambda game_path, chapter_id: str(game_dir),
    )

    worker = _DataConvertWorkerThread(
        _FakeG3M(),
        str(mod_folder),
        {
            "version": "1.2.3",
            "game": "deltarune",
            "files": {"deltarune_1": {"data_file_path": "data.csx"}},
        },
        str(tmp_path / "game_root"),
        "g3mpatch",
    )
    result = []
    worker.finished.connect(lambda success, message: result.append((success, message)))

    worker.run()

    assert result == [
        (True, tr("modding_tools.convert_data_success", count=1, version="1.2.3 - g3mpatch"))
    ]
    version_zip = versions_dir / "1.2.3 - g3mpatch.zip"
    with zipfile.ZipFile(version_zip) as zf:
        assert "data.g3mpatch" in zf.namelist()
        converted_config = json.loads(zf.read("mod_config.json").decode("utf-8"))
    assert converted_config["files"]["deltarune_1"]["data_file_path"] == "data.g3mpatch"


def test_data_convert_preserves_chapter_relative_path_in_converted_config(
    tmp_path, monkeypatch
):
    """Checks that chapter-scoped conversions keep chapter folders in mod_config."""
    mod_folder = tmp_path / "mod"
    versions_dir = mod_folder / "mod_versions"
    patch_dir = mod_folder / "chapter_3"
    patch_dir.mkdir(parents=True)
    versions_dir.mkdir()
    patch_path = patch_dir / "data.xdelta"
    patch_path.write_text("old patch", encoding="utf-8")
    config_path = mod_folder / "mod_config.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "game": "deltarune",
                "files": {"deltarune_3": {"data_file_path": "chapter_3/data.xdelta"}},
            }
        ),
        encoding="utf-8",
    )
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "data.win").write_text("original", encoding="utf-8")

    monkeypatch.setattr(
        "models.game_modes.get_game",
        lambda game: SimpleNamespace(
            get_tab=lambda file_key: SimpleNamespace(tab_id=file_key)
        ),
    )
    monkeypatch.setattr(
        "utils.mod.config_parser.resolve_mod_file_path",
        lambda folder, stored_path: str(mod_folder / stored_path),
    )
    monkeypatch.setattr(
        "utils.path_utils.find_chapter_resource_dir",
        lambda game_path, chapter_id: str(game_dir),
    )

    worker = _DataConvertWorkerThread(
        _FakeG3M(),
        str(mod_folder),
        {
            "version": "1.2.3",
            "game": "deltarune",
            "files": {"deltarune_3": {"data_file_path": "chapter_3/data.xdelta"}},
        },
        str(tmp_path / "game_root"),
        "g3mpatch",
    )
    result = []
    worker.finished.connect(lambda success, message: result.append((success, message)))

    worker.run()

    assert result == [
        (True, tr("modding_tools.convert_data_success", count=1, version="1.2.3 - g3mpatch"))
    ]
    version_zip = versions_dir / "1.2.3 - g3mpatch.zip"
    with zipfile.ZipFile(version_zip) as zf:
        assert "chapter_3/data.g3mpatch" in zf.namelist()
        converted_config = json.loads(zf.read("mod_config.json").decode("utf-8"))
    assert (
        converted_config["files"]["deltarune_3"]["data_file_path"]
        == "chapter_3/data.g3mpatch"
    )


def test_data_convert_reports_localized_filesystem_error(tmp_path, monkeypatch):
    """Checks that data convert surfaces localized filesystem errors."""
    mod_folder = tmp_path / "mod"
    mod_folder.mkdir()
    missing_path = os.path.join(str(mod_folder), "data.win")
    monkeypatch.setattr(
        "utils.mod.config_parser.resolve_mod_file_path",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            FileNotFoundError(2, "No such file", missing_path)
        ),
    )

    worker = _DataConvertWorkerThread(
        _FakeG3M(),
        str(mod_folder),
        {
            "version": "1.2.3",
            "game": "deltarune",
            "files": {"deltarune_1": {"data_file_path": "data.win"}},
        },
        str(tmp_path / "game_root"),
        "xdelta",
    )
    result = []
    worker.finished.connect(lambda success, message: result.append((success, message)))

    worker.run()

    assert result == [(False, tr("errors.file_not_found", path=missing_path))]


def test_convert_worker_keeps_generated_patch_even_if_roundtrip_would_fail(tmp_path):
    """Checks that converting keeps the generated patch without local verification."""
    original_path = tmp_path / "original.win"
    source_patch = tmp_path / "source.xdelta"
    output_path = tmp_path / "converted.g3mpatch"
    original_path.write_text("original", encoding="utf-8")
    source_patch.write_text("source patch", encoding="utf-8")

    worker = _ConvertWorkerThread(
        _LossyFakeG3M(),
        str(original_path),
        str(source_patch),
        str(output_path),
        False,
    )
    result = []
    worker.finished.connect(lambda rc, out, err: result.append((rc, out, err)))

    worker.run()

    assert result == [(0, "", "")]
    assert output_path.exists()


def test_create_patch_worker_keeps_generated_patch_even_if_roundtrip_would_fail(tmp_path):
    """Checks that patch create keeps the generated patch without local verification."""
    original_path = tmp_path / "original.win"
    modified_path = tmp_path / "modified.win"
    output_path = tmp_path / "created.g3mpatch"
    original_path.write_text("original", encoding="utf-8")
    modified_path.write_text("modified", encoding="utf-8")

    worker = _CreatePatchWorkerThread(
        _LossyFakeG3M(),
        str(original_path),
        str(modified_path),
        str(output_path),
        False,
    )
    result = []
    worker.finished.connect(lambda rc, out, err: result.append((rc, out, err)))

    worker.run()

    assert result == [(0, "", "")]
    assert output_path.exists()


def test_data_convert_allows_generated_patch_without_roundtrip_check(tmp_path, monkeypatch):
    """Checks that data convert keeps generated patches without local verification."""
    mod_folder = tmp_path / "mod"
    versions_dir = mod_folder / "mod_versions"
    mod_folder.mkdir(parents=True)
    versions_dir.mkdir()
    patch_path = mod_folder / "data.xdelta"
    patch_path.write_text("old patch", encoding="utf-8")
    config_path = mod_folder / "mod_config.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "game": "deltarune",
                "files": {"deltarune_1": {"data_file_path": "data.xdelta"}},
            }
        ),
        encoding="utf-8",
    )
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "data.win").write_text("original", encoding="utf-8")

    monkeypatch.setattr(
        "models.game_modes.get_game",
        lambda game: SimpleNamespace(
            get_tab=lambda file_key: SimpleNamespace(tab_id=file_key)
        ),
    )
    monkeypatch.setattr(
        "utils.mod.config_parser.resolve_mod_file_path",
        lambda folder, stored_path: str(mod_folder / stored_path),
    )
    monkeypatch.setattr(
        "utils.path_utils.find_chapter_resource_dir",
        lambda game_path, chapter_id: str(game_dir),
    )

    worker = _DataConvertWorkerThread(
        _LossyFakeG3M(),
        str(mod_folder),
        {
            "version": "1.2.3",
            "game": "deltarune",
            "files": {"deltarune_1": {"data_file_path": "data.xdelta"}},
        },
        str(tmp_path / "game_root"),
        "g3mpatch",
    )
    result = []
    worker.finished.connect(lambda success, message: result.append((success, message)))

    worker.run()

    assert result == [
        (True, tr("modding_tools.convert_data_success", count=1, version="1.2.3 - g3mpatch"))
    ]
    version_zip = versions_dir / "1.2.3 - g3mpatch.zip"
    assert version_zip.exists()
    with zipfile.ZipFile(version_zip) as zf:
        assert "data.g3mpatch" in zf.namelist()


def test_patch_tab_suggests_output_extension(monkeypatch):
    """Checks that patch tab suggests obvious output names and extensions."""
    app = QApplication.instance() or QApplication([])

    tab = _PatchTab(_FakeG3M(), SimpleNamespace(local_config={}))
    tab._original_row.set_path("C:/mods/original.win")
    tab._second_row.set_path("C:/mods/modified.win")
    tab._action_combo.setCurrentIndex(0)
    tab._mode_combo.setCurrentIndex(0)

    assert tab._output_row.path().endswith("modified.g3mpatch")

    tab._action_combo.setCurrentIndex(2)
    tab._mode_combo.setCurrentIndex(1)
    tab._second_row.set_path("C:/mods/data.g3mpatch")

    assert tab._output_row.path().endswith("data.xdelta")
    app.processEvents()


def test_patch_tab_csx_apply_uses_execute(tmp_path):
    """Checks that patch tab applies csx scripts through g3mtool execute."""
    app = QApplication.instance() or QApplication([])

    calls = []

    class _RecordingG3M(_FakeG3M):
        def execute(
            self,
            target,
            args=None,
            data_file=None,
            output_path=None,
            input_path=None,
            progress_callback=None,
        ):
            calls.append((target, args, data_file, output_path, input_path))
            return super().execute(
                target,
                args,
                data_file,
                output_path,
                input_path,
                progress_callback,
            )

        def is_available(self):
            return True

    tab = _PatchTab(_RecordingG3M(), SimpleNamespace(local_config={}))
    input_data = tmp_path / "data.win"
    input_data.write_text("original", encoding="utf-8")
    script = tmp_path / "script.csx"
    script.write_text("// fake", encoding="utf-8")
    output_data = tmp_path / "patched.win"

    tab._mode_combo.setCurrentText("csx")
    tab._original_row.set_path(str(input_data))
    tab._second_row.set_path(str(script))
    tab._output_row.set_path(str(output_data))

    tab._on_run()
    tab._worker.wait(5000)
    app.processEvents()

    assert calls == [(str(script), None, str(input_data), str(output_data), None)]
    assert output_data.exists()


def test_merge_tab_suggests_patched_output_name():
    """Checks that merge tab suggests a merged data output file."""
    app = QApplication.instance() or QApplication([])

    tab = _MergeTab(_FakeG3M(), SimpleNamespace(local_config={}))
    tab._original_row.set_path("C:/game/data.win")

    assert tab._output_row.path().endswith("data_merged.win")
    app.processEvents()


def test_create_patch_worker_emits_incremental_progress(tmp_path):
    original_path = tmp_path / "original.win"
    modified_path = tmp_path / "modified.win"
    output_path = tmp_path / "created.g3mpatch"
    original_path.write_text("original", encoding="utf-8")
    modified_path.write_text("modified", encoding="utf-8")

    worker = _CreatePatchWorkerThread(
        _FakeG3M(),
        str(original_path),
        str(modified_path),
        str(output_path),
        False,
    )
    progress = []
    worker.progress.connect(lambda percent, label: progress.append((percent, label)))

    worker.run()

    assert progress == [
        (1, "Creating patch"),
        (2, "Creating patch"),
        (4, "Creating patch"),
        (100, "Creating patch"),
    ]


def test_convert_worker_maps_both_stages_into_smoother_progress(tmp_path):
    original_path = tmp_path / "original.win"
    source_patch = tmp_path / "source.xdelta"
    output_path = tmp_path / "converted.g3mpatch"
    original_path.write_text("original", encoding="utf-8")
    source_patch.write_text("source patch", encoding="utf-8")

    worker = _ConvertWorkerThread(
        _FakeG3M(),
        str(original_path),
        str(source_patch),
        str(output_path),
        False,
    )
    progress = []
    worker.progress.connect(lambda percent, label: progress.append((percent, label)))

    worker.run()

    assert progress == [
        (1, "Applying xdelta"),
        (1, "Applying xdelta"),
        (2, "Applying xdelta"),
        (50, "Applying xdelta"),
        (51, "Creating patch"),
        (51, "Creating patch"),
        (52, "Creating patch"),
        (100, "Creating patch"),
    ]


def test_patch_tab_updates_status_during_apply_progress(tmp_path):
    app = QApplication.instance() or QApplication([])

    tab = _PatchTab(_FakeG3M(), SimpleNamespace(local_config={}))
    input_data = tmp_path / "data.win"
    patch_file = tmp_path / "patch.g3mpatch"
    output_data = tmp_path / "patched.win"
    input_data.write_text("original", encoding="utf-8")

    with open(patch_file, "wb") as handle:
        handle.write(_FakeG3M._PATCH_PREFIX + b"patched")

    tab._mode_combo.setCurrentText("g3mpatch")
    tab._action_combo.setCurrentIndex(1)
    tab._original_row.set_path(str(input_data))
    tab._second_row.set_path(str(patch_file))
    tab._output_row.set_path(str(output_data))

    updates = []
    original_set_text = tab._status_label.setText

    def capture(text):
        updates.append(text)
        original_set_text(text)

    tab._status_label.setText = capture
    tab._on_run()
    tab._worker.wait(5000)
    app.processEvents()

    assert any("Applying patch: 1%" in text for text in updates)
    assert any("Applying patch: 4%" in text for text in updates)
    assert tab._status_label.text() == tr("modding_tools.success")
