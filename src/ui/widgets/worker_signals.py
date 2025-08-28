from PyQt6.QtCore import QObject, pyqtSignal

class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str, str)
    result = pyqtSignal(object)
    progress = pyqtSignal(int)
    update_label = pyqtSignal(object, object, str, bool)