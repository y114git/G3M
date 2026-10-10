"""GameBanana metadata and page-link installation regressions."""

import json
import zipfile
from typing import cast
from unittest.mock import Mock

import pytest
import requests
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QDialog, QWidget

from adapters.gamebanana_adapter import GameBananaAPI
from app.protocol_handler import _enqueue_g3m_url
from controllers.mod.operations_controller import ModOperationsController
from models.download_models import TargetKind
from ui.dialogs.downloads_dialog import DownloadsDialog
from ui.dialogs.file_picker_dialog import GameBananaFilePickerDialog
from ui.dialogs.manual_install.workers import MetadataThread
from utils.mod.config import load_mod_config
from utils.mod.utils import parse_gamebanana_mod_url, resolve_mod_icon
from workers.install.url_install_worker import UrlInstallThread
from workers.use_worker import UseWorker


@pytest.fixture
def profile(monkeypatch):
    data = {
        "_idRow": 42, "_sName": "Current name", "_sVersion": "9.9",
        "_sDescription": "Current description", "_aSubmitter": {"_sName": "Author"},
        "_aGame": {"_idRow": 6755},
        "_aPreviewMedia": {"_aImages": [{"_sBaseUrl": "https://images.gamebanana.com/img/ss/mods", "_sFile": "current.jpg"}]},
        "_aFiles": [
            {"_idRow": 11, "_sFile": "pack.g3m", "_sVersion": "2.1", "_sMd5Checksum": "a" * 32, "_aModManagerIntegrations": [{"_idToolRow": 20615}]},
            {"_idRow": 22, "_sFile": "music.zip", "_sVersion": "1.5"},
            {"_idRow": 33, "_sFile": "old.zip", "_bIsArchived": True},
            {"_idRow": 44, "_sFile": "missing.zip", "_bHasContents": False},
        ],
    }
    monkeypatch.setattr(GameBananaAPI, "get_mod_profile_page", Mock(return_value=data))
    return data


@pytest.mark.parametrize(("package", "own_icon"), [
    ("g3m", None), ("g3m", "icon.png"), ("g3m", "https://example.com/own.png"),
    ("deltamod", None), ("deltamod", "icon.png"), ("deltamod", "_icon.png"),
])
def test_install_persists_icon_priority_and_selected_file_version(qapp, tmp_path, profile, package, own_icon):
    archive_path, mods = tmp_path / "pack.zip", tmp_path / "mods"
    mods.mkdir()
    with zipfile.ZipFile(archive_path, "w") as archive:
        if package == "g3m":
            config = {"config_version": "2.0.0", "id": "pack", "name": "Pack", "version": "1.0", "authors": ["Package author"], "game": "deltarune", "files": []}
            if own_icon:
                config["icon"] = own_icon if own_icon.startswith("https:") else f"${{mod_path}}/{own_icon}"
            archive.writestr("mod_config.json", json.dumps(config))
        else:
            archive.writestr("_deltamodInfo.json", json.dumps({"metadata": {"name": "Pack", "author": ["Package author"], "game": "toby.deltarune"}}))
            archive.writestr("modding.xml", '<patches><patch to="./chapter1_windows/data.win" patch="patch.xdelta" type="xdelta" /></patches>')
            archive.writestr("patch.xdelta", b"patch")
        if own_icon and not own_icon.startswith("https:"):
            archive.writestr(own_icon, b"package icon")
    worker = UseWorker("install", str(archive_path), TargetKind.MOD, str(mods), {"gb_mod_id": 42, "icon": "https://example.com/old.jpg", "version": "2.1"})
    finished = []
    worker.use_finished.connect(lambda *args: finished.append(args))
    worker.run()
    assert finished == [("install", True, False, "")]
    path = next(mods.glob("*/mod_config.json"))
    saved = load_mod_config(path)
    expected = own_icon if own_icon and own_icon.startswith("https:") else f"${{mod_path}}/{own_icon}" if own_icon else "https://images.gamebanana.com/img/ss/mods/current.jpg"
    assert saved["icon"] == expected
    assert saved["version"] == "2.1"
    assert resolve_mod_icon(saved, str(path.parent)) == (str(path.parent / own_icon) if own_icon and not own_icon.startswith("https:") else expected)


@pytest.mark.parametrize("response", [None, {}, {"_idRow": 42}, requests.RequestException("offline")])
def test_refresh_keeps_cached_values_when_profile_data_is_unavailable(tmp_path, monkeypatch, response):
    fetch = Mock(side_effect=response) if isinstance(response, Exception) else Mock(return_value=response)
    monkeypatch.setattr(GameBananaAPI, "get_mod_profile_page", fetch)
    metadata = {"gb_mod_id": 42, "name": "Cached", "icon": "https://example.com/cached.png", "version": "2.1"}
    worker = UseWorker("refresh", "", TargetKind.MOD, str(tmp_path), metadata)
    refreshed = worker._build_gb_metadata()
    assert refreshed["name"] == metadata["name"]
    assert refreshed["icon"] == metadata["icon"]
    assert refreshed["version"] == metadata["version"]


def test_refresh_keeps_full_description(profile):
    profile["_sDescription"] = "Full description. " * 30
    assert GameBananaAPI().get_install_metadata({"mod_id": 42})["description"] == profile["_sDescription"]


def test_supported_files_share_integration_metadata(profile, monkeypatch):
    from config.config import GAMEBANANA_TOOL_ID_DELTAMOD

    monkeypatch.setattr(GameBananaAPI, "_compatibility_cache", {})
    profile["_aFiles"][1]["_aModManagerIntegrations"] = [
        {"_idToolRow": str(GAMEBANANA_TOOL_ID_DELTAMOD), "_sName": "DELTAMOD"}, None, {"_idToolRow": "invalid"},
    ]
    supported = GameBananaAPI().get_supported_files_for_mod(42)
    assert supported["has_g3m_file"] and supported["has_deltamod_file"]
    assert supported["preferred_format"] == "g3m"
    assert [file["tool_names"] for file in supported["supported_files"]] == [["20615"], ["DELTAMOD"]]
    assert supported["tool_ids"] == sorted([20615, GAMEBANANA_TOOL_ID_DELTAMOD])


@pytest.mark.parametrize(("url", "item_type"), [
    ("https://gamebanana.com/mods/42", "Mod"),
    ("http://www.gamebanana.com/wips/42/?foo=bar#files", "Wip"),
    ("g3m://https://gamebanana.com/mods/42", "Mod"),
    ("deltahub://https//gamebanana.com/wips/42", "Wip"),
])
@pytest.mark.parametrize("file_container", [list, dict])
def test_page_links_load_metadata_and_all_available_files(qapp, profile, url, item_type, file_container):
    if file_container is dict:
        profile["_aFiles"] = {str(entry["_idRow"]): entry for entry in profile["_aFiles"]}
    worker = UrlInstallThread(None, url)
    loaded, failures = [], []
    worker.gamebanana_mod_ready.connect(lambda _task, mod: loaded.append(mod))
    worker.result_ready.connect(lambda *args: failures.append(args))
    worker.run()
    assert not failures
    assert len(loaded) == 1
    mod = loaded[0]
    assert mod.id == f"gb_{item_type.casefold()}_42"
    assert mod.icon.endswith("/current.jpg")
    assert mod.name == "Current name"
    assert mod.game == "deltarune"
    assert [file["id"] for file in mod.gamebanana_supported_files] == [11, 22]
    assert mod.gamebanana_supported_files[0]["name"] == "pack.g3m"
    assert mod.gamebanana_supported_files[0]["md5"] == "a" * 32
    assert mod.gamebanana_supported_files[0]["compatibility"] == "g3m"
    assert cast(Mock, GameBananaAPI.get_mod_profile_page).call_args.kwargs["itemtype"] == item_type


@pytest.mark.parametrize("url", ["https://gamebanana.com.evil.example/mods/42", "https://gamebanana.com/dl/42", "https://example.com/mods/42", "https://gamebanana.com/mods/42/files", "file://gamebanana.com/mods/42", "https://user@gamebanana.com/mods/42", "https://gamebanana.com/mods/nope"])
def test_only_gamebanana_page_links_are_recognized(url):
    assert parse_gamebanana_mod_url(url) is None


@pytest.mark.parametrize("case", ["no_profile", "no_files", "offline", "cancelled"])
def test_page_resolution_failure_or_cancellation_never_starts_install(qapp, profile, monkeypatch, case):
    worker = UrlInstallThread(None, "https://gamebanana.com/mods/42")
    loaded, failures = [], []
    worker.gamebanana_mod_ready.connect(lambda _task, mod: loaded.append(mod) if mod is not None else None)
    worker.result_ready.connect(lambda *args: failures.append(args))
    if case == "no_profile":
        monkeypatch.setattr(GameBananaAPI, "get_mod_profile_page", lambda *args, **kwargs: None)
    elif case == "no_files":
        profile["_aFiles"] = []
    elif case == "offline":
        monkeypatch.setattr(GameBananaAPI, "get_mod_profile_page", Mock(side_effect=requests.RequestException("offline")))
    else:
        worker.cancel()
    worker.run()
    assert not loaded
    assert bool(failures) == (case != "cancelled")
    assert all(success is False and message for success, message in failures)


@pytest.mark.parametrize("accepted", [True, False])
def test_page_worker_opens_existing_picker_on_gui_thread(qtbot, app_state, profile, monkeypatch, accepted):
    parent = QWidget()
    qtbot.addWidget(parent)
    controller = ModOperationsController(app_state, Mock(), Mock(), parent)
    vars(parent)["mod_ops"] = controller
    controller._notify_gamebanana_card_refresh = Mock()
    controller._enqueue_gamebanana_download = Mock()
    threads = []

    def choose(dialog):
        threads.append(QThread.currentThread())
        assert dialog.list_widget.count() == 2
        dialog.list_widget.setCurrentRow(1)
        return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected

    monkeypatch.setattr(GameBananaFilePickerDialog, "exec", choose)
    worker = UrlInstallThread(parent, "https://gamebanana.com/mods/42")
    app_state.current_task, app_state.is_installing = worker, True
    worker.start()
    qtbot.waitUntil(lambda: bool(threads))
    qtbot.waitUntil(lambda: not worker.isRunning())
    assert threads == [parent.thread()]
    assert not app_state.is_installing
    assert app_state.current_task is None
    assert controller._enqueue_gamebanana_download.call_count == int(accepted)
    if accepted:
        assert controller._enqueue_gamebanana_download.call_args.args[1]["id"] == 22


@pytest.mark.parametrize("stale", [True, False])
def test_cancelled_or_replaced_page_task_cannot_open_picker(qapp, app_state, stale):
    parent = QWidget()
    controller = ModOperationsController(app_state, Mock(), Mock(), parent)
    vars(parent)["mod_ops"] = controller
    controller.install_mod = Mock()
    worker = UrlInstallThread(parent, "https://gamebanana.com/mods/42")
    app_state.current_task, app_state.is_installing = worker, True
    if stale:
        app_state.current_task = object()
    else:
        worker.cancel()
    worker.gamebanana_mod_ready.emit(worker, object())
    controller.install_mod.assert_not_called()
    assert app_state.is_installing is stale
    assert (app_state.current_task is None) is not stale
    parent.deleteLater()


@pytest.mark.parametrize("section", ["mods", "wips"])
@pytest.mark.parametrize("accepted", [True, False])
def test_protocol_page_link_routes_to_profile_loader(monkeypatch, section, accepted):
    confirmation = Mock()
    confirmation.return_value.exec.return_value = accepted
    monkeypatch.setattr("ui.dialogs.confirm_external_download_dialog.ConfirmExternalDownloadDialog", confirmation)
    window = Mock()
    url = f"https://gamebanana.com/{section}/42"
    _enqueue_g3m_url(window, f"g3m://{url}")
    confirmation.assert_called_once()
    assert window.mod_service.install_from_url.call_count == int(accepted)
    if accepted:
        window.mod_service.install_from_url.assert_called_once_with(url)
    window.downloads_manager.enqueue_with_feedback.assert_not_called()


@pytest.mark.parametrize("url", ["https://gamebanana.com/mods/42", "https://gamebanana.com/wips/42", "https://example.com/pack.zip"])
def test_downloads_page_links_resolve_before_enqueuing(qtbot, app_state, url):
    parent = QWidget()
    qtbot.addWidget(parent)
    service = Mock()
    vars(parent)["mod_service"] = service
    manager = Mock(records=[])
    manager.parent.return_value = parent
    dialog = DownloadsDialog(manager, app_state, parent)
    qtbot.addWidget(dialog)
    dialog._enqueue_url(url)
    if parse_gamebanana_mod_url(url) is not None:
        service.install_from_url.assert_called_once_with(url)
        manager.enqueue.assert_not_called()
    else:
        assert manager.enqueue.call_args.kwargs["source_url"] == url
        manager.parent.assert_not_called()


def test_metadata_client_initialization_failure_keeps_manual_import_usable(qtbot, monkeypatch):
    monkeypatch.setattr("ui.dialogs.manual_install.workers.GameBananaAPI", Mock(side_effect=requests.RequestException("session unavailable")))
    worker = MetadataThread({"mod_id": 42})
    result = []
    worker.result_ready.connect(result.append)
    worker.start()
    qtbot.waitUntil(lambda: bool(result))
    qtbot.waitUntil(lambda: not worker.isRunning())
    assert result == [{}]
