"""Regression tests for the current manual-import flow."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollBar,
    QStyle,
    QStyleOptionToolButton,
    QStyleOptionViewItem,
    QTreeWidgetItem,
    QWidget,
)

from adapters.gamebanana_adapter import GameBananaAPI
from config.config import DEFAULT_COLORS
from config.style_loader import build_stylesheet
from models.game_modes import (
    CustomGameRecord,
    CustomSingleTabGame,
    GameEntry,
    get_all_game_entries,
    get_game,
    replace_game_entries,
)
from services.localization_service import tr
from ui.common.dialog_theme import DynamicMessageBox
from ui.dialogs.manual_install.dialog import ManualModInstallDialog
from ui.dialogs.mod_editor.dialog import ModEditorDialog
from utils.mod.config import load_mod_config


def _parent(tmp_path):
    parent = QWidget()
    vars(parent)["app_state"] = SimpleNamespace(local_config={}, mods_dir=str(tmp_path / "mods"))
    vars(parent)["mod_service"] = object()
    return parent


@pytest.fixture
def manual_parent(qtbot, tmp_path):
    parent = _parent(tmp_path)
    qtbot.addWidget(parent)
    return parent


def _save_import(dialog, qtbot, monkeypatch):
    dialog._on_finish()
    qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted, timeout=30000)
    mods_dir = dialog.target_mods_dir or dialog.app_state.mods_dir
    config_path = next(Path(mods_dir).glob("*/mod_config.json"))
    return load_mod_config(config_path), config_path.parent


def test_manual_import_copies_sources_without_guessing_operations(
    qtbot, manual_parent, tmp_path, monkeypatch
):
    prepared = tmp_path / "prepared"
    (prepared / "assets").mkdir(parents=True)
    (prepared / "README.md").write_text("Guide", encoding="utf-8")
    (prepared / "assets" / "patch.xdelta").write_text("patch", encoding="utf-8")
    parent = manual_parent
    dialog = ManualModInstallDialog(parent, str(prepared))

    assert dialog.sources.topLevelItemCount() == 2
    assert not hasattr(dialog, "data_file_selections")
    assert not hasattr(dialog, "additional_patches_mappings")
    assert dialog._items["assets/patch.xdelta"].text(1) == tr("ui.manual_install_unconfigured")
    dialog._assign("assets/patch.xdelta", {"type": ""})
    dialog._update_summary()
    config, folder = _save_import(dialog, qtbot, monkeypatch)
    saved = load_mod_config(folder / "mod_config.json")

    assert (folder / "files" / "README.md").read_text(encoding="utf-8") == "Guide"
    assert (folder / "files" / "assets" / "patch.xdelta").read_text(
        encoding="utf-8"
    ) == "patch"
    assert config == saved
    assert saved["authors"] == ["Unknown"]
    assert saved["files"] == [{"source": "${mod_path}/files/README.md", "type": "info"}]


def test_manual_import_keeps_the_downloads_original_profile(
    qtbot, manual_parent, tmp_path, monkeypatch
):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "README.md").write_text("Guide", encoding="utf-8")
    parent = manual_parent
    original_profile = tmp_path / "original_profile"
    dialog = ManualModInstallDialog(
        parent, str(prepared), target_mods_dir=str(original_profile)
    )

    _config, folder = _save_import(dialog, qtbot, monkeypatch)

    assert folder.parent == original_profile
    assert not (tmp_path / "mods").exists()


def test_manual_import_saves_then_opens_the_current_editor(
    qtbot, manual_parent, tmp_path, monkeypatch
):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "patch.xdelta").write_text("patch", encoding="utf-8")
    parent = manual_parent
    dialog = ManualModInstallDialog(parent, str(prepared))
    opened = []
    monkeypatch.setattr(
        dialog,
        "_open_editor",
        lambda config, folder: opened.append((config, folder)) or True,
    )
    dialog._assign("patch.xdelta", {"type": ""})
    dialog._update_summary()
    dialog._on_finish(configure=True)
    qtbot.waitUntil(lambda: dialog._save_thread is None)

    assert dialog.result() == dialog.DialogCode.Accepted
    assert len(opened) == 1
    assert opened[0][0]["files"] == []
    assert (opened[0][1] / "files" / "patch.xdelta").is_file()


def test_manual_import_keeps_saved_mod_when_editor_is_cancelled(
    qtbot, manual_parent, tmp_path, monkeypatch
):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "patch.xdelta").write_text("patch", encoding="utf-8")
    parent = manual_parent
    dialog = ManualModInstallDialog(parent, str(prepared))
    created = []

    def cancel_editor(_config, folder):
        created.append(folder)
        return False

    monkeypatch.setattr(dialog, "_open_editor", cancel_editor)
    dialog._assign("patch.xdelta", {"type": ""})
    dialog._update_summary()
    dialog._on_finish(configure=True)
    qtbot.waitUntil(lambda: dialog._save_thread is None)

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert created and created[0].is_dir()


def test_manual_import_ignores_external_file_symlinks(tmp_path):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    external = tmp_path / "outside.txt"
    external.write_text("outside", encoding="utf-8")
    try:
        (prepared / "linked.txt").symlink_to(external)
    except OSError:
        return

    dialog = ManualModInstallDialog.__new__(ManualModInstallDialog)
    dialog.prepared_files_path = str(prepared)

    assert dialog._scan_files() == []


@pytest.mark.parametrize("item_type", ["mod", "wip"])
@pytest.mark.parametrize("cached_version", [None, "0.9"])
def test_manual_import_refreshes_and_saves_gamebanana_metadata(
    qtbot, manual_parent, tmp_path, monkeypatch, item_type, cached_version
):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "README.md").write_text("Guide", encoding="utf-8")
    profile = {
        "_idRow": 42,
        "_sName": "Remote mod",
        "_sDescription": "Actual description from the profile",
        "_sVersion": "1.01",
        "_aSubmitter": {"_sName": "Author"},
        "_aCategory": {"_sName": "Gameplay Adjustments"},
        "_aPreviewMedia": {
            "_aImages": [
                {
                    "_sBaseUrl": "https://images.gamebanana.com/img/ss/mods",
                    "_sFile": "icon.jpg",
                }
            ]
        },
        "_aTags": ["customization", "customization", "unsupported"],
    }
    fetch = Mock(return_value=profile)
    monkeypatch.setattr(GameBananaAPI, "get_mod_profile_page", fetch)
    metadata = {
        "mod_id": 42,
        "item_type": item_type,
        "description": "No description",
        "game": "undertale",
        "game_version": "1.08",
        "version": cached_version,
    }
    parent = manual_parent
    parent.mod_service = Mock()
    qtbot.addWidget(parent)
    dialog = ManualModInstallDialog(parent, str(prepared), metadata)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._metadata_thread is None)

    config, folder = _save_import(dialog, qtbot, monkeypatch)

    assert config == load_mod_config(folder / "mod_config.json")
    assert config["id"] == f"gb_{item_type}_42"
    assert config["name"] == "Remote mod"
    assert config["authors"] == ["Author"]
    assert config["description"] == profile["_sDescription"]
    assert config["icon"] == "https://images.gamebanana.com/img/ss/mods/icon.jpg"
    assert (
        config["homepage"]
        == f"https://gamebanana.com/{'wips' if item_type == 'wip' else 'mods'}/42"
    )
    assert config["version"] == (cached_version or "1.01")
    assert config["game"] == "undertale"
    assert config["game_version"] == "1.08"
    assert config["tags"] == ["customization", "other", "gameplay"]
    assert metadata["description"] == "No description"
    assert fetch.call_args.kwargs["itemtype"] == (
        "Wip" if item_type == "wip" else "Mod"
    )

    editor = ModEditorDialog(
        parent, is_creating=False, mod_data=dict(config, folder_path=str(folder))
    )
    qtbot.addWidget(editor)
    assert editor.description_edit.text() == config["description"]
    assert editor.icon_edit.text() == config["icon"]
    editor.description_edit.setText("My description")
    editor.icon_edit.setText("https://example.com/my-icon.png")
    editor.game_version_edit.setText("My game build")
    monkeypatch.setattr(editor, "_safe_information", lambda *_args: None)
    editor._save()
    saved = load_mod_config(folder / "mod_config.json")
    assert editor.result() == QDialog.DialogCode.Accepted
    assert saved["description"] == "My description"
    assert saved["icon"] == "https://example.com/my-icon.png"
    assert saved["game_version"] == "My game build"


def test_manual_import_keeps_edits_made_while_metadata_loads(
    qtbot, manual_parent, tmp_path, monkeypatch
):
    gate = threading.Event()

    def fetch(*_args, **_kwargs):
        assert gate.wait(2)
        return {
            "_idRow": 42,
            "_sName": "Remote name",
            "_sDescription": "Remote description",
            "_aSubmitter": {"_sName": "Remote author"},
        }

    monkeypatch.setattr(GameBananaAPI, "get_mod_profile_page", fetch)
    parent = manual_parent
    qtbot.addWidget(parent)
    dialog = ManualModInstallDialog(
        parent,
        str(tmp_path),
        {"mod_id": 42, "name": "Cached name", "authors": ["Cached author"]},
    )
    qtbot.addWidget(dialog)
    try:
        assert not cast(QPushButton, dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)).isEnabled()
        assert cast(QPushButton, dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)).toolTip() == tr("tooltips.manual_install_save_loading")
        assert dialog.configure_button is not None
        assert dialog.configure_button.toolTip() == tr("tooltips.manual_install_save_loading")
        dialog.name_edit.setText("My name")
        assert not hasattr(dialog, "authors_edit")
    finally:
        gate.set()
    qtbot.waitUntil(lambda: dialog._metadata_thread is None)
    config = dialog._config("gb_mod_42", dialog.name_edit.text())
    assert config["name"] == "My name"
    assert config["authors"] == ["Remote author"]
    assert config["description"] == "Remote description"


@pytest.mark.parametrize("failure", [None, ConnectionError("offline")])
def test_manual_import_uses_cached_metadata_when_refresh_fails(
    qtbot, manual_parent, tmp_path, monkeypatch, failure
):
    fetch = Mock(side_effect=failure) if failure else Mock(return_value=None)
    monkeypatch.setattr(GameBananaAPI, "get_mod_profile_page", fetch)
    metadata = {
        "mod_id": 42,
        "name": "Cached mod",
        "authors": ["Author, Jr.", "Another author"],
        "description": "Cached description",
        "icon": "https://example.com/icon.png",
        "profile_url": "https://gamebanana.com/mods/42",
        "version": "1.2",
        "game": "undertale",
        "game_version": "1.08",
        "tags": ["textedit"],
    }
    parent = manual_parent
    qtbot.addWidget(parent)
    dialog = ManualModInstallDialog(parent, str(tmp_path), metadata)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._metadata_thread is None)
    config = dialog._config("gb_mod_42", dialog.name_edit.text())
    for field in (
        "name",
        "authors",
        "description",
        "icon",
        "version",
        "game",
        "game_version",
        "tags",
    ):
        assert config[field] == metadata[field]
    assert config["homepage"] == metadata["profile_url"]
    assert not cast(QPushButton, dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)).isEnabled()
    assert dialog.configure_button is not None
    assert not dialog.configure_button.isEnabled()


def test_successful_validation_preserves_status_and_clears_corrected_errors(qtbot, manual_parent, tmp_path):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "README.md").write_text("guide", encoding="utf-8")
    dialog = ManualModInstallDialog(manual_parent, str(prepared))
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._detection_thread is None)
    original_name = dialog.name_edit.text()
    dialog.status_label.set_localized_text("ui.manual_install_no_files")
    status = dialog.status_label.text()
    assert dialog._validate()
    assert dialog.status_label.text() == status
    dialog.name_edit.setText("")
    assert not dialog._validate()
    dialog.name_edit.setText(original_name)
    assert dialog._validate()
    assert dialog.status_label.text() == ""


def test_manual_import_can_close_during_metadata_request(qtbot, manual_parent, tmp_path, monkeypatch):
    gate = threading.Event()

    def fetch(*_args, **_kwargs):
        assert gate.wait(2)
        return {"_idRow": 42, "_sName": "Remote name"}

    monkeypatch.setattr(GameBananaAPI, "get_mod_profile_page", fetch)
    parent = manual_parent
    qtbot.addWidget(parent)
    dialog = ManualModInstallDialog(
        parent, str(tmp_path), {"mod_id": 42, "name": "Cached name"}
    )
    thread = dialog._metadata_thread
    assert thread is not None
    with qtbot.waitSignal(thread.finished):
        dialog.reject()
        dialog.deleteLater()
        gate.set()
    assert not (tmp_path / "mods").exists()


def test_save_requires_explicit_configuration_or_skip(qtbot, manual_parent, tmp_path, monkeypatch):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "unknown.bin").write_bytes(b"payload")
    dialog = ManualModInstallDialog(manual_parent, str(prepared))
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._detection_thread is None)
    opened, question = Mock(), Mock()
    monkeypatch.setattr(dialog, "_open_editor", opened)
    monkeypatch.setattr(QMessageBox, "question", question)
    assert dialog._items["unknown.bin"].text(1) == tr("ui.manual_install_unconfigured")
    assert not cast(QPushButton, dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)).isEnabled()
    assert dialog.configure_button is not None
    assert not dialog.configure_button.isEnabled()
    for configure in (False, True):
        dialog._on_finish(configure=configure)
        assert not (tmp_path / "mods").exists()
    assert len(dialog.status_label.text().splitlines()) == 2
    dialog._items["unknown.bin"].setSelected(True)
    dialog._set_selected_action(dialog.action_combo.findData(""))
    assert dialog._items["unknown.bin"].text(1) == tr("ui.manual_install_skip")
    assert cast(QPushButton, dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)).isEnabled()
    assert dialog.configure_button is not None
    assert dialog.configure_button.isEnabled()
    saved, folder = _save_import(dialog, qtbot, monkeypatch)
    assert saved["files"] == []
    assert (folder / "files/unknown.bin").read_bytes() == b"payload"
    opened.assert_not_called()
    question.assert_not_called()


@pytest.mark.parametrize("action", ["overwrite", "patch", "extract"])
def test_action_without_destination_blocks_save(
    qtbot, manual_parent, tmp_path, monkeypatch, action
):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "patch.xdelta").write_bytes(b"unknown patch")
    dialog = ManualModInstallDialog(manual_parent, str(prepared))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog._assign("patch.xdelta", {"type": action})
    dialog._update_summary()
    assert not cast(QPushButton, dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)).isEnabled()
    assert dialog.configure_button is not None
    assert not dialog.configure_button.isEnabled()
    dialog._on_finish()
    assert not (tmp_path / "mods").exists()
    assert dialog._items["patch.xdelta"].foreground(2).color().name() == "#f44336"
    dialog._assign("patch.xdelta", {"type": ""})
    dialog._update_summary()
    saved, folder = _save_import(dialog, qtbot, monkeypatch)
    assert saved["files"] == []
    assert (folder / "files/patch.xdelta").is_file()



def test_invalid_destination_is_highlighted_and_not_saved(qtbot, manual_parent, tmp_path):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "payload.bin").write_bytes(b"payload")
    parent = manual_parent
    dialog = ManualModInstallDialog(parent, str(prepared))
    dialog._stop_detection()
    dialog._assign("payload.bin", {"type": "overwrite", "target": "../outside"})
    dialog._on_finish()
    assert not (tmp_path / "mods").exists()
    assert dialog.status_label.text()
    assert dialog._items["payload.bin"].foreground(2).color().name() == "#f44336"


def test_bulk_folder_mapping_keeps_nested_paths_for_hundreds_of_files(
    qtbot, manual_parent, tmp_path, monkeypatch
):
    prepared, game_root = tmp_path / "prepared", tmp_path / "game"
    game_root.mkdir()
    for index in range(300):
        source = (
            prepared / "MusicPack/music" / f"group{index // 100}" / f"track{index}.ogg"
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"music")
    parent = manual_parent
    game = get_game("undertale")
    assert game is not None
    parent.app_state.local_config[game.path_config_key] = str(
        game_root
    )
    dialog = ManualModInstallDialog(
        parent, str(prepared), initial_game_type="undertale"
    )
    dialog._stop_detection()
    cast(QTreeWidgetItem, dialog.sources.topLevelItem(0)).setSelected(True)
    dialog._set_selected_action(dialog.action_combo.findData("overwrite"))
    destination = game_root / "MusicPack"
    destination.mkdir()
    monkeypatch.setattr(
        "ui.dialogs.manual_install.dialog.get_existing_directory",
        lambda *_args: str(destination),
    )
    dialog._browse_selected()
    assert (
        dialog._assignments["MusicPack/"]["target"]
        == "${game_path}/MusicPack"
    )
    saved, folder = _save_import(dialog, qtbot, monkeypatch)
    assert saved["files"] == [{"type": "hard-extract", "source": "${mod_path}/files/MusicPack/", "target": "${game_path}/MusicPack/"}]
    assert (
        folder / "files/MusicPack/music/group2/track299.ogg"
    ).read_bytes() == b"music"


def test_browse_uses_the_most_specific_game_data_placeholder(
    qtbot, manual_parent, tmp_path, monkeypatch
):
    prepared, game_root = tmp_path / "prepared", tmp_path / "game"
    prepared.mkdir()
    saves = game_root / "saves"
    saves.mkdir(parents=True)
    target = saves / "slot.sav"
    target.write_bytes(b"save")
    (prepared / "slot.sav").write_bytes(b"mod save")
    parent = manual_parent
    game = get_game("undertale")
    assert game is not None
    parent.app_state.local_config.update(
        {game.path_config_key: str(game_root), game.data_path_config_key: str(saves)}
    )
    dialog = ManualModInstallDialog(
        parent, str(prepared), initial_game_type="undertale"
    )
    dialog._stop_detection()
    cast(QTreeWidgetItem, dialog.sources.topLevelItem(0)).setSelected(True)
    monkeypatch.setattr(
        "ui.dialogs.manual_install.dialog.get_open_file_name",
        lambda *_args: (str(target), ""),
    )
    dialog._browse_selected()
    assert dialog._assignments["slot.sav"]["target"] == "${game_data_path}/slot.sav"


def test_bulk_file_selection_uses_posix_common_folder(qtbot, manual_parent, tmp_path, monkeypatch):
    prepared, game_root = tmp_path / "prepared", tmp_path / "game"
    game_root.mkdir()
    for relative in ("pack/music/one/a.ogg", "pack/music/two/b.ogg"):
        path = prepared / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"music")
    parent = manual_parent
    game = get_game("undertale")
    assert game is not None
    parent.app_state.local_config[game.path_config_key] = str(
        game_root
    )
    dialog = ManualModInstallDialog(
        parent, str(prepared), initial_game_type="undertale"
    )
    dialog._stop_detection()
    for item in dialog._items.values():
        if item.childCount() == 0:
            item.setSelected(True)
    monkeypatch.setattr(
        "ui.dialogs.manual_install.dialog.get_existing_directory",
        lambda *_args: str(game_root),
    )
    dialog._browse_selected()
    assert (
        dialog._assignments["pack/music/one/a.ogg"]["target"]
        == "${game_path}/one/a.ogg"
    )
    assert (
        dialog._assignments["pack/music/two/b.ogg"]["target"]
        == "${game_path}/two/b.ogg"
    )


def test_existing_file_as_destination_parent_is_highlighted(qtbot, manual_parent, tmp_path):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "payload.bin").write_bytes(b"payload")
    (tmp_path / "file").write_bytes(b"existing file")
    parent = manual_parent
    dialog = ManualModInstallDialog(parent, str(prepared))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog._assign(
        "payload.bin", {"type": "overwrite", "target": (tmp_path / "file/child").as_posix()}
    )
    assert not dialog._validate()
    assert dialog._items["payload.bin"].foreground(2).color().name() == "#f44336"


@pytest.mark.parametrize("replace_game_root", [False, True])
def test_file_overwrite_can_replace_directory_but_not_game_root(
    qtbot, manual_parent, tmp_path, replace_game_root
):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "payload.bin").write_bytes(b"payload")
    game_root = tmp_path / "game"
    target = game_root if replace_game_root else game_root / "directory"
    target.mkdir(parents=True)
    existing_file = target / "existing.bin"
    existing_file.write_bytes(b"existing file")
    game = get_game("undertale")
    assert game is not None
    manual_parent.app_state.local_config[game.path_config_key] = str(game_root)
    dialog = ManualModInstallDialog(manual_parent, str(prepared), initial_game_type="undertale")
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog._assign("payload.bin", {"type": "overwrite", "target": target.as_posix()})

    assert dialog._validate() is not replace_game_root
    assert (dialog._items["payload.bin"].foreground(2).color().name() == "#f44336") is replace_game_root
    assert existing_file.read_bytes() == b"existing file"


@pytest.mark.parametrize("valid_base", [True, False])
def test_manual_patch_binding_is_checked_before_save(qtbot, manual_parent, tmp_path, monkeypatch, valid_base):
    monkeypatch.setattr(DynamicMessageBox, "exec", lambda _self: QMessageBox.StandardButton.Cancel)
    import shutil

    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    prepared, game_root = tmp_path / "prepared", tmp_path / "game"
    prepared.mkdir()
    game_root.mkdir()
    shutil.copyfile(
        fixtures / "patches/undertale/patch.xdelta", prepared / "patch.xdelta"
    )
    target = game_root / "base.bin"
    if valid_base:
        shutil.copyfile(fixtures / "game_data/undertale/data.win", target)
    else:
        target.write_bytes(b"wrong base")
    original = target.read_bytes()
    parent = manual_parent
    game = get_game("undertale")
    assert game is not None
    parent.app_state.local_config[game.path_config_key] = str(
        game_root
    )
    dialog = ManualModInstallDialog(
        parent, str(prepared), initial_game_type="undertale"
    )
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog._assign("patch.xdelta", {"type": "patch", "target": "${game_path}/base.bin"})
    dialog._on_finish()
    assert dialog._checking_save
    assert cast(QPushButton, dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)).toolTip() == tr("tooltips.manual_install_save_checking")
    assert dialog.configure_button is not None
    assert dialog.configure_button.toolTip() == tr("tooltips.manual_install_save_checking")
    qtbot.waitUntil(lambda: not dialog._checking_save, timeout=10000)
    if valid_base:
        qtbot.waitUntil(
            lambda: dialog.result() == QDialog.DialogCode.Accepted, timeout=10000
        )
        config = load_mod_config(next((tmp_path / "mods").glob("*/mod_config.json")))
        assert isinstance(config["files"], list)
        assert isinstance(config["files"][0], dict)
        assert config["files"][0]["target_hash"].startswith("sha256:")
    else:
        assert not (tmp_path / "mods").exists()
        assert dialog._items["patch.xdelta"].foreground(2).color().name() != "#f44336"
        assert dialog.sources.isEnabled()
        assert dialog.save_button.isEnabled()
    assert target.read_bytes() == original


def test_late_detection_does_not_replace_manual_assignments(
    qtbot, manual_parent, tmp_path, monkeypatch
):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "file.bin").write_bytes(b"payload")
    gate, started = threading.Event(), threading.Event()

    def detect(*_args, **_kwargs):
        started.set()
        assert gate.wait(5)
        return {
            "file.bin": {"type": "overwrite", "target": "${game_path}/automatic.bin"}
        }

    monkeypatch.setattr("ui.dialogs.manual_install.workers.detect_operations", detect)
    parent = manual_parent
    dialog = ManualModInstallDialog(parent, str(prepared))
    qtbot.waitUntil(started.is_set)
    try:
        dialog._items["file.bin"].setText(2, str(tmp_path / "manual.bin"))
    finally:
        gate.set()
    qtbot.waitUntil(lambda: dialog._detection_thread is None)
    assert dialog._assignments["file.bin"]["target"].endswith("/manual.bin")


@pytest.mark.parametrize("reason", ["invalid_name", "unconfigured"])
def test_failed_save_resumes_detection_without_losing_manual_choices(
    qtbot, manual_parent, tmp_path, monkeypatch, reason
):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    for name in ("auto.bin", "manual.bin"):
        (prepared / name).write_bytes(b"payload")
    gate, started = threading.Event(), threading.Event()
    calls = []

    def detect(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            started.set()
            assert gate.wait(5)
        return {
            name: {"type": "overwrite", "target": "${user_path}/auto.bin"}
            for name in ("auto.bin", "manual.bin")
        }

    monkeypatch.setattr("ui.dialogs.manual_install.workers.detect_operations", detect)
    parent = manual_parent
    dialog = ManualModInstallDialog(parent, str(prepared))
    qtbot.addWidget(dialog)
    qtbot.waitUntil(started.is_set)
    try:
        dialog._items["manual.bin"].setText(2, str(tmp_path / "manual.bin"))
        if reason == "invalid_name":
            dialog._assign("auto.bin", {"type": "overwrite", "target": "${user_path}/auto.bin"})
            dialog.name_edit.clear()
        dialog._on_finish()
        if reason == "unconfigured":
            assert dialog._detection_thread is not None
            gate.set()
        qtbot.waitUntil(lambda: dialog._detection_thread is None)
        assert len(calls) == (2 if reason == "invalid_name" else 1)
        assert dialog._assignments["auto.bin"]["target"] == "${user_path}/auto.bin"
        assert dialog._assignments["manual.bin"]["target"].endswith("/manual.bin")
        assert not (tmp_path / "mods").exists()
        if reason == "invalid_name":
            assert dialog.name_edit.property("invalid")
    finally:
        gate.set()


def test_cancel_during_save_removes_only_the_attempt(qtbot, manual_parent, tmp_path, monkeypatch):
    from ui.dialogs.manual_install import workers as module

    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "README.md").write_text("guide", encoding="utf-8")
    parent = manual_parent
    untouched = tmp_path / "mods" / "existing"
    untouched.mkdir(parents=True)
    (untouched / "important.txt").write_text("keep", encoding="utf-8")
    gate, started = threading.Event(), threading.Event()
    original = module.write_import

    def slow_save(*args):
        started.set()
        assert gate.wait(5)
        return original(*args)

    monkeypatch.setattr(module, "write_import", slow_save)
    dialog = ManualModInstallDialog(parent, str(prepared))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._on_finish()
    qtbot.waitUntil(started.is_set)
    try:
        assert cast(QPushButton, dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)).toolTip() == tr("tooltips.manual_install_save_saving")
        assert dialog.configure_button is not None
        assert dialog.configure_button.toolTip() == tr("tooltips.manual_install_save_saving")
        dialog.reject()
        assert dialog._save_thread is not None
    finally:
        gate.set()
    qtbot.waitUntil(lambda: dialog._save_thread is None)
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert list((tmp_path / "mods").iterdir()) == [untouched]
    assert (untouched / "important.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("font_size", [14, 24])
def test_manual_toolbar_heights_and_split_button_geometry(
    qtbot, tmp_path, font_size, manual_parent
):
    (tmp_path / "file.bin").write_bytes(b"payload")
    parent = manual_parent
    parent.setStyleSheet(
        build_stylesheet(
            DEFAULT_COLORS["background"],
            DEFAULT_COLORS["elements"],
            DEFAULT_COLORS["border"],
            DEFAULT_COLORS["hover"],
            DEFAULT_COLORS["select"],
            DEFAULT_COLORS["main_text"],
            font_size_main=font_size,
        )
    )
    dialog = ManualModInstallDialog(parent, str(tmp_path))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    screen = dialog.screen()
    assert screen is not None
    assert dialog.width() == min(1105, screen.availableGeometry().width() - 40)
    font = QFont(dialog.font())
    font.setPixelSize(font_size)
    dialog.setFont(font)
    dialog._items["file.bin"].setSelected(True)
    dialog.show()
    qtbot.waitExposed(dialog)
    controls = (dialog.filter_edit, dialog.action_combo, dialog.browse_button)
    assert len({widget.height() for widget in controls}) == 1
    assert len({widget.y() for widget in controls}) == 1
    button = dialog.browse_button
    option = QStyleOptionToolButton()
    button.initStyleOption(option)
    menu = cast(QStyle, button.style()).subControlRect(
        QStyle.ComplexControl.CC_ToolButton,
        option,
        QStyle.SubControl.SC_ToolButtonMenu,
        button,
    )
    assert button.rect().contains(menu)
    assert menu.width() >= 30
    assert menu.left() > button.iconSize().width() + 10
    assert dialog.width() >= dialog.minimumWidth()
    screen = dialog.screen()
    assert screen is not None
    assert dialog.width() <= screen.availableGeometry().width()


def test_ctrl_selection_and_cell_edits_apply_to_all_selected_files(
    qtbot, tmp_path, manual_parent
):
    for name in ("a.xdelta", "b.xdelta", "c.bin"):
        (tmp_path / name).write_bytes(b"payload")
    parent = manual_parent
    dialog = ManualModInstallDialog(parent, str(tmp_path))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog.show()
    qtbot.waitExposed(dialog)
    first, second = (dialog._items[name] for name in ("a.xdelta", "b.xdelta"))
    qtbot.mouseClick(
        dialog.sources.viewport(),
        Qt.MouseButton.LeftButton,
        pos=dialog.sources.visualItemRect(first).center(),
    )
    qtbot.mouseClick(
        dialog.sources.viewport(),
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
        pos=dialog.sources.visualItemRect(second).center(),
    )
    assert set(dialog._selected_files()) == {"a.xdelta", "b.xdelta"}
    dialog.sources.editItem(first, 2)
    destination = dialog.sources.findChild(QLineEdit)
    assert destination is not None
    destination.setText(str(tmp_path / "base.bin"))
    qtbot.keyClick(destination, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: bool(dialog._assignments.get("a.xdelta")))
    for name in ("a.xdelta", "b.xdelta"):
        assert dialog._assignments[name]["type"] == "patch"
        assert dialog._assignments[name]["target"].endswith("/base.bin")
    assert not dialog._assignments.get("c.bin")
    dialog.sources.editItem(first, 1)
    action = dialog.sources.findChild(QComboBox)
    assert action is not None
    index = action.findData("overwrite")
    action.setCurrentIndex(index)
    action.activated.emit(index)
    qtbot.keyClick(action, Qt.Key.Key_Return)
    assert all(
        dialog._assignments[name]["type"] == "overwrite"
        for name in ("a.xdelta", "b.xdelta")
    )
    assert not dialog._assignments.get("c.bin")


def test_bulk_browse_file_menu_assigns_one_destination(
    qtbot, tmp_path, monkeypatch, manual_parent
):
    for name in ("a.bin", "b.bin"):
        (tmp_path / name).write_bytes(b"payload")
    parent = manual_parent
    dialog = ManualModInstallDialog(parent, str(tmp_path))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    for item in dialog._items.values():
        item.setSelected(True)
    chosen = tmp_path / "game/base.bin"
    chosen.parent.mkdir()
    choose_file = Mock(return_value=(str(chosen), ""))
    monkeypatch.setattr(
        "ui.dialogs.manual_install.dialog.get_open_file_name", choose_file
    )
    menu = dialog.browse_button.menu()
    assert menu is not None
    menu.actions()[0].trigger()
    choose_file.assert_called_once()
    assert len({entry["target"] for entry in dialog._assignments.values()}) == 1
    assert all(
        entry["target"].endswith("/game/base.bin")
        for entry in dialog._assignments.values()
    )


def test_custom_games_rescan_preserve_unmatched_choices_and_save_confirmed_patch(
    qtbot, tmp_path, monkeypatch, manual_parent
):
    import shutil

    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    shutil.copyfile(
        fixtures / "patches/undertale/patch.xdelta", prepared / "patch.xdelta"
    )
    (prepared / "README.txt").write_text("instructions", encoding="utf-8")
    original_entries = get_all_game_entries()
    games = []
    for index, game_id in enumerate(("custom_wrong", "custom_right", "custom_hidden")):
        game = CustomSingleTabGame(
            CustomGameRecord(game_id, game_id, "game.exe", "base.bin")
        )
        games.append(
            GameEntry(game_id, False, game_id != "custom_hidden", 100 + index, game)
        )
    hidden_builtin = original_entries[0].id
    replace_game_entries(
        [
            replace(entry, is_visible=False) if entry.id == hidden_builtin else entry
            for entry in original_entries
        ]
        + games
    )
    dialog = None
    try:
        parent = manual_parent
        for entry in games:
            root = tmp_path / entry.id
            root.mkdir()
            if entry.id == "custom_right":
                shutil.copyfile(
                    fixtures / "game_data/undertale/data.win", root / "base.bin"
                )
            else:
                (root / "base.bin").write_bytes(b"wrong game version")
            parent.app_state.local_config[entry.game_definition.path_config_key] = str(
                root
            )
        target = tmp_path / "custom_right/base.bin"
        original = target.read_bytes()
        dialog = ManualModInstallDialog(
            parent, str(prepared), initial_game_type="custom_wrong"
        )
        qtbot.addWidget(dialog)
        ids = {
            dialog.game_combo.itemData(index)
            for index in range(dialog.game_combo.count())
        }
        assert {"custom_wrong", "custom_right"} <= ids
        assert "custom_hidden" not in ids
        assert hidden_builtin not in ids
        qtbot.waitUntil(lambda: dialog._detection_thread is None, timeout=10000)
        assert not dialog._assignments.get("patch.xdelta")
        assert dialog.status_label.text() == tr(
            "ui.manual_install_detection_unconfigured", count=1
        )
        dialog._items["patch.xdelta"].setText(2, "${user_path}/previous.bin")
        dialog._items["README.txt"].setText(2, "${user_path}/manual-instructions.txt")
        instructions = dict(dialog._assignments["README.txt"])
        previous = dict(dialog._assignments["patch.xdelta"])
        dialog.game_combo.setCurrentIndex(dialog.game_combo.findData("undertale"))
        qtbot.waitUntil(lambda: dialog._detection_thread is None, timeout=10000)
        assert dialog._assignments["patch.xdelta"] == previous
        assert dialog._assignments["README.txt"] == instructions
        dialog.game_combo.setCurrentIndex(dialog.game_combo.findData("custom_right"))
        qtbot.waitUntil(lambda: dialog._detection_thread is None, timeout=10000)
        assert dialog._assignments["patch.xdelta"]["type"] == "patch"
        assert dialog._assignments["patch.xdelta"]["target"] == "${game_path}/base.bin"
        assert dialog._assignments["patch.xdelta"]["target_hash"].startswith("sha256:")
        assert dialog._assignments["README.txt"] == instructions
        config, _folder = _save_import(dialog, qtbot, monkeypatch)
        assert config["game"] == "custom_right"
        assert isinstance(config["files"], list)
        assert isinstance(config["files"][0], dict)
        assert config["files"][0]["target"] == "${game_path}/base.bin"
        assert target.read_bytes() == original
    finally:
        if dialog is not None:
            dialog._stop_detection()
        replace_game_entries(original_entries)


@pytest.mark.parametrize(
    "suffix", [".txt", ".md", ".markdown", ".html", ".htm", ".PDF"]
)
def test_manual_install_document_formats_and_tab_state(
    qtbot, tmp_path, manual_parent, suffix
):
    from PyQt6.QtGui import QPainter, QPdfWriter

    document = tmp_path / f"Guide{suffix}"
    if suffix == ".PDF":
        writer = QPdfWriter(str(document))
        painter = QPainter(writer)
        painter.drawText(100, 100, "Installation guide")
        painter.end()
        del writer
    else:
        text = (
            "# Installation guide\n\n[Mod page](https://gamebanana.com/)"
            if suffix in {".md", ".markdown"}
            else "<h1>Installation guide</h1>"
            if suffix in {".html", ".htm"}
            else "Installation guide"
        )
        document.write_text(text, encoding="utf-16" if suffix == ".txt" else "utf-8")
    dialog = ManualModInstallDialog(manual_parent, str(tmp_path))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog.show()
    qtbot.waitExposed(dialog)
    size = dialog.size()
    assignments = {name: dict(entry) for name, entry in dialog._assignments.items()}
    assert dialog._document_viewer is None
    dialog.tabs.setCurrentIndex(1)
    viewer = dialog._document_viewer
    assert viewer is not None
    if suffix == ".PDF":
        assert viewer._pdf_document.pageCount() == 1
    else:
        assert viewer.viewer.isReadOnly()
        assert "Installation guide" in viewer.viewer.toPlainText()
        if suffix != ".txt":
            assert viewer.viewer.document().begin().blockFormat().headingLevel() == 1
        if suffix in {".md", ".markdown"}:
            from PyQt6.QtGui import QPalette

            link = viewer.viewer.document().find("Mod page").charFormat()
            assert link.anchorHref() == "https://gamebanana.com/"
            assert link.foreground().color() == viewer.viewer.palette().color(
                QPalette.ColorRole.Text
            )
    dialog.tabs.setCurrentIndex(0)
    dialog.tabs.setCurrentIndex(1)
    assert dialog._document_viewer is viewer
    assert dialog._assignments == assignments
    assert dialog.size() == size
    assert dialog.document_combo.height() == dialog.open_document_button.height()
    dialog.reject()
    assert dialog._document_viewer is None
    assert not (tmp_path / "mods").exists()


def test_manual_install_documents_include_unpacked_patch_instructions(
    qtbot, tmp_path, manual_parent
):
    folder = tmp_path / "patch"
    folder.mkdir()
    (folder / "g3mpatch.json").write_text('{"original": {}}', encoding="utf-8")
    (folder / "README.txt").write_text("Patch instructions", encoding="utf-8")
    dialog = ManualModInstallDialog(manual_parent, str(tmp_path))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    assert len(dialog.all_files) == 1
    assert dialog.document_combo.currentText() == "patch/README.txt"
    dialog.tabs.setCurrentIndex(1)
    assert dialog._document_viewer is not None
    assert dialog._document_viewer.viewer is not None
    assert dialog._document_viewer.viewer.toPlainText() == "Patch instructions"


def test_manual_install_source_double_click_selects_its_document(
    qtbot, tmp_path, manual_parent
):
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    dialog = ManualModInstallDialog(manual_parent, str(tmp_path))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog.show()
    qtbot.waitExposed(dialog)
    index = dialog.sources.indexFromItem(dialog._items["b.txt"], 0)
    position = dialog.sources.visualRect(index).center()
    qtbot.mouseClick(dialog.sources.viewport(), Qt.MouseButton.LeftButton, pos=position)
    qtbot.mouseDClick(
        dialog.sources.viewport(), Qt.MouseButton.LeftButton, pos=position
    )
    assert dialog.tabs.currentIndex() == 1
    assert dialog.document_combo.currentText() == "b.txt"
    assert dialog._document_viewer is not None
    assert dialog._document_viewer.viewer is not None
    assert dialog._document_viewer.viewer.toPlainText() == "b.txt"


@pytest.mark.parametrize("opened", [True, False])
def test_manual_install_external_open_requires_a_click(
    qtbot, tmp_path, manual_parent, monkeypatch, opened
):
    binary = tmp_path / "asset.bin"
    binary.write_bytes(b"\x00\x01\x02")
    open_native = Mock(return_value=opened)
    monkeypatch.setattr(
        "ui.dialogs.manual_install.dialog.open_path_native", open_native
    )
    dialog = ManualModInstallDialog(manual_parent, str(tmp_path))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.tabs.setCurrentIndex(1)
    assert dialog._document_viewer is None
    assert dialog._document_hint.text() == tr("ui.manual_install_external_hint")
    open_native.assert_not_called()
    qtbot.mouseClick(dialog.open_document_button, Qt.MouseButton.LeftButton)
    open_native.assert_called_once_with(str(binary))
    if not opened:
        assert dialog.status_label.text() == tr("ui.manual_install_open_failed")


def test_manual_install_missing_document_does_not_break_validation(
    qtbot, tmp_path, manual_parent, monkeypatch
):
    document = tmp_path / "README.txt"
    document.write_text("instructions", encoding="utf-8")
    dialog = ManualModInstallDialog(manual_parent, str(tmp_path))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    document.unlink()
    dialog.tabs.setCurrentIndex(1)
    assert dialog._document_viewer is not None
    assert dialog._document_viewer.viewer is not None
    assert dialog._document_viewer.viewer.toPlainText() == tr("status.loading_error")
    open_native = Mock()
    monkeypatch.setattr(
        "ui.dialogs.manual_install.dialog.open_path_native", open_native
    )
    dialog._open_document()
    open_native.assert_not_called()
    assert dialog.status_label.text() == tr("ui.manual_install_open_failed")
    dialog.name_edit.clear()
    dialog._on_finish()
    assert dialog.tabs.currentIndex() == 0
    assert dialog.name_edit.property("invalid")
    assert not (tmp_path / "mods").exists()


def test_manual_install_documents_empty_state(qtbot, tmp_path, manual_parent):
    dialog = ManualModInstallDialog(manual_parent, str(tmp_path))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog.tabs.setCurrentIndex(1)
    assert not dialog.document_combo.isEnabled()
    assert not dialog.open_document_button.isEnabled()
    assert dialog._document_hint.text() == tr("dialogs.no_readme_files")


@pytest.mark.parametrize("source_kind", ["folder", "zip"])
@pytest.mark.parametrize("action", ["overwrite", "extract"])
@pytest.mark.parametrize("target_kind", ["folder", "file", "zip"])
def test_manual_container_operations_save_execute_and_restore(
    qtbot, manual_parent, tmp_path, monkeypatch, source_kind, action, target_kind
):
    import zipfile

    from services.mod_operation_executor import ModOperationExecutor
    from utils.mod.operation_plan import ModPathContext, build_mod_operation_plan

    prepared, game_root = tmp_path / "prepared", tmp_path / "game"
    prepared.mkdir()
    game_root.mkdir()
    if source_kind == "folder":
        (prepared / "pack/nested/empty").mkdir(parents=True)
        (prepared / "pack/nested/new.bin").write_bytes(b"new")
        relative = "pack/"
    else:
        relative = "pack.zip"
        with zipfile.ZipFile(prepared / relative, "w") as archive:
            archive.writestr("nested/new.bin", b"new")
            archive.writestr("nested/empty/", b"")
    destination = game_root / ("destination.zip" if target_kind == "zip" else "destination")
    if target_kind == "folder":
        destination.mkdir()
        (destination / "old.bin").write_bytes(b"old")
    elif target_kind == "zip":
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr("old.bin", b"old")
    else:
        destination.write_bytes(b"old")
    original = destination.read_bytes() if destination.is_file() else None
    game = get_game("undertale")
    assert game is not None
    manual_parent.app_state.local_config[game.path_config_key] = str(game_root)
    dialog = ManualModInstallDialog(manual_parent, str(prepared), initial_game_type="undertale")
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    target = "${game_path}/" + destination.name
    dialog._assign(relative, {"type": action, "target": target})
    # Extract has a directory destination. A plain file is not a directory.
    if action == "extract" and target_kind == "file":
        assert not dialog._validate()
        return
    assert dialog._validate(), dialog.status_label.text()
    config, saved = _save_import(dialog, qtbot, monkeypatch)
    context = ModPathContext.create(mod_path=saved, game_path=game_root, game_data_path=None, user_path=tmp_path)
    plan = build_mod_operation_plan(config, context)
    assert not plan.has_errors, plan.findings
    journal = ModOperationExecutor(tmp_path / "session").execute(plan)
    if source_kind == "zip" and action == "overwrite":
        assert destination.is_file()
        with zipfile.ZipFile(destination) as archive:
            assert archive.read("nested/new.bin") == b"new"
            assert "old.bin" not in archive.namelist()
    elif target_kind == "zip" and action == "extract":
        with zipfile.ZipFile(destination) as archive:
            assert archive.read("nested/new.bin") == b"new"
            assert ("old.bin" in archive.namelist()) == (action == "extract")
    else:
        assert (destination / "nested/new.bin").read_bytes() == b"new"
        assert (destination / "nested/empty").is_dir()
        assert (destination / "old.bin").exists() == (action == "extract")
    journal.restore()
    if original is not None:
        assert destination.read_bytes() == original
    else:
        assert sorted(path.name for path in destination.iterdir()) == ["old.bin"]


def test_manual_music_copy_replace_saves_executes_and_restores(qtbot, manual_parent, tmp_path, monkeypatch):
    from services.mod_operation_executor import ModOperationExecutor
    from utils.mod.operation_plan import ModPathContext, build_mod_operation_plan

    prepared, game_root = tmp_path / "prepared", tmp_path / "game"
    prepared.mkdir()
    game_root.mkdir()
    (prepared / "music.ogg").write_bytes(b"OggS-new")
    target = game_root / "music.ogg"
    target.write_bytes(b"OggS-original")
    game = get_game("undertale")
    assert game is not None
    manual_parent.app_state.local_config[game.path_config_key] = str(game_root)
    dialog = ManualModInstallDialog(manual_parent, str(prepared), initial_game_type="undertale")
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog._items["music.ogg"].setSelected(True)
    assert dialog.action_combo.findData("overwrite") >= 0
    assert dialog.action_combo.findData("extract") == -1
    dialog._set_selected_action(dialog.action_combo.findData("overwrite"))
    monkeypatch.setattr("ui.dialogs.manual_install.dialog.get_open_file_name", lambda *args: (str(target), ""))
    dialog._browse_selected(folder=False)
    assert dialog.save_button.isEnabled()
    config, saved = _save_import(dialog, qtbot, monkeypatch)
    assert config["files"] == [{"type": "overwrite", "source": "${mod_path}/files/music.ogg", "target": "${game_path}/music.ogg"}]
    context = ModPathContext.create(mod_path=saved, game_path=game_root, game_data_path=None, user_path=tmp_path)
    journal = ModOperationExecutor(tmp_path / "session").execute(build_mod_operation_plan(config, context))
    assert target.read_bytes() == b"OggS-new"
    journal.restore()
    assert target.read_bytes() == b"OggS-original"


def test_manual_mixed_selection_action_intersection_and_parent_precedence(qtbot, manual_parent, tmp_path):
    import zipfile

    prepared = tmp_path / "prepared"
    (prepared / "pack").mkdir(parents=True)
    (prepared / "pack/file.bin").write_bytes(b"file")
    (prepared / "patch.xdelta").write_bytes(b"patch")
    with zipfile.ZipFile(prepared / "archive.zip", "w") as archive:
        archive.writestr("file.bin", b"file")
    dialog = ManualModInstallDialog(manual_parent, str(prepared))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    for relative in ("pack/", "pack/file.bin", "archive.zip"):
        dialog._items[relative].setSelected(True)
    assert set(dialog._selected_files()) == {"pack/", "archive.zip"}
    assert dialog.action_combo.findData("extract") >= 0
    dialog._items["patch.xdelta"].setSelected(True)
    assert {dialog.action_combo.itemData(index) for index in range(1, dialog.action_combo.count())} == {None, "", "overwrite"}
    dialog._assign("pack/file.bin", {"type": "overwrite", "target": "${game_path}/child.bin"})
    dialog._assign("pack/", {"type": "overwrite", "target": "${game_path}/pack"})
    assert "pack/file.bin" not in dialog._configured_sources()
    dialog._assign("pack/", {})
    assert "pack/file.bin" in dialog._configured_sources()


def test_manual_hide_configured_persists_and_keeps_incomplete_rows_visible(qtbot, manual_parent, tmp_path):
    from services.localization_service import localization_service
    from services.settings_service import SettingsManager
    from utils.file_utils import load_json

    prepared = tmp_path / "prepared"
    (prepared / "pack").mkdir(parents=True)
    (prepared / "pack/file.bin").write_bytes(b"file")
    (prepared / "README.txt").write_text("Guide", encoding="utf-8")
    (prepared / "pending.bin").write_bytes(b"file")
    manual_parent.app_state.config_path = str(tmp_path / "settings.json")
    manual_parent.settings_service = SettingsManager(manual_parent.app_state, Mock(), localization_service, parent=manual_parent)
    dialog = ManualModInstallDialog(manual_parent, str(prepared))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog.hide_configured.setChecked(True)
    dialog._assign("pending.bin", {"type": "overwrite"})
    dialog._assign("pack/", {"type": "extract", "target": "${game_path}/pack"})
    dialog._update_summary()
    assert dialog._items["README.txt"].isHidden()
    assert dialog._items["pack/"].isHidden()
    assert dialog._items["pack/file.bin"].isHidden()
    assert not dialog._items["pending.bin"].isHidden()
    dialog.reject()
    manual_parent.app_state.local_config = load_json(manual_parent.app_state.config_path)
    second = ManualModInstallDialog(manual_parent, str(prepared))
    qtbot.addWidget(second)
    second._stop_detection()
    assert second.hide_configured.isChecked()
    assert second._items["README.txt"].isHidden()
    second.hide_configured.setChecked(False)
    assert not load_json(manual_parent.app_state.config_path)["manual_install_hide_configured"]


@pytest.mark.parametrize("relative", ["pack/", "pending.bin"])
def test_explicit_skip_is_configured_and_does_not_install_descendants(qtbot, manual_parent, tmp_path, relative):
    prepared = tmp_path / "prepared"
    (prepared / "pack").mkdir(parents=True)
    (prepared / "pack/README.txt").write_text("Guide", encoding="utf-8")
    (prepared / "pack/file.bin").write_bytes(b"file")
    (prepared / "pending.bin").write_bytes(b"pending")
    dialog = ManualModInstallDialog(manual_parent, str(prepared))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog._items[relative].setSelected(True)
    dialog._set_selected_action(dialog.action_combo.findData(""))
    dialog.hide_configured.setChecked(True)
    assert dialog._configured(relative)
    assert dialog._items[relative].isHidden()
    if relative.endswith("/"):
        assert dialog._configured("pack/file.bin")
        assert dialog._configured_sources() == []
    else:
        assert dialog._configured_sources() == ["pack/README.txt"]


@pytest.mark.parametrize("unsafe", [False, True])
def test_manual_extract_rejects_invalid_archives_without_saving(qtbot, manual_parent, tmp_path, unsafe):
    import zipfile

    prepared, game_root = tmp_path / "prepared", tmp_path / "game"
    prepared.mkdir()
    game_root.mkdir()
    if unsafe:
        with zipfile.ZipFile(prepared / "pack.zip", "w") as archive:
            archive.writestr("../escape.bin", b"escape")
    else:
        (prepared / "pack.zip").write_bytes(b"not an archive")
    game = get_game("undertale")
    assert game is not None
    manual_parent.app_state.local_config[game.path_config_key] = str(game_root)
    dialog = ManualModInstallDialog(manual_parent, str(prepared), initial_game_type="undertale")
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog._assign("pack.zip", {"type": "extract", "target": "${game_path}/"})
    dialog.hide_configured.setChecked(True)
    dialog._on_finish()
    qtbot.waitUntil(lambda: dialog._save_thread is None)
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert not list(Path(manual_parent.app_state.mods_dir).glob("*/mod_config.json"))
    assert not (tmp_path / "escape.bin").exists()
    assert not dialog._items["pack.zip"].isHidden()
    assert dialog._items["pack.zip"].foreground(2).color().name() == "#f44336"


def test_manual_folder_with_archive_extension_is_still_a_folder(qtbot, manual_parent, tmp_path, monkeypatch):
    from services.mod_operation_executor import ModOperationExecutor
    from utils.mod.operation_plan import ModPathContext, build_mod_operation_plan

    prepared, game_root = tmp_path / "prepared", tmp_path / "game"
    (prepared / "pack.zip/nested").mkdir(parents=True)
    (prepared / "pack.zip/nested/file.bin").write_bytes(b"new")
    game_root.mkdir()
    game = get_game("undertale")
    assert game is not None
    manual_parent.app_state.local_config[game.path_config_key] = str(game_root)
    dialog = ManualModInstallDialog(manual_parent, str(prepared), initial_game_type="undertale")
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog._assign("pack.zip/", {"type": "extract", "target": "${game_path}/"})
    config, saved = _save_import(dialog, qtbot, monkeypatch)
    plan = build_mod_operation_plan(config, ModPathContext.create(mod_path=saved, game_path=game_root, game_data_path=None, user_path=tmp_path))
    assert not plan.has_errors, plan.findings
    journal = ModOperationExecutor(tmp_path / "session").execute(plan)
    assert (game_root / "nested/file.bin").read_bytes() == b"new"
    journal.restore()
    assert not (game_root / "nested").exists()



@pytest.mark.parametrize("patch_name", ["patch.xdelta", "patch.g3mpatch"])
@pytest.mark.parametrize("target_exists", [True, False])
@pytest.mark.parametrize("game_configured", [True, False])
@pytest.mark.parametrize("proceed", [True, False])
def test_unverified_patch_can_be_saved_or_reconfigured(qtbot, manual_parent, tmp_path, monkeypatch, patch_name, target_exists, game_configured, proceed):
    prepared, game_root = tmp_path / "prepared", tmp_path / "game"
    prepared.mkdir()
    game_root.mkdir()
    (prepared / patch_name).write_bytes(b"patch")
    if target_exists:
        (game_root / "base.bin").write_bytes(b"base")
    game = get_game("undertale")
    assert game is not None
    if game_configured:
        manual_parent.app_state.local_config[game.path_config_key] = str(game_root)

    def verify(*_args, **_kwargs):
        raise ValueError(f"{patch_name}: cannot apply patch")

    warnings = []
    def warn(warning):
        warnings.append((warning.parentWidget(), warning.windowTitle(), warning.text(), warning.standardButtons(), warning.standardButton(warning.defaultButton())))
        return QMessageBox.StandardButton.Save if proceed else QMessageBox.StandardButton.Cancel

    monkeypatch.setattr("ui.dialogs.manual_install.workers.verify_operations", verify)
    monkeypatch.setattr(DynamicMessageBox, "exec", warn)
    dialog = ManualModInstallDialog(manual_parent, str(prepared), initial_game_type="undertale")
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog._assign(patch_name, {"type": "patch", "target": "${game_path}/base.bin", "target_hash": "sha256:" + "a" * 64})
    dialog._on_finish()
    qtbot.waitUntil(lambda: not dialog._checking_save)
    assert len(warnings) == 1
    assert warnings[0][2] == tr("ui.manual_install_patch_warning")
    assert warnings[0][-1] == QMessageBox.StandardButton.Cancel
    if proceed:
        qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted)
        config = load_mod_config(next((tmp_path / "mods").glob("*/mod_config.json")))
        assert isinstance(config["files"], list)
        assert config["files"] == [{"type": "patch", "source": "${mod_path}/files/" + patch_name, "target": "${game_path}/base.bin"}]
    else:
        assert not (tmp_path / "mods").exists()
        assert dialog.sources.isEnabled()
        assert dialog.save_button.isEnabled()
        assert dialog._assignments[patch_name]["target"] == "${game_path}/base.bin"
        assert dialog._items[patch_name].foreground(2).color().name() != "#f44336"
    assert (game_root / "base.bin").exists() == target_exists
    if target_exists:
        assert (game_root / "base.bin").read_bytes() == b"base"


@pytest.mark.parametrize("source_kind", ["folder", "file"])
@pytest.mark.parametrize("target_kind", ["game", "parent"])
def test_manual_replacement_cannot_clear_game_root_or_its_parent(qtbot, manual_parent, tmp_path, source_kind, target_kind):
    prepared, game_root = tmp_path / "prepared", tmp_path / "installed/game"
    (prepared / "pack").mkdir(parents=True)
    (prepared / "pack/file.bin").write_bytes(b"file")
    (prepared / "replacement.bin").write_bytes(b"replacement")
    game_root.mkdir(parents=True)
    (game_root / "game.bin").write_bytes(b"game")
    game = get_game("undertale")
    assert game is not None
    manual_parent.app_state.local_config[game.path_config_key] = str(game_root)
    dialog = ManualModInstallDialog(manual_parent, str(prepared), initial_game_type="undertale")
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    relative = "pack/" if source_kind == "folder" else "replacement.bin"
    target = game_root if target_kind == "game" else game_root.parent
    dialog._assign(relative, {"type": "overwrite", "target": str(target)})
    assert not dialog._validate()
    assert dialog._items[relative].foreground(2).color().name() == "#f44336"
    assert (game_root / "game.bin").read_bytes() == b"game"



def test_empty_folders_and_individually_configured_children_control_save(qtbot, manual_parent, tmp_path):
    prepared = tmp_path / "prepared"
    (prepared / "pack/nested").mkdir(parents=True)
    (prepared / "empty").mkdir()
    (prepared / "pack/nested/file.bin").write_bytes(b"file")
    (prepared / "pack/README.txt").write_text("Guide", encoding="utf-8")
    dialog = ManualModInstallDialog(manual_parent, str(prepared))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog._items["pack/nested/file.bin"].setText(2, "${user_path}/file.bin")
    assert dialog._configured("pack/")
    assert dialog._items["pack/"].text(1) == tr("ui.manual_install_configured")
    assert not dialog._configured("empty/")
    assert not cast(QPushButton, dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)).isEnabled()
    dialog._items["empty/"].setSelected(True)
    dialog._set_selected_action(dialog.action_combo.findData(""))
    assert cast(QPushButton, dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)).isEnabled()
    assert dialog.configure_button is not None
    assert dialog.configure_button.isEnabled()
    assert set(dialog._configured_sources()) == {"pack/README.txt", "pack/nested/file.bin"}
    dialog._set_selected_action(dialog.action_combo.findText(tr("ui.manual_install_unconfigured")))
    assert dialog._items["empty/"].text(1) == tr("ui.manual_install_unconfigured")
    assert not cast(QPushButton, dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)).isEnabled()
    dialog._assign("pack/", {"type": "overwrite"})
    dialog._update_summary()
    assert not dialog._configured("pack/")
    dialog._on_finish()
    assert dialog._items["pack/"].foreground(2).color().name() == "#f44336"
    assert not (tmp_path / "mods").exists()


def test_action_cell_distinguishes_unconfigured_and_explicit_skip(qtbot, manual_parent, tmp_path):
    (tmp_path / "file.bin").write_bytes(b"payload")
    dialog = ManualModInstallDialog(manual_parent, str(tmp_path))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    index = dialog.sources.indexFromItem(dialog._items["file.bin"], 1)
    delegate = dialog.sources.itemDelegateForColumn(1)
    assert delegate is not None
    editor = delegate.createEditor(dialog.sources.viewport(), QStyleOptionViewItem(), index)
    assert isinstance(editor, QComboBox)
    qtbot.addWidget(editor)
    delegate.setEditorData(editor, index)
    assert editor.currentData() is None
    assert editor.currentText() == tr("ui.manual_install_unconfigured")
    editor.setCurrentIndex(editor.findData(""))
    delegate.setModelData(editor, dialog.sources.model(), index)
    assert dialog._configured("file.bin")
    assert cast(QPushButton, dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)).isEnabled()
    delegate.setEditorData(editor, index)
    assert editor.currentData() == ""
    editor.setCurrentIndex(editor.findData(None))
    delegate.setModelData(editor, dialog.sources.model(), index)
    assert not dialog._configured("file.bin")
    assert dialog._items["file.bin"].text(1) == tr("ui.manual_install_unconfigured")
    assert not cast(QPushButton, dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)).isEnabled()


def test_long_manual_install_errors_keep_save_and_cancel_visible(qtbot, manual_parent, tmp_path):
    from PyQt6.QtWidgets import QScrollArea

    (tmp_path / "file.bin").write_bytes(b"payload")
    dialog = ManualModInstallDialog(manual_parent, str(tmp_path))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    dialog.status_label.setText("\n".join(f"Invalid destination {index}" for index in range(1000)))
    dialog.resize(800, 480)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.height() == 480
    parent_widget = dialog.status_label.parentWidget()
    assert parent_widget is not None
    scroll = parent_widget.parentWidget()
    assert isinstance(scroll, QScrollArea)
    assert cast(QScrollBar, scroll.verticalScrollBar()).maximum() > 0
    for button in dialog.buttons.buttons():
        position = button.mapTo(dialog, button.rect().topLeft())
        assert dialog.rect().contains(button.rect().translated(position))
    qtbot.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel), Qt.MouseButton.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Rejected



def test_manual_install_can_close_and_delete_while_detection_runs(qtbot, manual_parent, tmp_path, monkeypatch):
    from PyQt6 import sip
    from PyQt6.QtCore import QTimer

    (tmp_path / "file.bin").write_bytes(b"payload")
    started, released = threading.Event(), threading.Event()

    def detect(_files, _context, _apply, *, cancelled, progress, **_options):
        started.set()
        try:
            assert released.wait(5)
            assert cancelled()
            progress(1, 1)
            return {"file.bin": {"type": "overwrite", "target": "${game_path}/file.bin"}}
        finally:
            released.set()

    monkeypatch.setattr("ui.dialogs.manual_install.workers.detect_operations", detect)
    dialog = ManualModInstallDialog(manual_parent, str(tmp_path))
    dialog.show()
    qtbot.waitUntil(started.is_set)
    timer_ran = []
    QTimer.singleShot(0, lambda: timer_ran.append(True))
    qtbot.waitUntil(lambda: bool(timer_ran))
    thread = dialog._detection_thread
    results = []
    assert thread is not None
    thread.result_ready.connect(lambda *args: results.append(args))
    try:
        assert thread is not None
        with qtbot.waitSignal(thread.finished):
            qtbot.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel), Qt.MouseButton.LeftButton)
            assert dialog._detection_thread is None
            assert thread is not None
            assert thread.isInterruptionRequested()
            dialog.deleteLater()
            qtbot.waitUntil(lambda: sip.isdeleted(dialog))
            released.set()
    finally:
        released.set()
    assert not results
    assert not (tmp_path / "mods").exists()



@pytest.mark.parametrize("configure", [False, True])
def test_manual_save_tooltip_tracks_configuration(qtbot, manual_parent, tmp_path, configure):
    (tmp_path / "pending.bin").write_bytes(b"payload")
    dialog = ManualModInstallDialog(manual_parent, str(tmp_path))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    button = dialog.configure_button if configure else dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    expected = tr("tooltips.manual_install_save_unconfigured", count=1)
    assert button is not None
    assert not button.isEnabled()
    assert button is not None
    assert button.toolTip() == expected
    dialog._assign("pending.bin", {"type": "overwrite"})
    dialog._update_summary()
    assert button is not None
    assert not button.isEnabled()
    assert button is not None
    assert button.toolTip() == expected
    dialog._items["pending.bin"].setText(2, "${user_path}/pending.bin")
    assert button is not None
    assert button.isEnabled()
    assert button is not None
    assert not button.toolTip()


def test_empty_manual_install_save_tooltip_explains_how_to_retry(qtbot, manual_parent, tmp_path):
    dialog = ManualModInstallDialog(manual_parent, str(tmp_path))
    qtbot.addWidget(dialog)
    dialog._stop_detection()
    for button in (dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), dialog.configure_button):
        assert button is not None
        assert not button.isEnabled()
        assert button is not None
        assert button.toolTip() == tr("tooltips.manual_install_save_no_files")


def test_manual_install_adds_a_custom_game_and_selects_it(
    qtbot, manual_parent, tmp_path, monkeypatch
):
    import ui.dialogs.manual_install.dialog as module
    from ui.dialogs.custom_game_dialog import CustomGameDialog

    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "patch.xdelta").write_text("patch", encoding="utf-8")
    entries = [SimpleNamespace(id="deltarune", display_name="DELTARUNE")]

    def create(**values):
        entries.append(SimpleNamespace(id="mystery", display_name=values["display_name"]))
        return entries[-1]

    registry = Mock(create_custom_game=Mock(side_effect=create))
    vars(manual_parent)["game_registry_service"] = registry
    monkeypatch.setattr(module, "get_visible_game_entries", lambda: list(entries))
    monkeypatch.setattr(module, "get_game", lambda _game_id: None)

    def accept(dialog):
        dialog.display_name_edit.setText("Mystery")
        dialog.primary_executable_edit.setText("mystery.exe")
        dialog.data_file_name_edit.setText("data.win")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(CustomGameDialog, "exec", accept)
    dialog = ManualModInstallDialog(manual_parent, str(prepared))
    assert dialog.add_game_button.toolTip() == tr("games.add_custom_title")
    assert not dialog.add_game_button.icon().isNull()

    dialog.add_game_button.click()

    assert [dialog.game_combo.itemData(i) for i in range(dialog.game_combo.count())] == [
        "deltarune",
        "mystery",
    ]
    assert dialog.game_combo.currentData() == "mystery"
    assert registry.create_custom_game.call_args.kwargs["primary_executable"] == "mystery.exe"
    dialog._stop_detection()


def test_manual_install_hides_the_add_game_button_without_a_registry(manual_parent, tmp_path):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "patch.xdelta").write_text("patch", encoding="utf-8")
    dialog = ManualModInstallDialog(manual_parent, str(prepared))

    assert dialog.add_game_button.isHidden()
    dialog._stop_detection()
