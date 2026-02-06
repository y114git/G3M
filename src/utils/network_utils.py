"""Network utilities for HTTP requests and downloads."""
import os
import platform
import re
import time
import logging
import threading
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config.constants import MAX_DOWNLOAD_RETRIES, DOWNLOAD_CHUNK_SIZE, NETWORK_TIMEOUT_SHORT, NETWORK_TIMEOUT_MEDIUM, NETWORK_TIMEOUT_HEAD, NETWORK_TIMEOUT_LONG
_session_lock = threading.Lock()
_shared_session = None


def get_session(app_state=None):
    if app_state and hasattr(app_state, 'network_session') and app_state.network_session is not None:
        return app_state.network_session
    global _shared_session
    if _shared_session is not None:
        return _shared_session
    with _session_lock:
        if _shared_session is None:
            _shared_session = _build_session()
    return _shared_session


def _build_session():
    from config.constants import LAUNCHER_VERSION, BROWSER_HEADERS
    logging.getLogger('urllib3.connectionpool').setLevel(logging.ERROR)
    logging.getLogger('requests').setLevel(logging.WARNING)
    session = requests.Session()
    headers = dict(BROWSER_HEADERS or {})
    headers.setdefault('User-Agent', f'DELTAHUB/{LAUNCHER_VERSION}')
    session.headers.update(headers)
    retry = Retry(total=3, connect=3, read=3, backoff_factor=0.3, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=('HEAD', 'GET', 'PUT', 'DELETE', 'OPTIONS', 'TRACE', 'POST'), raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=32)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


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
    except (requests.RequestException, ValueError, AttributeError):
        pass
    return Path(url.split('?', 1)[0]).name or 'file.tmp'


def download_file(session, url, tmp_path, progress_callback=None, total_size=0, downloaded_ref=None, max_retries=MAX_DOWNLOAD_RETRIES, cancel_check=None, on_response=None):
    if downloaded_ref is None:
        downloaded_ref = [0]
    try:
        expected_size = int(session.head(url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD).headers.get('content-length', 0))
    except (requests.RequestException, ValueError):
        expected_size = 0
    for attempt in range(1, max_retries + 1):
        try:
            current_size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            headers = {'Range': f'bytes={current_size}-'} if expected_size and 0 < current_size < expected_size else {}
            if session is None:
                session = get_session()
            r = session.get(url, stream=True, timeout=NETWORK_TIMEOUT_LONG, allow_redirects=True, headers=headers)
            r.raise_for_status()
            try:
                if on_response:
                    on_response(r)
            except (TypeError, AttributeError) as e:
                logging.debug(f'download_file: on_response callback failed: {e}')
            mode = 'ab' if getattr(r, 'status_code', 200) == 206 and 'Range' in headers else 'wb'
            duplicate_remaining = current_size if mode == 'wb' and current_size > 0 else 0
            try:
                this_request_expected = int(r.headers.get('content-length', 0))
            except (ValueError, TypeError):
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
                            downloaded_ref[0] += sz - duplicate_remaining
                            duplicate_remaining = 0
                    else:
                        downloaded_ref[0] += sz
                    if total_size > 0 and progress_callback:
                        try:
                            progress_callback(int(min(100, max(0, downloaded_ref[0] / total_size * 100))))
                        except (TypeError, ZeroDivisionError):
                            pass
            if this_request_expected and written_this_request < this_request_expected:
                raise IOError('connection dropped during download')
            if expected_size and (os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0) < expected_size:
                continue
            return
        except (requests.RequestException, OSError, IOError):
            if attempt >= max_retries:
                raise
            try:
                time.sleep(min(2.0, 0.2 * attempt))
            except OSError:
                pass


def check_internet_connection(max_attempts=2):
    for attempt in range(max_attempts):
        try:
            get_session().get('https://www.google.com', timeout=NETWORK_TIMEOUT_SHORT)
            return True
        except requests.RequestException:
            continue
    return False


def safe_request(method, url, session=None, timeout=None, **kwargs):
    try:
        return getattr(session or get_session(), method.lower())(url, timeout=timeout or NETWORK_TIMEOUT_MEDIUM, **kwargs)
    except Exception:
        return None


def increment_launch_counter():
    from config.constants import CLOUD_FUNCTIONS_BASE_URL
    os_key = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'macos'}.get(platform.system(), 'other')
    safe_request('post', f'{CLOUD_FUNCTIONS_BASE_URL}/incrementLaunches', json={'os': os_key}, timeout=NETWORK_TIMEOUT_SHORT)
