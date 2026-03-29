from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from adapters.gamebanana_adapter import GameBananaAPI
from app_context.service_container import ServiceContainer
from models.app_state import AppState
from services.announce_service import AnnounceService
from services.customization_service import CustomizationManager
from services.downloads_manager import DownloadsManager
from services.game_registry_service import GameRegistryService
from services.game_versions_manager import GameVersionsManager
from services.launch_service import GameLauncher
from services.localization_service import localization_service
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
from session.session_manager import SessionManager
from ui.common.feedback import FeedbackManager
from utils.path_utils import get_launcher_dir, get_user_data_root

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ApplicationContext:
    app_state: AppState
    services: ServiceContainer
    session_manager: SessionManager
    launcher_dir: str
    lang_service: Any
    dialog_parent: Any = None
    pending_install_url: str | None = None
    _qt_translator_holder: dict[str, Any] = field(default_factory=dict)

    def attach_window(
        self,
        window,
        *,
        parent_for_dialogs=None,
        initial_url: str | None = None,
    ) -> None:
        self.dialog_parent = parent_for_dialogs or window
        self.pending_install_url = initial_url
        window.context = self
        window.app_state = self.app_state
        window.lang_service = self.lang_service
        window.launcher_dir = self.launcher_dir
        window.dialog_parent = self.dialog_parent
        window.server = None
        for name in self.services.__dataclass_fields__:
            setattr(window, name, getattr(self.services, name))
        window.session_manager = self.session_manager
        window.session_id = self.session_manager.session_id
        window.presence_thread = self.session_manager.thread
        window.presence_worker = self.session_manager.worker
        window._online_timer = self.session_manager.timer

    def update_qt_locale(self, language_code: str) -> None:
        localization_service.update_qt_locale(
            language_code,
            self._qt_translator_holder,
        )


def build_application_context(parent=None) -> ApplicationContext:
    app_state = AppState()
    GameBananaAPI.set_app_state(app_state)
    from utils.network_utils import _build_session

    app_state.network_session = _build_session()
    app_state.config_dir = os.path.join(get_user_data_root(), "settings")
    app_state.mods_dir = ""
    app_state.mods_metadata_path = ""
    os.makedirs(app_state.config_dir, exist_ok=True)
    app_state.config_path = os.path.join(app_state.config_dir, "settings.json")
    feedback_service = FeedbackManager(parent)
    feedback_service.app_state = app_state
    settings_service = SettingsManager(
        app_state, feedback_service, localization_service, parent=parent
    )
    app_state.local_config = settings_service.read_json(app_state.config_path) or {}
    qt_translator_holder: dict[str, Any] = {}
    saved_language = localization_service.initialize_localization(
        app_state.local_config,
        app_state.config_path,
        settings_service.write_local_config,
        settings_service.write_json,
    )
    localization_service.update_qt_locale(saved_language, qt_translator_holder)
    settings_service.ensure_config_defaults()
    announce_service = AnnounceService(app_state, settings_service)
    game_registry_service = GameRegistryService(app_state, settings_service, parent)
    game_registry_service.load()
    profile_service = ProfileService(app_state, settings_service, parent)
    profile_service.initialize()
    settings_service.profile_service = profile_service
    session_manager = SessionManager(app_state, parent=parent)
    mod_service = ModManager(app_state, feedback_service, settings_service, parent)
    pizza_oven_conversion_service = PizzaOvenConversionService()
    game_launcher = GameLauncher(app_state, feedback_service, mod_service, parent)
    update_checker = UpdateChecker(app_state, feedback_service, parent)
    customization_service = CustomizationManager(app_state, parent)
    used_mods_service = UsedModsManager(
        app_state,
        mod_service,
        feedback_service,
        settings_service,
        parent,
    )
    user_root = get_user_data_root()
    plugins_dir = os.path.join(user_root, "plugins")
    os.makedirs(plugins_dir, exist_ok=True)
    downloads_manager = DownloadsManager(
        user_root, lambda: app_state.local_config, parent
    )

    plugin_state_service: PluginStateService | None = None
    plugin_catalog_service: PluginCatalogService | None = None
    plugin_runtime_service: PluginRuntimeService | None = None
    plugin_install_service: PluginInstallService | None = None

    try:
        plugin_state_service = PluginStateService(settings_service, plugins_dir)
        plugin_catalog_service = PluginCatalogService(
            app_state, settings_service, plugins_dir
        )
        plugin_runtime_service = PluginRuntimeService(
            app_state,
            feedback_service,
            settings_service,
            profile_service,
            game_registry_service,
            customization_service,
            downloads_manager,
            plugin_state_service,
            plugin_catalog_service,
            plugins_dir,
        )
        plugin_install_service = PluginInstallService(
            plugin_state_service, plugin_runtime_service, plugins_dir
        )
        plugin_runtime_service.scan_installed_plugins()
    except Exception as e:
        logger.error("Failed to initialize plugin services: %s", e, exc_info=True)
    downloads_manager.set_app_context(
        mods_dir=app_state.mods_dir, plugin_install_service=plugin_install_service
    )
    downloads_manager.startup()
    game_versions_manager = GameVersionsManager(
        user_root, lambda: app_state.local_config, parent
    )
    game_versions_manager.startup()
    services = ServiceContainer(
        feedback_service=feedback_service,
        settings_service=settings_service,
        announce_service=announce_service,
        game_registry_service=game_registry_service,
        profile_service=profile_service,
        mod_service=mod_service,
        game_launcher=game_launcher,
        update_checker=update_checker,
        customization_service=customization_service,
        used_mods_service=used_mods_service,
        downloads_manager=downloads_manager,
        game_versions_manager=game_versions_manager,
        pizza_oven_conversion_service=pizza_oven_conversion_service,
        plugin_state_service=plugin_state_service,
        plugin_catalog_service=plugin_catalog_service,
        plugin_runtime_service=plugin_runtime_service,
        plugin_install_service=plugin_install_service,
    )
    return ApplicationContext(
        app_state=app_state,
        services=services,
        session_manager=session_manager,
        launcher_dir=get_launcher_dir(),
        lang_service=localization_service,
        _qt_translator_holder=qt_translator_holder,
    )
