"""Dialog for arranging mod priority and sequential patching steps."""

from __future__ import annotations

from typing import Any, override

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDropEvent, QFocusEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from services.localization_service import tr
from ui.common.dialog_theme import apply_dialog_theme, get_dialog_theme_values


class _StepListWidget(QListWidget):
    def __init__(self, owner: ModPriorityStepsDialog, step_index: int) -> None:
        super().__init__()
        self.owner = owner
        self.step_index = step_index
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    @override
    def focusInEvent(self, event: QFocusEvent | None) -> None:
        self.owner._set_active_step(self.step_index)
        super().focusInEvent(event)

    @override
    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        self.owner._set_active_step(self.step_index)
        super().mousePressEvent(event)

    def dropEvent(self, event: QDropEvent | None) -> None:
        if event is None:
            return
        source = event.source()
        if isinstance(source, _StepListWidget) and source is not self:
            item = source.currentItem()
            mod = item.data(Qt.ItemDataRole.UserRole) if item else None
            if mod is not None:
                row = self.indexAt(event.position().toPoint()).row()
                self.owner._move_mod_to_step(
                    mod, self.step_index, None if row < 0 else row
                )
                event.acceptProposedAction()
                return
        super().dropEvent(event)


class _StepGroupBox(QGroupBox):
    def __init__(self, owner: ModPriorityStepsDialog, step_index: int) -> None:
        super().__init__(tr("ui.step_number", number=step_index + 1))
        self.owner = owner
        self.step_index = step_index

    @override
    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        self.owner._set_active_step(self.step_index)
        super().mousePressEvent(event)


class ModPriorityStepsDialog(QDialog):
    def __init__(
        self,
        mod_steps: list[list[Any]],
        app_state,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self._steps = [list(step) for step in mod_steps if step] or [[]]
        self._step_lists: list[_StepListWidget] = []
        self._step_groups: list[_StepGroupBox] = []
        self._active_step_index = 0
        self.result_steps: list[list[Any]] | None = None
        self.setWindowTitle(tr("ui.priority_steps_title"))
        self.setMinimumSize(550, 560)
        self._setup_ui()
        self.apply_theme()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)
        self.instructions_label = QLabel()
        self.instructions_label.setWordWrap(True)
        self.instructions_label.setObjectName("instructionsLabel")
        layout.addWidget(self.instructions_label)

        self.steps_scroll = QScrollArea()
        self.steps_scroll.setWidgetResizable(True)
        self.steps_container = QWidget()
        self.steps_layout = QVBoxLayout(self.steps_container)
        self.steps_layout.setContentsMargins(0, 0, 0, 0)
        self.steps_scroll.setWidget(self.steps_container)
        layout.addWidget(self.steps_scroll)

        step_buttons = QHBoxLayout()
        self._localized_buttons: dict[str, QPushButton] = {}
        for text_key, callback in (
            ("ui.add_step", self._add_step),
            ("ui.remove_step", self._remove_selected_step),
            ("ui.move_step_up", lambda: self._move_step(-1)),
            ("ui.move_step_down", lambda: self._move_step(1)),
        ):
            button = QPushButton()
            button.clicked.connect(callback)
            step_buttons.addWidget(button)
            self._localized_buttons[text_key] = button
        layout.addLayout(step_buttons)

        buttons = QHBoxLayout()
        up = QPushButton()
        up.clicked.connect(lambda: self._move_selected_mod(-1))
        buttons.addWidget(up)
        self._localized_buttons["ui.move_up"] = up
        down = QPushButton()
        down.clicked.connect(lambda: self._move_selected_mod(1))
        buttons.addWidget(down)
        self._localized_buttons["ui.move_down"] = down
        buttons.addStretch()
        cancel = QPushButton()
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self._localized_buttons["ui.cancel_button"] = cancel
        ok = QPushButton()
        ok.clicked.connect(self._accept_dialog)
        ok.setDefault(True)
        buttons.addWidget(ok)
        self._localized_buttons["ui.ok"] = ok
        layout.addLayout(buttons)
        self._rebuild_steps()
        self.relocalize_ui()

    def _capture_steps(self) -> list[list[Any]]:
        if not self._step_lists:
            return [list(step) for step in self._steps]
        return [
            [
                item.data(Qt.ItemDataRole.UserRole)
                for row in range(widget.count())
                if (item := widget.item(row)) is not None
            ]
            for widget in self._step_lists
        ]

    def _rebuild_steps(self) -> None:
        while self.steps_layout.count():
            item = self.steps_layout.takeAt(0)
            if item is not None and (widget := item.widget()):
                widget.deleteLater()
        self._step_lists = []
        self._step_groups = []
        for index, step in enumerate(self._steps):
            group = _StepGroupBox(self, index)
            group.setProperty("step_index", index)
            group_layout = QVBoxLayout(group)
            widget = _StepListWidget(self, index)
            widget.clicked.connect(
                lambda _index, step_index=index: self._set_active_step(step_index)
            )
            widget.currentItemChanged.connect(
                lambda current, _previous, step_index=index: (
                    self._on_current_item_changed(step_index, current)
                )
            )
            for mod in step:
                item = QListWidgetItem(getattr(mod, "name", None) or str(mod))
                item.setData(Qt.ItemDataRole.UserRole, mod)
                widget.addItem(item)
            group_layout.addWidget(widget)
            self.steps_layout.addWidget(group)
            self._step_groups.append(group)
            self._step_lists.append(widget)
        self.steps_layout.addStretch()
        self._refresh_active_step_style()

    def _add_step(self) -> None:
        self._steps = self._capture_steps()
        self._steps.append([])
        self._active_step_index = len(self._steps) - 1
        self._rebuild_steps()

    def _remove_selected_step(self) -> None:
        self._steps = self._capture_steps()
        if len(self._steps) <= 1:
            return
        selected = min(self._active_step_index, len(self._steps) - 1)
        removed = self._steps.pop(selected)
        target = selected - 1 if selected > 0 else 0
        self._steps[target].extend(removed)
        self._active_step_index = target
        self._rebuild_steps()

    def _move_step(self, offset: int) -> None:
        self._steps = self._capture_steps()
        selected = min(self._active_step_index, len(self._steps) - 1)
        target = selected + offset
        if 0 <= target < len(self._steps):
            self._steps[selected], self._steps[target] = (
                self._steps[target],
                self._steps[selected],
            )
            self._active_step_index = target
            self._rebuild_steps()

    def _set_active_step(self, index: int) -> None:
        if 0 <= index < len(self._step_lists):
            self._active_step_index = index
            self._refresh_active_step_style()

    def _on_current_item_changed(
        self, step_index: int, current: QListWidgetItem | None
    ) -> None:
        if current is None:
            return
        self._set_active_step(step_index)
        for index, widget in enumerate(self._step_lists):
            if index != step_index:
                widget.clearSelection()
                widget.setCurrentItem(None)

    def _refresh_active_step_style(self) -> None:
        for index, group in enumerate(self._step_groups):
            group.setProperty("activeStep", index == self._active_step_index)
            group.style().unpolish(group)
            group.style().polish(group)
            group.update()

    def _move_selected_mod(self, offset: int) -> None:
        if not self._step_lists:
            return
        widget = self._step_lists[
            min(self._active_step_index, len(self._step_lists) - 1)
        ]
        row = widget.currentRow()
        target = row + offset
        if row >= 0 and 0 <= target < widget.count():
            item = widget.takeItem(row)
            widget.insertItem(target, item)
            widget.setCurrentRow(target)

    def _move_mod_to_step(
        self, mod: Any, target_step: int, target_row: int | None = None
    ) -> None:
        steps = self._capture_steps()
        for step in steps:
            step[:] = [candidate for candidate in step if candidate is not mod]
        while target_step >= len(steps):
            steps.append([])
        row = len(steps[target_step]) if target_row is None else target_row
        steps[target_step].insert(max(0, min(row, len(steps[target_step]))), mod)
        self._steps = steps
        self._active_step_index = target_step
        self._rebuild_steps()

    def _normalized_steps(self) -> list[list[Any]]:
        result = []
        seen: set[int] = set()
        for step in self._capture_steps():
            normalized = []
            for mod in step:
                identity = id(mod)
                if identity in seen:
                    continue
                seen.add(identity)
                normalized.append(mod)
            if normalized:
                result.append(normalized)
        return result

    def _accept_dialog(self) -> None:
        self.result_steps = self._normalized_steps()
        self.accept()

    def get_result(self) -> list[list[Any]]:
        return (
            self.result_steps
            if self.result_steps is not None
            else self._normalized_steps()
        )

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("ui.priority_steps_title"))
        self.info_label.setText(tr("ui.priority_steps_info"))
        self.instructions_label.setText(tr("ui.priority_steps_instructions"))
        for key, button in self._localized_buttons.items():
            button.setText(tr(key))
        for index, group in enumerate(self._step_groups):
            group.setTitle(tr("ui.step_number", number=index + 1))

    def apply_theme(self) -> None:
        apply_dialog_theme(self, self.app_state)
        theme = get_dialog_theme_values(self.app_state)
        self.setStyleSheet(
            self.styleSheet()
            + f'\nQGroupBox[activeStep="true"] {{ border: 2px dashed {theme["select"]}; }}'
        )
        self.instructions_label.setStyleSheet(
            f"color: {theme['secondary_text']}; font-size: 11px;"
        )

    def _apply_theme(self) -> None:
        self.apply_theme()
