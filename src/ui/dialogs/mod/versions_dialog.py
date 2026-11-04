"""Mod Versions dialog - manage per-mod version snapshots stored as zips in mod_versions/."""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import tempfile
from typing import TYPE_CHECKING, cast

from PyQt6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent

if TYPE_CHECKING:
    from services.mod.service import ModManager

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from presentation.drag_drop import (
    collect_drop_file_paths,
    collect_drop_urls,
)
from services.localization_service import tr
from ui.common.dialog_theme import (
    DynamicDialog,
    build_dialog_theme_stylesheet,
    build_progress_bar_stylesheet,
    get_dialog_text_color,
    get_dialog_theme_values,
)
from ui.utils.thread_lifetime import ManagedQThread, retire_qthread
from ui.utils.ui_utils import UIAnimator, format_size
from utils.date_format import format_timestamp
from utils.mod.utils import is_gamebanana_id
from utils.mod.version_utils import apply_version_zip as _apply_version_zip
from utils.mod.version_utils import (
    create_version_zip,
)
from utils.mod.version_utils import list_local_versions as _list_local_versions
from utils.mod.version_utils import resolve_content_path as _resolve_content_path
from utils.path_utils import colored_icon
from utils.process_utils import format_filesystem_error, format_network_error

logger = logging.getLogger(__name__)


def _convert_archive_to_version_zip(
    archive_path: str, mod_folder: str, version_name: str
) -> bool:
    """Extract archive, convert if needed (deltamod), then zip content into mod_versions/."""
    temp_dir = tempfile.mkdtemp(prefix="mv_conv_")
    try:
        from utils.archive_utils import ArchiveExtractor

        ArchiveExtractor.extract(archive_path, temp_dir)
    except Exception as e:
        logger.error(
            "mod_versions: extract failed: %s - %s", type(e).__name__, e, exc_info=True
        )
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False

    try:
        from utils.file_utils import normalize_mod_package

        try:
            normalize_mod_package(temp_dir, require_manifest=False)
        except Exception as e:
            logger.exception(
                "mod_versions: normalize_mod_package failed for %s with require_manifest=False: %s",
                temp_dir,
                e,
            )
        content_path = _resolve_content_path(temp_dir)
        create_version_zip(
            content_path, mod_folder, version_name, ignore_versions_dir=False
        )
        return True
    except Exception as e:
        logger.error("mod_versions: convert failed: %s", e, exc_info=True)
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


class _ModVersionWorker(ManagedQThread):
    """Background worker for download + convert operations."""

    progress = pyqtSignal(int)
    result_ready = pyqtSignal(bool, str)

    def __init__(
        self, url: str, mod_folder: str, version_name: str, parent=None
    ) -> None:
        super().__init__(parent)
        self._url = url
        self._mod_folder = mod_folder
        self._version_name = version_name
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        tmp_path = None
        try:
            self.progress.emit(10)
            from utils.network_utils import get_session

            session = get_session()
            resp = session.get(self._url, timeout=120, stream=True)
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            suffix = ".zip"
            cd = resp.headers.get("content-disposition", "")
            if "filename=" in cd:
                fn = cd.split("filename=")[-1].strip("\"'")
                if "." in fn:
                    suffix = "." + fn.rsplit(".", 1)[-1]
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix, prefix="mv_dl_"
            ) as tmp:
                received = 0
                for chunk in resp.iter_content(chunk_size=65536):
                    if self._cancelled:
                        tmp_path = tmp.name
                        self.result_ready.emit(False, "cancelled")
                        return
                    tmp.write(chunk)
                    received += len(chunk)
                    if total > 0:
                        self.progress.emit(10 + int(70 * received / total))
                tmp_path = tmp.name
            self.progress.emit(80)
            if self._cancelled:
                self.result_ready.emit(False, "cancelled")
                return
            ok = _convert_archive_to_version_zip(
                tmp_path, self._mod_folder, self._version_name
            )
            self.progress.emit(100)
            self.result_ready.emit(ok, "" if ok else "convert_failed")
        except Exception as e:
            logger.error("_ModVersionWorker: %s", e, exc_info=True)
            self.result_ready.emit(False, format_network_error(e, url=self._url))
        finally:
            if tmp_path:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)


class _VersionItemWidget(QFrame):
    switch_requested = pyqtSignal(dict)
    delete_requested = pyqtSignal(dict)

    def __init__(self, version_info: dict, parent=None) -> None:
        super().__init__(parent)
        self._info = version_info
        self.setObjectName("mod_version_record")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        left = QVBoxLayout()
        left.setSpacing(2)
        self._name_label = QLabel(self._info["name"])
        self._name_label.setObjectName("mod_version_name")
        self._name_label.setTextFormat(Qt.TextFormat.PlainText)
        self._name_label.setWordWrap(True)
        self._name_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        font = self._name_label.font()
        font.setBold(True)
        self._name_label.setFont(font)
        left.addWidget(self._name_label)
        parts = []
        if self._info.get("size"):
            parts.append(format_size(self._info["size"]))
        if self._info.get("mtime"):
            parts.append(format_timestamp(self._info["mtime"]))
        self._info_label = QLabel(" · ".join(parts))
        self._info_label.setObjectName("mod_version_info")
        left.addWidget(self._info_label)
        layout.addLayout(left, 1)
        self._switch_btn = QPushButton(tr("mod_versions.switch"))
        self._switch_btn.setObjectName("mod_version_btn_switch")
        self._switch_btn.clicked.connect(lambda: self.switch_requested.emit(self._info))
        layout.addWidget(self._switch_btn)
        self._delete_btn = QPushButton(tr("mod_versions.delete"))
        self._delete_btn.setObjectName("mod_version_btn_delete")
        self._delete_btn.clicked.connect(lambda: self.delete_requested.emit(self._info))
        layout.addWidget(self._delete_btn)

    def relocalize_ui(self):
        self._switch_btn.setText(tr("mod_versions.switch"))
        self._delete_btn.setText(tr("mod_versions.delete"))


class ModVersionsDialog(DynamicDialog):
    def __init__(self, mod_folder: str, mod_data, app_state, parent=None) -> None:
        super().__init__(parent)
        self._mod_folder = mod_folder
        self._mod_data = mod_data
        self._app_state = app_state
        self._mod_service = self._resolve_mod_service(parent)
        self._version_widgets: dict[str, _VersionItemWidget] = {}
        self._worker: _ModVersionWorker | None = None
        self._import_queue: list[tuple[str, str]] = []
        self.setWindowTitle(tr("mod_versions.title"))
        self.setMinimumSize(500, 380)
        self.resize(540, 460)
        self.setModal(True)
        self.setAcceptDrops(True)
        self._build_ui()
        self._apply_theme()
        self._populate()

    def _is_gamebanana_mod(self) -> bool:
        if hasattr(self._mod_data, "is_gamebanana_mod") and callable(
            self._mod_data.is_gamebanana_mod
        ):
            return bool(self._mod_data.is_gamebanana_mod())
        key = (
            self._mod_data.get("id")
            if isinstance(self._mod_data, dict)
            else getattr(self._mod_data, "id", None)
        )
        return is_gamebanana_id(key)

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(6)

        header = QHBoxLayout()
        self._title_label = QLabel(tr("mod_versions.title"))
        self._title_label.setObjectName("mod_versions_title")
        font = self._title_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self._title_label.setFont(font)
        header.addWidget(self._title_label)
        header.addStretch()
        self._close_btn = QPushButton(tr("common.close"))
        self._close_btn.setObjectName("mod_versions_close_btn")
        self._close_btn.clicked.connect(self.close)
        header.addWidget(self._close_btn)
        main.addLayout(header)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 4)
        actions.addStretch()
        tc = get_dialog_text_color(self._app_state)
        self._add_btn = QPushButton(tr("mod_versions.add_local"))
        self._add_btn.setObjectName("mod_versions_add_btn")
        self._add_btn.setIcon(colored_icon("add", tc))
        self._add_btn.setIconSize(QSize(16, 16))
        self._add_btn.clicked.connect(self._on_add_local)
        actions.addWidget(self._add_btn)
        if self._is_gamebanana_mod():
            self._gb_btn = QPushButton(tr("mod_versions.download_from_gb"))
            self._gb_btn.setObjectName("mod_versions_gb_btn")
            self._gb_btn.clicked.connect(self._on_download_from_gb)
            actions.addWidget(self._gb_btn)
        actions.addStretch()
        main.addLayout(actions)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFixedHeight(14)
        self._progress_bar.setVisible(False)
        main.addWidget(self._progress_bar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._list_widget)
        main.addWidget(self._scroll)

        self._empty_label = QLabel(tr("mod_versions.empty"))
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setObjectName("mod_versions_empty")
        main.addWidget(self._empty_label)

    def _apply_theme(self):
        base = build_dialog_theme_stylesheet(self._app_state)
        theme = get_dialog_theme_values(self._app_state)
        extra = f"""
            QFrame#mod_version_record {{
                background-color: {theme["elements"]};
                border: 2px solid {theme["border"]};
                border-radius: {theme["button_radius"]}px;
            }}
            QLabel#mod_version_name {{
                font-weight: bold;
                font-size: 13px;
            }}
            QLabel#mod_version_info {{
                font-size: 11px;
                color: {theme["secondary_text"]};
            }}
            QLabel#mod_versions_title {{
                font-size: 16px;
            }}
            QLabel#mod_versions_empty {{
                font-size: 13px;
                color: {theme["secondary_text"]};
            }}
        """
        self.set_theme_stylesheet(base + extra + build_progress_bar_stylesheet(theme))

    def _populate(self):
        self._clear_list()
        for v in _list_local_versions(self._mod_folder):
            self._add_version_widget(v)
        self._update_empty_visibility()

    def _clear_list(self):
        for w in self._version_widgets.values():
            self._list_layout.removeWidget(w)
            w.deleteLater()
        self._version_widgets.clear()

    def _add_version_widget(self, version_info: dict):
        w = _VersionItemWidget(version_info, self)
        w.switch_requested.connect(self._on_switch)
        w.delete_requested.connect(self._on_delete)
        self._version_widgets[version_info["path"]] = w
        idx = max(0, self._list_layout.count() - 1)
        self._list_layout.insertWidget(idx, w)

    def _update_empty_visibility(self):
        has = bool(self._version_widgets)
        self._scroll.setVisible(has)
        self._empty_label.setVisible(not has)

    def _is_busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _set_busy(self, busy: bool):
        self._progress_bar.setVisible(busy)
        self._add_btn.setEnabled(not busy)
        if hasattr(self, "_gb_btn"):
            self._gb_btn.setEnabled(not busy)
        if busy:
            UIAnimator.progress_to(self._progress_bar, 0, self._app_state)

    def _ask_version_name(self, default: str = "") -> str | None:
        name, ok = QInputDialog.getText(
            self,
            tr("mod_versions.name_prompt_title"),
            tr("mod_versions.name_prompt"),
            text=default,
        )
        if not ok or not name.strip():
            return None
        return name.strip()

    def _on_add_local(self):
        if self._is_busy():
            return
        dialog = DynamicDialog(self)
        dialog.set_localized_title("mod_versions.add_local")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        btn_layout = QHBoxLayout()
        create_btn = dialog.localize_text(QPushButton(), "mod_versions.create_snapshot")
        create_btn.clicked.connect(lambda: dialog.done(1))
        btn_layout.addWidget(create_btn)
        import_btn = dialog.localize_text(QPushButton(), "mod_versions.import_file")
        import_btn.clicked.connect(lambda: dialog.done(2))
        btn_layout.addWidget(import_btn)
        layout.addLayout(btn_layout)
        dialog.set_theme_stylesheet(build_dialog_theme_stylesheet(self._app_state))
        result = dialog.exec()
        if result == 1:
            name = self._ask_version_name()
            if name:
                self._do_create_snapshot(name)
        elif result == 2:
            self._do_import()

    def _do_create_snapshot(self, version_name: str):
        try:
            create_version_zip(
                self._mod_folder,
                self._mod_folder,
                version_name,
                ignore_versions_dir=True,
            )
            self._populate()
        except Exception as e:
            logger.error("mod_versions: snapshot failed: %s", e, exc_info=True)
            self._safe_warning(
                tr("errors.error"),
                format_filesystem_error(e, path=self._mod_folder),
            )

    def _do_import(self):
        from ui.common.feedback import FeedbackManager
        from ui.dialogs.import_dialog import ImportDialog

        feedback = FeedbackManager(self)
        dialog = ImportDialog(self, feedback, "mod_versions", "*.zip *.7z *.rar")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.import_method == "file" and dialog.selected_file:
            self._import_from_path(dialog.selected_file, prompt_for_name=True)
        elif dialog.import_method == "url" and dialog.selected_url:
            self._start_url_worker(dialog.selected_url, prompt_for_name=True)

    def _safe_warning(self, title: str, message: str) -> None:
        try:
            QMessageBox.warning(self, title, message)
        except Exception:
            logger.exception("mod_versions: failed to show warning dialog")

    def _safe_information(self, title: str, message: str) -> None:
        try:
            QMessageBox.information(self, title, message)
        except Exception:
            logger.exception("mod_versions: failed to show information dialog")

    def _safe_question(self, *args, **kwargs):
        try:
            return QMessageBox.question(self, *args, **kwargs)
        except Exception:
            logger.exception("mod_versions: failed to show question dialog")
            return QMessageBox.StandardButton.No

    def _import_from_path(
        self,
        archive_path: str,
        version_name: str | None = None,
        prompt_for_name: bool = True,
    ):
        base = os.path.splitext(os.path.basename(archive_path))[0]
        if version_name is None:
            version_name = (
                self._ask_version_name(default=base) if prompt_for_name else base
            )
            if not version_name:
                return
        self._set_busy(True)
        self._progress_bar.setValue(50)
        try:
            _convert_archive_to_version_zip(
                archive_path, self._mod_folder, version_name
            )
            self._populate()
        except Exception as e:
            logger.error("mod_versions: import failed: %s", e, exc_info=True)
            self._safe_warning(
                tr("errors.error"),
                format_filesystem_error(e, path=archive_path),
            )
        finally:
            self._set_busy(False)
            self._process_next_import()

    def _start_url_worker(
        self,
        url: str,
        version_name: str | None = None,
        prompt_for_name: bool = True,
    ):
        if self._is_busy():
            self._import_queue.append(("url", url))
            return
        if not version_name:
            base = (
                os.path.splitext(os.path.basename(url.split("?")[0]))[0] or "download"
            )
            version_name = (
                self._ask_version_name(default=base) if prompt_for_name else base
            )
            if not version_name:
                return
        self._set_busy(True)
        self._worker = _ModVersionWorker(
            url, self._mod_folder, version_name, parent=self
        )
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.result_ready.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_progress(self, value: int) -> None:
        UIAnimator.progress_to(self._progress_bar, value, self._app_state)

    def _on_worker_finished(self, success: bool, error: str):
        if self._worker:
            retire_qthread(self._worker)
            self._worker = None
        self._set_busy(False)
        if success:
            self._populate()
            self._process_next_import()
        elif error and error != "cancelled":
            self._safe_warning(tr("errors.error"), error)
            self._process_next_import()
        else:
            self._process_next_import()

    def _process_next_import(self):
        if self._is_busy() or not self._import_queue:
            return
        kind, value = self._import_queue.pop(0)
        if kind == "file":
            self._import_from_path(value, prompt_for_name=False)
        elif kind == "url":
            self._start_url_worker(value, prompt_for_name=False)

    def _on_download_from_gb(self):
        if self._is_busy():
            return
        from utils.mod.utils import get_gamebanana_item_type, get_gamebanana_mod_id

        mod_id_str = get_gamebanana_mod_id(self._mod_data)
        if not mod_id_str:
            self._safe_warning(
                tr("errors.error"), tr("errors.invalid_gamebanana_mod_id")
            )
            return
        mod_id = int(mod_id_str)
        itemtype = get_gamebanana_item_type(self._mod_data)
        from adapters.gamebanana_adapter import GameBananaAPI

        try:
            api = GameBananaAPI()
            all_files = self._format_gb_files(
                api.get_mod_files(mod_id, itemtype=itemtype) or []
            )
        except Exception as e:
            logger.error("mod_versions: GameBanana files failed: %s", e, exc_info=True)
            self._safe_warning(tr("errors.error"), format_network_error(e))
            return
        if not all_files:
            self._safe_information(
                tr("mod_versions.title"),
                tr("errors.mod_no_files", mod_name=self._get_mod_attr("name", "")),
            )
            return
        from ui.dialogs.file_picker_dialog import GameBananaFilePickerDialog

        picker = GameBananaFilePickerDialog(
            self,
            all_files,
            str(self._get_mod_attr("name", "") or ""),
            self._get_mod_attr("homepage"),
        )
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        selected = picker.get_selected_file()
        if not selected:
            return
        download_url = selected.get("download_url") or selected.get("_sDownloadUrl")
        if not download_url:
            file_id = selected.get("id") or selected.get("_idRow")
            if file_id:
                download_url = f"https://gamebanana.com/dl/{file_id}"
        if not download_url:
            self._safe_warning(tr("errors.error"), tr("errors.no_download_url"))
            return
        file_name = (
            selected.get("name")
            or selected.get("_sFile")
            or f"file_{selected.get('id', 'unknown')}"
        )
        version_name = os.path.splitext(file_name)[0]
        self._start_url_worker(download_url, version_name)

    @staticmethod
    def _format_gb_files(raw_files: list) -> list[dict]:
        formatted = []
        for f in raw_files:
            if not isinstance(f, dict):
                continue
            file_id = f.get("_idRow")
            if not file_id:
                continue
            if not f.get("_bHasContents", True):
                continue
            name = f.get("_sFile") or f.get("_sName") or f"file_{file_id}"
            download_url = (
                f.get("_sDownloadUrl") or f"https://gamebanana.com/dl/{file_id}"
            )
            formatted.append(
                {
                    "id": file_id,
                    "_idRow": file_id,
                    "name": name,
                    "_sFile": name,
                    "download_url": download_url,
                    "_sDownloadUrl": download_url,
                    "version": f.get("_sVersion", ""),
                    "description": f.get("_sDescription", ""),
                    "size_bytes": f.get("_nFilesize") or 0,
                    "timestamp": f.get("_tsDateAdded"),
                    "download_count": f.get("_nDownloadCount") or 0,
                    "md5": f.get("_sMd5Checksum"),
                    "analysis_state": f.get("_sAnalysisState"),
                    "analysis_result": f.get("_sAnalysisResult"),
                    "av_state": f.get("_sAvState"),
                    "av_result": f.get("_sAvResult"),
                }
            )
        return formatted

    def _get_mod_attr(self, attr: str, default=None):
        if isinstance(self._mod_data, dict):
            return self._mod_data.get(attr, default)
        return getattr(self._mod_data, attr, default)

    @staticmethod
    def _resolve_mod_service(parent) -> ModManager | None:
        if parent and hasattr(parent, "mod_service"):
            return parent.mod_service
        parent_app = getattr(parent, "parent_app", None)
        if parent_app and hasattr(parent_app, "mod_service"):
            return parent_app.mod_service
        return None

    def _refresh_mods_after_change(self) -> None:
        if not self._mod_service:
            return
        self._mod_service.invalidate_mods_cache()
        self._mod_service.load_local_mods()
        self._mod_service.mod_list_updated.emit()

    def _on_switch(self, version_info: dict):
        reply = self._safe_question(
            tr("mod_versions.confirm_switch_title"),
            tr("mod_versions.confirm_switch_text", name=version_info["name"]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.setCursor(Qt.CursorShape.WaitCursor)
            _apply_version_zip(self._mod_folder, version_info["path"])
            self._refresh_mods_after_change()
            self._safe_information(
                tr("mod_versions.title"),
                tr("mod_versions.switch_success", name=version_info["name"]),
            )
        except Exception as e:
            logger.error("mod_versions: switch failed: %s", e, exc_info=True)
            self._safe_warning(
                tr("errors.error"),
                format_filesystem_error(e, path=version_info["path"]),
            )
        finally:
            self.unsetCursor()

    def _on_delete(self, version_info: dict):
        reply = self._safe_question(
            tr("mod_versions.confirm_delete_title"),
            tr("mod_versions.confirm_delete_text", name=version_info["name"]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(version_info["path"])
            self._populate()
        except Exception as e:
            logger.error("mod_versions: delete failed: %s", e, exc_info=True)
            self._safe_warning(
                tr("errors.error"),
                format_filesystem_error(e, path=version_info["path"]),
            )

    def dragEnterEvent(self, a0):
        event = cast(QDragEnterEvent, a0)
        if getattr(event, "source", lambda: None)() is not None:
            event.ignore()
            return
        md = event.mimeData()
        if collect_drop_file_paths(md) or collect_drop_urls(md):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, a0):
        event = cast(QDropEvent, a0)
        if getattr(event, "source", lambda: None)() is not None:
            event.ignore()
            return
        if self._is_busy():
            md = event.mimeData()
            for path in collect_drop_file_paths(md):
                self._import_queue.append(("file", path))
            for url in collect_drop_urls(md):
                self._import_queue.append(("url", url))
            event.acceptProposedAction()
            return
        md = event.mimeData()
        paths = collect_drop_file_paths(md)
        urls = collect_drop_urls(md)
        if paths or urls:
            event.acceptProposedAction()
            for path in paths:
                self._import_queue.append(("file", path))
            for url in urls:
                self._import_queue.append(("url", url))
            self._process_next_import()

    def closeEvent(self, a0):
        event = cast(QCloseEvent, a0)
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        super().closeEvent(event)

    def relocalize_ui(self):
        self.setWindowTitle(tr("mod_versions.title"))
        self._title_label.setText(tr("mod_versions.title"))
        self._close_btn.setText(tr("common.close"))
        self._add_btn.setText(tr("mod_versions.add_local"))
        self._add_btn.setIcon(
            colored_icon("add", get_dialog_text_color(self._app_state))
        )
        self._empty_label.setText(tr("mod_versions.empty"))
        if hasattr(self, "_gb_btn"):
            self._gb_btn.setText(tr("mod_versions.download_from_gb"))
        for w in self._version_widgets.values():
            w.relocalize_ui()

    def refresh_theme(self):
        self._apply_theme()
        self._add_btn.setIcon(
            colored_icon("add", get_dialog_text_color(self._app_state))
        )
