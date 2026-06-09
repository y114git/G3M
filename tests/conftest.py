"""Shared pytest fixtures and test configuration."""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication

from models.app_state import AppState
from ui.common.feedback import FeedbackManager
from utils.path_utils import set_user_data_root_override

_THREAD_ATTRS = (
    "_compatibility_thread",
    "_icon_loader_runnable",
    "thread",
    "_thread",
    "worker_thread",
    "_worker_thread",
    "monitor_thread",
    "fetch_thread",
    "details_thread",
    "metadata_thread",
    "install_thread",
    "full_install_thread",
    "current_install_thread",
    "changelog_thread",
    "presence_thread",
)


def _pump_events(app: QApplication, cycles: int = 3) -> None:
    for _ in range(cycles):
        app.processEvents()


def _stop_known_widget_threads(app: QApplication) -> None:
    from PyQt6.QtCore import QThread

    for widget in list(app.allWidgets()):
        for attr_name in _THREAD_ATTRS:
            try:
                thread = getattr(widget, attr_name, None)
                if not isinstance(thread, QThread):
                    continue
                if thread.isRunning():
                    thread.requestInterruption()
                    thread.quit()
                    if not thread.wait(50):
                        thread.terminate()
                        thread.wait(50)
                thread.deleteLater()
            except Exception as e:
                logging.debug(f'_stop_known_widget_threads: {attr_name}: {e}')


def _close_widgets(app: QApplication) -> None:
    for widget in list(app.topLevelWidgets()):
        try:
            widget.close()
            widget.deleteLater()
        except Exception as e:
            logging.debug("_close_widgets: failed closing top-level widget: %s", e, exc_info=True)


@pytest.fixture(scope='session')
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app

    from PyQt6.QtCore import QThread, QThreadPool

    from ui.utils.ui_utils import safe_stop_thread
    _pump_events(app)
    thread_pool = QThreadPool.globalInstance()
    if thread_pool is not None:
        thread_pool.clear()
        if thread_pool.activeThreadCount() > 0:
            thread_pool.waitForDone(200)
    for widget in app.allWidgets():
        for attr_name in _THREAD_ATTRS:
            try:
                thread = getattr(widget, attr_name, None)
                if thread and isinstance(thread, QThread):
                    safe_stop_thread(thread, timeout=100, blocking=False)
            except Exception as e:
                logging.debug(f'teardown_qt_threads: failed to stop thread attribute {attr_name}: {e}', exc_info=True)
    _close_widgets(app)
    _pump_events(app)


@pytest.fixture(autouse=True)
def sandbox_user_data_paths(monkeypatch, request, temp_dir):
    sandbox_root = Path(temp_dir) / "G3M"
    sandbox_root.mkdir(parents=True, exist_ok=True)
    temp_path = sandbox_root
    home_dir = temp_path / "home"
    appdata_dir = temp_path / "appdata"
    localappdata_dir = temp_path / "localappdata"
    for path in (home_dir, appdata_dir, localappdata_dir):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    monkeypatch.setenv("APPDATA", str(appdata_dir))
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata_dir))
    monkeypatch.setenv("TMP", str(temp_path))
    monkeypatch.setenv("TEMP", str(temp_path))
    monkeypatch.setenv("TMPDIR", str(temp_path))
    skip_override = any(
        marker.name == "skip_user_data_override"
        for marker in request.node.iter_markers()
    )
    if not skip_override:
        set_user_data_root_override(str(temp_path))
    yield
    if not skip_override:
        set_user_data_root_override(None)


@pytest.fixture(autouse=True)
def cleanup_threads(request):
    yield
    if "qapp" not in request.fixturenames:
        return
    app = QApplication.instance()
    if app is None:
        return
    from PyQt6.QtCore import QThreadPool
    _pump_events(app)
    try:
        _stop_known_widget_threads(app)
    except Exception as e:
        logging.debug(f'cleanup_threads: failed during thread cleanup sweep: {e}', exc_info=True)
    _close_widgets(app)
    _pump_events(app)
    pool = QThreadPool.globalInstance()
    if pool is not None:
        pool.clear()
        if pool.activeThreadCount() > 0:
            try:
                timeout_ms = int(os.getenv("WAIT_FOR_DONE_TIMEOUT_MS", "5000"))
            except ValueError:
                timeout_ms = 5000
            pool.waitForDone(timeout_ms)
    _pump_events(app)


@pytest.fixture
def temp_dir(tmp_path_factory):
    return str(tmp_path_factory.mktemp("g3m"))


@pytest.fixture
def temp_mods_dir(temp_dir):
    mods_dir = os.path.join(temp_dir, 'mods')
    os.makedirs(mods_dir, exist_ok=True)
    return mods_dir


@pytest.fixture
def temp_config_dir(temp_dir):
    config_dir = os.path.join(temp_dir, 'settings')
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


@pytest.fixture
def app_state(temp_dir, temp_mods_dir, temp_config_dir):
    state = AppState()
    state.config_dir = temp_config_dir
    state.mods_dir = temp_mods_dir
    state.config_path = os.path.join(temp_config_dir, 'settings.json')
    state.mods_metadata_path = os.path.join(temp_mods_dir, 'mods_data.json')
    return state


@pytest.fixture
def feedback_service(qapp):
    parent = QObject()
    manager = FeedbackManager(parent)
    return manager


@pytest.fixture
def mock_requests():
    with patch('requests.get') as mock_get, patch('requests.post') as mock_post, patch('requests.Session') as mock_session:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.text = ''
        mock_response.content = b''
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        mock_post.return_value = mock_response
        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session_instance.post.return_value = mock_response
        mock_session.return_value = mock_session_instance
        yield {'get': mock_get, 'post': mock_post, 'session': mock_session, 'response': mock_response}


@pytest.fixture
def sample_mod_config():
    return {'config_version': '1.0.0', 'id': 'test_mod_001', 'name': 'Test Mod', 'version': '1.0.0', 'author': 'Test Author', 'description': 'A test mod', 'game': 'deltarune', 'files': {}}


@pytest.fixture
def sample_mod_folder(temp_mods_dir, sample_mod_config):
    key = sample_mod_config.get('id', 'test_mod_001')
    mod_folder = os.path.join(temp_mods_dir, key)
    os.makedirs(mod_folder, exist_ok=True)
    import json
    config_path = os.path.join(mod_folder, 'mod_config.json')
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(sample_mod_config, f, indent=2)
    return mod_folder


@pytest.fixture
def game_data_dir():
    tests_dir = Path(__file__).parent
    game_data_path = tests_dir / 'fixtures' / 'game_data'
    return str(game_data_path)


@pytest.fixture
def patches_dir():
    tests_dir = Path(__file__).parent
    patches_path = tests_dir / 'fixtures' / 'patches'
    return str(patches_path)


@pytest.fixture
def deltarune_chapter_dirs(game_data_dir):
    base = Path(game_data_dir) / 'deltarune'
    return {'menu': str(base / 'chapter0_menu'), 'chapter1': str(base / 'chapter1_'), 'chapter2': str(base / 'chapter2_'), 'chapter3': str(base / 'chapter3_'), 'chapter4': str(base / 'chapter4_')}


@pytest.fixture
def patches_game_dirs(patches_dir):
    patches_path = Path(patches_dir)
    if not patches_path.exists():
        return {}
    result = {}
    deltarune_path = patches_path / 'deltarune'
    if deltarune_path.exists():
        result['deltarune'] = {'menu': str(deltarune_path / 'chapter0_menu'), 'chapter1': str(deltarune_path / 'chapter1_'), 'chapter2': str(deltarune_path / 'chapter2_'), 'chapter3': str(deltarune_path / 'chapter3_'), 'chapter4': str(deltarune_path / 'chapter4_')}
    for game_name in ['deltarune_demo', 'undertale', 'undertale_yellow', 'pizzatower', 'sugaryspire']:
        game_path = patches_path / game_name
        if game_path.exists():
            result[game_name] = str(game_path)
    return result


@pytest.fixture
def mods_dir():
    tests_dir = Path(__file__).parent
    mods_path = tests_dir / 'fixtures' / 'mods'
    return str(mods_path)


@pytest.fixture
def full_mod_structure_dir(mods_dir):
    return str(Path(mods_dir) / 'test_mod_full_structure')


@pytest.fixture
def all_test_mods_dirs(mods_dir):
    mods_path = Path(mods_dir)
    if not mods_path.exists():
        return {}
    return {'full_structure': str(mods_path / 'test_mod_full_structure'), 'chapter1_only': str(mods_path / 'test_mod_chapter1_only'), 'multiple_chapters': str(mods_path / 'test_mod_multiple_chapters'), 'demo': str(mods_path / 'test_mod_demo'), 'undertale': str(mods_path / 'test_mod_undertale')}
