"""UI styling utilities and theme management."""
import os
import logging
from PyQt6.QtCore import Qt, QThreadPool
import weakref
from PyQt6 import sip
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QLabel
_STYLE_TEMPLATE = 'QFrame#{frame_selector} {{\n    background-color: {bg_color};\n    border: {border_width} solid {border_color};\n}}\nQFrame#{frame_selector}:hover {{\n    border-color: {hover_border_color};\n}}\nQLabel#{icon_selector} {{\n    border: 2px solid {border_color};\n}}\nQLabel#versionLabel {{\n    color: {version_text_color};\n}}\nQLabel#secondaryText {{\n    color: {version_text_color};\n    font-size: 12px;\n}}\nQLabel#primaryText {{\n    color: {text_color};\n    font-size: 12px;\n}}\nQPushButton#plaqueButton, QPushButton#plaqueButtonInstall, QPushButton#plaqueButtonUninstall {{\n    min-width: 110px;\n    max-width: 110px;\n    min-height: 35px;\n    max-height: 35px;\n    font-size: 15px;\n    padding: 1px;\n}}\nQPushButton#plaqueButtonInstall {{\n    background-color: #4CAF50;\n    font-weight: bold;\n}}\nQPushButton#plaqueButtonInstall:hover {{\n    background-color: #5cb85c;\n}}\nQPushButton#plaqueButtonUninstall {{\n    background-color: #F44336;\n    font-weight: bold;\n}}\nQPushButton#plaqueButtonUninstall:hover {{\n    background-color: #d32f2f;\n}}'


def generate_widget_style(frame_selector, bg_color, border_color, hover_border_color, text_color, version_text_color, is_selected=False, icon_selector='modIcon'):
    border_width = '3px' if is_selected else '1px'
    current_border_color = hover_border_color if is_selected else border_color
    return _STYLE_TEMPLATE.format(frame_selector=frame_selector, bg_color=bg_color, border_width=border_width, border_color=current_border_color, hover_border_color=hover_border_color, icon_selector=icon_selector, version_text_color=version_text_color, text_color=text_color)


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


_EMPTY_MESSAGE_STYLE = 'QLabel {{\n    color: {color};\n    font-size: {font_size}px;\n    font-style: italic;\n    opacity: 0.75;\n    background-color: transparent;\n    padding: 40px;\n}}'


def show_empty_message_in_layout(layout, text, local_config=None, font_size=16):
    empty_text_color = 'rgba(255, 255, 255, 178)'
    if local_config:
        empty_text_color = get_theme_color(local_config, 'version_text', empty_text_color)
    parent = layout.parentWidget() if hasattr(layout, 'parentWidget') else None
    empty_label = QLabel(text, parent)
    empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    empty_label.setStyleSheet(_EMPTY_MESSAGE_STYLE.format(color=empty_text_color, font_size=font_size))
    layout.insertWidget(layout.count() - 1, empty_label)


def get_theme_color(config, color_key, default_color):
    if config and hasattr(config, 'get'):
        return config.get(f'custom_color_{color_key}') or default_color
    return default_color


def rgba_from_color(color: str, alpha: int = 128, fallback: str = 'rgba(0, 0, 0, 128)') -> str:
    if isinstance(color, str) and color.startswith('#') and (len(color) >= 7):
        try:
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            return f'rgba({r}, {g}, {b}, {alpha})'
        except ValueError:
            return fallback
    return fallback


def build_tag_checkbox_style(text_color: str, font_size: int = 12, indicator_size: int = 16, spacing: int = 5) -> str:
    return f'\n            QCheckBox {{\n                color: {text_color};\n                font-size: {font_size}px;\n                spacing: {spacing}px;\n            }}\n            QCheckBox::indicator {{\n                width: {indicator_size}px;\n                height: {indicator_size}px;\n            }}\n        '


def clear_layout_widgets(layout, keep_last_n=1, hide_instead_of_delete=False):
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
            if hide_instead_of_delete:
                widget.hide()
                widget.setParent(None)
            else:
                widget.setParent(None)
                widget.deleteLater()
        except (RuntimeError, AttributeError) as e:
            logging.debug(f'clear_layout_widgets: Error removing widget: {e}')


def load_mod_icon_universal(icon_label, mod_data, size=80):
    from utils.path_utils import resource_path

    def _crop_and_scale_pixmap(pixmap, allow_empty=False):
        icon_size = min(pixmap.width(), pixmap.height())
        if icon_size <= 0 and allow_empty:
            return pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        cropped = pixmap.copy((pixmap.width() - icon_size) // 2, (pixmap.height() - icon_size) // 2, icon_size, icon_size)
        return cropped.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    assets_icon_path = resource_path('assets/icons/icon.ico')
    default_pixmap = None
    for default_icon_path in (assets_icon_path,):
        if os.path.exists(default_icon_path):
            try:
                default_pixmap = QPixmap(default_icon_path)
                if not default_pixmap.isNull():
                    default_pixmap = _crop_and_scale_pixmap(default_pixmap, allow_empty=True)
                    break
            except Exception as e:
                logging.debug(f'load_mod_icon_universal: Error loading default icon from {default_icon_path}: {e}')
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
            if os.path.isabs(icon_url):
                local_icon_to_load = icon_url
            else:
                key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None)
                is_local_key = key and isinstance(key, str) and key.startswith('local_')
                if is_local_key:
                    mod_folder_path = None
                    try:
                        if hasattr(mod_data, 'folder_path'):
                            mod_folder_path = mod_data.folder_path
                    except Exception as e:
                        logging.debug(f'load_mod_icon_universal: Error getting folder_path from mod_data: {e}')
                    if mod_folder_path and os.path.isdir(mod_folder_path):
                        resolved_path = os.path.normpath(os.path.join(mod_folder_path, icon_url))
                        if os.path.exists(resolved_path):
                            local_icon_to_load = resolved_path
                        else:
                            local_icon_to_load = icon_url
                    else:
                        local_icon_to_load = icon_url
                else:
                    local_icon_to_load = icon_url
        elif icon_path:
            local_icon_to_load = icon_path
        if local_icon_to_load and os.path.exists(local_icon_to_load):
            try:
                pixmap = QPixmap(local_icon_to_load)
                if not pixmap.isNull():
                    scaled_pixmap = _crop_and_scale_pixmap(pixmap)
                    icon_label.setPixmap(scaled_pixmap)
                    return
            except Exception as e:
                logging.debug(f'load_mod_icon_universal: Error loading pixmap from {local_icon_to_load}: {e}')
        if icon_url and isinstance(icon_url, str) and icon_url.startswith(('http://', 'https://')):
            try:
                from workers import WorkerSignals
                from ui.utils.image_loader import ImageLoaderRunnable
                pool = QThreadPool.globalInstance()
                signals = WorkerSignals(icon_label)
                label_ref = weakref.ref(icon_label)

                def _on_loaded_image(img):
                    try:
                        lbl = label_ref()
                        if not lbl:
                            return
                        try:
                            if sip.isdeleted(lbl):
                                return
                        except (RuntimeError, AttributeError):
                            return
                        try:
                            if not hasattr(lbl, 'parent') or (hasattr(lbl, 'parent') and lbl.parent() is None and (not hasattr(lbl, 'window'))):
                                pass
                        except (RuntimeError, AttributeError):
                            return
                        if img is not None and (not getattr(img, 'isNull', lambda: True)()):
                            pm = QPixmap.fromImage(img)
                            if not pm.isNull():
                                scaled_pixmap = _crop_and_scale_pixmap(pm)
                                lbl.setPixmap(scaled_pixmap)
                    except (RuntimeError, AttributeError) as e:
                        logging.debug(f'load_mod_icon_universal: Widget deleted during image load: {e}')
                    except Exception as e:
                        logging.debug(f'load_mod_icon_universal: Error setting pixmap: {e}')

                def _on_error(url, err):
                    logging.debug(f'load_mod_icon_universal: Failed to load image from URL {url}: {err}')
                signals.result.connect(_on_loaded_image)
                signals.error.connect(_on_error)
                runnable = ImageLoaderRunnable(icon_url, signals)
                setattr(icon_label, '_icon_loader_signals', signals)
                setattr(icon_label, '_icon_loader_runnable', runnable)

                def _cleanup_refs():
                    try:
                        signals.result.disconnect(_on_loaded_image)
                        signals.error.disconnect(_on_error)
                    except (TypeError, RuntimeError) as e:
                        logging.debug(f'load_mod_icon_universal: Error disconnecting signals in cleanup: {e}')
                    try:
                        if hasattr(icon_label, '_icon_loader_signals'):
                            delattr(icon_label, '_icon_loader_signals')
                        if hasattr(icon_label, '_icon_loader_runnable'):
                            delattr(icon_label, '_icon_loader_runnable')
                    except Exception as e:
                        logging.debug(f'load_mod_icon_universal: Error cleaning up icon loader attributes: {e}')
                    try:
                        if pool is not None and pool.activeThreadCount() > 0:
                            pool.waitForDone(1000)
                    except Exception as e:
                        logging.debug(f'load_mod_icon_universal: Error waiting for pool in cleanup: {e}')
                try:
                    icon_label.destroyed.connect(_cleanup_refs)
                except Exception as e:
                    logging.debug(f'load_mod_icon_universal: Error connecting destroyed signal: {e}')
                if pool is not None:
                    pool.start(runnable)
            except Exception as e:
                logging.debug(f'load_mod_icon_universal: Error setting up async icon loader for {icon_url}: {e}')
    except Exception as e:
        logging.debug(f'load_mod_icon_universal: Unexpected error: {e}')
