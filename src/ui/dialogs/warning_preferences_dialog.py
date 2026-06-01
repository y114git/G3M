"""Warning preference editor."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config.config import QSS_ARROW_LABEL, QSS_BOLD_TRANSPARENT
from services.localization_service import tr
from services.warning_service import (
    WarningSeverity,
    iter_warning_definitions,
    normalize_warning_preferences,
)
from ui.common.dialog_theme import apply_dialog_theme
from ui.common.styling import get_section_line_color
from ui.utils.ui_utils import UIAnimator


class WarningPreferencesDialog(QDialog):
    def __init__(self, local_config: dict, parent=None) -> None:
        super().__init__(parent)
        self.local_config = local_config
        self.app_state = getattr(parent, "app_state", None)
        self.preferences = normalize_warning_preferences(self.local_config)
        self.warning_checkboxes: dict[str, QCheckBox] = {}
        self.warning_help_buttons: dict[str, QToolButton] = {}
        self.section_title_labels: dict[WarningSeverity, QLabel] = {}
        self.section_arrows: dict[WarningSeverity, QLabel] = {}
        self.section_content_widgets: dict[WarningSeverity, QWidget] = {}
        self._warning_definitions = iter_warning_definitions()
        self.warning_definitions_by_id = {
            item.warning_id: item for item in self._warning_definitions
        }
        self.setObjectName("warning_preferences_dialog")
        self.setMinimumWidth(680)
        self._build_ui()
        self.relocalize_ui()
        self._load_preferences()
        self._apply_state()
        apply_dialog_theme(self, self.app_state)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.title_label = QLabel()
        self.title_label.setObjectName("warning_preferences_title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        self.skip_all_checkbox = QCheckBox()
        self.skip_all_checkbox.setObjectName("skip_all_warnings_checkbox")
        self.skip_all_checkbox.setChecked(bool(self.preferences.get("skip_all", False)))
        self.skip_all_checkbox.stateChanged.connect(lambda _state: self._apply_state())
        layout.addWidget(self.skip_all_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(scroll)
        self.sections_layout = QVBoxLayout(content)
        self.sections_layout.setSpacing(10)
        self.sections_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        for severity in (
            WarningSeverity.CRITICAL,
            WarningSeverity.MAJOR,
            WarningSeverity.MINOR,
        ):
            section_widget, section_layout = self._create_warning_section(
                severity, content
            )
            self.sections_layout.addWidget(section_widget)
            for definition in (
                item for item in self._warning_definitions if item.severity == severity
            ):
                row = QWidget(content)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(6)
                checkbox = QCheckBox()
                checkbox.setObjectName(f"warning_item_{definition.warning_id}")
                checkbox.setProperty("warning_id", definition.warning_id)
                self.warning_checkboxes[definition.warning_id] = checkbox
                help_button = QToolButton(row)
                help_button.setObjectName(f"warning_help_{definition.warning_id}")
                help_button.setText("?")
                help_button.setAutoRaise(True)
                help_button.setCursor(Qt.CursorShape.WhatsThisCursor)
                self.warning_help_buttons[definition.warning_id] = help_button
                row_layout.addWidget(checkbox, stretch=1)
                row_layout.addWidget(help_button)
                section_layout.addWidget(row)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _create_warning_section(
        self, severity: WarningSeverity, parent: QWidget
    ) -> tuple[QWidget, QVBoxLayout]:
        section = QWidget(parent)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 8, 0, 4)
        section_layout.setSpacing(6)

        header = QWidget(section)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        line_color = get_section_line_color(self.local_config)
        line_style = f"color: {line_color};"
        line_left = QFrame(header)
        line_left.setFrameShape(QFrame.Shape.HLine)
        line_left.setFrameShadow(QFrame.Shadow.Sunken)
        line_left.setStyleSheet(line_style)
        header_layout.addWidget(line_left, stretch=1)

        title_label = QLabel(header)
        title_label.setObjectName(f"warning_section_{severity.value}")
        title_label.setStyleSheet(QSS_BOLD_TRANSPARENT)
        self.section_title_labels[severity] = title_label
        header_layout.addWidget(title_label)

        arrow = QLabel("▼", header)
        arrow.setStyleSheet(QSS_ARROW_LABEL)
        self.section_arrows[severity] = arrow
        header_layout.addWidget(arrow)

        line_right = QFrame(header)
        line_right.setFrameShape(QFrame.Shape.HLine)
        line_right.setFrameShadow(QFrame.Shadow.Sunken)
        line_right.setStyleSheet(line_style)
        header_layout.addWidget(line_right, stretch=1)

        content = QWidget(section)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(22, 8, 22, 8)
        content_layout.setSpacing(8)
        self.section_content_widgets[severity] = content

        header.mousePressEvent = lambda _event, value=severity: self._toggle_section(
            value
        )

        section_layout.addWidget(header)
        section_layout.addWidget(content)
        return section, content_layout

    def _toggle_section(self, severity: WarningSeverity) -> None:
        content = self.section_content_widgets[severity]
        is_expanded = content.isHidden()
        self.section_arrows[severity].setText("▼" if is_expanded else "▶")
        UIAnimator.collapse_expand(content, is_expanded, 200, self.app_state)

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("warnings.manage_title"))
        self.title_label.setText(tr("warnings.manage_title"))
        self.skip_all_checkbox.setText(tr("warnings.skip_all"))
        self.skip_all_checkbox.setToolTip(tr("warnings.skip_all_tooltip"))
        for severity, label in self.section_title_labels.items():
            label.setText(tr(f"warnings.sections.{severity.value}"))
        for warning_id, checkbox in self.warning_checkboxes.items():
            definition = self.warning_definitions_by_id[warning_id]
            checkbox.setText(tr(definition.label_key))
            tooltip = tr(definition.tooltip_key)
            checkbox.setToolTip(tooltip)
            self.warning_help_buttons[warning_id].setToolTip(tooltip)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText(
            tr("ui.ok")
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).setText(
            tr("ui.cancel_button")
        )

    def _load_preferences(self) -> None:
        warning_overrides = self.preferences.get("warning_overrides", {})
        for warning_id, checkbox in self.warning_checkboxes.items():
            definition = self.warning_definitions_by_id[warning_id]
            checkbox.blockSignals(True)
            checkbox.setChecked(
                bool(warning_overrides.get(warning_id, definition.enabled_by_default))
            )
            checkbox.blockSignals(False)

    def _apply_state(self) -> None:
        skip_all = self.skip_all_checkbox.isChecked()
        for checkbox in self.warning_checkboxes.values():
            checkbox.setEnabled(not skip_all)

    def accept(self) -> None:
        warning_overrides = {}
        for warning_id, checkbox in self.warning_checkboxes.items():
            default = self.warning_definitions_by_id[warning_id].enabled_by_default
            if checkbox.isChecked() != default:
                warning_overrides[warning_id] = checkbox.isChecked()
        self.local_config["warning_preferences"] = {
            "skip_all": self.skip_all_checkbox.isChecked(),
            "warning_overrides": warning_overrides,
        }
        super().accept()
