from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QWIDGETSIZE_MAX, QApplication


class TestFilterScaling:
    """Tests for filter scaling."""
    """Test filter widget scaling behavior to prevent regression of scale-down bug.

    The fix: theme_controller resets maximumHeight on filter scroll areas to 16777215
    BEFORE applying the new stylesheet. This breaks the circular dependency where
    the old maximumHeight prevents inner widgets from shrinking when scaling down.
    The event filters then correctly re-set maximumHeight based on the new sizeHint.
    """

    def test_library_maximum_height_reset_allows_shrink(self, qapp, app_state, feedback_service):
        """Checks that librarying maximum height reset allows shrink."""
        from ui.builders.library_tab_builder import LibraryTabBuilder

        builder = LibraryTabBuilder(app_state, None)
        widget = builder.build()
        widget.show()
        QApplication.processEvents()

        filters_scroll = builder.widgets.get('filters_scroll')
        assert filters_scroll is not None

        filters_scroll.setMaximumHeight(500)
        QApplication.processEvents()

        filters_scroll.setMaximumHeight(QWIDGETSIZE_MAX)
        QApplication.processEvents()

        assert filters_scroll.maximumHeight() == QWIDGETSIZE_MAX

        widget.close()
        widget.deleteLater()
        QApplication.processEvents()

    def test_search_maximum_height_reset_allows_shrink(self, qapp, app_state, feedback_service):
        """Checks that searching maximum height reset allows shrink."""
        from ui.builders.search_tab_builder import ModsBrowserTabBuilder

        builder = ModsBrowserTabBuilder(app_state, None)
        widget = builder.build()
        widget.show()
        QApplication.processEvents()

        filters_scroll = builder.widgets.get('filters_scroll')
        assert filters_scroll is not None

        filters_scroll.setMaximumHeight(500)
        QApplication.processEvents()

        filters_scroll.setMaximumHeight(QWIDGETSIZE_MAX)
        QApplication.processEvents()

        assert filters_scroll.maximumHeight() == QWIDGETSIZE_MAX

        widget.close()
        widget.deleteLater()
        QApplication.processEvents()

    def test_library_eventfilter_sets_maxheight(self, qapp, app_state, feedback_service):
        """Checks that librarying eventfilter sets maxheight."""
        from ui.builders.library_tab_builder import LibraryTabBuilder

        builder = LibraryTabBuilder(app_state, None)
        widget = builder.build()
        widget.show()
        QApplication.processEvents()

        filters_scroll = builder.widgets.get('filters_scroll')
        filters_widget = filters_scroll.widget()

        resize_event = QEvent(QEvent.Type.Resize)
        builder.eventFilter(filters_widget, resize_event)

        assert filters_scroll.maximumHeight() == filters_widget.sizeHint().height()

        widget.close()
        widget.deleteLater()
        QApplication.processEvents()

    def test_search_eventfilter_sets_maxheight(self, qapp, app_state, feedback_service):
        """Checks that searching eventfilter sets maxheight."""
        from ui.builders.search_tab_builder import ModsBrowserTabBuilder

        builder = ModsBrowserTabBuilder(app_state, None)
        widget = builder.build()
        widget.show()
        QApplication.processEvents()

        filters_scroll = builder.widgets.get('filters_scroll')
        filters_widget = filters_scroll.widget()

        resize_event = QEvent(QEvent.Type.Resize)
        builder.eventFilter(filters_widget, resize_event)

        assert filters_scroll.maximumHeight() == filters_widget.sizeHint().height()

        widget.close()
        widget.deleteLater()
        QApplication.processEvents()
