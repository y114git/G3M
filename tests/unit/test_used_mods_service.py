"""Unit tests for test used mods service."""

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


def test_direct_launch_menu_warning_failure_is_suppressed(app_state):
    """Checks menu-tab direct-launch warning cannot crash used-mods UI flow."""
    feedback_service = Mock()
    feedback_service.show_message.side_effect = RuntimeError("toast deleted")
    settings_service = Mock()
    app_state.local_config = {}

    service = UsedModsManager(
        app_state,
        Mock(),
        feedback_service,
        settings_service,
        parent=None,
    )

    service.toggle_direct_launch_for_chapter("deltarune_0")

    feedback_service.show_message.assert_called_once()
    settings_service.write_local_config.assert_not_called()


def test_mod_steps_default_to_one_step_without_metadata(app_state):
    mods = [
        SimpleNamespace(id="main", name="Main"),
        SimpleNamespace(id="addon", name="Addon"),
    ]
    service = UsedModsManager(app_state, Mock(), Mock(), Mock(), parent=None)
    service.used_mods = {"deltarune": mods}

    assert service.get_mod_steps("deltarune") == [mods]


def test_set_mod_steps_normalizes_duplicates_and_persists_flat_compatibility(app_state):
    main = SimpleNamespace(id="main", name="Main")
    addon = SimpleNamespace(id="addon", name="Addon")
    settings_service = Mock()
    service = UsedModsManager(
        app_state, Mock(), Mock(), settings_service, parent=None
    )
    service._mods_state_loaded = True
    service.used_mods = {"deltarune": [main, addon]}

    service.set_mod_steps("deltarune", [[main], [addon, main], []])

    assert service.get_mod_steps("deltarune") == [[main], [addon]]
    assert service.get_used_mods_list("deltarune") == [main, addon]
    assert app_state.local_config["mod_steps_deltarune"] == {
        "deltarune": [["main"], ["addon"]]
    }
    assert app_state.local_config["used_mods_deltarune"] == {
        "deltarune": ["main", "addon"]
    }
    settings_service.write_local_config.assert_called_once()


def test_get_active_mod_steps_returns_saved_plan_for_single_tab_game(app_state):
    from models.game_modes import get_game

    app_state.game_mode = get_game("undertale")
    main = SimpleNamespace(id="main", name="Main")
    addon = SimpleNamespace(id="addon", name="Addon")
    service = UsedModsManager(app_state, Mock(), Mock(), Mock(), parent=None)
    service.used_mods = {"undertale": [main, addon]}
    app_state.local_config["mod_steps_undertale"] = {
        "undertale": [["main"], ["addon"]]
    }

    assert service.get_active_mod_steps() == {
        "undertale": [[main], [addon]]
    }


def test_get_mod_steps_migrates_legacy_chapter_key(app_state):
    mod = SimpleNamespace(id="main", name="Main")
    service = UsedModsManager(app_state, Mock(), Mock(), Mock(), parent=None)
    service.used_mods = {"deltarune_0": [mod]}
    app_state.local_config["mod_steps_deltarune"] = {"0": [["main"]]}

    assert service.get_mod_steps("deltarune_0") == [[mod]]
    assert app_state.local_config["mod_steps_deltarune"] == {
        "deltarune_0": [["main"]]
    }


def test_normalizing_steps_preserves_pending_ids_in_original_step(app_state):
    mod = SimpleNamespace(id="loaded", name="Loaded")
    service = UsedModsManager(app_state, Mock(), Mock(), Mock(), parent=None)
    service.used_mods = {"deltarune": [mod]}
    service._pending_mod_ids = {"deltarune": ["pending"]}
    app_state.local_config["mod_steps_deltarune"] = {
        "deltarune": [["pending"], ["loaded"]]
    }

    service._normalize_stored_steps("deltarune")

    assert app_state.local_config["mod_steps_deltarune"]["deltarune"] == [
        ["pending"],
        ["loaded"],
    ]


def test_set_mod_steps_suppresses_persistence_failure(app_state):
    mod = SimpleNamespace(id="main", name="Main")
    settings = Mock()
    settings.write_local_config.side_effect = OSError("disk full")
    service = UsedModsManager(app_state, Mock(), Mock(), settings, parent=None)
    service._mods_state_loaded = True

    service.set_mod_steps("deltarune", [[mod]])

    assert service.used_mods["deltarune"] == [mod]
    settings.write_local_config.assert_called()


def test_normalizing_steps_appends_unassigned_mods_in_resolved_order(app_state):
    mods = [SimpleNamespace(id=mod_id, name=mod_id) for mod_id in ("z", "a", "m")]
    service = UsedModsManager(app_state, Mock(), Mock(), Mock(), parent=None)
    service.used_mods = {"deltarune": mods}
    app_state.local_config["mod_steps_deltarune"] = {"deltarune": [["a"]]}

    service._normalize_stored_steps("deltarune")

    assert app_state.local_config["mod_steps_deltarune"]["deltarune"] == [
        ["a", "z", "m"]
    ]


def test_remove_mod_cleans_saved_step_membership(app_state):
    main = SimpleNamespace(id="main", name="Main")
    addon = SimpleNamespace(id="addon", name="Addon")
    settings_service = Mock()
    service = UsedModsManager(app_state, Mock(), Mock(), settings_service, parent=None)
    service._mods_state_loaded = True
    service.used_mods = {"deltarune": [main, addon]}
    app_state.local_config["mod_steps_deltarune"] = {
        "deltarune": [["main"], ["addon"]]
    }

    service.remove_mod_from_all_chapters(main)

    assert app_state.local_config["mod_steps_deltarune"] == {
        "deltarune": [["addon"]]
    }
