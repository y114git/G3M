"""Configurable local support archive dialog."""

from __future__ import annotations

import statistics
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.config import QSS_ARROW_LABEL, QSS_BOLD_TRANSPARENT
from services.localization_service import tr
from services.support_package_service import SupportPackageService
from ui.common.dialog_theme import apply_dialog_theme
from ui.common.styling import get_section_line_color
from ui.utils.ui_utils import UIAnimator
from workers.support_package_worker import SupportPackageWorker


class SupportPackagerDialog(QDialog):
    def __init__(self, app_state, parent=None, service=None) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._service = service or SupportPackageService(
            app_state, mod_service=getattr(parent, "mod_service", None)
        )
        self._worker = None
        self._items: dict[str, QCheckBox] = {}
        self._labels: dict[str, tuple[str, bool]] = {}
        self._section_titles: dict[str, tuple[QLabel, str, bool]] = {}
        self._section_arrows: dict[str, QLabel] = {}
        self._section_contents: dict[str, QWidget] = {}
        self._section_lines: list[QFrame] = []
        self._ui_intervals: list[float] = []
        self._last_ui_tick = time.perf_counter()
        self.setObjectName("support_packager_dialog")
        self.setMinimumSize(700, 620)
        self.resize(820, 760)
        self._build_ui()
        self.relocalize_ui()
        self._apply_custom_state()
        self.refresh_theme()
        self._sample_timer = QTimer(self)
        self._sample_timer.setInterval(16)
        self._sample_timer.timeout.connect(self._record_ui_tick)
        self._sample_timer.start()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        self._title = QLabel()
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet(QSS_BOLD_TRANSPARENT)
        layout.addWidget(self._title)
        self._description = QLabel()
        self._description.setWordWrap(True)
        self._description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._description)
        self._custom = QCheckBox()
        self._custom.setChecked(False)
        self._custom.stateChanged.connect(lambda _state: self._apply_custom_state())

        self._sections_scroll = QScrollArea(self)
        self._sections_scroll.setWidgetResizable(True)
        self._sections_scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(self._sections_scroll)
        self._sections_layout = QVBoxLayout(content)
        self._sections_layout.setContentsMargins(0, 0, 0, 0)
        self._sections_layout.setSpacing(10)
        self._sections_scroll.setWidget(content)
        layout.addWidget(self._sections_scroll, 1)
        self._populate_sections(content)
        self._sections_layout.addStretch(1)

        range_row = QHBoxLayout()
        self._range_label = QLabel()
        self._range = QComboBox()
        for days in (None, 1, 7, 30):
            self._range.addItem("", days)
        range_row.addWidget(self._range_label)
        range_row.addWidget(self._range, 1)
        layout.addLayout(range_row)

        buttons = QHBoxLayout()
        buttons.addWidget(self._custom)
        buttons.addStretch(1)
        self._cancel = QPushButton()
        self._cancel.clicked.connect(self.reject)
        self._build = QPushButton()
        self._build.clicked.connect(self._choose_destination)
        buttons.addWidget(self._cancel)
        buttons.addWidget(self._build)
        layout.addLayout(buttons)
        self._apply_custom_state()

    def _populate_sections(self, parent: QWidget) -> None:
        self._add_section(
            parent,
            "application",
            "support_packager.category.application",
            [
                ("app.version", "support_packager.field.version", True),
                ("app.selection", "support_packager_app.selection", True),
                ("app.operations", "support_packager_app.operations", True),
                ("app.background", "support_packager_app.background", True),
                ("app.launch", "support_packager_app.launch", True),
            ],
        )
        self._add_section(
            parent,
            "system",
            "support_packager.category.system",
            [
                ("system.os", "support_packager.field.os", True),
                ("system.machine", "support_packager.field.machine", True),
                ("system.python", "support_packager.field.python", True),
                ("system.memory", "support_packager.field.memory", True),
                ("system.boot", "support_packager.field.time", True),
                ("system.processes", "support_packager.field.processes", True),
                ("system.network", "support_packager.field.network", True),
                ("system.performance", "support_packager_fields.performance", True),
                (
                    "system.ui_performance",
                    "support_packager_fields.ui_performance",
                    True,
                ),
            ],
        )
        self._add_section(
            parent,
            "configuration",
            "support_packager_categories.configuration",
            [
                ("metadata.settings", "support_packager.field.settings", True),
                ("metadata.mods", "support_packager.field.mods", True),
                ("structure.files", "support_packager.field.structure", True),
            ],
        )
        g3m_files = [
            (
                f"g3m_file::{path.relative_to(self._service.root).as_posix()}",
                path.relative_to(self._service.root).as_posix(),
                False,
            )
            for path in self._service.shareable_g3m_files()
        ]
        self._add_section(
            parent,
            "g3m_files",
            "support_packager_categories.g3m_files",
            g3m_files,
        )
        patch_items = [
            (
                f"patch_manifest::{path.resolve()}::{entry}",
                self._service.redact_text(str(path)),
                False,
            )
            for path, entry in self._service.g3mpatch_manifests()
        ]
        self._add_section(
            parent,
            "patches",
            "support_packager_categories.patches",
            patch_items,
        )
        log_items = [
            (
                f"log:{path.relative_to(self._service.root).as_posix()}",
                path.relative_to(self._service.root).as_posix(),
                False,
            )
            for path in self._service.available_logs()
        ]
        self._add_section(parent, "logs", "support_packager.category.logs", log_items)
        game_items = [
            (
                f"game_structure::{self._service.archive_component(name)}",
                name,
                False,
            )
            for name, _root in self._service.game_roots()
        ]
        self._add_section(
            parent, "games", "support_packager_categories.games", game_items
        )
        appdata_items = [
            (
                f"appdata_structure::{self._service.archive_component(name)}",
                name,
                False,
            )
            for name, _root in self._service.special_appdata_roots()
        ]
        self._add_section(
            parent, "appdata", "support_packager_categories.appdata", appdata_items
        )
        for mod_id, name, root in self._service.installed_mods():
            options = [
                (
                    f"mod_structure::{mod_id}",
                    "support_packager_mod.structure",
                    True,
                ),
                (f"mod_files::{mod_id}", "support_packager_mod.files", True),
            ]
            if (root / "mod_config.json").is_file():
                options.insert(
                    0,
                    (f"mod_config::{mod_id}", "support_packager_mod.config", True),
                )
            self._add_section(
                parent,
                f"mod:{mod_id}",
                name,
                options,
                title_is_key=False,
            )

    def _add_section(
        self,
        parent: QWidget,
        section_id: str,
        title: str,
        options: list[tuple[str, str, bool]],
        *,
        title_is_key: bool = True,
    ) -> None:
        section = QWidget(parent)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 8, 0, 4)
        section_layout.setSpacing(6)
        header = QWidget(section)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        line_color = get_section_line_color(self._app_state.local_config)
        label = QLabel(header)
        label.setStyleSheet(QSS_BOLD_TRANSPARENT)
        header_layout.addWidget(label)
        arrow = QLabel("▶", header)
        arrow.setStyleSheet(QSS_ARROW_LABEL)
        header_layout.addWidget(arrow)
        line = QFrame(header)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {line_color};")
        self._section_lines.append(line)
        header_layout.addWidget(line, 1)
        self._section_titles[section_id] = (label, title, title_is_key)
        self._section_arrows[section_id] = arrow
        body = QWidget(section)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(22, 8, 22, 8)
        body_layout.setSpacing(8)
        if not options:
            empty = QLabel()
            empty.setProperty("support_empty", True)
            body_layout.addWidget(empty)
        for option_id, label, is_key in options:
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            self._items[option_id] = checkbox
            self._labels[option_id] = (label, is_key)
            body_layout.addWidget(checkbox)
        self._section_contents[section_id] = body
        header.mousePressEvent = lambda _event, key=section_id: self._toggle_section(
            key
        )
        section_layout.addWidget(header)
        section_layout.addWidget(body)
        self._sections_layout.addWidget(section)

    def _toggle_section(self, section_id: str) -> None:
        if not self._custom.isChecked():
            return
        content = self._section_contents[section_id]
        expand = content.isHidden()
        self._section_arrows[section_id].setText("▼" if expand else "▶")
        UIAnimator.collapse_expand(content, expand, 200, self._app_state)

    def _apply_custom_state(self) -> None:
        custom = self._custom.isChecked()
        for checkbox in self._items.values():
            checkbox.setEnabled(custom)
            if not custom:
                checkbox.setChecked(True)
        for section_id, content in self._section_contents.items():
            if not custom:
                content.setVisible(True)
            self._section_arrows[section_id].setText(
                "▼" if not content.isHidden() else "▶"
            )
        self._range.setEnabled(True)

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("support_packager.title"))
        self._title.setText(tr("support_packager.title"))
        self._description.setText(tr("support_packager.description"))
        self._custom.setText(tr("support_packager_options.custom_settings"))
        self._custom.setToolTip(tr("support_packager_options.custom_settings_tooltip"))
        for section_id, (label, value, is_key) in self._section_titles.items():
            if section_id.startswith("mod:"):
                label.setText(f"{tr('support_packager_categories.mod')}: {value}")
            else:
                label.setText(tr(value) if is_key else value)
        for option_id, checkbox in self._items.items():
            value, is_key = self._labels[option_id]
            checkbox.setText(tr(value) if is_key else value)
        for content in self._section_contents.values():
            for label in content.findChildren(QLabel):
                if label.property("support_empty"):
                    label.setText(tr("support_packager_options.empty"))
        self._range_label.setText(tr("support_packager.log_range"))
        for index, key in enumerate(("all", "day", "week", "month")):
            self._range.setItemText(index, tr(f"support_packager.range.{key}"))
        self._cancel.setText(tr("ui.cancel_button"))
        self._build.setText(tr("support_packager.build"))

    def refresh_theme(self) -> None:
        apply_dialog_theme(self, self._app_state)
        line_style = f"color: {get_section_line_color(self._app_state.local_config)};"
        for line in self._section_lines:
            line.setStyleSheet(line_style)

    def _record_ui_tick(self) -> None:
        now = time.perf_counter()
        self._ui_intervals.append(now - self._last_ui_tick)
        self._last_ui_tick = now
        if len(self._ui_intervals) > 240:
            del self._ui_intervals[:-240]

    def _runtime_metrics(self) -> dict[str, object]:
        values = [value for value in self._ui_intervals if value > 0]
        if not values:
            return {"available": False}
        return {
            "available": True,
            "sample_count": len(values),
            "timer_target_hz": 62.5,
            "observed_callback_hz": 1 / statistics.fmean(values),
            "median_interval_ms": statistics.median(values) * 1000,
            "maximum_interval_ms": max(values) * 1000,
            "note": "UI event-loop timer responsiveness; not rendered-frame FPS",
        }

    def _choose_destination(self) -> None:
        default = str(Path.home() / "G3M-Support.zip")
        destination, _ = QFileDialog.getSaveFileName(
            self, tr("support_packager.save_title"), default, "ZIP (*.zip)"
        )
        if not destination:
            return
        if not destination.lower().endswith(".zip"):
            destination += ".zip"
        selected = {
            key
            for key, item in self._items.items()
            if not key.startswith("log:") and item.isChecked() and item.isEnabled()
        }
        logs = {
            key.removeprefix("log:")
            for key, item in self._items.items()
            if key.startswith("log:") and item.isChecked() and item.isEnabled()
        }
        if not self._custom.isChecked():
            selected = {key for key in self._items if not key.startswith("log:")}
            logs = {
                key.removeprefix("log:")
                for key in self._items
                if key.startswith("log:")
            }
        self._set_busy(True)
        self._worker = SupportPackageWorker(
            self._service,
            destination,
            selected,
            logs,
            self._range.currentData(),
            self._runtime_metrics(),
        )
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _set_busy(self, busy: bool) -> None:
        self._build.setEnabled(not busy)
        self._custom.setEnabled(not busy)
        if not busy:
            self._apply_custom_state()
        else:
            for checkbox in self._items.values():
                checkbox.setEnabled(False)
            self._range.setEnabled(False)

    def _on_completed(self, path: str) -> None:
        QMessageBox.information(
            self,
            tr("support_packager.title"),
            tr("support_packager.completed", path=path),
        )

    def _on_failed(self, message: str) -> None:
        QMessageBox.critical(
            self,
            tr("support_packager.title"),
            tr("support_packager.failed", error=message),
        )

    def reject(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
        super().reject()
