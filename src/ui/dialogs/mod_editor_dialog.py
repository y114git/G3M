"""Dialog for creating and editing local mods."""

import logging
import os
import shutil
import uuid
from contextlib import suppress
from typing import override

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from models.game_modes import get_game, get_visible_game_entries
from services.localization_service import tr
from ui.common.styling import (
    clamp_border_radius,
    get_border_radius,
    get_theme_color,
    get_ui_scale_factor,
    round_pixmap,
)
from utils.file_utils import (
    get_file_filter,
    get_unique_mod_dir,
)
from utils.mod_config_parser import (
    MOD_ALLOWED_TAGS,
    MOD_FIELD_LIMITS,
    build_mod_config_data,
    normalize_mod_config_data,
    parse_extra_files_raw,
    resolve_mod_file_path,
)
from utils.path_utils import colored_icon, resource_path


class ModEditorDialog(QDialog):
    """Native dialog for creating/editing local mods."""

    def __init__(self, parent, is_creating=True, mod_data=None) -> None:
        super().__init__(parent)
        self.parent_app = parent
        self._app_state = self._resolve_app_state(parent)
        self.is_creating = is_creating
        payload = (
            mod_data.get("mod_data")
            if isinstance(mod_data, dict) and isinstance(mod_data.get("mod_data"), dict)
            else mod_data
        )
        self.mod_data = payload or {}
        self.mod_id = self.mod_data.get("id") if isinstance(self.mod_data, dict) else None
        self._last_browse_dir = os.path.expanduser("~")
        self._cfg = getattr(self._app_state, "local_config", None)
        self.setWindowTitle(tr("ui.create_mod") if is_creating else tr("ui.edit_mod"))
        self.setModal(True)
        scale = self._cfg.get("ui_scale", 1.0) if self._cfg else 1.0
        self.resize(round(1110 * scale), round(700 * scale))
        self.setMinimumSize(round(700 * scale), round(500 * scale))
        self._init_ui()
        if not is_creating and mod_data:
            self._populate_fields()

    def _br(self, w=None, h=None):
        r = get_border_radius(self._get_config())
        if w or h:
            return clamp_border_radius(r, width=w or 0, height=h or 0)
        return r

    def _get_config(self):
        app_state = self._app_state or getattr(self.parent_app, "app_state", None)
        config = getattr(app_state, "local_config", None) if app_state else None
        if config is not None:
            self._cfg = config
            return config
        return getattr(self, "_cfg", None)

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

    def _color(self, key, fallback):
        return get_theme_color(self._get_config(), key, fallback)

    def _ui_scale(self) -> float:
        return get_ui_scale_factor(self._get_config(), default=1.0)

    def _icon_size(self, base: int) -> QSize:
        size = max(14, round(base * self._ui_scale()))
        return QSize(size, size)

    def _mix_color(self, color_value, factor=0.18):
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

    def _icon(self, icon_name):
        icon_key = {
            "folder_icon.svg": "folder",
            "delete_icon.svg": "delete",
            "cross_icon.svg": "cross",
            "add_icon.svg": "add",
        }.get(icon_name)
        if icon_key:
            return colored_icon(icon_key, self._color("main_text", "#e8e9eb"))
        return colored_icon("folder", self._color("main_text", "#e8e9eb"))

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
        rect = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(rect.center())
        self.move(frame.topLeft())

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setSpacing(14)

        settings_frame = QFrame()
        settings_frame.setFrameStyle(QFrame.Shape.Box)
        settings_frame.setObjectName("modEditorSettingsFrame")
        s_layout = QVBoxLayout(settings_frame)
        s_layout.setContentsMargins(16, 16, 16, 16)
        s_layout.setSpacing(12)

        game_row = QHBoxLayout()
        game_row.addStretch()
        game_row.addWidget(QLabel(tr("ui.mod_type_label")))
        self.game_combo = QComboBox()
        self.game_combo.setToolTip(tr("tooltips.mod_editor_game"))
        self._visible_game_ids = set()
        for entry in get_visible_game_entries():
            self.game_combo.addItem(entry.display_name, entry.id)
            self._visible_game_ids.add(entry.id)
        self.game_combo.currentIndexChanged.connect(self._update_file_tabs)
        game_row.addWidget(self.game_combo)
        game_row.addStretch()
        s_layout.addLayout(game_row)

        self._build_form(s_layout)
        layout.addWidget(settings_frame)

        self._build_file_section(layout)
        self._load_default_icon()

        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)
        self._build_action_buttons(main_layout)

        border = self._color("border", "#039d5b")
        background = self._color("background", "#282828")
        elements = self._color("elements", "#222222")
        self.setStyleSheet(
            f"""
            QFrame#modEditorSettingsFrame, QFrame#modEditorFilesFrame {{
                border: 1px solid {border};
                border-radius: {self._br()}px;
                background-color: {background};
            }}
            QFrame[fileActionsRow="true"] {{
                border: 1px solid {border};
                border-radius: {self._br()}px;
                background-color: {elements};
            }}
            QLabel[sectionTitle="true"] {{
                font-size: 15px;
                font-weight: 700;
                qproperty-alignment: AlignCenter;
            }}
            QLabel[hintText="true"] {{
                color: {self._color("secondary_text", "#96b2a0")};
                qproperty-alignment: AlignCenter;
            }}
            QLineEdit, QComboBox {{
                background-color: {elements};
            }}
            QTabWidget::pane, QScrollArea {{
                background-color: {background};
            }}
            QFrame[fileCard="true"] {{
                border: 1px solid {border};
                border-radius: {self._br()}px;
                background-color: {elements};
            }}
            """
        )

    def _build_section_title(self, text):
        label = QLabel(text)
        label.setProperty("sectionTitle", True)
        return label

    def _build_form(self, parent):
        hint = QLabel(tr("ui.mod_editor_fields_hint"))
        hint.setWordWrap(True)
        hint.setProperty("hintText", True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        parent.addWidget(hint)

        parent.addWidget(QLabel(tr("ui.mod_name_label")))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(tr("ui.enter_mod_name"))
        self.name_edit.setToolTip(tr("tooltips.mod_editor_name"))
        parent.addWidget(self.name_edit)
        parent.addSpacing(6)

        parent.addWidget(QLabel(tr("ui.mod_author")))
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText(tr("ui.enter_author_name"))
        self.author_edit.setToolTip(tr("tooltips.mod_editor_author"))
        if not self.is_creating:
            self.author_edit.setReadOnly(True)
        parent.addWidget(self.author_edit)
        parent.addSpacing(6)

        parent.addWidget(QLabel(tr("ui.short_description")))
        self.description_edit = QLineEdit()
        self.description_edit.setMaxLength(200)
        self.description_edit.setPlaceholderText(tr("ui.short_description_placeholder"))
        self.description_edit.setToolTip(tr("tooltips.mod_editor_description"))
        parent.addWidget(self.description_edit)
        parent.addSpacing(6)

        parent.addWidget(QLabel(tr("ui.homepage")))
        self.homepage_edit = QLineEdit()
        self.homepage_edit.setPlaceholderText("https://example.com/mod-page")
        self.homepage_edit.setToolTip(tr("tooltips.mod_editor_homepage"))
        parent.addWidget(self.homepage_edit)

        parent.addWidget(QLabel(tr("files.icon_label")))
        icon_row = QHBoxLayout()
        self.icon_browse_btn = self._make_icon_text_button(
            "folder_icon.svg",
            "",
            tr("ui.mod_editor_pick_icon_tooltip"),
        )
        self.icon_browse_btn.clicked.connect(self._browse_icon)
        icon_row.addWidget(self.icon_browse_btn)
        self.icon_edit = QLineEdit()
        self.icon_edit.setPlaceholderText(tr("ui.icon_file_path_placeholder"))
        self.icon_edit.setToolTip(tr("tooltips.mod_editor_icon"))
        self.icon_edit.textChanged.connect(self._on_icon_text_changed)
        icon_row.addWidget(self.icon_edit)
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(64, 64)
        bc = self._color("border", "#039d5b")
        pr = self._br(64, 64)
        self.icon_preview.setStyleSheet(
            f"border: 2px solid {bc}; border-radius: {pr}px;"
        )
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_preview.setText(tr("ui.icon_preview"))
        icon_row.addWidget(self.icon_preview)
        parent.addLayout(icon_row)
        parent.addSpacing(6)

        parent.addWidget(QLabel(tr("ui.mod_tags_label")))
        tags_row = QHBoxLayout()
        self.tag_textedit = QCheckBox(tr("tags.textedit_text"))
        self.tag_customization = QCheckBox(tr("tags.customization"))
        self.tag_gameplay = QCheckBox(tr("tags.gameplay"))
        self.tag_other = QCheckBox(tr("tags.other"))
        for t in [
            self.tag_textedit,
            self.tag_customization,
            self.tag_gameplay,
            self.tag_other,
        ]:
            t.setToolTip(tr("tooltips.mod_editor_tags"))
            tags_row.addWidget(t)
        parent.addLayout(tags_row)
        if self.is_creating:
            self.tag_other.setChecked(True)

        parent.addSpacing(6)
        parent.addWidget(QLabel(tr("ui.overall_mod_version")))
        self.version_edit = QLineEdit()
        self.version_edit.setPlaceholderText("1.0.0")
        self.version_edit.setToolTip(tr("tooltips.mod_editor_version"))
        parent.addWidget(self.version_edit)
        parent.addSpacing(6)

        parent.addWidget(QLabel(tr("ui.game_version_label")))
        self.game_version_edit = QLineEdit()
        self.game_version_edit.setPlaceholderText("1.04")
        self.game_version_edit.setToolTip(tr("tooltips.mod_editor_game_version"))
        parent.addWidget(self.game_version_edit)

    def _build_file_section(self, parent):
        frame = QFrame()
        frame.setObjectName("modEditorFilesFrame")
        frame.setFrameStyle(QFrame.Shape.Box)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(16, 16, 16, 16)
        fl.setSpacing(12)
        fl.addWidget(self._build_section_title(tr("ui.files_management")))
        hint = QLabel(tr("ui.mod_editor_files_hint"))
        hint.setWordWrap(True)
        hint.setProperty("hintText", True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fl.addWidget(hint)
        self.file_tabs = QTabWidget()
        self.file_tabs.setStyleSheet(
            "QTabWidget::tab-bar { alignment: center; } QTabBar::tab { padding: 4px 8px; }"
        )
        fl.addWidget(self.file_tabs)
        parent.addWidget(frame)
        self._update_file_tabs()

    def _update_file_tabs(self):
        while self.file_tabs.count():
            self.file_tabs.removeTab(0)
        game = self.game_combo.currentData()
        game_def = get_game(game)
        if game_def:
            for tab in game_def.tabs:
                self._add_file_tab(tr(tab.name_key))
        else:
            self._add_file_tab(game or "Unknown")

    def _add_file_tab(self, name):
        tab = QWidget()
        root_layout = QVBoxLayout(tab)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        scroll = QScrollArea(tab)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(round(300 * self._ui_scale()))
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        data_btn = self._make_icon_text_button(
            "add_icon.svg", tr("ui.add_data_file")
        )
        data_btn.setToolTip(tr("tooltips.mod_editor_add_data"))
        data_btn.setProperty("is_data_button", True)
        data_btn.clicked.connect(lambda: self._on_add_data(tab, layout))

        extra_btn = self._make_icon_text_button(
            "add_icon.svg", tr("ui.add_extra_files")
        )
        extra_btn.setToolTip(tr("tooltips.mod_editor_add_extra"))
        extra_btn.clicked.connect(lambda: self._on_add_extra(layout))
        row_frame = QFrame()
        row_frame.setProperty("fileActionsRow", True)
        row = QHBoxLayout(row_frame)
        row.setContentsMargins(12, 10, 12, 10)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(data_btn)
        row.addWidget(extra_btn)
        layout.addWidget(row_frame)
        layout.addStretch()
        tab._file_layout = layout
        tab._data_button = data_btn
        tab._has_data_frame = False
        tab._file_scroll = scroll
        scroll.setWidget(content)
        root_layout.addWidget(scroll)
        self.file_tabs.addTab(tab, name)

    def _get_tab_file_layout(self, tab):
        layout = getattr(tab, "_file_layout", None) if tab else None
        if layout:
            return layout
        if not tab:
            return None
        for child in tab.findChildren(QScrollArea):
            widget = child.widget()
            if widget and widget.layout():
                return widget.layout()
        return tab.layout()

    def _on_add_data(self, tab, layout):
        if getattr(tab, "_has_data_frame", False):
            return
        self._create_file_frame(layout, "data")

    def _on_add_extra(self, layout):
        self._create_file_frame(layout, "extra")

    def _create_file_frame(self, tab_layout, file_type):
        tab = self._get_tab_for_layout(tab_layout)
        if file_type == "data":
            self._set_tab_has_data(tab, True)
        frame = QFrame()
        frame.setProperty("fileCard", True)
        frame.setFrameStyle(QFrame.Shape.Box)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(12, 12, 12, 12)
        fl.setSpacing(8)
        if file_type == "data":
            title_text, file_filter = (
                tr("files.data_file"),
                get_file_filter("data_files"),
            )
            browse_title = tr("ui.select_data_file", file_type="data")
        else:
            title_text = tr("ui.add_extra_files")
            file_filter = "All Files (*)"
            browse_title = tr("ui.select_file")
        title_lbl = QLabel(title_text)
        title_lbl.setStyleSheet("font-weight: bold;")
        title_lbl.setProperty("file_type", file_type)
        fl.addWidget(title_lbl)
        path_edit = QLineEdit()
        path_edit.setPlaceholderText(tr("ui.select_file"))
        path_edit.setToolTip(tr("tooltips.mod_editor_selected_file"))
        path_edit.setProperty(
            "is_local_path" if file_type == "data" else "is_local_extra_path", True
        )
        fl.addWidget(path_edit)
        browse_btn = self._make_icon_text_button(
            "folder_icon.svg",
            tr("ui.browse_button"),
            tr("ui.browse_button"),
        )
        browse_btn.clicked.connect(
            lambda: self._browse_file(path_edit, browse_title, file_filter, file_type)
        )
        del_btn = self._make_icon_text_button(
            "delete_icon.svg", tr("buttons.delete"), tr("buttons.delete")
        )
        del_btn.clicked.connect(
            lambda: self._remove_file_frame(tab_layout, frame, file_type)
        )
        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 4, 0, 0)
        actions_row.setSpacing(8)
        actions_row.addStretch()
        actions_row.addWidget(browse_btn)
        actions_row.addWidget(del_btn)
        actions_row.addStretch()
        fl.addLayout(actions_row)
        tab_layout.insertWidget(tab_layout.count() - 1, frame)

    def _make_icon_text_button(self, icon, text, tooltip=None):
        button = QPushButton(text)
        button.setIcon(self._icon(icon))
        button.setIconSize(self._icon_size(18))
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setMinimumWidth(round(112 * self._ui_scale()))
        if tooltip:
            button.setToolTip(tooltip)
        return button

    @staticmethod
    def _normalize_config_path(path: str) -> str:
        if not path:
            return path
        normalized = path.replace("\\", "/")
        if normalized.endswith("/"):
            normalized = normalized.rstrip("/")
        return normalized

    @classmethod
    def _format_config_path(cls, path: str, *, is_directory: bool | None = None) -> str:
        if not path:
            return path
        normalized = path.replace("\\", "/")
        had_trailing_slash = normalized.endswith("/")
        if is_directory is None:
            is_directory = had_trailing_slash or os.path.isdir(path)
        if is_directory:
            return normalized.rstrip("/") + "/"
        return normalized.rstrip("/")

    def _get_tab_for_layout(self, layout):
        for i in range(self.file_tabs.count()):
            tab = self.file_tabs.widget(i)
            if getattr(tab, "_file_layout", None) is layout:
                return tab
        return None

    def _set_tab_has_data(self, tab, has_data):
        if tab is None:
            return
        tab._has_data_frame = has_data
        data_button = getattr(tab, "_data_button", None)
        if isinstance(data_button, QPushButton):
            data_button.setVisible(not has_data)

    def _remove_file_frame(self, layout, frame, file_type):
        frame.hide()
        layout.removeWidget(frame)
        frame.deleteLater()
        if file_type == "data":
            self._set_tab_has_data(self._get_tab_for_layout(layout), False)

    def _browse_file(self, line_edit, title, file_filter, file_type):
        if file_type == "data":
            path, _ = QFileDialog.getOpenFileName(
                self, title, self._last_browse_dir, file_filter
            )
            if path:
                self._last_browse_dir = os.path.dirname(path)
                line_edit.setText(self._format_config_path(path))
        else:
            msg = QMessageBox(self)
            msg.setWindowTitle(tr("ui.select"))
            msg.setText(tr("ui.select_file_or_folder"))
            file_btn = msg.addButton(
                tr("ui.file"), QMessageBox.ButtonRole.AcceptRole
            )
            folder_btn = msg.addButton(
                tr("ui.folder"), QMessageBox.ButtonRole.ActionRole
            )
            msg.addButton(QMessageBox.StandardButton.Cancel)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == file_btn:
                path, _ = QFileDialog.getOpenFileName(
                    self, title, self._last_browse_dir, file_filter
                )
                if path:
                    self._last_browse_dir = os.path.dirname(path)
                    line_edit.setText(self._format_config_path(path))
            elif clicked == folder_btn:
                path = QFileDialog.getExistingDirectory(
                    self, title, self._last_browse_dir
                )
                if path:
                    self._last_browse_dir = path
                    line_edit.setText(self._format_config_path(path, is_directory=True))

    def _browse_icon(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("ui.select_icon_file"),
            self._last_browse_dir,
            get_file_filter("image_files"),
        )
        if path:
            self._last_browse_dir = os.path.dirname(path)
            self.icon_edit.setText(path)

    def _on_icon_text_changed(self, text):
        text = text.strip()
        if not text:
            self._load_default_icon()
        elif text.startswith(("http://", "https://")):
            self._load_icon_from_url(text)
        else:
            self._load_icon_preview(text)

    def _load_default_icon(self):
        try:
            logo = resource_path("assets/icons/icon.ico")
            if os.path.exists(logo):
                px = QPixmap(logo)
                if not px.isNull():
                    pr = self._br(64, 64)
                    scaled = px.scaled(
                        64,
                        64,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self.icon_preview.setPixmap(
                        round_pixmap(scaled, pr) if pr > 0 else scaled
                    )
                    return
        except Exception as e:
            logging.warning(f"Load default icon failed: {e}")
        self.icon_preview.setText(tr("ui.icon_preview"))

    def _load_icon_from_url(self, url):
        from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
        from PyQt6.QtGui import QImage

        self.icon_preview.setText(tr("ui.loading_placeholder"))

        class _Signals(QObject):
            loaded = pyqtSignal(QImage)

        signals = _Signals(self)
        signals.loaded.connect(self._apply_url_icon)

        class _IconFetch(QRunnable):
            def __init__(self, url, signals) -> None:
                super().__init__()
                self._url, self._signals = url, signals

            def run(self):
                try:
                    from utils.network_utils import get_session

                    resp = get_session().get(self._url, timeout=10)
                    resp.raise_for_status()
                    img = QImage()
                    if img.loadFromData(resp.content) and not img.isNull():
                        self._signals.loaded.emit(img)
                    else:
                        self._signals.loaded.emit(QImage())
                except Exception:
                    self._signals.loaded.emit(QImage())

        QThreadPool.globalInstance().start(_IconFetch(url, signals))

    def _set_icon_pixmap(self, px):
        """Crop to square center, scale to 64x64, apply border radius."""
        if px.isNull():
            self.icon_preview.setText(tr("status.loading_error"))
            return
        size = min(px.width(), px.height())
        cropped = px.copy(
            (px.width() - size) // 2, (px.height() - size) // 2, size, size
        )
        pr = self._br(64, 64)
        scaled = cropped.scaled(
            64,
            64,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.icon_preview.setPixmap(round_pixmap(scaled, pr) if pr > 0 else scaled)

    def _apply_url_icon(self, image):
        if image.isNull():
            self.icon_preview.setText(tr("status.loading_error"))
        else:
            self._set_icon_pixmap(QPixmap.fromImage(image))

    def _load_icon_preview(self, path):
        try:
            resolved = path
            if not os.path.isabs(path) or not os.path.exists(path):
                mod_folder = self._find_mod_folder()
                if mod_folder:
                    candidate = os.path.normpath(os.path.join(mod_folder, path))
                    if os.path.isfile(candidate):
                        resolved = candidate
            self._set_icon_pixmap(QPixmap(resolved))
        except Exception:
            self.icon_preview.setText(tr("status.loading_error"))

    def _build_action_buttons(self, parent):
        row = QHBoxLayout()
        if not self.is_creating:
            del_btn = QPushButton(tr("ui.delete_mod"))
            dr = self._br(h=max(1, del_btn.sizeHint().height()))
            tc = self._color("main_text", "#e8e9eb")
            del_btn.setStyleSheet(
                f"background-color: darkred; color: {tc}; border-radius: {dr}px;"
            )
            del_btn.setToolTip(tr("tooltips.delete_mod"))
            del_btn.clicked.connect(self._delete_mod)
            row.addWidget(del_btn)
            row.addSpacing(10)
            export_btn = QPushButton(tr("ui.export_mod"))
            export_btn.setToolTip(tr("tooltips.export_mod"))
            export_btn.clicked.connect(self._export_mod)
            row.addWidget(export_btn)
            row.addSpacing(10)
            open_folder_btn = QPushButton(tr("ui.open_mod_folder"))
            open_folder_btn.setToolTip(tr("tooltips.open_mod_folder"))
            open_folder_btn.clicked.connect(self._open_mod_folder)
            row.addWidget(open_folder_btn)
            row.addSpacing(10)
            switch_version_btn = QPushButton(tr("mod_versions.switch_version_button"))
            switch_version_btn.setToolTip(tr("tooltips.mod_versions"))
            switch_version_btn.clicked.connect(self._open_mod_versions)
            row.addWidget(switch_version_btn)
        row.addStretch()
        cancel_btn = QPushButton(tr("ui.cancel_button"))
        cancel_btn.setToolTip(tr("tooltips.cancel"))
        cancel_btn.clicked.connect(self._on_cancel)
        row.addWidget(cancel_btn)
        row.addSpacing(10)
        save_btn = QPushButton(
            tr("ui.finish_creation") if self.is_creating else tr("ui.save_changes")
        )
        save_btn.setToolTip(tr("tooltips.save_mod"))
        save_btn.clicked.connect(self._save_mod)
        row.addWidget(save_btn)
        parent.addLayout(row)

    def _on_cancel(self):
        if (
            QMessageBox.question(
                self, tr("dialogs.cancel_changes"), tr("dialogs.unsaved_changes_lost")
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.reject()

    def _validate(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, tr("errors.error"), tr("dialogs.mod_name_empty"))
            return False
        url = self.homepage_edit.text().strip()
        if url:
            from urllib.parse import urlparse

            try:
                r = urlparse(url)
                if not all([r.scheme in ["http", "https"], r.netloc]):
                    raise ValueError
                p = r.path.lower()
                if any(
                    p.endswith(ext)
                    for ext in [
                        ".zip",
                        ".g3mpatch",
                        ".rar",
                        ".7z",
                        ".exe",
                        ".xdelta",
                        ".win",
                        ".ios",
                        ".patch",
                        ".tar",
                        ".gz",
                    ]
                ):
                    QMessageBox.warning(
                        self,
                        tr("errors.error"),
                        tr("dialogs.invalid_homepage_direct_download"),
                    )
                    return False
            except Exception:
                QMessageBox.warning(
                    self, tr("errors.error"), tr("dialogs.invalid_homepage")
                )
                return False
        if len(self.name_edit.text().strip()) > MOD_FIELD_LIMITS["name"]:
            QMessageBox.warning(self, tr("errors.error"), tr("dialogs.mod_name_too_long"))
            return False
        if len(self.author_edit.text().strip()) > MOD_FIELD_LIMITS["author"]:
            QMessageBox.warning(self, tr("errors.error"), tr("dialogs.mod_author_too_long"))
            return False
        if len(self.version_edit.text().strip()) > MOD_FIELD_LIMITS["version"]:
            QMessageBox.warning(
                self, tr("errors.error"), tr("dialogs.mod_version_too_long")
            )
            return False
        if len((self.game_combo.currentData() or "").strip()) > MOD_FIELD_LIMITS["game"]:
            QMessageBox.warning(self, tr("errors.error"), tr("dialogs.mod_game_too_long"))
            return False
        if len(self.homepage_edit.text().strip()) > MOD_FIELD_LIMITS["homepage"]:
            QMessageBox.warning(self, tr("errors.error"), tr("dialogs.mod_homepage_too_long"))
            return False
        if len(self.icon_edit.text().strip()) > MOD_FIELD_LIMITS["icon"]:
            QMessageBox.warning(self, tr("errors.error"), tr("dialogs.mod_icon_too_long"))
            return False
        if len(self.game_version_edit.text().strip()) > MOD_FIELD_LIMITS["game_version"]:
            QMessageBox.warning(self, tr("errors.error"), tr("dialogs.mod_game_version_too_long"))
            return False
        if not any(
            [
                self.tag_textedit.isChecked(),
                self.tag_customization.isChecked(),
                self.tag_gameplay.isChecked(),
                self.tag_other.isChecked(),
            ]
        ):
            self.tag_other.setChecked(True)
        if self.is_creating and not self._has_any_mod_files():
            QMessageBox.warning(
                self, tr("errors.error"), tr("dialogs.mod_needs_at_least_one_file")
            )
            return False
        return self._validate_local_files()

    def _resolve_file_path(self, path):
        """Resolve a file path, trying the mod folder if it's relative or doesn't exist."""
        if not path:
            return path
        normalized = self._normalize_config_path(path)
        if os.path.exists(normalized):
            return normalized
        mod_folder = self._find_mod_folder()
        if mod_folder:
            candidate = resolve_mod_file_path(mod_folder, normalized)
            if os.path.exists(candidate):
                return candidate
            game = self.game_combo.currentData()
            for tab_idx in range(self.file_tabs.count()):
                resolved = self._resolve_path(normalized, tab_idx, mod_folder, game)
                if os.path.exists(resolved):
                    return resolved
        return normalized

    def _iter_tab_frames(self):
        """Yield (tab_index, tab_name, frame_data) for each file frame across all tabs."""
        for i in range(self.file_tabs.count()):
            tab = self.file_tabs.widget(i)
            layout = self._get_tab_file_layout(tab)
            if not tab or not layout:
                continue
            for j in range(layout.count()):
                item = layout.itemAt(j)
                w = item.widget() if item else None
                if not w or not hasattr(w, "layout") or not (fl := w.layout()):
                    continue
                data = self._extract_frame_data(fl)
                if data:
                    yield i, self.file_tabs.tabText(i), data

    def _has_any_mod_files(self):
        return any(
            d.get("path") or d.get("paths") for _, _, d in self._iter_tab_frames()
        )

    def _validate_local_files(self):
        for _, tab_name, data in self._iter_tab_frames():
            if (p := data.get("path")) and not os.path.exists(
                self._resolve_file_path(p)
            ):
                QMessageBox.warning(
                    self,
                    tr("dialogs.validation_error"),
                    tr("dialogs.tab_file_not_found", tab_name=tab_name, path=p),
                )
                return False
            for p in data.get("paths", []):
                if not os.path.exists(self._resolve_file_path(p)):
                    QMessageBox.warning(
                        self,
                        tr("dialogs.validation_error"),
                        tr(
                            "dialogs.tab_extra_file_not_found",
                            tab_name=tab_name,
                            path=p,
                        ),
                    )
                    return False
        return True

    def _collect_mod_data(self):
        tag_map = [
            ("textedit", self.tag_textedit),
            ("customization", self.tag_customization),
            ("gameplay", self.tag_gameplay),
            ("other", self.tag_other),
        ]
        tags = [name for name, cb in tag_map if cb.isChecked() and name in MOD_ALLOWED_TAGS]
        author = self.author_edit.text().strip() or tr("defaults.local_author")
        return {
            "name": self.name_edit.text().strip(),
            "version": self.version_edit.text().strip() or "1.0.0",
            "author": author,
            "description": self.description_edit.text().strip()
            or tr("defaults.no_description"),
            "homepage": self.homepage_edit.text().strip(),
            "icon": self.icon_edit.text().strip(),
            "tags": tags,
            "game": self.game_combo.currentData() or "deltarune",
            "game_version": self.game_version_edit.text().strip() or "1.04",
            "files": self._collect_files(),
        }

    def _collect_files(self):
        files = {}
        game = self.game_combo.currentData()
        game_def = get_game(game)
        tab_keys = [tab.tab_id for tab in game_def.tabs] if game_def else []
        for idx in range(self.file_tabs.count()):
            if idx >= len(tab_keys):
                break
            tab = self.file_tabs.widget(idx)
            layout = self._get_tab_file_layout(tab)
            if not tab or not layout:
                continue
            tab_files = {}
            for i in range(layout.count()):
                item = layout.itemAt(i)
                w = item.widget() if item else None
                if not w or not hasattr(w, "layout") or not (fl := w.layout()):
                    continue
                data = self._extract_frame_data(fl)
                if not data:
                    continue
                if data["type"] == "data" and data.get("path"):
                    tab_files["data_file_path"] = data["path"]
                elif data["type"] == "extra" and data.get("paths"):
                    extra_files = tab_files.setdefault("extra_files", [])
                    existing_paths = {
                        extra_file for extra_file in extra_files if isinstance(extra_file, str)
                    }
                    for path in data["paths"]:
                        if path not in existing_paths:
                            extra_files.append(path)
                            existing_paths.add(path)
            if tab_files:
                files[tab_keys[idx]] = tab_files
        return files

    def _extract_frame_data(self, fl):
        if fl.count() == 0:
            return None
        title_w = fl.itemAt(0).widget() if fl.itemAt(0) else None
        if not isinstance(title_w, QLabel):
            return None
        ftype = title_w.property("file_type")
        if ftype == "data":
            path_edit = None
            for i in range(fl.count()):
                w = fl.itemAt(i).widget() if fl.itemAt(i) else None
                if isinstance(w, QLineEdit) and w.property("is_local_path"):
                    path_edit = w
            if path_edit and path_edit.text():
                return {
                    "type": "data",
                    "path": self._format_config_path(path_edit.text()),
                }
        elif ftype == "extra":
            paths = []
            for i in range(fl.count()):
                w = fl.itemAt(i).widget() if fl.itemAt(i) else None
                if (
                    isinstance(w, QLineEdit)
                    and w.property("is_local_extra_path")
                    and w.text()
                ):
                    paths.append(self._format_config_path(w.text()))
            if paths:
                return {"type": "extra", "paths": paths}
        return None

    def _save_mod(self):
        if not self._validate():
            return
        if self.is_creating:
            self._create_local_mod()
        else:
            self._update_local_mod()

    def _process_icon(self, target_dir):
        icon_path = self.icon_edit.text().strip()
        if not icon_path:
            return None
        if icon_path.startswith(("http://", "https://")):
            return icon_path
        resolved = self._resolve_file_path(icon_path)
        if os.path.exists(resolved):
            dest = os.path.join(target_dir, os.path.basename(resolved))
            if os.path.abspath(resolved) != os.path.abspath(dest):
                shutil.copy2(resolved, dest)
            return os.path.basename(resolved)
        return None

    def _collect_managed_file_paths(self, mod_dir, files_data, game):
        managed_paths = set()
        for _file_key, file_info in (files_data or {}).items():
            data_file = file_info.get("data_file_path") or file_info.get("data_file_url")
            if isinstance(data_file, str):
                managed_path = self._resolve_managed_mod_path(mod_dir, data_file)
                if managed_path:
                    managed_paths.add(managed_path)
            for extra_file in parse_extra_files_raw(file_info.get("extra_files", [])):
                managed_path = self._resolve_managed_mod_path(mod_dir, extra_file)
                if managed_path:
                    managed_paths.add(managed_path)
        return managed_paths

    @staticmethod
    def _resolve_managed_mod_path(file_folder, stored_path) -> str | None:
        if not isinstance(stored_path, str):
            return None
        cleaned_path = stored_path.strip().replace("\\", "/").rstrip("/")
        if not cleaned_path or os.path.isabs(cleaned_path):
            return None
        candidate = resolve_mod_file_path(file_folder, cleaned_path)
        try:
            if os.path.commonpath([os.path.abspath(file_folder), os.path.abspath(candidate)]) != os.path.abspath(file_folder):
                return None
        except ValueError:
            return None
        return candidate

    def _remove_stale_managed_files(self, mod_dir, old_files, new_files, game):
        previous_paths = self._collect_managed_file_paths(mod_dir, old_files, game)
        current_paths = self._collect_managed_file_paths(mod_dir, new_files, game)
        stale_paths = sorted(previous_paths - current_paths, key=len, reverse=True)
        for stale_path in stale_paths:
            if os.path.isdir(stale_path):
                shutil.rmtree(stale_path, ignore_errors=True)
            elif os.path.isfile(stale_path):
                with suppress(FileNotFoundError):
                    os.remove(stale_path)
            parent_dir = os.path.dirname(stale_path)
            while parent_dir and os.path.abspath(parent_dir) != os.path.abspath(mod_dir):
                try:
                    os.rmdir(parent_dir)
                except OSError:
                    break
                parent_dir = os.path.dirname(parent_dir)

    def _copy_files_to_mod_dir(self, mod_dir, files_data, game):
        processed = {}
        for file_key, fd in files_data.items():
            new_fd = {}
            data_path = fd.get("data_file_path") or fd.get("data_file_url")
            if data_path:
                resolved = self._resolve_file_path(data_path)
                if os.path.exists(resolved):
                    dest = os.path.join(mod_dir, os.path.basename(resolved))
                    if os.path.abspath(resolved) != os.path.abspath(dest):
                        if os.path.exists(dest):
                            if os.path.isdir(dest):
                                shutil.rmtree(dest)
                            else:
                                os.remove(dest)
                        if os.path.isdir(resolved):
                            shutil.copytree(resolved, dest)
                        else:
                            shutil.copy2(resolved, dest)
                    new_fd["data_file_path"] = self._format_config_path(
                        os.path.basename(resolved), is_directory=os.path.isdir(resolved)
                    )
            for path in parse_extra_files_raw(fd.get("extra_files", [])):
                if not path:
                    continue
                resolved = self._resolve_file_path(path)
                if not os.path.exists(resolved):
                    continue
                dest = os.path.join(mod_dir, os.path.basename(resolved))
                if os.path.abspath(resolved) != os.path.abspath(dest):
                    if os.path.exists(dest):
                        if os.path.isdir(dest):
                            shutil.rmtree(dest)
                        else:
                            os.remove(dest)
                    if os.path.isdir(resolved):
                        shutil.copytree(resolved, dest)
                    else:
                        shutil.copy2(resolved, dest)
                new_fd.setdefault("extra_files", []).append(
                    self._format_config_path(
                        os.path.basename(resolved),
                        is_directory=os.path.isdir(resolved),
                    )
                )
            if new_fd:
                processed[file_key] = new_fd
        return processed

    def _refresh_after_save(self):
        self.parent_app.mod_service.invalidate_mods_cache()
        self.parent_app.mod_service.load_local_mods()
        self.parent_app.mod_service.mod_list_updated.emit()
        if hasattr(self.parent_app, "library_display"):
            self.parent_app.library_display.update_display()

    def _create_local_mod(self):
        data = self._collect_mod_data()
        mod_id = f"local_{uuid.uuid4().hex[:12]}"
        folder = get_unique_mod_dir(self.parent_app.app_state.mods_dir, data["name"])
        mod_dir = os.path.join(self.parent_app.app_state.mods_dir, folder)
        try:
            os.makedirs(mod_dir)
            icon_val = self._process_icon(mod_dir)
            processed_files = self._copy_files_to_mod_dir(
                mod_dir, data.get("files", {}), data["game"]
            )
            config = {
                    "id": mod_id,
                    "version": data["version"],
                    "name": data["name"],
                    "description": data["description"],
                    "author": data["author"],
                    "homepage": data["homepage"],
                    "game": data["game"],
                    "game_version": data["game_version"],
                    "files": processed_files,
                    "tags": data["tags"],
                }
            if icon_val:
                config["icon"] = icon_val
            self.parent_app.settings_service.write_json(
                os.path.join(mod_dir, "mod_config.json"),
                build_mod_config_data(config),
            )
            self._refresh_after_save()
            QMessageBox.information(
                self,
                tr("dialogs.local_mod_created_title"),
                tr("dialogs.local_mod_created_message", mod_name=data["name"]),
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("errors.mod_creation_error"),
                tr("errors.mod_creation_failed", error=str(e)),
            )
            if os.path.exists(mod_dir):
                shutil.rmtree(mod_dir)

    def _find_mod_folder(self):
        if "folder_path" in self.mod_data and os.path.exists(
            self.mod_data["folder_path"]
        ):
            return self.mod_data["folder_path"]
        if self.mod_id and hasattr(self.parent_app, "mod_service"):
            p = self.parent_app.mod_service.get_mod_folder_path(self.mod_id)
            if p and os.path.exists(p):
                return p
        if "folder_name" in self.mod_data:
            p = os.path.join(
                self.parent_app.app_state.mods_dir, self.mod_data["folder_name"]
            )
            if os.path.exists(p):
                return p
        return None

    def _update_local_mod(self):
        data = self._collect_mod_data()
        if not self.mod_id:
            QMessageBox.critical(
                self, tr("errors.error"), tr("errors.id_not_found_update")
            )
            return
        mod_folder = self._find_mod_folder()
        if not mod_folder:
            QMessageBox.critical(
                self, tr("errors.error"), tr("errors.mod_folder_not_found_update")
            )
            return
        try:
            config_path = os.path.join(mod_folder, "mod_config.json")
            config = self.parent_app.settings_service.read_json(config_path)
            normalize_mod_config_data(config)
            icon_val = self._process_icon(mod_folder)
            processed_files = self._copy_files_to_mod_dir(
                mod_folder, data.get("files", {}), data["game"]
            )
            self._remove_stale_managed_files(
                mod_folder,
                config.get("files", {}),
                processed_files,
                data["game"],
            )
            config.update(
                {
                    "id": self.mod_id,
                    "version": data["version"],
                    "name": data["name"],
                    "description": data["description"],
                    "author": data["author"],
                    "homepage": data["homepage"],
                    "game": data["game"],
                    "game_version": data["game_version"],
                    "tags": data["tags"],
                    "files": processed_files,
                }
            )
            if icon_val:
                config["icon"] = icon_val
            self.parent_app.settings_service.write_json(config_path, config)
            self._refresh_after_save()
            QMessageBox.information(
                self,
                tr("dialogs.local_mod_updated_title"),
                tr("dialogs.local_mod_updated_message", mod_name=data["name"]),
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("errors.update_error"),
                tr("errors.local_mod_update_failed", error=str(e)),
            )

    def _delete_mod(self):
        if (
            QMessageBox.question(
                self,
                tr("dialogs.are_you_sure"),
                tr("dialogs.local_mod_deletion_confirmation"),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        if not self.mod_id:
            QMessageBox.critical(
                self, tr("errors.error"), tr("errors.id_not_found_for_deletion")
            )
            return
        mod_folder = self._find_mod_folder()
        if not mod_folder:
            QMessageBox.critical(
                self, tr("errors.error"), tr("errors.mod_folder_not_found_for_deletion")
            )
            return
        try:
            shutil.rmtree(mod_folder)
            self._refresh_after_save()
            self.accept()
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("errors.deletion_error"),
                tr("errors.local_mod_deletion_failed", error=str(e)),
            )

    def _export_mod(self):
        if not self.mod_id:
            return
        mod_folder = self._find_mod_folder()
        if not mod_folder or not os.path.exists(mod_folder):
            QMessageBox.critical(
                self,
                tr("errors.error"),
                tr("errors.mod_folder_not_found_simple", path=mod_folder or ""),
            )
            return
        mod_name = self.name_edit.text().strip() or "mod"
        export_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("ui.select_export_location"),
            f"{mod_name}.zip",
            "ZIP Archives (*.zip);;All Files (*)",
        )
        if not export_path:
            return
        try:
            import zipfile

            with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _dirs, files in os.walk(mod_folder):
                    for f in files:
                        fp = os.path.join(root, f)
                        zf.write(fp, os.path.relpath(fp, mod_folder))
            QMessageBox.information(
                self, tr("dialogs.success"), tr("status.mod_exported_success")
            )
        except Exception as e:
            QMessageBox.critical(
                self, tr("errors.error"), tr("errors.mod_export_failed", error=str(e))
            )

    def _open_mod_folder(self):
        mod_folder = self._find_mod_folder()
        if mod_folder and os.path.exists(mod_folder):
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(mod_folder))
        else:
            QMessageBox.warning(
                self,
                tr("errors.error"),
                tr("errors.mod_folder_not_found_simple", path=mod_folder or ""),
            )

    def _open_mod_versions(self):
        mod_folder = self._find_mod_folder()
        if not mod_folder or not os.path.exists(mod_folder):
            QMessageBox.warning(
                self,
                tr("errors.error"),
                tr("errors.mod_folder_not_found_simple", path=mod_folder or ""),
            )
            return
        from ui.dialogs.mod_versions_dialog import ModVersionsDialog

        app_state = getattr(self.parent_app, "app_state", None)
        if not app_state:
            logging.warning(
                "ModEditorDialog: Cannot open mod versions - app_state not available"
            )
            return
        dialog = ModVersionsDialog(mod_folder, self.mod_data, app_state, self)
        dialog.exec()

    def _populate_fields(self):
        d = self.mod_data
        if "mod_data" in d:
            d = d["mod_data"]
        self.name_edit.setText(d.get("name", ""))
        self.author_edit.setText(d.get("author", ""))
        self.description_edit.setText(d.get("description", ""))
        self.homepage_edit.setText(d.get("homepage", ""))
        icon_val = d.get("icon", "")
        mod_folder = self._find_mod_folder()
        if (
            not (icon_val and icon_val.startswith(("http://", "https://")))
            and mod_folder
        ):
            config_icon = d.get("icon")
            if config_icon and isinstance(config_icon, str) and config_icon.strip():
                config_icon = config_icon.strip()
                if config_icon.startswith(("http://", "https://")):
                    icon_val = config_icon
                else:
                    ip = os.path.normpath(os.path.join(mod_folder, config_icon))
                    if os.path.isfile(ip):
                        icon_val = config_icon
            if not icon_val:
                for ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico"]:
                    ip = os.path.join(mod_folder, f"_icon{ext}")
                    if os.path.exists(ip):
                        icon_val = os.path.relpath(ip, mod_folder)
                        break
        self.icon_edit.setText(icon_val)
        version = d.get("version", "")
        if isinstance(version, str) and "|" in version:
            version = version.split("|")[0]
        self.version_edit.setText(version)
        game = d.get("game", "deltarune")
        if game not in self._visible_game_ids:
            game_def = get_game(game)
            if game_def:
                self.game_combo.addItem(game_def.display_name, game)
        for i in range(self.game_combo.count()):
            if self.game_combo.itemData(i) == game:
                self.game_combo.setCurrentIndex(i)
                break
        tags = d.get("tags", [])
        self.tag_textedit.setChecked("textedit" in tags)
        self.tag_customization.setChecked("customization" in tags)
        self.tag_gameplay.setChecked("gameplay" in tags)
        self.tag_other.setChecked("other" in tags)
        self.game_version_edit.setText(d.get("game_version", ""))
        files_data = d.get("files", {})
        if files_data:
            self._populate_file_tabs(files_data, game)

    def _populate_file_tabs(self, files_data, game):
        game_def = get_game(game)
        if not game_def:
            logging.warning(
                "Unknown game '%s' in _populate_file_tabs, using first tab", game
            )
            fi = next(iter(files_data.values()), None)
            if fi and self.file_tabs.count():
                tab = self.file_tabs.widget(0)
                layout = getattr(tab, "_file_layout", None) if tab else None
                data_path = fi.get("data_file_path") or fi.get("data_file_url")
                if tab and layout and data_path:
                    self._create_file_frame(layout, "data")
                    self._fill_data_in_tab(layout, data_path)
            return
        for ti, tab_def in enumerate(game_def.tabs):
            fi = files_data.get(tab_def.files_key) or files_data.get(tab_def.tab_id)
            if fi and ti < self.file_tabs.count():
                tab = self.file_tabs.widget(ti)
                layout = getattr(tab, "_file_layout", None) if tab else None
                if not tab or not layout:
                    continue
                data_path = fi.get("data_file_path") or fi.get("data_file_url")
                if data_path:
                    self._create_file_frame(layout, "data")
                    self._fill_data_in_tab(layout, data_path)
                for extra_file in parse_extra_files_raw(fi.get("extra_files", [])):
                    self._create_file_frame(layout, "extra")
                    self._fill_extra_in_tab(layout, extra_file)

    def _resolve_path(self, file_path, tab_idx, mod_folder, game=None):
        if not file_path:
            return file_path
        if os.path.isabs(file_path) and os.path.exists(file_path):
            return file_path
        if not mod_folder:
            return file_path
        _game = game or self.game_combo.currentData()
        resolved = resolve_mod_file_path(mod_folder, file_path)
        return resolved if os.path.exists(resolved) else file_path

    def _fill_data_in_tab(self, layout, path):
        for i in range(layout.count() - 1, -1, -1):
            w = layout.itemAt(i).widget() if layout.itemAt(i) else None
            if not w or not hasattr(w, "layout") or not (fl := w.layout()):
                continue
            title = fl.itemAt(0).widget() if fl.count() > 0 and fl.itemAt(0) else None
            if not isinstance(title, QLabel) or title.property("file_type") != "data":
                continue
            for j in range(fl.count()):
                sub = fl.itemAt(j).widget() if fl.itemAt(j) else None
                if isinstance(sub, QLineEdit) and sub.property("is_local_path"):
                    sub.setText(path)
            return

    def _fill_extra_in_tab(self, layout, filename):
        for i in range(layout.count() - 1, -1, -1):
            w = layout.itemAt(i).widget() if layout.itemAt(i) else None
            if not w or not hasattr(w, "layout") or not (fl := w.layout()):
                continue
            title = fl.itemAt(0).widget() if fl.count() > 0 and fl.itemAt(0) else None
            if not isinstance(title, QLabel) or title.property("file_type") != "extra":
                continue
            for j in range(fl.count()):
                sub = fl.itemAt(j).widget() if fl.itemAt(j) else None
                if (
                    isinstance(sub, QLineEdit)
                    and sub.property("is_local_extra_path")
                    and not sub.text()
                ):
                    sub.setText(filename)
                    return

    def relocalize_ui(self):
        self.setWindowTitle(
            tr("ui.create_mod") if self.is_creating else tr("ui.edit_mod")
        )
