import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication
from core.app_state import AppState
from ui.common.feedback import FeedbackManager


@pytest.fixture(scope='session')
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app
    import time
    from PyQt6.QtCore import QThreadPool
    app.processEvents()
    time.sleep(0.2)
    app.processEvents()
    thread_pool = QThreadPool.globalInstance()
    if thread_pool is not None:
        thread_pool.waitForDone(2000)


@pytest.fixture(autouse=True)
def cleanup_threads(qapp):
    yield
    import time
    from PyQt6.QtCore import QThreadPool, QThread, QObject
    from PyQt6.QtWidgets import QWidget
    from utils.thread_utils import safe_stop_thread
    for _ in range(3):
        qapp.processEvents()
        time.sleep(0.05)

    def find_and_stop_threads(obj, visited=None):
        if visited is None:
            visited = set()
        try:
            obj_id = id(obj)
        except Exception:
            return
        if obj_id in visited:
            return
        visited.add(obj_id)
        try:
            import sip
            if hasattr(sip, 'isdeleted') and sip.isdeleted(obj):
                return
        except (ImportError, AttributeError):
            pass
        try:
            if isinstance(obj, QThread):
                try:
                    if obj.isRunning():
                        try:
                            obj.blockSignals(True)
                            for signal_name in ['finished', 'compatibility_checked', 'result', 'error', 'progress']:
                                if hasattr(obj, signal_name):
                                    try:
                                        signal = getattr(obj, signal_name)
                                        signal.disconnect()
                                    except (TypeError, RuntimeError):
                                        pass
                            obj.blockSignals(False)
                        except Exception:
                            pass
                        safe_stop_thread(obj, timeout=1000)
                    if not obj.isRunning():
                        try:
                            obj.deleteLater()
                        except Exception:
                            pass
                except Exception:
                    pass
                return
            if isinstance(obj, (QWidget, QObject)):
                for attr_name in ['_compatibility_thread', '_icon_loader_runnable', '_icon_loader_signals', 'thread', '_thread', 'worker_thread', '_worker_thread']:
                    try:
                        if hasattr(obj, attr_name):
                            thread = getattr(obj, attr_name)
                            if thread and isinstance(thread, QThread):
                                try:
                                    if thread.isRunning():
                                        try:
                                            thread.blockSignals(True)
                                            for signal_name in ['finished', 'compatibility_checked', 'result', 'error']:
                                                if hasattr(thread, signal_name):
                                                    try:
                                                        getattr(thread, signal_name).disconnect()
                                                    except (TypeError, RuntimeError):
                                                        pass
                                            thread.blockSignals(False)
                                        except Exception:
                                            pass
                                        safe_stop_thread(thread, timeout=1000)
                                    if not thread.isRunning():
                                        try:
                                            thread.deleteLater()
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                    except Exception:
                        pass
                try:
                    children = obj.children()
                    for child in children:
                        find_and_stop_threads(child, visited)
                except Exception:
                    pass
        except Exception:
            pass
    try:
        for widget in qapp.allWidgets():
            find_and_stop_threads(widget)
    except Exception:
        pass
    for _ in range(3):
        qapp.processEvents()
        time.sleep(0.05)
    pool = QThreadPool.globalInstance()
    if pool is not None:
        pool.clear()
        if pool.activeThreadCount() > 0:
            pool.waitForDone(2000)
    for _ in range(5):
        qapp.processEvents()
        time.sleep(0.05)


@pytest.fixture
def temp_dir():
    temp_path = tempfile.mkdtemp(prefix='deltahub_test_')
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


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
def temp_plugins_dir(temp_dir):
    plugins_dir = os.path.join(temp_dir, 'plugins')
    os.makedirs(plugins_dir, exist_ok=True)
    return plugins_dir


@pytest.fixture
def app_state(temp_dir, temp_mods_dir, temp_config_dir, temp_plugins_dir):
    state = AppState()
    state.config_dir = temp_config_dir
    state.mods_dir = temp_mods_dir
    state.plugins_dir = temp_plugins_dir
    state.config_path = os.path.join(temp_config_dir, 'settings.json')
    state.mods_metadata_path = os.path.join(temp_mods_dir, 'metadata.json')
    state.plugins_metadata_path = os.path.join(temp_plugins_dir, 'metadata.json')
    return state


@pytest.fixture
def feedback_manager(qapp):
    parent = QObject()
    manager = FeedbackManager(parent)
    return manager


@pytest.fixture
def mock_gamebanana_api():
    with patch('src.utils.gamebanana_api.GameBananaAPI') as mock_api_class:
        mock_api = MagicMock()
        mock_api_class.return_value = mock_api
        mock_api.get_game_mods.return_value = ([], [])
        mock_api.get_mod_details.return_value = {}
        mock_api.get_supported_files_for_mod.return_value = {'supported_files': [], 'has_supported_files': False, 'compatibility_checked': True}
        mock_api.get_file_contents.return_value = []
        yield mock_api


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
def mock_file_operations(temp_dir):

    def mock_get_user_data_root():
        return temp_dir

    def mock_get_user_mods_dir():
        return os.path.join(temp_dir, 'mods')

    def mock_get_user_plugins_dir():
        return os.path.join(temp_dir, 'plugins')
    with patch('src.utils.path_utils.get_user_data_root', mock_get_user_data_root), patch('src.utils.path_utils.get_user_mods_dir', mock_get_user_mods_dir), patch('src.utils.path_utils.get_user_plugins_dir', mock_get_user_plugins_dir):
        yield


@pytest.fixture
def sample_mod_config():
    return {'mod_key': 'test_mod_001', 'name': 'Test Mod', 'version': '1.0.0', 'author': 'Test Author', 'description': 'A test mod', 'game': 'deltarune', 'chapters': [1, 2], 'files': []}


@pytest.fixture
def sample_mod_folder(temp_mods_dir, sample_mod_config):
    mod_key = sample_mod_config['mod_key']
    mod_folder = os.path.join(temp_mods_dir, mod_key)
    os.makedirs(mod_folder, exist_ok=True)
    import json
    config_path = os.path.join(mod_folder, 'mod_config.json')
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(sample_mod_config, f, indent=2)
    return mod_folder


@pytest.fixture
def mock_localization():
    with patch('src.managers.localization_manager.localization_manager') as mock_loc:
        mock_loc.tr = lambda key, **kwargs: key
        mock_loc.detect_system_language.return_value = 'en'
        mock_loc.load_language.return_value = True
        yield mock_loc


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
def game_dirs(game_data_dir):
    base = Path(game_data_dir)
    return {'deltarune': str(base / 'deltarune'), 'deltarune_demo': str(base / 'deltarune_demo'), 'undertale': str(base / 'undertale'), 'undertale_yellow': str(base / 'undertale_yellow')}


@pytest.fixture
def patches_dirs(patches_dir):
    patches_path = Path(patches_dir)
    if not patches_path.exists():
        return []
    patch_dirs = []
    for game_dir in patches_path.iterdir():
        if game_dir.is_dir():
            if (game_dir / 'chapter1_').exists() or (game_dir / 'chapter0_menu').exists():
                for chapter_dir in game_dir.iterdir():
                    if chapter_dir.is_dir():
                        patch_dirs.append(str(chapter_dir))
            else:
                patch_dirs.append(str(game_dir))
    return patch_dirs


@pytest.fixture
def patches_game_dirs(patches_dir):
    patches_path = Path(patches_dir)
    if not patches_path.exists():
        return {}
    result = {}
    deltarune_path = patches_path / 'deltarune'
    if deltarune_path.exists():
        result['deltarune'] = {'menu': str(deltarune_path / 'chapter0_menu'), 'chapter1': str(deltarune_path / 'chapter1_'), 'chapter2': str(deltarune_path / 'chapter2_'), 'chapter3': str(deltarune_path / 'chapter3_'), 'chapter4': str(deltarune_path / 'chapter4_')}
    for game_name in ['deltarune_demo', 'undertale', 'undertale_yellow']:
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


@pytest.fixture(autouse=True)
def setup_test_environment(mock_localization):
    pass
