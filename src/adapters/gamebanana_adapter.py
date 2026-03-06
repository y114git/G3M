"""GameBanana API client."""
import requests
import logging
import json
import re
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from config.constants import GAMEBANANA_API_BASE, GAMEBANANA_GAME_IDS, GAMEBANANA_TOOL_ID_DELTAHUB, GAMEBANANA_TOOL_ID_DELTAMOD, NETWORK_TIMEOUT_MEDIUM, NETWORK_TIMEOUT_SHORT
from utils.network_utils import get_session
from models.mod_models import ModInfo
logger = logging.getLogger(__name__)


class GameBananaAPI:
    _compatibility_cache: Dict[int, Dict[str, Any]] = {}
    _app_state = None

    @classmethod
    def set_app_state(cls, app_state):
        cls._app_state = app_state

    def __init__(self):
        self.base_url = GAMEBANANA_API_BASE
        self.core_api_base = 'https://api.gamebanana.com'
        self.session = get_session()
        self._last_request_time = 0.0
        self._min_request_interval = 0.2
        self._rate_limit_wait_time = 0.0

    def _reset_rate_limit_state(self):
        if self._app_state and self._app_state.local_config.get('gb_rate_limit_start', 0):
            self._app_state.local_config['gb_rate_limit_start'] = 0
            self._app_state.local_config['gb_rate_limit_notified_this_session'] = False

    def _wait_for_rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if self._rate_limit_wait_time > 0:
            wait = max(self._rate_limit_wait_time, self._min_request_interval - elapsed)
            if wait > 0:
                time.sleep(wait)
                self._rate_limit_wait_time = 0.0
        elif elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _handle_rate_limit_retry(self, status_code, attempt, max_retries, message=''):
        if status_code != 429 or attempt >= max_retries:
            return False
        wait_time = (attempt + 1) * 3
        self._rate_limit_wait_time = max(self._rate_limit_wait_time, wait_time)
        if message:
            logger.warning(message.format(wait_time=wait_time))
        time.sleep(wait_time)
        return True

    def _handle_request_exception(self, e, mod_id=None, operation='operation'):
        status_code = getattr(getattr(e, 'response', None), 'status_code', None)
        ctx = f' for mod {mod_id}' if mod_id else ''
        if status_code == 400:
            logger.debug(f'{operation}{ctx} failed (400): {e}')
        elif status_code == 429:
            self._rate_limit_wait_time = max(self._rate_limit_wait_time, 5.0)
            logger.warning(f'{operation}{ctx}: Rate limit (429)')
            if self._app_state and not self._app_state.local_config.get('gb_rate_limit_start', 0):
                self._app_state.local_config['gb_rate_limit_start'] = time.time()
                self._app_state.gb_rate_limit_error.emit()
        elif status_code and status_code >= 500:
            logger.error(f'{operation}{ctx}: Server error {status_code}: {e}')
        else:
            logger.warning(f'{operation}{ctx}: {e}')

    def _api_request(self, url, params=None, timeout=None, max_retries=2, operation='API request', mod_id=None):
        for attempt in range(max_retries + 1):
            try:
                self._wait_for_rate_limit()
                response = self.session.get(url, params=params, timeout=timeout or NETWORK_TIMEOUT_MEDIUM)
                response.raise_for_status()
                self._reset_rate_limit_state()

                if not response.text or not response.text.strip():
                    logger.warning(f'{operation} for mod {mod_id}: Empty response')
                    return None
                return response.json()
            except json.JSONDecodeError as e:
                logger.warning(f'{operation} for mod {mod_id}: {e}')
                return None
            except requests.RequestException as e:
                sc = getattr(getattr(e, 'response', None), 'status_code', None)
                if self._handle_rate_limit_retry(sc, attempt, max_retries, f'{operation}: Rate limit, waiting {{wait_time}}s'):
                    continue
                self._handle_request_exception(e, mod_id, operation)
                return None
            except Exception as e:
                logger.error(f'{operation}: Unexpected error: {e}', exc_info=True)
                return None
        return None

    def get_game_mods(self, game_id, page=1, per_page=20, sort='default', metadata_cache=None, max_retries=2, app_state=None):
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
                self._reset_rate_limit_state()
                data = response.json()
                records = data.get('_aRecords', [])
                game_name = next((n for n, v in GAMEBANANA_GAME_IDS.items() if v == game_id), 'deltarune')
                mapped_mods: List[ModInfo] = []
                for record in records:
                    model_name = record.get('_sModelName')
                    if model_name not in ('Mod', 'Wip', 'WIP'):
                        continue
                    mod_id = record.get('_idRow')
                    if mod_id:
                        mod_id_str = str(mod_id)
                        is_wip = model_name in ('Wip', 'WIP')
                        hide_wips = getattr(app_state, 'local_config', {}).get('hide_wips_without_downloads', False) if app_state else False
                        if hide_wips and is_wip:
                            try:
                                if not int(record.get('_nDownloadCount') or 0):
                                    continue
                            except (ValueError, TypeError):
                                continue
                        mod_info = self._map_mod_data(record, game_name, is_wip=is_wip)
                        if mod_info:
                            raw_downloads = record.get('_nDownloadCount')
                            try:
                                mod_info.downloads = None if raw_downloads is None else max(int(raw_downloads), 0)
                            except (ValueError, TypeError):
                                mod_info.downloads = None
                            downloads_value = mod_info.downloads
                            cache_valid = False
                            cached_category = None
                            if metadata_cache:
                                cache_valid = metadata_cache.is_valid(mod_id_str)
                                if cache_valid:
                                    cached_downloads = metadata_cache.get_field(mod_id_str, 'downloads')
                                    cached_tagline = metadata_cache.get_field(mod_id_str, 'tagline')
                                    cached_category = metadata_cache.get_field(mod_id_str, 'category')
                                    if cached_downloads is not None:
                                        mod_info.downloads = cached_downloads
                                    elif downloads_value is not None:
                                        mod_info.downloads = downloads_value
                                    if cached_tagline:
                                        mod_info.tagline = cached_tagline
                                    if cached_category:
                                        mod_info.gamebanana_category = cached_category
                            try:
                                current_downloads = None if mod_info.downloads is None else max(int(mod_info.downloads), 0)
                            except (ValueError, TypeError):
                                current_downloads = None
                            mod_info.downloads = current_downloads
                            needs_meta = ((current_downloads is None) or (not mod_info.tagline or mod_info.tagline == 'No description' or len(mod_info.tagline) < 10) or (not mod_info.gamebanana_category)) and not cache_valid
                            if needs_meta:
                                mods_needing_metadata.append(mod_id_str)
                            mod_info.has_full_metadata = not needs_meta
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

    def _get_item_type_from_url(self, external_url=None):
        return 'Wip' if external_url and '/wips/' in external_url else 'Mod'

    def _get_item_field(self, mod_id, field_name, extractor_func=None, itemtype=None, external_url=None, max_retries=2):
        itemtype = itemtype or self._get_item_type_from_url(external_url)
        params = {'itemtype': itemtype, 'itemid': mod_id, 'fields': field_name}
        for attempt in range(max_retries + 1):
            try:
                self._wait_for_rate_limit()
                response = self.session.get(f'{self.core_api_base}/Core/Item/Data', params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
                response.raise_for_status()
                self._reset_rate_limit_state()
                if not response.text or not response.text.strip():
                    return None
                data = response.json()
                if isinstance(data, list) and data:
                    fv = data[0]
                elif isinstance(data, dict):
                    fv = data.get(field_name) or data.get('name') or data.get('Category().name') or data.get('Category') or data.get('_sName')
                else:
                    fv = data
                if isinstance(fv, list):
                    fv = (fv[0][0] if isinstance(fv[0], list) and fv[0] else fv[0]) if fv else None
                if extractor_func and fv is not None:
                    try:
                        return extractor_func(fv)
                    except Exception:
                        return None
                return fv
            except json.JSONDecodeError:
                return None
            except requests.RequestException as e:
                sc = getattr(getattr(e, 'response', None), 'status_code', None)
                if self._handle_rate_limit_retry(sc, attempt, max_retries):
                    continue
                self._handle_request_exception(e, mod_id, f'_get_item_field({field_name})')
                return None
            except Exception as e:
                logger.error(f'_get_item_field({field_name}) for mod {mod_id}: {e}', exc_info=True)
                return None
        return None

    @staticmethod
    def _extract_int(value):
        try:
            return int(value) if isinstance(value, (int, float)) else int(float(value)) if isinstance(value, str) and value.strip() else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _extract_str(value):
        s = (value if isinstance(value, str) else str(value) if value is not None else '').strip()
        return s or None

    @staticmethod
    def _extract_category(value):
        s = (value if isinstance(value, str) else str(value) if value is not None else '').strip()
        return s if s and s.lower() not in ('none', 'null', '') else None

    def get_mod_downloads_only(self, mod_id, external_url=None):
        return self._get_item_field(mod_id, 'downloads', self._extract_int, external_url=external_url)

    def get_mod_description_only(self, mod_id, external_url=None):
        return self._get_item_field(mod_id, 'description', self._extract_str, external_url=external_url)

    def get_mod_category_only(self, mod_id, external_url=None):
        return self._get_item_field(mod_id, 'Category().name', self._extract_category, external_url=external_url)

    def _fetch_fields(self, mod_id, fields, external_url=None, max_retries=2, timeout=None):
        """Shared helper for fetching multiple fields from Core/Item/Data."""
        itemtype = self._get_item_type_from_url(external_url)
        params = {'itemtype': itemtype, 'itemid': mod_id, 'fields': ','.join(fields)}
        for attempt in range(max_retries + 1):
            try:
                self._wait_for_rate_limit()
                response = self.session.get(f'{self.core_api_base}/Core/Item/Data', params=params, timeout=timeout or NETWORK_TIMEOUT_MEDIUM)
                response.raise_for_status()
                self._reset_rate_limit_state()
                if not response.text or not response.text.strip():
                    return None
                data = response.json()
                if not data:
                    return None
                if isinstance(data, list):
                    return self._map_fields_from_list(data, fields) if len(data) >= len(fields) else (data[0] if isinstance(data[0], dict) else self._map_fields_from_list(data, fields))
                if isinstance(data, dict):
                    return self._map_fields_from_dict(data, fields) or {f: data.get(f) for f in fields}
                return None
            except (json.JSONDecodeError, requests.RequestException, Exception) as e:
                if isinstance(e, requests.RequestException):
                    sc = getattr(getattr(e, 'response', None), 'status_code', None)
                    if self._handle_rate_limit_retry(sc, attempt, max_retries):
                        continue
                    self._handle_request_exception(e, mod_id, f'_fetch_fields({",".join(fields)})')
                elif isinstance(e, Exception):
                    logger.error(f'_fetch_fields for mod {mod_id}: {e}', exc_info=True)
                return None
        return None

    def get_mod_text_and_screenshots(self, mod_id, external_url=None, max_retries=2):
        return self._fetch_fields(mod_id, ('text', 'screenshots'), external_url, max_retries, NETWORK_TIMEOUT_SHORT)

    def get_mod_full_details_for_display(self, mod_id, external_url=None, max_retries=2):
        return self._fetch_fields(mod_id, ('text', 'description', 'screenshots'), external_url, max_retries)

    def get_mod_details(self, mod_id, external_url=None, max_retries=2):
        itemtype = self._get_item_type_from_url(external_url)
        data = self._api_request(f'{self.base_url}/{itemtype}/{mod_id}', max_retries=max_retries, operation='get_mod_details', mod_id=mod_id)
        return data if isinstance(data, dict) else None

    def get_mod_preview_media(self, mod_id, external_url=None, max_retries=2):
        itemtype = self._get_item_type_from_url(external_url)
        params = {'itemtype': itemtype, 'itemid': mod_id, 'fields': 'Preview().aPreviewMedia()'}
        data = self._api_request(f'{self.core_api_base}/Core/Item/Data', params, max_retries=max_retries, operation='get_mod_preview_media', mod_id=mod_id)
        return data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else (data if isinstance(data, dict) else None)

    def get_mod_profile_page(self, mod_id, external_url=None, max_retries=2):
        itemtype = self._get_item_type_from_url(external_url)
        data = self._api_request(f'{self.base_url}/{itemtype}/{mod_id}/ProfilePage', max_retries=max_retries, operation='get_mod_profile_page', mod_id=mod_id)
        return data if isinstance(data, dict) else None

    def get_mod_files(self, mod_id, external_url=None, max_retries=2):
        itemtype = self._get_item_type_from_url(external_url)
        params = {'itemtype': itemtype, 'itemid': mod_id, 'fields': 'Files().aFiles()'}
        data = self._api_request(f'{self.core_api_base}/Core/Item/Data', params, max_retries=max_retries, operation='get_mod_files', mod_id=mod_id)
        return [v for v in data[0].values() if isinstance(v, dict)] or None if isinstance(data, list) and data and isinstance(data[0], dict) else None

    def _get_mod_file_compatibility(self, mod_id, external_url=None):
        cached = self._compatibility_cache.get(mod_id)
        if cached:
            return cached
        compatibility = {'supported_files': [], 'has_supported_files': False, 'preferred_format': None, 'tool_ids': set(), 'has_deltahub_file': False, 'has_deltamod_file': False, 'compatibility_checked': False}
        try:
            profile_data = self.get_mod_profile_page(mod_id, external_url=external_url) or {}
            profile_files = list(profile_data.get('_aFiles', {}).values()) if isinstance(profile_data.get('_aFiles'), dict) else profile_data.get('_aFiles', [])
            compatibility['compatibility_checked'] = isinstance(profile_files, list)
            for file_entry in profile_files:
                if not isinstance(file_entry, dict) or not (file_id := self._safe_int(file_entry.get('_idRow'))):
                    continue
                file_tool_ids = [self._safe_int(integration.get('_idToolRow')) for integration in file_entry.get('_aModManagerIntegrations', []) if isinstance(integration, dict) and self._safe_int(integration.get('_idToolRow'))]
                file_tool_names = [integration.get('_sName', str(tool_id)) for integration in file_entry.get('_aModManagerIntegrations', []) if isinstance(integration, dict) and (tool_id := self._safe_int(integration.get('_idToolRow')))]
                compatibility_label = None
                if GAMEBANANA_TOOL_ID_DELTAHUB in file_tool_ids:
                    compatibility_label = 'deltahub'
                    compatibility['has_deltahub_file'] = True
                elif GAMEBANANA_TOOL_ID_DELTAMOD in file_tool_ids:
                    compatibility_label = 'deltamod'
                    compatibility['has_deltamod_file'] = True
                if compatibility_label:
                    file_payload = self._build_file_metadata(file_id=file_id, profile_entry=file_entry, details_entry=None, tool_ids=file_tool_ids, tool_names=file_tool_names, compatibility_label=compatibility_label)
                    compatibility['supported_files'].append(file_payload)
                    compatibility['tool_ids'].update(file_tool_ids)
            if compatibility['supported_files']:
                compatibility['has_supported_files'] = True
                compatibility['preferred_format'] = 'deltahub' if compatibility['has_deltahub_file'] else ('deltamod' if compatibility['has_deltamod_file'] else None)
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

    def get_file_contents(self, file_id, max_retries=2):
        params = {'itemtype': 'File', 'itemid': file_id, 'fields': 'aFileTree()'}
        data = self._api_request(f'{self.core_api_base}/Core/Item/Data', params, max_retries=max_retries, operation='get_file_contents', mod_id=file_id)
        if data is None:
            return None
        ft = data[0] if isinstance(data, list) and data else data
        if isinstance(ft, dict):
            return [v for k, v in ft.items() if isinstance(v, str) and k not in ('screenshots', 'folders')] or None
        if isinstance(ft, list):
            return ft if (not ft or isinstance(ft[0], str)) else (ft[0] if isinstance(ft[0], list) else None)
        return None

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
                    response = self.session.get(url, params=params, timeout=NETWORK_TIMEOUT_MEDIUM)
                    response.raise_for_status()
                    self._reset_rate_limit_state()
                    data = response.json()
                    all_records.extend(data.get('_aRecords', []))
                    if not all_data:
                        all_data = data.copy()
                    break
                except requests.RequestException as e:
                    status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') and e.response else None
                    if self._handle_rate_limit_retry(status_code, attempt, max_retries):
                        continue
                    self._handle_request_exception(e, None, f'search_mods({model_type})')
                    break
                except Exception as e:
                    logger.error(f'search_mods({model_type}) for game {game_id}: {e}', exc_info=True)
                    break
        if all_data:
            all_data['_aRecords'] = all_records
            if '_nRecordCount' in all_data:
                all_data['_nRecordCount'] = len(all_records)
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
    def fix_screenshot_urls(screenshots, external_url=None):
        if not screenshots or not isinstance(screenshots, list) or not (external_url and '/wips/' in external_url):
            return screenshots
        return [u.replace('/img/ss/mods/', '/img/ss/wips/') if isinstance(u, str) and '/img/ss/mods/' in u else u for u in screenshots]

    @staticmethod
    def extract_screenshots_from_api(screenshots_data: Optional[str], external_url: Optional[str] = None) -> List[str]:
        if not screenshots_data or not isinstance(screenshots_data, str):
            return []
        try:
            screenshots_list = json.loads(screenshots_data)
            if not isinstance(screenshots_list, list):
                return []
            is_wip = external_url and '/wips/' in external_url
            base_url = 'https://images.gamebanana.com/img/ss/wips' if is_wip else 'https://images.gamebanana.com/img/ss/mods'
            return [f'{base_url}/{screenshot_obj.get("_sFile") or screenshot_obj.get("_sFile800") or screenshot_obj.get("_sFile530") or screenshot_obj.get("_sFile220")}' for screenshot_obj in screenshots_list if isinstance(screenshot_obj, dict) and (screenshot_obj.get('_sFile') or screenshot_obj.get('_sFile800') or screenshot_obj.get('_sFile530') or screenshot_obj.get('_sFile220'))]
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            logger.debug(f'Error parsing screenshots data: {e}')
            return []

    @staticmethod
    def extract_icon_url(preview_media):
        if not preview_media:
            return None
        images = preview_media.get('_aImages', [])
        if images and images[0].get('_sBaseUrl') and images[0].get('_sFile'):
            return f"{images[0]['_sBaseUrl']}/{images[0]['_sFile']}"
        return None

    @staticmethod
    def extract_tags(tags):
        if not tags:
            return []
        return [t['_sRawTag'] if isinstance(t, dict) else t for t in tags if (isinstance(t, str) and t) or (isinstance(t, dict) and t.get('_sRawTag'))]

    _TAG_MAP = [
        ('textedit', ['translation', 'text', 'text changes', 'translations', 'text edits']),
        ('gameplay', ['gameplay adjustments', 'fight', 'gameplay', 'difficulty changes', 'multiplayer', 'cyop', 'afom', 'towers', 'levels', 'extension', 'full game edit', 'laps', 'level edits', 'rework', 'ranks']),
        ('customization', ['spamton', 'kris', 'jevil', 'ralsei', 'music replacement', 'skins', 'music', 'settings', 'resprites', 'effects', 'custom sprites', 'tilesets', 'characters', 're-sprites', 'ui', 'taunts', 'titlecard']),
    ]

    @staticmethod
    def category_to_tag(category):
        if not category:
            return 'other'
        cl = category.lower().strip()
        cn = re.sub(r'[\\/]+', ' ', cl)
        for tag, cats in GameBananaAPI._TAG_MAP:
            for part in cn.split():
                if any(c in part or part in c for c in cats):
                    return tag
            if any(c in cl for c in cats):
                return tag
        return 'other'

    def _map_mod_data(self, gb_data, game_name, is_wip=False):
        mod_id = gb_data.get('_idRow')
        if not mod_id:
            return None
        submitter = gb_data.get('_aSubmitter', {})
        desc = (gb_data.get('_sDescription', '') or '').strip()
        tagline = desc[:200] if desc and len(desc) >= 10 else 'No description'
        raw_downloads = gb_data.get('_nDownloadCount')
        try:
            downloads = None if raw_downloads is None else max(int(raw_downloads), 0)
        except (ValueError, TypeError):
            downloads = None
        gbc = gb_data.get('_aCategory') or gb_data.get('Category')
        category = None
        if gbc:
            if isinstance(gbc, dict):
                category = gbc.get('_sName') or gbc.get('name')
            elif isinstance(gbc, str):
                category = gbc
            elif isinstance(gbc, list) and gbc:
                c = gbc[0]
                category = (c.get('_sName') or c.get('name')) if isinstance(c, dict) else (c if isinstance(c, str) else str(c) if c else None)
        external_url = gb_data.get('_sProfileUrl') or f"https://gamebanana.com/{'wips' if is_wip else 'mods'}/{mod_id}"
        return ModInfo(key=f'gb_{mod_id}', name=gb_data.get('_sName', 'Unknown Mod'), version=gb_data.get('_sVersion', '') or '1.0.0', author=submitter.get('_sName', 'Unknown') if isinstance(submitter, dict) else 'Unknown', tagline=tagline, game_version='Not specified', downloads=downloads, created_date=self.timestamp_to_date(gb_data.get('_tsDateAdded')) or 'N/A', last_updated=self.timestamp_to_date(gb_data.get('_tsDateModified')) or 'N/A', game=game_name, is_verified=gb_data.get('_bIsVerified', False), icon_url=self.extract_icon_url(gb_data.get('_aPreviewMedia', {})), tags=self.extract_tags(gb_data.get('_aTags', [])), external_url=external_url, screenshots_url=[], description_url=gb_data.get('_sTextUrl', ''), full_description=None, gamebanana_has_compatible_file=False, gamebanana_category=category, gamebanana_is_tool_compatible=False, gamebanana_supported_files=[], gamebanana_supported_tool_ids=[], gamebanana_preferred_format=None, gamebanana_has_deltahub_file=False, gamebanana_has_deltamod_file=False, gamebanana_compatibility_checked=False)
