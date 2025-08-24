import os
import sys
import platform
from dotenv import load_dotenv
LAUNCHER_VERSION = '2.0.0pre1'
APP_ID = 'deltahub.y.114'

def _load_config_sources():
    root_env = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
    if os.path.exists(root_env):
        load_dotenv(root_env)
    else:
        load_dotenv()
    try:
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
        else:
            exe_dir = os.path.abspath('.')
        cfg_path = os.path.join(exe_dir, 'config.env')
        if os.path.exists(cfg_path):
            load_dotenv(cfg_path)
    except Exception:
        pass
    try:
        import importlib
        _se = importlib.import_module('secrets_embed')
        for k in ('DATA_FIREBASE_URL', 'CLOUD_FUNCTIONS_BASE_URL', 'INTERNAL_SALT'):
            if not os.getenv(k, '') and hasattr(_se, k):
                os.environ[k] = getattr(_se, k)
    except Exception:
        pass
_load_config_sources()
DATA_FIREBASE_URL = os.getenv('DATA_FIREBASE_URL', '')
CLOUD_FUNCTIONS_BASE_URL = os.getenv('CLOUD_FUNCTIONS_BASE_URL', '')
_FB_ID_TOKEN = None
_FB_TOKEN_EXPIRES_AT = 0.0

def get_firebase_id_token() -> str:
    return ''
STEAM_APP_ID_FULL, STEAM_APP_ID_DEMO, STEAM_APP_ID_UNDERTALE = ('1671210', '1690940', '391540')
GAME_PROCESS_NAMES = ['DELTARUNE.exe', 'DELTARUNE', 'UNDERTALE.exe', 'UNDERTALE', 'runner']
SAVE_SLOT_FINISH_MAP = {0: 3, 1: 4, 2: 5}
ARCH = platform.machine()
DEFAULT_FONT_FALLBACK_CHAIN = ['Determination Sans Rus', 'DejaVu Sans', 'Noto Sans', 'Liberation Sans', 'Arial', 'Noto Color Emoji', 'Segoe UI Emoji', 'Apple Color Emoji']
SOCIAL_LINKS = {'telegram': 'https://t.me/y_maintg', 'discord': 'https://discord.gg/gg4EvZpWKd'}
UI_COLORS = {'status_error': 'red', 'status_warning': 'orange', 'status_success': 'green', 'status_info': 'gray', 'status_ready': 'lightgreen', 'status_steam': 'blue', 'link': '#00BFFF', 'social_discord': '#8A2BE2', 'saves_button': 'yellow'}
THEMES = {'default': {'name': 'Deltarune', 'background': 'images/bg_fountain.gif', 'font_family': 'Determination Sans Rus', 'font_size_main': 16, 'font_size_small': 12, 'colors': {'main_fg': '#000000', 'top_level_fg': '#000000', 'button': '#000000', 'button_hover': '#333333', 'button_text': '#FFFFFF', 'border': '#FFFFFF', 'text': '#FFFFFF'}}}
BROWSER_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

def resource_path(relative_path: str) -> str:
    if getattr(sys, 'frozen', False):
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)