"""Plugin metadata and context models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from config.config import (
    PLUGIN_API_VERSION as CONFIG_PLUGIN_API_VERSION,
)
from config.config import (
    PLUGIN_HOOKS as CONFIG_PLUGIN_HOOKS,
)
from config.config import (
    PLUGIN_TAGS as CONFIG_PLUGIN_TAGS,
)

PLUGIN_API_VERSION = CONFIG_PLUGIN_API_VERSION
PLUGIN_HOOKS = CONFIG_PLUGIN_HOOKS
PLUGIN_TAGS = CONFIG_PLUGIN_TAGS


@runtime_checkable
class PluginStateServiceProtocol(Protocol):
    """Protocol for plugin state service operations."""

    def get_plugin_setting(self, plugin_id: str, key: str, default: Any = None) -> Any: ...
    def set_plugin_setting(self, plugin_id: str, key: str, value: Any) -> None: ...
    def get_plugin_settings(self, plugin_id: str) -> dict[str, Any]: ...


class PluginRelation(StrEnum):
    REQUIRE = "require"
    CONFLICT = "conflict"


@dataclass(slots=True)
class PluginManifest:
    config_version: int
    id: str
    name: str
    description: str
    author: str
    version: str
    entry: str
    api_version: str = ""
    icon: str = ""
    homepage: str = ""
    tags: list[str] = field(default_factory=list)
    relations: dict[str, str] = field(default_factory=dict)
    hooks: list[str] = field(default_factory=list)
    settings_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CatalogPluginEntry:
    id: str
    name: str
    description: str
    author: str
    version: str
    api_version: str
    icon: str = ""
    homepage: str = ""
    download_link: str = ""
    tags: list[str] = field(default_factory=list)
    relations: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class InstalledPluginRecord:
    manifest: PluginManifest | None
    path: str
    status: str = "installed"
    enabled: bool = False
    is_local: bool = False
    error: str = ""
    compatible: bool = True
    update_available: bool = False
    catalog_entry: CatalogPluginEntry | None = None

    @property
    def plugin_id(self) -> str:
        return self.manifest.id if self.manifest else ""


@dataclass(slots=True)
class PluginSettingsAccessor:
    plugin_id: str
    state_service: PluginStateServiceProtocol

    def get(self, key: str, default: Any = None) -> Any:
        """Get a plugin setting value with optional default."""
        return self.state_service.get_plugin_setting(self.plugin_id, key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a plugin setting value."""
        self.state_service.set_plugin_setting(self.plugin_id, key, value)

    def all(self) -> dict[str, Any]:
        """Get all settings for this plugin as a dictionary."""
        return self.state_service.get_plugin_settings(self.plugin_id)


@dataclass(slots=True)
class PluginTaskRuntime:
    set_progress_callback: Any = None
    set_status_callback: Any = None
    is_cancelled_callback: Any = None
    get_backup_manager_callback: Any = None
    restore_backups_callback: Any = None
    copy_backups_callback: Any = None

    def set_progress(self, progress: int, message: str = "") -> None:
        if callable(self.set_progress_callback):
            self.set_progress_callback(int(progress), str(message or ""))

    def set_status(self, message: str, status_type: str = "info") -> None:
        if callable(self.set_status_callback):
            self.set_status_callback(str(message or ""), str(status_type or "info"))

    def is_cancelled(self) -> bool:
        return bool(self.is_cancelled_callback()) if callable(self.is_cancelled_callback) else False

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise InterruptedError("Plugin task cancelled")

    def get_host_backup_manager(self) -> Any:
        return self.get_backup_manager_callback() if callable(self.get_backup_manager_callback) else None

    def restore_host_backups(self) -> bool:
        return bool(self.restore_backups_callback()) if callable(self.restore_backups_callback) else False

    def copy_host_backups_to(self, destination_dir: str) -> list[str]:
        if callable(self.copy_backups_callback):
            return self.copy_backups_callback(destination_dir)
        return []


@dataclass(slots=True)
class PluginContext:
    plugin_id: str
    app_state: Any
    feedback_service: Any
    settings_service: Any
    profile_service: Any
    game_registry_service: Any
    customization_service: Any
    used_mods_service: Any
    downloads_manager: Any
    localization_service: Any
    plugin_settings: PluginSettingsAccessor
    task_runtime: PluginTaskRuntime | None = None


@dataclass(slots=True)
class PluginUiContext:
    plugin_id: str
    host_context: PluginContext
    app_state: Any
    feedback_service: Any
    customization_service: Any
    localization_service: Any
    plugin_settings: PluginSettingsAccessor
