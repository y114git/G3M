import logging
from typing import Any

from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config.constants import (
    BASE_TAG_NAMES,
    LIBRARY_IMPORT_ARCHIVE_EXTENSIONS,
)
from models.game_modes import get_visible_game_entries
from services.localization_service import tr
from ui.builders.shared_filters_builder import (
    apply_filters_frame_style,
    create_downloads_button,
    create_filters_frame,
    create_game_versions_button,
    create_modding_tools_button,
    create_modgame_combo,
    create_search_button,
    create_sort_controls,
    create_tag_checkboxes,
)
from ui.common.styling import (
    apply_scroll_area_chrome,
    apply_stylesheet_if_changed,
    build_button_style,
    build_scrollbar_qss,
    clamp_border_radius,
    get_border_radius,
    get_theme_colors,
    get_widget_border_radius,
    install_panel_style_handler,
    install_scroll_area_update_handlers,
    install_size_hint_height_sync,
)
from ui.widgets.shared.custom_controls import _ZeroHintWidget

logger = logging.getLogger(__name__)


class _DropAreaWidget(QWidget):
    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(
            u.toLocalFile().lower().endswith(LIBRARY_IMPORT_ARCHIVE_EXTENSIONS)
            for u in e.mimeData().urls()
        ):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [
                u.toLocalFile()
                for u in e.mimeData().urls()
                if u.toLocalFile().lower().endswith(LIBRARY_IMPORT_ARCHIVE_EXTENSIONS)
            ]
            if paths:
                e.acceptProposedAction()
                self.files_dropped.emit(paths)


class LibraryTabBuilder(QObject):
    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent)
        self.app_state, self.parent, self.widgets = app_state, parent, {}

    def _get_colors(self):
        return get_theme_colors(
            self.app_state.local_config,
            border="#039d5b",
            button="#222222",
            button_hover="#616b78",
            text="#e8e9eb",
            background="#282828",
        )

    def build(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(5)
        layout.setContentsMargins(10, 10, 10, 10)
        f_scroll = QScrollArea(widget)
        f_scroll.setWidgetResizable(True)
        f_scroll.setFrameShape(QFrame.Shape.NoFrame)
        f_scroll.setStyleSheet("QScrollArea { background-color: transparent; }")
        f_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        f_scroll.setMinimumWidth(200)
        filters = self._create_library_filters_widget()
        f_scroll.setWidget(filters)
        install_size_hint_height_sync(
            filters, f_scroll, attr_name="_library_filters_scroll_height_filter"
        )
        if self.app_state.local_config.get("hide_library_filters", False):
            f_scroll.setVisible(False)
        layout.addWidget(f_scroll)
        self.widgets["filters_scroll"] = f_scroll
        colors = self._get_colors()

        profile_row = QHBoxLayout()
        profile_row.setContentsMargins(0, 2, 0, 2)
        profile_row.addStretch()
        profile_combo = QComboBox()
        profile_combo.setObjectName("profile_combo")
        profile_combo.setMinimumWidth(180)
        profile_row.addWidget(profile_combo)
        profile_settings_btn = QPushButton()
        profile_settings_btn.setObjectName("profile_settings_button")
        profile_settings_btn.setIconSize(QSize(20, 20))
        profile_settings_btn.setToolTip(tr("profiles.manager_title"))
        profile_settings_btn.setContentsMargins(0, 0, 0, 0)
        profile_settings_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        profile_row.addWidget(profile_settings_btn)
        profile_row.addStretch()
        layout.addLayout(profile_row)
        self.widgets["profile_combo"] = profile_combo
        self.widgets["profile_settings_button"] = profile_settings_btn

        ctrl = QHBoxLayout()
        ctrl.setContentsMargins(0, 5, 0, 5)
        add_btn = QPushButton()
        add_btn.setObjectName("add_mod_button")
        self.widgets["add_mod_button"] = add_btn
        add_btn.setIconSize(QSize(20, 20))
        add_btn.setToolTip(tr("ui.add_mod"))
        add_btn.setContentsMargins(0, 0, 0, 0)
        add_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        ctrl.addStretch()
        ctrl.addWidget(add_btn)
        ctrl.addSpacing(20)
        game_combo = create_modgame_combo(
            self.app_state, get_visible_game_entries(), "selected_game_type"
        )
        ctrl.addWidget(game_combo)
        ctrl.addSpacing(4)
        game_versions_btn = create_game_versions_button(self.app_state)
        ctrl.addWidget(game_versions_btn)
        ctrl.addSpacing(20)
        ch_cb = QCheckBox(tr("ui.chapter_mode"))
        f_cb = QCheckBox(tr("ui.full_install"))
        ctrl.addWidget(ch_cb)
        ctrl.addWidget(f_cb)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        self._update_add_mod_button_size_and_style(add_btn, game_combo, colors)
        self._update_profile_settings_button_style(
            profile_settings_btn, game_combo, colors
        )
        layout.addSpacing(5)
        ch_tabs = QWidget()
        ch_tabs.setObjectName("chapter_tabs_container")
        ch_tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        t_layout = QHBoxLayout(ch_tabs)
        t_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t_layout.setContentsMargins(20, 10, 20, 10)
        t_layout.setSpacing(10)
        t_layout.addStretch()
        fs = max(1, int(14 * self.app_state.local_config.get("ui_scale", 1.0)))
        tab_btns = []
        for i, name in enumerate(
            [
                tr("chapters.menu"),
                tr("tabs.chapter_1"),
                tr("tabs.chapter_2"),
                tr("tabs.chapter_3"),
                tr("tabs.chapter_4"),
            ]
        ):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setObjectName(f"chapter_tab_{i}")
            btn.setStyleSheet(
                build_button_style(
                    btn.objectName(),
                    colors["button"],
                    colors["button_hover"],
                    colors["text"],
                    colors["border"],
                    width=None,
                    height=None,
                    font_size=fs,
                    border_radius=clamp_border_radius(
                        get_border_radius(self.app_state.local_config),
                        height=max(25, btn.sizeHint().height()),
                    ),
                    padding="5px",
                    checked_bg_color=colors["button_hover"],
                    checked_border_color=colors["border"],
                    checked_border_width=3,
                )
            )
            t_layout.addWidget(btn)
            tab_btns.append(btn)
        t_layout.addStretch()
        ch_tabs.setVisible(False)
        layout.addWidget(ch_tabs)
        content_hlayout = QHBoxLayout()
        content_hlayout.setSpacing(10)

        mods_cont = _DropAreaWidget()
        mods_cont.setObjectName("mods_background")
        mods_cont.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        m_layout = QVBoxLayout(mods_cont)
        m_layout.setContentsMargins(15, 15, 15, 15)
        m_layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)
        mods_lbl = QLabel(tr("ui.installed_mods_label"))
        mods_lbl.setStyleSheet("font-weight: bold; font-size: 16px;")
        mods_lbl.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header_row.addWidget(mods_lbl)
        header_row.addStretch()
        p_btn = QPushButton(tr("ui.priority"))
        m_btn = QPushButton(tr("ui.create_modpack_button"))
        for b, n in [(p_btn, "priority_button"), (m_btn, "create_modpack_button")]:
            b.setObjectName(n)
            b.setEnabled(False)
            self._update_priority_button_style(
                b, colors["button"], colors["border"], colors["button_hover"]
            )
        header_row.addWidget(p_btn)
        header_row.addWidget(m_btn)
        m_layout.addLayout(header_row)

        scroll = QScrollArea(mods_cont)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        mods_w = _ZeroHintWidget(scroll)
        mw_layout = QVBoxLayout(mods_w)
        mw_layout.addStretch()
        mw_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(mods_w)
        m_layout.addWidget(scroll)
        container_padding = 15

        def _apply_inner_clip():
            container_radius = get_widget_border_radius(
                mods_cont, get_border_radius(self.app_state.local_config)
            )
            content_padding = max(container_padding, (container_radius * 4 + 9) // 10)
            viewport_inset = max(2, min(10, container_radius // 5))
            scrollbar_corner_inset = max(6, min(18, container_radius // 2))
            scrollbar_qss = build_scrollbar_qss(
                colors["text"],
                get_border_radius(self.app_state.local_config),
                vertical_margin=(scrollbar_corner_inset, 2, scrollbar_corner_inset, 0),
                horizontal_margin=(
                    0,
                    scrollbar_corner_inset,
                    scrollbar_corner_inset,
                    scrollbar_corner_inset,
                ),
            )
            viewport = scroll.viewport() if hasattr(scroll, "viewport") else None
            v_scrollbar = (
                scroll.verticalScrollBar()
                if hasattr(scroll, "verticalScrollBar")
                else None
            )
            clip_key = (
                container_radius,
                content_padding,
                viewport_inset,
                scrollbar_corner_inset,
                int(scroll.width() or 0),
                int(scroll.height() or 0),
                int(viewport.width() or 0) if viewport else 0,
                int(viewport.height() or 0) if viewport else 0,
                bool(v_scrollbar.isVisible()) if v_scrollbar else False,
                int(
                    (v_scrollbar.width() or v_scrollbar.sizeHint().width())
                    if v_scrollbar
                    else 0
                ),
            )
            if getattr(scroll, "_library_inner_clip_key", None) == clip_key:
                return
            margin_key = (
                content_padding,
                content_padding,
                content_padding,
                content_padding,
            )
            if getattr(mods_cont, "_library_layout_margin_key", None) != margin_key:
                m_layout.setContentsMargins(*margin_key)
                mods_cont._library_layout_margin_key = margin_key
            apply_stylesheet_if_changed(
                scroll,
                f"""QScrollArea {{ background-color: transparent; border: none; }}{scrollbar_qss}""",
                cache_attr="_library_scroll_stylesheet_cache",
            )
            scrollbar_extent = apply_scroll_area_chrome(
                scroll,
                max(0, container_radius - viewport_inset),
                scrollbar_radius=get_border_radius(self.app_state.local_config),
                qss=scrollbar_qss,
            )
            viewport_margin_key = (
                viewport_inset,
                viewport_inset,
                max(viewport_inset, scrollbar_extent + 2),
                viewport_inset,
            )
            try:
                if (
                    getattr(scroll, "_library_viewport_margin_key", None)
                    != viewport_margin_key
                ):
                    scroll.setViewportMargins(*viewport_margin_key)
                    scroll._library_viewport_margin_key = viewport_margin_key
            except AttributeError, TypeError:
                logger.exception(
                    "LibraryTabBuilder: setViewportMargins failed for viewport_inset=%s",
                    viewport_inset,
                )
            scroll._library_inner_clip_key = clip_key

        mods_cont._inner_clip_callback = _apply_inner_clip
        install_scroll_area_update_handlers(
            scroll, _apply_inner_clip, "library_viewport_clip"
        )
        install_panel_style_handler(
            mods_cont,
            self.app_state.local_config,
            attr_name="_library_panel_style_filter",
        )
        content_hlayout.addWidget(mods_cont, 5)

        from ui.widgets.mod.mod_summary_panel import ModSummaryPanel

        summary_panel = ModSummaryPanel(self.app_state)
        install_panel_style_handler(
            summary_panel,
            self.app_state.local_config,
            attr_name="_summary_panel_style_filter",
        )
        content_hlayout.addWidget(summary_panel, 4)

        layout.addLayout(content_hlayout, 1)
        self.widgets.update(
            {
                "library_filters_widget": filters,
                "add_mod_button": add_btn,
                "game_type_combo": game_combo,
                "chapter_mode_checkbox": ch_cb,
                "full_install_checkbox": f_cb,
                "chapter_tabs_widget": ch_tabs,
                "chapter_tabs_layout": t_layout,
                "chapter_tab_buttons": tab_btns,
                "installed_mods_container": mods_cont,
                "installed_mods_scroll": scroll,
                "installed_mods_widget": mods_w,
                "installed_mods_layout": mw_layout,
                "priority_button": p_btn,
                "create_modpack_button": m_btn,
                "installed_mods_label": mods_lbl,
                "library_game_versions_button": game_versions_btn,
                "mod_summary_panel": summary_panel,
            }
        )
        return widget

    def _create_library_filters_widget(self) -> QFrame:
        w, layout = create_filters_frame()
        apply_filters_frame_style(w, self.app_state)
        w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        _vc = Qt.AlignmentFlag.AlignVCenter
        sort_combo, sort_btn = create_sort_controls(
            self.app_state, [tr("ui.sort_by_name"), tr("ui.sort_by_date")]
        )
        layout.addWidget(sort_combo, 0, _vc)
        layout.addWidget(sort_btn, 0, _vc)
        layout.addSpacing(20)
        tags_lbl = QLabel(tr("ui.tags_label"))
        layout.addWidget(tags_lbl, 0, _vc)
        tags = create_tag_checkboxes(self.app_state, (*BASE_TAG_NAMES, "gamebanana"))
        for t in tags.values():
            layout.addWidget(t, 0, _vc)
        layout.addStretch()
        modding_tools_btn = create_modding_tools_button(self.app_state)
        layout.addWidget(modding_tools_btn, 0, _vc)
        layout.addSpacing(4)
        downloads_btn = create_downloads_button(self.app_state)
        layout.addWidget(downloads_btn, 0, _vc)
        layout.addSpacing(4)
        search_btn = create_search_button(self.app_state)
        layout.addWidget(search_btn, 0, _vc)
        self.widgets.update(
            {
                "library_sort_combo": sort_combo,
                "library_sort_order_btn": sort_btn,
                "library_tags_label": tags_lbl,
                "library_search_button": search_btn,
                "library_downloads_button": downloads_btn,
                "library_modding_tools_button": modding_tools_btn,
                "library_tag_widgets": list(tags.values()),
            }
        )
        self.widgets.update({f"library_tag_{k}": v for k, v in tags.items()})
        return w

    def _square_btn_qss(self, obj_name, combo_height, colors):
        """Return QSS for a square icon button matching the combo height."""
        br = clamp_border_radius(
            get_border_radius(self.app_state.local_config),
            width=combo_height,
            height=combo_height,
            border_width=2,
        )
        return f"QPushButton#{obj_name} {{ border: 2px solid {colors['border']}; border-radius: {br}px; background-color: {colors['button']}; color: {colors['text']}; margin: 0px; padding: 0px; }} QPushButton#{obj_name}:hover {{ background-color: {colors['button_hover']}; }}"

    def _update_add_mod_button_size_and_style(self, add_btn, game_combo, colors):
        """Update add_mod_button to be square matching the combo height."""
        from utils.path_utils import colored_icon

        combo_height = game_combo.sizeHint().height()
        add_btn.setFixedSize(combo_height, combo_height)
        add_btn.setIcon(colored_icon("add", colors["text"]))
        add_btn.setStyleSheet(
            self._square_btn_qss(add_btn.objectName(), combo_height, colors)
        )

    def _update_profile_settings_button_style(self, btn, game_combo, colors):
        """Update profile_settings_button to be square matching the combo height."""
        from utils.path_utils import colored_icon

        combo_height = game_combo.sizeHint().height()
        btn.setFixedSize(combo_height, combo_height)
        btn.setIcon(colored_icon("settings", colors["text"]))
        btn.setStyleSheet(self._square_btn_qss(btn.objectName(), combo_height, colors))

    def _update_priority_button_style(self, btn, btn_clr, brd_clr, hvr_clr):
        n = btn.objectName()
        t = self._get_colors()["text"]
        fs = max(1, int(14 * self.app_state.local_config.get("ui_scale", 1.0)))
        btn.setStyleSheet(
            build_button_style(
                n,
                btn_clr,
                hvr_clr,
                t,
                brd_clr,
                width=None,
                height=None,
                font_size=fs,
                border_radius=clamp_border_radius(
                    get_border_radius(self.app_state.local_config),
                    height=max(30, btn.sizeHint().height()),
                ),
                padding="5px",
            )
        )

    def update_priority_button_style(self):
        colors = self._get_colors()
        for k in ("priority_button", "create_modpack_button"):
            if k in self.widgets:
                self._update_priority_button_style(
                    self.widgets[k],
                    colors["button"],
                    colors["border"],
                    colors["button_hover"],
                )
        game_combo = self.widgets.get("game_type_combo")
        if game_combo:
            if "add_mod_button" in self.widgets:
                self._update_add_mod_button_size_and_style(
                    self.widgets["add_mod_button"], game_combo, colors
                )
            if "profile_settings_button" in self.widgets:
                self._update_profile_settings_button_style(
                    self.widgets["profile_settings_button"], game_combo, colors
                )
        tag_lbl = self.widgets.get("library_tags_label")
        if tag_lbl:
            tag_lbl.setStyleSheet(f"color: {colors['text']};")

    def get_widgets(self) -> dict[str, Any]:
        return self.widgets
