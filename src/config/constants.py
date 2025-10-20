import platform
from .loader import get_config_value
LAUNCHER_VERSION = '2.1.3stable'
APP_ID = 'deltahub.y.114'
DATA_FIREBASE_URL = get_config_value('DATA_FIREBASE_URL', '')
CLOUD_FUNCTIONS_BASE_URL = get_config_value('CLOUD_FUNCTIONS_BASE_URL', '')
STEAM_APP_ID_FULL, STEAM_APP_ID_DEMO, STEAM_APP_ID_UNDERTALE = ('1671210', '1690940', '391540')
GAME_PROCESS_NAMES = ['DELTARUNE.exe', 'DELTARUNE', 'UNDERTALE.exe', 'UNDERTALE', 'runner']
SAVE_SLOT_FINISH_MAP = {0: 3, 1: 4, 2: 5}
ARCH = platform.machine()
SOCIAL_LINKS = {'telegram': 'https://t.me/y_maintg', 'discord': 'https://discord.gg/gg4EvZpWKd'}
UI_COLORS = {'status_error': 'red', 'status_warning': 'orange', 'status_success': 'green', 'status_info': 'gray', 'status_ready': 'lightgreen', 'status_steam': 'blue', 'link': '#00BFFF', 'social_discord': '#8A2BE2', 'saves_button': 'yellow'}
THEMES = {'default': {'name': 'Deltarune', 'background': 'images/bg_fountain.gif', 'font_family': 'Determination Sans Rus', 'font_size_main': 16, 'font_size_small': 12, 'colors': {'main_fg': '#000000', 'top_level_fg': '#000000', 'button': '#000000', 'button_hover': '#333333', 'button_text': '#FFFFFF', 'border': '#FFFFFF', 'text': '#FFFFFF'}}}
BROWSER_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
