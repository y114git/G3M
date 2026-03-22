import json
import zipfile
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

from ui.dialogs.g3m_actions_dialog import _DataConvertTab, _DataConvertWorkerThread


class _FakeG3M:
    def xpatch_apply(self, original, patch, output):
        with open(output, "w", encoding="utf-8") as f:
            f.write(f"{original}|{patch}")
        return 0, "", ""

    def patch_create(self, original, modified, output):
        with open(output, "w", encoding="utf-8") as f:
            f.write(f"{original}|{modified}")
        return 0, "", ""


def test_data_convert_tab_blocks_controls_while_busy(monkeypatch):
    app = QApplication.instance() or QApplication([])

    monkeypatch.setattr(_DataConvertTab, "_populate_profiles", lambda self: None)
    tab = _DataConvertTab(_FakeG3M(), SimpleNamespace(local_config={}))
    monkeypatch.setattr(tab, "_scan_mods", lambda *_: tab._run_btn.setEnabled(True))

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
    mod_folder = tmp_path / "mod"
    chapter_dir = mod_folder / "chapter1"
    versions_dir = mod_folder / "mod_versions"
    chapter_dir.mkdir(parents=True)
    versions_dir.mkdir()
    patch_path = chapter_dir / "data.xdelta"
    patch_path.write_text("old patch", encoding="utf-8")
    config_path = mod_folder / "mod_config.json"
    config_path.write_text(
        json.dumps(
            {"version": "1.2.3", "files": {"1": {"data_file_url": "data.xdelta"}}}
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
        "utils.mod_config_parser.resolve_chapter_folder",
        lambda file_key, folder, game: str(chapter_dir),
    )
    monkeypatch.setattr(
        "utils.path_utils.find_chapter_resource_dir",
        lambda game_path, chapter_id: str(game_dir),
    )

    worker = _DataConvertWorkerThread(
        _FakeG3M(),
        str(mod_folder),
        {"version": "1.2.3", "files": {"1": {"data_file_url": "data.xdelta"}}},
        str(tmp_path / "game_root"),
        False,
    )
    result = []
    worker.finished.connect(lambda success, message: result.append((success, message)))

    worker.run()

    assert result and result[0][0] is True
    assert patch_path.read_text(encoding="utf-8") == "old patch"
    assert (
        json.loads(config_path.read_text(encoding="utf-8"))["files"]["1"][
            "data_file_url"
        ]
        == "data.xdelta"
    )

    version_zip = versions_dir / "1.2.3 - g3mpatch.zip"
    assert version_zip.is_file()
    with zipfile.ZipFile(version_zip) as zf:
        assert "chapter1/data.zip" in zf.namelist()
        converted_config = json.loads(zf.read("mod_config.json").decode("utf-8"))
    assert converted_config["files"]["1"]["data_file_url"] == "data.zip"
