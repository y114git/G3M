"""Background image loading worker."""
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage


class BgLoader(QThread):
    loaded = pyqtSignal(object)

    def __init__(self, path: str, size):
        super().__init__()
        self._path, self._size = path, size

    def run(self):
        ext = self._path.lower().split('.')[-1] if '.' in self._path else ''
        self.loaded.emit(('video', self._path) if ext in ('mp4', 'webm', 'avi', 'mkv', 'mov', 'm4v', '3gp', 'mpg', 'mpeg', 'flv', 'wmv') else (('gif', self._path) if ext == 'gif' else ('img', QImage(self._path))))
