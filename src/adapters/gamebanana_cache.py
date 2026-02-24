"""GameBanana metadata caching."""
import json
import logging
import threading
import time
from pathlib import Path
from typing import Dict, Any
from config.constants import CACHE_STALE_TTL, CACHE_MAX_ENTRIES

logger = logging.getLogger(__name__)


class GameBananaMetadataCache:
    """Minimized GameBanana metadata cache."""
    _locks: Dict[str, threading.RLock] = {}

    def __init__(self, path: str):
        p = Path(path)
        self.file = p if p.suffix == '.json' else p / 'gamebanana_cache.json'
        self.lock = self._locks.setdefault(str(self.file.absolute()), threading.RLock())
        self._cache: Dict[str, Any] = {}
        self._load()

    def _load(self):
        with self.lock:
            if not self.file.exists():
                return
            try:
                with open(self.file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    now = time.time()
                    self._cache = {k: v for k, v in data.items()
                                   if isinstance(v, dict) and now - v.get('timestamp', 0) < CACHE_STALE_TTL}
            except Exception:
                self._cache = {}

    def flush(self):
        """Save cache to disk simply."""
        with self.lock:
            try:
                self.file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.file, 'w', encoding='utf-8') as f:
                    json.dump(self._cache, f, separators=(',', ':'), ensure_ascii=False)
            except (IOError, OSError) as e:
                logger.error(f'Cache save failed: {e}')

    def get_field(self, mod_id: str, field: str):
        with self.lock:
            entry = self._cache.get(mod_id)
            if entry and time.time() - entry.get('timestamp', 0) < CACHE_STALE_TTL:
                return entry.get(field)
            return None

    def is_valid(self, mod_id: str) -> bool:
        return self.get_field(mod_id, 'timestamp') is not None

    def set(self, mod_id: str, downloads=None, tagline=None, **kwargs):
        with self.lock:
            entry = self._cache.get(mod_id, {'timestamp': 0})
            updates = {k: v for k, v in {'downloads': downloads, 'tagline': tagline, **kwargs}.items() if v is not None}
            entry.update(updates)
            entry['timestamp'] = entry['last_accessed'] = time.time()
            self._cache[mod_id] = entry
            if len(self._cache) > CACHE_MAX_ENTRIES:
                lru = min(self._cache, key=lambda k: self._cache[k].get('last_accessed', 0))
                self._cache.pop(lru)
            self.flush()

    def clear(self):
        """Simply truncate the cache file to empty object."""
        with self.lock:
            self._cache = {}
            self.flush()

    def clear_stale(self):
        with self.lock:
            now = time.time()
            expired = [k for k, v in self._cache.items() if now - v.get('timestamp', 0) >= CACHE_STALE_TTL]
            for k in expired:
                self._cache.pop(k)
            if expired:
                self.flush()
            return len(expired)

    def size(self) -> int:
        return len(self._cache)
