"""GameBanana API client.

This module provides a client for interacting with the GameBanana API to fetch mod data.
"""
import requests
import logging
import json
import re
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from config.constants import GAMEBANANA_API_BASE, GAMEBANANA_GAME_IDS, GAMEBANANA_TOOL_ID_DELTAHUB, GAMEBANANA_TOOL_ID_DELTAMOD, NETWORK_TIMEOUT_MEDIUM, NETWORK_TIMEOUT_SHORT
from utils.network_utils import get_session
from utils.file_utils import check_filename_is_deltamod_info
from models.mod_models import ModInfo
logger = logging.getLogger(__name__)


class GameBananaAPI:

    def __init__(self):
        """Initialize the GameBanana API client."""
        self.base_url = GAMEBANANA_API_BASE
        self.core_api_base = 'https://api.gamebanana.com'
        self.session = get_session()
        self._compatibility_cache: Dict[int, Dict[str, Any]] = {}
        self._last_request_time = 0.0
        self._min_request_interval = 0.2
        self._rate_limit_wait_time = 0.0

    def _wait_for_rate_limit(self):
        """Wait for rate limit cooldown before making next request."""
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        if self._rate_limit_wait_time > 0:
            wait_time = max(self._rate_limit_wait_time, self._min_request_interval - time_since_last)
            if wait_time > 0:
                logger.debug(f'GameBananaAPI: Rate limiting - waiting {wait_time:.2f} seconds')
                time.sleep(wait_time)
                self._rate_limit_wait_time = 0.0
        elif time_since_last < self._min_request_interval:
            wait_time = self._min_request_interval - time_since_last
            time.sleep(wait_time)
        self._last_request_time = time.time()

    def _handle_rate_limit_retry(self, status_code: Optional[int], attempt: int, max_retries: int, message: str) -> bool:
        """Handle rate limit retry logic.

        Args:
            status_code: HTTP status code.
            attempt: Current attempt number.
            max_retries: Maximum retry attempts.
            message: Log message template.

        Returns:
            bool: True if should retry, False otherwise.
        """
        if status_code != 429 or attempt >= max_retries:
            return False
        wait_time = (attempt + 1) * 3
        self._rate_limit_wait_time = max(self._rate_limit_wait_time, wait_time)
        logger.warning(message.format(wait_time=wait_time))
        time.sleep(wait_time)
        return True

    def _handle_request_exception(self, e: Exception, mod_id: Optional[int] = None, operation: str = 'operation') -> None:
        """Handle and log request exceptions.

        Args:
            e: Exception that occurred.
            mod_id: Optional mod ID for context.
            operation: Operation description for logging.
        """
        status_code = getattr(getattr(e, 'response', None), 'status_code', None)
        ctx = f' for mod {mod_id}' if mod_id else ''
        if status_code == 400:
            logger.debug(f'{operation}{ctx} failed (400 Bad Request): {e}')
        elif status_code == 429:
            self._rate_limit_wait_time = max(self._rate_limit_wait_time, 5.0)
            logger.warning(f'{operation}{ctx}: Rate limit (429)')
        elif status_code and status_code >= 500:
            logger.error(f'{operation}{ctx}: Server error {status_code}: {e}')
        else:
            logger.warning(f'{operation}{ctx}: {e}')

    def _api_request(self, url: str, params: Dict = None, timeout: int = None, max_retries: int = 2, operation: str = 'API request', mod_id: Optional[int] = None) -> Optional[Any]:
        """Make an API request with retry logic and rate limiting.

        Args:
            url: API endpoint URL.
            params: Query parameters.
            timeout: Request timeout in seconds.
            max_retries: Maximum retry attempts.
            operation: Operation description for logging.
            mod_id: Optional mod ID for context.

        Returns:
            Optional[Any]: JSON response data or None on error.
        """
        if timeout is None:
            timeout = NETWORK_TIMEOUT_MEDIUM
        for attempt in range(max_retries + 1):
            try:
                self._wait_for_rate_limit()
                response = self.session.get(url, params=params, timeout=timeout)
                response.raise_for_status()
                if not response.text or not response.text.strip():
                    ctx = f' for mod {mod_id}' if mod_id else ''
                    logger.warning(f'{operation}{ctx}: Empty response from API')
                    return None
                return response.json()
            except json.JSONDecodeError as e:
                ctx = f' for mod {mod_id}' if mod_id else ''
                logger.warning(f'{operation}{ctx}: {e}')
                return None
            except requests.RequestException as e:
                status_code = getattr(getattr(e, 'response', None), 'status_code', None)
                if self._handle_rate_limit_retry(status_code, attempt, max_retries, f'{operation}: Rate limit, waiting {{wait_time}}s'):
                    continue
                self._handle_request_exception(e, mod_id, operation)
                return None
            except Exception as e:
                logger.error(f'{operation}: Unexpected error: {e}', exc_info=True)
                return None
        return None

    def get_game_mods(self, game_id: int, page: int = 1, per_page: int = 20, sort: str = 'default', metadata_cache=None, max_retries: int = 2, app_state=None) -> Tuple[Optional[List[ModInfo]], List[str]]:
        """Fetch mods for a specific game from GameBanana.

        Args:
            game_id: GameBanana game ID.
            page: Page number to fetch.
            per_page: Number of mods per page.
            sort: Sort order (default, new, updated).
            metadata_cache: Optional metadata cache.
            max_retries: Maximum retry attempts.
            app_state: Optional application state.

        Returns:
            Tuple[Optional[List[ModInfo]], List[str]]: List of mods and list of mod IDs needing metadata.
        """
        valid_sorts = ['default', 'new', 'updated']
        effective_sort = sort if sort in valid_sorts else 'default'
        url = f'{self.base_url}/Game/{game_id}/Subfeed'
        params = {'_nPage': page, '_nPerpage': per_page, '_sSort': effective_sort, '_csvModelInclusions': 'Mod,Wip'}
        mods_needing_metadata = []
        for attempt in range(max_retries + 1):
            try:
                self._wait_for_rate_limit()
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
                mapped_mods: List[ModInfo] = []
                for record in records:
                    model_name = record.get('_sModelName')
                    if model_name not in ('Mod', 'Wip', 'WIP'):
                        continue
                    mod_id = record.get('_idRow')
                    if mod_id:
                        mod_id_str = str(mod_id)
                        is_wip = model_name in ('Wip', 'WIP')
                        hide_mods_without_files = False
                        if app_state and hasattr(app_state, 'local_config'):
                            hide_mods_without_files = app_state.local_config.get('hide_mods_without_files', False)
                        else:
                            hide_mods_without_files = False
                        if hide_mods_without_files:
                            files_data = record.get('_aFiles')
                            has_files = False
                            if files_data:
                                if isinstance(files_data, dict) and len(files_data) > 0:
                                    has_files = True
                                elif isinstance(files_data, list) and len(files_data) > 0:
                                    has_files = True
                            if not has_files:
                                try:
                                    if is_wip:
                                        external_url = f'https://gamebanana.com/wips/{mod_id}'
                                    else:
                                        external_url = f'https://gamebanana.com/mods/{mod_id}'
                                    files = self.get_mod_files(mod_id, external_url=external_url)
                                    has_files = bool(files and len(files) > 0)
                                except Exception:
                                    has_files = False
                            if not has_files:
                                continue
                        mod_info = self._map_mod_data(record, game_name, is_wip=is_wip)
                        if mod_info:
                            downloads_from_gb = record.get('_nDownloadCount')
                            downloads_value = 0
                            if downloads_from_gb is not None:
                                try:
                                    downloads_value = int(downloads_from_gb)
                                except (ValueError, TypeError):
                                    downloads_value = 0
                            mod_info.downloads = downloads_value
                            cache_valid = False
                            cached_category = None
                            if metadata_cache:
                                cache_valid = metadata_cache.is_valid(mod_id_str)
                                if cache_valid:
                                    cached_downloads = metadata_cache.get_field(mod_id_str, 'downloads')
                                    cached_tagline = metadata_cache.get_field(mod_id_str, 'tagline')
                                    cached_category = metadata_cache.get_field(mod_id_str, 'category')
                                    if cached_downloads is not None and cached_downloads > 0:
                                        mod_info.downloads = cached_downloads
                                    elif downloads_value > 0:
                                        mod_info.downloads = downloads_value
                                    if cached_tagline:
                                        mod_info.tagline = cached_tagline
                                    if cached_category:
                                        mod_info.gamebanana_category = cached_category
                            current_downloads = mod_info.downloads
                            if current_downloads is None:
                                current_downloads = 0
                            else:
                                try:
                                    current_downloads = int(current_downloads)
                                except (ValueError, TypeError):
                                    current_downloads = 0
                            mod_info.downloads = current_downloads
                            current_tagline = mod_info.tagline
                            current_category = mod_info.gamebanana_category
                            needs_downloads = current_downloads == 0 or current_downloads is None
                            needs_tagline = not current_tagline or current_tagline == 'No description' or len(current_tagline) < 10
                            needs_category = not current_category
                            if (needs_downloads or needs_tagline or needs_category) and (not cache_valid):
                                mods_needing_metadata.append(mod_id_str)
                                try:
                                    mod_info.has_full_metadata = False
                                except Exception:
                                    pass
                            else:
                                try:
                                    mod_info.has_full_metadata = True
                                except Exception:
                                    pass
                            mapped_mods.append(mod_info)
                return (mapped_mods, mods_needing_metadata)
            except requests.RequestException as e:
                status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') and e.response else None
                if self._handle_rate_limit_retry(status_code, attempt, max_retries, f'get_game_mods: Rate limit (429) for game {game_id}, waiting {{wait_time}} seconds before retry'):
                    continue
                self._handle_request_exception(e, None, f'Error fetching mods for game {game_id}')
                return (None, [])
            except Exception as e:
                logger.error(f'Unexpected error fetching mods for game {game_id}: {e}')
                return (None, [])
        return (None, [])

    def _get_item_type_from_url(self, external_url: Optional[str] = None) -> str:
        """Determine GameBanana item type from URL.

        Args:
            external_url: Optional external URL.

        Returns:
            str: 'Wip' or 'Mod'.
        """
        if external_url and '/wips/' in external_url:
            return 'Wip'
        return 'Mod'

    def _get_item_field(self, mod_id: int, field_name: str, extractor_func=None, itemtype: Optional[str] = None, external_url: Optional[str] = None, max_retries: int = 2) -> Optional[Any]:
        """Get a specific field from a GameBanana item.

        Args:
            mod_id: GameBanana mod ID.
            field_name: Name of field to retrieve.
            extractor_func: Optional function to extract/transform the value.
            itemtype: Item type (Mod or Wip).
            external_url: Optional external URL.
            max_retries: Maximum retry attempts.

        Returns:
            Optional[Any]: Field value or None.
        """
        url = f'{self.core_api_base}/Core/Item/Data'
        if not itemtype:
            itemtype = self._get_item_type_from_url(external_url)
        params = {'itemtype': itemtype, 'itemid': mod_id, 'fields': field_name}
        for attempt in range(max_retries + 1):
            try:
                self._wait_for_rate_limit()
                logger.debug(f'_get_item_field: Fetching {field_name} for mod {mod_id} (type: {itemtype})')
                response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
                response.raise_for_status()
                if not response.text or not response.text.strip():
                    logger.warning(f'_get_item_field: Empty response for mod {mod_id}, field {field_name} (type: {itemtype})')
                    return None
                data = response.json()
                logger.debug(f'_get_item_field: Got response for mod {mod_id}, field {field_name}, data type: {type(data)}')
                field_value = None
                if isinstance(data, list) and len(data) > 0:
                    field_value = data[0]
                elif isinstance(data, dict):
                    field_value = data.get(field_name) or data.get('name') or data.get('Category().name') or data.get('Category') or data.get('_sName')
                else:
                    field_value = data
                if isinstance(field_value, list):
                    if len(field_value) > 0:
                        first_item = field_value[0]
                        if isinstance(first_item, list) and len(first_item) > 0:
                            field_value = first_item[0]
                        else:
                            field_value = first_item
                    else:
                        field_value = None
                if extractor_func and field_value is not None:
                    try:
                        return extractor_func(field_value)
                    except Exception as e:
                        logger.warning(f'_get_item_field: Extractor function failed for {field_name}: {e}')
                        return None
                return field_value
            except json.JSONDecodeError as e:
                logger.warning(f'Error fetching {field_name} for mod {mod_id}: {e}')
                return None
            except requests.RequestException as e:
                status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') and e.response else None
                if self._handle_rate_limit_retry(status_code, attempt, max_retries, f'_get_item_field: Rate limit (429) for mod {mod_id}, waiting {{wait_time}} seconds before retry'):
                    continue
                self._handle_request_exception(e, mod_id, f'Error fetching {field_name}')
                return None
            except Exception as e:
                logger.error(f'Unexpected error fetching {field_name} for mod {mod_id}: {e}', exc_info=True)
                return None
        return None

    def get_mod_downloads_only(self, mod_id: int, external_url: Optional[str] = None) -> Optional[int]:
        """Get only the download count for a mod.

        Args:
            mod_id: GameBanana mod ID.
            external_url: Optional external URL.

        Returns:
            Optional[int]: Download count or None.
        """

        def extract_downloads(value):
            if isinstance(value, (int, float)):
                return int(value)
            elif isinstance(value, str) and value.strip():
                try:
                    return int(float(value))
                except (ValueError, TypeError):
                    return None
            return None
        result = self._get_item_field(mod_id, 'downloads', extract_downloads, external_url=external_url)
        if result is not None:
            logger.debug(f'get_mod_downloads_only: Successfully got downloads for mod {mod_id}: {result}')
        else:
            logger.warning(f'get_mod_downloads_only: No valid downloads value for mod {mod_id}')
        return result

    def get_mod_description_only(self, mod_id: int, external_url: Optional[str] = None) -> Optional[str]:
        """Get only the description for a mod.

        Args:
            mod_id: GameBanana mod ID.
            external_url: Optional external URL.

        Returns:
            Optional[str]: Description text or None.
        """

        def extract_description(value):
            if isinstance(value, str):
                return value.strip() if value.strip() else None
            elif value is not None:
                return str(value).strip() if str(value).strip() else None
            return None
        result = self._get_item_field(mod_id, 'description', extract_description, external_url=external_url)
        if result:
            logger.debug(f'get_mod_description_only: Successfully got description for mod {mod_id}')
        else:
            logger.debug(f'get_mod_description_only: No valid description value for mod {mod_id}')
        return result

    def get_mod_category_only(self, mod_id: int, external_url: Optional[str] = None) -> Optional[str]:
        """Get only the category for a mod.

        Args:
            mod_id: GameBanana mod ID.
            external_url: Optional external URL.

        Returns:
            Optional[str]: Category name or None.
        """

        def extract_category(value):
            if isinstance(value, str):
                category_value = value.strip()
            elif value is not None:
                category_value = str(value).strip()
            else:
                return None
            if category_value and category_value.lower() not in ('none', 'null', ''):
                return category_value
            return None
        return self._get_item_field(mod_id, 'Category().name', extract_category, external_url=external_url)

    def get_mod_text_and_screenshots(self, mod_id: int, external_url: Optional[str] = None, max_retries: int = 2) -> Optional[Dict]:
        """Get text description and screenshots for a mod.

        Args:
            mod_id: GameBanana mod ID.
            external_url: Optional external URL.
            max_retries: Maximum retry attempts.

        Returns:
            Optional[Dict]: Dictionary with 'text' and 'screenshots' keys or None.
        """
        url = f'{self.core_api_base}/Core/Item/Data'
        itemtype = self._get_item_type_from_url(external_url)
        params = {'itemtype': itemtype, 'itemid': mod_id, 'fields': 'text,screenshots'}
        fields = ('text', 'screenshots')
        for attempt in range(max_retries + 1):
            try:
                self._wait_for_rate_limit()
                logger.debug(f'get_mod_text_and_screenshots: Fetching text and screenshots for mod {mod_id} (type: {itemtype})')
                response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_SHORT)
                response.raise_for_status()
                if not response.text or not response.text.strip():
                    logger.warning(f'get_mod_text_and_screenshots: Empty response for mod {mod_id} (type: {itemtype})')
                    return None
                data = response.json()
                if not data:
                    logger.debug(f'get_mod_text_and_screenshots: Empty response for mod {mod_id}')
                    return None
                logger.debug(f"get_mod_text_and_screenshots: Got response for mod {mod_id}, data type: {type(data)}, length: {(len(data) if isinstance(data, (list, dict)) else 'N/A')}")
                result = {'text': None, 'screenshots': None}
                if isinstance(data, list) and len(data) >= 2:
                    result = self._map_fields_from_list(data, fields)
                elif isinstance(data, list) and len(data) > 0:
                    if isinstance(data[0], dict):
                        logger.debug('get_mod_text_and_screenshots: Response is list with dict at index 0')
                        result = data[0]
                    else:
                        result = self._map_fields_from_list(data, fields)
                elif isinstance(data, dict):
                    logger.debug(f'get_mod_text_and_screenshots: Response is dict, keys: {list(data.keys())}')
                    result['text'] = data.get('text')
                    result['screenshots'] = data.get('screenshots')
                else:
                    logger.warning(f'get_mod_text_and_screenshots: Unexpected response format for mod {mod_id}: {type(data)}, value: {str(data)[:200]}')
                    return None
                logger.debug(f"get_mod_text_and_screenshots: Successfully parsed details for mod {mod_id}, has text: {bool(result.get('text'))}, has screenshots: {result.get('screenshots') is not None}")
                return result
            except json.JSONDecodeError as e:
                logger.warning(f'Error fetching text and screenshots for mod {mod_id}: {e}')
                return None
            except requests.RequestException as e:
                status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') and e.response else None
                if self._handle_rate_limit_retry(status_code, attempt, max_retries, f'get_mod_text_and_screenshots: Rate limit (429) for mod {mod_id}, waiting {{wait_time}} seconds before retry'):
                    continue
                self._handle_request_exception(e, mod_id, 'Error fetching text and screenshots')
                return None
            except Exception as e:
                logger.error(f'Unexpected error fetching text and screenshots for mod {mod_id}: {e}', exc_info=True)
                return None
        return None

    def get_mod_full_details_for_display(self, mod_id: int, external_url: Optional[str] = None, max_retries: int = 2) -> Optional[Dict]:
        """Get full details for displaying a mod (text, description, screenshots).

        Args:
            mod_id: GameBanana mod ID.
            external_url: Optional external URL.
            max_retries: Maximum retry attempts.

        Returns:
            Optional[Dict]: Dictionary with mod details or None.
        """
        url = f'{self.core_api_base}/Core/Item/Data'
        itemtype = self._get_item_type_from_url(external_url)
        params = {'itemtype': itemtype, 'itemid': mod_id, 'fields': 'text,description,screenshots'}
        fields = ('text', 'description', 'screenshots')
        for attempt in range(max_retries + 1):
            try:
                self._wait_for_rate_limit()
                logger.debug(f'get_mod_full_details_for_display: Fetching details for mod {mod_id} (type: {itemtype})')
                response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
                response.raise_for_status()
                if not response.text or not response.text.strip():
                    logger.warning(f'get_mod_full_details_for_display: Empty response for mod {mod_id} (type: {itemtype})')
                    return None
                data = response.json()
                logger.debug(f"get_mod_full_details_for_display: Got response for mod {mod_id}, data type: {type(data)}, length: {(len(data) if isinstance(data, (list, dict)) else 'N/A')}")
                if isinstance(data, list) and len(data) >= 3:
                    result = self._map_fields_from_list(data, fields)
                    logger.debug(f"get_mod_full_details_for_display: Successfully parsed details for mod {mod_id}, has text: {bool(result['text'])}, has description: {bool(result['description'])}, has screenshots: {bool(result['screenshots'])}")
                    return result
                elif isinstance(data, list) and len(data) > 0:
                    if isinstance(data[0], dict):
                        logger.debug('get_mod_full_details_for_display: Response is list with dict at index 0')
                        result = self._map_fields_from_dict(data[0], fields)
                        return result if result else None
                    else:
                        logger.warning(f"get_mod_full_details_for_display: Response is list but has {len(data)} elements (expected 3), first element type: {(type(data[0]) if len(data) > 0 else 'N/A')}")
                        result = self._map_fields_from_list(data, fields)
                        return result if result else None
                elif isinstance(data, dict):
                    logger.debug(f'get_mod_full_details_for_display: Response is dict, keys: {list(data.keys())}')
                    result = self._map_fields_from_dict(data, fields)
                    return result if result else None
                else:
                    logger.warning(f'get_mod_full_details_for_display: Unexpected response format for mod {mod_id}: {type(data)}, value: {str(data)[:200]}')
                    return None
            except json.JSONDecodeError as e:
                logger.warning(f'Error fetching full details for mod {mod_id}: {e}')
                return None
            except requests.RequestException as e:
                status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') and e.response else None
                if self._handle_rate_limit_retry(status_code, attempt, max_retries, f'get_mod_full_details_for_display: Rate limit (429) for mod {mod_id}, waiting {{wait_time}} seconds before retry'):
                    continue
                self._handle_request_exception(e, mod_id, 'Error fetching full details')
                return None
            except Exception as e:
                logger.error(f'Unexpected error fetching full details for mod {mod_id}: {e}', exc_info=True)
                return None
        return None

    def _get_mod_full_details(self, mod_id: int, external_url: Optional[str] = None) -> Optional[Dict]:
        """Internal method to get full mod details.

        Args:
            mod_id: GameBanana mod ID.
            external_url: Optional external URL.

        Returns:
            Optional[Dict]: Dictionary with mod details or None.
        """
        return self.get_mod_full_details_for_display(mod_id, external_url=external_url)

    def get_mod_details(self, mod_id: int, external_url: Optional[str] = None, max_retries: int = 2) -> Optional[Dict]:
        """Get basic mod details from GameBanana.

        Args:
            mod_id: GameBanana mod ID.
            external_url: Optional external URL.
            max_retries: Maximum retry attempts.

        Returns:
            Optional[Dict]: Mod details dictionary or None.
        """
        itemtype = self._get_item_type_from_url(external_url)
        url = f'{self.base_url}/{itemtype}/{mod_id}'
        data = self._api_request(url, max_retries=max_retries, operation='get_mod_details', mod_id=mod_id)
        return data if isinstance(data, dict) else None

    def get_mod_preview_media(self, mod_id: int, external_url: Optional[str] = None, max_retries: int = 2) -> Optional[Dict]:
        """Get preview media for a mod.

        Args:
            mod_id: GameBanana mod ID.
            external_url: Optional external URL.
            max_retries: Maximum retry attempts.

        Returns:
            Optional[Dict]: Preview media data or None.
        """
        itemtype = self._get_item_type_from_url(external_url)
        params = {'itemtype': itemtype, 'itemid': mod_id, 'fields': 'Preview().aPreviewMedia()'}
        data = self._api_request(f'{self.core_api_base}/Core/Item/Data', params, max_retries=max_retries, operation='get_mod_preview_media', mod_id=mod_id)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        return data if isinstance(data, dict) else None

    def get_mod_profile_page(self, mod_id: int, external_url: Optional[str] = None, max_retries: int = 2) -> Optional[Dict]:
        """Get mod profile page data.

        Args:
            mod_id: GameBanana mod ID.
            external_url: Optional external URL.
            max_retries: Maximum retry attempts.

        Returns:
            Optional[Dict]: Profile page data or None.
        """
        itemtype = self._get_item_type_from_url(external_url)
        url = f'{self.base_url}/{itemtype}/{mod_id}/ProfilePage'
        data = self._api_request(url, max_retries=max_retries, operation='get_mod_profile_page', mod_id=mod_id)
        return data if isinstance(data, dict) else None

    def get_mod_files(self, mod_id: int, external_url: Optional[str] = None, max_retries: int = 2) -> Optional[List[Dict]]:
        """Get list of files available for a mod.

        Args:
            mod_id: GameBanana mod ID.
            external_url: Optional external URL.
            max_retries: Maximum retry attempts.

        Returns:
            Optional[List[Dict]]: List of file data dictionaries or None.
        """
        itemtype = self._get_item_type_from_url(external_url)
        params = {'itemtype': itemtype, 'itemid': mod_id, 'fields': 'Files().aFiles()'}
        data = self._api_request(f'{self.core_api_base}/Core/Item/Data', params, max_retries=max_retries, operation='get_mod_files', mod_id=mod_id)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return [v for v in data[0].values() if isinstance(v, dict)] or None
        return None

    def _get_mod_file_compatibility(self, mod_id: int, external_url: Optional[str] = None) -> Dict[str, Any]:
        """Check mod file compatibility with DELTAHUB/DELTAMOD.

        Args:
            mod_id: GameBanana mod ID.
            external_url: Optional external URL.

        Returns:
            Dict[str, Any]: Compatibility information dictionary.
        """
        cached = self._compatibility_cache.get(mod_id)
        if cached:
            return cached
        compatibility: Dict[str, Any] = {'supported_files': [], 'has_supported_files': False, 'preferred_format': None, 'tool_ids': set(), 'has_deltahub_file': False, 'has_deltamod_file': False, 'compatibility_checked': False}
        try:
            profile_data = self.get_mod_profile_page(mod_id, external_url=external_url) or {}
            profile_files = profile_data.get('_aFiles') or []
            if isinstance(profile_files, dict):
                profile_files = list(profile_files.values())
            if isinstance(profile_files, list):
                compatibility['compatibility_checked'] = True
            else:
                profile_files = []
            for file_entry in profile_files:
                if not isinstance(file_entry, dict):
                    continue
                file_id = self._safe_int(file_entry.get('_idRow'))
                if file_id is None:
                    continue
                integrations = file_entry.get('_aModManagerIntegrations') or []
                file_tool_ids: List[int] = []
                file_tool_names: List[str] = []
                for integration in integrations:
                    if not isinstance(integration, dict):
                        continue
                    tool_id = self._safe_int(integration.get('_idToolRow'))
                    if tool_id is None:
                        continue
                    file_tool_ids.append(tool_id)
                    name = integration.get('_sName') or str(tool_id)
                    file_tool_names.append(name)
                compatibility_label = None
                if GAMEBANANA_TOOL_ID_DELTAHUB in file_tool_ids:
                    compatibility_label = 'deltahub'
                    compatibility['has_deltahub_file'] = True
                elif GAMEBANANA_TOOL_ID_DELTAMOD in file_tool_ids:
                    compatibility_label = 'deltamod'
                    compatibility['has_deltamod_file'] = True
                if not compatibility_label:
                    continue
                details_entry = None
                file_payload = self._build_file_metadata(file_id=file_id, profile_entry=file_entry, details_entry=details_entry, tool_ids=file_tool_ids, tool_names=file_tool_names, compatibility_label=compatibility_label)
                compatibility['supported_files'].append(file_payload)
                compatibility['tool_ids'].update(file_tool_ids)
            if compatibility['supported_files']:
                compatibility['has_supported_files'] = True
                if compatibility['has_deltahub_file']:
                    compatibility['preferred_format'] = 'deltahub'
                elif compatibility['has_deltamod_file']:
                    compatibility['preferred_format'] = 'deltamod'
            compatibility['tool_ids'] = sorted(list(compatibility['tool_ids']))
        except Exception as e:
            logger.warning(f'_get_mod_file_compatibility: Failed to collect compatibility for mod {mod_id}: {e}', exc_info=True)
        self._compatibility_cache[mod_id] = compatibility
        return compatibility

    def get_supported_files_for_mod(self, mod_id: int, external_url: Optional[str] = None) -> Dict[str, Any]:
        return self._get_mod_file_compatibility(int(mod_id), external_url=external_url)

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _map_fields_from_list(data: List[Any], fields: Tuple[str, ...]) -> Dict[str, Any]:
        return {field: data[idx] if len(data) > idx else None for idx, field in enumerate(fields)}

    @staticmethod
    def _map_fields_from_dict(data: Dict[str, Any], fields: Tuple[str, ...]) -> Dict[str, Any]:
        return {field: data.get(field) for field in fields if field in data}

    @staticmethod
    def _first_value(entries: List[Optional[Dict[str, Any]]], key: str, default: Any = None) -> Any:
        for entry in entries:
            if not entry:
                continue
            value = entry.get(key)
            if value not in (None, ''):
                return value
        return default

    def _build_file_metadata(self, file_id: int, profile_entry: Dict[str, Any], details_entry: Optional[Dict[str, Any]], tool_ids: List[int], tool_names: List[str], compatibility_label: str) -> Dict[str, Any]:
        sources = [profile_entry, details_entry or {}]
        size_val = self._safe_int(self._first_value(sources, '_nFilesize'))
        timestamp_val = self._safe_int(self._first_value(sources, '_tsDateAdded'))
        download_count = self._safe_int(self._first_value(sources, '_nDownloadCount'))
        return {'id': file_id, 'name': self._first_value(sources, '_sFile', f'file_{file_id}'), 'version': self._first_value(sources, '_sVersion', '1.0.0'), 'description': self._first_value(sources, '_sDescription', ''), 'download_url': self._first_value(sources, '_sDownloadUrl'), 'size_bytes': size_val or 0, 'timestamp': timestamp_val, 'download_count': download_count or 0, 'md5': self._first_value(sources, '_sMd5Checksum'), 'analysis_state': self._first_value(sources, '_sAnalysisState'), 'analysis_result': self._first_value(sources, '_sAnalysisResult'), 'analysis_result_verbose': self._first_value(sources, '_sAnalysisResultVerbose'), 'av_state': self._first_value(sources, '_sAvState'), 'av_result': self._first_value(sources, '_sAvResult'), 'is_archived': bool(self._first_value(sources, '_bIsArchived', False)), 'has_contents': bool(self._first_value(sources, '_bHasContents', False)), 'tool_ids': tool_ids, 'tool_names': tool_names, 'compatibility': compatibility_label}

    def get_file_contents(self, file_id: int, max_retries: int = 2) -> Optional[List[str]]:
        url = f'{self.core_api_base}/Core/Item/Data'
        params = {'itemtype': 'File', 'itemid': file_id, 'fields': 'aFileTree()'}
        for attempt in range(max_retries + 1):
            try:
                self._wait_for_rate_limit()
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
                status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') and e.response else None
                if self._handle_rate_limit_retry(status_code, attempt, max_retries, f'get_file_contents: Rate limit (429) for file_id {file_id}, waiting {{wait_time}} seconds before retry'):
                    continue
                logger.error(f'Error fetching file contents for {file_id}: {e}')
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f'Response status: {e.response.status_code}, response text: {e.response.text[:200]}')
                return None
            except Exception as e:
                logger.error(f'Unexpected error fetching file contents for {file_id}: {e}', exc_info=True)
                return None
        return None

    def check_file_has_deltamodinfo(self, file_id: int) -> bool:
        file_type = self.check_file_compatibility(file_id)
        return file_type is not None

    def check_file_compatibility(self, file_id: int) -> Optional[str]:
        file_tree = self.get_file_contents(file_id)
        if not file_tree or not isinstance(file_tree, list):
            return None
        has_deltahub = any((isinstance(f, str) and f.lower() == 'mod_config.json' for f in file_tree))
        has_deltamod = any((isinstance(f, str) and check_filename_is_deltamod_info(f) for f in file_tree))
        if has_deltahub:
            return 'deltahub'
        if has_deltamod:
            return 'deltamod'
        return None

    def find_compatible_file(self, mod_id: int, external_url: Optional[str] = None) -> Optional[Dict]:
        files = self.get_mod_files(mod_id, external_url=external_url)
        if not files:
            return None
        deltahub_file, deltamod_file = (None, None)
        for file_info in files:
            file_id = file_info.get('_idRow')
            if not file_id or not file_info.get('_bHasContents', False):
                continue
            file_format = self.check_file_compatibility(file_id)
            if file_format == 'deltahub':
                file_info['file_format'] = 'deltahub'
                deltahub_file = file_info
            elif file_format == 'deltamod' and (not deltamod_file):
                file_info['file_format'] = 'deltamod'
                deltamod_file = file_info
        return deltahub_file or deltamod_file

    def search_mods(self, game_id: int, search_string: Optional[str] = None, page: int = 1, per_page: int = 20, sort: str = 'best_match', max_retries: int = 2) -> Optional[Dict]:
        url = f'{self.base_url}/Util/Search/Results'
        search_str = search_string.strip() if search_string and len(search_string.strip()) >= 2 else '  '
        per_page_limit = min(per_page, 50)
        all_records = []
        all_data = {}
        for model_type in ['Mod', 'Wip']:
            params = {'_idGameRow': game_id, '_sModelName': model_type, '_nPage': page, '_nPerpage': per_page_limit, '_sOrder': sort, '_sSearchString': search_str}
            for attempt in range(max_retries + 1):
                try:
                    self._wait_for_rate_limit()
                    logger.debug(f'search_mods: Requesting {model_type} URL: {url} with params: {params} for game {game_id}, page {page}, sort={sort}')
                    response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
                    logger.debug(f'search_mods: {model_type} response status: {response.status_code}, URL: {response.url}')
                    response.raise_for_status()
                    data = response.json()
                    records = data.get('_aRecords', [])
                    logger.debug(f'search_mods: Got {len(records)} {model_type} results for game {game_id}, page {page}, sort={sort}')
                    all_records.extend(records)
                    if not all_data:
                        all_data = data.copy()
                    break
                except requests.RequestException as e:
                    status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') and e.response else None
                    if self._handle_rate_limit_retry(status_code, attempt, max_retries, f'search_mods: Rate limit (429) for {model_type} game {game_id}, waiting {{wait_time}} seconds before retry'):
                        continue
                    logger.error(f'Error searching {model_type} mods for game {game_id}: {e}')
                    if hasattr(e, 'response') and e.response is not None:
                        logger.error(f'Response status: {e.response.status_code}, response text: {e.response.text[:500]}')
                    break
                except Exception as e:
                    logger.error(f'Unexpected error searching {model_type} mods for game {game_id}: {e}', exc_info=True)
                    break
        if all_data:
            all_data['_aRecords'] = all_records
            if '_nRecordCount' in all_data:
                all_data['_nRecordCount'] = len(all_records)
            logger.debug(f'search_mods: Combined {len(all_records)} total results (Mod + Wip) for game {game_id}, page {page}, sort={sort}')
            return all_data
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
    def fix_screenshot_urls(screenshots: list, external_url: Optional[str] = None) -> list:
        if not screenshots or not isinstance(screenshots, list):
            return screenshots
        is_wip = external_url and '/wips/' in external_url
        if not is_wip:
            return screenshots
        fixed_screenshots = []
        for url in screenshots:
            if isinstance(url, str):
                if '/img/ss/mods/' in url:
                    fixed_url = url.replace('/img/ss/mods/', '/img/ss/wips/')
                    fixed_screenshots.append(fixed_url)
                else:
                    fixed_screenshots.append(url)
            else:
                fixed_screenshots.append(url)
        return fixed_screenshots

    @staticmethod
    def extract_screenshots_from_api(screenshots_data: Optional[str], external_url: Optional[str] = None) -> List[str]:
        screenshots = []
        if not screenshots_data or not isinstance(screenshots_data, str):
            return screenshots
        try:
            screenshots_list = json.loads(screenshots_data)
            if not isinstance(screenshots_list, list):
                return screenshots
            is_wip = external_url and '/wips/' in external_url
            base_url = 'https://images.gamebanana.com/img/ss/wips' if is_wip else 'https://images.gamebanana.com/img/ss/mods'
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
        gameplay_categories = ['gameplay adjustments', 'fight', 'gameplay', 'difficulty changes', 'multiplayer', 'cyop', 'afom', 'towers', 'levels', 'extension', 'full game edit', 'laps', 'level edits', 'rework', 'ranks']
        customization_categories = ['spamton', 'kris', 'jevil', 'ralsei', 'music replacement', 'skins', 'music', 'settings', 'resprites', 'effects', 'custom sprites', 'tilesets', 'characters', 're-sprites', 'ui', 'taunts', 'titlecard']
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

    def _map_mod_data(self, gb_data: Dict, game_name: str, is_wip: bool = False) -> Optional[ModInfo]:
        mod_id = gb_data.get('_idRow')
        if not mod_id:
            return None
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
        external_url = gb_data.get('_sProfileUrl')
        if not external_url and mod_id:
            if is_wip:
                external_url = f'https://gamebanana.com/wips/{mod_id}'
            else:
                external_url = f'https://gamebanana.com/mods/{mod_id}'
        return ModInfo(key=f'gb_{mod_id}', name=name, version=version, author=author, tagline=tagline, game_version=game_version, downloads=downloads, created_date=created_date, last_updated=last_updated, game=game_name, is_verified=gb_data.get('_bIsVerified', False), icon_url=icon_url, tags=tags, external_url=external_url, screenshots_url=screenshots, description_url=gb_data.get('_sTextUrl', ''), full_description=None, gamebanana_has_compatible_file=False, gamebanana_category=category, gamebanana_is_tool_compatible=False, gamebanana_supported_files=[], gamebanana_supported_tool_ids=[], gamebanana_preferred_format=None, gamebanana_has_deltahub_file=False, gamebanana_has_deltamod_file=False, gamebanana_compatibility_checked=False)

    @staticmethod
    def mod_data_dict_to_mod_info(mod_data: Dict[str, Any], game_name: str = 'deltarune') -> Optional[ModInfo]:
        try:
            key = mod_data.get('key') or mod_data.get('mod_key')
            if not key or not key.startswith('gb_'):
                return None
            mod_id = key.replace('gb_', '', 1)
            if not mod_id:
                return None
            data_dict = mod_data.copy()
            if 'key' not in data_dict and 'mod_key' not in data_dict:
                data_dict['key'] = key
            if 'game' not in data_dict and 'modgame' not in data_dict:
                data_dict['game'] = game_name
            data_dict['hide_mod'] = False
            data_dict['ban_status'] = False
            data_dict['files'] = {}
            if 'has_full_metadata' not in data_dict:
                data_dict['has_full_metadata'] = True
            return ModInfo.from_dict(data_dict)
        except Exception as e:
            logger.error(f'Error converting mod data to ModInfo: {e}', exc_info=True)
            return None
