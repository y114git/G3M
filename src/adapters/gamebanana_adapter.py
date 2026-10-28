"""GameBanana API client."""

import json
import logging
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from config.config import (
    GAMEBANANA_API_BASE,
    GAMEBANANA_TOOL_ID_DELTAMOD,
    GAMEBANANA_TOOL_ID_G3M,
    MOD_CATALOG_URL,
    NETWORK_TIMEOUT_MEDIUM,
    NETWORK_TIMEOUT_SHORT,
)
from models.exceptions import AppError
from models.game_modes import get_gamebanana_reverse_map
from models.mod_models import BrowserModInfo
from utils.mod.tags import normalize_tag
from utils.network_utils import get_session

logger = logging.getLogger(__name__)

_G3M_LIST_TTL_SECONDS = 30
_G3M_LIST_TIMEOUT = (2, 3)  # connect, read


@dataclass(frozen=True)
class G3MConfirmedMod:
    """One entry of the list of mods confirmed to install without Manual install."""

    note: str = ""
    game: str = ""  # G3M game id; empty means any game
    game_version: str = ""


class GameBananaAPI:
    _compatibility_cache: dict[int, dict[str, Any]] = {}
    _app_state = None
    g3m_confirmed: dict[str, G3MConfirmedMod] = {}
    _g3m_confirmed_loaded_at = float("-inf")
    _g3m_confirmed_etag = ""

    @classmethod
    def load_g3m_confirmed(cls) -> None:
        """Read the mods that the G3M creator confirmed install without Manual install.

        One attempt, a few seconds at most: without the list the cards simply lack its badges.
        """
        cls._g3m_confirmed_loaded_at = time.monotonic()
        try:
            response = requests.get(
                MOD_CATALOG_URL,
                headers={"If-None-Match": cls._g3m_confirmed_etag} if cls._g3m_confirmed_etag else {},
                timeout=_G3M_LIST_TIMEOUT,
            )
            if response.status_code == requests.codes.not_modified:
                return
            response.raise_for_status()
            cls._g3m_confirmed_etag = response.headers.get("ETag", "")
            cls.g3m_confirmed = {
                str(entry["id"]): G3MConfirmedMod(
                    *(str(entry.get(key) or "").strip() for key in ("note", "game", "game_version"))
                )
                for entry in response.json().get("mods", [])
                if isinstance(entry, dict) and entry.get("id")
            }
        except Exception as error:
            logger.warning("GameBananaAPI: G3M mod list unavailable (%s): %s", type(error).__name__, error)

    @classmethod
    def set_app_state(cls, app_state) -> None:
        cls._app_state = app_state

    def __init__(self) -> None:
        self.base_url = GAMEBANANA_API_BASE
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
        max_retries=2,
        search_string: str | None = None,
    ):
        if time.monotonic() - self._g3m_confirmed_loaded_at > _G3M_LIST_TTL_SECONDS:
            self.load_g3m_confirmed()
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
        mapped_mods: list[BrowserModInfo] = []
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

    def get_installable_mod(self, mod_id: int, item_type: str = "Mod") -> BrowserModInfo:
        """The mod with its downloadable files, ready to install straight from a link; raises AppError."""
        profile = self.get_mod_profile_page(mod_id, itemtype=item_type, max_retries=0, timeout=NETWORK_TIMEOUT_SHORT)
        if not profile:
            raise AppError("errors.mod_not_found")
        game_id = self._safe_int((profile.get("_aGame") or {}).get("_idRow")) or 0
        mod = self._map_mod_data(profile, get_gamebanana_reverse_map().get(game_id, "deltarune"), is_wip=item_type == "Wip")
        if not mod:
            raise AppError("errors.mod_not_found")
        files = profile.get("_aFiles") or []
        for entry in files.values() if isinstance(files, dict) else files:
            if not isinstance(entry, dict) or not (file_id := self._safe_int(entry.get("_idRow"))) or not entry.get("_bHasContents", True) or entry.get("_bIsArchived"):
                continue
            mod.gamebanana_supported_files.append(self._build_file_metadata(file_id, entry, f"gb_{item_type.lower()}_{mod_id}"))
        if not mod.gamebanana_supported_files:
            raise AppError("errors.mod_no_files", mod_name=mod.name)
        return mod

    def get_mod_profile_page(self, mod_id, itemtype="Mod", max_retries=2, timeout=None):
        data = self._api_request(
            f"{self.base_url}/{itemtype}/{mod_id}/ProfilePage",
            max_retries=max_retries,
            timeout=timeout,
            operation="get_mod_profile_page",
            mod_id=mod_id,
        )
        return data if isinstance(data, dict) else None

    def get_mod_game_id(self, mod_id, itemtype="Mod") -> int | None:
        """The GameBanana id of the game a mod is listed under, if it can be looked up."""
        profile = self.get_mod_profile_page(mod_id, itemtype=itemtype, max_retries=0, timeout=NETWORK_TIMEOUT_SHORT)
        game = profile.get("_aGame") if profile else None
        return self._safe_int(game.get("_idRow")) if isinstance(game, dict) else None

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

    def get_install_metadata(self, metadata: dict) -> dict:
        """Refresh available display metadata, retaining the selected file's version."""
        result = {}
        try:
            is_wip = str(metadata.get("item_type", "mod")).strip().casefold() == "wip"
            profile = self.get_mod_profile_page(
                metadata["mod_id"], itemtype="Wip" if is_wip else "Mod",
                max_retries=0, timeout=NETWORK_TIMEOUT_SHORT,
            )
            if isinstance(profile, dict):
                mod = self._map_mod_data(profile, metadata.get("game", "deltarune"), is_wip=is_wip)
                if mod:
                    for field, key in (("name", "_sName"), ("description", "_sDescription"), ("version", "_sVersion")):
                        if profile.get(key) and not (field == "version" and metadata.get("version")):
                            result[field] = profile[key] if field == "description" else getattr(mod, field)
                    for field in ("homepage", "icon", "tags"):
                        if value := getattr(mod, field):
                            result[field] = value
                    if isinstance(submitter := profile.get("_aSubmitter"), dict) and submitter.get("_sName"):
                        result["authors"] = mod.authors
                    if mod.gamebanana_category:
                        result["category"] = mod.gamebanana_category
        except Exception:
            logger.warning("Could not refresh GameBanana install metadata", exc_info=True)
        return result

    def _get_mod_file_compatibility(self, mod_id, itemtype="Mod"):
        cached = self._compatibility_cache.get(mod_id)
        if cached:
            return cached
        compatibility = {
            "supported_files": [],
            "has_supported_files": False,
            "preferred_format": None,
            "tool_ids": set(),
            "has_g3m_file": False,
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
                file_payload = self._build_file_metadata(
                    file_id, file_entry, f"gb_{itemtype.lower()}_{mod_id}"
                )
                compatibility_label = file_payload["compatibility"]
                if compatibility_label == "g3m":
                    compatibility["has_g3m_file"] = True
                elif compatibility_label == "deltamod":
                    compatibility["has_deltamod_file"] = True
                if compatibility_label:
                    compatibility["supported_files"].append(file_payload)
                    compatibility["tool_ids"].update(file_payload["tool_ids"])
            if compatibility["supported_files"]:
                compatibility["has_supported_files"] = True
                compatibility["preferred_format"] = (
                    "g3m"
                    if compatibility["has_g3m_file"]
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

    def resolve_dependency_download(
        self, dependency_id: str, game: str
    ) -> dict[str, Any] | None:
        """Return one deterministic GameBanana download for a operation relation.

        G3M and Deltamod integrations take precedence. For ordinary GameBanana
        uploads, use the newest available file and let the existing converter
        decide whether it can be installed automatically.
        """
        match = re.fullmatch(r"gb_(mod|wip)_([0-9]+)", dependency_id)
        if not match:
            return None
        kind, raw_id = match.groups()
        mod_id = int(raw_id)
        item_type = "Wip" if kind == "wip" else "Mod"
        compatibility = self.get_supported_files_for_mod(mod_id, item_type)
        files = compatibility.get("supported_files") or []
        from utils.mod.utils import sort_gamebanana_files_by_priority

        profile = self.get_mod_profile_page(mod_id, itemtype=item_type) or {}
        if files:
            selected = sort_gamebanana_files_by_priority(files)[0]
        else:
            raw_files = profile.get("_aFiles", [])
            raw_files = (
                list(raw_files.values()) if isinstance(raw_files, dict) else raw_files
            )
            available = [
                item
                for item in raw_files
                if isinstance(item, dict)
                and item.get("_idRow")
                and item.get("_bHasContents", True)
                and not item.get("_bIsArchived")
            ]
            if not available:
                return None
            selected = max(
                available,
                key=lambda item: (
                    self._safe_int(item.get("_tsDateAdded")) or 0,
                    self._safe_int(item.get("_idRow")) or 0,
                ),
            )
        return self._build_download_resolution(
            dependency_id, kind, mod_id, game, profile, selected
        )

    def resolve_mod_update_downloads(
        self, mod_id: str, game: str
    ) -> list[dict[str, Any]]:
        """Return every downloadable file at the newest GameBanana version."""
        match = re.fullmatch(r"gb_(mod|wip)_([0-9]+)", mod_id)
        if not match:
            return []
        kind, raw_id = match.groups()
        gamebanana_id = int(raw_id)
        item_type = "Wip" if kind == "wip" else "Mod"
        compatibility = self.get_supported_files_for_mod(gamebanana_id, item_type)
        supported = {
            str(file.get("id") or file.get("_idRow")): file
            for file in compatibility.get("supported_files") or []
            if isinstance(file, dict)
        }
        profile = self.get_mod_profile_page(gamebanana_id, itemtype=item_type) or {}
        raw_files = profile.get("_aFiles", [])
        raw_files = list(raw_files.values()) if isinstance(raw_files, dict) else raw_files
        files = self._latest_gamebanana_files(raw_files)
        return [
            resolution
            for file in files
            if (
                resolution := self._build_download_resolution(
                    mod_id,
                    kind,
                    gamebanana_id,
                    game,
                    profile,
                    {**file, **supported.get(str(file.get("_idRow")), {})},
                )
            )
        ]

    @staticmethod
    def _latest_gamebanana_files(raw_files: Any) -> list[dict[str, Any]]:
        files = [
            file
            for file in raw_files or []
            if isinstance(file, dict)
            and file.get("_idRow")
            and file.get("_bHasContents", True)
            and not file.get("_bIsArchived", False)
        ]
        file_versions = [
            (file, str(file.get("_sVersion") or file.get("version") or "").strip())
            for file in files
        ]
        versioned = [(file, version) for file, version in file_versions if version]
        if not versioned:
            return [
                max(
                    files,
                    key=lambda file: (
                        GameBananaAPI._safe_int(file.get("_tsDateAdded")) or 0,
                        GameBananaAPI._safe_int(file.get("_idRow")) or 0,
                    ),
                )
            ] if files else []
        latest = max(
            (version for _, version in versioned),
            key=GameBananaAPI._gamebanana_version_key,
        )
        latest_key = GameBananaAPI._gamebanana_version_key(latest)
        latest_files = [
            file
            for file, version in versioned
            if GameBananaAPI._gamebanana_version_key(version) == latest_key
        ]
        latest_timestamp = max(
            (GameBananaAPI._safe_int(file.get("_tsDateAdded")) or 0)
            for file in latest_files
        )
        newer_unversioned = [
            file
            for file, version in file_versions
            if not version
            and (GameBananaAPI._safe_int(file.get("_tsDateAdded")) or 0)
            > latest_timestamp
        ]
        return sorted(
            [*latest_files, *newer_unversioned],
            key=lambda file: GameBananaAPI._safe_int(file.get("_tsDateAdded")) or 0,
            reverse=True,
        )

    @staticmethod
    def _gamebanana_version_key(version: str) -> tuple[int, ...]:
        parts = [int(part) for part in re.findall(r"\d+", version)]
        while len(parts) > 1 and parts[-1] == 0:
            parts.pop()
        return tuple(parts) or (0,)

    def _build_download_resolution(
        self,
        dependency_id: str,
        kind: str,
        mod_id: int,
        game: str,
        profile: dict[str, Any],
        selected: dict[str, Any],
    ) -> dict[str, Any] | None:
        file_id = selected.get("id") or selected.get("_idRow")
        download_url = selected.get("download_url") or selected.get("_sDownloadUrl")
        if not download_url and file_id:
            download_url = f"https://gamebanana.com/dl/{file_id}"
        if not download_url or not file_id:
            return None
        submitter = profile.get("_aSubmitter")
        category_data = profile.get("_aRootCategory") or profile.get("_aCategory")
        category = (
            category_data.get("_sName") or category_data.get("name")
            if isinstance(category_data, dict)
            else category_data if isinstance(category_data, str) else None
        )
        return {
            "id": dependency_id,
            "display_name": str(profile.get("_sName") or dependency_id),
            "source_url": str(download_url),
            "canonical_key": f"gb_{kind}_{mod_id}_{file_id}",
            "metadata": {
                "gb_mod_id": mod_id,
                "item_type": kind,
                "gb_file_id": file_id,
                "file_name": selected.get("name") or selected.get("_sFile"),
                "size_bytes": selected.get("size_bytes") or selected.get("_nFilesize"),
                "md5": selected.get("md5") or selected.get("_sMd5Checksum"),
                "timestamp": selected.get("timestamp") or selected.get("_tsDateAdded"),
                "download_count": selected.get("download_count")
                or selected.get("_nDownloadCount"),
                "analysis_state": selected.get("analysis_state")
                or selected.get("_sAnalysisState"),
                "analysis_result": selected.get("analysis_result")
                or selected.get("_sAnalysisResult"),
                "av_state": selected.get("av_state") or selected.get("_sAvState"),
                "av_result": selected.get("av_result") or selected.get("_sAvResult"),
                "compatibility": selected.get("compatibility"),
                "name": profile.get("_sName"),
                "authors": (
                    [submitter.get("_sName")]
                    if isinstance(submitter, dict) and submitter.get("_sName")
                    else []
                ),
                "version": selected.get("version")
                or selected.get("_sVersion")
                or profile.get("_sVersion"),
                "description": selected.get("description")
                or selected.get("_sDescription")
                or profile.get("_sDescription"),
                "homepage": profile.get("_sProfileUrl")
                or f"https://gamebanana.com/{'wips' if kind == 'wip' else 'mods'}/{mod_id}",
                "icon": self.extract_icon(profile.get("_aPreviewMedia")),
                "tags": self.extract_tags(profile.get("_aTags")),
                "category": category,
                "game": game,
            },
        }

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _first_value(
        entries: Sequence[Mapping[str, Any] | None], key: str, default: Any = None
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
        mod_key: str = "",
    ) -> dict[str, Any]:
        integrations = [
            (tool_id, integration.get("_sName", str(tool_id)))
            for integration in profile_entry.get("_aModManagerIntegrations") or []
            if isinstance(integration, dict)
            and (tool_id := self._safe_int(integration.get("_idToolRow"))) is not None
        ]
        tool_ids = [tool_id for tool_id, _ in integrations]
        sources = [profile_entry]
        size_val = self._safe_int(self._first_value(sources, "_nFilesize"))
        timestamp_val = self._safe_int(self._first_value(sources, "_tsDateAdded"))
        download_count = self._safe_int(self._first_value(sources, "_nDownloadCount"))
        return {
            "id": file_id,
            "name": self._first_value(sources, "_sFile", f"file_{file_id}"),
            "version": self._first_value(sources, "_sVersion", ""),
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
            "tool_names": [name for _, name in integrations],
            # Every GameBanana mod can carry the G3M tool, so only mods from the confirmed list install by themselves.
            "compatibility": (
                "g3m"
                if GAMEBANANA_TOOL_ID_G3M in tool_ids and mod_key in self.g3m_confirmed
                else "deltamod" if GAMEBANANA_TOOL_ID_DELTAMOD in tool_ids else ""
            ),
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
        return GameBananaAPI.fix_screenshot_urls(urls, is_wip=is_wip) or []

    @staticmethod
    def extract_tags(tags) -> list[str]:
        if not tags:
            return []
        result: list[str] = []
        for tag in tags:
            value = tag.get("_sRawTag") if isinstance(tag, dict) else tag
            if isinstance(value, str) and value:
                result.append(value)
        return result

    @staticmethod
    def category_to_tag(category) -> str:
        return normalize_tag(category)

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
        homepage = (
            gb_data.get("_sProfileUrl")
            or f"https://gamebanana.com/{'wips' if is_wip else 'mods'}/{mod_id}"
        )
        preview_media = gb_data.get("_aPreviewMedia", {})
        raw_has_files = gb_data.get("_bHasFiles", True)
        has_files = raw_has_files not in (False, 0, "0", "false", "False", None)
        return BrowserModInfo(
            id=f"gb_{'wip' if is_wip else 'mod'}_{mod_id}",
            name=gb_data.get("_sName", "Unknown Mod"),
            version=gb_data.get("_sVersion", "") or "1.0.0",
            authors=(
                [submitter.get("_sName") or "Unknown"]
                if isinstance(submitter, dict)
                else ["Unknown"]
            ),
            description=description,
            game_version="Not specified",
            description_url=gb_data.get("_sTextUrl", ""),
            downloads=downloads,
            game=game_name,
            like_count=like_count,
            icon=self.extract_icon(preview_media),
            tags=tags,
            hide_mod=False,
            ban_status=False,
            is_nsfw=is_nsfw,
            has_files=has_files,
            is_wip=is_wip,
            demo_url=None,
            demo_version=None,
            created_date=self.timestamp_to_date(gb_data.get("_tsDateAdded")) or "N/A",
            last_updated=self.timestamp_to_date(
                gb_data.get("_tsDateModified") or gb_data.get("_tsDateUpdated")
            )
            or "N/A",
            homepage=homepage,
            screenshots_url=self._extract_preview_urls(preview_media, is_wip=is_wip),
            full_description=None,
            gamebanana_category=category,
            gamebanana_supported_files=[],
            gamebanana_compatibility_checked=False,
            has_full_metadata=True,
        )
