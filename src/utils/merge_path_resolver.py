"""Path resolution helpers for mod merging — resolves mod source dirs and game target dirs."""
import os
from typing import Any, Optional

from utils.file_utils import sanitize_filename, get_chapter_folder_name, load_json
from utils.mod_utils import get_mod_key, get_mod_name
from utils.path_utils import find_chapter_resource_dir
from utils import merge_mod_detection


def resolve_mod_game(mod_data, source_dir=None):
    """Resolve the game type from mod_data attributes and optional source directory."""
    game = getattr(mod_data, 'game', None) or getattr(mod_data, 'modgame', None)
    if not game and hasattr(mod_data, 'config_data'):
        config = getattr(mod_data, 'config_data')
        if isinstance(config, dict):
            game = config.get('game') or config.get('modgame')
    if not game and source_dir:
        config_path = os.path.join(source_dir, 'mod_config.json')
        if os.path.exists(config_path):
            try:
                config_data = load_json(config_path, migrate_config=True)
                game = config_data.get('game') or config_data.get('modgame')
            except Exception:
                pass
    return game


def get_mod_source_dir(mod_data: Any, chapter_id: int, mod_service, app_state, logger) -> Optional[str]:
    """Resolve the source directory for a mod's chapter content."""
    key = get_mod_key(mod_data)
    if not key:
        logger.warning('_get_mod_source_dir: mod_data has no key')
        return None
    mod_folder_path = mod_service.get_mod_folder_path(key)
    if mod_folder_path and os.path.isdir(mod_folder_path):
        source_dir = mod_folder_path
    else:
        mod_name = get_mod_name(mod_data, key)
        folder_name = sanitize_filename(mod_name)
        source_dir = os.path.join(app_state.mods_dir, folder_name)
        if not os.path.isdir(source_dir):
            source_dir = None
            if os.path.exists(app_state.mods_dir):
                for folder_name in os.listdir(app_state.mods_dir):
                    folder_path = os.path.join(app_state.mods_dir, folder_name)
                    if not os.path.isdir(folder_path):
                        continue
                    config_path = os.path.join(folder_path, 'mod_config.json')
                    if os.path.exists(config_path):
                        try:
                            config_data = load_json(config_path, migrate_config=True)
                            if (config_data.get('key') or config_data.get('mod_key')) == key:
                                source_dir = folder_path
                                break
                        except Exception:
                            pass
            if not source_dir:
                return None
    game = resolve_mod_game(mod_data, source_dir)
    chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
    chapter_dir = os.path.join(source_dir, chapter_folder_name)
    if not os.path.isdir(chapter_dir):
        if chapter_id == 0:
            if game == 'pizzatower':
                pizzatower_dir = os.path.join(source_dir, 'pizzatower')
                if os.path.isdir(pizzatower_dir):
                    return pizzatower_dir
            alt_menu_dir = os.path.join(source_dir, 'menu')
            if os.path.isdir(alt_menu_dir):
                return alt_menu_dir
        elif chapter_id == -1:
            return source_dir
        return None
    return chapter_dir


def get_target_dir(chapter_id: int, app_state, logger, game: Optional[str] = None) -> Optional[str]:
    """Resolve the target directory (game install path) for a chapter."""
    from models.game_modes import DemoGameMode, UndertaleGameMode, UndertaleYellowGameMode, PizzaTowerGameMode, SugarySpireGameMode
    from config.constants import SLOT_ID_PIZZA_TOWER, SLOT_ID_UNDERTALE, SLOT_ID_UNDERTALE_YELLOW, SLOT_ID_DEMO, SLOT_ID_SUGARY_SPIRE
    _GAME_CONFIGS = {
        'deltarune_demo': (DemoGameMode, 'DELTARUNEdemo.app', lambda s: s.demo_game_path, [SLOT_ID_DEMO, -1]),
        'undertale': (UndertaleGameMode, 'UNDERTALE.app', None, [SLOT_ID_UNDERTALE, 0]),
        'undertaleyellow': (UndertaleYellowGameMode, 'Undertale Yellow.app', None, [SLOT_ID_UNDERTALE_YELLOW, 0]),
        'pizzatower': (PizzaTowerGameMode, 'PizzaTower.app', None, [SLOT_ID_PIZZA_TOWER]),
        'sugaryspire': (SugarySpireGameMode, 'SugarySpire_ExhibitionNight.app', None, [SLOT_ID_SUGARY_SPIRE, 0]),
    }
    if game:
        if game in _GAME_CONFIGS:
            mode_cls, app_name, path_getter, slot_ids = _GAME_CONFIGS[game]
            gm = mode_cls()
            base_path = path_getter(app_state) if path_getter else gm.get_game_path(app_state.local_config)
            if chapter_id in slot_ids:
                if not base_path:
                    logger.warning(f'{game} game path not found in config for chapter {chapter_id}')
                    return None
                return merge_mod_detection.resolve_macos_path(base_path, app_name)
            if not base_path:
                return None
        else:
            base_path = app_state.game_path
            if not base_path:
                return None
    else:
        base_path = app_state.game_mode.get_game_path(app_state.local_config)
        if not base_path:
            return None
        for gkey, (mode_cls, app_name, _, slot_ids) in _GAME_CONFIGS.items():
            if isinstance(app_state.game_mode, mode_cls) and chapter_id in slot_ids:
                return merge_mod_detection.resolve_macos_path(base_path, app_name)
    return find_chapter_resource_dir(base_path, chapter_id)
