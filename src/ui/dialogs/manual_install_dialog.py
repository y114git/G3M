import logging
import os
import shutil
from typing import override

from PyQt6.QtCore import QSize, Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config.config import (
    DATA_FILE_EXTENSIONS,
    MOD_CONFIG_FILENAME,
    MOD_ROOT_DOC_EXTENSIONS,
)
from models.game_modes import get_all_game_entries, get_game
from services.localization_service import tr
from ui.common.dialog_theme import get_dialog_theme_values
from ui.common.styling import clamp_border_radius, get_ui_scale_factor
from utils.file_utils import (
    get_chapter_folder_name,
    get_unique_mod_dir,
    save_json,
)
from utils.mod_config_parser import build_mod_config_data
from utils.path_utils import colored_icon, find_chapter_resource_dir


class ManualModInstallDialog(QDialog):
    _OPENABLE_DOC_EXTENSIONS = {
        ".cfg",
        ".ini",
        ".json",
        ".log",
        ".markdown",
        ".md",
        ".rtf",
        ".txt",
        ".yaml",
        ".yml",
    }

    def __init__(
        self,
        parent,
        prepared_files_path: str,
        gamebanana_metadata: dict | None = None,
        source_file_path: str | None = None,
        initial_game_type: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.prepared_files_path = prepared_files_path
        self.gamebanana_metadata = gamebanana_metadata or {}
        self.source_file_path = source_file_path
        self.app_state = None
        self.mod_service = None
        p = parent
        while p:
            if hasattr(p, "app_state") and hasattr(p, "mod_service"):
                self.app_state = p.app_state
                self.mod_service = p.mod_service
                break
            p = p.parent() if hasattr(p, "parent") and callable(p.parent) else None
        if self.app_state is None:
            self.app_state = self._resolve_app_state(parent)
        self.temp_dir_to_cleanup = None
        self.initial_game_type = initial_game_type
        self.data_file_selections = {}
        self.extra_files_mappings = {}
        self.extra_files_chapters = {}
        self.all_files = []
        self.extra_file_widgets = {}
        self.unused_files = set()
        self.xdelta_patches_mappings = {}
        self.xdelta_patch_widgets = {}
        self.setWindowTitle(tr("dialogs.manual_install_title"))
        self.setModal(True)
        self.resize(900, 700)
        self.setMinimumSize(800, 600)
        self._scan_files()
        self.init_ui()

    @override
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._center_on_screen()

    def _center_on_screen(self):
        screen = self.screen() or self.windowHandle().screen() if self.windowHandle() else None
        if screen is None and self.parentWidget():
            screen = self.parentWidget().screen()
        if screen is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

    def _icon(self, icon_name: str):
        icon_key = {
            "folder_icon.svg": "folder",
            "delete_icon.svg": "delete",
            "cross_icon.svg": "cross",
            "add_icon.svg": "add",
        }.get(icon_name, "folder")
        return colored_icon(icon_key, self._theme_value("main_text", "#e8e9eb"))

    def _mix_color(self, color_value: str, factor=0.18):
        color = QColor(color_value)
        if not color.isValid():
            return color_value
        base = QColor(0, 0, 0)
        mixed = QColor(
            round(color.red() * (1 - factor) + base.red() * factor),
            round(color.green() * (1 - factor) + base.green() * factor),
            round(color.blue() * (1 - factor) + base.blue() * factor),
            235,
        )
        return mixed.name(QColor.NameFormat.HexArgb)

    def _theme_value(self, key: str, fallback: str) -> str:
        app_state = self.app_state
        theme = get_dialog_theme_values(app_state) if app_state else {}
        return theme.get(key, fallback)

    @staticmethod
    def _resolve_app_state(start_obj) -> object | None:
        current = start_obj
        visited = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            app_state = getattr(current, "app_state", None)
            if app_state is not None and getattr(app_state, "local_config", None) is not None:
                return app_state
            parent_getter = getattr(current, "parent", None)
            if callable(parent_getter):
                current = parent_getter()
            else:
                current = None
        return None

    def _ui_scale(self) -> float:
        config = getattr(self.app_state, "local_config", None)
        return get_ui_scale_factor(config, default=1.0) if config else 1.0

    def _icon_size(self, base: int) -> QSize:
        size = max(14, round(base * self._ui_scale()))
        return QSize(size, size)

    def closeEvent(self, event):
        if self.temp_dir_to_cleanup and os.path.exists(self.temp_dir_to_cleanup):
            try:
                shutil.rmtree(self.temp_dir_to_cleanup, ignore_errors=True)
            except Exception as e:
                logging.warning(f"Failed to cleanup temp directory: {e}")
        super().closeEvent(event)

    def _scan_files(self):
        self.all_files = []
        if not os.path.exists(self.prepared_files_path):
            return
        for root, _dirs, files in os.walk(self.prepared_files_path):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, self.prepared_files_path)
                self.all_files.append((file_path, rel_path))

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)

        game_layout = QHBoxLayout()
        game_layout.addStretch()
        game_layout.addWidget(QLabel(tr("ui.mod_type_label")))
        self.game_combo = QComboBox()
        self.game_combo.setMinimumWidth(240)
        self.game_combo.setToolTip(tr("tooltips.manual_install_game"))
        for entry in get_all_game_entries():
            self.game_combo.addItem(entry.display_name, entry.id)
        game_value = self.initial_game_type
        if not game_value and self.app_state and hasattr(self.app_state, "game_mode"):
            from services.game_detection_service import get_game_type_string

            game_value = get_game_type_string(self.app_state.game_mode)
        if game_value:
            for i in range(self.game_combo.count()):
                if self.game_combo.itemData(i) == game_value:
                    self.game_combo.setCurrentIndex(i)
                    break
        self.game_combo.currentIndexChanged.connect(self._update_file_tabs)
        game_layout.addWidget(self.game_combo)
        game_layout.addStretch()
        main_layout.addLayout(game_layout)
        main_layout.addWidget(self._build_summary_card())
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("QTabWidget::tab-bar { alignment: center; }")
        self._create_data_tab()
        self._create_extra_files_tab()
        main_layout.addWidget(self.tab_widget)
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText(
            tr("dialogs.finish_creating_mod")
        )
        button_box.accepted.connect(self._on_finish)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)
        self._apply_theme_styles()

    def _build_section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size: 15px; font-weight: 700;")
        return label

    def _build_summary_card(self) -> QWidget:
        frame = QWidget()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)
        self.files_summary_label = QLabel()
        self.files_summary_label.setWordWrap(True)
        self.files_summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.files_summary_label.setToolTip(tr("tooltips.manual_install_summary"))
        layout.addWidget(self.files_summary_label)
        self._refresh_summary_text()
        return frame

    def _refresh_summary_text(self):
        total = len(self.all_files)
        docs = sum(1 for fp, _ in self.all_files if self._is_openable_doc(fp))
        possible_data = sum(
            1
            for fp, _ in self.all_files
            if os.path.splitext(fp)[1].lower() in DATA_FILE_EXTENSIONS
        )
        assigned_data_paths = set(self.data_file_selections.values())
        for patch_map in self.xdelta_patches_mappings.values():
            assigned_data_paths.update(patch_map.keys())
            assigned_data_paths.update(patch_map.values())
        data_count = max(0, possible_data - len(assigned_data_paths))
        text = tr(
            "ui.manual_install_summary",
            total=total,
            docs=docs,
            data=data_count,
        )
        if hasattr(self, "files_summary_label"):
            self.files_summary_label.setText(text)

    def _create_data_tab(self):
        data_widget = QWidget()
        data_layout = QVBoxLayout(data_widget)
        data_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        info_label = QLabel(tr("dialogs.data_tab_info"))
        info_label.setWordWrap(True)
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label.setProperty("hintText", True)
        info_label.setToolTip(tr("tooltips.manual_install_data_tab"))
        data_layout.addWidget(info_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        self.data_tabs = QTabWidget()
        self.data_tabs.setStyleSheet("QTabWidget::tab-bar { alignment: center; }")
        scroll_layout.addWidget(self.data_tabs)
        scroll.setWidget(scroll_content)
        data_layout.addWidget(scroll)
        self.tab_widget.addTab(data_widget, tr("dialogs.data_tab"))
        self._update_file_tabs()

    def _create_extra_files_tab(self):
        extra_widget = QWidget()
        extra_layout = QVBoxLayout(extra_widget)
        extra_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.extra_instructions_label = QLabel(self._extra_files_instructions_text())
        self.extra_instructions_label.setWordWrap(True)
        self.extra_instructions_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.extra_instructions_label.setProperty("hintText", True)
        self.extra_instructions_label.setToolTip(tr("tooltips.manual_install_extra_tab"))
        self.extra_instructions_label.setStyleSheet("font-size: 11px; padding: 10px;")
        extra_layout.addWidget(self.extra_instructions_label)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setMaximumHeight(400)
        scroll_area.setMinimumHeight(200)
        scroll_content = QWidget()
        self.extra_files_list_layout = QVBoxLayout(scroll_content)
        self.extra_files_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.extra_files_list_layout.setSpacing(10)
        scroll_area.setWidget(scroll_content)
        extra_layout.addWidget(scroll_area, 1)
        self.tab_widget.addTab(extra_widget, tr("dialogs.extra_files_tab"))
        self._populate_extra_files_list()

    def _update_file_tabs(self):
        self.data_tabs.clear()
        self.data_file_edits = {}
        game = self.game_combo.currentData()
        game_def = get_game(game)
        if game_def and game_def.is_multi_tab:
            for tab in game_def.tabs:
                name = tr(tab.name_key)
                widget = self._create_chapter_data_widget(tab.tab_id, display_name=name)
                self.data_tabs.addTab(widget, name)
        else:
            game_display = self.game_combo.currentText()
            single_widget = self._create_chapter_data_widget(
                game, display_name=game_display
            )
            self.data_tabs.addTab(single_widget, tr("dialogs.data_file"))
        self._update_extra_files_instructions()
        self._populate_extra_files_list()

    def _chapter_entries(self) -> list[tuple[str, str]]:
        game = self.game_combo.currentData()
        game_def = get_game(game)
        if game_def and game_def.is_multi_tab:
            return [(tab.tab_id, tr(tab.name_key)) for tab in game_def.tabs]
        return [(game, self.game_combo.currentText())]

    def _extra_files_instructions_text(self) -> str:
        if self.game_combo.currentData() == "deltarune":
            return tr("dialogs.extra_files_path_instructions_deltarune")
        return tr("dialogs.extra_files_path_instructions")

    def _update_extra_files_instructions(self) -> None:
        label = getattr(self, "extra_instructions_label", None)
        if label is not None:
            label.setText(self._extra_files_instructions_text())

    def _create_chapter_data_widget(
        self, chapter_id: str, display_name: str = ""
    ) -> QWidget:
        widget = QWidget()
        widget._chapter_id = chapter_id
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        label = display_name or self._chapter_display_name(chapter_id)
        info_text = tr("dialogs.select_data_file_info", chapter=label)
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label.setProperty("hintText", True)
        layout.addWidget(info_label)
        file_path_layout = QHBoxLayout()
        self.data_file_edits = getattr(self, "data_file_edits", {})
        file_edit = QLineEdit()
        file_edit.setReadOnly(True)
        file_edit.setPlaceholderText(tr("dialogs.no_file_selected"))
        file_edit.setToolTip(tr("tooltips.manual_install_data_file"))
        if chapter_id in self.data_file_selections:
            file_edit.setText(self.data_file_selections[chapter_id])
        self.data_file_edits[chapter_id] = file_edit
        file_path_layout.addWidget(file_edit)
        browse_btn = self._make_tool_button(
            "folder_icon.svg", tr("ui.browse_button"), tr("ui.browse_button")
        )
        browse_btn.clicked.connect(
            lambda checked, cid=chapter_id: self._browse_data_file(cid)
        )
        file_path_layout.addWidget(browse_btn)
        clear_btn = self._make_tool_button(
            "cross_icon.svg", tr("ui.clear_button"), ""
        )
        clear_btn.setToolTip(tr("tooltips.clear_selection"))
        clear_btn.clicked.connect(
            lambda checked, cid=chapter_id: self._clear_data_file(cid)
        )
        file_path_layout.addWidget(clear_btn)
        layout.addLayout(file_path_layout)
        add_xdelta_btn = QPushButton(tr("dialogs.add_additional_xdelta"))
        add_xdelta_btn.setIcon(self._icon("add_icon.svg"))
        add_xdelta_btn.setToolTip(tr("tooltips.manual_install_add_xdelta"))
        add_xdelta_btn.clicked.connect(
            lambda checked, cid=chapter_id: self._add_xdelta_patch(cid)
        )
        layout.addWidget(add_xdelta_btn, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(10)
        xdelta_patches_section = self._create_xdelta_patches_section(chapter_id)
        if xdelta_patches_section:
            layout.addWidget(xdelta_patches_section)
        layout.addStretch()
        return widget

    def _show_file_picker_dialog(
        self, files: list, title: str, label_text: str
    ) -> str | None:
        file_dialog = QDialog(self)
        file_dialog.setWindowTitle(title)
        file_dialog.resize(600, 400)
        layout = QVBoxLayout(file_dialog)
        layout.addWidget(QLabel(label_text))
        from PyQt6.QtWidgets import QListWidget

        list_widget = QListWidget()
        for file_path, rel_path in files:
            item_text = f"{os.path.basename(file_path)} ({rel_path})"
            list_widget.addItem(item_text)
            list_widget.item(list_widget.count() - 1).setData(
                Qt.ItemDataRole.UserRole, file_path
            )
        list_widget.itemDoubleClicked.connect(self._on_picker_item_double_clicked)
        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)
        layout.addWidget(list_widget)
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(file_dialog.accept)
        button_box.rejected.connect(file_dialog.reject)
        layout.addWidget(button_box)
        if file_dialog.exec() == QDialog.DialogCode.Accepted:
            current_item = list_widget.currentItem()
            if current_item:
                return current_item.data(Qt.ItemDataRole.UserRole)
        return None

    def _on_picker_item_double_clicked(self, item):
        file_path = item.data(Qt.ItemDataRole.UserRole) if item else ""
        if self._is_openable_doc(file_path):
            self._open_local_file(file_path)

    @classmethod
    def _is_openable_doc(cls, file_path: str) -> bool:
        return os.path.splitext(file_path)[1].lower() in cls._OPENABLE_DOC_EXTENSIONS

    def _create_file_name_widget(self, file_path: str, rel_path: str) -> QWidget:
        file_name = os.path.basename(file_path)
        if not self._is_openable_doc(file_path):
            label = QLabel(file_name)
            label.setToolTip(rel_path)
            label.setMinimumWidth(120)
            label.setMaximumWidth(200)
            return label
        button = QPushButton(file_name)
        theme = get_dialog_theme_values(self.app_state) if self.app_state else {}
        theme_color = theme.get("secondary_text", "#6de985")
        button.setFlat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(f"{rel_path}\n{tr('ui.open_instructions')}")
        button.setMinimumWidth(120)
        button.setMaximumWidth(200)
        button.setStyleSheet(
            f"QPushButton {{ text-align: left; color: {theme_color}; border: none; padding: 0px; }}"
            "QPushButton:hover { text-decoration: underline; }"
        )
        button.clicked.connect(lambda _=False, p=file_path: self._open_local_file(p))
        return button

    def _make_tool_button(self, icon_name, tooltip: str, text: str = "") -> QPushButton:
        button = QPushButton(text)
        button.setIcon(self._icon(icon_name))
        button.setIconSize(self._icon_size(18))
        button.setToolTip(tooltip)
        return button

    def _open_local_file(self, file_path: str):
        if not self._is_openable_doc(file_path):
            return
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(
                self, tr("errors.error"), file_path or tr("errors.error")
            )
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(file_path)):
            QMessageBox.warning(self, tr("errors.error"), file_path)

    def _browse_data_file(self, chapter_id: str):
        selected_data, used_patches = self._get_excluded_files()
        excluded = selected_data | used_patches
        found_files = [
            (fp, rp)
            for fp, rp in self.all_files
            if fp not in excluded
            and os.path.splitext(fp)[1].lower() in DATA_FILE_EXTENSIONS
        ]
        if not found_files:
            QMessageBox.information(
                self,
                tr("dialogs.no_data_files"),
                tr("dialogs.no_data_files_in_directory"),
            )
            return
        chapter_label = self._chapter_display_name(chapter_id)
        file_path = self._show_file_picker_dialog(
            found_files,
            tr("dialogs.select_data_file", file_type="DATA"),
            tr("dialogs.select_data_file_info", chapter=chapter_label),
        )
        if file_path:
            self.data_file_selections[chapter_id] = file_path
            if chapter_id in self.data_file_edits:
                self.data_file_edits[chapter_id].setText(os.path.basename(file_path))
            self._update_data_file_visibility()
            self._populate_extra_files_list()
            self._update_xdelta_patches_section(chapter_id)
            self._refresh_summary_text()

    def _clear_data_file(self, chapter_id: str):
        if chapter_id in self.data_file_selections:
            del self.data_file_selections[chapter_id]
        if chapter_id in self.data_file_edits:
            self.data_file_edits[chapter_id].clear()
        self._update_data_file_visibility()
        self._populate_extra_files_list()
        self._update_xdelta_patches_section(chapter_id)
        self._refresh_summary_text()

    def _update_data_file_visibility(self):
        for chapter_id in list(self.xdelta_patch_widgets.keys()):
            self._update_xdelta_patches_section(chapter_id)

    def _get_excluded_files(self):
        selected = set(self.data_file_selections.values())
        patches = set()
        for p in self.xdelta_patches_mappings.values():
            patches.update(p.keys())
        return selected, patches

    def _get_available_xdelta_files(self, chapter_id: str) -> list[tuple]:
        selected_data, used_patches = self._get_excluded_files()
        excluded = selected_data | self.unused_files | used_patches
        return [
            (fp, rp)
            for fp, rp in self.all_files
            if fp not in excluded
            and os.path.splitext(fp)[1].lower() in (".xdelta", ".vcdiff")
        ]

    def _create_xdelta_patches_section(self, chapter_id: str) -> QWidget | None:
        if (
            chapter_id not in self.xdelta_patches_mappings
            or not self.xdelta_patches_mappings[chapter_id]
        ):
            return None
        section_widget = QWidget()
        section_layout = QVBoxLayout(section_widget)
        section_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        section_layout.setSpacing(10)
        info_label = QLabel(tr("dialogs.xdelta_patches_info"))
        info_label.setWordWrap(True)
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label.setProperty("hintText", True)
        info_label.setStyleSheet("font-size: 11px; padding: 10px;")
        section_layout.addWidget(info_label)
        section_title = QLabel(tr("dialogs.xdelta_patches_section"))
        section_title.setStyleSheet("font-weight: bold; font-size: 12px;")
        section_layout.addWidget(section_title)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setMaximumHeight(300)
        scroll_area.setMinimumHeight(150)
        scroll_content = QWidget()
        patches_layout = QVBoxLayout(scroll_content)
        patches_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        patches_layout.setSpacing(10)
        if chapter_id not in self.xdelta_patch_widgets:
            self.xdelta_patch_widgets[chapter_id] = {}
        for file_path in self.xdelta_patches_mappings[chapter_id]:
            rel_path = next((rp for fp, rp in self.all_files if fp == file_path), "")
            patch_widget = self._create_xdelta_patch_widget(
                file_path, rel_path, chapter_id
            )
            patches_layout.addWidget(patch_widget)
            self.xdelta_patch_widgets[chapter_id][file_path] = patch_widget
        patches_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        section_layout.addWidget(scroll_area)
        return section_widget

    def _create_xdelta_patch_widget(
        self, file_path: str, rel_path: str, chapter_id: str
    ) -> QWidget:
        widget = QWidget()
        widget.setProperty("fileCard", True)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)
        layout.addWidget(self._create_file_name_widget(file_path, rel_path))
        path_input = QLineEdit()
        path_input.setObjectName(f"xdelta_path_input_{file_path}")
        path_input.setMinimumWidth(200)
        if (
            chapter_id in self.xdelta_patches_mappings
            and file_path in self.xdelta_patches_mappings[chapter_id]
        ):
            path_input.setText(self.xdelta_patches_mappings[chapter_id][file_path])
        path_input.setPlaceholderText(tr("dialogs.xdelta_patch_target_path"))
        path_input.setToolTip(tr("tooltips.manual_install_xdelta_target"))
        path_input.textChanged.connect(
            lambda text, fp=file_path, cid=chapter_id: (
                self._on_xdelta_target_path_changed(fp, text, cid)
            )
        )
        layout.addWidget(path_input, 1)
        browse_btn = self._make_tool_button(
            "folder_icon.svg", tr("ui.browse_button"), tr("ui.browse_button")
        )
        browse_btn.clicked.connect(
            lambda checked, fp=file_path, cid=chapter_id: (
                self._browse_xdelta_target_file(fp, cid)
            )
        )
        layout.addWidget(browse_btn)
        clear_btn = self._make_tool_button(
            "cross_icon.svg", tr("ui.clear_button"), ""
        )
        clear_btn.setObjectName(f"xdelta_clear_btn_{file_path}")
        clear_btn.setToolTip(tr("tooltips.clear_selection"))
        clear_btn.clicked.connect(
            lambda checked, fp=file_path, cid=chapter_id: self._clear_xdelta_patch(
                fp, cid
            )
        )
        layout.addWidget(clear_btn)
        return widget

    def _on_xdelta_target_path_changed(
        self, file_path: str, text: str, chapter_id: str
    ):
        normalized = self._normalize_relative_target_path(text, chapter_id)
        if (
            normalized != text
            and chapter_id in self.xdelta_patch_widgets
            and file_path in self.xdelta_patch_widgets[chapter_id]
        ):
            widget = self.xdelta_patch_widgets[chapter_id][file_path]
            path_input = widget.findChild(QLineEdit, f"xdelta_path_input_{file_path}")
            if path_input:
                path_input.setText(normalized)
        if chapter_id not in self.xdelta_patches_mappings:
            self.xdelta_patches_mappings[chapter_id] = {}
        if normalized:
            self.xdelta_patches_mappings[chapter_id][file_path] = normalized
        elif file_path in self.xdelta_patches_mappings[chapter_id]:
            del self.xdelta_patches_mappings[chapter_id][file_path]

    @staticmethod
    def _normalize_path(path: str, trailing_slash: bool = False) -> str:
        if not path:
            return ""
        path = path.strip().strip("/").strip("\\").replace("\\", "/")
        result = "/".join(
            p for p in path.split("/") if p and p != ".." and not os.path.isabs(p)
        )
        return (result + "/") if result and trailing_slash else result

    def _browse_xdelta_target_file(self, file_path: str, chapter_id: str):
        target_root = self._get_target_root_for_chapter(chapter_id)
        if not target_root:
            return
        target_file, _ = QFileDialog.getOpenFileName(
            self, tr("dialogs.select_target_folder"), target_root
        )
        if target_file:
            target_root_normalized = os.path.normpath(os.path.abspath(target_root))
            file_normalized = os.path.normpath(os.path.abspath(target_file))
            if file_normalized.startswith(target_root_normalized):
                rel_file = os.path.relpath(target_file, target_root)
                rel_file = self._normalize_relative_target_path(rel_file, chapter_id)
                if (
                    chapter_id in self.xdelta_patch_widgets
                    and file_path in self.xdelta_patch_widgets[chapter_id]
                ):
                    widget = self.xdelta_patch_widgets[chapter_id][file_path]
                    path_input = widget.findChild(
                        QLineEdit, f"xdelta_path_input_{file_path}"
                    )
                    if path_input:
                        path_input.setText(rel_file)
                        if chapter_id not in self.xdelta_patches_mappings:
                            self.xdelta_patches_mappings[chapter_id] = {}
                        self.xdelta_patches_mappings[chapter_id][file_path] = rel_file
            else:
                QMessageBox.warning(
                    self, tr("errors.error"), tr("dialogs.path_outside_game_folder")
                )

    def _add_xdelta_patch(self, chapter_id: str):
        available_xdelta = self._get_available_xdelta_files(chapter_id)
        if not available_xdelta:
            QMessageBox.information(
                self,
                tr("dialogs.no_data_files"),
                tr("dialogs.no_xdelta_files_available"),
            )
            return
        file_path = self._show_file_picker_dialog(
            available_xdelta,
            tr("dialogs.select_xdelta_patch"),
            tr("dialogs.select_xdelta_patch_info"),
        )
        if file_path:
            if chapter_id not in self.xdelta_patches_mappings:
                self.xdelta_patches_mappings[chapter_id] = {}
            self.xdelta_patches_mappings[chapter_id][file_path] = ""
            self._update_xdelta_patches_section(chapter_id)
            self._populate_extra_files_list()
            self._refresh_summary_text()

    def _clear_xdelta_patch(self, file_path: str, chapter_id: str):
        if (
            chapter_id in self.xdelta_patches_mappings
            and file_path in self.xdelta_patches_mappings[chapter_id]
        ):
            del self.xdelta_patches_mappings[chapter_id][file_path]
        self._update_xdelta_patches_section(chapter_id)
        self._populate_extra_files_list()
        self._refresh_summary_text()

    def _update_xdelta_patches_section(self, chapter_id: str):
        current_tab_index = self.data_tabs.currentIndex()
        if self.data_tabs.count() > current_tab_index:
            current_widget = self.data_tabs.widget(current_tab_index)
            if current_widget:
                layout = current_widget.layout()
                if layout:
                    for i in range(layout.count()):
                        item = layout.itemAt(i)
                        if item and item.widget():
                            widget = item.widget()
                            if (
                                hasattr(widget, "objectName")
                                and widget.objectName() == "xdelta_patches_section"
                            ):
                                layout.removeWidget(widget)
                                widget.deleteLater()
                                break
                    if self.xdelta_patches_mappings.get(chapter_id):
                        xdelta_section = self._create_xdelta_patches_section(chapter_id)
                        if xdelta_section:
                            xdelta_section.setObjectName("xdelta_patches_section")
                            layout.insertWidget(layout.count() - 1, xdelta_section)

    def _populate_extra_files_list(self):
        if not hasattr(self, "extra_files_list_layout"):
            return
        while self.extra_files_list_layout.count():
            item = self.extra_files_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        selected_data, used_patches = self._get_excluded_files()
        extra_files = [
            (fp, rp)
            for fp, rp in self.all_files
            if fp not in selected_data and fp not in used_patches
        ]
        if not extra_files:
            no_files_label = QLabel(tr("dialogs.no_data_files"))
            no_files_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.extra_files_list_layout.addWidget(no_files_label)
            return
        self.extra_file_widgets.clear()
        for file_path, rel_path in extra_files:
            file_widget = self._create_extra_file_widget(file_path, rel_path)
            self.extra_files_list_layout.addWidget(file_widget)
            self.extra_file_widgets[file_path] = file_widget
        self.extra_files_list_layout.addStretch()

    def _guess_chapter_for_file(self, rel_path: str) -> str | None:
        chapter_id, _normalized = self._extract_chapter_prefixed_path(rel_path)
        return chapter_id

    def _chapter_alias_map(self) -> dict[str, str]:
        folder_to_chapter = {}
        for chapter_id, _name in self._chapter_entries():
            for alias in self._chapter_path_aliases(chapter_id):
                folder_to_chapter[alias] = chapter_id
        return folder_to_chapter

    def _extract_chapter_prefixed_path(
        self, path: str, *, trailing_slash: bool | None = None
    ) -> tuple[str | None, str]:
        if trailing_slash is None:
            trailing_slash = str(path or "").endswith(("/", "\\"))
        normalized = self._normalize_path(path, trailing_slash=trailing_slash)
        if not normalized:
            return None, ""
        preserve_trailing = normalized.endswith("/")
        working = normalized[:-1] if preserve_trailing else normalized
        if not working:
            return None, ""
        first_part, _, rest = working.partition("/")
        chapter_id = self._chapter_alias_map().get(first_part.lower())
        if not chapter_id:
            return None, normalized
        if not rest:
            return chapter_id, ""
        return chapter_id, f"{rest}/" if preserve_trailing else rest

    def _default_extra_target_path(self, file_path: str, rel_path: str) -> str:
        normalized = str(rel_path or "").replace("\\", "/").strip("/")
        chapter_id, stripped = self._extract_chapter_prefixed_path(normalized)
        if chapter_id:
            self.extra_files_chapters.setdefault(file_path, chapter_id)
            normalized = stripped.strip("/")
        if not normalized:
            return ""
        dir_part = os.path.dirname(normalized).replace("\\", "/").strip("/")
        return self._normalize_path(dir_part, trailing_slash=True)

    def _chapter_path_aliases(self, chapter_id: str) -> set[str]:
        aliases: set[str] = set()
        game = self.game_combo.currentData()
        storage_name = get_chapter_folder_name(chapter_id, game=game)
        if storage_name:
            aliases.add(storage_name.replace("\\", "/").strip("/").lower())
        if "_" in chapter_id:
            suffix = chapter_id.rsplit("_", 1)[1]
            if suffix.isdigit():
                aliases.add(f"chapter{suffix}")
                aliases.add(f"chapter_{suffix}")
                aliases.add(f"chapter{suffix}_")
                aliases.add(f"chapter{suffix}_windows")
        target_root = self._peek_target_root_for_chapter(chapter_id)
        if target_root:
            target_name = os.path.basename(os.path.normpath(target_root))
            if target_name:
                aliases.add(target_name.replace("\\", "/").strip("/").lower())
        return {alias for alias in aliases if alias}

    def _strip_chapter_prefix(self, normalized_path: str, chapter_id: str) -> str:
        if not normalized_path:
            return ""
        stripped = normalized_path
        lowered = stripped.lower()
        for alias in self._chapter_path_aliases(chapter_id):
            if lowered == alias:
                return ""
            prefix = f"{alias}/"
            if lowered.startswith(prefix):
                stripped = stripped[len(prefix) :]
                lowered = stripped.lower()
        return stripped

    def _normalize_relative_target_path(
        self,
        path: str,
        chapter_id: str,
        *,
        trailing_slash: bool = False,
    ) -> str:
        normalized = self._normalize_path(path, trailing_slash=trailing_slash)
        if not normalized:
            return ""
        preserve_trailing = normalized.endswith("/")
        working = normalized[:-1] if preserve_trailing else normalized
        working = self._strip_chapter_prefix(working, chapter_id)
        if not working:
            return ""
        return f"{working}/" if preserve_trailing else working

    def _create_extra_file_widget(self, file_path: str, rel_path: str) -> QWidget:
        widget = QWidget()
        widget.setProperty("fileCard", True)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)
        layout.addWidget(self._create_file_name_widget(file_path, rel_path))
        auto_path = self._default_extra_target_path(file_path, rel_path)
        path_input = QLineEdit()
        path_input.setObjectName("path_input")
        path_input.setMinimumWidth(200)
        if file_path in self.extra_files_mappings:
            path_input.setText(self.extra_files_mappings[file_path])
        elif auto_path:
            path_input.setText(auto_path)
            self.extra_files_mappings[file_path] = auto_path
        path_input.setPlaceholderText(tr("dialogs.enter_relative_path"))
        path_input.textChanged.connect(
            lambda text, fp=file_path: self._on_path_changed(fp, text)
        )
        if file_path in self.unused_files:
            path_input.setEnabled(False)
        layout.addWidget(path_input, 1)
        browse_btn = self._make_tool_button(
            "folder_icon.svg", tr("ui.browse_button"), tr("ui.browse_button")
        )
        browse_btn.setObjectName("browse_target_button")
        browse_btn.clicked.connect(
            lambda checked, fp=file_path: self._browse_target_folder(fp)
        )
        if file_path in self.unused_files:
            browse_btn.setEnabled(False)
        layout.addWidget(browse_btn)
        toggle_btn = QPushButton()
        toggle_btn.setObjectName(f"toggle_btn_{file_path}")
        if file_path in self.unused_files:
            toggle_btn.setText(tr("ui.use_button"))
        else:
            toggle_btn.setText(tr("ui.remove_button"))
        toggle_btn.clicked.connect(
            lambda checked, fp=file_path: self._toggle_file_usage(fp)
        )
        layout.addWidget(toggle_btn)
        return widget

    def _on_path_changed(self, file_path: str, text: str):
        normalized = self._normalize_path(text, trailing_slash=True)
        if normalized != text and file_path in self.extra_file_widgets:
            widget = self.extra_file_widgets[file_path]
            path_input = widget.findChild(QLineEdit, "path_input")
            if path_input:
                path_input.setText(normalized)
        if file_path not in self.unused_files:
            chapter_id, _stripped = self._extract_chapter_prefixed_path(normalized)
            if chapter_id:
                self.extra_files_chapters[file_path] = chapter_id
            self.extra_files_mappings[file_path] = normalized
        elif file_path in self.extra_files_mappings:
            del self.extra_files_mappings[file_path]

    def _browse_target_folder(self, file_path: str):
        game_root = self._get_or_prompt_game_folder()
        if not game_root:
            return
        folder = QFileDialog.getExistingDirectory(
            self, tr("dialogs.select_target_folder"), game_root
        )
        if folder:
            game_root_normalized = os.path.normpath(os.path.abspath(game_root))
            folder_normalized = os.path.normpath(os.path.abspath(folder))
            if folder_normalized.startswith(game_root_normalized):
                rel_folder = os.path.relpath(folder, game_root)
                rel_folder = rel_folder.replace("\\", "/").strip("/")
                if rel_folder:
                    rel_folder += "/"
                if file_path in self.extra_file_widgets:
                    widget = self.extra_file_widgets[file_path]
                    path_input = widget.findChild(QLineEdit, "path_input")
                    if path_input:
                        path_input.setText(rel_folder)
                        chapter_id, _stripped = self._extract_chapter_prefixed_path(
                            rel_folder, trailing_slash=True
                        )
                        if chapter_id:
                            self.extra_files_chapters[file_path] = chapter_id
                        self.extra_files_mappings[file_path] = rel_folder
            else:
                QMessageBox.warning(
                    self, tr("errors.error"), tr("dialogs.path_outside_game_folder")
                )

    def _get_target_root_for_chapter(self, chapter_id: str) -> str | None:
        game_root = self._get_or_prompt_game_folder()
        if not game_root:
            return None
        return self._resolve_target_root_for_chapter(game_root, chapter_id)

    def _peek_target_root_for_chapter(self, chapter_id: str) -> str | None:
        game_def = get_game(self.game_combo.currentData() or "")
        if not game_def or not self.app_state or not getattr(self.app_state, "local_config", None):
            return None
        try:
            game_root = game_def.get_game_path(self.app_state.local_config)
        except Exception:
            return None
        if not game_root:
            return None
        return self._resolve_target_root_for_chapter(game_root, chapter_id)

    def _resolve_target_root_for_chapter(
        self, game_root: str, chapter_id: str
    ) -> str | None:
        game_def = get_game(self.game_combo.currentData() or "")
        if not game_def or not game_def.is_multi_tab:
            return game_root
        chapter_root = find_chapter_resource_dir(
            game_root,
            chapter_id,
            getattr(game_def, "macos_app_names", ("DELTARUNE.app", "DELTARUNEdemo.app")),
        )
        return chapter_root or game_root

    def _get_or_prompt_game_folder(self) -> str | None:
        game_def = get_game(self.game_combo.currentData() or "")
        game_root = None
        if game_def:
            try:
                game_root = game_def.get_game_path(self.app_state.local_config)
            except Exception as e:
                logging.debug(
                    f"ManualInstallDialog: Failed to get game path: {e}", exc_info=True
                )
        if not game_root or not os.path.exists(game_root):
            settings_service = None
            if hasattr(self.parent(), "settings_service"):
                settings_service = self.parent().settings_service
            elif self.app_state and hasattr(self.app_state, "settings_service"):
                settings_service = self.app_state.settings_service
            if settings_service and game_def:
                old_game_mode = self.app_state.game_mode
                self.app_state.game_mode = game_def
                try:
                    prompted = settings_service.prompt_for_game_path(is_initial=False)
                finally:
                    self.app_state.game_mode = old_game_mode
                if prompted:
                    try:
                        game_root = game_def.get_game_path(self.app_state.local_config)
                    except Exception as e:
                        logging.debug(
                            f"ManualInstallDialog: Failed to get game path after prompt: {e}",
                            exc_info=True,
                        )
        return game_root if game_root and os.path.exists(game_root) else None

    def _toggle_file_usage(self, file_path: str):
        is_unused = file_path not in self.unused_files
        if is_unused:
            self.unused_files.add(file_path)
            self.extra_files_mappings.pop(file_path, None)
        else:
            self.unused_files.discard(file_path)
        if file_path not in self.extra_file_widgets:
            return
        widget = self.extra_file_widgets[file_path]
        toggle_btn = widget.findChild(QPushButton, f"toggle_btn_{file_path}")
        if toggle_btn:
            toggle_btn.setText(
                tr("ui.use_button") if is_unused else tr("ui.remove_button")
            )
        path_input = widget.findChild(QLineEdit, "path_input")
        if path_input:
            path_input.setEnabled(not is_unused)
            if is_unused:
                path_input.clear()
        browse_btn = widget.findChild(QPushButton, "browse_target_button")
        if browse_btn:
            browse_btn.setEnabled(not is_unused)
        self._refresh_summary_text()

    def _apply_theme_styles(self):
        border = self._theme_value("border", "#2d5440")
        background = self._theme_value("background", "#132019")
        elements = self._theme_value("elements", "#1d3a2b")
        hint = self._theme_value("secondary_text", "#8fa89a")
        field_bg = self._mix_color(elements, 0.08)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {self._mix_color(background, 0.08)};
            }}
            QWidget {{
                color: {self._theme_value("main_text", "#e8e9eb")};
            }}
            QTabWidget::pane, QScrollArea {{
                background-color: {field_bg};
            }}
            QLineEdit, QComboBox {{
                background-color: {elements};
            }}
            QComboBox {{
                border: 2px solid {border};
                border-radius: {clamp_border_radius(7, height=max(30, round(36 * self._ui_scale())), border_width=2)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {elements};
                border: 2px solid {border};
                selection-background-color: {self._theme_value("hover", "#3cb371")};
                selection-color: {self._theme_value("main_text", "#e8e9eb")};
            }}
            QWidget[fileCard="true"] {{
                background-color: {field_bg};
                border: 1px solid {border};
                border-radius: 10px;
            }}
            QLabel[hintText="true"] {{
                color: {hint};
                qproperty-alignment: AlignCenter;
            }}
            """
        )
        for widget in (self.files_summary_label,):
            widget.setStyleSheet(f"color: {hint}; background-color: {elements}; border: 1px solid {border}; border-radius: 10px;")

    def _on_finish(self):
        has_data_files = bool(self.data_file_selections)
        selected_data, used_patches = self._get_excluded_files()
        extra_files_count = sum(
            1
            for fp, _ in self.all_files
            if fp not in selected_data
            and fp not in self.unused_files
            and fp not in used_patches
        )
        has_extra_files = extra_files_count > 0
        if not has_data_files and (not has_extra_files):
            QMessageBox.warning(
                self, tr("errors.error"), tr("dialogs.no_data_file_selected")
            )
            return
        for patches in self.xdelta_patches_mappings.values():
            for target_path in patches.values():
                if not target_path or not target_path.strip():
                    QMessageBox.warning(
                        self,
                        tr("errors.error"),
                        tr("dialogs.xdelta_patch_no_target_path"),
                    )
                    return
        try:
            self._create_mod_from_files()
            self.accept()
        except Exception as e:
            logging.error(f"Failed to create mod: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                tr("errors.error"),
                tr("errors.manual_install_failed", error=str(e)),
            )

    @staticmethod
    def _copy_file_to_relative_path(
        target_mod_dir: str,
        source_path: str,
        relative_path: str,
    ) -> str:
        normalized_relative = relative_path.replace("\\", "/").strip().strip("/")
        if not normalized_relative:
            normalized_relative = os.path.basename(source_path)
        target_path = os.path.join(
            target_mod_dir, normalized_relative.replace("/", os.sep)
        )
        target_dir = os.path.dirname(target_path)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
        base_name, extension = os.path.splitext(target_path)
        suffix = 1
        while os.path.exists(target_path):
            target_path = f"{base_name}_{suffix}{extension}"
            suffix += 1
        shutil.copy2(source_path, target_path)
        return os.path.relpath(target_path, target_mod_dir).replace("\\", "/")

    def _storage_prefix_for_chapter(self, chapter_id: str) -> str:
        game = self.game_combo.currentData()
        game_def = get_game(game)
        if game_def and game_def.is_multi_tab:
            return get_chapter_folder_name(chapter_id, game=game)
        return ""

    def _join_storage_path(self, chapter_id: str, *parts: str) -> str:
        normalized_parts = []
        prefix = self._storage_prefix_for_chapter(chapter_id)
        if prefix:
            normalized_parts.append(prefix)
        for part in parts:
            text = str(part or "").replace("\\", "/").strip("/")
            if text:
                normalized_parts.append(text)
        return "/".join(normalized_parts)

    def _chapter_display_name(self, chapter_id: str) -> str:
        for i in range(self.data_tabs.count()):
            widget = self.data_tabs.widget(i)
            if widget and getattr(widget, "_chapter_id", None) == chapter_id:
                return self.data_tabs.tabText(i)
        if "_" in chapter_id:
            suffix = chapter_id.rsplit("_", 1)[1]
            if suffix == "0":
                return tr("tabs.menu_root")
            try:
                return tr(f"tabs.chapter_{suffix}")
            except Exception:
                return suffix
        return chapter_id

    def _copy_root_docs_to_mod(self, target_mod_dir: str) -> None:
        for file_path, relative_path in self.all_files:
            if os.path.dirname(relative_path):
                continue
            if os.path.splitext(file_path)[1].lower() not in MOD_ROOT_DOC_EXTENSIONS:
                continue
            if not os.path.isfile(file_path):
                continue
            shutil.copy2(
                file_path,
                os.path.join(target_mod_dir, os.path.basename(file_path)),
            )

    def _create_mod_from_files(self):
        if not self.app_state or not self.mod_service:
            raise ValueError("app_state or mod_service not available")
        if self.gamebanana_metadata.get("mod_id"):
            item_type = self.gamebanana_metadata.get("item_type", "mod").lower()
            mod_id = f"gb_{item_type}_{self.gamebanana_metadata['mod_id']}"
        else:
            import time

            mod_id = f"local_manual_{int(time.time())}"
        if self.gamebanana_metadata.get("name"):
            mod_name = self.gamebanana_metadata["name"]
        elif self.source_file_path:
            from utils.file_utils import remove_archive_extension

            archive_name = os.path.basename(self.source_file_path)
            mod_name = remove_archive_extension(archive_name)
        else:
            mod_name = "Manual Mod"
        folder_name = get_unique_mod_dir(self.app_state.mods_dir, mod_name)
        target_mod_dir = os.path.join(self.app_state.mods_dir, folder_name)
        os.makedirs(target_mod_dir, exist_ok=True)
        files_structure = {}
        game = self.game_combo.currentData()
        for chapter_id, data_file_path in self.data_file_selections.items():
            files_structure.setdefault(chapter_id, {})
            stored_data_path = self._copy_file_to_relative_path(
                target_mod_dir,
                data_file_path,
                self._join_storage_path(
                    chapter_id, os.path.basename(data_file_path)
                ),
            )
            files_structure[chapter_id]["data_file_path"] = stored_data_path
        selected_data, used_patches = self._get_excluded_files()
        excluded = selected_data | self.unused_files | used_patches
        all_extra_files = [
            (fp, self.extra_files_mappings.get(fp, ""))
            for fp in (fp for fp, _ in self.all_files if fp not in excluded)
        ]
        for chapter_id, patches in self.xdelta_patches_mappings.items():
            files_structure.setdefault(chapter_id, {})
            for xdelta_file_path, target_path in patches.items():
                if not target_path or not target_path.strip():
                    continue
                target_path_normalized = target_path.replace("\\", "/").strip("/")
                if not target_path_normalized:
                    continue
                dir_part = os.path.dirname(target_path_normalized)
                file_part = os.path.basename(target_path_normalized)
                renamed_xdelta_name = f"{file_part}.xdelta"
                stored_patch_path = self._join_storage_path(
                    chapter_id, dir_part, renamed_xdelta_name
                )
                copied_path = self._copy_file_to_relative_path(
                    target_mod_dir,
                    xdelta_file_path,
                    stored_patch_path,
                )
                files_structure[chapter_id].setdefault("extra_files", []).append(
                    copied_path
                )
        for extra_file_path, relative_path in all_extra_files:
            relative_path = (
                relative_path.strip().strip("/").strip("\\") if relative_path else ""
            )
            path_chapter_id, stripped_relative_path = self._extract_chapter_prefixed_path(
                relative_path
            )
            if path_chapter_id:
                target_chapter_id = path_chapter_id
                relative_path = stripped_relative_path.strip().strip("/").strip("\\")
            else:
                relative_path = relative_path.strip().strip("/").strip("\\")
                target_chapter_id = self.extra_files_chapters.get(extra_file_path)
            target_chapter_id = (
                target_chapter_id
                or (
                    min(self.data_file_selections.keys())
                    if game == "deltarune" and self.data_file_selections
                    else game
                )
            )
            files_structure.setdefault(target_chapter_id, {})
            stored_extra_path = self._join_storage_path(
                target_chapter_id,
                relative_path,
                os.path.basename(extra_file_path),
            )
            copied_path = self._copy_file_to_relative_path(
                target_mod_dir,
                extra_file_path,
                stored_extra_path,
            )
            files_structure[target_chapter_id].setdefault("extra_files", []).append(
                copied_path
            )
        config_data = {
            "id": mod_id,
            "name": mod_name,
            "game": game,
            "files": files_structure,
        }
        if self.gamebanana_metadata:
            from adapters.gamebanana_adapter import GameBananaAPI

            for field in (
                "author",
                "description",
                "icon",
                "homepage",
                "tags",
                "version",
            ):
                if self.gamebanana_metadata.get(field):
                    config_data[field] = self.gamebanana_metadata[field]
            category_tag = GameBananaAPI.category_to_tag(
                self.gamebanana_metadata.get("category")
            )
            if category_tag:
                existing_tags = config_data.get("tags", [])
                if not isinstance(existing_tags, list):
                    existing_tags = [existing_tags] if existing_tags else []
                if category_tag not in existing_tags:
                    existing_tags.append(category_tag)
                config_data["tags"] = existing_tags
            config_data.setdefault("author", "Unknown")
            config_data.setdefault("version", "1.0.0")
        else:
            config_data["author"] = "Unknown"
            config_data["version"] = "1.0.0"
        self._copy_root_docs_to_mod(target_mod_dir)
        config_path = os.path.join(target_mod_dir, MOD_CONFIG_FILENAME)
        save_json(config_path, build_mod_config_data(config_data), indent=2)
        logging.info(f"Manual mod created: {target_mod_dir}")
