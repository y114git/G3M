import platform
from PyQt6.QtWidgets import QVBoxLayout, QWidget, QLabel
from PyQt6.QtCore import Qt


class SystemMonitorWidget(QWidget):
    def __init__(self, main_app_instance):
        super().__init__()
        self.main_app = main_app_instance
        self.tr = main_app_instance.lang_manager.get_text

        self.setStyleSheet(self.main_app.styleSheet())

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_label = QLabel("<b>System Information</b>")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        os_label = QLabel(f"<b>Operating System:</b> {platform.system()}")
        os_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(os_label)

        platform_label = QLabel(f"<b>Platform:</b> {platform.platform()}")
        platform_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(platform_label)

        arch_label = QLabel(f"<b>Architecture:</b> {platform.architecture()[0]}")
        arch_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(arch_label)
