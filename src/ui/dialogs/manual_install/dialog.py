"""Create one current-format local mod from otherwise unrecognised files."""

from __future__ import annotations

import logging
import os
import posixpath
import shutil
import uuid
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast, override

from PyQt6.QtCore import (
    QCoreApplication,
    QEvent,
    QSignalBlocker,
    Qt,
    pyqtSlot,
)
from PyQt6.QtGui import QBrush, QCloseEvent, QColor, QHelpEvent, QHoverEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.config import (
    CURRENT_PLATFORM,
    MOD_DOCUMENTATION_EXTENSIONS,
)
from models.game_modes import get_game, get_visible_game_entries
from services.localization_service import tr
from ui.common.dialog_theme import (
    DynamicDialog,
    DynamicMessageBox,
    get_dialog_theme_values,
)
from ui.common.localized_label import LocalizedLabel
from ui.dialogs.custom_game_dialog import CustomGameDialog, run_custom_game_dialog
from ui.dialogs.manual_install.detection import (
    default_action,
    scan_files,
    scan_import_files,
)
from ui.dialogs.manual_install.styling import apply_manual_install_theme
from ui.dialogs.manual_install.workers import (
    DetectionThread,
    MetadataThread,
    SaveThread,
)
from ui.dialogs.mod.readme_dialog import ReadmeFileViewer
from ui.utils.gui_thread import find_attribute
from ui.utils.thread_lifetime import retire_qthread
from utils.file_utils import remove_archive_extension
from utils.mod.archive import archive_format
from utils.mod.config import (
    MOD_CONFIG_MAX_DISPLAY_CHARS,
    MOD_CONFIG_VERSION,
    is_direct_absolute_path,
    validate_mod_config,
)
from utils.mod.operation_plan import (
    ModPathContext,
    build_mod_operation_plan,
    portable_operation_path,
    resolve_operation_path,
)
from utils.mod.tags import normalize_tags
from utils.native_integration import (
    get_existing_directory,
    get_open_file_name,
    open_path_native,
)
from utils.path_utils import (
    colored_icon,
    resolve_execution_runtime,
    resolve_game_executable,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_INVALID_COLOR = QColor("#F44336")
_ACTIONS = (
    (None, "ui.manual_install_unconfigured"),
    ("", "ui.manual_install_skip"),
    ("overwrite", "ui.manual_install_replace"),
    ("patch", "ui.manual_install_patch"),
    ("info", "ui.manual_install_info"),
    ("extract", "ui.manual_install_extract"),
)


class _ActionDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):  # noqa: N802
        editor = QComboBox(parent)
        dialog = cast(ManualModInstallDialog, cast(QWidget, self.parent()).window())
        relative = index.siblingAtColumn(0).data(Qt.ItemDataRole.UserRole)
        selected = dialog._selected_files()
        for action, key in dialog._available_actions(
            selected if relative in selected else [relative]
        ):
            editor.addItem(tr(key), action)
        editor.activated.connect(lambda _index: self.commitData.emit(editor))
        return editor

    def setEditorData(self, editor, index):  # noqa: N802
        editor = cast(QComboBox, editor)
        editor.setCurrentIndex(
            max(0, editor.findData(index.data(Qt.ItemDataRole.UserRole)))
        )

    def setModelData(self, editor, model, index):  # noqa: N802
        editor = cast(QComboBox, editor)
        if model is None:
            return
        model.setData(index, editor.currentData(), Qt.ItemDataRole.UserRole)
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class _SourceDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):  # noqa: N802
        return None


class ManualModInstallDialog(DynamicDialog):
    """Assign import files before saving one current-format local mod."""

    def __init__(
        self,
        parent,
        prepared_files_path: str,
        gamebanana_metadata: dict | None = None,
        source_file_path: str | None = None,
        initial_game_type: str | None = None,
        *,
        target_mods_dir: str | None = None,
        auto_install: bool = False,
    ) -> None:
        super().__init__(parent)
        self.prepared_files_path = prepared_files_path
        self.auto_install = auto_install
        self._auto_started = False
        self._detection_error = ""
        self.gamebanana_metadata = dict(gamebanana_metadata or {})
        self._metadata_thread: MetadataThread | None = None
        self._detection_thread: DetectionThread | None = None
        self._save_thread: SaveThread | None = None
        self._cancelled = False
        self._checking_save = False
        self._configure_after_save = False
        self._saved_config: dict[str, object] = {}
        self._metadata_initial_name = ""
        self._assignments: dict[str, dict] = {}
        self._touched: set[str] = set()
        self._items: dict[str, QTreeWidgetItem] = {}
        self.source_file_path = source_file_path
        self.initial_game_type = initial_game_type
        self.target_mods_dir = target_mods_dir
        self.temp_dir_to_cleanup: str | None = None
        self.app_state = find_attribute(parent, "app_state")
        self._settings_service = find_attribute(parent, "settings_service")
        self._game_registry = find_attribute(parent, "game_registry_service")
        self.all_files = self._scan_files()
        packed = [
            Path(source)
            for source, _relative in self.all_files
            if Path(source).is_dir()
        ]
        self._source_nodes = {relative: source for source, relative in self.all_files}
        self._source_nodes.update(
            (relative, source)
            for source, relative in scan_files(
                Path(prepared_files_path), include_directories=True
            )
            if relative.endswith("/")
            and not any(Path(source).is_relative_to(folder) for folder in packed)
        )
        self._source_nodes = dict(
            sorted(self._source_nodes.items(), key=lambda item: item[0].casefold())
        )
        screen = self.screen()
        if screen is None:
            raise RuntimeError("manual installation requires a screen")
        available = screen.availableGeometry()
        self.resize(
            min(1105, available.width() - 40), min(680, available.height() - 80)
        )
        self.setMinimumSize(
            min(720, available.width() - 40), min(480, available.height() - 80)
        )
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        self._build_ui()
        self._populate()
        self.relocalize_ui()
        self.finished.connect(self._stop_metadata_load)
        self.finished.connect(self._stop_detection)
        self.finished.connect(self._stop_save)
        self.finished.connect(self._dispose_document)
        self.game_combo.currentIndexChanged.connect(self._start_detection)
        self._start_detection()
        if self.gamebanana_metadata.get("mod_id"):
            self._metadata_initial_name = self.name_edit.text()
            self._metadata_thread = MetadataThread(self.gamebanana_metadata)
            self._metadata_thread.result_ready.connect(self._on_metadata_loaded)
            self.relocalize_ui()
            self._metadata_thread.start()

    def _scan_files(self) -> list[tuple[str, str]]:
        return scan_import_files(Path(self.prepared_files_path))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        self.tabs = QTabWidget(self)
        installation = QWidget(self.tabs)
        installation_layout = QVBoxLayout(installation)
        installation_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(installation)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        installation_layout.addWidget(scroll)
        settings = QWidget(scroll)
        scroll.setWidget(settings)
        content = QVBoxLayout(settings)
        content.setContentsMargins(8, 8, 8, 8)
        content.setSpacing(12)
        self.tabs.addTab(installation, tr("ui.manual_install_tab_installation"))
        root.addWidget(self.tabs, 1)
        form = QFormLayout()
        self.game_combo = QComboBox(self)
        self._fill_game_combo()
        self.add_game_button = QPushButton(self)
        self.add_game_button.setObjectName("manualInstallAddGameButton")
        self.add_game_button.setVisible(
            self._game_registry is not None and self.app_state is not None
        )
        self.add_game_button.clicked.connect(self._add_game)
        game_row = QHBoxLayout()
        game_row.setSpacing(8)
        game_row.addWidget(self.game_combo, 1)
        game_row.addWidget(self.add_game_button)
        self.game_label = QLabel(self)
        form.addRow(self.game_label, game_row)
        self.name_edit = QLineEdit(self)
        self.name_edit.setMaxLength(MOD_CONFIG_MAX_DISPLAY_CHARS)
        self.name_label = QLabel(self)
        form.addRow(self.name_label, self.name_edit)
        content.addLayout(form)
        self.name_edit.editingFinished.connect(self._validate)
        summary = QHBoxLayout()
        summary.setSpacing(8)
        self.files_summary_label = QLabel(self)
        self.files_summary_label.setObjectName("manualInstallHint")
        self.files_summary_label.setWordWrap(True)
        summary.addWidget(self.files_summary_label, 1)
        self.selection_hint_label = QLabel(self)
        self.selection_hint_label.setWordWrap(True)
        self.selection_hint_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        summary.addWidget(self.selection_hint_label, 1)
        content.addLayout(summary)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText(tr("ui.manual_install_filter"))
        self.filter_edit.textChanged.connect(self._filter_files)
        toolbar.addWidget(self.filter_edit, 1)
        self.action_combo = QComboBox(self)
        self.action_combo.activated.connect(self._set_selected_action)
        toolbar.addWidget(self.action_combo)
        self.browse_button = QToolButton(self)
        self.browse_button.setText(tr("ui.manual_install_browse"))
        self.browse_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.browse_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        browse_menu = QMenu(self.browse_button)
        browse_menu.addAction(
            tr("ui.file"), lambda: self._browse_selected(folder=False)
        )
        browse_menu.addAction(
            tr("ui.folder"), lambda: self._browse_selected(folder=True)
        )
        self.browse_button.setMenu(browse_menu)
        self.browse_button.clicked.connect(lambda: self._browse_selected())
        toolbar.addWidget(self.browse_button)
        for widget in (self.filter_edit, self.action_combo, self.browse_button):
            widget.setSizePolicy(
                widget.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Minimum
            )
        content.addLayout(toolbar)
        self.sources = QTreeWidget(self)
        self.sources.setColumnCount(3)
        self.sources.setHeaderLabels(
            [
                tr("ui.manual_install_file"),
                tr("ui.manual_install_action"),
                tr("ui.manual_install_target"),
            ]
        )
        self.sources.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.sources.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.sources.setUniformRowHeights(True)
        self.sources.setAnimated(False)
        self.sources.setMinimumHeight(self.sources.fontMetrics().height() * 5)
        self.sources.setAlternatingRowColors(False)
        self.sources.setEditTriggers(
            QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.sources.setItemDelegateForColumn(1, _ActionDelegate(self.sources))
        self.sources.setItemDelegateForColumn(0, _SourceDelegate(self.sources))
        cast(QHeaderView, self.sources.header()).setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive
        )
        cast(QHeaderView, self.sources.header()).setSectionResizeMode(
            1, QHeaderView.ResizeMode.Interactive
        )
        cast(QHeaderView, self.sources.header()).setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.sources.setColumnWidth(0, 280)
        self.sources.setColumnWidth(1, 230)
        self.sources.itemSelectionChanged.connect(self._update_selection)
        self.sources.itemChanged.connect(self._item_changed)
        self.sources.itemDoubleClicked.connect(self._source_activated)
        content.addWidget(self.sources, 1)
        self._build_documents()
        self.status_label = LocalizedLabel(self)
        self.status_label.setWordWrap(True)
        status_scroll = QScrollArea(self)
        self._status_scroll = status_scroll
        status_scroll.setWidgetResizable(True)
        status_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        status_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        status_scroll.setMinimumHeight(self.status_label.fontMetrics().height() * 2 + 8)
        status_scroll.setMaximumHeight(self.status_label.fontMetrics().height() * 4 + 8)
        status_scroll.setWidget(self.status_label)
        root.addWidget(status_scroll)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.save_button = cast(
            QPushButton, self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        )
        cast(QHBoxLayout, self.buttons.layout()).setSpacing(8)
        self.buttons.accepted.connect(self._on_finish)
        self.buttons.rejected.connect(self.reject)
        self.configure_button = cast(
            QPushButton,
            self.buttons.addButton(
                tr("ui.manual_install_configure"),
                QDialogButtonBox.ButtonRole.ActionRole,
            ),
        )
        for button in (self.save_button, self.configure_button):
            button.setAttribute(Qt.WidgetAttribute.WA_Hover)
            button.installEventFilter(self)
        self.configure_button.clicked.connect(
            lambda _checked: self._on_finish(configure=True)
        )
        footer = QHBoxLayout()
        self.hide_configured = QCheckBox(tr("ui.manual_install_hide_configured"), self)
        self.hide_configured.setChecked(
            bool(
                (getattr(self.app_state, "local_config", {}) or {}).get(
                    "manual_install_hide_configured", False
                )
            )
        )
        self.hide_configured.toggled.connect(self._hide_configured_changed)
        footer.addWidget(self.hide_configured)
        footer.addStretch()
        footer.addWidget(self.buttons)
        root.addLayout(footer)
        apply_manual_install_theme(self)

    def _build_documents(self) -> None:
        page = QWidget(self.tabs)
        self._documents_layout = QVBoxLayout(page)
        self._documents_layout.setContentsMargins(8, 8, 8, 8)
        self._documents_layout.setSpacing(12)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.document_combo = QComboBox(page)
        self.document_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.document_combo.setMinimumContentsLength(16)
        label = QLabel(tr("ui.manual_install_file"), page)
        self.document_label = label
        label.setBuddy(self.document_combo)
        row.addWidget(label)
        row.addWidget(self.document_combo, 1)
        self.open_document_button = QPushButton(
            tr("ui.manual_install_open_external"), page
        )
        self.open_document_button.clicked.connect(self._open_document)
        row.addWidget(self.open_document_button)
        for widget in (self.document_combo, self.open_document_button):
            widget.setSizePolicy(
                widget.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Minimum
            )
        self._documents_layout.addLayout(row)
        self._document_hint = QLabel(page)
        self._document_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._document_hint.setWordWrap(True)
        self._documents_layout.addWidget(self._document_hint, 1)
        self._document_viewer: ReadmeFileViewer | None = None
        files = scan_files(Path(self.prepared_files_path))
        for source, relative in sorted(
            files,
            key=lambda item: (
                Path(item[0]).suffix.casefold() not in MOD_DOCUMENTATION_EXTENSIONS,
                item[1].casefold(),
            ),
        ):
            self.document_combo.addItem(relative, source)
        self.document_combo.setEnabled(bool(files))
        self.open_document_button.setEnabled(bool(files))
        self.tabs.addTab(page, tr("ui.manual_install_tab_documents"))
        self.document_combo.currentIndexChanged.connect(self._show_document)
        self.tabs.currentChanged.connect(self._show_document)

    def _dispose_document(self) -> None:
        if viewer := self._document_viewer:
            self._document_viewer = None
            viewer.dispose()
            self._documents_layout.removeWidget(viewer)
            viewer.deleteLater()

    def _show_document(self) -> None:
        if self.tabs.currentIndex() != 1:
            return
        source = self.document_combo.currentData()
        self.document_combo.setToolTip(self.document_combo.currentText())
        if self._document_viewer and self._document_viewer.file_path == source:
            return
        self._dispose_document()
        readable = (
            source and Path(source).suffix.casefold() in MOD_DOCUMENTATION_EXTENSIONS
        )
        self._document_hint.setVisible(not readable)
        if readable:
            viewer = ReadmeFileViewer(source, self.tabs.widget(1))
            self._document_viewer = viewer
            self._documents_layout.addWidget(viewer, 1)
            viewer.load_content()
        else:
            self._document_hint.setText(
                tr(
                    "ui.manual_install_external_hint"
                    if source
                    else "dialogs.no_readme_files"
                )
            )

    def _open_document(self) -> None:
        source = self.document_combo.currentData()
        if source:
            path = Path(source)
            try:
                opened = (
                    path.is_file()
                    and path.resolve().is_relative_to(
                        Path(self.prepared_files_path).resolve()
                    )
                    and open_path_native(str(path))
                )
            except OSError:
                opened = False
            if not opened:
                self.status_label.set_localized_text("ui.manual_install_open_failed")

    def _source_activated(self, item, column: int) -> None:
        if column == 2:
            self._browse_selected()
        elif column == 1:
            self.sources.editItem(item, column)
        elif relative := item.data(0, Qt.ItemDataRole.UserRole):
            source = next(
                (source for source, name in self.all_files if name == relative), None
            )
            index = self.document_combo.findData(source)
            if index >= 0:
                self.document_combo.setCurrentIndex(index)
                self.tabs.setCurrentIndex(1)

    def _fill_game_combo(self, selected: str = "") -> None:
        with QSignalBlocker(self.game_combo):
            self.game_combo.clear()
            for game in get_visible_game_entries():
                self.game_combo.addItem(game.display_name, game.id)
            self.game_combo.setCurrentIndex(max(0, self.game_combo.findData(selected)))

    def _add_game(self) -> None:
        if self._game_registry is None:
            return
        registry = self._game_registry
        created: list[str] = []
        saved = run_custom_game_dialog(
            CustomGameDialog(self.app_state, parent=self),
            lambda values: created.append(registry.create_custom_game(**values).id),
        )
        if saved:
            self._fill_game_combo(str(self.game_combo.currentData() or ""))
            # Selecting the new game restarts the detection for it.
            self.game_combo.setCurrentIndex(self.game_combo.findData(created[0]))

    def _populate(self) -> None:
        source_name = (
            remove_archive_extension(os.path.basename(self.source_file_path))
            if self.source_file_path
            else Path(self.prepared_files_path).name
        )
        self.name_edit.setText(
            str(self.gamebanana_metadata.get("name") or source_name or "Manual Mod")
        )
        wanted = self.initial_game_type or self.gamebanana_metadata.get("game") or ""
        for index in range(self.game_combo.count()):
            if self.game_combo.itemData(index) == wanted:
                self.game_combo.setCurrentIndex(index)
                break
        self.sources.blockSignals(True)
        folder_icon = colored_icon(
            "folder", get_dialog_theme_values(self.app_state)["main_text"]
        )
        for relative in self._source_nodes:
            parts = PurePosixPath(relative).parts
            parent = self._items.get("/".join(parts[:-1]) + "/")
            item = QTreeWidgetItem(
                [parts[-1], tr("ui.manual_install_unconfigured"), ""]
            )
            (parent.addChild(item) if parent else self.sources.addTopLevelItem(item))
            if relative.endswith("/"):
                item.setIcon(0, folder_icon)
            item.setData(0, Qt.ItemDataRole.UserRole, relative)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self._items[relative] = item
            if (
                getattr(self.app_state, "local_config", {}).get("manual_install_docs_as_info", True)
                and not relative.endswith("/")
                and Path(relative).suffix.casefold() in MOD_DOCUMENTATION_EXTENSIONS
            ):
                self._assignments[relative] = {"type": "info"}
                item.setData(1, Qt.ItemDataRole.UserRole, "info")
                item.setText(1, tr("ui.manual_install_info"))
        self.sources.expandToDepth(0)
        self.sources.blockSignals(False)
        self._update_summary()

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("dialogs.manual_install_title"))
        self.game_label.setText(tr("ui.mod_type_label"))
        self.add_game_button.setToolTip(tr("games.add_custom_title"))
        self.add_game_button.setAccessibleName(tr("games.add_custom_title"))
        self.name_label.setText(tr("ui.mod_name_label"))
        self.document_label.setText(tr("ui.manual_install_file"))
        menu = self.browse_button.menu()
        if menu is not None:
            for action, key in zip(menu.actions(), ("ui.file", "ui.folder"), strict=True):
                action.setText(tr(key))
        self.save_button.setText(
            tr("status.loading" if self._metadata_thread else "ui.manual_install_save")
        )
        self.configure_button.setText(tr("ui.manual_install_configure"))
        cast(
            QPushButton, self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        ).setText(tr("dialogs.cancel"))
        self.filter_edit.setPlaceholderText(tr("ui.manual_install_filter"))
        self.browse_button.setText(tr("ui.manual_install_browse"))
        self.sources.setHeaderLabels(
            [
                tr("ui.manual_install_file"),
                tr("ui.manual_install_action"),
                tr("ui.manual_install_target"),
            ]
        )
        self._update_summary()
        self.tabs.setTabText(0, tr("ui.manual_install_tab_installation"))
        self.tabs.setTabText(1, tr("ui.manual_install_tab_documents"))
        self.open_document_button.setText(tr("ui.manual_install_open_external"))
        modifier = "⌘" if CURRENT_PLATFORM == "Darwin" else "Ctrl"
        self.selection_hint_label.setText(
            tr("ui.manual_install_multiselect_hint", modifier=modifier)
        )
        hint = tr("ui.manual_install_selection_hint", modifier=modifier)
        self.selection_hint_label.setToolTip(hint)
        self.sources.setToolTip(hint)
        self.hide_configured.setText(tr("ui.manual_install_hide_configured"))
        self._update_selection()
        if self._document_hint.isVisible():
            self._document_hint.setText(tr("ui.manual_install_external_hint" if self.document_combo.currentData() else "dialogs.no_readme_files"))
        self.status_label.relocalize_ui()
        if self.name_edit.property("invalid") or any(item.foreground(2).color() == _INVALID_COLOR for item in self._items.values()):
            self._validate()

    def apply_theme(self) -> None:
        apply_manual_install_theme(self)
        icon = colored_icon("folder", get_dialog_theme_values(self.app_state)["main_text"])
        for relative, item in self._items.items():
            if relative.endswith("/"):
                item.setIcon(0, icon)
        self.ensurePolished()
        self.sources.setMinimumHeight(self.sources.fontMetrics().height() * 5)
        height = self.status_label.fontMetrics().height()
        self._status_scroll.setMinimumHeight(height * 2 + 8)
        self._status_scroll.setMaximumHeight(height * 4 + 8)

    @pyqtSlot(dict)
    def _on_metadata_loaded(self, metadata: dict) -> None:
        if self._metadata_thread is None:
            return
        self.gamebanana_metadata.update(metadata)
        if (
            metadata.get("name")
            and self.name_edit.text() == self._metadata_initial_name
        ):
            self.name_edit.setText(str(metadata["name"]))
        self._stop_metadata_load()
        self.relocalize_ui()
        self._auto_install_step()

    def _stop_metadata_load(self) -> None:
        if thread := self._metadata_thread:
            self._metadata_thread = None
            thread.requestInterruption()
            retire_qthread(thread)

    def _context(self) -> ModPathContext:
        game = get_game(str(self.game_combo.currentData() or ""))
        config = getattr(self.app_state, "local_config", {}) or {}
        game_path = game.get_game_path(config) if game else None
        executable = None
        if game and game_path:
            executable = config.get(
                game.get_custom_exec_config_key()
            ) or resolve_game_executable(game_path, game.executable_type)
        return ModPathContext.create(
            mod_path=self.prepared_files_path,
            game_path=game_path,
            game_data_path=game.get_data_path(config) if game else None,
            user_path=Path.home(),
            runtime=resolve_execution_runtime(executable),
        )

    def _start_detection(self) -> None:
        self._stop_detection()
        self._touched.clear()
        self._update_summary()
        self._resume_detection()

    def _resume_detection(self) -> None:
        self.status_label.set_localized_text("ui.manual_install_detecting", completed=0, total=len(self.all_files))
        thread = DetectionThread(
            self.all_files,
            self._context(),
            dict(getattr(self.app_state, "local_config", {}) or {}),
        )
        self._detection_thread = thread
        thread.result_ready.connect(self._detected)
        thread.progress.connect(self._detection_progress)
        thread.start()

    def _stop_detection(self) -> None:
        if thread := self._detection_thread:
            self._detection_thread = None
            thread.requestInterruption()
            retire_qthread(thread)

    @pyqtSlot(int, int)
    def _detection_progress(self, completed: int, total: int) -> None:
        if self.sender() is self._detection_thread:
            self.status_label.set_localized_text("ui.manual_install_detecting", completed=completed, total=total)

    @pyqtSlot(dict, str)
    def _detected(self, assignments: dict, error: str) -> None:
        if self.sender() is not self._detection_thread:
            return
        for relative, entry in assignments.items():
            if relative not in self._touched and (
                entry.get("type") != "info" or relative not in self._assignments
            ):
                self._assign(relative, entry)
        self._detection_error = error
        self._stop_detection()
        self._update_summary()
        if not self._validate():
            self._auto_install_step()
            return
        unconfigured = sum(
            not self._configured(relative) for relative in self._source_nodes
        )
        status = (
            "ui.manual_install_detection_unconfigured"
            if unconfigured
            else "ui.manual_install_detection_done"
        )
        context = self._context()
        if not (context.game_path or context.game_data_path):
            status = "ui.manual_install_no_game"
        self.status_label.set_localized_text(
            "ui.manual_install_detection_failed" if error else status,
            error=error, count=unconfigured,
        )
        self._auto_install_step()

    def _auto_install_step(self) -> None:
        """Hidden run: save once every file is set up, otherwise give up so the user can finish by hand."""
        if (
            not self.auto_install
            or self._auto_started
            or self._detection_thread
            or self._metadata_thread
        ):
            return
        self._auto_started = True
        context = self._context()
        unconfigured = [relative for relative in self._source_nodes if not self._configured(relative)]
        reason = (
            f"detection failed: {self._detection_error}" if self._detection_error
            else "no game folder is set" if not (context.game_path or context.game_data_path)
            else "the file list is not valid" if self.app_state is None or not self._validate()
            else f"{len(unconfigured)} of {len(self._source_nodes)} files are not set up" if unconfigured
            else "it has no file that changes the game" if all(
                self._assignments[relative].get("type") == "info" for relative in self._configured_sources()
            )
            else ""
        )
        if reason:
            logger.info("Automatic installation declined: %s", reason)
            self.reject()
            return
        self._on_finish()

    def _assign(self, relative: str, entry: dict) -> None:
        self._assignments[relative] = dict(entry)
        item = self._items[relative]
        with QSignalBlocker(self.sources):
            action = entry.get("type")
            item.setData(1, Qt.ItemDataRole.UserRole, action)
            item.setText(1, tr(dict(_ACTIONS)[action]))
            item.setText(2, entry.get("target", ""))
            item.setToolTip(2, entry.get("target", ""))
            for column in range(3):
                item.setForeground(column, QBrush())

    def _selected_files(self) -> list[str]:
        selected = {
            item.data(0, Qt.ItemDataRole.UserRole)
            for item in self.sources.selectedItems()
            if not item.isHidden()
        }
        return [
            relative
            for relative in self._source_nodes
            if relative in selected
            and not any(parent in selected for parent in self._parents(relative))
        ]

    @staticmethod
    def _parents(relative: str) -> list[str]:
        parts = PurePosixPath(relative).parts
        return ["/".join(parts[:index]) + "/" for index in range(1, len(parts))]

    def _available_actions(self, selected):
        allowed = {action for action, _key in _ACTIONS}
        for relative in selected:
            source = self._source_nodes[relative]
            allowed.intersection_update(
                {None, "", "overwrite", "extract"}
                if relative.endswith("/")
                or (archive_format(source) and not relative.endswith(".g3mpatch"))
                else {None, "", "overwrite", "patch"}
                | (
                    {"info"}
                    if Path(relative).suffix.casefold() in MOD_DOCUMENTATION_EXTENSIONS
                    else set()
                )
            )
        return [(action, key) for action, key in _ACTIONS if action in allowed]

    def _update_selection(self) -> None:
        selected = self._selected_files()
        with QSignalBlocker(self.action_combo):
            self.action_combo.clear()
            self.action_combo.addItem(tr("ui.manual_install_action"), None)
            for action, key in self._available_actions(selected):
                self.action_combo.addItem(tr(key), action)
        self.action_combo.setEnabled(bool(selected))
        self.browse_button.setEnabled(bool(selected))

    @staticmethod
    def _with_action(entry: dict, action: str | None) -> dict:
        """Return the entry with a new action; None/skip discard its destination."""
        if not action:
            return {"type": ""} if action == "" else {}
        entry = dict(entry, type=action)
        entry.pop("target_hash", None)
        if action == "info":
            entry.pop("target", None)
        return entry

    def _set_selected_action(self, index: int) -> None:
        action = self.action_combo.itemData(index)
        if index == 0:
            return
        if action not in dict(self._available_actions(self._selected_files())):
            return
        for relative in self._selected_files():
            entry = self._with_action(self._assignments.get(relative, {}), action)
            self._touched.add(relative)
            self._assign(relative, entry)
        self.action_combo.setCurrentIndex(0)
        self._update_summary()
        self._validate()

    def _item_changed(self, item, column: int) -> None:
        relative = item.data(0, Qt.ItemDataRole.UserRole)
        if not relative or column not in (1, 2):
            return
        action = item.data(1, Qt.ItemDataRole.UserRole)
        target = item.text(2).strip().replace("\\", "/")
        current = self._assignments.get(relative, {})
        if (column == 1 and action == current.get("type")) or (
            column == 2 and target == current.get("target", "")
        ):
            return
        selected = self._selected_files() if item.isSelected() else [relative]
        if column == 1 and action not in dict(self._available_actions(selected)):
            self._assign(relative, current)
            return
        context = self._context()
        for selected_relative in selected:
            entry = dict(self._assignments.get(selected_relative, {}))
            entry.pop("target_hash", None)
            if column == 1:
                entry = self._with_action(entry, action)
            elif target:
                if entry.get("type") in (None, "", "info"):
                    entry["type"] = default_action(selected_relative)
                entry["target"] = (
                    portable_operation_path(target, context)
                    if is_direct_absolute_path(target)
                    else target
                )
            else:
                entry.pop("target", None)
            self._touched.add(selected_relative)
            self._assign(selected_relative, entry)
        self._update_summary()
        self._validate()

    def _browse_selected(self, *, folder: bool | None = None) -> None:
        selected = self._selected_files()
        if not selected:
            return
        context = self._context()
        start = str(context.game_path or Path.home())
        selected_items = [
            item for item in self.sources.selectedItems() if not item.isHidden()
        ]
        directories = any(relative.endswith("/") for relative in selected)
        extracting = any(
            self._assignments.get(relative, {}).get("type") == "extract"
            for relative in selected
        )
        all_patches = all(
            self._assignments.get(relative, {}).get("type") == "patch"
            for relative in selected
        )
        if folder is False or (
            folder is None
            and (
                (len(selected) == 1 and not directories and not extracting)
                or all_patches
            )
        ):
            chosen, _filter = get_open_file_name(
                self,
                tr("ui.manual_install_target"),
                start,
                f"{tr('file_descriptions.all_files')} (*)",
            )
            targets = dict.fromkeys(selected, chosen) if chosen else {}
        else:
            chosen = get_existing_directory(self, tr("ui.manual_install_target"), start)
            if not chosen:
                return
            bases = [
                str(PurePosixPath(item.data(0, Qt.ItemDataRole.UserRole)).parent)
                for item in selected_items
            ]
            common = posixpath.commonpath(bases)
            targets = {
                relative: chosen
                if self._assignments.get(relative, {}).get("type") == "extract"
                or (len(selected) == 1 and relative.endswith("/"))
                else str(
                    Path(chosen).joinpath(
                        *PurePosixPath(relative)
                        .relative_to(PurePosixPath(common))
                        .parts
                    )
                )
                for relative in selected
            }
        for relative, target in targets.items():
            entry = dict(self._assignments.get(relative, {}))
            if entry.get("type") == "info":
                continue
            entry.pop("target_hash", None)
            entry["type"] = entry.get("type") or default_action(relative)
            entry["target"] = portable_operation_path(target, context)
            self._touched.add(relative)
            self._assign(relative, entry)
        self._update_summary()
        self._validate()

    def _hide_configured_changed(self, checked: bool) -> None:
        if self.app_state is not None:
            self.app_state.local_config["manual_install_hide_configured"] = checked
            if self._settings_service is not None:
                self._settings_service.write_local_config()
        self._filter_files(self.filter_edit.text())

    def _filter_files(self, text: str) -> None:
        query = text.casefold().strip()

        def visit(item):
            relative = item.data(0, Qt.ItemDataRole.UserRole)
            visible = bool(
                item.foreground(2).color() == _INVALID_COLOR
                or (
                    relative
                    and query in f"{relative} {item.text(2)}".casefold()
                    and not (
                        self.hide_configured.isChecked() and self._configured(relative)
                    )
                )
            )
            for index in range(item.childCount()):
                visible = visit(item.child(index)) or visible
            item.setHidden(not visible)
            return visible

        for index in range(self.sources.topLevelItemCount()):
            visit(self.sources.topLevelItem(index))
        self._update_selection()

    def _update_summary(self) -> None:
        configured = {
            relative: self._configured(relative) for relative in self._source_nodes
        }
        with QSignalBlocker(self.sources):
            for relative, item in self._items.items():
                action = self._assignments.get(relative, {}).get("type")
                key = (
                    "ui.manual_install_configured"
                    if action is None and configured[relative]
                    else dict(_ACTIONS)[action]
                )
                item.setText(1, tr(key))
        self.files_summary_label.setText(
            tr(
                "ui.manual_install_hint",
                count=len(configured),
                configured=sum(configured.values()),
                unconfigured=sum(not ready for ready in configured.values()),
            )
        )
        self._update_save_buttons(sum(not ready for ready in configured.values()))
        self._filter_files(self.filter_edit.text())

    @override
    def eventFilter(self, a0, a1) -> bool:
        watched = a0
        event = cast(QEvent, a1)
        if not isinstance(watched, QWidget):
            return super().eventFilter(watched, event)
        if (
            event.type() == QEvent.Type.HoverEnter
            and not watched.isEnabled()
            and watched.toolTip()
        ):
            position = cast(QHoverEvent, event).position().toPoint()
            QCoreApplication.sendEvent(
                watched,
                QHelpEvent(
                    QEvent.Type.ToolTip,
                    position,
                    watched.mapToGlobal(position),
                ),
            )
        return super().eventFilter(watched, event)

    def _update_save_buttons(self, unconfigured: int | None = None) -> None:
        if unconfigured is None:
            unconfigured = sum(
                not self._configured(relative) for relative in self._source_nodes
            )
        key = (
            "loading"
            if self._metadata_thread
            else "checking"
            if self._checking_save
            else "saving"
            if self._save_thread
            else "no_files"
            if not self._source_nodes
            else "unconfigured"
            if unconfigured
            else ""
        )
        tooltip = (
            tr(f"tooltips.manual_install_save_{key}", count=unconfigured) if key else ""
        )
        for button in (self.save_button, self.configure_button):
            button.setEnabled(not key)
            button.setToolTip(tooltip)

    def _configured(self, relative: str) -> bool:
        if self._assigned(relative) or any(
            self._assigned(parent) for parent in self._parents(relative)
        ):
            return True
        item = self._items[relative]
        return bool(
            relative.endswith("/")
            and self._assignments.get(relative, {}).get("type") is None
            and item.childCount()
            and all(
                self._configured(
                    cast(QTreeWidgetItem, item.child(index)).data(
                        0, Qt.ItemDataRole.UserRole
                    )
                )
                for index in range(item.childCount())
            )
        )

    def _assigned(self, relative: str) -> bool:
        entry = self._assignments.get(relative, {})
        return (
            entry.get("type") == "info"
            or bool(entry.get("type") and entry.get("target"))
            or entry.get("type") == ""
        )

    def _configured_sources(self) -> list[str]:
        return [
            relative
            for relative in self._source_nodes
            if self._assigned(relative)
            and self._assignments[relative].get("type")
            and not any(
                self._assigned(parent)
                and (
                    self._assignments[parent].get("type") == ""
                    or self._assignments[relative].get("type") != "info"
                )
                for parent in self._parents(relative)
            )
        ]

    def _validate(self) -> bool:
        with QSignalBlocker(self.sources):
            config = self._config("local_manual_preview", self.name_edit.text().strip())
            issues = validate_mod_config(config)
            errors = [issue for issue in issues if issue.severity == "error"]
            messages = []
            configured = self._configured_sources()
            for item in self._items.values():
                for column in range(3):
                    item.setForeground(column, QBrush())
            for issue in issues:
                if issue.severity == "error" and issue.path.startswith("files["):
                    index = int(issue.path.split("[", 1)[1].split("]", 1)[0])
                    if index < len(configured):
                        self._mark_invalid(configured[index])
                        messages.append(
                            f"{configured[index]}: {tr('ui.mod_editor_validation_invalid')}"
                        )
                elif issue.severity == "error":
                    label = tr(
                        "ui.mod_authors"
                        if issue.path.startswith("authors")
                        else "ui.mod_name_label"
                        if issue.path == "name"
                        else "ui.mod_editor_validation_configuration"
                    )
                    messages.append(f"{label} {tr('ui.mod_editor_validation_invalid')}")
            if not messages:
                files = cast(list[dict], config["files"])
                for leaf, relative in zip(files, configured, strict=True):
                    source = Path(self._source_nodes[relative])
                    if source.is_dir() and not relative.endswith("/"):
                        source = source / "g3mpatch.json"
                    leaf["source"] = (
                        f"${{mod_path}}/{source.relative_to(self.prepared_files_path).as_posix()}"
                        + ("/" if relative.endswith("/") else "")
                    )
                    leaf.pop("target_hash", None)
                    leaf.pop("source_hash", None)
                context = self._context()
                plan = build_mod_operation_plan(config, context)
                protected = {
                    Path(root).resolve()
                    for root in (
                        context.game_path,
                        context.game_data_path,
                        context.user_path,
                    )
                    if root
                }
                for operation in plan.operations:
                    if isinstance(operation.target, Path):
                        parent = operation.target.parent
                        while not parent.exists() and parent != parent.parent:
                            parent = parent.parent
                        # Folder replacement clears only this destination, never a game/data root.
                        replaces_directory = operation.type == "hard-extract" or (
                            operation.type == "overwrite"
                            and not operation.target_is_directory
                            and operation.target.is_dir()
                        )
                        if (
                            not parent.is_dir()
                            or (
                                operation.type == "extract"
                                and operation.target.is_file()
                            )
                            or (
                                replaces_directory
                                and (
                                    any(
                                        root.is_relative_to(operation.target.resolve())
                                        for root in protected
                                    )
                                    or operation.target == operation.target.parent
                                )
                            )
                        ):
                            relative = configured[operation.index - 1]
                            self._mark_invalid(relative)
                            messages.append(
                                f"{relative}: {tr('ui.mod_editor_validation_target_unsupported')}"
                            )
                for finding in plan.findings:
                    # Compatibility is checked before saving, with an option to proceed.
                    leaf = files[finding.operation_index - 1]
                    unavailable_root = finding.code == "target_root" and any(
                        leaf.get("target", "").startswith(f"${{{name}}}/") and root is None
                        for name, root in (("game_path", context.game_path), ("game_data_path", context.game_data_path))
                    )
                    if leaf["type"] == "patch" and (finding.code in {"target_missing", "target_archive", "target_archive_write"} or unavailable_root):
                        continue
                    if finding.severity == "error":
                        relative = configured[finding.operation_index - 1]
                        self._mark_invalid(relative)
                        messages.append(f"{relative}: {finding.message}")
            valid = not messages
            self.name_edit.setProperty(
                "invalid", any(issue.path == "name" for issue in errors)
            )
            cast(QStyle, self.name_edit.style()).unpolish(self.name_edit)
            cast(QStyle, self.name_edit.style()).polish(self.name_edit)
            if not valid:
                self._show_errors()
                self.status_label.set_localized_text("ui.manual_install_invalid", details="\n".join(messages[:3]))
            elif getattr(self, "_validation_failed", False):
                self.status_label.clear()
            self._validation_failed = not valid
            return valid

    def _mark_invalid(self, relative: str) -> None:
        self._items[relative].setForeground(2, QBrush(_INVALID_COLOR))

    def _show_errors(self, error: str = "") -> None:
        with QSignalBlocker(self.sources):
            for relative, item in self._items.items():
                if error.startswith(f"{relative}:"):
                    self._mark_invalid(relative)
                if item.foreground(2).color() == _INVALID_COLOR:
                    parent = item.parent()
                    while parent is not None:
                        parent.setExpanded(True)
                        parent = parent.parent()
        self._filter_files(self.filter_edit.text())

    def _identity(self) -> tuple[str, str]:
        metadata = self.gamebanana_metadata
        if metadata.get("mod_id"):
            item_type = str(metadata.get("item_type") or "mod").lower()
            mod_id = f"gb_{item_type}_{metadata['mod_id']}"
        else:
            mod_id = f"local_manual_{uuid.uuid4().hex[:12]}"
        return mod_id, self.name_edit.text().strip() or "Manual Mod"

    def _config(self, mod_id: str, mod_name: str) -> dict[str, object]:
        authors = self.gamebanana_metadata.get("authors")
        context = self._context()
        config: dict[str, object] = {
            "config_version": MOD_CONFIG_VERSION,
            "id": mod_id,
            "name": mod_name,
            "version": str(self.gamebanana_metadata.get("version") or "1.0.0"),
            "authors": (
                [
                    name.strip()
                    for name in authors
                    if isinstance(name, str) and name.strip()
                ]
                if isinstance(authors, list)
                else []
            )
            or ["Unknown"],
            "game": str(self.game_combo.currentData() or "deltarune"),
            "files": [
                self._operation(relative, context)
                for relative in self._configured_sources()
            ],
        }
        for field in ("description", "homepage", "icon", "game_version"):
            if value := self.gamebanana_metadata.get(field):
                config[field] = str(value)
        if not config.get("homepage") and self.gamebanana_metadata.get("profile_url"):
            config["homepage"] = str(self.gamebanana_metadata["profile_url"])
        valid = normalize_tags(
            [
                *(self.gamebanana_metadata.get("tags") or []),
                self.gamebanana_metadata.get("category"),
            ]
        )
        if valid:
            config["tags"] = valid
        return config

    def _operation(self, relative: str, context: ModPathContext) -> dict:
        entry = dict(
            self._assignments[relative], source=f"${{mod_path}}/files/{relative}"
        )
        if relative.endswith("/") and entry["type"] == "overwrite":
            try:
                target = resolve_operation_path(
                    entry["target"].rstrip("/"), context=context, is_target=True
                )
            except ValueError:
                target = None
            if isinstance(target, Path) and (
                target.is_file() or archive_format(target)
            ):
                entry["target"] = entry["target"].rstrip("/")
            else:
                entry["type"] = "hard-extract"
        if entry["type"].endswith("extract"):
            entry["target"] = entry["target"].rstrip("/") + "/"
        return entry

    def _open_editor(self, config: dict[str, object], folder: Path) -> bool:
        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        payload = dict(config, folder_path=str(folder))
        return (
            ModEditorDialog(
                self.parentWidget() or self, is_creating=False, mod_data=payload
            ).exec()
            == QDialog.DialogCode.Accepted
        )

    def _on_finish(self, *, configure: bool = False) -> None:
        if self._metadata_thread or self._save_thread or self._checking_save:
            return
        unconfigured = [
            relative
            for relative in self._source_nodes
            if not self._configured(relative)
        ]
        if unconfigured:
            self.tabs.setCurrentIndex(0)
            self._update_summary()
            self.status_label.set_localized_text("ui.manual_install_detection_unconfigured", count=len(unconfigured))
            with QSignalBlocker(self.sources):
                for relative in unconfigured:
                    if self._assignments.get(relative, {}).get("type"):
                        self._mark_invalid(relative)
            self._filter_files(self.filter_edit.text())
            return
        was_detecting = self._detection_thread is not None
        self._stop_detection()
        if not self._validate():
            self.tabs.setCurrentIndex(0)
            if was_detecting:
                self._resume_detection()
            return
        if self.app_state is None or not self._source_nodes:
            self._safe_critical(
                tr("errors.error"),
                tr(
                    "errors.manual_install_failed",
                    error=tr("ui.manual_install_no_files"),
                ),
            )
            return
        if any(
            self._assignments[relative].get("type") == "patch"
            for relative in self._configured_sources()
        ):
            self._checking_save = True
            self._configure_after_save = configure
            self._set_busy(True)
            self.status_label.set_localized_text(
                    "ui.manual_install_detecting",
                    completed=0,
                    total=len(self.all_files),
                )
            thread = DetectionThread(
                self.all_files,
                self._context(),
                dict(getattr(self.app_state, "local_config", {}) or {}),
                checks={
                    relative: dict(self._assignments[relative])
                    for relative in self._configured_sources()
                    if not relative.endswith("/")
                },
                game=str(self.game_combo.currentData() or ""),
            )
            self._detection_thread = thread
            thread.result_ready.connect(self._checked_save)
            thread.start()
        else:
            self._begin_save(configure)

    @pyqtSlot(dict, str)
    def _checked_save(self, assignments: dict, error: str) -> None:
        if self.sender() is not self._detection_thread:
            return
        self._stop_detection()
        self._checking_save = False
        if error and self.auto_install:
            logger.info("Automatic installation declined: %s", error)
            self.reject()
            return
        if error:
            self._set_busy(False)
            warning = DynamicMessageBox(self)
            warning.setIcon(QMessageBox.Icon.Warning)
            warning.set_localized_title("dialogs.manual_install_title")
            warning.localize(warning.setText, "ui.manual_install_patch_warning")
            warning.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
            for button, key in ((QMessageBox.StandardButton.Save, "ui.manual_install_save"), (QMessageBox.StandardButton.Cancel, "dialogs.cancel")):
                warning.localize_text(cast(QPushButton, warning.button(button)), key)
            warning.setDefaultButton(QMessageBox.StandardButton.Cancel)
            warning.apply_theme()
            choice = warning.exec()
            warning.deleteLater()
            if choice != QMessageBox.StandardButton.Save:
                self.tabs.setCurrentIndex(0)
                self.sources.setFocus()
                return
            # Failed verification must not preserve hashes from a previous binding.
            for entry in self._assignments.values():
                entry.pop("source_hash", None)
                entry.pop("target_hash", None)
        for relative, entry in assignments.items():
            self._assign(relative, entry)
        self._begin_save(self._configure_after_save)

    def _begin_save(self, configure: bool) -> None:
        mod_id, mod_name = self._identity()
        config = self._config(mod_id, mod_name)
        self._configure_after_save = configure
        self._saved_config = config
        mods_dir = self.target_mods_dir
        if mods_dir is None:
            if self.app_state is None:
                raise ValueError("manual installation requires a mods directory")
            mods_dir = self.app_state.mods_dir
        thread = SaveThread(
            [(source, relative) for relative, source in self._source_nodes.items()],
            config,
            Path(mods_dir),
            self.prepared_files_path,
        )
        self._save_thread = thread
        thread.result_ready.connect(self._saved)
        self._set_busy(True)
        self.status_label.set_localized_text("ui.manual_install_saving")
        thread.start()

    def _set_busy(self, busy: bool) -> None:
        for widget in (
            self.sources,
            self.game_combo,
            self.add_game_button,
            self.name_edit,
            self.filter_edit,
            self.hide_configured,
            self.action_combo,
            self.browse_button,
        ):
            widget.setEnabled(not busy)
        self._update_save_buttons()
        if not busy:
            self._update_selection()

    def _stop_save(self) -> None:
        if thread := self._save_thread:
            thread.requestInterruption()
            # Keep receiving completion: cancellation can race the final config write.
            retire_qthread(thread)

    @pyqtSlot(object, str)
    def _saved(self, folder, error: str) -> None:
        thread = self._save_thread
        if self.sender() is not thread:
            return
        self._save_thread = None
        retire_qthread(thread)
        if self._cancelled:
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)
            super().reject()
            return
        if folder is not None:
            self.accept()
            if self._configure_after_save:
                self._open_editor(self._saved_config, folder)
        elif error and self.auto_install:
            logger.info("Automatic installation could not save: %s", error)
            self.reject()
        elif error:
            self._set_busy(False)
            self.tabs.setCurrentIndex(0)
            self._show_errors(error)
            self.status_label.set_localized_text("errors.manual_install_failed", error=error)

    @staticmethod
    def _safe_critical(title: str, message: str) -> None:
        try:
            QMessageBox.critical(None, title, message)
        except RuntimeError:
            logger.exception("Could not show manual-import error")

    @override
    def reject(self) -> None:
        if self._save_thread is not None:
            self._cancelled = True
            self._stop_save()
            cast(
                QPushButton, self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
            ).setEnabled(False)
            self.status_label.set_localized_text("ui.manual_install_cancelling")
            return
        super().reject()

    @override
    def closeEvent(self, a0) -> None:
        event = cast(QCloseEvent, a0)
        if self._save_thread is not None:
            self.reject()
            event.ignore()
            return
        if self.temp_dir_to_cleanup:
            shutil.rmtree(self.temp_dir_to_cleanup, ignore_errors=True)
        super().closeEvent(event)
