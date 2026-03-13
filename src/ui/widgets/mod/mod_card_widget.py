import threading
from PyQt6.QtCore import pyqtSignal, Qt, QThread
from PyQt6.QtWidgets import QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QFrame, QWidget
from .base_mod_widget import BaseModWidget
from services.localization_service import tr
from ui.common.styling import get_theme_color, get_border_radius, get_card_button_metrics, get_widget_dimensions
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
    download_requested = pyqtSignal(object)
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
        self.setFixedHeight(self._card_height())
        self._compatibility_thread = None
        self._init_ui()
        self._check_installation_status()
        self.update_action_button_state()
        self._update_style()
        if self.is_installed and hasattr(self, 'action_button'):
            self._apply_unaction_button_style()
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

    def _update_style(self):
        super()._update_style()
        for attr in ('created_label_title', 'updated_label_title'):
            label = getattr(self, attr, None)
            if label:
                label.setStyleSheet(f'color: {self._get_theme_text_color()};')
        if hasattr(self, 'action_button'):
            if self.is_installed:
                self._apply_unaction_button_style()
            else:
                self._apply_download_style()

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

    def _get_downloads_manager(self):
        if self.parent_app and hasattr(self.parent_app, 'downloads_manager'):
            return self.parent_app.downloads_manager
        return None

    def _get_likes_text(self):
        try:
            key = get_mod_key(self.mod_data)
            likes_value = getattr(self.mod_data, 'like_count', None)
            if key and key.startswith('gb_'):
                has_full = getattr(self.mod_data, 'has_full_metadata', True)
                if not has_full:
                    return tr('ui.loading_placeholder')
            return f'❤ {likes_value if likes_value is not None else 0}'
        except Exception:
            return '❤ N/A'

    def _init_ui(self):
        super()._init_ui()
        likes_text = self._get_likes_text()
        self.likes_label = QLabel(likes_text, self)
        self.likes_label.setObjectName('secondaryText')
        self.likes_label.setToolTip(tr('ui.likes_tooltip'))
        self.likes_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.title_layout.addWidget(self.likes_label)
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
        self.action_button = QPushButton(tr('buttons.download'), self.actions_widget)
        self.action_button.setObjectName('cardButtonDownload')
        self.action_button.clicked.connect(self._on_action_button_clicked)
        actions_layout.addWidget(self.details_button)
        actions_layout.addWidget(self.action_button)
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
        self._update_action_button()

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
            self._apply_download_style()
        except Exception as e:
            logging.warning(f'ModCardWidget: Error updating compatibility info: {e}', exc_info=True)

    def _apply_unaction_button_style(self):
        if not hasattr(self, 'action_button'):
            return
        text_color = self._get_theme_text_color('#e8e9eb')
        border = self._get_theme_border_color('#039d5b')
        config = self._resolve_theme_config()
        br = get_border_radius(config)
        button_width, button_height, button_font_size = get_card_button_metrics(config)
        from ui.common.styling import build_button_style
        self.action_button.setStyleSheet(build_button_style('cardButtonUninstall', '#F44336', '#d32f2f', text_color, border, width=button_width, height=button_height, font_size=button_font_size, border_radius=br))

    def _update_action_button(self):
        if self.is_installed:
            self.action_button.setText(tr('buttons.delete'))
            self.action_button.setObjectName('cardButtonUninstall')
            self._apply_unaction_button_style()
            self.action_button.setToolTip('')
        else:
            self.action_button.setText(tr('buttons.download'))
            self.action_button.setObjectName('cardButtonDownload')
            self._apply_download_style()
        self.update_action_button_state()

    def update_action_button_state(self):
        if not hasattr(self, 'action_button'):
            return
        if self.is_installed:
            self.action_button.setEnabled(True)
            return
        app_state = self._get_app_state()
        if not app_state:
            self.action_button.setEnabled(True)
            return
        if getattr(app_state, 'is_installing', False):
            self.action_button.setEnabled(False)
            return
        key = get_mod_key(self.mod_data)
        if key and key.startswith('gb_'):
            dm = self._get_downloads_manager()
            if dm:
                prefix = f'gb_mod_{key.replace("gb_", "", 1)}'
                for r in dm.records:
                    if r.canonical_key and r.canonical_key.startswith(prefix) and r.is_active:
                        self.action_button.setEnabled(False)
                        self.action_button.setToolTip(tr('downloads.already_downloading'))
                        return
        self.action_button.setEnabled(True)

    def _apply_download_style(self):
        self.action_button.setStyleSheet('')
        self.action_button.setToolTip('')

    def _on_action_button_clicked(self):
        if self.is_installed:
            self.uninstall_requested.emit(self.mod_data)
        else:
            self.download_requested.emit(self.mod_data)

    def update_installation_status(self):
        was_installed = self.is_installed
        self._check_installation_status()
        if was_installed != self.is_installed:
            key = get_mod_key(self.mod_data)
            if key and key.startswith('gb_'):
                if not self.is_installed:
                    for attr, val in [('gamebanana_compatibility_checked', False), ('gamebanana_is_tool_compatible', False), ('gamebanana_supported_files', [])]:
                        setattr(self.mod_data, attr, val)
                self._apply_download_style()

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
                    icon_width, icon_height = get_widget_dimensions(getattr(self, 'icon_label', None))
                    load_mod_icon_universal(self.icon_label, self.mod_data, size=(icon_width or self._icon_size(), icon_height or self._icon_size()), local_fallback=self._resolve_local_icon_fallback(), border_radius=br, border_width=bw, border_color=bc)
            if hasattr(self, 'likes_label'):
                self.likes_label.setText(self._get_likes_text())
            if hasattr(self, 'tagline_label'):
                tagline = getattr(self.mod_data, 'tagline', '') or tr('ui.no_description')
                key = get_mod_key(self.mod_data)
                if key and key.startswith('gb_') and not getattr(self.mod_data, 'has_full_metadata', True):
                    tagline = tr('ui.loading_placeholder')
                if len(tagline) > 200:
                    tagline = tagline[:197] + '...'
                self.tagline_label.setText(tagline)
            if not self.is_installed:
                self._apply_download_style()
        except Exception as e:
            logging.warning(f'ModCardWidget: Error updating mod data: {e}', exc_info=True)

    def set_selected(self, selected):
        self.is_selected = selected
        if hasattr(self, '_update_actions_visibility'):
            self._update_actions_visibility()
        self._update_style()
        if hasattr(self, 'action_button') and self.is_installed:
            button_obj_name = self.action_button.objectName()
            if button_obj_name == 'cardButtonUninstall':
                self._apply_unaction_button_style()

    def update_labels_text(self):
        super().update_labels_text()
        if hasattr(self, 'created_label_title'):
            self.created_label_title.setText(tr('ui.created_label'))
        if hasattr(self, 'updated_label_title'):
            self.updated_label_title.setText(tr('ui.updated_label'))
        if hasattr(self, 'likes_label'):
            self.likes_label.setToolTip(tr('ui.likes_tooltip'))
        if hasattr(self, 'details_button'):
            self.details_button.setText(tr('ui.details_button'))
        if hasattr(self, 'action_button'):
            if self.is_installed:
                self.action_button.setText(tr('buttons.delete'))
            else:
                self.action_button.setText(tr('buttons.download'))
                self._apply_download_style()
