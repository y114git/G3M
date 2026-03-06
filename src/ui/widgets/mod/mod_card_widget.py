import threading
from typing import Optional
from PyQt6.QtCore import pyqtSignal, Qt, QThread
from PyQt6.QtWidgets import QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QFrame, QWidget
from .base_mod_widget import BaseModWidget
from services.localization_service import tr
from ui.common.styling import get_theme_color, get_border_radius
from utils.mod_utils import get_mod_key
import logging
from ui.utils.ui_utils import UIAnimator


class CompatibilityCheckThread(QThread):
    _semaphore = threading.Semaphore(3)
    compatibility_checked = pyqtSignal(object, dict)

    def __init__(self, mod_data, parent=None):
        super().__init__(parent)
        self.mod_data = mod_data

    def run(self):
        if not self._semaphore.acquire(timeout=15):
            return
        try:
            if self.isInterruptionRequested():
                return
            key = get_mod_key(self.mod_data)
            if not key or not key.startswith('gb_'):
                return
            mod_id = key.replace('gb_', '', 1)
            if not mod_id:
                return
            from adapters.gamebanana_adapter import GameBananaAPI
            cached = GameBananaAPI._compatibility_cache.get(int(mod_id))
            if cached:
                self.compatibility_checked.emit(self.mod_data, cached)
                return
            api = GameBananaAPI()
            if self.isInterruptionRequested():
                return
            external_url = getattr(self.mod_data, 'external_url', None)
            compat = api.get_supported_files_for_mod(int(mod_id), external_url=external_url)
            self.compatibility_checked.emit(self.mod_data, compat)
        except Exception as e:
            logging.warning(f'CompatibilityCheckThread: Error checking compatibility: {e}', exc_info=True)
        finally:
            self._semaphore.release()


class ModCardWidget(BaseModWidget):
    install_requested = pyqtSignal(object)
    uninstall_requested = pyqtSignal(object)
    details_requested = pyqtSignal(object)

    def __init__(self, mod_data, parent=None, parent_app=None):
        super().__init__(mod_data, parent)
        self.hide()
        if parent_app:
            self.parent_app = parent_app
        elif parent and hasattr(parent, 'parent_app'):
            self.parent_app = parent.parent_app
        elif parent:
            current = parent
            while current:
                if hasattr(current, 'mod_service') or hasattr(current, 'app_state'):
                    self.parent_app = current
                    break
                current = current.parent() if hasattr(current, 'parent') else None
        self.is_installed = False
        self._last_icon_url = getattr(mod_data, 'icon_url', None) or getattr(mod_data, 'icon_path', None)
        self.frame_selector = 'modCard'
        self.setObjectName('modCard')
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedHeight(120)
        self.gb_status_label = None
        self._compatibility_thread = None
        self._init_ui()
        self._check_installation_status()
        self.update_install_button_state()
        self._update_style()
        if self.is_installed and hasattr(self, 'install_button'):
            self._apply_uninstall_button_style()
        key = get_mod_key(self.mod_data)
        if key and key.startswith('gb_'):
            self._start_compatibility_check()
        try:
            self.destroyed.connect(self._cleanup_compatibility_thread)
        except Exception:
            pass
        UIAnimator.fade_in(self, 200, getattr(self.parent_app, 'app_state', None) if getattr(self, 'parent_app', None) else None)

    def _cleanup_compatibility_thread(self):
        try:
            thread = getattr(self, '_compatibility_thread', None)
            if not thread:
                return
            if thread.isRunning():
                thread.requestInterruption()
                thread.quit()
                try:
                    thread.compatibility_checked.disconnect()
                    thread.finished.disconnect()
                except (TypeError, RuntimeError):
                    pass
                thread.finished.connect(lambda: thread.deleteLater() if thread.isFinished() else None)
            elif thread.isFinished():
                thread.deleteLater()
        except Exception:
            pass
        self._compatibility_thread = None

    def _create_tags_layout_if_needed(self, info_layout):
        tags_layout = QHBoxLayout()
        tags_layout.setContentsMargins(0, 5, 0, 0)
        tags_layout.setSpacing(10)
        key = get_mod_key(self.mod_data)
        if key and key.startswith('gb_'):
            self.gb_status_label = QLabel(self)
            self.gb_status_label.setObjectName('gbStatusLabel')
            tags_layout.addWidget(self.gb_status_label)
            self._update_gamebanana_status_label()
        tags_layout.addStretch()
        info_layout.addLayout(tags_layout)

    def _update_style(self):
        super()._update_style()
        for attr in ('created_label_title', 'updated_label_title'):
            label = getattr(self, attr, None)
            if label:
                label.setStyleSheet(f'color: {self._get_theme_text_color()};')

    def _get_theme_text_color(self, fallback='#e8e9eb'):
        config = self._resolve_theme_config()
        return get_theme_color(config, 'text', fallback) if config else fallback

    def _get_theme_border_color(self, fallback='#039d5b'):
        config = self._resolve_theme_config()
        return get_theme_color(config, 'border', fallback) if config else fallback

    def _get_app_state(self):
        if self.parent_app and hasattr(self.parent_app, 'app_state'):
            return self.parent_app.app_state
        return None

    def _get_mod_identifier(self):
        try:
            key = get_mod_key(self.mod_data)
            if not key:
                return None
            if key.startswith('gb_') and key[3:]:
                return f'gb::{key[3:]}'
            return f'key::{key}'
        except Exception:
            return None

    def _get_downloads_text(self):
        try:
            key = get_mod_key(self.mod_data)
            downloads_value = getattr(self.mod_data, 'downloads', None)
            if key and key.startswith('gb_'):
                has_full = getattr(self.mod_data, 'has_full_metadata', True)
                if not has_full:
                    return tr('ui.loading_placeholder')
            return f'⤓ {downloads_value if downloads_value is not None else "N/A"}'
        except Exception:
            downloads_value = getattr(self.mod_data, 'downloads', None)
            return f'⤓ {downloads_value if downloads_value is not None else "N/A"}'

    def _init_ui(self):
        super()._init_ui()
        downloads_text = self._get_downloads_text()
        self.downloads_label = QLabel(downloads_text, self)
        self.downloads_label.setObjectName('secondaryText')
        self.downloads_label.setToolTip(tr('ui.downloads_tooltip'))
        self.downloads_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.title_layout.addWidget(self.downloads_label)
        created_date_text = self.mod_data.created_date or 'N/A'
        created_container = QWidget(self)
        created_container_layout = QHBoxLayout(created_container)
        created_container_layout.setContentsMargins(0, 0, 0, 0)
        created_container_layout.setSpacing(0)
        created_label_title = QLabel(tr('ui.created_label'), created_container)
        created_label_title.setObjectName('primaryText')
        created_label_value = QLabel(f' {created_date_text}', created_container)
        created_label_value.setObjectName('secondaryText')
        created_container_layout.addWidget(created_label_title)
        created_container_layout.addWidget(created_label_value)
        self.created_container = created_container
        self.created_label_title = created_label_title
        updated_date_text = self.mod_data.last_updated or 'N/A'
        updated_container = QWidget(self)
        updated_container_layout = QHBoxLayout(updated_container)
        updated_container_layout.setContentsMargins(0, 0, 0, 0)
        updated_container_layout.setSpacing(0)
        updated_label_title = QLabel(tr('ui.updated_label'), updated_container)
        updated_label_title.setObjectName('primaryText')
        updated_label_value = QLabel(f' {updated_date_text}', updated_container)
        updated_label_value.setObjectName('secondaryText')
        updated_container_layout.addWidget(updated_label_title)
        updated_container_layout.addWidget(updated_label_value)
        self.updated_container = updated_container
        self.updated_label_title = updated_label_title
        containers = [self.author_container, self.category_container, updated_container, created_container]
        for i, container in enumerate(containers):
            self.metadata_layout.addWidget(container)
            if i < len(containers) - 1:
                separator = QLabel('|', self)
                separator.setObjectName('secondaryText')
                self.metadata_layout.addWidget(separator)
        self.metadata_layout.addStretch()
        self.actions_widget = QWidget(self)
        actions_layout = QVBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(5)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details_button = QPushButton(tr('ui.details_button'), self.actions_widget)
        self.details_button.setObjectName('cardButton')
        self.details_button.clicked.connect(lambda: self.details_requested.emit(self.mod_data))
        self.install_button = QPushButton(tr('buttons.install'), self.actions_widget)
        self.install_button.setObjectName('cardButtonInstall')
        self.install_button.clicked.connect(self._on_install_button_clicked)
        actions_layout.addWidget(self.details_button)
        actions_layout.addWidget(self.install_button)
        self.actions_widget.setVisible(False)
        self.main_layout.addWidget(self.actions_widget)

    def _update_actions_visibility(self):
        if hasattr(self, 'actions_widget'):
            self.actions_widget.setVisible(self.is_selected)

    def _check_installation_status(self):
        if self.parent_app and hasattr(self.parent_app, 'mod_service'):
            key = get_mod_key(self.mod_data) or ''
            try:
                self.is_installed = self.parent_app.mod_service.is_mod_installed(key)
            except Exception as e:
                logging.error(f'ModCardWidget: Error checking installation by key {key}: {e}', exc_info=True)
                self.is_installed = False
            if not self.is_installed and key and key.startswith('gb_'):
                try:
                    self.is_installed = key in self.parent_app.mod_service._get_mods_cache()
                except Exception as e:
                    logging.warning(f'ModCardWidget: Error checking cache for key {key}: {e}', exc_info=True)
        else:
            self.is_installed = False
        self._update_install_button()

    def _start_compatibility_check(self):
        if getattr(self.mod_data, 'gamebanana_compatibility_checked', False):
            return
        key = get_mod_key(self.mod_data)
        if key and key.startswith('gb_'):
            try:
                from adapters.gamebanana_adapter import GameBananaAPI
                cached = GameBananaAPI._compatibility_cache.get(int(key[3:]))
                if cached:
                    self._on_compatibility_checked(self.mod_data, cached)
                    return
            except (ValueError, TypeError):
                pass
        if self._compatibility_thread:
            if self._compatibility_thread.isFinished():
                try:
                    self._compatibility_thread.compatibility_checked.disconnect()
                except (TypeError, RuntimeError):
                    pass
                try:
                    self._compatibility_thread.finished.disconnect()
                except (TypeError, RuntimeError):
                    pass
                self._compatibility_thread = None
            elif self._compatibility_thread.isRunning():
                return
        from PyQt6.QtCore import QTimer
        if not hasattr(self, '_compatibility_check_timer'):
            self._compatibility_check_timer = QTimer()
            self._compatibility_check_timer.setSingleShot(True)
            self._compatibility_check_timer.timeout.connect(self._do_start_compatibility_check)
        import random
        delay = 200 + random.randint(0, 300)
        self._compatibility_check_timer.start(delay)

    def _do_start_compatibility_check(self):
        try:
            if getattr(self.mod_data, 'gamebanana_compatibility_checked', False):
                return
            if self._compatibility_thread and self._compatibility_thread.isRunning():
                return
            self._compatibility_thread = CompatibilityCheckThread(self.mod_data, self)
            self._compatibility_thread.compatibility_checked.connect(self._on_compatibility_checked)
            self._compatibility_thread.finished.connect(lambda: setattr(self, '_compatibility_thread', None))
            self._compatibility_thread.start()
        except Exception as e:
            logging.warning(f'ModCardWidget: Failed to start compatibility check: {e}', exc_info=True)

    _COMPAT_ATTR_MAP = {
        'gamebanana_supported_files': ('supported_files', []),
        'gamebanana_has_compatible_file': ('has_supported_files', False),
        'gamebanana_is_tool_compatible': ('has_supported_files', False),
        'gamebanana_compatibility_checked': ('compatibility_checked', False),
        'gamebanana_preferred_format': ('preferred_format', None),
        'gamebanana_has_deltahub_file': ('has_deltahub_file', False),
        'gamebanana_has_deltamod_file': ('has_deltamod_file', False),
    }

    def _on_compatibility_checked(self, mod_data, compat_info):
        if mod_data != self.mod_data:
            return
        try:
            for attr, (info_key, default) in self._COMPAT_ATTR_MAP.items():
                setattr(self.mod_data, attr, compat_info.get(info_key, default))
            self._apply_gamebanana_install_styles()
            self._update_gamebanana_status_label()
        except Exception as e:
            logging.warning(f'ModCardWidget: Error updating compatibility info: {e}', exc_info=True)

    def _apply_uninstall_button_style(self):
        if not hasattr(self, 'install_button'):
            return
        text_color = self._get_theme_text_color('#e8e9eb')
        border = self._get_theme_border_color('#039d5b')
        config = self._resolve_theme_config()
        br = get_border_radius(config)
        from ui.common.styling import build_button_style
        self.install_button.setStyleSheet(build_button_style('cardButtonUninstall', '#F44336', '#d32f2f', text_color, border, border_radius=br))

    def _update_install_button(self):
        if self.is_installed:
            self.install_button.setText(tr('buttons.delete'))
            self.install_button.setObjectName('cardButtonUninstall')
            self._apply_uninstall_button_style()
            self.install_button.setToolTip('')
        else:
            self.install_button.setText(tr('buttons.install'))
            self.install_button.setObjectName('cardButtonInstall')
            self._apply_gamebanana_install_styles()
        self.update_install_button_state()

    def update_install_button_state(self):
        if not hasattr(self, 'install_button'):
            return
        app_state = self._get_app_state()
        if app_state:
            is_installing = getattr(app_state, 'is_installing', False)
            self.install_button.setEnabled(not is_installing)

    def _apply_gamebanana_install_styles(self):
        key = get_mod_key(self.mod_data)
        if not key or not key.startswith('gb_'):
            self.install_button.setStyleSheet('')
            self.install_button.setToolTip('')
            return
        compatible = bool(getattr(self.mod_data, 'gamebanana_is_tool_compatible', False))
        checked = bool(getattr(self.mod_data, 'gamebanana_compatibility_checked', False))
        if checked and (not compatible):
            text_color = self._get_theme_text_color('#e8e9eb')
            border = self._get_theme_border_color('#039d5b')
            config = self._resolve_theme_config()
            br = get_border_radius(config)
            from ui.common.styling import build_button_style
            self.install_button.setStyleSheet(build_button_style('cardButtonInstall', '#FFC107', '#FFB300', text_color, border, border_radius=br))
            self.install_button.setToolTip(tr('ui.gamebanana_status_manual_tooltip'))
        else:
            self.install_button.setStyleSheet('')
            self.install_button.setToolTip('')

    def _format_gamebanana_format(self, fmt: Optional[str]) -> str:
        if fmt == 'deltahub':
            return tr('ui.gamebanana_format_deltahub')
        if fmt == 'deltamod':
            return tr('ui.gamebanana_format_deltamod')
        return tr('defaults.not_specified')

    def _update_gamebanana_status_label(self):
        if not self.gb_status_label:
            return
        key = get_mod_key(self.mod_data)
        is_gb = bool(key and key.startswith('gb_'))
        if not is_gb:
            self.gb_status_label.setVisible(False)
            return
        self.gb_status_label.setVisible(True)
        if self.is_installed:
            self._set_gamebanana_status(tr('ui.gamebanana_status_installed'), '#4CAF50', tr('ui.gamebanana_status_installed_tooltip'))
            return
        compatible = bool(getattr(self.mod_data, 'gamebanana_is_tool_compatible', False))
        checked = bool(getattr(self.mod_data, 'gamebanana_compatibility_checked', False))
        files = getattr(self.mod_data, 'gamebanana_supported_files', []) or []
        preferred = getattr(self.mod_data, 'gamebanana_preferred_format', None)
        if compatible:
            text = tr('ui.gamebanana_status_ready')
            color = '#4CAF50'
            tooltip = tr('ui.gamebanana_status_ready_tooltip', files=len(files) or 1, format=self._format_gamebanana_format(preferred))
        elif checked:
            text = tr('ui.gamebanana_status_manual')
            color = '#FFC107'
            tooltip = tr('ui.gamebanana_status_manual_tooltip')
        else:
            text = tr('ui.gamebanana_status_unknown')
            color = '#9E9E9E'
            tooltip = tr('ui.gamebanana_status_unknown_tooltip')
        self._set_gamebanana_status(text, color, tooltip)

    def _set_gamebanana_status(self, text: str, color: str, tooltip: str):
        if not self.gb_status_label:
            return
        self.gb_status_label.setText(text)
        self.gb_status_label.setStyleSheet(f'color: {color}; font-size: 13px; font-weight: bold; background: transparent;')
        self.gb_status_label.setToolTip(tooltip)

    def _on_install_button_clicked(self):
        if self.is_installed:
            self.uninstall_requested.emit(self.mod_data)
        else:
            self.install_requested.emit(self.mod_data)

    def update_installation_status(self):
        was_installed = self.is_installed
        self._check_installation_status()
        if was_installed != self.is_installed:
            key = get_mod_key(self.mod_data)
            if key and key.startswith('gb_'):
                if not self.is_installed:
                    for attr, val in [('gamebanana_compatibility_checked', False), ('gamebanana_is_tool_compatible', False), ('gamebanana_supported_files', [])]:
                        setattr(self.mod_data, attr, val)
                    self._start_compatibility_check()
                self._update_gamebanana_status_label()
                self._apply_gamebanana_install_styles()

    def update_mod_data(self):
        try:
            if hasattr(self, 'icon_label'):
                new_icon = getattr(self.mod_data, 'icon_url', None) or getattr(self.mod_data, 'icon_path', None)
                if new_icon != getattr(self, '_last_icon_url', None):
                    self._last_icon_url = new_icon
                    from ui.common.styling import load_mod_icon_universal, get_theme_color
                    config = self._resolve_theme_config()
                    br = get_border_radius(config)
                    bc = get_theme_color(config, 'border', '#039d5b') if config else None
                    bw = 2 if bc else 0
                    load_mod_icon_universal(self.icon_label, self.mod_data, size=80, local_fallback=self._resolve_local_icon_fallback(), border_radius=br, border_width=bw, border_color=bc)
            if hasattr(self, 'downloads_label'):
                self.downloads_label.setText(self._get_downloads_text())
            if hasattr(self, 'tagline_label'):
                tagline = getattr(self.mod_data, 'tagline', '') or tr('ui.no_description')
                key = get_mod_key(self.mod_data)
                if key and key.startswith('gb_') and not getattr(self.mod_data, 'has_full_metadata', True):
                    tagline = tr('ui.loading_placeholder')
                if len(tagline) > 200:
                    tagline = tagline[:197] + '...'
                self.tagline_label.setText(tagline)
            key = get_mod_key(self.mod_data)
            if key and key.startswith('gb_'):
                if not getattr(self.mod_data, 'gamebanana_compatibility_checked', False):
                    if not (self._compatibility_thread and self._compatibility_thread.isRunning()):
                        if not (hasattr(self, '_compatibility_check_timer') and self._compatibility_check_timer.isActive()):
                            self._start_compatibility_check()
            self._update_gamebanana_status_label()
            if not self.is_installed:
                self._apply_gamebanana_install_styles()
        except Exception as e:
            logging.warning(f'ModCardWidget: Error updating mod data: {e}', exc_info=True)

    def set_selected(self, selected):
        self.is_selected = selected
        if hasattr(self, '_update_actions_visibility'):
            self._update_actions_visibility()
        self._update_style()
        if hasattr(self, 'install_button') and self.is_installed:
            button_obj_name = self.install_button.objectName()
            if button_obj_name == 'cardButtonUninstall':
                self._apply_uninstall_button_style()

    def update_labels_text(self):
        super().update_labels_text()
        if hasattr(self, 'created_label_title'):
            self.created_label_title.setText(tr('ui.created_label'))
        if hasattr(self, 'updated_label_title'):
            self.updated_label_title.setText(tr('ui.updated_label'))
        if hasattr(self, 'details_button'):
            self.details_button.setText(tr('ui.details_button'))
        if hasattr(self, 'install_button'):
            if self.is_installed:
                self.install_button.setText(tr('buttons.delete'))
            else:
                self.install_button.setText(tr('buttons.install'))
                self._apply_gamebanana_install_styles()
        self._update_gamebanana_status_label()
