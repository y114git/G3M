import os
import io
from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QPushButton, QGroupBox
from localization.manager import tr

def update_mod_widget_style(widget, frame_selector, parent_app=None):
    if parent_app and hasattr(parent_app, 'local_config'):
        config = parent_app.local_config
        plaque_bg_color = get_theme_color(config, 'button', 'black')
        border_color = get_theme_color(config, 'border', '#fff')
        hover_border_color = get_theme_color(config, 'button_hover', '#fff')
        version_text_color = get_theme_color(config, 'version_text', 'rgba(255, 255, 255, 178)')
    else:
        plaque_bg_color = 'black'
        border_color = '#fff'
        hover_border_color = '#fff'
        version_text_color = 'rgba(255, 255, 255, 178)'
    border_width = '3px' if getattr(widget, 'is_selected', False) else '1px'
    current_border_color = hover_border_color if getattr(widget, 'is_selected', False) else border_color
    widget.setStyleSheet(f'\n        QFrame#{frame_selector} {{\n            background-color: {plaque_bg_color};\n            border: {border_width} solid {current_border_color};\n        }}\n        QFrame#{frame_selector}:hover {{\n            border-color: {hover_border_color};\n        }}\n        QLabel#modIcon {{\n            border: 2px solid {border_color};\n        }}\n        QLabel#versionLabel {{\n            color: {version_text_color};\n        }}\n        QLabel#secondaryText {{\n            color: {version_text_color};\n            font-size: 12px;\n        }}\n        QLabel#primaryText {{\n            color: white;\n            font-size: 12px;\n        }}\n        QPushButton#plaqueButton, QPushButton#plaqueButtonInstall {{\n            min-width: 110px;\n            max-width: 110px;\n            min-height: 35px;\n            max-height: 35px;\n            font-size: 15px;\n            padding: 1px;\n        }}\n        QPushButton#plaqueButtonInstall {{\n            background-color: #4CAF50;\n            font-weight: bold;\n        }}\n        QPushButton#plaqueButtonInstall:hover {{\n            background-color: #5cb85c;\n        }}\n    ')

def show_empty_message_in_layout(layout, text, local_config=None, font_size=16):
    empty_text_color = 'rgba(255, 255, 255, 178)'
    if local_config:
        empty_text_color = get_theme_color(local_config, 'version_text', empty_text_color)
    empty_label = QLabel(text)
    empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    empty_label.setStyleSheet(f'\n        QLabel {{\n            color: {empty_text_color};\n            font-size: {font_size}px;\n            font-style: italic;\n            opacity: 0.75;\n            background-color: transparent;\n            padding: 40px;\n        }}\n    ')
    layout.insertWidget(layout.count() - 1, empty_label)

def get_theme_color(config, color_key, default_color):
    if config and hasattr(config, 'get'):
        return config.get(f'custom_color_{color_key}') or default_color
    return default_color

def create_file_group_universal(label_text, button_text, file_filter, line_edit, mode='open'):
    group_box = QGroupBox(label_text)
    layout = QVBoxLayout(group_box)
    if mode == 'open':
        line_edit.setReadOnly(True)
        line_edit.setPlaceholderText(tr('ui.select_file'))
    else:
        line_edit.setPlaceholderText(tr('ui.file_path_placeholder'))
    button = QPushButton(button_text)
    layout.addWidget(line_edit)
    layout.addWidget(button)
    return (group_box, button)

def clear_layout_widgets(layout, keep_last_n=1):
    if not layout:
        return
    end_index = layout.count() - keep_last_n
    for i in reversed(range(end_index)):
        item = layout.itemAt(i)
        if item:
            widget = item.widget()
            if widget:
                widget.setParent(None)

def load_mod_icon_universal(icon_label, mod_data, size=80):
    from utils.file_utils import resource_path
    assets_icon_path = resource_path('icons/icon.ico')
    fallback_icon_path = os.path.join(os.path.dirname(__file__), 'icon.ico')
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
        default_pixmap.fill(QColor('#333'))
    icon_label.setPixmap(default_pixmap)
    try:
        pixmap = None
        icon_path = getattr(mod_data, 'icon_path', None)
        if icon_path and os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                icon_size = min(pixmap.width(), pixmap.height())
                cropped = pixmap.copy((pixmap.width() - icon_size) // 2, (pixmap.height() - icon_size) // 2, icon_size, icon_size)
                scaled_pixmap = cropped.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                icon_label.setPixmap(scaled_pixmap)
                return
        elif getattr(mod_data, 'icon_url', None):
            icon_url = mod_data.icon_url
            if isinstance(icon_url, str) and icon_url.startswith(('http://', 'https://')):
                from PyQt6.QtCore import QThread, pyqtSignal

                class _IconLoader(QThread):
                    loaded = pyqtSignal(object)
                    failed = pyqtSignal(str)

                    def __init__(self, url):
                        super().__init__()
                        self.url = url

                    def run(self):
                        try:
                            from utils.cache import _PIX_CACHE, _IMG_CACHE_LOCK, _NET_SEM
                            if _PIX_CACHE is not None and _IMG_CACHE_LOCK is not None:
                                with _IMG_CACHE_LOCK:
                                    if self.url in _PIX_CACHE:
                                        self.loaded.emit(_PIX_CACHE[self.url])
                                        return
                            import requests
                            if _NET_SEM:
                                _NET_SEM.acquire()
                            try:
                                resp = requests.get(self.url, timeout=8)
                            finally:
                                try:
                                    if _NET_SEM:
                                        _NET_SEM.release()
                                except Exception:
                                    pass
                            resp.raise_for_status()
                            try:
                                image_data = io.BytesIO(resp.content)
                                pil_img = Image.open(image_data)
                                if 'icc_profile' in pil_img.info:
                                    del pil_img.info['icc_profile']
                                buffer = io.BytesIO()
                                pil_img.save(buffer, format='PNG')
                                processed_content = buffer.getvalue()
                            except Exception:
                                processed_content = resp.content
                            img = QImage()
                            if img.loadFromData(processed_content):
                                pm = QPixmap.fromImage(img)
                                if _PIX_CACHE is not None:
                                    try:
                                        if _IMG_CACHE_LOCK is not None:
                                            _IMG_CACHE_LOCK.acquire()
                                        _PIX_CACHE[self.url] = pm
                                    except Exception:
                                        pass
                                    finally:
                                        try:
                                            if _IMG_CACHE_LOCK is not None:
                                                _IMG_CACHE_LOCK.release()
                                        except Exception:
                                            pass
                                self.loaded.emit(pm)
                            else:
                                self.failed.emit('decode')
                        except Exception as e:
                            self.failed.emit(str(e))
                worker = _IconLoader(icon_url)
                setattr(icon_label, '_icon_loader', worker)

                def safe_cleanup():
                    try:
                        if worker and (not sip.isdeleted(worker)):
                            worker.requestInterruption()
                            worker.quit()
                            worker.wait(1000)
                    except Exception:
                        pass
                try:
                    icon_label.destroyed.connect(safe_cleanup)
                except Exception:
                    pass

                def _on_loaded(pm: QPixmap):
                    try:
                        if pm and (not pm.isNull()):
                            icon_size = min(pm.width(), pm.height())
                            cropped = pm.copy((pm.width() - icon_size) // 2, (pm.height() - icon_size) // 2, icon_size, icon_size)
                            scaled_pixmap = cropped.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                            icon_label.setPixmap(scaled_pixmap)
                    except Exception as e:
                        print(f'Error applying mod icon: {e}')

                def _on_failed(err: str):
                    print(f'Icon load failed: {err}')
                worker.loaded.connect(_on_loaded)
                worker.failed.connect(_on_failed)
                worker.start()
    except Exception as e:
        print(f'Error loading mod icon: {e}')