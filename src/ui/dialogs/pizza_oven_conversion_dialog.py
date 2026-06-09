"""Dialog for Pizza Oven conversion options and progress."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from services.localization_service import tr


class PizzaOvenConversionDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dialogs.po_convert_title"))
        self.setModal(True)
        self.resize(560, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        intro = QLabel(tr("dialogs.po_convert_intro"))
        intro.setWordWrap(True)
        intro.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(intro)

        benefits = QLabel(tr("dialogs.po_convert_benefits"))
        benefits.setWordWrap(True)
        benefits.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(benefits)

        warning = QLabel(tr("dialogs.po_convert_original_files_warning"))
        warning.setWordWrap(True)
        warning.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(warning)

        layout.addStretch()

        button_box = QDialogButtonBox()
        self.start_button = button_box.addButton(
            tr("buttons.start_po_convert"),
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.cancel_button = button_box.addButton(
            tr("dialogs.cancel"), QDialogButtonBox.ButtonRole.RejectRole
        )
        self.start_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(button_box)
