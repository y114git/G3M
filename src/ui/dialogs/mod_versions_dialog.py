"""Mod Versions dialog - manage per-mod version snapshots stored as zips in mod_versions/."""

import contextlib
import logging
import os
import shutil
import tempfile
import time
import zipfile

from PyQt6.QtCore import QSize, Qt, QThread, pyqtSignal
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
    QVBoxLayout,
    QWidget,
)

from services.localization_service import tr
from ui.common.dialog_theme import (
    build_dialog_theme_stylesheet,
    get_dialog_text_color,
    get_dialog_theme_values,
)
from ui.utils.ui_utils import format_size
from utils.mod_version_utils import (
    create_version_zip,
)
from utils.path_utils import colored_icon

logger = logging.getLogger(__name__)

MOD_VERSIONS_DIR = "mod_versions"


def _list_local_versions(mod_folder: str) -> list[dict]:
    versions_dir = os.path.join(mod_folder, MOD_VERSIONS_DIR)
    if not os.path.isdir(versions_dir):
        return []
    result = []
    for fname in sorted(os.listdir(versions_dir)):
        fpath = os.path.join(versions_dir, fname)
        if not os.path.isfile(fpath) or not fname.lower().endswith(".zip"):
            continue
        try:
            stat = os.stat(fpath)
            size = stat.st_size
            mtime = stat.st_mtime
        except OSError:
            size, mtime = 0, 0
        result.append(
            {
                "name": os.path.splitext(fname)[0],
                "filename": fname,
                "path": fpath,
                "size": size,
                "mtime": mtime,
            }
        )
    return result


def _clear_mod_folder(mod_folder: str):
    for item in os.listdir(mod_folder):
        if item == MOD_VERSIONS_DIR:
            continue
        path = os.path.join(mod_folder, item)
        if os.path.isdir(path):
            try:
                shutil.rmtree(path)
            except OSError as e:
                logger.warning("mod_versions: failed to remove %s: %s", path, e)
        else:
            try:
                os.remove(path)
            except OSError as e:
                logger.warning("mod_versions: failed to remove %s: %s", path, e)


def _resolve_content_path(temp_dir: str) -> str:
    """Resolve single directory layers and convert deltamod if present."""
    content_path = temp_dir
    contents = os.listdir(temp_dir)
    if len(contents) == 1:
        single = os.path.join(temp_dir, contents[0])
        if os.path.isdir(single):
            content_path = single
    from utils.file_utils import has_deltamod_info_file

    files_in_root = os.listdir(content_path)
    if has_deltamod_info_file(files_in_root):
        from adapters.deltamod_adapter import DeltamodConverter

        converter = DeltamodConverter(content_path, temp_dir)
        result = converter.convert()
        if result and os.path.isdir(result):
            content_path = result
    return content_path


def _apply_version_zip(mod_folder: str, zip_path: str):
    """Apply version zip, converting deltamod contents if needed."""
    temp_dir = tempfile.mkdtemp(prefix="mv_apply_")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp_dir)
        content_path = _resolve_content_path(temp_dir)

        _clear_mod_folder(mod_folder)
        for item in os.listdir(content_path):
            src = os.path.join(content_path, item)
            dst = os.path.join(mod_folder, item)
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


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


class _ModVersionWorker(QThread):
    """Background worker for download + convert operations."""

    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)

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
                        os.unlink(tmp_path)
                        self.finished.emit(False, "cancelled")
                        return
                    tmp.write(chunk)
                    received += len(chunk)
                    if total > 0:
                        self.progress.emit(10 + int(70 * received / total))
                tmp_path = tmp.name
            self.progress.emit(80)
            if self._cancelled:
                self.finished.emit(False, "cancelled")
                return
            ok = _convert_archive_to_version_zip(
                tmp_path, self._mod_folder, self._version_name
            )
            self.progress.emit(100)
            self.finished.emit(ok, "" if ok else "convert_failed")
        except Exception as e:
            logger.error("_ModVersionWorker: %s", e, exc_info=True)
            self.finished.emit(False, str(e))
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
        font = self._name_label.font()
        font.setBold(True)
        self._name_label.setFont(font)
        left.addWidget(self._name_label)
        parts = []
        if self._info.get("size"):
            parts.append(format_size(self._info["size"]))
        if self._info.get("mtime"):
            parts.append(
                time.strftime("%Y-%m-%d %H:%M", time.localtime(self._info["mtime"]))
            )
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


class ModVersionsDialog(QDialog):
    def __init__(self, mod_folder: str, mod_data, app_state, parent=None) -> None:
        super().__init__(parent)
        self._mod_folder = mod_folder
        self._mod_data = mod_data
        self._app_state = app_state
        self._version_widgets: dict[str, _VersionItemWidget] = {}
        self._worker: _ModVersionWorker | None = None
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
            return self._mod_data.is_gamebanana_mod()
        key = (
            self._mod_data.get("key")
            if isinstance(self._mod_data, dict)
            else getattr(self._mod_data, "key", None)
        )
        return bool(
            key
            and isinstance(key, str)
            and (key.startswith("gb_mod_") or key.startswith("gb_wip_"))
        )

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
                background-color: {theme["button"]};
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
            QProgressBar {{
                background-color: {theme["background"]};
                border: 2px solid {theme["border"]};
                border-radius: 4px;
                text-align: center;
                font-size: 10px;
                color: {theme["text"]};
            }}
            QProgressBar::chunk {{
                background-color: {theme["secondary_text"]};
                border-radius: 3px;
            }}
        """
        self.setStyleSheet(base + extra)

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
            self._progress_bar.setValue(0)

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
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("mod_versions.add_local"))
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        btn_layout = QHBoxLayout()
        create_btn = QPushButton(tr("mod_versions.create_snapshot"))
        create_btn.clicked.connect(lambda: dialog.done(1))
        btn_layout.addWidget(create_btn)
        import_btn = QPushButton(tr("mod_versions.import_file"))
        import_btn.clicked.connect(lambda: dialog.done(2))
        btn_layout.addWidget(import_btn)
        layout.addLayout(btn_layout)
        dialog.setStyleSheet(build_dialog_theme_stylesheet(self._app_state))
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
            QMessageBox.warning(self, tr("errors.error"), str(e))

    def _do_import(self):
        from ui.common.feedback import FeedbackManager
        from ui.dialogs.import_dialog import ImportDialog

        feedback = FeedbackManager(self)
        dialog = ImportDialog(self, feedback, "mod_versions", "*.zip *.7z *.rar")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.import_method == "file" and dialog.selected_file:
            self._import_from_path(dialog.selected_file)
        elif dialog.import_method == "url" and dialog.selected_url:
            self._start_url_worker(dialog.selected_url)

    def _import_from_path(self, archive_path: str):
        base = os.path.splitext(os.path.basename(archive_path))[0]
        version_name = self._ask_version_name(default=base)
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
            QMessageBox.warning(self, tr("errors.error"), str(e))
        finally:
            self._set_busy(False)

    def _start_url_worker(self, url: str, version_name: str | None = None):
        if self._is_busy():
            return
        if not version_name:
            base = (
                os.path.splitext(os.path.basename(url.split("?")[0]))[0] or "download"
            )
            version_name = self._ask_version_name(default=base)
            if not version_name:
                return
        self._set_busy(True)
        self._worker = _ModVersionWorker(
            url, self._mod_folder, version_name, parent=self
        )
        self._worker.progress.connect(self._progress_bar.setValue)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self, success: bool, error: str):
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        self._set_busy(False)
        if success:
            self._populate()
        elif error and error != "cancelled":
            QMessageBox.warning(self, tr("errors.error"), error)

    def _on_download_from_gb(self):
        if self._is_busy():
            return
        from utils.mod_utils import get_gamebanana_item_type, get_gamebanana_mod_id

        mod_id_str = get_gamebanana_mod_id(self._mod_data)
        if not mod_id_str:
            QMessageBox.warning(
                self, tr("errors.error"), tr("errors.invalid_gamebanana_mod_id")
            )
            return
        mod_id = int(mod_id_str)
        itemtype = get_gamebanana_item_type(self._mod_data)
        from adapters.gamebanana_adapter import GameBananaAPI

        api = GameBananaAPI()
        all_files = self._format_gb_files(
            api.get_mod_files(mod_id, itemtype=itemtype) or []
        )
        if not all_files:
            QMessageBox.information(
                self,
                tr("mod_versions.title"),
                tr("errors.mod_no_files", mod_name=self._get_mod_attr("name", "")),
            )
            return
        from ui.dialogs.file_picker_dialog import GameBananaFilePickerDialog

        picker = GameBananaFilePickerDialog(
            self,
            all_files,
            self._get_mod_attr("name", ""),
            self._get_mod_attr("external_url"),
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
            QMessageBox.warning(self, tr("errors.error"), tr("errors.no_download_url"))
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

    def _on_switch(self, version_info: dict):
        reply = QMessageBox.question(
            self,
            tr("mod_versions.confirm_switch_title"),
            tr("mod_versions.confirm_switch_text", name=version_info["name"]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.setCursor(Qt.CursorShape.WaitCursor)
            _apply_version_zip(self._mod_folder, version_info["path"])
            QMessageBox.information(
                self,
                tr("mod_versions.title"),
                tr("mod_versions.switch_success", name=version_info["name"]),
            )
        except Exception as e:
            logger.error("mod_versions: switch failed: %s", e, exc_info=True)
            QMessageBox.warning(self, tr("errors.error"), str(e))
        finally:
            self.unsetCursor()

    def _on_delete(self, version_info: dict):
        reply = QMessageBox.question(
            self,
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
            QMessageBox.warning(self, tr("errors.error"), str(e))

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasUrls() or md.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self._is_busy():
            return
        md = event.mimeData()
        if md.hasUrls():
            for u in md.urls():
                path = u.toLocalFile()
                if path and os.path.isfile(path):
                    event.acceptProposedAction()
                    self._import_from_path(path)
                    return
                s = u.toString()
                if s.startswith(("http://", "https://")):
                    event.acceptProposedAction()
                    self._start_url_worker(s)
                    return
        if md.hasText():
            text = md.text().strip()
            if text.startswith(("http://", "https://")):
                event.acceptProposedAction()
                self._start_url_worker(text)

    def closeEvent(self, event):
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
