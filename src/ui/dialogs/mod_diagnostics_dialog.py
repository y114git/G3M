"""Preflight diagnostics dialog for selected library mods."""

from __future__ import annotations

import difflib
import logging
import os
import tempfile
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from multiprocessing import Process
from typing import Any, cast

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models.execution_plan import PatchPlan
from services.diagnostics.preflight_service import (
    DiagnosticsPreflightService,
    PreflightReport,
    export_preflight_report,
)
from services.localization_service import tr
from services.mod_diagnostics_service import (
    DataImpact,
    DiagnosticsReport,
    ModDiagnosticsService,
)
from ui.common.dialog_theme import (
    build_dialog_theme_stylesheet,
    get_dialog_theme_values,
)
from ui.utils.thread_lifetime import ManagedQThread
from utils.mod.utils import get_mod_id, get_mod_name
from utils.native_integration import get_save_file_name

MAX_G3MPATCH_PREVIEW_BYTES = 100 * 1024 * 1024
logger = logging.getLogger(__name__)


def _play_audio_preview_process(sound_path: str) -> None:
    try:
        __import__("playsound3").playsound(os.path.abspath(sound_path))
    except ImportError:
        logger.warning(
            "ModDiagnosticsDialog: audio preview is unavailable because playsound3 is not installed"
        )
    except Exception as exc:
        logger.warning(
            "ModDiagnosticsDialog: failed to play audio preview %s: %s",
            sound_path,
            exc,
        )


class DiagnosticsWorker(ManagedQThread):
    result_ready = pyqtSignal(object)

    def __init__(
        self,
        service: ModDiagnosticsService,
        section_mods: dict[str, list[Any]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._section_mods = section_mods

    def run(self) -> None:
        self.result_ready.emit(self._service.build_report(self._section_mods))


class DiagnosticsPreflightWorker(ManagedQThread):
    result_ready = pyqtSignal(object)
    progress_update = pyqtSignal(int, str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        service: DiagnosticsPreflightService,
        plan: PatchPlan,
        resolver,
        game_path: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._plan = plan
        self._resolver = resolver
        self._game_path = game_path

    def cancel(self) -> None:
        self.requestInterruption()
        self._service.cancel()

    def run(self) -> None:
        try:
            report = self._service.run(
                self._plan,
                self._resolver,
                self._game_path,
                progress=lambda value, phase: self.progress_update.emit(value, phase),
            )
            self.result_ready.emit(report)
        except Exception as error:
            logger.error("Deep diagnostics failed: %s", error, exc_info=True)
            self.failed.emit(str(error))


class ModDiagnosticsDialog(QDialog):
    """Non-modal diagnostics and preflight window."""

    def __init__(self, app_state, mod_service, used_mods_service, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._mod_service = mod_service
        self._used_mods_service = used_mods_service
        self._all_mods: list[Any] = []
        self._mod_checks: dict[str, QCheckBox] = {}
        self._mod_rows: dict[str, QLabel] = {}
        self._active_mod_keys: set[str] = set()
        self._resource_type_checks: dict[str, QCheckBox] = {}
        self._selected_resource_types: set[str] = set()
        self._resource_filters_initialized = False
        self._preview_temp_dir = os.path.join(
            tempfile.gettempdir(), "g3m_diagnostics_preview"
        )
        self._audio_process: Process | None = None
        self._current_audio_path = ""
        self._report: DiagnosticsReport | None = None
        self._worker: DiagnosticsWorker | None = None
        self._preflight_report: PreflightReport | None = None
        self._preflight_worker: DiagnosticsPreflightWorker | None = None
        self.setWindowTitle(tr("diagnostics.title"))
        self.setMinimumSize(900, 600)
        self.resize(1300, 820)
        self.setModal(False)
        self._build_ui()
        self._apply_theme()
        self._load_initial_mods()
        self._run_analysis()

    def _build_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(8)

        header = QHBoxLayout()
        self._title_label = QLabel(tr("diagnostics.title"))
        self._title_label.setObjectName("diagnostics_title")
        font = self._title_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self._title_label.setFont(font)
        header.addWidget(self._title_label)
        header.addStretch()
        self._close_btn = QPushButton(tr("common.close"))
        self._close_btn.clicked.connect(self.close)
        header.addWidget(self._close_btn)
        main.addLayout(header)

        self._summary_row = QHBoxLayout()
        self._summary_labels: dict[str, QLabel] = {}
        for key in (
            "selected_mods",
            "new_files",
            "modified_files",
            "conflicts",
            "data_files",
            "deep_analyzable_data_files",
            "issues",
        ):
            label = QLabel("0")
            label.setObjectName(f"diagnostics_summary_{key}")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._summary_labels[key] = label
            self._summary_row.addWidget(label)
        main.addLayout(self._summary_row)

        self._preflight_controls = QVBoxLayout()
        preflight_actions = QHBoxLayout()
        preflight_status = QHBoxLayout()
        self._run_preflight_btn = QPushButton(tr("diagnostics.run_actual_analysis"))
        self._run_preflight_btn.setToolTip(
            tr("diagnostics.run_actual_analysis_tooltip")
        )
        self._cancel_preflight_btn = QPushButton(
            tr("diagnostics.cancel_actual_analysis")
        )
        self._cancel_preflight_btn.setEnabled(False)
        self._export_preflight_btn = QPushButton(tr("diagnostics.export_actual_report"))
        self._export_preflight_btn.setEnabled(False)
        self._preflight_progress = QProgressBar()
        self._preflight_progress.setRange(0, 100)
        self._preflight_progress.setValue(0)
        self._preflight_progress.setTextVisible(True)
        self._preflight_phase = QLabel(tr("diagnostics.actual_analysis_not_run"))
        self._preflight_phase.setWordWrap(True)
        self._run_preflight_btn.clicked.connect(self._run_preflight)
        self._cancel_preflight_btn.clicked.connect(self._cancel_preflight)
        self._export_preflight_btn.clicked.connect(self._export_preflight)
        preflight_actions.addWidget(self._run_preflight_btn)
        preflight_actions.addWidget(self._cancel_preflight_btn)
        preflight_actions.addWidget(self._export_preflight_btn)
        preflight_actions.addStretch()
        preflight_status.addWidget(self._preflight_progress, 1)
        preflight_status.addWidget(self._preflight_phase, 2)
        self._preflight_controls.addLayout(preflight_actions)
        self._preflight_controls.addLayout(preflight_status)
        main.addLayout(self._preflight_controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self._mods_panel = QWidget()
        self._mods_panel.setMinimumWidth(180)
        self._mods_panel.setMaximumWidth(340)
        mods_layout = QVBoxLayout(self._mods_panel)
        mods_layout.setContentsMargins(0, 0, 0, 0)
        self._mods_label = QLabel(tr("diagnostics.mods"))
        mods_layout.addWidget(self._mods_label)
        self._scope_label = QLabel("")
        self._scope_label.setWordWrap(True)
        self._scope_label.setObjectName("diagnostics_scope")
        mods_layout.addWidget(self._scope_label)
        self._mods_list = QWidget()
        self._mods_list_layout = QVBoxLayout(self._mods_list)
        self._mods_list_layout.setContentsMargins(4, 4, 4, 4)
        self._mods_list_layout.addStretch()
        self._mods_scroll = QScrollArea()
        self._mods_scroll.setWidgetResizable(True)
        self._mods_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._mods_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._mods_scroll.setWidget(self._mods_list)
        mods_layout.addWidget(self._mods_scroll, 1)
        splitter.addWidget(self._mods_panel)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setUsesScrollButtons(False)
        self._overview = QTextEdit()
        self._overview.setReadOnly(True)
        self._file_tree = QTreeWidget()
        self._file_tree.setHeaderLabels(
            [
                tr("diagnostics.column_target"),
                tr("diagnostics.column_operation"),
                tr("diagnostics.column_mod"),
            ]
        )
        self._prepare_tree(self._file_tree)
        self._data_tab = QWidget()
        data_layout = QVBoxLayout(self._data_tab)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(6)
        self._resource_filter_scroll = QScrollArea()
        self._resource_filter_scroll.setWidgetResizable(True)
        self._resource_filter_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._resource_filter_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._resource_filter_host = QWidget()
        self._resource_filter_layout = QHBoxLayout(self._resource_filter_host)
        self._resource_filter_layout.setContentsMargins(4, 2, 4, 2)
        self._resource_filter_layout.setSpacing(8)
        self._resource_filter_layout.addStretch()
        self._resource_filter_scroll.setWidget(self._resource_filter_host)
        data_layout.addWidget(self._resource_filter_scroll)
        self._data_tree = QTreeWidget()
        self._data_tree.setHeaderLabels(
            [
                tr("diagnostics.column_target"),
                tr("diagnostics.column_operation"),
                tr("diagnostics.column_mod"),
            ]
        )
        self._prepare_tree(self._data_tree)
        data_layout.addWidget(self._data_tree, 1)
        self._preview_compare_panel = QTextEdit()
        self._preview_compare_panel.setReadOnly(True)
        self._preview_compare_panel.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._preview_compare_panel.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._preview_compare_tab = QWidget()
        preview_layout = QVBoxLayout(self._preview_compare_tab)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(6)
        audio_controls = QHBoxLayout()
        self._audio_play_btn = QPushButton(tr("diagnostics.preview_play"))
        self._audio_stop_btn = QPushButton(tr("diagnostics.preview_stop"))
        self._audio_status = QLabel("")
        self._audio_play_btn.clicked.connect(self._play_preview_audio)
        self._audio_stop_btn.clicked.connect(self._stop_preview_audio)
        self._audio_play_btn.setEnabled(False)
        self._audio_stop_btn.setEnabled(False)
        self._audio_play_btn.setVisible(False)
        self._audio_stop_btn.setVisible(False)
        audio_controls.addWidget(self._audio_play_btn)
        audio_controls.addWidget(self._audio_stop_btn)
        audio_controls.addWidget(self._audio_status, 1)
        preview_layout.addLayout(audio_controls)
        preview_layout.addWidget(self._preview_compare_panel, 1)
        self._issues_list = QListWidget()
        self._issues_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._tabs.addTab(self._overview, tr("diagnostics.tab_overview"))
        self._tabs.addTab(self._file_tree, tr("diagnostics.tab_files"))
        self._tabs.addTab(self._data_tab, tr("diagnostics.tab_data"))
        self._tabs.addTab(
            self._preview_compare_tab, tr("diagnostics.tab_preview_compare")
        )
        self._tabs.addTab(self._issues_list, tr("diagnostics.tab_issues"))
        self._preflight_steps_tree = QTreeWidget()
        self._preflight_steps_tree.setHeaderLabels(
            [
                tr("diagnostics.column_step"),
                tr("diagnostics.column_mod"),
                tr("diagnostics.column_status"),
            ]
        )
        self._prepare_tree(self._preflight_steps_tree)
        self._preflight_resources_tab = QWidget()
        actual_resources_layout = QVBoxLayout(self._preflight_resources_tab)
        actual_resources_layout.setContentsMargins(0, 0, 0, 0)
        self._preflight_search = QLineEdit()
        self._preflight_search.setPlaceholderText(
            tr("diagnostics.search_actual_resources")
        )
        self._preflight_resources_tree = QTreeWidget()
        self._preflight_resources_tree.setHeaderLabels(
            [
                tr("diagnostics.column_target"),
                tr("diagnostics.column_operation"),
                tr("diagnostics.column_mod"),
            ]
        )
        self._prepare_tree(self._preflight_resources_tree)
        self._preflight_search.textChanged.connect(self._filter_preflight_resources)
        actual_resources_layout.addWidget(self._preflight_search)
        actual_resources_layout.addWidget(self._preflight_resources_tree, 1)
        self._preflight_files_tree = QTreeWidget()
        self._preflight_files_tree.setHeaderLabels(
            [
                tr("diagnostics.column_target"),
                tr("diagnostics.column_operation"),
                tr("diagnostics.column_mod"),
            ]
        )
        self._prepare_tree(self._preflight_files_tree)
        self._tabs.addTab(
            self._preflight_steps_tree, tr("diagnostics.tab_actual_steps")
        )
        self._tabs.addTab(
            self._preflight_resources_tab, tr("diagnostics.tab_actual_resources")
        )
        self._tabs.addTab(
            self._preflight_files_tree, tr("diagnostics.tab_actual_files")
        )
        splitter.addWidget(self._tabs)

        self._inspector = QTextEdit()
        self._inspector.setReadOnly(True)
        self._inspector.setMinimumWidth(220)
        splitter.addWidget(self._inspector)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([240, 780, 280])
        main.addWidget(splitter, 1)

        self._file_tree.itemSelectionChanged.connect(self._show_selected_file)
        self._data_tree.itemSelectionChanged.connect(self._show_selected_data)
        self._file_tree.itemDoubleClicked.connect(
            lambda _item, _column: self._open_selected_file()
        )
        self._data_tree.itemDoubleClicked.connect(
            lambda _item, _column: self._open_selected_data()
        )
        self._issues_list.currentItemChanged.connect(self._show_selected_issue)
        self._preflight_steps_tree.itemSelectionChanged.connect(
            self._show_selected_preflight_step
        )
        self._preflight_resources_tree.itemSelectionChanged.connect(
            self._show_selected_preflight_resource
        )
        self._preflight_files_tree.itemSelectionChanged.connect(
            self._show_selected_preflight_file
        )

    @staticmethod
    def _prepare_tree(tree: QTreeWidget) -> None:
        tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        tree.header().setStretchLastSection(False)
        tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

    def _load_initial_mods(self) -> None:
        section_mods = self._initial_section_mods()
        self._active_mod_keys = {
            self._mod_identity_key(mod_data)
            for mods in section_mods.values()
            for mod_data in mods
        }
        seen: set[str] = set()
        self._all_mods = []
        for mod_data in self._library_mods_for_current_scope():
            mod_key = self._mod_identity_key(mod_data)
            if mod_key and mod_key not in seen:
                seen.add(mod_key)
                self._all_mods.append(mod_data)
        for mods in section_mods.values():
            for mod_data in mods:
                mod_key = self._mod_identity_key(mod_data)
                if mod_key and mod_key not in seen:
                    seen.add(mod_key)
                    self._all_mods.append(mod_data)
        self._scope_label.setText(self._scope_text())
        self._rebuild_mod_checkboxes(selected=self._active_mod_keys)

    def _library_mods_for_current_scope(self) -> list[Any]:
        installed_mods = self._mod_service.get_installed_mods_list()
        parent = self.parent()
        library_display = getattr(parent, "library_display", None)
        filter_installed = getattr(
            library_display,
            "filter_and_sort_installed",
            getattr(library_display, "_filter_and_sort_installed", None),
        )
        if callable(filter_installed):
            installed_mods = filter_installed(installed_mods)
        else:
            installed_mods = self._filter_installed_for_current_game(installed_mods)
        selected_chapter = self._current_scope_chapter()
        scoped_mods: list[Any] = []
        for mod_info in cast(Iterable[Any], installed_mods):
            mod_data = self._mod_service.create_mod_object_from_info(
                mod_info, getattr(self._app_state, "all_mods", None)
            )
            if not mod_data:
                continue
            if selected_chapter and not self._mod_has_files_for_section(
                mod_data,
                selected_chapter,
            ):
                continue
            scoped_mods.append(mod_data)
        return scoped_mods

    def _filter_installed_for_current_game(
        self, installed_mods: list[dict]
    ) -> list[dict]:
        game_id = getattr(getattr(self._app_state, "game_mode", None), "game_id", "")
        if not game_id:
            return list(installed_mods)
        return [
            mod_info
            for mod_info in installed_mods
            if mod_info.get("game", "deltarune") == game_id
        ]

    def _mod_has_files_for_section(self, mod_data, section_id: str) -> bool:
        checker = getattr(self._mod_service, "mod_has_files_for_chapter", None)
        if callable(checker):
            return bool(checker(mod_data, section_id))
        return bool(
            hasattr(mod_data, "get_chapter_data")
            and mod_data.get_chapter_data(section_id)
        )

    def _initial_section_mods(self) -> dict[str, list[Any]]:
        section_mods: dict[str, list[Any]] = {}
        game_mode = getattr(self._app_state, "game_mode", None)
        selected = self._current_scope_chapter()
        if selected:
            mods = self._used_mods_service.get_used_mods_list(selected) or []
            section_mods[str(selected)] = list(mods)
            return section_mods
        active_selections = getattr(
            self._used_mods_service,
            "get_active_mod_selections",
            None,
        )
        if callable(active_selections):
            selections = active_selections() or {}
            if not isinstance(selections, dict):
                selections = {}
            return {
                str(section_id): list(mods or [])
                for section_id, mods in selections.items()
                if mods
            }
        for tab in getattr(game_mode, "tabs", []) or []:
            mods = self._used_mods_service.get_used_mods_list(tab.tab_id) or []
            if mods:
                section_mods[tab.tab_id] = list(mods)
        return section_mods

    def _rebuild_mod_checkboxes(self, selected: set[str]) -> None:
        while self._mods_list_layout.count() > 1:
            item = self._mods_list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._mod_checks.clear()
        self._mod_rows.clear()
        for mod_data in self._all_mods:
            mod_key = self._mod_identity_key(mod_data)
            row = QFrame()
            row.setObjectName("diagnostics_mod_row")
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(8, 7, 8, 7)
            row_layout.setSpacing(2)
            profile_active = mod_key in self._active_mod_keys
            check = QCheckBox(self._mod_checkbox_text(mod_data, profile_active))
            check.setToolTip(self._mod_tooltip(mod_data, profile_active))
            check.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            check.setChecked(mod_key in selected)
            check.stateChanged.connect(lambda _state: self._run_analysis())
            detail = QLabel(self._mod_detail_text(mod_data))
            detail.setObjectName("diagnostics_mod_detail")
            detail.setWordWrap(True)
            row_layout.addWidget(check)
            row_layout.addWidget(detail)
            self._mod_checks[mod_key] = check
            self._mod_rows[mod_key] = detail
            self._mods_list_layout.insertWidget(self._mods_list_layout.count() - 1, row)

    def _selected_mods(self) -> list[Any]:
        selected = {
            mod_id for mod_id, check in self._mod_checks.items() if check.isChecked()
        }
        return [
            mod for mod in self._all_mods if self._mod_identity_key(mod) in selected
        ]

    def _selected_section_mods(self) -> dict[str, list[Any]]:
        game_mode = getattr(self._app_state, "game_mode", None)
        selected_mods = self._selected_mods()
        if not selected_mods:
            return {}
        selected_chapter = self._current_scope_chapter()
        if selected_chapter:
            return {str(selected_chapter): selected_mods}
        section_mods: dict[str, list[Any]] = {}
        for tab in getattr(game_mode, "tabs", []) or []:
            mods = [
                mod
                for mod in selected_mods
                if hasattr(mod, "get_chapter_data") and mod.get_chapter_data(tab.tab_id)
            ]
            if mods:
                section_mods[tab.tab_id] = mods
        default_tab = getattr(game_mode, "default_tab_id", None)
        if not section_mods and default_tab:
            section_mods[str(default_tab)] = selected_mods
        return section_mods

    def _run_analysis(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._refresh_mod_row_labels()
        self._set_busy(True)
        service = ModDiagnosticsService(self._app_state, self._mod_service)
        self._worker = DiagnosticsWorker(service, self._selected_section_mods(), self)
        self._worker.result_ready.connect(self._on_report_ready)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _selected_patch_plan(self) -> tuple[PatchPlan, dict[str, Any]]:
        selected_sections = self._selected_section_mods()
        resolver_map: dict[str, Any] = {}
        planned: dict[str, list[list[Any]]] = {}
        get_steps = getattr(self._used_mods_service, "get_mod_steps", None)
        for section_id, selected_mods in selected_sections.items():
            selected_by_id = {
                str(get_mod_id(mod)): mod for mod in selected_mods if get_mod_id(mod)
            }
            resolver_map.update(selected_by_id)
            stored_steps = get_steps(section_id) if callable(get_steps) else []
            steps = [
                [
                    selected_by_id[str(get_mod_id(mod))]
                    for mod in step
                    if str(get_mod_id(mod)) in selected_by_id
                ]
                for step in cast(Iterable[Iterable[Any]], stored_steps or [])
            ]
            steps = [step for step in steps if step]
            assigned = {str(get_mod_id(mod)) for step in steps for mod in step}
            unassigned = [
                mod for mod in selected_mods if str(get_mod_id(mod)) not in assigned
            ]
            if unassigned:
                if steps:
                    steps[0].extend(unassigned)
                else:
                    steps = [unassigned]
            if steps:
                planned[str(section_id)] = steps
        return PatchPlan.from_runtime(planned), resolver_map

    def _run_preflight(self) -> None:
        if self._preflight_worker and self._preflight_worker.isRunning():
            return
        self._clear_preflight_result()
        plan, resolver_map = self._selected_patch_plan()
        if not plan.sections:
            self._preflight_phase.setText(tr("diagnostics.no_mods_selected"))
            return
        game_mode = getattr(self._app_state, "game_mode", None)
        game_path = (
            game_mode.get_game_path(self._app_state.local_config) if game_mode else ""
        )
        if not game_path or not os.path.isdir(game_path):
            self._preflight_phase.setText(tr("diagnostics.actual_game_path_missing"))
            return
        service = DiagnosticsPreflightService(self._app_state, self._mod_service)
        worker = DiagnosticsPreflightWorker(
            service,
            plan,
            resolver_map.get,
            game_path,
            self,
        )
        self._preflight_worker = worker
        worker.progress_update.connect(self._on_preflight_progress)
        worker.result_ready.connect(self._on_preflight_ready)
        worker.failed.connect(self._on_preflight_failed)
        worker.finished.connect(
            lambda current=worker: self._finish_preflight_worker(current)
        )
        self._run_preflight_btn.setEnabled(False)
        self._cancel_preflight_btn.setEnabled(True)
        self._export_preflight_btn.setEnabled(False)
        self._preflight_progress.setValue(0)
        self._preflight_phase.setText(tr("diagnostics.actual_phase_staging"))
        worker.start()

    def _cancel_preflight(self) -> None:
        worker = self._preflight_worker
        if worker and worker.isRunning():
            self._cancel_preflight_btn.setEnabled(False)
            self._preflight_phase.setText(tr("diagnostics.actual_phase_cancelling"))
            worker.cancel()

    def _finish_preflight_worker(self, worker: DiagnosticsPreflightWorker) -> None:
        if self._preflight_worker is worker:
            self._preflight_worker = None
        self._run_preflight_btn.setEnabled(True)
        self._cancel_preflight_btn.setEnabled(False)
        worker.deleteLater()

    def _on_preflight_progress(self, value: int, phase: str) -> None:
        self._preflight_progress.setValue(value)
        if phase.startswith("patching_step:"):
            _prefix, section, step, total = phase.split(":", 3)
            text = tr(
                "diagnostics.actual_phase_step",
                section=section,
                step=step,
                total=total,
            )
        else:
            key = {
                "staging_game": "diagnostics.actual_phase_staging",
                "building_report": "diagnostics.actual_phase_report",
                "completed": "diagnostics.actual_phase_completed",
                "cancelled": "diagnostics.actual_phase_cancelled",
                "failed": "diagnostics.actual_phase_failed",
            }.get(phase)
            text = tr(key) if key else phase
        self._preflight_phase.setText(text)

    def _on_preflight_ready(self, report: PreflightReport) -> None:
        self._preflight_report = report
        self._export_preflight_btn.setEnabled(True)
        self._populate_preflight_report(report)
        quick_conflicts = self._report.summary.conflicts if self._report else 0
        self._summary_labels["conflicts"].setText(
            tr(
                "diagnostics.summary_conflicts",
                count=max(quick_conflicts, report.conflict_count),
            )
        )
        if report.cancelled:
            self._preflight_phase.setText(tr("diagnostics.actual_phase_cancelled"))
        elif report.success:
            self._preflight_phase.setText(tr("diagnostics.actual_phase_completed"))
            self._preflight_progress.setValue(100)
        else:
            self._preflight_phase.setText(tr("diagnostics.actual_phase_failed"))

    def _on_preflight_failed(self, error: str) -> None:
        self._clear_preflight_result()
        self._preflight_phase.setText(
            tr("diagnostics.actual_analysis_failed", error=error)
        )

    def _clear_preflight_result(self) -> None:
        self._preflight_report = None
        self._export_preflight_btn.setEnabled(False)
        self._preflight_progress.setValue(0)
        self._preflight_steps_tree.clear()
        self._preflight_resources_tree.clear()
        self._preflight_files_tree.clear()
        self._preflight_search.clear()
        self._inspector.clear()

    def _populate_preflight_report(self, report: PreflightReport) -> None:
        self._preflight_steps_tree.clear()
        self._preflight_resources_tree.clear()
        self._preflight_files_tree.clear()
        for step in report.steps:
            item = QTreeWidgetItem(
                [
                    tr(
                        "diagnostics.actual_step_label",
                        section=step.section_id,
                        step=step.step_index,
                    ),
                    ", ".join(step.mod_ids),
                    tr(
                        "diagnostics.actual_status_success"
                        if step.success
                        else "diagnostics.actual_status_failed"
                    ),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, step)
            self._preflight_steps_tree.addTopLevelItem(item)
        resource_groups: dict[tuple[str, int, str], QTreeWidgetItem] = {}
        for resource in report.resources:
            group_key = (
                resource.section_id,
                resource.step_index,
                resource.resource_type,
            )
            group = resource_groups.get(group_key)
            if group is None:
                group = QTreeWidgetItem(
                    [
                        f"{resource.section_id} / {tr('ui.step_number', number=resource.step_index)} / {resource.resource_type}",
                        "",
                        "",
                    ]
                )
                resource_groups[group_key] = group
                self._preflight_resources_tree.addTopLevelItem(group)
            item = QTreeWidgetItem(
                [resource.name, resource.operation, ", ".join(resource.mod_ids)]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, resource)
            group.addChild(item)
        for change in report.files:
            item = QTreeWidgetItem(
                [change.relative_path, change.operation, ", ".join(change.mod_ids)]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, change)
            self._preflight_files_tree.addTopLevelItem(item)
        self._preflight_resources_tree.expandToDepth(0)
        if report.issues:
            self._inspector.setPlainText("\n\n".join(report.issues))

    def _filter_preflight_resources(self, text: str) -> None:
        needle = text.strip().casefold()
        for index in range(self._preflight_resources_tree.topLevelItemCount()):
            group = self._preflight_resources_tree.topLevelItem(index)
            visible_children = 0
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                haystack = " ".join(
                    child.text(column) for column in range(3)
                ).casefold()
                hidden = bool(needle and needle not in haystack)
                child.setHidden(hidden)
                visible_children += int(not hidden)
            group.setHidden(visible_children == 0)

    def _show_selected_preflight_step(self) -> None:
        items = self._preflight_steps_tree.selectedItems()
        if not items:
            return
        step = items[0].data(0, Qt.ItemDataRole.UserRole)
        if step is not None:
            self._inspector.setPlainText(
                tr(
                    "diagnostics.actual_step_details",
                    section=step.section_id,
                    step=step.step_index,
                    mods=", ".join(step.mod_ids),
                    duration=f"{step.duration_seconds:.2f}",
                    status=tr(
                        "diagnostics.actual_status_success"
                        if step.success
                        else "diagnostics.actual_status_failed"
                    ),
                    error=step.error or tr("diagnostics.no"),
                )
            )

    def _show_selected_preflight_resource(self) -> None:
        items = self._preflight_resources_tree.selectedItems()
        if not items:
            return
        resource = items[0].data(0, Qt.ItemDataRole.UserRole)
        if resource is not None:
            self._inspector.setPlainText(
                tr(
                    "diagnostics.actual_resource_details",
                    section=resource.section_id,
                    step=resource.step_index,
                    resource_type=resource.resource_type,
                    name=resource.name,
                    operation=resource.operation,
                    mods=", ".join(resource.mod_ids),
                    files="\n".join(resource.files)
                    or tr("diagnostics.no_resource_files"),
                    details=resource.details or tr("diagnostics.no_resource_summary"),
                )
            )

    def _show_selected_preflight_file(self) -> None:
        items = self._preflight_files_tree.selectedItems()
        if not items:
            return
        change = items[0].data(0, Qt.ItemDataRole.UserRole)
        if change is not None:
            self._inspector.setPlainText(
                tr(
                    "diagnostics.actual_file_details",
                    path=change.relative_path,
                    operation=change.operation,
                    section=change.section_id,
                    step=change.step_index,
                    mods=", ".join(change.mod_ids),
                    before_size=change.before_size,
                    after_size=change.after_size,
                    before_hash=change.before_hash,
                    after_hash=change.after_hash,
                )
            )

    def _export_preflight(self) -> None:
        if self._preflight_report is None:
            return
        path, _selected_filter = get_save_file_name(
            self,
            tr("diagnostics.export_actual_report"),
            "g3m-diagnostics.html",
            "HTML (*.html)",
        )
        if not path:
            return
        try:
            export_preflight_report(self._preflight_report, path)
            self._preflight_phase.setText(tr("diagnostics.actual_export_completed"))
        except OSError as error:
            self._preflight_phase.setText(
                tr("diagnostics.actual_export_failed", error=str(error))
            )

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self._inspector.setPlainText(tr("diagnostics.running"))

    def _on_report_ready(self, report: DiagnosticsReport) -> None:
        self._report = report
        self._populate_summary(report)
        self._populate_overview(report)
        self._sync_resource_filters(report)
        self._populate_file_tree(report)
        self._populate_data_tree(report)
        self._populate_preview_compare_panel(report)
        self._populate_issues(report)
        self._inspector.setToolTip("")
        self._inspector.setPlainText(tr("diagnostics.select_item_hint"))

    def _populate_summary(self, report: DiagnosticsReport) -> None:
        summary = report.summary
        values = {
            "selected_mods": tr(
                "diagnostics.summary_mods", count=summary.selected_mods
            ),
            "new_files": tr("diagnostics.summary_new", count=summary.new_files),
            "modified_files": tr(
                "diagnostics.summary_modified", count=summary.modified_files
            ),
            "conflicts": tr("diagnostics.summary_conflicts", count=summary.conflicts),
            "data_files": tr("diagnostics.summary_data", count=summary.data_files),
            "deep_analyzable_data_files": tr(
                "diagnostics.summary_deep",
                count=summary.deep_analyzable_data_files,
            ),
            "issues": tr("diagnostics.summary_issues", count=summary.issues),
        }
        for key, text in values.items():
            self._summary_labels[key].setText(text)

    def _populate_overview(self, report: DiagnosticsReport) -> None:
        summary = report.summary
        if summary.issues == 0:
            status = tr("diagnostics.overview_ok")
        elif summary.conflicts:
            status = tr("diagnostics.overview_conflicts")
        else:
            status = tr("diagnostics.overview_warnings")
        self._overview.setHtml(
            "<h2>{}</h2><p>{}</p><p>{}</p><ul>{}</ul>".format(
                tr("diagnostics.overview_title"),
                status,
                tr("diagnostics.g3mpatch_tip"),
                "".join(
                    f"<li>{line}</li>"
                    for line in (
                        tr("diagnostics.summary_mods", count=summary.selected_mods),
                        tr("diagnostics.summary_new", count=summary.new_files),
                        tr(
                            "diagnostics.summary_modified", count=summary.modified_files
                        ),
                        tr("diagnostics.summary_conflicts", count=summary.conflicts),
                        tr(
                            "diagnostics.summary_deep",
                            count=summary.deep_analyzable_data_files,
                        ),
                    )
                ),
            )
        )
        if summary.selected_mods == 0:
            self._overview.append(f"<p><b>{tr('diagnostics.no_mods_selected')}</b></p>")

    def _populate_file_tree(self, report: DiagnosticsReport) -> None:
        self._file_tree.clear()
        if not report.file_impacts and not report.data_impacts:
            self._file_tree.addTopLevelItem(
                QTreeWidgetItem([tr("diagnostics.empty_files"), "", ""])
            )
            return
        by_root: dict[str, list] = defaultdict(list)
        for impact in report.file_impacts:
            by_root[impact.target_root].append(impact)
        for root, impacts in sorted(by_root.items()):
            root_item = QTreeWidgetItem([self._compact_path(root), "", ""])
            root_item.setToolTip(0, root)
            self._file_tree.addTopLevelItem(root_item)
            for impact in sorted(impacts, key=lambda item: item.target_relative_path):
                target_label = self._display_target_path(
                    impact.target_root,
                    impact.target_relative_path,
                )
                item = QTreeWidgetItem(
                    [
                        target_label,
                        tr(f"diagnostics.operation_{impact.operation}"),
                        impact.mod_name,
                    ]
                )
                item.setToolTip(0, impact.target_path)
                item.setToolTip(2, impact.mod_name)
                item.setData(0, Qt.ItemDataRole.UserRole, impact)
                self._apply_operation_color(item, impact.operation)
                root_item.addChild(item)
            root_item.setExpanded(True)
        if report.data_impacts:
            data_root = QTreeWidgetItem([tr("diagnostics.data_file_group"), "", ""])
            self._file_tree.addTopLevelItem(data_root)
            for impact in report.data_impacts:
                target_label = self._compact_path(impact.target_data_path or "")
                item = QTreeWidgetItem(
                    [
                        target_label,
                        tr("diagnostics.operation_modify"),
                        impact.mod_name,
                    ]
                )
                item.setToolTip(0, impact.target_data_path or "")
                item.setToolTip(2, impact.mod_name)
                item.setData(0, Qt.ItemDataRole.UserRole, impact)
                self._apply_operation_color(
                    item, "modify" if impact.deep_analysis_available else "unknown"
                )
                data_root.addChild(item)
            data_root.setExpanded(True)
        self._file_tree.setColumnWidth(0, 360)
        self._file_tree.setColumnWidth(1, 120)

    def _sync_resource_filters(self, report: DiagnosticsReport) -> None:
        resource_types = sorted(
            {
                str(entry.get("type", ""))
                for impact in report.data_impacts
                for entry in impact.resource_entries
                if entry.get("type")
            },
            key=str.casefold,
        )
        if not self._resource_filters_initialized:
            self._selected_resource_types = set(resource_types)
            self._resource_filters_initialized = True
        else:
            self._selected_resource_types &= set(resource_types)
            self._selected_resource_types |= {
                resource_type
                for resource_type in resource_types
                if resource_type not in self._resource_type_checks
            }
        while self._resource_filter_layout.count() > 1:
            item = self._resource_filter_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._resource_type_checks.clear()
        if not resource_types:
            label = QLabel(tr("diagnostics.resource_filters_empty"))
            self._resource_filter_layout.insertWidget(0, label)
            return
        for resource_type in resource_types:
            check = QCheckBox(resource_type)
            check.setChecked(resource_type in self._selected_resource_types)
            check.setToolTip(
                tr("diagnostics.resource_filter_tooltip", resource_type=resource_type)
            )
            check.stateChanged.connect(self._on_resource_filter_changed)
            self._resource_type_checks[resource_type] = check
            self._resource_filter_layout.insertWidget(
                self._resource_filter_layout.count() - 1, check
            )

    def _on_resource_filter_changed(self, *_args) -> None:
        self._selected_resource_types = {
            resource_type
            for resource_type, check in self._resource_type_checks.items()
            if check.isChecked()
        }
        if self._report:
            self._populate_data_tree(self._report)

    def _populate_data_tree(self, report: DiagnosticsReport) -> None:
        self._data_tree.clear()
        if not report.data_impacts:
            self._data_tree.addTopLevelItem(
                QTreeWidgetItem([tr("diagnostics.empty_data"), "", ""])
            )
            return
        for impact in report.data_impacts:
            target_label = self._compact_path(impact.target_data_path or "")
            item = QTreeWidgetItem(
                [
                    target_label,
                    impact.patch_type,
                    impact.mod_name,
                ]
            )
            item.setToolTip(0, impact.target_data_path or "")
            item.setToolTip(2, impact.mod_name)
            item.setData(0, Qt.ItemDataRole.UserRole, impact)
            self._apply_operation_color(
                item, "modify" if impact.deep_analysis_available else "unknown"
            )
            self._data_tree.addTopLevelItem(item)
            for entry in impact.resource_entries:
                if entry.get("type") not in self._selected_resource_types:
                    continue
                child = QTreeWidgetItem(
                    [
                        f"{entry['type']}/{entry['name']}",
                        tr(f"diagnostics.resource_{entry['operation']}"),
                        impact.mod_name,
                    ]
                )
                child.setData(0, Qt.ItemDataRole.UserRole, (impact, entry))
                child.setToolTip(0, self._resource_tooltip(entry))
                self._apply_operation_color(
                    child, self._resource_operation_color(entry)
                )
                item.addChild(child)
                for file_path in self._resource_files_for_entry(impact, entry):
                    file_item = QTreeWidgetItem(
                        [
                            file_path,
                            tr("diagnostics.operation_file"),
                            impact.mod_name,
                        ]
                    )
                    file_item.setData(
                        0, Qt.ItemDataRole.UserRole, (impact, entry, file_path)
                    )
                    file_item.setToolTip(0, file_path)
                    child.addChild(file_item)
            item.setExpanded(False)
        self._data_tree.setColumnWidth(0, 360)
        self._data_tree.setColumnWidth(1, 110)

    def _populate_preview_compare_panel(self, report: DiagnosticsReport) -> None:
        deep_count = report.summary.deep_analyzable_data_files
        self._set_preview_text(tr("diagnostics.preview_compare_hint", count=deep_count))

    def _populate_issues(self, report: DiagnosticsReport) -> None:
        self._issues_list.clear()
        if not report.issues:
            self._issues_list.addItem(tr("diagnostics.empty_issues"))
            return
        for issue in report.issues:
            item = QListWidgetItem(f"[{issue.severity.upper()}] {issue.title}")
            item.setData(Qt.ItemDataRole.UserRole, issue)
            self._issues_list.addItem(item)

    @staticmethod
    def _apply_operation_color(item: QTreeWidgetItem, operation: str) -> None:
        colors = {
            "add": Qt.GlobalColor.green,
            "modify": Qt.GlobalColor.yellow,
            "replace": Qt.GlobalColor.yellow,
            "conflict": Qt.GlobalColor.red,
        }
        color = colors.get(operation)
        if color:
            for column in range(item.columnCount()):
                item.setForeground(column, color)

    def _show_selected_file(self) -> None:
        items = self._file_tree.selectedItems()
        if not items:
            return
        impact = items[0].data(0, Qt.ItemDataRole.UserRole)
        if not impact:
            return
        if isinstance(impact, DataImpact):
            self._show_data_impact(impact)
            return
        notes = "\n".join(impact.notes)
        diff_text = self._build_text_file_diff(impact)
        if not diff_text and self._looks_text_like(impact.source_path):
            diff_text = self._read_text_preview(impact.source_path)
        self._inspector.setToolTip(
            f"Target: {impact.target_path}\nSource: {impact.source_path}"
        )
        self._inspector.setPlainText(
            tr(
                "diagnostics.file_inspector",
                target=self._display_target_path(
                    impact.target_root,
                    impact.target_relative_path,
                ),
                source=self._compact_path(impact.source_path),
                mod=impact.mod_name,
                operation=tr(f"diagnostics.operation_{impact.operation}"),
                notes=notes or tr("diagnostics.no_extra_notes"),
            )
            + ("\n\n" + diff_text if diff_text else "")
        )
        if diff_text:
            self._set_preview_text(diff_text)
            self._tabs.setCurrentWidget(self._preview_compare_tab)
        elif self._looks_image_like(impact.source_path) or self._looks_audio_like(
            impact.source_path
        ):
            self._set_preview_file(
                impact.source_path,
                title=self._display_target_path(
                    impact.target_root,
                    impact.target_relative_path,
                ),
            )
            self._tabs.setCurrentWidget(self._preview_compare_tab)

    def _open_selected_file(self) -> None:
        items = self._file_tree.selectedItems()
        if not items:
            return
        impact = items[0].data(0, Qt.ItemDataRole.UserRole)
        if isinstance(impact, DataImpact):
            self._tabs.setCurrentWidget(self._data_tab)
            return
        if not impact:
            return
        path = (
            impact.source_path
            if os.path.exists(impact.source_path)
            else impact.target_path
        )
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _build_text_file_diff(self, impact) -> str:
        if not impact.existing or not impact.analyzable:
            return ""
        if not self._looks_text_like(impact.source_path) or not self._looks_text_like(
            impact.target_path
        ):
            return tr("diagnostics.binary_diff_unavailable")
        try:
            with open(impact.target_path, encoding="utf-8", errors="replace") as handle:
                before = handle.read().splitlines()
            with open(impact.source_path, encoding="utf-8", errors="replace") as handle:
                after = handle.read().splitlines()
        except OSError:
            return ""
        diff = "\n".join(
            difflib.unified_diff(
                before,
                after,
                fromfile=impact.target_path,
                tofile=impact.source_path,
                lineterm="",
            )
        )
        return diff or tr("diagnostics.no_text_diff")

    @staticmethod
    def _looks_text_like(path: str) -> bool:
        return (
            str(path or "")
            .lower()
            .endswith(
                (
                    ".txt",
                    ".json",
                    ".csv",
                    ".ini",
                    ".cfg",
                    ".yaml",
                    ".yml",
                    ".xml",
                    ".po",
                    ".lang",
                    ".md",
                    ".gml",
                    ".yy",
                    ".asm",
                    ".shader",
                    ".fsh",
                    ".vsh",
                )
            )
        )

    @staticmethod
    def _looks_image_like(path: str) -> bool:
        return (
            str(path or "")
            .lower()
            .endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"))
        )

    @staticmethod
    def _looks_audio_like(path: str) -> bool:
        return (
            str(path or "").lower().endswith((".wav", ".ogg", ".mp3", ".flac", ".m4a"))
        )

    def _show_selected_data(self) -> None:
        items = self._data_tree.selectedItems()
        if not items:
            return
        data = items[0].data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if isinstance(data, tuple) and len(data) == 3:
            impact, entry, file_path = data
            self._show_resource_file(impact, entry, file_path)
            return
        if isinstance(data, tuple):
            impact, entry = data
            self._show_resource_entry(impact, entry)
            return
        impact: DataImpact = data
        self._show_data_impact(impact)

    def _show_data_impact(self, impact: DataImpact) -> None:
        resources = "\n".join(
            f"{name}: +{counts.get('new', 0)} ~{counts.get('changed', 0)} -{counts.get('deleted', 0)}"
            for name, counts in impact.resource_summary.items()
        )
        notes = tr("diagnostics.g3mpatch_tip") if impact.notes else ""
        self._inspector.setToolTip(
            f"Target: {impact.target_data_path or ''}\nPatch: {impact.patch_path or ''}"
        )
        self._inspector.setPlainText(
            tr(
                "diagnostics.data_inspector",
                target=self._compact_path(impact.target_data_path or ""),
                patch=self._compact_path(impact.patch_path or ""),
                mod=impact.mod_name,
                patch_type=impact.patch_type,
                deep=tr("diagnostics.yes")
                if impact.deep_analysis_available
                else tr("diagnostics.no"),
                resources=resources or notes or tr("diagnostics.no_resource_summary"),
            )
        )

    def _show_resource_entry(self, impact: DataImpact, entry: dict[str, Any]) -> None:
        files = self._resource_files_for_entry(impact, entry)
        file_lines = (
            "\n".join(files[:30]) if files else tr("diagnostics.no_resource_files")
        )
        self._inspector.setToolTip(impact.patch_path or "")
        self._inspector.setPlainText(
            tr(
                "diagnostics.resource_inspector",
                mod=impact.mod_name,
                resource_type=entry.get("type", ""),
                operation=tr(
                    f"diagnostics.resource_{entry.get('operation', 'changed')}"
                ),
                name=entry.get("name", ""),
                patch=self._compact_path(impact.patch_path or ""),
                files=file_lines,
            )
        )
        comparison = self._resource_comparison_text(impact, entry)
        preview = self._preview_g3mpatch_resource_file(impact, files)
        if preview:
            self._set_preview_text((comparison + "\n\n" + preview).strip())
            self._tabs.setCurrentWidget(self._preview_compare_tab)
        elif comparison:
            self._set_preview_text(comparison)
            self._tabs.setCurrentWidget(self._preview_compare_tab)

    def _show_resource_file(
        self, impact: DataImpact, entry: dict[str, Any], file_path: str
    ) -> None:
        self._inspector.setToolTip(f"{impact.patch_path or ''}\n{file_path}")
        self._inspector.setPlainText(
            tr(
                "diagnostics.resource_file_inspector",
                mod=impact.mod_name,
                resource_type=entry.get("type", ""),
                name=entry.get("name", ""),
                file=file_path,
                patch=self._compact_path(impact.patch_path or ""),
            )
        )
        preview = self._preview_g3mpatch_resource_file(impact, [file_path])
        if preview:
            self._set_preview_text(preview)
            self._tabs.setCurrentWidget(self._preview_compare_tab)
            return
        extracted = self._extract_g3mpatch_file(impact, file_path)
        if extracted:
            self._set_preview_file(extracted, title=file_path)
            self._tabs.setCurrentWidget(self._preview_compare_tab)

    def _open_selected_data(self) -> None:
        items = self._data_tree.selectedItems()
        if not items:
            return
        data = items[0].data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple) and len(data) == 3:
            impact, _entry, file_path = data
            self._open_g3mpatch_file(impact, file_path)
            return
        if isinstance(data, tuple):
            impact, entry = data
            files = self._resource_files_for_entry(impact, entry)
            if files:
                self._open_g3mpatch_file(impact, files[0])
            elif impact.patch_path and os.path.exists(impact.patch_path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(impact.patch_path))

    def _resource_files_for_entry(
        self, impact: DataImpact, entry: dict[str, Any]
    ) -> list[str]:
        return list(entry.get("files") or [])

    def _preview_g3mpatch_resource_file(
        self, impact: DataImpact, files: list[str]
    ) -> str:
        if not impact.patch_path:
            return ""
        preview_file = next((file for file in files if self._looks_text_like(file)), "")
        if not preview_file:
            if files:
                return tr("diagnostics.binary_preview_hint", file=files[0])
            return ""
        try:
            with zipfile.ZipFile(impact.patch_path) as archive:
                info = archive.getinfo(preview_file)
                if info.file_size > MAX_G3MPATCH_PREVIEW_BYTES:
                    return tr(
                        "diagnostics.preview_file_too_large",
                        file=preview_file,
                        size=self._format_size(info.file_size),
                        limit=self._format_size(MAX_G3MPATCH_PREVIEW_BYTES),
                    )
                text = archive.read(preview_file).decode("utf-8", errors="replace")
        except (KeyError, OSError, zipfile.BadZipFile):
            return ""
        return f"{preview_file}\n\n{text[:12000]}"

    def _open_g3mpatch_file(self, impact: DataImpact, file_path: str) -> None:
        out_path = self._extract_g3mpatch_file(impact, file_path)
        if out_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(out_path))

    def _extract_g3mpatch_file(self, impact: DataImpact, file_path: str) -> str:
        if not impact.patch_path or not file_path:
            return ""
        try:
            with zipfile.ZipFile(impact.patch_path) as archive:
                info = archive.getinfo(file_path)
                if info.file_size > MAX_G3MPATCH_PREVIEW_BYTES:
                    return ""
                data = archive.read(file_path)
        except (KeyError, OSError, zipfile.BadZipFile):
            return ""
        safe_name = file_path.replace("\\", "/").strip("/").replace("/", "_")
        patch_key = os.path.splitext(os.path.basename(impact.patch_path))[0]
        out_dir = os.path.join(self._preview_temp_dir, patch_key)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, safe_name)
        with open(out_path, "wb") as handle:
            handle.write(data)
        return out_path

    @staticmethod
    def _format_size(size: int) -> str:
        if size >= 1024 * 1024:
            return f"{size / 1024 / 1024:.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B"

    def _set_preview_text(self, text: str) -> None:
        self._stop_preview_audio()
        self._current_audio_path = ""
        self._audio_play_btn.setEnabled(False)
        self._audio_stop_btn.setEnabled(False)
        self._audio_play_btn.setVisible(False)
        self._audio_stop_btn.setVisible(False)
        self._audio_status.setText("")
        self._preview_compare_panel.setPlainText(text)

    def _set_preview_file(self, path: str, *, title: str = "") -> None:
        self._stop_preview_audio()
        self._current_audio_path = ""
        self._audio_play_btn.setEnabled(False)
        self._audio_stop_btn.setEnabled(False)
        self._audio_play_btn.setVisible(False)
        self._audio_stop_btn.setVisible(False)
        self._audio_status.setText("")
        if self._looks_image_like(path):
            url = QUrl.fromLocalFile(path).toString()
            self._preview_compare_panel.setHtml(
                '<h3>{}</h3><p>{}</p><img src="{}" style="max-width: 100%;">'.format(
                    title or os.path.basename(path),
                    tr("diagnostics.image_preview_hint"),
                    url,
                )
            )
            return
        if self._looks_audio_like(path):
            self._current_audio_path = path
            self._audio_play_btn.setEnabled(True)
            self._audio_stop_btn.setEnabled(True)
            self._audio_play_btn.setVisible(True)
            self._audio_stop_btn.setVisible(True)
            self._audio_status.setText(os.path.basename(path))
            self._preview_compare_panel.setPlainText(
                tr(
                    "diagnostics.audio_preview_hint",
                    file=title or os.path.basename(path),
                )
            )
            return
        self._preview_compare_panel.setPlainText(
            tr("diagnostics.binary_preview_hint", file=title or path)
        )

    def _play_preview_audio(self) -> None:
        if not self._current_audio_path:
            return
        self._stop_preview_audio()
        process = Process(
            target=_play_audio_preview_process,
            args=(os.path.abspath(self._current_audio_path),),
            daemon=True,
        )
        process.start()
        self._audio_process = process

    def _stop_preview_audio(self) -> None:
        process = self._audio_process
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=1.0)
        self._audio_process = None

    def _resource_comparison_text(
        self, impact: DataImpact, entry: dict[str, Any]
    ) -> str:
        if not self._report:
            return ""
        resource_type = entry.get("type")
        name = entry.get("name")
        matches = [
            (other_impact, other_entry)
            for other_impact in self._report.data_impacts
            for other_entry in other_impact.resource_entries
            if other_impact.section_id == impact.section_id
            and other_entry.get("type") == resource_type
            and other_entry.get("name") == name
        ]
        if len(matches) <= 1:
            return ""
        mod_names = {other_impact.mod_name for other_impact, _other_entry in matches}
        if len(mod_names) == 1:
            title = tr(
                "diagnostics.multi_data_resource_title",
                resource_type=resource_type,
                name=name,
                count=len(matches),
                mod=next(iter(mod_names)),
            )
        else:
            title = tr(
                "diagnostics.multi_mod_resource_title",
                resource_type=resource_type,
                name=name,
                count=len(mod_names),
            )
        lines = [title]
        for other_impact, other_entry in matches:
            lines.append(
                "- {}: {} ({})".format(
                    other_impact.mod_name,
                    tr(
                        f"diagnostics.resource_{other_entry.get('operation', 'changed')}"
                    ),
                    ", ".join(
                        self._resource_files_for_entry(other_impact, other_entry)[:4]
                    )
                    or tr("diagnostics.no_resource_files"),
                )
            )
        return "\n".join(lines)

    @staticmethod
    def _read_text_preview(path: str) -> str:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                return handle.read()[:12000]
        except OSError:
            return ""

    @staticmethod
    def _resource_tooltip(entry: dict[str, Any]) -> str:
        return f"{entry.get('type', '')}/{entry.get('name', '')}"

    @staticmethod
    def _resource_operation_color(entry: dict[str, Any]) -> str:
        operation = entry.get("operation")
        if operation == "new":
            return "add"
        if operation == "deleted":
            return "conflict"
        return "modify"

    def _show_selected_issue(self, current: QListWidgetItem | None, _previous) -> None:
        if not current:
            return
        issue = current.data(Qt.ItemDataRole.UserRole)
        if not issue:
            return
        self._inspector.setToolTip(issue.target_path)
        self._inspector.setPlainText(
            tr(
                "diagnostics.issue_inspector",
                title=issue.title,
                explanation=issue.explanation,
                target=self._compact_path(issue.target_path),
                mods=", ".join(issue.affected_mods),
                recommendation=issue.recommendation,
            )
        )

    @staticmethod
    def _display_target_path(target_root: str, relative_path: str) -> str:
        root_name = os.path.basename(os.path.normpath(target_root)) or target_root
        rel = str(relative_path or "").replace("\\", "/").strip("/")
        return f"{root_name}/{rel}" if rel else root_name

    @staticmethod
    def _compact_path(path: str) -> str:
        if not path:
            return ""
        normalized = os.path.normpath(path)
        parts = normalized.replace("\\", "/").split("/")
        if len(parts) <= 2:
            return normalized.replace("\\", "/")
        return "/".join(parts[-2:])

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("diagnostics.title"))
        self._title_label.setText(tr("diagnostics.title"))
        self._close_btn.setText(tr("common.close"))
        self._mods_label.setText(tr("diagnostics.mods"))
        self._audio_play_btn.setText(tr("diagnostics.preview_play"))
        self._audio_stop_btn.setText(tr("diagnostics.preview_stop"))
        self._run_preflight_btn.setText(tr("diagnostics.run_actual_analysis"))
        self._run_preflight_btn.setToolTip(
            tr("diagnostics.run_actual_analysis_tooltip")
        )
        self._cancel_preflight_btn.setText(tr("diagnostics.cancel_actual_analysis"))
        self._export_preflight_btn.setText(tr("diagnostics.export_actual_report"))
        self._preflight_search.setPlaceholderText(
            tr("diagnostics.search_actual_resources")
        )
        self._preflight_steps_tree.setHeaderLabels(
            [
                tr("diagnostics.column_step"),
                tr("diagnostics.column_mod"),
                tr("diagnostics.column_status"),
            ]
        )
        common_headers = [
            tr("diagnostics.column_target"),
            tr("diagnostics.column_operation"),
            tr("diagnostics.column_mod"),
        ]
        self._preflight_resources_tree.setHeaderLabels(common_headers)
        self._preflight_files_tree.setHeaderLabels(common_headers)
        self._scope_label.setText(self._scope_text())
        self._refresh_mod_row_labels()
        for index, key in enumerate(
            (
                "diagnostics.tab_overview",
                "diagnostics.tab_files",
                "diagnostics.tab_data",
                "diagnostics.tab_preview_compare",
                "diagnostics.tab_issues",
                "diagnostics.tab_actual_steps",
                "diagnostics.tab_actual_resources",
                "diagnostics.tab_actual_files",
            )
        ):
            self._tabs.setTabText(index, tr(key))
        if self._report:
            self._on_report_ready(self._report)
        if self._preflight_report:
            self._populate_preflight_report(self._preflight_report)

    def refresh_theme(self) -> None:
        self._apply_theme()

    def _apply_theme(self) -> None:
        theme = get_dialog_theme_values(self._app_state)
        base = build_dialog_theme_stylesheet(self._app_state)
        extra = f"""
            QLabel#diagnostics_title {{
                font-size: 16px;
            }}
            QLabel#diagnostics_scope {{
                color: {theme["main_text"]};
                font-size: 12px;
            }}
            QFrame#diagnostics_mod_row {{
                border: 1px solid {theme["border"]};
                border-radius: {theme["field_radius"]}px;
                background-color: {theme["background"]};
            }}
            QLabel#diagnostics_mod_detail {{
                color: {theme["main_text"]};
                font-size: 11px;
            }}
            QTextEdit, QTreeWidget, QScrollArea {{
                background-color: {theme["background"]};
                border: 2px solid {theme["border"]};
                border-radius: {theme["field_radius"]}px;
                color: {theme["main_text"]};
                padding: 6px;
            }}
            QSplitter::handle {{
                background-color: transparent;
                margin: 0 4px;
            }}
            QSplitter::handle:hover {{
                background-color: {theme["border"]};
                border-radius: 3px;
            }}
        """
        self.setStyleSheet(base + extra)

    def _refresh_mod_row_labels(self) -> None:
        for mod_data in self._all_mods:
            mod_key = self._mod_identity_key(mod_data)
            check = self._mod_checks.get(mod_key)
            detail = self._mod_rows.get(mod_key)
            if not check:
                continue
            profile_active = mod_key in self._active_mod_keys
            check.setText(self._mod_checkbox_text(mod_data, profile_active))
            check.setToolTip(self._mod_tooltip(mod_data, profile_active))
            if detail:
                detail.setText(self._mod_detail_text(mod_data))

    def _scope_text(self) -> str:
        game_mode = getattr(self._app_state, "game_mode", None)
        game_id = getattr(game_mode, "game_id", "") or tr("diagnostics.unknown_scope")
        chapter_id = self._current_scope_chapter()
        if chapter_id:
            return tr("diagnostics.scope_chapter", game=game_id, chapter=chapter_id)
        return tr("diagnostics.scope_game", game=game_id)

    def _current_scope_chapter(self) -> str | None:
        if getattr(self._app_state, "current_mode", None) != "chapter":
            return None
        return getattr(self._app_state, "selected_chapter_id", None)

    @staticmethod
    def _mod_identity_key(mod_data) -> str:
        mod_id = str(get_mod_id(mod_data) or "").strip().casefold()
        name = str(get_mod_name(mod_data, "") or "").strip().casefold()
        game = str(getattr(mod_data, "game", "") or "").strip().casefold()
        return "|".join(part for part in (mod_id, name, game) if part)

    def _mod_checkbox_text(self, mod_data, active: bool) -> str:
        return get_mod_name(mod_data)

    def _mod_tooltip(self, mod_data, active: bool) -> str:
        return tr(
            "diagnostics.mod_tooltip",
            name=get_mod_name(mod_data),
            state=tr(
                "diagnostics.mod_state_enabled"
                if active
                else "diagnostics.mod_state_available"
            ),
            scope=self._scope_text(),
            kind=self._mod_kind_label(mod_data),
        )

    def _mod_detail_text(self, mod_data) -> str:
        sections = self._section_labels_for_mod(mod_data)
        return tr(
            "diagnostics.mod_detail",
            kind=self._mod_kind_label(mod_data),
            sections=(
                ", ".join(sections) if sections else tr("diagnostics.no_section_files")
            ),
        )

    def _section_labels_for_mod(self, mod_data) -> list[str]:
        game_mode = getattr(self._app_state, "game_mode", None)
        labels = []
        for tab in getattr(game_mode, "tabs", []) or []:
            if hasattr(mod_data, "get_chapter_data") and mod_data.get_chapter_data(
                tab.tab_id
            ):
                labels.append(str(tab.tab_id).replace("deltarune_", "CH"))
        return labels

    def _mod_kind_label(self, mod_data) -> str:
        chapter_id = self._current_scope_chapter()
        game_mode = getattr(self._app_state, "game_mode", None)
        section_ids = (
            [chapter_id]
            if chapter_id
            else [tab.tab_id for tab in getattr(game_mode, "tabs", []) or []]
        )
        kinds = set()
        for cid in section_ids:
            file_data = (
                mod_data.get_chapter_data(cid)
                if hasattr(mod_data, "get_chapter_data")
                else None
            )
            if not file_data:
                continue
            data_path = str(getattr(file_data, "data_file_path", "") or "").lower()
            if data_path.endswith(".g3mpatch"):
                kinds.add("G3MPATCH")
            elif data_path.endswith((".xdelta", ".vcdiff")):
                kinds.add("XDELTA")
            elif data_path.endswith(".csx"):
                kinds.add("CSX")
            elif data_path.endswith((".win", ".unx", ".ios", ".droid")):
                kinds.add("DATA")
            if getattr(file_data, "extra_files", None):
                kinds.add("FILES")
        return " + ".join(sorted(kinds)) or tr("diagnostics.mod_kind_unknown")

    def closeEvent(self, event) -> None:
        self._stop_preview_audio()
        workers = [self._worker, self._preflight_worker]
        running = [worker for worker in workers if worker and worker.isRunning()]
        for worker in running:
            if hasattr(worker, "cancel"):
                worker.cancel()
            else:
                worker.requestInterruption()
            worker.wait(1000)
        still_running = [worker for worker in running if worker.isRunning()]
        if still_running:
            if not getattr(self, "_close_when_worker_finishes", False):
                self._close_when_worker_finishes = True
                for worker in still_running:
                    worker.finished.connect(self.close)
            event.ignore()
            return
        event.accept()
        self.deleteLater()
