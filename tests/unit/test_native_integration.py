"""Tests for native OS dialog and open helpers."""

from __future__ import annotations

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
