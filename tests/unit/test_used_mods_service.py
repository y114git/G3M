from types import SimpleNamespace
from unittest.mock import Mock

from services.used_mods_service import UsedModsManager


def test_load_used_mods_state_drops_deleted_mods_that_were_previously_loaded(app_state):
    """Checks that loading used mods clears deleted mods instead of keeping ghost entries."""
    deleted_mod = SimpleNamespace(id="ghost_mod", name="Ghost Mod")
    app_state.current_mode = "normal"
    app_state.local_config["used_mods_deltarune"] = {"deltarune": "ghost_mod"}
    app_state.all_mods = []

    mod_service = Mock()
    mod_service.is_mod_installed.return_value = False
    mod_service.get_installed_mods_list.return_value = []
    mod_service.get_mod_config.return_value = None
    settings_service = Mock()

    service = UsedModsManager(
        app_state,
        mod_service,
        Mock(),
        settings_service,
        parent=None,
    )
    service._mods_state_loaded = True
    service.used_mods = {"deltarune": [deleted_mod]}

    service.load_used_mods_state()

    assert service.used_mods == {}
    assert not hasattr(service, "_pending_mod_ids")
    assert app_state.local_config["used_mods_deltarune"] == {}
    settings_service.write_local_config.assert_called_once()


def test_load_used_mods_state_keeps_pending_ids_when_mods_never_loaded(app_state):
    """Checks that unresolved ids still stay pending during early loading."""
    app_state.current_mode = "normal"
    app_state.local_config["used_mods_deltarune"] = {"deltarune": "pending_mod"}
    app_state.all_mods = []

    mod_service = Mock()
    mod_service.is_mod_installed.return_value = False
    mod_service.get_installed_mods_list.return_value = []
    mod_service.get_mod_config.return_value = None
    settings_service = Mock()

    service = UsedModsManager(
        app_state,
        mod_service,
        Mock(),
        settings_service,
        parent=None,
    )

    service.load_used_mods_state()

    assert service.used_mods == {}
    assert service._pending_mod_ids == {"deltarune": ["pending_mod"]}
    assert app_state.local_config["used_mods_deltarune"] == {"deltarune": "pending_mod"}


def test_load_used_mods_state_keeps_previously_loaded_mod_when_missing_is_unconfirmed(
    app_state,
):
    """Previously loaded selections should survive reload races until removal is confirmed."""
    loaded_mod = SimpleNamespace(id="kept_mod", name="Kept Mod")
    app_state.current_mode = "normal"
    app_state.local_config["used_mods_deltarune"] = {"deltarune": "kept_mod"}
    app_state.all_mods = []

    mod_service = Mock()
    mod_service.is_mod_installed.side_effect = RuntimeError("cache not ready")
    mod_service.get_installed_mods_list.return_value = []
    mod_service.get_mod_config.return_value = None
    settings_service = Mock()

    service = UsedModsManager(
        app_state,
        mod_service,
        Mock(),
        settings_service,
        parent=None,
    )
    service._mods_state_loaded = True
    service.used_mods = {"deltarune": [loaded_mod]}

    service.load_used_mods_state()

    assert service.used_mods == {"deltarune": [loaded_mod]}
    assert not hasattr(service, "_pending_mod_ids")
    assert app_state.local_config["used_mods_deltarune"] == {"deltarune": "kept_mod"}
    settings_service.write_local_config.assert_called_once()
