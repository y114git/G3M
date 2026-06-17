"""Unit tests for background loading worker."""

from __future__ import annotations

from PyQt6.QtCore import QSize

from workers.background_loader_worker import BgLoader


def test_background_loader_emits_fallback_for_malformed_path(qapp):
    worker = BgLoader(None, QSize(640, 480))
    loaded = []
    worker.loaded.connect(lambda payload: loaded.append(payload))

    worker.run()

    assert len(loaded) == 1
    assert loaded[0][0] == "img"
    assert loaded[0][1].isNull()
