"""Tests for native OS dialog and open helpers."""

from __future__ import annotations

import types

from utils import native_integration


def test_qt_filter_to_tk_filetypes_supports_multiple_patterns():
    filetypes = native_integration._qt_filter_to_tk_filetypes(
        "Images (*.png *.jpg);;All Files (*)"
    )
    assert filetypes == [("Images", ("*.png", "*.jpg")), ("All Files", "*")]


def test_default_extension_from_filter_uses_first_specific_glob():
    assert (
        native_integration._default_extension_from_filter(
            "ZIP Archives (*.zip);;All Files (*)"
        )
        == ".zip"
    )


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
