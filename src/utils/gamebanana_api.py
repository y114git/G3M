import requests
import logging
import json
import re
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from config.constants import GAMEBANANA_API_BASE, GAMEBANANA_GAME_IDS, NETWORK_TIMEOUT_MEDIUM
from utils.network_utils import get_session
from models.mod_models import ModInfo
from managers.localization_manager import tr
logger = logging.getLogger(__name__)


class GameBananaAPI:

    def __init__(self):
        self.base_url = GAMEBANANA_API_BASE
        self.core_api_base = 'https://api.gamebanana.com'
        self.session = get_session()

    def get_game_mods(self, game_id: int, page: int = 1, per_page: int = 20, sort: str = 'default', metadata_cache=None) -> Tuple[Optional[List[Dict]], List[str]]:
        valid_sorts = ['default', 'new', 'updated']
        effective_sort = sort if sort in valid_sorts else 'default'
        url = f'{self.base_url}/Game/{game_id}/Subfeed'
        params = {'_nPage': page, '_nPerpage': per_page, '_sSort': effective_sort, '_csvModelInclusions': 'Mod'}
        mods_needing_metadata = []
        try:
            response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
            response.raise_for_status()
            data = response.json()
            records = data.get('_aRecords', [])
            game_name = None
            for name, id_val in GAMEBANANA_GAME_IDS.items():
                if id_val == game_id:
                    game_name = name
                    break
            if not game_name:
                game_name = 'deltarune'
            mapped_mods = []
            for record in records:
                if record.get('_sModelName') == 'Mod':
                    mod_id = record.get('_idRow')
                    if mod_id:
                        mod_id_str = str(mod_id)
                        mapped_data = self._map_mod_data(record, game_name)
                        if mapped_data:
                            downloads_from_gb = record.get('_nDownloadCount')
                            downloads_value = 0
                            if downloads_from_gb is not None:
                                try:
                                    downloads_value = int(downloads_from_gb)
                                except (ValueError, TypeError):
                                    downloads_value = 0
                            mapped_data['downloads'] = downloads_value
                            cache_valid = False
                            cached_category = None
                            if metadata_cache:
                                cache_valid = metadata_cache.is_valid(mod_id_str)
                                if cache_valid:
                                    cached_downloads = metadata_cache.get_downloads(mod_id_str)
                                    cached_tagline = metadata_cache.get_tagline(mod_id_str)
                                    cached_category = metadata_cache.get_category(mod_id_str)
                                    if cached_downloads is not None and cached_downloads > 0:
                                        mapped_data['downloads'] = cached_downloads
                                    elif downloads_value > 0:
                                        mapped_data['downloads'] = downloads_value
                                    if cached_tagline:
                                        mapped_data['tagline'] = cached_tagline
                                    if cached_category:
                                        mapped_data['gamebanana_category'] = cached_category
                            current_downloads = mapped_data.get('downloads', 0)
                            if current_downloads is None:
                                current_downloads = 0
                            else:
                                try:
                                    current_downloads = int(current_downloads)
                                except (ValueError, TypeError):
                                    current_downloads = 0
                            mapped_data['downloads'] = current_downloads
                            current_tagline = mapped_data.get('tagline', '')
                            current_category = mapped_data.get('gamebanana_category')
                            needs_downloads = current_downloads == 0 or current_downloads is None
                            needs_tagline = not current_tagline or current_tagline == 'No description' or len(current_tagline) < 10
                            needs_category = not current_category
                            if (needs_downloads or needs_tagline or needs_category) and (not cache_valid):
                                mods_needing_metadata.append(mod_id_str)
                            mapped_mods.append(mapped_data)
            return (mapped_mods, mods_needing_metadata)
        except requests.RequestException as e:
            logger.error(f'Error fetching mods for game {game_id}: {e}')
            return (None, [])
        except Exception as e:
            logger.error(f'Unexpected error fetching mods for game {game_id}: {e}')
            return (None, [])

    def get_mod_downloads_only(self, mod_id: int) -> Optional[int]:
        url = f'{self.core_api_base}/Core/Item/Data'
        params = {'itemtype': 'Mod', 'itemid': mod_id, 'fields': 'downloads'}
        try:
            logger.debug(f'get_mod_downloads_only: Fetching downloads for mod {mod_id}')
            response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
            response.raise_for_status()
            data = response.json()
            logger.debug(f'get_mod_downloads_only: Got response for mod {mod_id}, data type: {type(data)}')
            downloads_value = None
            if isinstance(data, list) and len(data) > 0:
                downloads_field = data[0]
            elif isinstance(data, dict):
                downloads_field = data.get('downloads')
            else:
                downloads_field = data
            if downloads_field is not None:
                if isinstance(downloads_field, list) and len(downloads_field) > 0:
                    downloads_value = downloads_field[0]
                elif isinstance(downloads_field, (int, float)):
                    downloads_value = downloads_field
                elif isinstance(downloads_field, str) and downloads_field.strip():
                    try:
                        downloads_value = int(float(downloads_field))
                    except (ValueError, TypeError):
                        downloads_value = None
                if downloads_value is not None:
                    try:
                        result = int(downloads_value)
                        logger.debug(f'get_mod_downloads_only: Successfully got downloads for mod {mod_id}: {result}')
                        return result
                    except (ValueError, TypeError):
                        logger.warning(f'get_mod_downloads_only: Could not convert downloads value to int for mod {mod_id}: {downloads_value}')
            logger.warning(f'get_mod_downloads_only: No valid downloads value for mod {mod_id}')
            return None
        except requests.RequestException as e:
            logger.error(f'Error fetching downloads for mod {mod_id}: {e}')
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f'Response status: {e.response.status_code}, response text: {e.response.text[:500]}')
            return None
        except Exception as e:
            logger.error(f'Unexpected error fetching downloads for mod {mod_id}: {e}', exc_info=True)
            return None

    def get_mod_description_only(self, mod_id: int) -> Optional[str]:
        url = f'{self.core_api_base}/Core/Item/Data'
        params = {'itemtype': 'Mod', 'itemid': mod_id, 'fields': 'description'}
        try:
            logger.debug(f'get_mod_description_only: Fetching description for mod {mod_id}')
            response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
            response.raise_for_status()
            data = response.json()
            logger.debug(f'get_mod_description_only: Got response for mod {mod_id}, data type: {type(data)}')
            description_value = None
            if isinstance(data, list) and len(data) > 0:
                description_field = data[0]
            elif isinstance(data, dict):
                description_field = data.get('description')
            else:
                description_field = data
            if description_field is not None:
                if isinstance(description_field, list) and len(description_field) > 0:
                    description_value = description_field[0]
                elif isinstance(description_field, str):
                    description_value = description_field
                else:
                    description_value = str(description_field) if description_field else None
                if description_value and isinstance(description_value, str) and description_value.strip():
                    logger.debug(f'get_mod_description_only: Successfully got description for mod {mod_id}')
                    return description_value.strip()
            logger.warning(f'get_mod_description_only: No valid description value for mod {mod_id}')
            return None
        except requests.RequestException as e:
            logger.error(f'Error fetching description for mod {mod_id}: {e}')
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f'Response status: {e.response.status_code}, response text: {e.response.text[:500]}')
            return None
        except Exception as e:
            logger.error(f'Unexpected error fetching description for mod {mod_id}: {e}', exc_info=True)
            return None

    def get_mod_category_only(self, mod_id: int) -> Optional[str]:
        url = f'{self.core_api_base}/Core/Item/Data'
        params = {'itemtype': 'Mod', 'itemid': mod_id, 'fields': 'Category().name'}
        try:
            response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
            response.raise_for_status()
            data = response.json()
            category_value = None
            if isinstance(data, list):
                if len(data) > 0:
                    first_item = data[0]
                    if isinstance(first_item, list):
                        if len(first_item) > 0:
                            category_value = first_item[0]
                    elif isinstance(first_item, str):
                        category_value = first_item
                    elif first_item is not None:
                        category_value = str(first_item)
            elif isinstance(data, dict):
                category_field = data.get('name') or data.get('Category().name') or data.get('Category') or data.get('_sName')
                if isinstance(category_field, list) and len(category_field) > 0:
                    category_value = category_field[0]
                elif isinstance(category_field, str):
                    category_value = category_field
                elif category_field is not None:
                    category_value = str(category_field)
            elif isinstance(data, str):
                category_value = data
            if category_value:
                if not isinstance(category_value, str):
                    category_value = str(category_value)
                category_value = category_value.strip()
                if category_value and category_value.lower() not in ('none', 'null', ''):
                    return category_value
            return None
        except requests.RequestException as e:
            logger.error(f'Error fetching category for mod {mod_id}: {e}')
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f'Response status: {e.response.status_code}, response text: {e.response.text[:500]}')
            return None
        except Exception as e:
            logger.error(f'Unexpected error fetching category for mod {mod_id}: {e}', exc_info=True)
            return None

    def get_mod_text_and_screenshots(self, mod_id: int) -> Optional[Dict]:
        url = f'{self.core_api_base}/Core/Item/Data'
        params = {'itemtype': 'Mod', 'itemid': mod_id, 'fields': 'text,screenshots'}
        try:
            logger.debug(f'get_mod_text_and_screenshots: Fetching text and screenshots for mod {mod_id}')
            response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"get_mod_text_and_screenshots: Got response for mod {mod_id}, data type: {type(data)}, length: {(len(data) if isinstance(data, (list, dict)) else 'N/A')}")
            result = {'text': None, 'screenshots': None}
            if isinstance(data, list) and len(data) >= 2:
                result['text'] = data[0] if len(data) > 0 else None
                result['screenshots'] = data[1] if len(data) > 1 else None
            elif isinstance(data, list) and len(data) > 0:
                if isinstance(data[0], dict):
                    logger.debug('get_mod_text_and_screenshots: Response is list with dict at index 0')
                    result = data[0]
                else:
                    if len(data) > 0:
                        result['text'] = data[0]
                    if len(data) > 1:
                        result['screenshots'] = data[1]
            elif isinstance(data, dict):
                logger.debug(f'get_mod_text_and_screenshots: Response is dict, keys: {list(data.keys())}')
                result['text'] = data.get('text')
                result['screenshots'] = data.get('screenshots')
            else:
                logger.warning(f'get_mod_text_and_screenshots: Unexpected response format for mod {mod_id}: {type(data)}, value: {str(data)[:200]}')
                return None
            logger.debug(f"get_mod_text_and_screenshots: Successfully parsed details for mod {mod_id}, has text: {bool(result.get('text'))}, has screenshots: {result.get('screenshots') is not None}")
            return result if result.get('text') or result.get('screenshots') else None
        except requests.RequestException as e:
            logger.error(f'Error fetching text and screenshots for mod {mod_id}: {e}')
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f'Response status: {e.response.status_code}, response text: {e.response.text[:500]}')
                logger.error(f'Request URL: {url}, params: {params}')
            return None
        except Exception as e:
            logger.error(f'Unexpected error fetching text and screenshots for mod {mod_id}: {e}', exc_info=True)
            return None

    def get_mod_full_details_for_display(self, mod_id: int) -> Optional[Dict]:
        url = f'{self.core_api_base}/Core/Item/Data'
        params = {'itemtype': 'Mod', 'itemid': mod_id, 'fields': 'text,description,screenshots'}
        try:
            logger.debug(f'get_mod_full_details_for_display: Fetching details for mod {mod_id}')
            response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"get_mod_full_details_for_display: Got response for mod {mod_id}, data type: {type(data)}, length: {(len(data) if isinstance(data, (list, dict)) else 'N/A')}")
            if isinstance(data, list) and len(data) >= 3:
                result = {'text': data[0] if len(data) > 0 else None, 'description': data[1] if len(data) > 1 else None, 'screenshots': data[2] if len(data) > 2 else None}
                logger.debug(f"get_mod_full_details_for_display: Successfully parsed details for mod {mod_id}, has text: {bool(result['text'])}, has description: {bool(result['description'])}, has screenshots: {bool(result['screenshots'])}")
                return result
            elif isinstance(data, list) and len(data) > 0:
                if isinstance(data[0], dict):
                    logger.debug('get_mod_full_details_for_display: Response is list with dict at index 0')
                    return data[0]
                else:
                    logger.warning(f"get_mod_full_details_for_display: Response is list but has {len(data)} elements (expected 3), first element type: {(type(data[0]) if len(data) > 0 else 'N/A')}")
                    result = {}
                    if len(data) > 0:
                        result['text'] = data[0]
                    if len(data) > 1:
                        result['description'] = data[1]
                    if len(data) > 2:
                        result['screenshots'] = data[2]
                    return result if result else None
            elif isinstance(data, dict):
                logger.debug(f'get_mod_full_details_for_display: Response is dict, keys: {list(data.keys())}')
                return data
            else:
                logger.warning(f'get_mod_full_details_for_display: Unexpected response format for mod {mod_id}: {type(data)}, value: {str(data)[:200]}')
                return None
        except requests.RequestException as e:
            logger.error(f'Error fetching full details for mod {mod_id}: {e}')
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f'Response status: {e.response.status_code}, response text: {e.response.text[:500]}')
                logger.error(f'Request URL: {url}, params: {params}')
            return None
        except Exception as e:
            logger.error(f'Unexpected error fetching full details for mod {mod_id}: {e}', exc_info=True)
            return None

    def _get_mod_full_details(self, mod_id: int) -> Optional[Dict]:
        return self.get_mod_full_details_for_display(mod_id)

    def get_game_mods_raw(self, game_id: int, page: int = 1, sort: str = 'default') -> Optional[Dict]:
        url = f'{self.base_url}/Game/{game_id}/Subfeed'
        params = {'_nPage': page, '_sSort': sort, '_csvModelInclusions': 'Mod'}
        try:
            response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f'Error fetching mods for game {game_id}: {e}')
            return None
        except Exception as e:
            logger.error(f'Unexpected error fetching mods for game {game_id}: {e}')
            return None

    def get_mod_details(self, mod_id: int) -> Optional[Dict]:
        url = f'{self.base_url}/Mod/{mod_id}/ProfilePage'
        try:
            response = self.session.get(url, timeout=NETWORK_TIMEOUT_MEDIUM)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                logger.warning(f'get_mod_details: Response for mod {mod_id} is not a dict, type: {type(data)}')
                return None
            return data
        except requests.RequestException as e:
            logger.error(f'Error fetching mod details for {mod_id}: {e}')
            if hasattr(e, 'response') and e.response is not None:
                logger.debug(f'Response status: {e.response.status_code}')
            return None
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f'Error parsing mod details JSON for {mod_id}: {e}')
            return None
        except Exception as e:
            logger.error(f'Unexpected error fetching mod details for {mod_id}: {e}', exc_info=True)
            return None

    def get_mod_preview_media(self, mod_id: int) -> Optional[Dict]:
        url = f'{self.core_api_base}/Core/Item/Data'
        params = {'itemtype': 'Mod', 'itemid': mod_id, 'fields': 'Preview().aPreviewMedia()'}
        try:
            logger.debug(f'get_mod_preview_media: Fetching preview media for mod {mod_id}')
            response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
            response.raise_for_status()
            data = response.json()
            logger.debug(f'get_mod_preview_media: Got response for mod {mod_id}, data type: {type(data)}')
            if isinstance(data, list) and len(data) > 0:
                preview_media = data[0]
                if isinstance(preview_media, dict):
                    return preview_media
            elif isinstance(data, dict):
                return data
            return None
        except requests.RequestException as e:
            logger.error(f'Error fetching preview media for mod {mod_id}: {e}')
            return None
        except Exception as e:
            logger.error(f'Unexpected error fetching preview media for mod {mod_id}: {e}', exc_info=True)
            return None

    def get_mod_files(self, mod_id: int) -> Optional[List[Dict]]:
        url = f'{self.core_api_base}/Core/Item/Data'
        import urllib.parse
        fields_param = 'Files().aFiles()'
        params = {'itemtype': 'Mod', 'itemid': mod_id, 'fields': fields_param}
        try:
            full_url = f'{url}?itemtype=Mod&itemid={mod_id}&fields={urllib.parse.quote(fields_param)}'
            logger.debug(f'get_mod_files: Requesting URL: {full_url}')
            response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
            response.raise_for_status()
            data = response.json()
            logger.debug(f'get_mod_files: Response status: {response.status_code}, data type: {type(data)}')
            if isinstance(data, list) and len(data) > 0:
                files_dict = data[0]
                if isinstance(files_dict, dict):
                    files_list = []
                    for file_id, file_data in files_dict.items():
                        if isinstance(file_data, dict):
                            files_list.append(file_data)
                        else:
                            logger.warning(f'Unexpected file data type for file_id {file_id}: {type(file_data)}')
                    logger.debug(f'get_mod_files: Found {len(files_list)} files for mod {mod_id}')
                    return files_list if files_list else None
                else:
                    logger.warning(f'get_mod_files: Expected dict for files, got {type(files_dict)}, value: {files_dict}')
            else:
                logger.warning(f"get_mod_files: Unexpected response format for mod {mod_id}: {type(data)}, length: {(len(data) if isinstance(data, list) else 'N/A')}")
            return None
        except requests.RequestException as e:
            logger.error(f'Error fetching mod files for {mod_id}: {e}, URL was: {url}, params: {params}')
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f'Response status: {e.response.status_code}, response text: {e.response.text[:200]}')
            return None
        except Exception as e:
            logger.error(f'Unexpected error fetching mod files for {mod_id}: {e}', exc_info=True)
            return None

    def get_file_contents(self, file_id: int) -> Optional[List[str]]:
        url = f'{self.core_api_base}/Core/Item/Data'
        params = {'itemtype': 'File', 'itemid': file_id, 'fields': 'aFileTree()'}
        try:
            logger.debug(f'get_file_contents: Fetching file tree for file_id {file_id}')
            response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
            response.raise_for_status()
            data = response.json()
            logger.debug(f'get_file_contents: Got response for file_id {file_id}, data type: {type(data)}')
            file_tree = data[0] if isinstance(data, list) and len(data) > 0 else data
            logger.debug(f'get_file_contents: Processing file_tree type: {type(file_tree)}')
            if isinstance(file_tree, dict):
                file_list = []
                for key, value in file_tree.items():
                    if key in ('screenshots', 'folders') or isinstance(value, (list, dict)):
                        continue
                    if isinstance(value, str):
                        file_list.append(value)
                logger.info(f'get_file_contents: Extracted {len(file_list)} file names from dict format for file_id {file_id}')
                return file_list if file_list else None
            elif isinstance(file_tree, list):
                if len(file_tree) > 0:
                    if isinstance(file_tree[0], str):
                        logger.debug(f'get_file_contents: Returning list of {len(file_tree)} file names')
                        return file_tree
                    elif isinstance(file_tree[0], list):
                        logger.debug('get_file_contents: Found nested list structure, extracting first element')
                        return file_tree[0]
                    else:
                        logger.warning(f'get_file_contents: Unexpected list element type: {type(file_tree[0])}')
                else:
                    logger.debug('get_file_contents: Empty list returned')
                    return []
            else:
                logger.warning(f'get_file_contents: Unexpected file_tree type: {type(file_tree)}, value: {str(file_tree)[:200]}')
            return None
        except requests.RequestException as e:
            logger.error(f'Error fetching file contents for {file_id}: {e}')
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f'Response status: {e.response.status_code}, response text: {e.response.text[:200]}')
            return None
        except Exception as e:
            logger.error(f'Unexpected error fetching file contents for {file_id}: {e}', exc_info=True)
            return None

    def check_file_has_deltamodinfo(self, file_id: int) -> bool:
        file_type = self.check_file_compatibility(file_id)
        return file_type is not None

    def check_file_compatibility(self, file_id: int) -> Optional[str]:
        file_tree = self.get_file_contents(file_id)
        if not file_tree:
            logger.debug(f'check_file_compatibility: No file tree returned for file_id {file_id}')
            return None
        if not isinstance(file_tree, list):
            logger.warning(f'check_file_compatibility: file_tree is not a list, type: {type(file_tree)}')
            return None
        logger.debug(f'check_file_compatibility: Checking file_id {file_id}, file_tree has {len(file_tree)} items')
        has_deltamod = False
        has_deltahub = False
        for file_name in file_tree:
            if isinstance(file_name, str):
                file_lower = file_name.lower()
                if file_lower == 'mod_config.json' or file_name == 'mod_config.json':
                    has_deltahub = True
                    logger.info(f'check_file_compatibility: Found mod_config.json in file: {file_name}')
                elif '_deltamodinfo.json' in file_lower:
                    has_deltamod = True
                    logger.info(f'check_file_compatibility: Found _deltamodInfo.json in file: {file_name}')
            else:
                logger.debug(f'check_file_compatibility: Skipping non-string item: {type(file_name)}')
        if has_deltahub:
            logger.info(f'check_file_compatibility: File {file_id} is DELTAHUB format (mod_config.json)')
            return 'deltahub'
        elif has_deltamod:
            logger.info(f'check_file_compatibility: File {file_id} is Deltamod format (_deltamodInfo.json)')
            return 'deltamod'
        logger.debug(f'check_file_compatibility: No compatible file found in file_id {file_id}')
        return None

    def find_compatible_file(self, mod_id: int) -> Optional[Dict]:
        files = self.get_mod_files(mod_id)
        if not files:
            logger.debug(f'find_compatible_file: No files found for mod_id {mod_id}')
            return None
        logger.debug(f'find_compatible_file: Checking {len(files)} files for mod_id {mod_id}')
        deltahub_file = None
        deltamod_file = None
        for file_info in files:
            file_id = file_info.get('_idRow')
            if not file_id:
                logger.debug(f'find_compatible_file: File info missing _idRow: {file_info}')
                continue
            has_contents = file_info.get('_bHasContents', False)
            if not has_contents:
                logger.debug(f'find_compatible_file: File {file_id} does not have contents (_bHasContents=False), skipping')
                continue
            logger.debug(f'find_compatible_file: Checking file_id {file_id} for compatibility')
            file_format = self.check_file_compatibility(file_id)
            if file_format == 'deltahub':
                logger.info(f'find_compatible_file: Found DELTAHUB format file {file_id} for mod_id {mod_id}')
                file_info['file_format'] = 'deltahub'
                deltahub_file = file_info
            elif file_format == 'deltamod':
                logger.info(f'find_compatible_file: Found Deltamod format file {file_id} for mod_id {mod_id}')
                file_info['file_format'] = 'deltamod'
                if deltamod_file is None:
                    deltamod_file = file_info
        if deltahub_file:
            logger.info(f'find_compatible_file: Returning DELTAHUB format file for mod_id {mod_id}')
            return deltahub_file
        elif deltamod_file:
            logger.info(f'find_compatible_file: Returning Deltamod format file for mod_id {mod_id}')
            return deltamod_file
        logger.warning(f'find_compatible_file: No compatible file found for mod_id {mod_id}')
        return None

    def search_mods(self, game_id: int, search_string: Optional[str] = None, page: int = 1, per_page: int = 20, sort: str = 'best_match') -> Optional[Dict]:
        url = f'{self.base_url}/Util/Search/Results'
        params = {'_idGameRow': game_id, '_sModelName': 'Mod', '_nPage': page, '_nPerpage': min(per_page, 50), '_sOrder': sort}
        if search_string and len(search_string.strip()) >= 2:
            params['_sSearchString'] = search_string.strip()
        else:
            params['_sSearchString'] = '  '
        try:
            logger.debug(f'search_mods: Requesting URL: {url} with params: {params} for game {game_id}, page {page}, sort={sort}')
            response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
            logger.debug(f'search_mods: Response status: {response.status_code}, URL: {response.url}')
            response.raise_for_status()
            data = response.json()
            records = data.get('_aRecords', [])
            logger.debug(f'search_mods: Got {len(records)} results for game {game_id}, page {page}, sort={sort}')
            return data
        except requests.RequestException as e:
            logger.error(f'Error searching mods for game {game_id}: {e}')
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f'Response status: {e.response.status_code}, response text: {e.response.text[:500]}')
                logger.error(f"Request URL: {(response.url if hasattr(e, 'response') and hasattr(e.response, 'url') else url)}")
            return None
        except Exception as e:
            logger.error(f'Unexpected error searching mods for game {game_id}: {e}', exc_info=True)
            return None

    @staticmethod
    def timestamp_to_date(timestamp: Optional[int]) -> Optional[str]:
        if timestamp is None:
            return None
        try:
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime('%d.%m.%y %H:%M')
        except (ValueError, OSError):
            return None

    @staticmethod
    def extract_screenshots_from_api(screenshots_data: Optional[str]) -> List[str]:
        screenshots = []
        if not screenshots_data or not isinstance(screenshots_data, str):
            return screenshots
        try:
            screenshots_list = json.loads(screenshots_data)
            if not isinstance(screenshots_list, list):
                return screenshots
            base_url = 'https://images.gamebanana.com/img/ss/mods'
            for screenshot_obj in screenshots_list:
                if isinstance(screenshot_obj, dict):
                    file_name = screenshot_obj.get('_sFile') or screenshot_obj.get('_sFile800') or screenshot_obj.get('_sFile530') or screenshot_obj.get('_sFile220')
                    if file_name:
                        screenshot_url = f'{base_url}/{file_name}'
                        screenshots.append(screenshot_url)
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            logger.debug(f'Error parsing screenshots data: {e}')
        return screenshots

    @staticmethod
    def extract_all_screenshots(preview_media: Optional[Dict]) -> List[str]:
        screenshots = []
        if not preview_media:
            return screenshots
        images = preview_media.get('_aImages', [])
        for image in images:
            if isinstance(image, dict) and image.get('_sType') == 'screenshot':
                base_url = image.get('_sBaseUrl', '')
                file_name = image.get('_sFile', '')
                if base_url and file_name:
                    screenshot_url = f'{base_url}/{file_name}'
                    screenshots.append(screenshot_url)
        return screenshots

    @staticmethod
    def extract_icon_url(preview_media: Optional[Dict]) -> Optional[str]:
        if not preview_media:
            return None
        images = preview_media.get('_aImages', [])
        if not images:
            return None
        first_image = images[0]
        base_url = first_image.get('_sBaseUrl', '')
        file_name = first_image.get('_sFile', '')
        if base_url and file_name:
            return f'{base_url}/{file_name}'
        return None

    @staticmethod
    def extract_tags(tags: Optional[List]) -> List[str]:
        if not tags:
            return []
        result = []
        for tag in tags:
            if isinstance(tag, str) and tag:
                result.append(tag)
            elif isinstance(tag, dict) and tag.get('_sRawTag'):
                result.append(tag['_sRawTag'])
        return result

    @staticmethod
    def category_to_tag(category: Optional[str]) -> str:
        if not category:
            return 'other'
        category_lower = category.lower().strip()
        textedit_categories = ['translation', 'text', 'text changes', 'translations', 'text edits']
        gameplay_categories = ['gameplay adjustments', 'fight', 'gameplay', 'difficulty changes', 'multiplayer']
        customization_categories = ['spamton', 'kris', 'jevil', 'ralsei', 'music replacement', 'skins', 'music', 'settings', 'resprites', 'effects', 'custom sprites']
        category_normalized = re.sub('[\\\\/]+', ' ', category_lower)
        categories = category_normalized.split()
        for cat_part in categories:
            cat_part = cat_part.strip()
            if not cat_part:
                continue
            for cat in textedit_categories:
                if cat in cat_part or cat_part in cat:
                    return 'textedit'
            for cat in gameplay_categories:
                if cat in cat_part or cat_part in cat:
                    return 'gameplay'
            for cat in customization_categories:
                if cat in cat_part or cat_part in cat:
                    return 'customization'
        for cat in textedit_categories:
            if cat in category_lower:
                return 'textedit'
        for cat in gameplay_categories:
            if cat in category_lower:
                return 'gameplay'
        for cat in customization_categories:
            if cat in category_lower:
                return 'customization'
        return 'other'

    def _map_mod_data(self, gb_data: Dict, game_name: str) -> Dict[str, Any]:
        mod_id = gb_data.get('_idRow')
        name = gb_data.get('_sName', 'Unknown Mod')
        version = gb_data.get('_sVersion', '') or '1.0.0'
        submitter = gb_data.get('_aSubmitter', {})
        author = submitter.get('_sName', 'Unknown') if isinstance(submitter, dict) else 'Unknown'
        description = gb_data.get('_sDescription', '')
        if description and description.strip() and (len(description.strip()) >= 10):
            tagline = description[:200].strip()
        else:
            tagline = 'No description'
        downloads = 0
        downloads_from_gb = gb_data.get('_nDownloadCount')
        if downloads_from_gb is not None:
            try:
                downloads = int(downloads_from_gb)
            except (ValueError, TypeError):
                downloads = 0
        else:
            downloads = 0
        screenshots = []
        created_timestamp = gb_data.get('_tsDateAdded')
        updated_timestamp = gb_data.get('_tsDateModified')
        created_date = self.timestamp_to_date(created_timestamp) or 'N/A'
        last_updated = self.timestamp_to_date(updated_timestamp) or 'N/A'
        game_version = 'Not specified'
        preview_media = gb_data.get('_aPreviewMedia', {})
        icon_url = self.extract_icon_url(preview_media)
        tags = self.extract_tags(gb_data.get('_aTags', []))
        has_compatible_file = None
        category = None
        gamebanana_category = gb_data.get('_aCategory') or gb_data.get('Category')
        if gamebanana_category:
            if isinstance(gamebanana_category, dict):
                category = gamebanana_category.get('_sName') or gamebanana_category.get('name')
            elif isinstance(gamebanana_category, str):
                category = gamebanana_category
            elif isinstance(gamebanana_category, list) and len(gamebanana_category) > 0:
                category = gamebanana_category[0]
                if isinstance(category, dict):
                    category = category.get('_sName') or category.get('name')
                elif not isinstance(category, str):
                    category = str(category) if category else None
        return {'key': f'gb_{mod_id}', 'name': name, 'version': version, 'author': author, 'tagline': tagline, 'game_version': game_version, 'downloads': downloads, 'created_date': created_date, 'last_updated': last_updated, 'modgame': game_name, 'is_verified': gb_data.get('_bIsVerified', False), 'icon_url': icon_url, 'tags': tags, 'external_url': gb_data.get('_sProfileUrl'), 'screenshots_url': screenshots, 'description_url': gb_data.get('_sTextUrl', ''), 'full_description': None, 'is_gamebanana_mod': True, 'gamebanana_mod_id': str(mod_id), 'gamebanana_mod_type': gb_data.get('_sModelName', 'Mod'), 'gamebanana_last_update_timestamp': updated_timestamp, 'gamebanana_has_compatible_file': has_compatible_file, 'gamebanana_category': category}

    @staticmethod
    def mod_data_dict_to_mod_info(mod_data: Dict[str, Any], game_name: str = 'deltarune') -> Optional[ModInfo]:
        try:
            mod_id = mod_data.get('gamebanana_mod_id')
            if not mod_id:
                return None
            category = mod_data.get('gamebanana_category')
            return ModInfo(key=mod_data.get('key', f'gb_{mod_id}'), name=mod_data.get('name', 'Unknown Mod'), version=mod_data.get('version', '1.0.0'), author=mod_data.get('author', tr('defaults.unknown')), tagline=mod_data.get('tagline', tr('status.no_description_status')), game_version=mod_data.get('game_version', tr('defaults.not_specified')), description_url=mod_data.get('description_url', ''), downloads=mod_data.get('downloads', 0), modgame=mod_data.get('modgame', game_name), is_verified=mod_data.get('is_verified', False), icon_url=mod_data.get('icon_url'), tags=mod_data.get('tags', []), hide_mod=False, is_local_mod=False, ban_status=False, files={}, created_date=mod_data.get('created_date'), last_updated=mod_data.get('last_updated'), external_url=mod_data.get('external_url'), screenshots_url=mod_data.get('screenshots_url', []), full_description=mod_data.get('full_description'), is_gamebanana_mod=True, gamebanana_mod_id=str(mod_id), gamebanana_mod_type=mod_data.get('gamebanana_mod_type', 'Mod'), gamebanana_last_update_timestamp=mod_data.get('gamebanana_last_update_timestamp'), gamebanana_has_compatible_file=mod_data.get('gamebanana_has_compatible_file'), gamebanana_category=category)
        except Exception as e:
            logger.error(f'Error converting mod data to ModInfo: {e}', exc_info=True)
            return None
