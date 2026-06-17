"""Unit tests for test window startup helpers."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.window.startup import (
    force_finish_initialization,
    handle_pending_install,
    on_mod_scan_finished,
    on_mods_loaded,
    post_show_initialization,
    trigger_initial_mods_refresh,
    update_installed_mods_display,
)


def test_handle_pending_install_consumes_url():
    window = SimpleNamespace(
        context=SimpleNamespace(pending_install_url="g3m://https://example.com/mod.zip"),
        handle_one_click_install=Mock(),
    )

    handle_pending_install(window)

    window.handle_one_click_install.assert_called_once_with(
        "g3m://https://example.com/mod.zip"
    )
    assert window.context.pending_install_url is None


def test_on_mods_loaded_stops_timer_and_emits_initialization():
    timer = Mock()
    timer.isActive.return_value = True
    signal = Mock()
    signal.emit = Mock()
    window = SimpleNamespace(
        initialization_timer=timer,
        initialization_finished=signal,
        app_state=SimpleNamespace(
            initialization_completed=False,
            pending_announce_check=False,
            update_in_progress=False,
        ),
    )

    on_mods_loaded(window)

    timer.stop.assert_called_once()
    signal.emit.assert_called_once()
    assert window.app_state.initialization_completed is True


def test_force_finish_initialization_sets_mods_loaded_before_emit():
    signal = Mock()
    signal.emit = Mock()
    app_state = SimpleNamespace(
        initialization_completed=False,
        pending_announce_check=False,
        update_in_progress=False,
        mods_loaded=False,
    )
    window = SimpleNamespace(initialization_finished=signal, app_state=app_state)

    force_finish_initialization(window)

    assert app_state.mods_loaded is True
    signal.emit.assert_called_once()


def test_post_show_initialization_runs_once():
    window = SimpleNamespace(_post_show_initialized=False)

    with patch(
        "bootstrap.bootstrap_coordinator.BootstrapCoordinator.post_show_initialization"
    ) as post_init:
        post_show_initialization(window)
        post_show_initialization(window)

    assert post_init.call_count == 1


def test_update_installed_mods_display_marks_library_initialized():
    display = Mock()
    window = SimpleNamespace(
        app_state=SimpleNamespace(
            current_mode="library",
            selected_chapter_id=None,
            library_initialized=False,
        ),
        library_display=SimpleNamespace(update_display=display),
    )

    update_installed_mods_display(window, set_library_initialized=True)

    display.assert_called_once()
    assert window.app_state.library_initialized is True


def test_trigger_initial_mods_refresh_builds_callbacks():
    refresh_controller = Mock()
    search_display = SimpleNamespace(update_filtered_mods=Mock())
    game_launch = SimpleNamespace(update_button_state=Mock())
    mods_loaded_signal = Mock()
    window = SimpleNamespace(
        refresh_controller=refresh_controller,
        language_combo=object(),
        search_display=search_display,
        game_launch=game_launch,
        mods_loaded_signal=mods_loaded_signal,
        app_state=SimpleNamespace(all_mods=["mod"]),
        _update_installed_mods_display=Mock(),
    )

    with patch("app.window.startup.relocalize_ui") as relocalize:
        trigger_initial_mods_refresh(window, saved_chapter_mode=True)
        kwargs = refresh_controller.refresh_mods_list.call_args.kwargs
        assert kwargs["is_initial"] is True
        assert kwargs["language_combo"] is window.language_combo
        kwargs["localization_callback"]()
        relocalize.assert_called_once_with(window)
        kwargs["on_fetch_finished_kwargs"]["update_action_button_callback"]()
        game_launch.update_button_state.assert_called_once()


def test_mod_scan_error_ignores_broken_status_feedback():
    """Checks scan failure still re-enables the window if status UI is gone."""
    window = SimpleNamespace(
        mod_service=SimpleNamespace(load_local_mods=Mock(side_effect=RuntimeError("scan failed"))),
        feedback_service=SimpleNamespace(
            update_status=Mock(side_effect=RuntimeError("status deleted"))
        ),
        setEnabled=Mock(),
    )

    on_mod_scan_finished(window, {})

    window.feedback_service.update_status.assert_called_once()
    window.setEnabled.assert_called_once_with(True)
