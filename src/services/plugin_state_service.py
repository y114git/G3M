"""Persistent plugin state storage."""

from __future__ import annotations

import os

from models.plugin_models import PLUGIN_TAGS


class PluginStateService:
    """Reads and writes DELTAHUB/plugins/plugins_data.json."""

    def __init__(self, settings_service, plugins_dir: str) -> None:
        self.settings_service = settings_service
        self.plugins_dir = plugins_dir
        self.state_path = os.path.join(plugins_dir, "plugins_data.json")
        self._state = self._load()

    def _default_state(self) -> dict:
        return {
            "enabled": {},
            "settings": {},
            "filters": {"installed_only": False, "tags": []},
            "install_meta": {},
        }

    def _load(self) -> dict:
        os.makedirs(self.plugins_dir, exist_ok=True)
        data = self.settings_service.read_json(self.state_path) or {}
        state = self._default_state()
        for key in state:
            value = data.get(key, state[key])
            state[key] = value if isinstance(value, type(state[key])) else state[key]
        filters = state["filters"]
        filters["installed_only"] = bool(filters.get("installed_only", False))
        filters["tags"] = [
            tag for tag in filters.get("tags", []) if isinstance(tag, str) and tag in PLUGIN_TAGS
        ]
        self._write_state(state)
        return state

    def _save(self) -> None:
        self._write_state(self._state)

    def _write_state(self, state: dict) -> None:
        self.settings_service.write_json(self.state_path, state)

    def is_enabled(self, plugin_id: str) -> bool:
        return bool(self._state["enabled"].get(plugin_id, False))

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        self._state["enabled"][plugin_id] = bool(enabled)
        self._save()

    def get_plugin_settings(self, plugin_id: str) -> dict:
        return dict(self._state["settings"].get(plugin_id, {}))

    def get_plugin_setting(self, plugin_id: str, key: str, default=None):
        return self._state["settings"].get(plugin_id, {}).get(key, default)

    def set_plugin_setting(self, plugin_id: str, key: str, value) -> None:
        self._state["settings"].setdefault(plugin_id, {})[key] = value
        self._save()

    def clear_plugin(self, plugin_id: str) -> None:
        for section in ("enabled", "settings", "install_meta"):
            self._state[section].pop(plugin_id, None)
        self._save()

    def get_filters(self) -> dict:
        return {
            "installed_only": bool(self._state["filters"].get("installed_only", False)),
            "tags": list(self._state["filters"].get("tags", [])),
        }

    def set_filters(self, *, installed_only: bool, tags: list[str]) -> None:
        self._state["filters"] = {
            "installed_only": bool(installed_only),
            "tags": [tag for tag in tags if tag in PLUGIN_TAGS],
        }
        self._save()

    def get_install_meta(self, plugin_id: str) -> dict:
        meta = dict(self._state["install_meta"].get(plugin_id, {}))
        if "local" not in meta and "unsupported" in meta:
            meta["local"] = bool(meta.pop("unsupported"))
            self._state["install_meta"][plugin_id] = meta
            self._save()
        return meta

    def set_install_meta(self, plugin_id: str, **meta) -> None:
        current = self._state["install_meta"].setdefault(plugin_id, {})
        current.update(meta)
        self._save()
