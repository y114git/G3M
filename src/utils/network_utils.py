import os
import platform
import re
import time
import logging
from pathlib import Path
import requests
import threading
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config.constants import MAX_DOWNLOAD_RETRIES, DOWNLOAD_CHUNK_SIZE, NETWORK_TIMEOUT_SHORT, NETWORK_TIMEOUT_MEDIUM, NETWORK_TIMEOUT_HEAD, NETWORK_TIMEOUT_LONG
_session_lock = threading.Lock()
_shared_session = None


def get_session(app_state=None) -> requests.Session:
    if app_state and hasattr(app_state, 'network_session') and (app_state.network_session is not None):
        return app_state.network_session
    global _shared_session
    if _shared_session is not None:
        return _shared_session
    with _session_lock:
        if _shared_session is None:
            _shared_session = _build_session()
    return _shared_session


def _build_session() -> requests.Session:
    from config.constants import LAUNCHER_VERSION, BROWSER_HEADERS
    urllib3_logger = logging.getLogger('urllib3.connectionpool')
    urllib3_logger.setLevel(logging.ERROR)
    requests_logger = logging.getLogger('requests')
    requests_logger.setLevel(logging.WARNING)
    session = requests.Session()
    headers = dict(BROWSER_HEADERS or {})
    headers.setdefault('User-Agent', f'DELTAHUB/{LAUNCHER_VERSION}')
    session.headers.update(headers)
    retry = Retry(total=3, connect=3, read=3, backoff_factor=0.3, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=('HEAD', 'GET', 'PUT', 'DELETE', 'OPTIONS', 'TRACE', 'POST'), raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=32)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


def close_shared_session() -> None:
    global _shared_session
    with _session_lock:
        if _shared_session is not None:
            try:
                _shared_session.close()
            finally:
                _shared_session = None


def get_filename_from_url(session, url):
    try:
        from urllib.parse import urlparse, unquote
        response = session.head(url, timeout=NETWORK_TIMEOUT_MEDIUM, allow_redirects=True)
        if (content_disp := response.headers.get('Content-Disposition')):
            if (fn_match := re.search('filename\\*?=(.+)', content_disp, re.IGNORECASE)):
                fn_data = fn_match.group(1).strip()
                if fn_data.lower().startswith("utf-8''"):
                    return unquote(fn_data[7:], 'utf-8')
                return fn_data.strip('"\'')
        path = urlparse(response.url).path
        if path and path != '/' and (not path.endswith('/')):
            potential_name = os.path.basename(unquote(path))
            if '.' in potential_name:
                return potential_name
    except (requests.RequestException, ValueError, AttributeError) as e:
        pass
    return Path(url.split('?', 1)[0]).name or 'file.tmp'


def download_file(session, url, tmp_path, progress_callback=None, total_size: int = 0, downloaded_ref: list[int] | None = None, max_retries: int = MAX_DOWNLOAD_RETRIES, cancel_check=None, on_response=None):
    if downloaded_ref is None:
        downloaded_ref = [0]
    expected_size = 0
    try:
        h = session.head(url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD)
        expected_size = int(h.headers.get('content-length', 0))
    except (requests.RequestException, ValueError) as e:
        expected_size = 0
    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            current_size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            headers = {}
            if expected_size and 0 < current_size < expected_size:
                headers['Range'] = f'bytes={current_size}-'
            if session is None:
                session = get_session()
            r = session.get(url, stream=True, timeout=NETWORK_TIMEOUT_LONG, allow_redirects=True, headers=headers)
            r.raise_for_status()
            try:
                if on_response:
                    on_response(r)
            except (TypeError, AttributeError) as e:
                logging.debug(f'download_file: on_response callback failed: {e}')
            status_code = getattr(r, 'status_code', 200)
            duplicate_remaining = 0
            mode = 'ab'
            if status_code == 206 and 'Range' in headers:
                mode = 'ab'
            else:
                mode = 'wb'
                if current_size > 0:
                    duplicate_remaining = current_size
            this_request_expected = 0
            try:
                this_request_expected = int(r.headers.get('content-length', 0))
            except (ValueError, TypeError) as e:
                logging.debug(f'download_file: failed to parse content-length: {e}')
                this_request_expected = 0
            written_this_request = 0
            with open(tmp_path, mode) as f:
                for chunk in r.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    if not chunk:
                        continue
                    if cancel_check and cancel_check():
                        raise RuntimeError('download_cancelled')
                    f.write(chunk)
                    sz = len(chunk)
                    written_this_request += sz
                    if duplicate_remaining > 0:
                        if sz <= duplicate_remaining:
                            duplicate_remaining -= sz
                        else:
                            add = sz - duplicate_remaining
                            downloaded_ref[0] += add
                            duplicate_remaining = 0
                    else:
                        downloaded_ref[0] += sz
                    if total_size > 0 and progress_callback:
                        try:
                            progress = int(min(100, max(0, downloaded_ref[0] / total_size * 100)))
                            progress_callback(progress)
                        except (TypeError, ZeroDivisionError) as e:
                            logging.debug(f'download_file: progress callback failed: {e}')
            final_size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            if this_request_expected and written_this_request < this_request_expected:
                raise IOError('connection dropped during download')
            if expected_size and final_size < expected_size:
                continue
            return
        except (requests.RequestException, OSError, IOError) as e:
            if attempt >= max_retries:
                raise
            try:
                time.sleep(min(2.0, 0.2 * attempt))
            except OSError as sleep_e:
                logging.debug(f'download_file: sleep failed: {sleep_e}')


def check_internet_connection(max_attempts: int = 2) -> bool:
    for attempt in range(max_attempts):
        try:
            session = get_session()
            session.get('https://www.google.com', timeout=NETWORK_TIMEOUT_SHORT)
            return True
        except requests.RequestException:
            if attempt < max_attempts - 1:
                continue
    return False


def safe_request(method: str, url: str, session=None, timeout=None, **kwargs):
    if session is None:
        session = get_session()
    if timeout is None:
        timeout = NETWORK_TIMEOUT_MEDIUM
    try:
        method_func = getattr(session, method.lower())
        return method_func(url, timeout=timeout, **kwargs)
    except requests.RequestException as e:
        return None
    except Exception as e:
        return None


def increment_launch_counter() -> None:
    from config.constants import CLOUD_FUNCTIONS_BASE_URL
    os_map = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'macos'}
    os_key = os_map.get(platform.system(), 'other')
    url = f'{CLOUD_FUNCTIONS_BASE_URL}/incrementLaunches'
    safe_request('post', url, json={'os': os_key}, timeout=NETWORK_TIMEOUT_SHORT)
