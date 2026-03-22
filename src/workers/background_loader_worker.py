"""Background image loading worker."""

from PyQt6.QtCore import QSize, QThread, pyqtSignal
from PyQt6.QtGui import QImage


class BgLoader(QThread):
    loaded = pyqtSignal(object)

    def __init__(self, path: str, size: QSize) -> None:
        super().__init__()
        self._path, self._size = path, size

    def run(self) -> None:
        ext = self._path.lower().split(".")[-1] if "." in self._path else ""
        if ext in (
            "mp4",
            "webm",
            "avi",
            "mkv",
            "mov",
            "m4v",
            "3gp",
            "mpg",
            "mpeg",
            "flv",
            "wmv",
        ):
            result = ("video", self._path)
        elif ext == "gif":
            result = ("gif", self._path)
        else:
            result = ("img", QImage(self._path))
        self.loaded.emit(result)
