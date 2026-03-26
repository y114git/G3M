"""GameBanana API client."""

import json
import logging
import re
import time
from datetime import datetime
from typing import Any

import requests

from config.config import (
    GAMEBANANA_API_BASE,
    GAMEBANANA_TOOL_ID_DELTAHUB,
    GAMEBANANA_TOOL_ID_DELTAMOD,
    NETWORK_TIMEOUT_MEDIUM,
)
from models.game_modes import get_gamebanana_reverse_map
from models.mod_models import ModInfo
from utils.network_utils import get_session

logger = logging.getLogger(__name__)


class GameBananaAPI:
    _compatibility_cache: dict[int, dict[str, Any]] = {}
    _app_state = None

    @classmethod
    def set_app_state(cls, app_state) -> None:
        cls._app_state = app_state

    def __init__(self) -> None:
        self.base_url = GAMEBANANA_API_BASE
        self.core_api_base = "https://api.gamebanana.com"
        self.session = get_session()
        self._last_request_time = 0.0
        self._min_request_interval = 0.2
        self._rate_limit_wait_time = 0.0

    def _reset_rate_limit_state(self):
        if self._app_state and self._app_state.local_config.get(
            "gb_rate_limit_start", 0
        ):
            self._app_state.local_config["gb_rate_limit_start"] = 0
            self._app_state.local_config["gb_rate_limit_notified_this_session"] = False

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

    def _handle_rate_limit_retry(self, status_code, attempt, max_retries, message=""):
        if status_code != 429 or attempt >= max_retries:
            return False
        wait_time = (attempt + 1) * 3
        self._rate_limit_wait_time = max(self._rate_limit_wait_time, wait_time)
        if message:
            logger.warning(message.format(wait_time=wait_time))
        time.sleep(wait_time)
        return True

    def _handle_request_exception(self, e, mod_id=None, operation="operation"):
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        ctx = f" for mod {mod_id}" if mod_id else ""
        if status_code == 400:
            logger.debug(f"{operation}{ctx} failed (400): {e}")
        elif status_code == 429:
            self._rate_limit_wait_time = max(self._rate_limit_wait_time, 5.0)
            logger.warning(f"{operation}{ctx}: Rate limit (429)")
            if self._app_state and not self._app_state.local_config.get(
                "gb_rate_limit_start", 0
            ):
                self._app_state.local_config["gb_rate_limit_start"] = time.time()
                self._app_state.gb_rate_limit_error.emit()
        elif status_code and status_code >= 500:
            logger.error(f"{operation}{ctx}: Server error {status_code}: {e}")
        else:
            logger.warning(f"{operation}{ctx}: {e}")

    def _api_request(
        self,
        url,
        params=None,
        timeout=None,
        max_retries=2,
        operation="API request",
        mod_id=None,
    ):
        for attempt in range(max_retries + 1):
            try:
                self._wait_for_rate_limit()
                response = self.session.get(
                    url, params=params, timeout=timeout or NETWORK_TIMEOUT_MEDIUM
                )
                response.raise_for_status()
                self._reset_rate_limit_state()

                if not response.text or not response.text.strip():
                    if operation in ("get_game_mods", "search_mods"):
                        logger.debug(
                            f"{operation}: Empty response, returning empty result set"
                        )
                        return {}
                    logger.debug(f"{operation} for mod {mod_id}: Empty response")
                    return None
                return response.json()
            except json.JSONDecodeError as e:
                logger.warning(f"{operation} for mod {mod_id}: {e}")
                return None
            except requests.RequestException as e:
                sc = getattr(getattr(e, "response", None), "status_code", None)
                if self._handle_rate_limit_retry(
                    sc,
                    attempt,
                    max_retries,
                    f"{operation}: Rate limit, waiting {{wait_time}}s",
                ):
                    continue
                self._handle_request_exception(e, mod_id, operation)
                return None
            except Exception as e:
                logger.error(f"{operation}: Unexpected error: {e}", exc_info=True)
                return None
        return None

    @staticmethod
    def _normalize_sort(sort: str | None) -> str:
        if sort == "relevant":
            return "default"
        return sort if sort in ("default", "new", "updated") else "default"

    def get_game_mods(
        self,
        game_id,
        page=1,
        per_page=20,
        sort="relevant",
        metadata_cache=None,
        max_retries=2,
        app_state=None,
        search_string: str | None = None,
    ):
        effective_sort = self._normalize_sort(sort)
        params = {
            "_nPage": page,
            "_nPerpage": per_page,
            "_sSort": effective_sort,
            "_csvModelInclusions": "Mod,Wip",
        }
        if search_string and search_string.strip():
            params["_sName"] = search_string.strip()
        data = self._api_request(
            f"{self.base_url}/Game/{game_id}/Subfeed",
            params=params,
            max_retries=max_retries,
            operation="get_game_mods",
        )
        if not isinstance(data, dict):
            return (None, [])
        records = data.get("_aRecords", [])
        game_name = get_gamebanana_reverse_map().get(int(game_id), "deltarune")
        mapped_mods: list[ModInfo] = []
        for record in records:
            model_name = record.get("_sModelName")
            if model_name not in ("Mod", "Wip", "WIP"):
                continue
            mod_info = self._map_mod_data(
                record, game_name, is_wip=model_name in ("Wip", "WIP")
            )
            if mod_info:
                mapped_mods.append(mod_info)
        return (mapped_mods, [])

    def _get_item_field(
        self, mod_id, field_name, extractor_func=None, itemtype="Mod", max_retries=2
    ):
        profile = self.get_mod_profile_page(
            mod_id, itemtype=itemtype, max_retries=max_retries
        )
        if not isinstance(profile, dict):
            return None
        field_map = {
            "downloads": profile.get("_nDownloadCount"),
            "description": profile.get("_sDescription"),
            "text": profile.get("_sText"),
        }
        value = field_map.get(field_name)
        if extractor_func and value is not None:
            try:
                return extractor_func(value)
            except Exception:
                return None
        return value

    def get_mod_downloads_only(self, mod_id, itemtype="Mod", max_retries=2):
        value = self._get_item_field(
            mod_id, "downloads", itemtype=itemtype, max_retries=max_retries
        )
        return self._safe_int(value)

    def _fetch_fields(
        self, mod_id, fields, itemtype="Mod", max_retries=2, timeout=None
    ):
        profile = self.get_mod_profile_page(
            mod_id, itemtype=itemtype, max_retries=max_retries, timeout=timeout
        )
        if not isinstance(profile, dict):
            return None
        result = {}
        for field in fields:
            if field == "text":
                result[field] = profile.get("_sText") or profile.get("_sDescription")
            elif field == "description":
                result[field] = profile.get("_sDescription")
            elif field == "screenshots":
                result[field] = self._extract_preview_urls(
                    profile.get("_aPreviewMedia"), is_wip=itemtype == "Wip"
                )
            else:
                result[field] = profile.get(field)
        return result

    def get_mod_full_details_for_display(self, mod_id, itemtype="Mod", max_retries=2):
        return self._fetch_fields(
            mod_id,
            ("text", "description", "screenshots", "_nDownloadCount"),
            itemtype,
            max_retries,
        )

    def get_mod_profile_page(self, mod_id, itemtype="Mod", max_retries=2, timeout=None):
        data = self._api_request(
            f"{self.base_url}/{itemtype}/{mod_id}/ProfilePage",
            max_retries=max_retries,
            timeout=timeout,
            operation="get_mod_profile_page",
            mod_id=mod_id,
        )
        return data if isinstance(data, dict) else None

    def get_mod_files(self, mod_id, itemtype="Mod", max_retries=2):
        profile = self.get_mod_profile_page(
            mod_id, itemtype=itemtype, max_retries=max_retries
        )
        if not isinstance(profile, dict):
            return None
        profile_files = profile.get("_aFiles", [])
        if isinstance(profile_files, dict):
            return [
                value for value in profile_files.values() if isinstance(value, dict)
            ]
        return (
            [value for value in profile_files if isinstance(value, dict)]
            if isinstance(profile_files, list)
            else None
        )

    def _get_mod_file_compatibility(self, mod_id, itemtype="Mod"):
        cached = self._compatibility_cache.get(mod_id)
        if cached:
            return cached
        compatibility = {
            "supported_files": [],
            "has_supported_files": False,
            "preferred_format": None,
            "tool_ids": set(),
            "has_deltahub_file": False,
            "has_deltamod_file": False,
            "compatibility_checked": False,
        }
        try:
            profile_data = self.get_mod_profile_page(mod_id, itemtype=itemtype) or {}
            profile_files = (
                list(profile_data.get("_aFiles", {}).values())
                if isinstance(profile_data.get("_aFiles"), dict)
                else profile_data.get("_aFiles", [])
            )
            compatibility["compatibility_checked"] = isinstance(profile_files, list)
            for file_entry in profile_files:
                if not isinstance(file_entry, dict) or not (
                    file_id := self._safe_int(file_entry.get("_idRow"))
                ):
                    continue
                file_tool_ids = [
                    self._safe_int(integration.get("_idToolRow"))
                    for integration in file_entry.get("_aModManagerIntegrations", [])
                    if isinstance(integration, dict)
                    and self._safe_int(integration.get("_idToolRow"))
                ]
                file_tool_names = [
                    integration.get("_sName", str(tool_id))
                    for integration in file_entry.get("_aModManagerIntegrations", [])
                    if isinstance(integration, dict)
                    and (tool_id := self._safe_int(integration.get("_idToolRow")))
                ]
                compatibility_label = None
                if GAMEBANANA_TOOL_ID_DELTAHUB in file_tool_ids:
                    compatibility_label = "deltahub"
                    compatibility["has_deltahub_file"] = True
                elif GAMEBANANA_TOOL_ID_DELTAMOD in file_tool_ids:
                    compatibility_label = "deltamod"
                    compatibility["has_deltamod_file"] = True
                if compatibility_label:
                    file_payload = self._build_file_metadata(
                        file_id=file_id,
                        profile_entry=file_entry,
                        details_entry=None,
                        tool_ids=file_tool_ids,
                        tool_names=file_tool_names,
                        compatibility_label=compatibility_label,
                    )
                    compatibility["supported_files"].append(file_payload)
                    compatibility["tool_ids"].update(file_tool_ids)
            if compatibility["supported_files"]:
                compatibility["has_supported_files"] = True
                compatibility["preferred_format"] = (
                    "deltahub"
                    if compatibility["has_deltahub_file"]
                    else ("deltamod" if compatibility["has_deltamod_file"] else None)
                )
            compatibility["tool_ids"] = sorted(compatibility["tool_ids"])
        except Exception as e:
            logger.warning(
                f"_get_mod_file_compatibility: Failed to collect compatibility for mod {mod_id}: {e}",
                exc_info=True,
            )
        self._compatibility_cache[mod_id] = compatibility
        return compatibility

    def get_supported_files_for_mod(
        self, mod_id: int, itemtype: str = "Mod"
    ) -> dict[str, Any]:
        return self._get_mod_file_compatibility(int(mod_id), itemtype=itemtype)

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _first_value(
        entries: list[dict[str, Any] | None], key: str, default: Any = None
    ) -> Any:
        for entry in entries:
            if not entry:
                continue
            value = entry.get(key)
            if value not in (None, ""):
                return value
        return default

    def _build_file_metadata(
        self,
        file_id: int,
        profile_entry: dict[str, Any],
        details_entry: dict[str, Any] | None,
        tool_ids: list[int],
        tool_names: list[str],
        compatibility_label: str,
    ) -> dict[str, Any]:
        sources = [profile_entry, details_entry or {}]
        size_val = self._safe_int(self._first_value(sources, "_nFilesize"))
        timestamp_val = self._safe_int(self._first_value(sources, "_tsDateAdded"))
        download_count = self._safe_int(self._first_value(sources, "_nDownloadCount"))
        return {
            "id": file_id,
            "name": self._first_value(sources, "_sFile", f"file_{file_id}"),
            "version": self._first_value(sources, "_sVersion", "1.0.0"),
            "description": self._first_value(sources, "_sDescription", ""),
            "download_url": self._first_value(sources, "_sDownloadUrl"),
            "size_bytes": size_val or 0,
            "timestamp": timestamp_val,
            "download_count": download_count or 0,
            "md5": self._first_value(sources, "_sMd5Checksum"),
            "analysis_state": self._first_value(sources, "_sAnalysisState"),
            "analysis_result": self._first_value(sources, "_sAnalysisResult"),
            "analysis_result_verbose": self._first_value(
                sources, "_sAnalysisResultVerbose"
            ),
            "av_state": self._first_value(sources, "_sAvState"),
            "av_result": self._first_value(sources, "_sAvResult"),
            "is_archived": bool(self._first_value(sources, "_bIsArchived", False)),
            "has_contents": bool(self._first_value(sources, "_bHasContents", False)),
            "tool_ids": tool_ids,
            "tool_names": tool_names,
            "compatibility": compatibility_label,
        }

    def search_mods(
        self,
        game_id: int,
        search_string: str | None = None,
        page: int = 1,
        per_page: int = 20,
        sort: str = "relevant",
        max_retries: int = 2,
    ) -> dict | None:
        data = self._api_request(
            f"{self.base_url}/Game/{game_id}/Subfeed",
            params={
                "_nPage": page,
                "_nPerpage": per_page,
                "_sSort": self._normalize_sort(sort),
                "_csvModelInclusions": "Mod,Wip",
                "_sName": (search_string or "").strip(),
            },
            max_retries=max_retries,
            operation="search_mods",
        )
        return data if isinstance(data, dict) else None

    @staticmethod
    def timestamp_to_date(timestamp: int | None) -> str | None:
        if timestamp is None:
            return None
        try:
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime("%d.%m.%y %H:%M")
        except (ValueError, OSError):
            return None

    @staticmethod
    def fix_screenshot_urls(screenshots, is_wip: bool = False) -> list | None:
        if not screenshots or not isinstance(screenshots, list) or not is_wip:
            return screenshots
        return [
            u.replace("/img/ss/mods/", "/img/ss/wips/")
            if isinstance(u, str) and "/img/ss/mods/" in u
            else u
            for u in screenshots
        ]

    @staticmethod
    def extract_screenshots_from_api(
        screenshots_data: str | None, is_wip: bool = False
    ) -> list[str]:
        if not screenshots_data or not isinstance(screenshots_data, str):
            return []
        try:
            screenshots_list = json.loads(screenshots_data)
            if not isinstance(screenshots_list, list):
                return []
            base_url = (
                "https://images.gamebanana.com/img/ss/wips"
                if is_wip
                else "https://images.gamebanana.com/img/ss/mods"
            )
            return [
                f"{base_url}/{screenshot_obj.get('_sFile') or screenshot_obj.get('_sFile800') or screenshot_obj.get('_sFile530') or screenshot_obj.get('_sFile220')}"
                for screenshot_obj in screenshots_list
                if isinstance(screenshot_obj, dict)
                and (
                    screenshot_obj.get("_sFile")
                    or screenshot_obj.get("_sFile800")
                    or screenshot_obj.get("_sFile530")
                    or screenshot_obj.get("_sFile220")
                )
            ]
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            logger.debug(f"Error parsing screenshots data: {e}")
            return []

    @staticmethod
    def extract_icon(preview_media) -> str | None:
        if not preview_media:
            return None
        images = preview_media.get("_aImages", [])
        if images and images[0].get("_sBaseUrl") and images[0].get("_sFile"):
            return f"{images[0]['_sBaseUrl']}/{images[0]['_sFile']}"
        return None

    @staticmethod
    def _extract_preview_urls(preview_media, is_wip: bool = False) -> list[str]:
        if not isinstance(preview_media, dict):
            return []
        urls = []
        for image in preview_media.get("_aImages", []) or []:
            if not isinstance(image, dict):
                continue
            base_url = image.get("_sBaseUrl")
            file_name = (
                image.get("_sFile800")
                or image.get("_sFile530")
                or image.get("_sFile220")
                or image.get("_sFile")
                or image.get("_sFile100")
            )
            if base_url and file_name:
                urls.append(f"{base_url}/{file_name}")
        return GameBananaAPI.fix_screenshot_urls(urls, is_wip=is_wip)

    @staticmethod
    def extract_tags(tags) -> list[str]:
        if not tags:
            return []
        return [
            t["_sRawTag"] if isinstance(t, dict) else t
            for t in tags
            if (isinstance(t, str) and t) or (isinstance(t, dict) and t.get("_sRawTag"))
        ]

    _TAG_MAP = [
        (
            "textedit",
            ["text", "text changes", "translations", "text edits"],
        ),
        (
            "gameplay",
            [
                "gameplay adjustments",
                "fight",
                "gameplay",
                "difficulty changes",
                "multiplayer",
                "cyop",
                "afom",
                "towers",
                "levels",
                "extension",
                "full game edit",
                "laps",
                "level edits",
                "rework",
                "ranks",
            ],
        ),
        (
            "customization",
            [
                "spamton",
                "kris",
                "jevil",
                "ralsei",
                "music replacement",
                "skins",
                "music",
                "settings",
                "resprites",
                "effects",
                "custom sprites",
                "tilesets",
                "characters",
                "re-sprites",
                "ui",
                "taunts",
                "titlecard",
            ],
        ),
    ]

    @staticmethod
    def category_to_tag(category) -> str:
        if not category:
            return "other"
        cl = category.lower().strip()
        cn = re.sub(r"[\\/]+", " ", cl)
        for tag, cats in GameBananaAPI._TAG_MAP:
            for part in cn.split():
                if any(c in part or part in c for c in cats):
                    return tag
            if any(c in cl for c in cats):
                return tag
        return "other"

    def _map_mod_data(self, gb_data, game_name, is_wip=False):
        mod_id = gb_data.get("_idRow")
        if not mod_id:
            return None
        submitter = gb_data.get("_aSubmitter", {})
        desc = (gb_data.get("_sDescription", "") or "").strip()
        description = desc[:200] if desc else "No description"
        raw_downloads = gb_data.get("_nDownloadCount")
        try:
            downloads = None if raw_downloads is None else max(int(raw_downloads), 0)
        except (ValueError, TypeError):
            downloads = None
        raw_likes = gb_data.get("_nLikeCount")
        try:
            like_count = None if raw_likes is None else max(int(raw_likes), 0)
        except (ValueError, TypeError):
            like_count = None
        gbc = (
            gb_data.get("_aRootCategory")
            or gb_data.get("_aCategory")
            or gb_data.get("Category")
        )
        category = None
        if gbc:
            if isinstance(gbc, dict):
                category = gbc.get("_sName") or gbc.get("name")
            elif isinstance(gbc, str):
                category = gbc
            elif isinstance(gbc, list) and gbc:
                c = gbc[0]
                category = (
                    (c.get("_sName") or c.get("name"))
                    if isinstance(c, dict)
                    else (c if isinstance(c, str) else str(c) if c else None)
                )
        tags = self.extract_tags(gb_data.get("_aTags", []))
        nsfw_text_values = [
            gb_data.get("_sContentRating"),
            gb_data.get("ContentRating"),
            gb_data.get("MaturityRating"),
            category,
        ]
        is_nsfw = any(
            bool(gb_data.get(field))
            for field in (
                "_bIsNsfw",
                "is_nsfw",
                "IsNsfw",
                "nsfw",
                "adult",
                "is_adult",
                "has_adult_content",
                "_bHasContentRatings",
                "has_content_ratings",
            )
        )
        if not is_nsfw:
            is_nsfw = any(
                ("nsfw" in str(value).casefold())
                or ("adult" in str(value).casefold())
                or ("18+" in str(value).casefold())
                for value in nsfw_text_values
                if value
            )
        if not is_nsfw:
            is_nsfw = any(
                ("nsfw" in str(tag).casefold())
                or ("adult" in str(tag).casefold())
                or ("18+" in str(tag).casefold())
                for tag in tags
            )
        external_url = (
            gb_data.get("_sProfileUrl")
            or f"https://gamebanana.com/{'wips' if is_wip else 'mods'}/{mod_id}"
        )
        preview_media = gb_data.get("_aPreviewMedia", {})
        raw_has_files = gb_data.get("_bHasFiles", True)
        has_files = raw_has_files not in (False, 0, "0", "false", "False", None)
        return ModInfo(
            id=f"gb_{'wip' if is_wip else 'mod'}_{mod_id}",
            name=gb_data.get("_sName", "Unknown Mod"),
            version=gb_data.get("_sVersion", "") or "1.0.0",
            author=submitter.get("_sName", "Unknown")
            if isinstance(submitter, dict)
            else "Unknown",
            description=description,
            game_version="Not specified",
            description_url=gb_data.get("_sTextUrl", ""),
            downloads=downloads,
            game=game_name,
            is_verified=gb_data.get("_bIsVerified", False),
            like_count=like_count,
            icon=self.extract_icon(preview_media),
            tags=tags,
            hide_mod=False,
            ban_status=False,
            is_nsfw=is_nsfw,
            has_files=has_files,
            is_wip=is_wip,
            files={},
            demo_url=None,
            demo_version=None,
            created_date=self.timestamp_to_date(gb_data.get("_tsDateAdded")) or "N/A",
            last_updated=self.timestamp_to_date(
                gb_data.get("_tsDateModified") or gb_data.get("_tsDateUpdated")
            )
            or "N/A",
            external_url=external_url,
            screenshots_url=self._extract_preview_urls(preview_media, is_wip=is_wip),
            full_description=None,
            gamebanana_has_compatible_file=False,
            gamebanana_category=category,
            gamebanana_is_tool_compatible=False,
            gamebanana_supported_files=[],
            gamebanana_supported_tool_ids=[],
            gamebanana_preferred_format=None,
            gamebanana_has_deltahub_file=False,
            gamebanana_has_deltamod_file=False,
            gamebanana_compatibility_checked=False,
            has_full_metadata=True,
        )
