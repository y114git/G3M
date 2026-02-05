"""Background image loading worker."""
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage


class BgLoader(QThread):
    loaded = pyqtSignal(object)

    def __init__(self, path: str, size):
        super().__init__()
        self._path, self._size = path, size

    def run(self):
        self.loaded.emit(('gif', self._path) if self._path.lower().endswith('.gif') else ('img', QImage(self._path)))
