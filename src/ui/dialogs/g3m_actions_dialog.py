"""Non-modal G3M Actions dialog with Patch, Merge, Info, Diff tabs."""

import logging
import os
import shutil
import tempfile

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
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

from services.localization_service import tr
from ui.common.dialog_theme import (
    build_dialog_theme_stylesheet,
    get_dialog_theme_values,
)

logger = logging.getLogger(__name__)

_DATA_FILTER = "Data files (*.win *.ios *.unx *.droid);;All Files (*)"
_PATCH_FILTER = "Patch files (*.zip *.xdelta);;All Files (*)"
_DATA_PATCH_FILTER = (
    "Data / Patch files (*.win *.ios *.unx *.droid *.zip *.xdelta);;All Files (*)"
)
_ALL_FILTER = "All Files (*)"


def _get_app_font(app_state) -> str:
    """Return the current DELTAHUB font family or fallback."""
    parent = app_state
    while parent and not hasattr(parent, "custom_font_family"):
        parent = getattr(parent, "parent", None)
    ff = getattr(parent, "custom_font_family", None) if parent else None
    return f"'{ff}'" if ff else "'Segoe UI', sans-serif"


class _WorkerThread(QThread):
    """Run a G3M command off the UI thread."""

    finished = pyqtSignal(int, str, str)

    def __init__(self, func, args, parent=None) -> None:
        super().__init__(parent)
        self._func, self._args = func, args

    def run(self):
        try:
            rc, out, err = self._func(*self._args)
            self.finished.emit(rc, out, err)
        except Exception as e:
            self.finished.emit(-1, "", str(e))


class _PathRow(QWidget):
    """Reusable row: label + line-edit + browse button."""

    def __init__(
        self, label_key: str, file_filter: str, parent=None, save_mode: bool = False
    ) -> None:
        super().__init__(parent)
        self._filter = file_filter
        self._save_mode = save_mode
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._label = QLabel(tr(label_key))
        self._label.setMinimumWidth(80)
        self._label_key = label_key
        lay.addWidget(self._label)
        self._edit = QLineEdit()
        self._edit.setPlaceholderText(tr("ui.file_path_placeholder"))
        lay.addWidget(self._edit, 1)
        self._btn = QPushButton(tr("ui.browse_button"))
        self._btn.setObjectName("g3m_actions_browse_btn")
        self._btn.clicked.connect(self._browse)
        lay.addWidget(self._btn)

    def _browse(self):
        if self._save_mode:
            path, _ = QFileDialog.getSaveFileName(
                self, tr("ui.save_file"), "", self._filter
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, tr("ui.select_file"), "", self._filter
            )
        if path:
            self._edit.setText(path)

    def path(self) -> str:
        return self._edit.text().strip()

    def set_path(self, p: str):
        self._edit.setText(p)

    def relocalize(self):
        self._label.setText(tr(self._label_key))
        self._edit.setPlaceholderText(tr("ui.file_path_placeholder"))
        self._btn.setText(tr("ui.browse_button"))


class _PatchTab(QWidget):
    def __init__(self, g3m, app_state, parent=None) -> None:
        super().__init__(parent)
        self._g3m, self._app_state = g3m, app_state
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        self._mode_label = QLabel(tr("g3m_actions.patch_mode"))
        mode_row.addWidget(self._mode_label)
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["g3mpatch", "xdelta"])
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self._mode_combo)
        mode_row.addSpacing(20)
        self._action_label = QLabel(tr("g3m_actions.patch_action"))
        mode_row.addWidget(self._action_label)
        self._action_combo = QComboBox()
        self._action_combo.addItems(
            [tr("g3m_actions.action_create"), tr("g3m_actions.action_apply")]
        )
        self._action_combo.currentIndexChanged.connect(self._on_action_changed)
        mode_row.addWidget(self._action_combo)
        mode_row.addStretch()
        lay.addLayout(mode_row)

        self._original_row = _PathRow("g3m_actions.original_file", _DATA_FILTER)
        lay.addWidget(self._original_row)
        self._second_row = _PathRow("g3m_actions.modified_file", _DATA_FILTER)
        lay.addWidget(self._second_row)
        self._output_row = _PathRow(
            "g3m_actions.output_file", _ALL_FILTER, save_mode=True
        )
        lay.addWidget(self._output_row)

        lay.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._run_btn = QPushButton(tr("g3m_actions.run"))
        self._run_btn.setObjectName("g3m_actions_run_btn")
        self._run_btn.clicked.connect(self._on_run)
        btn_row.addWidget(self._run_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._status_label = QLabel("")
        self._status_label.setObjectName("g3m_actions_status")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        lay.addWidget(self._status_label)

    def _on_action_changed(self, _idx):
        is_create = self._action_combo.currentIndex() == 0
        key = "g3m_actions.modified_file" if is_create else "g3m_actions.patch_file"
        self._second_row._label.setText(tr(key))
        self._second_row._label_key = key
        self._update_filters()

    def _on_mode_changed(self, _idx):
        self._update_filters()

    def _update_filters(self):
        is_xdelta = self._mode_combo.currentIndex() == 1
        is_create = self._action_combo.currentIndex() == 0
        if is_xdelta:
            self._original_row._filter = _ALL_FILTER
            self._second_row._filter = _ALL_FILTER
        elif is_create:
            self._original_row._filter = _DATA_FILTER
            self._second_row._filter = _DATA_FILTER
        else:
            self._original_row._filter = _DATA_FILTER
            self._second_row._filter = _PATCH_FILTER

    def _on_run(self):
        if not self._g3m or not self._g3m.is_available():
            QMessageBox.warning(
                self, tr("g3m_actions.title"), tr("errors.g3mtool_not_available")
            )
            return
        orig, second, out = (
            self._original_row.path(),
            self._second_row.path(),
            self._output_row.path(),
        )
        if not orig or not second or not out:
            QMessageBox.warning(
                self, tr("g3m_actions.title"), tr("g3m_actions.select_all_paths")
            )
            return
        mode = self._mode_combo.currentText()
        is_create = self._action_combo.currentIndex() == 0
        if mode == "xdelta":
            func = self._g3m.xpatch_create if is_create else self._g3m.xpatch_apply
        else:
            func = self._g3m.patch_create if is_create else self._g3m.apply_patch
        self._run_btn.setEnabled(False)
        self._status_label.setText(tr("g3m_actions.running"))
        self._worker = _WorkerThread(func, (orig, second, out))
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_finished(self, rc, out, err):
        self._run_btn.setEnabled(True)
        self._worker = None
        if rc == 0:
            self._status_label.setText(tr("g3m_actions.success"))
        else:
            self._status_label.setText(tr("g3m_actions.failed", error=err[:300]))

    def has_user_interaction(self) -> bool:
        return bool(
            self._original_row.path()
            or self._second_row.path()
            or self._output_row.path()
            or self._worker
        )

    def relocalize(self):
        self._mode_label.setText(tr("g3m_actions.patch_mode"))
        self._action_label.setText(tr("g3m_actions.patch_action"))
        self._action_combo.setItemText(0, tr("g3m_actions.action_create"))
        self._action_combo.setItemText(1, tr("g3m_actions.action_apply"))
        self._original_row.relocalize()
        self._second_row.relocalize()
        self._output_row.relocalize()
        self._run_btn.setText(tr("g3m_actions.run"))


class _MergeTab(QWidget):
    def __init__(self, g3m, app_state, parent=None) -> None:
        super().__init__(parent)
        self._g3m, self._app_state = g3m, app_state
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        cb_row = QHBoxLayout()
        self._code_cb = QCheckBox(tr("checkboxes.merge_code"))
        self._props_cb = QCheckBox(tr("checkboxes.merge_properties"))
        cb_row.addWidget(self._code_cb)
        cb_row.addWidget(self._props_cb)
        cb_row.addStretch()
        lay.addLayout(cb_row)

        self._original_row = _PathRow("g3m_actions.original_file", _DATA_FILTER)
        lay.addWidget(self._original_row)

        list_label = QLabel(tr("g3m_actions.merge_list"))
        lay.addWidget(list_label)
        self._list_label = list_label

        self._file_list = QListWidget()
        self._file_list.setMinimumHeight(100)
        lay.addWidget(self._file_list, 1)

        list_btns = QHBoxLayout()
        list_btns.setSpacing(6)
        self._add_btn = QPushButton(tr("g3m_actions.merge_add"))
        self._add_btn.setObjectName("g3m_actions_merge_add")
        self._add_btn.clicked.connect(self._on_add)
        self._remove_btn = QPushButton(tr("g3m_actions.merge_remove"))
        self._remove_btn.setObjectName("g3m_actions_merge_remove")
        self._remove_btn.clicked.connect(self._on_remove)
        self._up_btn = QPushButton(tr("ui.move_up"))
        self._up_btn.clicked.connect(lambda: self._move(-1))
        self._down_btn = QPushButton(tr("ui.move_down"))
        self._down_btn.clicked.connect(lambda: self._move(1))
        for b in (self._add_btn, self._remove_btn, self._up_btn, self._down_btn):
            list_btns.addWidget(b)
        list_btns.addStretch()
        lay.addLayout(list_btns)

        self._output_row = _PathRow(
            "g3m_actions.output_file", _ALL_FILTER, save_mode=True
        )
        lay.addWidget(self._output_row)

        run_row = QHBoxLayout()
        run_row.addStretch()
        self._run_btn = QPushButton(tr("g3m_actions.merge_run"))
        self._run_btn.setObjectName("g3m_actions_run_btn")
        self._run_btn.clicked.connect(self._on_run)
        run_row.addWidget(self._run_btn)
        run_row.addStretch()
        lay.addLayout(run_row)

        self._status_label = QLabel("")
        self._status_label.setObjectName("g3m_actions_status")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        lay.addWidget(self._status_label)

    def _on_add(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("ui.select_file"), "", _DATA_PATCH_FILTER
        )
        for p in paths:
            item = QListWidgetItem(os.path.basename(p))
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self._file_list.insertItem(0, item)

    def _on_remove(self):
        for item in self._file_list.selectedItems():
            self._file_list.takeItem(self._file_list.row(item))

    def _move(self, direction):
        row = self._file_list.currentRow()
        if row < 0:
            return
        new_row = row + direction
        if 0 <= new_row < self._file_list.count():
            item = self._file_list.takeItem(row)
            self._file_list.insertItem(new_row, item)
            self._file_list.setCurrentRow(new_row)

    def _on_run(self):
        if not self._g3m or not self._g3m.is_available():
            QMessageBox.warning(
                self, tr("g3m_actions.title"), tr("errors.g3mtool_not_available")
            )
            return
        orig = self._original_row.path()
        out = self._output_row.path()
        patches = [
            self._file_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._file_list.count())
        ]
        if not orig or len(patches) < 2 or not out:
            QMessageBox.warning(
                self, tr("g3m_actions.title"), tr("g3m_actions.merge_need_files")
            )
            return
        self._run_btn.setEnabled(False)
        self._status_label.setText(tr("g3m_actions.running"))
        self._worker = _WorkerThread(
            self._g3m.merge_patches,
            (
                orig,
                patches,
                out,
                None,
                None,
                self._code_cb.isChecked(),
                self._props_cb.isChecked(),
            ),
        )
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_finished(self, rc, out, err):
        self._run_btn.setEnabled(True)
        self._worker = None
        if rc == 0:
            self._status_label.setText(tr("g3m_actions.success"))
        else:
            self._status_label.setText(tr("g3m_actions.failed", error=err[:300]))

    def has_user_interaction(self) -> bool:
        return bool(
            self._original_row.path()
            or self._file_list.count()
            or self._output_row.path()
            or self._worker
        )

    def relocalize(self):
        self._code_cb.setText(tr("checkboxes.merge_code"))
        self._props_cb.setText(tr("checkboxes.merge_properties"))
        self._original_row.relocalize()
        self._list_label.setText(tr("g3m_actions.merge_list"))
        self._add_btn.setText(tr("g3m_actions.merge_add"))
        self._remove_btn.setText(tr("g3m_actions.merge_remove"))
        self._up_btn.setText(tr("ui.move_up"))
        self._down_btn.setText(tr("ui.move_down"))
        self._output_row.relocalize()
        self._run_btn.setText(tr("g3m_actions.merge_run"))


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

        self._file_row = _PathRow("g3m_actions.info_file", _DATA_PATCH_FILTER)
        lay.addWidget(self._file_row)

        cb_row = QHBoxLayout()
        self._verbose_cb = QCheckBox(tr("g3m_actions.verbose"))
        cb_row.addWidget(self._verbose_cb)
        cb_row.addStretch()
        self._run_btn = QPushButton(tr("g3m_actions.info_run"))
        self._run_btn.setObjectName("g3m_actions_run_btn")
        self._run_btn.clicked.connect(self._on_run)
        cb_row.addWidget(self._run_btn)
        lay.addLayout(cb_row)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setObjectName("g3m_actions_info_output")
        self._output.textChanged.connect(self._on_output_text_changed)
        lay.addWidget(self._output, 1)

    def _on_run(self):
        if not self._g3m or not self._g3m.is_available():
            QMessageBox.warning(
                self, tr("g3m_actions.title"), tr("errors.g3mtool_not_available")
            )
            return
        target = self._file_row.path()
        if not target:
            QMessageBox.warning(
                self, tr("g3m_actions.title"), tr("g3m_actions.select_all_paths")
            )
            return
        self._run_btn.setEnabled(False)
        self._set_output_text(tr("g3m_actions.running"))
        self._worker = _WorkerThread(
            self._g3m.info, (target, self._verbose_cb.isChecked())
        )
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_finished(self, rc, out, err):
        self._run_btn.setEnabled(True)
        self._worker = None
        if rc == 0:
            self._set_output_text(out)
        else:
            self._set_output_text(
                tr("g3m_actions.failed", error=err[:500]) + "\n\n" + out
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
        self._verbose_cb.setText(tr("g3m_actions.verbose"))
        self._run_btn.setText(tr("g3m_actions.info_run"))


class _DiffTab(QWidget):
    def __init__(self, g3m, app_state, parent_dialog=None) -> None:
        super().__init__(parent_dialog)
        self._g3m, self._app_state = g3m, app_state
        self._parent_dialog = parent_dialog
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        self._file1_row = _PathRow("g3m_actions.diff_file1", _DATA_PATCH_FILTER)
        lay.addWidget(self._file1_row)
        self._file2_row = _PathRow("g3m_actions.diff_file2", _DATA_PATCH_FILTER)
        lay.addWidget(self._file2_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._run_btn = QPushButton(tr("g3m_actions.diff_run"))
        self._run_btn.setObjectName("g3m_actions_run_btn")
        self._run_btn.clicked.connect(self._on_run)
        btn_row.addWidget(self._run_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._status_label = QLabel("")
        self._status_label.setObjectName("g3m_actions_status")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        lay.addWidget(self._status_label)
        lay.addStretch()

    def _on_run(self):
        if not self._g3m or not self._g3m.is_available():
            QMessageBox.warning(
                self, tr("g3m_actions.title"), tr("errors.g3mtool_not_available")
            )
            return
        f1, f2 = self._file1_row.path(), self._file2_row.path()
        if not f1 or not f2:
            QMessageBox.warning(
                self, tr("g3m_actions.title"), tr("g3m_actions.select_all_paths")
            )
            return
        self._run_btn.setEnabled(False)
        self._status_label.setText(tr("g3m_actions.running"))
        out_dir = tempfile.mkdtemp(prefix="g3m_actions_diff_")
        self._out_dir = out_dir
        self._worker = _WorkerThread(self._g3m.diff, (f1, f2, out_dir))
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_finished(self, rc, out, err):
        self._run_btn.setEnabled(True)
        self._worker = None
        if rc != 0:
            self._status_label.setText(tr("g3m_actions.failed", error=err[:300]))
            self._cleanup_out_dir()
            return
        self._status_label.setText(tr("g3m_actions.success"))
        md_file = self._find_md(self._out_dir)
        if md_file:
            from ui.dialogs.g3mtool_diff_viewer import DiffViewerDialog

            dlg = DiffViewerDialog(
                md_file, self._app_state, self._parent_dialog or self
            )
            dlg.destroyed.connect(self._cleanup_out_dir)
            dlg.show()
        else:
            self._status_label.setText(tr("g3m_actions.diff_no_report"))
            self._cleanup_out_dir()

    def _cleanup_out_dir(self):
        if self._out_dir:
            shutil.rmtree(self._out_dir, ignore_errors=True)
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
        self._run_btn.setText(tr("g3m_actions.diff_run"))


class G3MActionsDialog(QDialog):
    """Non-modal G3M Actions dialog."""

    def __init__(self, g3m_manager, app_state, parent=None) -> None:
        super().__init__(parent)
        self._g3m = g3m_manager
        self._app_state = app_state
        self.setWindowTitle(tr("g3m_actions.title"))
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
        self._title_label = QLabel(tr("g3m_actions.title"))
        self._title_label.setObjectName("g3m_actions_title")
        font = self._title_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self._title_label.setFont(font)
        header.addWidget(self._title_label)
        header.addStretch()
        self._close_btn = QPushButton(tr("common.close"))
        self._close_btn.setObjectName("g3m_actions_close_btn")
        self._close_btn.clicked.connect(self.close)
        header.addWidget(self._close_btn)
        main.addLayout(header)

        self._tabs = QTabWidget()
        self._patch_tab = _PatchTab(self._g3m, self._app_state)
        self._merge_tab = _MergeTab(self._g3m, self._app_state)
        self._info_tab = _InfoTab(self._g3m, self._app_state)
        self._diff_tab = _DiffTab(self._g3m, self._app_state, self)
        self._tabs.addTab(self._patch_tab, tr("g3m_actions.tab_patch"))
        self._tabs.addTab(self._merge_tab, tr("g3m_actions.tab_merge"))
        self._tabs.addTab(self._info_tab, tr("g3m_actions.tab_info"))
        self._tabs.addTab(self._diff_tab, tr("g3m_actions.tab_diff"))
        main.addWidget(self._tabs)

    def _apply_theme(self):
        base = build_dialog_theme_stylesheet(self._app_state)
        theme = get_dialog_theme_values(self._app_state)
        font_family = _get_app_font(self._app_state)
        extra = f"""
            QLabel#g3m_actions_title {{
                font-size: 16px;
            }}
            QLabel#g3m_actions_status {{
                font-size: 12px;
                color: {theme["secondary_text"]};
            }}
            QTextEdit#g3m_actions_info_output {{
                background-color: {theme["background"]};
                border: 2px solid {theme["border"]};
                border-radius: {theme["field_radius"]}px;
                color: {theme["text"]};
                font-family: {font_family};
                font-size: 12px;
                padding: 6px;
            }}
            QTabWidget::pane {{
                border: 2px solid {theme["border"]};
                border-radius: {theme["button_radius"]}px;
                background-color: {theme["background"]};
            }}
            QTabBar::tab {{
                background-color: {theme["button"]};
                color: {theme["text"]};
                border: 2px solid {theme["border"]};
                border-bottom: none;
                padding: 6px 14px;
                margin-right: 2px;
                border-top-left-radius: {theme["button_radius"]}px;
                border-top-right-radius: {theme["button_radius"]}px;
            }}
            QTabBar::tab:selected {{
                background-color: {theme["button_hover"]};
                border-bottom: 2px solid {theme["background"]};
            }}
            QTabBar::tab:hover {{
                background-color: {theme["button_hover"]};
            }}
            QComboBox {{
                background-color: {theme["button"]};
                border: 2px solid {theme["border"]};
                border-radius: {theme["field_radius"]}px;
                color: {theme["text"]};
                padding: 4px 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {theme["background"]};
                color: {theme["text"]};
                selection-background-color: {theme["button_hover"]};
            }}
            QListWidget {{
                background-color: {theme["background"]};
                border: 2px solid {theme["border"]};
                border-radius: {theme["field_radius"]}px;
                color: {theme["text"]};
            }}
            QListWidget::item:selected {{
                background-color: {theme["button_hover"]};
            }}
        """
        self.setStyleSheet(base + extra)

    def relocalize_ui(self):
        self.setWindowTitle(tr("g3m_actions.title"))
        self._title_label.setText(tr("g3m_actions.title"))
        self._close_btn.setText(tr("common.close"))
        self._tabs.setTabText(0, tr("g3m_actions.tab_patch"))
        self._tabs.setTabText(1, tr("g3m_actions.tab_merge"))
        self._tabs.setTabText(2, tr("g3m_actions.tab_info"))
        self._tabs.setTabText(3, tr("g3m_actions.tab_diff"))
        self._patch_tab.relocalize()
        self._merge_tab.relocalize()
        self._info_tab.relocalize()
        self._diff_tab.relocalize()

    def _stop_all_workers(self):
        for tab in (self._patch_tab, self._merge_tab, self._info_tab, self._diff_tab):
            worker = getattr(tab, "_worker", None)
            if worker and worker.isRunning():
                worker.quit()
                worker.wait(3000)
        if self._g3m and hasattr(self._g3m, "cancel_active_processes"):
            self._g3m.cancel_active_processes()

    def _has_any_interaction(self) -> bool:
        return any(
            tab.has_user_interaction()
            for tab in (
                self._patch_tab,
                self._merge_tab,
                self._info_tab,
                self._diff_tab,
            )
        )

    def closeEvent(self, event):
        if self._has_any_interaction():
            reply = QMessageBox.question(
                self,
                tr("g3m_actions.title"),
                tr("g3m_actions.confirm_close"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._stop_all_workers()
        event.accept()
        self.deleteLater()

    def refresh_theme(self):
        self._apply_theme()
