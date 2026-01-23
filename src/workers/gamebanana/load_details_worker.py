"""GameBanana mod details loading worker.

This module provides a worker thread for loading detailed mod information from GameBanana.
"""
import logging
import json
from typing import List
from PyQt6.QtCore import QThread, pyqtSignal
from models.mod_models import ModInfo
from adapters.gamebanana_adapter import GameBananaAPI
logger = logging.getLogger(__name__)


class LoadGameBananaDetailsThread(QThread):
    progress = pyqtSignal(int, int)
    mod_updated = pyqtSignal(ModInfo)
    finished = pyqtSignal()

    def __init__(self, mods: List[ModInfo], parent=None):
        super().__init__(parent)
        self.mods = mods
        self.api = GameBananaAPI()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            if self._cancelled:
                self.finished.emit()
                return
            gb_mods = [m for m in self.mods if getattr(m, 'key', None) and getattr(m, 'key', None).startswith('gb_')]
            total = len(gb_mods)
            if total == 0:
                self.finished.emit()
                return
            if self._cancelled:
                self.finished.emit()
                return
            for idx, mod in enumerate(gb_mods):
                if self._cancelled:
                    break
                try:
                    key = getattr(mod, 'key', None)
                    mod_id_str = key.replace('gb_', '', 1) if key else None
                    if not mod_id_str:
                        continue
                    mod_id = int(mod_id_str)
                    has_full_desc = hasattr(mod, 'full_description') and mod.full_description and mod.full_description.strip()
                    has_tagline = hasattr(mod, 'tagline') and mod.tagline and mod.tagline.strip()
                    needs_load = not has_full_desc or not has_tagline
                    if not needs_load:
                        continue
                    original_downloads = getattr(mod, 'downloads', 0)
                    if idx > 0:
                        import time
                        time.sleep(0.1)
                        if self._cancelled:
                            break
                    external_url = getattr(mod, 'external_url', None)
                    full_details = self.api.get_mod_full_details_for_display(mod_id, external_url=external_url)
                    if self._cancelled:
                        break
                    if full_details:
                        if self._cancelled:
                            break
                        self._update_mod_with_details(mod, full_details, original_downloads)
                        if not self._cancelled and (mod.full_description or mod.downloads is not None or mod.screenshots_url or mod.tagline):
                            try:
                                self.mod_updated.emit(mod)
                            except Exception as e:
                                logger.error(f'LoadGameBananaDetailsThread: Error emitting mod_updated signal for mod {mod_id}: {e}', exc_info=True)
                except Exception as e:
                    key = getattr(mod, 'key', None)
                    mod_id_str = key.replace('gb_', '', 1) if key else 'unknown'
                    logger.error(f'LoadGameBananaDetailsThread: Error loading details for mod {mod_id_str}: {e}', exc_info=True)
                    continue
                if self._cancelled:
                    break
                if (idx + 1) % 5 == 0 or idx + 1 == total:
                    if not self._cancelled:
                        self.progress.emit(idx + 1, total)
        except Exception as e:
            logger.error(f'LoadGameBananaDetailsThread: Unexpected error in run: {e}', exc_info=True)
        finally:
            self.finished.emit()

    def _update_mod_with_details(self, mod: ModInfo, full_details: dict, fallback_downloads: int = 0):
        import re

        def _extract_text_value(field):
            if not field:
                return None
            if isinstance(field, list) and len(field) > 0:
                return field[0]
            if isinstance(field, str):
                return field
            return str(field)
        text_value = _extract_text_value(full_details.get('text'))
        if text_value and text_value.strip():
            mod.full_description = text_value
        desc_value = _extract_text_value(full_details.get('description'))
        if desc_value and desc_value.strip():
            mod.tagline = desc_value
        if (not hasattr(mod, 'tagline') or not mod.tagline) and hasattr(mod, 'full_description') and mod.full_description:
            tagline_clean = re.sub('<[^>]+>', '', mod.full_description)
            mod.tagline = tagline_clean[:200].strip()
            if len(tagline_clean) > 200:
                mod.tagline += '...'
        if fallback_downloads is not None and fallback_downloads >= 0:
            mod.downloads = fallback_downloads
        elif not hasattr(mod, 'downloads') or mod.downloads is None:
            mod.downloads = 0
        screenshots_field = full_details.get('screenshots')
        if screenshots_field:
            external_url = getattr(mod, 'external_url', None)
            is_wip = external_url and '/wips/' in external_url
            screenshots_data = None
            if isinstance(screenshots_field, list) and len(screenshots_field) > 0:
                screenshots_data = screenshots_field[0]
            elif not isinstance(screenshots_field, list):
                screenshots_data = screenshots_field
            if isinstance(screenshots_data, str):
                mod.screenshots_url = self.api.extract_screenshots_from_api(screenshots_data, external_url=external_url)
            elif isinstance(screenshots_data, list):
                screenshots = []
                base_url = 'https://images.gamebanana.com/img/ss/wips' if is_wip else 'https://images.gamebanana.com/img/ss/mods'
                for screenshot_obj in screenshots_data:
                    if isinstance(screenshot_obj, dict):
                        file_name = screenshot_obj.get('_sFile') or screenshot_obj.get('_sFile800') or screenshot_obj.get('_sFile530') or screenshot_obj.get('_sFile220')
                        if file_name:
                            screenshot_url = f'{base_url}/{file_name}'
                            screenshots.append(screenshot_url)
                mod.screenshots_url = screenshots
            elif isinstance(screenshots_data, dict):
                try:
                    screenshots_str = json.dumps(screenshots_data)
                    mod.screenshots_url = self.api.extract_screenshots_from_api(screenshots_str, external_url=external_url)
                except (TypeError, ValueError):
                    mod.screenshots_url = []
            else:
                mod.screenshots_url = []
