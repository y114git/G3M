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

        self.intro_label = QLabel()
        self.intro_label.setWordWrap(True)
        self.intro_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        layout.addWidget(self.intro_label)

        self.benefits_label = QLabel()
        self.benefits_label.setWordWrap(True)
        self.benefits_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        layout.addWidget(self.benefits_label)

        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        layout.addWidget(self.warning_label)

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
        self.relocalize_ui()

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("dialogs.po_convert_title"))
        self.intro_label.setText(tr("dialogs.po_convert_intro"))
        self.benefits_label.setText(tr("dialogs.po_convert_benefits"))
        self.warning_label.setText(tr("dialogs.po_convert_original_files_warning"))
        self.start_button.setText(tr("buttons.start_po_convert"))
        self.cancel_button.setText(tr("dialogs.cancel"))
