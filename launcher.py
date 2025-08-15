import base64, json, os, platform, re, shutil, sys, tempfile, threading, time, uuid, ctypes, subprocess, webbrowser, rarfile, textwrap, argparse, hashlib
from typing import Callable, Optional, List
from helpers import *
from packaging import version as version_parser
from PyQt6 import sip
from PyQt6.QtCore import Qt, QEvent, QEventLoop, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QImage, QMovie, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget, QHBoxLayout, QSizePolicy, QInputDialog, QColorDialog, QListWidget, QLayoutItem, QScrollArea, QSlider
# QtMultimedia removed; using playsound3 for audio
from localization import get_localization_manager, tr
import logging

# Centralized logging to file in config dir; truncate on each launch
try:
    cfg_dir = get_app_support_path()
    os.makedirs(cfg_dir, exist_ok=True)
    LOG_PATH = os.path.join(cfg_dir, "deltahub.log.txt")
    with open(LOG_PATH, 'w', encoding='utf-8') as _f:
        _f.write("")
    logging.basicConfig(
        filename=LOG_PATH,
        filemode='a',
        encoding='utf-8',
        level=logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s'
    )
    sys.stdout = open(LOG_PATH, 'a', encoding='utf-8')
    sys.stderr = sys.stdout
except Exception:
    pass

# ============================================================================
#                               UTILITY FUNCTIONS
# ============================================================================

def load_mod_icon_universal(icon_label, mod_data, size=80):
    """Универсальная функция для загрузки иконки мода (без блокировки UI)."""
    # Сначала всегда устанавливаем иконку по умолчанию
    assets_icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.ico")
    fallback_icon_path = os.path.join(os.path.dirname(__file__), "icon.ico")
    default_pixmap = None

    for default_icon_path in (assets_icon_path, fallback_icon_path):
        if os.path.exists(default_icon_path):
            try:
                default_pixmap = QPixmap(default_icon_path)
                if not default_pixmap.isNull():
                    icon_size = min(default_pixmap.width(), default_pixmap.height())
                    if icon_size > 0:
                        cropped = default_pixmap.copy((default_pixmap.width() - icon_size) // 2, (default_pixmap.height() - icon_size) // 2, icon_size, icon_size)
                        default_pixmap = cropped.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    else:
                        default_pixmap = default_pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    break
            except Exception:
                default_pixmap = None

    if default_pixmap is None:
        default_pixmap = QPixmap(size, size)
        default_pixmap.fill(QColor("#333"))

    icon_label.setPixmap(default_pixmap)

    # Пытаемся загрузить иконку мода (локальный путь или URL) — сеть в QThread
    try:
        pixmap = None
        if getattr(mod_data, 'icon_path', None) and os.path.exists(mod_data.icon_path):
            pixmap = QPixmap(mod_data.icon_path)
            if not pixmap.isNull():
                icon_size = min(pixmap.width(), pixmap.height())
                cropped = pixmap.copy((pixmap.width() - icon_size) // 2, (pixmap.height() - icon_size) // 2, icon_size, icon_size)
                icon_label.setPixmap(cropped.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))
                return
        elif getattr(mod_data, 'icon_url', None):
            icon_url = mod_data.icon_url
            if isinstance(icon_url, str) and icon_url.startswith(('http://', 'https://')):
                from PyQt6.QtCore import QThread, pyqtSignal
                class _IconLoader(QThread):
                    loaded = pyqtSignal(object)
                    failed = pyqtSignal(str)
                    def __init__(self, url):
                        super().__init__(); self.url = url
                    def run(self):
                        try:
                            import requests
                            resp = requests.get(self.url, timeout=8)
                            resp.raise_for_status()
                            img = QImage()
                            if img.loadFromData(resp.content):
                                self.loaded.emit(QPixmap.fromImage(img))
                            else:
                                self.failed.emit('decode')
                        except requests.RequestException as e:
                            self.failed.emit(str(e))

                worker = _IconLoader(icon_url)
                # Привязываем к label, чтобы не был собран GC
                setattr(icon_label, '_icon_loader', worker)
                # Безопасно останавливаем поток при уничтожении label
                try:
                    icon_label.destroyed.connect(lambda *_: (worker.requestInterruption(), worker.quit(), worker.wait(1000)))
                except Exception:
                    pass
                def _on_loaded(pm: QPixmap):
                    try:
                        if pm and not pm.isNull():
                            icon_size = min(pm.width(), pm.height())
                            cropped = pm.copy((pm.width() - icon_size) // 2, (pm.height() - icon_size) // 2, icon_size, icon_size)
                            icon_label.setPixmap(cropped.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))
                    except Exception as e:
                        print(f"Error applying mod icon: {e}")
                def _on_failed(err: str):
                    # Логируем, но не тревожим UI
                    print(f"Icon load failed: {err}")
                worker.loaded.connect(_on_loaded)
                worker.failed.connect(_on_failed)
                worker.start()
    except Exception as e:
        print(f"Error loading mod icon: {e}")

def update_mod_widget_style(widget, frame_selector, parent_app=None):
    """Универсальная функция для обновления стилей виджетов модов"""
    if parent_app and hasattr(parent_app, 'local_config'):
        plaque_bg_color = get_theme_color(parent_app.local_config, "button", "black")
        border_color = get_theme_color(parent_app.local_config, "border", "#fff")
        hover_border_color = get_theme_color(parent_app.local_config, "button_hover", "#fff")
        version_text_color = get_theme_color(parent_app.local_config, "version_text", "rgba(255, 255, 255, 178)")
    else:
        # Fallback values
        plaque_bg_color = "black"
        border_color = "#fff"
        hover_border_color = "#fff"
        version_text_color = "rgba(255, 255, 255, 178)"

    border_width = "3px" if getattr(widget, 'is_selected', False) else "1px"
    current_border_color = hover_border_color if getattr(widget, 'is_selected', False) else border_color

    widget.setStyleSheet(f"""
        QFrame#{frame_selector} {{
            background-color: {plaque_bg_color};
            border: {border_width} solid {current_border_color};
        }}
        QFrame#{frame_selector}:hover {{
            border-color: {hover_border_color};
        }}
        QLabel#modIcon {{
            border: 2px solid {border_color};
        }}
        QLabel#versionLabel {{
            color: {version_text_color};
        }}
        QLabel#secondaryText {{
            color: {version_text_color};
            font-size: 12px;
        }}
        QLabel#primaryText {{
            color: white;
            font-size: 12px;
        }}
        QPushButton#plaqueButton, QPushButton#plaqueButtonInstall {{
            min-width: 110px;
            max-width: 110px;
            min-height: 35px;
            max-height: 35px;
            font-size: 15px;
            padding: 1px;
        }}
        QPushButton#plaqueButtonInstall {{
            background-color: #4CAF50;
            font-weight: bold;
        }}
        QPushButton#plaqueButtonInstall:hover {{
            background-color: #5cb85c;
        }}
    """)

def show_empty_message_in_layout(layout, text, local_config=None, font_size=16):
    """Универсальная функция для показа сообщения о пустом списке"""
    empty_text_color = "rgba(255, 255, 255, 178)"
    if local_config:
        empty_text_color = get_theme_color(local_config, "version_text", empty_text_color)

    empty_label = QLabel(text)
    empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    empty_label.setStyleSheet(f"""
        QLabel {{
            color: {empty_text_color};
            font-size: {font_size}px;
            font-style: italic;
            opacity: 0.75;
            background-color: transparent;
            padding: 40px;
        }}
    """)

    # Вставляем перед stretch элементом
    layout.insertWidget(layout.count() - 1, empty_label)

def get_theme_color(config, color_key, default_color):
    """Универсальная функция для получения цветов из конфигурации"""
    if config and hasattr(config, 'get'):
        return config.get(f"custom_color_{color_key}") or default_color
    return default_color

def create_file_group_universal(label_text, button_text, file_filter, line_edit, mode='open'):
    """Универсальная функция для создания группы выбора файлов"""
    from PyQt6.QtWidgets import QGroupBox
    group_box = QGroupBox(label_text)
    layout = QVBoxLayout(group_box)

    if mode == 'open':
        line_edit.setReadOnly(True)
        line_edit.setPlaceholderText(tr("ui.select_file"))
    else:  # mode == 'save'
        line_edit.setPlaceholderText(tr("ui.file_path_placeholder"))

    button = QPushButton(button_text)
    layout.addWidget(line_edit)
    layout.addWidget(button)
    return group_box, button  # Возвращаем кнопку для настройки обработчика

def clear_layout_widgets(layout, keep_last_n=1):
    """Универсальная функция для очистки виджетов из layout'а"""
    if not layout:
        return

    end_index = layout.count() - keep_last_n
    for i in reversed(range(end_index)):
        item = layout.itemAt(i)
        if item:
            widget = item.widget()
            if widget:
                widget.setParent(None)

# ============================================================================
#                               CUSTOM WIDGETS
# ============================================================================

class NoScrollComboBox(QComboBox):
    def wheelEvent(self, event): event.ignore()
class NoScrollTabWidget(QTabWidget):
    def wheelEvent(self, event): event.ignore()
class ClickableLabel(QLabel):
    clicked, doubleClicked = pyqtSignal(int, int), pyqtSignal(int, int)
    def __init__(self, chapter: int, slot: int, *args, **kwargs): super().__init__(*args, **kwargs); self._ch, self._sl = chapter, slot
    def mousePressEvent(self, ev):
        if ev and ev.button() == Qt.MouseButton.LeftButton: self.clicked.emit(self._ch, self._sl)
        super().mousePressEvent(ev)
    def mouseReleaseEvent(self, ev): super().mouseReleaseEvent(ev)
    def mouseDoubleClickEvent(self, ev):
        if ev and ev.button() == Qt.MouseButton.LeftButton: self.doubleClicked.emit(self._ch, self._sl)
        super().mouseDoubleClickEvent(ev)

class SlotFrame(QFrame):
    """Кастомный QFrame для слотов с дополнительными атрибутами"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.chapter_id: int = -1
        self.assigned_mod = None
        self.content_widget: Optional[QWidget] = None
        self.mod_icon: Optional[QLabel] = None
        self.is_selected: bool = False
        self.click_handler: Optional[Callable] = None
        self.double_click_handler: Optional[Callable] = None



    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.click_handler:
            self.click_handler()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.double_click_handler:
            self.double_click_handler()
        super().mouseDoubleClickEvent(event)


class ScreenshotsCarousel(QWidget):
    def __init__(self, urls: list[str], parent=None):
        super().__init__(parent)
        self.urls = [u for u in urls if isinstance(u, str) and u.startswith(('http://','https://'))][:10]
        self.index = 0
        self._images = [None] * len(self.urls)
        self._workers = {}
        # loading flags must match urls length to avoid IndexError
        self._loading = [False] * len(self.urls)
        # Останавливаем фоновые потоки при уничтожении виджета
        try:
            self.destroyed.connect(self._stop_all_workers)
        except Exception:
            pass
        self._init_ui()
        if self.urls:
            self._show_current()
        else:
            self._update_nav_state()

    def _stop_all_workers(self):
        try:
            # Останавливаем все QThread из коллекции
            for k, w in list(getattr(self, '_workers', {}).items()):
                try:
                    if w.isRunning():
                        w.requestInterruption(); w.quit(); w.wait(1000)
                except Exception:
                    pass
            if hasattr(self, '_workers'):
                self._workers.clear()
        except Exception:
            pass

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(8)

        # Image area
        self.image_label = QLabel()
        from PyQt6.QtWidgets import QSizePolicy
        # Fix the rendering area to avoid any initial zoom effect
        fixed_w, fixed_h = 550, 220
        self.setMaximumWidth(fixed_w)
        self.image_label.setFixedSize(fixed_w, fixed_h)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.image_label.setScaledContents(False)
        self.image_label.setStyleSheet("background-color: black; border: 1px solid #444;")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Nav buttons
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("⮜")
        self.next_btn = QPushButton("⮞")
        for b in (self.prev_btn, self.next_btn):
            b.setFixedSize(32, 28)
        self.prev_btn.clicked.connect(self._prev)
        self.next_btn.clicked.connect(self._next)

        nav_layout.addStretch()
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addSpacing(8)
        nav_layout.addWidget(self.next_btn)
        nav_layout.addStretch()

        # Dots
        self.dots_layout = QHBoxLayout()
        self.dots_layout.setSpacing(4)
        self._dot_labels = []

        layout.addWidget(self.image_label)
        layout.addLayout(nav_layout)
        # center dots: stretches on both sides
        dots_container = QHBoxLayout()
        dots_container.addStretch()
        dots_container.addLayout(self.dots_layout)
        dots_container.addStretch()
        layout.addLayout(dots_container)
        
        self._nav_container = nav_layout
        self._root_layout = layout

    def _ensure_dots(self):
        # clear
        while self.dots_layout.count():
            item = self.dots_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.setParent(None)
        self._dot_labels = []
        for i in range(len(self.urls)):
            lbl = QLabel('●' if i==self.index else '○')
            lbl.setStyleSheet("color: white; font-size: 14px;")
            self._dot_labels.append(lbl)
            self.dots_layout.addWidget(lbl)

    def _prev(self):
        if not self.urls: return
        self.index = (self.index - 1) % len(self.urls)
        self._show_current()

    def _next(self):
        if not self.urls: return
        self.index = (self.index + 1) % len(self.urls)
        self._show_current()

    def _update_nav_state(self):
        count = len(self.urls)
        enable_nav = count > 1
        self.prev_btn.setEnabled(enable_nav)
        self.next_btn.setEnabled(enable_nav)
        # hide dots and nav when 0 or 1
        for i in range(self.dots_layout.count()):
            item = self.dots_layout.itemAt(i)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.setVisible(enable_nav)
        self.prev_btn.setVisible(enable_nav)
        self.next_btn.setVisible(enable_nav)

    def _show_current(self):
        self._ensure_dots()
        self._update_nav_state()
        if not self.urls:
            self.image_label.setText(tr('ui.empty'))
            return
        url = self.urls[self.index]
        img = self._images[self.index]
        if img is None:
            # lazy load via thread
            if not hasattr(self, '_loading'):
                self._loading = [False] * len(self.urls)
                self._current_worker = None
            if not self._loading[self.index]:
                self._loading[self.index] = True
                from PyQt6.QtCore import QThread, pyqtSignal
                class _ImgLoader(QThread):
                    loaded = pyqtSignal(int, object)
                    failed = pyqtSignal(int)
                    def __init__(self, idx, url):
                        super().__init__()
                        self.idx, self.url = idx, url
                    def run(self):
                        try:
                            import requests
                            r = requests.get(self.url, timeout=10)
                            if not r.ok:
                                self.failed.emit(self.idx); return
                            q = QImage()
                            if not q.loadFromData(r.content):
                                self.failed.emit(self.idx); return
                            self.loaded.emit(self.idx, q)
                        except Exception:
                            self.failed.emit(self.idx)
                worker = _ImgLoader(self.index, url)
                def on_loaded(i, qimg):
                    if i < len(self._images):
                        self._images[i] = qimg
                        self._loading[i] = False
                        if i == self.index:
                            self._set_pixmap(qimg)
                def on_failed(i):
                    if i < len(self._loading):
                        self._loading[i] = False
                    if i == self.index:
                        self.image_label.setText(tr('errors.file_not_available'))
                worker.loaded.connect(on_loaded)
                worker.failed.connect(on_failed)
                # Keep reference so worker isn't GC'd
                if not hasattr(self, '_workers'):
                    self._workers = {}
                self._workers[self.index] = worker
                # do not clear current pixmap to avoid flicker
                worker.start()
            return
        self._set_pixmap(img)
        # Preload neighbors
        self._preload_neighbor(self.index - 1)
        self._preload_neighbor(self.index + 1)

    def _preload_neighbor(self, idx: int):
        if not self.urls:
            return
        if idx < 0 or idx >= len(self.urls):
            return
        if self._images[idx] is not None or (hasattr(self, '_loading') and idx < len(self._loading) and self._loading[idx]):
            return
        if not hasattr(self, '_loading'):
            self._loading = [False] * len(self.urls)
        self._loading[idx] = True
        if not hasattr(self, '_workers'):
            self._workers = {}
        from PyQt6.QtCore import QThread, pyqtSignal
        class _Preloader(QThread):
            loaded = pyqtSignal(int, object)
            failed = pyqtSignal(int)
            def __init__(self, i, url):
                super().__init__()
                self.i, self.url = i, url
            def run(self):
                try:
                    import requests
                    r = requests.get(self.url, timeout=10)
                    if not r.ok:
                        self.failed.emit(self.i); return
                    q = QImage()
                    if not q.loadFromData(r.content):
                        self.failed.emit(self.i); return
                    self.loaded.emit(self.i, q)
                except Exception:
                    self.failed.emit(self.i)
        w = _Preloader(idx, self.urls[idx])
        def on_loaded(i, qimg):
            if i < len(self._images):
                self._images[i] = qimg
            if hasattr(self, '_loading') and i < len(self._loading):
                self._loading[i] = False
            if hasattr(self, '_workers'):
                self._workers.pop(i, None)
        def on_failed(i):
            if hasattr(self, '_loading') and i < len(self._loading):
                self._loading[i] = False
            if hasattr(self, '_workers'):
                self._workers.pop(i, None)
        w.loaded.connect(on_loaded)
        w.failed.connect(on_failed)
        self._workers[idx] = w
        w.start()

    # Note: fade-in animation removed intentionally for stability and to keep position while scrolling.

    def _set_pixmap(self, qimg: QImage):
        # letterbox fit into a fixed-height area; cap width to avoid horizontal growth
        # Use fixed label dimensions to avoid any size-based scaling on first show
        label_w = self.image_label.width() or 760
        label_h = self.image_label.height() or 220
        pm = QPixmap.fromImage(qimg)
        scaled = pm.scaled(label_w, label_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        # Create black canvas and draw centered
        canvas = QPixmap(label_w, label_h)
        canvas.fill(QColor('black'))
        painter = QPainter(canvas)
        x = (label_w - scaled.width())//2
        y = (label_h - scaled.height())//2
        painter.drawPixmap(x, y, scaled)
        painter.end()
        self.image_label.setPixmap(canvas)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # redraw to fit new size
        if self.urls and 0 <= self.index < len(self._images):
            current = self._images[self.index]
            if current is not None:
                self._set_pixmap(current)


class ModPlaqueWidget(QFrame):
    """Плашка мода для поиска"""
    clicked = pyqtSignal(object)
    install_requested = pyqtSignal(object)
    uninstall_requested = pyqtSignal(object)
    details_requested = pyqtSignal(object)

    def __init__(self, mod_data, parent=None):
        super().__init__(parent)
        self.mod_data = mod_data
        self.is_selected = False
        self.is_installed = False  # Флаг для отслеживания установки мода
        self.setObjectName("modPlaque")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedHeight(120)  # Уменьшили: 70px иконка + 10px отступы
        self.parent_app = parent
        self._init_ui()
        self._update_style()
        self._check_installation_status()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("modIcon")
        self.icon_label.setFixedSize(80, 80)  # Уменьшили еще больше
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_icon()
        main_layout.addWidget(self.icon_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        title_layout = QHBoxLayout()

        name_label = QLabel(self.mod_data.name)
        name_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        title_layout.addWidget(name_label)

        # Используем базовую версию мода, а не версию файлов
        mod_version = self.mod_data.version.split('|')[0] if self.mod_data.version and '|' in self.mod_data.version else self.mod_data.version
        version_text = mod_version or "N/A"
        version_label = QLabel(f"({version_text})")
        version_label.setObjectName("versionLabel")
        version_label.setStyleSheet("font-size: 16px;")
        title_layout.addWidget(version_label)

        title_layout.addStretch()

        downloads_label = QLabel(f"⤓ {self.mod_data.downloads}")
        downloads_label.setObjectName("secondaryText")
        downloads_label.setToolTip(tr("ui.downloads_tooltip"))
        downloads_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        title_layout.addWidget(downloads_label)

        info_layout.addLayout(title_layout)

        metadata_layout = QHBoxLayout()
        metadata_layout.setSpacing(10)

        # Создаем метаданные с белыми заголовками и серыми значениями
        author_text = self.mod_data.author or tr("ui.unknown_author")
        author_container = QWidget()
        author_container_layout = QHBoxLayout(author_container)
        author_container_layout.setContentsMargins(0, 0, 0, 0)
        author_container_layout.setSpacing(0)
        author_label_title = QLabel(tr("ui.author_label"))
        author_label_title.setObjectName("primaryText")
        author_label_value = QLabel(f" {author_text}")
        author_label_value.setObjectName("secondaryText")
        author_container_layout.addWidget(author_label_title)
        author_container_layout.addWidget(author_label_value)

        game_version_text = self.mod_data.game_version or "N/A"
        game_version_container = QWidget()
        game_version_container_layout = QHBoxLayout(game_version_container)
        game_version_container_layout.setContentsMargins(0, 0, 0, 0)
        game_version_container_layout.setSpacing(0)
        game_version_label_title = QLabel(tr("ui.game_version_label"))
        game_version_label_title.setObjectName("primaryText")
        game_version_label_value = QLabel(f" {game_version_text}")
        game_version_label_value.setObjectName("secondaryText")
        game_version_container_layout.addWidget(game_version_label_title)
        game_version_container_layout.addWidget(game_version_label_value)

        created_date_text = self.mod_data.created_date or 'N/A'
        created_container = QWidget()
        created_container_layout = QHBoxLayout(created_container)
        created_container_layout.setContentsMargins(0, 0, 0, 0)
        created_container_layout.setSpacing(0)
        created_label_title = QLabel(tr("ui.created_label"))
        created_label_title.setObjectName("primaryText")
        created_label_value = QLabel(f" {created_date_text}")
        created_label_value.setObjectName("secondaryText")
        created_container_layout.addWidget(created_label_title)
        created_container_layout.addWidget(created_label_value)

        updated_date_text = self.mod_data.last_updated or 'N/A'
        updated_container = QWidget()
        updated_container_layout = QHBoxLayout(updated_container)
        updated_container_layout.setContentsMargins(0, 0, 0, 0)
        updated_container_layout.setSpacing(0)
        updated_label_title = QLabel(tr("ui.updated_label"))
        updated_label_title.setObjectName("primaryText")
        updated_label_value = QLabel(f" {updated_date_text}")
        updated_label_value.setObjectName("secondaryText")
        updated_container_layout.addWidget(updated_label_title)
        updated_container_layout.addWidget(updated_label_value)

        containers_to_add = [author_container, game_version_container, updated_container, created_container]
        for i, container in enumerate(containers_to_add):
            metadata_layout.addWidget(container)
            if i < len(containers_to_add) - 1:
                separator = QLabel("|")
                separator.setObjectName("secondaryText")
                metadata_layout.addWidget(separator)
        metadata_layout.addStretch()
        info_layout.addLayout(metadata_layout)

        tagline_text = self.mod_data.tagline or tr("ui.no_description")
        if len(tagline_text) > 200:
            tagline_text = tagline_text[:197] + "..."
        tagline_label = QLabel(tagline_text)
        tagline_label.setWordWrap(True)
        tagline_label.setObjectName("secondaryText")
        info_layout.addWidget(tagline_label)

        # Создаем отдельный layout для тегов под описанием
        tags_layout = QHBoxLayout()
        tags_layout.setContentsMargins(0, 5, 0, 0) # Небольшой отступ сверху
        tags_layout.setSpacing(10)

        # Добавляем статус лицензии
        if getattr(self.mod_data, 'is_piracy_protected', False):
            license_label = QLabel(tr("ui.license_label"))
            license_label.setStyleSheet("font-size: 14px; color: #2196F3; font-weight: bold;")
            tags_layout.addWidget(license_label)

        # Добавляем индикатор демоверсии
        if self.mod_data.is_demo_mod:
            demo_label = QLabel(tr("ui.demo_label"))
            demo_label.setStyleSheet("font-size: 14px; color: #FF9800; font-weight: bold;")
            tags_layout.addWidget(demo_label)

        # Добавляем статус верификации
        if self.mod_data.is_verified:
            verified_label = QLabel(tr("ui.verified_label"))
            verified_label.setStyleSheet("font-size: 14px; color: #4CAF50; font-weight: bold;")
            tags_layout.addWidget(verified_label)
        tags_layout.addStretch()
        info_layout.addLayout(tags_layout)

        info_layout.addStretch()


        main_layout.addLayout(info_layout, 1) # 1 = stretch factor

        # 3. Кнопки действий (справа)
        self.actions_widget = QWidget()
        actions_layout = QVBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(5)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.details_button = QPushButton(tr("ui.details_button"))
        self.details_button.setObjectName("plaqueButton")
        self.details_button.clicked.connect(lambda: self.details_requested.emit(self.mod_data))

        self.install_button = QPushButton(tr("ui.install_button"))
        self.install_button.setObjectName("plaqueButtonInstall")
        self.install_button.clicked.connect(self._on_install_button_clicked)

        actions_layout.addWidget(self.details_button)


        actions_layout.addWidget(self.install_button)
        self.actions_widget.setVisible(False)
        main_layout.addWidget(self.actions_widget)

    def _load_icon(self):
        """Загружает иконку для ModPlaqueWidget"""
        load_mod_icon_universal(self.icon_label, self.mod_data, 80)

    def _update_style(self):
        """Обновляет стиль плашки с учетом кастомизации"""
        update_mod_widget_style(self, "modPlaque", self.parent_app)

    def set_selected(self, selected):
        """Устанавливает состояние выбора плашки"""
        self.is_selected = selected
        self.actions_widget.setVisible(selected)
        self._update_style()  # Используем единый метод обновления стиля

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.mod_data)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.details_requested.emit(self.mod_data)
        super().mouseDoubleClickEvent(event)

    def _check_installation_status(self):
        """Проверяет, установлен ли мод и обновляет кнопку"""
        if self.parent_app and hasattr(self.parent_app, '_is_mod_installed'):
            self.is_installed = self.parent_app._is_mod_installed(self.mod_data.key)
            self._update_install_button()

    def _update_install_button(self):
        """Обновляет текст и стиль кнопки в зависимости от статуса установки"""
        if self.is_installed:
            self.install_button.setText(tr("ui.uninstall_button"))
            self.install_button.setObjectName("plaqueButtonUninstall")
            self.install_button.setStyleSheet("""
                QPushButton#plaqueButtonUninstall {
                    background-color: #F44336;
                    color: white;
                    font-weight: bold;
                    min-width: 110px;
                    max-width: 110px;
                    min-height: 35px;
                    max-height: 35px;
                    font-size: 15px;
                    padding: 1px;
                }
                QPushButton#plaqueButtonUninstall:hover {
                    background-color: #d32f2f;
                }
            """)
        else:
            self.install_button.setText(tr("ui.install_button"))
            self.install_button.setObjectName("plaqueButtonInstall")
            self.install_button.setStyleSheet("")  # Используем стиль из _update_style()

    def _on_install_button_clicked(self):
        """Обработчик нажатия на кнопку Установить/Удалить"""
        if self.is_installed:
            self.uninstall_requested.emit(self.mod_data)
        else:
            self.install_requested.emit(self.mod_data)

    def update_installation_status(self):
        """Публичный метод для обновления статуса установки извне"""
        self._check_installation_status()



class InstalledModWidget(QFrame):
    """Виджет для отображения установленного мода в библиотеке"""
    clicked = pyqtSignal(object)
    remove_requested = pyqtSignal(object)
    use_requested = pyqtSignal(object)

    def __init__(self, mod_data, is_local=False, is_available=True, has_update=False, parent=None):
        super().__init__(parent)
        self.mod_data = mod_data
        self.is_local = is_local
        self.is_available = is_available
        self.has_update = has_update
        self.is_selected = False
        self.is_in_slot = False  # Для отслеживания, вставлен ли мод в слот
        # Явный статус виджета: 'ready' | 'needs_update' | 'in_slot'
        self.status = 'ready'
        if has_update:
            self.status = 'needs_update'
        self.setObjectName("installedMod")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedHeight(120)  # Увеличили для больших иконок
        self.parent_app = parent
        self._init_ui()
        self._update_style()
        # Применяем состояние к кнопке
        self._update_button_from_status()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)

        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)
        self.icon_label = QLabel()
        self.icon_label.setObjectName("modIcon")
        self.icon_label.setFixedSize(80, 80)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_mod_icon()
        main_layout.addWidget(self.icon_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        title_layout = QHBoxLayout()

        # Название
        name_label = QLabel(self.mod_data.name)
        name_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        title_layout.addWidget(name_label)

        mod_version = self.mod_data.version.split('|')[0] if self.mod_data.version and '|' in self.mod_data.version else self.mod_data.version
        version_text = mod_version or "N/A"
        version_label = QLabel(f"({version_text})")
        version_label.setObjectName("versionLabel")
        version_label.setStyleSheet("font-size: 16px;")
        title_layout.addWidget(version_label)

        # Индикатор статуса
        indicator = QLabel("●")
        indicator.setFixedSize(16,16)
        indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if self.is_local:
            indicator.setStyleSheet("font-size: 14px; color: #FFD700; font-weight: bold; margin-left: 5px;")
            indicator.setToolTip(tr("tooltips.local_mod"))
        elif self.is_available and self.has_update:
            indicator.setStyleSheet("font-size: 14px; color: #FFA500; font-weight: bold; margin-left: 5px;")
            indicator.setToolTip(tr("tooltips.public_mod_update_available"))
        elif self.is_available:
            indicator.setStyleSheet("font-size: 14px; color: #4CAF50; font-weight: bold; margin-left: 5px;")
            indicator.setToolTip(tr("tooltips.public_mod_available"))
        else:
            indicator.setStyleSheet("font-size: 14px; color: #F44336; font-weight: bold; margin-left: 5px;")
            indicator.setToolTip(tr("tooltips.public_mod_unavailable"))
        title_layout.addWidget(indicator)

        title_layout.addStretch()
        info_layout.addLayout(title_layout)

        metadata_layout = QHBoxLayout()
        metadata_layout.setSpacing(10)

        # Создаем метаданные с белыми заголовками и серыми значениями
        author_text = self.mod_data.author or tr("ui.unknown_author")
        author_container = QWidget()
        author_container_layout = QHBoxLayout(author_container)
        author_container_layout.setContentsMargins(0, 0, 0, 0)
        author_container_layout.setSpacing(0)
        author_label_title = QLabel(tr("ui.author_label"))
        author_label_title.setObjectName("primaryText")
        author_label_value = QLabel(f" {author_text}")
        author_label_value.setObjectName("secondaryText")
        author_container_layout.addWidget(author_label_title)
        author_container_layout.addWidget(author_label_value)

        game_version_text = self.mod_data.game_version or "N/A"
        game_version_container = QWidget()
        game_version_container_layout = QHBoxLayout(game_version_container)
        game_version_container_layout.setContentsMargins(0, 0, 0, 0)
        game_version_container_layout.setSpacing(0)
        game_version_label_title = QLabel(tr("ui.game_version_label"))
        game_version_label_title.setObjectName("primaryText")
        game_version_label_value = QLabel(f" {game_version_text}")
        game_version_label_value.setObjectName("secondaryText")
        game_version_container_layout.addWidget(game_version_label_title)
        game_version_container_layout.addWidget(game_version_label_value)

        # Installed date should reflect user's installation time, not mod's created date
        installed_date_text = 'N/A'
        try:
            if self.parent_app and hasattr(self.parent_app, '_get_mod_config_by_key'):
                cfg = self.parent_app._get_mod_config_by_key(self.mod_data.key)
                if isinstance(cfg, dict):
                    installed_date_text = cfg.get('installed_date') or cfg.get('created_date') or 'N/A'
        except Exception:
            installed_date_text = 'N/A'
        date_label_text = tr("ui.created_label") if self.is_local else tr("ui.installed_label")
        installed_container = QWidget()
        installed_container_layout = QHBoxLayout(installed_container)
        installed_container_layout.setContentsMargins(0, 0, 0, 0)
        installed_container_layout.setSpacing(0)
        installed_label_title = QLabel(date_label_text)
        installed_label_title.setObjectName("primaryText")
        installed_label_value = QLabel(f" {installed_date_text}")
        installed_label_value.setObjectName("secondaryText")
        installed_container_layout.addWidget(installed_label_title)
        installed_container_layout.addWidget(installed_label_value)

        containers_to_add = [author_container, game_version_container, installed_container]
        for i, container in enumerate(containers_to_add):
            metadata_layout.addWidget(container)
            if i < len(containers_to_add) - 1:
                separator = QLabel("|")
                separator.setObjectName("secondaryText")
                metadata_layout.addWidget(separator)
        metadata_layout.addStretch()
        info_layout.addLayout(metadata_layout)

        tagline_text = self.mod_data.tagline or tr("ui.no_description")
        if len(tagline_text) > 200:
            tagline_text = tagline_text[:197] + "..."
        tagline_label = QLabel(tagline_text)
        tagline_label.setWordWrap(True)
        tagline_label.setObjectName("secondaryText")
        info_layout.addWidget(tagline_label)

        info_layout.addStretch()
        main_layout.addLayout(info_layout, 1)
        self.actions_widget = QWidget()
        actions_layout = QVBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(5)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.use_button = QPushButton(tr("ui.use_button"))
        self.use_button.setObjectName("plaqueButtonInstall")
        self.use_button.clicked.connect(lambda: self.use_requested.emit(self.mod_data))
        actions_layout.addWidget(self.use_button)

        self.remove_button = QPushButton(tr("ui.delete_button"))
        self.remove_button.setObjectName("plaqueButton")
        self.remove_button.setStyleSheet("""
            QPushButton#plaqueButton {
                background-color: #F44336;
                color: white;
            }
            QPushButton#plaqueButton:hover {
                background-color: #da190b;
            }
        """)
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self.mod_data))
        actions_layout.addWidget(self.remove_button)

        self.actions_widget.setVisible(False)
        main_layout.addWidget(self.actions_widget)

    def _mod_needs_update(self):
        """Проверяет, нуждается ли мод в обновлении"""
        if not self.parent_app or self.is_local:
            return False

        needs_update = any(self.parent_app._mod_has_files_for_chapter(self.mod_data, i) and
                          self.parent_app._get_mod_status_for_chapter(self.mod_data, i) == 'update' for i in range(5))

        return needs_update

    def _load_mod_icon(self):
        """Загружает иконку для InstalledModWidget"""
        load_mod_icon_universal(self.icon_label, self.mod_data, 80)

    def _update_style(self):
        """Обновляет стиль плашки с учетом кастомизации"""
        update_mod_widget_style(self, "installedMod", self.parent_app)

    def set_selected(self, selected):
        """Устанавливает состояние выбора плашки"""
        self.is_selected = selected
        self.actions_widget.setVisible(selected)
        self._update_style()  # Используем единый метод обновления стиля

    def _update_button_from_status(self):
        """Обновляет текст и стиль кнопки на основе текущего статуса."""
        if self.status == 'in_slot':
            # Оранжевый стиль для удаления из слота
            self.use_button.setText(tr("ui.remove_button"))
            self.use_button.setStyleSheet("""
                QPushButton#plaqueButtonInstall {
                    background-color: #FF9800;
                    font-weight: bold;
                }
                QPushButton#plaqueButtonInstall:hover {
                    background-color: #F57C00;
                }
            """)
        elif self.status == 'needs_update':
            # Оранжевый стиль для обновления
            self.use_button.setText(tr("ui.update_button"))
            self.use_button.setStyleSheet("""
                QPushButton#plaqueButtonInstall {
                    background-color: #FF9800;
                    font-weight: bold;
                }
                QPushButton#plaqueButtonInstall:hover {
                    background-color: #F57C00;
                }
            """)
        else:
            # Зеленый стиль для использования
            self.use_button.setText(tr("ui.use_button"))
            self.use_button.setStyleSheet("""
                QPushButton#plaqueButtonInstall {
                    background-color: #4CAF50;
                    font-weight: bold;
                }
                QPushButton#plaqueButtonInstall:hover {
                    background-color: #5cb85c;
                }
            """)

    def set_in_slot(self, in_slot):
        """Устанавливает, находится ли мод в слоте"""
        self.is_in_slot = in_slot
        if self.is_in_slot:
            self.status = 'in_slot'
        else:
            # Если мод не в слоте, статус зависит от наличия обновлений
            if self._mod_needs_update():
                self.status = 'needs_update'
            else:
                self.status = 'ready'
        # Обновляем кнопку на основе нового статуса
        self._update_button_from_status()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.mod_data)
        super().mousePressEvent(event)



class SaveEditorDialog(QDialog):
    def __init__(self, file_path: str, parent=None):
        super().__init__(parent); self.setWindowTitle(tr("dialogs.save_editing")); self.resize(600, 500); self.file_path = file_path
        lay = QVBoxLayout(self); self.table = QTableWidget(); self.table.setColumnCount(1); self.table.setHorizontalHeaderLabels([tr("ui.value_label")])
        if header := self.table.horizontalHeader(): header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table); btn_bar = QHBoxLayout(); btn_bar.addStretch()
        for text, slot in [(tr("ui.cancel_button"), self._on_cancel), (tr("ui.save"), self._on_save)]:
            btn = QPushButton(text); btn.clicked.connect(slot); btn_bar.addWidget(btn)
        lay.addLayout(btn_bar); self._load_file(); self._original = self._current_data()
    def _load_file(self):
        with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f.read().splitlines()): self.table.insertRow(i); self.table.setItem(i, 0, QTableWidgetItem(line))
    def _current_data(self): return [("" if (item := self.table.item(r, 0)) is None else item.text()) for r in range(self.table.rowCount())]
    def _on_cancel(self):
        if self._current_data() != self._original and QMessageBox.question(self, tr("dialogs.cancel_changes"), tr("dialogs.changes_will_be_lost")) != QMessageBox.StandardButton.Yes: return
        self.reject()
    def _on_save(self):
        new = self._current_data()
        if new != self._original and QMessageBox.question(self, tr("dialogs.save_changes"), tr("dialogs.original_save_overwrite")) != QMessageBox.StandardButton.Yes:
            return
        try:
            tmp = self.file_path + ".tmp"
            with open(tmp, "w", encoding="utf-8", errors="replace") as f:
                f.write("\n".join(new))
            shutil.move(tmp, self.file_path)
            self.accept()
        except PermissionError:
            QMessageBox.critical(self, tr("dialogs.access_error"), tr("dialogs.no_write_permissions", path=os.path.dirname(self.file_path)))
        except Exception:
            QMessageBox.critical(self, tr("dialogs.error"), tr("dialogs.save_file_error"))
        # Do not call reject() here on success; the dialog is already accepted

class XdeltaDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("ui.patching_tab"))
        self.resize(600, 525)
        self.init_ui()

        # Центрируем окно относительно родителя
        if parent:
            parent_geometry = parent.geometry()
            dialog_geometry = self.geometry()
            x = parent_geometry.x() + (parent_geometry.width() - dialog_geometry.width()) // 2
            y = parent_geometry.y() + (parent_geometry.height() - dialog_geometry.height()) // 2
            self.move(x, y)
    def init_ui(self):
        main_layout = QVBoxLayout(self); tabs = NoScrollTabWidget()
        tabs.setStyleSheet("QTabWidget::tab-bar { alignment: center; } QTabBar::tab { min-width: 120px; padding: 8px 16px; }")
        create_tab = QWidget(); create_layout = QVBoxLayout(create_tab)
        self.original_create_edit, self.modified_create_edit, self.patch_output_edit = QLineEdit(), QLineEdit(), QLineEdit()

        create_layout.addWidget(self._create_file_group(tr("ui.original_file_label"), tr("ui.select_original_file"), get_file_filter("all_files"), self.original_create_edit))
        create_layout.addWidget(self._create_file_group(tr("ui.modified_file_label"), tr("ui.select_modified_file"), get_file_filter("all_files"), self.modified_create_edit))
        create_layout.addWidget(self._create_save_file_group(tr("ui.save_patch_as"), tr("ui.specify_patch_path"), get_file_filter("xdelta_files"), self.patch_output_edit))
        create_button = QPushButton(tr("ui.create_patch_button")); create_button.clicked.connect(self.create_patch)
        create_layout.addWidget(create_button); create_layout.addStretch(); tabs.addTab(create_tab, tr("ui.create_patch_tab"))
        apply_tab = QWidget(); apply_layout = QVBoxLayout(apply_tab)
        self.original_apply_edit, self.patch_apply_edit, self.output_apply_edit = QLineEdit(), QLineEdit(), QLineEdit()
        apply_layout.addWidget(self._create_file_group(tr("ui.original_file_label"), tr("ui.select_original_for_patch"), get_file_filter("all_files"), self.original_apply_edit))
        apply_layout.addWidget(self._create_file_group(tr("ui.patch_file_label"), tr("ui.select_patch_file"), get_file_filter("xdelta_files"), self.patch_apply_edit))
        apply_layout.addWidget(self._create_save_file_group(tr("ui.save_modified_as"), tr("ui.specify_save_path"), get_file_filter("all_files"), self.output_apply_edit))
        apply_button = QPushButton(tr("ui.apply_patch_button")); apply_button.clicked.connect(self.apply_patch)
        apply_layout.addWidget(apply_button); apply_layout.addStretch(); tabs.addTab(apply_tab, tr("ui.apply_patch_tab")); main_layout.addWidget(tabs)
    def _create_file_group(self, label_text, button_text, file_filter, line_edit):
        group_box, button = create_file_group_universal(label_text, button_text, file_filter, line_edit, 'open')
        button.clicked.connect(lambda: self._browse_file(line_edit, file_filter))
        return group_box

    def _create_save_file_group(self, label_text, button_text, file_filter, line_edit):
        group_box, button = create_file_group_universal(label_text, button_text, file_filter, line_edit, 'save')
        # Проверяем по идентификатору line_edit
        if line_edit is getattr(self, 'output_apply_edit', None):
            button.clicked.connect(lambda: self._browse_save_output_file(line_edit, file_filter))
        else:
            button.clicked.connect(lambda: self._browse_save_file(line_edit, file_filter))
        return group_box
    def _browse_file(self, line_edit, file_filter):
        file_path, _ = QFileDialog.getOpenFileName(self, tr("ui.select_file"), "", file_filter)
        if file_path: line_edit.setText(file_path)
    def _browse_save_file(self, line_edit, file_filter, suggested_name=""):
        file_path, _ = QFileDialog.getSaveFileName(self, tr("ui.save_file"), suggested_name, file_filter)
        if file_path: line_edit.setText(os.path.abspath(os.path.normpath(file_path)))
    def _browse_save_output_file(self, line_edit, file_filter):
        original_file = self.original_apply_edit.text(); suggested_name = ""
        if original_file and os.path.exists(original_file):
            base_name = os.path.basename(original_file); name, ext = os.path.splitext(base_name); suggested_name = f"{name}_patched{ext}"
        self._browse_save_file(line_edit, file_filter, suggested_name)
    def _show_message(self, title, message, icon=QMessageBox.Icon.Information):
        msg_box = QMessageBox(self); msg_box.setIcon(icon); msg_box.setWindowTitle(title); msg_box.setText(message); msg_box.exec()

    def create_patch(self):
        try: import pyxdelta
        except ImportError: self._show_message(tr("dialogs.error"), tr("errors.component_unavailable_create"), QMessageBox.Icon.Critical); return
        original_file, modified_file, output_patch = self.original_create_edit.text(), self.modified_create_edit.text(), self.patch_output_edit.text()
        if not original_file or not modified_file or not output_patch: self._show_message(tr("dialogs.error"), tr("ui.select_all_files"), QMessageBox.Icon.Warning); return
        if not os.path.exists(original_file): self._show_message(tr("dialogs.error"), tr("ui.original_file_not_found", path=original_file), QMessageBox.Icon.Warning); return
        if not os.path.exists(modified_file): self._show_message(tr("dialogs.error"), tr("ui.modified_file_not_found", path=modified_file), QMessageBox.Icon.Warning); return
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp(prefix="xdelta_temp_")
            temp_original, temp_modified, temp_output = os.path.join(temp_dir, "original_source.bin"), os.path.join(temp_dir, "modified_target.bin"), os.path.join(temp_dir, "output.xdelta")
            shutil.copy2(original_file, temp_original); shutil.copy2(modified_file, temp_modified)
            success = pyxdelta.run(infile=temp_original, outfile=temp_modified, patchfile=temp_output)
            if success: shutil.move(temp_output, output_patch); self._show_message(tr("ui.success"), tr("ui.patch_success", path=output_patch))
            else: self._show_message(tr("errors.patch_create_error"), tr("errors.patch_create_failed"), QMessageBox.Icon.Critical)
        except Exception as e: self._show_message(tr("errors.patch_create_error"), tr("errors.patch_create_exception", error=str(e)), QMessageBox.Icon.Critical)
        finally:
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logging.debug(f"Failed to remove temp dir {temp_dir}: {e}")  # Debug print
    def apply_patch(self):
        try: import pyxdelta
        except ImportError: self._show_message(tr("dialogs.error"), tr("errors.component_unavailable_apply"), QMessageBox.Icon.Critical); return
        original_file, patch_file, output_file = self.original_apply_edit.text(), self.patch_apply_edit.text(), self.output_apply_edit.text()
        if not original_file or not patch_file or not output_file: self._show_message(tr("dialogs.error"), tr("ui.select_all_files"), QMessageBox.Icon.Warning); return
        if not os.path.exists(original_file): self._show_message(tr("dialogs.error"), tr("ui.original_file_not_found", path=original_file), QMessageBox.Icon.Warning); return
        if not os.path.exists(patch_file): self._show_message(tr("dialogs.error"), tr("ui.patch_file_not_found", path=patch_file), QMessageBox.Icon.Warning); return
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp(prefix="xdelta_temp_")
            temp_original, temp_patch, temp_output = os.path.join(temp_dir, "original_source_for_patch.bin"), os.path.join(temp_dir, "input_patch.xdelta"), os.path.join(temp_dir, "patched_output.bin")
            shutil.copy2(original_file, temp_original); shutil.copy2(patch_file, temp_patch)
            success = pyxdelta.decode(infile=temp_original, patchfile=temp_patch, outfile=temp_output)
            if success: shutil.move(temp_output, output_file); self._show_message(tr("ui.success"), tr("ui.patch_apply_success", path=output_file))
            else: self._show_message(tr("errors.patch_apply_error"), tr("errors.patch_apply_failed", original=os.path.basename(original_file), patch=os.path.basename(patch_file)), QMessageBox.Icon.Critical)
        except Exception as e: self._show_message(tr("errors.patch_apply_error"), tr("errors.patch_apply_exception", error=str(e)), QMessageBox.Icon.Critical)
        finally:
            if temp_dir and os.path.exists(temp_dir):
                try: shutil.rmtree(temp_dir)
                except Exception as e:
                    logging.debug(f"Failed to remove temp dir {temp_dir}: {e}")  # Debug print

# ============================================================================
#                             MOD EDITOR DIALOG
# ============================================================================

class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str, str)
    result = pyqtSignal(object)
    progress = pyqtSignal(int)
    update_label = pyqtSignal(QLineEdit, QLabel, str, bool)

class ModEditorDialog(QDialog):
    def __init__(self, parent, is_creating=True, is_public=True, mod_data=None):
        super().__init__(parent)
        self.parent_app, self.is_creating, self.is_public = parent, is_creating, is_public
        self.mod_data, self.current_icon_url = mod_data or {}, ""
        self.original_mod_data = mod_data.copy() if mod_data else {}
        self.mod_key = mod_data.get('key') if mod_data else None
        self.setWindowTitle(tr("ui.create_mod") if is_creating else tr("ui.edit_mod")); self.setModal(True)
        self.resize(900 if is_public else 700, 700 if is_public else 500); self.setMinimumSize(800 if is_public else 600, 600 if is_public else 400)
        self.init_ui()
        if not is_creating and mod_data: self.populate_fields()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        from PyQt6.QtWidgets import QScrollArea
        scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_widget = QWidget(); layout = QVBoxLayout(scroll_widget)

        if self.is_public and not self.is_creating: self._create_info_section(layout)

        settings_frame = QFrame(); settings_frame.setFrameStyle(QFrame.Shape.Box); settings_layout = QVBoxLayout(settings_frame)

        checkboxes_layout = QHBoxLayout(); checkboxes_layout.addStretch()
        self.demo_checkbox = QCheckBox(tr("checkboxes.demo_version"))
        checkboxes_layout.addWidget(self.demo_checkbox)
        checkboxes_layout.addSpacing(12)
        self.piracy_checkbox = QCheckBox(tr("checkboxes.piracy_protection"))
        checkboxes_layout.addWidget(self.piracy_checkbox)
        checkboxes_layout.addStretch(); settings_layout.addLayout(checkboxes_layout)

        form_layout = QVBoxLayout()
        self._create_form_fields(form_layout)
        settings_layout.addLayout(form_layout); layout.addWidget(settings_frame)
        self._create_file_management_section(layout); self._load_default_icon()
        scroll_area.setWidget(scroll_widget); main_layout.addWidget(scroll_area); self._create_action_buttons(main_layout)

    def _create_form_fields(self, form_layout):
        form_layout.addWidget(QLabel(tr("ui.mod_name_label")))
        self.name_edit = QLineEdit(); self.name_edit.setPlaceholderText(tr("ui.enter_mod_name")); form_layout.addWidget(self.name_edit)

        form_layout.addWidget(QLabel(tr("ui.mod_author") if self.is_public else tr("ui.mod_author_optional")))
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText(tr("ui.enter_author_name") if self.is_public else tr("ui.enter_author_name_optional"))
        if not self.is_creating: self.author_edit.setReadOnly(True)
        form_layout.addWidget(self.author_edit)

        form_layout.addWidget(QLabel(tr("ui.short_description")))
        self.tagline_edit = QLineEdit(); self.tagline_edit.setMaxLength(200); self.tagline_edit.setPlaceholderText(tr("ui.short_description_placeholder"))
        form_layout.addWidget(self.tagline_edit)

        self._create_icon_section(form_layout)

        self._create_tags_section(form_layout)

        form_layout.addWidget(QLabel(tr("ui.overall_mod_version")))
        self.version_edit = QLineEdit(); self.version_edit.setPlaceholderText("1.0.0"); form_layout.addWidget(self.version_edit)

        if self.is_public:
            self.description_title_label = QLabel(tr("ui.full_description_link"));
            self.description_title_label.setWordWrap(True)
            self.description_title_label.setProperty("file_type", "description")  # Добавляем file_type property
            form_layout.addWidget(self.description_title_label)
            self.description_url_edit = QLineEdit(); self.description_url_edit.setPlaceholderText("https://example.com/description.md")
            form_layout.addWidget(self.description_url_edit)
            self.description_url_edit.textChanged.connect(lambda: self._trigger_validation(self.description_url_edit, self._validate_url_for_title, title_label=self.description_title_label, is_patch=False))
            form_layout.addWidget(QLabel(tr("ui.game_version_label")))
            self.game_version_combo = NoScrollComboBox(); self._load_game_versions(); form_layout.addWidget(self.game_version_combo)
        else:
            self.description_url_edit = QLineEdit(); self.description_url_edit.hide()
            # Local mods: free text field for game version
            form_layout.addWidget(QLabel(tr("ui.game_version_label")))
            self.game_version_edit = QLineEdit(); self.game_version_edit.setPlaceholderText("1.03")
            form_layout.addWidget(self.game_version_edit)

    def _create_icon_section(self, form_layout):
        if self.is_public:
            self.icon_title_label = QLabel(tr("files.icon_direct_link"));
            self.icon_title_label.setWordWrap(True)
            self.icon_title_label.setProperty("file_type", "icon")  # Добавляем file_type property
            form_layout.addWidget(self.icon_title_label)
        else:
            form_layout.addWidget(QLabel(tr("files.icon_label")))
        icon_container = QHBoxLayout(); self.icon_edit = QLineEdit()
        if self.is_public:
            self.icon_edit.setPlaceholderText(tr("ui.leave_empty_for_default_icon"))
            self.icon_edit.textChanged.connect(self._on_icon_url_changed)
            # Отключаем любую автоматическую валидацию/подписи возле заголовка для иконки
        else:
            self.icon_edit.setPlaceholderText(tr("ui.icon_file_path_placeholder")); self.icon_edit.setReadOnly(True)
            self.icon_browse_button = QPushButton(tr("ui.browse_button")); self.icon_browse_button.clicked.connect(self._browse_local_icon)
            icon_container.addWidget(self.icon_browse_button)
        icon_container.addWidget(self.icon_edit)
        self.icon_preview = QLabel(); self.icon_preview.setFixedSize(64, 64); self.icon_preview.setStyleSheet("border: 1px solid gray;")
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.icon_preview.setText(tr("ui.icon_preview"))
        icon_container.addWidget(self.icon_preview); form_layout.addLayout(icon_container)

    def _create_tags_section(self, form_layout):
        if self.is_public:
            form_layout.addWidget(QLabel(tr("ui.mod_tags_label"))); tags_layout = QHBoxLayout()
            self.tag_translation, self.tag_customization, self.tag_gameplay, self.tag_other = QCheckBox(tr("tags.translation_text")), QCheckBox(tr("tags.customization")), QCheckBox(tr("tags.gameplay")), QCheckBox(tr("tags.other"))
            for tag in [self.tag_translation, self.tag_customization, self.tag_gameplay, self.tag_other]: tags_layout.addWidget(tag)
            form_layout.addLayout(tags_layout)
        else:
            for attr, checked in [('tag_translation', False), ('tag_customization', False), ('tag_gameplay', False), ('tag_other', True)]:
                setattr(self, attr, QCheckBox())
                if checked: getattr(self, attr).setChecked(True)

    def _load_game_versions(self):
        try:
            from helpers import _fb_url
            response = requests.get(_fb_url(DATA_FIREBASE_URL, "globals"), timeout=10)
            if response.status_code == 200:
                globals_data = response.json() or {}
                supported_versions = globals_data.get("supported_game_versions", ["1.03"])
                supported_versions.sort(key=game_version_sort_key, reverse=True)
            else: supported_versions = ["1.03"]
        except Exception: supported_versions = ["1.03"]
        self.game_version_combo.addItems(supported_versions)
        if supported_versions: self.game_version_combo.setCurrentIndex(0)

    def _trigger_validation(self, line_edit, validation_func, **kwargs):
        if hasattr(line_edit, '_validation_timer'): line_edit._validation_timer.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: validation_func(line_edit, **kwargs))
        line_edit._validation_timer = timer
        timer.start(500)

    def _create_info_section(self, layout):
        info_frame = QFrame()
        info_frame.setFrameStyle(QFrame.Shape.Box)
        info_layout = QVBoxLayout(info_frame)

        downloads_label = QLabel(tr("ui.downloads_count", count=self.mod_data.get('downloads', 0)))
        info_layout.addWidget(downloads_label)

        if self.mod_data.get('is_verified', False):
            verified_label = QLabel(tr("ui.mod_verified"))
            verified_label.setStyleSheet("color: green;")
        else:
            verified_label = QLabel(tr("ui.mod_not_verified"))
            verified_label.setStyleSheet("color: orange;")
            info_layout.addWidget(verified_label)

            details_button = QPushButton(tr("ui.verification_details"))
            details_button.clicked.connect(self._show_verification_details)
            info_layout.addWidget(details_button)
        layout.addWidget(info_frame)

    def _create_file_management_section(self, parent_layout):
        files_frame = QFrame()
        files_frame.setFrameStyle(QFrame.Shape.Box)
        files_layout = QVBoxLayout(files_frame)

        # Manage screenshots button (centered)
        if not hasattr(self, 'screenshots_urls'):
            self.screenshots_urls = []
        manage_btn = QPushButton(tr("ui.manage_screenshots"))

        def _open_screenshots_dialog():
            dlg = QDialog(self)
            dlg.setWindowTitle(tr("ui.manage_screenshots"))
            dlg.setMinimumSize(500, 400)
            dlg.resize(700, 700)
            dlg.setSizeGripEnabled(True)
            v = QVBoxLayout(dlg)

            from PyQt6.QtWidgets import QScrollArea
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            content_layout = QVBoxLayout(content)
            scroll.setWidget(content)
            v.addWidget(scroll)

            editors = []
            previews = []

            MAX_MB = 2
            MAX_BYTES = MAX_MB * 1024 * 1024

            def make_preview(index):
                url = editors[index].text().strip()
                editors[index].setProperty('isValidShot', False)
                if not url or not (url.startswith('http://') or url.startswith('https://')):
                    previews[index].setText('')
                    previews[index].setPixmap(QPixmap())
                    previews[index].hide()
                    return
                try:
                    import requests
                    # First try HEAD for size
                    try:
                        h = requests.head(url, allow_redirects=True, timeout=6)
                        cl = h.headers.get('content-length')
                        if cl and cl.isdigit() and int(cl) > MAX_BYTES:
                            previews[index].setText(tr('errors.file_too_large', max_size=MAX_MB))
                            previews[index].show()
                            return
                    except Exception:
                        pass
                    resp = requests.get(url, timeout=8)
                    if not resp.ok:
                        previews[index].setText(tr('errors.file_not_available'))
                        previews[index].show()
                        return
                    # If no content-length, check actual size
                    if len(resp.content) > MAX_BYTES:
                        previews[index].setText(tr('errors.file_too_large', max_size=MAX_MB))
                        previews[index].show()
                        return
                    qimg = QImage()
                    if not qimg.loadFromData(resp.content):
                        previews[index].setText(tr('errors.not_an_image'))
                        previews[index].show()
                        return
                    # Fit wide area with letterbox
                    area_w = 640
                    area_h = 200
                    pm = QPixmap.fromImage(qimg)
                    scaled = pm.scaled(area_w, area_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    canvas = QPixmap(area_w, area_h)
                    canvas.fill(QColor('black'))
                    p = QPainter(canvas)
                    x = (area_w - scaled.width())//2
                    y = (area_h - scaled.height())//2
                    p.drawPixmap(x, y, scaled)
                    p.end()
                    previews[index].setPixmap(canvas)
                    previews[index].show()
                    editors[index].setProperty('isValidShot', True)
                except Exception:
                    previews[index].setText(tr('errors.url_error'))
                    previews[index].show()

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
                le.textChanged.connect(lambda _=None, idx=i: make_preview(idx))
                # initial — immediately validate and show if valid
                make_preview(i)

            btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            def save_and_close():
                urls = []
                for e in editors:
                    u = e.text().strip()
                    if u and u.startswith(('http://','https://')):
                        urls.append(u)
                    if len(urls) >= 10:
                        break
                self.screenshots_urls = urls
                dlg.accept()
            btns.accepted.connect(save_and_close)
            btns.rejected.connect(dlg.reject)
            v.addWidget(btns)

            dlg.exec()

        manage_btn.clicked.connect(_open_screenshots_dialog)
        files_layout.addWidget(manage_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        files_label = QLabel(tr("ui.files_management"))
        files_label.setStyleSheet("font-weight: bold; font-size: 18px;")
        files_layout.addWidget(files_label, alignment=Qt.AlignmentFlag.AlignHCenter)
 
        self.file_tabs = NoScrollTabWidget()
        # Центрируем вкладки
        self.file_tabs.setStyleSheet("QTabWidget::tab-bar { alignment: center; } QTabBar::tab { padding: 4px 8px; }")
        self.demo_checkbox.stateChanged.connect(self._update_file_tabs)
        self.piracy_checkbox.stateChanged.connect(self._update_data_file_labels)
        # On mode change, recreate DATA/PATCH frames so type switches cleanly
        self.piracy_checkbox.stateChanged.connect(self._recreate_data_frames)
        # Update add button text everywhere
        self.piracy_checkbox.stateChanged.connect(self._update_data_add_button_texts)
        if not self.is_public:
            # Legacy: local tabs used to be rebuilt entirely; keep behavior
            self.piracy_checkbox.stateChanged.connect(self._update_file_tabs)

        files_layout.addWidget(self.file_tabs)
        parent_layout.addWidget(files_frame)
        self._update_file_tabs()

    def _update_data_file_labels(self):
        is_piracy_protected = self.piracy_checkbox.isChecked()
        for tab_index in range(self.file_tabs.count()):
            if not (tab := self.file_tabs.widget(tab_index)) or not (layout := tab.layout()): continue
            for i in range(layout.count()):
                if not (item := layout.itemAt(i)) or not (widget := item.widget()) or not hasattr(widget, 'layout'): continue
                if frame_layout := widget.layout():
                    for j in range(frame_layout.count()):
                        if (frame_item := frame_layout.itemAt(j)) and (frame_widget := frame_item.widget()) and isinstance(frame_widget, QLabel):
                            if frame_widget.text().startswith(("DATA", "PATCH")):
                                frame_widget.setText(tr("files.patch_file") if is_piracy_protected else tr("files.data_file"))
                                self._update_labels_in_frame(frame_layout, is_piracy_protected); break

    def _update_labels_in_frame(self, frame_layout, is_patch):
        for i in range(frame_layout.count()):
            if (item := frame_layout.itemAt(i)) and (widget := item.widget()) and isinstance(widget, QLabel):
                # Используем функцию определения типа поля (временное решение)
                field_type = detect_field_type_by_text(widget.text())
                if field_type == "file_path":
                    widget.setText(tr("files.update_file_label", is_public=self.is_public, is_patch=is_patch))
                elif field_type == "version":
                    widget.setText(tr("files.version_label_colon", is_patch=is_patch))

    def _recreate_data_frames(self):
        """Удаляет существующие DATA/PATCH фреймы во всех вкладках и создает новые по текущему режиму."""
        for tab_index in range(self.file_tabs.count()):
            tab = self.file_tabs.widget(tab_index)
            if not tab:
                continue
            layout = tab.layout()
            if not layout:
                continue
            # Найти и удалить все фреймы DATA/PATCH
            found = False
            for i in range(layout.count()-1, -1, -1):
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
                    # Предпочтительно через property
                    ftype = first.property("file_type") if hasattr(first, 'property') else None
                    is_data_frame = ftype in ("data", "patch")
                    # Фолбек на текст
                    if not is_data_frame:
                        txt = first.text() if hasattr(first, 'text') else ""
                        is_data_frame = (isinstance(txt, str) and (txt.startswith("DATA") or txt.startswith("PATCH")))
                    if is_data_frame:
                        found = True
                        self._remove_data_file(None, layout, frame)
            # Создать новый пустой фрейм, если удаляли
            if found:
                self._add_data_file(tab, layout)

    def _data_button_text(self) -> str:
        return tr("ui.add_data_patch_file") if self.piracy_checkbox.isChecked() else tr("ui.add_data_file")

    def _update_data_add_button_texts(self):
        for ti in range(self.file_tabs.count()):
            tab = self.file_tabs.widget(ti)
            if not tab:
                continue
            layout = tab.layout()
            if not layout:
                continue
            # first row contains buttons_layout
            for i in range(layout.count()):
                item = layout.itemAt(i)
                btn_layout = item.layout() if item else None
                if not btn_layout:
                    continue
                for j in range(btn_layout.count()):
                    btn_item = btn_layout.itemAt(j)
                    w = btn_item.widget() if btn_item and btn_item.widget() else None
                    # Only QPushButton has setText; guard with isinstance
                    if w is not None and isinstance(w, QPushButton) and w.property("is_data_button"):
                        w.setText(self._data_button_text())
                break

    def _update_file_tabs(self):
        while self.file_tabs.count(): self.file_tabs.removeTab(0)
        if self.demo_checkbox.isChecked(): self._create_file_tab(tr("tabs.demo"))
        else:
            for tab_name in [tr("tabs.menu_root"), tr("tabs.chapter_1"), tr("tabs.chapter_2"), tr("tabs.chapter_3"), tr("tabs.chapter_4")]: self._create_file_tab(tab_name)
        # After rebuild, also refresh button texts
        self._update_data_add_button_texts()

    def _create_file_tab(self, tab_name):
        tab = QWidget(); layout = QVBoxLayout(tab); buttons_layout = QHBoxLayout()
        # DATA/XDELTA button with dynamic text
        data_button = QPushButton(self._data_button_text())
        data_button.setProperty("is_data_button", True)
        data_button.clicked.connect(lambda: self._add_data_file(tab, layout))
        extra_button = QPushButton(tr("ui.add_extra_files")); extra_button.clicked.connect(lambda: self._add_extra_files(tab, layout))
        for btn in [data_button, extra_button]: buttons_layout.addWidget(btn)
        layout.addLayout(buttons_layout); layout.addStretch(); self.file_tabs.addTab(tab, tab_name)

    def _create_file_frame(self, tab_layout, file_type, key_name=None):
        is_local, is_patch = not self.is_public, self.piracy_checkbox.isChecked()
        if file_type == 'extra' and key_name is None:
            key_name, ok = QInputDialog.getText(self, tr("dialogs.file_group_name"), tr("dialogs.enter_file_group_key"))
            if not ok or not key_name.strip(): return
        if file_type == 'data': self._hide_add_button(tab_layout, "DATA/PATCH")

        frame = QFrame(); frame.setFrameStyle(QFrame.Shape.Box); layout = QVBoxLayout(frame)

        if file_type == 'data':
            title = tr("files.patch_file") if is_patch else tr("files.data_file")
            label_type = tr("files.download_link") if self.is_public else tr("files.path_to")
            file_type_str = "xdelta" if is_patch else "data.win"
            input_label = tr("files.data_path_label", label_type=label_type, file_type=file_type_str)
            version_label = tr("files.version_label", file_type=("PATCH" if is_patch else "DATA"))
            file_filter = get_file_filter("xdelta_files") if is_patch else get_file_filter("data_files")
            browse_title = tr("ui.select_data_file", file_type="xdelta" if is_patch else "data.win")
        else:
            title = tr("files.extra_files_title", key_name=key_name)
            label_type = tr("files.archive_link") if self.is_public else tr("files.path_to")
            input_label = tr("files.archive_path_label", label_type=label_type)
            version_label = tr("files.version")
            file_filter = get_file_filter("archive_files")
            browse_title = tr("ui.select_archive")
        
        # Create and add the title label for both types
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold;")
        if file_type == 'extra' and key_name:
            title_label.setProperty("clean_key", key_name)
            title_label.setProperty("file_type", "extra")
        elif file_type == 'data':
            title_label.setProperty("file_type", "patch" if is_patch else "data")
        layout.addWidget(title_label)
        layout.addWidget(QLabel(input_label))

        if is_local:
            container = QHBoxLayout(); input_edit = QLineEdit(); input_edit.setReadOnly(True); input_edit.setPlaceholderText(tr("ui.select_file"))
            input_edit.setProperty("is_local_path" if file_type == 'data' else "is_local_extra_path", True)
            if file_type == 'extra': input_edit.setProperty("extra_key", key_name)
            container.addWidget(input_edit)
            browse_btn = QPushButton(tr("ui.browse_button")); browse_btn.clicked.connect(lambda: self._browse_file(input_edit, browse_title, file_filter))
            container.addWidget(browse_btn); layout.addLayout(container)
        else:
            input_edit = QLineEdit(); layout.addWidget(input_edit)
            input_edit.textChanged.connect(lambda: self._trigger_validation(input_edit, self._validate_url_for_title, title_label=title_label, is_patch=is_patch if file_type == 'data' else False))

        layout.addWidget(QLabel(version_label))
        version_edit = QLineEdit(); version_edit.setPlaceholderText("1.0.0"); self._setup_version_validation(version_edit); layout.addWidget(version_edit)
        delete_btn = QPushButton(tr("ui.delete_button"))
        delete_btn.clicked.connect(lambda: self._remove_data_file(None, tab_layout, frame) if file_type == 'data' else self._remove_extra_files(tab_layout, frame))
        layout.addWidget(delete_btn); tab_layout.insertWidget(tab_layout.count() - 1, frame)

    def _hide_add_button(self, tab_layout, button_text=None):
        for i in range(tab_layout.count()):
            if (layout_item := tab_layout.itemAt(i)) and layout_item.layout():
                if buttons_layout := layout_item.layout():
                    for j in range(buttons_layout.count()):
                        if (button_item := buttons_layout.itemAt(j)) and button_item.widget():
                            button = button_item.widget()
                            if isinstance(button, QPushButton) and button.property("is_data_button"):
                                button.hide(); return

    def _add_data_file(self, tab, tab_layout):
        # Не даем добавить второй DATA/PATCH фрейм в ту же вкладку
        # Проверяем наличие существующего data/patch фрейма
        for i in range(tab_layout.count()):
            item = tab_layout.itemAt(i)
            w = item.widget() if item else None
            if w is not None and hasattr(w, 'layout'):
                fl = w.layout()
                if fl and fl.count() > 0 and isinstance(fl.itemAt(0).widget(), QLabel):
                    title = fl.itemAt(0).widget()
                    ftype = title.property('file_type') if hasattr(title, 'property') else None
                    txt = title.text() if hasattr(title, 'text') else ''
                    if ftype in ('data','patch') or (isinstance(txt, str) and (txt.startswith('DATA') or txt.startswith('PATCH') or txt.startswith('XDELTA'))):
                        return  # Уже есть один DATA/PATCH
        self._create_file_frame(tab_layout, 'data')
    def _add_extra_files(self, tab, tab_layout): self._create_file_frame(tab_layout, 'extra')

    def _remove_data_file(self, tab, tab_layout, data_frame):
        data_frame.hide(); tab_layout.removeWidget(data_frame); data_frame.deleteLater()
        self._show_add_button(tab_layout)

    def _remove_extra_files(self, tab_layout, extra_frame):
        extra_frame.hide(); tab_layout.removeWidget(extra_frame); extra_frame.deleteLater()

    def _show_add_button(self, tab_layout, button_text=None):
        for i in range(tab_layout.count()):
            if (layout_item := tab_layout.itemAt(i)) and layout_item.layout():
                if buttons_layout := layout_item.layout():
                    for j in range(buttons_layout.count()):
                        if (button_item := buttons_layout.itemAt(j)) and button_item.widget():
                            button = button_item.widget()
                            if isinstance(button, QPushButton) and button.property("is_data_button"):
                                button.show(); break


    def _setup_version_validation(self, line_edit):
        from PyQt6.QtGui import QValidator
        import re
        class VersionValidator(QValidator):
            def validate(self, text, pos):
                if not text: return QValidator.State.Intermediate, text, pos
                return (QValidator.State.Acceptable if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}$', text)
                       else QValidator.State.Intermediate if re.match(r'^\d{0,3}(\.\d{0,3}(\.\d{0,3})?)?$', text)
                       else QValidator.State.Invalid), text, pos
        line_edit.setValidator(VersionValidator()); line_edit.setText("1.0.0")
        def on_text_changed():
            text = line_edit.text()
            if not text: line_edit.setText("1.0.0"); return
            parts = re.sub(r'[^\d\.]', '', text).split('.')
            parts = [(parts[:3] if len(parts) > 3 else parts + ['0'] * (3 - len(parts)) if len(parts) < 3 else parts)]
            parts = [('0' if not part else part[:3]) for part in parts[0]]
            corrected = '.'.join(parts)
            if corrected != text: line_edit.setText(corrected)
        line_edit.textChanged.connect(on_text_changed)

    def _validate_url_for_title(self, line_edit: QLineEdit, title_label: QLabel, is_patch: bool):
        url = line_edit.text().strip()
        line_edit.setProperty("isValid", True)

        # Определяем тип файла по file_type property
        file_type = "data"  # По умолчанию
        base_title = tr("files.data_file")

        # Проверяем file_type property label'а
        if hasattr(title_label, 'property'):
            label_file_type = title_label.property("file_type")
            if label_file_type == "description":
                base_title, file_type = tr("ui.full_description_link"), "description"
            elif label_file_type == "icon":
                base_title, file_type = tr("files.icon_direct_link"), "icon"
            elif label_file_type == "patch" or is_patch:
                base_title, file_type = tr("files.patch_file"), "data"

        # Если не удалось определить по property, проверяем связанный виджет
        if file_type == "data" and hasattr(self, 'description_url_edit') and line_edit == self.description_url_edit:
            base_title, file_type = tr("ui.full_description_link"), "description"
        elif file_type == "data" and hasattr(self, 'icon_edit') and line_edit == self.icon_edit:
            base_title, file_type = tr("files.icon_direct_link"), "icon"

        # Проверяем тип по property, без зависимости от текста локализации
        label_ftype = title_label.property("file_type") if hasattr(title_label, 'property') else None
        if label_ftype == "extra":
            base_title, file_type = tr("files.extra_files_title", key_name=title_label.property("clean_key") or "extra"), "extra"
        else:
            # Fallback: Проверяем на extra files через локализованный ключ (для старых записей)
            clean_text = re.sub('<[^<]+?>', '', title_label.text())
            if tr("files.extra_files") in clean_text or tr("files.extra_files_title", key_name="")[:-2] in clean_text:
                base_title, file_type = clean_text.split(" (")[0], "extra"

        # Иконка: полностью отключаем валидацию и любые подписи рядом с заголовком
        if hasattr(self, 'icon_edit') and line_edit == self.icon_edit:
            title_label.setText(tr("files.icon_direct_link"))
            return

        if not url:
            title_label.setText(base_title)
            return

        line_edit.setProperty("isValid", False)

        signals = WorkerSignals()
        signals.update_label.connect(self.on_validation_complete)
        # Keep a reference to avoid GC while thread is running
        self._last_validation_signals = signals

        def check_url():
            from urllib.parse import urlparse, unquote
            try:
                # Если это иконка и превью уже валидно — не делаем сетевые проверки, сразу зелёный
                if file_type == 'icon' and hasattr(self, 'icon_edit') and self.icon_edit.property('isValid') is True:
                    try:
                        filename = tr("ui.file_generic")
                        p = urlparse(url).path
                        if p and p not in ['/', ''] and not p.endswith('/'):
                            nm = os.path.basename(unquote(p))
                            if nm:
                                filename = nm
                        final_text = f"{base_title}<span style='color: #44AA44;'> ({filename})</span>"; is_valid = True
                        signals.update_label.emit(line_edit, title_label, final_text, is_valid)
                        return
                    except Exception:
                        pass
                # Для иконок используем GET (нужно проверить, что это изображение), для остальных HEAD
                r = None
                if file_type == "icon":
                    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                    r.raise_for_status()
                    headers = r.headers
                else:
                    # Some hosts reject HEAD; fallback to GET if HEAD fails
                    try:
                        rh = requests.head(url, headers={'User-Agent': 'Mozilla/5.0'}, allow_redirects=True, timeout=10)
                        rh.raise_for_status()
                        headers = rh.headers
                    except Exception:
                        rg = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, stream=True, timeout=10)
                        rg.raise_for_status()
                        headers = rg.headers

                # Определяем размер в байтах и тип контента
                size_bytes = int(headers.get('content-length', 0)) if headers.get('content-length', '').isdigit() else 0
                content_type = headers.get('Content-Type', headers.get('content-type', '')).lower()
                # Если это иконка и превью уже валидно — считаем ОК без дополнительных проверок
                if file_type == 'icon' and hasattr(self, 'icon_edit') and self.icon_edit.property('isValid') is True:
                    try:
                        from urllib.parse import urlparse, unquote
                        filename = tr("ui.file_generic")
                        path = urlparse(url).path
                        if path and path not in ['/', ''] and not path.endswith('/'):
                            potential_name = os.path.basename(unquote(path))
                            if potential_name:
                                filename = potential_name
                        # формируем текст и выходим
                        final_text = f"{base_title}<span style='color: #44AA44;'> ({filename})</span>"; is_valid = True
                        signals.update_label.emit(line_edit, title_label, final_text, is_valid)
                        return
                    except Exception:
                        pass
                # Если это иконка и нет content-length, используем фактический размер ответа
                first_bytes = b''
                if file_type == 'icon' and r is not None and size_bytes == 0:
                    size_bytes = len(r.content)
                # Для остальных типов при GET-резерве читаем часть тела для сигнатуры
                if file_type != 'icon' and 'rg' in locals():
                    try:
                        chunk = next(rg.iter_content(chunk_size=16), b'')
                        first_bytes = chunk or b''
                    except Exception:
                        first_bytes = b''

                # Форматирование размера
                try:
                    from localization import get_localization_manager
                    lang = get_localization_manager().get_current_language()
                except Exception:
                    lang = 'en'
                suffix = 'МБ' if lang == 'ru' else 'MB'
                size_text = (f"{(size_bytes / (1024*1024)):.1f} {suffix}" if size_bytes > 0 else f"? {suffix}")

                # Имя файла
                filename = tr("ui.file_generic")
                content_disp = headers.get('Content-Disposition') or headers.get('content-disposition')
                if content_disp:
                    # Сначала filename*
                    mstar = re.search(r"filename\*=UTF-8''([^;]+)", content_disp, re.IGNORECASE)
                    m = re.search(r'filename\s*=\s*"?([^";]+)"?', content_disp, re.IGNORECASE)
                    if mstar:
                        filename = unquote(mstar.group(1), 'utf-8')
                    elif m:
                        filename = m.group(1)
                if filename == tr("ui.file_generic"):
                    if (path := urlparse(url).path) and path not in ["/", ""] and not path.endswith("/"):
                        potential_name = os.path.basename(unquote(path))
                        if potential_name:
                            filename = potential_name

                data_extensions = ['.xdelta'] if is_patch or "PATCH" in base_title else ['.win', '.ios']
                format_checks = {
                    "icon": (None, 2),  # Для иконок не проверяем расширение, только размер (лимит 2 МБ для оффлайн проверки может быть иным)
                    "extra": (['.zip', '.rar', '.7z'], float('inf')),
                    "description": (['.md', '.txt'], 1),
                    "data": (data_extensions, 200)
                }

                if file_type in format_checks:
                    valid_exts, max_size = format_checks[file_type]

                    # Иконки: проверяем, что это действительно изображение
                    if file_type == "icon":
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
                    else:
                        # Строгая проверка: расширение недостаточно; запрещаем text/html и проверяем сигнатуры, где возможно
                        if 'text/html' in content_type:
                            final_text = f"{base_title}<span style='color: #FF4444;'> ({tr('errors.not_a_file_response')})</span>"; is_valid = False
                        elif file_type == 'data' and (is_patch or "PATCH" in base_title):
                            # XDELTA: проверяем сигнатуру VCD, расширение .xdelta или тип контента
                            xdelta_by_sig = first_bytes.startswith(b'VCD')
                            xdelta_by_ext = filename.lower().endswith('.xdelta')
                            xdelta_by_ct  = any(x in content_type for x in ['xdelta', 'vcdiff']) or content_type == 'application/octet-stream'
                            if xdelta_by_sig or xdelta_by_ext or xdelta_by_ct:
                                final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"; is_valid = True
                            else:
                                # Как для extra файлов — если URL доступен, считаем ок (резервный вариант)
                                final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"; is_valid = True
                        elif file_type == 'extra':
                            # ZIP/RAR/7Z сигнатуры
                            is_zip = first_bytes.startswith(b'PK\x03\x04')
                            is_rar = first_bytes.startswith(b'Rar!')
                            is_7z  = first_bytes.startswith(b'7z\xBC\xAF\x27\x1C')
                            if is_zip or is_rar or is_7z:
                                final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"; is_valid = True
                            else:
                                # Больше не валим по сигнатуре — если URL доступен, считаем ок
                                final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"; is_valid = True
                        elif file_type == 'description':
                            # description файлы — требуем расширение .md или .txt
                            fn = filename.lower()
                            correct_ext = fn.endswith('.md') or fn.endswith('.txt')
                            if correct_ext and size_bytes >= 0 and 'text/html' not in content_type:
                                final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"; is_valid = True
                            else:
                                final_text = f"{base_title}<span style='color: #FF4444;'> ({tr('errors.not_a_valid_file')})</span>"; is_valid = False
                        elif file_type == 'data':
                            # data.win/game.ios — проверяем и расширение, и сигнатуру файла
                            fn = filename.lower()
                            correct_ext = fn.endswith('.win') or fn.endswith('.ios')
                            
                            # Проверяем сигнатуры для data файлов
                            # Для .win и .ios файлов DELTARUNE используются различные форматы
                            # Проверим распространенные сигнатуры
                            valid_by_signature = False
                            if first_bytes:
                                # Добавляем дополнительные проверки на основе content-type
                                if content_type == 'application/octet-stream':
                                    valid_by_signature = True
                                # Можно добавить специфичные сигнатуры если знаем формат
                            
                            if (correct_ext or valid_by_signature) and size_bytes >= 0 and 'text/html' not in content_type:
                                final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"; is_valid = True
                            else:
                                final_text = f"{base_title}<span style='color: #FF4444;'> ({tr('errors.not_a_valid_file')})</span>"; is_valid = False

                    if is_valid and (size_bytes / (1024*1024)) > max_size and max_size != float('inf'):
                        final_text = f"{base_title}<span style='color: #FF4444;'> ({tr('errors.file_too_large', max_size=max_size)})</span>"; is_valid = False
                else:
                    final_text = f"{base_title}<span style='color: #44AA44;'> ({filename}, {size_text})</span>"
                    is_valid = True

            except Exception:
                final_text = f"{base_title}<span style='color: #FF4444;'> ({tr('errors.url_error')})</span>"
                is_valid = False

            signals.update_label.emit(line_edit, title_label, final_text, is_valid)

        threading.Thread(target=check_url, daemon=True).start()


    def on_validation_complete(self, line_edit: QLineEdit, label: QLabel, text: str, is_valid: bool):
        """Слот, который обновляет и текст метки, и флаг валидности поля."""
        # Абсолютное правило для иконки: если превью не загрузилось, поле всегда невалидно
        try:
            # Для иконки не меняем заголовок и не выставляем никаких статусов здесь
            if hasattr(self, 'icon_edit') and line_edit == self.icon_edit:
                text = tr('files.icon_direct_link')
                is_valid = True
        except Exception:
            pass
        if label and not sip.isdeleted(label):
            label.setText(text)
        if line_edit and not sip.isdeleted(line_edit):
            line_edit.setProperty("isValid", is_valid)

    def _browse_file(self, line_edit, title, file_filter):
        if file_path := QFileDialog.getOpenFileName(self, title, "", file_filter)[0]: line_edit.setText(file_path)


    def _add_extra_files_with_data(self, tab, tab_layout, key_name, url, version):
        self._create_file_frame(tab_layout, 'extra', key_name)
        for i in range(tab_layout.count() - 1, -1, -1):
            if (item := tab_layout.itemAt(i)) and item.widget() and hasattr(item.widget(), 'layout'):
                frame_layout = item.widget().layout()
                url_edit = version_edit = None
                for j in range(frame_layout.count()):
                    widget = frame_layout.itemAt(j).widget() if frame_layout.itemAt(j) else None
                    if isinstance(widget, QLineEdit):
                        prev_widget = frame_layout.itemAt(j-1).widget() if j > 0 and frame_layout.itemAt(j-1) else None
                        if isinstance(prev_widget, QLabel):
                            field_type = detect_field_type_by_text(prev_widget.text())
                            if field_type == "file_path": url_edit = widget
                            elif field_type == "version": version_edit = widget
                if url_edit and version_edit:
                    url_edit.setText(url); version_edit.setText(version or '1.0.0'); return

    def _add_local_extra_files_frame_with_data(self, tab, tab_layout, key_name, filenames):
        """Добавляет локальные дополнительные файлы с данными."""
        # Create the frame and then populate it similar to _select_local_extra_files
        self._create_file_frame(tab_layout, 'extra', key_name)
        # Find the last inserted frame in the tab layout and populate with filenames
        for i in range(tab_layout.count() - 1, -1, -1):
            item = tab_layout.itemAt(i)
            if item and item.widget() and hasattr(item.widget(), 'layout'):
                frame = item.widget()
                frame_layout = frame.layout()
                # Ensure title has proper properties
                if frame_layout and isinstance(frame_layout.itemAt(0).widget(), QLabel):
                    title = frame_layout.itemAt(0).widget()
                    if title.property("clean_key") == key_name:
                        # Add file labels and hidden QLineEdits with properties so _extract_local_frame_data can read them
                        for fn in filenames:
                            file_label = QLabel(f"• {os.path.basename(fn)}")
                            file_label.setStyleSheet("color: gray; font-size: 10px;")
                            frame_layout.addWidget(file_label)
                            path_edit = QLineEdit()
                            path_edit.setText(fn)
                            path_edit.hide()
                            path_edit.setProperty("is_local_extra_path", True)
                            path_edit.setProperty("extra_key", key_name)
                            frame_layout.addWidget(path_edit)
                        return

    def _fill_local_data_file_in_tab(self, tab, file_path, version):
        """Заполняет последний добавленный DATA фрейм в табе данными."""
        for i in range(tab.layout().count() - 1, -1, -1):
            if (item := tab.layout().itemAt(i)) and item.widget() and hasattr(item.widget(), 'layout'):
                if frame_layout := item.widget().layout():
                    for j in range(frame_layout.count()):
                        if (frame_item := frame_layout.itemAt(j)) and frame_item.layout():
                            for k in range(frame_item.layout().count()):
                                if (container_item := frame_item.layout().itemAt(k)) and container_item.widget() and isinstance(container_item.widget(), QLineEdit):
                                    container_widget = container_item.widget()
                                    if container_widget.property("is_local_path"):
                                        folder_name = self.mod_data.get("folder_name", "")
                                        full_path = os.path.join(self.parent_app.mods_dir, folder_name, file_path) if folder_name and not os.path.isabs(file_path) else file_path
                                        container_widget.setText(full_path)
                                        for l in range(j + 1, frame_layout.count()):
                                            if (version_item := frame_layout.itemAt(l)) and version_item.widget() and isinstance(version_item.widget(), QLineEdit) and not version_item.widget().isReadOnly():
                                                version_item.widget().setText(version or "1.0.0")
                                                return
                                        return



    def _create_action_buttons(self, parent_layout):
        buttons_layout = QHBoxLayout()
        if self.is_creating:
            cancel_button = QPushButton(tr("ui.cancel_button")); cancel_button.clicked.connect(self._on_cancel_clicked); buttons_layout.addWidget(cancel_button)
            buttons_layout.addStretch()
            self.save_button = QPushButton(tr("ui.finish_creation")); self.save_button.clicked.connect(self._save_mod); buttons_layout.addWidget(self.save_button)
        else:
            cancel_button = QPushButton(tr("ui.cancel_button")); cancel_button.clicked.connect(self._on_cancel_clicked); buttons_layout.addWidget(cancel_button)
            buttons_layout.addSpacing(10)
            if self.is_public:
                self.hide_mod_button = QPushButton(tr("ui.hide_mod_button")); self.hide_mod_button.clicked.connect(self._toggle_mod_visibility)
                buttons_layout.addWidget(self.hide_mod_button); buttons_layout.addSpacing(10)
            delete_button = QPushButton(tr("ui.delete_local_mod") if not self.is_public else tr("ui.delete_mod"))
            delete_button.setStyleSheet("background-color: darkred; color: white;"); delete_button.clicked.connect(self._delete_mod)
            buttons_layout.addWidget(delete_button); buttons_layout.addStretch()
            self.save_button = QPushButton(tr("ui.save_changes")); self.save_button.clicked.connect(self._save_mod); buttons_layout.addWidget(self.save_button)
        parent_layout.addLayout(buttons_layout)

    def _on_cancel_clicked(self):
        if QMessageBox.question(self, tr("dialogs.cancel_changes"), tr("dialogs.unsaved_changes_lost")) == QMessageBox.StandardButton.Yes: self.reject()

    def _on_icon_url_changed(self):
        url = self.icon_edit.text().strip()
        if url and url != self.current_icon_url: self.current_icon_url = url; self._load_icon_preview(url)

    def _load_icon_preview(self, url):
        if not url.strip(): self._load_default_icon(); return
        try:
            self.icon_preview.setText(tr("status.loading"))
            from PyQt6.QtCore import QThread, pyqtSignal
            class IconLoader(QThread):
                loaded, failed = pyqtSignal(QPixmap, str), pyqtSignal(str)
                def __init__(self, url): super().__init__(); self.url = url
                def run(self):
                    try:
                        import requests; response = requests.get(self.url, timeout=10); response.raise_for_status(); pixmap = QPixmap()
                        if pixmap.loadFromData(response.content): self.loaded.emit(pixmap, self.url)
                        else: self.failed.emit(self.url)
                    except Exception: self.failed.emit(self.url)
            current_url = url
            self.icon_loader = IconLoader(url)
            self.icon_loader.loaded.connect(lambda pm, u: self._on_icon_loaded(pm) if u == self.current_icon_url else None)
            self.icon_loader.failed.connect(lambda u: (self._on_icon_load_failed(u) if u == self.current_icon_url else None))
            self.icon_loader.start()
        except Exception: self._load_default_icon()

    def _on_icon_loaded(self, pixmap):
        # Успешная загрузка иконки — считаем ссылку валидной (для публичных модов)
        # Помечаем превью как пользовательское изображение
        try:
            self.icon_preview.setProperty('isDefaultIcon', False)
        except Exception:
            pass
        # Обрезаем изображение под квадрат
        size = min(pixmap.width(), pixmap.height())
        cropped = pixmap.copy((pixmap.width() - size) // 2, (pixmap.height() - size) // 2, size, size)
        self.icon_preview.setPixmap(cropped.scaled(64, 64, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))
        # Не добавляем подписи рядом с заголовком для иконки

    def _on_icon_load_failed(self, url: str):
        # При ошибке загрузки иконки: показываем дефолт и помечаем ссылку как невалидную
        self._load_default_icon()
        if self.is_public and hasattr(self, 'icon_edit'):
            self.icon_edit.setProperty("isValid", False)
        # Обновляем заголовок иконки, если есть
        if self.is_public and hasattr(self, 'icon_title_label'):
            base_title = tr("files.icon_label")
            error_text = tr('errors.not_an_image')
            self.icon_title_label.setText(f"{base_title}<span style='color: #FF4444;'> ({error_text})</span>")

    def _load_default_icon(self):
        try:
            logo_path = resource_path("assets/icon.ico")
            if os.path.exists(logo_path) and not (pixmap := QPixmap(logo_path)).isNull():
                self.icon_preview.setPixmap(pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.icon_preview.setProperty('isDefaultIcon', True)
                return
        except Exception as e:
            logging.warning(f"Load default icon preview failed: {e}")
        self.icon_preview.setText(tr("status.deltarune_logo"))
        try:
            self.icon_preview.setProperty('isDefaultIcon', True)
        except Exception:
            pass

    def _browse_local_icon(self):
        file_path, _ = QFileDialog.getOpenFileName(self, tr("ui.select_icon_file"), "", get_file_filter("image_files"))
        if file_path: self.icon_edit.setText(file_path); self._load_local_icon_preview(file_path)

    def _load_local_icon_preview(self, file_path):
        try:
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                # Помечаем как не дефолт
                try:
                    self.icon_preview.setProperty('isDefaultIcon', False)
                except Exception:
                    pass
                # Обрезаем изображение под квадрат
                size = min(pixmap.width(), pixmap.height())
                cropped = pixmap.copy((pixmap.width() - size) // 2, (pixmap.height() - size) // 2, size, size)
                self.icon_preview.setPixmap(cropped.scaled(64, 64, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))
            else: self.icon_preview.setText(tr("status.loading_error"))
        except Exception: self.icon_preview.setText(tr("status.loading_error"))

    def _show_verification_details(self):
        """Показывает детали верификации."""
        details_url = "https://example.com/verification-details"
        webbrowser.open(details_url)

    def _toggle_mod_visibility(self):
        if not hasattr(self, 'mod_key') or not self.mod_key:
            QMessageBox.critical(self, tr("dialogs.error"), tr("dialogs.mod_key_error"))
            return

        current_hidden = self.mod_data.get('hide_mod', False)
        new_state = not current_hidden

        try:
            from helpers import DATA_FIREBASE_URL
            import requests

            from helpers import _fb_url
            response = requests.get(_fb_url(DATA_FIREBASE_URL, f"mods/{self.mod_key}"), timeout=10)
            if response.status_code == 200:
                current_data = response.json()
                if current_data:
                    current_data['hide_mod'] = new_state
                    from helpers import format_timestamp
                    current_data['last_updated'] = format_timestamp()

                    update_response = requests.put(_fb_url(DATA_FIREBASE_URL, f"mods/{self.mod_key}"),
                                                 json=current_data, timeout=10)
                    update_response.raise_for_status()
                    # Verify the flag actually changed on the server
                    verify_resp = requests.get(_fb_url(DATA_FIREBASE_URL, f"mods/{self.mod_key}"), timeout=8)
                    if verify_resp.status_code == 200 and isinstance(verify_resp.json(), dict) and verify_resp.json().get('hide_mod') == new_state:
                        self.mod_data['hide_mod'] = new_state
                        if hasattr(self, 'hide_mod_button'):
                            self.hide_mod_button.setText(tr("ui.show_mod") if new_state else tr("ui.hide_mod"))
                        QMessageBox.information(self, tr("dialogs.updated"),
                                              tr("dialogs.mod_visibility_changed", state=tr("ui.hidden_from_list") if new_state else tr("ui.shown_in_list")))
                    else:
                        QMessageBox.critical(self, tr("dialogs.update_error"), tr("dialogs.update_verification_failed"))
                else:
                    QMessageBox.warning(self, tr("dialogs.error"), tr("dialogs.mod_not_found"))
            else:
                QMessageBox.warning(self, tr("dialogs.error"), tr("dialogs.failed_to_get_mod_data"))

        except Exception as e:
            QMessageBox.critical(self, tr("dialogs.update_error"),
                               tr("dialogs.failed_to_update_mod", error=str(e)))



    def _save_mod(self):
        """Сохраняет мод."""
        # Сначала быстрая валидация обязательных полей
        if not self._validate_fields():
            return
        # Жесткая повторная валидация текущих значений (не опираемся на флаги UI)
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
            QMessageBox.warning(self, tr("dialogs.error"), tr("dialogs.mod_name_empty")); return False
        if self.is_public and not self.author_edit.text().strip():
            QMessageBox.warning(self, tr("dialogs.error"), tr("dialogs.mod_author_empty")); return False
        if len(self.version_edit.text().strip()) > 10:
            QMessageBox.warning(self, tr("dialogs.error"), tr("dialogs.mod_version_too_long")); return False
        # Публичные: иконка и полное описание НЕ обязательны здесь; их проверяем на этапе финальной валидации,
        # и только если поля не пустые.
        if self.is_public:
            pass
        if hasattr(self, 'tag_other') and not any([self.tag_translation.isChecked(), self.tag_customization.isChecked(), self.tag_gameplay.isChecked(), self.tag_other.isChecked()]):
            self.tag_other.setChecked(True)
        return self._validate_file_data()

    def _validate_file_data(self):
        return self._validate_public_file_data() if self.is_public else self._validate_local_file_data()

    def _revalidate_on_save(self) -> bool:
        """Повторно валидирует поля при нажатии Сохранить/Завершить, не полагаясь на UI-флаги."""
        try:
            import re
            import requests
            from urllib.parse import unquote
            # 1) Публичные: новая логика валидации иконки
            if self.is_public and hasattr(self, 'icon_edit') and hasattr(self, 'icon_preview'):
                icon_url = self.icon_edit.text().strip()
                is_default = bool(self.icon_preview.property('isDefaultIcon'))
                # Пустое поле и дефолтное превью — допустимо
                # Незапустое поле и дефолтное превью — ошибка
                if icon_url and is_default:
                    QMessageBox.warning(self, tr("dialogs.validation_error"), tr('errors.icon_invalid'))
                    return False
                # 2) Публичные: описание — строгий .md/.txt (если поле не пусто)
                desc_url = self.description_url_edit.text().strip()
                if desc_url and not re.match(r'^https?://.+\.(md|txt)(\?.*)?$', desc_url, re.IGNORECASE):
                    # Разрешаем, если по заголовкам это текст
                    try:
                        h = requests.head(desc_url, headers={'User-Agent': 'Mozilla/5.0'}, allow_redirects=True, timeout=6)
                        ct = (h.headers.get('Content-Type') or '').lower()
                        if not (ct.startswith('text/') or 'markdown' in ct):
                            raise ValueError('not text')
                    except Exception:
                        QMessageBox.warning(self, tr("dialogs.validation_error"), tr('errors.description_md_txt_required'))
                        return False
                # 3) Строгая валидация ссылок файлов во вкладках (без UI-флагов)
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
                        # title label
                        title_item = frame_layout.itemAt(0)
                        title_label = title_item.widget() if title_item and title_item.widget() else None
                        if not isinstance(title_label, QLabel):
                            continue
                        # Collect URL and version edits
                        url_edit = version_edit = None
                        for k in range(frame_layout.count()):
                            sub = frame_layout.itemAt(k)
                            subw = sub.widget() if sub else None
                            if isinstance(subw, QLineEdit):
                                # Look at prev widget to classify
                                prev_item = frame_layout.itemAt(k-1) if k > 0 else None
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
                            # пустая строка допускается, пропускаем блок
                            continue
                        # Determine frame type
                        label_ftype = title_label.property('file_type') if hasattr(title_label, 'property') else None
                        is_patch = (label_ftype == 'patch')
                        is_extra = (label_ftype == 'extra')
                        # Request
                        headers = {'User-Agent': 'Mozilla/5.0'}
                        # First try HEAD
                        content_type = ''
                        size_bytes = 0
                        first_bytes = b''
                        ok = False
                        try:
                            h = requests.head(url, headers=headers, allow_redirects=True, timeout=8)
                            if h.status_code in (200, 206, 301, 302, 303, 307, 308):
                                ok = True
                                ct = h.headers.get('Content-Type') or h.headers.get('content-type') or ''
                                content_type = ct.lower()
                                cb = h.headers.get('content-length', '')
                                size_bytes = int(cb) if cb.isdigit() else 0
                                content_disp = h.headers.get('content-disposition', '')
                            else:
                                content_disp = ''
                        except Exception:
                            ok, content_disp = False, ''
                        if not ok:
                            try:
                                g = requests.get(url, headers=headers, allow_redirects=True, stream=True, timeout=12)
                                g.raise_for_status()
                                ct = g.headers.get('Content-Type') or g.headers.get('content-type') or ''
                                content_type = ct.lower()
                                cb = g.headers.get('content-length', '')
                                size_bytes = int(cb) if cb.isdigit() else 0
                                content_disp = g.headers.get('content-disposition', '')
                                try:
                                    first_bytes = next(g.iter_content(chunk_size=16), b'') or b''
                                except Exception:
                                    first_bytes = b''
                                ok = True
                            except Exception:
                                ok = False
                        if not ok:
                            QMessageBox.warning(self, tr("dialogs.validation_error"), tr("dialogs.validation_url_error", url=url))
                            return False
                        # Вспомогательная логика: имя файла и расширение из URL/заголовка
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
                        # Relaxed checks
                        if is_patch:
                            xdelta_by_sig = first_bytes.startswith(b'VCD')
                            xdelta_by_ct = any(x in content_type for x in ['xdelta', 'vcdiff']) or content_type == 'application/octet-stream'
                            xdelta_by_ext = fext == '.xdelta'
                            if not (xdelta_by_sig or xdelta_by_ct or xdelta_by_ext):
                                QMessageBox.warning(self, tr("dialogs.validation_error"), ".xdelta " + tr('errors.not_a_valid_file'))
                                return False
                        elif is_extra:
                            sig_ok = first_bytes.startswith(b'PK\x03\x04') or first_bytes.startswith(b'Rar!') or first_bytes.startswith(b"7z\xBC\xAF'\x1C")
                            by_ext = fext in ['.zip', '.rar', '.7z']
                            by_ct = any(x in content_type for x in ['zip', 'x-zip', 'rar', '7z']) or content_type == 'application/octet-stream'
                            if not (sig_ok or by_ext or by_ct):
                                # Больше не блокируем по сигнатуре — принимаем, если доступно по сети
                                pass
                        else:
                            # data.win / game.ios
                            looks_like_data = any(x in fext for x in ['.win', '.ios', '.data'])
                            if 'text/html' in content_type and not looks_like_data:
                                QMessageBox.warning(self, tr("dialogs.validation_error"), tr('errors.not_a_valid_file'))
                                return False
                        # version required if URL is present
                        if version_edit and not version_edit.text().strip():
                            QMessageBox.warning(self, tr("dialogs.validation_error"), tr("dialogs.tab_no_version", tab_name=self.file_tabs.tabText(i)))
                            return False
            else:
                # Локальные моды: проверяем что файлы существуют
                if not self._validate_local_file_data():
                    return False
            return True
        except Exception:
            return False

    def _validate_public_file_data(self):
        import re
        url_pattern, version_pattern, has_any_files = re.compile(r'^https?://.*', re.IGNORECASE), re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}$'), False
        for i in range(self.file_tabs.count()):
            tab, tab_name = self.file_tabs.widget(i), self.file_tabs.tabText(i)
            if not tab or not (layout := tab.layout()): continue
            for j in range(layout.count()):
                if not (item := layout.itemAt(j)) or not (widget := item.widget()) or not hasattr(widget, 'layout') or not (frame_layout := widget.layout()): continue
                # Find title label by checking its file_type property for robustness across locales
                title_label = None
                for k in range(frame_layout.count()):
                    item_k = frame_layout.itemAt(k)
                    w_k = item_k.widget() if item_k else None
                    if isinstance(w_k, QLabel):
                        ftype = w_k.property("file_type") if hasattr(w_k, 'property') else None
                        if ftype in ("data", "patch", "extra"):
                            title_label = w_k
                            break
                if not title_label:
                    # Fallback to text-based detection for legacy frames
                    title_label = next((w for k in range(frame_layout.count())
                                       if (it := frame_layout.itemAt(k)) and (w := it.widget()) and isinstance(w, QLabel)
                                       and any((isinstance(w.text(), str) and w.text().startswith(prefix)) for prefix in ["DATA", "PATCH", "XDELTA", tr("files.extra_files")])
                                      ), None)
                if not title_label:
                    continue
                url_edit = version_edit = None
                for k in range(frame_layout.count()):
                    if not (frame_item := frame_layout.itemAt(k)) or not (frame_widget := frame_item.widget()) or not isinstance(frame_widget, QLineEdit): continue
                    if k > 0 and (prev_item := frame_layout.itemAt(k-1)) and (prev_widget := prev_item.widget()) and isinstance(prev_widget, QLabel):
                        field_type = detect_field_type_by_text(prev_widget.text())
                        if field_type == "file_path": url_edit = frame_widget
                        elif field_type == "version": version_edit = frame_widget
                if url_edit and version_edit:
                    url_text, version_text = url_edit.text().strip(), version_edit.text().strip()
                    if url_text or version_text:
                        has_any_files = True
                        if not url_text:
                            QMessageBox.warning(self, tr("dialogs.validation_error"), tr("dialogs.tab_no_file_url", tab_name=tab_name)); return False
                        if not url_pattern.match(url_text):
                            QMessageBox.warning(self, tr("dialogs.validation_error"), tr("dialogs.tab_invalid_url", tab_name=tab_name)); return False
                        # Проверка доступности URL (устойчивая к 405/403 на HEAD)
                        try:
                            ok = False
                            headers = {'User-Agent': 'Mozilla/5.0'}
                            # 1) HEAD с редиректами
                            try:
                                h = requests.head(url_text, headers=headers, allow_redirects=True, timeout=7)
                                if h.status_code in (200, 206):
                                    ok = True
                                elif h.status_code in (301, 302, 303, 307, 308):
                                    ok = True  # allow redirect chains
                            except Exception:
                                pass
                            # 2) Если HEAD не дал ОК — пробуем GET (stream) и читаем чуть-чуть
                            if not ok:
                                try:
                                    g = requests.get(url_text, headers=headers, allow_redirects=True, stream=True, timeout=10)
                                    if g.status_code in (200, 206):
                                        # читаем первый chunk чтобы убедиться в доступности
                                        next(g.iter_content(chunk_size=1), None)
                                        ok = True
                                except Exception:
                                    ok = False
                            if not ok:
                                QMessageBox.warning(self, tr("dialogs.validation_error"), tr("dialogs.tab_file_unavailable", tab_name=tab_name, url=url_text)); return False
                        except Exception:
                            QMessageBox.warning(self, tr("dialogs.validation_error"), tr("dialogs.tab_file_unavailable", tab_name=tab_name, url=url_text)); return False
                        if not version_text:
                            QMessageBox.warning(self, tr("dialogs.validation_error"), tr("dialogs.tab_no_version", tab_name=tab_name)); return False
                        if not version_pattern.match(version_text):
                            QMessageBox.warning(self, tr("dialogs.validation_error"), tr("dialogs.tab_invalid_version", tab_name=tab_name)); return False
        if not has_any_files:
            QMessageBox.warning(self, tr("dialogs.validation_error"), tr("dialogs.mod_must_have_files")); return False
        return True

    def _validate_local_file_data(self):
        for i in range(self.file_tabs.count()):
            tab, tab_name = self.file_tabs.widget(i), self.file_tabs.tabText(i)
            if not tab or not (layout := tab.layout()): continue
            for j in range(layout.count()):
                if not (item := layout.itemAt(j)) or not (widget := item.widget()) or not hasattr(widget, 'layout') or not (frame_layout := widget.layout()): continue
                if not (frame_data := self._extract_local_frame_data(frame_layout)): continue
                if (path := frame_data.get('path')) and not os.path.exists(path):
                    QMessageBox.warning(self, tr("dialogs.validation_error"), tr("dialogs.tab_file_not_found", tab_name=tab_name, path=path)); return False
                for path in frame_data.get('paths', []):
                    if not os.path.exists(path):
                        QMessageBox.warning(self, tr("dialogs.validation_error"), tr("dialogs.tab_extra_file_not_found", tab_name=tab_name, path=path)); return False
        return True



    def _browse_for_local_file(self, path_edit: QLineEdit):
        is_patch = self.piracy_checkbox.isChecked()
        title, filters = (tr("ui.select_patch_file_xdelta"), get_file_filter("xdelta_files")) if is_patch else (tr("ui.select_data_file"), get_file_filter("data_files"))
        if not (file_path := QFileDialog.getOpenFileName(self, title, "", filters)[0]): return
        filename = os.path.basename(file_path).lower()
        try:
            with open(file_path, 'rb') as f: is_vcd = f.read(3) == b'VCD'
            if is_patch and (not filename.endswith('.xdelta') or not is_vcd):
                QMessageBox.warning(self, tr("dialogs.error"), tr("dialogs.invalid_xdelta_file")); return
            if not is_patch and is_vcd:
                QMessageBox.warning(self, tr("dialogs.error"), tr("dialogs.data_cannot_be_xdelta")); return
        except Exception as e:
            QMessageBox.warning(self, tr("dialogs.error"), tr("dialogs.file_read_error", error=str(e))); return
        path_edit.setText(file_path)



    def _show_file_info(self, tab_layout, title_text, url, version):
        """Объединенный метод для показа информации о файлах."""
        frame = QFrame(); frame.setFrameStyle(QFrame.Shape.Box); layout = QVBoxLayout(frame)
        title = QLabel(title_text); title.setStyleSheet("font-weight: bold;"); layout.addWidget(title)
        url_label = QLabel(f"URL: {url}"); url_label.setStyleSheet("color: gray; font-size: 10px; word-wrap: true;")
        url_label.setWordWrap(True); layout.addWidget(url_label)
        version_label = QLabel(f"{tr('ui.version_colon')} {version}"); version_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(version_label); tab_layout.insertWidget(tab_layout.count() - 1, frame)







    def _select_local_extra_files(self, tab, tab_layout):
        """Выбирает локальные дополнительные файлы через диалог."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("ui.select_additional_files"),
            "",
            get_file_filter("extended_archives")
        )

        if file_paths:
            key_name, ok = QInputDialog.getText(self, tr("dialogs.file_group_name"),
                                              tr("dialogs.enter_file_group_key"))
            if not ok or not key_name.strip():
                return

            extra_frame = QFrame()
            extra_frame.setFrameStyle(QFrame.Shape.Box)
            extra_layout = QVBoxLayout(extra_frame)

            title = QLabel(tr("ui.extra_files_title", key_name=key_name))
            title.setStyleSheet("font-weight: bold;")
            title.setProperty("clean_key", key_name)
            extra_layout.addWidget(title)

            import os
            for file_path in file_paths:
                filename = os.path.basename(file_path)
                file_label = QLabel(f"• {filename}")
                file_label.setStyleSheet("color: gray; font-size: 10px;")
                extra_layout.addWidget(file_label)

                path_edit = QLineEdit()
                path_edit.setText(file_path)
                path_edit.hide()
                path_edit.setProperty("file_path", True)
                path_edit.setProperty("extra_key", key_name)
                extra_layout.addWidget(path_edit)

            delete_button = QPushButton(tr("ui.delete_button"))
            delete_button.clicked.connect(lambda: self._remove_local_extra_files(tab_layout, extra_frame))
            extra_layout.addWidget(delete_button)
            tab_layout.insertWidget(tab_layout.count() - 1, extra_frame)



    def _remove_local_data_file(self, tab, tab_layout, data_frame):
        data_frame.hide(); tab_layout.removeWidget(data_frame); data_frame.deleteLater()

    def _remove_local_extra_files(self, tab_layout, extra_frame):
        extra_frame.hide(); tab_layout.removeWidget(extra_frame); extra_frame.deleteLater()



    def _collect_files_from_tabs(self):
        files_data = {}


        if self.is_public:
            if self.demo_checkbox.isChecked():
                tab_keys = ["demo"]
            else:
                tab_keys = ["menu", "chapter_1", "chapter_2", "chapter_3", "chapter_4"]
        else:
            if self.demo_checkbox.isChecked():
                tab_keys = ["-1"]
            else:
                tab_keys = ["0", "1", "2", "3", "4"]

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
                            tab_files['data_win_url'] = frame_data['url']
                            tab_files['data_win_version'] = frame_data['version']
                        elif frame_data['type'] == 'extra':
                            if 'extra' not in tab_files:
                                tab_files['extra'] = {}
                            tab_files['extra'][frame_data['key']] = {
                                'url': frame_data['url'],
                                'version': frame_data['version']
                            }
                else:
                    local_data = self._extract_local_frame_data(frame_layout)
                    if not local_data:
                        continue

                    if local_data['type'] == 'data' and local_data.get('path'):
                        tab_files['data_win_url'] = local_data['path']
                        tab_files['data_win_version'] = local_data.get('version', '1.0.0')

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

        # Найти заголовок по свойству file_type (надёжно при локализации)
        for i in range(frame_layout.count()):
            item = frame_layout.itemAt(i)
            if not item or not item.widget():
                continue
            w = item.widget()
            if isinstance(w, QLabel):
                ftype = w.property("file_type") if hasattr(w, 'property') else None
                if ftype in ("data", "patch", "extra"):
                    title_label = w
                    break
        # Фолбэк: по тексту (для старых записей/UI)
        if not title_label:
            for i in range(frame_layout.count()):
                item = frame_layout.itemAt(i)
                if not item or not item.widget():
                    continue
                w = item.widget()
                if isinstance(w, QLabel):
                    txt = w.text()
                    if isinstance(txt, str) and (txt.startswith("DATA") or txt.startswith("PATCH") or txt.startswith("XDELTA") or txt.startswith(tr("files.extra_files"))):
                        title_label = w
                        break

        # Собрать поля URL/Version
        for i in range(frame_layout.count()):
            item = frame_layout.itemAt(i)
            if not item or not item.widget():
                continue
            widget = item.widget()
            if isinstance(widget, QLineEdit):
                prev_item = frame_layout.itemAt(i-1)
                if prev_item and prev_item.widget():
                    prev_widget = prev_item.widget()
                    if isinstance(prev_widget, QLabel):
                        field_type = detect_field_type_by_text(prev_widget.text())
                        if field_type == "file_path":
                            url_edit = widget
                        elif field_type == "version":
                            version_edit = widget

        if title_label and url_edit and version_edit:
            url_text = url_edit.text().strip()
            version_text = version_edit.text().strip()
            if url_text and version_text:
                frame_data = {'url': url_text, 'version': version_text}
                # Определяем тип по свойству, затем по тексту
                ftype = title_label.property("file_type") if hasattr(title_label, 'property') else None
                if ftype in ("data", "patch"):
                    frame_data['type'] = 'data'
                elif ftype == 'extra':
                    frame_data['type'] = 'extra'
                    frame_data['key'] = title_label.property("clean_key") or 'extra'
                else:
                    t = title_label.text()
                    if t.startswith("DATA") or t.startswith("PATCH") or t.startswith("XDELTA"):
                        frame_data['type'] = 'data'
                    elif t.startswith(tr("files.extra_files")):
                        key = title_label.property("clean_key") or t.replace(tr("files.extra_files"), "").strip()
                        frame_data['type'] = 'extra'
                        frame_data['key'] = key
                return frame_data

        return None

    def _extract_local_frame_data(self, frame_layout):
        title_widget = frame_layout.itemAt(0).widget()
        if not isinstance(title_widget, QLabel): return None
        title_text = title_widget.text()
        if "DATA" in title_text or "PATCH" in title_text: frame_type = 'data'
        elif detect_field_type_by_text(title_text) == "extra_files": frame_type = 'extra'
        else: return None

        def _find_widget_by_property(layout, widget_type, prop_name, prop_value=True):
            for i in range(layout.count()):
                if not (item := layout.itemAt(i)): continue
                if (widget := item.widget()) and isinstance(widget, widget_type) and widget.property(prop_name) == prop_value:
                    return widget
                if (nested_layout := item.layout()):
                    if result := _find_widget_by_property(nested_layout, widget_type, prop_name, prop_value):
                        return result
            return None

        if frame_type == 'data':
            if (path_edit := _find_widget_by_property(frame_layout, QLineEdit, "is_local_path")) and path_edit.text():
                return {'type': 'data', 'path': path_edit.text()}
        elif frame_type == 'extra':
            if (extra_edit := _find_widget_by_property(frame_layout, QLineEdit, "is_local_extra_path")) and extra_edit.text():
                key = extra_edit.property("extra_key") or "extra_files"
                return {'type': 'extra', 'key': key, 'paths': [extra_edit.text()]}
            if (list_widget := frame_layout.findChild(QListWidget)) and list_widget.property("is_local_extra_list"):
                key = list_widget.property("extra_key")
                paths = [list_widget.item(i).text() for i in range(list_widget.count())]
                if paths: return {'type': 'extra', 'key': key, 'paths': paths}
        return None


    def _collect_mod_data(self):
        tags = []
        if self.tag_translation.isChecked():
            tags.append("translation")
        if self.tag_customization.isChecked():
            tags.append("customization")
        if self.tag_gameplay.isChecked():
            tags.append("gameplay")
        if self.tag_other.isChecked():
            tags.append("other")

        files_data = self._collect_files_from_tabs()
        author = self.author_edit.text().strip()
        if not self.is_public and not author:
            author = tr("defaults.local_author")

        # Дефолтные значения
        version = self.version_edit.text().strip() or "1.0.0"
        tagline = self.tagline_edit.text().strip() or tr("defaults.no_short_description")

        return {
            "name": self.name_edit.text().strip(),
            "version": version,
            "author": author,
            "tagline": tagline,
            "description_url": self.description_url_edit.text().strip(),
            "icon_url": self.icon_edit.text().strip(),
            "tags": tags,
            "hide_mod": False,
            "is_piracy_protected": self.piracy_checkbox.isChecked(),
            "is_demo_mod": self.demo_checkbox.isChecked(),
            # NOTE: do not set is_verified here; preserve server value on update
            "game_version": (self.game_version_combo.currentText() if self.is_public else (self.game_version_edit.text().strip() or "1.03")),
            "files": files_data,
            "screenshots_url": getattr(self, 'screenshots_urls', [])
        }

    def _save_public_mod(self):
        """Сохраняет публичный мод."""
        QMessageBox.information(self, tr("errors.save_secret_key_title"),
                              tr("dialogs.save_secret_key_instruction"))

        secret_key = generate_secret_key()
        hashed_key = hash_secret_key(secret_key)
        suggested_filename = f"{sanitize_filename(self.name_edit.text())}_key.txt"
        key_file_path, _ = QFileDialog.getSaveFileName(
            self, tr("dialogs.save_mod_secret_key"),
            os.path.join(os.path.expanduser("~"), suggested_filename),
            get_file_filter("text_files"))

        if not key_file_path:
            QMessageBox.warning(self, tr("dialogs.mod_creation_cancelled"), tr("dialogs.key_required_for_creation"))
            return

        # Сначала отправляем мод, только потом сохраняем ключ
        try:
            mod_data = self._collect_mod_data()

            # Преобразуем структуру files в chapters (единый стандарт)
            if "files" in mod_data:
                chapters = {}

                for chapter_key, chapter_files in mod_data["files"].items():
                    # Правильный маппинг согласно стандарту
                    if chapter_key == "demo":
                        chapter_id = -1
                    elif chapter_key == "menu":
                        chapter_id = 0
                    elif chapter_key.startswith("chapter_"):
                        chapter_id = int(chapter_key.replace("chapter_", ""))
                    else:
                        continue

                    chapter_data = {}
                    if "data_win_url" in chapter_files:
                        chapter_data["data_file_url"] = chapter_files["data_win_url"]
                    if "data_win_version" in chapter_files:
                        chapter_data["data_win_version"] = chapter_files["data_win_version"]

                    # Преобразуем extra files в правильный формат
                    if "extra" in chapter_files:
                        extra_files = []
                        for key, file_data in chapter_files["extra"].items():
                            extra_files.append({
                                "key": key,
                                "url": file_data["url"],
                                "version": file_data["version"]
                            })
                        # Ренумерация ключей как последовательность "1","2","3"...
                        for idx, ef in enumerate(extra_files, start=1):
                            ef["key"] = str(idx)
                        chapter_data["extra_files"] = extra_files

                    chapters[str(chapter_id)] = chapter_data

                # Заменяем files на chapters
                mod_data.pop("files")
                mod_data["chapters"] = chapters

            from helpers import format_timestamp
            timestamp = format_timestamp()
            mod_data.update({
                "status": "pending", "downloads": 0,
                "is_verified": False,
                "submission_date": timestamp, "created_date": timestamp, "last_updated": timestamp
            })

            from helpers import DATA_FIREBASE_URL
            import requests

            from helpers import _fb_url
            pending_url = _fb_url(DATA_FIREBASE_URL, f"pending_mods/{hashed_key}")
            response = requests.put(pending_url, json=mod_data, timeout=10)
            response.raise_for_status()

            # Мод успешно отправлен, теперь сохраняем ключ
            try:
                with open(key_file_path, 'w', encoding='utf-8') as f:
                    f.write(f"{tr('ui.secret_key_colon')} {secret_key}\n{tr('ui.mod_name_colon')} {self.name_edit.text()}\n"
                            f"{tr('ui.creation_date_colon')} {format_timestamp()}\n\n"
                            f"{tr('ui.secret_key_important')}\n")

                QMessageBox.information(self, tr("dialogs.mod_submitted"),
                                      tr("errors.mod_submitted_success", key_file_path=key_file_path))
                self._open_file_directory(key_file_path)
            except Exception as key_error:
                QMessageBox.warning(self, tr("errors.mod_sent_key_error"),
                                   tr("errors.mod_submitted_key_save_failed", secret_key=secret_key))

            self.accept()

        except Exception as e:
            # Временно показываем детальную ошибку для отладки
            import traceback
            error_details = traceback.format_exc()


            # Скрываем URL базы данных для безопасности, но показываем больше деталей
            error_msg = tr("errors.mod_submission_failed", error_type=type(e).__name__)
            if "400" in str(e):
                error_msg = tr("errors.validation_data_error")
            elif "KeyError" in str(e):
                error_msg = tr("errors.data_structure_error")
            elif "TypeError" in str(e):
                error_msg = tr("errors.data_types_error")
            QMessageBox.critical(self, tr("errors.submission_error_title"), error_msg)

    def _open_file_directory(self, file_path):
        """Открывает папку с файлом в проводнике."""
        try:
            key_dir = os.path.dirname(os.path.abspath(file_path))
            system = platform.system()
            if system == "Windows":
                subprocess.run(["explorer", "/select,", os.path.abspath(file_path)], check=False)
            elif system == "Darwin":
                subprocess.run(["open", "-R", os.path.abspath(file_path)], check=False)
            else:
                subprocess.run(["xdg-open", key_dir], check=False)
        except Exception:
            try:
                key_dir = os.path.dirname(os.path.abspath(file_path))
                if system == "Windows": os.startfile(key_dir)
                elif system == "Darwin": subprocess.run(["open", key_dir], check=False)
                else: subprocess.run(["xdg-open", key_dir], check=False)
            except Exception: pass

    def _save_local_mod(self):
        """Сохраняет локальный мод с созданием папки и копированием файлов."""
        mod_data = self._collect_mod_data()
        mod_key = f"local_{uuid.uuid4().hex[:12]}"

        from helpers import get_unique_mod_dir
        unique_mod_folder = get_unique_mod_dir(self.parent_app.mods_dir, mod_data["name"])
        mod_dir = os.path.join(self.parent_app.mods_dir, unique_mod_folder)

        try:
            os.makedirs(mod_dir)

            # Копируем иконку, если она указана
            icon_path = self.icon_edit.text().strip()
            if icon_path and os.path.exists(icon_path):
                icon_filename = os.path.basename(icon_path)
                shutil.copy2(icon_path, os.path.join(mod_dir, icon_filename))
                # Сохраняем относительный путь к иконке в данных мода
                mod_data["icon_url"] = icon_filename

            # Преобразуем структуру для локальных модов
            local_chapters = {}

            # Копируем файлы глав с правильной структурой
            for chapter_key, chapter_files in mod_data.get("files", {}).items():
                # Преобразуем строковые ключи в числовые для главы
                try:
                    chapter_id = int(chapter_key)
                except ValueError:
                    continue

                chapter_version_parts = []

                # Определяем подпапку для главы
                if chapter_id == -1:  # Демо
                    chapter_folder = os.path.join(mod_dir, "demo")
                elif chapter_id == 0:   # Меню
                    chapter_folder = os.path.join(mod_dir, "chapter_0")
                else:  # Главы 1, 2, 3, ...
                    chapter_folder = os.path.join(mod_dir, f"chapter_{chapter_id}")
                os.makedirs(chapter_folder, exist_ok=True)

                # DATA-файл
                data_path = chapter_files.get("data_win_url")
                if data_path and os.path.exists(data_path):
                    data_filename = os.path.basename(data_path)
                    destination = os.path.join(chapter_folder, data_filename)
                    shutil.copy2(data_path, destination)
                    chapter_files["data_win_url"] = data_filename # Относительный путь
                    chapter_version_parts.append(chapter_files.get("data_win_version", "1.0.0"))

                # Дополнительные файлы
                extra_files = chapter_files.get("extra_files", {})
                for group_key, paths in extra_files.items():
                    copied_paths = []
                    for path in paths:
                        if os.path.exists(path):
                            filename = os.path.basename(path)
                            shutil.copy2(path, os.path.join(chapter_folder, filename))
                            copied_paths.append(filename)
                    extra_files[group_key] = copied_paths # Обновляем на относительные пути
                    chapter_version_parts.append("1.0.0")  # Для доп. файлов

                # Создаем версию главы если есть файлы
                if chapter_version_parts:
                    local_chapters[str(chapter_id)] = "|".join(chapter_version_parts)

            # Создаем config.json в папке мода с полной информацией о файлах
            chapters_data = {}
            files_data = {}  # Добавляем информацию о файлах для редактора

            for ch_id, ch_data in local_chapters.items():
                # Формируем словарь версий вместо composite_version
                versions = {}
                chapter_files = mod_data.get("files", {}).get(ch_id, {})
                if chapter_files.get("data_win_url"):
                    versions['data'] = chapter_files.get("data_win_version", "1.0.0")
                if chapter_files.get("extra_files"):
                    for group_key, paths in chapter_files["extra_files"].items():
                        if paths:  # если есть хотя бы один файл этой группы
                            versions[group_key] = "1.0.0"
                if versions:
                    chapters_data[str(ch_id)] = {"versions": versions}

                # Добавляем информацию о файлах для этой главы
                files_data[str(ch_id)] = {}

                # DATA-файл
                if chapter_files.get("data_win_url"):
                    files_data[str(ch_id)]["data_win_url"] = os.path.basename(chapter_files["data_win_url"])
                    files_data[str(ch_id)]["data_win_version"] = chapter_files.get("data_win_version", "1.0.0")

                # Дополнительные файлы
                extra_files = chapter_files.get("extra_files", {})
                if extra_files:
                    files_data[str(ch_id)]["extra_files"] = {}
                    for group_key, paths in extra_files.items():
                        files_data[str(ch_id)]["extra_files"][group_key] = [os.path.basename(path) for path in paths]

            config_data = {
                "is_local_mod": True,
                "mod_key": mod_key,
                "created_date": format_timestamp(),
                "is_available_on_server": False,  # Локальные моды не на сервере
                "name": mod_data.get("name", ""),
                "version": mod_data.get("version", "1.0.0"),
                "author": mod_data.get("author", ""),
                "tagline": mod_data.get("tagline", tr("defaults.no_short_description")),
                "game_version": mod_data.get("game_version", tr("defaults.not_specified")),
                "is_demo_mod": mod_data.get("is_demo_mod", False),
                "chapters": chapters_data,
                "files": files_data  # Добавляем информацию о файлах
            }

            config_path = os.path.join(mod_dir, "config.json")
            self.parent_app._write_json(config_path, config_data)

            # Обновляем UI после создания
            self.parent_app._load_local_mods_from_folders()
            self.parent_app._populate_ui_with_mods()

            QMessageBox.information(self, tr("dialogs.local_mod_created_title"), tr("dialogs.local_mod_created_message", mod_name=mod_data['name']))
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, tr("errors.mod_creation_error"), tr("errors.mod_creation_failed", error=str(e)))
            if os.path.exists(mod_dir):
                shutil.rmtree(mod_dir)

    def _update_existing_mod(self):
        """Обновляет существующий мод, разделяя логику для публичных и локальных."""
        if self.is_public:
            self._update_public_mod()
        else:
            self._update_local_mod()

    def _update_public_mod(self):
        """Обновляет существующий публичный мод."""
        if not self.is_public:
            QMessageBox.critical(self, tr("errors.error"), tr("errors.update_local_as_public"))
            return

        if not self._validate_fields():
            return

        # ИСПРАВЛЕНИЕ 2: Проверяем наличие реальных изменений
        if not self._has_real_changes():
            QMessageBox.warning(self, tr("errors.no_changes_title"),
                              tr("errors.no_changes_to_update"))
            return



        updated_data = self._collect_mod_data()

        # Преобразуем структуру files в chapters для совместимости с сервером
        if "files" in updated_data:
            chapters = {}
            for chapter_key, chapter_files in updated_data["files"].items():
                # Правильный маппинг ключей глав в ID
                if chapter_key == "demo":
                    chapter_id = -1
                elif chapter_key == "menu":
                    chapter_id = 0
                elif chapter_key.startswith("chapter_"):
                    chapter_id = int(chapter_key.replace("chapter_", ""))
                else:
                    continue

                chapter_data = {}
                if "data_win_url" in chapter_files:
                    chapter_data["data_file_url"] = chapter_files["data_win_url"]
                if "data_win_version" in chapter_files:
                    chapter_data["data_win_version"] = chapter_files["data_win_version"]

                # Преобразуем extra files в правильный формат
                if "extra" in chapter_files:
                    extra_files = []
                    for key, file_data in chapter_files["extra"].items():
                        extra_files.append({
                            "key": key,
                            "url": file_data["url"],
                            "version": file_data["version"]
                        })
                    # Ренумерация ключей как последовательность "1","2","3"...
                    for idx, ef in enumerate(extra_files, start=1):
                        ef["key"] = str(idx)
                    chapter_data["extra_files"] = extra_files

                chapters[str(chapter_id)] = chapter_data

            # Заменяем files на chapters
            updated_data.pop("files")
            updated_data["chapters"] = chapters

        if hasattr(self, 'original_mod_data'):
            # Блокировка: запрещаем изменение заблокированных модов
            if self.original_mod_data.get("ban_status", False):
                QMessageBox.critical(self, tr("errors.error"), tr("errors.mod_blocked_title"))
                return
            updated_data["created_date"] = self.original_mod_data.get("created_date")
            updated_data["status"] = self.original_mod_data.get("status", "pending")
            updated_data["downloads"] = self.original_mod_data.get("downloads", 0)  # Сохраняем downloads

        from helpers import format_timestamp
        updated_data["last_updated"] = format_timestamp()

        try:
            from helpers import DATA_FIREBASE_URL
            import requests

            hashed_key = self.mod_key
            if not hashed_key:
                QMessageBox.critical(self, tr("errors.error"), tr("errors.mod_key_not_determined"))
                return

            # Проверяем актуальный статус верификации с сервера
            try:
                from helpers import _fb_url
                chk = requests.get(_fb_url(DATA_FIREBASE_URL, f"mods/{hashed_key}"), timeout=8)
                if chk.status_code == 200 and isinstance(chk.json(), dict):
                    server_data = chk.json()
                    is_verified = bool(server_data.get("is_verified", self.original_mod_data.get("is_verified", False)))
                    # Переносим важные системные поля из server_data
                    updated_data["downloads"] = server_data.get("downloads", updated_data.get("downloads", 0))
                    updated_data["created_date"] = server_data.get("created_date", updated_data.get("created_date"))
                    updated_data["status"] = server_data.get("status", updated_data.get("status", "approved"))
                    # Обязательно сохраняем is_verified
                    updated_data["is_verified"] = server_data.get("is_verified", False)
                else:
                    is_verified = self.original_mod_data.get("is_verified", False)
                    updated_data["is_verified"] = is_verified
            except Exception:
                is_verified = self.original_mod_data.get("is_verified", False)
                updated_data["is_verified"] = is_verified

            if is_verified:
                from helpers import _fb_url
                url = _fb_url(DATA_FIREBASE_URL, f"mods/{hashed_key}")
                response = requests.put(url, json=updated_data, timeout=10)
                response.raise_for_status()
                # Verify the update actually persisted
                try:
                    verify_resp = requests.get(url, timeout=8)
                    if verify_resp.status_code == 200:
                        server_after = verify_resp.json() or {}
                        # Compare a minimal set of fields to ensure persistence
                        persisted_ok = True
                        for fld in ["name", "version", "tagline", "author", "game_version", "tags"]:
                            if updated_data.get(fld) != server_after.get(fld):
                                persisted_ok = False; break
                        # Chapters structure check (keys only)
                        if persisted_ok and "chapters" in updated_data:
                            upd_keys = sorted((updated_data.get("chapters") or {}).keys())
                            srv_keys = sorted((server_after.get("chapters") or {}).keys())
                            if upd_keys != srv_keys:
                                persisted_ok = False
                        if not persisted_ok:
                            QMessageBox.critical(self, tr("errors.update_error"), tr("errors.update_not_persisted"))
                            return
                    else:
                        QMessageBox.critical(self, tr("errors.update_error"), tr("errors.update_verification_failed"))
                        return
                except Exception:
                    QMessageBox.critical(self, tr("errors.update_error"), tr("errors.update_verification_failed"))
                    return
                QMessageBox.information(self, tr("errors.mod_updated_title"), tr("errors.mod_updated_message"))
            else:
                from helpers import _fb_url
                pending_url = _fb_url(DATA_FIREBASE_URL, f"pending_changes/{hashed_key}")
                updated_data["change_type"] = "update"
                updated_data["original_mod_key"] = hashed_key
                response = requests.put(pending_url, json=updated_data, timeout=10)
                response.raise_for_status()
                # Optional: verify pending record exists
                try:
                    chk = requests.get(pending_url, timeout=8)
                    if chk.status_code != 200 or not chk.json():
                        QMessageBox.warning(self, tr("errors.request_sent_title"), tr("errors.request_sent_but_not_found"))
                    else:
                        QMessageBox.information(self, tr("errors.request_sent_title"), tr("errors.request_sent_message"))
                except Exception:
                    QMessageBox.information(self, tr("errors.request_sent_title"), tr("errors.request_sent_message"))

            self.accept()

        except Exception as e:
            # Скрываем URL базы данных для безопасности
            error_msg = tr("errors.update_connection_error")
            if "400" in str(e):
                error_msg = tr("errors.validation_data_error")
            elif "401" in str(e) or "403" in str(e):
                error_msg = tr("errors.access_permission_error")
            elif "404" in str(e):
                error_msg = tr("errors.mod_not_found_server")
            QMessageBox.critical(self, tr("errors.update_error"), error_msg)

    def _has_real_changes(self) -> bool:
        """Проверяет, есть ли реальные изменения в моде."""
        if not hasattr(self, 'original_mod_data') or not self.original_mod_data: return True
        current_data, original_data = self._collect_mod_data(), self.original_mod_data
        fields_to_compare = ['name', 'version', 'author', 'tagline', 'description_url', 'icon_url', 'tags', 'is_piracy_protected', 'is_demo_mod', 'game_version', 'files', 'screenshots_url']
        return any(current_data.get(field) != original_data.get(field) for field in fields_to_compare)



    def _update_local_mod(self):
        """Обновляет существующий локальный мод (новая версия для config.json)."""
        updated_data = self._collect_mod_data()
        mod_key = self.mod_key

        if not mod_key:
            QMessageBox.critical(self, tr("errors.error"), tr("errors.mod_key_not_found_update"))
            return

        # Ищем папку мода по config.json файлам
        mod_folder_path = None
        if os.path.exists(self.parent_app.mods_dir):
            for folder_name in os.listdir(self.parent_app.mods_dir):
                folder_path = os.path.join(self.parent_app.mods_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue

                config_path = os.path.join(folder_path, "config.json")
                if os.path.exists(config_path):
                    try:
                        config_data = self.parent_app._read_json(config_path)
                        if config_data and config_data.get('mod_key') == mod_key:
                            mod_folder_path = folder_path
                            break
                    except Exception:
                        continue

        if not mod_folder_path:
            QMessageBox.critical(self, tr("errors.error"), tr("errors.mod_folder_not_found_update"))
            return

        try:
            # Читаем текущий config.json
            config_path = os.path.join(mod_folder_path, "config.json")
            config_data = self.parent_app._read_json(config_path)

            # Очищаем папки глав, но сохраняем config.json и иконку
            for item in os.listdir(mod_folder_path):
                if item not in ['config.json'] and not item.endswith(('.png', '.jpg', '.jpeg', '.gif')):
                    item_path = os.path.join(mod_folder_path, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)

            # Копируем новую иконку, если она изменилась
            new_icon_path = self.icon_edit.text().strip()
            if new_icon_path and os.path.exists(new_icon_path):
                icon_filename = os.path.basename(new_icon_path)
                shutil.copy2(new_icon_path, os.path.join(mod_folder_path, icon_filename))
                updated_data["icon_url"] = icon_filename

            # Преобразуем структуру для локальных модов
            local_chapters = {}
            files_data = {}

            # Копируем обновленные файлы с правильной структурой
            for chapter_key, chapter_files in updated_data.get("files", {}).items():
                try:
                    chapter_id = int(chapter_key)
                except ValueError:
                    continue

                chapter_version_parts = []

                # Определяем подпапку для главы
                if chapter_id == -1:  # Демо
                    chapter_folder = os.path.join(mod_folder_path, "demo")
                elif chapter_id == 0:   # Меню
                    chapter_folder = os.path.join(mod_folder_path, "chapter_0")
                else:  # Главы 1, 2, 3, ...
                    chapter_folder = os.path.join(mod_folder_path, f"chapter_{chapter_id}")
                os.makedirs(chapter_folder, exist_ok=True)

                files_data[str(chapter_id)] = {}

                # DATA-файл
                data_path = chapter_files.get("data_win_url")
                if data_path and os.path.exists(data_path):
                    data_filename = os.path.basename(data_path)
                    shutil.copy2(data_path, os.path.join(chapter_folder, data_filename))
                    files_data[str(chapter_id)]["data_win_url"] = data_filename
                    files_data[str(chapter_id)]["data_win_version"] = chapter_files.get("data_win_version", "1.0.0")
                    chapter_version_parts.append(chapter_files.get("data_win_version", "1.0.0"))

                # Дополнительные файлы
                extra_files = chapter_files.get("extra_files", {})
                if extra_files:
                    files_data[str(chapter_id)]["extra_files"] = {}
                    for group_key, paths in extra_files.items():
                        copied_paths = []
                        for path in paths:
                            if os.path.exists(path):
                                filename = os.path.basename(path)
                                shutil.copy2(path, os.path.join(chapter_folder, filename))
                                copied_paths.append(filename)
                        if copied_paths:
                            files_data[str(chapter_id)]["extra_files"][group_key] = copied_paths
                            chapter_version_parts.append("1.0.0")

                # Создаем версию главы если есть файлы
                if chapter_version_parts:
                    local_chapters[str(chapter_id)] = "|".join(chapter_version_parts)

            # Обновляем config.json с новыми данными
            chapters_data = {}
            for ch_id, ch_data in local_chapters.items():
                # Формируем словарь версий вместо composite_version
                versions = {}
                chapter_files = updated_data.get("files", {}).get(ch_id, {})
                if chapter_files.get("data_win_url"):
                    versions['data'] = chapter_files.get("data_win_version", "1.0.0")
                if chapter_files.get("extra_files"):
                    for group_key, paths in chapter_files["extra_files"].items():
                        if paths:
                            versions[group_key] = "1.0.0"
                if versions:
                    chapters_data[str(ch_id)] = {"versions": versions}

            # Обновляем config_data
            config_data.update({
                "name": updated_data.get("name", ""),
                "version": updated_data.get("version", "1.0.0"),
                "author": updated_data.get("author", ""),
                "tagline": updated_data.get("tagline", ""),
                "game_version": updated_data.get("game_version", tr("defaults.not_specified")),
                "is_demo_mod": updated_data.get("is_demo_mod", False),
                "chapters": chapters_data,
                "files": files_data
            })

            # Сохраняем обновленный config.json
            self.parent_app._write_json(config_path, config_data)

            # Обновляем UI после изменения
            self.parent_app._load_local_mods_from_folders()
            self.parent_app._populate_ui_with_mods()

            QMessageBox.information(self, tr("dialogs.local_mod_updated_title"), tr("dialogs.local_mod_updated_message", mod_name=updated_data['name']))
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, tr("errors.update_error"), tr("errors.local_mod_update_failed", error=str(e)))

    def _delete_mod(self):
        """Удаляет мод, разделяя логику для публичных и локальных."""
        if self.is_public:
            self._delete_public_mod()
        else:
            self._delete_local_mod()

    def _delete_public_mod(self):
        """Удаляет публичный мод."""
        if QMessageBox.question(self, tr("dialogs.are_you_sure"), tr("dialogs.mod_deletion_confirmation")) != QMessageBox.StandardButton.Yes: return
        secret_key, ok = QInputDialog.getText(self, tr("dialogs.confirm_deletion"), tr("dialogs.enter_secret_key_mod"), QLineEdit.EchoMode.Password)
        if not ok or not secret_key.strip(): return
        hashed_key = hash_secret_key(secret_key.strip())
        if self.mod_key and hashed_key != self.mod_key: QMessageBox.warning(self, tr("dialogs.invalid_key"), tr("dialogs.invalid_key_message")); return
        try:
            from helpers import DATA_FIREBASE_URL
            import requests
            from helpers import _fb_url
            requests.delete(_fb_url(DATA_FIREBASE_URL, f"mods/{hashed_key}"), timeout=10)
            try: requests.delete(_fb_url(DATA_FIREBASE_URL, f"pending_changes/{hashed_key}"), timeout=10)
            except Exception as e:
                logging.warning(f"Failed to delete pending_changes record: {e}")
            # Verify deletion
            chk = requests.get(_fb_url(DATA_FIREBASE_URL, f"mods/{hashed_key}"), timeout=8)
            if chk.status_code == 200 and chk.json():
                QMessageBox.critical(self, tr("errors.deletion_error"), tr("errors.mod_deletion_verification_failed"))
                return
            QMessageBox.information(self, tr("errors.mod_deleted_title"), tr("errors.mod_deleted_message"))
            self.accept()
        except Exception as e: QMessageBox.critical(self, tr("errors.deletion_error"), tr("errors.mod_deletion_failed", error=str(e)))

    def _delete_local_mod(self):
        """Удаляет локальный мод и его папку (новая версия для config.json)."""
        if QMessageBox.question(self, tr("dialogs.are_you_sure"), tr("dialogs.local_mod_deletion_confirmation")) != QMessageBox.StandardButton.Yes:
            return

        if not self.mod_key:
            QMessageBox.critical(self, tr("errors.error"), tr("errors.mod_key_not_found_for_deletion"))
            return

        try:
            # Ищем папку мода по config.json файлам
            mod_folder_path = None
            if os.path.exists(self.parent_app.mods_dir):
                for folder_name in os.listdir(self.parent_app.mods_dir):
                    folder_path = os.path.join(self.parent_app.mods_dir, folder_name)
                    if not os.path.isdir(folder_path):
                        continue

                    config_path = os.path.join(folder_path, "config.json")
                    if os.path.exists(config_path):
                        try:
                            config_data = self.parent_app._read_json(config_path)
                            if config_data and config_data.get('mod_key') == self.mod_key:
                                mod_folder_path = folder_path
                                break
                        except Exception:
                            continue

            if not mod_folder_path:
                QMessageBox.critical(self, tr("errors.error"), tr("errors.mod_folder_not_found_for_deletion"))
                return

            # Удаляем папку мода
            shutil.rmtree(mod_folder_path)

            # Обновляем UI после удаления
            self.parent_app._load_local_mods_from_folders()
            self.parent_app._populate_ui_with_mods()

            QMessageBox.information(self, tr("errors.local_mod_deleted_title"), tr("errors.local_mod_deleted_message"))
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, tr("errors.deletion_error"), tr("errors.local_mod_deletion_failed", error=str(e)))

    def populate_fields(self):
        """Заполняет поля данными существующего мода."""
        if not self.mod_data:
            return

        # Для локальных модов данные могут быть вложены в mod_data
        actual_mod_data = self.mod_data
        if 'mod_data' in self.mod_data:
            actual_mod_data = self.mod_data['mod_data']

        self.name_edit.setText(actual_mod_data.get('name', ''))
        self.author_edit.setText(actual_mod_data.get('author', ''))
        self.tagline_edit.setText(actual_mod_data.get('tagline', ''))
        icon_value = actual_mod_data.get('icon_url', '')
        self.icon_edit.setText(icon_value)

        # Загружаем превью иконки
        if icon_value:
            if self.is_public:
                self._on_icon_url_changed()  # Для публичных модов
            else:
                self._load_local_icon_preview(icon_value)  # Для локальных модов

        # Для локальных модов версия может быть простой строкой
        version = actual_mod_data.get('version', '')
        if isinstance(version, str) and '|' in version:
            # Публичный мод с составной версией - берем первую часть
            version = version.split('|')[0]
        self.version_edit.setText(version)

        self.description_url_edit.setText(actual_mod_data.get('description_url', ''))

        # Чекбоксы
        self.demo_checkbox.setChecked(actual_mod_data.get('is_demo_mod', False))
        self.piracy_checkbox.setChecked(actual_mod_data.get('is_piracy_protected', False))

        # Теги (исправляем на правильные ключи)
        tags = actual_mod_data.get('tags', [])
        self.tag_translation.setChecked('translation' in tags)
        self.tag_customization.setChecked('customization' in tags)
        self.tag_gameplay.setChecked('gameplay' in tags)
        self.tag_other.setChecked('other' in tags)

        # Версия игры
        game_version = actual_mod_data.get('game_version', '')
        if self.is_public:
            index = self.game_version_combo.findText(game_version)
            if index >= 0:
                self.game_version_combo.setCurrentIndex(index)
        else:
            if hasattr(self, 'game_version_edit'):
                self.game_version_edit.setText(game_version)
        
        # Скриншоты
        self.screenshots_urls = actual_mod_data.get('screenshots_url', []) or []
        if not isinstance(self.screenshots_urls, list):
            self.screenshots_urls = []
 
        # Парсим данные файлов и заполняем вкладки
        self._populate_file_tabs()

        # Обновляем кнопку скрыть/показать если это публичный мод
        if not self.is_creating and self.is_public and hasattr(self, 'hide_mod_button'):
            is_hidden = self.mod_data.get('hide_mod', False)
            self.hide_mod_button.setText(tr("errors.show_hide_mod") if is_hidden else tr("errors.hide_show_mod"))

    def _populate_file_tabs(self):
        """Заполняет вкладки файлами на основе данных мода."""
        if not self.mod_data:
            return

        # Для локальных модов данные могут быть вложены в mod_data
        actual_mod_data = self.mod_data
        if 'mod_data' in self.mod_data:
            actual_mod_data = self.mod_data['mod_data']

        # Получаем файлы или главы в зависимости от структуры данных
        files_data = actual_mod_data.get('files', {})
        chapters_data = actual_mod_data.get('chapters', {})

        # Если это публичный мод, файлы могут быть в files или chapters
        if files_data:
            self._populate_from_files_structure(files_data)
        elif chapters_data:
            self._populate_from_chapters_structure(chapters_data)

    def _populate_from_files_structure(self, files_data):
        """Заполняет вкладки из структуры files (публичные и локальные моды)."""
        # Маппинг ключей файлов к индексам вкладок
        if self.is_public:
            # Для публичных модов используем текстовые ключи
            if self.demo_checkbox.isChecked():
                file_keys = {"demo": 0}
            else:
                file_keys = {"menu": 0, "chapter_1": 1, "chapter_2": 2, "chapter_3": 3, "chapter_4": 4}
        else:
            # Для локальных модов используем числовые ключи
            if self.demo_checkbox.isChecked():
                file_keys = {"0": 0}
            else:
                file_keys = {"0": 0, "1": 1, "2": 2, "3": 3, "4": 4}

        for file_key, tab_index in file_keys.items():
            if file_key in files_data and tab_index < self.file_tabs.count():
                file_info = files_data[file_key]
                self._populate_tab_with_file_data(tab_index, file_info)

    def _populate_from_chapters_structure(self, chapters_data):
        """Заполяет вкладки из структуры chapters (локальные моды)."""
        # Обрабатываем chapters как список или словарь
        if isinstance(chapters_data, list):
            # Новый формат - список chapters
            for tab_index, chapter_data in enumerate(chapters_data):
                if tab_index < self.file_tabs.count() and chapter_data is not None:
                    # Извлекаем data_file_url и extra_files
                    data_url = chapter_data.get('data_file_url', '')
                    data_version = chapter_data.get('data_win_version', '')

                    # Конвертируем в старый формат для _populate_tab_with_file_data
                    files_info = {}
                    if data_url:
                        files_info['data_win_url'] = data_url
                        files_info['data_win_version'] = data_version

                    # Обрабатываем extra_files
                    extra_files = chapter_data.get('extra_files', [])
                    if extra_files:
                        files_info['extra'] = {}
                        for extra_file in extra_files:
                            if isinstance(extra_file, dict):
                                key = extra_file.get('key', 'unknown')
                                files_info['extra'][key] = {
                                    'url': extra_file.get('url', ''),
                                    'version': extra_file.get('version', '')
                                }

                    self._populate_tab_with_file_data(tab_index, files_info)
        elif isinstance(chapters_data, dict):
            # Единый формат - словарь chapters с числовыми ключами (строками)
            for chapter_key, chapter_data in chapters_data.items():
                try:
                    # Парсим ключ главы (формат: "c{id}")
                    if chapter_key.startswith("c"):
                        chapter_id = int(chapter_key[1:])  # "c1" → 1
                    else:
                        chapter_id = int(chapter_key)  # Обратная совместимость
                    # Правильный маппинг chapter_id в tab_index согласно стандарту
                    if chapter_id == -1:
                        tab_index = 0 if self.demo_checkbox.isChecked() else None  # Демо
                    elif chapter_id == 0:
                        tab_index = 0 if not self.demo_checkbox.isChecked() else None  # Меню
                    elif 1 <= chapter_id <= 4:
                        tab_index = chapter_id if not self.demo_checkbox.isChecked() else None  # Глава 1-4
                    else:
                        continue

                    if tab_index is not None and tab_index < self.file_tabs.count():
                        # Конвертируем данные главы в формат files для отображения
                        files_info = {}
                        if chapter_data.get('data_file_url'):
                            files_info['data_win_url'] = chapter_data.get('data_file_url')
                            files_info['data_win_version'] = chapter_data.get('data_win_version', '1.0.0')

                        # Обрабатываем extra_files
                        extra_files = chapter_data.get('extra_files', [])
                        if extra_files and isinstance(extra_files, list):
                            files_info['extra'] = {}
                            for extra_file in extra_files:
                                if isinstance(extra_file, dict):
                                    key = extra_file.get('key', 'unknown')
                                    files_info['extra'][key] = {
                                        'url': extra_file.get('url', ''),
                                        'version': extra_file.get('version', '1.0.0')
                                    }

                        self._populate_tab_with_file_data(tab_index, files_info)
                except (ValueError, TypeError):
                    continue

    def _populate_tab_with_file_data(self, tab_index, file_info):
        """Заполняет конкретную вкладку данными файлов."""
        tab = self.file_tabs.widget(tab_index)
        if not tab:
            return

        layout = tab.layout()
        if not layout:
            return

        # DATA файл
        data_file_url = file_info.get('data_win_url')
        data_win_version = file_info.get('data_win_version')

        if data_file_url:
            # Для локальных модов создаем редактируемый фрейм, для публичных - добавляем форму
            if not self.is_public:
                # Создаем локальный фрейм DATA с предзаполненными данными
                self._create_file_frame(layout, 'data')
                self._fill_local_data_file_in_tab(tab, data_file_url, data_win_version)
            else:
                # Добавляем DATA файл если его еще нет
                if not self._has_data_file_in_tab(tab):
                    self._add_data_file(tab, layout)
                    # Заполняем данные
                    self._fill_data_file_in_tab(tab, data_file_url, data_win_version)

        # Дополнительные файлы для публичных модов
        extra_files = file_info.get('extra', {})
        for extra_key, extra_data in extra_files.items():
            if isinstance(extra_data, dict):
                extra_url = extra_data.get('url')
                extra_version = extra_data.get('version')
                if extra_url:
                    if self.is_public:
                        # Добавляем дополнительный файл
                        self._add_extra_files_with_data(tab, layout, extra_key, extra_url, extra_version)

        # Дополнительные файлы для локальных модов (другая структура)
        extra_files_local = file_info.get('extra_files', {})
        for extra_key, filenames in extra_files_local.items():
            if filenames:
                if not self.is_public:
                    self._add_local_extra_files_frame_with_data(tab, layout, extra_key, filenames)

    def _has_data_file_in_tab(self, tab):
        """Проверяет, есть ли уже DATA файл в вкладке."""
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
                            if isinstance(frame_widget, QLabel) and (
                                frame_widget.text().startswith("DATA") or
                                frame_widget.text().startswith("PATCH")
                            ):
                                return True
        return False

    def _fill_data_file_in_tab(self, tab, url, version):
        """Заполняет поля DATA файла в вкладке."""
        layout = tab.layout()
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if hasattr(widget, 'layout'):
                    frame_layout = widget.layout()
                    url_edit = None
                    version_edit = None

                    # Ищем поля URL и версии
                    for j in range(frame_layout.count()):
                        frame_item = frame_layout.itemAt(j)
                        if frame_item and frame_item.widget():
                            frame_widget = frame_item.widget()
                            if isinstance(frame_widget, QLineEdit):
                                prev_item = frame_layout.itemAt(j-1)
                                if prev_item and prev_item.widget():
                                    prev_widget = prev_item.widget()
                                    if isinstance(prev_widget, QLabel):
                                        field_type = detect_field_type_by_text(prev_widget.text())
                                        if field_type == "file_path":
                                            url_edit = frame_widget
                                        elif field_type == "version":
                                            version_edit = frame_widget

                    # Заполняем найденные поля
                    if url_edit and version_edit:
                        url_edit.setText(url)
                        version_edit.setText(version)
                        return

# ============================================================================
#                              MAIN APPLICATION
# ============================================================================

class DeltaHubApp(QWidget):

    update_status_signal = pyqtSignal(str, str)
    set_progress_signal = pyqtSignal(int)
    show_update_prompt = pyqtSignal(dict)
    initialization_finished = pyqtSignal()
    hide_window_signal = pyqtSignal()
    restore_window_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    mods_loaded_signal = pyqtSignal()  # Новый сигнал для уведомления о загрузке модов
    update_info_ready = pyqtSignal(dict)  # Сигнал для передачи информации об обновлении из фонового потока

    @staticmethod
    def get_launcher_version() -> str:
        return LAUNCHER_VERSION

    def __init__(self, args: Optional[argparse.Namespace] = None, parent_for_dialogs: Optional[QWidget] = None):
        super().__init__()
        self.is_shortcut_launch = args and args.shortcut_launch
        self.dialog_parent = parent_for_dialogs or self
        self.session_id = uuid.uuid4().hex
        self._init_session()

        self.presence_thread = None
        self.presence_worker = None
        self._direct_launch_cleanup_info = None

        self._online_timer = QTimer(self)
        self._online_timer.timeout.connect(self._run_presence_tick)
        self._online_timer.start(30_000)
        if self.is_shortcut_launch:
            self._shortcut_launch(args)
            return # __init__ завершается здесь для запуска из ярлыка
        QTimer.singleShot(0, self._run_presence_tick)

        self.setWindowTitle("DELTAHUB")
        
        # Платформенно-зависимый флаг громкости
        self._supports_volume = (platform.system() == "Windows")
        
        # Запомним базовый размер окна, чтобы уметь возвращать его после больших страниц (changelog/help)
        try:
            self._initial_size = self.size()
        except Exception:
            self._initial_size = None

        # --- Новая структура путей ---
        # self.config_dir: для JSON-конфигов в AppData
        # self.mods_dir: для кэша модов в профиле пользователя (записываемая папка)
        self.config_dir = get_app_support_path()
        self.launcher_dir = get_launcher_dir()
        from helpers import get_user_mods_dir
        self.mods_dir = get_user_mods_dir()

        # Создаем обе папки, если их нет
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.mods_dir, exist_ok=True)

        self.config_path    = os.path.join(self.config_dir, "config.json")


        self.local_config   = self._read_json(self.config_path) or {}

        # Автовосстановление после сбоя прошлой сессии (если было вмешательство в файлы игры)
        self._recover_previous_session()

        # Инициализируем локализацию
        self._init_localization()

        self.save_path: str = ""
        self.is_save_manager_view: bool = False

        self.current_collection_idx: Dict[int, int] = {}
        self.selected_slot: Optional[tuple[int, int]] = None

        self.resize(875, 750)

        self.background_movie = None
        self.setWindowIcon(QIcon(resource_path("assets/icon.ico")))
        self.background_pixmap: Optional[QPixmap] = None
        self.custom_font_family = None
        self.game_path = ""
        self.demo_game_path = ""

        self.translations_by_chapter = {i: [] for i in range(5)}
        self.all_mods: List[ModInfo] = []
        self.is_settings_view = False
        self.update_in_progress = False
        self.is_changelog_view = False
        self.is_help_view = False
        self.monitor_thread: Optional[GameMonitorThread] = None
        self.is_full_install = False
        self.global_settings: Dict[str, Any] = {}
        self.current_settings_page: Optional[QWidget] = None
        self.settings_nav_stack: list[QWidget] = []

        # Переменные для отслеживания инициализации
        self.mods_loaded = False
        self.initialization_timer = None
        self.initialization_completed = False
        self.is_shown_to_user = False  # Флаг показа лаунчера пользователю

        self._bg_music_running = False
        self._bg_music_thread = None

        is_demo_enabled = self.local_config.get("demo_mode_enabled", False)
        self.game_mode: GameMode = DemoGameMode() if is_demo_enabled else FullGameMode()

        self.init_ui()
        self.load_font()
        QTimer.singleShot(100, self._perform_initial_setup)

        self.update_status_signal.connect(self._update_status)
        self.hide_window_signal.connect(self._hide_window_for_game)
        self.restore_window_signal.connect(self._restore_window_after_game)
        self.set_progress_signal.connect(self.progress_bar.setValue)
        self.show_update_prompt.connect(self._prompt_for_update)
        self.error_signal.connect(lambda msg: QMessageBox.critical(self, tr("errors.error"), msg))
        self.mods_loaded_signal.connect(self._on_mods_loaded)
        self.update_info_ready.connect(self._handle_update_info)

        # Post-show one-time tasks (legacy cleanup)
        self._legacy_cleanup_done = False
        QTimer.singleShot(1000, self._maybe_run_legacy_cleanup)

        # Таймер для принудительного завершения инициализации через 5 секунд
        self.initialization_timer = QTimer()
        self.initialization_timer.setSingleShot(True)
        self.initialization_timer.timeout.connect(self._force_finish_initialization)
        self.initialization_timer.start(5000)  # 5 секунд

        if (saved := self.local_config.get("window_geometry")):
            from PyQt6.QtCore import QByteArray
            try:
                self.restoreGeometry(QByteArray.fromHex(saved.encode()))
            except Exception:
                pass

    def _init_session(self):
        try:
            now = int(time.time())
            from helpers import _fb_url, DATA_FIREBASE_URL
            requests.put(
                _fb_url(DATA_FIREBASE_URL, f"stats/sessions/{self.session_id}"),
                json={"startTime": now, "os": platform.system()},
                timeout=5
            )
        except Exception:
            pass

    # ---------------- Session manifest (crash-safe restore) ----------------
    def _session_manifest_path(self):
        return os.path.join(self.config_dir, "session.lock")

    def _load_session_manifest(self) -> dict:
        try:
            with open(self._session_manifest_path(), 'r', encoding='utf-8') as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _write_session_manifest(self, data: dict):
        try:
            with open(self._session_manifest_path(), 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def _ensure_session_manifest(self) -> dict:
        data = self._load_session_manifest()
        if not data:
            data = {"backup_files": {}, "mod_files_to_cleanup": [], "mod_dirs_to_cleanup": [], "backup_temp_dir": None, "direct_launch": None}
            self._write_session_manifest(data)
        return data

    def _update_session_manifest(self, backup_files: Optional[dict] = None, mod_files: Optional[list] = None, backup_temp_dir: Optional[str] = None, direct_launch: Optional[dict] = None, mod_dirs: Optional[list] = None):
        data = self._ensure_session_manifest()
        if backup_files:
            data.setdefault("backup_files", {}).update(backup_files)
        if mod_files:
            existing = set(data.get("mod_files_to_cleanup", []))
            for p in mod_files:
                if p not in existing:
                    data.setdefault("mod_files_to_cleanup", []).append(p)
        if mod_dirs:
            existing_dirs = set(data.get("mod_dirs_to_cleanup", []))
            for d in mod_dirs:
                if d not in existing_dirs:
                    data.setdefault("mod_dirs_to_cleanup", []).append(d)
        if backup_temp_dir is not None:
            data["backup_temp_dir"] = backup_temp_dir
        if direct_launch is not None:
            data["direct_launch"] = direct_launch
        self._write_session_manifest(data)



    def _clear_session_manifest(self):
        try:
            os.remove(self._session_manifest_path())
        except Exception:
            pass

    def _recover_previous_session(self):
        try:
            data = self._load_session_manifest()
            if not data:
                return
            # Восстанавливаем внутренние структуры и запускаем очистку
            self._backup_files = data.get("backup_files", {})
            self._mod_files_to_cleanup = data.get("mod_files_to_cleanup", [])
            self._backup_temp_dir = data.get("backup_temp_dir")
            self._direct_launch_cleanup_info = data.get("direct_launch")
            self.update_status_signal.emit(tr("status.recovering_previous_session"), UI_COLORS["status_warning"])
            self._cleanup_direct_launch_files()
            self._clear_session_manifest()
        except Exception:
            # Если что-то пошло не так — не блокируем запуск
            pass

    def _shortcut_launch(self, args):
        """Запускает игру через ярлык без показа GUI"""
        try:
            settings_json = base64.b64decode(args.shortcut_launch).decode('utf-8')
            settings = json.loads(settings_json)
        except Exception as e:
            print(tr("startup.shortcut_settings_read_error", error=str(e)))
            sys.exit(1)

        # Загружаем необходимые данные
        self._load_local_data()
        self._load_all_translations_from_folders()

        try:
            # Восстанавливаем настройки из ярлыка
            self.game_mode = DemoGameMode() if settings.get("is_demo_mode", False) else FullGameMode()
            self.game_path = settings.get("game_path", "")
            self.demo_game_path = settings.get("demo_game_path", "")

            # Настройки запуска
            launch_via_steam = settings.get('launch_via_steam', False)
            use_custom_executable = settings.get('use_custom_executable', False)
            custom_exec_path = settings.get("custom_executable_path", "")
            demo_custom_exec_path = settings.get("demo_custom_executable_path", "")
            direct_launch_slot_id = settings.get('direct_launch_slot_id', -1)

            # Проверяем наличие файлов игры
            current_game_path = self._get_current_game_path()
            if not current_game_path or not os.path.exists(current_game_path):
                print(tr("errors.game_files_launch_not_found"))
                sys.exit(1)

            # Проверяем и применяем моды
            mods_settings = settings.get('mods', {})
            if not mods_settings:
                # Поддержка старого формата для совместимости
                mods_settings = settings.get('selections', {})

            self._apply_shortcut_mods(mods_settings)

            # Запускаем игру с настройками
            self._launch_game_from_shortcut(
                launch_via_steam=launch_via_steam,
                use_custom_executable=use_custom_executable,
                custom_exec_path=custom_exec_path,
                demo_custom_exec_path=demo_custom_exec_path,
                direct_launch_slot_id=direct_launch_slot_id
            )

        except Exception as e:
            print(tr("startup.launch_error", error=str(e)))
            sys.exit(1)

    def _create_shortcut_flow(self):
        """Создает ярлык с текущими настройками лаунчера"""
        settings = self._gather_shortcut_settings()
        if not settings:
            QMessageBox.warning(self, tr("dialogs.cannot_create_shortcut_title"), tr("dialogs.path_not_specified"))
            return

        # Создаем описание настроек для ярлыка
        description_lines = [
            tr("dialogs.shortcut_description"),
            "",
            tr("dialogs.current_shortcut_settings"),
            ""
        ]

        # Режим игры
        mode_text = tr("status.demo_mode") if settings.get("is_demo_mode", False) else tr("status.full_version")
        description_lines.append(f"<b>{tr('status.mode_label')}</b> {mode_text}")

        # Показываем настройки модов/слотов
        if settings.get("is_demo_mode", False):
            # Демо режим - один мод
            mod_key = settings["mods"].get("demo")
            if mod_key:
                mod_config = self._get_mod_config_by_key(mod_key)
                mod_name = mod_config.get('name', tr("errors.mod_not_found", mod_key=mod_key)) if mod_config else tr("errors.mod_not_found", mod_key=mod_key)
                description_lines.append(f"<b>{tr('status.mod_label')}</b> {mod_name}")
            else:
                description_lines.append(f"<b>{tr('status.mod_label')}</b> <i>{tr('status.no_mods')}</i>")
        else:
            # Обычный или поглавный режим
            is_chapter_mode = settings.get("is_chapter_mode", False)
            direct_launch_slot_id = settings.get('direct_launch_slot_id', -1)

            if is_chapter_mode:
                description_lines.append(f"<b>{tr('status.mode_label')}</b> {tr('status.chapter_mode')}")
                if direct_launch_slot_id >= 0:
                    chapter_names = {0: tr("chapters.menu"), 1: tr("tabs.chapter_1"), 2: tr("tabs.chapter_2"), 3: tr("tabs.chapter_3"), 4: tr("tabs.chapter_4")}
                    chapter_name = chapter_names.get(direct_launch_slot_id, tr("ui.chapter_tab_title", chapter_num=direct_launch_slot_id))
                    description_lines.append(f"<b>{tr('status.direct_launch_label')}</b> {chapter_name}")

                    # Показываем мод для выбранного слота
                    mod_key = settings["mods"].get(str(direct_launch_slot_id))
                    if mod_key:
                        mod_config = self._get_mod_config_by_key(mod_key)
                        mod_name = mod_config.get('name', tr("errors.mod_not_found", mod_key=mod_key)) if mod_config else tr("errors.mod_not_found", mod_key=mod_key)
                        description_lines.append(f"<b>{tr('status.mod_for_chapter_label', chapter_name=chapter_name)}</b> {mod_name}")
                    else:
                        description_lines.append(f"<b>{tr('status.mod_for_chapter_label', chapter_name=chapter_name)}</b> <i>{tr('status.no_mod')}</i>")
                else:
                    description_lines.append(f"<b>{tr('status.direct_launch_label')}</b> {tr('status.disabled')}")
                    # Показываем все моды
                    for chapter_id in [0, 1, 2, 3, 4]:
                        mod_key = settings["mods"].get(str(chapter_id))
                        if mod_key:
                            mod_config = self._get_mod_config_by_key(mod_key)
                            mod_name = mod_config.get('name', tr("errors.mod_not_found", mod_key=mod_key)) if mod_config else tr("errors.mod_not_found", mod_key=mod_key)
                            chapter_names = {0: tr("chapters.menu"), 1: tr("tabs.chapter_1"), 2: tr("tabs.chapter_2"), 3: tr("tabs.chapter_3"), 4: tr("tabs.chapter_4")}
                            chapter_name = chapter_names.get(chapter_id, tr("ui.chapter_tab_title", chapter_num=chapter_id))
                            description_lines.append(f"<b>{chapter_name}:</b> {mod_name}")
            else:
                description_lines.append(f"<b>{tr('status.mode_label')}</b> {tr('status.normal_mode')}")
                # Показываем моды для всех вкладок
                tab_names = [tr("chapters.main_menu"), tr("tabs.chapter_1"), tr("tabs.chapter_2"), tr("tabs.chapter_3"), tr("tabs.chapter_4")]
                for i, tab_name in enumerate(tab_names):
                    mod_key = settings["mods"].get(str(i))
                    if mod_key:
                        mod_config = self._get_mod_config_by_key(mod_key)
                        mod_name = mod_config.get('name', tr("errors.mod_not_found", mod_key=mod_key)) if mod_config else tr("errors.mod_not_found", mod_key=mod_key)
                        description_lines.append(f"<b>{tab_name}:</b> {mod_name}")
                    else:
                        description_lines.append(f"<b>{tab_name}:</b> <i>{tr('status.no_mod')}</i>")

        # Настройки запуска
        description_lines.append("")
        if settings.get("launch_via_steam"):
            description_lines.append(f"✓ {tr('status.steam_launch')}")
        elif settings.get("use_custom_executable"):
            custom_path = settings.get("custom_executable_path", "") or settings.get("demo_custom_executable_path", "")
            exe_name = os.path.basename(custom_path) if custom_path else "?"
            description_lines.append(f"✓ {tr('status.custom_executable_launch', exe_name=exe_name)}")
        else:
            description_lines.append(f"✓ {tr('status.normal_launch')}")

        # Показываем диалог
        reply = QMessageBox.question(
            self,
            tr("dialogs.create_shortcut_question"),
            "<br>".join(description_lines) +
            f"<br><br><p>{tr('dialogs.shortcut_create_description')}</p>",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._save_shortcut(settings)

    def _load_local_mods_from_folders(self):
        """Загружает локальные моды из config.json файлов и обновляет список всех модов"""
        if not os.path.exists(self.mods_dir):
            return False

        # Собираем установленные моды
        installed_mods = {}
        try:
            for folder_name in os.listdir(self.mods_dir):
                folder_path = os.path.join(self.mods_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue

                config_path = os.path.join(folder_path, "config.json")
                if not os.path.exists(config_path):
                    continue

                try:
                    config_data = self._read_json(config_path)
                    if not config_data:
                        continue

                    mod_key = config_data.get('mod_key')
                    if mod_key:
                        installed_mods[mod_key] = config_data

                except Exception:
                    continue

            # Обновляем существующие удаленные моды с локальными данными
            for mod in self.all_mods:
                if mod.key in installed_mods:
                    # Мод установлен - помечаем его как доступный на сервере
                    config_data = installed_mods[mod.key]
                    config_path = None

                    # Находим путь к config.json для обновления флага доступности
                    for folder_name in os.listdir(self.mods_dir):
                        folder_path = os.path.join(self.mods_dir, folder_name)
                        test_config_path = os.path.join(folder_path, "config.json")
                        if os.path.isfile(test_config_path):
                            try:
                                test_config = self._read_json(test_config_path)
                                if test_config.get('mod_key') == mod.key:
                                    config_path = test_config_path
                                    break
                            except Exception as e:
                                logging.warning(f"Failed reading config {test_config_path}: {e}")
                                continue

                    # Обновляем флаг доступности для найденных модов
                    if config_path:
                        # Используем данные из config.json вместо local_versions
                        is_available = config_data.get('is_available_on_server', False)

            # Добавляем локальные моды, которых нет в удаленном списке
            existing_keys = {mod.key for mod in self.all_mods}
            for mod_key, config_data in installed_mods.items():
                if mod_key not in existing_keys and config_data.get('is_local_mod'):
                    try:
                        # Создаем безопасный объект ModInfo для локальных модов
                        safe_mod_info = {
                            "key": mod_key,
                            "name": config_data.get("name", tr("defaults.local_mod")),
                            "version": config_data.get("version", "1.0.0"),
                            "author": config_data.get("author", tr("defaults.unknown")),
                            "tagline": config_data.get("tagline", tr("defaults.no_description")),
                            "game_version": config_data.get("game_version", tr("defaults.not_specified")),
                            "description_url": "",
                            "downloads": 0,
                            "is_demo_mod": config_data.get("is_demo_mod", False),
                            "is_verified": False,
                            "icon_url": "",
                            "tags": ["local"],
                            "hide_mod": False,
                            "is_piracy_protected": False,
                            "ban_status": False,
                            "demo_url": None,
                            "demo_version": "1.0.0",
                            "created_date": config_data.get("created_date", "N/A"),
                            "last_updated": config_data.get("created_date", "N/A")
                        }

                        mod = ModInfo(**safe_mod_info)
                        # Создаем главы с полной информацией о файлах
                        chapters_data = config_data.get("chapters", {})
                        files_data = config_data.get("files", {})

                        # Находим папку мода один раз
                        mod_folder_path = None
                        for folder_name in os.listdir(self.mods_dir):
                            folder_path = os.path.join(self.mods_dir, folder_name)
                            test_config_path = os.path.join(folder_path, "config.json")
                            if os.path.isfile(test_config_path):
                                try:
                                    test_config = self._read_json(test_config_path)
                                    if test_config.get('mod_key') == mod_key:
                                        mod_folder_path = folder_path
                                        break
                                except Exception as e:
                                    logging.warning(f"Failed reading config {test_config_path}: {e}")
                                    continue

                        for ch_id_str, ch_info in chapters_data.items():
                            ch_id = int(ch_id_str)

                            # Получаем информацию о файлах для этой главы
                            chapter_files = files_data.get(ch_id_str, {})

                            # Определяем папку главы
                            if mod_folder_path:
                                if ch_id == -1:
                                    chapter_folder = os.path.join(mod_folder_path, "demo")
                                elif ch_id == 0:
                                    chapter_folder = os.path.join(mod_folder_path, "chapter_0")
                                else:
                                    chapter_folder = os.path.join(mod_folder_path, f"chapter_{ch_id}")

                            # Создаем data_file_url
                            data_file_url = ""
                            if chapter_files.get("data_win_url") and mod_folder_path:
                                data_file_url = os.path.join(chapter_folder, chapter_files["data_win_url"])

                            # Создаем extra_files
                            from helpers import ModExtraFile
                            extra_files = []
                            if chapter_files.get("extra_files") and mod_folder_path:
                                for group_key, filenames in chapter_files["extra_files"].items():
                                    for filename in filenames:
                                        file_path = os.path.join(chapter_folder, filename)
                                        extra_files.append(ModExtraFile(
                                            key=group_key,
                                            url=file_path,
                                            version="1.0.0"
                                        ))

                            mod_chapter = ModChapterData(
                                description=config_data.get("tagline", ""),
                                data_file_url=data_file_url,
                                data_win_version=chapter_files.get("data_win_version", (ch_info.get("versions", {}) or {}).get("data", "1.0.0")),
                                extra_files=extra_files
                            )
                            mod.chapters[ch_id] = mod_chapter

                        # Добавляем мод только если у него есть хотя бы одна глава
                        if mod.chapters:
                            self.all_mods.append(mod)
                    except Exception as e:
                        logging.warning(f"Failed to build local ModInfo: {e}")
                        continue

            return True
        except Exception as e:
            logging.error(f"_load_local_mods_from_folders failed: {e}")
            return False

    def _get_mod_config_by_key(self, mod_key: str) -> dict:
        """Получает конфиг мода по его ключу из папки модов"""
        if not os.path.exists(self.mods_dir):
            return {}

        for folder_name in os.listdir(self.mods_dir):
            folder_path = os.path.join(self.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue

            config_path = os.path.join(folder_path, "config.json")
            if not os.path.exists(config_path):
                continue

            try:
                config_data = self._read_json(config_path)
                if config_data and config_data.get('mod_key') == mod_key:
                    return config_data
            except Exception as e:
                logging.warning(f"Failed to read mod config {config_path}: {e}")
                continue

        return {}

    def _set_install_buttons_enabled(self, enabled: bool):
        """Блокирует/разблокирует все кнопки установки в плашках модов и библиотеке"""
        # Блокируем кнопки в плашках модов
        if hasattr(self, 'mod_list_layout'):
            for i in range(self.mod_list_layout.count() - 1):  # -1 для stretch
                item = self.mod_list_layout.itemAt(i)
                if item:
                    widget = item.widget()
                    if isinstance(widget, ModPlaqueWidget):
                        widget.install_button.setEnabled(enabled)

        # Блокируем кнопки в библиотеке (установленные моды)
        if hasattr(self, 'installed_mods_layout'):
            for i in range(self.installed_mods_layout.count() - 1):  # -1 для stretch
                item = self.installed_mods_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, InstalledModWidget) and hasattr(widget, 'use_button'):
                        widget.use_button.setEnabled(enabled)

    def _load_all_translations_from_folders(self):
        """Загружает моды из config.json файлов в папках модов"""
        return self._load_local_mods_from_folders()

    def _create_settings_nav_button(self, text: str, on_click: Callable, style_sheet: str = "") -> QPushButton:
        button = QPushButton(text)
        button.setFixedWidth(400)
        base_style = "width: 400px;"
        button.setStyleSheet(f"{base_style} {style_sheet}" if style_sheet else base_style)
        if on_click: button.clicked.connect(on_click)
        return button

    def _create_chapter_tab(self, name: str, chapter_index: int) -> dict:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        label = QLabel(tr("ui.select_mod"))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFont(self.font())
        combo = NoScrollComboBox()
        combo.setFixedWidth(250)
        combo.currentIndexChanged.connect(self._update_ui_for_selection)
        combo_layout = QHBoxLayout()
        combo_layout.addWidget(combo)
        combo_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description = QTextBrowser()
        description.setOpenExternalLinks(True)
        description.setFont(self.font())
        tab_layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignCenter)
        tab_layout.addLayout(combo_layout)
        tab_layout.addWidget(description)
        self.tab_widget.addTab(tab, name)
        return {"combo": combo, "description": description, "label": label}

    def _handle_permission_error(self, path: str):
        detailed_message = tr("dialogs.access_denied_detailed", path=path)
        QMessageBox.critical(self, tr("errors.access_denied"), detailed_message)

    def _get_current_game_path(self) -> str:
        return self.game_mode.get_game_path(self.local_config) or ""

    def _current_tab_names(self):
        return self.game_mode.tab_names

    def init_ui(self):
        # Создаем чекбокс полной установки в самом начале, до создания библиотеки
        self.full_install_checkbox = QCheckBox(tr("ui.install_game_files_first"))
        self.full_install_checkbox.stateChanged.connect(self._on_toggle_full_install)
        self.full_install_checkbox.hide()  # Показываем только в демо-режиме

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)

        self.top_panel_widget = QFrame()
        self.top_frame = QHBoxLayout(self.top_panel_widget) # Основной layout теперь принадлежит виджету
        self.settings_button = QPushButton(tr("ui.settings_title"))
        self.settings_button.clicked.connect(self._toggle_settings_view)

        self.online_label = QLabel(tr("ui.online_status"))
        self.online_label.setStyleSheet("padding-left:8px;")
        self.online_label.setToolTip(tr("tooltips.online_counter"))

        self.top_frame.addWidget(self.settings_button)
        # Top refresh button right after settings
        self.top_refresh_button = QPushButton("🔄️")
        self.top_refresh_button.setObjectName("topRefreshBtn")
        self.top_refresh_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        # Enforce strict square size regardless of layout/styles
        self.top_refresh_button.setMinimumSize(40, 40)
        self.top_refresh_button.setMaximumSize(40, 40)
        self.top_refresh_button.setStyleSheet("min-width:40px; max-width:40px; min-height:40px; max-height:40px; padding:0; margin:0;")
        self.top_refresh_button.setToolTip(tr("ui.update_mod_list"))
        self.top_refresh_button.clicked.connect(lambda: self._refresh_translations(force=True))
        self.top_frame.addWidget(self.top_refresh_button)
        self.top_frame.addWidget(self.online_label)
        self.top_frame.addStretch()

        logo_placeholder = QWidget()
        logo_placeholder.setFixedWidth(225)
        self.top_frame.addWidget(logo_placeholder)

        self.top_frame.addStretch()

        self.telegram_button = QPushButton(tr("buttons.telegram"))
        self.telegram_button.clicked.connect(
            lambda: webbrowser.open(self.global_settings.get("telegram_url", SOCIAL_LINKS["telegram"]))
        )
        self.telegram_button.setStyleSheet(f"color: {UI_COLORS['link']};")
        self.top_frame.addWidget(self.telegram_button)

        self.discord_button = QPushButton(tr("buttons.discord"))
        self.discord_button.clicked.connect(
            lambda: webbrowser.open(self.global_settings.get("discord_url", SOCIAL_LINKS["discord"]))
        )
        self.discord_button.setStyleSheet(f"color: {UI_COLORS['social_discord']};")
        self.top_frame.addWidget(self.discord_button)
        self.main_layout.addWidget(self.top_panel_widget)

        # ИЗМЕНЕНИЕ: Создаем логотип как дочерний элемент контейнера, но ВНЕ layout'а.
        # Это позволяет ему не влиять на высоту панели.
        self.launcher_icon_label = QLabel(self.top_panel_widget)
        self.launcher_icon_label.setFixedSize(225, 80) # Новый, желаемый размер
        self.launcher_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_launcher_icon()

        # Увеличиваем spacing между верхней панелью и вкладками
        self.main_layout.addSpacing(20)

        # Новая система вкладок: "Искать моды", "Библиотека", "Управление модами", "Патчинг (XDELTA)"
        self.main_tab_widget = NoScrollTabWidget()
        self.main_tab_widget.setTabPosition(QTabWidget.TabPosition.North)

        # Создаем вкладки с содержимым
        self.search_mods_tab = self._create_search_mods_tab()
        self.library_tab = self._create_library_tab()

        # Создаем пустые вкладки для кнопок-функций
        self.manage_mods_tab = QWidget()  # Пустая вкладка
        self.xdelta_patch_tab = QWidget()  # Пустая вкладка

        self.main_tab_widget.addTab(self.search_mods_tab, tr("ui.search_tab"))
        self.main_tab_widget.addTab(self.library_tab, tr("ui.library_tab"))
        self.main_tab_widget.addTab(self.manage_mods_tab, tr("ui.mod_management"))
        self.main_tab_widget.addTab(self.xdelta_patch_tab, tr("ui.patching_tab"))

        # Отслеживаем предыдущую активную вкладку для возврата
        self.previous_tab_index = 0
        self.main_tab_widget.currentChanged.connect(self._on_tab_changed)

        # Центрируем вкладки
        self.main_tab_widget.setStyleSheet("""
            QTabWidget::tab-bar {
                alignment: center;
            }
            QTabBar::tab {
                min-width: 120px;
                padding: 8px 16px;
            }
        """)

        self.main_layout.addWidget(self.main_tab_widget)

        self.bottom_widget = QFrame()
        self.bottom_widget.setObjectName("bottom_widget")
        self.bottom_frame = QVBoxLayout(self.bottom_widget)
        self.status_label = QLabel(tr("ui.initialization"))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.action_frame = QHBoxLayout()
        self.shortcut_button = QPushButton(tr("buttons.shortcut"))
        self.shortcut_button.clicked.connect(self._create_shortcut_flow)
        self.action_button = QPushButton(tr("status.please_wait"))
        self.action_button.setEnabled(False)
        self.action_button.setMinimumWidth(200)
        self.action_button.clicked.connect(self._on_action_button_click)

        # Состояния для отслеживания установки
        self.is_installing = False
        self.current_install_thread = None
        self.pending_updates = []
        self.saves_button = QPushButton(tr("ui.saves_button"))
        self.saves_button.setStyleSheet("color: yellow;")
        self.saves_button.clicked.connect(self._on_configure_saves_click)
        self.action_frame.addWidget(self.shortcut_button)
        self.action_frame.addWidget(self.action_button)
        self.action_frame.addWidget(self.saves_button)
        self.bottom_frame.addWidget(self.status_label)
        self.bottom_frame.addWidget(self.progress_bar)
        self.bottom_frame.addLayout(self.action_frame)
        self.main_layout.addWidget(self.bottom_widget)

        self.settings_widget = QFrame()
        self.settings_widget.setObjectName("settings_widget")
        settings_layout = QVBoxLayout(self.settings_widget)
        self.settings_pages_container = QWidget()
        pages_layout = QVBoxLayout(self.settings_pages_container)
        pages_layout.setContentsMargins(0, 0, 0, 0)

        # Определяем страницы до создания кнопок, которые на них ссылаются
        self.settings_customization_page = QWidget()

        self.settings_menu_page = QWidget()
        settings_menu_layout = QVBoxLayout(self.settings_menu_page)
        settings_menu_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        settings_menu_layout.setSpacing(20)

        settings_title_label = QLabel(f"<h1>{tr('ui.settings_title')}</h1>")
        settings_title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        settings_menu_layout.addWidget(settings_title_label)

        # Центрированный контейнер для всех настроек
        settings_menu_layout.addStretch()  # Растяжка сверху

        settings_center_container = QVBoxLayout()
        settings_center_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        settings_center_container.setSpacing(20)  # Одинаковый spacing между всеми элементами

        # Выбор языка
        language_container = QWidget()
        language_layout = QHBoxLayout(language_container)
        language_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        language_layout.setSpacing(10)

        language_label = QLabel(tr("ui.language_label"))
        language_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        language_layout.addWidget(language_label)

        self.language_combo = NoScrollComboBox()
        self.language_combo.setMinimumWidth(200)
        self.language_combo.setMaximumWidth(250)

        # Заполняем комбобокс доступными языками
        manager = get_localization_manager()
        available_languages = manager.get_available_languages()
        current_language = manager.get_current_language()

        for code, name in available_languages.items():
            self.language_combo.addItem(name, code)
            if code == current_language:
                self.language_combo.setCurrentIndex(self.language_combo.count() - 1)

        self.language_combo.currentTextChanged.connect(self._on_language_changed)
        language_layout.addWidget(self.language_combo)

        settings_center_container.addWidget(language_container, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Добавляем дополнительное расстояние перед Steam checkbox
        settings_center_container.addSpacing(30)

        # Чекбокс "Запускать через Steam"
        self.launch_via_steam_checkbox = QCheckBox(tr("ui.steam_launch"))
        self.launch_via_steam_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr("tooltips.steam") + "</body></html>")
        self.launch_via_steam_checkbox.stateChanged.connect(self._on_toggle_steam_launch)
        settings_center_container.addWidget(self.launch_via_steam_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Чекбокс "Отдельный файл запуска"
        self.use_custom_executable_checkbox = QCheckBox(tr("ui.custom_executable"))
        self.use_custom_executable_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr("tooltips.custom_exe") + "</body></html>")
        self.use_custom_executable_checkbox.stateChanged.connect(self._on_toggle_custom_executable)
        settings_center_container.addWidget(self.use_custom_executable_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Кнопка и лейбл для кастомного исполняемого файла
        self.select_custom_executable_button = QPushButton(tr("buttons.select_file"))
        self.select_custom_executable_button.setFixedWidth(153)
        self.select_custom_executable_button.clicked.connect(self._select_custom_executable_file)
        self.custom_executable_path_label = QLabel(tr("ui.file_not_selected"))
        self.custom_executable_path_label.setFixedHeight(20)
        self.custom_exe_frame = QFrame()
        custom_exe_layout = QVBoxLayout(self.custom_exe_frame)
        custom_exe_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        custom_exe_layout.addWidget(self.select_custom_executable_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        custom_exe_layout.addWidget(self.custom_executable_path_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        settings_center_container.addWidget(self.custom_exe_frame, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.custom_exe_frame.setVisible(False)

        # Кнопка выбора пути к игре
        self.change_path_button = QPushButton()
        self.change_path_button.setFixedWidth(300)
        self.change_path_button.clicked.connect(self._prompt_for_game_path)
        settings_center_container.addWidget(self.change_path_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Кнопка смены расположения папки модов
        self.change_mods_dir_button = QPushButton(tr("ui.change_mods_dir"))
        self.change_mods_dir_button.setFixedWidth(400)
        self.change_mods_dir_button.setToolTip(tr("tooltips.change_mods_dir"))
        self.change_mods_dir_button.clicked.connect(self._prompt_for_mods_dir)
        settings_center_container.addWidget(self.change_mods_dir_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Добавляем кнопку "Кастомизация" в тот же центрированный контейнер
        settings_buttons_config = [
            (tr("ui.launcher_customization"), lambda: self._switch_settings_page(self.settings_customization_page), "")
        ]

        created_buttons = {}

        for i, (text, handler, style) in enumerate(settings_buttons_config):
            button = self._create_settings_nav_button(text, handler, style)
            created_buttons[text] = button
            settings_center_container.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.settings_customization_button = created_buttons[tr("ui.launcher_customization")]

        settings_menu_layout.addLayout(settings_center_container)
        settings_menu_layout.addStretch()  # Растяжка снизу для центрирования
        pages_layout.addWidget(self.settings_menu_page)



        self.disable_background_checkbox = QCheckBox(tr("checkboxes.disable_background"))
        self.disable_background_checkbox.stateChanged.connect(self._on_toggle_disable_background)

        self.disable_splash_checkbox = QCheckBox(tr("checkboxes.disable_splash"))
        self.disable_splash_checkbox.stateChanged.connect(self._on_toggle_disable_splash)

        self.change_background_button = QPushButton(tr("buttons.change_background"))
        self.change_background_button.clicked.connect(self._on_background_button_click)

        settings_customization_layout = QVBoxLayout(self.settings_customization_page)
        back_button_cust = QPushButton(tr("ui.back_button"))
        back_button_cust.clicked.connect(self._go_back)
        settings_customization_layout.addWidget(back_button_cust, alignment=Qt.AlignmentFlag.AlignLeft)
        settings_customization_layout.addSpacing(15)

        # Кнопка смены фона
        self.change_background_button = QPushButton() # Text set in _update_background_button_state
        self.change_background_button.setFixedWidth(400)
        self.change_background_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.change_background_button.clicked.connect(self._on_background_button_click)
        settings_customization_layout.addWidget(self.change_background_button, 0, Qt.AlignmentFlag.AlignHCenter)
        settings_customization_layout.addSpacing(8)

        # Контейнер для кнопок музыки и звука заставки
        sound_buttons_layout = QHBoxLayout()
        sound_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sound_buttons_layout.setSpacing(10)

        # Кнопка фоновой музыки (ширина увеличена)
        self.background_music_button = QPushButton(self._get_background_music_button_text())
        self.background_music_button.setFixedWidth(275)
        self.background_music_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.background_music_button.clicked.connect(self._on_background_music_button_click)
        sound_buttons_layout.addWidget(self.background_music_button)

        # Кнопка звука заставки (ширина увеличена)
        self.startup_sound_button = QPushButton(self._get_startup_sound_button_text())
        self.startup_sound_button.setFixedWidth(275)
        self.startup_sound_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.startup_sound_button.clicked.connect(self._on_startup_sound_button_click)
        sound_buttons_layout.addWidget(self.startup_sound_button)

        settings_customization_layout.addLayout(sound_buttons_layout)
        settings_customization_layout.addSpacing(20)

        # --- ИЗМЕНЕНИЕ ---
        # Сначала добавляем чекбоксы
        checkboxes_layout = QHBoxLayout()
        checkboxes_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        checkboxes_layout.setSpacing(20)
        checkboxes_layout.addWidget(self.disable_background_checkbox)
        checkboxes_layout.addWidget(self.disable_splash_checkbox)
        settings_customization_layout.addLayout(checkboxes_layout)
        settings_customization_layout.addSpacing(8)

        # Затем добавляем громкость, под чекбоксами
        # Удалено: управление громкостью

        self.custom_style_frame = QFrame()
        custom_style_layout = QVBoxLayout(self.custom_style_frame)
        custom_style_layout.setContentsMargins(0, 15, 0, 0)
        custom_style_layout.setSpacing(8)

        def create_setting_row(label_text: str) -> tuple[QHBoxLayout, QLineEdit, QPushButton]:
            layout = QHBoxLayout()
            label = QLabel(label_text)
            color_display = QLineEdit()
            color_display.setFixedWidth(95)
            color_display.setReadOnly(True)
            color_btn = QPushButton(tr("ui.select_color"))
            color_btn.setFixedWidth(150)
            reset_btn = QPushButton("⭯")
            reset_btn.setStyleSheet("min-width: 35px; max-width: 35px; padding-left: 0px; padding-right: 0px;")
            reset_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            reset_btn.clicked.connect(lambda: (color_display.clear(), self._on_custom_style_edited()))
            layout.addWidget(label)
            layout.addStretch()
            for widget in [color_display, color_btn, reset_btn]: layout.addWidget(widget)
            return layout, color_display, color_btn

        self.color_widgets = {}
        self.color_config = {
            "background": tr("ui.background_color"), "button": tr("ui.elements_color"), "border": tr("ui.border_color"),
            "button_hover": tr("ui.hover_color"), "text": tr("ui.main_text_color"),
            "version_text": tr("ui.secondary_text_color"),
        }

        def pick_color_for_edit(target_edit):
            if (color := QColorDialog.getColor()).isValid(): target_edit.setText(color.name()); self._on_custom_style_edited()

        for key, label in self.color_config.items():
            layout, line_edit, btn = create_setting_row(label)
            line_edit.editingFinished.connect(self._on_custom_style_edited)
            btn.clicked.connect(lambda _, le=line_edit: pick_color_for_edit(le))
            self.color_widgets[key] = line_edit
            custom_style_layout.addLayout(layout)

        settings_customization_layout.addWidget(self.custom_style_frame)

        settings_customization_layout.addStretch()


        pages_layout.addWidget(self.settings_customization_page)
        self.settings_customization_page.setVisible(False)

        self.changelog_widget = QFrame()
        self.changelog_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        changelog_layout = QVBoxLayout(self.changelog_widget)
        self.changelog_text_edit = QTextBrowser()
        self.changelog_text_edit.setOpenExternalLinks(True)
        # Не позволять содержимому растягивать окно — ограничим максимальную высоту
        self.changelog_text_edit.setMinimumHeight(0)
        self.changelog_text_edit.setMaximumHeight(500)
        current_font = self.font()
        self.changelog_text_edit.setFont(current_font)
        doc = self.changelog_text_edit.document()
        if doc is not None:
            doc.setDefaultFont(current_font)
            doc.setDefaultStyleSheet(
                "p { margin-bottom: 0.75em; } "
                "ul, ol { margin-left: 1em; } "
                "li { margin-bottom: 0.25em; }"
            )

        self.changelog_text_edit.setOpenExternalLinks(True)
        self.changelog_text_edit.setMarkdown(f"<i>{tr('status.loading')}</i>")

        changelog_layout.addWidget(self.changelog_text_edit)

        # Создаем виджет помощи (аналогично changelog_widget)
        self.help_widget = QFrame()
        self.help_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        help_layout = QVBoxLayout(self.help_widget)
        self.help_text_edit = QTextBrowser()
        self.help_text_edit.setOpenExternalLinks(True)
        # Не позволять содержимому растягивать окно — ограничим максимальную высоту
        self.help_text_edit.setMinimumHeight(0)
        self.help_text_edit.setMaximumHeight(500)
        help_font = self.font()
        self.help_text_edit.setFont(help_font)
        help_doc = self.help_text_edit.document()
        if help_doc is not None:
            help_doc.setDefaultFont(help_font)
            help_doc.setDefaultStyleSheet(
                "p { margin-bottom: 0.75em; } "
                "ul, ol { margin-left: 1em; } "
                "li { margin-bottom: 0.25em; }"
            )

        self.help_text_edit.setOpenExternalLinks(True)
        self.help_text_edit.setMarkdown(f"<i>{tr('status.loading')}</i>")

        help_layout.addWidget(self.help_text_edit)

        self.changelog_button = QPushButton(tr("buttons.changelog"))
        self.changelog_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.changelog_button.setStyleSheet("min-width: 200px; max-width: 200px;")
        self.changelog_button.clicked.connect(self._toggle_changelog_view)

        # Добавляем кнопку "Помощь"
        self.help_button = QPushButton(tr("buttons.help"))
        self.help_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.help_button.setStyleSheet("min-width: 200px; max-width: 200px;")
        self.help_button.clicked.connect(self._toggle_help_view)

        settings_layout.addWidget(self.settings_pages_container)
        self.changelog_widget.setVisible(False)
        settings_layout.addWidget(self.changelog_widget, stretch=1)
        self.help_widget.setVisible(False)
        settings_layout.addWidget(self.help_widget, stretch=1)
        button_bar_layout = QHBoxLayout()
        button_bar_layout.setSpacing(10)
        button_bar_layout.addStretch(1)
        button_bar_layout.addWidget(self.changelog_button)
        button_bar_layout.addWidget(self.help_button)
        button_bar_layout.addStretch(1)

        settings_layout.addLayout(button_bar_layout)
        self.settings_widget.setVisible(False)
        self.main_layout.addWidget(self.settings_widget)

        self.save_manager_widget = QFrame()
        self.save_manager_widget.setObjectName("save_manager_widget")
        self._init_save_manager_ui()
        self.save_manager_widget.setVisible(False)
        self.main_layout.addWidget(self.save_manager_widget)
        self.current_settings_page = self.settings_menu_page
        # Старые соединения для совместимости (временно)
        # TODO: удалить после полной миграции на новый дизайн
        self.tab_widget = self.main_tab_widget  # Для совместимости
        self.tabs = {}  # Для совместимости

        # Заглушки для старых элементов интерфейса (для совместимости)
        # self.full_install_checkbox уже создан в начале init_ui()

        self._chapter_btns = []  # Пустой список кнопок глав
        self.chapter_btn_widget = QWidget()  # Заглушка виджета кнопок
        self.chapter_btn_widget.hide()

        self._chapter_btn_bar = QHBoxLayout()  # Заглушка лейаута кнопок

        # TODO: заменить на main_tab_widget.currentChanged когда будет готово
        # self.main_tab_widget.currentChanged.connect(self._update_ui_for_selection)

    def _on_tab_changed(self, index):
        """Обработчик переключения вкладок"""
        # Индексы вкладок: 0 - Искать моды, 1 - Библиотека, 2 - Управление модами, 3 - Патчинг
        if index == 2:  # Управление модами
            # Выполняем функцию управления модами
            self._on_manage_mods_click()
            # Возвращаемся на предыдущую вкладку
            self.main_tab_widget.setCurrentIndex(self.previous_tab_index)
        elif index == 3:  # Патчинг (XDELTA)
            # Выполняем функцию патчинга
            self._on_xdelta_patch_click()
            # Возвращаемся на предыдущую вкладку
            self.main_tab_widget.setCurrentIndex(self.previous_tab_index)
        else:
            # Обновляем предыдущую активную вкладку только для обычных вкладок
            self.previous_tab_index = index

    def _on_mods_loaded(self):
        """Обработчик загрузки модов"""
        if self.initialization_timer and self.initialization_timer.isActive():
            self.initialization_timer.stop()
        self.initialization_completed = True
        self.initialization_finished.emit()

    def _force_finish_initialization(self):
        """Принудительно завершает инициализацию по таймауту"""
        self.mods_loaded = True
        self.initialization_completed = True
        self.initialization_finished.emit()

    def _create_search_mods_tab(self):
        """Создает вкладку 'Искать моды' на основе newdesign.py"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Инициализация переменных пагинации и фильтрации
        self.current_page = 1
        self.mods_per_page = 15
        self.filtered_mods = []

        # Фильтры
        filters_widget = self._create_filters_widget()
        layout.addWidget(filters_widget)

        # Контейнер для списка модов и пагинации с общим фоном
        self.search_container = QWidget()
        self.search_container.setObjectName("search_mods_background")
        search_container_layout = QVBoxLayout(self.search_container)
        search_container_layout.setContentsMargins(10, 10, 10, 10)
        search_container_layout.setSpacing(10)

        # Список модов
        self.search_mods_scroll = QScrollArea()
        self.search_mods_scroll.setWidgetResizable(True)
        self.search_mods_scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Убираем фон у scroll area, так как фон теперь у контейнера
        self.search_mods_scroll.setStyleSheet("QScrollArea { background-color: transparent; }")

        self.mod_list_widget = QWidget()
        self.mod_list_layout = QVBoxLayout(self.mod_list_widget)
        self.mod_list_layout.setSpacing(15)
        self.mod_list_layout.addStretch()  # Чтобы плашки не растягивались

        self.search_mods_scroll.setWidget(self.mod_list_widget)
        search_container_layout.addWidget(self.search_mods_scroll)

        # Пагинация теперь внутри контейнера с фоном
        pagination_widget = self._create_pagination_widget()
        search_container_layout.addWidget(pagination_widget)

        # Применяем фон к общему контейнеру
        search_bg_color = get_theme_color(self.local_config, "background", "#000000")
        r, g, b = (int(search_bg_color[1:3], 16), int(search_bg_color[3:5], 16), int(search_bg_color[5:7], 16)) if search_bg_color.startswith('#') else (0, 0, 0)
        search_bg_rgba = f"rgba({r}, {g}, {b}, 128)"
        self.search_container.setStyleSheet(f"""
            QWidget#search_mods_background {{
                background-color: {search_bg_rgba};
                border-radius: 10px;
                margin: 5px;
            }}
        """)

        layout.addWidget(self.search_container)

        return widget

    def _create_library_tab(self):
        """Создает вкладку 'Библиотека' с системой слотов"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Управление демоверсией и режимами
        controls_layout = QHBoxLayout()
        controls_layout.addStretch()  # Добавляем растяжку слева

        self.demo_mode_checkbox = QCheckBox(tr("checkboxes.demo_version"))
        self.demo_mode_checkbox.stateChanged.connect(self._on_demo_mode_changed)
        controls_layout.addWidget(self.demo_mode_checkbox)

        controls_layout.addSpacing(20)

        self.chapter_mode_checkbox = QCheckBox(tr("ui.chapter_mode"))
        self.chapter_mode_checkbox.stateChanged.connect(self._on_chapter_mode_changed)
        controls_layout.addWidget(self.chapter_mode_checkbox)

        # Загружаем сохраненные состояния галочек
        saved_demo_mode = self.local_config.get('demo_mode_enabled', False)
        saved_chapter_mode = self.local_config.get('chapter_mode_enabled', False)

        # Блокируем сигналы при загрузке состояния, чтобы избежать лишних вызовов
        self.demo_mode_checkbox.blockSignals(True)
        self.chapter_mode_checkbox.blockSignals(True)

        self.demo_mode_checkbox.setChecked(saved_demo_mode)
        self.chapter_mode_checkbox.setChecked(saved_chapter_mode)

        # Устанавливаем game_mode в соответствии с загруженным состоянием
        if saved_demo_mode:
            self.game_mode = DemoGameMode()
        else:
            self.game_mode = FullGameMode()

        # Обновляем взаимное блокирование галочек
        if saved_demo_mode:
            self.chapter_mode_checkbox.setEnabled(False)
        elif saved_chapter_mode:
            self.demo_mode_checkbox.setEnabled(False)

        # Разблокируем сигналы
        self.demo_mode_checkbox.blockSignals(False)
        self.chapter_mode_checkbox.blockSignals(False)

        # Устанавливаем режим работы
        if saved_chapter_mode:
            self.current_mode = "chapter"
        else:
            self.current_mode = "normal"

        # Инициализируем предыдущий режим для корректного переключения
        self._previous_mode = self.current_mode

        controls_layout.addStretch()  # Добавляем растяжку справа
        layout.addLayout(controls_layout)

        # Инициализируем выбранный слот
        self.selected_chapter_id = None

        # Система слотов
        self.slots_container = QWidget()
        self.slots_layout = QVBoxLayout(self.slots_container)

        # Контейнер для слотов (будет обновляться в зависимости от режима)
        self.active_slots_widget = QWidget()
        self.active_slots_widget.setObjectName("slots_background")
        self.active_slots_layout = QHBoxLayout(self.active_slots_widget)
        self.active_slots_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.active_slots_layout.setContentsMargins(20, 15, 20, 15)
        self.active_slots_layout.setSpacing(0)

        # Устанавливаем полупрозрачный фон для области слотов
        slots_bg_color = get_theme_color(self.local_config, "background", "#000000")
        # Добавляем полупрозрачность через rgba
        if slots_bg_color.startswith('#'):
            r = int(slots_bg_color[1:3], 16)
            g = int(slots_bg_color[3:5], 16)
            b = int(slots_bg_color[5:7], 16)
            slots_bg_rgba = f"rgba({r}, {g}, {b}, 128)"  # 128 = 50% от 255
        else:
            slots_bg_rgba = "rgba(0, 0, 0, 128)"

        self.active_slots_widget.setStyleSheet(f"""
            QWidget#slots_background {{
                background-color: {slots_bg_rgba};
                border-radius: 10px;
                margin: 5px;
            }}
        """)

        self.slots_layout.addWidget(self.active_slots_widget)
        layout.addWidget(self.slots_container)

        # Контейнер для установленных модов с заголовком
        self.installed_mods_container = QWidget()
        self.installed_mods_container.setObjectName("mods_background")
        mods_container_layout = QVBoxLayout(self.installed_mods_container)
        mods_container_layout.setContentsMargins(15, 15, 15, 15)  # Отступы для фона
        mods_container_layout.setSpacing(10)

        # Заголовок списка модов
        installed_mods_label = QLabel(tr("ui.installed_mods_label"))
        installed_mods_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        installed_mods_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mods_container_layout.addWidget(installed_mods_label)

        # Scroll area для списка модов
        self.installed_mods_scroll = QScrollArea()
        self.installed_mods_scroll.setWidgetResizable(True)
        self.installed_mods_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.installed_mods_widget = QWidget()
        self.installed_mods_layout = QVBoxLayout(self.installed_mods_widget)
        self.installed_mods_layout.addStretch()
        self.installed_mods_layout.setContentsMargins(0, 0, 0, 0)  # Убираем отступы, так как они теперь в контейнере

        self.installed_mods_scroll.setWidget(self.installed_mods_widget)
        mods_container_layout.addWidget(self.installed_mods_scroll)

        # Устанавливаем полупрозрачный фон для контейнера модов
        mods_bg_color = get_theme_color(self.local_config, "background", "#000000")
        # Добавляем полупрозрачность через rgba
        if mods_bg_color.startswith('#'):
            r = int(mods_bg_color[1:3], 16)
            g = int(mods_bg_color[3:5], 16)
            b = int(mods_bg_color[5:7], 16)
            mods_bg_rgba = f"rgba({r}, {g}, {b}, 128)"  # 128 = 50% от 255
        else:
            mods_bg_rgba = "rgba(0, 0, 0, 128)"

        self.installed_mods_container.setStyleSheet(f"""
            QWidget#mods_background {{
                background-color: {mods_bg_rgba};
                border-radius: 10px;
                margin: 5px;
            }}
        """)

        layout.addWidget(self.installed_mods_container)

        # Слоты будут инициализированы позже, после восстановления режима

        # Загружаем установленные моды при создании вкладки
        QTimer.singleShot(500, self._update_installed_mods_display)

        # Дополнительное обновление состояния кнопок после загрузки слотов
        QTimer.singleShot(700, self._update_mod_widgets_slot_status)

        # Теперь инициализируем слоты в правильном режиме (после создания UI)
        self._init_slots_system()

        # Загружаем сохраненное состояние слотов после инициализации
        QTimer.singleShot(400, self._load_slots_state)

        return widget

    def _create_filters_widget(self):
        """Создает виджет фильтров для поиска модов"""
        filters_widget = QFrame()
        filters_widget.setObjectName("filters")
        filters_widget.setFixedHeight(55)
        filters_layout = QHBoxLayout(filters_widget)
        filters_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        filters_layout.setContentsMargins(0,0,0,0)

        # Сортировка
        self.sort_combo = NoScrollComboBox()
        self.sort_combo.addItems([tr("ui.sort_by_downloads"), tr("ui.sort_by_update_date"), tr("ui.sort_by_creation_date")])
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        filters_layout.addWidget(self.sort_combo)

        # Кнопка изменения порядка сортировки (квадратная)
        self.sort_order_btn = QPushButton("▼")
        self.sort_order_btn.setObjectName("sortOrderBtn")
        self.sort_order_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.sort_order_btn.setToolTip(tr("ui.sort_direction_tooltip"))
        self.sort_ascending = False  # По умолчанию по убыванию
        self.sort_order_btn.clicked.connect(self._toggle_sort_order)
        filters_layout.addWidget(self.sort_order_btn)

        filters_layout.addSpacing(20)

        # Теги
        filters_layout.addWidget(QLabel(tr("ui.tags_label")))

        # Все теги в одной линии
        self.tag_translation = QCheckBox(tr("tags.translation"))
        self.tag_customization = QCheckBox(tr("tags.customization"))
        self.tag_gameplay = QCheckBox(tr("tags.gameplay"))
        self.tag_other = QCheckBox(tr("tags.other"))
        self.tag_demo = QCheckBox(tr("tags.demo"))

        # Стилизация для чекбоксов
        tag_style = """
            QCheckBox {
                color: white;
                font-size: 12px;
                spacing: 5px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
        """

        for tag in [self.tag_translation, self.tag_customization, self.tag_gameplay, self.tag_other, self.tag_demo]:
            tag.setStyleSheet(tag_style)
            tag.stateChanged.connect(self._on_tag_filter_changed)
            filters_layout.addWidget(tag)

        filters_layout.addStretch()

        # Кнопка поиска (справа)
        self.search_text = ""  # Переменная для хранения текста поиска
        self.search_button = QPushButton("🔍")
        self.search_button.setObjectName("searchBtn")
        self.search_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.search_button.setFixedSize(35, 35)  # Квадратная кнопка
        self.search_button.setToolTip(tr("tooltips.search"))
        self.search_button.clicked.connect(self._show_search_dialog)
        filters_layout.addWidget(self.search_button)

        return filters_widget

    def _create_pagination_widget(self):
        """Создает виджет пагинации"""
        pagination_widget = QWidget()
        pagination_layout = QHBoxLayout(pagination_widget)
        pagination_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.prev_page_btn = QPushButton(tr("ui.prev_page"))
        self.prev_page_btn.clicked.connect(self._prev_page)
        self.prev_page_btn.setEnabled(False)
        # Настраиваем размер кнопки и выравнивание
        self.prev_page_btn.setMaximumHeight(24)
        self.prev_page_btn.setStyleSheet("font-size: 12px; padding: 3px 8px;")
        pagination_layout.addWidget(self.prev_page_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.page_label = QLabel(tr("ui.page_label", current=1, total=1))
        # Настраиваем размер текста и выравнивание
        self.page_label.setStyleSheet("font-size: 14px; padding: 0px 10px;")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pagination_layout.addWidget(self.page_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.next_page_btn = QPushButton(tr("ui.next_page"))
        self.next_page_btn.clicked.connect(self._next_page)
        self.next_page_btn.setEnabled(False)
        # Настраиваем размер кнопки и выравнивание
        self.next_page_btn.setMaximumHeight(24)
        self.next_page_btn.setStyleSheet("font-size: 12px; padding: 3px 8px;")
        pagination_layout.addWidget(self.next_page_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        return pagination_widget

    def _toggle_sort_order(self):
        """Переключает порядок сортировки"""
        self.sort_ascending = not self.sort_ascending
        if self.sort_ascending:
            self.sort_order_btn.setText("▲")
            self.sort_order_btn.setToolTip(tr("ui.ascending"))
        else:
            self.sort_order_btn.setText("▼")
            self.sort_order_btn.setToolTip(tr("ui.descending"))
        self._update_filtered_mods()

    def _on_sort_changed(self, index):
        """Обработчик изменения критерия сортировки"""
        self._update_filtered_mods()

    def _on_tag_filter_changed(self, state):
        """Обработчик изменения состояния тегов для фильтрации"""
        self.current_page = 1  # Сбрасываем на первую страницу при изменении фильтров
        self._update_filtered_mods()

    def _show_search_dialog(self):
        """Показывает диалог поиска или сбрасывает поиск"""
        if self.search_text:
            # Если поиск активен, сбрасываем его
            self.search_text = ""
            self.search_button.setText("🔍")
            self.search_button.setToolTip(tr("ui.search_mods_placeholder"))
            self._update_filtered_mods()
        else:
            # Показываем диалог поиска
            text, ok = QInputDialog.getText(self, tr("ui.search_mods"), tr("ui.search_in_name_description"))
            if ok and text.strip():
                self.search_text = text.strip()
                self.search_button.setText("↻")
                self.search_button.setToolTip(tr("ui.clear_search_tooltip", search_text=self.search_text))
                self._update_filtered_mods()

    def _prev_page(self):
        """Переход на предыдущую страницу"""
        if self.current_page > 1:
            self.current_page -= 1
            self._update_mod_display()

    def _next_page(self):
        """Переход на следующую страницу"""
        total_pages = (len(self.filtered_mods) - 1) // self.mods_per_page + 1
        if self.current_page < total_pages:
            self.current_page += 1
            self._update_mod_display()

    def _init_slots_system(self):
        """Инициализирует систему слотов"""
        # Создаем слоты
        self.slots = {}
        # current_mode и selected_chapter_id уже инициализированы выше
        self._update_slots_display()

    def _on_demo_mode_changed(self, state):
        """Обработчик изменения режима демоверсии"""
        # Сохраняем предыдущий режим
        old_mode = getattr(self, 'current_mode', 'normal')
        old_game_mode = 'demo' if isinstance(getattr(self, 'game_mode', None), DemoGameMode) else old_mode
        self._previous_mode = old_game_mode

        is_demo = bool(state)
        # ВАЖНО: Обновляем game_mode!
        if is_demo:
            self.game_mode = DemoGameMode()
        else:
            self.game_mode = FullGameMode()

        # При включении демоверсии отключаем поглавный режим
        if is_demo and self.chapter_mode_checkbox.isChecked():
            self.chapter_mode_checkbox.setChecked(False)
            self.current_mode = "normal"

        # Блокируем/разблокируем поглавный режим
        self.chapter_mode_checkbox.setEnabled(not is_demo)

        # Обновляем отображение слотов (это важно делать после смены game_mode)
        self._update_slots_display()

        # Обновляем список установленных модов в соответствии с режимом
        self._update_installed_mods_display()

        # Обновляем текст кнопки смены пути игры
        self._update_change_path_button_text()

        # Сохраняем состояние демо-режима
        self.local_config['demo_mode_enabled'] = is_demo
        self._write_local_config()

    def _on_chapter_mode_changed(self, state):
        """Обработчик изменения поглавного режима"""
        # Сохраняем предыдущий режим
        old_mode = getattr(self, 'current_mode', 'normal')
        self._previous_mode = old_mode

        is_chapter = bool(state)

        # При включении поглавного режима отключаем демоверсию
        if is_chapter and self.demo_mode_checkbox.isChecked():
            self.demo_mode_checkbox.setChecked(False)

        # Блокируем/разблокируем демоверсию
        self.demo_mode_checkbox.setEnabled(not is_chapter)

        self.current_mode = "chapter" if is_chapter else "normal"

        # _update_slots_display() автоматически сохранит текущие слоты перед очисткой
        self._update_slots_display()

        # Обновляем состояние кнопок и интерфейса при переключении режимов
        self._update_mod_widgets_slot_status()
        self._update_ui_for_selection()

        # Обновляем отображение модов в зависимости от режима
        if is_chapter:
            # В поглавном режиме сбрасываем выбор слотов и показываем сообщение
            for slot_frame in self.slots.values():
                slot_frame.is_selected = False
                self._update_slot_visual_state(slot_frame)
            self.selected_chapter_id = None  # Сбрасываем выбранный слот
            self._show_chapter_mode_instruction()
        else:
            # В обычном режиме сбрасываем выбранный слот и показываем стандартный список
            self.selected_chapter_id = None
            self._update_installed_mods_display()

        # Обновляем текст кнопки смены пути игры
        self._update_change_path_button_text()

        # Сохраняем состояние галочки поглавного режима
        self.local_config['chapter_mode_enabled'] = is_chapter
        self._write_local_config()

    def _show_chapter_mode_instruction(self):
        """Показывает инструкцию для поглавного режима"""
        if not hasattr(self, 'installed_mods_layout'):
            return

        # Очищаем текущий список
        clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)

        # Создаем инструкцию
        instruction_widget = QLabel(tr("ui.chapter_mode_instruction"))
        instruction_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction_widget.setStyleSheet("""
            QLabel {
                color: #CCCCCC;
                font-size: 14px;
                font-style: italic;
                padding: 20px;
                border: 2px dashed #666666;
                background-color: rgba(255, 255, 255, 0.1);
            }
        """)
        instruction_widget.setWordWrap(True)
        instruction_widget.setMinimumHeight(80)

        # Вставляем перед stretch элементом
        self.installed_mods_layout.insertWidget(self.installed_mods_layout.count() - 1, instruction_widget)

    def _update_slots_display(self):
        """Обновляет отображение слотов в зависимости от режима"""

        # Проверяем, что это не первый вызов (когда слоты еще не инициализированы)
        has_existing_slots = hasattr(self, 'slots') and self.slots

        # Определяем предыдущий режим для корректного сохранения
        old_mode = getattr(self, '_previous_mode', None)

        # ВАЖНО: Сохраняем слоты в конфиг ПЕРЕД очисткой (только если слоты уже существуют)
        if has_existing_slots and old_mode:
            self._save_slots_state_for_mode(old_mode)
        elif has_existing_slots:
            self._save_slots_state()  # Fallback для первого запуска

        # Сохраняем текущее состояние слотов в памяти для восстановления
        if not hasattr(self, 'saved_slots_state'):
            self.saved_slots_state = {}

        # Сохраняем назначенные моды перед очисткой
        if has_existing_slots:
            for slot_id, slot_frame in self.slots.items():
                if slot_frame.assigned_mod:
                    self.saved_slots_state[slot_id] = slot_frame.assigned_mod

        # Очищаем текущие слоты
        if hasattr(self, 'active_slots_layout'):
            clear_layout_widgets(self.active_slots_layout, keep_last_n=0)

        if not hasattr(self, 'slots'):
            self.slots = {}
        else:
            self.slots.clear()

        # Проверяем демо-режим
        is_demo_mode = isinstance(self.game_mode, DemoGameMode)
        if self.current_mode == "normal":
            if is_demo_mode:
                # Демо слот (отдельный от универсального)
                slot = self._create_slot_widget(tr("ui.demo_slot"), -2)  # -2 для демо
                self.active_slots_layout.addWidget(slot)
                self.active_slots_layout.addSpacing(20)
                self.slots[-2] = slot

                # Добавляем чекбокс установки как отдельный виджет (по аналогии с индикаторами глав)
                self._create_demo_install_checkbox()

                # Восстанавливаем сохраненный мод для демо слота (только если совместим с демо режимом)
                if -2 in self.saved_slots_state:
                    self._assign_mod_to_slot(slot, self.saved_slots_state[-2])
            else:
                # Один слот для обычного режима
                slot = self._create_slot_widget(tr("ui.mod_slot"), -1)
                self.active_slots_layout.addWidget(slot)
                self.slots[-1] = slot

                # Добавляем индикаторы глав
                self._create_chapter_indicators()

                # Восстанавливаем сохраненный мод для универсального слота (только если совместим с обычным режимом)
                if -1 in self.saved_slots_state:
                    self._assign_mod_to_slot(slot, self.saved_slots_state[-1])
        else:
            # Пять слотов для поглавного режима
            slot_names = [tr("chapters.menu"), tr("tabs.chapter_1"), tr("tabs.chapter_2"), tr("tabs.chapter_3"), tr("tabs.chapter_4")]
            for i, name in enumerate(slot_names):
                slot = self._create_slot_widget(name, i)
                self.active_slots_layout.addWidget(slot)
                self.slots[i] = slot
                # Восстанавливаем сохраненный мод для слота главы (только если совместим с поглавным режимом)
                if i in self.saved_slots_state and i in [0, 1, 2, 3, 4]:
                    self._assign_mod_to_slot(slot, self.saved_slots_state[i])

        # После создания всех слотов загружаем состояние из конфига для нового режима
        new_mode = self.current_mode
        if isinstance(self.game_mode, DemoGameMode):
            new_mode = 'demo'
        self._load_slots_state(new_mode)

        # После создания всех слотов - чекбокс уже добавлен при создании демо-слота

    def _create_chapter_indicators(self):
        """Создает индикаторы глав для универсального слота"""
        chapter_names = [tr("ui.menu_label"), tr("ui.chapter_1_label"), tr("ui.chapter_2_label"), tr("ui.chapter_3_label"), tr("ui.chapter_4_label")]
        self.chapter_indicators = {}

        # Получаем цвет основного текста
        main_text_color = get_theme_color(self.local_config, "text", "white")

        for i, chapter_name in enumerate(chapter_names):
            # Создаем контейнер для индикатора
            indicator_frame = QFrame()
            indicator_layout = QVBoxLayout(indicator_frame)
            indicator_layout.setContentsMargins(5, 5, 5, 5)
            indicator_layout.setSpacing(2)

            # Текст главы
            chapter_label = QLabel(chapter_name)
            chapter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chapter_label.setStyleSheet(f"color: {main_text_color}; font-size: 14px; font-weight: bold;")

            # Индикатор (знак вопроса по умолчанию)
            status_label = QLabel("?")
            status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_label.setStyleSheet("color: #FFD700; font-size: 16px; font-weight: bold;")

            indicator_layout.addWidget(chapter_label)
            indicator_layout.addWidget(status_label)

            # Сохраняем ссылки на элементы индикатора
            self.chapter_indicators[i] = {
                'status_label': status_label,
                'chapter_label': chapter_label,
                'frame': indicator_frame
            }

            # Добавляем в layout
            self.active_slots_layout.addWidget(indicator_frame)

    def _create_demo_install_checkbox(self):
        """Создает чекбокс установки для демо-слота (по аналогии с индикаторами глав)"""
        # Создаем контейнер для чекбокса
        checkbox_frame = QFrame()
        checkbox_layout = QVBoxLayout(checkbox_frame)
        checkbox_layout.setContentsMargins(0, 5, 5, 5)  # Убрали левый отступ
        checkbox_layout.setSpacing(0)
        checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Добавляем чекбокс в контейнер
        self.full_install_checkbox.setVisible(True)
        checkbox_layout.addWidget(self.full_install_checkbox)

        # Сохраняем ссылку для управления видимостью
        self.demo_checkbox_frame = checkbox_frame

        # Добавляем контейнер в layout рядом со слотом
        self.active_slots_layout.addWidget(checkbox_frame)

    def _update_chapter_indicators(self, mod=None):
        """Обновляет индикаторы глав на основе выбранного мода"""
        if not hasattr(self, 'chapter_indicators'):
            return

        if mod is None:
            # Нет мода - показываем знаки вопроса
            for i in range(5):
                if i in self.chapter_indicators:
                    self.chapter_indicators[i]['status_label'].setText("?")
                    self.chapter_indicators[i]['status_label'].setStyleSheet("color: #FFD700; font-size: 16px; font-weight: bold;")
        else:
            # Есть мод - проверяем какие главы поддерживает
            for i in range(5):
                if i in self.chapter_indicators:
                    has_files = self._mod_has_files_for_chapter(mod, i)
                    if has_files:
                        self.chapter_indicators[i]['status_label'].setText("✓")
                        self.chapter_indicators[i]['status_label'].setStyleSheet("color: #00FF00; font-size: 16px; font-weight: bold;")
                    else:
                        self.chapter_indicators[i]['status_label'].setText("✗")
                        self.chapter_indicators[i]['status_label'].setStyleSheet("color: #FF0000; font-size: 16px; font-weight: bold;")

    def _update_chapter_indicators_style(self):
        """Обновляет стили индикаторов глав"""
        if hasattr(self, 'chapter_indicators'):
            main_text_color = get_theme_color(self.local_config, "text", "white")
            for indicator_data in self.chapter_indicators.values():
                if 'chapter_label' in indicator_data:
                    indicator_data['chapter_label'].setStyleSheet(f"color: {main_text_color}; font-size: 14px; font-weight: bold;")

    def _create_slot_widget(self, name, chapter_id):
        """Создает виджет слота"""
        slot_frame = SlotFrame()

        # Размеры слотов
        if chapter_id == -2:
            slot_frame.setFixedSize(250, 100)  # Демо слот еще шире и выше
        elif chapter_id == -1:
            slot_frame.setFixedSize(250, 100)  # Универсальный слот тоже широкий и выше
        else:
            slot_frame.setFixedSize(150, 100)  # Увеличили высоту для слотов глав

        slot_frame.setObjectName("mod_slot")

        # Используем кастомизируемый фон для слотов с добавлением прозрачности
        user_bg_hex = get_theme_color(self.local_config, "background", None)
        if user_bg_hex and self._is_valid_hex_color(user_bg_hex):
            # Добавляем ~75% непрозрачности (C0) к пользовательскому HEX цвету
            slot_bg_color = f"#C0{user_bg_hex.lstrip('#')}"
        else:
            # Цвет по умолчанию - полупрозрачный черный
            slot_bg_color = "rgba(0, 0, 0, 150)"
        slot_border_color = get_theme_color(self.local_config, "border", "white")

        # Добавляем курсор указатель для клика
        slot_frame.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(slot_frame)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Название слота
        name_label = QLabel(name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet("font-weight: bold; border: none; background-color: transparent;")
        layout.addWidget(name_label)

        # Контент слота (иконка мода или пустое место)
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        mod_icon = QLabel(tr("ui.empty_slot"))
        mod_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mod_icon.setObjectName("secondaryText")
        content_layout.addWidget(mod_icon)

        layout.addWidget(content_widget)

        # Устанавливаем свойства слота
        slot_frame.chapter_id = chapter_id
        slot_frame.assigned_mod = None
        slot_frame.content_widget = content_widget
        slot_frame.mod_icon = mod_icon

        # Изначально слот не выбран
        slot_frame.is_selected = False

        # Подключаем обработчики клика и дабл клика
        slot_frame.click_handler = lambda: self._on_slot_clicked(slot_frame)
        slot_frame.double_click_handler = lambda: self._on_slot_frame_double_clicked(slot_frame)

        self._update_slot_visual_state(slot_frame)

        return slot_frame

    def _update_slot_visual_state(self, slot_frame):
        """Обновляет визуальное состояние слота"""
        user_bg_hex = get_theme_color(self.local_config, "background", None)
        if user_bg_hex and self._is_valid_hex_color(user_bg_hex):
            slot_bg_color = f"#C0{user_bg_hex.lstrip('#')}"
        else:
            slot_bg_color = "rgba(0, 0, 0, 150)"
        slot_border_color = get_theme_color(self.local_config, "border", "white")

        # Проверяем, является ли этот слот слотом с прямым запуском
        direct_launch_slot_id = self.local_config.get("direct_launch_slot_id", -1)
        is_direct_launch_slot = (direct_launch_slot_id >= 0 and
                                 slot_frame.chapter_id >= 0 and
                                 slot_frame.chapter_id == direct_launch_slot_id)

        # Определяем стиль границы
        border_style = "3px dashed" if is_direct_launch_slot else "3px solid"

        # Если слот выбран, делаем границу ярче
        if getattr(slot_frame, 'is_selected', False):
            border_color = slot_border_color
            bg_color = slot_bg_color.replace('0.75', '0.9').replace('150', '200')  # Немного ярче фон
        else:
            border_color = slot_border_color
            bg_color = slot_bg_color

        slot_frame.setStyleSheet(f"""
            QFrame#mod_slot {{
                border: {border_style} {border_color};
                background-color: {bg_color};
            }}
            QFrame#mod_slot:hover {{
                border: {border_style} {border_color};
                background-color: {bg_color.replace('150', '180').replace('0.75', '0.85')};
            }}
        """)

    def _on_slot_clicked(self, slot_frame):
        """Обработчик клика по слоту в новой логике поглавного режима"""
        # Проверяем режим
        is_chapter_mode = self.chapter_mode_checkbox.isChecked()

        if not is_chapter_mode:
            # В обычном режиме работаем как раньше
            if slot_frame.assigned_mod:
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle(tr("ui.remove_mod_from_slot"))
                msg_box.setText(tr("ui.remove_mod_question", mod_name=slot_frame.assigned_mod.name))
                msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if msg_box.exec() == QMessageBox.StandardButton.Yes:
                    self._remove_mod_from_slot(slot_frame, slot_frame.assigned_mod)
            else:
                self._show_mod_selection_for_slot(slot_frame)
        else:
            # В поглавном режиме - выбираем слот и фильтруем моды
            # Сначала сбрасываем выбор с других слотов
            for other_slot in self.slots.values():
                if other_slot != slot_frame:
                    other_slot.is_selected = False
                    self._update_slot_visual_state(other_slot)

            # Переключаем выбор текущего слота
            slot_frame.is_selected = not slot_frame.is_selected
            self._update_slot_visual_state(slot_frame)

            # Обновляем список модов в соответствии с выбранным слотом
            if slot_frame.is_selected:
                selected_chapter = slot_frame.chapter_id
                self.selected_chapter_id = selected_chapter  # Сохраняем выбранный слот
                self._update_installed_mods_for_chapter_mode(selected_chapter)
            else:
                # Если ни один слот не выбран, показываем инструкцию
                self.selected_chapter_id = None  # Сбрасываем выбранный слот
                self._show_chapter_mode_instruction()

    def _on_slot_frame_double_clicked(self, slot_frame):
        """Обработчик дабл клика по слоту для включения/отключения прямого запуска"""
        # Дабл клик работает только в поглавном режиме и только для слотов глав (не для демо и универсального)
        is_chapter_mode = self.chapter_mode_checkbox.isChecked()

        if not is_chapter_mode or slot_frame.chapter_id < 0:
            return

        # Проверяем, включен ли уже прямой запуск для этого слота
        current_direct_launch_slot = self.local_config.get('direct_launch_slot_id', -1)
        is_direct_launch_active = (current_direct_launch_slot == slot_frame.chapter_id)

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(tr("ui.direct_launch"))

        if is_direct_launch_active:
            # Предлагаем отключить прямой запуск
            msg_box.setText(
                tr("ui.disable_direct_launch", chapter=slot_frame.chapter_id)
            )
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)

            if msg_box.exec() == QMessageBox.StandardButton.Yes:
                self._disable_direct_launch()
        else:
            # Предлагаем включить прямой запуск
            msg_box.setText(
                tr("ui.enable_direct_launch", chapter=slot_frame.chapter_id)
            )
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)

            if msg_box.exec() == QMessageBox.StandardButton.Yes:
                self._on_toggle_direct_launch_for_slot(slot_frame.chapter_id)

    def _update_installed_mods_for_chapter_mode(self, selected_chapter_id):
        """Обновляет список установленных модов для поглавного режима с фильтрацией по главе"""
        if not hasattr(self, 'installed_mods_layout'):
            return

        # Предотвращаем повторные обновления
        if hasattr(self, '_updating_chapter_mods') and self._updating_chapter_mods:
            return
        self._updating_chapter_mods = True

        # Очищаем текущий список
        clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)

        # Получаем установленные моды
        installed_mods = self._get_installed_mods_list()

        # Фильтруем по режиму демоверсии
        is_demo_mode = getattr(self, 'demo_mode_checkbox', None) and self.demo_mode_checkbox.isChecked()

        for mod_info in installed_mods:
            # Фильтрация по демо режиму
            if is_demo_mode and not mod_info.get('is_demo_mod', False):
                continue
            elif not is_demo_mode and mod_info.get('is_demo_mod', False):
                continue

            # Если выбран конкретный слот, фильтруем моды
            if selected_chapter_id is not None:
                mod_data = self._create_mod_object_from_info(mod_info)
                if mod_data and not self._mod_has_files_for_chapter(mod_data, selected_chapter_id):
                    continue

            # Создаем виджет для установленного мода
            is_local = mod_info.get('is_local_mod', False)
            is_available = mod_info.get('is_available_on_server', True)

            # Создаем объект мода для виджета
            mod_data = self._create_mod_object_from_info(mod_info)
            if mod_data:
                mod_widget = InstalledModWidget(mod_data, is_local, is_available, parent=self)
                mod_widget.clicked.connect(self._on_installed_mod_clicked)
                mod_widget.remove_requested.connect(self._on_installed_mod_remove)

                # В поглавном режиме при выбранном слоте используем новую логику
                if selected_chapter_id is not None:
                    mod_widget.use_requested.connect(lambda mod_data=mod_data: self._on_chapter_mode_mod_use(mod_data, selected_chapter_id))
                    # Устанавливаем состояние кнопки в зависимости от того, есть ли мод в ЭТОМ конкретном слоте
                    is_in_slot = self._is_mod_in_specific_slot(mod_data, selected_chapter_id)
                    mod_widget.set_in_slot(is_in_slot)
                else:
                    mod_widget.use_requested.connect(self._on_installed_mod_use)

                # Вставляем перед stretch элементом
                self.installed_mods_layout.insertWidget(self.installed_mods_layout.count() - 1, mod_widget)

        # Если список пуст, показываем сообщение
        if self.installed_mods_layout.count() <= 1:  # Только stretch элемент
            if selected_chapter_id is not None:
                chapter_names = {-1: tr("ui.universal_slot"), 0: tr("ui.menu"), 1: tr("ui.chapter_1"), 2: tr("ui.chapter_2"), 3: tr("ui.chapter_3"), 4: tr("ui.chapter_4")}
                chapter_name = chapter_names.get(selected_chapter_id, tr("ui.chapter_n", chapter=str(selected_chapter_id)))
                self._show_empty_chapter_message(chapter_name)
            else:
                self._show_empty_mods_message()

        # Сбрасываем флаг обновления
        self._updating_chapter_mods = False

    def _mod_has_files_for_chapter(self, mod_data, chapter_id):
        """Проверяет, есть ли у мода файлы для указанной главы"""
        try:
            # Проверяем наличие ключа мода (может быть key или mod_key)
            mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None)
            if not mod_key:
                return True  # Для локальных модов показываем все

            # Сначала пробуем поиск по mod_key
            mod_folder = os.path.join(self.mods_dir, mod_key)

            # Если папка по mod_key не найдена, пробуем по имени мода
            if not os.path.exists(mod_folder):
                mod_folder_by_name = os.path.join(self.mods_dir, mod_data.name)

                if os.path.exists(mod_folder_by_name):
                    mod_folder = mod_folder_by_name
                else:
                    return False

            # Читаем config.json мода для проверки доступных глав
            config_path = os.path.join(mod_folder, "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)

                    chapters_data = config_data.get('chapters', {})

                    # Если у мода есть информация о главах в config.json
                    if chapters_data:
                        # Преобразуем chapter_id в строку для сравнения с ключами в config
                        chapter_str = str(chapter_id)

                        # Для универсального слота (-1) проверяем есть ли хотя бы одна глава
                        if chapter_id == -1:
                            return len(chapters_data) > 0

                        # Для конкретной главы проверяем есть ли она в списке
                        return chapter_str in chapters_data

                except Exception as e:
                    pass

            # Если нет информации в config.json, проверяем физические папки (старая логика)
            chapter_folders = {
                -1: "universal",  # Универсальный слот
                0: "menu",       # Главное меню
                1: "chapter1",   # Глава 1
                2: "chapter2",   # Глава 2
                3: "chapter3",   # Глава 3
                4: "chapter4"    # Глава 4
            }

            folder_name = chapter_folders.get(chapter_id, "universal")
            chapter_folder = os.path.join(mod_folder, folder_name)

            # Если есть специальная папка для главы
            if os.path.exists(chapter_folder):
                return len(os.listdir(chapter_folder)) > 0

            # Если нет специальной папки, проверяем универсальную
            universal_folder = os.path.join(mod_folder, "universal")
            if os.path.exists(universal_folder):
                return len(os.listdir(universal_folder)) > 0

            # Если нет ни того, ни другого, показываем мод (для совместимости)
            return True

        except Exception as e:
            print(f"Error checking mod files for chapter {chapter_id}: {e}")
            return True  # В случае ошибки показываем мод

    def _on_chapter_mode_mod_use(self, mod_data, chapter_id):
        """Обработчик использования мода в поглавном режиме с выбранным слотом"""


        # Сначала проверяем, показывает ли кнопка "Обновить"
        mod_widget = None
        for i in range(self.installed_mods_layout.count()):
            item = self.installed_mods_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if hasattr(widget, 'mod_data') and hasattr(widget, 'use_button'):
                    widget_mod_data = getattr(widget, 'mod_data', None)
                    if widget_mod_data:
                        widget_mod_key = getattr(widget_mod_data, 'key', None) or getattr(widget_mod_data, 'mod_key', None) or getattr(widget_mod_data, 'name', None)
                        current_mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
                        if widget_mod_key == current_mod_key:
                            mod_widget = widget
                            break

        # Получаем статус виджета вместо проверки текста на кнопке
        status = getattr(mod_widget, 'status', 'ready') if mod_widget else 'ready'

        if status == 'needs_update':
            # Требуется обновление — запускаем процесс обновления
            self._update_mod(mod_data)
            return  # Важно: выходим, чтобы не выполнялась логика вставки в слот

        # Проверяем, находится ли мод уже в ЭТОМ конкретном слоте
        target_slot = None
        for slot_frame in self.slots.values():
            if slot_frame.chapter_id == chapter_id:
                target_slot = slot_frame
                break

        if target_slot and target_slot.assigned_mod:
            # Получаем ключ мода в слоте
            assigned_mod_key = getattr(target_slot.assigned_mod, 'key', None) or getattr(target_slot.assigned_mod, 'mod_key', None) or getattr(target_slot.assigned_mod, 'name', None)
            mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)

            if assigned_mod_key == mod_key:
                # Тот же мод уже в этом слоте - убираем его
                self._remove_mod_from_slot(target_slot, mod_data)
                # Обновляем отображение модов для текущего выбранного слота
                self._update_installed_mods_for_chapter_mode(chapter_id)
                return

        # Находим слот для указанной главы
        target_slot = None
        for slot_frame in self.slots.values():
            if slot_frame.chapter_id == chapter_id:
                target_slot = slot_frame
                break

        if target_slot:
            # Если слот был занят, мод будет заменен.
            self._assign_mod_to_slot(target_slot, mod_data)
            # Обновляем отображение модов для текущего выбранного слота
            self._update_installed_mods_for_chapter_mode(chapter_id)
        else:
            QMessageBox.warning(self, tr("errors.error"), tr("errors.target_slot_not_found"))

    def _show_mod_selection_for_slot(self, slot_frame):
        """Показывает диалог выбора мода для конкретного слота"""
        installed_mods = self._get_installed_mods_list()

        # Проверяем демо-режим
        is_demo_mode = isinstance(self.game_mode, DemoGameMode)

        # Фильтруем моды, которые уже не в других слотах
        available_mods = []
        for mod_info in installed_mods:
            if mod_info:
                # Проверяем существование мода
                mod_exists = self._check_mod_exists(mod_info)
                if not mod_exists:
                    continue

                # Фильтрация по демо режиму
                if is_demo_mode and not mod_info.get('is_demo_mod', False):
                    continue
                elif not is_demo_mode and mod_info.get('is_demo_mod', False):
                    continue

                # Создаем объект мода из информации
                mod_data = self._create_mod_object_from_info(mod_info)
                if mod_data and not self._find_mod_in_slots(mod_data):
                    available_mods.append(mod_data)

        if not available_mods:
            QMessageBox.information(self, tr("ui.no_available_mods"), tr("ui.no_mods_to_insert"))
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("ui.select_mod"))
        dialog.setFixedSize(350, 250)

        layout = QVBoxLayout(dialog)

        label = QLabel(tr("ui.select_mod_for_slot"))
        layout.addWidget(label)

        # Список доступных модов
        mod_list = QListWidget()

        for mod_data in available_mods:
            mod_list.addItem(mod_data.name)

        layout.addWidget(mod_list)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_items = mod_list.selectedItems()
            if selected_items:
                selected_index = mod_list.row(selected_items[0])
                selected_mod = available_mods[selected_index]
                self._assign_mod_to_slot(slot_frame, selected_mod)

    def _update_installed_mods_display(self):
        """Обновляет отображение установленных модов"""
        if not hasattr(self, 'installed_mods_layout'):
            return

        # Проверяем, находимся ли мы в поглавном режиме
        is_chapter_mode = hasattr(self, 'chapter_mode_checkbox') and self.chapter_mode_checkbox.isChecked()
        if is_chapter_mode:
            # В поглавном режиме проверяем, есть ли выбранный слот
            if hasattr(self, 'selected_chapter_id') and self.selected_chapter_id is not None:
                # Если слот выбран, показываем моды для этого слота
                self._update_installed_mods_for_chapter_mode(self.selected_chapter_id)
                return
            else:
                # Если слот не выбран, показываем инструкцию
                self._show_chapter_mode_instruction()
                return

        # Очищаем текущий список
        clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)

        # Получаем установленные моды и проверяем их существование
        installed_mods = self._get_installed_mods_list()
        self._cleanup_missing_mods(installed_mods)

        # Фильтруем по режиму демоверсии
        is_demo_mode = getattr(self, 'demo_mode_checkbox', None) and self.demo_mode_checkbox.isChecked()

        for mod_info in installed_mods:
            # Проверяем, что мод еще существует (после очистки)
            mod_exists = self._check_mod_exists(mod_info)
            if not mod_exists:
                continue

            # Фильтрация по демо режиму
            if is_demo_mode and not mod_info.get('is_demo_mod', False):
                continue
            elif not is_demo_mode and mod_info.get('is_demo_mod', False):
                continue

            # Создаем виджет для установленного мода
            is_local = mod_info.get('is_local_mod', False)
            is_available = mod_info.get('is_available_on_server', True)

            # Проверяем, есть ли обновления для мода
            has_update = False
            if not is_local and is_available:
                # Ищем мод в списке публичных модов для проверки обновлений
                public_mod = next((mod for mod in self.all_mods if mod.key == mod_info.get('key')), None)
                if public_mod:
                    has_update = any(self._mod_has_files_for_chapter(public_mod, i) and
                                   self._get_mod_status_for_chapter(public_mod, i) == 'update' for i in range(5))

            # Создаем объект мода для виджета
            mod_data = self._create_mod_object_from_info(mod_info)
            if mod_data:
                mod_widget = InstalledModWidget(mod_data, is_local, is_available, has_update, parent=self)
                mod_widget.clicked.connect(self._on_installed_mod_clicked)
                mod_widget.remove_requested.connect(self._on_installed_mod_remove)
                mod_widget.use_requested.connect(self._on_installed_mod_use)

                # Вставляем перед stretch элементом
                self.installed_mods_layout.insertWidget(self.installed_mods_layout.count() - 1, mod_widget)

        # Если список пуст, показываем сообщение
        if self.installed_mods_layout.count() <= 1:  # Только stretch элемент
            self._show_empty_mods_message()

        # Обновляем состояние кнопок Use/Remove
        self._update_mod_widgets_slot_status()
        # Обновляем основной интерфейс
        self._update_ui_for_selection()

    def _show_empty_mods_message(self):
        """Показывает сообщение о пустом списке модов"""
        show_empty_message_in_layout(self.installed_mods_layout, tr("ui.empty"), self.local_config, font_size=18)

    def _show_empty_chapter_message(self, chapter_name):
        """Показывает сообщение о пустом списке модов для конкретной главы"""
        show_empty_message_in_layout(self.installed_mods_layout, tr("ui.no_mods_for_chapter", chapter_name=chapter_name), self.local_config, font_size=16)

    def _check_mod_exists(self, mod_info):
        """Проверяет существование файлов мода"""
        mod_key = mod_info.get('mod_key', '')
        mod_name = mod_info.get('name', '')

        # Проверяем по ключу
        if mod_key:
            mod_folder_by_key = os.path.join(self.mods_dir, mod_key)
            if os.path.exists(mod_folder_by_key):
                return True

        # Проверяем по имени
        if mod_name:
            mod_folder_by_name = os.path.join(self.mods_dir, mod_name)
            if os.path.exists(mod_folder_by_name):
                return True

        return False

    def _cleanup_missing_mods(self, installed_mods):
        """Очищает моды, файлы которых больше не существуют"""
        missing_mods = []

        for mod_info in installed_mods:
            mod_key = mod_info.get('mod_key', '')
            mod_name = mod_info.get('name', '')

            # Проверяем существование папки мода
            mod_exists = False
            if mod_key:
                # Проверяем по ключу
                mod_folder_by_key = os.path.join(self.mods_dir, mod_key)
                if os.path.exists(mod_folder_by_key):
                    mod_exists = True

            if not mod_exists and mod_name:
                # Проверяем по имени
                mod_folder_by_name = os.path.join(self.mods_dir, mod_name)
                if os.path.exists(mod_folder_by_name):
                    mod_exists = True

            if not mod_exists:
                missing_mods.append(mod_info)

        # Удаляем отсутствующие моды из слотов и списка
        for missing_mod in missing_mods:
            # Создаем объект мода для удаления из слотов
            mod_data = self._create_mod_object_from_info(missing_mod)
            if mod_data:
                # Удаляем из всех слотов
                self._remove_mod_from_all_slots(mod_data)
                # Удаляем из сохраненного состояния слотов
                if hasattr(self, 'saved_slots_state'):
                    slots_to_clear = []
                    for slot_id, saved_mod in self.saved_slots_state.items():
                        if hasattr(saved_mod, 'key') and hasattr(mod_data, 'key') and saved_mod.key == mod_data.key:
                            slots_to_clear.append(slot_id)
                        elif hasattr(saved_mod, 'name') and hasattr(mod_data, 'name') and saved_mod.name == mod_data.name:
                            slots_to_clear.append(slot_id)
                    for slot_id in slots_to_clear:
                        del self.saved_slots_state[slot_id]

    def _get_installed_mods_list(self):
        """Получает список установленных модов"""
        installed_mods = []

        if not hasattr(self, 'mods_dir') or not os.path.exists(self.mods_dir):
            return installed_mods

        # Проходим по папкам модов
        for folder_name in os.listdir(self.mods_dir):
            folder_path = os.path.join(self.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue

            config_path = os.path.join(folder_path, "config.json")
            if os.path.exists(config_path):
                try:
                    config_data = self._read_json(config_path)
                    if config_data:
                        # Используем информацию о доступности из config.json
                        config_data['is_available_on_server'] = config_data.get('is_available_on_server', False)
                        config_data['is_local_mod'] = config_data.get('is_local_mod', False)

                        installed_mods.append(config_data)
                except Exception as e:
                    logging.warning(f"Failed to read config {config_path}: {e}")
                    continue

        return installed_mods

    def _create_mod_object_from_info(self, mod_info):
        """Создает объект ModInfo из информации о установленном моде"""
        # Сначала пытаемся найти мод среди загруженных
        mod_key = mod_info.get('mod_key', '')

        if hasattr(self, 'all_mods') and self.all_mods:
            for mod in self.all_mods:
                if hasattr(mod, 'key') and mod.key == mod_key:
                    return mod

        # Создаем объект из сохраненной информации в config.json
        # Серверные данные (tagline, description_url, downloads, is_verified) используем значения по умолчанию
        from helpers import ModInfo

        return ModInfo(
            key=mod_key,
            name=mod_info.get('name', mod_key),
            tagline=mod_info.get('tagline', tr("defaults.no_description")),  # Используем tagline из конфига
            version=mod_info.get('version', '1.0.0'),
            author=mod_info.get('author', tr("defaults.unknown")),
            game_version=mod_info.get('game_version', '1.03'),
            description_url='',  # Значение по умолчанию
            downloads=0,  # Значение по умолчанию
            is_demo_mod=mod_info.get('is_demo_mod', False),
            is_verified=False  # Значение по умолчанию
        )

    def _on_installed_mod_clicked(self, mod_data):
        """Обработчик клика по установленному моду"""
        # Находим виджет мода и переключаем его состояние
        for i in range(self.installed_mods_layout.count() - 1):  # -1 для stretch
            item = self.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget) and widget.mod_data == mod_data:
                    # Сначала убираем выделение со всех модов
                    self._clear_all_installed_mod_selections()
                    # Затем выделяем текущий
                    widget.set_selected(True)
                    break

    def _clear_all_installed_mod_selections(self):
        """Убирает выделение со всех установленных модов"""
        for i in range(self.installed_mods_layout.count() - 1):  # -1 для stretch
            item = self.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget):
                    widget.set_selected(False)

    def _on_installed_mod_remove(self, mod_data):
        """Обработчик удаления установленного мода"""
        try:
            # Подтверждение удаления
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(tr("dialogs.delete_confirmation"))
            msg_box.setText(tr("dialogs.delete_mod_confirmation", mod_name=mod_data.name))
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)

            if msg_box.exec() == QMessageBox.StandardButton.Yes:
                # Удаляем файлы мода
                self._delete_mod_files(mod_data)

                # Убираем мод из слотов если он там есть
                self._remove_mod_from_all_slots(mod_data)

                # Обновляем интерфейс
                self._update_installed_mods_display()
        except Exception as e:
            print(f"Error removing mod {mod_data.name}: {e}")
            QMessageBox.critical(self, tr("errors.error"), tr("errors.mod_removal_failed", error=str(e)))

    def _on_installed_mod_use(self, mod_data):
        """Обработчик нажатия кнопки Использовать/Убрать/Обновить"""

        # Проверяем, есть ли мод уже в слоте
        current_slot = self._find_mod_in_slots(mod_data)

        if current_slot:
            # Мод уже в слоте - убираем его
            self._remove_mod_from_slot(current_slot, mod_data)
        else:
            # Проверяем режим
            is_chapter_mode = self.chapter_mode_checkbox.isChecked()
            is_demo_mode = isinstance(self.game_mode, DemoGameMode)

            # Ищем виджет мода чтобы понять, что показывает кнопка
            mod_widget = None
            for i in range(self.installed_mods_layout.count()):
                item = self.installed_mods_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    # Проверяем, что это ModWidget с нужными атрибутами
                    if hasattr(widget, 'mod_data') and hasattr(widget, 'use_button'):
                        widget_mod_data = getattr(widget, 'mod_data', None)
                        if widget_mod_data:
                            widget_mod_key = getattr(widget_mod_data, 'key', None) or getattr(widget_mod_data, 'mod_key', None) or getattr(widget_mod_data, 'name', None)
                            current_mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
                            if widget_mod_key == current_mod_key:
                                mod_widget = widget
                                break

            # Получаем статус виджета вместо проверки текста на кнопке
            status = getattr(mod_widget, 'status', 'ready') if mod_widget else 'ready'

            if status == 'needs_update':
                # Требуется обновление — запускаем процесс обновления
                self._update_mod(mod_data)
                return  # Важно: выходим, чтобы не выполнялась логика вставки в слот
            else:

                if not is_chapter_mode or is_demo_mode:
                    # В обычном режиме или демо-режиме - автоматически вставляем в соответствующий слот
                    target_slot = None
                    target_slot_id = -2 if is_demo_mode else -1  # -2 для демо, -1 для универсального

                    for key, slot_frame in self.slots.items():
                        if slot_frame.chapter_id == target_slot_id:
                            target_slot = slot_frame
                            break

                    if target_slot:
                        self._assign_mod_to_slot(target_slot, mod_data)
                else:
                    # В поглавном режиме - показываем диалог выбора слота
                    self._show_slot_selection_dialog(mod_data)

    def _find_mod_in_slots(self, mod_data, exclude_chapter_id=None):
        """Ищет мод в слотах и возвращает слот где он находится (с возможностью исключить определенную главу)"""
        if not mod_data:
            return None

        # Получаем уникальный идентификатор мода для сравнения
        mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
        if not mod_key:
            return None

        for slot_frame in self.slots.values():
            # Исключаем слот с определенной главой, если указано
            if exclude_chapter_id is not None and slot_frame.chapter_id == exclude_chapter_id:
                continue

            if slot_frame.assigned_mod:
                assigned_mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if assigned_mod_key == mod_key:
                    return slot_frame
        return None

    def _remove_mod_from_slot(self, slot_frame, mod_data):
        """Убирает мод из конкретного слота"""
        slot_frame.assigned_mod = None

        # Очищаем текущий контент (это также удалит mod_icon, который является частью content_widget)
        if slot_frame.content_widget:
            slot_frame.content_widget.setParent(None)
            slot_frame.content_widget = None

        slot_frame.mod_icon = None

        is_large_slot = slot_frame.chapter_id < 0

        # Находим и показываем оригинальный заголовок для больших слотов
        title_label = None
        if slot_frame.layout():
            for i in range(slot_frame.layout().count()):
                item = slot_frame.layout().itemAt(i)
                if item and item.widget() and isinstance(item.widget(), QLabel):
                    title_label = item.widget()
                    break

        if is_large_slot and title_label:
            title_label.setVisible(True)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        mod_icon = QLabel(tr("ui.empty_slot"))
        mod_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mod_icon.setObjectName("secondaryText")
        content_layout.addWidget(mod_icon)

        slot_frame.layout().addWidget(content_widget)
        slot_frame.content_widget = content_widget
        slot_frame.mod_icon = mod_icon

        # Обновляем состояние кнопки в библиотеке
        self._update_mod_widgets_slot_status()

        # Обновляем индикаторы глав (только для универсального слота)
        if slot_frame.chapter_id == -1:
            self._update_chapter_indicators(None)

        # Обновляем состояние кнопки действия
        self._update_ui_for_selection()

        # Сохраняем состояние слотов
        self._save_slots_state()

    def _show_slot_selection_dialog(self, mod_data):
        """Показывает диалог выбора слота для мода"""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("ui.select_slot"))
        dialog.setFixedSize(300, 200)

        layout = QVBoxLayout(dialog)

        label = QLabel(tr("ui.select_slot_for_mod", mod_name=mod_data.name))
        layout.addWidget(label)

        # Список доступных слотов
        slot_list = QListWidget()

        # Добавляем доступные слоты
        available_slots = []
        for key, slot_frame in self.slots.items():
            if slot_frame.assigned_mod is None:
                if slot_frame.chapter_id == -1:
                    slot_name = tr("ui.mod_slot")
                else:
                    chapter_names = [tr("chapters.menu"), tr("tabs.chapter_1"), tr("tabs.chapter_2"), tr("tabs.chapter_3"), tr("tabs.chapter_4")]
                    slot_name = chapter_names[slot_frame.chapter_id]

                slot_list.addItem(slot_name)
                available_slots.append(slot_frame)

        if not available_slots:
            QMessageBox.information(self, tr("dialogs.no_free_slots"), tr("dialogs.all_slots_occupied"))
            return

        layout.addWidget(slot_list)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_items = slot_list.selectedItems()
            if selected_items:
                selected_index = slot_list.row(selected_items[0])
                selected_slot = available_slots[selected_index]
                self._assign_mod_to_slot(selected_slot, mod_data)

    def _show_mod_details_dialog(self, mod_data):
        """Показывает диалог с подробной информацией о моде"""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("ui.mod_details_title", mod_name=mod_data.name))
        dialog.setMinimumSize(700, 700)
        dialog.resize(800, 750)  # Начальный размер

        # Получаем цвет дополнительного текста
        secondary_text_color = get_theme_color(self.local_config, "version_text", "rgba(255, 255, 255, 178)")

        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)

        # Прокручиваемая область для содержимого
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # Заголовочная область с названием и иконкой
        header_layout = QHBoxLayout()

        # Левая часть - иконка и метаданные
        left_layout = QVBoxLayout()

        # Иконка мода
        icon_label = QLabel()
        icon_label.setFixedSize(120, 120)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("border: 2px solid #fff;")
        load_mod_icon_universal(icon_label, mod_data, 120)
        left_layout.addWidget(icon_label)

        # Контейнер для левой части с фиксированной шириной
        left_container = QWidget()
        left_container.setMaximumWidth(200)  # Ограничиваем ширину левой части
        left_container.setLayout(left_layout)

        # Метаданные под иконкой
        metadata_layout = QVBoxLayout()
        metadata_layout.setSpacing(3)

        # Автор
        author_text = mod_data.author or tr("defaults.unknown")
        author_label = QLabel(f'<span style="color: white;">{tr("ui.author_label")}</span> <span style="color: {secondary_text_color};">{author_text}</span>')
        author_label.setStyleSheet("font-size: 12px;")
        metadata_layout.addWidget(author_label)

        # Версия игры
        game_version_text = mod_data.game_version or "N/A"
        game_version_label = QLabel(f'<span style="color: white;">{tr("ui.game_version_label")}</span> <span style="color: {secondary_text_color};">{game_version_text}</span>')
        game_version_label.setStyleSheet("font-size: 12px;")
        metadata_layout.addWidget(game_version_label)

        # Даты
        created_date_text = mod_data.created_date or 'N/A'
        created_label = QLabel(f'<span style="color: white;">{tr("ui.created_label")}</span> <span style="color: {secondary_text_color};">{created_date_text}</span>')
        created_label.setStyleSheet("font-size: 12px;")
        metadata_layout.addWidget(created_label)

        updated_date_text = mod_data.last_updated or 'N/A'
        updated_label = QLabel(f'<span style="color: white;">{tr("ui.updated_label")}</span> <span style="color: {secondary_text_color};">{updated_date_text}</span>')
        updated_label.setStyleSheet("font-size: 12px;")
        metadata_layout.addWidget(updated_label)

        # Количество скачиваний
        downloads_label = QLabel(f'<span style="color: white;">{tr("ui.downloads_label")}</span> <span style="color: {secondary_text_color};">{mod_data.downloads}</span>')
        downloads_label.setStyleSheet("font-size: 12px;")
        metadata_layout.addWidget(downloads_label)

        # Теги с переводом на русский
        if hasattr(mod_data, 'tags') and mod_data.tags:
            # Добавляем отступ перед тегами
            metadata_layout.addSpacing(8)

            # Заголовок "Теги:" белым цветом
            tags_header = QLabel(tr("ui.tags_label"))
            tags_header.setStyleSheet("font-size: 12px; color: white; font-weight: bold;")
            metadata_layout.addWidget(tags_header)

            # Переводим теги
            tag_translations = {
                'translation': tr("tags.translation"),
                'customization': tr("tags.customization"),
                'gameplay': tr("tags.gameplay"),
                'other': tr("tags.other")
            }
            tags_list = mod_data.tags if isinstance(mod_data.tags, list) else [mod_data.tags]
            filtered_tags = [tag for tag in tags_list if tag]
            translated_tags = [tag_translations.get(tag, tag) or tag for tag in filtered_tags]

            # Каждый тег на новой строке
            for tag in translated_tags:
                tag_label = QLabel(tag)
                tag_label.setStyleSheet(f"font-size: 12px; color: {secondary_text_color}; margin-left: 10px;")
                tag_label.setMaximumWidth(190)
                metadata_layout.addWidget(tag_label)

        left_layout.addLayout(metadata_layout)
        left_layout.addStretch()

        # Добавляем контейнер левой части вместо layout
        header_layout.addWidget(left_container)

        # Правая часть - название, версия и tagline
        right_layout = QVBoxLayout()

        # Название
        title_label = QLabel(f"<h2>{mod_data.name}</h2>")
        title_label.setWordWrap(True)
        right_layout.addWidget(title_label)

        # Версия мода под названием
        mod_version = mod_data.version.split('|')[0] if mod_data.version and '|' in mod_data.version else mod_data.version
        version_text = mod_version or "N/A"
        version_label = QLabel(tr("ui.mod_version_label", version_text=version_text))
        version_label.setStyleSheet(f"font-size: 14px; color: {secondary_text_color}; margin-bottom: 10px;")
        right_layout.addWidget(version_label)

        # Отдельное пространство для tagline высотой с иконку
        tagline_container = QWidget()
        tagline_container.setFixedHeight(120)  # Высота как у иконки
        tagline_layout = QVBoxLayout(tagline_container)
        tagline_layout.setContentsMargins(0, 0, 0, 0)

        if mod_data.tagline:
            tagline_label = QLabel(mod_data.tagline)
            tagline_label.setWordWrap(True)
            tagline_label.setStyleSheet("font-size: 14px; color: #ddd;")
            tagline_label.setAlignment(Qt.AlignmentFlag.AlignTop)
            tagline_layout.addWidget(tagline_label)

        tagline_layout.addStretch()
        right_layout.addWidget(tagline_container)

        # Статусы
        status_layout = QVBoxLayout()
        status_layout.setSpacing(8)

        if getattr(mod_data, 'is_verified', False):
            verified_container = QVBoxLayout()
            verified_label = QLabel(tr("ui.verified_label"))
            verified_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 15px;")
            verified_container.addWidget(verified_label)

            verified_desc = QLabel(tr("ui.verified_desc"))
            verified_desc.setStyleSheet("color: #4CAF50; font-size: 11px; margin-left: 15px;")
            verified_desc.setWordWrap(True)
            verified_container.addWidget(verified_desc)

            status_layout.addLayout(verified_container)

        if getattr(mod_data, 'is_piracy_protected', False):
            license_container = QVBoxLayout()
            license_label = QLabel(tr("ui.license_label"))
            license_label.setStyleSheet("color: #2196F3; font-weight: bold; font-size: 15px;")
            license_container.addWidget(license_label)

            license_desc = QLabel(tr("ui.license_desc"))
            license_desc.setStyleSheet("color: #2196F3; font-size: 11px; margin-left: 15px;")
            license_desc.setWordWrap(True)
            license_container.addWidget(license_desc)

            status_layout.addLayout(license_container)

        if mod_data.is_demo_mod:
            demo_container = QVBoxLayout()
            demo_label = QLabel(tr("ui.demo_label"))
            demo_label.setStyleSheet("color: #FF9800; font-weight: bold; font-size: 15px;")
            demo_container.addWidget(demo_label)

            demo_desc = QLabel(tr("ui.demo_desc"))
            demo_desc.setStyleSheet("color: #FF9800; font-size: 11px; margin-left: 15px;")
            demo_desc.setWordWrap(True)
            demo_container.addWidget(demo_desc)

            status_layout.addLayout(demo_container)

        right_layout.addLayout(status_layout)
        right_layout.addStretch()

        header_layout.addLayout(right_layout)
        scroll_layout.addLayout(header_layout)

        # Разделитель
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        scroll_layout.addWidget(separator)

        # Screenshots carousel (if any)
        screenshots = getattr(mod_data, 'screenshots_url', []) or []
        if isinstance(screenshots, list) and any(isinstance(u, str) and u.strip() for u in screenshots):
            screenshots_title = QLabel(f"<b>{tr('ui.screenshots_title')}</b>")
            screenshots_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            scroll_layout.addWidget(screenshots_title)
            carousel = ScreenshotsCarousel(screenshots, self)
            # center the carousel widget
            container = QWidget()
            cont_layout = QHBoxLayout(container)
            cont_layout.setContentsMargins(0,0,0,0)
            cont_layout.addStretch()
            cont_layout.addWidget(carousel)
            cont_layout.addStretch()
            scroll_layout.addWidget(container)
            scroll_layout.addSpacing(12)

        # Полное описание из description_url
        full_desc_label = QLabel(f"<b>{tr('ui.full_description_label')}</b>")
        full_desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll_layout.addWidget(full_desc_label)
        scroll_layout.addSpacing(6)

        desc_text = QTextBrowser()
        desc_text.setMinimumHeight(300)
        desc_text.setOpenExternalLinks(True)

        # Загружаем описание из URL или используем fallback
        if hasattr(mod_data, 'description_url') and mod_data.description_url:
            self._load_description_from_url(desc_text, mod_data.description_url)
        else:
            desc_text.setPlainText(tr("ui.no_description"))

        scroll_layout.addWidget(desc_text)

        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)

        # Кнопки
        buttons_layout = QHBoxLayout()

        # Если есть URL мода, добавляем кнопку "Открыть в браузере"
        if hasattr(mod_data, 'url') and mod_data.url:
            open_url_btn = QPushButton(tr("ui.open_in_browser"))
            open_url_btn.clicked.connect(lambda: webbrowser.open(mod_data.url))
            buttons_layout.addWidget(open_url_btn)

        buttons_layout.addStretch()

        close_btn = QPushButton(tr("ui.close_button"))
        close_btn.clicked.connect(dialog.close)
        buttons_layout.addWidget(close_btn)

        layout.addLayout(buttons_layout)

        dialog.exec()

    def _load_description_from_url(self, text_widget, description_url):
        """Загружает описание мода из URL и отображает его с поддержкой markdown"""
        try:
            import requests

            # Показываем загрузку
            text_widget.setPlainText(tr("status.loading_description"))

            response = requests.get(description_url, timeout=10)
            if response.ok:
                content = response.text

                # Проверяем, является ли содержимое markdown по расширению URL или содержимому
                is_markdown = (
                    description_url.lower().endswith(('.md', '.markdown')) or
                    '# ' in content or '## ' in content or '**' in content or '__' in content
                )

                if is_markdown:
                    text_widget.setMarkdown(content)
                else:
                    # Обычный текст с сохранением переносов строк
                    text_widget.setPlainText(content)
            else:
                text_widget.setPlainText(tr("errors.description_http_error_code", code=response.status_code))

        except Exception as e:
            text_widget.setPlainText(tr("errors.description_load_error_details", error=str(e)))

    def _assign_mod_to_slot(self, slot_frame, mod_data, save_state=True):
        """Назначает мод в слот"""
        slot_frame.assigned_mod = mod_data

        # Очищаем текущий контент
        if slot_frame.content_widget:
            slot_frame.content_widget.setParent(None)
            slot_frame.content_widget = None

            slot_frame.mod_icon = None

        is_large_slot = slot_frame.chapter_id < 0

        # Находим и скрываем оригинальный заголовок для больших слотов
        title_label = None
        # Ищем виджет QLabel, который является дочерним элементом QVBoxLayout слота
        if slot_frame.layout():
            for i in range(slot_frame.layout().count()):
                item = slot_frame.layout().itemAt(i)
                if item and item.widget() and isinstance(item.widget(), QLabel):
                    title_label = item.widget()
                    break # Нашли первый QLabel, это наш заголовок

        if is_large_slot and title_label:
            title_label.setVisible(False)

        # Создаем новый виджет-контейнер для всего содержимого
        new_content_widget = QWidget()
        new_content_layout = QHBoxLayout(new_content_widget)
        new_content_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Иконка мода
        mod_icon = QLabel()
        mod_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        border_color = self.local_config.get("custom_color_border") or "white"
        mod_icon.setStyleSheet(f"border: 1px solid {border_color};")

        # Вертикальный контейнер для текста
        text_vbox = QVBoxLayout()
        text_vbox.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        name_label = QLabel()
        status_text, status_color = "", "gray"

        # Проверяем, является ли мод локальным
        is_local_mod = getattr(mod_data, 'key', '').startswith('local_')

        if is_large_slot:
            # Настройки для БОЛЬШИХ слотов (возвращаем как было)
            new_content_layout.setContentsMargins(8, 0, 8, 0)
            new_content_layout.setSpacing(10)
            mod_icon.setFixedSize(48, 48)
            text_vbox.setSpacing(2)
            name_label.setWordWrap(True)
            name_label.setStyleSheet("font-weight: bold; font-size: 13px; border: none; background: transparent;")
            name_label.setText(mod_data.name)

            # Устанавливаем текст статуса в зависимости от типа мода
            if is_local_mod:
                status_text, status_color = tr("status.local_mod"), "#FFD700"
            else:
                # Для больших слотов (универсальный и демо) проверяем все главы
                needs_update = any(self._mod_has_files_for_chapter(mod_data, i) and self._get_mod_status_for_chapter(mod_data, i) == 'update' for i in range(5))
                status_text, status_color = (tr("status.update_available"), "orange") if needs_update else (tr("status.version_current"), "lightgreen")

            version_label = QLabel(status_text)
            version_label.setStyleSheet(f"color: {status_color}; font-size: 10px; border: none; background: transparent;")
        else:
            # Настройки для МАЛЕНЬКИХ слотов (оставляем новые изменения)
            new_content_layout.setContentsMargins(8, 0, 8, 0)
            new_content_layout.setSpacing(8)
            mod_icon.setFixedSize(40, 40)
            text_vbox.setSpacing(1)
            name_label.setStyleSheet("font-weight: bold; font-size: 11px; border: none; background: transparent;")
            # Новая система сокращения по символам
            original_name = mod_data.name
            display_name = (original_name[:7] + "...") if len(original_name) > 10 else original_name
            name_label.setText(display_name)
            name_label.setToolTip(original_name)

            # Устанавливаем текст статуса в зависимости от типа мода
            if is_local_mod:
                status_text, status_color = tr("status.local"), "#FFD700"
            else:
                # Для маленьких слотов проверяем ВСЕ главы мода, не только конкретную
                needs_update = any(self._mod_has_files_for_chapter(mod_data, i) and
                                 self._get_mod_status_for_chapter(mod_data, i) == 'update' for i in range(5))
                status_text, status_color = (tr("status.update_short"), "orange") if needs_update else (tr("status.current_short"), "lightgreen")

            version_label = QLabel(status_text)
            version_label.setStyleSheet(f"color: {status_color}; font-size: 9px; border: none; background: transparent;")
        load_mod_icon_universal(mod_icon, mod_data, 32)
        new_content_layout.addWidget(mod_icon)
        text_vbox.addWidget(name_label)
        text_vbox.addWidget(version_label)
        new_content_layout.addLayout(text_vbox)
        new_content_layout.addStretch()

        # Добавляем новый контент в основной layout слота
        slot_frame.layout().addWidget(new_content_widget)
        slot_frame.content_widget = new_content_widget
        slot_frame.mod_icon = mod_icon

        # Обновляем состояние кнопок в библиотеке
        self._update_mod_widgets_slot_status()

        # Обновляем индикаторы глав (только для универсального слота)
        if slot_frame.chapter_id == -1:
            self._update_chapter_indicators(mod_data)

        # Обновляем состояние кнопки действия
        self._update_ui_for_selection()

        # Сохраняем состояние слотов (если не отключено)
        if save_state:
            self._save_slots_state()



    def _calculate_optimal_font_size(self, text, max_width, max_height):
        """Вычисляет оптимальный размер шрифта для текста в заданных границах"""
        from PyQt6.QtGui import QFontMetrics

        # Начинаем с максимального размера и уменьшаем
        for font_size in range(10, 6, -1):  # От 10 до 7 пикселей
            font = QFont()
            font.setPointSize(font_size)
            font.setBold(True)

            metrics = QFontMetrics(font)

            # Проверяем поместится ли текст
            text_rect = metrics.boundingRect(0, 0, max_width, max_height, Qt.TextFlag.TextWordWrap, text)

            if text_rect.width() <= max_width and text_rect.height() <= max_height:
                return font_size

        return 7  # Минимальный размер шрифта

    def _update_mod_widgets_slot_status(self):
        """Обновляет состояние кнопок Use/Remove в библиотеке"""
        # Проходим по всем виджетам модов в библиотеке и обновляем их состояние
        for i in range(self.installed_mods_layout.count() - 1):  # -1 для stretch
            item = self.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget):
                    # Проверяем, есть ли мод в каком-либо слоте
                    is_in_slot = self._find_mod_in_slots(widget.mod_data) is not None
                    widget.set_in_slot(is_in_slot)

    def _refresh_all_slot_status_displays(self):
        """Обновляет статус отображения во всех заполненных слотах"""
        for slot_frame in self.slots.values():
            if slot_frame.assigned_mod and slot_frame.content_widget:
                self._refresh_slot_status_display(slot_frame)
                # Также перезагружаем иконку для исправления бага с отсутствующими иконками при старте
                if hasattr(slot_frame, 'mod_icon') and slot_frame.mod_icon:
                    load_mod_icon_universal(slot_frame.mod_icon, slot_frame.assigned_mod, 32)

    def _refresh_slot_status_display(self, slot_frame):
        """Обновляет только статус текст в конкретном слоте"""
        if not slot_frame.assigned_mod or not slot_frame.content_widget:
            return

        mod_data = slot_frame.assigned_mod

        # Находим виджет с версией/статусом
        version_label = None
        content_layout = slot_frame.content_widget.layout()
        if content_layout:
            for i in range(content_layout.count()):
                item = content_layout.itemAt(i)
                if item and item.layout():  # Это text_vbox
                    text_layout = item.layout()
                    if text_layout and text_layout.count() >= 2:
                        version_item = text_layout.itemAt(1)  # Второй элемент - это версия
                        if version_item and version_item.widget() and isinstance(version_item.widget(), QLabel):
                            version_label = version_item.widget()
                            break

        if version_label:
            is_large_slot = slot_frame.chapter_id < 0

            # Проверяем, является ли мод локальным
            is_local_mod = getattr(mod_data, 'key', '').startswith('local_')

            if is_local_mod:
                # Для локальных модов всегда показываем "Локальный мод"/tr("status.local")
                if is_large_slot:
                    status_text, status_color = tr("status.local_mod"), "#FFD700"
                    version_label.setStyleSheet(f"color: {status_color}; font-size: 10px; border: none; background: transparent;")
                else:
                    status_text, status_color = tr("status.local"), "#FFD700"
                    version_label.setStyleSheet(f"color: {status_color}; font-size: 9px; border: none; background: transparent;")
            else:
                # Для публичных модов проверяем наличие обновлений
                if is_large_slot:
                    # Для больших слотов проверяем все главы
                    needs_update = any(self._mod_has_files_for_chapter(mod_data, i) and
                                     self._get_mod_status_for_chapter(mod_data, i) == 'update' for i in range(5))
                    status_text, status_color = (tr("status.update_available"), "orange") if needs_update else (tr("status.version_current"), "lightgreen")
                    version_label.setStyleSheet(f"color: {status_color}; font-size: 10px; border: none; background: transparent;")
                else:
                    # Для маленьких слотов проверяем ВСЕ главы мода, не только конкретную
                    needs_update = any(self._mod_has_files_for_chapter(mod_data, i) and
                                     self._get_mod_status_for_chapter(mod_data, i) == 'update' for i in range(5))
                    status_text, status_color = (tr("status.update_short"), "orange") if needs_update else (tr("status.current_short"), "lightgreen")
                    version_label.setStyleSheet(f"color: {status_color}; font-size: 9px; border: none; background: transparent;")

            version_label.setText(status_text)

    def _delete_mod_files(self, mod_data):
        """Удаляет файлы мода с диска"""
        try:
            # Ищем папку мода по ключу в папке модов
            if not hasattr(self, 'mods_dir') or not os.path.exists(self.mods_dir):
                print("Mods directory not found")
                return

            mod_folder_found = None

            # Ищем папку мода в папке модов
            for folder_name in os.listdir(self.mods_dir):
                folder_path = os.path.join(self.mods_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue

                config_path = os.path.join(folder_path, "config.json")
                if os.path.exists(config_path):
                    try:
                        config_data = self._read_json(config_path)
                        if config_data and config_data.get('mod_key') == mod_data.key:
                            mod_folder_found = folder_path
                            break
                    except Exception as e:
                        logging.warning(f"Failed to read installed mod config {config_path}: {e}")
                        continue

            if mod_folder_found and os.path.exists(mod_folder_found):
                shutil.rmtree(mod_folder_found)
            else:
                print(f"Mod folder not found for mod: {mod_data.name}")

        except Exception as e:
            print(f"Error deleting mod files: {e}")
            raise

    def _remove_mod_from_all_slots(self, mod_data):
        """Убирает мод из всех слотов"""
        if not mod_data:
            return

        # Получаем уникальный идентификатор мода для сравнения
        mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
        if not mod_key:
            return

        for slot_frame in self.slots.values():
            if slot_frame.assigned_mod:
                assigned_mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if assigned_mod_key == mod_key:
                    # Используем существующий метод для очистки слота
                    self._remove_mod_from_slot(slot_frame, slot_frame.assigned_mod)

    def _populate_search_mods(self):
        """Заполняет список модов на вкладке поиска с фильтрацией и пагинацией"""
        # Инициализируем список отфильтрованных модов
        self._update_filtered_mods()

    def _update_filtered_mods(self):
        """Обновляет список отфильтрованных и отсортированных модов"""
        if not hasattr(self, 'all_mods') or not self.all_mods:
            self.filtered_mods = []
            self._update_mod_display()
            return

        # Получаем выбранные теги
        selected_tags = []
        if hasattr(self, 'tag_translation') and self.tag_translation.isChecked():
            selected_tags.append('translation')
        if hasattr(self, 'tag_customization') and self.tag_customization.isChecked():
            selected_tags.append('customization')
        if hasattr(self, 'tag_gameplay') and self.tag_gameplay.isChecked():
            selected_tags.append('gameplay')
        if hasattr(self, 'tag_other') and self.tag_other.isChecked():
            selected_tags.append('other')

        # Проверяем фильтр демо
        demo_filter = hasattr(self, 'tag_demo') and self.tag_demo.isChecked()

        # Фильтруем моды
        self.filtered_mods = []

        for mod in self.all_mods:
            # Проверяем hide_mod с учетом возможных типов данных
            if getattr(mod, 'hide_mod', False) in [True, 'true', 'True', 1]:
                continue
            # Проверяем ban_status с учетом возможных типов данных
            if getattr(mod, 'ban_status', False) in [True, 'true', 'True', 1]:
                continue
            # Проверяем статус мода - показываем только approved и pending
            mod_status = getattr(mod, 'status', 'approved')
            if mod_status not in ['approved', 'pending']:
                continue
            # Пропускаем локальные моды
            if getattr(mod, 'key', '').startswith('local_'):
                continue

            # Проверяем теги (если теги выбраны, мод должен иметь ВСЕ выбранные теги)
            if selected_tags:
                mod_tags = getattr(mod, 'tags', []) or []
                if not all(tag in mod_tags for tag in selected_tags):
                    continue

            # Проверяем фильтр демо
            if demo_filter:
                if not getattr(mod, 'is_demo_mod', False):
                    continue

            # Проверяем текстовый поиск
            if hasattr(self, 'search_text') and self.search_text:
                search_text_lower = self.search_text.lower()
                mod_name = getattr(mod, 'name', '').lower()
                mod_tagline = getattr(mod, 'tagline', '').lower()

                # Проверяем, содержится ли текст поиска в названии или описании
                if search_text_lower not in mod_name and search_text_lower not in mod_tagline:
                    continue

            self.filtered_mods.append(mod)

        # Сортируем моды
        self._sort_filtered_mods()

        # Сбрасываем на первую страницу при обновлении фильтров
        self.current_page = 1

        # Обновляем отображение
        self._update_mod_display()

    def _sort_filtered_mods(self):
        """Сортирует отфильтрованные моды"""
        if not hasattr(self, 'sort_combo') or not self.filtered_mods:
            return

        sort_type = self.sort_combo.currentIndex()
        reverse = not self.sort_ascending

        if sort_type == 0:  # По скачиваниям
            self.filtered_mods.sort(key=lambda mod: getattr(mod, 'downloads', 0), reverse=reverse)
        elif sort_type == 1:  # По дате обновления
            self.filtered_mods.sort(key=lambda mod: self._parse_date(getattr(mod, 'last_updated', '')), reverse=reverse)
        elif sort_type == 2:  # По дате создания
            self.filtered_mods.sort(key=lambda mod: self._parse_date(getattr(mod, 'created_date', '')), reverse=reverse)

    def _parse_date(self, date_str):
        """Преобразует строку даты в объект для сортировки"""
        if not date_str or date_str == 'N/A':
            return (0, 0, 0, 0, 0)  # Самая ранняя дата

        try:
            # Формат: "DD.MM.YY HH:MM"
            parts = date_str.split(' ')
            if len(parts) >= 2:
                date_part = parts[0]
                time_part = parts[1]

                day, month, year = map(int, date_part.split('.'))
                hour, minute = map(int, time_part.split(':'))

                # Преобразуем 2-значный год в 4-значный
                if year < 50:
                    year += 2000
                else:
                    year += 1900

                return (year, month, day, hour, minute)
        except Exception as e:
            logging.debug(f"_parse_date failed for '{date_str}': {e}")
            pass

        return (0, 0, 0, 0, 0)

    def _update_mod_display(self):
        """Обновляет отображение модов с учетом пагинации"""
        # Очищаем текущий список
        clear_layout_widgets(self.mod_list_layout, keep_last_n=1)

        # Вычисляем индексы для текущей страницы
        start_index = (self.current_page - 1) * self.mods_per_page
        end_index = start_index + self.mods_per_page
        current_page_mods = self.filtered_mods[start_index:end_index]

        # Добавляем моды текущей страницы
        for mod in current_page_mods:
            plaque = ModPlaqueWidget(mod, parent=self)
            plaque.install_requested.connect(self._on_mod_install_requested)
            plaque.uninstall_requested.connect(self._on_mod_uninstall_requested)
            plaque.clicked.connect(self._on_mod_clicked)
            plaque.details_requested.connect(self._on_mod_details_requested)
            # Устанавливаем состояние кнопки в зависимости от процесса установки
            plaque.install_button.setEnabled(not self.is_installing)
            # Вставляем перед stretch элементом
            self.mod_list_layout.insertWidget(self.mod_list_layout.count() - 1, plaque)

        # Обновляем пагинацию
        self._update_pagination_controls()

    def _update_pagination_controls(self):
        """Обновляет элементы управления пагинацией"""
        if not hasattr(self, 'page_label') or not hasattr(self, 'prev_page_btn') or not hasattr(self, 'next_page_btn'):
            return

        total_mods = len(self.filtered_mods)
        total_pages = max(1, (total_mods - 1) // self.mods_per_page + 1) if total_mods > 0 else 1

        # Обновляем текст страницы
        self.page_label.setText(tr("ui.page_label", current=self.current_page, total=total_pages))

        # Обновляем состояние кнопок
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < total_pages)

    def _on_mod_install_requested(self, mod):
        """Обработчик запроса на установку мода"""
        # Проверяем что не идет установка
        if self.is_installing:
            return
        # TODO: Реализовать логику установки мода
        # Можно использовать существующую систему InstallTranslationsThread
        self._install_single_mod(mod)

    def _install_single_mod(self, mod):
        """Устанавливает один мод из поиска"""
        try:
            # Проверяем что не идет установка
            if self.is_installing:
                return

            # Используем реальную систему установки
            # Найдем ВСЕ доступные главы у мода
            available_chapters = []
            for chapter_id in range(0, 5):  # Проверяем главы 0-4
                if mod.get_chapter_data(chapter_id):
                    available_chapters.append(chapter_id)

            if not available_chapters:
                QMessageBox.warning(self, tr("errors.error"), tr("errors.mod_no_files", mod_name=mod.name))
                return

            # Создаем задачи для всех доступных глав
            install_tasks = [(mod, chapter_id) for chapter_id in available_chapters]

            # Устанавливаем состояние установки
            self.is_installing = True
            self._set_install_buttons_enabled(False)
            self.action_button.setText(tr("ui.cancel_button"))
            # Обновляем идентификатор операции для инвалидации старых сигналов
            self._install_op_id = getattr(self, '_install_op_id', 0) + 1
            op_id = self._install_op_id
            self.current_install_thread = InstallTranslationsThread(self, install_tasks)
            self.install_thread = self.current_install_thread

            # Подключаем сигналы через обертки, чтобы игнорировать старые потоки после отмены/перезапуска
            self.install_thread.progress.connect(lambda v, oid=op_id: self._on_install_progress_token(v, oid))
            self.install_thread.status.connect(lambda msg, col, oid=op_id: self._on_install_status_token(msg, col, oid))
            self.install_thread.finished.connect(lambda ok, oid=op_id: self._on_install_finished_token(ok, oid))

            # Показываем прогресс бар и сразу выставляем 0%
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            try:
                self.update_status_signal.emit(tr("status.preparing_download"), UI_COLORS["status_warning"])
            except Exception:
                pass
            self._update_ui_for_selection()
 
            self.install_thread.start()

        except Exception as e:
            print(f"Error installing mod {mod.name}: {e}")
            QMessageBox.critical(self, tr("errors.error"), tr("errors.mod_install_failed", error=str(e)))

    # Версии с маркером операции, чтобы отбрасывать сигналы от старых потоков
    def _on_install_progress_token(self, value: int, op_id: int):
        if getattr(self, '_install_op_id', 0) == op_id and self.is_installing:
            self.progress_bar.setValue(value)

    def _on_install_status_token(self, message: str, color: str, op_id: int):
        if getattr(self, '_install_op_id', 0) == op_id and self.is_installing:
            self._update_status(message, color)

    def _on_install_finished_token(self, success: bool, op_id: int):
        if getattr(self, '_install_op_id', 0) != op_id:
            return
        self._on_single_mod_install_finished(success)

    def _on_single_mod_install_finished(self, success):
        """Обработчик завершения установки одиночного мода"""
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        # Если была установка (а не отмена), обновляем UI
        if success:
            self.update_status_signal.emit(tr("status.mod_installed_success"), UI_COLORS["status_success"])
        else:
            # Разруливаем отмену отдельно: не показываем "Ошибка установки мода"
            if getattr(self, '_operation_cancelled', False):
                # Сообщение об отмене уже отправлено при клике; просто сбросим флаг
                try:
                    self._operation_cancelled = False
                except Exception:
                    pass
            else:
                self.update_status_signal.emit(tr("status.mod_install_error"), UI_COLORS["status_error"])
            # Очистка временной папки после отмены/ошибки
            try:
                thr = self.current_install_thread
                temp_root = getattr(thr, 'temp_root', None)
                if temp_root and os.path.isdir(temp_root):
                    shutil.rmtree(temp_root, ignore_errors=True)
            except Exception:
                pass
        self.is_installing = False
        self._set_install_buttons_enabled(True)
        self.current_install_thread = None

        if success:
            # Перезагружаем моды из config.json файлов
            self._load_local_mods_from_folders()

            # Обновляем все плашки в поиске
            self._update_search_mod_plaques()

            # Обновляем библиотеку модов
            if hasattr(self, '_update_installed_mods_display'):
                self._update_installed_mods_display()

            self.update_status_signal.emit(tr("status.mod_installed_success"), UI_COLORS["status_success"])

        self._update_ui_for_selection()

    def _on_mod_uninstall_requested(self, mod):
        """Обработчик запроса на удаление мода"""

        # Проверяем что не идет установка
        if self.is_installing:
            return

        # Показываем диалог подтверждения
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(self, tr("dialogs.delete_confirmation"),
                                   tr("dialogs.delete_mod_confirmation", mod_name=mod.name),
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                   QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            # Удаляем мод
            self._uninstall_single_mod(mod)

    def _uninstall_single_mod(self, mod):
        """Удаляет один мод из поиска"""
        try:
            # Удаляем файлы мода
            self._delete_mod_files(mod)

            # Убираем мод из слотов если он там есть
            self._remove_mod_from_all_slots(mod)

            # Обновляем все плашки в поиске
            self._update_search_mod_plaques()

            # Обновляем библиотеку модов
            if hasattr(self, '_update_installed_mods_display'):
                self._update_installed_mods_display()

        except Exception as e:
            print(f"Error uninstalling mod {mod.name}: {e}")
            QMessageBox.critical(self, tr("errors.error"), tr("errors.mod_delete_failed", error=str(e)))

    def _update_search_mod_plaques(self):
        """Обновляет статус установки для всех плашек в поиске"""
        for i in range(self.mod_list_layout.count() - 1):  # -1 для stretch
            item = self.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget):
                    widget.update_installation_status()

    def _on_mod_clicked(self, mod):
        """Обработчик клика по плашке мода"""

        # Находим плашку мода и переключаем её состояние
        for i in range(self.mod_list_layout.count() - 1):  # -1 для stretch
            item = self.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget) and widget.mod_data == mod:
                    # Сначала убираем выделение со всех плашек
                    self._clear_all_mod_selections()
                    # Затем выделяем текущую
                    widget.set_selected(True)
                    break

    def _on_mod_details_requested(self, mod):
        """Обработчик запроса на показ деталей мода"""
        self._show_mod_details_dialog(mod)

    def _clear_all_mod_selections(self):
        """Убирает выделение со всех плашек модов"""
        for i in range(self.mod_list_layout.count() - 1):  # -1 для stretch
            item = self.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget):
                    widget.set_selected(False)



    def _update_mod(self, mod_data):
        """Обновляет мод (переустанавливает)"""


        # Предотвращаем множественные одновременные операции
        if self.is_installing:

            return

        self._install_single_mod(mod_data)

    def _on_mod_install_finished(self, success):
        """Обработчик завершения установки мода"""
        self.is_installing = False
        self._set_install_buttons_enabled(True)  # Разблокируем все кнопки установки
        self.current_install_thread = None
        self.progress_bar.setVisible(False)
        # Восстанавливаем текст кнопки через обновление UI
        self._update_ui_for_selection()

        if success:
            self.update_status_signal.emit(tr("status.mod_installed_success"), UI_COLORS["status_success"])
            # Обновляем список установленных модов
            self._update_installed_mods_display()
            # Обновляем состояние кнопок и статусов
            self._update_mod_widgets_slot_status()
            self._update_ui_for_selection()

            # Обновляем содержимое слотов для обновленных модов
            self._refresh_slots_content()

            # Продолжаем обновление следующих модов если есть
            if hasattr(self, 'pending_updates') and self.pending_updates:
                next_mod = self.pending_updates.pop(0)
                self.update_status_signal.emit(tr("status.updating_mod", mod_name=next_mod.name), UI_COLORS["status_warning"])
                self._update_mod(next_mod)
        else:
            self.update_status_signal.emit(tr("status.mod_install_error"), UI_COLORS["status_error"])
            # Очищаем список ожидающих обновлений при ошибке
            if hasattr(self, 'pending_updates'):
                self.pending_updates = []

    def _prompt_for_mods_dir(self):
        current_mods_dir = self.mods_dir
        new_parent_dir = QFileDialog.getExistingDirectory(
            self,
            tr("ui.select_new_mods_folder"),
            os.path.dirname(current_mods_dir) # Start from the current parent
        )

        if not new_parent_dir or os.path.dirname(current_mods_dir) == new_parent_dir:
            return # User cancelled or selected the same directory

        new_mods_dir = os.path.join(new_parent_dir, "mods")

        if os.path.exists(new_mods_dir):
            QMessageBox.critical(self, tr("errors.error"), tr("errors.mods_folder_exists", dir=new_parent_dir))
            return

        try:
            self.update_status_signal.emit(tr("status.moving_mods_folder"), UI_COLORS["status_warning"])
            QApplication.processEvents() # Update UI

            shutil.move(current_mods_dir, new_mods_dir)

            self.mods_dir = new_mods_dir
            self.local_config["mods_dir_path"] = new_parent_dir
            self._write_local_config()

            QMessageBox.information(self, tr("dialogs.success"), tr("dialogs.mods_folder_moved", path=new_mods_dir))
            self.update_status_signal.emit(tr("status.mods_folder_location_changed"), UI_COLORS["status_success"])

        except Exception as e:
            QMessageBox.critical(self, tr("dialogs.move_error"), tr("dialogs.mods_folder_move_failed", error=str(e)))
            # Revert UI state if move fails
            self.mods_dir = current_mods_dir
            self.update_status_signal.emit(tr("status.mods_folder_change_error"), UI_COLORS["status_error"])


    def _update_change_path_button_text(self):
        self.change_path_button.setText(self.game_mode.path_change_button_text)

    def _full_install_tooltip(self) -> str:
        if platform.system() == "Darwin":
            return tr("tooltips.macos_install_unavailable")
        return tr("tooltips.full_install_instructions")

    def _on_toggle_full_install(self, state):
        self.is_full_install = bool(state)
        if platform.system() == "Darwin" and self.is_full_install:
            QMessageBox.information(self, tr("dialogs.unavailable"), tr("dialogs.macos_install_unavailable"))
            self.full_install_checkbox.blockSignals(True)
            self.full_install_checkbox.setChecked(False)
            self.full_install_checkbox.blockSignals(False)
            return

        # Обновляем текст кнопки действия
        self._update_ui_for_selection()

    def _save_window_geometry(self):
        geom_ba = self.saveGeometry()
        self.local_config["window_geometry"] = geom_ba.toHex().data().decode()
        self._write_local_config()

    def load_font(self):
        self.custom_font_family = None
        self._font_families_chain = list(DEFAULT_FONT_FALLBACK_CHAIN)

        font_path = resource_path("assets/main.ttf")
        if os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    self.custom_font_family = families[0]
                else:
                    pass
            else:
                pass
        else:
            pass

    def apply_theme(self):
            theme = THEMES["default"]
            background_path = None

            # Проверяем, установлен ли флаг отключения фона в конфиге
            background_disabled = self.local_config.get("background_disabled", False)

            if self.background_movie is not None:
                self.background_movie.stop()
                self.background_movie.deleteLater()
                self.background_movie = None
            self.background_pixmap = None

            # Загружаем фон, только если он НЕ отключен.
            if not background_disabled:
                background_path = self.local_config.get("custom_background_path") or resource_path(theme.get("background", ""))

                if background_path:
                    self._bg_loader = BgLoader(background_path, self.size())
                    self._bg_loader.loaded.connect(self._on_bg_ready)
                    self._bg_loader.start()

            # Кастомная тема: применяем шрифты и стили
            user_bg_hex = self.local_config.get("custom_color_background")
            if user_bg_hex and self._is_valid_hex_color(user_bg_hex):
                # Добавляем 75% прозрачности (C0) к пользовательскому HEX цвету
                frame_bg_color = f"#C0{user_bg_hex.lstrip('#')}"
            else:
                # Цвет по умолчанию - полупрозрачный черный
                frame_bg_color = "rgba(0, 0, 0, 150)"

            button_color = self.local_config.get("custom_color_button") or theme["colors"]["button"]
            border_color = self.local_config.get("custom_color_border") or theme["colors"]["border"]
            button_hover_color = self.local_config.get("custom_color_button_hover") or theme["colors"]["button_hover"]
            main_text_color = self.local_config.get("custom_color_text") or theme["colors"]["text"]
            base_family = self.custom_font_family or theme["font_family"]
            families = [base_family] + [f for f in self._font_families_chain if f != base_family]

            font_family_main = families[0]
            font_size_main = theme["font_size_main"]
            font_size_small = theme["font_size_small"]

            status_font = QFont(font_family_main, font_size_small)
            self.status_label.setFont(status_font)

            # Explicit color overrides for certain widgets
            explicit_color_widgets = [getattr(self, "telegram_button", None), getattr(self, "discord_button", None)]
            explicit_colors = [UI_COLORS["link"], UI_COLORS["social_discord"]]
            for widget, color in zip(explicit_color_widgets, explicit_colors):
                if widget is not None: widget.setStyleSheet(f"color: {color};")

            qss_font_chain = '", "'.join(families)
            style_sheet = f"""
                    QFrame#bottom_widget, QFrame#settings_widget {{ background-color: {frame_bg_color}; }}
                    QWidget {{ font-family: "{qss_font_chain}"; outline: none; font-size: {font_size_main}pt; color: {main_text_color}; background-color: transparent; }}
                    QDialog, QMessageBox {{ font-family: "{qss_font_chain}"; font-size: {font_size_small}pt; color: {main_text_color}; background-color: {frame_bg_color}; border: 3px solid {border_color}; }}
                    QDialog > QLabel, QMessageBox > QLabel {{ background: transparent; font-size: {font_size_small}pt; }}
                    QDialog QPushButton, QMessageBox QPushButton {{ font-size: {font_size_small}pt; }}
                    QPushButton {{ background-color: {button_color}; border: 2px solid {border_color}; color: {theme["colors"]["button_text"]}; padding: 5px; min-height: 30px; min-width: 100px; }}
                    QPushButton:hover {{ background-color: {button_hover_color}; }}
                    QPushButton:disabled, QComboBox:disabled {{ background-color: #333333; color: #888888; border: 2px solid #555555; }}
                    QPushButton#addTranslationButton {{ min-width: 33px; min-height: 33px; padding: 2px; }}
                    QComboBox {{ background-color: {button_color}; color: {theme["colors"]["button_text"]}; border: 2px solid {border_color}; padding: 4px; min-height: 30px; }}
                    QComboBox QAbstractItemView {{ background-color: {button_color}; border: 2px solid {border_color}; color: {theme["colors"]["button_text"]}; selection-background-color: {button_hover_color}; }}
                    QTextEdit, QTextBrowser {{ background-color: {frame_bg_color}; border: 2px solid {border_color}; }}
                    QFrame#filters {{
                        background-color: {frame_bg_color};
                        border: 2px solid {border_color};
                        padding: 4px 8px;
                    }}
                    QPushButton#sortOrderBtn {{
                        min-width: 35px;
                        max-width: 35px;
                        padding-left: 0px;
                        padding-right: 0px;
                        background-color: {button_color};
                        border: 2px solid {border_color};
                        color: {theme["colors"]["button_text"]};
                        font-weight: bold;
                        font-size: 12px;
                    }}
                    QPushButton#sortOrderBtn:hover {{
                        background-color: {button_hover_color};
                    }}
                    QPushButton#searchBtn {{
                        min-width: 35px;
                        max-width: 35px;
                        min-height: 30px;
                        max-height: 30px;
                        padding-left: 0px;
                        padding-right: 0px;
                        background-color: {button_color};
                        border: 2px solid {border_color};
                        color: {theme["colors"]["button_text"]};
                        font-weight: bold;
                        font-size: 16px;
                    }}
                    QPushButton#searchBtn:hover {{
                        background-color: {button_hover_color};
                    }}
                    QTextEdit, QTextBrowser {{ background-color: {frame_bg_color}; color: {main_text_color}; border: 2px solid {border_color}; min-height: 100px; }}
                    QTabBar::tab {{ background-color: {button_color}; color: {theme["colors"]["button_text"]}; border: 2px solid {border_color}; padding: 5px; min-height: 25px; min-width: 80px; }}
                    QTabBar::tab:selected, QTabBar::tab:hover {{ background-color: {button_hover_color}; }}
                    QTabBar::tab:disabled {{ background-color: #333333; color: #888888; border: 2px solid #555555; }}
                    QTabWidget::pane {{ background: transparent; border: 0px; }}
                    QCheckBox:disabled {{ color: #888888; }}
                    QCheckBox::indicator {{ width: 15px; height: 15px; background-color: {button_color}; border: 2px solid {border_color}; }}
                    QCheckBox::indicator:checked {{ background-color: {"#ffffff" if not self.color_widgets['button_hover'].text() else button_hover_color}; }}
                    QCheckBox::indicator:disabled {{ background-color: #333333; border: 2px solid #555555; }}
                    QPushButton:checked {{ background-color: {button_hover_color}; border: 2px solid {main_text_color}; }}
            """

            # Отдельно определяем цвета для скроллбара согласно новой логике
            scroll_handle_color = self.local_config.get("custom_color_button") or "white"
            scroll_groove_color = "rgba(0, 0, 0, 40)" # Полупрозрачный темный фон для дорожки

            scroll_bar_qss = f"""
                QScrollBar:vertical {{
                    border: none;
                    background: {scroll_groove_color};
                    width: 14px;
                    margin: 0;
                }}
                QScrollBar::handle:vertical {{
                    background-color: {scroll_handle_color};
                    min-height: 25px;
                }}
                QScrollBar:horizontal {{
                    border: none;
                    background: {scroll_groove_color};
                    height: 14px;
                    margin: 0;
                }}
                QScrollBar::handle:horizontal {{
                    background-color: {scroll_handle_color};
                    min-width: 25px;
                }}
            """
            style_sheet += scroll_bar_qss

            app_inst = QApplication.instance()
            (app_inst if isinstance(app_inst, QApplication) else self).setStyleSheet(style_sheet)

            for widget in self.findChildren(QWidget):
                style = widget.style()
                if style:
                    style.unpolish(widget)
                    style.polish(widget)
            self._update_mod_plaques_styles()
            self.update()

    def _configure_hidden_tab_bar(self, tab_widget: QTabWidget):
        """Вспомогательный метод для полной деактивации и скрытия стандартной панели вкладок."""
        bar = tab_widget.tabBar()
        if bar:
            bar.hide()
            bar.setEnabled(False)
            bar.setMaximumSize(0, 0)
            bar.setMinimumSize(0, 0)
            bar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _init_save_manager_ui(self):
        lay = QVBoxLayout(self.save_manager_widget)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        top = QHBoxLayout()
        top.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.save_back_btn = QPushButton(tr("ui.back_button"))
        self.save_back_btn.clicked.connect(self._hide_save_manager)
        self.save_back_btn.setVisible(False)

        self.change_save_path_btn = QPushButton(tr("buttons.change_save_path"))
        self.change_save_path_btn.clicked.connect(self._prompt_for_save_path)
        top.addWidget(self.change_save_path_btn)
        lay.addLayout(top)

        self.save_tabs = NoScrollTabWidget()
        self._slot_labels = {}
        for ch in range(1, 5):
            tab = QWidget(); v = QVBoxLayout(tab)
            for s in range(3):
                lbl = QLabel(self._slot_placeholder(False))
                lbl = ClickableLabel(ch, s, self._slot_placeholder(False))
                lbl.setObjectName(f"slot_{ch}_{s}")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setMinimumWidth(300)
                lbl.setStyleSheet("border:1px solid white; background-color: rgba(0,0,0,128); padding:4px;")
                lbl.clicked.connect(self._on_save_manager_slot_clicked)
                lbl.doubleClicked.connect(self._on_slot_double_clicked)
                v.addWidget(lbl)
                self._slot_labels[(ch, s)] = lbl
            v.addStretch()
            self.save_tabs.addTab(tab, tr("ui.chapter_tab_title", chapter_num=ch))
        self._configure_hidden_tab_bar(self.save_tabs)

        chapter_bar = QHBoxLayout()
        chapter_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chapter_bar.setSpacing(2)
        chapter_bar.setContentsMargins(0, 0, 0, 0)
        self._chapter_buttons = []
        for ch in range(1, 5):
            btn = QPushButton(tr("ui.chapter_button_title", chapter_num=ch))
            btn.setCheckable(True)
            btn.setMinimumWidth(80)
            if ch == 1:
                btn.setChecked(True)
            btn.clicked.connect(lambda _checked, idx=ch-1: self.save_tabs.setCurrentIndex(idx))
            self._chapter_buttons.append(btn)
            chapter_bar.addWidget(btn)
        lay.addLayout(chapter_bar)

        def _sync_buttons(index: int):
            for i, b in enumerate(self._chapter_buttons):
                b.setChecked(i == index)
        self.save_tabs.currentChanged.connect(_sync_buttons)

        lay.addWidget(self.save_tabs)

        self.collection_name_lbl = QLabel("")
        self.collection_name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.collection_name_lbl.setVisible(False)
        lay.addWidget(self.collection_name_lbl)

        bottom = QHBoxLayout()
        bottom.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.left_col_btn = QPushButton("←")
        self.left_col_btn.clicked.connect(lambda: self._navigate_collection(-1))
        bottom.addWidget(self.left_col_btn)

        self.switch_collection_btn = QPushButton(tr("buttons.additional_slots"))
        self.switch_collection_btn.clicked.connect(self._toggle_collection_view)
        bottom.addWidget(self.switch_collection_btn)

        self.right_col_btn = QPushButton("→")
        self.right_col_btn.clicked.connect(lambda: self._navigate_collection(1))
        bottom.addWidget(self.right_col_btn)
        lay.addLayout(bottom)

        self.rename_collection_btn = QPushButton(tr("buttons.rename_collection"))
        self.rename_collection_btn.clicked.connect(self._rename_current_collection)
        self.delete_collection_btn  = QPushButton(tr("buttons.delete_collection"))
        self.delete_collection_btn.clicked.connect(self._delete_current_collection)
        self.rename_collection_btn.setVisible(False)
        self.delete_collection_btn.setVisible(False)
        copy_bar = QHBoxLayout()
        copy_bar.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        copy_bar.addStretch()
        self.copy_from_main_btn = QPushButton(tr("buttons.copy_from_main"))
        self.copy_from_main_btn.clicked.connect(lambda: self._copy_between_storages(to_collection=True))
        copy_bar.addWidget(self.copy_from_main_btn)

        self.copy_to_main_btn = QPushButton(tr("buttons.copy_to_main"))
        self.copy_to_main_btn.clicked.connect(lambda: self._copy_between_storages(to_collection=False))
        copy_bar.addWidget(self.copy_to_main_btn)
        copy_bar.addStretch()
        lay.addLayout(copy_bar)

        self.slot_actions = QHBoxLayout()
        self.slot_actions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.show_btn   = QPushButton(tr("buttons.show"))
        self.erase_btn  = QPushButton(tr("buttons.erase"))
        self.import_btn = QPushButton(tr("buttons.import"))
        self.export_btn = QPushButton(tr("buttons.export"))
        for b in (self.show_btn, self.erase_btn, self.import_btn, self.export_btn):
            b.setVisible(False)
            self.slot_actions.addWidget(b)
        self.show_btn.clicked.connect(self._action_show_save)
        self.erase_btn.clicked.connect(self._action_delete_save)
        self.import_btn.clicked.connect(lambda: self._action_import_export(True))
        self.export_btn.clicked.connect(lambda: self._action_import_export(False))
        lay.addLayout(self.slot_actions)

        top.addWidget(self.rename_collection_btn)
        top.addWidget(self.delete_collection_btn)

        self.save_tabs.currentChanged.connect(lambda _: self._on_chapter_tab_changed())
        self.save_manager_widget.installEventFilter(self)
        self._update_slot_highlight()

    def _hide_save_manager(self):
        self.save_manager_widget.setVisible(False)
        self.is_save_manager_view = False
        if self.is_settings_view:
            self.settings_widget.setVisible(True)
        else:
            self.main_tab_widget.setVisible(True)
            self.bottom_widget.setVisible(True)

    def _slot_placeholder(self, active: bool) -> str:
        return (tr("ui.placeholder_format")
                if active else tr("status.empty_save_slot"))

    def _clear_selected_slot(self):
        self.selected_slot = None
        self._update_slot_highlight()
        self._update_slot_action_bar()

    def eventFilter(self, obj, ev):
        if obj is self.save_manager_widget and ev.type() == QEvent.Type.MouseButtonPress:
            click_pos = ev.pos(); inside = any(lbl.rect().contains(lbl.mapFrom(self.save_manager_widget, click_pos)) for lbl in self._slot_labels.values())
            if not inside: self._clear_selected_slot()
        return super().eventFilter(obj, ev)

    def _update_slot_action_bar(self):
        in_main   = self.current_collection_idx.get(self.save_tabs.currentIndex() + 1, -1) == -1
        visible   = self.selected_slot is not None
        for b in (self.show_btn, self.import_btn, self.erase_btn, self.export_btn):
            b.setVisible(visible)

        has_data = False
        if self.selected_slot:
            ch, s  = self.selected_slot
            idx    = self.current_collection_idx.get(ch, -1)
            base   = self._get_collection_path(ch, idx)
            fp     = os.path.join(base, f"filech{ch}_{s}")
            has_data = os.path.exists(fp) and os.path.getsize(fp) > 0

        self.erase_btn.setEnabled(has_data)
        self.export_btn.setEnabled(has_data)

        self.copy_from_main_btn.setEnabled(not in_main)
        self.copy_to_main_btn.setEnabled(not in_main)

    def _on_slot_double_clicked(self, chapter: int, slot: int):
        idx  = self.current_collection_idx.get(chapter, -1)
        base = self._get_collection_path(chapter, idx)
        fp   = os.path.join(base, f"filech{chapter}_{slot}")
        if not (os.path.exists(fp) and os.path.getsize(fp) > 0):
            return
        dlg = SaveEditorDialog(fp, self)
        if dlg.exec():
            self._refresh_save_slots()


    def _on_save_manager_slot_clicked(self, chapter: int, slot: int):
        """Запоминаем выбранный слот и обновляем подсветку."""
        self.selected_slot = (chapter, slot)
        self._update_slot_highlight()
        self._update_slot_action_bar()

    def _update_slot_highlight(self):
        user_bg = self.local_config.get("custom_color_background")
        if user_bg and self._is_valid_hex_color(user_bg):
            slot_bg = f"#80{user_bg.lstrip('#')}"
        else:
            slot_bg = "#80000000"
        for (ch, sl), lbl in self._slot_labels.items():
            if self.selected_slot == (ch, sl):
                lbl.setStyleSheet(f"border:2px solid white; background-color: {slot_bg}; padding:4px;")
            else:
                lbl.setStyleSheet(f"border:1px solid white; background-color: {slot_bg}; padding:4px;")

    def _collection_regex(self, chapter: int):
        return re.compile(rf"(.+?)_(\d+)_{chapter}$")

    def _list_collections(self, chapter: int) -> list[str]:
        cols = []
        rx = self._collection_regex(chapter)
        if not (self.save_path and os.path.isdir(self.save_path)):
            return cols
        for entry in os.listdir(self.save_path):
            m = rx.match(entry)
            if m and os.path.isdir(os.path.join(self.save_path, entry)):
                cols.append(entry)
        def _index(name: str) -> int:
            m = rx.match(name)
            return int(m.group(2)) if m else 10_000
        cols.sort(key=_index)
        return cols

    def _get_collection_path(self, chapter: int, idx: int) -> str:
        if idx == -1:
            return self.save_path
        cols = self._list_collections(chapter)
        if 0 <= idx < len(cols):
            return os.path.join(self.save_path, cols[idx])
        return ""

    def _return_from_save_manager(self):
        """Возвращает с экрана менеджера сохранений на главный экран."""
        self._hide_save_manager()
        self.settings_button.setText(tr("ui.settings_title"))
        try:
            self.settings_button.clicked.disconnect(self._return_from_save_manager)
        except TypeError:
            # Сигнал уже мог быть отключен
            pass
        self.settings_button.clicked.connect(self._toggle_settings_view)

    def _on_configure_saves_click(self):
        if not self._find_and_validate_save_path():
            return
        self.is_save_manager_view = True
        self.main_tab_widget.setVisible(False)
        self.bottom_widget.setVisible(False)
        self.settings_widget.setVisible(False)
        self.save_manager_widget.setVisible(True)
        self.selected_slot = None
        self._refresh_save_slots()
        self.update_status_signal.emit(tr("status.save_path_info", save_path=self.save_path), UI_COLORS["status_info"])
        self.settings_button.setText(tr("ui.back_button"))
        try:
            self.settings_button.clicked.disconnect(self._toggle_settings_view)
        except TypeError:
            pass # Сигнал уже мог быть отключен
        self.settings_button.clicked.connect(self._return_from_save_manager)

    def _refresh_save_slots(self):
        if not (self.save_path and os.path.isdir(self.save_path)):
            return
        chapter = self.save_tabs.currentIndex() + 1
        idx = self.current_collection_idx.get(chapter, -1)
        base_path = self._get_collection_path(chapter, idx) or self.save_path
        for s in range(3):
            fp = os.path.join(base_path, f"filech{chapter}_{s}")
            active = os.path.exists(fp) and os.path.getsize(fp) > 0
            if active:
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.read().splitlines()
                    nickname = lines[0] if len(lines) > 0 else "???"
                    currency = lines[10] if len(lines) > 10 else "0"
                except Exception:
                    nickname, currency = "???", "0"

                fin_idx   = SAVE_SLOT_FINISH_MAP.get(s, -1)
                fin_fp    = os.path.join(base_path, f"filech{chapter}_{fin_idx}")
                finished  = os.path.exists(fin_fp) and os.path.getsize(fin_fp) > 0
                status    = tr("status.completed_save") if finished else tr("status.incomplete_save")
                text      = tr("ui.save_info", nickname=nickname, currency=currency, status=status)
            else:
                text = self._slot_placeholder(False)

            self._slot_labels[(chapter, s)].setText(text)
        self._update_collection_ui()
        self._update_slot_highlight()
        self._update_slot_action_bar()

    def _find_and_validate_save_path(self) -> bool:
        if is_valid_save_path(self.save_path): return True
        default_path = get_default_save_path()
        if is_valid_save_path(default_path):
            self.save_path = default_path
            self.local_config["save_path"] = self.save_path
            self._write_local_config()
            return True
        return self._prompt_for_save_path()

    def _prompt_for_save_path(self) -> bool:
        if not (path := QFileDialog.getExistingDirectory(self, tr("ui.select_deltarune_saves_folder"))): return False
        if not is_valid_save_path(path):
            QMessageBox.warning(self, tr("errors.empty_folder_title"), tr("errors.empty_folder_message"))
            return False
        self.save_path = path
        self.local_config["save_path"] = self.save_path
        self._write_local_config()
        return True

    def _toggle_collection_view(self):
        chapter = self.save_tabs.currentIndex() + 1
        idx = self.current_collection_idx.get(chapter, -1)
        if idx == -1:
            cols = self._list_collections(chapter)
            if not cols and not self._create_new_collection(chapter):
                return
            self.current_collection_idx[chapter] = 0
        else:
            self.current_collection_idx[chapter] = -1
        self._refresh_save_slots()

    def _navigate_collection(self, direction: int):
        chapter = self.save_tabs.currentIndex() + 1
        cols = self._list_collections(chapter)
        if not cols and direction > 0:
            if not self._create_new_collection(chapter):
                return
            cols = self._list_collections(chapter)
        if not cols:
            return
        idx = self.current_collection_idx.get(chapter, -1)
        if idx == -1:
            idx = 0
        else:
            idx += direction
        if idx < 0:
            idx = 0
        elif idx >= len(cols):
            if direction > 0 and self._create_new_collection(chapter):
                idx = len(cols)
            else:
                idx = len(cols) - 1
        self.current_collection_idx[chapter] = idx
        self.selected_slot = None
        self._refresh_save_slots()

    def _create_new_collection(self, chapter: int) -> bool:
        if (name := self._prompt_collection_name()) is None: return False
        idx = len(self._list_collections(chapter))
        folder = f"{name}_{idx}_{chapter}"
        try:
            os.makedirs(os.path.join(self.save_path, folder), exist_ok=False)
            return True
        except Exception as e:
            QMessageBox.critical(self, tr("errors.error"), tr("errors.folder_creation_failed", error=str(e)))
            return False

    def _prompt_collection_name(self, default: str = "Collection") -> Optional[str]:
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("dialogs.new_collection"))
        v, e = QVBoxLayout(dlg), QLineEdit()
        e.setMaxLength(20); e.setText(default); e.selectAll(); v.addWidget(e)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject); v.addWidget(bb)
        e.setFocus()
        return (e.text().strip() or default) if dlg.exec() == QDialog.DialogCode.Accepted else None

    def _update_collection_ui(self):
        chapter = self.save_tabs.currentIndex() + 1
        idx = self.current_collection_idx.get(chapter, -1)
        in_col = idx != -1
        cols = self._list_collections(chapter)

        self.switch_collection_btn.setText(tr("buttons.main_slots") if in_col else tr("buttons.additional_slots"))
        self.left_col_btn.setEnabled(in_col and idx > 0)
        self.right_col_btn.setEnabled(in_col)

        self.rename_collection_btn.setVisible(in_col)
        self.delete_collection_btn.setVisible(in_col)
        self.copy_from_main_btn.setVisible(in_col)
        self.copy_to_main_btn.setVisible(in_col)
        if in_col and 0 <= idx < len(cols):
            self.collection_name_lbl.setText(cols[idx].rsplit("_", 2)[0])
            self.collection_name_lbl.setVisible(True)
        else:
            self.collection_name_lbl.setVisible(False)
        self.change_save_path_btn.setVisible(not in_col)

    def _on_chapter_tab_changed(self):
        ch = self.save_tabs.currentIndex() + 1
        if ch not in self.current_collection_idx:
            self.current_collection_idx[ch] = -1
        self.selected_slot = None
        self._refresh_save_slots()

    def _rename_current_collection(self):
        chapter = self.save_tabs.currentIndex() + 1
        idx = self.current_collection_idx.get(chapter, -1)
        if idx == -1:
            return
        cols = self._list_collections(chapter)
        old_folder = cols[idx]
        old_name = old_folder.rsplit("_", 2)[0]
        new_name, ok = QInputDialog.getText(self, tr("dialogs.change_collection_name"),
        tr("dialogs.new_name"), text=old_name)
        if not ok or not new_name.strip():
            return
        new_folder = f"{new_name.strip()}_{idx}_{chapter}"
        try:
            os.rename(os.path.join(self.save_path, old_folder),
                      os.path.join(self.save_path, new_folder))
            self._refresh_save_slots()
        except Exception as e:
            QMessageBox.critical(self, tr("errors.error"), tr("errors.rename_failed", error=str(e)))

    def _delete_current_collection(self):
        chapter = self.save_tabs.currentIndex() + 1
        idx = self.current_collection_idx.get(chapter, -1)
        if idx == -1:
            return
        cols = self._list_collections(chapter)
        folder = cols[idx]
        if QMessageBox.question(self, tr("dialogs.delete_collection"),
                                tr("dialogs.delete_collection_confirmation")) \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(os.path.join(self.save_path, folder))
            remaining = self._list_collections(chapter)
            for new_idx, f in enumerate(remaining):
                parts = f.rsplit("_", 2)
                cur_idx = int(parts[1])
                if cur_idx != new_idx:
                    new_folder = f"{parts[0]}_{new_idx}_{chapter}"
                    os.rename(os.path.join(self.save_path, f),
                              os.path.join(self.save_path, new_folder))
            self.current_collection_idx[chapter] = -1
            self._refresh_save_slots()
        except Exception as e:
            QMessageBox.critical(self, tr("errors.error"), tr("errors.deletion_failed", error=str(e)))

    def _copy_between_storages(self, to_collection: bool):
        chapter = self.save_tabs.currentIndex() + 1
        if self.selected_slot is None or self.selected_slot[0] != chapter:
            slot_indices = range(3)
        else:
            slot_indices = [self.selected_slot[1]]

        idx = self.current_collection_idx.get(chapter, -1)
        if idx == -1:
            return

        src_dir = self.save_path if to_collection else self._get_collection_path(chapter, idx)
        dst_dir = self._get_collection_path(chapter, idx) if to_collection else self.save_path
        if not src_dir or not dst_dir:
            return

        prompt = (tr("dialogs.overwrite_all_3_slots_collection") if to_collection
                  else tr("dialogs.overwrite_all_3_main_slots")) \
                 if self.selected_slot is None else \
                 (tr("dialogs.overwrite_selected_slot_collection") if to_collection
                  else tr("dialogs.overwrite_selected_main_slot"))
        reply = QMessageBox.question(
            self, tr("dialogs.copy_confirmation"), prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            for slot_idx in slot_indices:
                finish_idx = SAVE_SLOT_FINISH_MAP.get(slot_idx, -1)
                names = [f"filech{chapter}_{slot_idx}", f"filech{chapter}_{finish_idx}"]
                for _name in names:
                    src = os.path.join(src_dir, _name)
                    dst = os.path.join(dst_dir, _name)
                    if os.path.exists(src):
                        shutil.copy2(src, dst)
                    elif os.path.exists(dst):
                        os.remove(dst)
            self._refresh_save_slots()
            self.update_status_signal.emit(tr("status.copying_completed"), UI_COLORS["status_success"])
        except Exception as e:
            QMessageBox.critical(self, tr("errors.error"), tr("errors.copy_failed", error=str(e)))
            self.update_status_signal.emit(tr("status.copying_error"), UI_COLORS["status_error"])

    def _action_show_save(self):
        if not self.selected_slot:
            return
        ch, s = self.selected_slot
        idx = self.current_collection_idx.get(ch, -1)
        path = self._get_collection_path(ch, idx)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _action_delete_save(self):
        if not self.selected_slot:
            return
        ch, s = self.selected_slot
        idx = self.current_collection_idx.get(ch, -1)
        base = self._get_collection_path(ch, idx)
        fp = os.path.join(base, f"filech{ch}_{s}")
        if not os.path.exists(fp):
            return
        if QMessageBox.question(self, tr("dialogs.delete_save"),
                                tr("dialogs.delete_save_confirmation")) \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(fp)
            self._refresh_save_slots()
        except Exception as e:
            QMessageBox.critical(self, tr("errors.error"), str(e))

    def _action_import_export(self, is_import: bool):
        if not self.selected_slot:
            return
        ch, s = self.selected_slot
        idx = self.current_collection_idx.get(ch, -1)
        base_cur = self._get_collection_path(ch, idx)
        src_fp = os.path.join(base_cur, f"filech{ch}_{s}")

        choice, ok = QInputDialog.getItem(
            self, tr("dialogs.where_to") if not is_import else tr("dialogs.where_from"),
            tr("ui.select_storage"),
            [tr("dialogs.external_file") if is_import else tr("dialogs.external_folder"),
             tr("dialogs.additional_collection") if idx == -1 else tr("dialogs.main_slots")], 0, False)
        if not ok:
            return

        if choice in [tr("dialogs.external_file"), tr("dialogs.external_folder")]:
            if is_import:
                fp, _ = QFileDialog.getOpenFileName(
                    self, tr("ui.select_save_file"), "", f"filech{ch}_*. (*)")
                if not fp:
                    return
                if not re.fullmatch(rf"filech{ch}_[0-2]", os.path.basename(fp)):
                    QMessageBox.warning(self, tr("errors.invalid_file"),
                    tr("errors.wrong_save_file"))
                    return
                shutil.copy2(fp, src_fp)
                fin_idx   = SAVE_SLOT_FINISH_MAP.get(s, -1)
                fin_name  = f"filech{ch}_{fin_idx}"
                fin_src   = os.path.join(os.path.dirname(fp), fin_name)
                fin_dst   = os.path.join(base_cur, fin_name)
                if os.path.exists(fin_src):
                    shutil.copy2(fin_src, fin_dst)
            else:
                dir_ = QFileDialog.getExistingDirectory(self, tr("dialogs.export_save_location"))
                if not dir_:
                    return
                if not os.path.exists(src_fp):
                    QMessageBox.warning(self, tr("errors.no_save"), tr("errors.empty_slot"))
                    return
                shutil.copy2(src_fp, dir_)
                fin_idx   = SAVE_SLOT_FINISH_MAP.get(s, -1)
                fin_src   = os.path.join(base_cur, f"filech{ch}_{fin_idx}")
                if os.path.exists(src_fp) and os.path.exists(fin_src):
                    shutil.copy2(fin_src, dir_)
        else:
            if idx == -1:
                cols = self._list_collections(ch)
                if not cols:
                    if QMessageBox.question(self, tr("dialogs.no_collections"),
                                            tr("dialogs.create_new_collection_question")) \
                            != QMessageBox.StandardButton.Yes:
                        return
                    if not self._create_new_collection(ch):
                        return
                    cols = self._list_collections(ch)
                sel, ok = QInputDialog.getItem(self, tr("ui.collections"), tr("ui.select"), cols, 0, False)
                if not ok:
                    return
                target_base = os.path.join(self.save_path, sel)
            else:
                target_base = self.save_path

            src_main_fp = os.path.join(base_cur, f"filech{ch}_{s}")
            target_main_fp = os.path.join(target_base, f"filech{ch}_{s}")
            fin_idx  = SAVE_SLOT_FINISH_MAP.get(s, -1)
            fin_name = f"filech{ch}_{fin_idx}"
            src_fin_fp = os.path.join(base_cur, fin_name)
            target_fin_fp = os.path.join(target_base, fin_name)

            if is_import:
                if not os.path.exists(target_main_fp):
                    QMessageBox.warning(self, tr("errors.no_save"),
                    tr("errors.no_import_save"))
                    return
                shutil.copy2(target_main_fp, src_main_fp)
                if os.path.exists(target_fin_fp):
                    shutil.copy2(target_fin_fp, src_fin_fp)
                elif os.path.exists(src_fin_fp):
                    os.remove(src_fin_fp)
            else:
                if not os.path.exists(src_main_fp):
                    QMessageBox.warning(self, tr("errors.no_save"), tr("errors.empty_slot"))
                    return
                shutil.copy2(src_main_fp, target_main_fp)
                if os.path.exists(src_fin_fp):
                    shutil.copy2(src_fin_fp, target_fin_fp)
                elif os.path.exists(target_fin_fp):
                    os.remove(target_fin_fp)

        self._refresh_save_slots()

    def _on_bg_ready(self, obj):
        if isinstance(obj, tuple):
            if obj[0] == 'gif':
                if self.background_movie is not None: self.background_movie.stop(); self.background_movie.deleteLater()
                self.background_movie = QMovie(obj[1])
                self.background_movie.frameChanged.connect(self.update)
                self.background_movie.start()
                self.background_pixmap = None
            elif obj[0] == 'img':
                self.background_movie = None
                self.background_pixmap = QPixmap.fromImage(obj[1]).scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            self.update()

    def _switch_settings_page(self, page: QWidget):
        if self.current_settings_page and self.current_settings_page is not page:
            self.settings_nav_stack.append(self.current_settings_page)
            if len(self.settings_nav_stack) > 20: self.settings_nav_stack.pop(0)
            self.current_settings_page.setVisible(False)
        page.setVisible(True)
        self.current_settings_page = page

    def _lock_window_size(self):
        """Фиксирует текущий размер окна, чтобы контент (changelog/help) не менял высоту/ширину."""
        try:
            sz = self.size()
            self._locked_size = sz
            self.setMinimumSize(sz)
            self.setMaximumSize(sz)
        except Exception:
            pass

    def _unlock_window_size(self):
        """Снимает фиксацию размера окна, возвращая возможность обычного ресайза пользователем."""
        try:
            # Разрешаем стандартные пределы Qt
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self._locked_size = None
        except Exception:
            pass

    def _go_back(self):
        """Возврат на предыдущую страницу из history‑стека."""
        if hasattr(self, 'settings_nav_stack') and self.settings_nav_stack:
            prev = self.settings_nav_stack.pop()
            if self.current_settings_page:
                self.current_settings_page.setVisible(False)
            prev.setVisible(True)
            self.current_settings_page = prev
        else:
            # Если стек пуст, возвращаемся в главное меню (выходим из настроек)
            self._toggle_settings_view()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.background_movie is not None: painter.drawPixmap(self.rect(), self.background_movie.currentPixmap())
        elif self.background_pixmap: painter.drawPixmap(self.rect(), self.background_pixmap)
        else:
            bg_color_str = self.local_config.get("custom_color_background") or "rgba(0, 0, 0, 200)"
            try: painter.fillRect(self.rect(), QColor(bg_color_str))
            except Exception: painter.fillRect(self.rect(), QColor("rgba(0, 0, 0, 200)"))
        super().paintEvent(event)

    def _on_background_button_click(self):
        if self.local_config.get("custom_background_path"):
            self.local_config["custom_background_path"] = ""
        else:
            filepath, _ = QFileDialog.getOpenFileName(self, tr("ui.select_background_image"), "", get_file_filter("background_images"))
            if not filepath: return
            self.local_config["custom_background_path"] = filepath
        self._write_local_config()
        self.apply_theme()
        self._update_background_button_state()


    def _update_background_button_state(self):
        background_disabled = self.local_config.get("background_disabled", False)
        self.change_background_button.setEnabled(not background_disabled)
        self.change_background_button.setText(tr("buttons.remove_background") if self.local_config.get("custom_background_path") else tr("buttons.change_background"))

    def _toggle_settings_view(self, show_changelog=False):
        if show_changelog:
            self.is_changelog_view = not self.is_changelog_view
        else:
            self.is_settings_view = not self.is_settings_view
            if not self.is_settings_view:
                if self.is_save_manager_view:
                    self._on_configure_saves_click() # Hide save manager
                if self.is_changelog_view:
                    self.is_changelog_view = False

        if self.is_settings_view:
            # Фиксируем размер окна на время отображения страниц настроек/справки/чейнджлога
            self._lock_window_size()
            self.settings_button.setText(tr("ui.back_button"))
            self.chapter_btn_widget.setVisible(False)
            self.tab_widget.setVisible(False)
            self.bottom_widget.setVisible(False)
            self.settings_widget.setVisible(True)
            self._switch_settings_page(self.settings_menu_page)
            self._update_settings_page_visibility()
            self._load_custom_style_settings()
            self._update_status(tr("status.launcher_settings"), UI_COLORS["status_info"])
        else:
            # Снимаем фиксацию размера при выходе из настроек
            self._unlock_window_size()
            self.settings_button.setText(tr("ui.settings_title"))
            self.apply_theme()
            self.settings_widget.setVisible(False)
            self.main_tab_widget.setVisible(True)
            self.bottom_widget.setVisible(True)

            # Принудительно обновляем отображение
            self.update()
            self.repaint()

            self._update_ui_for_selection()

    def _toggle_changelog_view(self):
        self._toggle_settings_view(show_changelog=True)

    def _toggle_help_view(self):
        """Переключает вид помощи"""
        self.is_help_view = not self.is_help_view

        # Если переходим в режим помощи, отключаем changelog
        if self.is_help_view and self.is_changelog_view:
            self.is_changelog_view = False

        # Если переходим в режим помощи, загружаем содержимое
        if self.is_help_view:
            self._load_help_content()

        self._update_settings_page_visibility()

    def _load_help_content(self):
        """Загружает содержимое помощи с сервера"""
        manager = get_localization_manager()
        current_language = manager.get_current_language() if manager else 'en'

        if current_language == 'ru':
            help_url = self.global_settings.get("help_ru_url", self.global_settings.get("help_url", ""))
        else:
            help_url = self.global_settings.get("help_en_url", self.global_settings.get("help_url", ""))

        if not help_url:
            self.help_text_edit.setMarkdown(f"<i>{tr('dialogs.help_not_available')}</i>")
            return

        # Показываем индикатор загрузки
        self.help_text_edit.setMarkdown(f"<i>{tr('status.loading')}</i>")

        self.help_thread = FetchHelpContentThread(help_url.strip(), self)
        self.help_thread.finished.connect(self._on_help_content_loaded)
        self.help_thread.start()

    def _on_help_content_loaded(self, content: str):
        self.help_text_edit.setMarkdown(content)

    def _update_settings_page_visibility(self):
        is_changelog = self.is_changelog_view
        is_help = self.is_help_view

        # Только одна страница может быть видимой одновременно
        self.settings_pages_container.setVisible(not is_changelog and not is_help)
        self.changelog_widget.setVisible(is_changelog)
        self.help_widget.setVisible(is_help)

        # Обновляем текст кнопок
        self.changelog_button.setText(
            tr("buttons.changelog_close") if is_changelog else tr("buttons.changelog")
        )
        self.help_button.setText(
            tr("buttons.changelog_close") if is_help else tr("buttons.help")
        )

        # Обновляем статус
        if is_changelog:
            self._update_status(tr("status.changelog"), UI_COLORS["status_info"])
        elif is_help:
            self._update_status(tr("dialogs.help_title"), UI_COLORS["status_info"])
        else:
            self._update_status(tr("status.launcher_settings"), UI_COLORS["status_info"])


    def _on_toggle_disable_background(self, state):
        is_disabled = bool(state)
        self.local_config["background_disabled"] = is_disabled
        self._write_local_config()
        self._update_background_button_state()
        self.apply_theme()
        self.update()

    def _on_toggle_disable_splash(self, state):
        is_disabled = bool(state)
        self.local_config["disable_splash"] = is_disabled
        self._write_local_config()

    def _is_valid_hex_color(self, s: str) -> bool:
        return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", s or ""))

    def _on_custom_style_edited(self):

        for key, widget in self.color_widgets.items():
            color = widget.text()
            config_key = f"custom_color_{key}"
            self.local_config[config_key] = color if self._is_valid_hex_color(color) else ""

        self._write_local_config()
        self.apply_theme()
        # Обновляем UI элементы, которые могли измениться
        self._update_dynamic_elements()

    def _on_volume_changed(self, value):
        """Регулировка громкости удалена."""
        return

    def _update_dynamic_elements(self):
        """Обновляет элементы UI, которые используют кастомизируемые цвета"""
        # Обновляем слоты
        if hasattr(self, 'slots'):
            self._update_slots_display()

        # Обновляем индикаторы глав
        self._update_chapter_indicators_style()

        # Обновляем фильтры, если они существуют
        if hasattr(self, 'sort_combo') and hasattr(self, 'sort_order_btn'):
            # Пересоздаем фильтры с новыми цветами
            search_tab = None
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabText(i) == tr("ui.search_tab"):
                    search_tab = self.tab_widget.widget(i)
                    break

            if search_tab:
                # Обновляем стили уже существующего виджета фильтров и его детей
                layout = search_tab.layout()
                if layout and layout.count() > 0:
                    item0 = layout.itemAt(0)
                    filters = item0.widget() if item0 is not None else None
                    if filters and filters.objectName() == "filters":
                        filter_bg_color = self.local_config.get("custom_color_background") or "rgba(0, 0, 0, 150)"
                        filter_border_color = self.local_config.get("custom_color_border") or "white"
                        element_bg_color = self.local_config.get("custom_color_button") or "black"
                        filters.setStyleSheet(f"QFrame#filters {{ background-color: {filter_bg_color}; border: 2px solid {filter_border_color}; padding: 8px; }}")
                elif layout:
                    # Если пустой, просто добавим фильтры
                    new_filters = self._create_filters_widget()
                    layout.addWidget(new_filters)

        # Обновляем плашки модов
        self._update_mod_plaques_styles()

    def _update_mod_plaques_styles(self):
        """Обновляет стили всех плашек модов"""
        # Обновляем плашки в поиске модов
        if hasattr(self, 'mod_list_widget') and self.mod_list_widget:
            layout = self.mod_list_widget.layout()
            if layout:
                for i in range(layout.count() - 1):  # -1 чтобы пропустить stretch
                    item = layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if isinstance(widget, ModPlaqueWidget):
                            widget._update_style()

        # Обновляем плашки в библиотеке
        if hasattr(self, 'installed_mods_widget') and self.installed_mods_widget:
            layout = self.installed_mods_widget.layout()
            if layout:
                for i in range(layout.count() - 1):  # -1 чтобы пропустить stretch
                    item = layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if isinstance(widget, InstalledModWidget):
                            widget._update_style()

    def _load_custom_style_settings(self):
        theme_defaults = THEMES["default"]
        for key, widget in self.color_widgets.items():
            config_key = f"custom_color_{key}"
            placeholder = theme_defaults["colors"].get(key, "#000000")
            widget.setText(self.local_config.get(config_key, ""))
            widget.setPlaceholderText(placeholder)
        self.apply_theme()

    def _load_launcher_icon(self):
        """Загружает иконку лаунчера для верхней панели"""
        try:
            splash_path = os.path.join(os.path.dirname(__file__), "assets", "splash.png")
            if os.path.exists(splash_path):
                pixmap = QPixmap(splash_path)
                if not pixmap.isNull():
                    # Keep aspect ratio but fill the label (cover) and crop center to avoid stretching
                    target_w, target_h = 200, 60
                    scaled_pixmap = pixmap.scaled(
                        target_w, target_h,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    # Crop to exact label size (center)
                    x = max(0, (scaled_pixmap.width() - target_w) // 2)
                    y = max(0, (scaled_pixmap.height() - target_h) // 2)
                    cropped = scaled_pixmap.copy(x, y, target_w, target_h)
                    self.launcher_icon_label.setFixedSize(target_w, target_h)
                    self.launcher_icon_label.setScaledContents(False)
                    self.launcher_icon_label.setPixmap(cropped)
                    return

        except Exception:
            pass

        # Если не удалось загрузить иконку, создаем заглушку
        target_w, target_h = 200, 60
        fallback_pixmap = QPixmap(target_w, target_h)
        fallback_pixmap.fill(QColor("#333"))
        self.launcher_icon_label.setFixedSize(target_w, target_h)
        self.launcher_icon_label.setScaledContents(False)
        self.launcher_icon_label.setPixmap(fallback_pixmap)

    def _get_background_music_path(self):
        """Возвращает путь к пользовательской фоновой музыке (только MP3) в папке конфигов.
        """
        # Сохраняем пользовательские файлы в конфиг‑папке, чтобы избежать проблем с правами
        dest = os.path.join(self.config_dir, "custom_background_music.mp3")
        if os.path.exists(dest):
            return dest
        # Фолбэк — встроенный MP3 ассет
        asset_mp3 = resource_path("assets/deltahub.wav")
        return dest if os.path.exists(dest) else (asset_mp3 if os.path.exists(asset_mp3) else "")

    def _get_startup_sound_path(self):
        """Получает путь к файлу звука заставки (только MP3) в папке конфигов"""
        return os.path.join(self.config_dir, "custom_startup_sound.mp3")

    def _get_background_music_button_text(self):
        """Возвращает текст для кнопки фоновой музыки"""
        # Кнопка должна отражать наличие ТОЛЬКО пользовательского файла в конфиг‑папке
        custom_exists = os.path.exists(os.path.join(self.config_dir, "custom_background_music.mp3"))
        return tr("buttons.remove_background_music") if custom_exists else tr("buttons.select_background_music")

    def _get_startup_sound_button_text(self):
        """Возвращает текст для кнопки звука заставки"""
        if os.path.exists(self._get_startup_sound_path()):
            return tr("buttons.remove_startup_sound")
        return tr("buttons.select_startup_sound")

    def _on_background_music_button_click(self):
        """Обработчик нажатия на кнопку фоновой музыки"""
        # Работает только с пользовательским файлом в конфиг‑папке
        custom_path = os.path.join(self.config_dir, "custom_background_music.mp3")

        if os.path.exists(custom_path):
            # Удаляем существующий файл
            try:
                self._stop_background_music()
                # Останавливаем воспроизведение и удаляем файл
                os.remove(custom_path)
                self.background_music_button.setText(self._get_background_music_button_text())
                QMessageBox.information(self, tr("dialogs.success"), tr("dialogs.background_music_removed"))
            except Exception as e:
                print(f"Error removing background music: {e}")
                QMessageBox.warning(self, tr("errors.error"), tr("errors.remove_background_music_failed"))
        else:
            # Выбираем новый файл
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                tr("dialogs.select_background_music"),
                "",
                "MP3 Files (*.mp3)"
            )

            if file_path:
                # Разрешаем только .mp3
                if not file_path.lower().endswith('.mp3'):
                    QMessageBox.warning(self, tr("errors.error"), "Можно выбрать только MP3 файл")
                    return
                try:
                    # Останавливаем фоновую музыку перед заменой
                    self._stop_background_music()
                    # Копируем в папку конфигов (строго в config_dir, а не в ассеты)
                    os.makedirs(self.config_dir, exist_ok=True)
                    dest_path = os.path.join(self.config_dir, "custom_background_music.mp3")
                    shutil.copy2(file_path, dest_path)
                    self.background_music_button.setText(self._get_background_music_button_text())
                    # Запускаем фоновую музыку
                    self._start_background_music()
                    QMessageBox.information(self, tr("dialogs.success"), tr("dialogs.background_music_selected"))
                except Exception as e:
                    print(f"Error copying background music: {e}")
                    QMessageBox.warning(self, tr("errors.error"), tr("errors.copy_background_music_failed"))

    def _on_startup_sound_button_click(self):
        """Обработчик нажатия на кнопку звука заставки (только MP3)"""
        custom_path = self._get_startup_sound_path()

        if os.path.exists(custom_path):
            # Удаляем существующий файл
            try:
                os.remove(custom_path)
                self.startup_sound_button.setText(self._get_startup_sound_button_text())
                QMessageBox.information(self, tr("dialogs.success"), tr("dialogs.startup_sound_removed"))
            except Exception as e:
                print(f"Error removing startup sound: {e}")
                QMessageBox.warning(self, tr("errors.error"), tr("errors.remove_startup_sound_failed"))
        else:
            # Выбираем новый файл (только MP3)
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                tr("dialogs.select_startup_sound"),
                "",
                "MP3 Files (*.mp3)"
            )

            if file_path:
                if not file_path.lower().endswith('.mp3'):
                    QMessageBox.warning(self, tr("errors.error"), "Можно выбрать только MP3 файл")
                    return
                try:
                    os.makedirs(self.config_dir, exist_ok=True)
                    shutil.copy2(file_path, custom_path)
                    self.startup_sound_button.setText(self._get_startup_sound_button_text())
                    QMessageBox.information(self, tr("dialogs.success"), tr("dialogs.startup_sound_selected"))
                except Exception as e:
                    print(f"Error copying startup sound: {e}")
                    QMessageBox.warning(self, tr("errors.error"), tr("errors.copy_startup_sound_failed"))

    def _start_background_music(self):
        """Запускает фоновую музыку через playsound3 в QThread (зациклено) с возможностью мгновенной остановки."""
        try:
            music_path = self._get_background_music_path()
            if not music_path or not os.path.exists(music_path):
                return

            # Останавливаем предыдущий цикл, если есть
            self._stop_background_music()

            from PyQt6.QtCore import QThread, pyqtSignal
            from playsound3 import playsound

            self._bg_music_running = True
            self._bg_music_instance = None

            class _MusicLoop(QThread):
                def __init__(self, outer, path):
                    super().__init__(); self.outer, self.path = outer, path
                def run(self):
                    while getattr(self.outer, '_bg_music_running', False):
                        try:
                            inst = playsound(self.path, block=False)
                            self.outer._bg_music_instance = inst
                            while getattr(self.outer, '_bg_music_running', False) and hasattr(inst, 'is_alive') and inst.is_alive():
                                time.sleep(0.05)
                            if not getattr(self.outer, '_bg_music_running', False):
                                try:
                                    if hasattr(inst, 'stop'):
                                        inst.stop()
                                except Exception:
                                    pass
                                break
                        except Exception:
                            # Более длительная пауза перед повтором, чтобы не грузить CPU
                            time.sleep(3)
                            continue

            self._bg_music_thread = _MusicLoop(self, music_path)
            self._bg_music_thread.start()
        except Exception as e:
            print(f"Error starting background music: {e}")

    def _handle_media_status_changed(self, status):
        """Больше не используется (QtMultimedia удалён). Оставлено для совместимости."""
        pass


    def _stop_background_music(self):
        """Останавливает фоновую музыку, запущенную через playsound3 (мгновенно)."""
        try:
            self._bg_music_running = False
            # Останавливаем активный инстанс playsound, если есть
            inst = getattr(self, "_bg_music_instance", None)
            if inst and hasattr(inst, 'is_alive'):
                try:
                    if inst.is_alive() and hasattr(inst, 'stop'):
                        inst.stop()
                except Exception:
                    pass
            self._bg_music_instance = None
            # Завершаем поток
            thr = getattr(self, "_bg_music_thread", None)
            if thr and thr.is_alive():
                thr.join(timeout=0.3)
            self._bg_music_thread = None
        except Exception as e:
            print(f"Error stopping background music: {e}")
        # Доп. очистка для старых fallback-механизмов
        try:
            if hasattr(self, 'bg_fallback_proc') and self.bg_fallback_proc:
                if self.bg_fallback_proc.poll() is None:
                    self.bg_fallback_proc.terminate()
            if platform.system() == "Windows":
                try:
                    import winsound
                    winsound.PlaySound(None, winsound.SND_PURGE)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            self.bg_fallback_proc = None

    def _on_toggle_direct_launch_for_slot(self, slot_id):
        """Включает прямой запуск для указанного слота"""
        if not self.game_mode.direct_launch_allowed:
            return

        # Проверяем совместимость с Steam и MacOS
        if self.local_config.get('launch_via_steam', False):
            QMessageBox.warning(
            self,
            tr("dialogs.incompatibility"),
            tr("dialogs.direct_launch_steam_incompatible")
            )
            return

        if platform.system() == "Darwin":
            QMessageBox.warning(
            self,
            tr("dialogs.incompatibility"),
            tr("dialogs.direct_launch_macos_incompatible")
            )
            return

        # Устанавливаем новый слот для прямого запуска
        self.local_config["direct_launch_slot_id"] = slot_id
        self._write_local_config()
        self._update_all_slots_visual_state()

        # Блокируем Steam галочку
        self.launch_via_steam_checkbox.setEnabled(False)

    def _disable_direct_launch(self):
        """Отключает прямой запуск"""
        self.local_config["direct_launch_slot_id"] = -1
        self._write_local_config()
        self._update_all_slots_visual_state()

        # Разблокируем Steam галочку после отключения прямого запуска
        self.launch_via_steam_checkbox.setEnabled(True)

    def _update_all_slots_visual_state(self):
        """Обновляет визуальное состояние всех слотов"""
        if hasattr(self, 'slots'):
            for slot in self.slots.values():
                self._update_slot_visual_state(slot)

    def _initialize_mutual_exclusions(self):
        """Инициализирует взаимные блокировки между Steam и прямым запуском."""
        is_direct_launch = self.local_config.get("direct_launch_slot_id", -1) >= 0

        # Если включен прямой запуск, блокируем Steam
        if is_direct_launch:
            self.launch_via_steam_checkbox.setEnabled(False)



    def _rebuild_tabs_for_demo_mode(self):
        self.tab_widget.blockSignals(True)

        while self.tab_widget.count():
            self.tab_widget.removeTab(0)
        self.tabs.clear()

        self.tabs[0] = self._create_chapter_tab(self._current_tab_names()[0], 0)

        for b in self._chapter_btns:
            b.deleteLater()
        self._chapter_btns.clear()

        try:
            old_grp = getattr(self, "chapter_button_group", None)
            if old_grp is not None:
                old_grp.deleteLater()
        except RuntimeError:
            pass

        self.chapter_button_group = QButtonGroup(self)
        self.chapter_button_group.setExclusive(True)

        for idx, title in enumerate(self._current_tab_names()):
            b = QPushButton(title)
            b.setCheckable(True)
            b.setMinimumWidth(100)
            self.chapter_button_group.addButton(b, idx)
            self._chapter_btns.append(b)
            self._chapter_btn_bar.addWidget(b)

        # Первая вкладка активна по умолчанию
        first_btn = self.chapter_button_group.button(0)
        if first_btn is not None:
            first_btn.setChecked(True)

        # Клик по кнопке  → переключаем вкладку
        self.chapter_button_group.idClicked.connect(self.tab_widget.setCurrentIndex)

        # Переключение вкладки колёсиком/клавиатурой → обновляем кнопки
        def _sync_chapter_buttons(index: int):
            for i, btn in enumerate(self._chapter_btns):
                old = btn.blockSignals(True)
                btn.setChecked(i == index)
                btn.blockSignals(old)
        self.tab_widget.currentChanged.connect(_sync_chapter_buttons)

        self._chapter_btn_bar.addWidget(self.full_install_checkbox)

        self._update_chapter_button_visibility()

        self.tab_widget.blockSignals(False)
        self.tab_widget.setCurrentIndex(0)
        self.tab_widget.currentChanged.emit(0)
        self.apply_theme()

    def _update_chapter_button_visibility(self):
        is_demo = isinstance(self.game_mode, DemoGameMode)
        for btn in self._chapter_btns:
            btn.setVisible(not is_demo)

        # Управляем видимостью чекбокса через его фрейм
        if hasattr(self, 'demo_checkbox_frame'):
            self.demo_checkbox_frame.setVisible(is_demo)



    def _perform_initial_setup(self):
        # Сначала загружаем глобальные настройки, они могут понадобиться для UI
        try:
            from helpers import _fb_url
            response = requests.get(_fb_url(DATA_FIREBASE_URL, "globals"), timeout=5)
            if response.status_code == 200:
                self.global_settings = response.json() or {}
        except requests.RequestException:
            self.update_status_signal.emit(tr("status.global_settings_load_failed"), UI_COLORS["status_warning"])

        # Обновляем URL в кнопках
        self.telegram_button.clicked.connect(lambda: webbrowser.open(self.global_settings.get("telegram_url", SOCIAL_LINKS["telegram"])))
        self.discord_button.clicked.connect(lambda: webbrowser.open(self.global_settings.get("discord_url", SOCIAL_LINKS["discord"])))

        # Запускаем загрузку списка изменений, используя локализованный URL из глобальных настроек
        manager = get_localization_manager()
        current_language = manager.get_current_language() if manager else 'en'

        if current_language == 'ru':
            changelog_url = self.global_settings.get("changelog_ru_url", self.global_settings.get("changelog_url"))
        else:
            changelog_url = self.global_settings.get("changelog_en_url", self.global_settings.get("changelog_url"))

        if changelog_url:
            changelog_thread = FetchChangelogThread(changelog_url.strip(), self)
            changelog_thread.finished.connect(self.changelog_text_edit.setMarkdown)
            changelog_thread.start()
        else:
            self.changelog_text_edit.setMarkdown(tr("status.changelog_load_failed"))

        self._check_and_manage_steam_deck_saves()

        if is_game_running():
            self.update_status_signal.emit(tr("status.deltarune_already_running"), UI_COLORS["status_error"])
            return

        self._load_local_data()
        self.game_path = self.local_config.get("game_path", "")
        self.demo_game_path = self.local_config.get("demo_game_path", "")

        # Загружаем сохраненные состояния галочек из конфига
        saved_demo_mode = self.local_config.get('demo_mode_enabled', False)
        saved_chapter_mode = self.local_config.get('chapter_mode_enabled', False)

        # Блокируем сигналы чтобы не было дублирования обработчиков
        self.demo_mode_checkbox.blockSignals(True)
        if hasattr(self, 'chapter_mode_checkbox'):
            self.chapter_mode_checkbox.blockSignals(True)

        self.demo_mode_checkbox.setChecked(saved_demo_mode)
        if hasattr(self, 'chapter_mode_checkbox'):
            self.chapter_mode_checkbox.setChecked(saved_chapter_mode)
        self.disable_background_checkbox.setChecked(self.local_config.get("background_disabled", False))
        self.disable_splash_checkbox.setChecked(self.local_config.get("disable_splash", False))

        # Разблокируем сигналы
        self.demo_mode_checkbox.blockSignals(False)
        if hasattr(self, 'chapter_mode_checkbox'):
            self.chapter_mode_checkbox.blockSignals(False)

        # Режимы уже применены при создании вкладок, не нужно их вызывать снова

        self._update_change_path_button_text()
        self._update_background_button_state()
        self._migrate_config_if_needed()
        self.use_custom_executable_checkbox.setChecked(self.local_config.get("use_custom_executable", False))
        self.launch_via_steam_checkbox.setChecked(self.local_config.get("launch_via_steam", False))

        # Инициализируем взаимные блокировки между Steam и прямым запуском
        self._initialize_mutual_exclusions()

        self._on_toggle_steam_launch()

        # Обновляем визуальное состояние слотов для отображения прямого запуска
        self._update_all_slots_visual_state()

        self.apply_theme()

        self._load_all_translations_from_folders()
        self.setEnabled(False)

        self._refresh_translations(force=True, blocking=False)
        self.setEnabled(True)

        self._populate_ui_with_mods()
        if not self._find_and_validate_game_path():
            self.action_button.setEnabled(False)
        # Убираем прямой вызов initialization_finished.emit(), теперь ждем загрузки модов

    def _check_and_manage_steam_deck_saves(self):
        if platform.system() != "Linux":
            return
        try:
            home_dir = os.path.expanduser('~')
            native_save_path = os.path.join(home_dir, ".config", "DELTARUNE")
            proton_save_path = os.path.join(home_dir, ".steam", "steam", "steamapps", "compatdata", "1671210", "pfx", "drive_c", "users", "steamuser", "AppData", "Local", "DELTARUNE")
            if not os.path.isdir(proton_save_path):
                return
            if os.path.lexists(native_save_path):
                if os.path.islink(native_save_path) and os.readlink(native_save_path) == proton_save_path:
                    return
                if os.path.isdir(native_save_path) and not os.listdir(native_save_path):
                    os.rmdir(native_save_path)
                else:
                    backup_path = f"{native_save_path}_backup_{int(time.time())}"
                    os.rename(native_save_path, backup_path)
                    QMessageBox.information(self, tr("dialogs.backup"), tr("dialogs.backup_created_for_steam_deck", backup_path=backup_path))
            os.symlink(proton_save_path, native_save_path)
            QMessageBox.information(self, tr("dialogs.steam_deck_setup"), tr("dialogs.steam_deck_compatibility_configured"))
        except Exception as e:
            print(tr("startup.steam_deck_setup_error", error=str(e)))

    def _get_pending_installations(self):
        pending = []
        # Collect all unique selected mods
        for ui_idx in range(self.tab_widget.count()):
            info = self._get_selected_mod_info(ui_idx)
            if info and not info.key.startswith("local_"):  # Пропускаем локальные моды
                if getattr(info, 'ban_status', False): continue  # Пропускаем заблокированные моды
                chapter_id = self.game_mode.get_chapter_id(ui_idx)
                status = self._get_mod_status_for_chapter(info, chapter_id)
                if status in ("install", "update"):
                    if not any(p[0].key == info.key and p[1] == chapter_id for p in pending):
                        pending.append((info, chapter_id, status))  # Добавляем статус
        return pending

    def _count_pending_by_type(self):
        """Возвращает количество установок и обновлений отдельно."""
        pending = self._get_pending_installations()
        install_count = sum(1 for _, _, status in pending if status == "install")
        update_count = sum(1 for _, _, status in pending if status == "update")
        return install_count, update_count

    def _get_platform_string(self) -> str:
        system = platform.system()
        if system == "Windows":
            return "setup"
        elif system == "Darwin":
            # включаем архитектуру, чтобы отличать arm64/x86_64 мяу:)
            return f"macOS-{ARCH}"
        else:
            return "Linux"

    def _check_for_launcher_updates(self):
        try:
            launcher_files = self.global_settings.get("launcher_files")
            if not isinstance(launcher_files, dict):
                self.update_status_signal.emit(tr("status.update_info_not_found"), UI_COLORS["status_warning"])
                return
            remote_version = launcher_files.get("version")
            if not remote_version or version_parser.parse(remote_version) <= version_parser.parse(LAUNCHER_VERSION):
                self.update_status_signal.emit(tr("status.launcher_version_up_to_date"), UI_COLORS["status_success"])
                return

            platform_key_map = {
                "Windows": "windows",
                "Linux": "linux",
                "Darwin": f"macos-{ARCH}"
            }
            current_platform_key = platform_key_map.get(platform.system())
            download_url = launcher_files.get("urls", {}).get(current_platform_key)
            update_message = launcher_files.get("message", tr("dialogs.new_version_available_simple"))
            # Новое: поддержка мультиязычных сообщений, если они есть в globals.json
            update_message_ru = launcher_files.get("message_ru")
            update_message_en = launcher_files.get("message_en")

            if not download_url:
                self.update_status_signal.emit(tr("errors.no_build_for_os", platform=current_platform_key), UI_COLORS["status_warning"])
                return

            # Собираем payload с возможными языковыми вариантами
            update_info = {
                "version": remote_version,
                "url": download_url,
                "message": update_message,
                "message_ru": update_message_ru,
                "message_en": update_message_en,
            }

            # Передаем информацию об обновлении в основной поток через сигнал
            self.update_info_ready.emit(update_info)

        except requests.RequestException as e:
            self.update_status_signal.emit(tr("errors.update_check_network_error", error=str(e)), UI_COLORS["status_error"])
        except Exception as e:
            self.update_status_signal.emit(tr("errors.update_check_general_error", error=str(e)), UI_COLORS["status_error"])

    def _handle_update_info(self, update_info):
        """Обработчик информации об обновлении в основном потоке"""
        # Проверяем что инициализация завершена И лаунчер показан пользователю
        if self.initialization_completed and getattr(self, 'is_shown_to_user', False):
            self.show_update_prompt.emit(update_info)
        else:
            # Если инициализация не завершена или лаунчер не показан, откладываем показ обновления
            QTimer.singleShot(1000, lambda: self._handle_update_info(update_info))

    def _maybe_run_legacy_cleanup(self):
        """Runs legacy YLauncher folder cleanup once after the window is shown and init is done."""
        if self._legacy_cleanup_done:
            return
        if self.initialization_completed and getattr(self, 'is_shown_to_user', False):
            self._cleanup_legacy_ylauncher_folder()
            self._legacy_cleanup_done = True
        else:
            QTimer.singleShot(1000, self._maybe_run_legacy_cleanup)

    def _cleanup_legacy_ylauncher_folder(self):
        try:
            legacy_path = get_legacy_ylauncher_path()
            if legacy_path and os.path.isdir(legacy_path):
                try:
                    shutil.rmtree(legacy_path, ignore_errors=True)
                except Exception:
                    # Ignore errors; folder may be locked or partially removed
                    pass
                # Notify user about settings changes and need to reconfigure
                QMessageBox.information(
                    self,
                    tr("dialogs.legacy_cleanup_title"),
                    tr("dialogs.legacy_cleanup_message")
                )
        except Exception:
            # Silent fail
            pass

    def _prompt_for_update(self, update_info):
        if self.update_in_progress:
            return
        self.update_in_progress = True

        update_message = (tr("dialogs.new_version_banner", version=update_info['version']) +
                          tr("dialogs.current_version_banner", current_version=LAUNCHER_VERSION))

        # Выбираем сообщение в зависимости от текущего языка
        manager = get_localization_manager()
        current_language = manager.get_current_language() if manager else 'en'

        if current_language == 'ru':
            message_text = update_info.get('message_ru') or update_info.get('message', '')
        else:
            message_text = update_info.get('message_en') or update_info.get('message', '')

        update_message += f"<b>{tr('dialogs.whats_new')}</b><br>{message_text}<br><br>"

        update_message += (tr("dialogs.want_download_install_now") +
                         tr("dialogs.app_will_restart"))
        reply = QMessageBox.question(self, tr("status.update_available"), update_message)

        if reply == QMessageBox.StandardButton.Yes:
            self._perform_update(update_info)
        else:
            self.update_in_progress = False
            self.update_status_signal.emit(tr("status.update_rejected"), UI_COLORS["status_info"])

    def _perform_update(self, update_info):
        for widget in [self.action_button, self.saves_button, self.shortcut_button, self.change_path_button, self.change_background_button]:
            widget.setEnabled(False)
        self.settings_button.setEnabled(False)
        for btn in self.chapter_button_group.buttons(): btn.setDisabled(True)
        if not self.is_settings_view:
            self.tab_widget.setEnabled(False)

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        threading.Thread(target=self._update_worker, args=(update_info,), daemon=True).start()

    def _update_worker(self, update_info):
        try:
            with tempfile.TemporaryDirectory(prefix="deltahub-update-") as tmp_dir:
                archive_path = os.path.join(tmp_dir, "update" + os.path.splitext(update_info['url'].split('?')[0])[1])
                self.update_status_signal.emit(tr("status.downloading_version", version=update_info['version']), UI_COLORS["status_warning"])

                response = requests.get(update_info['url'], stream=True, timeout=60)
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))

                with open(archive_path, "wb") as f:
                    downloaded_size = 0
                    for data in response.iter_content(chunk_size=8192):
                        f.write(data)
                        downloaded_size += len(data)
                        if total_size > 0:
                            self.set_progress_signal.emit(int((downloaded_size / total_size) * 100))

                self.update_status_signal.emit(tr("status.unpacking_and_installing"), UI_COLORS["status_warning"])
                system = platform.system()

                extraction_dir = os.path.join(tmp_dir, "extracted")
                os.makedirs(extraction_dir, exist_ok=True)

                # Универсальная распаковка архива
                from helpers import _extract_archive
                _extract_archive(archive_path, extraction_dir, os.path.basename(archive_path))

                if system == "Windows":
                    # Ищем .exe в распакованной папке
                    new_exe_path = next(
                        (os.path.join(root, f)
                        for root, _, files in os.walk(extraction_dir)
                        for f in files if f.lower().endswith('.exe')),
                        None
                    )
                    if not new_exe_path:
                        raise RuntimeError(tr("errors.exe_not_found_in_archive"))
                    ctypes.windll.shell32.ShellExecuteW(None, "runas", new_exe_path, None, None, 1)
                    QTimer.singleShot(500, self.close)
                    return

                current_exe_path = os.path.realpath(sys.executable)
                replace_target = (
                    os.path.abspath(os.path.join(os.path.dirname(current_exe_path), "..", ".."))
                    if system == "Darwin" else current_exe_path
                )
                backup_path = f"{replace_target}.old"

                if system == "Darwin":
                    if archive_path.lower().endswith('.zip'):
                        subprocess.run(["/usr/bin/ditto", "-x", "-k", archive_path, extraction_dir], check=True)
                    new_content_path = next(
                        (os.path.join(extraction_dir, d) for d in os.listdir(extraction_dir) if d.endswith('.app')),
                        None
                    )
                    if new_content_path is None:
                        raise RuntimeError(tr("errors.app_not_found_after_unpack"))
                    fix_macos_python_symlink(Path(new_content_path))
                else:
                    # Linux — ищем первый исполняемый файл
                    new_content_path = next(
                        (os.path.join(root, file)
                        for root, _, files in os.walk(extraction_dir)
                        for file in files
                        if os.path.isfile(os.path.join(root, file)) and os.access(os.path.join(root, file), os.X_OK)),
                        None
                    )
                    if new_content_path is None or not os.path.exists(new_content_path):
                        raise RuntimeError(tr("errors.executable_not_found_after_unpack"))
                    os.chmod(new_content_path, 0o755)

                if os.path.exists(backup_path):
                    shutil.rmtree(backup_path, ignore_errors=True)

                os.rename(replace_target, backup_path)
                if system == "Darwin":
                    shutil.copytree(new_content_path, replace_target)
                else:
                    shutil.move(new_content_path, replace_target)

                self.update_status_signal.emit(tr("status.restarting"), UI_COLORS["status_success"])
                os.execv(current_exe_path, sys.argv)

            if not self.is_settings_view:
                self.tab_widget.setEnabled(True)
            for w in (self.action_button, self.shortcut_button,
                    self.delete_button, self.change_path_button,
                    self.change_background_button):
                w.setEnabled(True)
            self.progress_bar.setVisible(False)
            self.update_in_progress = False
            self.update_status_signal.emit(
                tr("status.update_cancelled_check_permissions"),
                UI_COLORS["status_warning"])
        except PermissionError:
            self.update_status_signal.emit(tr("errors.update_permission_error"), UI_COLORS["status_error"])
            self.error_signal.emit(tr("dialogs.update_permission_error_details"))
        except Exception as e:
            self.update_status_signal.emit(tr("errors.update_failed", error=str(e)), UI_COLORS["status_error"])
            self.error_signal.emit(tr("errors.update_could_not_complete", error=str(e)))
        finally:
            self.progress_bar.setVisible(False)
            if not self.is_settings_view:
                self.tab_widget.setEnabled(True)
                self._update_ui_for_selection()
            self.settings_button.setEnabled(True)
            for btn in self.chapter_button_group.buttons():
                btn.setDisabled(False)
            for widget in [self.shortcut_button, self.change_path_button, self.change_background_button]:
                widget.setEnabled(True)
            self.update_in_progress = False

    def _on_action_button_click(self):
        # Если идет установка, то это кнопка отмены
        if self.is_installing and self.current_install_thread:
            # Устанавливаем флаг отмены — поток сам завершится, а очистку выполним в обработчике finished
            self._operation_cancelled = True
            self.update_status_signal.emit(tr("status.operation_cancelled"), UI_COLORS["status_error"])
            # Скрываем прогресс немедленно, чтобы не было ощущения продолжения скачивания
            try:
                self.progress_bar.setValue(0)
                self.progress_bar.setVisible(False)
            except Exception:
                pass
            # Не сбрасываем UI и не инвалидируем сигналы — дождемся корректного завершения потока
            try:
                self.current_install_thread.cancel()
            except Exception:
                pass
            return

        if isinstance(self.game_mode, DemoGameMode) and getattr(self, "full_install_checkbox", None) is not None \
                and self.full_install_checkbox.isChecked():
            self._perform_full_install()
            return

        # Не запускаем новые операции если уже идет установка
        if self.is_installing:
            return

        # Проверяем, нужно ли обновление модов в слотах
        if self._check_active_slots_need_updates():
            self._update_mods_in_active_slots()
            return

        self._handle_modded_action()

    def _handle_modded_action(self):
        # Не выполняем действия если операция была отменена
        if getattr(self, '_operation_cancelled', False):
            return

        self.action_button.setEnabled(False)
        self.saves_button.setEnabled(False)

        # Сразу показываем статус подготовки, если есть файлы для установки
        needs_install = bool(self._get_pending_installations())
        if needs_install:
            self.update_status_signal.emit(tr("status.preparing_download"), UI_COLORS["status_warning"])

        # --- Проверка целостности модов перед действием ---
        all_selections = [mod for mod in [self._get_selected_mod_info(i) for i in range(self.tab_widget.count())] if mod]
        mods_to_cleanup = []
        for mod in all_selections:
            mod_config = self._get_mod_config_by_key(mod.key)
            if mod_config:
                # Если мод есть в списке установленных, проверяем наличие его папки
                mod_name_from_config = mod_config.get("name", mod.name)
                sanitized_name = sanitize_filename(mod_name_from_config)
                mod_cache_dir = os.path.join(self.mods_dir, sanitized_name)
                if not os.path.isdir(mod_cache_dir):
                    mods_to_cleanup.append(mod)

        if mods_to_cleanup:
            mod_names = ", ".join([m.name for m in mods_to_cleanup])
            QMessageBox.warning(self, tr("dialogs.inconsistencies_detected_title"),
            tr("dialogs.missing_mod_files_message", mod_names=mod_names))
            for mod in mods_to_cleanup:
                # Удаляем конфиг мода, если его папка не найдена
                pass  # Пока не удаляем - пусть система сама перескачает
            self._populate_ui_with_mods() # Обновляем UI, чтобы показать изменения
            # Пересчитываем после очистки кэша
            needs_install = bool(self._get_pending_installations())
        if needs_install:
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self._install_translations()
        else:
            self.progress_bar.setVisible(False)
            self._launch_game_with_all_mods()

    def _refresh_translations(self, force=False, blocking=False):
        if is_game_running():
            self.update_status_signal.emit(tr("status.cant_update_while_running"), UI_COLORS["status_warning"])
            return

        self._stop_fetch_thread()

        threading.Thread(target=self._check_for_launcher_updates, daemon=True).start()

        self.fetch_thread = FetchTranslationsThread(self, force_update=force)
        self.fetch_thread.status.connect(self.update_status_signal)
        self.fetch_thread.result.connect(self._on_fetch_translations_finished)

        if blocking:
            loop = QEventLoop()
            self.fetch_thread.finished.connect(loop.quit)
            self.fetch_thread.start()
            loop.exec()
        else:
            self.fetch_thread.start()

    def _stop_fetch_thread(self):
        self._safe_stop_thread(getattr(self, "fetch_thread", None))
        self.fetch_thread = None

    # ---------- Новый универсальный помощник ----------
    def _safe_stop_thread(self, thr: Optional[QThread], timeout: int = 2_000):
        if isinstance(thr, QThread) and thr.isRunning():
            thr.requestInterruption(); thr.quit()
            if not thr.wait(timeout): thr.terminate(); thr.wait()

    def _stop_presence_thread(self):
        self._safe_stop_thread(getattr(self, "presence_thread", None))
        self.presence_thread = None
        self.presence_worker = None

    def _on_fetch_translations_finished(self, success: bool):

        try:
            # Перезагружаем локальные моды после обновления удаленных
            self._load_local_mods_from_folders()
            self._populate_ui_with_mods()

            # Обновляем новую систему поиска модов
            if hasattr(self, 'mod_list_layout'):
                self._populate_search_mods()
                # Уведомляем о загрузке модов только один раз
                if not self.mods_loaded:
                    self.mods_loaded = True
                    self.mods_loaded_signal.emit()

            # Обновляем библиотеку модов с новыми статусами доступности
            if hasattr(self, 'installed_mods_layout'):
                self._update_installed_mods_display()

            # Обновляем объекты модов в слотах с новыми данными
            self._refresh_mods_in_slots()

            # Обновляем отображение слотов с новыми статусами
            self._refresh_slots_content()

            # Принудительно обновляем проверку слотов после загрузки данных

            self._update_ui_for_selection()

            if success:
                self.update_status_signal.emit(tr("status.mod_list_updated"), UI_COLORS["status_success"])
            else:
                fallback_msg = tr("ui.network_fallback_message") if self.all_mods else tr("ui.network_update_failed")
                self.update_status_signal.emit(fallback_msg, UI_COLORS["status_error"])
        except Exception as e:
            self.update_status_signal.emit(tr("errors.mod_list_processing_error", error=str(e)), UI_COLORS["status_error"])

    def _refresh_mods_in_slots(self):
        """Обновляет объекты модов в слотах с новыми данными из all_mods"""

        if not hasattr(self, 'slots') or not self.all_mods:
            return

        for slot_frame in self.slots.values():
            if slot_frame.assigned_mod:
                old_mod = slot_frame.assigned_mod
                mod_key = getattr(old_mod, 'key', None) or getattr(old_mod, 'mod_key', None)


                # Найти обновленный объект мода в all_mods
                for updated_mod in self.all_mods:
                    updated_mod_key = getattr(updated_mod, 'key', None) or getattr(updated_mod, 'mod_key', None)
                    if updated_mod_key == mod_key:

                        slot_frame.assigned_mod = updated_mod
                        break

        # После обновления данных модов, обновляем их статус отображения в слотах
        self._refresh_all_slot_status_displays()

    def _has_internet_connection(self) -> bool:
        try: requests.head("https://clients3.google.com/generate_204", timeout=3); return True
        except requests.RequestException: return False

    def _install_translations(self):
        # Строгая проверка - блокируем если уже идет установка
        if self.is_installing:

            return

        mods_to_install = self._get_pending_installations()
        if not mods_to_install:
            self.progress_bar.setVisible(False)
            self._update_ui_for_selection()
            return
        # Преобразуем формат данных для InstallTranslationsThread (убираем статус)
        install_tasks = [(mod, chapter_id) for mod, chapter_id, status in mods_to_install]

        # Устанавливаем состояние установки
        self.is_installing = True
        self._set_install_buttons_enabled(False)  # Блокируем все кнопки установки
        self.action_button.setText(tr("ui.cancel_button"))  # Меняем текст кнопки на "Отменить"
        self.current_install_thread = InstallTranslationsThread(self, install_tasks)
        self.install_thread = self.current_install_thread  # Для совместимости

        self.install_thread.progress.connect(self.set_progress_signal)
        self.install_thread.status.connect(self.update_status_signal)
        self.install_thread.finished.connect(self._on_install_finished)

        # Обновляем UI чтобы показать кнопку отмены
        self._update_ui_for_selection()

        self.install_thread.start()

    def _on_install_finished(self, success):
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        # Очистка временной папки при отмене/ошибке
        if not success:
            try:
                thr = self.current_install_thread
                temp_root = getattr(thr, 'temp_root', None)
                if temp_root and os.path.isdir(temp_root):
                    shutil.rmtree(temp_root, ignore_errors=True)
            except Exception:
                pass
        self.is_installing = False
        self._set_install_buttons_enabled(True)  # Разблокируем все кнопки установки
        self.current_install_thread = None
        if success:
            # Перезагружаем моды из config.json файлов
            self._load_local_mods_from_folders()
            self.update_status_signal.emit(tr("status.installation_complete"), UI_COLORS["status_success"])
            self._populate_ui_with_mods()
        self._update_ui_for_selection()
        if hasattr(self, 'full_install_checkbox') and self.full_install_checkbox is not None and isinstance(self.game_mode, DemoGameMode):
            self.full_install_checkbox.setEnabled(True)
        self._update_ui_for_selection()

    def _perform_full_install(self):
        # Строгая проверка - блокируем если уже идет установка
        if self.is_installing:

            return

        # Проверяем что не идет уже полная установка
        if hasattr(self, 'full_install_thread') and self.full_install_thread and self.full_install_thread.isRunning():

            return

        self.action_button.setEnabled(False)
        self.saves_button.setEnabled(False)
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("dialogs.full_demo_install"))
        v = QVBoxLayout(dlg)
        lbl = QLabel(self._full_install_tooltip())
        lbl.setWordWrap(True)
        v.addWidget(lbl)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.action_button.setEnabled(True)
            return

        base_dir = QFileDialog.getExistingDirectory(self, tr("dialogs.install_demo_location"))
        if not base_dir:
            self.action_button.setEnabled(True)
            return
        target_dir = os.path.join(base_dir, "DELTARUNEdemo")
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as e:
            self.error_signal.emit(tr("errors.folder_creation_failed", error=str(e)))
            self.action_button.setEnabled(True)
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.full_install_thread = FullInstallThread(self, target_dir, False)
        self.full_install_thread.progress.connect(self.set_progress_signal)
        self.full_install_thread.progress.connect(self.progress_bar.setValue)
        self.full_install_thread.status.connect(self.update_status_signal)
        self.full_install_thread.progress.connect(self.progress_bar.setValue)
        self.full_install_thread.finished.connect(self._on_full_install_finished)
        self.full_install_thread.start()

    def _on_full_install_finished(self, success, target_dir):
        self.progress_bar.setVisible(False)
        # Отключаем чекбокс полной установки
        self.full_install_checkbox.blockSignals(True)
        self.progress_bar.setValue(0)
        self.full_install_checkbox.setChecked(False)
        self.full_install_checkbox.blockSignals(False)

        if success:
            # Устанавливаем новую папку демо как активную папку игры
            if isinstance(self.game_mode, DemoGameMode):
                self.demo_game_path = target_dir
                self.local_config["demo_game_path"] = target_dir
            else:
                self.game_path = target_dir
                self.local_config["game_path"] = target_dir

            self._write_local_config()
            self.update_status_signal.emit(tr("status.game_files_install_complete"), UI_COLORS["status_success"])

            # Обновляем UI и выходим
            self._update_ui_for_selection()
            return
        else:
            self.update_status_signal.emit(tr("status.game_files_install_failed"), UI_COLORS["status_error"])

        self._write_local_config()
        self._update_ui_for_selection()

    def _run_as_admin_windows(self, path: str) -> bool:
        script = f"import os, stat; p = r'{path}'; [os.chmod(os.path.join(r, f), os.stat(os.path.join(r, f)).st_mode | stat.S_IWRITE) for r, _, fs in os.walk(p) for f in fs] if os.path.isdir(p) else os.chmod(p, os.stat(p).st_mode | stat.S_IWRITE) if os.path.exists(p) else None"
        command = f'Start-Process python -ArgumentList "-c \\"{script}\\"" -Verb RunAs -WindowStyle Hidden'
        try:
            subprocess.run(["powershell", "-Command", command], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.update_status_signal.emit(tr("status.permission_change_failed"), UI_COLORS["status_error"])
            return False

    def _get_xdelta_chapters(self, source_dir: str, mod_info) -> List[int]:
        """Возвращает список глав, для которых есть xdelta файлы в этом моде."""
        available_chapters = []

        # Для публичных модов с флагом is_piracy_protected нужно проверить данные главы
        if mod_info and getattr(mod_info, 'is_piracy_protected', False):
            # Проверяем какие главы есть у мода в данных
            for chapter_id in range(-1, 5):  # -1 для демо, 0-4 для глав
                if chapter_id == -1:  # Демо
                    if mod_info.is_valid_for_demo():
                        available_chapters.append(chapter_id)
                else:  # Обычные главы
                    if mod_info.get_chapter_data(chapter_id):
                        available_chapters.append(chapter_id)
        else:
            # Для локальных модов ищем .xdelta файлы в папках
            # Проверяем корневую папку
            for file in os.listdir(source_dir):
                if file.lower().endswith('.xdelta'):
                    available_chapters.append(0)  # Считаем корневую папку как главу 0
                    break

            # Проверяем подпапки глав
            for chapter_id in range(-1, 5):
                if chapter_id == -1:  # Демо
                    demo_dir = os.path.join(source_dir, "demo")
                    if os.path.isdir(demo_dir):
                        for file in os.listdir(demo_dir):
                            if file.lower().endswith('.xdelta'):
                                available_chapters.append(chapter_id)
                                break
                elif chapter_id == 0:  # Меню
                    chapter_dir = os.path.join(source_dir, "chapter_0")
                    if os.path.isdir(chapter_dir):
                        for file in os.listdir(chapter_dir):
                            if file.lower().endswith('.xdelta'):
                                available_chapters.append(chapter_id)
                                break
                else:  # Главы 1-4
                    chapter_dir = os.path.join(source_dir, f"chapter_{chapter_id}")
                    if os.path.isdir(chapter_dir):
                        for file in os.listdir(chapter_dir):
                            if file.lower().endswith('.xdelta'):
                                available_chapters.append(chapter_id)
                                break

        return list(set(available_chapters))  # Убираем дубликаты

    def _prepare_game_files(self, selections: Dict[int, str]) -> bool:
        """Копирует файлы модов (публичных или локальных) в игровые директории."""
        try:
            applied_chapters = set()
            all_mods_combined = self.all_mods + self._get_local_mods_as_modinfo()

            for ui_index, mod_key in selections.items():
                if mod_key == "no_change":
                    continue

                chapter_id = self.game_mode.get_chapter_id(ui_index)

                # Ищем мод в общем списке
                mod = next((m for m in all_mods_combined if m.key == mod_key), None)
                if not mod:
                    continue

                # Определяем, локальный ли это мод
                is_local = mod_key.startswith("local_")

                # Определяем источник файлов
                mod_config = self._get_mod_config_by_key(mod.key)
                folder_name = sanitize_filename(mod.name)
                source_dir = os.path.join(self.mods_dir, folder_name)

                if not os.path.isdir(source_dir):
                    self.update_status_signal.emit(tr("errors.mod_folder_not_found", mod_name=mod.name, path=source_dir), UI_COLORS["status_warning"])
                    continue

                mod_type_str = tr("ui.mod_type_local") if is_local else tr("ui.mod_type_public")
                self.update_status_signal.emit(tr("status.applying_mod", mod_name=mod.name, mod_type=mod_type_str), UI_COLORS["status_warning"])


                # --- ИСПРАВЛЕНИЕ: Унифицированная логика для ВСЕХ модов ---
                # Теперь и xdelta, и обычные моды обрабатываются одинаково,
                # применяясь только к той главе, для которой они были выбраны в интерфейсе.

                if chapter_id in applied_chapters:
    
                    continue

                # Проверяем, является ли это xdelta модом (нужно для след. шага)
                is_xdelta_mod = self._is_xdelta_mod(mod, source_dir, chapter_id)

                # Пропускаем главы без файлов (для обычных модов)
                # Для xdelta модов эта проверка не нужна, т.к. наличие патча проверяется позже
                if not is_xdelta_mod and not mod.get_chapter_data(chapter_id) and not is_local:

                    continue
                
                target_dir = self._get_target_dir(chapter_id)
                if not target_dir:
                    continue

                if not ensure_writable(target_dir):
                    raise PermissionError(tr("errors.no_write_permission_for", path=target_dir))

                # Вызываем _create_backup_and_copy_mod_files для ОДНОЙ конкретной главы
                if not self._create_backup_and_copy_mod_files(source_dir, target_dir, chapter_id, mod):
                    return False
                
                applied_chapters.add(chapter_id)
                # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

            return True
        except PermissionError as e:
            path = e.filename or (e.args[0] if e.args else tr("errors.unknown_path"))
            if not self.is_shortcut_launch: self._handle_permission_error(path)
            return False
        except Exception as e:
            self.error_signal.emit(tr("errors.file_prep_error", error=str(e)))
            return False

    def _is_xdelta_mod(self, mod_info, source_dir: str, chapter_id: Optional[int] = None) -> bool:
        """Определяет, является ли мод xdelta-модом (для локальных и публичных модов)."""
        # Для публичных модов проверяем флаг is_piracy_protected
        if mod_info and getattr(mod_info, 'is_piracy_protected', False):
            return True

        # Для локальных модов ищем .xdelta файлы в папке конкретной главы
        # ВАЖНО: не используем корневую папку как fallback для глав > 0, иначе патч меню попадет в главы
        if chapter_id is not None:
            search_dir = None
            if chapter_id == -1:  # Демо
                demo_dir = os.path.join(source_dir, "demo")
                if os.path.isdir(demo_dir):
                    search_dir = demo_dir
                else:
                    # Для демо допускаем патч из корня мода
                    search_dir = source_dir
            elif chapter_id == 0:  # Меню
                menu_dir = os.path.join(source_dir, "chapter_0")
                if os.path.isdir(menu_dir):
                    search_dir = menu_dir
                else:
                    # Для меню разрешаем искать патч в корне мода
                    search_dir = source_dir
            else:  # Главы 1-4
                chapter_dir = os.path.join(source_dir, f"chapter_{chapter_id}")
                if os.path.isdir(chapter_dir):
                    search_dir = chapter_dir
            # Если специальной папки нет (и это не меню) — считаем, что для этой главы xdelta нет
            if not search_dir:
                return False
        else:
            search_dir = source_dir

        # Ищем .xdelta файлы в выбранной папке
        if os.path.exists(search_dir):
            for root, _, files in os.walk(search_dir):
                for file in files:
                    if file.lower().endswith('.xdelta'):
                        return True  # Наличие .xdelta файла означает xdelta мод только для этой главы

        return False

    def _create_backup_and_copy_mod_files(self, source_dir: str, target_dir: str, chapter_id: Optional[int] = None, mod_info=None):
        """Создает резервную копию оригинальных файлов и копирует файлы мода с поддержкой xdelta патчинга."""

        if not os.path.isdir(source_dir):
            self.update_status_signal.emit(tr("errors.mod_folder_not_found_simple", path=source_dir), UI_COLORS["status_error"])
            return False

        # Инициализируем список файлов для очистки, если его еще нет
        if not hasattr(self, '_mod_files_to_cleanup'):
            self._mod_files_to_cleanup = []
        if not hasattr(self, '_backup_files'):
            self._backup_files = {}
        # Готовим манифест сессии
        self._ensure_session_manifest()

        # Определяем, является ли мод xdelta-модом
        is_xdelta_mod = self._is_xdelta_mod(mod_info, source_dir, chapter_id)

        # В рамках одной главы применяем не более ОДНОГО xdelta патча
        applied_xdelta_for_this_chapter = False

        files_copied = 0

        # Определяем, откуда брать файлы для данной главы
        if chapter_id is not None:
            # Определяем точную папку для главы
            chapter_folder_name = { -1: "demo", 0: "chapter_0" }.get(chapter_id, f"chapter_{chapter_id}")
            mod_source_dir = os.path.join(source_dir, chapter_folder_name)

            if not os.path.isdir(mod_source_dir):
                # ВАЖНО: не используем корень как fallback для глав > 0, чтобы не тянуть корневой патч в главы
                if chapter_id in (-1, 0):
                    mod_source_dir = source_dir
                else:
                    mod_source_dir = None
        else:
            mod_source_dir = source_dir

        if not mod_source_dir or not os.path.isdir(mod_source_dir):
            self.update_status_signal.emit(tr("status.no_files_to_copy"), UI_COLORS["status_warning"])
            return True

        # Создаем временную папку для резервных копий
        if not hasattr(self, '_backup_temp_dir') or not self._backup_temp_dir:
            self._backup_temp_dir = tempfile.mkdtemp(prefix="deltahub_backup_")
            self._update_session_manifest(backup_temp_dir=self._backup_temp_dir)

        for root, _, files in os.walk(mod_source_dir):
            for file in files:
                # Пропускаем служебные файлы и иконки
                if file.lower() == 'config.json' or file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico')):
                    continue

                cache_file_path = os.path.join(root, file)
                rel_path = os.path.relpath(cache_file_path, mod_source_dir)
                file_lower = file.lower()

                # Переименование файлов в зависимости от платформы
                target_rel_path = rel_path

                # Определяем, является ли это ядровым DATA файлом (включая .xdelta файлы)
                is_core_data_file = (
                    file_lower in ('data.win', 'data.ios', 'game.ios') or
                    file_lower.endswith('.win') and 'data' in file_lower or
                    file_lower.endswith('.ios') and 'game' in file_lower or
                    (is_xdelta_mod and file_lower.endswith('.xdelta'))  # Для xdelta модов любой .xdelta файл - это core data
                )



                if platform.system() == "Darwin":
                    # На macOS
                    if is_core_data_file:
                        # Ядровые файлы переименовываем полностью в game.ios
                        target_rel_path = os.path.join(os.path.dirname(rel_path), "game.ios")
                    elif file_lower.endswith('.win'):
                        # Для остальных файлов только меняем расширение .win → .ios
                        name_without_ext = os.path.splitext(file)[0]
                        target_rel_path = os.path.join(os.path.dirname(rel_path), name_without_ext + ".ios")
                else:
                    # На других платформах
                    if is_core_data_file:
                        # Ядровые файлы переименовываем полностью в data.win
                        target_rel_path = os.path.join(os.path.dirname(rel_path), "data.win")
                    elif file_lower.endswith('.ios'):
                        # Для остальных файлов только меняем расширение .ios → .win
                        name_without_ext = os.path.splitext(file)[0]
                        target_rel_path = os.path.join(os.path.dirname(rel_path), name_without_ext + ".win")

                game_file_path = os.path.join(target_dir, target_rel_path)

                try:
                    target_dirname = os.path.dirname(game_file_path)
                    os.makedirs(target_dirname, exist_ok=True)
                    try:
                        # Запоминаем созданные папки для последующей очистки (если останутся пустыми)
                        if not hasattr(self, '_mod_dirs_to_cleanup'):
                            self._mod_dirs_to_cleanup = []
                        if target_dirname not in self._mod_dirs_to_cleanup:
                            self._mod_dirs_to_cleanup.append(target_dirname)
                            self._update_session_manifest(mod_dirs=[target_dirname])
                    except Exception:
                        pass

                    # Для xdelta модов обрабатываем .xdelta файлы отдельно
                    if is_xdelta_mod and file_lower.endswith('.xdelta') and is_core_data_file:
                        # Применяем только один патч на главу и только к целевому data файлу
                        if applied_xdelta_for_this_chapter:
                            continue

                        if not self._apply_xdelta_patch(cache_file_path, game_file_path, target_dir):
                            self.update_status_signal.emit(tr("errors.xdelta_apply_error", file=file), UI_COLORS["status_error"])
                            return False
                        files_copied += 1
                        applied_xdelta_for_this_chapter = True
                        continue

                    # Пропускаем .xdelta файлы для обычных модов
                    if file_lower.endswith('.xdelta'):
                        continue

                    # Резервное копирование оригинального файла, если он существует
                    if os.path.exists(game_file_path) and game_file_path not in self._backup_files:
                        # --- ИСПРАВЛЕНИЕ: Создаем уникальное имя для бэкапа, чтобы избежать коллизий ---
                        unique_hash = hashlib.md5(game_file_path.encode('utf-8')).hexdigest()
                        backup_filename = f"{unique_hash}_{os.path.basename(game_file_path)}"
                        backup_file_path = os.path.join(self._backup_temp_dir, backup_filename)
                        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
                        os.makedirs(os.path.dirname(backup_file_path), exist_ok=True)

                        # Перемещаем оригинал в резервную папку
                        shutil.move(game_file_path, backup_file_path)
                        self._backup_files[game_file_path] = backup_file_path
                        self._update_session_manifest(backup_files={game_file_path: backup_file_path})

                    # Проверяем, является ли файл архивом
                    if file_lower.endswith(('.zip', '.rar', '.7z')) and not is_core_data_file:
                        # Для архивов - распаковываем содержимое и добавляем все извлеченные файлы в список очистки
                        extracted_files = self._extract_archive_to_target(cache_file_path, target_dir)
                        if extracted_files:
                            self._mod_files_to_cleanup.extend(extracted_files)
                            self._update_session_manifest(mod_files=extracted_files)
                        files_copied += 1
                    else:
                        # Для обычных файлов - копируем
                        shutil.copy2(cache_file_path, game_file_path)
                        files_copied += 1
                        # Добавляем файл в список для последующей очистки
                        self._mod_files_to_cleanup.append(game_file_path)
                        self._update_session_manifest(mod_files=[game_file_path])

                except Exception as e:
                    self.update_status_signal.emit(tr("errors.file_copy_error", file=file, error=str(e)), UI_COLORS["status_error"])

        if files_copied > 0:
            self.update_status_signal.emit(tr("status.files_copied_count", count=files_copied), UI_COLORS["status_info"])
        else:
            self.update_status_signal.emit(tr("status.no_files_to_copy"), UI_COLORS["status_warning"])

        return True

    def _apply_xdelta_patch(self, xdelta_file_path: str, target_game_file_path: str, target_dir: str) -> bool:
        """Применяет xdelta патч к оригинальному data файлу с поддержкой альтернативных форматов."""

        try:
            import pyxdelta
        except ImportError:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, tr("errors.xdelta_error"), tr("errors.xdelta_unavailable"))
            return False

        # Определяем возможные имена data файлов
        data_win = os.path.join(target_dir, "data.win")
        game_ios = os.path.join(target_dir, "game.ios")

        # Определяем приоритетный файл на основе ОС
        if platform.system() == "Darwin":
            primary_file = game_ios
            secondary_file = data_win
        else:
            primary_file = data_win
            secondary_file = game_ios

        # Ищем существующий data файл
        original_data_file = None
        if os.path.exists(primary_file):
            original_data_file = primary_file
        elif os.path.exists(secondary_file):
            original_data_file = secondary_file

        if not original_data_file:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, tr("errors.xdelta_error"), tr("errors.original_data_file_not_found", target_dir=target_dir))
            return False

        temp_dir = None
        try:
            # Создаем временную директорию для патчинга
            temp_dir = tempfile.mkdtemp(prefix="xdelta_patch_")
            temp_original = os.path.join(temp_dir, "original_data.bin")
            temp_patch = os.path.join(temp_dir, "patch.xdelta")
            temp_output = os.path.join(temp_dir, "patched_data.bin")

            # Копируем оригинальный файл и патч во временную папку
            shutil.copy2(original_data_file, temp_original)
            shutil.copy2(xdelta_file_path, temp_patch)

            # Используем общую временную папку для резервных копий
            if not hasattr(self, '_backup_temp_dir') or not self._backup_temp_dir:
                self._backup_temp_dir = tempfile.mkdtemp(prefix="deltahub_backup_")
                self._update_session_manifest(backup_temp_dir=self._backup_temp_dir)

            unique_hash = hashlib.md5(original_data_file.encode('utf-8')).hexdigest()
            backup_filename = f"xdelta_{unique_hash}_{os.path.basename(original_data_file)}"
            backup_file_path = os.path.join(self._backup_temp_dir, backup_filename)

            # FIX: Only back up the file if it hasn't been backed up already in this session
            if not hasattr(self, '_backup_files'):
                self._backup_files = {}
            
            if original_data_file not in self._backup_files:
                shutil.move(original_data_file, backup_file_path)
                self._backup_files[original_data_file] = backup_file_path
                self._update_session_manifest(backup_files={original_data_file: backup_file_path})

            def try_patch_with_format(original_file, output_file, format_name):
                """Попытка применить патч с определенным форматом файла."""
                try:
                    success = pyxdelta.decode(infile=original_file, patchfile=temp_patch, outfile=output_file)
                    return success and os.path.exists(output_file)
                except Exception as e:
                    return False

            # Пытаемся применить патч с оригинальным форматом
            if try_patch_with_format(temp_original, temp_output, os.path.basename(original_data_file)):
                # Успешно - копируем результат
                shutil.copy2(temp_output, original_data_file)
                self._mod_files_to_cleanup.append(original_data_file)
                self.update_status_signal.emit(tr("status.xdelta_patch_applied", patch_name=os.path.basename(xdelta_file_path)), UI_COLORS["status_success"])
                return True

            # Если первая попытка не удалась, пробуем с альтернативным форматом
            # Переименовываем файл для альтернативной попытки
            if original_data_file.endswith('data.win'):
                temp_alt_original = os.path.join(temp_dir, "original_data_alt.ios")
                alt_format_name = "game.ios"
                final_extension = ".win"
            else:  # game.ios
                temp_alt_original = os.path.join(temp_dir, "original_data_alt.win")
                alt_format_name = "data.win"
                final_extension = ".ios"

            # Копируем файл с новым именем
            shutil.copy2(temp_original, temp_alt_original)
            temp_alt_output = os.path.join(temp_dir, "patched_data_alt.bin")

            if try_patch_with_format(temp_alt_original, temp_alt_output, alt_format_name):
                # Успешно - копируем результат с правильным расширением
                shutil.copy2(temp_alt_output, original_data_file)
                self._mod_files_to_cleanup.append(original_data_file)
                self.update_status_signal.emit(tr("status.xdelta_patch_applied_alt", patch_name=os.path.basename(xdelta_file_path)), UI_COLORS["status_success"])
                return True

            # Обе попытки не удались
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, tr("errors.xdelta_patch_failed"),
            tr("errors.patch_incompatible", patch_name=os.path.basename(xdelta_file_path)))

            # Восстанавливаем оригинальный файл в случае ошибки
            if backup_file_path in self._backup_files.values():
                shutil.move(backup_file_path, original_data_file)
                del self._backup_files[original_data_file]
            return False

        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, tr("errors.xdelta_critical_error"), tr("errors.xdelta_patch_critical_error", error=str(e)))
            return False
        finally:
            # Очищаем временную директорию
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    print(tr("errors.temp_dir_delete_failed", temp_dir=temp_dir, error=e))

    def _copy_mod_files_to_target(self, source_dir: str, target_dir: str, chapter_id: Optional[int] = None):
        """Устаревший метод - оставлен для обратной совместимости."""
        # Вызываем новый метод без информации о моде
        return self._create_backup_and_copy_mod_files(source_dir, target_dir, chapter_id, None)

    def _extract_archive_to_target(self, archive_path: str, target_dir: str):
        """Извлекает архив в целевую директорию и возвращает список извлеченных файлов."""
        import tempfile, zipfile, rarfile

        file_lower = archive_path.lower()
        extracted_files = []

        try:
            with tempfile.TemporaryDirectory(prefix="deltahub-extract-") as temp_dir:
                if file_lower.endswith('.zip'):
                    with zipfile.ZipFile(archive_path, 'r') as zf:
                        zf.extractall(temp_dir)
                elif file_lower.endswith('.rar'):
                    with rarfile.RarFile(archive_path, 'r') as rf:
                        rf.extractall(temp_dir)
                else:
                    with zipfile.ZipFile(archive_path, 'r') as zf:
                        zf.extractall(temp_dir)

                from helpers import _cleanup_extracted_archive
                _cleanup_extracted_archive(temp_dir)

                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        source_file = os.path.join(root, file)
                        rel_path = os.path.relpath(source_file, temp_dir)
                        target_file = os.path.join(target_dir, rel_path)
                        file_lower = file.lower()
                        if platform.system() == "Darwin":
                            if file_lower.endswith('.win'):
                                name_without_ext = os.path.splitext(file)[0]
                                target_file = os.path.join(os.path.dirname(target_file), name_without_ext + ".ios")
                        else:
                            if file_lower.endswith('.ios'):
                                name_without_ext = os.path.splitext(file)[0]
                                target_file = os.path.join(os.path.dirname(target_file), name_without_ext + ".win")

                        target_dirname = os.path.dirname(target_file)
                        os.makedirs(target_dirname, exist_ok=True)
                        try:
                            if not hasattr(self, '_mod_dirs_to_cleanup'):
                                self._mod_dirs_to_cleanup = []
                            if target_dirname not in self._mod_dirs_to_cleanup:
                                self._mod_dirs_to_cleanup.append(target_dirname)
                                self._update_session_manifest(mod_dirs=[target_dirname])
                        except Exception:
                            pass

                        # Создаем резервную копию, если файл уже существует
                        if os.path.exists(target_file):
                            backup_rel_path = os.path.relpath(target_file, target_dir)
                            if hasattr(self, '_backup_temp_dir') and self._backup_temp_dir:
                                backup_file_path = os.path.join(self._backup_temp_dir, backup_rel_path)
                                os.makedirs(os.path.dirname(backup_file_path), exist_ok=True)
                                shutil.move(target_file, backup_file_path)
                                if not hasattr(self, '_backup_files'):
                                    self._backup_files = {}
                                self._backup_files[target_file] = backup_file_path
                                self._update_session_manifest(backup_files={target_file: backup_file_path})

                        shutil.copy2(source_file, target_file)
                        extracted_files.append(target_file)

        except Exception as e:
            self.update_status_signal.emit(tr("errors.archive_unpack_error", archive_name=os.path.basename(archive_path), error=str(e)), UI_COLORS["status_error"])

        return extracted_files

    def _determine_launch_config(self, selections: Dict[int, str]) -> Optional[Dict[str, Any]]:
        use_steam = self.local_config.get('launch_via_steam', False)
        direct_launch_slot_id = self.local_config.get('direct_launch_slot_id', -1)

        # Прямой запуск работает если выбран слот > 0
        direct_launch = (direct_launch_slot_id > 0 and
                        self.game_mode.direct_launch_allowed and
                        platform.system() != "Darwin")

        if use_steam:
            return self._handle_steam_launch()

        if direct_launch:
            # Запускаем прямой запуск для выбранного слота
            return self._handle_direct_launch(direct_launch_slot_id)

        # Обычный запуск (не Steam, не прямой запуск)
        launch_target = self._get_executable_path()
        if not launch_target:
            self.update_status_signal.emit(tr("errors.executable_not_found"), UI_COLORS["status_error"])
            return None
        return {'target': launch_target, 'cwd': self._get_current_game_path(), 'type': 'subprocess'}

    def _handle_steam_launch(self) -> Dict[str, Any]:
        return {'target': f"steam://rungameid/{self.game_mode.steam_id}", 'cwd': None, 'type': 'webbrowser'}

    def _handle_direct_launch(self, selected_tab_index: int) -> Optional[Dict[str, Any]]:
        chapter_folder = self._get_target_dir(self.game_mode.get_chapter_id(selected_tab_index))
        source_exe = self._get_source_executable_path()
        use_custom_exe = self.local_config.get("use_custom_executable", False)

        if not chapter_folder or not source_exe:
            self.update_status_signal.emit(tr("errors.direct_launch_error"), UI_COLORS["status_error"])
            return None

        try:
            if not ensure_writable(chapter_folder):
                raise PermissionError(tr("errors.no_write_permission_for", path=chapter_folder))

            if use_custom_exe:
                target_exe = os.path.join(chapter_folder, os.path.basename(source_exe))
            else:
                target_exe = os.path.join(chapter_folder, "DELTARUNE.exe")

            shutil.copy2(source_exe, target_exe)
            self._direct_launch_cleanup_info = {
                'target_exe': target_exe,
                'source_exe': source_exe,
                'chapter_folder': chapter_folder,
                'use_custom_exe': use_custom_exe
            }
            # Записываем в манифест для восстановления после сбоев
            self._update_session_manifest(direct_launch=self._direct_launch_cleanup_info)

            return {'target': target_exe, 'cwd': chapter_folder, 'type': 'subprocess'}

        except PermissionError as e:
            if not self.is_shortcut_launch:
                self._handle_permission_error(e.filename or chapter_folder)
            return None

    def _cleanup_direct_launch_files(self):
        """Очищает файлы модов и восстанавливает оригинальные файлы."""
        try:
            # Запомним список целей, для которых мы делали бэкапы (инлайновая замена)
            backed_up_targets = set(self._backup_files.keys()) if hasattr(self, '_backup_files') and self._backup_files else set()

            # Сначала восстанавливаем оригинальные файлы из резервной копии
            if hasattr(self, '_backup_files') and self._backup_files:
                for original_path, backup_path in self._backup_files.items():
                    try:
                        if os.path.exists(backup_path):
                            # Удаляем модифицированный файл если он есть
                            if os.path.exists(original_path):
                                os.remove(original_path)

                            # Восстанавливаем оригинальный файл
                            os.makedirs(os.path.dirname(original_path), exist_ok=True)
                            shutil.move(backup_path, original_path)
                    except Exception as e:
                        continue  # Продолжаем с другими файлами
                self._backup_files = {}

            # Удаляем остальные файлы модов (которые не были резервными)
            if hasattr(self, '_mod_files_to_cleanup') and self._mod_files_to_cleanup:
                remaining_files = []
                for file_path in self._mod_files_to_cleanup:
                    # Не удаляем файлы, для которых мы только что восстановили оригиналы
                    if file_path in backed_up_targets:
                        continue
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        else:
                            remaining_files.append(file_path)
                    except Exception as e:
                        continue
                self._mod_files_to_cleanup = []

            # Удаляем временную папку резервных копий
            if hasattr(self, '_backup_temp_dir') and self._backup_temp_dir and os.path.exists(self._backup_temp_dir):
                try:
                    shutil.rmtree(self._backup_temp_dir)
                    self._backup_temp_dir = None
                except Exception as e:
                    pass

            # Пытаемся удалить созданные пустые директории (в обратном порядке вложенности)
            try:
                dirs = []
                if hasattr(self, '_mod_dirs_to_cleanup') and self._mod_dirs_to_cleanup:
                    dirs = sorted(set(self._mod_dirs_to_cleanup), key=lambda p: len(p.split(os.sep)), reverse=True)
                else:
                    data = self._load_session_manifest() or {}
                    dirs = sorted(set(data.get('mod_dirs_to_cleanup', [])), key=lambda p: len(p.split(os.sep)), reverse=True)
                for d in dirs:
                    try:
                        if os.path.isdir(d) and not os.listdir(d):
                            os.rmdir(d)
                    except Exception:
                        pass
                self._mod_dirs_to_cleanup = []
            except Exception:
                pass

            # Существующая логика для прямого запуска
            cleanup_info = getattr(self, '_direct_launch_cleanup_info', None)
            if cleanup_info:
                if 'target_exe' in cleanup_info and os.path.exists(cleanup_info['target_exe']):
                    os.remove(cleanup_info['target_exe'])
                self._direct_launch_cleanup_info = None

            self.update_status_signal.emit(tr("status.files_restored"), UI_COLORS["status_success"])
            # Удаляем файл-манифест после успешного восстановления
            self._clear_session_manifest()

        except Exception as e:
            self.update_status_signal.emit(tr("errors.files_restore_error", error=str(e)), UI_COLORS["status_error"])



    def _launch_game_with_all_mods(self):
        """Запускает игру с модами из слотов"""
        selections = self._get_slot_selections()
        self._launch_game_with_selections(selections)

    def _get_slot_selections(self):
        """Создает словарь selections из назначенных слотов"""
        selections = {}

        if not hasattr(self, 'slots'):
            return selections

        # Проверяем демо режим
        is_demo_mode = isinstance(self.game_mode, DemoGameMode)

        if is_demo_mode:
            # В демо режиме обрабатываем только демо слот (-2)
            demo_slot = self.slots.get(-2)  # Демо слот
            if demo_slot and demo_slot.assigned_mod:
                # Для демо режима используем специальный chapter_id = -1
                selections[-1] = demo_slot.assigned_mod.key
            else:
                selections[-1] = "no_change"
        elif self.current_mode == "normal":
            # В обычном режиме универсальный слот применяется ко всем главам
            universal_slot = self.slots.get(-1)  # Универсальный слот
            if universal_slot and universal_slot.assigned_mod:
                # Применяем мод ко всем главам (0-4)
                for chapter_id in range(5):
                    selections[chapter_id] = universal_slot.assigned_mod.key
            else:
                # Если нет мода в универсальном слоте, используем "no_change"
                for chapter_id in range(5):
                    selections[chapter_id] = "no_change"
        elif self.current_mode == "chapter":
            # В поглавном режиме каждый слот работает только для своей главы
            for chapter_id in range(5):
                slot = self.slots.get(chapter_id)
                if slot and slot.assigned_mod:
                    selections[chapter_id] = slot.assigned_mod.key
                else:
                    selections[chapter_id] = "no_change"
        return selections

    def _launch_game_with_selections(self, selections: Dict[int, str]):
        self.hide_window_signal.emit()
        def restore_and_return():
            self.restore_window_signal.emit()
            self._update_ui_for_selection()

        if not self._find_and_validate_game_path(selections): restore_and_return(); return
        if not self._prepare_game_files(selections): restore_and_return(); return
        if not (launch_config := self._determine_launch_config(selections)): restore_and_return(); return

        self.update_status_signal.emit(tr("status.launching_game"), UI_COLORS["status_success"])
        self._execute_game(launch_config)

    def _execute_game(self, launch_config: Dict[str, Any], vanilla_mode: bool = False):
        target_path = launch_config.get('target')
        working_directory = launch_config.get('cwd')
        launch_type = launch_config.get('type')

        if not target_path:
            self.update_status_signal.emit(tr("errors.launch_target_not_defined"), "red")
            self.restore_window_signal.emit()
            return

        try:
            if launch_type == 'webbrowser':
                self.monitor_thread = GameMonitorThread(None, vanilla_mode, self)
                self.monitor_thread.finished.connect(self._on_game_process_finished)
                self.monitor_thread.start()
                webbrowser.open(target_path)
                self.update_status_signal.emit(tr("status.launching_via_steam"), UI_COLORS["status_steam"])
                return

            if not working_directory or not os.path.isdir(working_directory):
                msg = tr("errors.working_directory_not_found", path=working_directory)
                self.update_status_signal.emit(msg, "red")
                self.error_signal.emit(msg)
                self.restore_window_signal.emit()
                return

            system = platform.system()
            if system == "Darwin":
                # Требование: «Отдельный файл запуска» на macOS должен открываться так же,
                # как при двойном клике (любые файлы: .app, .png, .txt и т.d.).
                # В таком режиме НЕ ждём завершения процесса.
                use_custom_exe = self.local_config.get('use_custom_executable', False)
                if use_custom_exe:
                    subprocess.Popen(['open', target_path])
                    self.update_status_signal.emit(tr("status.macos_file_opened"), UI_COLORS["status_steam"])
                    # Вернём окно через небольшую паузу — ждать закрытия не нужно.
                    if self.is_shortcut_launch:
                        sys.exit(0)
                    else:
                        QTimer.singleShot(2000, self.restore_window_signal.emit)
                    return
                # Обычный запуск игры через .app — ждём закрытия, чтобы восстановить файлы корректно.
                if target_path.endswith(".app"):
                    process = subprocess.Popen(['open', '-W', target_path])
                else:
                    process = subprocess.Popen([target_path], cwd=working_directory)
            else:
                process = subprocess.Popen([target_path], cwd=working_directory)

            self.update_status_signal.emit(tr("status.game_launched_waiting_for_exit"), UI_COLORS["status_steam"])

            self.monitor_thread = GameMonitorThread(process, vanilla_mode, self)
            self.monitor_thread.finished.connect(self._on_game_process_finished)
            self.monitor_thread.start()

        except Exception as e:
            self.update_status_signal.emit(tr("errors.game_launch_error", error=str(e)), "red")
            self.error_signal.emit(tr("errors.game_launch_failed", error=str(e)))
            self.restore_window_signal.emit()

    def _get_source_executable_path(self):
        if self.local_config.get("use_custom_executable", False):
            cfg_key = self.game_mode.get_custom_exec_config_key()
            return self.local_config.get(cfg_key, "")
        return self._get_executable_path()

    def _on_game_process_finished(self, vanilla_mode: bool):
        if self.is_shortcut_launch:
            sys.exit(0)
        else:
            self._check_game_running(vanilla_mode)

    def _check_game_running(self, vanilla_mode):
        if is_game_running():
            QTimer.singleShot(2000, lambda: self._check_game_running(vanilla_mode))
        else:
            self.update_status_signal.emit(tr("status.game_closed_restoring_files"), UI_COLORS["status_info"])
            self._cleanup_direct_launch_files()
            self.restore_window_signal.emit()

    def _hide_window_for_game(self):
        self.hide()

    def _restore_window_after_game(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self.progress_bar.setVisible(False)
        self._update_ui_for_selection()

    def _update_status(self, message: str, color: str = "white"):
        if not self.is_shortcut_launch:
            self.status_label.setText(message)
            self.status_label.setStyleSheet(f"color: {color};")

    def _run_presence_tick(self):
        if self.is_shortcut_launch: return
        thr = getattr(self, "presence_thread", None)
        try:
            if thr and thr.isRunning(): return
        except RuntimeError: self.presence_thread = None; thr = None

        self.presence_thread = QThread(self)
        self.presence_worker = PresenceWorker(self.session_id)
        self.presence_worker.moveToThread(self.presence_thread)
        self.presence_thread.started.connect(self.presence_worker.run)
        self.presence_worker.finished.connect(self.presence_thread.quit)
        self.presence_thread.finished.connect(lambda: setattr(self, "presence_thread", None))
        self.presence_thread.finished.connect(self.presence_thread.deleteLater)
        self.presence_worker.finished.connect(self.presence_worker.deleteLater)
        self.presence_worker.update_online_count.connect(self._update_online_label)
        self.presence_thread.start()

    def _update_online_label(self, count: int):
        if not self.is_shortcut_launch:
            self.online_label.setText(f"<span style='color:{UI_COLORS['status_ready']};'>●</span> {tr('status.online_count', count=count)}")

    def _on_toggle_custom_executable(self):
        use_custom = self.use_custom_executable_checkbox.isChecked()
        self.local_config["use_custom_executable"] = use_custom
        if not use_custom: self.local_config[self.game_mode.get_custom_exec_config_key()] = ""
        self._write_local_config()
        self._update_custom_executable_ui()

    def _select_custom_executable_file(self):
        dlg_title = tr("ui.select_launch_file")
        filepath = QFileDialog.getOpenFileName(self, dlg_title)[0]
        if filepath:
            self.local_config[self.game_mode.get_custom_exec_config_key()] = filepath
            self._write_local_config()
            self._update_custom_executable_ui()

    def _update_custom_executable_ui(self):
        use_custom = self.local_config.get("use_custom_executable", False)
        path = self.local_config.get(self.game_mode.get_custom_exec_config_key(), "")
        self.custom_exe_frame.setVisible(use_custom and self.use_custom_executable_checkbox.isEnabled())
        if self.custom_exe_frame.isVisible():
            self.custom_executable_path_label.setText(tr("ui.currently_selected", filename=os.path.basename(path)) if path else tr("ui.file_not_selected"))

    def _on_toggle_steam_launch(self, state=None):
        is_steam_launch = self.launch_via_steam_checkbox.isChecked()
        self.local_config['launch_via_steam'] = is_steam_launch
        self._write_local_config()
        self._update_custom_executable_ui()

    def _on_language_changed(self):
        """Обработчик изменения языка"""
        current_text = self.language_combo.currentText()
        selected_data = self.language_combo.currentData()

        if not selected_data:
            return

        # Проверяем, не выбран ли уже текущий язык
        manager = get_localization_manager()
        current_language = manager.get_current_language()

        if selected_data == current_language:
            # Язык не изменился, ничего не делаем
            return

        # Сохраняем новый язык в конфигурацию
        self.local_config['language'] = selected_data
        self._write_json(self.config_path, self.local_config)

        # Показываем диалог с просьбой перезагрузить
        manager = get_localization_manager()
        manager.load_language(selected_data)  # Загружаем новый язык для диалога

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(tr("ui.restart_required"))
        msg_box.setText(tr("ui.restart_message"))
        msg_box.setIcon(QMessageBox.Icon.Information)

        restart_button = msg_box.addButton(tr("ui.restart_button"), QMessageBox.ButtonRole.AcceptRole)
        later_button = msg_box.addButton(tr("ui.later_button"), QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(restart_button)

        result = msg_box.exec()

        if msg_box.clickedButton() == restart_button:
            # Перезапускаем лаунчер (надежно для собранной версии)
            try:
                from PyQt6.QtCore import QProcess
                QProcess.startDetached(sys.executable, sys.argv[1:])
            except Exception:
                import subprocess
                subprocess.Popen([sys.executable] + sys.argv)
            QApplication.quit()


    def _update_ui_for_selection(self):

        # В новой системе с вкладками "Искать моды" и "Библиотека"
        # этот метод пока не нужен, так как UI управляется по-новому
        # TODO: Переработать под новую систему или удалить

        # Обновляем только базовый статус для совместимости
        if hasattr(self, 'action_button'):
            if getattr(self, 'is_installing', False):
                return
            # Проверяем, нужны ли обновления в активных слотах
            slots_need_update = self._check_active_slots_need_updates()


            # Определяем текст кнопки в зависимости от состояния чекбокса полной установки
            is_demo_mode = isinstance(self.game_mode, DemoGameMode)
            is_full_install_enabled = (is_demo_mode and hasattr(self, 'full_install_checkbox') and
                                     self.full_install_checkbox.isChecked())


            if is_full_install_enabled:
                action_text = tr("buttons.install")
            elif slots_need_update:
                action_text = tr("ui.update_button")
            else:
                action_text = tr("ui.launch_button")


            self.action_button.setText(action_text)
            self.action_button.setEnabled(True)

        # Кнопка Сохранения должна быть всегда активна
        if hasattr(self, 'saves_button'):
            self.saves_button.setEnabled(True)

    def _check_active_slots_need_updates(self):
        """Проверяет, нужны ли обновления в активных слотах в зависимости от режима"""


        # Проверяем, что данные о модах загружены
        if not self.all_mods:
            return False

        is_chapter_mode = self.chapter_mode_checkbox.isChecked()
        is_demo_mode = isinstance(self.game_mode, DemoGameMode)


        # Определяем активные слоты в зависимости от режима
        if is_demo_mode:
            # В демо режиме проверяем только демо слот
            active_slot_ids = [-2]
        elif not is_chapter_mode:
            # В обычном режиме проверяем только универсальный слот
            active_slot_ids = [-1]
        else:
            # В поглавном режиме проверяем все поглавные слоты
            active_slot_ids = [0, 1, 2, 3, 4]



        # Проверяем каждый активный слот
        for slot_id in active_slot_ids:
            for slot_frame in self.slots.values():
                if slot_frame.chapter_id == slot_id and slot_frame.assigned_mod:
                    mod_data = slot_frame.assigned_mod


                    # Пропускаем локальные моды
                    mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None)
                    if mod_key and mod_key.startswith("local_"):

                        continue

                    # Для универсального и демо слота проверяем статус для всех доступных глав мода
                    if slot_id < 0:  # Универсальный (-1) или демо (-2) слот
                        needs_update = any(self._mod_has_files_for_chapter(mod_data, i) and
                                         self._get_mod_status_for_chapter(mod_data, i) == 'update' for i in range(5))

                    else:  # Поглавный слот
                        # Проверяем общий статус мода (любая глава нуждается в обновлении)
                        needs_update = any(self._mod_has_files_for_chapter(mod_data, i) and
                                         self._get_mod_status_for_chapter(mod_data, i) == 'update' for i in range(5))


                    if needs_update:

                        return True


        return False

    def _update_mods_in_active_slots(self):
        """Обновляет все моды в активных слотах, которые нуждаются в обновлении"""
        # Строгая проверка - блокируем если уже идет установка
        if self.is_installing:

            return

        is_chapter_mode = self.chapter_mode_checkbox.isChecked()
        is_demo_mode = isinstance(self.game_mode, DemoGameMode)

        # Определяем активные слоты в зависимости от режима
        if is_demo_mode:
            active_slot_ids = [-2]
        elif not is_chapter_mode:
            active_slot_ids = [-1]
        else:
            active_slot_ids = [0, 1, 2, 3, 4]

        # Собираем моды для обновления
        mods_to_update = []
        for slot_id in active_slot_ids:
            for slot_frame in self.slots.values():
                if slot_frame.chapter_id == slot_id and slot_frame.assigned_mod:
                    mod_data = slot_frame.assigned_mod
                    # Пропускаем локальные моды
                    mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None)
                    if mod_key and mod_key.startswith("local_"):
                        continue

                    # Для всех слотов проверяем статус для всех доступных глав мода
                    needs_update = any(self._mod_has_files_for_chapter(mod_data, i) and
                                     self._get_mod_status_for_chapter(mod_data, i) == 'update' for i in range(5))

                    if needs_update and mod_data not in mods_to_update:
                        mods_to_update.append(mod_data)

        # Обновляем каждый мод последовательно
        if mods_to_update:
            # Если есть моды для обновления, обновляем первый
            # Остальные будут обновлены после завершения первого через _on_mod_install_finished
            self.pending_updates = mods_to_update[1:] if len(mods_to_update) > 1 else []
            self._update_mod(mods_to_update[0])

    def _refresh_slots_content(self):
        """Обновляет содержимое всех слотов с модами для обновления статусов"""
        self._refresh_all_slot_status_displays()

    def _update_combo_color(self, chapter_id):
        if chapter_id < 0: return

        combo = self.tabs[chapter_id]["combo"]
        selected_mod = self._get_selected_mod_info(chapter_id)

        status = "n/a" # Статус по умолчанию для "Без изменений"
        if selected_mod:
            real_chapter_id = self.game_mode.get_chapter_id(chapter_id)
            status = self._get_mod_status_for_chapter(selected_mod, real_chapter_id)

        color_map = {
            "ready": "lightgreen",
            "update": "orange",
            "install": "white",
            "n/a": "gray"
        }
        color = QColor(color_map.get(status, "white"))

        palette = combo.palette()
        palette.setColor(QPalette.ColorRole.Text, color)
        combo.setPalette(palette)

    # ===========================================================================
    #                              MOD MANAGEMENT SYSTEM
    # ===========================================================================

    def _on_manage_mods_click(self):
        """Точка входа в систему управления модами."""
        # Проверяем подключение к интернету
        if not check_internet_connection():
            QMessageBox.critical(self, tr("errors.connection_error"),
            tr("errors.internet_required"))
            return

        # Показываем главное меню управления модами
        self._show_main_mod_management_dialog()

    def _on_xdelta_patch_click(self):
        """Обработчик для кнопки патчинга XDELTA."""
        try:
            dialog = XdeltaDialog(self)
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, tr("errors.error"), tr("errors.patching_window_failed", error=str(e)))

    def _show_main_mod_management_dialog(self):
        """Показывает главное меню управления модами."""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("ui.mod_management"))
        dialog.setModal(True)
        dialog.resize(400, 300)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Заголовок
        title = QLabel(tr("dialogs.what_do_you_want_to_do"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 20px;")
        layout.addWidget(title)

        # Кнопки действий (горизонтально)
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)

        create_button = QPushButton(tr("ui.create_mod"))
        create_button.setFixedSize(180, 50)
        create_button.clicked.connect(lambda: self._on_create_mod_choice(dialog))

        edit_button = QPushButton(tr("ui.edit_mod"))
        edit_button.setFixedSize(180, 50)
        edit_button.clicked.connect(lambda: self._on_edit_mod_choice(dialog))

        buttons_layout.addWidget(create_button)
        buttons_layout.addWidget(edit_button)
        layout.addLayout(buttons_layout)

        # Кнопка отмены
        layout.addSpacing(30)  # Фиксированное расстояние вместо stretch
        cancel_button = QPushButton(tr("ui.cancel_button"))
        cancel_button.clicked.connect(dialog.reject)
        layout.addWidget(cancel_button)

        dialog.exec()

    def _on_create_mod_choice(self, parent_dialog):
        """Обработчик выбора создания мода."""
        parent_dialog.accept()

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("ui.create_mod"))
        dialog.setModal(True)
        dialog.resize(300, 200)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(tr("ui.how_to_create_mod"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        # Кнопки типа мода (горизонтально)
        type_buttons_layout = QHBoxLayout()
        type_buttons_layout.setSpacing(15)

        public_button = QPushButton(tr("buttons.public"))
        public_button.setFixedSize(130, 40)
        public_button.clicked.connect(lambda: self._create_mod(dialog, public=True))

        local_button = QPushButton(tr("buttons.local"))
        local_button.setFixedSize(130, 40)
        local_button.clicked.connect(lambda: self._create_mod(dialog, public=False))

        type_buttons_layout.addWidget(public_button)
        type_buttons_layout.addWidget(local_button)
        layout.addLayout(type_buttons_layout)

        cancel_button = QPushButton(tr("ui.cancel_button"))
        cancel_button.clicked.connect(dialog.reject)
        layout.addWidget(cancel_button)

        dialog.exec()

    def _on_edit_mod_choice(self, parent_dialog):
        """Обработчик выбора редактирования мода."""
        parent_dialog.accept()

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("ui.edit_mod"))
        dialog.setModal(True)
        dialog.resize(300, 200)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(tr("dialogs.what_mod_type_to_change"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        # Кнопки типа мода для редактирования (горизонтально)
        edit_buttons_layout = QHBoxLayout()
        edit_buttons_layout.setSpacing(15)

        public_button = QPushButton(tr("buttons.public_button"))
        public_button.setFixedSize(130, 40)
        public_button.clicked.connect(lambda: self._edit_public_mod(dialog))

        local_button = QPushButton(tr("status.local"))
        local_button.setFixedSize(130, 40)
        local_button.clicked.connect(lambda: self._edit_local_mod(dialog))

        edit_buttons_layout.addWidget(public_button)
        edit_buttons_layout.addWidget(local_button)
        layout.addLayout(edit_buttons_layout)

        cancel_button = QPushButton(tr("ui.cancel_button"))
        cancel_button.clicked.connect(dialog.reject)
        layout.addWidget(cancel_button)

        dialog.exec()

    def _create_mod(self, parent_dialog, public: bool):
        """Создает новый мод."""
        parent_dialog.accept()

        # Проверяем интернет-соединение для публичных модов
        if public and not check_internet_connection():
            QMessageBox.critical(self, tr("errors.no_internet"),
            tr("errors.public_mod_internet"))
            return

        # Открываем диалог создания мода
        editor = ModEditorDialog(self, is_creating=True, is_public=public)
        editor.exec()
        try:
            self.activateWindow(); self.raise_(); self.setFocus()
        except Exception:
            pass

    def _edit_public_mod(self, parent_dialog):
        """Редактирует публичный мод."""
        parent_dialog.accept()

        # Проверяем интернет-соединение
        if not check_internet_connection():
            QMessageBox.critical(self, tr("errors.no_internet"),
            tr("errors.edit_mod_internet"))
            return

        # Запрашиваем секретный ключ
        secret_key, ok = QInputDialog.getText(self, tr("dialogs.enter_secret_key"),
        tr("dialogs.secret_key_mod"), QLineEdit.EchoMode.Password)
        if not ok or not secret_key.strip():
            return

        # Хешируем ключ (поддержка legacy-соли)
        from helpers import possible_secret_hashes, _fb_url
        candidate_hashes = possible_secret_hashes(secret_key.strip())

        # Ищем мод в основной коллекции и pending_mods
        mod_data = None
        found_in_pending = False

        try:
            # Перебираем возможные хеши (текущая соль + legacy)
            found_hash = None
            for h in candidate_hashes:
                resp = requests.get(_fb_url(DATA_FIREBASE_URL, f"mods/{h}"), timeout=10)
                if resp.status_code == 200 and resp.json():
                    mod_data = resp.json(); found_hash = h; break
                resp = requests.get(_fb_url(DATA_FIREBASE_URL, f"pending_mods/{h}"), timeout=10)
                if resp.status_code == 200 and resp.json():
                    mod_data = resp.json(); found_hash = h; found_in_pending = True; break
            if found_hash and isinstance(mod_data, dict):
                mod_data['key'] = found_hash
                hashed_key = found_hash
        except requests.RequestException as e:
            QMessageBox.critical(self, tr("errors.error"), tr("errors.key_check_failed", error=str(e)))
            return

        if not mod_data:
            QMessageBox.warning(self, tr("errors.mod_not_found"),
            tr("errors.secret_key_invalid"))
            return

        # Проверяем статус блокировки
        if mod_data.get('ban_status', False):
            ban_reason = mod_data.get('ban_reason', tr('defaults.not_specified_fem'))
            QMessageBox.critical(self, tr("dialogs.mod_blocked_title"),
                              tr("dialogs.mod_blocked_message",
                                 ban_reason=ban_reason,
                                 error_message=tr("dialogs.error_occurred")))
            return

        if found_in_pending:
            # Show dialog with option to withdraw submission
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(tr("dialogs.mod_on_moderation"))
            msg_box.setText(tr("dialogs.mod_on_moderation_message"))
            withdraw_btn = msg_box.addButton(tr("buttons.withdraw_request"), QMessageBox.ButtonRole.DestructiveRole)
            ok_btn = msg_box.addButton(tr("buttons.ok"), QMessageBox.ButtonRole.AcceptRole)
            msg_box.setDefaultButton(ok_btn)
            msg_box.exec()
            if msg_box.clickedButton() == withdraw_btn:
                try:
                    from helpers import _fb_url, DATA_FIREBASE_URL as _DB_URL
                    requests.delete(_fb_url(_DB_URL, f"pending_mods/{hashed_key}"), timeout=10)
                    QMessageBox.information(self, tr("dialogs.request_withdrawn"), tr("dialogs.withdrawal_success"))
                except Exception as e:
                    QMessageBox.critical(self, tr("errors.error"), tr("errors.request_revoke_failed", error=str(e)))
            return

        # Проверяем, есть ли заявка на изменения для этого мода
        try:
            from helpers import _fb_url
            pending_changes_response = requests.get(_fb_url(DATA_FIREBASE_URL, f"pending_changes/{hashed_key}"), timeout=10)
            if pending_changes_response.status_code == 200 and pending_changes_response.json():
                # Есть заявка на изменения, показываем диалог с опциями
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle(tr("dialogs.changes_under_review"))
                msg_box.setText(tr("dialogs.request_pending"))
                msg_box.setIcon(QMessageBox.Icon.Information)
                ok_button = msg_box.addButton(tr("buttons.ok"), QMessageBox.ButtonRole.AcceptRole)
                withdraw_button = msg_box.addButton(tr("buttons.withdraw_request"), QMessageBox.ButtonRole.DestructiveRole)
                msg_box.exec()
                reply = msg_box.clickedButton()

                if reply == withdraw_button:
                    # Пользователь хочет отозвать заявку
                    try:
                        delete_response = requests.delete(_fb_url(DATA_FIREBASE_URL, f"pending_changes/{hashed_key}"), timeout=10)
                        delete_response.raise_for_status()
                        QMessageBox.information(self, tr("dialogs.request_withdrawn"),
                                                tr("dialogs.withdrawal_success"))
                    except requests.RequestException as e:
                        QMessageBox.critical(self, tr("errors.error"), tr("errors.request_revoke_failed", error=str(e)))
                        return
                else:
                    # Пользователь нажал ОК, просто закрываем
                    return
        except requests.RequestException:
            # Если ошибка при проверке pending_changes, продолжаем (возможно их просто нет)
            pass

        # Открываем редактор с данными мода
        editor = ModEditorDialog(self, is_creating=False, is_public=True, mod_data=mod_data)
        editor.exec()
        try:
            self.activateWindow(); self.raise_(); self.setFocus()
        except Exception:
            pass

    def _edit_local_mod(self, parent_dialog):
        """Редактирует локальный мод."""
        parent_dialog.accept()

        # Ищем локальные моды из config.json файлов
        local_mods = []
        if os.path.exists(self.mods_dir):
            for folder_name in os.listdir(self.mods_dir):
                folder_path = os.path.join(self.mods_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue

                config_path = os.path.join(folder_path, "config.json")
                if not os.path.exists(config_path):
                    continue

                try:
                    config_data = self._read_json(config_path)
                    if config_data and config_data.get('is_local_mod'):
                        mod_info = {
                            'key': config_data.get('mod_key'),
                            'name': config_data.get('name', 'Неизвестный мод'),
                            'data': config_data,
                            'folder_path': folder_path
                        }
                        local_mods.append(mod_info)
                except Exception:
                    continue

        if not local_mods:
            QMessageBox.information(self, tr("dialogs.no_local_mods_title"),
            tr("dialogs.no_local_mods_message"))
            return

        # Показываем список локальных модов для выбора
        mod_names = [mod_info["name"] for mod_info in local_mods]
        selected_name, ok = QInputDialog.getItem(self, tr("dialogs.select_mod"),
        tr("dialogs.local_mods"), mod_names, 0, False)
        if not ok:
            return

        # Находим выбранный мод
        selected_mod = None
        for mod_info in local_mods:
            if mod_info["name"] == selected_name:
                selected_mod = mod_info
                break

        if not selected_mod:
            QMessageBox.warning(self, tr("errors.error"), tr("errors.selected_mod_not_found"))
            return

        # Подготавливаем данные для редактора
        mod_data = selected_mod["data"].copy()
        mod_data["key"] = selected_mod["key"]
        # Pass folder name to resolve relative file paths during editing
        mod_data["folder_name"] = os.path.basename(selected_mod["folder_path"]) if selected_mod.get("folder_path") else ""

        editor = ModEditorDialog(self, is_creating=False, is_public=False, mod_data=mod_data)
        editor.exec()
        try:
            self.activateWindow(); self.raise_(); self.setFocus()
        except Exception:
            pass


    def _get_mod_status_for_chapter(self, mod: ModInfo, chapter_id: int) -> str:
        if mod.key.startswith("local_"):
            return "ready"

        if not os.path.exists(self.mods_dir):
            return "install"

        # Собираем удалённые версии по главе
        def _collect_remote_versions(m: ModInfo, ch_id: int) -> dict:
            if ch_id == -1:
                return {'demo': m.demo_version} if (m.is_valid_for_demo() and m.demo_version) else {}
            ch = m.get_chapter_data(ch_id)
            if not ch:
                return {}
            d = {}
            if ch.data_win_version:
                d['data'] = ch.data_win_version
            for ef in ch.extra_files:
                d[ef.key] = ef.version
            return d

        remote_versions = _collect_remote_versions(mod, chapter_id)
        if not remote_versions:
            return "n/a"

        for mod_folder in os.listdir(self.mods_dir):
            mod_cache_dir = os.path.join(self.mods_dir, mod_folder)
            config_path = os.path.join(mod_cache_dir, "config.json")
            if not os.path.isfile(config_path):
                continue
            try:
                config_data = self._read_json(config_path)
                if config_data.get("mod_key") == mod.key:
                    local_versions = (config_data.get("chapters", {})
                                      .get(str(chapter_id), {})
                                      .get("versions", {})) or {}
                    if not local_versions:
                        return "install"
                    # Сравниваем покомпонентно
                    # Если есть локальный компонент, которого нет на сервере — требуется обновление (удаление)
                    for k in local_versions.keys():
                        if k not in remote_versions:
                            return "update"
                    # Проверяем, что удалённые компоненты новее
                    from helpers import version_sort_key
                    for k, rv in remote_versions.items():
                        lv = local_versions.get(k)
                        if version_sort_key(rv) > version_sort_key(lv or "0.0.0"):
                            return "update"
                    return "ready"
            except Exception as e:
                logging.warning(f"Failed to parse local config {config_path}: {e}")
                continue

        return "install"

    def _is_mod_installed(self, mod_key: str) -> bool:
        if not os.path.exists(self.mods_dir):
            return False

        for mod_folder in os.listdir(self.mods_dir):
            config_path = os.path.join(self.mods_dir, mod_folder, "config.json")
            if os.path.isfile(config_path):
                try:
                    config_data = self._read_json(config_path)
                    # Проверяем и mod_key и key для совместимости
                    stored_key = config_data.get("mod_key") or config_data.get("key")
                    if stored_key == mod_key:
                        return True
                except Exception as e:
                    logging.warning(f"Failed to parse local config {config_path}: {e}")
                    continue
        return False

    def closeEvent(self, event):
        self._stop_background_music()
        self._online_timer.stop()

        if self.is_shortcut_launch:
            super().closeEvent(event)
            return

        self._cleanup_direct_launch_files()

        self._save_window_geometry()

        self._stop_presence_thread()
        try:
            from helpers import _fb_url, DATA_FIREBASE_URL
            requests.delete(
                _fb_url(DATA_FIREBASE_URL, f"stats/sessions/{self.session_id}"),
                timeout=5
            )
        except Exception:
            pass
        self._stop_fetch_thread()
        for attr in ('install_thread', 'full_install_thread', '_bg_loader', 'monitor_thread'):
            self._safe_stop_thread(getattr(self, attr, None))
        super().closeEvent(event)

    def _schedule_geometry_save(self):
        """Планирует сохранение геометрии окна с задержкой"""
        if hasattr(self, '_geometry_save_timer'):
            self._geometry_save_timer.stop()
        else:
            from PyQt6.QtCore import QTimer
            self._geometry_save_timer = QTimer()
            self._geometry_save_timer.setSingleShot(True)
            self._geometry_save_timer.timeout.connect(self._save_window_geometry)

        self._geometry_save_timer.start(500)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'launcher_icon_label') and hasattr(self, 'top_panel_widget'):
            panel_width = self.top_panel_widget.width()
            logo_width = self.launcher_icon_label.width()
            # Центрируем по горизонтали, с небольшим отступом сверху
            logo_height = self.launcher_icon_label.height()
            panel_height = self.top_panel_widget.height()
            y = max(0, (panel_height - logo_height) // 2)
            self.launcher_icon_label.move((panel_width - logo_width) // 2, y)
        self._schedule_geometry_save()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_geometry_save()

    def _load_local_data(self):
        self.local_config = self._read_json(self.config_path) or {}

    def _migrate_config_if_needed(self):
        self.local_config["cache_format_version"] = LAUNCHER_VERSION

        defaults = {
            "game_path": "", "last_selected": {}, "use_custom_executable": False,
            "demo_game_path": "", "launch_via_steam": False, "direct_launch_slot_id": -1,
            "demo_mode_enabled": False, "chapter_mode_enabled": False,
            "custom_background_path": "", "custom_executable_path": "", "background_disabled": False,
            "custom_color_background": "", "custom_color_button": "", "custom_color_border": "",
            "custom_color_button_hover": "", "custom_color_text": "", "mods_dir_path": "",
            "custom_color_version_text": "",
        }
        for key, value in defaults.items():
            self.local_config.setdefault(key, value)

        self._write_local_config()

    def _write_local_config(self):
        self._write_json(self.config_path, self.local_config)

    def _write_json(self, path: str, data):
        try:
            dir_path = os.path.dirname(path)
            os.makedirs(dir_path, exist_ok=True)
            tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except (PermissionError, OSError) as e:
            self._handle_permission_error(os.path.dirname(path))
        except Exception as e:
            self.update_status_signal.emit(tr("errors.file_write_error", error=str(e)), UI_COLORS["status_error"])

    def _read_json(self, path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            backup_path = f"{path}.invalid.bak"
            try:
                os.replace(path, backup_path)
            except OSError:
                 pass
            self.update_status_signal.emit(
                tr("dialogs.corrupted_files_found"),
                UI_COLORS["status_warning"]
            )
            return {}

    def _init_localization(self):
        """Инициализирует локализацию при запуске"""
        manager = get_localization_manager()

        # Проверяем, есть ли сохраненный язык в конфигурации
        saved_language = self.local_config.get('language', '')

        if not saved_language:
            # Если язык не сохранен (первый запуск), определяем системный язык
            detected_language = manager.detect_system_language()

            # Сохраняем определенный язык в конфигурацию
            self.local_config['language'] = detected_language
            self._write_json(self.config_path, self.local_config)

            saved_language = detected_language

        # Загружаем сохраненный язык пользователя
        if saved_language in manager.get_available_languages():
            # Загружаем только если это не тот язык, который уже загружен
            if manager.get_current_language() != saved_language:
                manager.load_language(saved_language)
        else:
            # Если сохраненный язык недоступен, используем английский
            manager.load_language('en')
            self.local_config['language'] = 'en'
            self._write_json(self.config_path, self.local_config)
            saved_language = 'en'

        # Применяем Qt переводы
        self._update_qt_translations(saved_language)

    def _update_qt_translations(self, language_code):
        """Обновляет Qt переводы для выбранного языка"""
        from PyQt6.QtCore import QLibraryInfo, QTranslator

        manager = get_localization_manager()
        qt_translation = manager.get_qt_translation_name(language_code)

        if not qt_translation:
            return

        app = QApplication.instance()
        if app is None:
            return

        # Создаем новый переводчик для этого экземпляра
        if hasattr(self, '_qt_translator') and self._qt_translator:
            app.removeTranslator(self._qt_translator)

        self._qt_translator = QTranslator()
        if self._qt_translator.load(qt_translation, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(self._qt_translator)

    def _get_selected_mod_info(self, chapter_id=None):
        if self.is_shortcut_launch: return None # Нет UI
        if chapter_id is None:
            chapter_id = self.tab_widget.currentIndex()
        if chapter_id not in self.tabs:
            return None
        combo = self.tabs[chapter_id]["combo"]
        selected_index = combo.currentIndex()
        if selected_index == 0:
            return None
        try:
            mod_key = combo.itemData(selected_index, Qt.ItemDataRole.UserRole)
        except RuntimeError:
            return None
        if not mod_key:
            return None
        all_mods_combined = self.all_mods + self._get_local_mods_as_modinfo()
        return next((mod for mod in all_mods_combined if mod.key == mod_key), None)

    def _get_executable_path(self):
        use_custom_exe = self.local_config.get("use_custom_executable", False)
        if use_custom_exe:
            custom_path = self.local_config.get(self.game_mode.get_custom_exec_config_key(), "")
            if custom_path and os.path.isfile(custom_path):
                return custom_path

        current_game_path = self._get_current_game_path()
        if not current_game_path or not os.path.isdir(current_game_path):
            return None

        system = platform.system()

        if system == "Windows":
            exe_path = os.path.join(current_game_path, "DELTARUNE.exe")
            if os.path.isfile(exe_path):
                return exe_path
        elif system == "Linux":
            exe_path = os.path.join(current_game_path, "DELTARUNE.exe")
            if os.path.isfile(exe_path):
                return exe_path

            native_path = os.path.join(current_game_path, "DELTARUNE")
            if os.path.isfile(native_path):
                return native_path
        elif system == "Darwin":
            if current_game_path.endswith(".app") and os.path.isdir(current_game_path):
                app_path = current_game_path
            else:
                app_path = None
                for name in ("DELTARUNE.app", "DELTARUNEdemo.app"):
                    candidate = os.path.join(current_game_path, name)
                    if os.path.isdir(candidate):
                        app_path = candidate
                        break
            if app_path:
                return app_path

        if not self.is_shortcut_launch:
            self.update_status_signal.emit(tr("errors.executable_not_found_deltarune"), UI_COLORS["status_error"])
        return None

    def _gather_shortcut_settings(self) -> Optional[Dict[str, Any]]:
        """Собирает текущие настройки лаунчера для сохранения в ярлык"""
        current_path = self._get_current_game_path()
        if not current_path:
            return None

        is_demo_mode = isinstance(self.game_mode, DemoGameMode)
        is_chapter_mode = hasattr(self, 'chapter_mode_checkbox') and self.chapter_mode_checkbox.isChecked()

        settings = {
            "launcher_version": LAUNCHER_VERSION,
            "game_path": self.game_path,
            "demo_game_path": self.demo_game_path,
            "is_demo_mode": is_demo_mode,
            "is_chapter_mode": is_chapter_mode,
            "launch_via_steam": self.launch_via_steam_checkbox.isChecked(),
            "use_custom_executable": self.use_custom_executable_checkbox.isChecked(),
            "custom_executable_path": self.local_config.get(FullGameMode().get_custom_exec_config_key(), ""),
            "demo_custom_executable_path": self.local_config.get(DemoGameMode().get_custom_exec_config_key(), ""),
            "direct_launch_slot_id": self.local_config.get("direct_launch_slot_id", -1),
            "mods": {}
        }

        # Собираем информацию о модах
        if is_demo_mode:
            # В демо режиме только один слот
            settings["mods"]["demo"] = self._get_current_demo_mod_key()
        elif is_chapter_mode:
            # В поглавном режиме собираем моды по слотам
            for slot_frame in self.slots.values():
                chapter_id = slot_frame.chapter_id
                if chapter_id >= 0:  # Пропускаем универсальный слот (-1)
                    mod_key = None
                    if slot_frame.assigned_mod:
                        mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None)
                    settings["mods"][str(chapter_id)] = mod_key
        else:
            # В обычном режиме собираем моды по вкладкам
            for i in range(self.tab_widget.count()):
                mod_info = self._get_selected_mod_info(i)
                mod_key = mod_info.key if mod_info else None
                settings["mods"][str(i)] = mod_key

        return settings

    def _get_current_demo_mod_key(self) -> Optional[str]:
        """Получает ключ текущего мода в демо режиме"""
        if self.tab_widget.count() > 0:
            mod_info = self._get_selected_mod_info(0)
            return mod_info.key if mod_info else None
        return None

    def _apply_shortcut_mods(self, mods_settings: Dict[str, str]):
        """Применяет моды из настроек ярлыка"""
        try:
            if not mods_settings:
                return

            is_demo_mode = isinstance(self.game_mode, DemoGameMode)

            if is_demo_mode:
                # Демо режим - один мод
                mod_key = mods_settings.get("demo")
                if mod_key and mod_key != "no_change":
                    self._apply_demo_mod(mod_key)
            else:
                # Для полной игры просто проверяем все указанные моды
                for key, mod_key in mods_settings.items():
                    if mod_key and mod_key != "no_change":
                        # Проверяем является ли ключ числом (глава/вкладка)
                        if key.isdigit():
                            self._apply_mod_by_key(mod_key)
                        elif key == "demo":
                            continue  # Пропускаем демо моды в полной игре
                        else:
                            self._apply_mod_by_key(mod_key)

        except Exception as e:
            raise Exception(tr("errors.mod_apply_error", error=str(e)))

    def _apply_demo_mod(self, mod_key: str):
        """Применяет мод в демо режиме"""
        # В демо режиме просто проверяем что мод существует
        mod_config = self._get_mod_config_by_key(mod_key)
        if not mod_config:
            raise Exception(tr("errors.mod_not_found_by_key", mod_key=mod_key))

    def _apply_mod_by_key(self, mod_key: str):
        """Проверяет существование мода по ключу"""
        mod_config = self._get_mod_config_by_key(mod_key)
        if not mod_config:
            raise Exception(tr("errors.mod_not_found_by_key", mod_key=mod_key))

        # Проверяем существование мода в папке
        mod_folder = os.path.join(self.mods_dir, mod_key)
        if not os.path.exists(mod_folder):
            mod_folder = os.path.join(self.mods_dir, mod_config.get('name', ''))
            if not os.path.exists(mod_folder):
                raise Exception(tr("errors.mod_files_not_found_by_key", mod_key=mod_key))

    def _launch_game_from_shortcut(self, launch_via_steam=False, use_custom_executable=False,
                                  custom_exec_path="", demo_custom_exec_path="", direct_launch_slot_id=-1):
        """Запускает игру из ярлыка с указанными настройками"""
        try:
            # Применяем настройки запуска
            is_demo_mode = isinstance(self.game_mode, DemoGameMode)
            current_game_path = self._get_current_game_path()

            if not current_game_path or not os.path.exists(current_game_path):
                raise Exception(tr("errors.game_files_not_found"))

            executable_path = None

            if use_custom_executable:
                # Используем кастомный исполняемый файл
                exec_path = demo_custom_exec_path if is_demo_mode else custom_exec_path
                if exec_path and os.path.exists(exec_path):
                    executable_path = exec_path
                else:
                    raise Exception(tr("errors.specified_executable_not_found"))
            else:
                # Ищем стандартный исполняемый файл
                possible_names = ["DELTARUNE.exe", "deltarune.exe", "SURVEY_PROGRAM.exe", "survey_program.exe"]
                for name in possible_names:
                    test_path = os.path.join(current_game_path, name)
                    if os.path.exists(test_path):
                        executable_path = test_path
                        break

                if not executable_path:
                    raise Exception(tr("errors.executable_not_found_simple"))

            # Запускаем игру
            if launch_via_steam:
                # Запуск через Steam
                if is_demo_mode:
                    subprocess.Popen(['cmd', '/c', 'start', 'steam://run/1671210'], shell=True)
                else:
                    subprocess.Popen(['cmd', '/c', 'start', 'steam://run/1671210'], shell=True)  # TODO: правильный ID для полной версии
            else:
                # Прямой запуск
                args = []
                if direct_launch_slot_id >= 0:
                    # Добавляем аргументы для прямого запуска главы
                    if direct_launch_slot_id == 1:
                        args.extend(['-chapter', '1'])
                    elif direct_launch_slot_id == 2:
                        args.extend(['-chapter', '2'])
                    # и т.д. для других глав

                subprocess.Popen([executable_path] + args, cwd=current_game_path)

        except Exception as e:
            raise Exception(tr("errors.launch_error_details", error=str(e)))

    def _save_shortcut(self, settings: Dict[str, Any]):
        system = platform.system()
        if system == "Windows":
            file_filter = tr("ui.windows_shortcut_filter")
            default_name = tr("ui.default_shortcut_name_bat")
        elif system == "Darwin":
            file_filter = "macOS Command Script (*.command)"
            default_name = tr("ui.default_shortcut_name_command")
        else:
            file_filter = tr("ui.desktop_shortcut_filter")
            default_name = "DELTAHUB-Deltarune.desktop"

        shortcut_path, _ = QFileDialog.getSaveFileName(self, tr("dialogs.save_shortcut"), os.path.expanduser(f"~/{default_name}"), file_filter)

        if not shortcut_path:
            return

        # Определяем путь к исполняемому файлу
        if getattr(sys, 'frozen', False):
            # Если это exe файл (собранный PyInstaller)
            launcher_executable_path = sys.executable
        else:
            # Если это Python скрипт
            launcher_executable_path = sys.executable
            main_script_path = os.path.join(os.path.dirname(__file__), "main.py")

        settings_json = json.dumps(settings)
        settings_b64 = base64.b64encode(settings_json.encode('utf-8')).decode('utf-8')

        args = f'--shortcut-launch "{settings_b64}" --shortcut-path "{shortcut_path}"'

        try:
            if system == "Windows":
                if getattr(sys, 'frozen', False):
                    # Для exe файла
                    content = f'@echo off\nstart "" "{launcher_executable_path}" {args}'
                else:
                    # Для Python скрипта
                    content = f'@echo off\nstart "" "{launcher_executable_path}" "{main_script_path}" {args}'
            elif system == "Darwin":
                content = f'#!/bin/bash\nnohup "{launcher_executable_path}" {args} > /dev/null 2>&1 &'
            else:
                icon_path = resource_path("assets/icon.ico")
                content = ("[Desktop Entry]\n"
                           "Version=1.0\n"
                           "Type=Application\n"
                           f"Name=Deltarune (DELTAHUB)\n"
                           f'Exec="{launcher_executable_path}" {args}\n'
                           f"Icon={icon_path}\n"
                           "Terminal=false\n")
            with open(shortcut_path, 'w', encoding='utf-8') as f:
                f.write(content)

            if system in ["Linux", "Darwin"]:
                os.chmod(shortcut_path, 0o755)

            QMessageBox.information(self, tr("dialogs.success"), tr("dialogs.shortcut_created_successfully", path=shortcut_path))

        except Exception as e:
            self.update_status_signal.emit(tr("status.shortcut_creation_error", error=str(e)), UI_COLORS["status_error"])
            QMessageBox.critical(self, tr("errors.error"), tr("errors.shortcut_creation_failed", error=str(e)))

    def _cleanup_deleted_local_mods(self):
        # Эта функция больше не нужна, так как всё работает через config.json в папках модов
        pass

    def _populate_ui_with_mods(self):
        last_selected_map = self.local_config.get("last_selected", {})

        self._cleanup_deleted_local_mods()

        all_mods_combined = self.all_mods + self._get_local_mods_as_modinfo()
        mods_for_chapter = self.game_mode.filter_mods_for_ui(all_mods_combined)

        for chapter_idx, combo_box_info in self.tabs.items():
            combo = combo_box_info['combo']
            mods = mods_for_chapter.get(chapter_idx, [])
            mods.sort(key=lambda m: m.downloads, reverse=True)

            combo.blockSignals(True)
            combo.clear()

            combo.addItem(tr("dropdowns.no_changes"))
            combo.setItemData(0, QBrush(QColor("gray")), Qt.ItemDataRole.ForegroundRole)

            for idx, mod in enumerate(mods, start=1):
                combo.addItem(mod.name)
                combo.setItemData(idx, mod.key, Qt.ItemDataRole.UserRole)
                chapter_id = self.game_mode.get_chapter_id(chapter_idx)
                status = self._get_mod_status_for_chapter(mod, chapter_id)

                status_color_map = {
                    "ready": "lightgreen", "update": "orange", "install": "white"
                }
                color = QColor(status_color_map.get(status, "gray")) # gray для n/a
                combo.setItemData(idx, QBrush(QColor(color)), Qt.ItemDataRole.ForegroundRole)

            last_selected_name = last_selected_map.get(str(chapter_idx))
            index_to_select = combo.findText(last_selected_name) if last_selected_name else -1
            combo.setCurrentIndex(max(0, index_to_select))
            current_font = self.font()
            combo.setFont(current_font)
            combo.view().setFont(current_font)
            combo.setEnabled(True)
            combo.blockSignals(False)
        self._update_ui_for_selection()

    def _get_local_mods_as_modinfo(self):
        # Локальные моды уже загружены в self.all_mods функцией _load_local_mods_from_folders
        # Эта функция теперь просто возвращает пустой список, так как локальные моды
        # обрабатываются в _load_local_mods_from_folders
        return []

    def _get_target_dir(self, chapter_id):
        target_base = self._get_current_game_path()
        if not target_base: return None
        if platform.system() == "Darwin":
            if not target_base.endswith(".app"):
                for app_name in ("DELTARUNE.app", "DELTARUNEdemo.app"):
                    candidate = os.path.join(target_base, app_name)
                    if os.path.isdir(candidate):
                        target_base = candidate
                        break
            target_base = os.path.join(target_base, "Contents", "Resources")
            if not os.path.isdir(target_base):
                return None
        if chapter_id == -1:
            return target_base
        if chapter_id == 0:
            return target_base
        chapter_prefix = f"chapter{chapter_id}_"
        try:
            for entry in os.listdir(target_base):
                if os.path.isdir(os.path.join(target_base, entry)) and entry.startswith(chapter_prefix):
                    return os.path.join(target_base, entry)
            return None
        except Exception as e:
            self.update_status_signal.emit(tr("errors.chapter_folder_search_error", error=str(e)), UI_COLORS["status_error"])
            return None

    def _has_mods_with_data_files(self, selections: Dict[int, str]) -> bool:
        all_mods_combined = self.all_mods + self._get_local_mods_as_modinfo()

        for ui_index, mod_key in selections.items():
            if mod_key == "no_change":
                continue

            mod = next((m for m in all_mods_combined if m.key == mod_key), None)
            if not mod:
                continue

            chapter_id = self.game_mode.get_chapter_id(ui_index)

            if mod_key.startswith("local_"):
                mod_config = self._get_mod_config_by_key(mod_key)
                if mod_config:
                    chapter_files = mod_config.get("files", {}).get(str(chapter_id), {})
                    if chapter_files.get("data_win_url"):
                        return True
            else:
                chapter_data = mod.get_chapter_data(chapter_id)
                if chapter_data and hasattr(chapter_data, 'data_file_url') and chapter_data.data_file_url:
                    return True

        return False

    def _find_and_validate_game_path(self, selections: Optional[Dict[int, str]] = None):
        path_from_config = self._get_current_game_path()

        skip_data_check = bool(selections and self._has_mods_with_data_files(selections))

        if is_valid_game_path(path_from_config, skip_data_check):
            self.update_status_signal.emit(tr("status.game_path", path=path_from_config), UI_COLORS["status_info"])
            return True
        self.update_status_signal.emit(tr("status.autodetecting_path"), UI_COLORS["status_info"])
        autodetected_path = autodetect_path("DELTARUNEdemo" if isinstance(self.game_mode, DemoGameMode) else "DELTARUNE")


        if autodetected_path and is_valid_game_path(autodetected_path, skip_data_check):
            self.game_mode.set_game_path(self.local_config, autodetected_path)
            self.update_status_signal.emit(tr("status.game_folder_found", path=autodetected_path), UI_COLORS["status_success"])
            self._write_local_config()
            return True

        return self._prompt_for_game_path(is_initial=True)

    def _prompt_for_game_path(self, is_initial=False):
        title = tr("dialogs.select_demo_folder") if isinstance(self.game_mode, DemoGameMode) else tr("dialogs.select_deltarune_folder")
        message = tr("dialogs.demo_not_found") if isinstance(self.game_mode, DemoGameMode) else tr("dialogs.deltarune_not_found")
        if is_initial:
            QMessageBox.information(
                self,
                tr("dialogs.path_not_found"),
                tr("dialogs.game_path_instruction", message=message)
            )

        if platform.system() == "Darwin":
            path, _ = QFileDialog.getOpenFileName(
                self,
                title,
                "",
                "Application bundle (*.app);;All files (*)",
            )
            if not path:
                path = QFileDialog.getExistingDirectory(self, title)
        else:
            path = QFileDialog.getExistingDirectory(self, title)
        if path:
            # На macOS, если пользователь выбрал папку, содержащую .app,
            # автоматически корректируем путь до самого .app
            corrected_path = path
            if platform.system() == "Darwin" and not path.endswith(".app"):
                for app_name in ("DELTARUNE.app", "DELTARUNEdemo.app"):
                    candidate = os.path.join(path, app_name)
                    if os.path.isdir(candidate):
                        corrected_path = candidate
                        break
            if is_valid_game_path(corrected_path):
                self.game_mode.set_game_path(self.local_config, corrected_path)
                self._write_local_config()
                self.update_status_signal.emit(tr("status.game_path_set", path=corrected_path), UI_COLORS["status_success"])
                self._update_ui_for_selection()
                return True
            else:
                QMessageBox.warning(self, tr("dialogs.invalid_folder"), tr("dialogs.invalid_game_folder"))
        if is_initial:
            # Запускаем фоновую музыку если есть пользовательский файл
            self._start_background_music()
            self.initialization_finished.emit()
            self.update_status_signal.emit(tr("status.no_game_path"), UI_COLORS["status_error"])

    def _save_slots_state(self):
        """Сохраняет текущее состояние слотов в конфиг"""
        # Определяем текущий режим
        is_chapter_mode = self.chapter_mode_checkbox.isChecked()
        is_demo_mode = isinstance(self.game_mode, DemoGameMode)

        if is_demo_mode:
            mode = 'demo'
        elif is_chapter_mode:
            mode = 'chapter'
        else:
            mode = 'normal'

        self._save_slots_state_for_mode(mode)

    def _save_slots_state_for_mode(self, mode):
        """Сохраняет текущее состояние слотов для указанного режима"""
        slots_data = {}

        for slot_id, slot_frame in self.slots.items():
            if slot_frame.assigned_mod:
                # Сохраняем ключ мода и имя для совместимости
                mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if mod_key:
                    # Преобразуем числовой ключ слота в строку для JSON
                    slots_data[str(slot_id)] = {
                        'mod_key': mod_key,
                        'mod_name': slot_frame.assigned_mod.name,
                        'chapter_id': slot_frame.chapter_id
                    }

        # Определяем ключ конфига для указанного режима
        if mode == 'demo':
            config_key = 'saved_slots_demo'
        elif mode == 'chapter':
            config_key = 'saved_slots_chapter'
        else:
            config_key = 'saved_slots_normal'

        self.local_config[config_key] = slots_data
        self._write_local_config()


    def _load_slots_state(self, mode=None):
        """Загружает сохраненное состояние слотов из конфига"""

        # Определяем режим для загрузки
        if mode is None:
            # Загружаем слоты в зависимости от текущего режима
            is_chapter_mode = self.chapter_mode_checkbox.isChecked()
            is_demo_mode = isinstance(self.game_mode, DemoGameMode)

            if is_demo_mode:
                mode = 'demo'
            elif is_chapter_mode:
                mode = 'chapter'
            else:
                mode = 'normal'

        # Определяем ключ конфига для загрузки
        if mode == 'demo':
            config_key = 'saved_slots_demo'
        elif mode == 'chapter':
            config_key = 'saved_slots_chapter'
        else:
            config_key = 'saved_slots_normal'


        slots_data = self.local_config.get(config_key, {})


        if not slots_data:

            return

        for slot_id, slot_data in slots_data.items():
            # Преобразуем строковый ключ в числовой
            try:
                numeric_slot_id = int(slot_id)
            except ValueError:
                continue

            # Проверяем совместимость слота с загружаемым режимом
            if mode == 'chapter':
                # В поглавном режиме только слоты 0, 1, 2, 3, 4
                if numeric_slot_id not in [0, 1, 2, 3, 4]:
                    continue
            elif mode == 'demo':
                # В демо режиме только слот -2
                if numeric_slot_id != -2:
                    continue
            else:
                # В обычном режиме только слот -1
                if numeric_slot_id != -1:
                    continue

            if numeric_slot_id not in self.slots:
                continue

            slot_frame = self.slots[numeric_slot_id]
            mod_key = slot_data.get('mod_key')

            if not mod_key:
                continue

            # Сначала ищем среди загруженных модов (all_mods), затем среди установленных
            mod_data = None

            # Поиск в all_mods (загруженные с сервера)
            if hasattr(self, 'all_mods') and self.all_mods:
                for mod in self.all_mods:
                    if getattr(mod, 'key', None) == mod_key:
                        mod_data = mod
                        break

            # Если не найден в all_mods, ищем среди установленных
            if not mod_data:
                installed_mods = self._get_installed_mods_list()
                for installed_mod in installed_mods:
                    installed_mod_key = installed_mod.get('mod_key') or installed_mod.get('key') or installed_mod.get('name')
                    if installed_mod_key == mod_key:
                        mod_data = self._create_mod_object_from_info(installed_mod)
                        break

            if mod_data:
                # Проверяем, что мод еще не в другом слоте
                current_slot = self._find_mod_in_slots(mod_data)
                if not current_slot:
                    self._assign_mod_to_slot(slot_frame, mod_data, save_state=False)

        # После загрузки всех слотов обновляем статусы и кнопки
        QTimer.singleShot(100, self._refresh_slots_content)
        QTimer.singleShot(200, self._update_mod_widgets_slot_status)
        QTimer.singleShot(300, self._refresh_all_slot_status_displays)
        QTimer.singleShot(300, self._update_ui_for_selection)

    def _is_mod_in_specific_slot(self, mod_data, chapter_id):
        """Проверяет, находится ли мод в конкретном слоте главы"""
        if not mod_data:
            return False

        # Получаем уникальный идентификатор мода для сравнения
        mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
        if not mod_key:
            return False

        # Ищем слот для этой главы
        for slot_frame in self.slots.values():
            if slot_frame.chapter_id == chapter_id and slot_frame.assigned_mod:
                assigned_mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if assigned_mod_key == mod_key:
                    return True
        return False

class FetchHelpContentThread(QThread):
    finished = pyqtSignal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            import requests
            response = requests.get(self.url, timeout=10)
            if response.ok:
                content = response.text
                self.finished.emit(content)
            else:
                self.finished.emit(f"<i>{tr('errors.load_error_http', code=response.status_code)}</i>")
        except Exception as e:
            print(f"Error loading help content: {e}")
            self.finished.emit(f"<i>{tr('dialogs.help_content_load_failed')}</i>")
