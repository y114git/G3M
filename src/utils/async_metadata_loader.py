"""Asynchronous metadata loading utilities for improved performance."""
import logging
import asyncio
import threading
from typing import List, Dict, Optional, Any, Tuple
import time
from adapters.gamebanana_adapter import GameBananaAPI
from models.mod_models import ModInfo
from adapters.gamebanana_cache import GameBananaMetadataCache

logger = logging.getLogger(__name__)


_rate_limit_lock = threading.Lock()
_last_request_time = 0.0
_MIN_REQUEST_INTERVAL = 0.2


def _wait_for_global_rate_limit():
    """Thread-safe rate limiting for GameBanana API."""
    global _last_request_time
    with _rate_limit_lock:
        elapsed = time.time() - _last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        _last_request_time = time.time()


class AsyncMetadataLoader:
    """Asynchronous mod metadata loading with native asyncio."""

    def __init__(self, max_concurrent: int = 4, batch_size: int = 8):
        self.max_concurrent = max_concurrent
        self.batch_size = batch_size
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def load_mods_metadata_async(self, mod_ids: List[str], metadata_cache: Optional[GameBananaMetadataCache] = None, app_state=None) -> List[Tuple[str, Any]]:
        """Load metadata for multiple mods asynchronously."""
        if not mod_ids:
            return []

        start_time = time.time()
        results = []

        uncached_mods = []
        if metadata_cache:
            for mod_id in mod_ids:
                if metadata_cache.is_valid(mod_id):
                    results.append((mod_id, {
                        'downloads': metadata_cache.get_field(mod_id, 'downloads'),
                        'tagline': metadata_cache.get_field(mod_id, 'tagline'),
                        'category': metadata_cache.get_field(mod_id, 'category')
                    }))
                else:
                    uncached_mods.append(mod_id)
        else:
            uncached_mods = mod_ids.copy()

        if not uncached_mods:
            logger.debug(f'AsyncMetadataLoader: All {len(mod_ids)} mods cached')
            return results

        logger.info(f'AsyncMetadataLoader: Loading {len(uncached_mods)} uncached mods (max_concurrent={self.max_concurrent})')

        for i in range(0, len(uncached_mods), self.batch_size):
            batch = uncached_mods[i:i + self.batch_size]
            batch_results = await self._process_metadata_batch(batch, metadata_cache, app_state)
            results.extend(batch_results)

            if i + self.batch_size < len(uncached_mods):
                await asyncio.sleep(0.1)

        if metadata_cache and hasattr(metadata_cache, 'flush_if_dirty'):
            metadata_cache.flush_if_dirty()

        elapsed = time.time() - start_time
        logger.info(f'AsyncMetadataLoader: Loaded {len(results)} mods in {elapsed:.2f}s')
        return results

    async def _process_metadata_batch(self, mod_ids: List[str], metadata_cache: Optional[GameBananaMetadataCache], app_state) -> List[Tuple[str, Any]]:
        """Process a batch of mod IDs concurrently."""
        tasks = [asyncio.create_task(self._load_with_semaphore(mod_id, app_state)) for mod_id in mod_ids]

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for mod_id, result in zip(mod_ids, results_list):
            if isinstance(result, Exception):
                logger.warning(f'AsyncMetadataLoader: Failed to load metadata for mod {mod_id}: {result}')
            elif result:
                results.append((mod_id, result))
                if metadata_cache:
                    self._cache_metadata(metadata_cache, mod_id, result)

        return results

    async def _load_with_semaphore(self, mod_id: str, app_state) -> Optional[Dict[str, Any]]:
        """Load metadata with semaphore control."""
        async with self._semaphore:
            return await asyncio.wait_for(self._load_single_mod_metadata(mod_id, app_state), timeout=10)

    async def _load_single_mod_metadata(self, mod_id_str: str, app_state) -> Optional[Dict[str, Any]]:
        """Load metadata for a single mod."""
        return await asyncio.to_thread(self._load_single_mod_metadata_sync, mod_id_str, app_state)

    def _load_single_mod_metadata_sync(self, mod_id_str: str, app_state) -> Optional[Dict[str, Any]]:
        """Synchronous metadata loading with rate limiting."""
        _wait_for_global_rate_limit()

        try:
            mod_id = int(mod_id_str)
            api = GameBananaAPI()

            external_url = None
            if app_state and hasattr(app_state, 'all_mods'):
                key = f'gb_{mod_id_str}'
                for mod in app_state.all_mods:
                    if getattr(mod, 'key', None) == key:
                        external_url = getattr(mod, 'external_url', None)
                        break

            downloads = tagline = category = None

            try:
                downloads = api.get_mod_downloads_only(mod_id, external_url=external_url)
            except Exception as e:
                logger.debug(f'Failed to load downloads for mod {mod_id}: {e}')

            try:
                desc = api.get_mod_description_only(mod_id, external_url=external_url)
                if desc and len(desc.strip()) >= 10:
                    tagline = desc[:200].strip()
            except Exception as e:
                logger.debug(f'Failed to load description for mod {mod_id}: {e}')

            try:
                category = api.get_mod_category_only(mod_id, external_url=external_url)
            except Exception as e:
                logger.debug(f'Failed to load category for mod {mod_id}: {e}')

            if downloads is not None or tagline or category:
                return {
                    'downloads': downloads,
                    'tagline': tagline or 'No description',
                    'category': category
                }

        except (ValueError, TypeError) as e:
            logger.warning(f'Invalid mod_id {mod_id_str}: {e}')
        except Exception as e:
            logger.error(f'Error loading metadata for mod {mod_id_str}: {e}')

        return None

    def _cache_metadata(self, metadata_cache: GameBananaMetadataCache, mod_id_str: str, metadata: Dict[str, Any]):
        """Cache metadata for future use."""
        try:
            metadata_cache.set(
                mod_id_str,
                metadata.get('downloads'),
                metadata.get('tagline', 'No description'),
                category=metadata.get('category')
            )
        except Exception as e:
            logger.warning(f'Failed to cache metadata for mod {mod_id_str}: {e}')


class AsyncGameModsLoader:
    """Asynchronous game mods loading with native asyncio."""

    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def load_game_mods_async(self, game_name: str, game_id: int, pages: List[int], per_page: int = 20,
                                   sort: str = 'default', metadata_cache: Optional[GameBananaMetadataCache] = None,
                                   app_state=None) -> Tuple[List[ModInfo], List[str]]:
        """Load mods for multiple pages asynchronously."""
        if not pages:
            return [], []

        start_time = time.time()
        logger.info(f'AsyncGameModsLoader: Loading {len(pages)} pages for {game_name} (max_concurrent={self.max_concurrent})')

        tasks = [(page, asyncio.create_task(self._load_single_page(game_id, page, per_page, sort, metadata_cache, app_state)))
                 for page in pages]

        all_mods = []
        mods_needing_metadata = []

        for page, task in tasks:
            try:
                page_mods, page_needing_metadata = await asyncio.wait_for(task, timeout=30)
                if page_mods:
                    all_mods.extend(page_mods)
                    mods_needing_metadata.extend(page_needing_metadata)
                    logger.debug(f'Loaded page {page} for {game_name}: {len(page_mods)} mods')
                else:
                    logger.debug(f'No mods data for {game_name} page {page}')
            except Exception as e:
                logger.error(f'Error loading page {page} for {game_name}: {e}')

        elapsed = time.time() - start_time
        logger.info(f'AsyncGameModsLoader: Loaded {len(all_mods)} mods for {game_name} in {elapsed:.2f}s')
        return all_mods, mods_needing_metadata

    async def _load_single_page(self, game_id: int, page: int, per_page: int, sort: str,
                                metadata_cache: Optional[GameBananaMetadataCache], app_state) -> Tuple[List[ModInfo], List[str]]:
        """Load a single page of mods."""
        return await asyncio.to_thread(self._load_single_page_sync, game_id, page, per_page, sort, metadata_cache, app_state)

    def _load_single_page_sync(self, game_id: int, page: int, per_page: int, sort: str,
                               metadata_cache: Optional[GameBananaMetadataCache], app_state) -> Tuple[List[ModInfo], List[str]]:
        """Synchronous page loading with rate limiting."""
        _wait_for_global_rate_limit()

        try:
            api = GameBananaAPI()
            mods_data, mods_needing_metadata = api.get_game_mods(
                game_id, page=page, per_page=per_page, sort=sort,
                metadata_cache=metadata_cache, app_state=app_state
            )
            return mods_data or [], mods_needing_metadata or []
        except Exception as e:
            logger.error(f'Error loading page {page}: {e}')
            return [], []
