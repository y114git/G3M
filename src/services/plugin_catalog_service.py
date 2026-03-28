"""Plugin catalog loading and caching."""

from __future__ import annotations

import logging
import time

from config.config import PLUGIN_CATALOG_URL
from models.plugin_models import CatalogPluginEntry

logger = logging.getLogger(__name__)


class PluginCatalogService:
    """Loads the remote plugin catalog only when requested."""
    _CACHE_TTL_SECONDS = 300

    def __init__(self, app_state, settings_service, plugins_dir: str) -> None:
        self.app_state = app_state
        self.settings_service = settings_service
        self.plugins_dir = plugins_dir
        self._catalog: dict | None = None
        self._catalog_loaded_at: float = 0.0
        self._entries_cache: list[CatalogPluginEntry] | None = None
        self._entries_by_id: dict[str, CatalogPluginEntry] | None = None

    def load_catalog(self, force_refresh: bool = False) -> dict:
        if (
            self._catalog is not None
            and not force_refresh
            and (time.time() - self._catalog_loaded_at) < self._CACHE_TTL_SECONDS
        ):
            return self._catalog
        if force_refresh:
            data = self._try_fetch_catalog()
            if data:
                self._catalog = data
                self._catalog_loaded_at = time.time()
                self._invalidate_cache()
                return data
        self._catalog = self._catalog or {}
        self._catalog_loaded_at = time.time() if self._catalog else 0.0
        self._invalidate_cache()
        return self._catalog

    def is_loaded(self) -> bool:
        return self._catalog is not None

    def refresh_catalog(self) -> dict:
        result = self.load_catalog(force_refresh=True)
        return result

    def list_entries(self, *, load_if_needed: bool = True) -> list[CatalogPluginEntry]:
        if self._entries_cache is None or (load_if_needed and self._catalog is None):
            catalog = self.load_catalog() if load_if_needed else (self._catalog or {})
            self._entries_cache = [
                CatalogPluginEntry(
                    id=str(item.get("id", "")).strip(),
                    name=str(item.get("name", "")).strip(),
                    description=str(item.get("description", "")).strip(),
                    author=str(item.get("author", "")).strip(),
                    version=str(item.get("version", "")).strip(),
                    api_version=str(item.get("api_version", "")).strip(),
                    icon=str(item.get("icon", "")).strip(),
                    homepage=str(item.get("homepage", "")).strip(),
                    download_link=str(item.get("download_link", "")).strip(),
                    tags=[str(tag).strip() for tag in item.get("tags", []) if str(tag).strip()],
                    relations={
                        str(key).strip(): str(value).strip()
                        for key, value in (item.get("relations", {}) or {}).items()
                        if str(key).strip() and str(value).strip()
                    },
                )
                for item in catalog.get("plugins", [])
                if str(item.get("id", "")).strip()
            ]
            self._entries_by_id = {entry.id: entry for entry in self._entries_cache}
        return self._entries_cache or []

    def get_entry(
        self, plugin_id: str, *, load_if_needed: bool = True
    ) -> CatalogPluginEntry | None:
        if self._entries_by_id is None or (load_if_needed and self._catalog is None):
            self.list_entries(load_if_needed=load_if_needed)
        return (self._entries_by_id or {}).get(plugin_id)

    def _try_fetch_catalog(self) -> dict | None:
        session = getattr(self.app_state, "network_session", None)
        if not session:
            return None
        try:
            response = session.get(PLUGIN_CATALOG_URL, timeout=5)
            response.raise_for_status()
            data = response.json() or {}
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.debug("PluginCatalogService: fetch failed: %s", e, exc_info=True)
        return None

    def _invalidate_cache(self) -> None:
        """Invalidate the entries cache when catalog changes."""
        self._entries_cache = None
        self._entries_by_id = None
