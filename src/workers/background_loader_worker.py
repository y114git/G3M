"""Background image loading worker."""

import logging

from PyQt6.QtCore import QSize, pyqtSignal
from PyQt6.QtGui import QImage

from ui.utils.thread_lifetime import ManagedQThread
from ui.utils.thread_lifetime import safe_emit as _safe_emit

logger = logging.getLogger(__name__)


class BgLoader(ManagedQThread):
    loaded = pyqtSignal(object)

    def __init__(self, path: object, size: QSize) -> None:
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
            logger.warning(
                "BgLoader: failed to load background %r: %s",
                self._path,
                e,
                exc_info=True,
            )
            result = ("img", QImage())
        _safe_emit(self.__class__.__name__, self.loaded, result)
