import logging
from typing import List, Optional
from PyQt6.QtCore import QThread, pyqtSignal
from utils.gamebanana_api import GameBananaAPI
from utils.gamebanana_cache import GameBananaMetadataCache
logger = logging.getLogger(__name__)


class LoadGameBananaMetadataThread(QThread):
    mod_updated = pyqtSignal(str, int, str, str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal()

    def __init__(self, mod_ids: List[str], metadata_cache: GameBananaMetadataCache, parent=None):
        super().__init__(parent)
        self.mod_ids = mod_ids
        self.metadata_cache = metadata_cache
        self.api = GameBananaAPI()
        self._cancelled = False
        self._batch_size = 5

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            total = len(self.mod_ids)
            if total == 0:
                logger.debug('LoadGameBananaMetadataThread: No mods to load metadata for')
                self.finished.emit()
                return
            loaded_count = 0
            for i in range(0, total, self._batch_size):
                if self._cancelled or self.isInterruptionRequested():
                    break
                batch = self.mod_ids[i:i + self._batch_size]
                for mod_id_str in batch:
                    if self._cancelled or self.isInterruptionRequested():
                        break
                    try:
                        mod_id = int(mod_id_str)
                        downloads, tagline, category = self._load_mod_metadata(mod_id)
                        downloads = downloads if downloads is not None else 0
                        tagline = tagline if tagline else 'No description'
                        category = category if category else None
                        self.metadata_cache.set(mod_id_str, downloads, tagline, category=category)
                        self.mod_updated.emit(mod_id_str, downloads, tagline, category or '')
                        loaded_count += 1
                    except (ValueError, TypeError) as e:
                        logger.warning(f'LoadGameBananaMetadataThread: Invalid mod_id {mod_id_str}: {e}')
                        continue
                    except Exception as e:
                        logger.error(f'LoadGameBananaMetadataThread: Error loading metadata for mod {mod_id_str}: {e}', exc_info=True)
                        continue
                    self.progress.emit(loaded_count, total)
                if i + self._batch_size < total and (not self._cancelled) and (not self.isInterruptionRequested()):
                    self.msleep(100)
            self.finished.emit()
        except Exception as e:
            logger.error(f'LoadGameBananaMetadataThread: Unexpected error: {e}', exc_info=True)
            self.finished.emit()

    def _load_mod_metadata(self, mod_id: int) -> tuple[Optional[int], Optional[str], Optional[str]]:
        downloads = None
        tagline = None
        category = None
        try:
            try:
                downloads = self.api.get_mod_downloads_only(mod_id)
            except Exception:
                downloads = None
            try:
                description = self.api.get_mod_description_only(mod_id)
                if description:
                    tagline = description[:200].strip()
                    if not tagline or len(tagline) < 10:
                        tagline = None
            except Exception:
                tagline = None
            try:
                category = self.api.get_mod_category_only(mod_id)
            except Exception:
                category = None
            return (downloads, tagline, category)
        except Exception as e:
            logger.error(f'LoadGameBananaMetadataThread: Error loading metadata for mod {mod_id}: {e}', exc_info=True)
            return (None, None, None)
