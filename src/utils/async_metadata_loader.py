"""Asynchronous metadata loading utilities for improved performance."""
import logging
from typing import List, Dict, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from adapters.gamebanana_adapter import GameBananaAPI
from models.mod_models import ModInfo
from adapters.gamebanana_cache import GameBananaMetadataCache

logger = logging.getLogger(__name__)


class AsyncMetadataLoader:
    """Handles asynchronous loading of mod metadata with minimal changes to existing code."""

    def __init__(self, max_workers: int = 4, batch_size: int = 8):
        self.max_workers = max_workers
        self.batch_size = batch_size
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def __del__(self):
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)

    def load_mods_metadata_async(self, mod_ids: List[str], metadata_cache: Optional[GameBananaMetadataCache] = None, app_state=None) -> List[Tuple[str, Any]]:
        """
        Load metadata for multiple mods asynchronously.

        Args:
            mod_ids: List of mod IDs to load metadata for
            metadata_cache: Cache instance for storing/retrieving metadata
            app_state: Application state for additional context

        Returns:
            List of tuples (mod_id, metadata_dict) for successfully loaded metadata
        """
        if not mod_ids:
            return []

        start_time = time.time()
        results = []

        uncached_mods = []
        if metadata_cache:
            for mod_id in mod_ids:
                if not metadata_cache.is_valid(mod_id):
                    uncached_mods.append(mod_id)
                else:

                    cached_data = {
                        'downloads': metadata_cache.get_field(mod_id, 'downloads'),
                        'tagline': metadata_cache.get_field(mod_id, 'tagline'),
                        'category': metadata_cache.get_field(mod_id, 'category')
                    }
                    results.append((mod_id, cached_data))
        else:
            uncached_mods = mod_ids.copy()

        if not uncached_mods:
            logger.debug(f'AsyncMetadataLoader: All {len(mod_ids)} mods had cached metadata')
            return results

        logger.info(f'AsyncMetadataLoader: Loading metadata for {len(uncached_mods)} uncached mods (max_workers={self.max_workers})')

        for i in range(0, len(uncached_mods), self.batch_size):
            batch = uncached_mods[i:i + self.batch_size]
            batch_results = self._process_metadata_batch(batch, metadata_cache, app_state)
            results.extend(batch_results)

            if i + self.batch_size < len(uncached_mods):
                time.sleep(0.1)

        elapsed = time.time() - start_time
        logger.info(f'AsyncMetadataLoader: Loaded metadata for {len(results)} mods in {elapsed:.2f}s')
        return results

    def _process_metadata_batch(self, mod_ids: List[str], metadata_cache: Optional[GameBananaMetadataCache], app_state) -> List[Tuple[str, Any]]:
        """Process a batch of mod IDs concurrently."""
        results = []
        futures = {}

        for mod_id_str in mod_ids:
            future = self.executor.submit(self._load_single_mod_metadata, mod_id_str, app_state)
            futures[future] = mod_id_str

        for future in as_completed(futures):
            mod_id_str = futures[future]
            try:
                metadata = future.result(timeout=10)
                if metadata:
                    results.append((mod_id_str, metadata))

                    if metadata_cache:
                        self._cache_metadata(metadata_cache, mod_id_str, metadata)
            except Exception as e:
                logger.warning(f'AsyncMetadataLoader: Failed to load metadata for mod {mod_id_str}: {e}')

        return results

    def _load_single_mod_metadata(self, mod_id_str: str, app_state) -> Optional[Dict[str, Any]]:
        """Load metadata for a single mod (runs in thread pool)."""
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

            downloads = None
            tagline = None
            category = None

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
    """Handles asynchronous loading of game mods with minimal changes."""

    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def __del__(self):
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)

    def load_game_mods_async(self, game_name: str, game_id: int, pages: List[int], per_page: int = 20,
                             sort: str = 'default', metadata_cache: Optional[GameBananaMetadataCache] = None,
                             app_state=None) -> Tuple[List[ModInfo], List[str]]:
        """
        Load mods for multiple pages asynchronously.

        Args:
            game_name: Game name for logging
            game_id: GameBanana game ID
            pages: List of page numbers to load
            per_page: Number of mods per page
            sort: Sort order
            metadata_cache: Cache instance
            app_state: Application state

        Returns:
            Tuple of (all_mods, mods_needing_metadata)
        """
        if not pages:
            return [], []

        start_time = time.time()
        logger.info(f'AsyncGameModsLoader: Loading {len(pages)} pages for {game_name} (max_workers={self.max_workers})')

        futures = {}
        all_mods = []
        mods_needing_metadata = []

        for page in pages:
            future = self.executor.submit(self._load_single_page, game_id, page, per_page, sort, metadata_cache, app_state)
            futures[future] = page

        for future in as_completed(futures):
            page = futures[future]
            try:
                page_mods, page_needing_metadata = future.result(timeout=30)
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

    def _load_single_page(self, game_id: int, page: int, per_page: int, sort: str,
                          metadata_cache: Optional[GameBananaMetadataCache], app_state) -> Tuple[List[ModInfo], List[str]]:
        """Load a single page of mods (runs in thread pool)."""
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
