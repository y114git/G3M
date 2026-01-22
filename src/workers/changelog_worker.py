import os
import time
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from config.constants import NETWORK_TIMEOUT_MEDIUM
from managers.localization_manager import tr
from utils.network_utils import get_session


class FetchChangelogWorker(QObject):
    finished = pyqtSignal(str)

    def __init__(self, source_path_or_url: str, parent=None):
        super().__init__(parent)
        self.source = source_path_or_url

    @pyqtSlot()
    def run(self):
        text = ''
        try:
            if self.source.startswith(('http://', 'https://')):
                params = {'ts': int(time.time())}
                headers = {'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}
                session = get_session()
                with session.get(self.source, params=params, headers=headers, timeout=NETWORK_TIMEOUT_MEDIUM) as resp:
                    resp.raise_for_status()
                    text = resp.text
            elif os.path.exists(self.source) or os.path.exists(self.source.replace('.md', '.txt')):
                path_to_read = self.source if os.path.exists(self.source) else self.source.replace('.md', '.txt')
                with open(path_to_read, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read()
            else:
                text = self.source
        except Exception:
            text = tr('errors.changelog_load_failed')
        finally:
            self.finished.emit(text)
