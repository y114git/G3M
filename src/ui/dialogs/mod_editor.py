import os
import platform
import re
import shutil
import subprocess
import threading
import uuid
import webbrowser
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPixmap, QPainter
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFrame, QCheckBox, QComboBox, QMessageBox, QFileDialog, QInputDialog, QDialogButtonBox, QWidget, QListWidget
from PyQt6 import sip
from localization.manager import tr
from ui.widgets.custom_controls import NoScrollComboBox, NoScrollTabWidget
from ui.widgets.worker_signals import WorkerSignals
from utils.file_utils import resource_path, detect_field_type_by_text, get_file_filter, format_timestamp, sanitize_filename
from utils.crypto_utils import generate_secret_key, hash_secret_key
from utils.file_utils import game_version_sort_key
import logging
import requests

class ModEditorDialog(QDialog):

    def __init__(self, parent, is_creating=True, is_public=True, mod_data=None):
        super().__init__(parent)
        self.parent_app, self.is_creating, self.is_public = (parent, is_creating, is_public)
        self.mod_data, self.current_icon_url = (mod_data or {}, '')
        self.original_mod_data = mod_data.copy() if mod_data else {}
        self.mod_key = mod_data.get('key') if mod_data else None
        self.setWindowTitle(tr('ui.create_mod') if is_creating else tr('ui.edit_mod'))
        self.setModal(True)
        self.resize(900 if is_public else 700, 700 if is_public else 500)
        self.setMinimumSize(800 if is_public else 600, 600 if is_public else 400)
        self.init_ui()
        if not is_creating and mod_data:
            self.populate_fields()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        from PyQt6.QtWidgets import QScrollArea
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        if self.is_public and (not self.is_creating):
            self._create_info_section(layout)
        settings_frame = QFrame()
        settings_frame.setFrameStyle(QFrame.Shape.Box)
        settings_layout = QVBoxLayout(settings_frame)
        modtype_layout = QHBoxLayout()
        modtype_layout.addStretch()
        modtype_layout.addWidget(QLabel(tr('ui.mod_type_label')))
        self.modtype_combo = QComboBox()
        self.modtype_combo.addItem('DELTARUNE', 'deltarune')
        self.modtype_combo.addItem('DELTARUNE DEMO', 'deltarunedemo')
        self.modtype_combo.addItem('UNDERTALE', 'undertale')
        self.modtype_combo.currentIndexChanged.connect(self._update_file_tabs)
        modtype_layout.addWidget(self.modtype_combo)
        modtype_layout.addSpacing(12)
        self.piracy_checkbox = QCheckBox(tr('checkboxes.piracy_protection'))
        modtype_layout.addWidget(self.piracy_checkbox)
        modtype_layout.addStretch()
        settings_layout.addLayout(modtype_layout)
        form_layout = QVBoxLayout()
        self._create_form_fields(form_layout)
        settings_layout.addLayout(form_layout)
        layout.addWidget(settings_frame)
        self._create_file_management_section(layout)
        self._load_default_icon()
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)
        self._create_action_buttons(main_layout)

    def _create_form_fields(self, form_layout):
        form_layout.addWidget(QLabel(tr('ui.mod_name_label')))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(tr('ui.enter_mod_name'))
        form_layout.addWidget(self.name_edit)
        form_layout.addWidget(QLabel(tr('ui.mod_author') if self.is_public else tr('ui.mod_author_optional')))
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText(tr('ui.enter_author_name') if self.is_public else tr('ui.enter_author_name_optional'))
        if not self.is_creating:
            self.author_edit.setReadOnly(True)
        form_layout.addWidget(self.author_edit)
        form_layout.addWidget(QLabel(tr('ui.short_description')))
        self.tagline_edit = QLineEdit()
        self.tagline_edit.setMaxLength(200)
        self.tagline_edit.setPlaceholderText(tr('ui.short_description_placeholder'))
        form_layout.addWidget(self.tagline_edit)
        self._create_icon_section(form_layout)
        self._create_tags_section(form_layout)
        form_layout.addWidget(QLabel(tr('ui.overall_mod_version')))
        self.version_edit = QLineEdit()
        self.version_edit.setPlaceholderText('1.0.0')
        form_layout.addWidget(self.version_edit)
        if self.is_public:
            self.description_title_label = QLabel(tr('ui.full_description_link'))
            self.description_title_label.setWordWrap(True)
            self.description_title_label.setProperty('file_type', 'description')
            form_layout.addWidget(self.description_title_label)
            self.description_url_edit = QLineEdit()
            self.description_url_edit.setPlaceholderText('https://example.com/description.md')
            form_layout.addWidget(self.description_url_edit)
            self.description_url_edit.textChanged.connect(lambda: self._trigger_validation(self.description_url_edit, self._validate_url_for_title, title_label=self.description_title_label, is_patch=False))
            form_layout.addWidget(QLabel(tr('ui.game_version_label')))
            self.game_version_combo = NoScrollComboBox()
            self._load_game_versions()
            form_layout.addWidget(self.game_version_combo)
        else:
            self.description_url_edit = QLineEdit()
            self.description_url_edit.hide()
            form_layout.addWidget(QLabel(tr('ui.game_version_label')))
            self.game_version_edit = QLineEdit()
            self.game_version_edit.setPlaceholderText('1.04')
            form_layout.addWidget(self.game_version_edit)

    def _create_icon_section(self, form_layout):
        if self.is_public:
            self.icon_title_label = QLabel(tr('files.icon_direct_link'))
            self.icon_title_label.setWordWrap(True)
            self.icon_title_label.setProperty('file_type', 'icon')
            form_layout.addWidget(self.icon_title_label)
        else:
            form_layout.addWidget(QLabel(tr('files.icon_label')))
        icon_container = QHBoxLayout()
        self.icon_edit = QLineEdit()
        if self.is_public:
            self.icon_edit.setPlaceholderText(tr('ui.leave_empty_for_default_icon'))
            self.icon_edit.textChanged.connect(self._on_icon_url_changed)
        else:
            self.icon_edit.setPlaceholderText(tr('ui.icon_file_path_placeholder'))
            self.icon_edit.setReadOnly(True)
            self.icon_browse_button = QPushButton(tr('ui.browse_button'))
            self.icon_browse_button.clicked.connect(self._browse_local_icon)
            icon_container.addWidget(self.icon_browse_button)
        icon_container.addWidget(self.icon_edit)
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(64, 64)
        self.icon_preview.setStyleSheet('border: 1px solid gray;')
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_preview.setText(tr('ui.icon_preview'))
        icon_container.addWidget(self.icon_preview)
        form_layout.addLayout(icon_container)

    def _create_tags_section(self, form_layout):
        if self.is_public:
            form_layout.addWidget(QLabel(tr('ui.mod_tags_label')))
            tags_layout = QHBoxLayout()
            self.tag_translation = QCheckBox(tr('tags.translation_text'))
            self.tag_customization = QCheckBox(tr('tags.customization'))
            self.tag_gameplay = QCheckBox(tr('tags.gameplay'))
            self.tag_other = QCheckBox(tr('tags.other'))
            for tag in [self.tag_translation, self.tag_customization, self.tag_gameplay, self.tag_other]:
                tags_layout.addWidget(tag)
            form_layout.addLayout(tags_layout)
        else:
            for attr, checked in [('tag_translation', False), ('tag_customization', False), ('tag_gameplay', False), ('tag_other', True)]:
                setattr(self, attr, QCheckBox())
                if checked:
                    getattr(self, attr).setChecked(True)

    def _load_game_versions(self):
        try:
            self.game_version_combo.blockSignals(True)
            self.game_version_combo.clear()
            self.game_version_combo.addItems(['1.04'])
            self.game_version_combo.setCurrentIndex(0)
            self.game_version_combo.blockSignals(False)
        except Exception:
            pass
        from PyQt6.QtCore import QThread

        class _VersFetch(QThread):
            got = pyqtSignal(list)

            def __init__(self, parent=None):
                super().__init__(parent)

            def run(self):
                try:
                    from config.constants import CLOUD_FUNCTIONS_BASE_URL
                    import requests
                    r = requests.get(f'{CLOUD_FUNCTIONS_BASE_URL}/getGlobalSettings', timeout=6)
                    if r.status_code == 200:
                        data = r.json() or {}
                        vers = data.get('supported_game_versions', ['1.04']) or ['1.04']
                        if isinstance(vers, list):
                            self.got.emit(vers)
                except Exception:
                    pass
        worker = _VersFetch(self)

        def _apply(vers):
            try:
                vers = list(vers)
                vers.sort(key=game_version_sort_key, reverse=True)
                self.game_version_combo.blockSignals(True)
                self.game_version_combo.clear()
                self.game_version_combo.addItems(vers)
                if vers:
                    self.game_version_combo.setCurrentIndex(0)
                self.game_version_combo.blockSignals(False)
            except Exception:
                pass
        worker.got.connect(_apply)
        try:
            self._version_fetch_worker = worker
        except Exception:
            pass
        worker.start()

    def _trigger_validation(self, line_edit, validation_func, **kwargs):
        if hasattr(line_edit, '_validation_timer'):
            line_edit._validation_timer.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: validation_func(line_edit, **kwargs))
        line_edit._validation_timer = timer
        timer.start(500)

    def _create_info_section(self, layout):
        info_frame = QFrame()
        info_frame.setFrameStyle(QFrame.Shape.Box)
        info_layout = QVBoxLayout(info_frame)
        downloads_label = QLabel(tr('ui.downloads_count', count=self.mod_data.get('downloads', 0)))
        info_layout.addWidget(downloads_label)
        if self.mod_data.get('is_verified', False):
            verified_label = QLabel(tr('ui.mod_verified'))
            verified_label.setStyleSheet('color: green;')
        else:
            verified_label = QLabel(tr('ui.mod_not_verified'))
            verified_label.setStyleSheet('color: orange;')
            info_layout.addWidget(verified_label)
            details_button = QPushButton(tr('ui.verification_details'))
            details_button.clicked.connect(self._show_verification_details)
            info_layout.addWidget(details_button)
        layout.addWidget(info_frame)

    def _create_file_management_section(self, parent_layout):
        files_frame = QFrame()
        files_frame.setFrameStyle(QFrame.Shape.Box)
        files_layout = QVBoxLayout(files_frame)
        if not hasattr(self, 'screenshots_urls'):
            self.screenshots_urls = []
        manage_btn = QPushButton(tr('ui.manage_screenshots'))

        def _open_screenshots_dialog():
            dlg = QDialog(self)
            dlg.setWindowTitle(tr('ui.manage_screenshots'))
            dlg.setMinimumSize(500, 400)
            dlg.resize(700, 700)
            dlg.setSizeGripEnabled(True)
            v_layout = QVBoxLayout(dlg)
            from PyQt6.QtWidgets import QScrollArea
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            content_layout = QVBoxLayout(content)
            scroll.setWidget(content)
            v_layout.addWidget(scroll)
            editors = []
            previews = []
            timers = []
            workers = {}
            MAX_MB = 2
            MAX_BYTES = MAX_MB * 1024 * 1024
            from PyQt6.QtCore import QThread, QTimer as _QTimer

            class ShotLoader(QThread):
                loaded = pyqtSignal(int, object)
                failed = pyqtSignal(int, str)

                def __init__(self, idx, url):
                    super().__init__()
                    self.idx, self.url = (idx, url)

                def run(self):
                    try:
                        from utils.cache import _IMG_CACHE, _IMG_CACHE_LOCK, _NET_SEM
                        if _IMG_CACHE is not None and _IMG_CACHE_LOCK is not None:
                            with _IMG_CACHE_LOCK:
                                if self.url in _IMG_CACHE:
                                    self.loaded.emit(self.idx, _IMG_CACHE[self.url])
                                    return
                        import requests
                        try:
                            if _NET_SEM:
                                _NET_SEM.acquire()
                            try:
                                h = requests.head(self.url, allow_redirects=True, timeout=6)
                            finally:
                                if _NET_SEM:
                                    _NET_SEM.release()
                            cl = h.headers.get('content-length')
                            if cl and cl.isdigit() and (int(cl) > MAX_BYTES):
                                self.failed.emit(self.idx, 'too_large')
                                return
                        except Exception:
                            pass
                        if _NET_SEM:
                            _NET_SEM.acquire()
                        try:
                            resp = requests.get(self.url, timeout=8)
                        finally:
                            if _NET_SEM:
                                _NET_SEM.release()
                        if not resp.ok:
                            self.failed.emit(self.idx, 'unavailable')
                            return
                        if len(resp.content) > MAX_BYTES:
                            self.failed.emit(self.idx, 'too_large')
                            return
                        qimg = QImage()
                        if not qimg.loadFromData(resp.content):
                            self.failed.emit(self.idx, 'not_image')
                            return
                        if _IMG_CACHE is not None and _IMG_CACHE_LOCK is not None:
                            try:
                                with _IMG_CACHE_LOCK:
                                    _IMG_CACHE[self.url] = qimg
                            except Exception:
                                pass
                        self.loaded.emit(self.idx, qimg)
                    except Exception:
                        self.failed.emit(self.idx, 'error')

            def _apply_preview(index, qimg):
                area_w, area_h = (640, 200)
                pm = QPixmap.fromImage(qimg)
                scaled = pm.scaled(area_w, area_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                canvas = QPixmap(area_w, area_h)
                canvas.fill(QColor('black'))
                p = QPainter(canvas)
                x = (area_w - scaled.width()) // 2
                y = (area_h - scaled.height()) // 2
                p.drawPixmap(x, y, scaled)
                p.end()
                previews[index].setPixmap(canvas)
                previews[index].show()
                editors[index].setProperty('isValidShot', True)

            def _apply_error(index, kind):
                msg = {'too_large': tr('errors.file_too_large', max_size=MAX_MB), 'unavailable': tr('errors.file_not_available'), 'not_image': tr('errors.not_an_image'), 'error': tr('errors.url_error')}.get(kind, tr('errors.url_error'))
                previews[index].setText(msg)
                previews[index].show()
                editors[index].setProperty('isValidShot', False)

            def schedule_preview(index):
                t = timers[index]
                t.stop()
                t.start(300)

            def run_preview(index):
                url = editors[index].text().strip()
                previews[index].setText('')
                previews[index].setPixmap(QPixmap())
                previews[index].hide()
                editors[index].setProperty('isValidShot', False)
                if not url or not url.startswith(('http://', 'https://')):
                    return
                if index in workers:
                    try:
                        w = workers.pop(index)
                        if w.isRunning():
                            w.requestInterruption()
                            w.quit()
                            w.wait(100)
                    except Exception:
                        pass
                w = ShotLoader(index, url)
                workers[index] = w
                w.loaded.connect(lambda i, img: _apply_preview(i, img))
                w.failed.connect(lambda i, k: _apply_error(i, k))
                w.start()
            for i in range(10):
                le = QLineEdit()
                le.setPlaceholderText(tr('ui.screenshot_url_placeholder'))
                if i < len(self.screenshots_urls):
                    le.setText(self.screenshots_urls[i])
                editors.append(le)
                content_layout.addWidget(le)
                prev = QLabel()
                prev.setAlignment(Qt.AlignmentFlag.AlignCenter)
                prev.setMinimumHeight(200)
                prev.setStyleSheet('background-color: black; border: 1px solid #444;')
                prev.hide()
                previews.append(prev)
                content_layout.addWidget(prev)
                t = _QTimer(dlg)
                t.setSingleShot(True)
                t.timeout.connect(lambda idx=i: run_preview(idx))
                timers.append(t)
                le.textChanged.connect(lambda _=None, idx=i: schedule_preview(idx))
                schedule_preview(i)
            btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)

            def save_and_close():
                urls = []
                for e in editors:
                    u = e.text().strip()
                    if u and u.startswith(('http://', 'https://')):
                        urls.append(u)
                    if len(urls) >= 10:
                        break
                self.screenshots_urls = urls
                dlg.accept()
            btns.accepted.connect(save_and_close)
            btns.rejected.connect(dlg.reject)
            v_layout.addWidget(btns)
            dlg.exec()
        manage_btn.clicked.connect(_open_screenshots_dialog)
        files_layout.addWidget(manage_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        files_label = QLabel(tr('ui.files_management'))
        files_label.setStyleSheet('font-weight: bold; font-size: 18px;')
        files_layout.addWidget(files_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.file_tabs = NoScrollTabWidget()
        self.file_tabs.setStyleSheet('QTabWidget::tab-bar { alignment: center; } QTabBar::tab { padding: 4px 8px; }')
        self.modtype_combo.currentIndexChanged.connect(self._update_file_tabs)
        self.piracy_checkbox.stateChanged.connect(self._update_data_file_labels)
        self.piracy_checkbox.stateChanged.connect(self._recreate_data_frames)
        self.piracy_checkbox.stateChanged.connect(self._update_data_add_button_texts)
        if not self.is_public:
            self.piracy_checkbox.stateChanged.connect(self._update_file_tabs)
        files_layout.addWidget(self.file_tabs)
        parent_layout.addWidget(files_frame)
        self._update_file_tabs()

    def _update_data_file_labels(self):
        is_piracy_protected = self.piracy_checkbox.isChecked()
        for tab_index in range(self.file_tabs.count()):
            if not (tab := self.file_tabs.widget(tab_index)) or not (layout := tab.layout()):
                continue
            for i in range(layout.count()):
                if not (item := layout.itemAt(i)) or not (widget := item.widget()) or (not hasattr(widget, 'layout')):
                    continue
                if (frame_layout := widget.layout()):
                    for j in range(frame_layout.count()):
                        if (frame_item := frame_layout.itemAt(j)) and (frame_widget := frame_item.widget()) and isinstance(frame_widget, QLabel):
                            if frame_widget.text().startswith(('DATA', 'PATCH')):
                                frame_widget.setText(tr('files.patch_file') if is_piracy_protected else tr('files.data_file'))
                                self._update_labels_in_frame(frame_layout, is_piracy_protected)
                                break

    def _update_labels_in_frame(self, frame_layout, is_patch):
        for i in range(frame_layout.count()):
            if (item := frame_layout.itemAt(i)) and (widget := item.widget()) and isinstance(widget, QLabel):
                field_type = detect_field_type_by_text(widget.text())
                if field_type == 'file_path':
                    widget.setText(tr('files.update_file_label', is_public=self.is_public, is_patch=is_patch))
                elif field_type == 'version':
                    widget.setText(tr('files.version_label_colon', is_patch=is_patch))

    def _recreate_data_frames(self):
        for tab_index in range(self.file_tabs.count()):
            tab = self.file_tabs.widget(tab_index)
            if not tab:
                continue
            layout = tab.layout()
            if not layout:
                continue
            found = False
            for i in range(layout.count() - 1, -1, -1):
                item = layout.itemAt(i)
                w = item.widget() if item else None
                if w is None or not hasattr(w, 'layout'):
                    continue
                frame = w
                frame_layout = frame.layout() if hasattr(frame, 'layout') else None
                if not frame_layout or frame_layout.count() == 0:
                    continue
                first_item = frame_layout.itemAt(0)
                first = first_item.widget() if first_item and first_item.widget() else None
                if isinstance(first, QLabel):
                    ftype = first.property('file_type') if hasattr(first, 'property') else None
                    is_data_frame = ftype in ('data', 'patch')
                    if not is_data_frame:
                        txt = first.text() if hasattr(first, 'text') else ''
                        is_data_frame = isinstance(txt, str) and (txt.startswith('DATA') or txt.startswith('PATCH'))
                    if is_data_frame:
                        found = True
                        self._remove_data_file(None, layout, frame)
            if found:
                self._add_data_file(tab, layout)

    def _data_button_text(self) -> str:
        return tr('ui.add_data_patch_file') if self.piracy_checkbox.isChecked() else tr('ui.add_data_file')

    def _update_data_add_button_texts(self):
        for ti in range(self.file_tabs.count()):
            tab = self.file_tabs.widget(ti)
            if not tab:
                continue
            layout = tab.layout()
            if not layout:
                continue
            for i in range(layout.count()):
                item = layout.itemAt(i)
                btn_layout = item.layout() if item else None
                if not btn_layout:
                    continue
                for j in range(btn_layout.count()):
                    btn_item = btn_layout.itemAt(j)
                    w = btn_item.widget() if btn_item and btn_item.widget() else None
                    if w is not None and isinstance(w, QPushButton) and w.property('is_data_button'):
                        w.setText(self._data_button_text())
                break

    def _update_file_tabs(self):
        while self.file_tabs.count():
            self.file_tabs.removeTab(0)
        modtype = self.modtype_combo.currentData()
        if modtype == 'deltarunedemo':
            self._create_file_tab(tr('tabs.demo'))
        elif modtype == 'undertale':
            self._create_file_tab('UNDERTALE')
        else:
            for tab_name in [tr('tabs.menu_root'), tr('tabs.chapter_1'), tr('tabs.chapter_2'), tr('tabs.chapter_3'), tr('tabs.chapter_4')]:
                self._create_file_tab(tab_name)
        self._update_data_add_button_texts()

    def _create_file_tab(self, tab_name):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        buttons_layout = QHBoxLayout()
        data_button = QPushButton(self._data_button_text())
        data_button.setProperty('is_data_button', True)
        data_button.clicked.connect(lambda: self._add_data_file(tab, layout))
        extra_button = QPushButton(tr('ui.add_extra_files'))
        extra_button.clicked.connect(lambda: self._add_extra_files(tab, layout))
        for btn in [data_button, extra_button]:
            buttons_layout.addWidget(btn)
        layout.addLayout(buttons_layout)
        layout.addStretch()
        self.file_tabs.addTab(tab, tab_name)

    def _create_file_frame(self, tab_layout, file_type, key_name=None):
        is_local, is_patch = (not self.is_public, self.piracy_checkbox.isChecked())
        if file_type == 'extra' and key_name is None:
            key_name, ok = QInputDialog.getText(self, tr('dialogs.file_group_name'), tr('dialogs.enter_file_group_key'))
            if not ok or not key_name.strip():
                return
        if file_type == 'data':
            self._hide_add_button(tab_layout, 'DATA/PATCH')
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.Box)
        layout = QVBoxLayout(frame)
        if file_type == 'data':
            title = tr('files.patch_file') if is_patch else tr('files.data_file')
            label_type = tr('files.download_link') if self.is_public else tr('files.path_to')
            file_type_str = 'xdelta' if is_patch else 'data.win'
            input_label = tr('files.data_path_label', label_type=label_type, file_type=file_type_str)
            version_label = tr('files.version_label', file_type='PATCH' if is_patch else 'DATA')
            file_filter = get_file_filter('xdelta_files') if is_patch else get_file_filter('data_files')
            browse_title = tr('ui.select_data_file', file_type='xdelta' if is_patch else 'data.win')
        else:
            title = tr('files.extra_files_title', key_name=key_name)
            label_type = tr('files.archive_link') if self.is_public else tr('files.path_to')
            input_label = tr('files.archive_path_label', label_type=label_type)
            version_label = tr('files.version')
            file_filter = get_file_filter('archive_files')
            browse_title = tr('ui.select_archive')
        title_label = QLabel(title)
        title_label.setStyleSheet('font-weight: bold;')
        if file_type == 'extra' and key_name:
            title_label.setProperty('clean_key', key_name)
            title_label.setProperty('file_type', 'extra')
        elif file_type == 'data':
            title_label.setProperty('file_type', 'patch' if is_patch else 'data')
        layout.addWidget(title_label)
        layout.addWidget(QLabel(input_label))
        if is_local:
            container = QHBoxLayout()
            input_edit = QLineEdit()
            input_edit.setReadOnly(True)
            input_edit.setPlaceholderText(tr('ui.select_file'))
            input_edit.setProperty('is_local_path' if file_type == 'data' else 'is_local_extra_path', True)
            if file_type == 'extra':
                input_edit.setProperty('extra_key', key_name)
            container.addWidget(input_edit)
            browse_btn = QPushButton(tr('ui.browse_button'))
            browse_btn.clicked.connect(lambda: self._browse_file(input_edit, browse_title, file_filter))
            container.addWidget(browse_btn)
            layout.addLayout(container)
        else:
            input_edit = QLineEdit()
            layout.addWidget(input_edit)
            input_edit.textChanged.connect(lambda: self._trigger_validation(input_edit, self._validate_url_for_title, title_label=title_label, is_patch=is_patch if file_type == 'data' else False))
        layout.addWidget(QLabel(version_label))
        version_edit = QLineEdit()
        version_edit.setPlaceholderText('1.0.0')
        self._setup_version_validation(version_edit)
        layout.addWidget(version_edit)
        delete_btn = QPushButton(tr('ui.delete_button'))
        delete_btn.clicked.connect(lambda: self._remove_data_file(None, tab_layout, frame) if file_type == 'data' else self._remove_extra_files(tab_layout, frame))
        layout.addWidget(delete_btn)
        tab_layout.insertWidget(tab_layout.count() - 1, frame)

    def _hide_add_button(self, tab_layout, button_text=None):
        for i in range(tab_layout.count()):
            if (layout_item := tab_layout.itemAt(i)) and layout_item.layout():
                if (buttons_layout := layout_item.layout()):
                    for j in range(buttons_layout.count()):
                        if (button_item := buttons_layout.itemAt(j)) and button_item.widget():
                            button = button_item.widget()
                            if isinstance(button, QPushButton) and button.property('is_data_button'):
                                button.hide()
                                return

    def _add_data_file(self, tab, tab_layout):
        for i in range(tab_layout.count()):
            item = tab_layout.itemAt(i)
            w = item.widget() if item else None
            if w is not None and hasattr(w, 'layout'):
                fl = w.layout()
                if fl and fl.count() > 0 and isinstance(fl.itemAt(0).widget(), QLabel):
                    title = fl.itemAt(0).widget()
                    ftype = title.property('file_type') if hasattr(title, 'property') else None
                    txt = title.text() if hasattr(title, 'text') else ''
                    if ftype in ('data', 'patch') or (isinstance(txt, str) and (txt.startswith('DATA') or txt.startswith('PATCH') or txt.startswith('XDELTA'))):
                        return
        self._create_file_frame(tab_layout, 'data')

    def _add_extra_files(self, tab, tab_layout):
        self._create_file_frame(tab_layout, 'extra')

    def _remove_data_file(self, tab, tab_layout, data_frame):
        data_frame.hide()
        tab_layout.removeWidget(data_frame)
        data_frame.deleteLater()
        self._show_add_button(tab_layout)

    def _remove_extra_files(self, tab_layout, extra_frame):
        extra_frame.hide()
        tab_layout.removeWidget(extra_frame)
        extra_frame.deleteLater()

    def _show_add_button(self, tab_layout, button_text=None):
        for i in range(tab_layout.count()):
            if (layout_item := tab_layout.itemAt(i)) and layout_item.layout():
                if (buttons_layout := layout_item.layout()):
                    for j in range(buttons_layout.count()):
                        if (button_item := buttons_layout.itemAt(j)) and button_item.widget():
                            button = button_item.widget()
                            if isinstance(button, QPushButton) and button.property('is_data_button'):
                                button.show()
                                break

    def _setup_version_validation(self, line_edit):
        from PyQt6.QtGui import QValidator
        import re

        class VersionValidator(QValidator):

            def validate(self, text, pos):
                if not text:
                    return (QValidator.State.Intermediate, text, pos)
                if re.match('^\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}$', text):
                    return (QValidator.State.Acceptable, text, pos)
                if re.match('^\\d{0,3}(\\.\\d{0,3}(\\.\\d{0,3})?)?$', text):
                    return (QValidator.State.Intermediate, text, pos)
                return (QValidator.State.Invalid, text, pos)
        line_edit.setValidator(VersionValidator())
        line_edit.setText('1.0.0')

        def on_text_changed():
            text = line_edit.text()
            if not text:
                line_edit.setText('1.0.0')
                return
            parts = re.sub('[^\\d\\.]', '', text).split('.')
            if len(parts) > 3:
                parts = parts[:3]
            elif len(parts) < 3:
                parts += ['0'] * (3 - len(parts))
            parts = ['0' if not part else part[:3] for part in parts]
            corrected = '.'.join(parts)
            if corrected != text:
                line_edit.setText(corrected)
        line_edit.textChanged.connect(on_text_changed)

    def _validate_url_for_title(self, line_edit: QLineEdit, title_label: QLabel, is_patch: bool):
        url = line_edit.text().strip()
        line_edit.setProperty('isValid', True)
        file_type = 'data'
        base_title = tr('files.data_file')
        if hasattr(title_label, 'property'):
            label_file_type = title_label.property('file_type')
            if label_file_type == 'description':
                base_title, file_type = (tr('ui.full_description_link'), 'description')
            elif label_file_type == 'icon':
                base_title, file_type = (tr('files.icon_direct_link'), 'icon')
            elif label_file_type == 'patch' or is_patch:
                base_title, file_type = (tr('files.patch_file'), 'data')
        if file_type == 'data' and hasattr(self, 'description_url_edit') and (line_edit == self.description_url_edit):
            base_title, file_type = (tr('ui.full_description_link'), 'description')
        elif file_type == 'data' and hasattr(self, 'icon_edit') and (line_edit == self.icon_edit):
            base_title, file_type = (tr('files.icon_direct_link'), 'icon')
        label_ftype = title_label.property('file_type') if hasattr(title_label, 'property') else None
        if label_ftype == 'extra':
            base_title, file_type = (tr('files.extra_files_title', key_name=title_label.property('clean_key') or 'extra'), 'extra')
        else:
            clean_text = re.sub('<[^<]+?>', '', title_label.text())
            if tr('files.extra_files') in clean_text or tr('files.extra_files_title', key_name='')[:-2] in clean_text:
                base_title, file_type = (clean_text.split(' (')[0], 'extra')
        if hasattr(self, 'icon_edit') and line_edit == self.icon_edit:
            title_label.setText(tr('files.icon_direct_link'))
            return
        if not url:
            title_label.setText(base_title)
            return
        line_edit.setProperty('isValid', False)
        signals = WorkerSignals()
        signals.update_label.connect(self.on_validation_complete)
        self._last_validation_signals = signals

        def check_url():
            from urllib.parse import urlparse, unquote
            try:
                if file_type == 'icon' and hasattr(self, 'icon_edit') and (self.icon_edit.property('isValid') is True):
                    try:
                        filename = tr('ui.file_generic')
                        p = urlparse(url).path
                        if p and p not in ['/', ''] and (not p.endswith('/')):
                            nm = os.path.basename(unquote(p))
                            if nm:
                                filename = nm
                        final_text = f"{base_title}<span style='color: #44AA44;'> ({filename})</span>"
                        is_valid = True
                        signals.update_label.emit(line_edit, title_label, final_text, is_valid)
                        return
                    except Exception:
                        pass
                r = None
                if file_type == 'icon':
                    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                    r.raise_for_status()
                    headers = r.headers
                else:
                    try:
                        rh = requests.head(url, headers={'User-Agent': 'Mozilla/5.0'}, allow_redirects=True, timeout=10)
                        rh.raise_for_status()
                        headers = rh.headers
                    except Exception:
                        rg = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, stream=True, timeout=10)
                        rg.raise_for_status()
                        headers = rg.headers
                size_bytes = int(headers.get('content-length', 0)) if headers.get('content-length', '').isdigit() else 0
                content_type = headers.get('Content-Type', headers.get('content-type', '')).lower()
                if file_type == 'icon' and hasattr(self, 'icon_edit') and (self.icon_edit.property('isValid') is True):
                    try:
                        from urllib.parse import urlparse, unquote
                        filename = tr('ui.file_generic')
                        path = urlparse(url).path
                        if path and path not in ['/', ''] and (not path.endswith('/')):
                            potential_name = os.path.basename(unquote(path))
                            if potential_name:
                                filename = potential_name
                        final_text = f"{base_title}<span style='color: #44AA44;'> ({filename})</span>"
                        is_valid = True
                        signals.update_label.emit(line_edit, title_label, final_text, is_valid)
                        return
                    except Exception:
                        pass
                first_bytes = b''
                if file_type == 'icon' and r is not None and (size_bytes == 0):
                    size_bytes = len(r.content)
                if file_type != 'icon' and 'rg' in locals():
                    try:
                        chunk = next(rg.iter_content(chunk_size=16), b'')
                        first_bytes = chunk or b''
                    except Exception:
                        first_bytes = b''
                try:
                    from localization.manager import get_localization_manager
                    lang = get_localization_manager().get_current_language()
                except Exception:
                    lang = 'en'
                suffix = 'МБ' if lang == 'ru' else 'MB'
                size_text = f'{size_bytes / (1024 * 1024):.1f} {suffix}' if size_bytes > 0 else f'? {suffix}'
                filename = tr('ui.file_generic')
                content_disp = headers.get('Content-Disposition') or headers.get('content-disposition')
                if content_disp:
                    mstar = re.search("filename\\*=UTF-8''([^;]+)", content_disp, re.IGNORECASE)
                    m = re.search('filename\\s*=\\s*"?([^";]+)"?', content_disp, re.IGNORECASE)
                    if mstar:
                        filename = unquote(mstar.group(1), 'utf-8')
                    elif m:
                        filename = m.group(1)
                if filename == tr('ui.file_generic'):
                    if (path := urlparse(url).path) and path not in ['/', ''] and (not path.endswith('/')):
                        potential_name = os.path.basename(unquote(path))
                        if potential_name:
                            filename = potential_name
                data_extensions = ['.xdelta'] if is_patch or 'PATCH' in base_title else ['.win', '.ios']
                format_checks = {'icon': (None, 2), 'extra': (['.zip', '.rar', '.7z'], float('inf')), 'description': (['.md', '.txt'], 1), 'data': (data_extensions, 200)}
                if file_type in format_checks:
                    valid_exts, max_size = format_checks[file_type]
                    if file_type == 'icon':
                        try:
                            from PyQt6.QtGui import QImage
                            img = QImage()
                            if r is not None and img.loadFromData(r.content):
                                final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"
                                is_valid = True
                            else:
                                final_text = f"{base_title}<span style='color: #FF4444;'> ({tr('errors.not_an_image')})</span>"
                                is_valid = False
                        except Exception:
                            final_text = f"{base_title}<span style='color: #FF4444;'> ({tr('errors.validation_error')})</span>"
                            is_valid = False
                    elif 'text/html' in content_type:
                        final_text = f"{base_title}<span style='color: #FF4444;'> ({tr('errors.not_a_file_response')})</span>"
                        is_valid = False
                    elif file_type == 'data' and (is_patch or 'PATCH' in base_title):
                        xdelta_by_sig = first_bytes.startswith(b'VCD')
                        xdelta_by_ext = filename.lower().endswith('.xdelta')
                        xdelta_by_ct = any((x in content_type for x in ['xdelta', 'vcdiff'])) or content_type == 'application/octet-stream'
                        if xdelta_by_sig or xdelta_by_ext or xdelta_by_ct:
                            final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"
                            is_valid = True
                        else:
                            final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"
                            is_valid = True
                    elif file_type == 'extra':
                        is_zip = first_bytes.startswith(b'PK\x03\x04')
                        is_rar = first_bytes.startswith(b'Rar!')
                        is_7z = first_bytes.startswith(b"7z\xbc\xaf'\x1c")
                        if is_zip or is_rar or is_7z:
                            final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"
                            is_valid = True
                        else:
                            final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"
                            is_valid = True
                    elif file_type == 'description':
                        fn = filename.lower()
                        correct_ext = fn.endswith('.md') or fn.endswith('.txt')
                        if correct_ext and size_bytes >= 0 and ('text/html' not in content_type):
                            final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"
                            is_valid = True
                        else:
                            final_text = f"{base_title}<span style='color: #FF4444;'> ({tr('errors.not_a_valid_file')})</span>"
                            is_valid = False
                    elif file_type == 'data':
                        fn = filename.lower()
                        correct_ext = fn.endswith('.win') or fn.endswith('.ios')
                        valid_by_signature = False
                        if first_bytes:
                            if content_type == 'application/octet-stream':
                                valid_by_signature = True
                        if (correct_ext or valid_by_signature) and size_bytes >= 0 and ('text/html' not in content_type):
                            final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"
                            is_valid = True
                        else:
                            final_text = f"{base_title}<span style='color: #FF4444;'> ({tr('errors.not_a_valid_file')})</span>"
                            is_valid = False
                    if is_valid and size_bytes / (1024 * 1024) > max_size and (max_size != float('inf')):
                        final_text = f"{base_title}<span style='color: #FF4444;'> ({tr('errors.file_too_large', max_size=max_size)})</span>"
                        is_valid = False
                else:
                    final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"
                    is_valid = True
            except Exception:
                final_text = f"{base_title}<span style='color: #FF4444;'> ({tr('errors.url_error')})</span>"
                is_valid = False
            signals.update_label.emit(line_edit, title_label, final_text, is_valid)
        threading.Thread(target=check_url, daemon=True).start()

    def on_validation_complete(self, line_edit: QLineEdit, label: QLabel, text: str, is_valid: bool):
        try:
            if hasattr(self, 'icon_edit') and line_edit == self.icon_edit:
                text = tr('files.icon_direct_link')
                is_valid = True
        except Exception:
            pass
        if label and (not sip.isdeleted(label)):
            label.setText(text)
        if line_edit and (not sip.isdeleted(line_edit)):
            line_edit.setProperty('isValid', is_valid)

    def _browse_file(self, line_edit, title, file_filter):
        if (file_path := QFileDialog.getOpenFileName(self, title, '', file_filter)[0]):
            line_edit.setText(file_path)

    def _add_extra_files_with_data(self, tab, tab_layout, key_name, url, version):
        self._create_file_frame(tab_layout, 'extra', key_name)
        for i in range(tab_layout.count() - 1, -1, -1):
            if (item := tab_layout.itemAt(i)) and item.widget() and hasattr(item.widget(), 'layout'):
                frame_layout = item.widget().layout()
                url_edit = version_edit = None
                for j in range(frame_layout.count()):
                    widget = frame_layout.itemAt(j).widget() if frame_layout.itemAt(j) else None
                    if isinstance(widget, QLineEdit):
                        prev_widget = frame_layout.itemAt(j - 1).widget() if j > 0 and frame_layout.itemAt(j - 1) else None
                        if isinstance(prev_widget, QLabel):
                            field_type = detect_field_type_by_text(prev_widget.text())
                            if field_type == 'file_path':
                                url_edit = widget
                            elif field_type == 'version':
                                version_edit = widget
                if url_edit and version_edit:
                    url_edit.setText(url)
                    version_edit.setText(version or '1.0.0')
                    return

    def _add_local_extra_files_frame_with_data(self, tab, tab_layout, key_name, filenames):
        self._create_file_frame(tab_layout, 'extra', key_name)
        for i in range(tab_layout.count() - 1, -1, -1):
            item = tab_layout.itemAt(i)
            if item and item.widget() and hasattr(item.widget(), 'layout'):
                frame = item.widget()
                frame_layout = frame.layout()
                if frame_layout and isinstance(frame_layout.itemAt(0).widget(), QLabel):
                    title = frame_layout.itemAt(0).widget()
                    if title.property('clean_key') == key_name:
                        for fn in filenames:
                            file_label = QLabel(f'• {os.path.basename(fn)}')
                            file_label.setStyleSheet('color: gray; font-size: 10px;')
                            frame_layout.addWidget(file_label)
                            path_edit = QLineEdit()
                            path_edit.setText(fn)
                            path_edit.hide()
                            path_edit.setProperty('is_local_extra_path', True)
                            path_edit.setProperty('extra_key', key_name)
                            frame_layout.addWidget(path_edit)
                        return

    def _fill_local_data_file_in_tab(self, tab, file_path, version):
        for i in range(tab.layout().count() - 1, -1, -1):
            if (item := tab.layout().itemAt(i)) and item.widget() and hasattr(item.widget(), 'layout'):
                if (frame_layout := item.widget().layout()):
                    for j in range(frame_layout.count()):
                        if (frame_item := frame_layout.itemAt(j)) and frame_item.layout():
                            for k in range(frame_item.layout().count()):
                                if (container_item := frame_item.layout().itemAt(k)) and container_item.widget() and isinstance(container_item.widget(), QLineEdit):
                                    container_widget = container_item.widget()
                                    if container_widget.property('is_local_path'):
                                        folder_name = self.mod_data.get('folder_name', '')
                                        full_path = os.path.join(self.parent_app.mods_dir, folder_name, file_path) if folder_name and (not os.path.isabs(file_path)) else file_path
                                        container_widget.setText(full_path)
                                        for version_idx in range(j + 1, frame_layout.count()):
                                            if (version_item := frame_layout.itemAt(version_idx)) and version_item.widget() and isinstance(version_item.widget(), QLineEdit) and (not version_item.widget().isReadOnly()):
                                                version_item.widget().setText(version or '1.0.0')
                                                return
                                        return

    def _create_action_buttons(self, parent_layout):
        buttons_layout = QHBoxLayout()
        if self.is_creating:
            cancel_button = QPushButton(tr('ui.cancel_button'))
            cancel_button.clicked.connect(self._on_cancel_clicked)
            buttons_layout.addWidget(cancel_button)
            buttons_layout.addStretch()
            self.save_button = QPushButton(tr('ui.finish_creation'))
            self.save_button.clicked.connect(self._save_mod)
            buttons_layout.addWidget(self.save_button)
        else:
            cancel_button = QPushButton(tr('ui.cancel_button'))
            cancel_button.clicked.connect(self._on_cancel_clicked)
            buttons_layout.addWidget(cancel_button)
            buttons_layout.addSpacing(10)
            if self.is_public:
                self.hide_mod_button = QPushButton(tr('ui.hide_mod_button'))
                self.hide_mod_button.clicked.connect(self._toggle_mod_visibility)
                buttons_layout.addWidget(self.hide_mod_button)
                buttons_layout.addSpacing(10)
            delete_button = QPushButton(tr('ui.delete_local_mod') if not self.is_public else tr('ui.delete_mod'))
            delete_button.setStyleSheet('background-color: darkred; color: white;')
            delete_button.clicked.connect(self._delete_mod)
            buttons_layout.addWidget(delete_button)
            buttons_layout.addStretch()
            self.save_button = QPushButton(tr('ui.save_changes'))
            self.save_button.clicked.connect(self._save_mod)
            buttons_layout.addWidget(self.save_button)
        parent_layout.addLayout(buttons_layout)

    def _on_cancel_clicked(self):
        if QMessageBox.question(self, tr('dialogs.cancel_changes'), tr('dialogs.unsaved_changes_lost')) == QMessageBox.StandardButton.Yes:
            self.reject()

    def _on_icon_url_changed(self):
        url = self.icon_edit.text().strip()
        if url and url != self.current_icon_url:
            self.current_icon_url = url
            self._load_icon_preview(url)

    def _load_icon_preview(self, url):
        if not url.strip():
            self._load_default_icon()
            return
        try:
            self.icon_preview.setText(tr('status.loading'))
            from PyQt6.QtCore import QThread, pyqtSignal

            class IconLoader(QThread):
                loaded, failed = (pyqtSignal(QPixmap, str), pyqtSignal(str))

                def __init__(self, url):
                    super().__init__()
                    self.url = url

                def run(self):
                    try:
                        import requests
                        response = requests.get(self.url, timeout=10)
                        response.raise_for_status()
                        pixmap = QPixmap()
                        if pixmap.loadFromData(response.content):
                            self.loaded.emit(pixmap, self.url)
                        else:
                            self.failed.emit(self.url)
                    except Exception:
                        self.failed.emit(self.url)
            self.icon_loader = IconLoader(url)
            self.icon_loader.loaded.connect(lambda pm, u: self._on_icon_loaded(pm) if u == self.current_icon_url else None)
            self.icon_loader.failed.connect(lambda u: self._on_icon_load_failed(u) if u == self.current_icon_url else None)
            self.icon_loader.start()
        except Exception:
            self._load_default_icon()

    def _on_icon_loaded(self, pixmap):
        try:
            self.icon_preview.setProperty('isDefaultIcon', False)
        except Exception:
            pass
        size = min(pixmap.width(), pixmap.height())
        cropped = pixmap.copy((pixmap.width() - size) // 2, (pixmap.height() - size) // 2, size, size)
        self.icon_preview.setPixmap(cropped.scaled(64, 64, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _on_icon_load_failed(self, url: str):
        self._load_default_icon()
        if self.is_public and hasattr(self, 'icon_edit'):
            self.icon_edit.setProperty('isValid', False)
        if self.is_public and hasattr(self, 'icon_title_label'):
            base_title = tr('files.icon_label')
            error_text = tr('errors.not_an_image')
            self.icon_title_label.setText(f"{base_title}<span style='color: #FF4444;'> ({error_text})</span>")

    def _load_default_icon(self):
        try:
            logo_path = resource_path('icons/icon.ico')
            if os.path.exists(logo_path) and (not (pixmap := QPixmap(logo_path)).isNull()):
                self.icon_preview.setPixmap(pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.icon_preview.setProperty('isDefaultIcon', True)
                return
        except Exception as e:
            logging.warning(f'Load default icon preview failed: {e}')
        self.icon_preview.setText(tr('status.deltarune_logo'))
        try:
            self.icon_preview.setProperty('isDefaultIcon', True)
        except Exception:
            pass

    def _browse_local_icon(self):
        file_path, _ = QFileDialog.getOpenFileName(self, tr('ui.select_icon_file'), '', get_file_filter('image_files'))
        if file_path:
            self.icon_edit.setText(file_path)
            self._load_local_icon_preview(file_path)

    def _load_local_icon_preview(self, file_path):
        try:
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                try:
                    self.icon_preview.setProperty('isDefaultIcon', False)
                except Exception:
                    pass
                size = min(pixmap.width(), pixmap.height())
                cropped = pixmap.copy((pixmap.width() - size) // 2, (pixmap.height() - size) // 2, size, size)
                self.icon_preview.setPixmap(cropped.scaled(64, 64, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))
            else:
                self.icon_preview.setText(tr('status.loading_error'))
        except Exception:
            self.icon_preview.setText(tr('status.loading_error'))

    def _show_verification_details(self):
        details_url = 'https://example.com/verification-details'
        webbrowser.open(details_url)

    def _toggle_mod_visibility(self):
        if not hasattr(self, 'mod_key') or not self.mod_key:
            QMessageBox.critical(self, tr('dialogs.error'), tr('dialogs.mod_key_error'))
            return
        current_hidden = self.mod_data.get('hide_mod', False)
        new_state = not current_hidden
        try:
            import requests
            from config.constants import CLOUD_FUNCTIONS_BASE_URL
            change = {'hide_mod': new_state}
            resp = requests.post(f'{CLOUD_FUNCTIONS_BASE_URL}/submitModChange', json={'modData': change, 'hashedKey': self.mod_key}, timeout=10)
            resp.raise_for_status()
            QMessageBox.information(self, tr('dialogs.request_sent_title'), tr('errors.request_sent_message'))
        except Exception as e:
            QMessageBox.critical(self, tr('dialogs.update_error'), tr('dialogs.failed_to_update_mod', error=str(e)))

    def _save_mod(self):
        if not self._validate_fields():
            return
        if not self._revalidate_on_save():
            return
        if self.is_creating:
            if self.is_public:
                self._save_public_mod()
            else:
                self._save_local_mod()
        else:
            self._update_existing_mod()

    def _validate_fields(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, tr('dialogs.error'), tr('dialogs.mod_name_empty'))
            return False
        if self.is_public and (not self.author_edit.text().strip()):
            QMessageBox.warning(self, tr('dialogs.error'), tr('dialogs.mod_author_empty'))
            return False
        if len(self.version_edit.text().strip()) > 10:
            QMessageBox.warning(self, tr('dialogs.error'), tr('dialogs.mod_version_too_long'))
            return False
        if self.is_public:
            pass
        if hasattr(self, 'tag_other') and (not any([self.tag_translation.isChecked(), self.tag_customization.isChecked(), self.tag_gameplay.isChecked(), self.tag_other.isChecked()])):
            self.tag_other.setChecked(True)
        return self._validate_file_data()

    def _validate_file_data(self):
        return self._validate_public_file_data() if self.is_public else self._validate_local_file_data()

    def _revalidate_on_save(self) -> bool:
        try:
            import re
            import requests
            from urllib.parse import unquote
            if self.is_public and hasattr(self, 'icon_edit') and hasattr(self, 'icon_preview'):
                icon_url = self.icon_edit.text().strip()
                is_default = bool(self.icon_preview.property('isDefaultIcon'))
                if icon_url and is_default:
                    QMessageBox.warning(self, tr('dialogs.validation_error'), tr('errors.icon_invalid'))
                    return False
                desc_url = self.description_url_edit.text().strip()
                if desc_url and (not re.match('^https?://.+\\.(md|txt)(\\?.*)?$', desc_url, re.IGNORECASE)):
                    try:
                        h = requests.head(desc_url, headers={'User-Agent': 'Mozilla/5.0'}, allow_redirects=True, timeout=6)
                        ct = (h.headers.get('Content-Type') or '').lower()
                        if not (ct.startswith('text/') or 'markdown' in ct):
                            raise ValueError('not text')
                    except Exception:
                        QMessageBox.warning(self, tr('dialogs.validation_error'), tr('errors.description_md_txt_required'))
                        return False
                for i in range(self.file_tabs.count()):
                    tab = self.file_tabs.widget(i)
                    if tab is None:
                        continue
                    layout = tab.layout() if hasattr(tab, 'layout') else None
                    if layout is None:
                        continue
                    for j in range(layout.count()):
                        item = layout.itemAt(j)
                        w = item.widget() if item and item.widget() else None
                        if w is None or not hasattr(w, 'layout'):
                            continue
                        frame_layout = w.layout() if hasattr(w, 'layout') else None
                        if frame_layout is None:
                            continue
                        title_item = frame_layout.itemAt(0)
                        title_label = title_item.widget() if title_item and title_item.widget() else None
                        if not isinstance(title_label, QLabel):
                            continue
                        url_edit = version_edit = None
                        for k in range(frame_layout.count()):
                            sub = frame_layout.itemAt(k)
                            subw = sub.widget() if sub else None
                            if isinstance(subw, QLineEdit):
                                prev_item = frame_layout.itemAt(k - 1) if k > 0 else None
                                prevw = prev_item.widget() if prev_item and prev_item.widget() else None
                                if isinstance(prevw, QLabel):
                                    ftype = detect_field_type_by_text(prevw.text())
                                    if ftype == 'file_path':
                                        url_edit = subw
                                    elif ftype == 'version':
                                        version_edit = subw
                        if not url_edit:
                            continue
                        url = url_edit.text().strip()
                        if not url:
                            continue
                        label_ftype = title_label.property('file_type') if hasattr(title_label, 'property') else None
                        is_patch = label_ftype == 'patch'
                        is_extra = label_ftype == 'extra'
                        headers = {'User-Agent': 'Mozilla/5.0'}
                        content_type = ''
                        first_bytes = b''
                        ok = False
                        try:
                            h = requests.head(url, headers=headers, allow_redirects=True, timeout=8)
                            if h.status_code in (200, 206, 301, 302, 303, 307, 308):
                                ok = True
                                ct = h.headers.get('Content-Type') or h.headers.get('content-type') or ''
                                content_type = ct.lower()
                                content_disp = h.headers.get('content-disposition', '')
                            else:
                                content_disp = ''
                        except Exception:
                            ok, content_disp = (False, '')
                        if not ok:
                            try:
                                g = requests.get(url, headers=headers, allow_redirects=True, stream=True, timeout=12)
                                g.raise_for_status()
                                ct = g.headers.get('Content-Type') or g.headers.get('content-type') or ''
                                content_type = ct.lower()
                                content_disp = g.headers.get('content-disposition', '')
                                try:
                                    first_bytes = next(g.iter_content(chunk_size=16), b'') or b''
                                except Exception:
                                    first_bytes = b''
                                ok = True
                            except Exception:
                                ok = False
                        if not ok:
                            QMessageBox.warning(self, tr('dialogs.validation_error'), tr('dialogs.validation_url_error', url=url))
                            return False

                        def _infer_filename(u: str, content_disp_hdr: str) -> str:
                            try:
                                cd = content_disp_hdr.lower()
                                if 'filename=' in cd:
                                    val = cd.split('filename=')[-1].strip().strip('"')
                                    return unquote(val)
                            except Exception:
                                pass
                            try:
                                from urllib.parse import urlparse
                                p = urlparse(u)
                                return os.path.basename(p.path)
                            except Exception:
                                return ''
                        fname = _infer_filename(url, content_disp)
                        fext = (os.path.splitext(fname)[1] or '').lower()
                        if is_patch:
                            xdelta_by_sig = first_bytes.startswith(b'VCD')
                            xdelta_by_ct = any((x in content_type for x in ['xdelta', 'vcdiff'])) or content_type == 'application/octet-stream'
                            xdelta_by_ext = fext == '.xdelta'
                            if not (xdelta_by_sig or xdelta_by_ct or xdelta_by_ext):
                                QMessageBox.warning(self, tr('dialogs.validation_error'), '.xdelta ' + tr('errors.not_a_valid_file'))
                                return False
                        elif is_extra:
                            sig_ok = first_bytes.startswith(b'PK\x03\x04') or first_bytes.startswith(b'Rar!') or first_bytes.startswith(b"7z\xbc\xaf'\x1c")
                            by_ext = fext in ['.zip', '.rar', '.7z']
                            by_ct = any((x in content_type for x in ['zip', 'x-zip', 'rar', '7z'])) or content_type == 'application/octet-stream'
                            if not (sig_ok or by_ext or by_ct):
                                pass
                        else:
                            looks_like_data = any((x in fext for x in ['.win', '.ios', '.data']))
                            if 'text/html' in content_type and (not looks_like_data):
                                QMessageBox.warning(self, tr('dialogs.validation_error'), tr('errors.not_a_valid_file'))
                                return False
                        if version_edit and (not version_edit.text().strip()):
                            QMessageBox.warning(self, tr('dialogs.validation_error'), tr('dialogs.tab_no_version', tab_name=self.file_tabs.tabText(i)))
                            return False
            elif not self._validate_local_file_data():
                return False
            return True
        except Exception:
            return False

    def _validate_public_file_data(self):
        import re
        url_pattern, version_pattern, has_any_files = (re.compile('^https?://.*', re.IGNORECASE), re.compile('^\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}$'), False)
        for i in range(self.file_tabs.count()):
            tab, tab_name = (self.file_tabs.widget(i), self.file_tabs.tabText(i))
            if not tab or not (layout := tab.layout()):
                continue
            for j in range(layout.count()):
                if not (item := layout.itemAt(j)) or not (widget := item.widget()) or (not hasattr(widget, 'layout')) or (not (frame_layout := widget.layout())):
                    continue
                title_label = None
                for k in range(frame_layout.count()):
                    item_k = frame_layout.itemAt(k)
                    w_k = item_k.widget() if item_k else None
                    if isinstance(w_k, QLabel):
                        ftype = w_k.property('file_type') if hasattr(w_k, 'property') else None
                        if ftype in ('data', 'patch', 'extra'):
                            title_label = w_k
                            break
                if not title_label:
                    title_label = next((w for k in range(frame_layout.count()) if (it := frame_layout.itemAt(k)) and (w := it.widget()) and isinstance(w, QLabel) and any((isinstance(w.text(), str) and w.text().startswith(prefix) for prefix in ['DATA', 'PATCH', 'XDELTA', tr('files.extra_files')]))), None)
                if not title_label:
                    continue
                url_edit = version_edit = None
                for k in range(frame_layout.count()):
                    if not (frame_item := frame_layout.itemAt(k)) or not (frame_widget := frame_item.widget()) or (not isinstance(frame_widget, QLineEdit)):
                        continue
                    if k > 0 and (prev_item := frame_layout.itemAt(k - 1)) and (prev_widget := prev_item.widget()) and isinstance(prev_widget, QLabel):
                        field_type = detect_field_type_by_text(prev_widget.text())
                        if field_type == 'file_path':
                            url_edit = frame_widget
                        elif field_type == 'version':
                            version_edit = frame_widget
                if url_edit and version_edit:
                    url_text, version_text = (url_edit.text().strip(), version_edit.text().strip())
                    if url_text or version_text:
                        has_any_files = True
                        if not url_text:
                            QMessageBox.warning(self, tr('dialogs.validation_error'), tr('dialogs.tab_no_file_url', tab_name=tab_name))
                            return False
                        if not url_pattern.match(url_text):
                            QMessageBox.warning(self, tr('dialogs.validation_error'), tr('dialogs.tab_invalid_url', tab_name=tab_name))
                            return False
                        try:
                            ok = False
                            headers = {'User-Agent': 'Mozilla/5.0'}
                            try:
                                h = requests.head(url_text, headers=headers, allow_redirects=True, timeout=7)
                                if h.status_code in (200, 206):
                                    ok = True
                                elif h.status_code in (301, 302, 303, 307, 308):
                                    ok = True
                            except Exception:
                                pass
                            if not ok:
                                try:
                                    g = requests.get(url_text, headers=headers, allow_redirects=True, stream=True, timeout=10)
                                    if g.status_code in (200, 206):
                                        next(g.iter_content(chunk_size=1), None)
                                        ok = True
                                except Exception:
                                    ok = False
                            if not ok:
                                QMessageBox.warning(self, tr('dialogs.validation_error'), tr('dialogs.tab_file_unavailable', tab_name=tab_name, url=url_text))
                                return False
                        except Exception:
                            QMessageBox.warning(self, tr('dialogs.validation_error'), tr('dialogs.tab_file_unavailable', tab_name=tab_name, url=url_text))
                            return False
                        if not version_text:
                            QMessageBox.warning(self, tr('dialogs.validation_error'), tr('dialogs.tab_no_version', tab_name=tab_name))
                            return False
                        if not version_pattern.match(version_text):
                            QMessageBox.warning(self, tr('dialogs.validation_error'), tr('dialogs.tab_invalid_version', tab_name=tab_name))
                            return False
        if not has_any_files:
            QMessageBox.warning(self, tr('dialogs.validation_error'), tr('dialogs.mod_must_have_files'))
            return False
        return True

    def _validate_local_file_data(self):
        for i in range(self.file_tabs.count()):
            tab, tab_name = (self.file_tabs.widget(i), self.file_tabs.tabText(i))
            if not tab or not (layout := tab.layout()):
                continue
            for j in range(layout.count()):
                if not (item := layout.itemAt(j)) or not (widget := item.widget()) or (not hasattr(widget, 'layout')) or (not (frame_layout := widget.layout())):
                    continue
                if not (frame_data := self._extract_local_frame_data(frame_layout)):
                    continue
                if (path := frame_data.get('path')) and (not os.path.exists(path)):
                    QMessageBox.warning(self, tr('dialogs.validation_error'), tr('dialogs.tab_file_not_found', tab_name=tab_name, path=path))
                    return False
                for path in frame_data.get('paths', []):
                    if not os.path.exists(path):
                        QMessageBox.warning(self, tr('dialogs.validation_error'), tr('dialogs.tab_extra_file_not_found', tab_name=tab_name, path=path))
                        return False
        return True

    def _browse_for_local_file(self, path_edit: QLineEdit):
        is_patch = self.piracy_checkbox.isChecked()
        title, filters = (tr('ui.select_patch_file_xdelta'), get_file_filter('xdelta_files')) if is_patch else (tr('ui.select_data_file'), get_file_filter('data_files'))
        if not (file_path := QFileDialog.getOpenFileName(self, title, '', filters)[0]):
            return
        filename = os.path.basename(file_path).lower()
        try:
            with open(file_path, 'rb') as f:
                is_vcd = f.read(3) == b'VCD'
            if is_patch and (not filename.endswith('.xdelta') or not is_vcd):
                QMessageBox.warning(self, tr('dialogs.error'), tr('dialogs.invalid_xdelta_file'))
                return
            if not is_patch and is_vcd:
                QMessageBox.warning(self, tr('dialogs.error'), tr('dialogs.data_cannot_be_xdelta'))
                return
        except Exception as e:
            QMessageBox.warning(self, tr('dialogs.error'), tr('dialogs.file_read_error', error=str(e)))
            return
        path_edit.setText(file_path)

    def _show_file_info(self, tab_layout, title_text, url, version):
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.Box)
        layout = QVBoxLayout(frame)
        title = QLabel(title_text)
        title.setStyleSheet('font-weight: bold;')
        layout.addWidget(title)
        url_label = QLabel(f'URL: {url}')
        url_label.setStyleSheet('color: gray; font-size: 10px; word-wrap: true;')
        url_label.setWordWrap(True)
        layout.addWidget(url_label)
        version_label = QLabel(f"{tr('ui.version_colon')} {version}")
        version_label.setStyleSheet('color: gray; font-size: 10px;')
        layout.addWidget(version_label)
        tab_layout.insertWidget(tab_layout.count() - 1, frame)

    def _select_local_extra_files(self, tab, tab_layout):
        file_paths, _ = QFileDialog.getOpenFileNames(self, tr('ui.select_additional_files'), '', get_file_filter('extended_archives'))
        if file_paths:
            key_name, ok = QInputDialog.getText(self, tr('dialogs.file_group_name'), tr('dialogs.enter_file_group_key'))
            if not ok or not key_name.strip():
                return
            extra_frame = QFrame()
            extra_frame.setFrameStyle(QFrame.Shape.Box)
            extra_layout = QVBoxLayout(extra_frame)
            title = QLabel(tr('ui.extra_files_title', key_name=key_name))
            title.setStyleSheet('font-weight: bold;')
            title.setProperty('clean_key', key_name)
            extra_layout.addWidget(title)
            import os
            for file_path in file_paths:
                filename = os.path.basename(file_path)
                file_label = QLabel(f'• {filename}')
                file_label.setStyleSheet('color: gray; font-size: 10px;')
                extra_layout.addWidget(file_label)
                path_edit = QLineEdit()
                path_edit.setText(file_path)
                path_edit.hide()
                path_edit.setProperty('file_path', True)
                path_edit.setProperty('extra_key', key_name)
                extra_layout.addWidget(path_edit)
            delete_button = QPushButton(tr('ui.delete_button'))
            delete_button.clicked.connect(lambda: self._remove_local_extra_files(tab_layout, extra_frame))
            extra_layout.addWidget(delete_button)
            tab_layout.insertWidget(tab_layout.count() - 1, extra_frame)

    def _remove_local_data_file(self, tab, tab_layout, data_frame):
        data_frame.hide()
        tab_layout.removeWidget(data_frame)
        data_frame.deleteLater()

    def _remove_local_extra_files(self, tab_layout, extra_frame):
        extra_frame.hide()
        tab_layout.removeWidget(extra_frame)
        extra_frame.deleteLater()

    def _collect_files_from_tabs(self):
        files_data = {}
        modtype = self.modtype_combo.currentData()
        if self.is_public:
            if modtype == 'deltarunedemo':
                tab_keys = ['demo']
            elif modtype == 'undertale':
                tab_keys = ['undertale']
            else:
                tab_keys = ['menu', 'chapter_1', 'chapter_2', 'chapter_3', 'chapter_4']
        elif modtype == 'deltarunedemo':
            tab_keys = ['demo']
        elif modtype == 'undertale':
            tab_keys = ['undertale']
        else:
            tab_keys = ['0', '1', '2', '3', '4']
        for tab_index in range(self.file_tabs.count()):
            if tab_index >= len(tab_keys):
                continue
            tab_key = tab_keys[tab_index]
            tab = self.file_tabs.widget(tab_index)
            if not tab:
                continue
            layout = tab.layout()
            if not layout:
                continue
            tab_files = {}
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if not item or not item.widget():
                    continue
                widget = item.widget()
                if widget is None or not hasattr(widget, 'layout'):
                    continue
                frame_layout = widget.layout()
                if not frame_layout:
                    continue
                if self.is_public:
                    frame_data = self._extract_frame_data(frame_layout)
                    if frame_data:
                        if frame_data['type'] == 'data':
                            tab_files['data_file_url'] = frame_data['url']
                            tab_files['data_file_version'] = frame_data['version']
                        elif frame_data['type'] == 'extra':
                            if 'extra' not in tab_files:
                                tab_files['extra'] = {}
                            tab_files['extra'][frame_data['key']] = {'url': frame_data['url'], 'version': frame_data['version']}
                else:
                    local_data = self._extract_local_frame_data(frame_layout)
                    if not local_data:
                        continue
                    if local_data['type'] == 'data' and local_data.get('path'):
                        tab_files['data_file_url'] = local_data['path']
                        tab_files['data_file_version'] = local_data.get('version', '1.0.0')
                    elif local_data['type'] == 'extra' and local_data.get('paths'):
                        if 'extra_files' not in tab_files:
                            tab_files['extra_files'] = {}
                        tab_files['extra_files'][local_data['key']] = local_data['paths']
            if tab_files:
                files_data[tab_key] = tab_files
        return files_data

    def _extract_frame_data(self, frame_layout):
        title_label = None
        url_edit = None
        version_edit = None
        for i in range(frame_layout.count()):
            item = frame_layout.itemAt(i)
            if not item or not item.widget():
                continue
            w = item.widget()
            if isinstance(w, QLabel):
                ftype = w.property('file_type') if hasattr(w, 'property') else None
                if ftype in ('data', 'patch', 'extra'):
                    title_label = w
                    break
        if not title_label:
            for i in range(frame_layout.count()):
                item = frame_layout.itemAt(i)
                if not item or not item.widget():
                    continue
                w = item.widget()
                if isinstance(w, QLabel):
                    txt = w.text()
                    if isinstance(txt, str) and (txt.startswith('DATA') or txt.startswith('PATCH') or txt.startswith('XDELTA') or txt.startswith(tr('files.extra_files'))):
                        title_label = w
                        break
        for i in range(frame_layout.count()):
            item = frame_layout.itemAt(i)
            if not item or not item.widget():
                continue
            widget = item.widget()
            if isinstance(widget, QLineEdit):
                prev_item = frame_layout.itemAt(i - 1)
                if prev_item and prev_item.widget():
                    prev_widget = prev_item.widget()
                    if isinstance(prev_widget, QLabel):
                        field_type = detect_field_type_by_text(prev_widget.text())
                        if field_type == 'file_path':
                            url_edit = widget
                        elif field_type == 'version':
                            version_edit = widget
        if title_label and url_edit and version_edit:
            url_text = url_edit.text().strip()
            version_text = version_edit.text().strip()
            if url_text and version_text:
                frame_data = {'url': url_text, 'version': version_text}
                ftype = title_label.property('file_type') if hasattr(title_label, 'property') else None
                if ftype in ('data', 'patch'):
                    frame_data['type'] = 'data'
                elif ftype == 'extra':
                    frame_data['type'] = 'extra'
                    frame_data['key'] = title_label.property('clean_key') or 'extra'
                else:
                    t = title_label.text()
                    if t.startswith('DATA') or t.startswith('PATCH') or t.startswith('XDELTA'):
                        frame_data['type'] = 'data'
                    elif t.startswith(tr('files.extra_files')):
                        key = title_label.property('clean_key') or t.replace(tr('files.extra_files'), '').strip()
                        frame_data['type'] = 'extra'
                        frame_data['key'] = key
                return frame_data
        return None

    def _extract_local_frame_data(self, frame_layout):
        title_widget = frame_layout.itemAt(0).widget()
        if not isinstance(title_widget, QLabel):
            return None
        title_text = title_widget.text()
        if 'DATA' in title_text or 'PATCH' in title_text:
            frame_type = 'data'
        elif detect_field_type_by_text(title_text) == 'extra_files':
            frame_type = 'extra'
        else:
            return None

        def _find_widget_by_property(layout, widget_type, prop_name, prop_value=True):
            for i in range(layout.count()):
                if not (item := layout.itemAt(i)):
                    continue
                if (widget := item.widget()) and isinstance(widget, widget_type) and (widget.property(prop_name) == prop_value):
                    return widget
                if (nested_layout := item.layout()):
                    if (result := _find_widget_by_property(nested_layout, widget_type, prop_name, prop_value)):
                        return result
            return None
        if frame_type == 'data':
            if (path_edit := _find_widget_by_property(frame_layout, QLineEdit, 'is_local_path')) and path_edit.text():
                return {'type': 'data', 'path': path_edit.text()}
        elif frame_type == 'extra':
            if (extra_edit := _find_widget_by_property(frame_layout, QLineEdit, 'is_local_extra_path')) and extra_edit.text():
                key = extra_edit.property('extra_key') or 'extra_files'
                return {'type': 'extra', 'key': key, 'paths': [extra_edit.text()]}
            if (list_widget := frame_layout.findChild(QListWidget)) and list_widget.property('is_local_extra_list'):
                key = list_widget.property('extra_key')
                paths = [list_widget.item(i).text() for i in range(list_widget.count())]
                if paths:
                    return {'type': 'extra', 'key': key, 'paths': paths}
        return None

    def _collect_mod_data(self):
        tags = []
        if self.tag_translation.isChecked():
            tags.append('translation')
        if self.tag_customization.isChecked():
            tags.append('customization')
        if self.tag_gameplay.isChecked():
            tags.append('gameplay')
        if self.tag_other.isChecked():
            tags.append('other')
        files_data = self._collect_files_from_tabs()
        author = self.author_edit.text().strip()
        if not self.is_public and (not author):
            author = tr('defaults.local_author')
        version = self.version_edit.text().strip() or '1.0.0'
        tagline = self.tagline_edit.text().strip() or tr('defaults.no_short_description')
        return {'name': self.name_edit.text().strip(), 'version': version, 'author': author, 'tagline': tagline, 'description_url': self.description_url_edit.text().strip(), 'icon_url': self.icon_edit.text().strip(), 'tags': tags, 'hide_mod': False, 'is_xdelta': self.piracy_checkbox.isChecked(), 'modtype': self.modtype_combo.currentData() or 'deltarune', 'game_version': self.game_version_combo.currentText() if self.is_public else self.game_version_edit.text().strip() or '1.04', 'files': files_data, 'screenshots_url': getattr(self, 'screenshots_urls', [])}

    def _save_public_mod(self):
        QMessageBox.information(self, tr('errors.save_secret_key_title'), tr('dialogs.save_secret_key_instruction'))
        secret_key = generate_secret_key()
        hashed_key = hash_secret_key(secret_key)
        suggested_filename = f'{sanitize_filename(self.name_edit.text())}_key.txt'
        key_file_path, _ = QFileDialog.getSaveFileName(self, tr('dialogs.save_mod_secret_key'), os.path.join(os.path.expanduser('~'), suggested_filename), get_file_filter('text_files'))
        if not key_file_path:
            QMessageBox.warning(self, tr('dialogs.mod_creation_cancelled'), tr('dialogs.key_required_for_creation'))
            return
        try:
            mod_data = self._collect_mod_data()
            from utils.file_utils import format_timestamp
            timestamp = format_timestamp()
            mod_data.update({'status': 'pending', 'downloads': 0, 'is_verified': False, 'submission_date': timestamp, 'created_date': timestamp, 'last_updated': timestamp})
            import requests
            from config.constants import CLOUD_FUNCTIONS_BASE_URL
            functions_url = f'{CLOUD_FUNCTIONS_BASE_URL}/submitNewMod'
            response = requests.post(functions_url, json={'modData': mod_data, 'hashedKey': hashed_key}, timeout=10)
            response.raise_for_status()
            try:
                with open(key_file_path, 'w', encoding='utf-8') as f:
                    f.write(f"{tr('ui.secret_key_colon')} {secret_key}\n{tr('ui.mod_name_colon')} {self.name_edit.text()}\n{tr('ui.creation_date_colon')} {format_timestamp()}\n\n{tr('ui.secret_key_important')}\n")
                QMessageBox.information(self, tr('dialogs.mod_submitted'), tr('errors.mod_submitted_success', key_file_path=key_file_path))
                self._open_file_directory(key_file_path)
            except Exception:
                QMessageBox.warning(self, tr('errors.mod_sent_key_error'), tr('errors.mod_submitted_key_save_failed', secret_key=secret_key))
            self.accept()
        except Exception as e:
            error_msg = tr('errors.mod_submission_failed', error_type=type(e).__name__)
            if '400' in str(e):
                error_msg = tr('errors.validation_data_error')
            elif 'KeyError' in str(e):
                error_msg = tr('errors.data_structure_error')
            elif 'TypeError' in str(e):
                error_msg = tr('errors.data_types_error')
            QMessageBox.critical(self, tr('errors.submission_error_title'), error_msg)

    def _open_file_directory(self, file_path):
        try:
            key_dir = os.path.dirname(os.path.abspath(file_path))
            system = platform.system()
            if system == 'Windows':
                subprocess.run(['explorer', '/select,', os.path.abspath(file_path)], check=False)
            elif system == 'Darwin':
                subprocess.run(['open', '-R', os.path.abspath(file_path)], check=False)
            else:
                subprocess.run(['xdg-open', key_dir], check=False)
        except Exception:
            try:
                key_dir = os.path.dirname(os.path.abspath(file_path))
                if system == 'Windows':
                    os.startfile(key_dir)
                elif system == 'Darwin':
                    subprocess.run(['open', key_dir], check=False)
                else:
                    subprocess.run(['xdg-open', key_dir], check=False)
            except Exception:
                pass

    def _save_local_mod(self):
        mod_data = self._collect_mod_data()
        mod_key = f'local_{uuid.uuid4().hex[:12]}'
        from utils.file_utils import get_unique_mod_dir
        unique_mod_folder = get_unique_mod_dir(self.parent_app.mods_dir, mod_data['name'])
        mod_dir = os.path.join(self.parent_app.mods_dir, unique_mod_folder)
        try:
            os.makedirs(mod_dir)
            icon_path = self.icon_edit.text().strip()
            if icon_path and os.path.exists(icon_path):
                icon_filename = os.path.basename(icon_path)
                shutil.copy2(icon_path, os.path.join(mod_dir, icon_filename))
                mod_data['icon_url'] = icon_filename
            local_files = {}
            for file_key, file_data in mod_data.get('files', {}).items():
                file_version_parts = []
                if file_key == 'demo':
                    file_folder = os.path.join(mod_dir, 'demo')
                elif file_key == 'undertale':
                    file_folder = os.path.join(mod_dir, 'undertale')
                elif file_key == '0':
                    file_folder = os.path.join(mod_dir, 'chapter_0')
                elif file_key in ['1', '2', '3', '4']:
                    file_folder = os.path.join(mod_dir, f'chapter_{file_key}')
                else:
                    continue
                os.makedirs(file_folder, exist_ok=True)
                data_path = file_data.get('data_file_url')
                if data_path and os.path.exists(data_path):
                    data_filename = os.path.basename(data_path)
                    destination = os.path.join(file_folder, data_filename)
                    shutil.copy2(data_path, destination)
                    file_data['data_file_url'] = data_filename
                    file_version_parts.append(file_data.get('data_file_version', '1.0.0'))
                extra_files = file_data.get('extra_files', {})
                for group_key, paths in extra_files.items():
                    copied_paths = []
                    for path in paths:
                        if os.path.exists(path):
                            filename = os.path.basename(path)
                            shutil.copy2(path, os.path.join(file_folder, filename))
                            copied_paths.append(filename)
                    extra_files[group_key] = copied_paths
                    file_version_parts.append('1.0.0')
                if file_version_parts:
                    local_files[file_key] = '|'.join(file_version_parts)
            files_data = {}
            for file_key, file_version in local_files.items():
                file_info = mod_data.get('files', {}).get(file_key, {})
                files_data[file_key] = {}
                if file_info.get('data_file_url'):
                    files_data[file_key]['data_file_url'] = os.path.basename(file_info['data_file_url'])
                    files_data[file_key]['data_file_version'] = file_info.get('data_file_version', '1.0.0')
                extra_files = file_info.get('extra_files', {})
                if extra_files:
                    files_data[file_key]['extra_files'] = {}
                    for group_key, paths in extra_files.items():
                        files_data[file_key]['extra_files'][group_key] = [os.path.basename(path) for path in paths]
            config_data = {'is_local_mod': True, 'mod_key': mod_key, 'created_date': format_timestamp(), 'is_available_on_server': False, 'name': mod_data.get('name', ''), 'version': mod_data.get('version', '1.0.0'), 'author': mod_data.get('author', ''), 'tagline': mod_data.get('tagline', tr('defaults.no_short_description')), 'game_version': mod_data.get('game_version', tr('defaults.not_specified')), 'modtype': mod_data.get('modtype', 'deltarune'), 'files': files_data}
            config_path = os.path.join(mod_dir, 'config.json')
            self.parent_app._write_json(config_path, config_data)
            self.parent_app._load_local_mods_from_folders()
            self.parent_app._update_installed_mods_display()
            QMessageBox.information(self, tr('dialogs.local_mod_created_title'), tr('dialogs.local_mod_created_message', mod_name=mod_data['name']))
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, tr('errors.mod_creation_error'), tr('errors.mod_creation_failed', error=str(e)))
            if os.path.exists(mod_dir):
                shutil.rmtree(mod_dir)

    def _update_existing_mod(self):
        if self.is_public:
            self._update_public_mod()
        else:
            self._update_local_mod()

    def _update_public_mod(self):
        if not self.is_public:
            QMessageBox.critical(self, tr('errors.error'), tr('errors.update_local_as_public'))
            return
        if not self._validate_fields():
            return
        if not self._has_real_changes():
            QMessageBox.warning(self, tr('errors.no_changes_title'), tr('errors.no_changes_to_update'))
            return
        updated_data = self._collect_mod_data()
        if hasattr(self, 'original_mod_data'):
            if self.original_mod_data.get('ban_status', False):
                QMessageBox.critical(self, tr('errors.error'), tr('dialogs.mod_blocked_title'))
                return
            updated_data['created_date'] = self.original_mod_data.get('created_date')
            updated_data['status'] = self.original_mod_data.get('status', 'pending')
            updated_data['downloads'] = self.original_mod_data.get('downloads', 0)
        from utils.file_utils import format_timestamp
        updated_data['last_updated'] = format_timestamp()
        try:
            import requests
            hashed_key = self.mod_key
            if not hashed_key:
                QMessageBox.critical(self, tr('errors.error'), tr('errors.mod_key_not_determined'))
                return
            try:
                from config.constants import CLOUD_FUNCTIONS_BASE_URL
                chk = requests.get(f'{CLOUD_FUNCTIONS_BASE_URL}/getModData?modId={hashed_key}', timeout=8)
                if chk.status_code == 200 and isinstance(chk.json(), dict):
                    server_data = chk.json()
                    is_verified = bool(server_data.get('is_verified', self.original_mod_data.get('is_verified', False)))
                    updated_data['downloads'] = server_data.get('downloads', updated_data.get('downloads', 0))
                    updated_data['created_date'] = server_data.get('created_date', updated_data.get('created_date'))
                    updated_data['status'] = server_data.get('status', updated_data.get('status', 'approved'))
                    updated_data['is_verified'] = server_data.get('is_verified', False)
                else:
                    is_verified = self.original_mod_data.get('is_verified', False)
                    updated_data['is_verified'] = is_verified
            except Exception:
                is_verified = self.original_mod_data.get('is_verified', False)
                updated_data['is_verified'] = is_verified
            from config.constants import CLOUD_FUNCTIONS_BASE_URL
            updated_data['change_type'] = 'update'
            updated_data['original_mod_key'] = hashed_key
            response = requests.post(f'{CLOUD_FUNCTIONS_BASE_URL}/submitModChange', json={'modData': updated_data, 'hashedKey': hashed_key}, timeout=10)
            response.raise_for_status()
            QMessageBox.information(self, tr('dialogs.request_sent_title'), tr('errors.request_sent_message'))
            self.accept()
        except Exception as e:
            error_msg = tr('errors.update_connection_error')
            if '400' in str(e):
                error_msg = tr('errors.validation_data_error')
            elif '401' in str(e) or '403' in str(e):
                error_msg = tr('errors.access_permission_error')
            elif '404' in str(e):
                error_msg = tr('errors.mod_not_found_server')
            QMessageBox.critical(self, tr('errors.update_error'), error_msg)

    def _has_real_changes(self) -> bool:
        if not hasattr(self, 'original_mod_data') or not self.original_mod_data:
            return True
        current_data, original_data = (self._collect_mod_data(), self.original_mod_data)
        fields_to_compare = ['name', 'version', 'author', 'tagline', 'description_url', 'icon_url', 'tags', 'is_xdelta', 'modtype', 'game_version', 'files', 'screenshots_url']
        return any((current_data.get(field) != original_data.get(field) for field in fields_to_compare))

    def _update_local_mod(self):
        updated_data = self._collect_mod_data()
        mod_key = self.mod_key
        if not mod_key:
            QMessageBox.critical(self, tr('errors.error'), tr('errors.mod_key_not_found_update'))
            return
        mod_folder_path = None
        if os.path.exists(self.parent_app.mods_dir):
            for folder_name in os.listdir(self.parent_app.mods_dir):
                folder_path = os.path.join(self.parent_app.mods_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                config_path = os.path.join(folder_path, 'config.json')
                if os.path.exists(config_path):
                    try:
                        config_data = self.parent_app._read_json(config_path)
                        if config_data and config_data.get('mod_key') == mod_key:
                            mod_folder_path = folder_path
                            break
                    except Exception:
                        continue
        if not mod_folder_path:
            QMessageBox.critical(self, tr('errors.error'), tr('errors.mod_folder_not_found_update'))
            return
        try:
            config_path = os.path.join(mod_folder_path, 'config.json')
            config_data = self.parent_app._read_json(config_path)
            for item in os.listdir(mod_folder_path):
                if item not in ['config.json'] and (not item.endswith(('.png', '.jpg', '.jpeg', '.gif'))):
                    item_path = os.path.join(mod_folder_path, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
            new_icon_path = self.icon_edit.text().strip()
            if new_icon_path and os.path.exists(new_icon_path):
                icon_filename = os.path.basename(new_icon_path)
                shutil.copy2(new_icon_path, os.path.join(mod_folder_path, icon_filename))
                updated_data['icon_url'] = icon_filename
            files_data = {}
            for file_key, file_data in updated_data.get('files', {}).items():
                if file_key == 'demo':
                    file_folder = os.path.join(mod_folder_path, 'demo')
                elif file_key == 'undertale':
                    file_folder = os.path.join(mod_folder_path, 'undertale')
                elif file_key == '0':
                    file_folder = os.path.join(mod_folder_path, 'chapter_0')
                elif file_key in ['1', '2', '3', '4']:
                    file_folder = os.path.join(mod_folder_path, f'chapter_{file_key}')
                else:
                    continue
                os.makedirs(file_folder, exist_ok=True)
                files_data[file_key] = {}
                data_path = file_data.get('data_file_url')
                if data_path and os.path.exists(data_path):
                    data_filename = os.path.basename(data_path)
                    shutil.copy2(data_path, os.path.join(file_folder, data_filename))
                    files_data[file_key]['data_file_url'] = data_filename
                    files_data[file_key]['data_file_version'] = file_data.get('data_file_version', '1.0.0')
                extra_files = file_data.get('extra_files', {})
                if extra_files:
                    files_data[file_key]['extra_files'] = {}
                    for group_key, paths in extra_files.items():
                        copied_paths = []
                        for path in paths:
                            if os.path.exists(path):
                                filename = os.path.basename(path)
                                shutil.copy2(path, os.path.join(file_folder, filename))
                                copied_paths.append(filename)
                        if copied_paths:
                            files_data[file_key]['extra_files'][group_key] = copied_paths
            config_data.update({'name': updated_data.get('name', ''), 'version': updated_data.get('version', '1.0.0'), 'author': updated_data.get('author', ''), 'tagline': updated_data.get('tagline', ''), 'game_version': updated_data.get('game_version', tr('defaults.not_specified')), 'modtype': updated_data.get('modtype', 'deltarune'), 'files': files_data})
            self.parent_app._write_json(config_path, config_data)
            self.parent_app._load_local_mods_from_folders()
            self.parent_app._update_installed_mods_display()
            QMessageBox.information(self, tr('dialogs.local_mod_updated_title'), tr('dialogs.local_mod_updated_message', mod_name=updated_data['name']))
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, tr('errors.update_error'), tr('errors.local_mod_update_failed', error=str(e)))

    def _delete_mod(self):
        if self.is_public:
            self._delete_public_mod()
        else:
            self._delete_local_mod()

    def _delete_public_mod(self):
        if QMessageBox.question(self, tr('dialogs.are_you_sure'), tr('dialogs.mod_deletion_confirmation')) != QMessageBox.StandardButton.Yes:
            return
        secret_key, ok = QInputDialog.getText(self, tr('dialogs.confirm_deletion'), tr('dialogs.enter_secret_key_mod'), QLineEdit.EchoMode.Password)
        if not ok or not secret_key.strip():
            return
        hashed_key = hash_secret_key(secret_key.strip())
        if self.mod_key and hashed_key != self.mod_key:
            QMessageBox.warning(self, tr('dialogs.invalid_key'), tr('dialogs.invalid_key_message'))
            return
        try:
            import requests
            from config.constants import CLOUD_FUNCTIONS_BASE_URL
            resp = requests.post(f'{CLOUD_FUNCTIONS_BASE_URL}/deletePublicMod', json={'hashedKey': hashed_key}, timeout=10)
            resp.raise_for_status()
            QMessageBox.information(self, tr('errors.mod_deleted_title'), tr('errors.mod_deleted_message'))
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, tr('errors.deletion_error'), tr('errors.mod_deletion_failed', error=str(e)))

    def _delete_local_mod(self):
        if QMessageBox.question(self, tr('dialogs.are_you_sure'), tr('dialogs.local_mod_deletion_confirmation')) != QMessageBox.StandardButton.Yes:
            return
        if not self.mod_key:
            QMessageBox.critical(self, tr('errors.error'), tr('errors.mod_key_not_found_for_deletion'))
            return
        try:
            mod_folder_path = None
            if os.path.exists(self.parent_app.mods_dir):
                for folder_name in os.listdir(self.parent_app.mods_dir):
                    folder_path = os.path.join(self.parent_app.mods_dir, folder_name)
                    if not os.path.isdir(folder_path):
                        continue
                    config_path = os.path.join(folder_path, 'config.json')
                    if os.path.exists(config_path):
                        try:
                            config_data = self.parent_app._read_json(config_path)
                            if config_data and config_data.get('mod_key') == self.mod_key:
                                mod_folder_path = folder_path
                                break
                        except Exception:
                            continue
            if not mod_folder_path:
                QMessageBox.critical(self, tr('errors.error'), tr('errors.mod_folder_not_found_for_deletion'))
                return
            shutil.rmtree(mod_folder_path)
            self.parent_app._load_local_mods_from_folders()
            self.parent_app._update_installed_mods_display()
            QMessageBox.information(self, tr('errors.local_mod_deleted_title'), tr('errors.local_mod_deleted_message'))
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, tr('errors.deletion_error'), tr('errors.local_mod_deletion_failed', error=str(e)))

    def populate_fields(self):
        if not self.mod_data:
            return
        actual_mod_data = self.mod_data
        if 'mod_data' in self.mod_data:
            actual_mod_data = self.mod_data['mod_data']
        self.name_edit.setText(actual_mod_data.get('name', ''))
        self.author_edit.setText(actual_mod_data.get('author', ''))
        self.tagline_edit.setText(actual_mod_data.get('tagline', ''))
        icon_value = actual_mod_data.get('icon_url', '')
        self.icon_edit.setText(icon_value)
        if icon_value:
            if self.is_public:
                self._on_icon_url_changed()
            else:
                self._load_local_icon_preview(icon_value)
        version = actual_mod_data.get('version', '')
        if isinstance(version, str) and '|' in version:
            version = version.split('|')[0]
        self.version_edit.setText(version)
        self.description_url_edit.setText(actual_mod_data.get('description_url', ''))
        modtype = actual_mod_data.get('modtype', 'deltarune')
        for i in range(self.modtype_combo.count()):
            if self.modtype_combo.itemData(i) == modtype:
                self.modtype_combo.setCurrentIndex(i)
                break
        self.piracy_checkbox.setChecked(actual_mod_data.get('is_xdelta', actual_mod_data.get('is_piracy_protected', False)))
        tags = actual_mod_data.get('tags', [])
        self.tag_translation.setChecked('translation' in tags)
        self.tag_customization.setChecked('customization' in tags)
        self.tag_gameplay.setChecked('gameplay' in tags)
        self.tag_other.setChecked('other' in tags)
        game_version = actual_mod_data.get('game_version', '')
        if self.is_public:
            index = self.game_version_combo.findText(game_version)
            if index >= 0:
                self.game_version_combo.setCurrentIndex(index)
        elif hasattr(self, 'game_version_edit'):
            self.game_version_edit.setText(game_version)
        self.screenshots_urls = actual_mod_data.get('screenshots_url', []) or []
        if not isinstance(self.screenshots_urls, list):
            self.screenshots_urls = []
        self._populate_file_tabs()
        if not self.is_creating and self.is_public and hasattr(self, 'hide_mod_button'):
            is_hidden = self.mod_data.get('hide_mod', False)
            self.hide_mod_button.setText(tr('errors.show_hide_mod') if is_hidden else tr('errors.hide_show_mod'))

    def _populate_file_tabs(self):
        if not self.mod_data:
            return
        actual_mod_data = self.mod_data
        if 'mod_data' in self.mod_data:
            actual_mod_data = self.mod_data['mod_data']
        files_data = actual_mod_data.get('files', {})
        chapters_data = actual_mod_data.get('chapters', {})
        if files_data:
            self._populate_from_files_structure(files_data)
        elif chapters_data:
            self._populate_from_files_structure(chapters_data)

    def _populate_from_files_structure(self, files_data):
        modtype = self.modtype_combo.currentData()
        if self.is_public:
            if modtype == 'deltarunedemo':
                file_keys = {'demo': 0}
            elif modtype == 'undertale':
                file_keys = {'undertale': 0}
            else:
                file_keys = {'menu': 0, 'chapter_1': 1, 'chapter_2': 2, 'chapter_3': 3, 'chapter_4': 4}
        elif modtype == 'deltarunedemo':
            file_keys = {'0': 0}
        elif modtype == 'undertale':
            file_keys = {'0': 0}
        else:
            file_keys = {'0': 0, '1': 1, '2': 2, '3': 3, '4': 4}
        for file_key, tab_index in file_keys.items():
            if file_key in files_data and tab_index < self.file_tabs.count():
                file_info = files_data[file_key]
                self._populate_tab_with_file_data(tab_index, file_info)

    def _populate_tab_with_file_data(self, tab_index, file_info):
        tab = self.file_tabs.widget(tab_index)
        if not tab:
            return
        layout = tab.layout()
        if not layout:
            return
        data_file_url = file_info.get('data_file_url')
        data_file_version = file_info.get('data_file_version')
        if data_file_url:
            if not self.is_public:
                self._create_file_frame(layout, 'data')
                self._fill_local_data_file_in_tab(tab, data_file_url, data_file_version)
            elif not self._has_data_file_in_tab(tab):
                self._add_data_file(tab, layout)
                self._fill_data_file_in_tab(tab, data_file_url, data_file_version)
        extra_files = file_info.get('extra', {})
        for extra_key, extra_data in extra_files.items():
            if isinstance(extra_data, dict):
                extra_url = extra_data.get('url')
                extra_version = extra_data.get('version')
                if extra_url:
                    if self.is_public:
                        self._add_extra_files_with_data(tab, layout, extra_key, extra_url, extra_version)
        extra_files_local = file_info.get('extra_files', {})
        for extra_key, filenames in extra_files_local.items():
            if filenames:
                if not self.is_public:
                    self._add_local_extra_files_frame_with_data(tab, layout, extra_key, filenames)

    def _has_data_file_in_tab(self, tab):
        layout = tab.layout()
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if hasattr(widget, 'layout'):
                    frame_layout = widget.layout()
                    for j in range(frame_layout.count()):
                        frame_item = frame_layout.itemAt(j)
                        if frame_item and frame_item.widget():
                            frame_widget = frame_item.widget()
                            if isinstance(frame_widget, QLabel) and (frame_widget.text().startswith('DATA') or frame_widget.text().startswith('PATCH')):
                                return True
        return False

    def _fill_data_file_in_tab(self, tab, url, version):
        layout = tab.layout()
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if hasattr(widget, 'layout'):
                    frame_layout = widget.layout()
                    url_edit = None
                    version_edit = None
                    for j in range(frame_layout.count()):
                        frame_item = frame_layout.itemAt(j)
                        if frame_item and frame_item.widget():
                            frame_widget = frame_item.widget()
                            if isinstance(frame_widget, QLineEdit):
                                prev_item = frame_layout.itemAt(j - 1)
                                if prev_item and prev_item.widget():
                                    prev_widget = prev_item.widget()
                                    if isinstance(prev_widget, QLabel):
                                        field_type = detect_field_type_by_text(prev_widget.text())
                                        if field_type == 'file_path':
                                            url_edit = frame_widget
                                        elif field_type == 'version':
                                            version_edit = frame_widget
                    if url_edit and version_edit:
                        url_edit.setText(url)
                        version_edit.setText(version)
                        return