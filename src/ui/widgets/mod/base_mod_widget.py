"""Base widget helpers shared by mod card widgets."""

import contextlib
import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from services.localization_service import tr
from ui.common.styling import (
    apply_stylesheet_if_changed,
    get_border_radius,
    get_card_layout_scale,
    get_theme_color,
    get_widget_dimensions,
    load_mod_icon_universal,
    update_mod_widget_style,
)
from utils.mod.utils import get_mod_id


class BaseModWidget(QFrame):
    clicked = pyqtSignal(object)

    def __init__(self, mod_data, parent=None) -> None:
        super().__init__(parent)
        self.mod_data = mod_data
        self.is_selected = False
        self.parent_app = parent
        self.frame_selector = ""
        self._metrics_cache_key = None
        self._last_icon_render_key = None
        self._icon_label_stylesheet_cache = None
        self._name_label_stylesheet_cache = None
        self._version_label_stylesheet_cache = None
        self._author_label_stylesheet_cache = None
        self._category_label_stylesheet_cache = None

    def _layout_scale(self) -> float:
        return get_card_layout_scale(self._resolve_theme_config())

    def _icon_size(self) -> int:
        return max(64, round(80 * self._layout_scale()))

    def _card_height(self) -> int:
        return max(120, round(120 * self._layout_scale()))

    def _title_font_size(self) -> int:
        return max(14, round(16 * self._layout_scale()))

    def _apply_metrics(self):
        scale = self._layout_scale()
        margin = max(8, round(10 * scale))
        spacing = max(10, round(15 * scale))
        title_spacing = max(6, round(8 * scale))
        metadata_spacing = max(8, round(10 * scale))
        icon_size = (
            self._icon_size()
            if hasattr(self, "icon_label") and self.icon_label
            else None
        )
        card_height = (
            self._card_height()
            if getattr(self, "frame_selector", "") in ("modCard", "installedMod")
            else None
        )
        metrics_key = (
            margin,
            spacing,
            title_spacing,
            metadata_spacing,
            icon_size,
            card_height,
        )
        if getattr(self, "_metrics_cache_key", None) == metrics_key:
            return False
        if hasattr(self, "main_layout") and self.main_layout:
            self.main_layout.setContentsMargins(margin, margin, margin, margin)
            self.main_layout.setSpacing(spacing)
        if hasattr(self, "title_layout") and self.title_layout:
            self.title_layout.setSpacing(title_spacing)
        if hasattr(self, "metadata_layout") and self.metadata_layout:
            self.metadata_layout.setSpacing(metadata_spacing)
        if hasattr(self, "icon_label") and self.icon_label:
            self.icon_label.setFixedSize(icon_size, icon_size)
        if getattr(self, "frame_selector", "") in ("modCard", "installedMod"):
            self.setFixedHeight(card_height)
        self._metrics_cache_key = metrics_key
        return True

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)
        self.icon_label = QLabel(self)
        self.icon_label.setObjectName("modIcon")
        self.icon_label.setFixedSize(80, 80)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_icon()
        main_layout.addWidget(self.icon_label)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        title_layout = QHBoxLayout()
        self.name_label = QLabel(self.mod_data.name, self)
        self.name_label.setObjectName("primaryText")
        self.name_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        title_layout.addWidget(self.name_label)
        mod_version = self.mod_data.version
        if mod_version and "|" in mod_version:
            mod_version = mod_version.split("|", 1)[0]
        version_text = mod_version or "N/A"
        version_label = QLabel(f"({version_text})", self)
        version_label.setObjectName("versionLabel")
        version_label.setStyleSheet("font-size: 16px;")
        title_layout.addWidget(version_label)
        title_layout.addStretch()
        self.title_layout = title_layout
        self.version_label = version_label
        info_layout.addLayout(title_layout)
        metadata_layout = QHBoxLayout()
        metadata_layout.setSpacing(10)
        author_text = self.mod_data.author or tr("defaults.unknown")
        author_container = QWidget(self)
        author_container_layout = QHBoxLayout(author_container)
        author_container_layout.setContentsMargins(0, 0, 0, 0)
        author_container_layout.setSpacing(0)
        self.author_label_title = QLabel(tr("ui.author_label"), author_container)
        self.author_label_title.setObjectName("primaryText")
        author_label_value = QLabel(f" {author_text}", author_container)
        author_label_value.setObjectName("secondaryText")
        author_container_layout.addWidget(self.author_label_title)
        author_container_layout.addWidget(author_label_value)
        category_text = getattr(self.mod_data, "gamebanana_category", None) or "N/A"
        category_container = QWidget(self)
        category_container_layout = QHBoxLayout(category_container)
        category_container_layout.setContentsMargins(0, 0, 0, 0)
        category_container_layout.setSpacing(0)
        self.category_label_title = QLabel(tr("ui.category_label"), category_container)
        self.category_label_title.setObjectName("primaryText")
        category_label_value = QLabel(f" {category_text}", category_container)
        category_label_value.setObjectName("secondaryText")
        category_container_layout.addWidget(self.category_label_title)
        category_container_layout.addWidget(category_label_value)
        self.author_container = author_container
        self.category_container = category_container
        self.metadata_layout = metadata_layout
        info_layout.addLayout(metadata_layout)
        description_text = self.mod_data.description or tr("ui.no_description")
        try:
            mod_id = get_mod_id(self.mod_data)
            if mod_id and mod_id.startswith("gb_"):
                has_full = getattr(self.mod_data, "has_full_metadata", True)
                if not has_full:
                    placeholder = tr("ui.loading_placeholder")
                    description_text = placeholder
        except Exception as e:
            logging.debug(
                f"BaseModWidget: failed to resolve description placeholder state: {e}",
                exc_info=True,
            )
        if len(description_text) > 200:
            description_text = description_text[:197] + "..."
        self.description_label = QLabel(description_text, self)
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName("secondaryText")
        info_layout.addWidget(self.description_label)
        self._create_tags_layout_if_needed(info_layout)
        info_layout.addStretch()
        main_layout.addLayout(info_layout, 1)
        self.main_layout = main_layout

    def _create_tags_layout_if_needed(self, info_layout):
        pass

    def _resolve_local_icon_fallback(self):
        key = get_mod_id(self.mod_data)
        if not key or not key.startswith("gb_"):
            return None
        app = self.parent_app
        if not app or not hasattr(app, "mod_service"):
            return None
        try:
            folder = app.mod_service.get_mod_folder_path(key)
            if not folder:
                return None
            config = app.mod_service.get_mod_config(key)
            if not config:
                return None
            from utils.mod.utils import resolve_mod_icon

            return resolve_mod_icon(config, folder)
        except Exception:
            return None

    def _load_icon(self):
        config = self._resolve_theme_config()
        br = get_border_radius(config)
        bc = get_theme_color(config, "border") if config else None
        bw = 2 if bc else 0
        local_fallback = self._resolve_local_icon_fallback()
        icon_width, icon_height = get_widget_dimensions(
            getattr(self, "icon_label", None)
        )
        icon_key = (
            get_mod_id(self.mod_data),
            getattr(self.mod_data, "icon", None),
            getattr(self.mod_data, "icon_path", None),
            icon_width or self._icon_size(),
            icon_height or self._icon_size(),
            local_fallback,
            br,
            bw,
            bc,
        )
        if getattr(self, "_last_icon_render_key", None) == icon_key:
            return
        apply_stylesheet_if_changed(
            self.icon_label,
            "border: none; background: transparent;",
            cache_attr="_icon_label_stylesheet_cache",
        )
        load_mod_icon_universal(
            self.icon_label,
            self.mod_data,
            (icon_width or self._icon_size(), icon_height or self._icon_size()),
            local_fallback=local_fallback,
            border_radius=br,
            border_width=bw,
            border_color=bc,
        )
        self._last_icon_render_key = icon_key

    def _resolve_theme_config(self):
        if self.parent_app:
            if hasattr(self.parent_app, "local_config"):
                return self.parent_app.local_config
            if hasattr(self.parent_app, "app_state") and hasattr(
                self.parent_app.app_state, "local_config"
            ):
                return self.parent_app.app_state.local_config
        return None

    def _update_style(self):
        self._apply_metrics()
        if self.frame_selector:
            update_mod_widget_style(self, self.frame_selector, self.parent_app)
        if hasattr(self, "icon_label"):
            self._load_icon()
        config = self._resolve_theme_config()
        if config:
            text_color = get_theme_color(config, "main_text")
            secondary_text_color = get_theme_color(config, "secondary_text")
            title_font_size = self._title_font_size()
            if hasattr(self, "name_label") and self.name_label:
                with contextlib.suppress(RuntimeError):
                    apply_stylesheet_if_changed(
                        self.name_label,
                        f"font-size: {title_font_size}px; font-weight: bold; color: {text_color};",
                        cache_attr="_name_label_stylesheet_cache",
                    )
            if hasattr(self, "version_label") and self.version_label:
                with contextlib.suppress(RuntimeError):
                    apply_stylesheet_if_changed(
                        self.version_label,
                        f"font-size: {title_font_size}px; color: {secondary_text_color};",
                        cache_attr="_version_label_stylesheet_cache",
                    )
            if hasattr(self, "author_label_title") and self.author_label_title:
                with contextlib.suppress(RuntimeError):
                    apply_stylesheet_if_changed(
                        self.author_label_title,
                        f"color: {text_color};",
                        cache_attr="_author_label_stylesheet_cache",
                    )
            if hasattr(self, "category_label_title") and self.category_label_title:
                with contextlib.suppress(RuntimeError):
                    apply_stylesheet_if_changed(
                        self.category_label_title,
                        f"color: {text_color};",
                        cache_attr="_category_label_stylesheet_cache",
                    )

    def update_labels_text(self):
        if hasattr(self, "author_label_title") and self.author_label_title:
            with contextlib.suppress(RuntimeError):
                self.author_label_title.setText(tr("ui.author_label"))
        if hasattr(self, "category_label_title") and self.category_label_title:
            with contextlib.suppress(RuntimeError):
                self.category_label_title.setText(tr("ui.category_label"))

    def set_selected(self, selected):
        if self.is_selected == selected:
            return
        self.is_selected = selected
        if hasattr(self, "_update_actions_visibility"):
            self._update_actions_visibility()
        self._update_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.mod_data)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            details_requested = getattr(self, "details_requested", None)
            if details_requested:
                details_requested.emit(self.mod_data)
        super().mouseDoubleClickEvent(event)
