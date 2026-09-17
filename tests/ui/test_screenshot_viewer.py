from unittest.mock import patch

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QToolButton

from services.localization_service import tr
from ui.widgets import mod_details_overlay
from ui.widgets.mod_details_overlay import ScreenshotViewerDialog


def test_screenshot_viewer_resizes_with_localized_navigation(qapp) -> None:
    with patch.object(ScreenshotViewerDialog, "_load"):
        dialog = ScreenshotViewerDialog(
            ["https://example.invalid/1.png", "https://example.invalid/2.png"]
        )
    dialog.show()
    qapp.processEvents()

    assert isinstance(dialog._prev, QToolButton)
    assert isinstance(dialog._next, QToolButton)
    assert dialog.windowTitle() == tr("ui.screenshot")
    assert dialog._label.accessibleName() == tr("ui.screenshot")
    assert dialog._prev.accessibleName() == tr("onboarding.back_button")
    assert dialog._next.accessibleName() == tr("onboarding.next_button")
    assert dialog._prev.minimumWidth() >= 36
    assert dialog._next.minimumWidth() >= 36

    image = QImage(1600, 900, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    dialog._on_image_loaded(None, 0, image)
    dialog.resize(500, 360)
    qapp.processEvents()

    pixmap = dialog._label.pixmap()
    assert pixmap is not None
    assert pixmap.width() <= dialog._label.width()
    assert pixmap.height() <= dialog._label.height()
    assert dialog.minimumWidth() <= 500
    assert dialog.minimumHeight() <= 360
    dialog.close()


def test_screenshot_context_menu_has_the_three_image_actions(qapp) -> None:
    actions = []
    with (
        patch.object(ScreenshotViewerDialog, "_load"),
        patch.object(
            mod_details_overlay._ScreenshotContextMenu,
            "exec",
            lambda menu, *_args: actions.extend(
                action.text() for action in menu.actions()
            ),
        ),
    ):
        dialog = ScreenshotViewerDialog(["https://example.invalid/1.png"])
        dialog.show()
        qapp.processEvents()
        dialog._show_context_menu(QPoint())
        qapp.processEvents()

    assert actions == [
        tr("ui.open_image_in_browser"),
        tr("ui.copy_image"),
        tr("ui.copy_image_url"),
    ]
    dialog.close()


def test_screenshot_viewer_clears_the_previous_image_before_navigation(qapp) -> None:
    with patch.object(ScreenshotViewerDialog, "_load") as load:
        dialog = ScreenshotViewerDialog(
            ["https://example.invalid/1.png", "https://example.invalid/2.png"]
        )
        image = QImage(16, 16, QImage.Format.Format_RGB32)
        image.fill(0x336699)
        dialog._source_pixmap = QPixmap.fromImage(image)
        dialog._label.setPixmap(dialog._source_pixmap)

        dialog._shift(1)

    assert dialog._source_pixmap.isNull()
    assert dialog._label.pixmap() is None or dialog._label.pixmap().isNull()
    assert dialog._index == 1
    assert load.call_count == 2
    dialog.close()
