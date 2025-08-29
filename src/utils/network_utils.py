import platform
import requests

def check_internet_connection() -> bool:
    try:
        requests.get('https://www.google.com', timeout=5)
        return True
    except requests.RequestException:
        return False