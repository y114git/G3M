"""Dialog for managing library profiles: create, duplicate, rename, delete, reorder."""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services.localization_service import tr
from services.profile_service import DEFAULT_PROFILE
from ui.common.dialog_theme import apply_dialog_theme, get_dialog_theme_values
from ui.common.styling import build_button_style, clamp_border_radius, get_border_radius
from utils.path_utils import colored_icon

_ITEM_HEIGHT = 84


class ProfileManagerDialog(QDialog):
    def __init__(self, profile_service, app_state, parent=None) -> None:
        super().__init__(parent)
        self.profile_service = profile_service
        self.app_state = app_state
        self._selected_row = -1
        self._chk_icon = None
        self.setWindowTitle(tr("profiles.manager_title"))
        self.setMinimumSize(750, 600)
        self._init_ui()
        self._apply_theme()
        self._refresh_list()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        self._action_btns = []
        for attr, _icon_name, tip_key, slot in (
            ("add_btn", "add", "profiles.create", self._on_create),
            ("dup_btn", "duplicate", "profiles.duplicate", self._on_duplicate),
            ("edit_btn", "edit", "profiles.rename", self._on_rename),
            ("del_btn", "delete", "profiles.delete", self._on_delete),
        ):
            btn = QPushButton()
            btn.setObjectName(f"profile_{attr}")
            btn.setToolTip(tr(tip_key))
            btn.setFixedSize(38, 38)
            btn.setIconSize(QSize(20, 20))
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
            setattr(self, attr, btn)
            self._action_btns.append(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

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

    def _refresh_list(self):
        self.list_widget.clear()
        self._selected_row = -1
        active = self.profile_service.active_name
        for name in self.profile_service.list_profiles():
            summary = self.profile_service.get_profile_summary(name)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setSizeHint(QSize(0, _ITEM_HEIGHT))
            widget = self._build_item_widget(summary, is_active=(name == active))
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        self._on_selection_changed()

    def _build_item_widget(self, summary: dict, is_active: bool = False) -> QWidget:
        widget = QWidget(self.list_widget.viewport())
        widget.setObjectName("profileItemWidget")
        h_layout = QHBoxLayout(widget)
        h_layout.setContentsMargins(10, 8, 10, 8)
        h_layout.setSpacing(8)

        info = QWidget(widget)
        v_layout = QVBoxLayout(info)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(3)
        name_label = QLabel(f"<b>{summary['name']}</b>", info)
        name_label.setObjectName("profileNameLabel")
        v_layout.addWidget(name_label)
        game_name = summary.get("game_display_name", summary["game"].upper())
        parts = [
            f"{game_name} ({summary['game_mod_count']})",
            tr("profiles.total_active", count=summary["total_mod_count"]),
        ]
        if summary["chapter_mode"]:
            cm = tr("ui.chapter_mode")
            if summary["direct_launch"]:
                cm += f" ({summary['direct_launch']})"
            parts.append(cm)
        detail_label = QLabel(" — ".join(parts), info)
        detail_label.setObjectName("profileDetailLabel")
        v_layout.addWidget(detail_label)
        h_layout.addWidget(info, 1)

        checkmark = QPushButton(widget)
        checkmark.setObjectName("profileCheckmark")
        checkmark.setFixedSize(36, 36)
        checkmark.setIconSize(QSize(22, 22))
        checkmark.setEnabled(False)
        checkmark.setVisible(is_active)
        if self._chk_icon:
            checkmark.setIcon(self._chk_icon)
        h_layout.addWidget(checkmark)

        use_btn = QPushButton(tr("ui.use_button"), widget)
        use_btn.setObjectName("profileUseBtn")
        use_btn.setVisible(False)
        use_btn.clicked.connect(lambda _=False, n=summary["name"]: self._on_use(n))
        h_layout.addWidget(use_btn)

        widget.setProperty("checkmark", checkmark)
        widget.setProperty("use_btn", use_btn)
        widget.setProperty("is_active", is_active)
        return widget

    def _selected_name(self) -> str:
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def _on_selection_changed(self, _index=None):
        name = self._selected_name()
        is_default = name == DEFAULT_PROFILE
        self.edit_btn.setVisible(bool(name) and not is_default)
        self.del_btn.setVisible(bool(name) and not is_default)
        prev = self._selected_row
        cur = self.list_widget.currentRow()
        self._selected_row = cur
        if prev >= 0 and prev != cur:
            self._set_item_selected_state(prev, False)
        if cur >= 0:
            self._set_item_selected_state(cur, True)

    def _set_item_selected_state(self, row: int, selected: bool):
        item = self.list_widget.item(row)
        if not item:
            return
        widget = self.list_widget.itemWidget(item)
        if not widget:
            return
        is_active = bool(widget.property("is_active"))
        if use_btn := widget.property("use_btn"):
            use_btn.setVisible(selected and not is_active)
        if checkmark := widget.property("checkmark"):
            checkmark.setVisible(is_active)

    def _on_use(self, name: str):
        if name == self.profile_service.active_name:
            return
        self.profile_service.switch(name)
        self._refresh_list()

    def _prompt_and_execute(
        self, action: callable, title_key: str, default_text: str = ""
    ):
        name, ok = QInputDialog.getText(
            self, tr(title_key), tr("profiles.enter_name"), text=default_text
        )
        if ok and name.strip() and name.strip() != default_text:
            if action(name.strip()):
                self._refresh_list()
            else:
                QMessageBox.warning(
                    self, tr("profiles.manager_title"), tr("profiles.already_exists")
                )

    def _on_create(self):
        self._prompt_and_execute(self.profile_service.create, "profiles.create")

    def _on_duplicate(self):
        if source := self._selected_name():
            self._prompt_and_execute(
                lambda n: self.profile_service.duplicate(source, n),
                "profiles.duplicate",
                f"{source} Copy",
            )

    def _on_rename(self):
        old_name = self._selected_name()
        if old_name and old_name != DEFAULT_PROFILE:
            self._prompt_and_execute(
                lambda n: self.profile_service.rename(old_name, n),
                "profiles.rename",
                old_name,
            )

    def _on_delete(self):
        name = self._selected_name()
        if not name or name == DEFAULT_PROFILE:
            return
        reply = QMessageBox.question(
            self,
            tr("profiles.manager_title"),
            tr("profiles.confirm_delete_text", name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not self.profile_service.delete(name):
            return
        self._refresh_list()

    def _on_rows_moved(self):
        names = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item:
                names.append(item.data(Qt.ItemDataRole.UserRole))
        self.profile_service.reorder(names)

    def _apply_theme(self):
        apply_dialog_theme(self, self.app_state)
        theme = get_dialog_theme_values(self.app_state)
        icon_color = theme["text"]
        br = clamp_border_radius(
            get_border_radius(self.app_state.local_config),
            width=38,
            height=38,
            border_width=2,
        )
        sq_btn_qss = f"""
            QPushButton {{
                border: 2px solid {theme["border"]};
                border-radius: {br}px;
                background-color: {theme["button"]};
                padding: 0px;
                min-width: 38px; max-width: 38px;
                min-height: 38px; max-height: 38px;
            }}
            QPushButton:hover {{
                background-color: {theme["button_hover"]};
            }}
        """
        for attr, icon_name in (
            ("add_btn", "add"),
            ("dup_btn", "duplicate"),
            ("edit_btn", "edit"),
            ("del_btn", "delete"),
        ):
            btn = getattr(self, attr)
            btn.setIcon(colored_icon(icon_name, icon_color))
            btn.setStyleSheet(sq_btn_qss)
        use_qss = build_button_style(
            "profileUseBtn",
            "#4CAF50",
            "#5cb85c",
            "#e8e9eb",
            theme["border"],
            width=90,
            height=32,
            font_size=13,
            border_radius=br,
        )
        chk_qss = "QPushButton#profileCheckmark { background: transparent; border: none; padding: 0px; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; }"
        self.setStyleSheet(
            self.styleSheet()
            + f"""
            QLabel#profileDetailLabel {{ color: {theme["secondary_text"]}; font-size: 11px; }}
            {use_qss}
            {chk_qss}
        """
        )
        self._chk_icon = colored_icon("checkmark", icon_color)
