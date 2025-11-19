import os
from PyQt6.QtCore import Qt, QThreadPool
import weakref
from PyQt6 import sip
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QPushButton, QGroupBox
from managers.localization_manager import tr


def generate_widget_style(frame_selector, bg_color, border_color, hover_border_color, text_color, version_text_color, is_selected=False, icon_selector='modIcon'):
    border_width = '3px' if is_selected else '1px'
    current_border_color = hover_border_color if is_selected else border_color
    return f'\n        QFrame#{frame_selector} {{\n            background-color: {bg_color};\n            border: {border_width} solid {current_border_color};\n        }}\n        QFrame#{frame_selector}:hover {{\n            border-color: {hover_border_color};\n        }}\n        QLabel#{icon_selector} {{\n            border: 2px solid {border_color};\n        }}\n        QLabel#versionLabel {{\n            color: {version_text_color};\n        }}\n        QLabel#secondaryText {{\n            color: {version_text_color};\n            font-size: 12px;\n        }}\n        QLabel#primaryText {{\n            color: {text_color};\n            font-size: 12px;\n        }}\n        QPushButton#plaqueButton, QPushButton#plaqueButtonInstall, QPushButton#plaqueButtonUninstall {{\n            min-width: 110px;\n            max-width: 110px;\n            min-height: 35px;\n            max-height: 35px;\n            font-size: 15px;\n            padding: 1px;\n        }}\n        QPushButton#plaqueButtonInstall {{\n            background-color: #4CAF50;\n            font-weight: bold;\n        }}\n        QPushButton#plaqueButtonInstall:hover {{\n            background-color: #5cb85c;\n        }}\n    '


def update_mod_widget_style(widget, frame_selector, parent_app=None):
    config = None
    if parent_app:
        if hasattr(parent_app, 'local_config'):
            config = parent_app.local_config
        elif hasattr(parent_app, 'app_state') and hasattr(parent_app.app_state, 'local_config'):
            config = parent_app.app_state.local_config
    if config:
        plaque_bg_color = get_theme_color(config, 'background', '#000000')
        border_color = get_theme_color(config, 'border', '#fff')
        hover_border_color = get_theme_color(config, 'button_hover', '#fff')
        text_color = get_theme_color(config, 'text', '#ffffff')
        version_text_color = get_theme_color(config, 'version_text', 'rgba(255, 255, 255, 178)')
    else:
        plaque_bg_color = '#000000'
        border_color = '#fff'
        hover_border_color = '#fff'
        text_color = '#ffffff'
        version_text_color = 'rgba(255, 255, 255, 178)'
    is_selected = getattr(widget, 'is_selected', False)
    icon_selector = 'pluginIcon' if frame_selector == 'pluginWidget' else 'modIcon'
    widget.setStyleSheet(generate_widget_style(frame_selector, plaque_bg_color, border_color, hover_border_color, text_color, version_text_color, is_selected, icon_selector))


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
    widgets_to_remove = []
    for i in reversed(range(end_index)):
        item = layout.itemAt(i)
        if item:
            widget = item.widget()
            if widget:
                widgets_to_remove.append(widget)
            else:
                layout.removeItem(item)
    for widget in widgets_to_remove:
        try:
            layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        except (RuntimeError, AttributeError):
            pass


def load_mod_icon_universal(icon_label, mod_data, size=80):
    from utils.path_utils import resource_path
    assets_icon_path = resource_path('assets/icons/icon.ico')
    default_pixmap = None
    for default_icon_path in (assets_icon_path,):
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
        icon_path = getattr(mod_data, 'icon_path', None)
        icon_url = getattr(mod_data, 'icon_url', None)
        local_icon_to_load = None
        if icon_url and (not icon_url.startswith(('http://', 'https://'))):
            local_icon_to_load = icon_url
        elif icon_path:
            local_icon_to_load = icon_path
        if local_icon_to_load and os.path.exists(local_icon_to_load):
            pixmap = QPixmap(local_icon_to_load)
            if not pixmap.isNull():
                icon_size = min(pixmap.width(), pixmap.height())
                cropped = pixmap.copy((pixmap.width() - icon_size) // 2, (pixmap.height() - icon_size) // 2, icon_size, icon_size)
                scaled_pixmap = cropped.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                icon_label.setPixmap(scaled_pixmap)
                return
        if icon_url and isinstance(icon_url, str) and icon_url.startswith(('http://', 'https://')):
            try:
                from workers import WorkerSignals
                from utils.image_loader import ImageLoaderRunnable
                pool = QThreadPool.globalInstance()
                signals = WorkerSignals(icon_label)
                label_ref = weakref.ref(icon_label)

                def _on_loaded_image(img):
                    try:
                        lbl = label_ref()
                        if not lbl:
                            return
                        if sip.isdeleted(lbl):
                            return
                        if img is not None and (not getattr(img, 'isNull', lambda: True)()):
                            pm = QPixmap.fromImage(img)
                            if not pm.isNull():
                                icon_size = min(pm.width(), pm.height())
                                cropped = pm.copy((pm.width() - icon_size) // 2, (pm.height() - icon_size) // 2, icon_size, icon_size)
                                scaled_pixmap = cropped.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                                lbl.setPixmap(scaled_pixmap)
                    except Exception:
                        pass

                def _on_error(url, err):
                    pass
                signals.result.connect(_on_loaded_image)
                signals.error.connect(_on_error)
                runnable = ImageLoaderRunnable(icon_url, signals)
                setattr(icon_label, '_icon_loader_signals', signals)
                setattr(icon_label, '_icon_loader_runnable', runnable)

                def _cleanup_refs():
                    try:
                        signals.result.disconnect(_on_loaded_image)
                        signals.error.disconnect(_on_error)
                    except (TypeError, RuntimeError):
                        pass
                    try:
                        if hasattr(icon_label, '_icon_loader_signals'):
                            delattr(icon_label, '_icon_loader_signals')
                        if hasattr(icon_label, '_icon_loader_runnable'):
                            delattr(icon_label, '_icon_loader_runnable')
                    except Exception:
                        pass
                    try:
                        if pool is not None and pool.activeThreadCount() > 0:
                            pool.waitForDone(1000)
                    except Exception:
                        pass
                try:
                    icon_label.destroyed.connect(_cleanup_refs)
                except Exception:
                    pass
                if pool is not None:
                    pool.start(runnable)
            except Exception:
                pass
    except Exception:
        pass
