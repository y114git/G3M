"""GameBanana 1-click links: parsing, queueing and unpacking of files without an extension."""

import io
import zipfile
from typing import cast
from unittest.mock import Mock, patch

import pytest
from PyQt6.QtWidgets import QListWidgetItem

from app.protocol_handler import _enqueue_g3m_url
from models.download_models import SourceKind
from utils.mod.archive import archive_suffix_from_content
from utils.mod.utils import parse_gamebanana_download_link
from workers.download_worker import DownloadWorker


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://gamebanana.com/mmdl/1863022", ("1863022", None)),
        ("https//gamebanana.com/mmdl/1863022?toolid=20615", ("1863022", None)),
        ("https//gamebanana.com/mmdl/1863022,Mod,730367", ("1863022", ("Mod", "730367"))),
        ("https://www.gamebanana.com/mmdl/1863022,wip,102106?toolid=20615", ("1863022", ("Wip", "102106"))),
        ("gamebanana.com/mmdl/5/", ("5", None)),
    ],
)
def test_parse_gamebanana_download_link(text, expected):
    assert parse_gamebanana_download_link(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "https://gamebanana.com.evil.test/mmdl/1,Mod,2",
        "https://evil.test/gamebanana.com/mmdl/1",
        "https://gamebanana.com/mmdl/abc",
        "https://gamebanana.com/mods/730367",
        "https://gamebanana.com/mmdl/1,Tool,2",
        "",
    ],
)
def test_parse_gamebanana_download_link_rejects_other_links(text):
    assert parse_gamebanana_download_link(text) is None


@patch("ui.dialogs.confirm_external_download_dialog.ConfirmExternalDownloadDialog")
def test_one_click_with_mod_id_is_queued_as_a_gamebanana_download(dialog):
    dialog.return_value.exec.return_value = True
    w = Mock()

    _enqueue_g3m_url(w, "g3m://https//gamebanana.com/mmdl/1863022,Mod,730367?toolid=20615")

    kwargs = w.downloads_manager.enqueue_with_feedback.call_args.kwargs
    assert kwargs["source_kind"] == SourceKind.GAMEBANANA
    assert kwargs["source_url"] == "https://gamebanana.com/dl/1863022"
    assert kwargs["canonical_key"] == "gb_mod_730367_1863022"
    assert kwargs["metadata"] == {"gb_mod_id": 730367, "item_type": "mod", "gb_file_id": 1863022}


@patch("ui.dialogs.confirm_external_download_dialog.ConfirmExternalDownloadDialog")
def test_one_click_without_mod_id_keeps_the_link_as_it_is(dialog):
    dialog.return_value.exec.return_value = True
    w = Mock()

    _enqueue_g3m_url(w, "g3m://https//gamebanana.com/mmdl/1863022?toolid=20615")

    kwargs = w.downloads_manager.enqueue_with_feedback.call_args.kwargs
    assert kwargs["source_kind"] == SourceKind.G3M_PROTOCOL
    assert kwargs["source_url"] == "https://gamebanana.com/mmdl/1863022?toolid=20615"


def test_archive_type_is_read_from_the_first_bytes(tmp_path):
    cases = {
        "zip": (b"PK\x03\x04rest", ".zip"),
        "empty_zip": (b"PK\x05\x06rest", ".zip"),
        "seven": (b"7z\xbc\xaf\x27\x1c\x00\x04", ".7z"),
        "rar": (b"Rar!\x1a\x07\x00", ".rar"),
        "text": (b"hello world", None),
        "empty": (b"", None),
    }
    for name, (content, suffix) in cases.items():
        path = tmp_path / name
        path.write_bytes(content)
        assert archive_suffix_from_content(path) == suffix
    assert archive_suffix_from_content(tmp_path / "missing") is None


def test_download_without_extension_is_renamed_to_its_archive_type(qapp, tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mod_config.json", "{}")
    target = tmp_path / "id__1863022"
    worker = DownloadWorker("record", "https://gamebanana.com/mmdl/1863022", str(target))
    finished = []
    worker.download_finished.connect(lambda *args: finished.append(args))
    monkeypatch.setattr("utils.network_utils.get_session", object)
    monkeypatch.setattr(
        "utils.network_utils.download_file",
        lambda _session, _url, path, **_kwargs: target.write_bytes(buffer.getvalue()),
    )

    worker.run()

    assert finished[0][1] is True
    assert finished[0][3] == str(target) + ".zip"
    assert (tmp_path / "id__1863022.zip").is_file()
    assert not target.exists()


def test_file_picker_puts_the_installable_package_before_a_bare_xdelta_one():
    from utils.mod.utils import sort_gamebanana_files_by_priority

    xdelta = {"id": 2, "name": "dojoplus_xdelta_96734.zip", "description": "XDELTA Package", "compatibility": "g3m", "timestamp": 200}
    package = {"id": 1, "name": "dojoplus_8b527.zip", "description": "G3M Package", "compatibility": "g3m", "timestamp": 150}

    assert sort_gamebanana_files_by_priority([xdelta, package]) == [package, xdelta]


def test_file_picker_prefers_the_g3m_package_over_deltamod_xdelta_and_manual_ones():
    from utils.mod.utils import sort_gamebanana_files_by_priority

    def file(file_id, name, timestamp):
        return {"id": file_id, "name": name, "compatibility": "g3m", "timestamp": timestamp}

    files = [
        file(4, "mod-v2233-manual.zip", 400),
        file(3, "mod-v2233-xdelta.zip", 300),
        file(2, "mod-v2233-deltamod.zip", 200),
        file(1, "mod-v2233-g3m.zip", 100),
    ]

    assert [f["id"] for f in sort_gamebanana_files_by_priority(files)] == [1, 2, 4, 3]


def test_file_picker_preselects_the_g3m_package_and_names_each_file(qapp):
    from ui.dialogs.file_picker_dialog import GameBananaFilePickerDialog

    xdelta = {"id": 2, "name": "dojoplus_xdelta_96734.zip", "description": "XDELTA Package", "compatibility": "g3m", "timestamp": 200}
    package = {"id": 1, "name": "dojoplus_8b527.zip", "description": "G3M Package", "compatibility": "g3m", "timestamp": 150}

    dialog = GameBananaFilePickerDialog(None, [xdelta, package], "Dojo+")

    selected = dialog.get_selected_file()
    assert selected is not None
    assert selected["id"] == 1
    assert [cast(QListWidgetItem, dialog.list_widget.item(i)).text() for i in range(2)] == [
        "dojoplus_8b527.zip (G3M Package)",
        "dojoplus_xdelta_96734.zip (XDELTA Package)",
    ]
