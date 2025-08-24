import platform
import requests

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