"""Configuration constants for the mod merge/patching system."""

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

MERGE_SUBDIRS = [
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
    ('variable\\s+name\\s+[\\\'"]?(\\w+)[\\\'"]?\\s+index\\s+\\([^)]+\\)\\s+not\\s+set\\s+before\\s+reading', 'variable_not_set'),
    ('global\\s+variable\\s+name\\s+[\\\'"]?(\\w+)[\\\'"]?\\s+index\\s+\\([^)]+\\)\\s+not\\s+set', 'global_variable_not_set'),
    ('ERROR\\s+in\\s+action\\s+number\\s+\\d+\\s+of\\s+(\\w+)\\s+Event\\d+\\s+for\\s+object\\s+(\\w+):', 'runtime_error'),
    ('undefined\\s+variable\\s+[\\\'"]?(\\w+)[\\\'"]?', 'undefined_variable'),
    ('compilation\\s+error', 'compilation_error'),
    ('compilation\\s+failed', 'compilation_failed'),
    ('failed\\s+to\\s+compile', 'compilation_failed'),
    ('variable\\s+[\\\'"]?(\\w+)[\\\'"]?\\s+is\\s+not\\s+defined', 'variable_not_defined'),
]

SKIP_FILES = ('config.json', 'mod_config.json', '_icon.png', 'icon.png', 'meta.json', '_deltamodInfo.json')

ARCHIVE_EXTENSIONS = ('.zip', '.7z', '.rar', '.tar.gz', '.lzma')
