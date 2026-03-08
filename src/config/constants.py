"""
Application-wide constants and configuration values.

This module is the central source of immutable project configuration shared across
the DELTAHUB application.
"""
import platform
import re
from .config_loader import get_config_value

"""Application identity and external service configuration."""
LAUNCHER_VERSION = '2.4.7stable'
APP_ID = 'deltahub.y.114'
SINGLE_INSTANCE_KEY = 'deltahub.y.114.single-instance-lock'
DATA_FIREBASE_URL = get_config_value('DATA_FIREBASE_URL', '')
CLOUD_FUNCTIONS_BASE_URL = get_config_value('CLOUD_FUNCTIONS_BASE_URL', '')
SOCIAL_LINKS = {
    'telegram': 'https://t.me/y_maintg',
    'discord': 'https://discord.gg/T7hyqxmSjf',
}
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

"""Platform and game runtime configuration."""
CURRENT_PLATFORM = platform.system()
IS_WINDOWS_PLATFORM = CURRENT_PLATFORM == 'Windows'
ARCH = platform.machine()
STEAM_APP_ID_FULL = '1671210'
STEAM_APP_ID_DEMO = '1690940'
STEAM_APP_ID_UNDERTALE = '391540'
STEAM_APP_ID_PIZZA_TOWER = '2231450'
GAME_PROCESS_NAMES = [
    'DELTARUNE.exe', 'DELTARUNE', 'UNDERTALE.exe', 'UNDERTALE',
    'Undertale Yellow.exe', 'Undertale Yellow', 'PizzaTower.exe', 'PizzaTower',
    'SugarySpire_ExhibitionNight.exe', 'SugarySpire_ExhibitionNight', 'runner',
]
GAME_EXECUTABLES = {
    'deltarune': {
        'windows': ('DELTARUNE.exe', 'DELTARUNE'),
        'linux': ('DELTARUNE', 'DELTARUNE.exe'),
        'mac': ('DELTARUNE.app', 'DELTARUNEdemo.app'),
    },
    'undertale': {
        'windows': ('UNDERTALE.exe', 'UNDERTALE'),
        'linux': ('UNDERTALE', 'UNDERTALE.exe'),
        'mac': ('UNDERTALE.app',),
    },
    'undertaleyellow': {
        'windows': ('Undertale Yellow.exe', 'Undertale Yellow', 'UNDERTALE.exe', 'UNDERTALE'),
        'linux': ('Undertale Yellow', 'UNDERTALE', 'Undertale Yellow.exe', 'UNDERTALE.exe'),
        'mac': ('UNDERTALE.app',),
    },
    'pizzatower': {
        'windows': ('PizzaTower.exe', 'PizzaTower'),
        'linux': ('PizzaTower', 'PizzaTower.exe'),
        'mac': ('PizzaTower.app',),
    },
    'sugaryspire': {
        'windows': ('SugarySpire_ExhibitionNight.exe', 'SugarySpire_ExhibitionNight'),
        'linux': ('SugarySpire_ExhibitionNight', 'SugarySpire_ExhibitionNight.exe'),
        'mac': ('SugarySpire_ExhibitionNight.app',),
    },
}

"""Theme, style, and shared UI configuration."""
UI_COLORS = {
    'status_error': 'red',
    'status_warning': 'orange',
    'status_success': 'green',
    'status_info': 'gray',
    'status_ready': 'lightgreen',
    'status_steam': 'blue',
    'link': '#00BFFF',
    'social_discord': '#8A2BE2',
    'saves_button': 'yellow',
}
THEMES = {
    'default': {
        'name': 'G3M',
        'background': 'images/background.png',
        'font_family': 'Determination Sans Rus',
        'font_size_main': 16,
        'font_size_small': 12,
        'colors': {
            'main_fg': '#282828',
            'top_level_fg': '#282828',
            'button': '#222222',
            'button_hover': '#616b78',
            'button_text': '#e8e9eb',
            'border': '#039d5b',
            'text': '#e8e9eb',
            'secondary_text': '#6de985',
        },
    }
}
SETTINGS_COLOR_CONFIG = {
    'background': 'ui.background_color',
    'button': 'ui.elements_color',
    'border': 'ui.border_color',
    'button_hover': 'ui.hover_color',
    'text': 'ui.main_text_color',
    'secondary_text': 'ui.secondary_text_color',
}
BASE_TAG_NAMES = ('textedit', 'customization', 'gameplay', 'other')
SEARCH_GAME_OPTIONS = (
    ('deltarune', 'deltarune'),
    ('undertale', 'undertale'),
    ('undertaleyellow', 'undertaleyellow'),
    ('pizzatower', 'pizzatower'),
    ('sugaryspire', 'sugaryspire'),
)
LIBRARY_GAME_OPTIONS = (*SEARCH_GAME_OPTIONS[:1], ('deltarunedemo', 'deltarunedemo'), *SEARCH_GAME_OPTIONS[1:])
LIBRARY_IMPORT_ARCHIVE_EXTENSIONS = ('.zip', '.7z', '.rar', '.tar.gz', '.lzma', '.gz')
PLUGIN_STATUS_STYLES = {
    'enabled': ('#4CAF50', 'plugins.status_enabled'),
    'disabled': ('#FFA500', 'plugins.status_disabled'),
}
CHAT_MESSAGE_BACKGROUND_COLOR = 'rgba(255, 255, 255, 0.1)'
RICH_HTML_IMAGE_CACHE_MAX_SIZE = 128
STYLES_TEMPLATE_SUBDIR = 'config/styles'
MOD_WIDGET_STYLE_TEMPLATE = '''QFrame#{frame_selector} {{
    background-color: {bg_color};
    border: {border_width} solid {border_color};
    border-radius: {frame_border_radius};
}}
QFrame#{frame_selector}:hover {{
    border-color: {hover_border_color};
}}
QLabel#{icon_selector} {{
    border: 2px solid {border_color};
    border-radius: {icon_border_radius};
}}
QLabel#versionLabel {{
    color: {secondary_text_color};
}}
QLabel#secondaryText {{
    color: {secondary_text_color};
    font-size: {secondary_font_size}px;
}}
QLabel#primaryText {{
    color: {text_color};
    font-size: {primary_font_size}px;
}}
QPushButton#cardButton, QPushButton#cardButtonInstall, QPushButton#cardButtonUninstall {{
    min-width: {button_width}px;
    max-width: {button_width}px;
    min-height: {button_height}px;
    max-height: {button_height}px;
    font-size: {button_font_size}px;
    padding: 1px;
    border-radius: {button_border_radius};
}}
QPushButton#cardButtonInstall {{
    background-color: #4CAF50;
    font-weight: bold;
}}
QPushButton#cardButtonInstall:hover {{
    background-color: #5cb85c;
}}
QPushButton#cardButtonUninstall {{
    background-color: #F44336;
    font-weight: bold;
}}
QPushButton#cardButtonUninstall:hover {{
    background-color: #d32f2f;
}}'''
EMPTY_LAYOUT_MESSAGE_STYLE = 'QLabel {{\n    color: {color};\n    font-size: {font_size}px;\n    font-style: italic;\n    opacity: 0.75;\n    background-color: transparent;\n    padding: 40px;\n}}'
ARROW_DOWN_SVG_TEMPLATE = '<?xml version="1.0" encoding="utf-8"?>\n<svg fill="{color}" width="800px" height="800px" viewBox="-6.5 0 32 32" version="1.1" xmlns="http://www.w3.org/2000/svg">\n<path d="M18.813 11.406l-7.906 9.906c-0.75 0.906-1.906 0.906-2.625 0l-7.906-9.906c-0.75-0.938-0.375-1.656 0.781-1.656h16.875c1.188 0 1.531 0.719 0.781 1.656z"></path>\n</svg>'
ARROW_UP_SVG_TEMPLATE = '<?xml version="1.0" encoding="utf-8"?>\n<svg fill="{color}" width="800px" height="800px" viewBox="-6.5 0 32 32" version="1.1" xmlns="http://www.w3.org/2000/svg">\n<g transform="translate(0,32) scale(1,-1)"><path d="M18.813 11.406l-7.906 9.906c-0.75 0.906-1.906 0.906-2.625 0l-7.906-9.906c-0.75-0.938-0.375-1.656 0.781-1.656h16.875c1.188 0 1.531 0.719 0.781 1.656z"></path></g>\n</svg>'
RICH_HTML_CSS_CLASS_MAP = {
    'RedColor': 'color:#ff4444;',
    'BlueColor': 'color:#5599ff;',
    'GreenColor': 'color:#44ff44;',
    'YellowColor': 'color:#ffdd44;',
    'WhiteColor': 'color:#ffffff;',
    'SelectedElement': '',
}
RICH_HTML_IMG_RE = re.compile(r'<img\b([^>]*)/?>', re.IGNORECASE | re.DOTALL)
RICH_HTML_ATTR_RE = re.compile(r'(\w[\w-]*)=["\']([^"\']*)["\']')
RICH_HTML_CLASS_RE = re.compile(r'<(\w+)\b([^>]*?)\bclass=["\']([^"\']*)["\']([^>]*)>', re.IGNORECASE)
RICH_HTML_FONT_COLOR_RE = re.compile(r'<font\b([^>]*?)\bcolor=["\']([^"\']*)["\']([^>]*)>(.*?)</font>', re.IGNORECASE | re.DOTALL)

"""Localization mapping constants."""
WIDGET_LOCALIZATIONS = [
    ('online_label', 'setToolTip', 'tooltips.online_counter'),
    ('telegram_button', 'setText', 'buttons.telegram'),
    ('beta_updates_checkbox', 'setToolTip', 'tooltips.beta_updates'),
    ('discord_button', 'setText', 'buttons.discord'),
    ('chat_button', 'setText', 'ui.chat_button'),
    ('shortcut_button', 'setText', 'buttons.shortcut'),
    ('tags_label', 'setText', 'ui.tags_label'),
    ('show_nsfw_checkbox', 'setText', 'ui.show_nsfw'),
    ('tag_textedit', 'setText', 'tags.textedit'),
    ('tag_customization', 'setText', 'tags.customization'),
    ('tag_gameplay', 'setText', 'tags.gameplay'),
    ('tag_other', 'setText', 'tags.other'),
    ('search_button', 'setToolTip', 'ui.search_placeholder'),
    ('prev_page_btn', 'setText', 'ui.prev_page'),
    ('next_page_btn', 'setText', 'ui.next_page'),
    ('chapter_mode_checkbox', 'setText', 'ui.chapter_mode'),
    ('full_install_checkbox', 'setText', 'ui.full_install'),
    ('language_label', 'setText', 'ui.language_label'),
    ('beta_updates_checkbox', 'setText', 'ui.beta_updates'),
    ('skip_patching_warnings_checkbox', 'setText', 'ui.skip_patching_warnings'),
    ('skip_patching_warnings_checkbox', 'setToolTip', 'tooltips.skip_patching_warnings'),
    ('fullscreen_checkbox', 'setText', 'ui.fullscreen'),
    ('fullscreen_checkbox', 'setToolTip', 'tooltips.fullscreen_tooltip'),
    ('ui_scale_label', 'setText', 'ui.scale_label'),
    ('border_radius_label', 'setText', 'ui.border_radius_label'),
    ('launch_via_steam_checkbox', 'setText', 'ui.steam_launch'),
    ('dont_hide_window_checkbox', 'setText', 'ui.dont_hide_window_on_launch'),
    ('dont_hide_window_checkbox', 'setToolTip', 'tooltips.dont_hide_window_on_launch'),
    ('hide_wips_without_downloads_checkbox', 'setText', 'ui.hide_wips_without_downloads'),
    ('reset_button', 'setText', 'buttons.reset_settings'),
    ('settings_custom_executable_button', 'setText', 'buttons.custom_executable'),
    ('settings_custom_executable_button', 'setToolTip', 'tooltips.custom_executable_library'),
    ('settings_reset_custom_exe_button', 'setToolTip', 'buttons.reset_settings'),
    ('settings_game_selector_label', 'setText', 'ui.mod_type_label'),
    ('theme_apply_btn', 'setToolTip', 'ui.apply_theme'),
    ('theme_save_btn', 'setToolTip', 'buttons.save_theme'),
    ('theme_delete_btn', 'setToolTip', 'buttons.delete_theme'),
    ('hide_library_filters_checkbox', 'setText', 'ui.hide_library_filters'),
    ('hide_library_filters_checkbox', 'setToolTip', 'tooltips.hide_library_filters'),
    ('disable_animations_checkbox', 'setText', 'checkboxes.disable_animations'),
    ('disable_background_checkbox', 'setText', 'checkboxes.disable_background'),
    ('disable_splash_checkbox', 'setText', 'checkboxes.disable_splash'),
    ('mods_per_page_label', 'setText', 'ui.mods_per_page_label'),
    ('mods_per_page_spinbox', 'setToolTip', 'ui.mods_per_page_tooltip'),
    ('gb_sort_label', 'setText', 'ui.gamebanana_sort_label'),
    ('auto_sorting_checkbox', 'setText', 'ui.auto_sorting'),
    ('auto_sorting_checkbox', 'setToolTip', 'ui.auto_sorting_tooltip'),
    ('blocklist_button', 'setText', 'ui.blocklist'),
    ('blocklist_button', 'setToolTip', 'ui.blocklist_tooltip'),
    ('priority_button', 'setText', 'ui.priority'),
    ('create_modpack_button', 'setText', 'ui.create_modpack_button'),
    ('library_tags_label', 'setText', 'ui.tags_label'),
    ('library_tag_textedit', 'setText', 'tags.textedit'),
    ('library_tag_customization', 'setText', 'tags.customization'),
    ('library_tag_gameplay', 'setText', 'tags.gameplay'),
    ('library_tag_other', 'setText', 'tags.other'),
    ('library_tag_gamebanana', 'setText', 'ui.only_gamebanana'),
    ('library_search_button', 'setToolTip', 'ui.search_placeholder'),
    ('installed_mods_label', 'setText', 'ui.installed_mods_label'),
    ('import_export_button', 'setText', 'ui.import_export_mod'),
    ('theme_button', 'setText', 'buttons.import_export_themes'),
    ('do_not_save_theme_checkbox', 'setText', 'ui.do_not_save_theme_after_import'),
    ('hide_mods_browser_tab_checkbox', 'setText', 'ui.hide_mods_browser_tab'),
    ('hide_library_tab_checkbox', 'setText', 'ui.hide_library_tab'),
    ('hide_plugins_tab_checkbox', 'setText', 'ui.hide_plugins_tab'),
    ('merge_properties_checkbox', 'setText', 'checkboxes.merge_properties'),
    ('merge_code_checkbox', 'setText', 'checkboxes.merge_code'),
    ('merge_properties_checkbox', 'setToolTip', 'tooltips.merge_properties'),
    ('merge_code_checkbox', 'setToolTip', 'tooltips.merge_code'),
    ('clear_cache_button', 'setText', 'ui.clear_cache_button'),
    ('clear_cache_button', 'setToolTip', 'tooltips.clear_cache_button'),
]
PLUGIN_WIDGET_LOCALIZATIONS = [
    ('plugins_search_button', 'setText', 'plugins.search_plugins'),
    ('plugins_import_button', 'setText', 'plugins.import_plugins'),
]
COMBO_LOCALIZATIONS = {
    'sort_combo': ['ui.sort_by_downloads', 'ui.sort_by_update_date', 'ui.sort_by_creation_date'],
    'modgame_combo': ['ui.deltarune', 'ui.undertale', 'ui.undertaleyellow', 'ui.pizzatower', 'ui.sugaryspire'],
    'library_sort_combo': ['ui.sort_by_name', 'ui.sort_by_date'],
    'game_type_combo': ['ui.deltarune', 'ui.deltarunedemo', 'ui.undertale', 'ui.undertaleyellow', 'ui.pizzatower', 'ui.sugaryspire'],
    'settings_game_combo': ['ui.deltarune', 'ui.deltarunedemo', 'ui.undertale', 'ui.undertaleyellow', 'ui.pizzatower', 'ui.sugaryspire'],
}

"""Network, background work, and timing limits."""
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
SEARCH_TIMEOUT_SECONDS = 10
ASYNC_METADATA_MIN_REQUEST_INTERVAL = 0.2
SEARCH_EXHAUSTED_PAGE_SENTINEL = 100

"""GameBanana integration constants."""
GAMEBANANA_API_BASE = 'https://gamebanana.com/apiv11'
GAMEBANANA_GAME_IDS = {
    'deltarune': 6755,
    'undertale': 5506,
    'undertaleyellow': 19606,
    'pizzatower': 7692,
    'sugaryspire': 18218,
}
GAMEBANANA_TOOL_ID_DELTAMOD = 20575
GAMEBANANA_TOOL_ID_DELTAHUB = 20615
GAMEBANANA_PER_PAGE = 20

"""Mod file, archive, cache, and content metadata constants."""
DATA_FILE_EXTENSIONS = ('.xdelta', '.vcdiff', '.win', '.unx', '.ios', '.droid')
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
MAX_PATCHING_ARCHIVES = 10
MOD_TYPE_G3MPATCH = 'g3mpatch'
MOD_TYPE_XDELTA = 'xdelta'
MOD_TYPE_DATAFILE = 'datafile'
MOD_TYPE_OVERRIDES_ONLY = 'overrides_only'
MOD_FILTER_TRUE_VALUES = (True, 'true', 'True', 1)
MOD_FILTER_NSFW_TEXT_MARKERS = ('nsfw', 'adult', '18+', '18plus', 'explicit', 'mature')

"""Patching system constants."""
EXPORT_SCRIPT_CONFIGS = [
    ('ExportSprites', 'Sprites'), ('ExportBackgrounds', 'Backgrounds'),
    ('ExportShaders', 'Shaders'), ('ExportFonts', 'Fonts'),
    ('ExportSounds', 'Sounds'), ('ExportCodeEntries', 'CodeEntries'),
    ('ExportTilesets', 'Tilesets'), ('ExportRooms', 'Rooms'),
    ('ExportGameObjects', 'GameObjects'), ('ExportPaths', 'Paths'),
    ('ExportTimelines', 'Timelines'), ('ExportAudioGroups', 'AudioGroups'),
    ('ExportTextureGroupInfo', 'TextureGroups'), ('ExportExtensions', 'Extensions'),
    ('ExportGeneralInfo', 'GeneralInfo'),
]
IMPORT_SCRIPT_CONFIGS = [
    ('ImportGeneralInfo', 'GeneralInfo'), ('ImportAudioGroups', 'AudioGroups'),
    ('ImportTextureGroupInfo', 'TextureGroups'), ('ImportSprites', 'Sprites'),
    ('ImportBackgrounds', 'Backgrounds'), ('ImportFonts', 'Fonts'),
    ('ImportSounds', 'Sounds'), ('ImportPaths', 'Paths'),
    ('ImportTilesets', 'Tilesets'), ('ImportShaders', 'Shaders'),
    ('ImportTimelines', 'Timelines'), ('ImportGameObjects', 'GameObjects'),
    ('ImportRooms', 'Rooms'), ('ImportCodeEntries', 'CodeEntries'),
    ('ImportExtensions', 'Extensions'),
]
SCRIPT_TYPES = [
    'Sprites', 'Sounds', 'CodeEntries', 'Fonts', 'Shaders', 'Backgrounds',
    'Tilesets', 'Rooms', 'GameObjects', 'Paths', 'Timelines', 'AudioGroups',
    'TextureGroupInfo', 'Extensions', 'GeneralInfo',
]
ASSET_TRACKING_CONFIGS = [
    ('CodeEntries', '.gml', 'code_files', False),
    ('Sprites', None, 'sprites', True),
    ('Backgrounds', '.png', 'backgrounds', False),
    ('Tilesets', '.json', 'tilesets', False),
    ('Shaders', None, 'shaders', True),
]
PATCH_SUBDIRS = [
    ('Sprites', 'sprite', True),
    ('Backgrounds', 'background', False),
    ('Tilesets', 'tileset', False),
    ('Shaders', 'shader', False),
    ('Fonts', 'font', False),
    ('Sounds', 'sound', False),
    ('Rooms', 'room', True),
]
XDELTA_ERROR_MAP = {
    'checksum': ('xdelta_checksum_mismatch', 'dialogs.patching_warning.xdelta_checksum_mismatch', 'errors.xdelta_patch_checksum_mismatch', True),
    'not_found': (None, None, 'errors.xdelta_patch_file_not_found', False),
    'permission': (None, None, 'errors.xdelta_patch_permission_denied', False),
    'corrupted': ('xdelta_patch_corrupted', 'dialogs.patching_warning.xdelta_patch_failed', 'errors.xdelta_patch_corrupted', True),
    'io': (None, None, 'errors.xdelta_patch_io_error', False),
    'unknown': ('xdelta_patch_failed', 'dialogs.patching_warning.xdelta_patch_failed', 'errors.xdelta_patch_unknown_error', True),
}
XDELTA_EXCEPTION_ERROR_KEYS = {
    'permission': 'errors.xdelta_patch_permission_denied',
    'not_found': 'errors.xdelta_patch_file_not_found',
    'io': 'errors.xdelta_patch_io_error',
}
COMPILATION_ERROR_PATTERNS = [
    ('variable\\s+name\\s+[\\\'\"]?(\\w+)[\\\'\"]?\\s+index\\s+\\([^)]+\\)\\s+not\\s+set\\s+before\\s+reading', 'variable_not_set'),
    ('global\\s+variable\\s+name\\s+[\\\'\"]?(\\w+)[\\\'\"]?\\s+index\\s+\\([^)]+\\)\\s+not\\s+set', 'global_variable_not_set'),
    ('ERROR\\s+in\\s+action\\s+number\\s+\\d+\\s+of\\s+(\\w+)\\s+Event\\d+\\s+for\\s+object\\s+(\\w+):', 'runtime_error'),
    ('undefined\\s+variable\\s+[\\\'\"]?(\\w+)[\\\'\"]?', 'undefined_variable'),
    ('compilation\\s+error', 'compilation_error'),
    ('compilation\\s+failed', 'compilation_failed'),
    ('failed\\s+to\\s+compile', 'compilation_failed'),
    ('variable\\s+[\\\'\"]?(\\w+)[\\\'\"]?\\s+is\\s+not\\s+defined', 'variable_not_defined'),
]
SKIP_FILES = ('config.json', 'mod_config.json', '_icon.png', 'icon.png', 'meta.json', '_deltamodinfo.json')
ARCHIVE_EXTENSIONS = ('.zip', '.7z', '.rar', '.tar.gz', '.lzma')
