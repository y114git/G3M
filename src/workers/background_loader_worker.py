"""Background image loading worker."""

import logging

from PyQt6.QtCore import QSize, QThread, pyqtSignal
from PyQt6.QtGui import QImage

logger = logging.getLogger(__name__)


def _safe_emit(owner: str, signal, *args) -> None:
    try:
        signal.emit(*args)
    except Exception as e:
        logger.warning("%s: failed to emit signal: %s", owner, e, exc_info=True)


class BgLoader(QThread):
    loaded = pyqtSignal(object)

    def __init__(self, path: str, size: QSize) -> None:
        super().__init__()
        self._path, self._size = path, size

    def run(self) -> None:
        try:
            path = self._path if isinstance(self._path, str) else ""
            ext = path.lower().split(".")[-1] if "." in path else ""
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
                result = ("video", path)
            elif ext == "gif":
                result = ("gif", path)
            else:
                result = ("img", QImage(path))
        except Exception as e:
            logger.warning("BgLoader: failed to load background %r: %s", self._path, e, exc_info=True)
            result = ("img", QImage())
        _safe_emit(self.__class__.__name__, self.loaded, result)
