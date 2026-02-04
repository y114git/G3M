"""GameBanana metadata caching.

This module provides caching for GameBanana mod metadata to reduce API calls.
"""
import json
import logging
import os
import threading
import time
from typing import Dict, Optional
logger = logging.getLogger(__name__)
CACHE_TTL = 24 * 60 * 60


class GameBananaMetadataCache:
    """Caches GameBanana mod metadata to reduce API calls."""

    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        self.cache_file = os.path.join(cache_dir, 'gamebanana_metadata_cache.json')
        self._cache: Dict[str, Dict] = {}
        self._lock = threading.RLock()
        self._load_cache()

    def _load_cache(self):
        with self._lock:
            if not os.path.exists(self.cache_file):
                self._cache = {}
                logger.debug('GameBananaMetadataCache: Cache file not found, starting with empty cache')
                return
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._cache = data
                        logger.info(f'GameBananaMetadataCache: Loaded {len(self._cache)} entries from cache')
                    else:
                        self._cache = {}
                        logger.warning('GameBananaMetadataCache: Invalid cache file format, starting with empty cache')
            except (json.JSONDecodeError, IOError, PermissionError, OSError) as e:
                logger.warning(f'GameBananaMetadataCache: Failed to load cache: {e}, starting with empty cache')
                self._cache = {}

    def _save_cache(self):
        with self._lock:
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
                from utils.file_utils import atomic_write_json
                atomic_write_json(self.cache_file, self._cache, indent=2)
                logger.debug(f'GameBananaMetadataCache: Saved {len(self._cache)} entries to cache')
            except (IOError, PermissionError, OSError) as e:
                logger.warning(f'GameBananaMetadataCache: Failed to save cache (non-critical): {e}')

    def get(self, mod_id: str) -> Optional[Dict]:
        """Get cached metadata for a mod.

        Args:
            mod_id: GameBanana mod ID.

        Returns:
            Optional[Dict]: Cached metadata or None.
        """
        with self._lock:
            return self._cache.get(mod_id)

    def _get_valid_entry(self, mod_id: str) -> Optional[Dict]:
        with self._lock:
            entry = self._cache.get(mod_id)
            if entry and self.is_valid(mod_id):
                return entry
            return None

    def _collect_stale_ids(self, current_time: float) -> list[str]:
        stale_ids = []
        for mod_id, entry in self._cache.items():
            timestamp = entry.get('timestamp', 0)
            if current_time - timestamp > CACHE_TTL:
                stale_ids.append(mod_id)
        return stale_ids

    def is_valid(self, mod_id: str) -> bool:
        """Check if cached metadata is still valid (not expired).

        Args:
            mod_id: GameBanana mod ID.

        Returns:
            bool: True if cache entry is valid.
        """
        with self._lock:
            if mod_id not in self._cache:
                return False
            entry = self._cache[mod_id]
            timestamp = entry.get('timestamp', 0)
            current_time = time.time()
            if current_time - timestamp > CACHE_TTL:
                logger.debug(f'GameBananaMetadataCache: Cache entry for mod {mod_id} is stale (age: {current_time - timestamp}s)')
                return False
            return True

    def set(self, mod_id: str, downloads: Optional[int] = None, tagline: Optional[str] = None, full_description: Optional[str] = None, screenshots: Optional[list] = None, category: Optional[str] = None):
        """Set or update cached metadata for a mod.

        Args:
            mod_id: GameBanana mod ID.
            downloads: Download count.
            tagline: Mod tagline/description.
            full_description: Full description text.
            screenshots: List of screenshot URLs.
            category: Mod category.
        """
        with self._lock:
            if mod_id in self._cache:
                entry = self._cache[mod_id]
            else:
                entry = {}
            if downloads is not None:
                entry['downloads'] = downloads
            if tagline is not None:
                entry['tagline'] = tagline
            if full_description is not None:
                entry['full_description'] = full_description
            if screenshots is not None:
                entry['screenshots'] = screenshots
            if category is not None:
                entry['category'] = category
            entry['timestamp'] = time.time()
            self._cache[mod_id] = entry
            self._save_cache()
            logger.debug(f'GameBananaMetadataCache: Cached metadata for mod {mod_id}: downloads={downloads}, tagline_length={(len(tagline) if tagline else 0)}, has_desc={bool(full_description)}, screenshots_count={(len(screenshots) if screenshots else 0)}, category={category}')

    def get_field(self, mod_id: str, field: str):
        """Get a specific field from cached metadata.

        Args:
            mod_id: GameBanana mod ID.
            field: Field name to retrieve.

        Returns:
            Field value or None if not cached or expired.
        """
        entry = self._get_valid_entry(mod_id)
        return entry.get(field) if entry else None

    def clear(self):
        """Clear all cached metadata."""
        with self._lock:
            self._cache = {}
            self._save_cache()
            logger.info('GameBananaMetadataCache: Cache cleared')

    def clear_stale(self):
        """Remove expired cache entries."""
        with self._lock:
            current_time = time.time()
            stale_ids = self._collect_stale_ids(current_time)
            for mod_id in stale_ids:
                del self._cache[mod_id]
            if stale_ids:
                self._save_cache()
                logger.info(f'GameBananaMetadataCache: Removed {len(stale_ids)} stale entries from cache')
            return len(stale_ids)

    def get_stale_mod_ids(self) -> list[str]:
        """Get list of mod IDs with expired cache entries.

        Returns:
            list[str]: List of stale mod IDs.
        """
        with self._lock:
            current_time = time.time()
            return self._collect_stale_ids(current_time)

    def size(self) -> int:
        """Get the number of cached entries.

        Returns:
            int: Number of cache entries.
        """
        with self._lock:
            return len(self._cache)
