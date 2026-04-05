"""Summary panel for displaying selected mod details in the Library tab."""

import html
import logging
import os
import threading

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from services.localization_service import tr
from ui.common.styling import (
    DEFAULT_COLORS,
    apply_stylesheet_if_changed,
    build_button_style,
    get_border_radius,
    get_card_button_metrics,
    get_card_layout_scale,
    get_theme_color,
    load_mod_icon_universal,
    rgba_from_color,
)
from utils.mod_readme_utils import find_mod_readme_files
from utils.path_utils import colored_icon

logger = logging.getLogger(__name__)


class ModSummaryPanel(QFrame):
    """Right-side panel showing selected mod summary info."""

    use_requested = pyqtSignal(object)
    edit_requested = pyqtSignal(object)
    export_requested = pyqtSignal(object)
    folder_requested = pyqtSignal(object)
    versions_requested = pyqtSignal(object)
    delete_requested = pyqtSignal(object)
    homepage_requested = pyqtSignal(object)
    readme_requested = pyqtSignal(object)

    _ACTION_DEFS = [
        ("external", "tooltips.open_homepage", "homepage_requested"),
        ("edit", "ui.edit_mod", "edit_requested"),
        ("export", "ui.export_mod", "export_requested"),
        ("folder", "tooltips.open_mod_folder", "folder_requested"),
        ("filerestore", "mod_versions.title", "versions_requested"),
        ("delete", "ui.delete_mod", "delete_requested"),
    ]

    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._current_mod = None
        self._current_mod_folder = None
        self._cached_metadata = None
        self._cached_file_info = None
        self._cached_mod_id = None
        self._current_readme_files = []
        self._mod_size_cache = {}
        self._size_threads = {}
        self._cache_lock = threading.Lock()
        self.setObjectName("summaryPanel")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAutoFillBackground(True)
        self._build_ui()

    def _get_config(self):
        return getattr(self._app_state, "local_config", None)

    def _layout_scale(self) -> float:
        return get_card_layout_scale(self._get_config())

    def _compute_folder_size_background(self, mod_folder: str):
        """Compute folder size in background thread and update UI."""
        if not mod_folder or not os.path.isdir(mod_folder):
            return

        with self._cache_lock:
            if mod_folder in self._mod_size_cache or mod_folder in self._size_threads:
                return
            self._size_threads[mod_folder] = threading.current_thread()

        try:
            total = sum(
                os.path.getsize(os.path.join(r, f))
                for r, _, files in os.walk(mod_folder)
                for f in files
            )

            with self._cache_lock:
                self._mod_size_cache[mod_folder] = total

            from PyQt6.QtCore import QTimer

            QTimer.singleShot(0, lambda: self._on_size_computed(mod_folder, total))

        except Exception as e:
            logging.debug(
                f"ModSummaryPanel: failed to calculate mod folder size for {mod_folder}: {e}",
                exc_info=True,
            )
        finally:
            with self._cache_lock:
                self._size_threads.pop(mod_folder, None)

    def _on_size_computed(self, mod_folder: str, size: int):
        """Called on main thread when size computation completes."""
        if mod_folder == self._current_mod_folder:
            self._update_metadata(self._current_mod, mod_folder, cache_result=True)
            self.apply_theme()

    def _build_ui(self):
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._empty_label = QLabel(tr("ui.select_mod"))
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setObjectName("emptySummaryLabel")
        root.addWidget(self._empty_label, 1)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("summaryScrollArea")
        self._scroll.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._scroll.setAutoFillBackground(True)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.viewport().setObjectName("summaryViewport")
        self._scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._content = QWidget()
        self._content.setObjectName("summaryContent")
        self._content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._content.setAutoFillBackground(True)
        cl = QVBoxLayout(self._content)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self._use_button = QPushButton(tr("ui.use_button"))
        self._use_button.setObjectName("summaryUseButton")
        self._use_button.clicked.connect(self._on_use_clicked)
        top_row.addWidget(self._use_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._readme_button = QPushButton(tr("dialogs.info"))
        self._readme_button.setObjectName("summaryReadmeButton")
        self._readme_button.clicked.connect(self._on_readme_clicked)
        self._readme_button.hide()
        top_row.addWidget(self._readme_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._playtime_widget = QWidget()
        playtime_layout = QHBoxLayout(self._playtime_widget)
        playtime_layout.setContentsMargins(0, 0, 0, 0)
        playtime_layout.setSpacing(4)
        playtime_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._playtime_icon = QLabel()
        self._playtime_icon.setFixedSize(16, 16)
        self._playtime_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._playtime_value = QLabel()
        self._playtime_value.setObjectName("summaryPlaytime")
        self._playtime_value.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        playtime_layout.addWidget(self._playtime_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        playtime_layout.addWidget(self._playtime_value, 0, Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(
            self._playtime_widget,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        top_row.addStretch()
        self._actions_widget = QWidget(self._content)
        actions = QHBoxLayout(self._actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(4)
        self._action_buttons = {}
        for icon_name, tooltip_key, signal_name in self._ACTION_DEFS:
            btn = QToolButton()
            btn.setObjectName("summaryActionButton")
            btn.setToolTip(tr(tooltip_key))
            btn.setIconSize(QSize(18, 18))
            btn.clicked.connect(
                lambda _checked=False, s=signal_name: self._emit_action(s)
            )
            actions.addWidget(btn)
            self._action_buttons[icon_name] = btn
        top_row.addWidget(self._actions_widget, 0, Qt.AlignmentFlag.AlignRight)
        cl.addLayout(top_row)

        hero = QHBoxLayout()
        hero.setSpacing(16)
        hero.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._mod_icon = QLabel()
        self._mod_icon.setFixedSize(96, 96)
        self._mod_icon.setObjectName("summaryModIcon")
        self._mod_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.addWidget(self._mod_icon, 0, Qt.AlignmentFlag.AlignTop)
        right_col = QVBoxLayout()
        right_col.setSpacing(6)
        right_col.addStretch()
        self._name_label = QLabel()
        self._name_label.setObjectName("summaryModName")
        self._name_label.setWordWrap(True)
        right_col.addWidget(self._name_label)
        self._description_label = QLabel()
        self._description_label.setObjectName("summaryDescription")
        self._description_label.setWordWrap(True)
        right_col.addWidget(self._description_label)
        right_col.addStretch()
        hero.addLayout(right_col, 1)
        cl.addLayout(hero)

        self._meta_label = QLabel()
        self._meta_label.setObjectName("summaryMetaRow")
        self._meta_label.setWordWrap(True)
        cl.addWidget(self._meta_label)

        self._data_label = QLabel()
        self._data_label.setObjectName("summaryInfoBlock")
        self._data_label.setWordWrap(True)
        self._data_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        cl.addWidget(self._data_label)

        self._extra_label = QLabel()
        self._extra_label.setObjectName("summaryInfoBlock")
        self._extra_label.setWordWrap(True)
        self._extra_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        cl.addWidget(self._extra_label)

        cl.addStretch()
        self._scroll.setWidget(self._content)
        if self._scroll.viewport():
            self._scroll.viewport().setAutoFillBackground(True)
        root.addWidget(self._scroll, 1)
        self._scroll.hide()

    def _emit_action(self, signal_name):
        if self._current_mod:
            getattr(self, signal_name).emit(self._current_mod)

    def _on_use_clicked(self):
        if self._current_mod:
            self.use_requested.emit(self._current_mod)

    def _on_readme_clicked(self):
        if self._current_mod:
            self.readme_requested.emit(self._current_mod)

    def show_empty(self):
        self._current_mod = None
        self._current_mod_folder = None
        self._cached_mod_id = None
        self._cached_metadata = None
        self._cached_file_info = None
        self._current_readme_files = []
        self._playtime_widget.hide()
        self._readme_button.hide()
        with self._cache_lock:
            self._mod_size_cache.clear()
            self._size_threads.clear()
        self._empty_label.show()
        self._scroll.hide()

    def show_mod(self, mod_data, mod_folder=None, is_active=False):
        from utils.patching.mod_resolve_utils import get_mod_id

        self._current_mod = mod_data
        self._current_mod_folder = self._resolve_mod_folder(mod_data, mod_folder)
        self._cached_mod_id = get_mod_id(mod_data) if mod_data else None
        self._cached_metadata = None
        self._cached_file_info = None
        self._current_readme_files = find_mod_readme_files(self._current_mod_folder)
        self._empty_label.hide()
        self._scroll.show()
        self._name_label.setText(getattr(mod_data, "name", "") or "")
        description = getattr(mod_data, "description", "") or tr("ui.no_description")
        self._description_label.setText(description)
        config = self._get_config()
        br = get_border_radius(config) if config else 0
        bc = get_theme_color(config, "border") if config else None
        load_mod_icon_universal(
            self._mod_icon,
            mod_data,
            96,
            border_radius=br,
            border_width=2 if bc else 0,
            border_color=bc,
        )
        self._update_metadata(mod_data, self._current_mod_folder)
        self._populate_file_info(mod_data, self._current_mod_folder)
        self._update_playtime(mod_data)
        self._update_action_visibility(mod_data, self._current_mod_folder)
        self.update_use_button_state(is_active)
        self.apply_theme()

    def _update_action_visibility(self, mod_data, mod_folder) -> None:
        is_local_mod = bool(mod_folder) and os.path.isdir(mod_folder)
        ext_url = getattr(mod_data, "homepage", None) or getattr(
            mod_data, "description_url", None
        )
        local_management_buttons = ("edit", "export", "folder", "filerestore", "delete")
        if "external" in self._action_buttons:
            self._action_buttons["external"].setVisible(bool(ext_url))
        for icon_name in local_management_buttons:
            if icon_name in self._action_buttons:
                self._action_buttons[icon_name].setVisible(is_local_mod)
        self._actions_widget.setVisible(
            any(button.isVisible() for button in self._action_buttons.values())
        )
        self._readme_button.setVisible(is_local_mod and bool(self._current_readme_files))

    def _update_metadata(self, mod_data, mod_folder, cache_result=False):
        config = self._get_config()
        tc = get_theme_color(config, "main_text") if config else DEFAULT_COLORS["main_text"]
        sc = (
            get_theme_color(config, "secondary_text")
            if config
            else DEFAULT_COLORS["secondary_text"]
        )
        parts = []
        author = getattr(mod_data, "author", None)
        if author:
            parts.append(
                f"<span style='color:{tc}'>{tr('ui.author_label')}</span> <span style='color:{sc}'>{author}</span>"
            )
        version = getattr(mod_data, "version", None)
        if version:
            if "|" in version:
                version = version.split("|", 1)[0]
            parts.append(
                f"<span style='color:{tc}'>{tr('ui.mod_version_label')}</span> <span style='color:{sc}'>{version}</span>"
            )
        game_version = getattr(mod_data, "game_version", None)
        if game_version:
            parts.append(
                f"<span style='color:{tc}'>{tr('ui.game_version_label')}</span> <span style='color:{sc}'>{game_version}</span>"
            )
        added = getattr(mod_data, "added_date", None)
        if added:
            parts.append(
                f"<span style='color:{tc}'>{tr('ui.added_label')}</span> <span style='color:{sc}'>{added}</span>"
            )
        updated = getattr(mod_data, "last_updated", None)
        if updated:
            parts.append(
                f"<span style='color:{tc}'>{tr('ui.updated_label')}</span> <span style='color:{sc}'>{updated}</span>"
            )
        if mod_folder and os.path.isdir(mod_folder):
            size_text = None
            with self._cache_lock:
                if mod_folder in self._mod_size_cache:
                    from ui.utils.ui_utils import format_size

                    size_text = format_size(self._mod_size_cache[mod_folder])

            if size_text:
                parts.append(
                    f"<span style='color:{tc}'>{tr('ui.size_label')}</span> <span style='color:{sc}'>{size_text}</span>"
                )
            else:
                thread = threading.Thread(
                    target=self._compute_folder_size_background,
                    args=(mod_folder,),
                    daemon=True,
                )
                thread.start()
                parts.append(
                    f"<span style='color:{tc}'>{tr('ui.size_label')}</span> <span style='color:{sc}'>...</span>"
                )

        metadata_text = "<br>".join(parts)
        self._cached_metadata = metadata_text if cache_result else None
        self._meta_label.setText(metadata_text)

    def _populate_file_info(self, mod_data, mod_folder, cache_result=False):
        files = getattr(mod_data, "files", None)
        if not files or not isinstance(files, dict):
            data_text = f"<span style='color:{get_theme_color(self._get_config(), 'secondary_text', DEFAULT_COLORS['secondary_text']) if self._get_config() else DEFAULT_COLORS['secondary_text']}'>{tr('ui.no_data_files')}</span>"
            self._cached_file_info = (data_text, False) if cache_result else None
            self._data_label.setText(data_text)
            self._extra_label.hide()
            return
        config = self._get_config()
        tc = get_theme_color(config, "main_text") if config else DEFAULT_COLORS["main_text"]
        sc = (
            get_theme_color(config, "secondary_text")
            if config
            else DEFAULT_COLORS["secondary_text"]
        )
        sorted_keys = sorted(
            files.keys(),
            key=lambda k: (0 if k == "0" else 1, int(k) if k.isdigit() else 999, k),
        )
        data_lines = []
        extra_total = 0
        extra_chapters = []
        for chapter_key in sorted_keys:
            ch_info = files[chapter_key]
            if ch_info is None:
                continue
            if isinstance(ch_info, dict):
                data_file = ch_info.get("data_file_path") or ch_info.get("data_file_url")
                extra_files = ch_info.get("extra_files", [])
            else:
                data_file = getattr(ch_info, "data_file_path", None)
                extra_files = getattr(ch_info, "extra_files", [])
            chapter_label = self._format_chapter_label(chapter_key)
            if data_file:
                size_str = ""
                raw_data_file = str(data_file).replace("\\", "/")
                display_name = self._format_display_path(raw_data_file)
                if mod_folder:
                    try:
                        data_path = self._resolve_data_file_path(
                            mod_folder, chapter_key, raw_data_file
                        )
                        if data_path:
                            from ui.utils.ui_utils import format_size

                            size_str = f" - {format_size(os.path.getsize(data_path))}"
                    except Exception as e:
                        logger.debug(
                            f"ModSummaryPanel: failed to calculate file size for chapter {chapter_key}: {e}",
                            exc_info=True,
                        )
                data_lines.append(
                    f"<span style='color:{tc}'>{html.escape(chapter_label)}:</span> <span style='color:{sc}'>{self._wrap_display_text(display_name)}{html.escape(size_str)}</span>"
                )
            extra_paths = self._collect_extra_paths(extra_files)
            if extra_paths:
                extra_total += len(extra_paths)
                file_lines = [
                    f"&nbsp;&nbsp;&nbsp;&nbsp;<span style='color:{sc}'>{self._wrap_display_text(self._format_display_path(file_path))}</span>"
                    for file_path in extra_paths
                ]
                extra_chapters.append((chapter_label, len(extra_paths), file_lines))
        data_text = (
            "<br>".join(data_lines)
            if data_lines
            else f"<span style='color:{sc}'>-</span>"
        )
        self._data_label.setText(
            f"<span style='color:{tc}; font-weight:600;'>{tr('ui.changed_data_files_label')}</span><br><br>{data_text}"
        )
        if extra_total > 0:
            lines = [
                f"<span style='color:{tc}; font-weight:600;'>{tr('ui.extra_files_label')}</span> <span style='color:{sc}'>{extra_total}</span>"
            ]
            for ch_label, ch_count, file_lines in extra_chapters:
                lines.append(
                    f"<br><span style='color:{tc}'>&nbsp;&nbsp;{html.escape(ch_label)}:</span> <span style='color:{sc}'>{ch_count}</span>"
                )
                lines.extend(file_lines)
            extra_text = "<br>".join(lines)
            self._extra_label.setText(extra_text)
            self._extra_label.show()
            self._cached_file_info = (
                (
                    f"<span style='color:{tc}; font-weight:600;'>{tr('ui.changed_data_files_label')}</span><br><br>{data_text}",
                    extra_text,
                )
                if cache_result
                else None
            )
        else:
            self._extra_label.hide()
            self._cached_file_info = (
                (
                    f"<span style='color:{tc}; font-weight:600;'>{tr('ui.changed_data_files_label')}</span><br><br>{data_text}",
                    False,
                )
                if cache_result
                else None
            )

    @staticmethod
    def _format_playtime_hours(hours: float) -> str:
        try:
            value = max(0.0, float(hours))
        except (TypeError, ValueError):
            return "0"
        if value <= 0:
            return "0"
        text = f"{value:.1f}"
        return text[:-2] if text.endswith(".0") else text

    def _update_playtime(self, mod_data) -> None:
        text = self._format_playtime_hours(getattr(mod_data, "playtime_hours", 0.0))
        self._playtime_icon.setPixmap(
            colored_icon("time", get_theme_color(self._get_config(), "main_text")).pixmap(
                16, 16
            )
        )
        self._playtime_value.setText(f"{text} {tr('ui.playtime_hours_suffix')}")
        self._playtime_widget.show()

    @staticmethod
    def _collect_extra_paths(extra_files) -> list[str]:
        """Return a flat list of extra file paths."""
        if isinstance(extra_files, dict):
            result: list[str] = []
            for values in extra_files.values():
                if isinstance(values, list):
                    result.extend(str(value) for value in values if value)
            return result
        if not isinstance(extra_files, list) or not extra_files:
            return []
        result = []
        for ef in extra_files:
            if ef:
                result.append(str(ef))
        return result

    @staticmethod
    def _format_display_path(path: str) -> str:
        normalized = str(path or "").replace("\\", "/")
        if not normalized:
            return ""
        is_dir = normalized.endswith("/")
        trimmed = normalized.rstrip("/")
        if not trimmed:
            return "/"
        name = os.path.basename(trimmed) or trimmed
        return f"{name}/" if is_dir else name

    @staticmethod
    def _wrap_display_text(text: str) -> str:
        escaped = html.escape(str(text or ""))
        for separator in ("/", "_", "-", ".", ")", "]"):
            escaped = escaped.replace(separator, f"{separator}&#8203;")
        for separator in ("(", "["):
            escaped = escaped.replace(separator, f"&#8203;{separator}")
        return escaped

    @staticmethod
    def _format_chapter_label(chapter_key) -> str:
        if isinstance(chapter_key, str) and chapter_key.startswith("deltarune_"):
            suffix = chapter_key.removeprefix("deltarune_")
            try:
                ch_id = int(suffix)
                if ch_id == 0:
                    return tr("tabs.menu_root")
                return tr("ui.chapter_title", chapter_num=ch_id)
            except (ValueError, TypeError):
                pass
        if chapter_key == "deltarune":
            return tr("tabs.menu_root")
        try:
            ch_id = int(chapter_key)
            if ch_id == 0:
                return tr("tabs.menu_root")
            return tr("ui.chapter_title", chapter_num=ch_id)
        except (ValueError, TypeError):
            return chapter_key.capitalize()

    def _resolve_data_file_path(
        self, mod_folder: str | None, chapter_key, data_file: str
    ) -> str:
        if not data_file:
            return ""
        data_file_str = str(data_file)
        if os.path.isfile(data_file_str):
            return data_file_str
        if not mod_folder or not os.path.isdir(mod_folder):
            return ""
        try:
            from utils.mod_config_parser import resolve_mod_file_path

            resolved = resolve_mod_file_path(mod_folder, data_file_str)
            if resolved and os.path.isfile(resolved):
                return resolved
        except ImportError as e:
            from utils.logging_utils import log_warning
            log_warning(f"resolve_mod_file_path not available: {e}")
        except Exception as e:
            from utils.logging_utils import log_warning
            log_warning(f"Failed to resolve chapter folder for {chapter_key}: {e}")
        file_name = os.path.basename(data_file_str.replace("\\", "/"))
        for root, _, files in os.walk(mod_folder):
            if file_name in files:
                return os.path.join(root, file_name)
        return ""

    @staticmethod
    def _resolve_mod_folder(mod_data, mod_folder: str | None) -> str | None:
        if mod_folder and os.path.isdir(mod_folder):
            return mod_folder
        for attr in ("folder_path",):
            candidate = getattr(mod_data, attr, None)
            if candidate and os.path.isdir(candidate):
                return candidate
        return mod_folder

    def update_use_button_state(self, is_active=False):
        config = self._get_config()
        border = get_theme_color(config, "border") if config else "#039d5b"
        br = get_border_radius(config) if config else 0
        metrics = get_card_button_metrics(config) if config else None
        bw, bh, bfs = (metrics[0], metrics[1], metrics[2]) if metrics else (100, 30, 13)
        if is_active:
            self._use_button.setText(tr("ui.remove_button"))
            apply_stylesheet_if_changed(
                self._use_button,
                build_button_style(
                    "summaryUseButton",
                    "#FF9800",
                    "#F57C00",
                    "#e8e9eb",
                    border,
                    width=bw,
                    height=bh,
                    font_size=bfs,
                    border_radius=br,
                ),
                cache_attr="_use_btn_ss_cache",
            )
        else:
            self._use_button.setText(tr("ui.use_button"))
            apply_stylesheet_if_changed(
                self._use_button,
                build_button_style(
                    "summaryUseButton",
                    "#4CAF50",
                    "#5cb85c",
                    "#e8e9eb",
                    border,
                    width=bw,
                    height=bh,
                    font_size=bfs,
                    border_radius=br,
                ),
                cache_attr="_use_btn_ss_cache",
            )

    def apply_theme(self):
        config = self._get_config()
        if not config:
            return
        text_color = get_theme_color(config, "main_text")
        secondary = get_theme_color(config, "secondary_text")
        border = get_theme_color(config, "border")
        button_hover = get_theme_color(config, "hover")
        background = rgba_from_color(get_theme_color(config, "background"))
        elements = get_theme_color(config, "elements", "#202326")
        br = get_border_radius(config)
        title_fs = max(14, round(16 * self._layout_scale()))
        apply_stylesheet_if_changed(
            self,
            f"""
            QFrame#summaryPanel {{
                background-color: {background};
                border: none;
                border-radius: {br}px;
            }}
            QScrollArea#summaryScrollArea {{
                background-color: {background};
                border: none;
                border-radius: {br}px;
            }}
            QWidget#summaryViewport {{
                background-color: {background};
                border: none;
                border-radius: {br}px;
            }}
            QWidget#summaryContent {{
                background-color: {background};
                border-radius: {br}px;
            }}
            """,
            cache_attr="_panel_ss_cache",
        )
        apply_stylesheet_if_changed(
            self._scroll.viewport(),
            f"background-color: {background}; border: none; border-radius: {br}px;",
            cache_attr="_scroll_viewport_ss_cache",
        )
        for name, btn in self._action_buttons.items():
            btn.setIcon(colored_icon(name, text_color))
            apply_stylesheet_if_changed(
                btn,
                f"""
                QToolButton#summaryActionButton {{
                    background: transparent; border: 2px solid {border};
                    border-radius: {min(br, 10)}px; min-width: 32px; min-height: 32px;
                    max-width: 32px; max-height: 32px; padding: 0;
                }}
                QToolButton#summaryActionButton:hover {{ background: {button_hover}; }}
            """,
                cache_attr=f"_action_{name}_ss_cache",
            )
        apply_stylesheet_if_changed(
            self._readme_button,
            build_button_style(
                "summaryReadmeButton",
                elements,
                button_hover,
                text_color,
                border,
                width=None,
                height=32,
                font_size=max(11, round(12 * self._layout_scale())),
                border_radius=min(br, 10),
                padding="0 12px",
            ),
            cache_attr="_readme_btn_ss_cache",
        )
        apply_stylesheet_if_changed(
            self._empty_label,
            f"color: {secondary}; font-size: 16px; font-weight: 600;",
            cache_attr="_empty_ss_cache",
        )
        apply_stylesheet_if_changed(
            self._name_label,
            f"font-size: {title_fs}px; font-weight: bold; color: {text_color};",
            cache_attr="_name_ss_cache",
        )
        apply_stylesheet_if_changed(
            self._description_label,
            f"color: {secondary};",
            cache_attr="_description_ss_cache",
        )
        apply_stylesheet_if_changed(
            self._playtime_value,
            f"color: {text_color}; font-weight: 600;",
            cache_attr="_playtime_ss_cache",
        )
        meta_bg = background
        apply_stylesheet_if_changed(
            self._meta_label,
            f"""
            background-color: {meta_bg}; border: 2px solid {border};
            border-radius: {min(br, 10)}px; padding: 8px 10px;
        """,
            cache_attr="_meta_ss_cache",
        )
        block_ss = f"""
            background-color: {meta_bg}; border: 2px solid {border};
            border-radius: {min(br, 14)}px; padding: 14px 16px;
        """
        apply_stylesheet_if_changed(
            self._data_label, block_ss, cache_attr="_data_ss_cache"
        )
        apply_stylesheet_if_changed(
            self._extra_label, block_ss, cache_attr="_extra_ss_cache"
        )
        apply_stylesheet_if_changed(
            self._mod_icon,
            f"""
            background-color: {meta_bg}; border: 2px solid {border};
            border-radius: {min(br, 18)}px;
        """,
            cache_attr="_icon_ss_cache",
        )
        if self._current_mod:
            load_mod_icon_universal(
                self._mod_icon,
                self._current_mod,
                96,
                border_radius=br,
                border_width=2,
                border_color=border,
            )
            self._update_metadata(
                self._current_mod, self._current_mod_folder, cache_result=True
            )
            self._populate_file_info(
                self._current_mod, self._current_mod_folder, cache_result=True
            )
            self._update_playtime(self._current_mod)
        self.update_use_button_state(self._use_button.text() == tr("ui.remove_button"))

    def refresh_theme(self):
        self._cached_metadata = None
        self._cached_file_info = None
        self._current_readme_files = find_mod_readme_files(self._current_mod_folder)
        self.apply_theme()

    def update_labels_text(self):
        self._empty_label.setText(tr("ui.select_mod"))
        self._use_button.setText(tr("ui.use_button"))
        self._readme_button.setText(tr("dialogs.info"))
        for icon_name, tooltip_key, _ in self._ACTION_DEFS:
            if icon_name in self._action_buttons:
                self._action_buttons[icon_name].setToolTip(tr(tooltip_key))
        if self._current_mod:
            self._update_action_visibility(self._current_mod, self._current_mod_folder)
            self._update_playtime(self._current_mod)
