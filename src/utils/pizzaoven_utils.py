import os
import logging
from typing import Optional


def is_pizzaoven_mod(mod_data: any) -> bool:
    try:
        if hasattr(mod_data, 'game') or hasattr(mod_data, 'modgame'):
            game_value = getattr(mod_data, 'game', None) or getattr(mod_data, 'modgame', None)
            return game_value == 'pizzaoven'
        if hasattr(mod_data, 'config_data'):
            config = getattr(mod_data, 'config_data')
            if isinstance(config, dict):
                return (config.get('game') or config.get('modgame')) == 'pizzaoven'
        if isinstance(mod_data, dict):
            return (mod_data.get('game') or mod_data.get('modgame')) == 'pizzaoven'
    except Exception as e:
        logging.debug(f'is_pizzaoven_mod: Error checking mod type: {e}')
    return False


def _has_pizza_tower_files(directory: str) -> bool:
    if not directory or not os.path.isdir(directory):
        return False
    try:
        files = os.listdir(directory)
        pizza_tower_extensions = ('.xdelta', '.win', '.bank', '.dll', '.mp4', '.vcdiff')
        for file in files:
            file_lower = file.lower()
            if file_lower in ('mod_config.json', 'config.json', '_icon.png', 'icon.png', 'meta.json', '_deltamodInfo.json'):
                continue
            if file_lower.endswith(pizza_tower_extensions):
                return True
            if file_lower in ('data.win', 'pizzatower.exe', 'game.ios'):
                return True
    except Exception as e:
        logging.debug(f'_has_pizza_tower_files: Error checking directory {directory}: {e}')
    return False


def find_pizzaoven_folder(mod_dir: str) -> Optional[str]:
    if not mod_dir or not os.path.isdir(mod_dir):
        return None
    pizzaoven_path = os.path.join(mod_dir, 'pizzaoven')
    if os.path.isdir(pizzaoven_path):
        return pizzaoven_path
    archive_extensions = ['.zip', '.7z', '.rar']
    for ext in archive_extensions:
        archive_path = os.path.join(mod_dir, f'pizzaoven{ext}')
        if os.path.isfile(archive_path):
            return archive_path
    for root, dirs, files in os.walk(mod_dir):
        depth = root[len(mod_dir):].count(os.sep)
        if depth > 2:
            continue
        if 'pizzaoven' in dirs:
            pizzaoven_path = os.path.join(root, 'pizzaoven')
            if os.path.isdir(pizzaoven_path):
                return pizzaoven_path
        for ext in archive_extensions:
            archive_name = f'pizzaoven{ext}'
            if archive_name in files:
                archive_path = os.path.join(root, archive_name)
                if os.path.isfile(archive_path):
                    return archive_path
    if _has_pizza_tower_files(mod_dir):
        logging.debug(f'find_pizzaoven_folder: Found Pizza Tower files in root directory: {mod_dir}')
        return mod_dir
    return None


def normalize_pizzaoven_structure(source_path: str) -> Optional[str]:
    if not source_path or not os.path.exists(source_path):
        return None
    if os.path.isfile(source_path):
        return source_path
    if not os.path.isdir(source_path):
        return None
    game_files = [f for f in os.listdir(source_path) if f.lower().endswith(('.xdelta', '.win', '.txt', '.png', '.bank', '.dll', '.mp4'))]
    if game_files:
        return source_path
    subdirs = [d for d in os.listdir(source_path) if os.path.isdir(os.path.join(source_path, d))]
    for subdir in subdirs:
        subdir_path = os.path.join(source_path, subdir)
        game_files = [f for f in os.listdir(subdir_path) if f.lower().endswith(('.xdelta', '.win', '.txt', '.png', '.bank', '.dll', '.mp4'))]
        if game_files:
            return subdir_path
    return source_path
