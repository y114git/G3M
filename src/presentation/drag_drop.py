"""Qt drag-and-drop helpers for lazy file export and multi-item imports."""

import logging
import os
import shutil
import tempfile
from collections.abc import Callable

from PyQt6.QtCore import QMimeData, QTimer, QUrl

logger = logging.getLogger(__name__)


class LazyFileExportMimeData(QMimeData):
    """Create an exported file only when the drop target requests URLs."""

    INTERNAL_FORMAT = "application/x-deltahub-lazy-file-export"

    def __init__(
        self,
        exporter: Callable[[str], bool],
        filename: str,
        internal_format: str | None = None,
    ) -> None:
        super().__init__()
        self._exporter = exporter
        self._filename = filename or "export.zip"
        self._internal_format = internal_format or self.INTERNAL_FORMAT
        self._temp_dir = None
        self._temp_path = None
        self._materialized = False

    def formats(self) -> list[str]:
        return [self._internal_format, "text/uri-list"]

    def hasUrls(self) -> bool:
        return True

    def urls(self) -> list[QUrl]:
        path = self._ensure_export_ready()
        return [QUrl.fromLocalFile(path)] if path else []

    def retrieveData(self, mime_type, meta_type):
        if mime_type == self._internal_format:
            return b"1"
        if mime_type == "text/uri-list":
            return self.urls()
        return super().retrieveData(mime_type, meta_type)

    def has_materialized_export(self) -> bool:
        return bool(self._temp_path and os.path.exists(self._temp_path))

    def cleanup(self) -> None:
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._temp_dir = None
        self._temp_path = None
        self._materialized = False

    def cleanup_later(self, delay_ms: int = 5000) -> None:
        if self.has_materialized_export():
            QTimer.singleShot(delay_ms, self.cleanup)
        else:
            self.cleanup()

    def _ensure_export_ready(self) -> str | None:
        if self._materialized:
            return self._temp_path if self.has_materialized_export() else None
        self._materialized = True
        try:
            safe_name = _sanitize_export_name(self._filename)
            self._temp_dir = tempfile.mkdtemp(prefix="deltahub_export_")
            self._temp_path = os.path.join(self._temp_dir, safe_name)
            if self._exporter(self._temp_path) and os.path.exists(self._temp_path):
                return self._temp_path
        except Exception as e:
            logger.warning("Lazy file export failed for %s: %s", self._filename, e, exc_info=True)
        self.cleanup()
        return None


def collect_drop_file_paths(mime_data: QMimeData) -> list[str]:
    paths = []
    if not mime_data.hasUrls():
        return paths
    for url in mime_data.urls():
        path = url.toLocalFile()
        if path and os.path.exists(path):
            paths.append(path)
    return paths


def collect_drop_urls(mime_data: QMimeData) -> list[str]:
    urls = []
    if mime_data.hasUrls():
        for url in mime_data.urls():
            value = url.toString().strip()
            if value.startswith(("http://", "https://")):
                urls.append(value)
    if mime_data.hasText():
        text = mime_data.text().strip()
        if text.startswith(("http://", "https://")) and text not in urls:
            urls.append(text)
    return urls


def _sanitize_export_name(name: str) -> str:
    clean = "".join(c if c.isalnum() or c in " ._-" else "_" for c in (name or "export.zip")).strip()
    return clean or "export.zip"
