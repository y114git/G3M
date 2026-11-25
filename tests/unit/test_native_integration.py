"""Tests for native OS dialog and open helpers."""

from __future__ import annotations

import os
import types

from utils import native_integration


def test_open_url_native_uses_shell_execute_on_windows(monkeypatch):
    shell32 = types.SimpleNamespace(
        ShellExecuteW=lambda *_args: 33,
    )
    monkeypatch.setattr(native_integration.os, "name", "nt")
    monkeypatch.setattr(
        native_integration.ctypes,
        "windll",
        types.SimpleNamespace(shell32=shell32),
        raising=False,
    )
    assert native_integration.open_url_native("https://example.com") is True


def test_open_path_native_uses_subprocess_on_linux(monkeypatch):
    calls = []

    def fake_popen(command):
        calls.append(command)
        return object()

    monkeypatch.setattr(native_integration.os, "name", "posix")
    monkeypatch.setattr(native_integration.sys, "platform", "linux")
    monkeypatch.setattr(native_integration.subprocess, "Popen", fake_popen)
    assert native_integration.open_path_native("/var/example") is True
    assert calls == [["xdg-open", "/var/example"]]


def test_get_open_file_name_uses_qt_dialog_without_tkinter(monkeypatch):
    calls = []
    parent = object()

    def fake_get_open_file_name(parent_arg, caption, directory, file_filter):
        calls.append((parent_arg, caption, directory, file_filter))
        return ("C:/Mods/test.zip", "ZIP Archives (*.zip)")

    monkeypatch.setattr(
        native_integration,
        "QFileDialog",
        types.SimpleNamespace(getOpenFileName=fake_get_open_file_name),
    )

    selected, chosen_filter = native_integration.get_open_file_name(
        parent,
        "Choose archive",
        "C:/Mods",
        "ZIP Archives (*.zip)",
    )

    assert selected == "C:/Mods/test.zip"
    assert chosen_filter == "ZIP Archives (*.zip)"
    assert calls == [(parent, "Choose archive", "C:/Mods", "ZIP Archives (*.zip)")]


def test_get_save_file_name_uses_qt_dialog_without_tkinter(monkeypatch):
    calls = []
    parent = object()

    def fake_get_save_file_name(parent_arg, caption, directory, file_filter):
        calls.append((parent_arg, caption, directory, file_filter))
        return ("C:/Exports/mod.zip", "ZIP Archives (*.zip)")

    monkeypatch.setattr(
        native_integration,
        "QFileDialog",
        types.SimpleNamespace(getSaveFileName=fake_get_save_file_name),
    )

    selected, chosen_filter = native_integration.get_save_file_name(
        parent,
        "Export mod",
        "mod.zip",
        "ZIP Archives (*.zip)",
    )

    assert selected == "C:/Exports/mod.zip"
    assert chosen_filter == "ZIP Archives (*.zip)"
    assert calls == [(parent, "Export mod", "mod.zip", "ZIP Archives (*.zip)")]


def _fake_dialogs(monkeypatch, chosen):
    calls = []

    def fake_open(_parent, _caption, directory, _filter):
        calls.append(directory)
        return (chosen, "")

    monkeypatch.setattr(
        native_integration,
        "QFileDialog",
        types.SimpleNamespace(getOpenFileName=fake_open, getSaveFileName=fake_open),
    )
    return calls


def test_dialogs_start_in_the_folder_of_the_last_dialog(monkeypatch, tmp_path):
    folder = tmp_path / "mods"
    folder.mkdir()
    calls = _fake_dialogs(monkeypatch, str(folder / "a.zip"))

    native_integration.get_open_file_name(None, "x", "")
    native_integration.get_open_file_name(None, "x", "")
    native_integration.get_save_file_name(None, "x", "out.zip")
    native_integration.get_open_file_name(None, "x", os.path.expanduser("~"))

    assert calls == ["", str(folder), os.path.join(str(folder), "out.zip"), str(folder)]


def test_a_folder_the_caller_names_wins_over_the_remembered_one(monkeypatch, tmp_path):
    remembered = tmp_path / "remembered"
    named = tmp_path / "named"
    remembered.mkdir()
    named.mkdir()
    calls = _fake_dialogs(monkeypatch, str(remembered / "a.zip"))
    native_integration.get_open_file_name(None, "x", "")

    native_integration.get_open_file_name(None, "x", str(named))

    assert calls[-1] == str(named)


def test_a_remembered_folder_that_is_gone_is_ignored(monkeypatch, tmp_path):
    folder = tmp_path / "gone"
    folder.mkdir()
    calls = _fake_dialogs(monkeypatch, str(folder / "a.zip"))
    native_integration.get_open_file_name(None, "x", "")
    folder.rmdir()

    native_integration.get_open_file_name(None, "x", "")

    assert calls[-1] == ""
