from unittest.mock import Mock, patch

from PyQt6.QtCore import QObject, QThread


def test_iter_shutdown_threads_collects_direct_and_container_threads(qapp):
    from app.cleanup import _iter_shutdown_threads

    root = QObject()
    direct = QThread(root)
    child = QObject(root)
    child.worker_thread = QThread(child)
    child._workers = {"a": QThread(child)}

    thread_entries = list(_iter_shutdown_threads(root))
    threads = [entry[0] for entry in thread_entries]

    assert direct in threads
    assert child.worker_thread in threads
    assert child._workers["a"] in threads
    assert len({id(thread) for thread in threads}) == len(threads)


def test_perform_close_cleanup_stops_discovered_threads(qapp):
    from app.cleanup import perform_close_cleanup

    root = QObject()
    root._safe_set_parent_none = Mock()
    root.customization_service = Mock()
    root.plugin_runtime_service = Mock()
    root.session_manager = Mock()
    root.search_display = Mock()
    root.game_launcher = Mock()
    root.game_launcher.monitor_thread = None
    root.game_launcher.mod_patcher = Mock()
    root.refresh_controller = Mock()
    root.refresh_controller.fetch_thread = None
    root.refresh_controller.details_thread = None
    root.settings_service = Mock()
    root.main_tab_widget = Mock()
    root.main_tab_widget.currentIndex.return_value = 0
    root.app_state = Mock()
    root.app_state.local_config = {}
    root.hide = Mock()
    child = QObject(root)
    child.thread = QThread(child)
    child._workers = {"download": QThread(child)}

    with (
        patch("app.cleanup.safe_stop_thread") as safe_stop_thread,
        patch("app.cleanup.QThreadPool.globalInstance") as pool_instance,
        patch("app.cleanup.QApplication.processEvents"),
    ):
        pool = Mock()
        pool_instance.return_value = pool
        perform_close_cleanup(root)

    stopped = [call.args[0] for call in safe_stop_thread.call_args_list]
    assert child.thread in stopped
    assert child._workers["download"] in stopped
    pool.clear.assert_called_once_with()
    pool.waitForDone.assert_called_once()


def test_perform_close_cleanup_skips_threads_managed_by_analytics_and_session(qapp):
    from app.cleanup import perform_close_cleanup

    root = QObject()
    root._safe_set_parent_none = Mock()
    root.customization_service = Mock()
    root.plugin_runtime_service = Mock()
    root.session_manager = Mock()
    root.search_display = Mock()
    root.game_launcher = Mock()
    root.game_launcher.monitor_thread = None
    root.game_launcher.mod_patcher = Mock()
    root.refresh_controller = Mock()
    root.refresh_controller.fetch_thread = None
    root.refresh_controller.details_thread = None
    root.settings_service = Mock()
    root.main_tab_widget = Mock()
    root.main_tab_widget.currentIndex.return_value = 0
    root.app_state = Mock()
    root.app_state.local_config = {}
    root.hide = Mock()
    root.analytics_service = QObject(root)
    analytics_thread = QThread(root.analytics_service)
    root.analytics_service._upload_thread = analytics_thread

    with (
        patch("app.cleanup.safe_stop_thread") as safe_stop_thread,
        patch("app.cleanup.QThreadPool.globalInstance") as pool_instance,
        patch("app.cleanup.QApplication.processEvents"),
    ):
        pool = Mock()
        pool_instance.return_value = pool
        perform_close_cleanup(root)

    stopped = [call.args[0] for call in safe_stop_thread.call_args_list]
    assert analytics_thread not in stopped
