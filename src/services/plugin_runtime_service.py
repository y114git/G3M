"""Plugin runtime scanning, loading, and hooks."""

from __future__ import annotations

import logging
import os
from typing import Any

from models.plugin_models import (
    InstalledPluginRecord,
    PluginContext,
    PluginManifest,
    PluginSettingsAccessor,
    PluginTaskRuntime,
    PluginUiContext,
)
from services.localization_service import localization_service
from services.plugin_support import (
    PluginValidationError,
    load_manifest,
    load_plugin_factory,
    load_plugin_langs,
    resolve_plugin_path,
)
from utils.process_utils import format_plugin_error

logger = logging.getLogger(__name__)


class PluginRuntimeService:
    """Scans installed plugins, loads enabled ones, and executes hooks."""

    def __init__(
        self,
        app_state,
        feedback_service,
        settings_service,
        profile_service,
        game_registry_service,
        customization_service,
        downloads_manager,
        plugin_state_service,
        plugin_catalog_service,
        plugins_dir: str,
    ) -> None:
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.settings_service = settings_service
        self.profile_service = profile_service
        self.game_registry_service = game_registry_service
        self.customization_service = customization_service
        self.downloads_manager = downloads_manager
        self.plugin_state_service = plugin_state_service
        self.plugin_catalog_service = plugin_catalog_service
        self.plugins_dir = plugins_dir
        self._installed: dict[str, InstalledPluginRecord] = {}
        self._instances: dict[str, Any] = {}
        self._enabled_instances: set[str] = set()

    def scan_installed_plugins(
        self, *, resolve_catalog: bool | None = None
    ) -> dict[str, InstalledPluginRecord]:
        os.makedirs(self.plugins_dir, exist_ok=True)
        localization_service.clear_plugin_strings()
        should_resolve_catalog = (
            self.plugin_catalog_service.is_loaded()
            if resolve_catalog is None
            else resolve_catalog
        )
        installed: dict[str, InstalledPluginRecord] = {}
        for name in sorted(os.listdir(self.plugins_dir)):
            plugin_dir = os.path.join(self.plugins_dir, name)
            manifest_path = os.path.join(plugin_dir, "plugin_config.json")
            if not os.path.isdir(plugin_dir) or not os.path.isfile(manifest_path):
                continue
            try:
                manifest = load_manifest(manifest_path)
                for code, strings in load_plugin_langs(plugin_dir).items():
                    localization_service.merge_plugin_strings(manifest.id, code, strings)
                catalog_entry = self.plugin_catalog_service.get_entry(
                    manifest.id,
                    load_if_needed=should_resolve_catalog,
                )
                install_meta = self.plugin_state_service.get_install_meta(manifest.id)
                is_local = install_meta.get("source") == "manual" or catalog_entry is None
                update_available = bool(
                    catalog_entry
                    and catalog_entry.version
                    and catalog_entry.version != manifest.version
                )
                error = ""
                status = "installed"
                installed[manifest.id] = InstalledPluginRecord(
                    manifest=manifest,
                    path=plugin_dir,
                    status=status,
                    enabled=self.plugin_state_service.is_enabled(manifest.id),
                    is_local=is_local,
                    error=error,
                    compatible=True,
                    update_available=update_available,
                    catalog_entry=catalog_entry,
                )
            except Exception as e:
                plugin_id = name
                logger.error("PluginRuntimeService: failed to scan %s: %s", name, e, exc_info=True)
                installed[plugin_id] = InstalledPluginRecord(
                    manifest=PluginManifest(
                        config_version=1,
                        id=plugin_id,
                        name=plugin_id,
                        description="",
                        author="",
                        version="",
                        api_version="",
                        entry="",
                    ),
                    path=plugin_dir,
                    status="broken",
                    error=format_plugin_error(e, plugin_id=plugin_id, details=plugin_dir),
                    compatible=False,
                )
        self._installed = installed
        self.reload_enabled_plugins()
        return installed

    def list_installed_plugins(self) -> list[InstalledPluginRecord]:
        return list(self._installed.values())

    def get_plugin(self, plugin_id: str) -> InstalledPluginRecord | None:
        return self._installed.get(plugin_id)

    def reload_plugin_localizations(self) -> None:
        for plugin in self._installed.values():
            for code, strings in load_plugin_langs(plugin.path).items():
                localization_service.merge_plugin_strings(plugin.plugin_id, code, strings)

    def _build_context(
        self,
        plugin_id: str,
        *,
        task_runtime: PluginTaskRuntime | None = None,
    ) -> PluginContext:
        plugin_feedback = self.feedback_service.scoped(
            localization_service.get_plugin_tr(plugin_id)
        )
        return PluginContext(
            plugin_id=plugin_id,
            app_state=self.app_state,
            feedback_service=plugin_feedback,
            settings_service=self.settings_service,
            profile_service=self.profile_service,
            game_registry_service=self.game_registry_service,
            customization_service=self.customization_service,
            downloads_manager=self.downloads_manager,
            localization_service=localization_service,
            plugin_settings=PluginSettingsAccessor(plugin_id, self.plugin_state_service),
            task_runtime=task_runtime,
        )

    def _build_ui_context(self, plugin_id: str) -> PluginUiContext:
        context = self._build_context(plugin_id)
        return PluginUiContext(
            plugin_id=plugin_id,
            host_context=context,
            app_state=self.app_state,
            feedback_service=context.feedback_service,
            customization_service=self.customization_service,
            localization_service=localization_service,
            plugin_settings=context.plugin_settings,
        )

    def _load_instance(self, plugin_id: str, *, enable: bool) -> Any:
        record = self._installed.get(plugin_id)
        if not record or not record.compatible:
            raise PluginValidationError("plugin_not_available")
        if not record.manifest:
            raise PluginValidationError("missing_manifest")
        if plugin_id in self._instances:
            instance = self._instances[plugin_id]
            if enable and plugin_id not in self._enabled_instances:
                context = self._build_context(plugin_id)
                if hasattr(instance, "on_enable"):
                    instance.on_enable(context)
                self._enabled_instances.add(plugin_id)
            return instance
        entry_path = resolve_plugin_path(record.path, record.manifest.entry)
        instance = load_plugin_factory(plugin_id, entry_path)()
        context = self._build_context(plugin_id)
        if hasattr(instance, "on_load"):
            instance.on_load(context)
        if enable and hasattr(instance, "on_enable"):
            instance.on_enable(context)
        if enable:
            self._enabled_instances.add(plugin_id)
        self._instances[plugin_id] = instance
        return instance

    def reload_enabled_plugins(self) -> None:
        active_ids = set(self._instances)
        desired_ids = {
            plugin_id
            for plugin_id, record in self._installed.items()
            if record.enabled and record.compatible
        }
        for plugin_id in active_ids - desired_ids:
            self.disable_plugin(plugin_id, persist=False)
        for plugin_id in desired_ids:
            try:
                self._load_instance(plugin_id, enable=True)
                self._apply_game_registry_hook(plugin_id)
            except Exception as e:
                logger.error("PluginRuntimeService: failed to load %s: %s", plugin_id, e, exc_info=True)
                record = self._installed.get(plugin_id)
                if record:
                    record.status = "broken"
                    record.error = format_plugin_error(e, plugin_id=plugin_id, details=record.path)
        self._enabled_instances = {
            plugin_id for plugin_id in desired_ids
            if plugin_id in self._instances
        }

    def _apply_game_registry_hook(self, plugin_id: str) -> None:
        plugin = self._instances.get(plugin_id)
        if not plugin or not hasattr(plugin, "contribute_game_definitions"):
            return
        with_context = self._build_context(plugin_id)
        try:
            plugin.contribute_game_definitions(with_context)
        except Exception as e:
            logger.debug("PluginRuntimeService: game_registry hook failed for %s: %s", plugin_id, e, exc_info=True)

    def _relation_errors(self, plugin_id: str) -> tuple[list[str], list[str]]:
        record = self._installed.get(plugin_id)
        if not record or not record.manifest:
            return [], []
        missing: list[str] = []
        conflicts: list[str] = []
        for dep_id, relation in record.manifest.relations.items():
            dep = self._installed.get(dep_id)
            if relation == "require" and (not dep or not dep.enabled or not dep.compatible):
                missing.append(dep_id)
            if relation == "conflict" and dep and dep.enabled:
                conflicts.append(dep_id)
        return missing, conflicts

    def enable_plugin(self, plugin_id: str, *, disable_conflicts: bool = True) -> tuple[bool, str]:
        record = self._installed.get(plugin_id)
        if not record:
            return False, format_plugin_error("plugin_not_found", plugin_id=plugin_id)
        if not record.compatible:
            return False, format_plugin_error("plugin_incompatible", plugin_id=plugin_id)
        missing, conflicts = self._relation_errors(plugin_id)
        if missing:
            return False, format_plugin_error("missing_dependencies", plugin_id=plugin_id)
        if conflicts and not disable_conflicts:
            return False, format_plugin_error("conflicts_present", plugin_id=plugin_id)
        for conflict_id in conflicts:
            self.disable_plugin(conflict_id)
        self.plugin_state_service.set_enabled(plugin_id, True)
        record.enabled = True
        record.status = "enabled"
        try:
            self._load_instance(plugin_id, enable=True)
            self._apply_game_registry_hook(plugin_id)
            return True, ""
        except Exception as e:
            record.status = "broken"
            record.error = format_plugin_error(e, plugin_id=plugin_id, details=record.path)
            self.plugin_state_service.set_enabled(plugin_id, False)
            record.enabled = False
            return False, record.error

    def disable_plugin(self, plugin_id: str, *, persist: bool = True) -> None:
        record = self._installed.get(plugin_id)
        if persist:
            self.plugin_state_service.set_enabled(plugin_id, False)
        if record:
            record.enabled = False
            if record.compatible:
                record.status = "installed"
        instance = self._instances.pop(plugin_id, None)
        if (
            instance
            and plugin_id in self._enabled_instances
            and hasattr(instance, "on_disable")
        ):
            try:
                instance.on_disable(self._build_context(plugin_id))
            except Exception as e:
                logger.debug("PluginRuntimeService: disable hook failed for %s: %s", plugin_id, e, exc_info=True)
        if plugin_id in self._enabled_instances:
            self._enabled_instances.remove(plugin_id)

    def execute_hook(self, hook_name: str, *args, **kwargs) -> list[Any]:
        return self.execute_hook_with_runtime(hook_name, None, *args, **kwargs)

    def execute_hook_with_runtime(
        self,
        hook_name: str,
        task_runtime: PluginTaskRuntime | None,
        *args,
        **kwargs,
    ) -> list[Any]:
        results: list[Any] = []
        method_name = f"on_{hook_name}"
        for plugin_id, instance in list(self._instances.items()):
            record = self._installed.get(plugin_id)
            if not record or not record.enabled:
                continue
            if not hasattr(instance, method_name):
                continue
            try:
                results.append(
                    getattr(instance, method_name)(
                        self._build_context(plugin_id, task_runtime=task_runtime),
                        *args,
                        **kwargs,
                    )
                )
            except InterruptedError:
                raise
            except Exception as e:
                logger.error("PluginRuntimeService: hook %s failed for %s: %s", hook_name, plugin_id, e, exc_info=True)
                if record:
                    record.error = format_plugin_error(e, plugin_id=plugin_id, details=record.path)
                    record.status = "broken"
        return results

    def has_enabled_hook(self, hook_name: str) -> bool:
        method_name = f"on_{hook_name}"
        for plugin_id, instance in self._instances.items():
            record = self._installed.get(plugin_id)
            if record and record.enabled and hasattr(instance, method_name):
                return True
        return False

    def get_settings_widget(self, plugin_id: str, parent=None):
        try:
            plugin = self._instances.get(plugin_id)
            if plugin is None:
                plugin = self._load_instance(plugin_id, enable=False)
            if hasattr(plugin, "create_settings_widget"):
                return plugin.create_settings_widget(self._build_ui_context(plugin_id), parent)
        except Exception as e:
            logger.error(
                "PluginRuntimeService: settings widget failed for %s: %s",
                plugin_id,
                e,
                exc_info=True,
            )
        return None

    def get_main_widget(self, plugin_id: str, parent=None):
        try:
            plugin = self._instances.get(plugin_id)
            if plugin is None:
                plugin = self._load_instance(plugin_id, enable=False)
            if hasattr(plugin, "create_main_widget"):
                return plugin.create_main_widget(self._build_ui_context(plugin_id), parent)
        except Exception as e:
            logger.error(
                "PluginRuntimeService: main widget failed for %s: %s",
                plugin_id,
                e,
                exc_info=True,
            )
        return None

    def get_navigation_actions(self, plugin_id: str) -> list[dict[str, Any]]:
        plugin = self._instances.get(plugin_id)
        record = self._installed.get(plugin_id)
        if plugin is None or not record or not record.enabled:
            return []
        if hasattr(plugin, "contribute_navigation_actions"):
            return plugin.contribute_navigation_actions(self._build_ui_context(plugin_id)) or []
        return []

    def run_settings_action(self, plugin_id: str, action_id: str, parent=None) -> Any:
        try:
            plugin = self._instances.get(plugin_id)
            if plugin is None:
                plugin = self._load_instance(plugin_id, enable=False)
            if hasattr(plugin, "handle_settings_action"):
                return plugin.handle_settings_action(
                    action_id,
                    self._build_ui_context(plugin_id),
                    parent,
                )
        except Exception as e:
            logger.debug(
                "PluginRuntimeService: settings action failed for %s: %s",
                plugin_id,
                e,
                exc_info=True,
            )
        return None
