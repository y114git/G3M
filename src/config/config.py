"""Application-wide constants and configuration values.

Single source of truth for all immutable project configuration shared across G3M.
"""

import os
import platform
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import styles as shared_styles

_dotenv_path = Path(__file__).resolve().parents[1] / ".env"
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _dotenv_path = Path(sys._MEIPASS) / "src" / ".env"

if _dotenv_path.is_file():
    load_dotenv(dotenv_path=_dotenv_path)

"""Application identity and external service configuration."""
APP_VERSION = "3.0.3stable"
APP_DISPLAY_NAME = "G3M"
APP_ORGANIZATION_NAME = "g3m"
APP_DATA_DIR_NAME = "G3M"
LEGACY_APP_DATA_DIR_NAME = "DELTAHUB"
PRIMARY_URL_SCHEME = "g3m"
LEGACY_URL_SCHEME = "deltahub"
URL_PROTOCOL_SCHEMES = (PRIMARY_URL_SCHEME, LEGACY_URL_SCHEME)
URL_PROTOCOL_PREFIXES = tuple(f"{scheme}://" for scheme in URL_PROTOCOL_SCHEMES)
URL_PROTOCOL_MIME_TYPES = tuple(
    f"x-scheme-handler/{scheme}" for scheme in URL_PROTOCOL_SCHEMES
)
URL_PROTOCOL_DESKTOP_ENTRY_NAME = f"{APP_DISPLAY_NAME} Launcher"
URL_PROTOCOL_DESKTOP_FILENAME = "g3m.desktop"
LOG_ARCHIVE_DIR_NAME = "g3m"
LOG_ARCHIVE_FILE_PREFIX = "g3m"
SINGLE_INSTANCE_KEY = "g3m.single-instance-lock"
CLOUD_FUNCTIONS_BASE_URL = os.getenv("CLOUD_FUNCTIONS_BASE_URL", "")
SOCIAL_LINKS = {
    "telegram": "https://t.me/y_maintg",
    "discord": "https://discord.gg/2MFdvFfD9a",
}
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

"""Platform and game runtime configuration."""
CURRENT_PLATFORM = platform.system()
IS_WINDOWS_PLATFORM = CURRENT_PLATFORM == "Windows"
ARCH = platform.machine()
STEAM_APP_ID_FULL = "1671210"
STEAM_APP_ID_DEMO = "1690940"
STEAM_APP_ID_UNDERTALE = "391540"
STEAM_APP_ID_PIZZA_TOWER = "2231450"

"""Plugin and profile runtime configuration."""
PLUGIN_API_VERSION = "1.0.0"
PLUGIN_CATALOG_URL = (
    "https://raw.githubusercontent.com/y114git/G3M/stable/catalog/plugins/plugins.json"
)
PLUGIN_HOOKS = {
    "app_ready",
    "app_shutdown",
    "before_mod_apply",
    "after_mod_apply_before_launch",
    "mod_apply_cancelled",
    "after_game_started",
    "before_restore_after_exit",
    "after_restore_after_exit",
    "language_changed",
    "theme_changed",
    "profile_changed",
    "settings_view",
    "main_view",
    "navigation_actions",
    "game_registry",
    "background_task",
}
PLUGIN_TAGS = {
    "interface",
    "game_experience",
    "tool",
    "other",
}
DEFAULT_PROFILE = "Default"
UNNAMED_PROFILE = "Unnamed"
PROFILE_STATIC_KEYS = frozenset(
    {
        "selected_game_type",
        "chapter_mode_enabled",
        "full_install_enabled",
        "direct_launch_chapter",
    }
)

"""Shared UI filter and style-adjacent configuration."""
UI_COLORS = shared_styles.UI_COLORS
DEFAULT_THEME = shared_styles.DEFAULT_THEME
DEFAULT_COLORS = shared_styles.DEFAULT_COLORS
FALLBACK_FRAME_BG = shared_styles.FALLBACK_FRAME_BG
FALLBACK_TOOLTIP_BG = shared_styles.FALLBACK_TOOLTIP_BG
FALLBACK_WINDOW_BG = shared_styles.FALLBACK_WINDOW_BG
FALLBACK_SCROLL_GROOVE = shared_styles.FALLBACK_SCROLL_GROOVE
SETTINGS_COLOR_CONFIG = shared_styles.SETTINGS_COLOR_CONFIG
CHAT_MESSAGE_BACKGROUND_COLOR = shared_styles.CHAT_MESSAGE_BACKGROUND_COLOR
RICH_HTML_IMAGE_CACHE_MAX_SIZE = shared_styles.RICH_HTML_IMAGE_CACHE_MAX_SIZE
STYLES_TEMPLATE_SUBDIR = shared_styles.STYLES_TEMPLATE_SUBDIR
QSS_TRANSPARENT_SCROLL = shared_styles.QSS_TRANSPARENT_SCROLL
QSS_TRANSPARENT_BG = shared_styles.QSS_TRANSPARENT_BG
QSS_BOLD_LABEL = shared_styles.QSS_BOLD_LABEL
QSS_BOLD_TRANSPARENT = shared_styles.QSS_BOLD_TRANSPARENT
QSS_TRANSPARENT_NOPAD = shared_styles.QSS_TRANSPARENT_NOPAD
QSS_PADDING_LEFT_8 = shared_styles.QSS_PADDING_LEFT_8
QSS_PADDING_LEFT_5 = shared_styles.QSS_PADDING_LEFT_5
QSS_ARROW_LABEL = shared_styles.QSS_ARROW_LABEL
QSS_LOADING_LABEL = shared_styles.QSS_LOADING_LABEL
QSS_TAB_ALIGNMENT = shared_styles.QSS_TAB_ALIGNMENT
QSS_SETTINGS_TAB_ALIGNMENT = shared_styles.QSS_SETTINGS_TAB_ALIGNMENT
MOD_WIDGET_STYLE_TEMPLATE = shared_styles.MOD_WIDGET_STYLE_TEMPLATE
EMPTY_LAYOUT_MESSAGE_STYLE = shared_styles.EMPTY_LAYOUT_MESSAGE_STYLE
ARROW_DOWN_SVG_TEMPLATE = shared_styles.ARROW_DOWN_SVG_TEMPLATE
ARROW_UP_SVG_TEMPLATE = shared_styles.ARROW_UP_SVG_TEMPLATE
RICH_HTML_CSS_CLASS_MAP = shared_styles.RICH_HTML_CSS_CLASS_MAP
BASE_TAG_NAMES = ("textedit", "customization", "gameplay", "other")
CYOP_AFOM_TAG = "CYOP/AFOM"
LIBRARY_IMPORT_ARCHIVE_EXTENSIONS = (".zip", ".7z", ".rar", ".tar.gz", ".lzma", ".gz")
MOD_README_EXTENSIONS = (".md", ".txt")
MOD_README_ENCODINGS = ("utf-8-sig", "utf-16", "cp1251", "latin-1")
MOD_ROOT_DOC_EXTENSIONS = (".md", ".markdown", ".txt")
RICH_HTML_IMG_RE = re.compile(r"<img\b([^>]*)/?>", re.IGNORECASE | re.DOTALL)
RICH_HTML_ATTR_RE = re.compile(r'(\w[\w-]*)=["\']([^"\']*)["\']')
RICH_HTML_CLASS_RE = re.compile(
    r'<(\w+)\b([^>]*?)\bclass=["\']([^"\']*)["\']([^>]*)>', re.IGNORECASE
)
RICH_HTML_FONT_COLOR_RE = re.compile(
    r'<font\b([^>]*?)\bcolor=["\']([^"\']*)["\']([^>]*)>(.*?)</font>',
    re.IGNORECASE | re.DOTALL,
)

"""Localization mapping constants."""
WIDGET_LOCALIZATIONS = [
    ("online_label", "setToolTip", "tooltips.online_counter"),
    ("telegram_button", "setToolTip", "buttons.telegram"),
    ("beta_updates_checkbox", "setToolTip", "tooltips.beta_updates"),
    ("discord_button", "setToolTip", "buttons.discord"),
    ("chat_button", "setText", "ui.chat_button"),
    ("shortcut_button", "setText", "buttons.shortcut"),
    ("tags_label", "setText", "ui.tags_label"),
    ("tags_label", "setToolTip", "tooltips.filter_by_tag"),
    ("show_nsfw_checkbox", "setText", "ui.show_nsfw"),
    ("show_nsfw_checkbox", "setToolTip", "tooltips.show_nsfw"),
    ("tag_textedit", "setText", "tags.textedit"),
    ("tag_customization", "setText", "tags.customization"),
    ("tag_gameplay", "setText", "tags.gameplay"),
    ("tag_other", "setText", "tags.other"),
    ("search_button", "setToolTip", "ui.search_placeholder"),
    ("sort_combo", "setToolTip", "tooltips.sort_mode"),
    ("modgame_combo", "setToolTip", "tooltips.select_game"),
    ("chapter_mode_checkbox", "setText", "ui.chapter_mode"),
    ("chapter_mode_checkbox", "setToolTip", "tooltips.chapter_mode"),
    ("full_install_checkbox", "setText", "ui.full_install"),
    ("full_install_checkbox", "setToolTip", "tooltips.full_install_toggle"),
    ("language_label", "setText", "ui.language_label"),
    ("language_combo", "setToolTip", "tooltips.language"),
    ("beta_updates_checkbox", "setText", "ui.beta_updates"),
    ("show_reset_buttons_checkbox", "setText", "ui.show_reset_buttons"),
    ("analytics_opt_in_checkbox", "setText", "ui.analytics_opt_in"),
    ("analytics_opt_in_checkbox", "setToolTip", "tooltips.analytics_opt_in"),
    ("skip_patching_warnings_checkbox", "setText", "ui.skip_patching_warnings"),
    ("fullscreen_checkbox", "setText", "ui.fullscreen"),
    ("fullscreen_checkbox", "setToolTip", "tooltips.fullscreen_tooltip"),
    ("ui_scale_label", "setText", "ui.scale_label"),
    ("ui_scale_spinbox", "setToolTip", "tooltips.ui_scale"),
    ("border_radius_label", "setText", "ui.border_radius_label"),
    ("launch_via_steam_checkbox", "setText", "ui.steam_launch"),
    ("dont_hide_window_checkbox", "setText", "ui.dont_hide_window_on_launch"),
    ("dont_hide_window_checkbox", "setToolTip", "tooltips.dont_hide_window_on_launch"),
    ("reset_button", "setText", "buttons.reset_settings"),
    ("settings_custom_executable_button", "setText", "buttons.custom_executable"),
    (
        "settings_custom_executable_button",
        "setToolTip",
        "tooltips.custom_executable_library",
    ),
    ("settings_reset_custom_exe_button", "setToolTip", "buttons.reset_settings"),
    ("settings_game_selector_label", "setText", "ui.mod_type_label"),
    ("theme_apply_btn", "setToolTip", "ui.apply_theme"),
    ("theme_save_btn", "setToolTip", "buttons.save_theme"),
    ("theme_delete_btn", "setToolTip", "buttons.delete_theme"),
    ("hide_library_filters_checkbox", "setText", "ui.hide_library_filters"),
    ("hide_library_filters_checkbox", "setToolTip", "tooltips.hide_library_filters"),
    ("disable_animations_checkbox", "setText", "checkboxes.disable_animations"),
    ("disable_background_checkbox", "setText", "checkboxes.disable_background"),
    (
        "disable_startup_sound_checkbox",
        "setText",
        "checkboxes.disable_startup_sound",
    ),
    (
        "pause_background_music_unfocused_checkbox",
        "setText",
        "checkboxes.pause_background_music_unfocused",
    ),
    (
        "pause_background_music_unfocused_checkbox",
        "setToolTip",
        "tooltips.pause_background_music_unfocused",
    ),
    ("blocklist_button", "setToolTip", "ui.blocklist_tooltip"),
    ("priority_button", "setText", "ui.priority"),
    ("priority_button", "setToolTip", "tooltips.mod_priority"),
    ("create_modpack_button", "setText", "ui.create_modpack_button"),
    ("create_modpack_button", "setToolTip", "tooltips.create_modpack"),
    ("library_tags_label", "setText", "ui.tags_label"),
    ("library_tags_label", "setToolTip", "tooltips.filter_by_tag"),
    ("library_tag_textedit", "setText", "tags.textedit"),
    ("library_tag_customization", "setText", "tags.customization"),
    ("library_tag_gameplay", "setText", "tags.gameplay"),
    ("library_tag_other", "setText", "tags.other"),
    ("library_tag_gamebanana", "setText", "ui.only_gamebanana"),
    ("library_search_button", "setToolTip", "ui.search_placeholder"),
    ("library_sort_combo", "setToolTip", "tooltips.sort_mode"),
    ("installed_mods_label", "setText", "ui.installed_mods_label"),
    ("installed_mods_label", "setToolTip", "tooltips.installed_mods"),
    ("add_mod_button", "setText", "ui.add_mod"),
    ("add_mod_button", "setToolTip", "ui.add_mod"),
    ("library_profile_label", "setText", "ui.profile_label"),
    ("library_game_label", "setText", "ui.game_label"),
    ("profile_combo", "setToolTip", "tooltips.profile_combo"),
    ("profile_settings_button", "setToolTip", "profiles.manager_title"),
    ("library_game_versions_button", "setToolTip", "tooltips.game_versions"),
    ("games_manager_button", "setToolTip", "games.manager_title"),
    ("theme_button", "setText", "buttons.import_export_themes"),
    ("do_not_save_theme_checkbox", "setText", "ui.do_not_save_theme_after_import"),
    ("hide_mods_browser_tab_checkbox", "setText", "ui.hide_mods_browser_tab"),
    ("hide_library_tab_checkbox", "setText", "ui.hide_library_tab"),
    ("merge_properties_checkbox", "setText", "checkboxes.merge_properties"),
    ("merge_code_checkbox", "setText", "checkboxes.merge_code"),
    ("merge_properties_checkbox", "setToolTip", "tooltips.merge_properties"),
    ("merge_code_checkbox", "setToolTip", "tooltips.merge_code"),
    ("downloads_no_auto_use_checkbox", "setText", "downloads.settings_no_auto_use"),
    ("downloads_delete_after_use_checkbox", "setText", "downloads.settings_delete_after_use",),
    ("downloads_save_local_imports_checkbox", "setText", "downloads.settings_save_local_imports",),
]
COMBO_LOCALIZATIONS = {
    "sort_combo": [
        "ui.sort_by_relevance",
        "ui.sort_by_creation_date",
        "ui.sort_by_update_date",
    ],
    "library_sort_combo": ["ui.sort_by_name", "ui.sort_by_date"],
}

"""Network, background work, and timing limits."""
NETWORK_TIMEOUT_SHORT = 5
NETWORK_TIMEOUT_MEDIUM = 15
NETWORK_TIMEOUT_LONG = 45
NETWORK_TIMEOUT_HEAD = 15
INITIALIZATION_TIMEOUT = 5000
ONLINE_UPDATE_INTERVAL = 1800000
LAUNCHER_FALLBACK_TIMEOUT = 8000
SPLASH_WATCHDOG_TIMEOUT = 15000
SPLASH_RETRY_DELAY = 100
IMAGE_CACHE_MAX_SIZE = 100
NETWORK_SEMAPHORE_LIMIT = 4
THREAD_WAIT_TIMEOUT = 2000
DOWNLOAD_CHUNK_SIZE = 262144
MAX_DOWNLOAD_RETRIES = 5
SEARCH_TIMEOUT_SECONDS = 10
SEARCH_EXHAUSTED_PAGE_SENTINEL = 100
TEMP_DIR_GLOBS = (
    "g3m_modpack_*",
    "g3m_multimod_*",
    "g3m-dl-*",
    "g3m-extract-*",
)
LEGACY_TEMP_DIR_GLOBS = (
    "deltahub_modpack_*",
    "deltahub_multimod_*",
    "deltahub-dl-*",
    "deltahub-extract-*",
)

"""GameBanana integration constants."""
GAMEBANANA_API_BASE = "https://gamebanana.com/apiv11"
GAMEBANANA_TOOL_ID_DELTAMOD = 20575
GAMEBANANA_TOOL_ID_G3M = 20615
GAMEBANANA_PER_PAGE = 15

"""Mod file, archive, cache, and content metadata constants."""
GAME_VERSION_MANIFEST_FILENAME = "game_version_data.json"
MOD_VERSIONS_DIR = "mod_versions"
DATA_FILE_EXTENSIONS = (
    ".xdelta",
    ".vcdiff",
    ".csx",
    ".win",
    ".unx",
    ".ios",
    ".droid",
    ".g3mpatch",
)
GAME_DATA_FILE_EXTENSIONS = (".win", ".unx", ".ios", ".droid")
GAME_DATA_FILENAMES = (
    "data.win",
    "game.ios",
    "game.unx",
    "game.droid",
)
MOD_CONFIG_FILENAME = "mod_config.json"
THEME_CONFIG_VERSION = "1.0.0"
THEME_CONFIG_FILENAME = "theme_config.json"
LEGACY_THEME_CONFIG_FILENAME = "theme.json"
THEME_CONFIG_FILENAMES = (
    THEME_CONFIG_FILENAME,
    LEGACY_THEME_CONFIG_FILENAME,
)
DATA_WIN_FILENAME = "data.win"
META_JSON_FILENAME = "meta.json"
ICON_PNG_FILENAME = "icon.png"
MOD_TYPE_G3MPATCH = "g3mpatch"
MOD_TYPE_XDELTA = "xdelta"
MOD_TYPE_CSX = "csx"
MOD_TYPE_DATAFILE = "datafile"
DELTAMOD_INFO_FILENAME = "_deltamodInfo.json"
MAX_PATCHING_ARCHIVES = 10
MOD_TYPE_OVERRIDES_ONLY = "overrides_only"
MOD_FILTER_TRUE_VALUES = (True, "true", "True", 1)
MOD_FILTER_NSFW_TEXT_MARKERS = ("nsfw", "adult", "18+", "18plus", "explicit", "mature")

SKIP_FILES = (
    "mod_config.json",
    "_icon.png",
    "icon.png",
    "meta.json",
    DELTAMOD_INFO_FILENAME,
)
ARCHIVE_EXTENSIONS = (".zip", ".7z", ".rar", ".tar.gz", ".lzma")
