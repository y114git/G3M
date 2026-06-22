"""Unit tests for test app context."""

import os
from unittest.mock import Mock, patch


def test_build_application_context_creates_services_and_session(qapp, temp_dir):
    """Checks that building application context creates services and session."""
    from app_context.application_context import build_application_context

    user_root = os.path.join(temp_dir, "user")
    profiles_dir = os.path.join(temp_dir, "profiles")
    for path in (user_root, profiles_dir):
        os.makedirs(path, exist_ok=True)
    mock_presence_response = Mock()
    mock_presence_response.status_code = 200
    mock_presence_response.json.return_value = {"online": 0}
    with (
        patch("app_context.application_context.get_user_data_root", return_value=user_root),
        patch("app_context.application_context.get_launcher_dir", return_value=temp_dir),
        patch(
            "services.g3mtool_patching_service.get_user_data_root",
            return_value=user_root,
        ),
        patch("services.profile_service.get_user_profiles_dir", return_value=profiles_dir),
        patch(
            "workers.presence_worker.cloud_function_request",
            return_value=mock_presence_response,
        ),
    ):
        context = build_application_context()
    assert context.app_state.mods_dir
    assert context.app_state.game_path == ""
    assert context.app_state.demo_game_path == ""
    assert context.services.mod_service is not None
    assert context.services.game_launcher is not None
    assert context.services.analytics_service is not None
    assert context.services.downloads_manager.mods_dir == context.app_state.mods_dir
    assert context.services.discord_rich_presence_service is not None
    assert context.services.plugin_state_service is not None
    assert context.services.plugin_catalog_service is not None
    assert context.services.plugin_runtime_service is not None
    assert context.services.plugin_install_service is not None
    assert context.session_manager.session_id
