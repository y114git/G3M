"""GameBanana metadata caching."""
import json
import logging
import os
import threading
import time
from typing import Dict, Optional
logger = logging.getLogger(__name__)
CACHE_TTL = 24 * 60 * 60
MAX_CACHE_ENTRIES = 5000
_SAVE_DELAY = 5.0


class GameBananaMetadataCache:
    """Caches GameBanana mod metadata to reduce API calls.

    Each entry stores its own timestamp. Entries older than CACHE_TTL (1 day)
    are removed on load and via clear_stale(). When a user encounters a mod
    with an expired/missing entry, it shows Loading... while fresh data is fetched.
    """

    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        self.cache_file = os.path.join(cache_dir, 'gamebanana_metadata_cache.json')
        self._cache: Dict[str, Dict] = {}
        self._lock = threading.RLock()
        self._dirty = False
        self._save_timer: Optional[threading.Timer] = None
        self._load_cache()

    def _load_cache(self):
        with self._lock:
            if not os.path.exists(self.cache_file):
                self._cache = {}
                return
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    self._cache = {}
                    self._try_remove_file()
                    return
                entries = data.get('entries', data) if '_version' in data else data
                if not isinstance(entries, dict):
                    self._cache = {}
                    self._try_remove_file()
                    return
                now = time.time()
                valid = {}
                for mod_id, entry in entries.items():
                    if mod_id.startswith('_'):
                        continue
                    if not isinstance(entry, dict):
                        continue
                    ts = entry.get('timestamp')
                    if not isinstance(ts, (int, float)) or ts <= 0 or ts > now:
                        continue
                    if now - ts > CACHE_TTL:
                        continue
                    valid[mod_id] = entry
                self._cache = valid
                if len(valid) != len(entries):
                    self._dirty = True
                    self._schedule_save()
                logger.info(f'GameBananaMetadataCache: Loaded {len(self._cache)} valid entries')
            except (json.JSONDecodeError, IOError, PermissionError, OSError, TypeError, ValueError) as e:
                logger.warning(f'GameBananaMetadataCache: Failed to load cache: {e}, resetting')
                self._cache = {}
                self._try_remove_file()

    def _try_remove_file(self):
        try:
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
        except OSError:
            pass

    def _schedule_save(self):
        if self._save_timer and self._save_timer.is_alive():
            self._save_timer.cancel()
        self._save_timer = threading.Timer(_SAVE_DELAY, self.flush)
        self._save_timer.daemon = True
        self._save_timer.start()

    def flush(self):
        with self._lock:
            if not self._dirty:
                return
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
                payload = self._cache
                tmp = self.cache_file + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
                os.replace(tmp, self.cache_file)
                self._dirty = False
            except (IOError, PermissionError, OSError) as e:
                logger.warning(f'GameBananaMetadataCache: Failed to save cache: {e}')
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except OSError:
                    pass

    def get(self, mod_id: str) -> Optional[Dict]:
        with self._lock:
            entry = self._cache.get(mod_id)
            if entry and isinstance(entry, dict):
                return entry
            return None

    def _get_valid_entry(self, mod_id: str) -> Optional[Dict]:
        with self._lock:
            entry = self._cache.get(mod_id)
            if entry and self.is_valid(mod_id):
                return entry
            return None

    def _is_timestamp_valid(self, ts, ttl):
        if not isinstance(ts, (int, float)) or ts <= 0:
            return False
        now = time.time()
        return ts <= now and (now - ts) <= ttl

    def is_valid(self, mod_id: str) -> bool:
        with self._lock:
            entry = self._cache.get(mod_id)
            if not entry or not isinstance(entry, dict):
                return False
            return self._is_timestamp_valid(entry.get('timestamp'), CACHE_TTL)

    def set(self, mod_id: str, downloads=None, tagline=None, full_description=None, screenshots=None, category=None):
        with self._lock:
            entry = self._cache.get(mod_id, {})
            updates = {k: v for k, v in {'downloads': downloads, 'tagline': tagline, 'full_description': full_description, 'screenshots': screenshots, 'category': category}.items() if v is not None}
            entry.update(updates)
            entry['timestamp'] = time.time()
            self._cache[mod_id] = entry
            self._dirty = True
            if len(self._cache) > MAX_CACHE_ENTRIES:
                self._evict_oldest()
            self._schedule_save()

    def get_field(self, mod_id: str, field: str):
        entry = self._get_valid_entry(mod_id)
        return entry.get(field) if entry else None

    def clear(self):
        with self._lock:
            self._cache = {}
            self._dirty = True
            self.flush()

    def clear_stale(self):
        with self._lock:
            stale = [mid for mid, e in self._cache.items()
                     if not self._is_timestamp_valid(e.get('timestamp'), CACHE_TTL)]
            for mid in stale:
                del self._cache[mid]
            if stale:
                self._dirty = True
                self._schedule_save()
                logger.info(f'GameBananaMetadataCache: Removed {len(stale)} stale entries')
            return len(stale)

    def _evict_oldest(self):
        if len(self._cache) <= MAX_CACHE_ENTRIES:
            return
        by_time = sorted(self._cache.items(), key=lambda kv: kv[1].get('timestamp', 0))
        to_remove = len(self._cache) - MAX_CACHE_ENTRIES
        for mod_id, _ in by_time[:to_remove]:
            del self._cache[mod_id]

    def size(self) -> int:
        with self._lock:
            return len(self._cache)
