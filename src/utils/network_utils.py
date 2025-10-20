import os
import platform
import re
import time
from pathlib import Path
import requests


def get_filename_from_url(session, url):
    try:
        from urllib.parse import urlparse, unquote
        response = session.head(url, timeout=10, allow_redirects=True)
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
    except Exception:
        pass
    return Path(url.split('?', 1)[0]).name or 'file.tmp'


def download_file(session, url, tmp_path, progress_callback=None, total_size: int = 0, downloaded_ref: list[int] | None = None, max_retries: int = 5):
    if downloaded_ref is None:
        downloaded_ref = [0]
    expected_size = 0
    try:
        h = session.head(url, allow_redirects=True, timeout=15)
        expected_size = int(h.headers.get('content-length', 0))
    except Exception:
        expected_size = 0
    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            current_size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            headers = {}
            if expected_size and 0 < current_size < expected_size:
                headers['Range'] = f'bytes={current_size}-'
            r = session.get(url, stream=True, timeout=60, allow_redirects=True, headers=headers)
            r.raise_for_status()
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
            except Exception:
                this_request_expected = 0
            written_this_request = 0
            with open(tmp_path, mode) as f:
                for chunk in r.iter_content(chunk_size=262144):
                    if not chunk:
                        continue
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
                        except Exception:
                            pass
            final_size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            if this_request_expected and written_this_request < this_request_expected:
                raise IOError('connection dropped during download')
            if expected_size and final_size < expected_size:
                continue
            return
        except Exception:
            if attempt >= max_retries:
                raise
            try:
                time.sleep(min(2.0, 0.2 * attempt))
            except Exception:
                pass


def check_internet_connection() -> bool:
    try:
        requests.get('https://www.google.com', timeout=5)
        return True
    except requests.RequestException:
        return False


def increment_launch_counter() -> None:
    from config.constants import CLOUD_FUNCTIONS_BASE_URL
    os_map = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'macos'}
    os_key = os_map.get(platform.system(), 'other')
    try:
        url = f'{CLOUD_FUNCTIONS_BASE_URL}/incrementLaunches'
        requests.post(url, json={'os': os_key}, timeout=5)
    except requests.RequestException:
        pass
