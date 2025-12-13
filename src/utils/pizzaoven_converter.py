import os
import json
import shutil
import uuid
import logging
import tempfile
from datetime import datetime
from typing import Optional, Dict, Any
from managers.localization_manager import tr
from utils.file_utils import get_unique_mod_dir
from utils.pizzaoven_utils import find_pizzaoven_folder, normalize_pizzaoven_structure
from utils.archive_utils import extract_archive


class PizzaOvenConverter:

    def __init__(self, source_path: str, mods_dir: str, archive_name: Optional[str] = None):
        self.source_path = source_path
        self.mods_dir = mods_dir
        self.archive_name = archive_name
        self.pizzaoven_path: Optional[str] = None
        self.temp_extract_dir: Optional[str] = None

    def convert(self) -> Optional[str]:
        try:
            if not self._validate_source():
                return None
            config_data = self._generate_config_json()
            if not config_data:
                return None
            mod_name = config_data.get('name', 'unnamed_mod')
            folder_name = get_unique_mod_dir(self.mods_dir, mod_name)
            target_mod_dir = os.path.join(self.mods_dir, folder_name)
            if os.path.exists(target_mod_dir):
                shutil.rmtree(target_mod_dir)
            os.makedirs(target_mod_dir)
            self._process_files(target_mod_dir)
            config_path = os.path.join(target_mod_dir, 'mod_config.json')
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
            logging.info(f"PizzaOven mod converted: {config_data.get('name')} → {target_mod_dir}")
            return target_mod_dir
        except Exception as e:
            logging.error(f'PizzaOven conversion failed: {e}', exc_info=True)
            return None
        finally:
            self._cleanup()

    def _validate_source(self) -> bool:
        if not os.path.exists(self.source_path):
            logging.debug(f'PizzaOvenConverter._validate_source: source_path does not exist: {self.source_path}')
            return False
        self.pizzaoven_path = find_pizzaoven_folder(self.source_path)
        if self.pizzaoven_path:
            logging.debug(f'PizzaOvenConverter._validate_source: found pizzaoven at: {self.pizzaoven_path}')
            return True
        logging.debug(f'PizzaOvenConverter._validate_source: pizzaoven folder not found in: {self.source_path}, but continuing anyway')
        self.pizzaoven_path = self.source_path
        return True

    def _generate_config_json(self) -> Optional[Dict[str, Any]]:
        if not self.pizzaoven_path:
            logging.error('PizzaOvenConverter._generate_config_json: pizzaoven_path is None')
            return None
        config_data = {}
        config_path = None
        search_root = self.source_path
        if self.pizzaoven_path == self.source_path:
            search_root = self.source_path
        elif self.pizzaoven_path and os.path.commonpath([self.source_path, self.pizzaoven_path]) == self.source_path:
            search_root = self.source_path
        else:
            search_root = self.source_path
        if os.path.isfile(os.path.join(search_root, 'mod_config.json')):
            config_path = os.path.join(search_root, 'mod_config.json')
        else:
            for root, dirs, files in os.walk(search_root):
                if self.pizzaoven_path and self.pizzaoven_path != self.source_path:
                    if 'pizzaoven' in root.lower() and root != self.source_path:
                        continue
                if 'mod_config.json' in files:
                    config_path = os.path.join(root, 'mod_config.json')
                    break
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    existing_config = json.load(f)
                    for key in ['name', 'author', 'version', 'tagline', 'description', 'external_url', 'game_version', 'tags', 'icon_url']:
                        if key in existing_config:
                            config_data[key] = existing_config[key]
            except Exception as e:
                logging.debug(f'PizzaOvenConverter: Failed to read existing config: {e}')
        if not config_data.get('name'):
            base_name = None
            if self.archive_name:
                base_name = self.archive_name
            else:
                base_name = os.path.basename(self.source_path)
            for ext in ['.tar.gz', '.tar.lzma', '.zip', '.7z', '.rar', '.lzma']:
                if base_name.lower().endswith(ext):
                    base_name = base_name[:-len(ext)]
                    break
            if base_name:
                config_data['name'] = base_name.replace('_', ' ').replace('-', ' ').title()
            else:
                config_data['name'] = 'PizzaOven Mod'
        key = config_data.get('key') or config_data.get('mod_key')
        if not key:
            mod_name = config_data.get('name', 'pizzaoven_mod')
            mod_name_clean = ''.join((c if c.isalnum() or c in ('_', '-') else '_' for c in mod_name.lower()))
            key = f'local_{mod_name_clean}_{uuid.uuid4().hex[:8]}'
        created_date = datetime.now().strftime('%d.%m.%y %H:%M')
        config = {'is_local_mod': True, 'key': key, 'created_date': created_date, 'is_available_on_server': False, 'name': config_data.get('name', tr('defaults.local_mod')), 'version': config_data.get('version', '1.0.0'), 'author': config_data.get('author', tr('defaults.unknown')), 'tagline': config_data.get('tagline', config_data.get('description', tr('defaults.no_description'))), 'external_url': config_data.get('external_url', ''), 'game_version': config_data.get('game_version', tr('defaults.not_specified')), 'game': 'pizzaoven', 'files': {}, 'tags': config_data.get('tags', [])}
        return config

    def _process_files(self, target_mod_dir: str) -> None:
        if not self.pizzaoven_path:
            return
        if os.path.isfile(self.pizzaoven_path):
            self.temp_extract_dir = tempfile.mkdtemp(prefix='pizzaoven_extract_')
            try:
                extract_archive(self.pizzaoven_path, self.temp_extract_dir)
                extracted_path = normalize_pizzaoven_structure(self.temp_extract_dir)
                if extracted_path and os.path.isdir(extracted_path):
                    pizzaoven_target = os.path.join(target_mod_dir, 'pizzaoven')
                    if os.path.exists(pizzaoven_target):
                        shutil.rmtree(pizzaoven_target)
                    shutil.copytree(extracted_path, pizzaoven_target)
            except Exception as e:
                logging.error(f'PizzaOvenConverter: Failed to extract archive: {e}', exc_info=True)
                return
        else:
            normalized_path = normalize_pizzaoven_structure(self.pizzaoven_path)
            if normalized_path and os.path.isdir(normalized_path):
                pizzaoven_target = os.path.join(target_mod_dir, 'pizzaoven')
                if os.path.exists(pizzaoven_target):
                    shutil.rmtree(pizzaoven_target)
                if normalized_path == self.pizzaoven_path == self.source_path:
                    os.makedirs(pizzaoven_target, exist_ok=True)
                    for item in os.listdir(normalized_path):
                        item_path = os.path.join(normalized_path, item)
                        item_lower = item.lower()
                        if item_lower in ('mod_config.json', 'config.json', '_icon.png', 'icon.png', 'meta.json', '_deltamodInfo.json'):
                            continue
                        if os.path.isdir(item_path):
                            shutil.copytree(item_path, os.path.join(pizzaoven_target, item))
                        else:
                            shutil.copy2(item_path, os.path.join(pizzaoven_target, item))
                else:
                    shutil.copytree(normalized_path, pizzaoven_target)
        icon_path = os.path.join(self.source_path, '_icon.png')
        if not os.path.exists(icon_path):
            for root, dirs, files in os.walk(self.source_path):
                if '_icon.png' in files:
                    icon_path = os.path.join(root, '_icon.png')
                    break
        if os.path.exists(icon_path):
            shutil.copy2(icon_path, os.path.join(target_mod_dir, '_icon.png'))

    def _cleanup(self) -> None:
        if self.temp_extract_dir and os.path.exists(self.temp_extract_dir):
            try:
                shutil.rmtree(self.temp_extract_dir)
            except Exception as e:
                logging.warning(f'PizzaOvenConverter: Failed to cleanup temp dir: {e}')
