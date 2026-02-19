"""GameBanana metadata caching."""
import json
import logging
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from config.constants import CACHE_STALE_TTL, CACHE_MAX_ENTRIES, CACHE_SAVE_DELAY

logger = logging.getLogger(__name__)


class GameBananaMetadataCache:
    """Caches GameBanana mod metadata with two-tier TTL (1h fresh, 7d stale)."""

    def __init__(self, cache_dir: str):
        self.cache_dir = Path(cache_dir)
        self.cache_file = self.cache_dir / 'gamebanana_cache.json'

        self._cache: Dict[str, Dict] = {}
        self._lock = threading.RLock()
        self._dirty = False
        self._save_timer: Optional[threading.Timer] = None

        self._load_cache()
        logger.info(f'GameBananaMetadataCache: Loaded {len(self._cache)} entries')

    def _load_cache(self):
        """Load cache from disk, removing expired entries."""
        with self._lock:
            if not self.cache_file.exists():
                return

            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if not isinstance(data, dict):
                    self._cache = {}
                    return

                now = time.time()
                expired_count = 0

                for mod_id, entry in data.items():
                    if not isinstance(entry, dict):
                        continue

                    timestamp = entry.get('timestamp', 0)
                    if not isinstance(timestamp, (int, float)) or timestamp <= 0:
                        continue

                    if now - timestamp >= CACHE_STALE_TTL:
                        expired_count += 1
                        continue

                    entry['last_accessed'] = now
                    self._cache[mod_id] = entry

                if expired_count > 0:
                    self._dirty = True
                    logger.info(f'GameBananaMetadataCache: Discarded {expired_count} expired entries')

            except (json.JSONDecodeError, IOError, OSError) as e:
                logger.error(f'GameBananaMetadataCache: Failed to load: {e}')
                self._cache = {}

    def _schedule_save(self):
        """Schedule delayed save."""
        if self._save_timer and self._save_timer.is_alive():
            self._save_timer.cancel()

        self._save_timer = threading.Timer(CACHE_SAVE_DELAY, self.flush)
        self._save_timer.daemon = True
        self._save_timer.start()

    def flush(self):
        """Save cache to disk."""
        with self._lock:
            if not self._dirty:
                return

            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                tmp_file = self.cache_file.with_suffix('.tmp')

                with open(tmp_file, 'w', encoding='utf-8') as f:
                    json.dump(self._cache, f, ensure_ascii=False, separators=(',', ':'))

                tmp_file.replace(self.cache_file)
                self._dirty = False

            except (IOError, OSError) as e:
                logger.error(f'GameBananaMetadataCache: Failed to save: {e}')
                if tmp_file.exists():
                    tmp_file.unlink(missing_ok=True)

    def get(self, mod_id: str) -> Optional[Dict]:
        """Get cached mod data."""
        with self._lock:
            entry = self._cache.get(mod_id)
            if not entry or not isinstance(entry, dict):
                return None

            timestamp = entry.get('timestamp', 0)
            age = time.time() - timestamp

            if age >= CACHE_STALE_TTL:
                return None

            entry['last_accessed'] = time.time()
            return entry.copy()

    def get_field(self, mod_id: str, field: str):
        """Get specific field from cached mod data."""
        entry = self.get(mod_id)
        return entry.get(field) if entry else None

    def is_valid(self, mod_id: str) -> bool:
        """Check if entry exists in cache."""
        return self.get(mod_id) is not None

    def set(self, mod_id: str, downloads=None, tagline=None, full_description=None, screenshots=None, category=None):
        """Cache mod metadata."""
        with self._lock:
            now = time.time()

            entry = self._cache.get(mod_id, {'timestamp': now, 'last_accessed': now})

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

            entry['timestamp'] = now
            entry['last_accessed'] = now
            self._cache[mod_id] = entry

            if len(self._cache) > CACHE_MAX_ENTRIES:
                self._evict_lru()

            self._dirty = True
            self._schedule_save()

    def _evict_lru(self):
        """Evict least recently used entries."""
        if len(self._cache) <= CACHE_MAX_ENTRIES:
            return

        sorted_entries = sorted(
            self._cache.items(),
            key=lambda kv: kv[1].get('last_accessed', 0)
        )

        to_remove = len(self._cache) - CACHE_MAX_ENTRIES
        for mod_id, _ in sorted_entries[:to_remove]:
            del self._cache[mod_id]

        logger.info(f'GameBananaMetadataCache: Evicted {to_remove} LRU entries')

    def clear_stale(self):
        """Remove expired entries (7+ days old)."""
        with self._lock:
            now = time.time()
            expired = [
                mod_id for mod_id, entry in self._cache.items()
                if now - entry.get('timestamp', 0) >= CACHE_STALE_TTL
            ]

            for mod_id in expired:
                del self._cache[mod_id]

            if expired:
                self._dirty = True
                self._schedule_save()
                logger.info(f'GameBananaMetadataCache: Removed {len(expired)} expired entries')

            return len(expired)

    def clear(self):
        """Clear all cache entries."""
        with self._lock:
            self._cache = {}
            self._dirty = True
            self.flush()
            logger.info('GameBananaMetadataCache: Cache cleared')

    def size(self) -> int:
        """Get number of cached entries."""
        with self._lock:
            return len(self._cache)
