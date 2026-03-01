"""GameBanana metadata loading worker."""
import logging
from PyQt6.QtCore import QThread, pyqtSignal
from adapters.gamebanana_adapter import GameBananaAPI
from adapters.gamebanana_cache import GameBananaMetadataCache
logger = logging.getLogger(__name__)


class LoadGameBananaMetadataThread(QThread):
    mod_updated, progress, finished = pyqtSignal(str, int, str, str), pyqtSignal(int, int), pyqtSignal()

    def __init__(self, mod_ids, metadata_cache: GameBananaMetadataCache, parent=None, app_state=None):
        super().__init__(parent)
        self.mod_ids, self.metadata_cache, self.api = mod_ids, metadata_cache, GameBananaAPI()
        self._cancelled, self._batch_size, self.app_state = False, 3, app_state

    def cancel(self): self._cancelled = True

    def _resolve_external_url(self, mod_id_str):
        if self.app_state and hasattr(self.app_state, 'all_mods'):
            key = f'gb_{mod_id_str}'
            for mod in self.app_state.all_mods:
                if getattr(mod, 'key', None) == key:
                    return getattr(mod, 'external_url', None)
        return None

    def _save_metadata(self, mod_id_str, downloads, tagline, category):
        tagline_to_save, category_to_save = tagline or 'No description', category
        self.metadata_cache.set(mod_id_str, downloads, tagline_to_save, category=category_to_save)
        self.mod_updated.emit(mod_id_str, downloads or 0, tagline_to_save, category_to_save or '')

    def run(self):
        try:
            total = len(self.mod_ids)
            if not total:
                logger.debug('LoadGameBananaMetadataThread: No mods to load metadata for')
                self.finished.emit()
                return

            try:
                from utils.async_metadata_loader import AsyncMetadataLoader
                async_loader = AsyncMetadataLoader(max_workers=4, batch_size=8)
                async_results = async_loader.load_mods_metadata_async(self.mod_ids, self.metadata_cache, self.app_state)

                loaded_count = 0
                for mod_id_str, metadata in async_results:
                    if self._cancelled or self.isInterruptionRequested():
                        break

                    downloads = metadata.get('downloads')
                    tagline = metadata.get('tagline')
                    category = metadata.get('category')

                    if downloads is not None or tagline or category:
                        self._save_metadata(mod_id_str, downloads, tagline, category)
                        loaded_count += 1

                    self.progress.emit(loaded_count, total)
                    self.msleep(50)

                logger.info(f'LoadGameBananaMetadataThread: Async loaded metadata for {loaded_count}/{total} mods')

            except Exception as async_error:
                logger.warning(f'Async metadata loading failed, falling back to sequential: {async_error}')

                loaded_count = 0
                for i in range(0, total, self._batch_size):
                    if self._cancelled or self.isInterruptionRequested():
                        break
                    for mod_id_str in self.mod_ids[i:i + self._batch_size]:
                        if self._cancelled or self.isInterruptionRequested():
                            break
                        try:
                            external_url = self._resolve_external_url(mod_id_str)
                            downloads, tagline, category = self._load_mod_metadata(int(mod_id_str), external_url=external_url)
                            if downloads is not None or tagline or category:
                                self._save_metadata(mod_id_str, downloads, tagline, category)
                                loaded_count += 1
                            else:
                                logger.debug(f'LoadGameBananaMetadataThread: Failed to load metadata for mod {mod_id_str}')
                        except (ValueError, TypeError) as e:
                            logger.warning(f'LoadGameBananaMetadataThread: Invalid mod_id {mod_id_str}: {e}')
                        except Exception as e:
                            logger.error(f'LoadGameBananaMetadataThread: Error loading metadata for mod {mod_id_str}: {e}', exc_info=True)
                        self.progress.emit(loaded_count, total)
                        self.msleep(300)
                    if i + self._batch_size < total and not self._cancelled and not self.isInterruptionRequested():
                        self.msleep(500)

            self.metadata_cache.flush()
            self.finished.emit()
        except Exception as e:
            logger.error(f'LoadGameBananaMetadataThread: Unexpected error: {e}', exc_info=True)
            self.metadata_cache.flush()
            self.finished.emit()

    def _load_mod_metadata(self, mod_id: int, external_url=None):
        try:
            try:
                downloads = self.api.get_mod_downloads_only(mod_id, external_url=external_url)
            except Exception:
                downloads = None
            try:
                desc = self.api.get_mod_description_only(mod_id, external_url=external_url)
                tagline = desc[:200].strip() if desc and len(desc[:200].strip()) >= 10 else None
            except Exception:
                tagline = None
            try:
                category = self.api.get_mod_category_only(mod_id, external_url=external_url)
            except Exception:
                category = None
            return (downloads, tagline, category)
        except Exception as e:
            logger.error(f'LoadGameBananaMetadataThread: Error loading metadata for mod {mod_id}: {e}', exc_info=True)
            return (None, None, None)
