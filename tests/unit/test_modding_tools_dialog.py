import json
import zipfile
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

from services.localization_service import tr
from ui.dialogs.modding_tools_dialog import (
    _ConvertWorkerThread,
    _CreatePatchWorkerThread,
    _DataConvertTab,
    _DataConvertWorkerThread,
    _MergeTab,
    _PatchTab,
)


class _FakeG3M:
    _PATCH_PREFIX = b"PATCH|"
    _XPATCH_PREFIX = b"XPATCH|"

    def apply_patch(self, original, patch, output):
        with open(patch, "rb") as handle:
            payload = handle.read()
        if payload.startswith(self._PATCH_PREFIX):
            with open(output, "wb") as f:
                f.write(payload[len(self._PATCH_PREFIX) :])
            return 0, "", ""
        with open(output, "w", encoding="utf-8") as f:
            f.write(f"{original}|{patch}")
        return 0, "", ""

    def xpatch_apply(self, original, patch, output):
        with open(patch, "rb") as handle:
            payload = handle.read()
        if payload.startswith(self._XPATCH_PREFIX):
            with open(output, "wb") as f:
                f.write(payload[len(self._XPATCH_PREFIX) :])
            return 0, "", ""
        with open(output, "w", encoding="utf-8") as f:
            f.write(f"{original}|{patch}")
        return 0, "", ""

    def patch_create(self, original, modified, output):
        with open(modified, "rb") as handle:
            payload = handle.read()
        with open(output, "wb") as f:
            f.write(self._PATCH_PREFIX + payload)
        return 0, "", ""

    def xpatch_create(self, original, modified, output):
        with open(modified, "rb") as handle:
            payload = handle.read()
        with open(output, "wb") as f:
            f.write(self._XPATCH_PREFIX + payload)
        return 0, "", ""

    def execute(self, target, args=None, data_file=None, output_path=None, input_path=None):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"{target}|{data_file}|{input_path}|{args}")
        return 0, "", ""

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
    """Checks that dataing convert tab blocks controls while busy."""
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
    """Checks that dataing convert creates new version without overwriting mod."""
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
        "utils.mod_config_parser.resolve_mod_file_path",
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
        False,
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
    """Checks that dataing convert accepts g3mpatch zip as source."""
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
        "utils.mod_config_parser.resolve_mod_file_path",
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
        True,
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
        "utils.mod_config_parser.resolve_mod_file_path",
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
        False,
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


def test_convert_worker_rejects_generated_patch_that_fails_roundtrip(tmp_path):
    """Checks that converting rejects generated patches that fail verification."""
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

    assert len(result) == 1
    assert result[0][0] == 1
    assert "failed verification" in result[0][2]
    assert not output_path.exists()


def test_create_patch_worker_rejects_generated_patch_that_fails_roundtrip(tmp_path):
    """Checks that create rejects generated patches that fail verification."""
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

    assert len(result) == 1
    assert result[0][0] == 1
    assert "failed verification" in result[0][2]
    assert not output_path.exists()


def test_data_convert_rejects_unverifiable_generated_patch(tmp_path, monkeypatch):
    """Checks that data convert stops when generated patch fails verification."""
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
        "utils.mod_config_parser.resolve_mod_file_path",
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
        False,
    )
    result = []
    worker.finished.connect(lambda success, message: result.append((success, message)))

    worker.run()

    assert len(result) == 1
    assert result[0][0] is False
    assert "failed verification" in result[0][1]
    assert patch_path.read_text(encoding="utf-8") == "old patch"
    assert not (versions_dir / "1.2.3 - g3mpatch.zip").exists()
    assert (
        json.loads(config_path.read_text(encoding="utf-8"))["files"]["deltarune_1"][
            "data_file_path"
        ]
        == "data.xdelta"
    )


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
        def execute(self, target, args=None, data_file=None, output_path=None, input_path=None):
            calls.append((target, args, data_file, output_path, input_path))
            return super().execute(target, args, data_file, output_path, input_path)

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
