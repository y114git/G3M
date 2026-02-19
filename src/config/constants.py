"""
Application-wide constants and configuration values.

This module defines all constant values used throughout the DELTAHUB application,
including version information, network timeouts, game identifiers, UI themes,
and various configuration parameters.
"""
import platform
from .config_loader import get_config_value
LAUNCHER_VERSION = '2.4.7stable'
APP_ID = 'deltahub.y.114'
DATA_FIREBASE_URL = get_config_value('DATA_FIREBASE_URL', '')
CLOUD_FUNCTIONS_BASE_URL = get_config_value('CLOUD_FUNCTIONS_BASE_URL', '')
STEAM_APP_ID_FULL, STEAM_APP_ID_DEMO, STEAM_APP_ID_UNDERTALE, STEAM_APP_ID_PIZZA_TOWER = ('1671210', '1690940', '391540', '2231450')
GAME_PROCESS_NAMES = ['DELTARUNE.exe', 'DELTARUNE', 'UNDERTALE.exe', 'UNDERTALE', 'Undertale Yellow.exe', 'Undertale Yellow', 'PizzaTower.exe', 'PizzaTower', 'SugarySpire_ExhibitionNight.exe', 'SugarySpire_ExhibitionNight', 'runner']
ARCH = platform.machine()
SOCIAL_LINKS = {'telegram': 'https://t.me/y_maintg', 'discord': 'https://discord.gg/T7hyqxmSjf'}
UI_COLORS = {'status_error': 'red', 'status_warning': 'orange', 'status_success': 'green', 'status_info': 'gray', 'status_ready': 'lightgreen', 'status_steam': 'blue', 'link': '#00BFFF', 'social_discord': '#8A2BE2', 'saves_button': 'yellow'}
THEMES = {'default': {'name': 'Deltarune', 'background': 'images/bg_fountain.gif', 'font_family': 'Determination Sans Rus', 'font_size_main': 16, 'font_size_small': 12, 'colors': {'main_fg': '#000000', 'top_level_fg': '#000000', 'button': '#000000', 'button_hover': '#333333', 'button_text': '#FFFFFF', 'border': '#FFFFFF', 'text': '#FFFFFF'}}}
BROWSER_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
NETWORK_TIMEOUT_SHORT = 5
NETWORK_TIMEOUT_MEDIUM = 15
NETWORK_TIMEOUT_LONG = 45
NETWORK_TIMEOUT_HEAD = 15
SPLASH_MIN_DURATION = 10.0
INITIALIZATION_TIMEOUT = 5000
ONLINE_UPDATE_INTERVAL = 60000
LAUNCHER_FALLBACK_TIMEOUT = 8000
SPLASH_WATCHDOG_TIMEOUT = 15000
SPLASH_RETRY_DELAY = 100
IMAGE_CACHE_MAX_SIZE = 100
NETWORK_SEMAPHORE_LIMIT = 4
THREAD_WAIT_TIMEOUT = 2000
DOWNLOAD_CHUNK_SIZE = 262144
MAX_DOWNLOAD_RETRIES = 5
DATA_FILE_EXTENSIONS = ('.xdelta', '.vcdiff', '.win')
GAMEBANANA_API_BASE = 'https://gamebanana.com/apiv11'
GAMEBANANA_GAME_IDS = {'deltarune': 6755, 'undertale': 5506, 'undertaleyellow': 19606, 'pizzatower': 7692, 'sugaryspire': 18218}
GAMEBANANA_TOOL_ID_DELTAMOD = 20575
GAMEBANANA_TOOL_ID_DELTAHUB = 20615
GAMEBANANA_PER_PAGE = 20
GAME_EXECUTABLES = {'deltarune': {'windows': ('DELTARUNE.exe', 'DELTARUNE'), 'linux': ('DELTARUNE', 'DELTARUNE.exe'), 'mac': ('DELTARUNE.app', 'DELTARUNEdemo.app')}, 'undertale': {'windows': ('UNDERTALE.exe', 'UNDERTALE'), 'linux': ('UNDERTALE', 'UNDERTALE.exe'), 'mac': ('UNDERTALE.app',)}, 'undertaleyellow': {'windows': ('Undertale Yellow.exe', 'Undertale Yellow', 'UNDERTALE.exe', 'UNDERTALE'), 'linux': ('Undertale Yellow', 'UNDERTALE', 'Undertale Yellow.exe', 'UNDERTALE.exe'), 'mac': ('UNDERTALE.app',)}, 'pizzatower': {'windows': ('PizzaTower.exe', 'PizzaTower'), 'linux': ('PizzaTower', 'PizzaTower.exe'), 'mac': ('PizzaTower.app',)}, 'sugaryspire': {'windows': ('SugarySpire_ExhibitionNight.exe', 'SugarySpire_ExhibitionNight'), 'linux': ('SugarySpire_ExhibitionNight', 'SugarySpire_ExhibitionNight.exe'), 'mac': ('SugarySpire_ExhibitionNight.app',)}}
MOD_CONFIG_FILENAME = 'mod_config.json'
DATA_WIN_FILENAME = 'data.win'
META_JSON_FILENAME = 'meta.json'
ICON_PNG_FILENAME = 'icon.png'
LEGACY_MOD_CONFIG_FILENAME = 'config.json'
LEGACY_META_JSON_FILENAME = '_deltamodInfo.json'
CACHE_FRESH_TTL = 3600
CACHE_STALE_TTL = 7 * 24 * 3600
CACHE_MAX_ENTRIES = 10000
CACHE_SAVE_DELAY = 5.0
SEARCH_TIMEOUT_SECONDS = 10
MAX_PATCHING_ARCHIVES = 10
MOD_TYPE_G3MPATCH = 'g3mpatch'
MOD_TYPE_XDELTA = 'xdelta'
MOD_TYPE_DATAFILE = 'datafile'
MOD_TYPE_OVERRIDES_ONLY = 'overrides_only'
SINGLE_INSTANCE_KEY = 'deltahub.y.114.single-instance-lock'
