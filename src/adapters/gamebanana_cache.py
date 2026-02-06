"""GameBanana metadata caching."""
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
        with self._lock:
            entry = self._cache.get(mod_id)
            return bool(entry and time.time() - entry.get('timestamp', 0) <= CACHE_TTL)

    def set(self, mod_id: str, downloads=None, tagline=None, full_description=None, screenshots=None, category=None):
        with self._lock:
            entry = self._cache.get(mod_id, {})
            updates = {k: v for k, v in {'downloads': downloads, 'tagline': tagline, 'full_description': full_description, 'screenshots': screenshots, 'category': category}.items() if v is not None}
            entry.update(updates)
            entry['timestamp'] = time.time()
            self._cache[mod_id] = entry
            self._save_cache()

    def get_field(self, mod_id: str, field: str):
        entry = self._get_valid_entry(mod_id)
        return entry.get(field) if entry else None

    def clear(self):
        with self._lock:
            self._cache = {}
            self._save_cache()

    def clear_stale(self):
        with self._lock:
            current_time = time.time()
            stale_ids = self._collect_stale_ids(current_time)
            for mod_id in stale_ids:
                del self._cache[mod_id]
            if stale_ids:
                self._save_cache()
                logger.info(f'GameBananaMetadataCache: Removed {len(stale_ids)} stale entries from cache')
            return len(stale_ids)

    def size(self) -> int:
        with self._lock:
            return len(self._cache)
