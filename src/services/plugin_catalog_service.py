"""Plugin catalog loading and caching."""

from __future__ import annotations

import logging
import os

from config.config import PLUGIN_CATALOG_URL
from models.plugin_models import CatalogPluginEntry

logger = logging.getLogger(__name__)


class PluginCatalogService:
    """Loads the remote plugin catalog only when requested."""

    def __init__(self, app_state, settings_service, plugins_dir: str) -> None:
        self.app_state = app_state
        self.settings_service = settings_service
        self.plugins_dir = plugins_dir
        self.cache_path = os.path.join(plugins_dir, "catalog_cache.json")
        self._catalog: dict | None = None
        self._entries_cache: list[CatalogPluginEntry] | None = None
        self._entries_by_id: dict[str, CatalogPluginEntry] | None = None

    def load_catalog(self, force_refresh: bool = False) -> dict:
        if self._catalog is not None and not force_refresh:
            return self._catalog
        os.makedirs(self.plugins_dir, exist_ok=True)
        if force_refresh:
            data = self._try_fetch_catalog()
            if data:
                self._catalog = data
                self._write_cache(data)
                self._invalidate_cache()
                return data
        cached = self.settings_service.read_json(self.cache_path) or {}
        if not cached:
            self._catalog = None
        else:
            self._catalog = cached
        self._invalidate_cache()
        return cached or {}

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
                    external_link=str(item.get("external_link", "")).strip(),
                    download_link=str(item.get("download_link", "")).strip(),
                    tags=[str(tag).strip() for tag in item.get("tags", []) if str(tag).strip()],
                    relations={
                        str(key).strip(): str(value).strip()
                        for key, value in (item.get("relations", {}) or {}).items()
                        if str(key).strip() and str(value).strip()
                    },
                    updated_at=str(item.get("updated_at", "")).strip(),
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

    def _write_cache(self, data: dict) -> None:
        self.settings_service.write_json(self.cache_path, data)

    def _invalidate_cache(self) -> None:
        """Invalidate the entries cache when catalog changes."""
        self._entries_cache = None
        self._entries_by_id = None
