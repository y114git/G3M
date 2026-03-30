import logging
import os

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from presentation.drag_drop import LazyFileExportMimeData
from services.localization_service import tr
from ui.common.styling import (
    apply_stylesheet_if_changed,
    build_button_style,
    get_border_radius,
    get_card_button_metrics,
    get_theme_color,
)
from ui.utils.ui_utils import UIAnimator
from utils.mod_utils import get_mod_id
from utils.path_utils import colored_icon, resource_path

from .base_mod_widget import BaseModWidget


class InstalledModWidget(BaseModWidget):
    details_requested = pyqtSignal(object)
    use_requested = pyqtSignal(object)
    _gb_status_pixmaps = {}
    _checkmark_icons = {}

    def _should_run_entry_animation(self) -> bool:
        parent_app = getattr(self, "parent_app", None)
        if not parent_app:
            return True
        if getattr(parent_app, "_library_batch_render_in_progress", False):
            return False
        main_tab_widget = getattr(parent_app, "main_tab_widget", None)
        library_tab = getattr(parent_app, "library_tab", None)
        if not main_tab_widget or library_tab is None:
            return True
        try:
            return main_tab_widget.currentWidget() is library_tab
        except Exception:
            return True

    def __init__(
        self, mod_data, parent=None, parent_app=None
    ) -> None:
        super().__init__(mod_data, parent)
        if parent_app:
            self.parent_app = parent_app
        self.hide()
        self._drag_start_pos = None
        self._drag_in_progress = False
        self._is_broken_cache = None
        self.use_button = None
        self.is_active = False
        self.status = "ready"
        self.frame_selector = "installedMod"
        self.setObjectName("installedMod")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedHeight(self._card_height())
        self._init_ui()
        self._update_button_from_status()

        if self._should_run_entry_animation():
            UIAnimator.fade_in(
                self,
                200,
                getattr(self.parent_app, "app_state", None)
                if self.parent_app
                else None,
            )

    def _init_ui(self):
        super()._init_ui()
        if hasattr(self, "category_container") and self.category_container:
            self.category_container.setParent(None)
            self.category_container.deleteLater()
            self.category_container = None
        self.title_layout.takeAt(self.title_layout.count() - 1)
        self.status_indicator = QLabel("●", self)
        self.status_indicator.setFixedSize(16, 16)
        self.status_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_indicator()
        self.title_layout.addWidget(self.status_indicator)
        self.title_layout.addStretch()
        game_version_text = getattr(self.mod_data, "game_version", None) or tr(
            "defaults.not_specified"
        )
        game_version_container = QWidget(self)
        game_version_container_layout = QHBoxLayout(game_version_container)
        game_version_container_layout.setContentsMargins(0, 0, 0, 0)
        game_version_container_layout.setSpacing(0)
        self.game_version_label_title = QLabel(
            tr("ui.game_version_label"), game_version_container
        )
        self.game_version_label_title.setObjectName("primaryText")
        game_version_label_value = QLabel(
            f" {game_version_text}", game_version_container
        )
        game_version_label_value.setObjectName("secondaryText")
        game_version_container_layout.addWidget(self.game_version_label_title)
        game_version_container_layout.addWidget(game_version_label_value)
        containers = [
            self.author_container,
            game_version_container,
        ]
        for i, container in enumerate(containers):
            self.metadata_layout.addWidget(container)
            if i < len(containers) - 1:
                separator = QLabel("|", self)
                separator.setObjectName("secondaryText")
                self.metadata_layout.addWidget(separator)
        self.metadata_layout.addStretch()
        self.checkmark_button = QPushButton(self)
        self.checkmark_button.setObjectName("checkmarkButton")
        self.checkmark_button.setFixedSize(40, 40)
        apply_stylesheet_if_changed(
            self.checkmark_button,
            "QPushButton { background: transparent; border: none; }",
            cache_attr="_checkmark_button_stylesheet_cache",
        )
        self.checkmark_button.setVisible(False)
        config = self._resolve_theme_config()
        checkmark_color = get_theme_color(config, "main_text") if config else "#039d5b"
        self.checkmark_button.setIcon(
            self._checkmark_icons.setdefault(
                (24, checkmark_color), colored_icon("checkmark", checkmark_color)
            )
        )
        self.checkmark_button.setIconSize(QSize(24, 24))
        self.checkmark_button.setEnabled(False)
        self.main_layout.addWidget(self.checkmark_button)
        self.actions_widget = QWidget(self)
        actions_layout = QVBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(5)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.use_button = QPushButton(tr("ui.use_button"), self.actions_widget)
        self.use_button.setObjectName("cardButtonInstall")
        self.use_button.clicked.connect(lambda: self.use_requested.emit(self.mod_data))
        actions_layout.addWidget(self.use_button)
        self.actions_widget.setVisible(False)
        self.main_layout.addWidget(self.actions_widget)
        self._update_style()

    def _apply_metrics(self):
        super()._apply_metrics()
        scale = self._layout_scale()
        indicator_size = max(14, round(16 * scale))
        if hasattr(self, "status_indicator") and self.status_indicator:
            self.status_indicator.setFixedSize(indicator_size, indicator_size)
        if hasattr(self, "checkmark_button") and self.checkmark_button:
            self.checkmark_button.setFixedWidth(max(32, round(40 * scale)))
        if (
            hasattr(self, "actions_widget")
            and self.actions_widget
            and self.actions_widget.layout()
        ):
            self.actions_widget.layout().setSpacing(max(4, round(5 * scale)))

    def _update_style(self):
        super()._update_style()
        config = self._resolve_theme_config()
        if config:
            text_color = get_theme_color(config, "main_text")
            label = getattr(self, "game_version_label_title", None)
            if label:
                apply_stylesheet_if_changed(
                    label,
                    f"color: {text_color};",
                    cache_attr="_game_version_label_title_stylesheet_cache",
                )
            if hasattr(self, "checkmark_button") and self.checkmark_button:
                icon_size = max(18, round(24 * self._layout_scale()))
                checkmark_color = get_theme_color(config, "main_text")
                self.checkmark_button.setIcon(
                    self._checkmark_icons.setdefault(
                        (icon_size, checkmark_color), colored_icon("checkmark", checkmark_color)
                    )
                )
                self.checkmark_button.setIconSize(QSize(icon_size, icon_size))
        self._update_button_from_status()

    def _update_indicator(self):
        font_size = max(12, round(14 * self._layout_scale()))
        margin_left = max(4, round(5 * self._layout_scale()))
        style = f"font-size: {font_size}px; font-weight: bold; margin-left: {margin_left}px;"

        if self._is_mod_broken():
            apply_stylesheet_if_changed(
                self.status_indicator,
                f"color: #F44336; {style}",
                cache_attr="_status_indicator_stylesheet_cache",
            )
            self.status_indicator.setToolTip(tr("tooltips.mod_broken"))

        if self._is_gamebanana_linked():
            gb_icon_path = resource_path("assets/icons/gbicon.png")
            if os.path.exists(gb_icon_path):
                icon_size = max(12, round(14 * self._layout_scale()))
                pixmap = self._gb_status_pixmaps.get(icon_size)
                if pixmap is None:
                    pixmap = QPixmap(gb_icon_path).scaled(
                        icon_size,
                        icon_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self._gb_status_pixmaps[icon_size] = pixmap
                self.status_indicator.setPixmap(pixmap)
                self.status_indicator.setText("")
            else:
                apply_stylesheet_if_changed(
                    self.status_indicator,
                    f"color: #FFD700; {style}",
                    cache_attr="_status_indicator_stylesheet_cache",
                )
            self.status_indicator.setToolTip(tr("tooltips.gamebanana_linked"))
            return

        apply_stylesheet_if_changed(
            self.status_indicator,
            f"color: #4CAF50; {style}",
            cache_attr="_status_indicator_stylesheet_cache",
        )
        self.status_indicator.setToolTip(tr("tooltips.mod_valid"))

    def _is_mod_broken(self) -> bool:
        if self._is_broken_cache is not None:
            return self._is_broken_cache
        try:
            if not self.mod_data:
                self._is_broken_cache = True
                return True
            key = get_mod_id(self.mod_data)
            if not key:
                self._is_broken_cache = True
                return True
            if not self.parent_app or not hasattr(self.parent_app, "mod_service"):
                self._is_broken_cache = False
                return False
            mod_folder = self.parent_app.mod_service.get_mod_folder_path(key)
            if not mod_folder or not os.path.exists(mod_folder):
                self._is_broken_cache = True
                return True
            files = getattr(self.mod_data, "files", None)
            if not files or not isinstance(files, dict):
                self._is_broken_cache = True
                return True
            from utils.mod_config_parser import resolve_mod_file_path

            for chapter_data in files.values():
                if chapter_data is None:
                    continue
                if isinstance(chapter_data, dict):
                    data_file = chapter_data.get("data_file_path") or chapter_data.get(
                        "data_file_url"
                    )
                else:
                    data_file = getattr(chapter_data, "data_file_path", None)
                if not data_file:
                    continue
                data_file_path = resolve_mod_file_path(mod_folder, data_file)
                if not os.path.exists(data_file_path):
                    self._is_broken_cache = True
                    return True
            self._is_broken_cache = False
            return False
        except Exception:
            self._is_broken_cache = True
            return True

    def _is_gamebanana_linked(self) -> bool:
        key = get_mod_id(self.mod_data)
        if not key:
            return False
        return isinstance(key, str) and key.startswith("gb_")

    def _update_button_from_status(self):
        if not self.use_button:
            return
        config = self._resolve_theme_config()
        border = get_theme_color(config, "border") if config else "#039d5b"
        br = get_border_radius(config) if config else 4
        button_width, button_height, button_font_size = get_card_button_metrics(config) if config else (80, 28, 12)
        if self.status == "active":
            self.use_button.setText(tr("ui.remove_button"))
            apply_stylesheet_if_changed(
                self.use_button,
                build_button_style(
                    "cardButtonInstall",
                    "#FF9800",
                    "#F57C00",
                    "#e8e9eb",
                    border,
                    width=button_width,
                    height=button_height,
                    font_size=button_font_size,
                    border_radius=br,
                ),
                cache_attr="_use_button_stylesheet_cache",
            )
        else:
            self.use_button.setText(tr("ui.use_button"))
            apply_stylesheet_if_changed(
                self.use_button,
                build_button_style(
                    "cardButtonInstall",
                    "#4CAF50",
                    "#5cb85c",
                    "#e8e9eb",
                    border,
                    width=button_width,
                    height=button_height,
                    font_size=button_font_size,
                    border_radius=br,
                ),
                cache_attr="_use_button_stylesheet_cache",
            )

    def _sync_status(self):
        self.status = "active" if self.is_active else "ready"
        self._update_button_from_status()
        self._update_actions_visibility()

    def set_active(self, active):
        if self.is_active == active:
            return
        self.is_active = active
        self._sync_status()

    def _update_actions_visibility(self):
        if not hasattr(self, "actions_widget") or not hasattr(self, "checkmark_button"):
            return
        if self.is_selected:
            self.actions_widget.setVisible(True)
            self.checkmark_button.setVisible(False)
        elif self.is_active:
            self.actions_widget.setVisible(False)
            self.checkmark_button.setVisible(True)
        else:
            self.actions_widget.setVisible(False)
            self.checkmark_button.setVisible(False)

    def set_selected(self, selected):
        super().set_selected(selected)
        self._update_actions_visibility()

    def update_labels_text(self):
        super().update_labels_text()
        if hasattr(self, "use_button") and self.use_button:
            self._update_button_from_status()

    def update_status(self):
        self._sync_status()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._drag_in_progress:
            return
        if not hasattr(self, "_drag_start_pos") or self._drag_start_pos is None:
            return
        if (event.pos() - self._drag_start_pos).manhattanLength() < 30:
            return
        self._start_drag_export()

    def _start_drag_export(self):
        try:
            controller = getattr(self.parent_app, "mod_import_export_controller", None)
            if not controller:
                return
            self._drag_in_progress = True
            self._drag_start_pos = None
            drag = QDrag(self)
            mod_name = getattr(self.mod_data, "name", "mod") or "mod"
            mime = LazyFileExportMimeData(
                lambda path: controller.export_mod_to_path(self.mod_data, path),
                f"{mod_name}.zip",
                internal_format="application/x-g3m-installed-mod-export",
            )
            drag.setMimeData(mime)
            try:
                drag.exec(Qt.DropAction.CopyAction)
            finally:
                self._drag_in_progress = False
                mime.cleanup_later()
        except Exception as e:
            self._drag_in_progress = False
            logging.warning(
                f"InstalledModWidget: drag export failed: {e}", exc_info=True
            )

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.details_requested.emit(self.mod_data)
            return
        super().mouseDoubleClickEvent(event)
