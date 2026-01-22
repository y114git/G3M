from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage


class BgLoader(QThread):
    loaded = pyqtSignal(object)

    def __init__(self, path: str, size):
        super().__init__()
        self._path = path
        self._size = size

    def run(self):
        if self._path.lower().endswith('.gif'):
            self.loaded.emit(('gif', self._path))
        else:
            img = QImage(self._path)
            self.loaded.emit(('img', img))
