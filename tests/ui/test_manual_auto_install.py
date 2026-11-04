"""A mod whose files all set themselves up installs without the manual dialog."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QWidget

from models.game_modes import get_game
from ui.dialogs.manual_install.auto import auto_manual_install

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
# Each platform runs its own build of the game data file.
DATA_FILE = {"win32": "data.win", "darwin": "game.ios"}.get(sys.platform, "game.unx")


@pytest.fixture
def parent(qtbot, tmp_path):
    widget = QWidget()
    game = get_game("undertale")
    assert game is not None
    state = SimpleNamespace(local_config={game.path_config_key: str(tmp_path / "game")}, mods_dir=str(tmp_path / "mods"))
    vars(widget)["app_state"] = state
    vars(widget)["mod_service"] = object()
    qtbot.addWidget(widget)
    return widget


def _game_with_patch(tmp_path, valid_base: bool) -> Path:
    prepared, game_root = tmp_path / "prepared", tmp_path / "game"
    prepared.mkdir()
    game_root.mkdir()
    shutil.copyfile(FIXTURES / "patches/undertale/patch.xdelta", prepared / "patch.xdelta")
    data = game_root / DATA_FILE
    if valid_base:
        shutil.copyfile(FIXTURES / "game_data/undertale/data.win", data)
    else:
        data.write_bytes(b"wrong base")
    return prepared


def test_a_patch_that_fits_the_game_file_installs_by_itself(parent, tmp_path):
    prepared = _game_with_patch(tmp_path, valid_base=True)
    original = (tmp_path / "game" / DATA_FILE).read_bytes()

    assert auto_manual_install(parent, str(prepared), initial_game_type="undertale")

    assert len(list((tmp_path / "mods").glob("*/mod_config.json"))) == 1
    assert (tmp_path / "game" / DATA_FILE).read_bytes() == original


def test_a_patch_that_does_not_fit_is_left_to_the_user(parent, tmp_path):
    prepared = _game_with_patch(tmp_path, valid_base=False)

    assert not auto_manual_install(parent, str(prepared), initial_game_type="undertale")

    assert not (tmp_path / "mods").exists()


def test_a_mod_with_only_documents_is_left_to_the_user(parent, tmp_path):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "README.md").write_text("Guide", encoding="utf-8")

    assert not auto_manual_install(parent, str(prepared), initial_game_type="undertale")

    assert not (tmp_path / "mods").exists()


def test_documents_next_to_a_fitting_patch_become_info_files_and_the_mod_installs(parent, tmp_path):
    prepared = _game_with_patch(tmp_path, valid_base=True)
    (prepared / "README.md").write_text("Guide", encoding="utf-8")
    (prepared / "notes.txt").write_text("Notes", encoding="utf-8")

    assert auto_manual_install(parent, str(prepared), initial_game_type="undertale")

    assert len(list((tmp_path / "mods").glob("*/mod_config.json"))) == 1


def test_documents_keep_the_mod_in_manual_installation_when_the_setting_is_off(parent, tmp_path):
    parent.app_state.local_config["manual_install_docs_as_info"] = False
    prepared = _game_with_patch(tmp_path, valid_base=True)
    (prepared / "README.md").write_text("Guide", encoding="utf-8")

    assert not auto_manual_install(parent, str(prepared), initial_game_type="undertale")

    assert not (tmp_path / "mods").exists()
