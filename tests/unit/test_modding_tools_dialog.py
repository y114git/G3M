"""Unit tests for test modding tools dialog."""

import json
import os
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QListWidgetItem

from services.localization_service import tr
from ui.dialogs.modding_tools_dialog import (
    ModdingToolsDialog,
    _BatchDataConvertWorkerThread,
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
        patch_output_path=None,
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

    def batch_create_patches(
        self,
        original_data_win,
        modified_files,
        output_dir,
        continue_on_error=False,
        include_xdelta_fallback=False,
        progress_callback=None,
    ):
        self._emit_progress(progress_callback, "Batch creating")
        return 0, "", ""

    def batch_apply_patches(
        self,
        original_data_win,
        patch_paths,
        output_dir,
        continue_on_error=False,
        include_xdelta_fallback=False,
        progress_callback=None,
    ):
        self._emit_progress(progress_callback, "Batch applying")
        return 0, "", ""

    def batch_merge_patches(
        self,
        original_data_win,
        patch_sets,
        output_dir,
        patch_output_dir=None,
        continue_on_error=False,
        merge_code=False,
        merge_properties=False,
        write_report=False,
        progress_callback=None,
    ):
        self._emit_progress(progress_callback, "Batch merging")
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
    assert app is not None

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


def test_data_convert_tab_requires_available_g3mtool(monkeypatch, tmp_path):
    """Checks that DATA conversion stops before worker creation when tool is missing."""
    app = QApplication.instance() or QApplication([])

    class _UnavailableG3M(_FakeG3M):
        def is_available(self):
            return False

    monkeypatch.setattr(_DataConvertTab, "_populate_profiles", lambda self: None)
    monkeypatch.setattr(_DataConvertTab, "_scan_mods", lambda self: None)
    worker = Mock()
    monkeypatch.setattr(
        "ui.dialogs.modding_tools_dialog._BatchDataConvertWorkerThread", worker
    )
    tab = _DataConvertTab(_UnavailableG3M(), SimpleNamespace(local_config={}))
    mod_dir = tmp_path / "mod"
    mod_dir.mkdir()
    item = QListWidgetItem("Broken Tool Mod")
    item.setCheckState(Qt.CheckState.Checked)
    item.setData(Qt.ItemDataRole.UserRole, str(mod_dir))
    tab._mod_list.addItem(item)

    tab._on_run()

    assert tab._status_label.text() == tr("errors.g3mtool_not_available")
    worker.assert_not_called()
    app.processEvents()


def test_data_convert_tab_run_requires_checked_mod(monkeypatch, tmp_path):
    """Checks that DATA conversion uses checked mods instead of current row."""
    app = QApplication.instance() or QApplication([])

    monkeypatch.setattr(_DataConvertTab, "_populate_profiles", lambda self: None)
    tab = _DataConvertTab(_FakeG3M(), SimpleNamespace(local_config={}))
    mod_folder = tmp_path / "mod"
    mod_folder.mkdir()

    list_item = QListWidgetItem("Mod")
    list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
    list_item.setCheckState(Qt.CheckState.Unchecked)
    list_item.setData(Qt.ItemDataRole.UserRole, str(mod_folder))
    tab._mod_list.addItem(list_item)
    tab._update_run_state()

    assert not tab._run_btn.isEnabled()

    list_item.setCheckState(Qt.CheckState.Checked)
    tab._update_run_state()

    assert tab._run_btn.isEnabled()
    app.processEvents()


def test_batch_data_convert_worker_processes_all_jobs(tmp_path, monkeypatch):
    """Checks that batch DATA conversion runs every selected mod."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "data.win").write_text("original", encoding="utf-8")
    jobs = []
    for index in range(2):
        mod_folder = tmp_path / f"mod{index}"
        versions_dir = mod_folder / "mod_versions"
        mod_folder.mkdir()
        versions_dir.mkdir()
        (mod_folder / "data.xdelta").write_text(f"patch{index}", encoding="utf-8")
        jobs.append(
            {
                "mod_folder": str(mod_folder),
                "config_data": {
                    "version": "1.2.3",
                    "game": "deltarune",
                    "files": {"deltarune_1": {"data_file_path": "data.xdelta"}},
                },
                "game_path": str(tmp_path / "game_root"),
                "name": f"Mod {index}",
            }
        )

    monkeypatch.setattr(
        "models.game_modes.get_game",
        lambda game: SimpleNamespace(
            get_tab=lambda file_key: SimpleNamespace(tab_id=file_key)
        ),
    )
    monkeypatch.setattr(
        "utils.mod.config_parser.resolve_mod_file_path",
        lambda folder, stored_path: os.path.join(folder, stored_path),
    )
    monkeypatch.setattr(
        "utils.path_utils.find_chapter_resource_dir",
        lambda game_path, chapter_id: str(game_dir),
    )

    worker = _BatchDataConvertWorkerThread(_FakeG3M(), jobs, "g3mpatch")
    result = []
    worker.finished.connect(lambda success, message: result.append((success, message)))

    worker.run()

    assert result == [
        (True, tr("modding_tools.convert_batch_success", count=2, total=2))
    ]
    for job in jobs:
        version_zip = os.path.join(
            job["mod_folder"], "mod_versions", "1.2.3 - g3mpatch.zip"
        )
        assert os.path.isfile(version_zip)


def test_batch_data_convert_worker_warning_continue_skips_failed_job(monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []

    class _FakeConvertWorker(QObject):
        progress = pyqtSignal(str)
        finished = pyqtSignal(bool, str)

        def __init__(self, _g3m, mod_folder, *_args, **_kwargs) -> None:
            super().__init__()
            self._mod_folder = mod_folder

        def run(self):
            calls.append(self._mod_folder)
            if self._mod_folder == "bad":
                self.finished.emit(False, "xdelta failed")
            else:
                self.finished.emit(True, "ok")

    monkeypatch.setattr(
        "ui.dialogs.modding_tools_dialog._DataConvertWorkerThread",
        _FakeConvertWorker,
    )
    worker = _BatchDataConvertWorkerThread(
        _FakeG3M(),
        [
            {"mod_folder": "bad", "config_data": {}, "game_path": "", "name": "Bad"},
            {"mod_folder": "good", "config_data": {}, "game_path": "", "name": "Good"},
        ],
        "g3mpatch",
    )
    warnings = []
    result = []
    worker.warning_confirmation_needed.connect(
        lambda message, details, report: (
            warnings.append((message.warning_id, details, report)),
            worker.confirm_warning(True),
        )
    )
    worker.finished.connect(lambda success, message: result.append((success, message)))

    worker.run()

    assert calls == ["bad", "good"]
    assert warnings == [("xdelta_apply_failed", "xdelta failed", None)]
    assert result == [
        (True, tr("modding_tools.convert_batch_success", count=1, total=2))
    ]
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


def test_patch_tab_batch_create_uses_batch_adapter(tmp_path):
    app = QApplication.instance() or QApplication([])
    calls = []

    class _RecordingG3M(_FakeG3M):
        def batch_create_patches(
            self,
            original_data_win,
            modified_files,
            output_dir,
            continue_on_error=False,
            include_xdelta_fallback=False,
            progress_callback=None,
        ):
            calls.append(
                (
                    original_data_win,
                    modified_files,
                    output_dir,
                    continue_on_error,
                    include_xdelta_fallback,
                )
            )
            return super().batch_create_patches(
                original_data_win,
                modified_files,
                output_dir,
                continue_on_error,
                include_xdelta_fallback,
                progress_callback,
            )

    tab = _PatchTab(_RecordingG3M(), SimpleNamespace(local_config={}))
    original = tmp_path / "data.win"
    modified_a = tmp_path / "a.win"
    modified_b = tmp_path / "b.win"
    out_dir = tmp_path / "out"
    original.write_text("original", encoding="utf-8")
    modified_a.write_text("a", encoding="utf-8")
    modified_b.write_text("b", encoding="utf-8")

    tab._batch_cb.setChecked(True)
    tab._continue_cb.setChecked(True)
    tab._xdelta_fallback_checkbox.setChecked(True)
    tab._original_row.set_path(str(original))
    tab._batch_output_row.set_path(str(out_dir))
    for path in (modified_a, modified_b):
        item = QListWidgetItem(path.name)
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        tab._batch_list.addItem(item)

    tab._on_run()
    tab._worker.wait(5000)
    app.processEvents()

    assert calls == [
        (
            str(original),
            [str(modified_a), str(modified_b)],
            str(out_dir),
            True,
            True,
        )
    ]
    assert tab._status_label.text() == tr("modding_tools.success")


def test_merge_tab_suggests_patched_output_name():
    """Checks that merge tab suggests a merged data output file."""
    app = QApplication.instance() or QApplication([])

    tab = _MergeTab(_FakeG3M(), SimpleNamespace(local_config={}))
    tab._original_row.set_path("C:/game/data.win")

    assert tab._output_row.path().endswith("data_merged.win")
    app.processEvents()


def test_merge_tab_single_run_uses_report_and_merge_flags(tmp_path):
    app = QApplication.instance() or QApplication([])
    calls = []

    class _RecordingG3M(_FakeG3M):
        def merge_patches(
            self,
            original_data_win,
            mod_patches,
            output_path,
            patch_output_path=None,
            report_path=None,
            log_path=None,
            merge_code=False,
            merge_properties=False,
            progress_callback=None,
        ):
            calls.append(
                (
                    original_data_win,
                    mod_patches,
                    output_path,
                    patch_output_path,
                    report_path,
                    log_path,
                    merge_code,
                    merge_properties,
                )
            )
            return super().merge_patches(
                original_data_win,
                mod_patches,
                output_path,
                patch_output_path,
                report_path,
                log_path,
                merge_code,
                merge_properties,
                progress_callback,
            )

    tab = _MergeTab(_RecordingG3M(), SimpleNamespace(local_config={}))
    original = tmp_path / "data.win"
    patch_a = tmp_path / "a.g3mpatch"
    patch_b = tmp_path / "b.g3mpatch"
    output = tmp_path / "merged.win"
    patch_output = tmp_path / "merged.g3mpatch"
    for path in (original, patch_a, patch_b):
        path.write_text("data", encoding="utf-8")

    tab._code_cb.setChecked(True)
    tab._props_cb.setChecked(True)
    tab._report_cb.setChecked(True)
    tab._original_row.set_path(str(original))
    tab._output_row.set_path(str(output))
    tab._patch_output_row.set_path(str(patch_output))
    for path in (patch_a, patch_b):
        item = QListWidgetItem(path.name)
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        tab._file_list.addItem(item)

    tab._on_run()
    tab._worker.wait(5000)
    app.processEvents()

    assert calls == [
        (
            str(original),
            [str(patch_a), str(patch_b)],
            str(output),
            str(patch_output),
            str(tmp_path / "merged_merge_report.md"),
            None,
            True,
            True,
        )
    ]
    assert tab._status_label.text() == tr("modding_tools.success")


def test_merge_tab_batch_uses_sets_and_flags(tmp_path):
    app = QApplication.instance() or QApplication([])
    calls = []

    class _RecordingG3M(_FakeG3M):
        def batch_merge_patches(
            self,
            original_data_win,
            patch_sets,
            output_dir,
            patch_output_dir=None,
            continue_on_error=False,
            merge_code=False,
            merge_properties=False,
            write_report=False,
            progress_callback=None,
        ):
            calls.append(
                (
                    original_data_win,
                    patch_sets,
                    output_dir,
                    patch_output_dir,
                    continue_on_error,
                    merge_code,
                    merge_properties,
                    write_report,
                )
            )
            return super().batch_merge_patches(
                original_data_win,
                patch_sets,
                output_dir,
                patch_output_dir,
                continue_on_error,
                merge_code,
                merge_properties,
                write_report,
                progress_callback,
            )

    tab = _MergeTab(_RecordingG3M(), SimpleNamespace(local_config={}))
    original = tmp_path / "data.win"
    out_dir = tmp_path / "merged"
    patch_out_dir = tmp_path / "patches"
    original.write_text("original", encoding="utf-8")
    set_a = [str(tmp_path / "a.g3mpatch"), str(tmp_path / "b.xdelta")]
    set_b = [str(tmp_path / "c.win"), str(tmp_path / "d.g3mpatch")]

    tab._batch_cb.setChecked(True)
    tab._continue_cb.setChecked(True)
    tab._code_cb.setChecked(True)
    tab._props_cb.setChecked(True)
    tab._report_cb.setChecked(True)
    tab._original_row.set_path(str(original))
    tab._batch_output_row.set_path(str(out_dir))
    tab._batch_patch_output_row.set_path(str(patch_out_dir))
    for patch_set in (set_a, set_b):
        item = QListWidgetItem("set")
        item.setData(Qt.ItemDataRole.UserRole, patch_set)
        tab._set_list.addItem(item)

    tab._on_run()
    tab._worker.wait(5000)
    app.processEvents()

    assert calls == [
        (str(original), [set_a, set_b], str(out_dir), str(patch_out_dir), True, True, True, True)
    ]
    assert tab._status_label.text() == tr("modding_tools.success")


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


def test_patch_tab_failure_uses_warning_event_feedback(monkeypatch):
    app = QApplication.instance() or QApplication([])
    tab = _PatchTab(_FakeG3M(), SimpleNamespace(local_config={}))
    warnings = []

    monkeypatch.setattr(
        "ui.dialogs.modding_tools_dialog.FeedbackManager.ask_patching_warning",
        lambda self, message, details="", report_path=None: warnings.append(
            (message.warning_id, details, report_path)
        )
        or False,
    )

    tab._on_finished(1, "", "xdelta checksum mismatch")

    assert warnings == [("xdelta_apply_failed", "xdelta checksum mismatch", None)]
    assert tab._status_label.text() == tr("modding_tools.failed_details_logged")
    app.processEvents()


def test_merge_tab_failure_uses_warning_event_feedback(monkeypatch):
    app = QApplication.instance() or QApplication([])
    tab = _MergeTab(_FakeG3M(), SimpleNamespace(local_config={}))
    warnings = []

    monkeypatch.setattr(
        "ui.dialogs.modding_tools_dialog.FeedbackManager.ask_patching_warning",
        lambda self, message, details="", report_path=None: warnings.append(
            (message.warning_id, details, report_path)
        )
        or False,
    )

    tab._on_finished(1, "", "merge conflict")

    assert warnings == [("merge_failed", "merge conflict", None)]
    assert tab._status_label.text() == tr("modding_tools.failed_details_logged")
    app.processEvents()
