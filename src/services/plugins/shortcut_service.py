"""Shortcut-specific plugin capture and headless runtime helpers."""

from __future__ import annotations

import json
import logging
import os
from types import SimpleNamespace
from typing import Any

from services.localization_service import localization_service
from services.plugins.runtime_service import PluginRuntimeService
from services.plugins.state_service import PluginStateService
from utils.path_utils import get_user_data_root

logger = logging.getLogger(__name__)


class ShortcutPluginContext:
    """Carries serializable shortcut plugin state between capture and launch."""

    def __init__(
        self,
        shortcut_config: dict[str, Any] | None = None,
        *,
        enabled: bool = True,
        phase: str = "capture",
    ) -> None:
        self.shortcut_config = dict(shortcut_config or {})
        self.enabled = bool(enabled)
        self.phase = str(phase or "capture")
        self.plugin_states: dict[str, dict[str, Any]] = {}
        self.summary_lines: list[tuple[str, str]] = []

    @property
    def game_id(self) -> str:
        return str(self.shortcut_config.get("game_id", "") or "").strip()

    @classmethod
    def from_shortcut_config(cls, shortcut_config: dict[str, Any]) -> ShortcutPluginContext:
        context = cls(
            shortcut_config,
            enabled=bool(shortcut_config.get("plugins_enabled")),
            phase="launch",
        )
        for plugin_id, payload in (shortcut_config.get("plugin_states", {}) or {}).items():
            if isinstance(plugin_id, str) and isinstance(payload, dict):
                context.plugin_states[plugin_id] = dict(payload)
        for item in shortcut_config.get("plugin_summary", []) or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            value = str(item.get("value", "")).strip()
            if label and value:
                context.summary_lines.append((label, value))
        return context

    def set_plugin_state(self, plugin_id: str, payload: dict[str, Any] | None) -> None:
        if not plugin_id:
            return
        self.plugin_states[str(plugin_id)] = dict(payload or {})

    def get_plugin_state(
        self, plugin_id: str, default: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = self.plugin_states.get(plugin_id)
        if isinstance(payload, dict):
            return dict(payload)
        return dict(default or {})

    def add_summary_line(self, label: str, value: Any) -> None:
        label_text = str(label or "").strip()
        value_text = str(value or "").strip()
        if label_text and value_text:
            self.summary_lines.append((label_text, value_text))

    def matches_game(
        self,
        *,
        allowed: set[str] | list[str] | tuple[str, ...] | None = None,
        blocked: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> bool:
        game_id = self.game_id.casefold()
        if not game_id:
            return False
        if allowed:
            allowed_ids = {str(item).strip().casefold() for item in allowed if str(item).strip()}
            if game_id not in allowed_ids:
                return False
        if blocked:
            blocked_ids = {str(item).strip().casefold() for item in blocked if str(item).strip()}
            if game_id in blocked_ids:
                return False
        return True

    def export_states(self) -> dict[str, dict[str, Any]]:
        return {plugin_id: dict(payload) for plugin_id, payload in self.plugin_states.items()}

    def export_summary(self) -> list[dict[str, str]]:
        return [{"label": label, "value": value} for label, value in self.summary_lines]


class _HeadlessSettingsService:
    def read_json(self, path: str):
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Shortcut plugin settings read failed for %s: %s", path, e)
            return None

    def write_json(self, path: str, data) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        except (OSError, TypeError, ValueError) as e:
            logger.warning("Shortcut plugin settings write failed for %s: %s", path, e)

    def pick_directory(self, _title: str, _start_path: str) -> str:
        return ""


class _HeadlessFeedbackService:
    def __init__(self, plugin_id: str | None = None) -> None:
        self._plugin_id = plugin_id or ""

    def scoped(self, plugin_tr) -> _HeadlessFeedbackService:
        plugin_id = self._plugin_id
        if callable(plugin_tr):
            plugin_id = getattr(plugin_tr, "__self__", None) or plugin_id
        return _HeadlessFeedbackService(str(plugin_id or self._plugin_id))

    def update_status(self, message: str, _color: str | None = None) -> None:
        if message:
            logger.info("Shortcut plugin status: %s", message)

    def show_message(self, level: str, title: str, message: str, **kwargs) -> None:
        logger.warning(
            "Shortcut plugin message [%s] %s: %s %s",
            level,
            title,
            message,
            kwargs if kwargs else "",
        )

    def ask_question(self, *_args, **_kwargs) -> bool:
        return False


class _HeadlessCatalogService:
    def is_loaded(self) -> bool:
        return False

    def get_entry(self, _plugin_id: str, *, load_if_needed: bool = True):
        return None


def execute_shortcut_plugin_hook(
    runtime_service: PluginRuntimeService | None,
    hook_name: str,
    shortcut_context: ShortcutPluginContext,
    *args,
) -> bool:
    if not runtime_service or not shortcut_context.enabled:
        return True
    results = runtime_service.execute_hook(hook_name, shortcut_context, *args)
    return not any(result is False for result in results)


def build_headless_plugin_runtime(
    local_config: dict[str, Any],
    *,
    game_mode=None,
    current_mode: str = "chapter",
) -> PluginRuntimeService | None:
    user_root = get_user_data_root()
    plugins_dir = os.path.join(user_root, "plugins")
    if not os.path.isdir(plugins_dir):
        return None
    language_code = str(local_config.get("language", "en") or "en")
    localization_service.load_language(language_code)
    app_state = SimpleNamespace(
        local_config=local_config,
        game_mode=game_mode,
        current_mode=current_mode,
        config_dir=os.path.join(user_root, "settings"),
        config_path=os.path.join(user_root, "settings", "settings.json"),
        network_session=None,
    )
    settings_service = _HeadlessSettingsService()
    plugin_state_service = PluginStateService(settings_service, plugins_dir)
    runtime_service = PluginRuntimeService(
        app_state,
        _HeadlessFeedbackService(),
        settings_service,
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        plugin_state_service,
        _HeadlessCatalogService(),
        plugins_dir,
    )
    runtime_service.scan_installed_plugins(resolve_catalog=False)
    return runtime_service
