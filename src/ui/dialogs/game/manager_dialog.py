"""Dialog for managing built-in and custom games."""

import logging

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services.game_registry_service import GameRegistryValidationError
from services.localization_service import tr
from ui.common.dialog_theme import apply_dialog_theme, get_dialog_theme_values
from ui.common.styling import clamp_border_radius, get_border_radius
from ui.dialogs.custom_game_dialog import CustomGameDialog
from utils.path_utils import colored_icon

logger = logging.getLogger(__name__)

_ITEM_HEIGHT = 88


class GameManagerDialog(QDialog):
    """Manage visibility, order, and custom games."""

    def __init__(
        self,
        registry_service,
        profile_service,
        game_versions_manager,
        settings_service,
        app_state,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.registry_service = registry_service
        self.profile_service = profile_service
        self.game_versions_manager = game_versions_manager
        self.settings_service = settings_service
        self.app_state = app_state
        self.setWindowTitle(tr("games.manager_title"))
        self.setMinimumSize(760, 620)
        self._selected_row = -1
        self._build_ui()
        self._apply_theme()
        self._refresh_list()
        self.registry_service.games_changed.connect(self._refresh_list)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self._action_btns = []
        for attr, icon_name, tip_key, slot in (
            ("add_btn", "add", "games.add_custom_title", self._on_add),
            ("edit_btn", "edit", "games.edit_custom_title", self._on_edit),
            ("del_btn", "delete", "games.delete_title", self._on_delete),
        ):
            btn = QPushButton()
            btn.setObjectName("gameManagerActionButton")
            btn.setFixedSize(38, 38)
            btn.setIconSize(QSize(20, 20))
            btn.setToolTip(tr(tip_key))
            btn.clicked.connect(slot)
            buttons.addWidget(btn)
            setattr(self, attr, btn)
            self._action_btns.append((btn, icon_name))
        buttons.addStretch()
        layout.addLayout(buttons)
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)
        self.list_widget.currentRowChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget, 1)
        close_btn = QPushButton(tr("ui.close_button"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)

    def _refresh_list(self) -> None:
        current_id = self._selected_game_id()
        self.list_widget.clear()
        for entry in self.registry_service.list_manager_games():
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setSizeHint(QSize(0, _ITEM_HEIGHT))
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, self._build_item_widget(entry))
        if self.list_widget.count():
            target_row = next(
                (
                    row
                    for row in range(self.list_widget.count())
                    if self.list_widget.item(row).data(Qt.ItemDataRole.UserRole)
                    == current_id
                ),
                0,
            )
            self.list_widget.setCurrentRow(target_row)
        self._on_selection_changed()

    def _build_item_widget(self, entry) -> QWidget:
        widget = QWidget(self.list_widget.viewport())
        row = QHBoxLayout(widget)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)
        info = QWidget(widget)
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(3)
        title = QLabel(f"<b>{entry.display_name}</b>")
        info_layout.addWidget(title)
        parts = [
            tr("games.builtin_badge") if entry.is_builtin else tr("games.custom_badge")
        ]
        if not entry.is_visible:
            parts.append(tr("games.hidden_badge"))
        if entry.steam_app_id:
            parts.append(f"Steam {entry.steam_app_id}")
        if entry.gamebanana_id:
            parts.append(f"GameBanana {entry.gamebanana_id}")
        detail = QLabel(" · ".join(parts))
        detail.setObjectName("gameManagerDetailLabel")
        info_layout.addWidget(detail)
        row.addWidget(info, 1)
        toggle = QCheckBox(tr("games.visible_label"))
        toggle.setChecked(entry.is_visible)
        toggle.stateChanged.connect(
            lambda state, game_id=entry.id: self._on_toggle_visibility(
                game_id, bool(state)
            )
        )
        row.addWidget(toggle)
        return widget

    def _selected_game_id(self) -> str:
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def _selected_entry(self):
        game_id = self._selected_game_id()
        return next(
            (
                entry
                for entry in self.registry_service.list_manager_games()
                if entry.id == game_id
            ),
            None,
        )

    def _on_selection_changed(self, _index=None) -> None:
        entry = self._selected_entry()
        is_custom = bool(entry and not entry.is_builtin)
        self.edit_btn.setEnabled(is_custom)
        self.del_btn.setEnabled(is_custom)

    def _on_rows_moved(self) -> None:
        ordered = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item:
                ordered.append(item.data(Qt.ItemDataRole.UserRole))
        self.registry_service.reorder(ordered)

    def _safe_warning(self, title: str, message: str) -> None:
        try:
            QMessageBox.warning(self, title, message)
        except Exception:
            logger.exception("game_manager: failed to show warning dialog")

    def _on_toggle_visibility(self, game_id: str, visible: bool) -> None:
        try:
            self.registry_service.set_visibility(game_id, visible)
        except GameRegistryValidationError as error:
            self._safe_warning(tr("games.manager_title"), tr(error.key))
            self._refresh_list()

    def _on_add(self) -> None:
        dialog = CustomGameDialog(self.app_state, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_dialog_values(dialog)

    def _on_edit(self) -> None:
        entry = self._selected_entry()
        if not entry or entry.is_builtin:
            return
        dialog = CustomGameDialog(
            self.app_state, self.registry_service.get_custom_game(entry.id), self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_dialog_values(dialog, entry.id)

    def _save_dialog_values(
        self, dialog: CustomGameDialog, game_id: str | None = None
    ) -> None:
        values = dialog.values()
        try:
            if game_id:
                self.registry_service.update_custom_game(game_id, **values)
            else:
                self.registry_service.create_custom_game(**values)
        except GameRegistryValidationError as error:
            self._safe_warning(tr("games.manager_title"), tr(error.key))
            self._save_dialog_values_retry(dialog, game_id)

    def _save_dialog_values_retry(
        self, dialog: CustomGameDialog, game_id: str | None = None
    ) -> None:
        retry = CustomGameDialog(self.app_state, dialog.record, self)
        retry.display_name_edit.setText(dialog.display_name_edit.text())
        retry.primary_executable_edit.setText(dialog.primary_executable_edit.text())
        retry.data_file_name_edit.setText(dialog.data_file_name_edit.text())
        retry.steam_app_id_edit.setText(dialog.steam_app_id_edit.text())
        retry.gamebanana_id_edit.setText(dialog.gamebanana_id_edit.text())
        if retry.exec() == QDialog.DialogCode.Accepted:
            self._save_dialog_values(retry, game_id)

    def _on_delete(self) -> None:
        entry = self._selected_entry()
        if not entry or entry.is_builtin:
            return
        msg = QMessageBox(self)
        msg.setWindowTitle(tr("games.delete_title"))
        msg.setText(tr("games.delete_confirm_text", name=entry.display_name))
        soft_btn = msg.addButton(
            tr("games.delete_registry_only"), QMessageBox.ButtonRole.AcceptRole
        )
        cleanup_btn = msg.addButton(
            tr("games.delete_with_cleanup"), QMessageBox.ButtonRole.DestructiveRole
        )
        msg.addButton(QMessageBox.StandardButton.Cancel)
        for button in msg.buttons():
            button.setMinimumWidth(button.sizeHint().width() + 18)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked not in (soft_btn, cleanup_btn):
            return
        if clicked == cleanup_btn:
            other_visible = [
                game.id
                for game in self.registry_service.list_visible_games()
                if game.id != entry.id
            ]
            if not other_visible:
                return
            fallback = other_visible[0]
            self.profile_service.cleanup_game_references(
                entry.id, fallback, remove_used_mods=True
            )
            self.game_versions_manager.cleanup_game(entry.id)
            self.profile_service.write_local_config()
        self.registry_service.delete_custom_game(entry.id)

    def _apply_theme(self) -> None:
        apply_dialog_theme(self, self.app_state)
        theme = get_dialog_theme_values(self.app_state)
        br = clamp_border_radius(
            get_border_radius(self.app_state.local_config),
            width=38,
            height=38,
            border_width=2,
        )
        btn_qss = f"""
            QPushButton#gameManagerActionButton {{
                border: 2px solid {theme["border"]};
                border-radius: {br}px;
                background-color: {theme["elements"]};
                min-width: 38px;
                max-width: 38px;
                min-height: 38px;
                max-height: 38px;
                padding: 0px;
            }}
            QPushButton#gameManagerActionButton:hover:enabled {{ background-color: {theme["hover"]}; }}
            QPushButton#gameManagerActionButton:disabled {{
                background-color: {theme["background"]};
                border-color: #6f6f6f;
            }}
            QLabel#gameManagerDetailLabel {{ color: {theme["secondary_text"]}; font-size: 11px; }}
        """
        self.setStyleSheet(self.styleSheet() + btn_qss)
        for btn, icon_name in self._action_btns:
            btn.setIcon(colored_icon(icon_name, theme["main_text"]))
