from __future__ import annotations

from dataclasses import dataclass

from services.analytics_service import AnalyticsService
from services.announce_service import AnnounceService
from services.customization_service import CustomizationManager
from services.downloads_manager import DownloadsManager
from services.game_registry_service import GameRegistryService
from services.game_versions_manager import GameVersionsManager
from services.launch_service import GameLauncher
from services.mod_service import ModManager
from services.pizza_oven_conversion_service import PizzaOvenConversionService
from services.plugin_catalog_service import PluginCatalogService
from services.plugin_install_service import PluginInstallService
from services.plugin_runtime_service import PluginRuntimeService
from services.plugin_state_service import PluginStateService
from services.profile_service import ProfileService
from services.settings_service import SettingsManager
from services.updatecheck_service import UpdateChecker
from services.used_mods_service import UsedModsManager
from ui.common.feedback import FeedbackManager


@dataclass(slots=True)
class ServiceContainer:
    feedback_service: FeedbackManager
    settings_service: SettingsManager
    analytics_service: AnalyticsService
    announce_service: AnnounceService
    game_registry_service: GameRegistryService
    profile_service: ProfileService
    mod_service: ModManager
    game_launcher: GameLauncher
    update_checker: UpdateChecker
    customization_service: CustomizationManager
    used_mods_service: UsedModsManager
    downloads_manager: DownloadsManager
    game_versions_manager: GameVersionsManager
    pizza_oven_conversion_service: PizzaOvenConversionService
    plugin_state_service: PluginStateService | None
    plugin_catalog_service: PluginCatalogService | None
    plugin_runtime_service: PluginRuntimeService | None
    plugin_install_service: PluginInstallService | None
