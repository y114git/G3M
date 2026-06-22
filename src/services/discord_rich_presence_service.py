"""Built-in Discord Rich Presence service."""

from __future__ import annotations

import json
import os
import struct
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QApplication, QWidget

from config.config import DRP_CLIENT_ID
from services.localization_service import localization_service

LARGE_IMAGE_KEY = "g3m_icon"
LARGE_IMAGE_TEXT = "G3M"
SYNC_INTERVAL_MS = 1000
SETTINGS_APPEARANCE_TAB_INDEX = 1
MODDING_TOOLS_CONVERT_TAB_INDEX = 0
MODDING_TOOLS_DIFF_TAB_INDEX = 4


@dataclass(slots=True)
class _PresenceState:
    details: str = ""
    start_timestamp: int | None = None
    semantic_key: str = ""


class _DiscordIPCClient:
    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self._handle = None
        self._pipe_index = 0

    def connect(self) -> bool:
        if self._handle is not None:
            return True
        for index in range(self._pipe_index, 10):
            path = rf"\\.\pipe\discord-ipc-{index}"
            try:
                flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
                fd = os.open(path, flags)
                try:
                    handle = os.fdopen(fd, "r+b", buffering=0)
                except OSError:
                    os.close(fd)
                    raise
                self._handle = handle
                self._pipe_index = index
                self._send_packet(0, {"v": 1, "client_id": self.client_id})
                return True
            except OSError:
                self.close()
                continue
        return False

    def set_activity(self, activity: dict[str, Any]) -> bool:
        return self._dispatch_activity(activity)

    def clear_activity(self) -> bool:
        return self._dispatch_activity(None)

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            with suppress(OSError):
                handle.close()

    def _dispatch_activity(self, activity: dict[str, Any] | None) -> bool:
        if self._handle is None and not self.connect():
            return False
        try:
            self._send_packet(
                1,
                {
                    "cmd": "SET_ACTIVITY",
                    "args": {"pid": os.getpid(), "activity": activity},
                    "nonce": str(time.time_ns()),
                },
            )
            return True
        except OSError:
            self.close()
            return False

    def _send_packet(self, opcode: int, payload: dict[str, Any]) -> None:
        if self._handle is None:
            raise OSError("Discord IPC not connected")
        data = json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        self._handle.write(struct.pack("<ii", opcode, len(data)))
        self._handle.write(data)
        self._handle.flush()


class DiscordRichPresenceService(QObject):
    def __init__(
        self,
        app_state,
        used_mods_service,
        parent=None,
        *,
        client=None,
        time_provider: Callable[[], int] | None = None,
    ) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.used_mods_service = used_mods_service
        self._client = client or _DiscordIPCClient(DRP_CLIENT_ID)
        self._time_provider = time_provider or (lambda: int(time.time()))
        self._timer: QTimer | None = None
        self._enabled = False
        self._dirty = False
        self._override_presence: dict[str, Any] | None = None
        self._state = _PresenceState()

    def start(self) -> None:
        self._ensure_timer()
        self.apply_enabled_setting()

    def shutdown(self) -> None:
        self._enabled = False
        if self._timer is not None:
            self._timer.stop()
        self._clear_presence()
        self._client.close()

    def apply_enabled_setting(self) -> None:
        self.set_enabled(not self.is_disabled_in_settings())

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled and self._has_client_id())
        if not self._enabled:
            if self._timer is not None:
                self._timer.stop()
            self._override_presence = None
            self._clear_presence()
            return
        self.refresh()
        if self._timer is not None:
            self._timer.start(SYNC_INTERVAL_MS)

    def is_disabled_in_settings(self) -> bool:
        return bool(self.app_state.local_config.get("disable_discord_rich_presence", False))

    def _has_client_id(self) -> bool:
        return bool(str(getattr(self._client, "client_id", "") or "").strip())

    def refresh(self) -> None:
        if not self._enabled:
            return
        payload = self._override_presence or self._resolve_semantic_presence()
        self._apply_presence_payload(payload)

    def on_language_changed(self, *_args) -> None:
        self.refresh()

    def on_theme_changed(self, *_args) -> None:
        self.refresh()

    def on_profile_changed(self, *_args) -> None:
        self._override_presence = None
        self.refresh()

    def on_before_mod_apply(self, *_args) -> None:
        self._set_override_presence("preparing_launch")

    def on_after_mod_apply_before_launch(self, *_args) -> None:
        self._set_override_presence("preparing_launch")

    def on_mod_apply_cancelled(self, *_args) -> None:
        self._override_presence = None
        self.refresh()

    def on_after_game_started(self, *_args) -> None:
        self._set_override_presence("playing")

    def on_before_restore_after_exit(self, *_args) -> None:
        self._set_override_presence("restoring")

    def on_after_restore_after_exit(self, *_args) -> None:
        self._override_presence = None
        self.refresh()

    def _ensure_timer(self) -> None:
        if self._timer is not None or QApplication.instance() is None:
            return
        self._timer = QTimer(self)
        self._timer.setInterval(SYNC_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)

    def _set_override_presence(self, semantic_key: str) -> None:
        if not self._enabled:
            return
        self._override_presence = self._resolve_override_presence(semantic_key)
        self._apply_presence_payload(self._override_presence)

    def _apply_presence_payload(self, payload: dict[str, Any] | None) -> None:
        if not payload:
            return
        details = str(payload.get("details", "") or "").strip()
        semantic_key = str(payload.get("key", "") or "").strip()
        if not details:
            return
        should_reset = (
            semantic_key != self._state.semantic_key
            or details != self._state.details
            or self._state.start_timestamp is None
        )
        self._state = _PresenceState(
            details=details,
            semantic_key=semantic_key,
            start_timestamp=(
                self._time_provider()
                if should_reset
                else self._state.start_timestamp
            ),
        )
        self._dirty = True
        self._sync_presence()

    def _sync_presence(self) -> None:
        if not self._enabled or not self._dirty:
            return
        if self._client.set_activity(self._build_activity(self._state)):
            self._dirty = False

    def _build_activity(self, state: _PresenceState) -> dict[str, Any]:
        activity: dict[str, Any] = {
            "details": state.details,
            "assets": {
                "large_image": LARGE_IMAGE_KEY,
                "large_text": LARGE_IMAGE_TEXT,
            },
            "instance": False,
        }
        if state.start_timestamp is not None:
            activity["timestamps"] = {"start": state.start_timestamp}
        return activity

    def _clear_presence(self) -> None:
        self._dirty = False
        self._client.clear_activity()

    def _resolve_override_presence(self, semantic_key: str) -> dict[str, Any]:
        if semantic_key == "playing":
            game_name = self._current_game_name()
            mods_amount = self._mods_amount()
            return {
                "key": "playing_with_mods" if mods_amount > 0 else "playing",
                "details": self._playing_details(game_name, mods_amount),
            }
        return {"key": semantic_key, "details": self._status_text(semantic_key)}

    def _resolve_semantic_presence(self) -> dict[str, Any]:
        if getattr(self.app_state, "search_text", "") or getattr(
            self.app_state, "library_search_text", ""
        ):
            return {"key": "searching", "details": self._status_text("searching")}

        for window in self._iter_visible_windows():
            if state := self._presence_from_window(window):
                return state

        main_window = self._main_window()
        if self._is_settings_plugins(main_window):
            return {"key": "plugins", "details": self._status_text("plugins")}
        if self._is_settings_appearance(main_window):
            return {"key": "appearance", "details": self._status_text("appearance")}
        if self._is_settings_open(main_window):
            return {"key": "configuring", "details": self._status_text("configuring")}
        if self._is_mods_browser_active(main_window):
            return {
                "key": "browsing_mods",
                "details": self._status_text("browsing_mods"),
            }
        return {
            "key": "preparing_launch",
            "details": self._status_text("preparing_launch"),
        }

    def _presence_from_window(self, window) -> dict[str, Any] | None:
        class_name = window.__class__.__name__
        if class_name == "CreateModpackDialog":
            return {
                "key": "creating_modpack",
                "details": self._status_text("creating_modpack"),
            }
        if class_name == "ModDetailsOverlay":
            return {"key": "mod_details", "details": self._status_text("mod_details")}
        if class_name == "DownloadsDialog":
            return {"key": "downloads", "details": self._status_text("downloads")}
        if class_name == "BlocklistDialog":
            return {"key": "blacklist", "details": self._status_text("blacklist")}
        if class_name == "GameVersionsDialog":
            return {"key": "game_backup", "details": self._status_text("game_backup")}
        if class_name == "ModVersionsDialog":
            return {"key": "mod_backup", "details": self._status_text("mod_backup")}
        if class_name == "ModEditorDialog":
            return {"key": "mod_editor", "details": self._status_text("mod_editor")}
        if class_name == "PluginDetailsDialog":
            return {"key": "plugins", "details": self._status_text("plugins")}
        if class_name == "ModdingToolsDialog":
            current_tab = self._current_index(getattr(window, "_tabs", None))
            key = "modding_tools"
            if current_tab == MODDING_TOOLS_CONVERT_TAB_INDEX:
                key = "converting_mods"
            elif current_tab == MODDING_TOOLS_DIFF_TAB_INDEX:
                key = "diff_report"
            return {"key": key, "details": self._status_text(key)}
        return None

    def _iter_visible_windows(self) -> list[QWidget]:
        app = QApplication.instance()
        if app is None:
            return []
        windows = []
        for widget in app.topLevelWidgets():
            if widget is None:
                continue
            try:
                if widget.isVisible():
                    windows.append(widget)
            except RuntimeError:
                continue
        windows.reverse()
        return windows

    def _main_window(self):
        main_window = getattr(self.app_state, "_app_window", None)
        if main_window is not None:
            return main_window
        for window in self._iter_visible_windows():
            if hasattr(window, "main_tab_widget") or hasattr(window, "settings_widget"):
                return window
        return None

    @staticmethod
    def _current_index(tab_widget) -> int | None:
        if tab_widget is None or not hasattr(tab_widget, "currentIndex"):
            return None
        try:
            return int(tab_widget.currentIndex())
        except Exception:
            return None

    def _is_settings_open(self, main_window) -> bool:
        settings_widget = getattr(main_window, "settings_widget", None)
        is_visible = getattr(settings_widget, "isVisible", None)
        if callable(is_visible):
            with suppress(Exception):
                if is_visible():
                    return True
        return bool(getattr(self.app_state, "is_settings_view", False))

    def _is_settings_appearance(self, main_window) -> bool:
        return self._is_settings_open(main_window) and self._current_index(
            getattr(main_window, "settings_tab_widget", None)
        ) == SETTINGS_APPEARANCE_TAB_INDEX

    def _is_settings_plugins(self, main_window) -> bool:
        if not self._is_settings_open(main_window):
            return False
        tab_widget = getattr(main_window, "settings_tab_widget", None)
        plugins_tab = getattr(main_window, "plugins_tab", None)
        if tab_widget is None or plugins_tab is None or not hasattr(tab_widget, "currentWidget"):
            return False
        try:
            return tab_widget.currentWidget() is plugins_tab
        except Exception:
            return False

    def _is_mods_browser_active(self, main_window) -> bool:
        if self._is_settings_open(main_window):
            return False
        tab_widget = getattr(main_window, "main_tab_widget", None)
        mods_browser_tab = getattr(main_window, "mods_browser_tab", None)
        if tab_widget is None or mods_browser_tab is None or not hasattr(tab_widget, "currentWidget"):
            return False
        try:
            return tab_widget.currentWidget() is mods_browser_tab
        except Exception:
            return False

    def _current_game_name(self) -> str:
        game_mode = getattr(self.app_state, "game_mode", None)
        for attr in ("display_label", "display_name", "game_id"):
            value = getattr(game_mode, attr, "")
            if str(value or "").strip():
                return str(value).strip()
        game = (
            self.app_state.local_config.get("selected_game_type")
            or self.app_state.local_config.get("selected_game")
            or ""
        )
        return str(game).strip()

    def _mods_amount(self) -> int:
        total = self._mods_amount_from_active_selections()
        if total > 0:
            return total
        if hasattr(self.used_mods_service, "get_active_mods_count"):
            with suppress(Exception):
                return int(self.used_mods_service.get_active_mods_count())
        return 0

    def _mods_amount_from_active_selections(self) -> int:
        if not hasattr(self.used_mods_service, "get_active_mod_selections"):
            return 0
        try:
            selections = self.used_mods_service.get_active_mod_selections() or {}
        except Exception:
            return 0
        if not isinstance(selections, dict):
            return 0
        total = 0
        for mods in selections.values():
            if isinstance(mods, list):
                total += len(mods)
        return total

    def _playing_details(self, game_name: str, mods_amount: int) -> str:
        resolved_game = game_name or self._tr("discord_rich_presence.status.unknown_game")
        if mods_amount > 0:
            return self._tr(
                "discord_rich_presence.status.playing_with_mods",
                game=resolved_game,
                mods_amount=mods_amount,
            )
        return self._tr("discord_rich_presence.status.playing", game=resolved_game)

    def _status_text(self, status_key: str) -> str:
        return self._tr(f"discord_rich_presence.status.{status_key}")

    @staticmethod
    def _tr(key: str, **kwargs) -> str:
        template = localization_service.get_text(key, **kwargs)
        try:
            return str(template).format(**kwargs)
        except Exception:
            return str(template)
