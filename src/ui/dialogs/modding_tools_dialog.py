"""Non-modal Modding Tools dialog with Convert DATA, Patch, Merge, Info, Diff tabs."""

import json
import logging
import os
import shutil
import tempfile
import threading
import zipfile
from contextlib import suppress

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.localization_service import localization_service, tr
from services.warning_service import create_warning_event
from ui.common.dialog_theme import (
    build_dialog_theme_stylesheet,
    get_dialog_theme_values,
)
from ui.common.feedback import FeedbackManager
from ui.utils.thread_lifetime import ManagedQThread, retire_qthread
from utils.file_utils import cleanup_temporary_directory, managed_temporary_directory
from utils.native_integration import (
    get_existing_directory,
    get_open_file_name,
    get_open_file_names,
    get_save_file_name,
)
from utils.process_utils import format_filesystem_error

logger = logging.getLogger(__name__)

_DATA_FILTER = "Data files (*.win *.ios *.unx *.droid);;All Files (*)"
_G3M_PATCH_FILTER = "Patch files (*.g3mpatch *.zip);;All Files (*)"
_CSX_FILTER = "Script files (*.csx);;All Files (*)"
_PATCH_FILTER = "Patch files (*.g3mpatch *.zip *.xdelta *.vcdiff *.csx);;All Files (*)"
_DATA_PATCH_FILTER = (
    "Data / Patch files (*.win *.ios *.unx *.droid *.g3mpatch *.zip *.xdelta *.vcdiff *.csx);;All Files (*)"
)
_ALL_FILTER = "All Files (*)"
_READY_DATA_TARGETS = ("data.win", "game.ios", "game.win")
_CONVERT_TARGET_OPTIONS = ("g3mpatch", "xdelta", *_READY_DATA_TARGETS)
_MONOSPACE_FONT_SIZE_PX = 12


def _css_url(path: str) -> str:
    return path.replace("\\", "/").replace(" ", "%20")


def _write_checkbox_checkmark(color: str) -> str:
    safe_color = color.strip() if color else "#00aa6a"
    file_key = safe_color.strip("#").replace("/", "_").replace("\\", "_")
    path = os.path.join(tempfile.gettempdir(), f"g3m_checkbox_check_{file_key}.svg")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        f'<path fill="none" stroke="{safe_color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round" d="M3.2 8.4 6.5 11.7 12.8 4.3"/>'
        "</svg>"
    )
    try:
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg)
    except Exception:
        logger.debug("Failed to write checkbox checkmark asset", exc_info=True)
        return ""
    return path


def _format_progress_status(percent: int, label: str) -> str:
    clean_percent = max(0, min(100, int(percent)))
    clean_label = str(label or "").strip()
    if clean_label:
        return f"{clean_label}: {clean_percent}%"
    return f"{tr('modding_tools.running')} {clean_percent}%"


def _safe_warning(parent, title: str, message: str) -> None:
    try:
        QMessageBox.warning(parent, title, message)
    except Exception:
        logger.warning("Modding tools warning dialog failed", exc_info=True)


def _safe_question(parent, title: str, message: str, buttons, default_button):
    try:
        return QMessageBox.question(parent, title, message, buttons, default_button)
    except Exception:
        logger.warning("Modding tools question dialog failed", exc_info=True)
        return default_button


def _safe_set_status(label, message: str) -> None:
    try:
        label.setText(message)
    except Exception:
        logger.warning("Modding tools status update failed", exc_info=True)


def _set_g3mtool_failure_status(label, operation: str, rc: int, out: str, err: str) -> None:
    details = (err or out or "").strip()
    if details:
        logger.info(
            "Modding tools %s failed with code %s: %s",
            operation,
            rc,
            details,
        )
    _safe_set_status(label, tr("modding_tools.failed_details_logged"))


def _show_g3mtool_failure(parent, label, operation: str, rc: int, out: str, err: str) -> None:
    _set_g3mtool_failure_status(label, operation, rc, out, err)
    _safe_warning(parent, tr("modding_tools.title"), tr("modding_tools.failed_details_logged"))


def _warning_id_for_g3mtool_failure(operation: str, details: str) -> str:
    lower_details = str(details or "").lower()
    if operation == "merge" or "merge" in lower_details:
        return "merge_failed"
    if "xdelta" in lower_details or "vcdiff" in lower_details:
        return "xdelta_apply_failed"
    if "g3mpatch" in lower_details or operation == "patch":
        return "g3mpatch_apply_failed"
    return "legacy_patching_warning"


def _show_g3mtool_warning_failure(
    parent,
    app_state,
    label,
    operation: str,
    rc: int,
    out: str,
    err: str,
) -> None:
    details = (err or out or "").strip()
    _set_g3mtool_failure_status(label, operation, rc, out, err)
    event = create_warning_event(
        _warning_id_for_g3mtool_failure(operation, details),
        details=details,
        fallback_message=tr("modding_tools.failed_details_logged"),
    )
    feedback = FeedbackManager(parent)
    feedback.app_state = app_state
    feedback.ask_patching_warning(event, details)


def _is_g3mpatch_source(path: str) -> bool:
    lower_path = str(path or "").lower()
    if lower_path.endswith(".g3mpatch"):
        return True
    if not lower_path.endswith(".zip"):
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            archive.getinfo("g3mpatch.json")
        return True
    except Exception:
        return False


def _is_xdelta_source(path: str) -> bool:
    return str(path or "").lower().endswith((".xdelta", ".vcdiff"))


def _is_csx_source(path: str) -> bool:
    return str(path or "").lower().endswith(".csx")


def _apply_source_to_data(
    g3m,
    original: str,
    patch: str,
    output: str,
    progress_callback=None,
):
    if _is_g3mpatch_source(patch):
        return g3m.apply_patch(
            original,
            patch,
            output,
            progress_callback=progress_callback,
        )
    if _is_xdelta_source(patch):
        return g3m.xpatch_apply(
            original,
            patch,
            output,
            progress_callback=progress_callback,
        )
    if _is_csx_source(patch):
        return g3m.execute(
            patch,
            data_file=original,
            output_path=output,
            progress_callback=progress_callback,
        )
    return -1, "", f"Unsupported source patch format: {patch}"


def _patch_create(
    g3m,
    original: str,
    modified: str,
    output: str,
    *,
    include_xdelta_fallback: bool = False,
    progress_callback=None,
):
    """Call patch_create with optional fallback support when available."""
    try:
        return g3m.patch_create(
            original,
            modified,
            output,
            include_xdelta_fallback=include_xdelta_fallback,
            progress_callback=progress_callback,
        )
    except TypeError as exc:
        if "include_xdelta_fallback" not in str(exc):
            if "progress_callback" not in str(exc):
                raise
            return g3m.patch_create(
                original,
                modified,
                output,
                include_xdelta_fallback=include_xdelta_fallback,
            )
        try:
            return g3m.patch_create(
                original,
                modified,
                output,
                progress_callback=progress_callback,
            )
        except TypeError as nested_exc:
            if "progress_callback" not in str(nested_exc):
                raise
            return g3m.patch_create(original, modified, output)


def _convert_target_mode(index: int) -> str:
    if 0 <= index < len(_CONVERT_TARGET_OPTIONS):
        return _CONVERT_TARGET_OPTIONS[index]
    return _CONVERT_TARGET_OPTIONS[0]


def _is_ready_data_source(path: str) -> bool:
    return str(path or "").lower().endswith((".win", ".ios", ".unx", ".droid"))


def _target_is_ready_data(target_mode: str) -> bool:
    return target_mode in _READY_DATA_TARGETS


def _target_version_label(target_mode: str) -> str:
    return target_mode


def _rename_data_output_name(target_name: str) -> str:
    return target_name


def _should_convert_source_to_target(path: str, target_mode: str) -> bool:
    lower_path = str(path or "").lower()
    if not lower_path:
        return False
    source_name = os.path.basename(lower_path)
    if target_mode == "g3mpatch":
        return _is_xdelta_source(path) or _is_csx_source(path)
    if target_mode == "xdelta":
        return _is_g3mpatch_source(path) or _is_csx_source(path)
    if target_mode in _READY_DATA_TARGETS:
        if _is_g3mpatch_source(path) or _is_xdelta_source(path) or _is_csx_source(path):
            return True
        if _is_ready_data_source(path):
            if source_name not in _READY_DATA_TARGETS:
                return False
            return source_name != target_mode
    return False


def _resolve_target_data_name(original_path: str, target_mode: str) -> str:
    if target_mode in _READY_DATA_TARGETS:
        return target_mode
    return os.path.basename(original_path)


def _get_app_font(app_state) -> str:
    """Return the current G3M font family."""
    ff = (app_state.local_config.get("custom_font_family") or "").strip()
    if not ff:
        parent = getattr(app_state, "_app_window", None)
        ff = (getattr(parent, "custom_font_family", None) or "").strip() if parent else ""
    if not ff:
        ff = (localization_service.load_font() or "").strip()
    return f"'{ff}'" if ff else ""


class _WorkerThread(ManagedQThread):
    """Run a G3M command off the UI thread."""

    result_ready = pyqtSignal(int, str, str)
    progress = pyqtSignal(int, str)

    def __init__(self, func, args, parent=None) -> None:
        super().__init__(parent)
        self._func, self._args = func, args

    def run(self):
        if self.isInterruptionRequested():
            return
        try:
            rc, out, err = self._func(*self._args, progress_callback=self.progress.emit)
        except TypeError as exc:
            if "progress_callback" not in str(exc):
                self.result_ready.emit(-1, "", str(exc))
                return
            try:
                rc, out, err = self._func(*self._args)
            except Exception as inner_exc:
                self.result_ready.emit(-1, "", str(inner_exc))
                return
        except Exception as e:
            self.result_ready.emit(-1, "", str(e))
            return
        if not self.isInterruptionRequested():
            self.result_ready.emit(rc, out, err)


class _PathRow(QWidget):
    """Reusable row: label + line-edit + browse button."""

    text_changed = pyqtSignal(str)

    def __init__(
        self,
        label_key: str,
        file_filter: str,
        parent=None,
        save_mode: bool = False,
        dir_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self._filter = file_filter
        self._save_mode = save_mode
        self._dir_mode = dir_mode
        self._save_path_getter = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._label = QLabel(tr(label_key))
        self._label.setMinimumWidth(80)
        self._label_key = label_key
        lay.addWidget(self._label)
        self._edit = QLineEdit()
        self._edit.setPlaceholderText(tr("ui.file_path_placeholder"))
        self._edit.setToolTip(tr("tooltips.file_path_field"))
        self._edit.textChanged.connect(self.text_changed.emit)
        lay.addWidget(self._edit, 1)
        self._btn = QPushButton(tr("ui.browse_button"))
        self._btn.setObjectName("modding_tools_browse_btn")
        self._btn.setToolTip(tr("tooltips.browse_file"))
        self._btn.clicked.connect(self._browse)
        lay.addWidget(self._btn)

    def _browse(self):
        if self._dir_mode:
            path = get_existing_directory(
                self,
                tr("dialogs.select_target_folder"),
                self.path(),
            )
        elif self._save_mode:
            start_path = self.path()
            if callable(self._save_path_getter):
                with suppress(Exception):
                    candidate = self._save_path_getter()
                    if isinstance(candidate, str) and candidate:
                        start_path = candidate
            path, _ = get_save_file_name(
                self, tr("ui.save_file"), start_path, self._filter
            )
        else:
            path, _ = get_open_file_name(
                self, tr("ui.select_file"), "", self._filter
            )
        if path:
            self._edit.setText(path)

    def path(self) -> str:
        return self._edit.text().strip()

    def set_path(self, p: str):
        self._edit.setText(p)

    def set_save_path_getter(self, getter) -> None:
        self._save_path_getter = getter

    def relocalize(self):
        self._label.setText(tr(self._label_key))
        self._edit.setPlaceholderText(tr("ui.file_path_placeholder"))
        self._btn.setText(tr("ui.browse_button"))


class _ConvertWorkerThread(ManagedQThread):
    """Two-step conversion: apply source patch → create target format patch."""

    result_ready = pyqtSignal(int, str, str)
    progress = pyqtSignal(int, str)

    def __init__(
        self,
        g3m,
        orig,
        patch,
        output,
        target_is_xdelta,
        include_xdelta_fallback=False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._g3m = g3m
        self._orig, self._patch, self._output = orig, patch, output
        self._target_is_xdelta = target_is_xdelta
        self._include_xdelta_fallback = include_xdelta_fallback

    def run(self):
        try:
            with managed_temporary_directory(prefix="g3m_convert_") as tmp:
                temp_modified = os.path.join(tmp, "modified.tmp")
                rc, out, err = _apply_source_to_data(
                    self._g3m,
                    self._orig,
                    self._patch,
                    temp_modified,
                    progress_callback=lambda percent, label: self.progress.emit(
                        min(50, max(1 if percent > 0 else 0, round(percent * 0.5))),
                        label,
                    ),
                )
                if rc != 0:
                    self.result_ready.emit(rc, out, err)
                    return
                if self.isInterruptionRequested():
                    return
                if self._target_is_xdelta:
                    rc, out, err = self._g3m.xpatch_create(
                        self._orig,
                        temp_modified,
                        self._output,
                        progress_callback=lambda percent, label: self.progress.emit(
                            min(100, 50 + max(1 if percent > 0 else 0, round(percent * 0.5))),
                            label,
                        ),
                    )
                else:
                    rc, out, err = _patch_create(
                        self._g3m,
                        self._orig,
                        temp_modified,
                        self._output,
                        include_xdelta_fallback=self._include_xdelta_fallback,
                        progress_callback=lambda percent, label: self.progress.emit(
                            min(100, 50 + max(1 if percent > 0 else 0, round(percent * 0.5))),
                            label,
                        ),
                    )
                if not self.isInterruptionRequested():
                    self.result_ready.emit(rc, out, err)
        except Exception as e:
            self.result_ready.emit(-1, "", str(e))


class _CreatePatchWorkerThread(ManagedQThread):
    """Create a patch from two data files and report the tool return code."""

    result_ready = pyqtSignal(int, str, str)
    progress = pyqtSignal(int, str)

    def __init__(
        self,
        g3m,
        orig,
        modified,
        output,
        target_is_xdelta,
        include_xdelta_fallback=False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._g3m = g3m
        self._orig = orig
        self._modified = modified
        self._output = output
        self._target_is_xdelta = target_is_xdelta
        self._include_xdelta_fallback = include_xdelta_fallback

    def run(self):
        if self.isInterruptionRequested():
            return
        try:
            if self._target_is_xdelta:
                rc, out, err = self._g3m.xpatch_create(
                    self._orig,
                    self._modified,
                    self._output,
                    progress_callback=self.progress.emit,
                )
            else:
                rc, out, err = _patch_create(
                    self._g3m,
                    self._orig,
                    self._modified,
                    self._output,
                    include_xdelta_fallback=self._include_xdelta_fallback,
                    progress_callback=self.progress.emit,
                )
            if not self.isInterruptionRequested():
                self.result_ready.emit(rc, out, err)
        except Exception as e:
            self.result_ready.emit(-1, "", str(e))


class _PatchTab(QWidget):
    def __init__(self, g3m, app_state, parent=None) -> None:
        super().__init__(parent)
        self._g3m, self._app_state = g3m, app_state
        self._worker = None
        self._output_user_modified = False
        self._setting_output_text = False
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        self._mode_label = QLabel(tr("modding_tools.patch_mode"))
        mode_row.addWidget(self._mode_label)
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["g3mpatch", "xdelta", "csx"])
        self._mode_combo.setToolTip(tr("tooltips.modding_tools_mode"))
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self._mode_combo)
        mode_row.addSpacing(20)
        self._action_label = QLabel(tr("modding_tools.patch_action"))
        mode_row.addWidget(self._action_label)
        self._action_combo = QComboBox()
        self._action_combo.addItems(
            [
                tr("modding_tools.action_create"),
                tr("modding_tools.action_apply"),
                tr("modding_tools.action_convert"),
            ]
        )
        self._action_combo.setToolTip(tr("tooltips.modding_tools_action"))
        self._action_combo.currentIndexChanged.connect(self._on_action_changed)
        mode_row.addWidget(self._action_combo)
        mode_row.addStretch()
        lay.addLayout(mode_row)

        batch_row = QHBoxLayout()
        self._batch_cb = QCheckBox(tr("modding_tools.batch_mode"))
        self._batch_cb.setToolTip(tr("tooltips.modding_tools_batch_mode"))
        self._batch_cb.toggled.connect(self._on_batch_toggled)
        self._continue_cb = QCheckBox(tr("modding_tools.continue_on_error"))
        self._continue_cb.setToolTip(tr("tooltips.modding_tools_continue_on_error"))
        batch_row.addWidget(self._batch_cb)
        batch_row.addWidget(self._continue_cb)
        batch_row.addStretch()
        lay.addLayout(batch_row)

        self._original_row = _PathRow("modding_tools.original_file", _DATA_FILTER)
        lay.addWidget(self._original_row)
        self._second_row = _PathRow("modding_tools.modified_file", _DATA_FILTER)
        lay.addWidget(self._second_row)
        self._batch_label = QLabel(tr("modding_tools.batch_inputs"))
        lay.addWidget(self._batch_label)
        self._batch_list = QListWidget()
        self._batch_list.setMinimumHeight(120)
        lay.addWidget(self._batch_list, 1)
        batch_btns = QHBoxLayout()
        batch_btns.setSpacing(6)
        self._batch_add_btn = QPushButton(tr("modding_tools.merge_add"))
        self._batch_add_btn.clicked.connect(self._on_batch_add)
        self._batch_remove_btn = QPushButton(tr("modding_tools.merge_remove"))
        self._batch_remove_btn.clicked.connect(self._on_batch_remove)
        batch_btns.addWidget(self._batch_add_btn)
        batch_btns.addWidget(self._batch_remove_btn)
        batch_btns.addStretch()
        lay.addLayout(batch_btns)
        self._output_row = _PathRow(
            "modding_tools.output_file", _ALL_FILTER, save_mode=True
        )
        self._output_row.set_save_path_getter(self._suggest_output_path)
        self._output_row.text_changed.connect(self._on_output_text_changed)
        lay.addWidget(self._output_row)
        self._batch_output_row = _PathRow(
            "modding_tools.output_folder", _ALL_FILTER, dir_mode=True
        )
        lay.addWidget(self._batch_output_row)
        self._original_row.text_changed.connect(self._maybe_suggest_output_path)
        self._second_row.text_changed.connect(self._maybe_suggest_output_path)

        self._xdelta_fallback_checkbox = QCheckBox(
            tr("checkboxes.g3mpatch_xdelta_fallback")
        )
        self._xdelta_fallback_checkbox.setToolTip(
            tr("tooltips.g3mpatch_xdelta_fallback")
        )
        lay.addWidget(self._xdelta_fallback_checkbox)
        self._update_xdelta_fallback_visibility()
        self._update_batch_visibility()

        lay.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._run_btn = QPushButton(tr("modding_tools.run"))
        self._run_btn.setObjectName("modding_tools_run_btn")
        self._run_btn.setToolTip(tr("tooltips.run_tool"))
        self._run_btn.clicked.connect(self._on_run)
        btn_row.addWidget(self._run_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._status_label = QLabel("")
        self._status_label.setObjectName("modding_tools_status")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        lay.addWidget(self._status_label)

    def _on_action_changed(self, _idx):
        if (
            self._mode_combo.currentText() == "csx"
            and self._action_combo.currentIndex() != 1
        ):
            self._action_combo.blockSignals(True)
            self._action_combo.setCurrentIndex(1)
            self._action_combo.blockSignals(False)
        action = self._action_combo.currentIndex()
        if action == 2:
            key = "modding_tools.source_patch"
        elif action == 1:
            key = "modding_tools.patch_file"
        else:
            key = "modding_tools.modified_file"
        self._second_row._label.setText(tr(key))
        self._second_row._label_key = key
        self._update_filters()
        self._update_xdelta_fallback_visibility()
        self._update_batch_visibility()
        self._maybe_suggest_output_path()

    def _on_mode_changed(self, _idx):
        if (
            self._mode_combo.currentText() == "csx"
            and self._action_combo.currentIndex() != 1
        ):
            self._action_combo.blockSignals(True)
            self._action_combo.setCurrentIndex(1)
            self._action_combo.blockSignals(False)
        self._update_filters()
        self._update_xdelta_fallback_visibility()
        self._update_batch_visibility()
        self._maybe_suggest_output_path()

    def _on_batch_toggled(self, _checked: bool) -> None:
        self._update_batch_visibility()
        self._maybe_suggest_output_path()

    def _batch_supported(self) -> bool:
        return (
            self._mode_combo.currentText() == "g3mpatch"
            and self._action_combo.currentIndex() in {0, 1}
        )

    def _update_batch_visibility(self) -> None:
        supported = self._batch_supported()
        self._batch_cb.setEnabled(supported)
        if not supported and self._batch_cb.isChecked():
            self._batch_cb.blockSignals(True)
            self._batch_cb.setChecked(False)
            self._batch_cb.blockSignals(False)
        batch = supported and self._batch_cb.isChecked()
        for widget in (
            self._batch_label,
            self._batch_list,
            self._batch_add_btn,
            self._batch_remove_btn,
            self._batch_output_row,
            self._continue_cb,
        ):
            widget.setVisible(batch)
        self._second_row.setVisible(not batch)
        self._output_row.setVisible(not batch)

    def _on_batch_add(self):
        file_filter = _DATA_FILTER if self._action_combo.currentIndex() == 0 else _G3M_PATCH_FILTER
        paths, _ = get_open_file_names(
            self, tr("ui.select_file"), "", file_filter
        )
        for path in paths:
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self._batch_list.addItem(item)

    def _on_batch_remove(self):
        for item in self._batch_list.selectedItems():
            self._batch_list.takeItem(self._batch_list.row(item))

    def _update_xdelta_fallback_visibility(self) -> None:
        visible = (
            self._mode_combo.currentText() == "g3mpatch"
            and self._action_combo.currentIndex() in {0, 2}
        )
        self._xdelta_fallback_checkbox.setVisible(visible)

    def _update_filters(self):
        mode = self._mode_combo.currentText()
        action = self._action_combo.currentIndex()
        self._output_row._filter = _DATA_FILTER
        if action == 2:
            self._original_row._filter = _DATA_FILTER
            self._second_row._filter = _PATCH_FILTER
            self._output_row._filter = _PATCH_FILTER
        elif mode == "xdelta":
            self._original_row._filter = _ALL_FILTER
            self._second_row._filter = _ALL_FILTER
            self._output_row._filter = _PATCH_FILTER if action == 0 else _DATA_FILTER
        elif action == 0:
            self._original_row._filter = _DATA_FILTER
            self._second_row._filter = _DATA_FILTER
            self._output_row._filter = _G3M_PATCH_FILTER
        else:
            self._original_row._filter = _DATA_FILTER
            if mode == "csx":
                self._second_row._filter = _CSX_FILTER
            else:
                self._second_row._filter = _G3M_PATCH_FILTER

    def _on_output_text_changed(self, _text: str) -> None:
        if not self._setting_output_text:
            self._output_user_modified = True

    def _set_output_path(self, path: str) -> None:
        self._setting_output_text = True
        try:
            self._output_row.set_path(path)
        finally:
            self._setting_output_text = False

    @staticmethod
    def _replace_extension(path: str, suffix: str) -> str:
        base = os.path.splitext(path)[0]
        return base + suffix

    def _suggest_output_path(self) -> str:
        mode = self._mode_combo.currentText()
        action = self._action_combo.currentIndex()
        orig = self._original_row.path()
        second = self._second_row.path()
        if action == 0:
            seed = second or orig
            if not seed:
                return ""
            suffix = ".csx" if mode == "csx" else ".xdelta" if mode == "xdelta" else ".g3mpatch"
            return self._replace_extension(seed, suffix)
        if action == 1:
            if not orig:
                return ""
            base, ext = os.path.splitext(orig)
            return f"{base}_patched{ext or '.win'}"
        if not second:
            return ""
        suffix = ".csx" if mode == "csx" else ".xdelta" if mode == "xdelta" else ".g3mpatch"
        return self._replace_extension(second, suffix)

    def _maybe_suggest_output_path(self, *_args) -> None:
        if self._output_user_modified and self._output_row.path():
            return
        suggested = self._suggest_output_path()
        if suggested:
            self._set_output_path(suggested)
            self._output_user_modified = False

    def _on_run(self):
        if not self._g3m or not self._g3m.is_available():
            _safe_warning(self, tr("modding_tools.title"), tr("errors.g3mtool_not_available"))
            return
        orig, second, out = (
            self._original_row.path(),
            self._second_row.path(),
            self._output_row.path(),
        )
        mode = self._mode_combo.currentText()
        action = self._action_combo.currentIndex()
        if self._batch_supported() and self._batch_cb.isChecked():
            self._on_batch_run(orig)
            return
        if not orig or not second or not out:
            _safe_warning(self, tr("modding_tools.title"), tr("modding_tools.select_all_paths"))
            return
        self._run_btn.setEnabled(False)
        _safe_set_status(self._status_label, tr("modding_tools.running"))
        if action == 2:
            target_is_xdelta = mode == "xdelta"
            self._worker = _ConvertWorkerThread(
                self._g3m,
                orig,
                second,
                out,
                target_is_xdelta,
                self._xdelta_fallback_checkbox.isChecked(),
            )
        else:
            is_create = action == 0
            if mode == "csx":
                self._worker = _WorkerThread(
                    self._g3m.execute,
                    (second, None, orig, out),
                )
            elif is_create:
                self._worker = _CreatePatchWorkerThread(
                    self._g3m,
                    orig,
                    second,
                    out,
                    mode == "xdelta",
                    self._xdelta_fallback_checkbox.isChecked(),
                )
            elif mode == "xdelta":
                self._worker = _WorkerThread(self._g3m.xpatch_apply, (orig, second, out))
            else:
                self._worker = _WorkerThread(self._g3m.apply_patch, (orig, second, out))
        self._worker.progress.connect(self._on_progress)
        self._worker.result_ready.connect(self._on_finished)
        self._worker.start()

    def _on_batch_run(self, orig: str) -> None:
        out_dir = self._batch_output_row.path()
        inputs = [
            item.data(Qt.ItemDataRole.UserRole)
            for i in range(self._batch_list.count())
            if (item := self._batch_list.item(i)) is not None
        ]
        if not orig or not inputs or not out_dir:
            _safe_warning(self, tr("modding_tools.title"), tr("modding_tools.batch_need_files"))
            return
        self._run_btn.setEnabled(False)
        _safe_set_status(self._status_label, tr("modding_tools.running"))
        if self._action_combo.currentIndex() == 0:
            self._worker = _WorkerThread(
                self._g3m.batch_create_patches,
                (
                    orig,
                    inputs,
                    out_dir,
                    self._continue_cb.isChecked(),
                    self._xdelta_fallback_checkbox.isChecked(),
                ),
            )
        else:
            self._worker = _WorkerThread(
                self._g3m.batch_apply_patches,
                (
                    orig,
                    inputs,
                    out_dir,
                    self._continue_cb.isChecked(),
                    self._xdelta_fallback_checkbox.isChecked(),
                ),
            )
        self._worker.progress.connect(self._on_progress)
        self._worker.result_ready.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, percent: int, label: str) -> None:
        _safe_set_status(self._status_label, _format_progress_status(percent, label))

    def _on_finished(self, rc, out, err):
        self._run_btn.setEnabled(True)
        retire_qthread(self._worker)
        self._worker = None
        if rc == 0:
            _safe_set_status(self._status_label, tr("modding_tools.success"))
        else:
            _show_g3mtool_warning_failure(
                self, self._app_state, self._status_label, "patch", rc, out, err
            )

    def has_user_interaction(self) -> bool:
        return bool(
            self._original_row.path()
            or self._second_row.path()
            or self._batch_list.count()
            or self._output_row.path()
            or self._batch_output_row.path()
            or self._worker
        )

    def relocalize(self):
        self._mode_label.setText(tr("modding_tools.patch_mode"))
        self._action_label.setText(tr("modding_tools.patch_action"))
        self._action_combo.setItemText(0, tr("modding_tools.action_create"))
        self._action_combo.setItemText(1, tr("modding_tools.action_apply"))
        self._action_combo.setItemText(2, tr("modding_tools.action_convert"))
        self._original_row.relocalize()
        self._second_row.relocalize()
        self._output_row.relocalize()
        self._batch_cb.setText(tr("modding_tools.batch_mode"))
        self._batch_cb.setToolTip(tr("tooltips.modding_tools_batch_mode"))
        self._continue_cb.setText(tr("modding_tools.continue_on_error"))
        self._continue_cb.setToolTip(tr("tooltips.modding_tools_continue_on_error"))
        self._batch_label.setText(tr("modding_tools.batch_inputs"))
        self._batch_add_btn.setText(tr("modding_tools.merge_add"))
        self._batch_remove_btn.setText(tr("modding_tools.merge_remove"))
        self._batch_output_row.relocalize()
        self._xdelta_fallback_checkbox.setText(
            tr("checkboxes.g3mpatch_xdelta_fallback")
        )
        self._xdelta_fallback_checkbox.setToolTip(
            tr("tooltips.g3mpatch_xdelta_fallback")
        )
        self._run_btn.setText(tr("modding_tools.run"))


class _DataConvertWorkerThread(ManagedQThread):
    """Batch-convert DATA files in a mod folder."""

    progress = pyqtSignal(str)
    result_ready = pyqtSignal(bool, str)

    def __init__(
        self, g3m, mod_folder, config_data, game_path, target_mode, parent=None
    ) -> None:
        super().__init__(parent)
        self._g3m = g3m
        self._mod_folder = mod_folder
        self._config_data = config_data
        self._game_path = game_path
        self._target_mode = target_mode

    def run(self):
        try:
            from models.game_modes import get_game
            from utils.mod.config_parser import resolve_mod_file_path
            from utils.mod.version_utils import (
                create_version_zip,
                get_unique_version_name,
            )
            from utils.patching.mod_content_utils import find_data_win
            from utils.path_utils import find_chapter_resource_dir

            files_data = self._config_data.get("files", {})
            game = self._config_data.get("game")
            game_def = get_game(game) if game else None
            items = []
            for file_key, ch_info in files_data.items():
                if not isinstance(ch_info, dict):
                    continue
                data_path = ch_info.get("data_file_path") or ch_info.get("data_file_url", "")
                if not data_path:
                    continue
                patch_path = resolve_mod_file_path(self._mod_folder, data_path)
                if not patch_path:
                    continue
                if not _should_convert_source_to_target(patch_path, self._target_mode):
                    continue
                if not os.path.isfile(patch_path):
                    continue
                tab = game_def.get_tab(file_key) if game_def else None
                chapter_id = tab.tab_id if tab else file_key
                resource_dir = find_chapter_resource_dir(self._game_path, chapter_id)
                if not resource_dir:
                    continue
                original = find_data_win(resource_dir, game_id=game)
                if not original:
                    self.result_ready.emit(
                        False,
                        tr(
                            "modding_tools.convert_original_not_found",
                            path=resource_dir,
                        ),
                    )
                    return
                items.append(
                    (ch_info, os.path.relpath(patch_path, self._mod_folder), original)
                )

            if not items:
                self.result_ready.emit(False, tr("modding_tools.convert_no_data_files"))
                return

            total = len(items)

            version = self._config_data.get("version", "1.0.0")
            version = (version.split("|", 1)[0].strip() if version else "") or "1.0.0"
            version_name = get_unique_version_name(
                self._mod_folder,
                f"{version} - {_target_version_label(self._target_mode)}",
            )
            self.progress.emit(
                tr("modding_tools.convert_saving_version", version=version_name)
            )

            with managed_temporary_directory(prefix="g3m_modconv_") as tmp:
                converted_mod_folder = os.path.join(tmp, "mod")
                shutil.copytree(
                    self._mod_folder,
                    converted_mod_folder,
                    ignore=shutil.ignore_patterns("mod_versions"),
                )
                converted = 0
                for i, (ch_info, patch_rel_path, original) in enumerate(items):
                    if self.isInterruptionRequested():
                        return
                    patch_path = os.path.join(converted_mod_folder, patch_rel_path)
                    self.progress.emit(
                        tr(
                            "modding_tools.convert_progress",
                            current=i + 1,
                            total=total,
                            file=os.path.basename(patch_path),
                        )
                    )
                    with managed_temporary_directory(prefix="g3m_modconv_file_") as work_dir:
                        temp_modified = os.path.join(work_dir, "modified.tmp")
                        rc, _, err = _apply_source_to_data(
                            self._g3m, original, patch_path, temp_modified
                        )
                        if self.isInterruptionRequested():
                            return
                        if _target_is_ready_data(self._target_mode):
                            target_name = _resolve_target_data_name(
                                original, self._target_mode
                            )
                            new_name = _rename_data_output_name(target_name)
                            new_path = os.path.join(os.path.dirname(patch_path), new_name)
                            is_patch_source = (
                                _is_g3mpatch_source(patch_path)
                                or _is_xdelta_source(patch_path)
                                or _is_csx_source(patch_path)
                            )
                            if is_patch_source:
                                if rc != 0:
                                    self.result_ready.emit(False, err)
                                    return
                                shutil.copy2(temp_modified, new_path)
                            elif _is_ready_data_source(patch_path):
                                shutil.copy2(patch_path, new_path)
                            else:
                                self.result_ready.emit(
                                    False,
                                    tr(
                                        "modding_tools.convert_unsupported_source",
                                        file=os.path.basename(patch_path),
                                    ),
                                )
                                return
                        else:
                            if rc != 0:
                                self.result_ready.emit(False, err)
                                return
                            new_name = f"{os.path.splitext(os.path.basename(patch_path))[0]}{'.xdelta' if self._target_mode == 'xdelta' else '.g3mpatch'}"
                            new_path = os.path.join(os.path.dirname(patch_path), new_name)
                            if self._target_mode == "xdelta":
                                rc, _, err = self._g3m.xpatch_create(
                                    original, temp_modified, new_path
                                )
                            else:
                                rc, _, err = _patch_create(
                                    self._g3m,
                                    original,
                                    temp_modified,
                                    new_path,
                                )
                            if rc != 0:
                                self.result_ready.emit(False, err)
                                return
                    if os.path.normpath(new_path) != os.path.normpath(patch_path):
                        with suppress(OSError):
                            os.remove(patch_path)
                    ch_info["data_file_path"] = os.path.relpath(
                        new_path, converted_mod_folder
                    ).replace("\\", "/")
                    converted += 1

                from utils.mod.config_parser import build_mod_config_data

                config_path = os.path.join(converted_mod_folder, "mod_config.json")
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(
                        build_mod_config_data(self._config_data),
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )
                create_version_zip(
                    converted_mod_folder,
                    self._mod_folder,
                    version_name,
                    ignore_versions_dir=True,
                )
            self.result_ready.emit(
                True,
                tr(
                    "modding_tools.convert_data_success",
                    count=converted,
                    version=version_name,
                ),
            )
        except Exception as e:
            self.result_ready.emit(
                False,
                format_filesystem_error(e, path=self._mod_folder),
            )


class _BatchDataConvertWorkerThread(ManagedQThread):
    """Convert selected mods one by one while keeping the UI responsive."""

    progress = pyqtSignal(str)
    warning_confirmation_needed = pyqtSignal(object, str, object)
    result_ready = pyqtSignal(bool, str)

    def __init__(self, g3m, jobs, target_mode, parent=None) -> None:
        super().__init__(parent)
        self._g3m = g3m
        self._jobs = list(jobs)
        self._target_mode = target_mode
        self._warning_event = threading.Event()
        self._warning_result = True

    def confirm_warning(self, accepted: bool) -> None:
        self._warning_result = accepted
        self._warning_event.set()

    def _request_warning_confirmation(
        self, message: str, details: str = "", warning_id: str = "legacy_patching_warning"
    ) -> bool:
        self._warning_result = True
        self._warning_event.clear()
        event = create_warning_event(warning_id, details=details, fallback_message=message)
        self.warning_confirmation_needed.emit(event, details, None)
        while not self._warning_event.wait(0.1):
            if self.isInterruptionRequested():
                return False
        return self._warning_result and not self.isInterruptionRequested()

    @staticmethod
    def _warning_id_for_error(message: str) -> str:
        lower = str(message or "").lower()
        if "xdelta" in lower:
            return "xdelta_apply_failed"
        if "merge" in lower:
            return "merge_failed"
        if "patch" in lower or "g3mpatch" in lower:
            return "g3mpatch_apply_failed"
        return "legacy_patching_warning"

    def run(self):
        total = len(self._jobs)
        converted = 0
        for index, job in enumerate(self._jobs, start=1):
            if self.isInterruptionRequested():
                self.result_ready.emit(
                    False,
                    tr(
                        "modding_tools.convert_batch_failed",
                        current=converted,
                        total=total,
                        error=tr("ui.cancel_button"),
                    ),
                )
                return
            mod_name = job.get("name") or os.path.basename(job["mod_folder"])
            self.progress.emit(
                tr(
                    "modding_tools.convert_batch_progress",
                    current=index,
                    total=total,
                    mod=mod_name,
                )
            )
            worker = _DataConvertWorkerThread(
                self._g3m,
                job["mod_folder"],
                job["config_data"],
                job["game_path"],
                self._target_mode,
            )
            result = []
            worker.progress.connect(
                lambda message, mod=mod_name: self.progress.emit(
                    tr("modding_tools.convert_batch_item_progress", mod=mod, message=message)
                )
            )
            worker.result_ready.connect(
                lambda success, message, captured=result: captured.append(
                    (success, message)
                )
            )
            worker.run()
            success, message = result[0] if result else (False, "")
            if not success:
                should_continue = self._request_warning_confirmation(
                    "",
                    details=message,
                    warning_id=self._warning_id_for_error(message),
                )
                if not should_continue:
                    self.result_ready.emit(
                        False,
                        tr(
                            "modding_tools.convert_batch_failed",
                            current=converted,
                            total=total,
                            error=message,
                        ),
                    )
                    return
                self.progress.emit(
                    tr("modding_tools.convert_batch_skipped", mod=mod_name)
                )
                continue
            converted += 1
        self.result_ready.emit(
            True,
            tr("modding_tools.convert_batch_success", count=converted, total=total),
        )


class _DataConvertTab(QWidget):
    """Tab: profile → auto-scan mods → select → batch convert DATA files."""

    def __init__(self, g3m, app_state, parent=None) -> None:
        super().__init__(parent)
        self._g3m, self._app_state = g3m, app_state
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        profile_row = QHBoxLayout()
        profile_row.addStretch()
        self._profile_label = QLabel(tr("modding_tools.convert_select_profile"))
        profile_row.addWidget(self._profile_label)
        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(200)
        self._profile_combo.setToolTip(tr("tooltips.profile_combo"))
        self._profile_combo.currentIndexChanged.connect(self._scan_mods)
        profile_row.addWidget(self._profile_combo)
        profile_row.addStretch()
        lay.addLayout(profile_row)

        fmt_row = QHBoxLayout()
        fmt_row.addStretch()
        self._fmt_label = QLabel(tr("modding_tools.convert_target_format"))
        fmt_row.addWidget(self._fmt_label)
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItems(list(_CONVERT_TARGET_OPTIONS))
        self._fmt_combo.setToolTip(tr("tooltips.modding_tools_target_format"))
        self._fmt_combo.currentIndexChanged.connect(self._scan_mods)
        fmt_row.addWidget(self._fmt_combo)
        fmt_row.addStretch()
        lay.addLayout(fmt_row)

        self._mod_label = QLabel(tr("modding_tools.convert_select_mod"))
        lay.addWidget(self._mod_label)
        self._mod_list = QListWidget()
        self._mod_list.setMinimumHeight(150)
        self._mod_list.setToolTip(tr("tooltips.modding_tools_mod_list"))
        self._mod_list.itemChanged.connect(self._update_run_state)
        lay.addWidget(self._mod_list, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._run_btn = QPushButton(tr("modding_tools.run"))
        self._run_btn.setObjectName("modding_tools_run_btn")
        self._run_btn.setToolTip(tr("tooltips.run_tool"))
        self._run_btn.clicked.connect(self._on_run)
        self._run_btn.setEnabled(False)
        btn_row.addWidget(self._run_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._status_label = QLabel("")
        self._status_label.setObjectName("modding_tools_status")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        lay.addWidget(self._status_label)

        self._populate_profiles()

    def _populate_profiles(self):
        from services.profile_service import ProfileService

        ps = self._app_state
        while ps and not isinstance(
            getattr(ps, "profile_service", None), ProfileService
        ):
            ps = getattr(ps, "parent", None)
        if ps and hasattr(ps, "profile_service"):
            profiles = ps.profile_service.list_profiles()
        else:
            from utils.path_utils import get_user_profiles_dir

            profiles_dir = get_user_profiles_dir()
            if os.path.isdir(profiles_dir):
                profiles = [
                    d
                    for d in os.listdir(profiles_dir)
                    if os.path.isdir(os.path.join(profiles_dir, d))
                ]
            else:
                profiles = []
        self._profile_combo.clear()
        for name in profiles:
            self._profile_combo.addItem(name)

    def _scan_mods(self, _idx=0):
        from config.config import MOD_CONFIG_FILENAME
        from utils.mod.config_parser import (
            normalize_mod_config_data,
            resolve_mod_file_path,
        )
        from utils.path_utils import get_profile_mods_root

        self._mod_list.blockSignals(True)
        self._mod_list.clear()
        self._mod_list.blockSignals(False)
        self._run_btn.setEnabled(False)
        _safe_set_status(self._status_label, "")
        profile_name = self._profile_combo.currentText()
        if not profile_name:
            return
        mods_root = get_profile_mods_root(profile_name)
        if not os.path.isdir(mods_root):
            _safe_set_status(self._status_label, tr("modding_tools.convert_no_mods"))
            return
        target_mode = _convert_target_mode(self._fmt_combo.currentIndex())
        found = 0
        for folder_name in sorted(os.listdir(mods_root)):
            folder_path = os.path.join(mods_root, folder_name)
            if not os.path.isdir(folder_path):
                continue
            config_path = os.path.join(folder_path, MOD_CONFIG_FILENAME)
            if not os.path.isfile(config_path):
                continue
            try:
                with open(config_path, encoding="utf-8") as f:
                    config_data = json.load(f)
                normalize_mod_config_data(config_data, mod_root_path=folder_path)
            except Exception:
                logger.debug("Skipping unreadable mod config: %s", config_path)
                continue
            files_data = config_data.get("files", {})
            if not isinstance(files_data, dict):
                continue
            has_convertible = False
            for ch in files_data.values():
                if not isinstance(ch, dict):
                    continue
                url = ch.get("data_file_path") or ch.get("data_file_url", "")
                if not url:
                    continue

                source_path = resolve_mod_file_path(folder_path, url)
                if _should_convert_source_to_target(source_path, target_mode):
                    has_convertible = True
                    break
            if not has_convertible:
                continue
            display = config_data.get("name", folder_name)
            item = QListWidgetItem(display)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, folder_path)
            item.setToolTip(folder_path)
            self._mod_list.blockSignals(True)
            self._mod_list.addItem(item)
            self._mod_list.blockSignals(False)
            found += 1

        if found == 0:
            _safe_set_status(self._status_label, tr("modding_tools.convert_no_mods"))
        else:
            self._update_run_state()

    def _checked_items(self) -> list[QListWidgetItem]:
        return [
            item
            for i in range(self._mod_list.count())
            if (item := self._mod_list.item(i)) is not None
            and item.checkState() == Qt.CheckState.Checked
        ]

    def _update_run_state(self, *_args) -> None:
        self._run_btn.setEnabled(bool(self._checked_items()))

    def _set_busy(self, busy: bool):
        self._profile_combo.setEnabled(not busy)
        self._fmt_combo.setEnabled(not busy)
        self._mod_list.setEnabled(not busy)
        if busy:
            self._run_btn.setEnabled(False)
        else:
            self._scan_mods()

    def _on_run(self):
        if self._worker and self._worker.isRunning():
            return
        checked_items = self._checked_items()
        if not checked_items:
            return
        if not self._g3m or not self._g3m.is_available():
            _safe_set_status(self._status_label, tr("errors.g3mtool_not_available"))
            return
        from models.game_modes import get_game
        from utils.mod.config_parser import normalize_mod_config_data

        jobs = []
        game_path_cache = {}
        for item in checked_items:
            mod_folder = item.data(Qt.ItemDataRole.UserRole)
            config_path = os.path.join(mod_folder, "mod_config.json")
            try:
                with open(config_path, encoding="utf-8") as f:
                    config_data = json.load(f)
                normalize_mod_config_data(config_data, mod_root_path=mod_folder)
            except Exception as e:
                _safe_set_status(
                    self._status_label,
                    tr("modding_tools.convert_data_failed", error=str(e)),
                )
                return

            game = config_data.get("game", "deltarune")
            if game in game_path_cache:
                game_def, game_path = game_path_cache[game]
            else:
                game_def = get_game(game)
                if not game_def:
                    _safe_set_status(
                        self._status_label,
                        tr("modding_tools.convert_game_path_missing", game=game),
                    )
                    return

                game_path = game_def.get_game_path(self._app_state.local_config)
                if not game_path or not os.path.isdir(game_path):
                    _safe_set_status(
                        self._status_label,
                        tr(
                            "modding_tools.convert_game_path_missing",
                            game=game_def.display_name,
                        )
                    )
                    return
                game_path_cache[game] = (game_def, game_path)
            jobs.append(
                {
                    "mod_folder": mod_folder,
                    "config_data": config_data,
                    "game_path": game_path,
                    "name": item.text(),
                }
            )

        target_mode = _convert_target_mode(self._fmt_combo.currentIndex())
        self._set_busy(True)
        _safe_set_status(self._status_label, tr("modding_tools.running"))
        self._worker = _BatchDataConvertWorkerThread(self._g3m, jobs, target_mode)
        self._worker.progress.connect(lambda message: _safe_set_status(self._status_label, message))
        self._worker.warning_confirmation_needed.connect(
            self._on_warning_confirmation_needed
        )
        self._worker.result_ready.connect(self._on_finished)
        self._worker.start()

    def _on_warning_confirmation_needed(self, message, details: str, report_path):
        feedback = FeedbackManager(self)
        feedback.app_state = self._app_state
        should_continue = feedback.ask_patching_warning(message, details, report_path)
        if self._worker:
            self._worker.confirm_warning(should_continue)

    def _on_finished(self, success, message):
        retire_qthread(self._worker)
        self._worker = None
        self._set_busy(False)
        if success:
            _safe_set_status(self._status_label, message)
        else:
            logger.info("Modding tools DATA conversion failed: %s", message)
            _safe_set_status(self._status_label, tr("modding_tools.failed_details_logged"))
            _safe_warning(
                self,
                tr("modding_tools.title"),
                tr("modding_tools.failed_details_logged"),
            )

    def has_user_interaction(self) -> bool:
        return bool(self._worker)

    def relocalize(self):
        self._profile_label.setText(tr("modding_tools.convert_select_profile"))
        self._fmt_label.setText(tr("modding_tools.convert_target_format"))
        self._mod_label.setText(tr("modding_tools.convert_select_mod"))
        self._run_btn.setText(tr("modding_tools.run"))


class _MergeTab(QWidget):
    def __init__(self, g3m, app_state, parent=None) -> None:
        super().__init__(parent)
        self._g3m, self._app_state = g3m, app_state
        self._worker = None
        self._output_user_modified = False
        self._setting_output_text = False
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        cb_row = QHBoxLayout()
        self._code_cb = QCheckBox(tr("checkboxes.merge_code"))
        self._props_cb = QCheckBox(tr("checkboxes.merge_properties"))
        self._batch_cb = QCheckBox(tr("modding_tools.batch_mode"))
        self._continue_cb = QCheckBox(tr("modding_tools.continue_on_error"))
        self._report_cb = QCheckBox(tr("modding_tools.merge_report"))
        cb_row.addWidget(self._code_cb)
        cb_row.addWidget(self._props_cb)
        cb_row.addWidget(self._batch_cb)
        cb_row.addWidget(self._continue_cb)
        cb_row.addWidget(self._report_cb)
        cb_row.addStretch()
        lay.addLayout(cb_row)
        self._batch_cb.toggled.connect(self._update_batch_visibility)

        self._original_row = _PathRow("modding_tools.original_file", _DATA_FILTER)
        lay.addWidget(self._original_row)

        list_label = QLabel(tr("modding_tools.merge_list"))
        lay.addWidget(list_label)
        self._list_label = list_label

        self._file_list = QListWidget()
        self._file_list.setMinimumHeight(100)
        lay.addWidget(self._file_list, 1)

        list_btns = QHBoxLayout()
        list_btns.setSpacing(6)
        self._add_btn = QPushButton(tr("modding_tools.merge_add"))
        self._add_btn.setObjectName("modding_tools_merge_add")
        self._add_btn.clicked.connect(self._on_add)
        self._remove_btn = QPushButton(tr("modding_tools.merge_remove"))
        self._remove_btn.setObjectName("modding_tools_merge_remove")
        self._remove_btn.clicked.connect(self._on_remove)
        self._up_btn = QPushButton(tr("ui.move_up"))
        self._up_btn.clicked.connect(lambda: self._move(-1))
        self._down_btn = QPushButton(tr("ui.move_down"))
        self._down_btn.clicked.connect(lambda: self._move(1))
        for b in (self._add_btn, self._remove_btn, self._up_btn, self._down_btn):
            list_btns.addWidget(b)
        self._add_set_btn = QPushButton(tr("modding_tools.merge_add_set"))
        self._add_set_btn.clicked.connect(self._on_add_set)
        list_btns.addWidget(self._add_set_btn)
        list_btns.addStretch()
        lay.addLayout(list_btns)

        self._set_label = QLabel(tr("modding_tools.merge_sets"))
        lay.addWidget(self._set_label)
        self._set_list = QListWidget()
        self._set_list.setMinimumHeight(80)
        lay.addWidget(self._set_list, 1)
        set_btns = QHBoxLayout()
        self._remove_set_btn = QPushButton(tr("modding_tools.merge_remove_set"))
        self._remove_set_btn.clicked.connect(self._on_remove_set)
        set_btns.addWidget(self._remove_set_btn)
        set_btns.addStretch()
        lay.addLayout(set_btns)

        self._output_row = _PathRow(
            "modding_tools.output_file", _DATA_FILTER, save_mode=True
        )
        self._output_row.set_save_path_getter(self._suggest_output_path)
        self._output_row.text_changed.connect(self._on_output_text_changed)
        lay.addWidget(self._output_row)
        self._patch_output_row = _PathRow(
            "modding_tools.merge_patch_output_file", _G3M_PATCH_FILTER, save_mode=True
        )
        lay.addWidget(self._patch_output_row)
        self._batch_output_row = _PathRow(
            "modding_tools.output_folder", _ALL_FILTER, dir_mode=True
        )
        lay.addWidget(self._batch_output_row)
        self._batch_patch_output_row = _PathRow(
            "modding_tools.merge_patch_output_folder", _ALL_FILTER, dir_mode=True
        )
        lay.addWidget(self._batch_patch_output_row)
        self._original_row.text_changed.connect(self._maybe_suggest_output_path)
        self._update_batch_visibility()

        run_row = QHBoxLayout()
        run_row.addStretch()
        self._run_btn = QPushButton(tr("modding_tools.merge_run"))
        self._run_btn.setObjectName("modding_tools_run_btn")
        self._run_btn.clicked.connect(self._on_run)
        run_row.addWidget(self._run_btn)
        run_row.addStretch()
        lay.addLayout(run_row)

        self._status_label = QLabel("")
        self._status_label.setObjectName("modding_tools_status")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        lay.addWidget(self._status_label)

    def _on_add(self):
        paths, _ = get_open_file_names(
            self, tr("ui.select_file"), "", _DATA_PATCH_FILTER
        )
        for p in paths:
            item = QListWidgetItem(os.path.basename(p))
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self._file_list.insertItem(0, item)
        self._maybe_suggest_output_path()

    def _on_remove(self):
        for item in self._file_list.selectedItems():
            self._file_list.takeItem(self._file_list.row(item))
        self._maybe_suggest_output_path()

    def _current_patches(self) -> list[str]:
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for i in range(self._file_list.count())
            if (item := self._file_list.item(i)) is not None
        ]

    def _on_add_set(self):
        patches = self._current_patches()
        if len(patches) < 2:
            _safe_warning(self, tr("modding_tools.title"), tr("modding_tools.merge_set_need_files"))
            return
        label = " + ".join(os.path.basename(path) for path in patches)
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, patches)
        item.setToolTip("\n".join(patches))
        self._set_list.addItem(item)

    def _on_remove_set(self):
        for item in self._set_list.selectedItems():
            self._set_list.takeItem(self._set_list.row(item))

    def _update_batch_visibility(self):
        batch = self._batch_cb.isChecked()
        for widget in (
            self._set_label,
            self._set_list,
            self._remove_set_btn,
            self._batch_output_row,
            self._batch_patch_output_row,
            self._continue_cb,
        ):
            widget.setVisible(batch)
        self._add_set_btn.setVisible(batch)
        self._report_cb.setVisible(True)
        self._output_row.setVisible(not batch)
        self._patch_output_row.setVisible(not batch)

    def _move(self, direction):
        row = self._file_list.currentRow()
        if row < 0:
            return
        new_row = row + direction
        if 0 <= new_row < self._file_list.count():
            item = self._file_list.takeItem(row)
            self._file_list.insertItem(new_row, item)
            self._file_list.setCurrentRow(new_row)

    def _on_output_text_changed(self, _text: str) -> None:
        if not self._setting_output_text:
            self._output_user_modified = True

    def _set_output_path(self, path: str) -> None:
        self._setting_output_text = True
        try:
            self._output_row.set_path(path)
        finally:
            self._setting_output_text = False

    def _suggest_output_path(self) -> str:
        orig = self._original_row.path()
        if not orig:
            return ""
        base, ext = os.path.splitext(orig)
        return f"{base}_merged{ext or '.win'}"

    def _maybe_suggest_output_path(self, *_args) -> None:
        if self._output_user_modified and self._output_row.path():
            return
        suggested = self._suggest_output_path()
        if suggested:
            self._set_output_path(suggested)
            self._output_user_modified = False

    def _on_run(self):
        if not self._g3m or not self._g3m.is_available():
            _safe_warning(self, tr("modding_tools.title"), tr("errors.g3mtool_not_available"))
            return
        orig = self._original_row.path()
        if self._batch_cb.isChecked():
            self._on_batch_run(orig)
            return
        out = self._output_row.path()
        patch_out = self._patch_output_row.path()
        patches = self._current_patches()
        if not orig or len(patches) < 2 or not out:
            _safe_warning(self, tr("modding_tools.title"), tr("modding_tools.merge_need_files"))
            return
        report_path = None
        if self._report_cb.isChecked():
            base, _ext = os.path.splitext(patch_out or out)
            report_path = f"{base}_merge_report.md"
        self._run_btn.setEnabled(False)
        _safe_set_status(self._status_label, tr("modding_tools.running"))
        self._worker = _WorkerThread(
            self._g3m.merge_patches,
            (
                orig,
                patches,
                out,
                patch_out or None,
                report_path,
                None,
                self._code_cb.isChecked(),
                self._props_cb.isChecked(),
            ),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.result_ready.connect(self._on_finished)
        self._worker.start()

    def _on_batch_run(self, orig: str) -> None:
        out_dir = self._batch_output_row.path()
        patch_out_dir = self._batch_patch_output_row.path()
        patch_sets = [
            item.data(Qt.ItemDataRole.UserRole)
            for i in range(self._set_list.count())
            if (item := self._set_list.item(i)) is not None
        ]
        if not orig or not out_dir or not patch_sets:
            _safe_warning(self, tr("modding_tools.title"), tr("modding_tools.merge_batch_need_files"))
            return
        self._run_btn.setEnabled(False)
        _safe_set_status(self._status_label, tr("modding_tools.running"))
        self._worker = _WorkerThread(
            self._g3m.batch_merge_patches,
            (
                orig,
                patch_sets,
                out_dir,
                patch_out_dir or None,
                self._continue_cb.isChecked(),
                self._code_cb.isChecked(),
                self._props_cb.isChecked(),
                self._report_cb.isChecked(),
            ),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.result_ready.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, percent: int, label: str) -> None:
        _safe_set_status(self._status_label, _format_progress_status(percent, label))

    def _on_finished(self, rc, out, err):
        self._run_btn.setEnabled(True)
        retire_qthread(self._worker)
        self._worker = None
        if rc == 0:
            _safe_set_status(self._status_label, tr("modding_tools.success"))
        else:
            _show_g3mtool_warning_failure(
                self, self._app_state, self._status_label, "merge", rc, out, err
            )

    def has_user_interaction(self) -> bool:
        return bool(
            self._original_row.path()
            or self._file_list.count()
            or self._output_row.path()
            or self._patch_output_row.path()
            or self._set_list.count()
            or self._batch_output_row.path()
            or self._batch_patch_output_row.path()
            or self._worker
        )

    def relocalize(self):
        self._code_cb.setText(tr("checkboxes.merge_code"))
        self._props_cb.setText(tr("checkboxes.merge_properties"))
        self._batch_cb.setText(tr("modding_tools.batch_mode"))
        self._batch_cb.setToolTip(tr("tooltips.modding_tools_batch_mode"))
        self._continue_cb.setText(tr("modding_tools.continue_on_error"))
        self._continue_cb.setToolTip(tr("tooltips.modding_tools_continue_on_error"))
        self._report_cb.setText(tr("modding_tools.merge_report"))
        self._original_row.relocalize()
        self._list_label.setText(tr("modding_tools.merge_list"))
        self._add_btn.setText(tr("modding_tools.merge_add"))
        self._remove_btn.setText(tr("modding_tools.merge_remove"))
        self._up_btn.setText(tr("ui.move_up"))
        self._down_btn.setText(tr("ui.move_down"))
        self._add_set_btn.setText(tr("modding_tools.merge_add_set"))
        self._set_label.setText(tr("modding_tools.merge_sets"))
        self._remove_set_btn.setText(tr("modding_tools.merge_remove_set"))
        self._output_row.relocalize()
        self._patch_output_row.relocalize()
        self._batch_output_row.relocalize()
        self._batch_patch_output_row.relocalize()
        self._run_btn.setText(tr("modding_tools.merge_run"))


class _InfoTab(QWidget):
    def __init__(self, g3m, app_state, parent=None) -> None:
        super().__init__(parent)
        self._g3m, self._app_state = g3m, app_state
        self._worker = None
        self._output_user_modified = False
        self._setting_output_text = False
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        self._file_row = _PathRow("modding_tools.info_file", _DATA_PATCH_FILTER)
        lay.addWidget(self._file_row)

        cb_row = QHBoxLayout()
        self._verbose_cb = QCheckBox(tr("modding_tools.verbose"))
        cb_row.addWidget(self._verbose_cb)
        cb_row.addStretch()
        self._run_btn = QPushButton(tr("modding_tools.info_run"))
        self._run_btn.setObjectName("modding_tools_run_btn")
        self._run_btn.clicked.connect(self._on_run)
        cb_row.addWidget(self._run_btn)
        lay.addLayout(cb_row)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setObjectName("modding_tools_info_output")
        self._output.textChanged.connect(self._on_output_text_changed)
        lay.addWidget(self._output, 1)

    def _on_run(self):
        if not self._g3m or not self._g3m.is_available():
            _safe_warning(self, tr("modding_tools.title"), tr("errors.g3mtool_not_available"))
            return
        target = self._file_row.path()
        if not target:
            _safe_warning(self, tr("modding_tools.title"), tr("modding_tools.select_all_paths"))
            return
        self._run_btn.setEnabled(False)
        self._set_output_text(tr("modding_tools.running"))
        self._worker = _WorkerThread(
            self._g3m.info, (target, self._verbose_cb.isChecked())
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.result_ready.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, percent: int, label: str) -> None:
        self._set_output_text(_format_progress_status(percent, label))

    def _on_finished(self, rc, out, err):
        self._run_btn.setEnabled(True)
        retire_qthread(self._worker)
        self._worker = None
        if rc == 0:
            self._set_output_text(out)
        else:
            details = (err or out or "").strip()
            if details:
                logger.info(
                    "Modding tools info failed with code %s: %s",
                    rc,
                    details,
                )
            self._set_output_text(tr("modding_tools.failed_details_logged"))
            _safe_warning(
                self,
                tr("modding_tools.title"),
                tr("modding_tools.failed_details_logged"),
            )

    def _set_output_text(self, text: str):
        self._setting_output_text = True
        self._output_user_modified = False
        try:
            self._output.setPlainText(text)
        finally:
            self._setting_output_text = False

    def _on_output_text_changed(self):
        if not self._setting_output_text:
            self._output_user_modified = True

    def has_user_interaction(self) -> bool:
        return bool(self._file_row.path() or self._output_user_modified or self._worker)

    def relocalize(self):
        self._file_row.relocalize()
        self._verbose_cb.setText(tr("modding_tools.verbose"))
        self._run_btn.setText(tr("modding_tools.info_run"))


class _DiffTab(QWidget):
    def __init__(self, g3m, app_state, parent_dialog=None) -> None:
        super().__init__(parent_dialog)
        self._g3m, self._app_state = g3m, app_state
        self._parent_dialog = parent_dialog
        self._worker = None
        self._out_dir = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        self._file1_row = _PathRow("modding_tools.diff_file1", _DATA_PATCH_FILTER)
        lay.addWidget(self._file1_row)
        self._file2_row = _PathRow("modding_tools.diff_file2", _DATA_PATCH_FILTER)
        lay.addWidget(self._file2_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._run_btn = QPushButton(tr("modding_tools.diff_run"))
        self._run_btn.setObjectName("modding_tools_run_btn")
        self._run_btn.clicked.connect(self._on_run)
        btn_row.addWidget(self._run_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._status_label = QLabel("")
        self._status_label.setObjectName("modding_tools_status")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        lay.addWidget(self._status_label)
        lay.addStretch()

    def _on_run(self):
        if not self._g3m or not self._g3m.is_available():
            _safe_warning(self, tr("modding_tools.title"), tr("errors.g3mtool_not_available"))
            return
        f1, f2 = self._file1_row.path(), self._file2_row.path()
        if not f1 or not f2:
            _safe_warning(self, tr("modding_tools.title"), tr("modding_tools.select_all_paths"))
            return
        self._run_btn.setEnabled(False)
        _safe_set_status(self._status_label, tr("modding_tools.running"))
        out_dir = tempfile.mkdtemp(prefix="modding_tools_diff_")
        self._out_dir = out_dir
        self._worker = _WorkerThread(self._g3m.diff, (f1, f2, out_dir))
        self._worker.progress.connect(self._on_progress)
        self._worker.result_ready.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, percent: int, label: str) -> None:
        _safe_set_status(self._status_label, _format_progress_status(percent, label))

    def _on_finished(self, rc, out, err):
        self._run_btn.setEnabled(True)
        retire_qthread(self._worker)
        self._worker = None
        if rc != 0:
            _show_g3mtool_failure(self, self._status_label, "diff", rc, out, err)
            self._cleanup_out_dir()
            return
        _safe_set_status(self._status_label, tr("modding_tools.success"))
        if self._out_dir is None:
            return
        md_file = self._find_md(self._out_dir)
        if md_file:
            from ui.dialogs.g3mtool_diff_viewer import DiffViewerDialog

            dlg = DiffViewerDialog(
                md_file, self._app_state, self._parent_dialog or self
            )
            dlg.destroyed.connect(self._cleanup_out_dir)
            dlg.show()
        else:
            _safe_set_status(self._status_label, tr("modding_tools.diff_no_report"))
            self._cleanup_out_dir()

    def _cleanup_out_dir(self):
        if self._out_dir:
            cleanup_temporary_directory(self._out_dir)
            self._out_dir = None

    @staticmethod
    def _find_md(directory: str) -> str | None:
        for f in os.listdir(directory):
            if f.endswith(".md"):
                return os.path.join(directory, f)
        return None

    def has_user_interaction(self) -> bool:
        return bool(self._file1_row.path() or self._file2_row.path() or self._worker)

    def relocalize(self):
        self._file1_row.relocalize()
        self._file2_row.relocalize()
        self._run_btn.setText(tr("modding_tools.diff_run"))


class ModdingToolsDialog(QDialog):
    """Non-modal Modding Tools dialog."""

    def __init__(self, g3m_manager, app_state, parent=None) -> None:
        super().__init__(parent)
        self._g3m = g3m_manager
        self._app_state = app_state
        self.setWindowTitle(tr("modding_tools.title"))
        self.setMinimumSize(900, 600)
        self.resize(1300, 820)
        self.setModal(False)
        self._build_ui()
        self._apply_theme()

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(4)

        header = QHBoxLayout()
        self._title_label = QLabel(tr("modding_tools.title"))
        self._title_label.setObjectName("modding_tools_title")
        font = self._title_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self._title_label.setFont(font)
        header.addWidget(self._title_label)
        header.addStretch()
        self._close_btn = QPushButton(tr("common.close"))
        self._close_btn.setObjectName("modding_tools_close_btn")
        self._close_btn.clicked.connect(self.close)
        header.addWidget(self._close_btn)
        main.addLayout(header)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._data_convert_tab = _DataConvertTab(self._g3m, self._app_state)
        self._patch_tab = _PatchTab(self._g3m, self._app_state)
        self._merge_tab = _MergeTab(self._g3m, self._app_state)
        self._info_tab = _InfoTab(self._g3m, self._app_state)
        self._diff_tab = _DiffTab(self._g3m, self._app_state, self)
        self._tabs.addTab(
            self._data_convert_tab, tr("modding_tools.convert_data_title")
        )
        self._tabs.addTab(self._patch_tab, tr("modding_tools.tab_patch"))
        self._tabs.addTab(self._merge_tab, tr("modding_tools.tab_merge"))
        self._tabs.addTab(self._info_tab, tr("modding_tools.tab_info"))
        self._tabs.addTab(self._diff_tab, tr("modding_tools.tab_diff"))
        main.addWidget(self._tabs)

    def _apply_theme(self):
        base = build_dialog_theme_stylesheet(self._app_state)
        theme = get_dialog_theme_values(self._app_state)
        font_family = _get_app_font(self._app_state)
        checkmark_path = _write_checkbox_checkmark(theme["border"])
        checkmark_image = (
            f'image: url("{_css_url(checkmark_path)}");' if checkmark_path else ""
        )
        extra = f"""
            QLabel#modding_tools_title {{
                font-size: 16px;
            }}
            QLabel#modding_tools_status {{
                font-size: 12px;
                color: {theme["secondary_text"]};
            }}
            QTextEdit#modding_tools_info_output {{
                background-color: {theme["background"]};
                border: 2px solid {theme["border"]};
                border-radius: {theme["field_radius"]}px;
                color: {theme["main_text"]};
                font-family: {font_family};
                font-size: {_MONOSPACE_FONT_SIZE_PX}px;
                padding: 6px;
            }}
            QTabWidget::tab-bar {{
                alignment: center;
                top: 4px;
            }}
            QTabWidget::pane {{
                border: 2px solid {theme["border"]};
                border-radius: {theme["button_radius"]}px;
                background-color: {theme["background"]};
                padding-top: 10px;
                top: -2px;
            }}
            QTabBar::tab {{
                background-color: {theme["elements"]};
                color: {theme["main_text"]};
                border: 2px solid {theme["border"]};
                border-bottom: none;
                padding: 6px 14px;
                margin: 0 3px 6px 3px;
                border-top-left-radius: {theme["button_radius"]}px;
                border-top-right-radius: {theme["button_radius"]}px;
            }}
            QTabBar::tab:selected {{
                background-color: {theme["hover"]};
                border-bottom: 2px solid {theme["background"]};
                margin-bottom: 2px;
            }}
            QTabBar::tab:hover {{
                background-color: {theme["hover"]};
            }}
            QComboBox {{
                background-color: {theme["elements"]};
                border: 2px solid {theme["border"]};
                border-radius: {theme["field_radius"]}px;
                color: {theme["main_text"]};
                padding: 6px 10px;
                min-height: 36px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {theme["elements"]};
                color: {theme["main_text"]};
                selection-background-color: {theme["hover"]};
                selection-color: {theme["main_text"]};
                border: 2px solid {theme["border"]};
            }}
            QListWidget {{
                background-color: {theme["elements"]};
                border: 2px solid {theme["border"]};
                border-radius: {theme["field_radius"]}px;
                color: {theme["main_text"]};
            }}
            QListWidget::item {{
                padding: 6px 8px;
            }}
            QListWidget::item:selected {{
                background-color: {theme["hover"]};
                color: {theme["main_text"]};
                border: 2px solid {theme["select"]};
                border-radius: {theme["field_radius"]}px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 2px solid {theme["border"]};
                border-radius: 4px;
                background-color: {theme["elements"]};
            }}
            QCheckBox::indicator:hover {{
                border-color: {theme["select"]};
                background-color: {theme["hover"]};
            }}
            QCheckBox::indicator:checked {{
                border-color: {theme["border"]};
                background-color: {theme["elements"]};
                {checkmark_image}
            }}
            QCheckBox::indicator:disabled {{
                border-color: {theme["secondary_text"]};
                background-color: {theme["background"]};
            }}
            QListWidget::indicator {{
                width: 16px;
                height: 16px;
                border: 2px solid {theme["border"]};
                border-radius: 4px;
                background-color: {theme["elements"]};
            }}
            QListWidget::indicator:hover {{
                border-color: {theme["select"]};
                background-color: {theme["hover"]};
            }}
            QListWidget::indicator:checked {{
                border-color: {theme["border"]};
                background-color: {theme["elements"]};
                {checkmark_image}
            }}
        """
        self.setStyleSheet(base + extra)

    def relocalize_ui(self):
        self.setWindowTitle(tr("modding_tools.title"))
        self._title_label.setText(tr("modding_tools.title"))
        self._close_btn.setText(tr("common.close"))
        self._tabs.setTabText(0, tr("modding_tools.convert_data_title"))
        self._tabs.setTabText(1, tr("modding_tools.tab_patch"))
        self._tabs.setTabText(2, tr("modding_tools.tab_merge"))
        self._tabs.setTabText(3, tr("modding_tools.tab_info"))
        self._tabs.setTabText(4, tr("modding_tools.tab_diff"))
        self._data_convert_tab.relocalize()
        self._patch_tab.relocalize()
        self._merge_tab.relocalize()
        self._info_tab.relocalize()
        self._diff_tab.relocalize()

    def _stop_all_workers(self) -> bool:
        if self._g3m and hasattr(self._g3m, "cancel_active_processes"):
            self._g3m.cancel_active_processes()
        active_workers = []
        for tab in (
            self._data_convert_tab,
            self._patch_tab,
            self._merge_tab,
            self._info_tab,
            self._diff_tab,
        ):
            worker = getattr(tab, "_worker", None)
            if worker:
                with suppress(TypeError, RuntimeError):
                    worker.finished.connect(self._resume_close_after_worker)
            if worker and worker.isRunning():
                worker.requestInterruption()
                worker.quit()
                if worker.isRunning():
                    active_workers.append(worker)
                    logger.warning(
                        "Modding tools worker %s is still stopping cooperatively",
                        type(worker).__name__,
                    )
        return not active_workers

    def _resume_close_after_worker(self) -> None:
        if getattr(self, "_closing_when_workers_finish", False):
            self.close()

    def _has_any_interaction(self) -> bool:
        return any(
            tab.has_user_interaction()
            for tab in (
                self._data_convert_tab,
                self._patch_tab,
                self._merge_tab,
                self._info_tab,
                self._diff_tab,
            )
        )

    def closeEvent(self, a0):
        event = a0
        if event is None:
            return
        if not getattr(self, "_closing_when_workers_finish", False) and self._has_any_interaction():
            reply = _safe_question(
                self,
                tr("modding_tools.title"),
                tr("modding_tools.confirm_close"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if not self._stop_all_workers():
            event.ignore()
            if not getattr(self, "_closing_when_workers_finish", False):
                self._closing_when_workers_finish = True
                for tab in (
                    self._data_convert_tab,
                    self._patch_tab,
                    self._merge_tab,
                    self._info_tab,
                    self._diff_tab,
                ):
                    worker = getattr(tab, "_worker", None)
                    if worker and worker.isRunning():
                        worker.finished.connect(self.close)
            return
        event.accept()
        self.deleteLater()

    def refresh_theme(self):
        self._apply_theme()
