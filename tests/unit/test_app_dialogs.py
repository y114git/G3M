"""Unit tests for AppWindow dialog callback safety."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock


def test_open_community_dialog_executes(monkeypatch):
    """Checks the community placeholder dialog opens through the public callback."""
    from app import dialogs

    dialog = Mock()
    dialog_class = Mock(return_value=dialog)
    monkeypatch.setattr(
        dialogs,
        "CommunityDialog",
        dialog_class,
        raising=False,
    )
    window = SimpleNamespace(app_state=SimpleNamespace())

    dialogs.open_community_dialog(window)

    dialog_class.assert_called_once_with(window, window.app_state)
    dialog.exec.assert_called_once_with()


def test_community_dialog_builds_gamebanana_feed_filters(qapp):
    """Checks the community view exposes both feed filters without loading early."""
    from ui.dialogs.community_dialog import CommunityDialog

    dialog = CommunityDialog(None, SimpleNamespace(global_settings={}))

    assert dialog.game_combo.itemData(0) is None
    assert dialog.feed_combo.itemData(0) == "New"
    assert dialog.feed_combo.itemData(1) == "Featured"
    assert dialog._worker is None


def test_community_dialog_does_not_retire_stopped_worker_twice(qapp, monkeypatch):
    from ui.dialogs import community_dialog

    dialog = community_dialog.CommunityDialog(
        None, SimpleNamespace(global_settings={})
    )
    worker = Mock()
    retired = []
    monkeypatch.setattr(community_dialog, "retire_qthread", retired.append)
    dialog._worker = worker

    dialog._stop_worker()
    monkeypatch.setattr(dialog, "sender", lambda: worker)
    dialog._on_finished()

    assert retired == [worker]


def test_download_record_update_ignores_broken_status_feedback():
    """Checks download record status feedback cannot crash card refresh."""
    from app.dialogs import on_downloads_record_updated
    from models.download_models import UseStatus

    card = Mock()
    window = SimpleNamespace(
        feedback_service=Mock(),
        search_display=SimpleNamespace(card_widget_cache={"card": card}),
    )
    window.feedback_service.update_status.side_effect = RuntimeError("status deleted")
    record = SimpleNamespace(
        use_status=UseStatus.NEEDS_MANUAL,
        display_name="Mod",
        id="mod",
    )

    on_downloads_record_updated(window, record)

    card.update_action_button_state.assert_called_once_with()


def test_full_install_toggle_ignores_broken_unavailable_feedback(monkeypatch):
    """Checks macOS full-install feedback failure still reverts checkbox state."""
    from app import game_ui

    window = SimpleNamespace(
        app_state=SimpleNamespace(is_full_install=False),
        feedback_service=Mock(),
        full_install_checkbox=Mock(),
        game_launch=Mock(),
        _set_checkbox_checked_silently=Mock(),
    )
    window.feedback_service.show_message.side_effect = RuntimeError("toast deleted")
    monkeypatch.setattr(game_ui.platform, "system", lambda: "Darwin")

    game_ui.on_toggle_full_install(window, True)

    assert window.app_state.is_full_install is True
    window._set_checkbox_checked_silently.assert_called_once_with(
        window.full_install_checkbox,
        False,
    )
    window.game_launch.update_button_state.assert_not_called()


def test_invalid_executable_feedback_failure_still_refreshes_and_clears_focus():
    """Checks invalid executable feedback failure does not skip cleanup."""
    from app.game_ui import _commit_validated_executable_text

    focus = Mock()
    window = SimpleNamespace(
        feedback_service=Mock(),
        settings_service=SimpleNamespace(
            validate_executable_path=Mock(return_value=False)
        ),
        focusWidget=Mock(return_value=focus),
    )
    window.feedback_service.show_message.side_effect = RuntimeError("toast deleted")
    save_callback = Mock()
    refresh_callback = Mock()

    _commit_validated_executable_text(
        window,
        "C:/bad.exe",
        save_callback,
        refresh_callback,
    )

    save_callback.assert_not_called()
    refresh_callback.assert_called_once_with()
    focus.clearFocus.assert_called_once_with()


def test_downloads_enqueue_with_feedback_ignores_broken_status(tmp_path):
    """Checks download enqueue still succeeds when status feedback is gone."""
    from models.download_models import SourceKind, TargetKind
    from services.downloads.manager import DownloadsManager

    manager = DownloadsManager(str(tmp_path), lambda: {})
    feedback_service = Mock()
    feedback_service.update_status.side_effect = RuntimeError("status deleted")
    manager.enqueue = Mock(return_value=("record-1", False))

    record_id, is_duplicate = manager.enqueue_with_feedback(
        feedback_service,
        display_name="Mod",
        source_kind=SourceKind.EXTERNAL_URL,
        target_kind=TargetKind.MOD,
        source_url="https://example.com/mod.zip",
    )

    assert record_id
    assert is_duplicate is False


def test_main_window_permission_error_ignores_broken_feedback():
    """Checks permission error reporting cannot crash when feedback UI is gone."""
    from app.window.main import AppWindow

    window = cast(AppWindow, SimpleNamespace(feedback_service=Mock()))
    window._safe_show_message = lambda *args, **kwargs: AppWindow._safe_show_message(
        window, *args, **kwargs
    )
    window.feedback_service.show_message.side_effect = RuntimeError("toast deleted")

    AppWindow._handle_permission_error(window, "C:/locked")

    window.feedback_service.show_message.assert_called_once_with(
        "error", "errors.access_denied", path="C:/locked"
    )


def test_main_window_rate_limit_ignores_broken_feedback():
    """Checks GB rate-limit persistence still happens when warning UI is gone."""
    from app.window.main import AppWindow

    window = cast(
        AppWindow,
        SimpleNamespace(
            app_state=SimpleNamespace(local_config={}),
            settings_service=Mock(),
            feedback_service=Mock(),
        ),
    )
    window._safe_show_message = lambda *args, **kwargs: AppWindow._safe_show_message(
        window, *args, **kwargs
    )
    window.feedback_service.show_message.side_effect = RuntimeError("toast deleted")

    AppWindow._on_gb_rate_limit_error(window)

    assert window.app_state.local_config["gb_rate_limit_notified_this_session"] is True
    window.settings_service.write_local_config.assert_called_once()
    window.feedback_service.show_message.assert_called_once()
