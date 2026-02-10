"""Handles batched metadata updates for GameBanana mods in search results."""
import logging
from PyQt6.QtCore import QTimer
from utils.mod_utils import get_gamebanana_mod_id

logger = logging.getLogger(__name__)


class SearchMetadataHandler:
    """Manages pending metadata updates with debounced batch application."""

    def __init__(self, app_state, app_window,
                 update_filtered_mods_cb, update_cards_cb):
        self.app_state = app_state
        self.app = app_window
        self._update_filtered_mods = update_filtered_mods_cb
        self._update_cards_for_mods = update_cards_cb
        self._pending_metadata_updates = {}
        self._metadata_update_timer = None

    def on_metadata_updated(self, mod_id: str, downloads: int, tagline: str, category: str = ''):
        try:
            if downloads is not None or tagline or category:
                try:
                    if hasattr(self.app, 'refresh_controller') and self.app.refresh_controller:
                        if hasattr(self.app.refresh_controller, '_current_metadata_batch'):
                            if mod_id in self.app.refresh_controller._current_metadata_batch:
                                self.app.refresh_controller._current_metadata_batch.remove(mod_id)
                                logger.debug(f'SearchMetadataHandler: Removed mod {mod_id} from current batch after successful load')
                        if hasattr(self.app_state, 'gamebanana_mods_needing_metadata') and self.app_state.gamebanana_mods_needing_metadata:
                            if mod_id in self.app_state.gamebanana_mods_needing_metadata:
                                self.app_state.gamebanana_mods_needing_metadata.remove(mod_id)
                                logger.debug(f'SearchMetadataHandler: Removed mod {mod_id} from metadata queue after successful load')
                except (ValueError, AttributeError) as e:
                    logger.debug(f'SearchMetadataHandler: Error removing mod {mod_id} from queue: {e}')
            self._pending_metadata_updates[mod_id] = (downloads, tagline, category)
            if self._metadata_update_timer is None:
                self._metadata_update_timer = QTimer()
                self._metadata_update_timer.setSingleShot(True)
                self._metadata_update_timer.timeout.connect(self.apply_pending_updates)
            self._metadata_update_timer.stop()
            self._metadata_update_timer.start(1500)
        except Exception as e:
            logger.error(f'SearchMetadataHandler: Error in on_metadata_updated: {e}', exc_info=True)

    def apply_pending_updates(self):
        try:
            if not self._pending_metadata_updates:
                return
            updated_mods = []
            needs_refilter = False
            downloads_changed = False
            if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                for mod in self.app_state.all_mods:
                    mod_id = get_gamebanana_mod_id(mod)
                    if not mod_id or mod_id not in self._pending_metadata_updates:
                        continue
                    update_data = self._pending_metadata_updates[mod_id]
                    if len(update_data) >= 3:
                        downloads, tagline, category = update_data
                    else:
                        downloads, tagline = (update_data[0], update_data[1])
                        category = ''
                    if downloads is not None and downloads >= 0:
                        old_downloads = getattr(mod, 'downloads', None)
                        if old_downloads is None:
                            old_downloads = 0
                        else:
                            try:
                                old_downloads = int(old_downloads)
                            except (ValueError, TypeError):
                                old_downloads = 0
                        try:
                            downloads_int = int(downloads)
                        except (ValueError, TypeError):
                            downloads_int = 0
                        if old_downloads != downloads_int:
                            mod.downloads = downloads_int
                            downloads_changed = True
                    if tagline and tagline != 'No description' and (mod.tagline != tagline):
                        mod.tagline = tagline
                    if category:
                        if not hasattr(mod, 'gamebanana_category') or mod.gamebanana_category != category:
                            mod.gamebanana_category = category
                            needs_refilter = True
                    try:
                        mod.has_full_metadata = True
                    except Exception:
                        pass
                    updated_mods.append(mod_id)
            self._pending_metadata_updates.clear()
            sort_needs_resort = False
            sort_type = None
            if hasattr(self.app, 'sort_combo'):
                sort_type = self.app.sort_combo.currentIndex()
                if sort_type == 0 and downloads_changed and (len(updated_mods) > 1):
                    sort_needs_resort = True
            if (sort_needs_resort or needs_refilter) and len(updated_mods) > 1:
                logger.debug(f"SearchMetadataHandler: Re-sorting mods after metadata update (downloads_changed={downloads_changed}, needs_refilter={needs_refilter}, sort_type={(sort_type if sort_type is not None else 'N/A')}, mods_count={len(updated_mods)})")
                self._update_filtered_mods(preserve_page=True)
            elif updated_mods:
                self._update_cards_for_mods(updated_mods)
        except Exception as e:
            logger.error(f'SearchMetadataHandler: Error in apply_pending_updates: {e}', exc_info=True)
            self._pending_metadata_updates.clear()
