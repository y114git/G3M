import logging
from PyQt6.QtCore import QObject, QTimer, QByteArray
from PyQt6.QtWidgets import QWidget
from typing import Optional


class WindowGeometryManager(QObject):

    def __init__(self, app_state, settings_manager, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.settings_manager = settings_manager
        self._geometry_save_timer: Optional[QTimer] = None

    def load_window_geometry(self, widget: QWidget) -> bool:
        saved = self.app_state.local_config.get('window_geometry')
        if not saved:
            return False
        try:
            widget.restoreGeometry(QByteArray.fromHex(saved.encode()))
            return True
        except Exception as e:
            logging.debug(f'load_window_geometry: failed: {e}')
            return False

    def save_window_geometry(self, widget: QWidget):
        geom_ba = widget.saveGeometry()
        self.app_state.local_config['window_geometry'] = geom_ba.toHex().data().decode()
        self.settings_manager.write_local_config()

    def schedule_geometry_save(self, widget: QWidget, timeout_ms: int = 500):
        if self._geometry_save_timer is None:
            self._geometry_save_timer = QTimer()
            self._geometry_save_timer.setSingleShot(True)
            self._geometry_save_timer.timeout.connect(lambda: self.save_window_geometry(widget))
        else:
            self._geometry_save_timer.stop()
        self._geometry_save_timer.start(timeout_ms)

    def lock_window_size(self, widget: QWidget):
        try:
            sz = widget.size()
            widget.setMinimumSize(sz)
            widget.setMaximumSize(sz)
        except Exception as e:
            logging.debug(f'lock_window_size: failed: {e}')

    def unlock_window_size(self, widget: QWidget):
        try:
            widget.setMinimumSize(0, 0)
            widget.setMaximumSize(16777215, 16777215)
        except Exception as e:
            logging.debug(f'unlock_window_size: failed: {e}')
