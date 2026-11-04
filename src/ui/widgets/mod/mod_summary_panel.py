"""Summary panel for displaying selected mod details in the Library tab."""

import base64
import html
import logging
import os
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models.mod_models import format_mod_authors
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
from utils.date_format import format_stored_date
from utils.mod.archive import ArchiveVirtualPath
from utils.mod.config import (
    MOD_CONFIG_VERSION,
    ModConfigValidationError,
    iter_mod_config_leaves,
    load_mod_config,
)
from utils.mod.operation_plan import ModPathContext, resolve_operation_path
from utils.mod.readme_utils import find_mod_readme_files
from utils.path_utils import colored_icon, resource_path

logger = logging.getLogger(__name__)

_OPERATION_ICON_FILES = {
    "patch": "patch_type_icon.svg",
    "overwrite": "overwrite_type_icon.svg",
    "soft-overwrite": "overwrite_type_icon.svg",
    "hard-overwrite": "overwrite_type_icon.svg",
    "extract": "extract_type_icon.svg",
    "soft-extract": "extract_type_icon.svg",
    "hard-extract": "extract_type_icon.svg",
    "info": "info_type_icon.svg",
}
_MAX_SUMMARY_AFFECTED_FILES = 4
_OPERATION_LABEL_KEYS = {
    "patch": "ui.mod_editor_type_patch",
    "overwrite": "ui.mod_editor_type_overwrite",
    "soft-overwrite": "ui.mod_editor_type_soft_overwrite",
    "hard-overwrite": "ui.mod_editor_type_hard_overwrite",
    "extract": "ui.mod_editor_type_extract",
    "soft-extract": "ui.mod_editor_type_soft_extract",
    "hard-extract": "ui.mod_editor_type_hard_extract",
    "info": "ui.mod_editor_type_info",
}


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
    _size_ready = pyqtSignal(str, int)

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
        self._is_active = False
        self._current_mod_folder = None
        self._current_readme_files = []
        self._mod_size_cache = {}
        self._size_threads = {}
        self._cache_lock = threading.Lock()
        self._operation_path_tooltips: dict[str, str] = {}
        self._operation_config: dict[str, object] | None = None
        self._operation_leaves: list[tuple[tuple[str, ...], Mapping[str, object]]] = []
        self._showing_all_operations = False
        self._size_ready.connect(self._on_size_computed)
        self.setObjectName("summaryPanel")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAutoFillBackground(True)
        self._build_ui()

    def _get_config(self):
        return getattr(self._app_state, "local_config", None)

    def _layout_scale(self) -> float:
        return get_card_layout_scale(self._get_config())

    def _start_folder_size_computation(self, mod_folder: str) -> None:
        """Measure a mod folder off the GUI thread; the result comes back through a signal."""
        with self._cache_lock:
            if mod_folder in self._mod_size_cache or mod_folder in self._size_threads:
                return
            thread = threading.Thread(
                target=self._compute_folder_size_background,
                args=(mod_folder,),
                daemon=True,
            )
            self._size_threads[mod_folder] = thread
        thread.start()

    def _compute_folder_size_background(self, mod_folder: str):
        """Runs on a plain Python thread, so it must only touch Qt through a signal."""
        try:
            total = sum(
                os.path.getsize(os.path.join(r, f))
                for r, _, files in os.walk(mod_folder)
                for f in files
            )
            with self._cache_lock:
                self._mod_size_cache[mod_folder] = total
            self._size_ready.emit(mod_folder, total)
        except RuntimeError:
            logger.debug("ModSummaryPanel: panel was deleted before the size arrived")
        except Exception as e:
            logger.debug(
                f"ModSummaryPanel: failed to calculate mod folder size for {mod_folder}: {e}",
                exc_info=True,
            )
        finally:
            with self._cache_lock:
                self._size_threads.pop(mod_folder, None)

    def _on_size_computed(self, mod_folder: str, size: int):
        """Called on main thread when size computation completes."""
        if mod_folder == self._current_mod_folder:
            self._update_metadata(self._current_mod, mod_folder)
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
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        cast(QWidget, self._scroll.viewport()).setObjectName("summaryViewport")
        cast(QWidget, self._scroll.viewport()).setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
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
        actions.setSpacing(8)
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

        self._state_label = QLabel()
        self._state_label.setObjectName("summaryInfoBlock")
        self._state_label.setWordWrap(True)
        self._state_label.hide()
        cl.addWidget(self._state_label)

        self._data_label = QLabel()
        self._data_label.setObjectName("summaryInfoBlock")
        self._data_label.setWordWrap(True)
        self._data_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._data_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._data_label.linkHovered.connect(self._on_operation_path_hover)
        cl.addWidget(self._data_label)

        self._all_operations_title = QLabel()
        self._all_operations_title.setObjectName("summaryOperationListTitle")
        self._all_operations_title.hide()
        cl.addWidget(self._all_operations_title)

        self._operations_tree = QTreeWidget()
        self._operations_tree.setObjectName("summaryOperationsTree")
        self._operations_tree.setColumnCount(3)
        self._operations_tree.setRootIsDecorated(False)
        self._operations_tree.setUniformRowHeights(True)
        self._operations_tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._operations_tree.setAlternatingRowColors(False)
        self._operations_tree.setMinimumHeight(180)
        self._operations_tree.setMaximumHeight(280)
        self._operations_tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._operations_tree.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._operations_tree.hide()
        cl.addWidget(self._operations_tree)

        self._operations_toggle = QPushButton()
        self._operations_toggle.setObjectName("summaryOperationsToggle")
        self._operations_toggle.clicked.connect(self._toggle_all_operations)
        self._operations_toggle.hide()
        cl.addWidget(self._operations_toggle, 0, Qt.AlignmentFlag.AlignLeft)

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
            cast(QWidget, self._scroll.viewport()).setAutoFillBackground(True)
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
        self._current_readme_files = []
        self._operation_config = None
        self._operation_leaves = []
        self._showing_all_operations = False
        self._operations_tree.clear()
        self._operations_tree.hide()
        self._all_operations_title.hide()
        self._operations_toggle.hide()
        self._playtime_widget.hide()
        self._readme_button.hide()
        with self._cache_lock:
            self._mod_size_cache.clear()
            self._size_threads.clear()
        self._empty_label.show()
        self._scroll.hide()

    def show_mod(self, mod_data, mod_folder=None, is_active=False, relation_issue=None):
        self._showing_all_operations = False
        self._operation_config = None
        self._operation_leaves = []
        self._operations_tree.clear()
        self._current_mod = mod_data
        self._current_mod_folder = self._resolve_mod_folder(mod_data, mod_folder)
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
        self._update_relation_issue(relation_issue)
        self._populate_file_info(mod_data, self._current_mod_folder)
        self._update_playtime(mod_data)
        self._update_action_visibility(mod_data, self._current_mod_folder)
        self.update_use_button_state(is_active)
        self.apply_theme()

    def _update_relation_issue(self, relation_issue) -> None:
        if not relation_issue:
            self._state_label.hide()
            return
        code, related_id = relation_issue
        tooltip_keys = {
            "dependency_missing": "tooltips.dependency_missing",
            "dependency_inactive": "tooltips.dependency_inactive",
            "dependency_relation_unsatisfied": "tooltips.dependency_order",
            "dependency_cycle": "tooltips.dependency_cycle",
            "conflict_active": "tooltips.conflict_active",
        }
        color = "#F44336" if code == "dependency_cycle" else "#FF9800"
        self._state_label.setText(
            f"<span style='color:{color};'>{html.escape(tr(tooltip_keys.get(code, 'tooltips.dependency_order'), mod_id=related_id))}</span>"
        )
        self._state_label.show()

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
            any(not button.isHidden() for button in self._action_buttons.values())
        )
        self._readme_button.setVisible(is_local_mod and bool(self._current_readme_files))

    def _update_metadata(self, mod_data, mod_folder):
        config = self._get_config()
        tc = get_theme_color(config, "main_text") if config else DEFAULT_COLORS["main_text"]
        sc = (
            get_theme_color(config, "secondary_text")
            if config
            else DEFAULT_COLORS["secondary_text"]
        )
        parts = []
        authors = format_mod_authors(getattr(mod_data, "authors", []))
        if authors:
            parts.append(
                f"<span style='color:{tc}'>{tr('ui.authors_label')}</span> <span style='color:{sc}'>{authors}</span>"
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
                f"<span style='color:{tc}'>{tr('ui.added_label')}</span> <span style='color:{sc}'>{format_stored_date(added)}</span>"
            )
        updated = getattr(mod_data, "last_updated", None)
        if updated:
            parts.append(
                f"<span style='color:{tc}'>{tr('ui.updated_label')}</span> <span style='color:{sc}'>{format_stored_date(updated)}</span>"
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
                self._start_folder_size_computation(mod_folder)
                parts.append(
                    f"<span style='color:{tc}'>{tr('ui.size_label')}</span> <span style='color:{sc}'>...</span>"
                )

        metadata_text = "<br>".join(parts)
        self._meta_label.setText(metadata_text)

    def _populate_file_info(self, mod_data, mod_folder):
        self._operation_path_tooltips.clear()
        self._data_label.setToolTip("")
        operation_config = self._load_operation_config(mod_folder)
        if operation_config is not None:
            self._populate_operation_file_info(operation_config)
            return
        self._operation_config = None
        self._operation_leaves = []
        self._showing_all_operations = False
        self._operations_tree.clear()
        self._operations_tree.hide()
        self._all_operations_title.hide()
        self._operations_toggle.hide()
        self._data_label.show()
        data_text = f"<span style='color:{get_theme_color(self._get_config(), 'secondary_text', DEFAULT_COLORS['secondary_text']) if self._get_config() else DEFAULT_COLORS['secondary_text']}'>{tr('ui.no_data_files')}</span>"
        self._data_label.setText(data_text)
        self._extra_label.hide()

    @staticmethod
    def _load_operation_config(mod_folder: str | None) -> dict[str, object] | None:
        if not mod_folder:
            return None
        try:
            config = load_mod_config(os.path.join(mod_folder, "mod_config.json"))
        except (ModConfigValidationError, OSError):
            return None
        return config if config.get("config_version") == MOD_CONFIG_VERSION else None

    def _populate_operation_file_info(self, config_data: dict[str, object]) -> None:
        config = self._get_config()
        tc = get_theme_color(config, "main_text") if config else DEFAULT_COLORS["main_text"]
        sc = get_theme_color(config, "secondary_text") if config else DEFAULT_COLORS["secondary_text"]
        files = config_data.get("files")
        self._operation_config = config_data
        self._operation_leaves = (
            list(iter_mod_config_leaves(files))
            if isinstance(files, list)
            else []
        )
        self._operation_path_tooltips.clear()
        self._data_label.setToolTip("")
        if not self._operation_leaves:
            self._data_label.show()
            self._data_label.setText(
                f"<span style='color:{tc}; font-weight:600;'>{tr('ui.mod_summary_changes')}</span>"
                f"<br><br><span style='color:{sc}'>-</span>"
            )
            self._operations_tree.clear()
            self._operations_tree.hide()
            self._all_operations_title.hide()
            self._operations_toggle.hide()
            self._extra_label.hide()
            return

        self._populate_operation_summary(tc, sc)
        self._operations_toggle.setText(
            tr(
                "ui.mod_summary_show_summary"
                if self._showing_all_operations
                else "ui.mod_summary_show_all"
            )
        )
        self._operations_toggle.show()
        if self._showing_all_operations:
            self._data_label.hide()
            self._all_operations_title.setText(
                tr(
                    "ui.mod_summary_all_operations",
                    count=len(self._operation_leaves),
                )
            )
            self._all_operations_title.show()
            self._populate_all_operations_tree()
            self._operations_tree.show()
        else:
            self._data_label.show()
            self._all_operations_title.hide()
            self._operations_tree.hide()
        self._extra_label.hide()

    def _populate_operation_summary(self, text_color: str, secondary_color: str) -> None:
        operation_counts: dict[str, int] = {}
        affected_files: list[tuple[int, str]] = []
        seen_targets: set[str] = set()
        for index, (_group_path, leaf) in enumerate(self._operation_leaves, start=1):
            operation = str(leaf.get("type", "info"))
            operation_counts[operation] = operation_counts.get(operation, 0) + 1
            target = leaf.get("target")
            if isinstance(target, str) and target not in seen_targets:
                seen_targets.add(target)
                affected_files.append((index, target))

        lines = []
        for operation, count in operation_counts.items():
            label = tr(_OPERATION_LABEL_KEYS.get(operation, "ui.mod_editor_type_info"))
            lines.append(
                f"{self._operation_icon_html(operation, text_color)}&nbsp;"
                f"<span style='color:{text_color}'>{html.escape(tr('ui.mod_summary_operation_count', operation=label, count=count))}</span>"
            )
        if affected_files:
            lines.append(
                f"<br><span style='color:{text_color}; font-weight:600;'>{tr('ui.mod_summary_affected_files')}</span>"
            )
            planned = self._planned_operation_paths(
                self._operation_config or {},
                [
                    (index, *self._operation_leaves[index - 1])
                    for index, _target in affected_files[:_MAX_SUMMARY_AFFECTED_FILES]
                ],
            )
            for index, target in affected_files[:_MAX_SUMMARY_AFFECTED_FILES]:
                target_key = f"target_{index}"
                target_path = planned.get(index, {}).get("target")
                self._operation_path_tooltips[target_key] = target_path or target
                lines.append(
                    f"• {self._operation_path_link(target_key, target, text_color)}"
                )
            hidden_count = len(affected_files) - _MAX_SUMMARY_AFFECTED_FILES
            if hidden_count > 0:
                lines.append(
                    f"<span style='color:{secondary_color}'>{html.escape(tr('ui.mod_summary_more_files', count=hidden_count))}</span>"
                )

        self._data_label.setText(
            f"<span style='color:{text_color}; font-weight:600;'>{tr('ui.mod_summary_changes')}</span>"
            f"<br><br>{'<br>'.join(lines)}"
        )

    def _populate_all_operations_tree(self) -> None:
        planned = self._planned_operation_paths(
            self._operation_config or {},
            [
                (index, group_path, leaf)
                for index, (group_path, leaf) in enumerate(
                    self._operation_leaves, start=1
                )
            ],
        )
        self._operations_tree.setUpdatesEnabled(False)
        self._operations_tree.clear()
        self._operations_tree.setHeaderLabels(
            [
                tr("ui.mod_editor_type"),
                tr("ui.mod_editor_source"),
                tr("ui.mod_editor_target"),
            ]
        )
        items = []
        for index, (_group_path, leaf) in enumerate(self._operation_leaves, start=1):
            operation = str(leaf.get("type", "info"))
            source = str(leaf.get("source", ""))
            target = str(leaf.get("target", ""))
            item = QTreeWidgetItem(
                [
                    tr(_OPERATION_LABEL_KEYS.get(operation, "ui.mod_editor_type_info")),
                    source,
                    target,
                ]
            )
            item.setToolTip(1, planned.get(index, {}).get("source") or source)
            item.setToolTip(2, planned.get(index, {}).get("target") or target)
            items.append(item)
        self._operations_tree.addTopLevelItems(items)
        self._operations_tree.setColumnWidth(0, 130)
        self._operations_tree.setColumnWidth(1, 220)
        self._operations_tree.setUpdatesEnabled(True)

    def _toggle_all_operations(self) -> None:
        if self._operation_config is None:
            return
        self._showing_all_operations = not self._showing_all_operations
        self._populate_operation_file_info(self._operation_config)

    @staticmethod
    def _operation_icon_html(operation: str, color: str) -> str:
        icon_name = _OPERATION_ICON_FILES.get(operation)
        if not icon_name:
            return ""
        try:
            with open(resource_path(f"assets/icons/{icon_name}"), encoding="utf-8") as icon_file:
                svg = re.sub(r"#[0-9A-Fa-f]{6}", color, icon_file.read())
        except OSError:
            return ""
        icon_data = base64.b64encode(svg.encode()).decode("ascii")
        return f"<img src='data:image/svg+xml;base64,{icon_data}' width='18' height='18'>"

    def _on_operation_path_hover(self, link: str) -> None:
        self._data_label.setToolTip(self._operation_path_tooltips.get(link, ""))

    def _planned_operation_paths(
        self,
        config_data: dict[str, object],
        leaves: list[tuple[int, tuple[str, ...], Mapping[str, object]]],
    ) -> dict[int, dict[str, str]]:
        mod_folder = self._current_mod_folder
        if not mod_folder:
            return {}
        game_mode = getattr(self._app_state, "game_mode", None)
        try:
            runtime_config = self._get_config() or {}
            game_path = game_mode.get_game_path(runtime_config) if game_mode else None
            game_data_path = game_mode.get_data_path(runtime_config) if game_mode else None
            context = ModPathContext.create(
                mod_path=mod_folder,
                game_path=game_path,
                game_data_path=game_data_path,
                user_path=Path.home(),
            )
            placeholders = config_data.get("placeholders", {})
            if not isinstance(placeholders, Mapping):
                placeholders = {}
            game = str(config_data.get("game", "") or "")
            planned = {}
            for index, _group_path, leaf in leaves:
                source = resolve_operation_path(
                    str(leaf["source"]),
                    context=context,
                    custom_placeholders=placeholders,
                    game=game,
                )
                target = (
                    resolve_operation_path(
                        str(leaf["target"]),
                        context=context,
                        custom_placeholders=placeholders,
                        is_target=True,
                        game=game,
                    )
                    if isinstance(leaf.get("target"), str)
                    else None
                )
                planned[index] = {
                    "source": self._resolved_operation_path(source) if source else "",
                    "target": self._resolved_operation_path(target) if target else "",
                }
            return planned
        except (AttributeError, ModConfigValidationError, OSError, TypeError, ValueError):
            return {}

    @staticmethod
    def _resolved_operation_path(value: Path | ArchiveVirtualPath) -> str:
        if isinstance(value, ArchiveVirtualPath):
            member = value.member.strip("/")
            return f"{value.archive}{'/' + member if member else ''}{'/' if value.directory else ''}"
        return str(value)

    def _operation_path_link(self, key: str, path: str, color: str) -> str:
        return (
            f"<a href='{html.escape(key, quote=True)}' style='color:{color}; "
            f"text-decoration:none;'>{self._wrap_display_text(path)}</a>"
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
    def _wrap_display_text(text: str) -> str:
        escaped = html.escape(str(text or ""))
        for separator in ("/", "_", "-", ".", ")", "]"):
            escaped = escaped.replace(separator, f"{separator}&#8203;")
        for separator in ("(", "["):
            escaped = escaped.replace(separator, f"&#8203;{separator}")
        return escaped

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
        self._is_active = bool(is_active)
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
            self._all_operations_title,
            f"color: {text_color}; font-weight: 600; padding: 2px 2px 0 2px;",
            cache_attr="_operations_title_ss_cache",
        )
        apply_stylesheet_if_changed(
            self._operations_tree,
            f"""
            QTreeWidget#summaryOperationsTree {{
                background-color: {meta_bg}; color: {text_color};
                border: 2px solid {border}; border-radius: {min(br, 14)}px;
                outline: none;
            }}
            QTreeWidget#summaryOperationsTree::item {{ min-height: 26px; padding: 3px 6px; }}
            QTreeWidget#summaryOperationsTree::item:hover {{ background-color: {button_hover}; }}
            QHeaderView::section {{
                background-color: {elements}; color: {secondary};
                border: none; border-bottom: 1px solid {border}; padding: 5px 6px;
                font-weight: 600;
            }}
            """,
            cache_attr="_operations_tree_ss_cache",
        )
        apply_stylesheet_if_changed(
            self._operations_toggle,
            build_button_style(
                "summaryOperationsToggle",
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
            cache_attr="_operations_toggle_ss_cache",
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
            self._update_metadata(self._current_mod, self._current_mod_folder)
            self._populate_file_info(self._current_mod, self._current_mod_folder)
            self._update_playtime(self._current_mod)
        self.update_use_button_state(self._is_active)

    def refresh_theme(self):
        self._current_readme_files = find_mod_readme_files(self._current_mod_folder)
        self.apply_theme()

    def update_labels_text(self):
        self._empty_label.setText(tr("ui.select_mod"))
        self.update_use_button_state(self._is_active)
        self._readme_button.setText(tr("dialogs.info"))
        for icon_name, tooltip_key, _ in self._ACTION_DEFS:
            if icon_name in self._action_buttons:
                self._action_buttons[icon_name].setToolTip(tr(tooltip_key))
        if self._current_mod:
            self._update_metadata(self._current_mod, self._current_mod_folder)
            self._description_label.setText(getattr(self._current_mod, "description", "") or tr("ui.no_description"))
            self._update_action_visibility(self._current_mod, self._current_mod_folder)
            self._update_playtime(self._current_mod)
            self._populate_file_info(self._current_mod, self._current_mod_folder)

    def relocalize_ui(self) -> None:
        self.update_labels_text()

    def rescale_ui(self) -> None:
        self.apply_theme()
