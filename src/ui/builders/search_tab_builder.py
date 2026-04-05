from typing import Any

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config.config import BASE_TAG_NAMES, CYOP_AFOM_TAG, QSS_TRANSPARENT_SCROLL
from models.game_modes import get_search_game_entries
from services.localization_service import tr
from ui.builders.shared_filters_builder import (
    apply_filters_frame_style,
    create_blocklist_button,
    create_downloads_button,
    create_filters_frame,
    create_modgame_combo,
    create_search_button,
    create_sort_controls,
    create_tag_checkboxes,
    set_pizzatower_only_tag_visibility,
)
from ui.common.styling import (
    apply_panel_style,
    build_tag_checkbox_style,
    get_theme_color,
    get_ui_scale_factor,
    install_scroll_area_update_handlers,
    install_scroll_viewport_clip,
    install_size_hint_height_sync,
    style_filter_scroll_area,
)


class ModsBrowserTabBuilder(QObject):
    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent)
        self.app_state, self.parent, self.widgets = app_state, parent, {}
        self.mod_list_columns = 1
        self._dynamic_style_signal_connected = False

    def refresh_dynamic_styles(self) -> None:
        show_nsfw_checkbox = self.widgets.get("show_nsfw_checkbox")
        filters_scroll = self.widgets.get("filters_scroll")
        if filters_scroll:
            style_filter_scroll_area(filters_scroll, getattr(self.app_state, "local_config", None))
        if not show_nsfw_checkbox:
            return
        config = getattr(self.app_state, "local_config", None)
        scale = get_ui_scale_factor(config)
        text_color = get_theme_color(config, "main_text")
        show_nsfw_checkbox.setStyleSheet(
            build_tag_checkbox_style(
                text_color,
                font_size=max(12, round(14 * scale)),
                indicator_size=max(16, round(18 * scale)),
                spacing=max(4, round(5 * scale)),
            )
        )

    def _connect_dynamic_style_refresh(self) -> None:
        if self._dynamic_style_signal_connected:
            return
        settings_service = getattr(self.parent, "settings_service", None)
        if settings_service is None:
            return
        settings_service.theme_changed.connect(self.refresh_dynamic_styles)
        self._dynamic_style_signal_connected = True

    def build(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        f_scroll = QScrollArea(widget)
        f_scroll.setWidgetResizable(True)
        f_scroll.setFrameShape(QFrame.Shape.NoFrame)
        f_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        f_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        f_scroll.setMinimumWidth(200)
        f_widget = self._create_filters_widget()
        f_scroll.setWidget(f_widget)
        install_size_hint_height_sync(
            f_widget, f_scroll, attr_name="_filters_scroll_height_filter"
        )
        install_scroll_area_update_handlers(
            f_scroll,
            lambda target=f_scroll: style_filter_scroll_area(
                target, getattr(self.app_state, "local_config", None)
            ),
            "search_filters_scroll",
        )
        layout.addWidget(f_scroll)
        self.widgets.update({"filters_scroll": f_scroll, "filters_widget": f_widget})
        container = QWidget(widget)
        container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        container.setObjectName("mods_browser_background")
        sc_layout = QVBoxLayout(container)
        sc_layout.setContentsMargins(10, 10, 10, 10)
        sc_layout.setSpacing(10)
        scroll = QScrollArea(container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(QSS_TRANSPARENT_SCROLL)
        scroll.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        mod_list = QWidget(scroll)
        mod_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        mod_list_layout = QGridLayout(mod_list)
        mod_list_layout.setContentsMargins(0, 0, 0, 0)
        mod_list_layout.setHorizontalSpacing(18)
        mod_list_layout.setVerticalSpacing(18)
        mod_list_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
        )
        scroll.setWidget(mod_list)
        sc_layout.addWidget(scroll)
        container_padding = 10
        install_scroll_viewport_clip(
            scroll,
            container,
            self.app_state.local_config,
            inset=container_padding,
            attr_name="_search_viewport_clip_filter",
        )
        apply_panel_style(container, self.app_state.local_config)
        layout.addWidget(container)
        self.widgets.update(
            {
                "mods_browser_container": container,
                "mods_browser_scroll": scroll,
                "mod_list_widget": mod_list,
                "mod_list_layout": mod_list_layout,
                "mod_list_columns": self.mod_list_columns,
            }
        )
        self._connect_dynamic_style_refresh()
        return widget

    def _create_filters_widget(self) -> QFrame:
        w, layout = create_filters_frame()
        apply_filters_frame_style(w, self.app_state)
        w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        align_vcenter = Qt.AlignmentFlag.AlignVCenter
        sort_combo, sort_btn = create_sort_controls(
            self.app_state,
            [
                (tr("ui.sort_by_relevance"), "relevant"),
                (tr("ui.sort_by_creation_date"), "new"),
                (tr("ui.sort_by_update_date"), "updated"),
            ],
            "search_sort_index",
            include_order_button=False,
        )
        layout.addWidget(sort_combo, 0, align_vcenter)
        layout.addSpacing(20)
        modgame_combo = create_modgame_combo(
            self.app_state, get_search_game_entries(), "selected_search_game"
        )
        layout.addWidget(modgame_combo, 0, align_vcenter)
        layout.addSpacing(20)
        tags_label = QLabel(tr("ui.tags_label"))
        tags_label.setToolTip(tr("tooltips.filter_by_tag"))
        layout.addWidget(tags_label, 0, align_vcenter)
        tags = create_tag_checkboxes(
            self.app_state,
            (*BASE_TAG_NAMES, ("cyop_afom", CYOP_AFOM_TAG, "tags.cyop_afom")),
        )
        for t in tags.values():
            layout.addWidget(t, 0, align_vcenter)
        set_pizzatower_only_tag_visibility(
            tags.get("cyop_afom"),
            (modgame_combo.currentData() or "deltarune") == "pizzatower",
        )
        show_nsfw_checkbox = QCheckBox(tr("ui.show_nsfw"))
        show_nsfw_checkbox.setChecked(
            bool(self.app_state.local_config.get("show_nsfw", False))
        )
        show_nsfw_checkbox.setToolTip(tr("tooltips.show_nsfw"))
        layout.addWidget(show_nsfw_checkbox, 0, align_vcenter)
        layout.addStretch()
        blocklist_btn = create_blocklist_button(self.app_state)
        layout.addWidget(blocklist_btn, 0, align_vcenter)
        layout.addSpacing(4)
        downloads_btn = create_downloads_button(self.app_state)
        layout.addWidget(downloads_btn, 0, align_vcenter)
        layout.addSpacing(4)
        search_btn = create_search_button(self.app_state)
        layout.addWidget(search_btn, 0, align_vcenter)
        self.widgets.update(
            {
                "sort_combo": sort_combo,
                "sort_order_btn": sort_btn,
                "modgame_combo": modgame_combo,
                "tags_label": tags_label,
                "show_nsfw_checkbox": show_nsfw_checkbox,
                "blocklist_button": blocklist_btn,
                "search_button": search_btn,
                "downloads_button": downloads_btn,
            }
        )
        self.widgets.update({f"tag_{k}": v for k, v in tags.items()})
        self.refresh_dynamic_styles()
        return w

    def get_widgets(self) -> dict[str, Any]:
        return self.widgets
