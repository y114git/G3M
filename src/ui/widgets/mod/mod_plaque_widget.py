from typing import Optional
from PyQt6.QtCore import pyqtSignal, Qt, QThread
from PyQt6.QtWidgets import QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QFrame, QWidget
from .base_mod_widget import BaseModWidget
from managers.localization_manager import tr
from ui.common.styling import get_theme_color
import logging


class CompatibilityCheckThread(QThread):
    compatibility_checked = pyqtSignal(object, dict)

    def __init__(self, mod_data, parent=None):
        super().__init__(parent)
        self.mod_data = mod_data

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            if not hasattr(self.mod_data, 'is_gamebanana_mod') or not self.mod_data.is_gamebanana_mod:
                return
            mod_id = getattr(self.mod_data, 'gamebanana_mod_id', None)
            if not mod_id:
                return
            from utils.gamebanana_api import GameBananaAPI
            api = GameBananaAPI()
            if self.isInterruptionRequested():
                return
            compat = api.get_supported_files_for_mod(int(mod_id))
            self.compatibility_checked.emit(self.mod_data, compat)
        except Exception as e:
            logging.warning(f'CompatibilityCheckThread: Error checking compatibility: {e}', exc_info=True)


class ModPlaqueWidget(BaseModWidget):
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
                if hasattr(current, 'mod_manager') or hasattr(current, 'app_state'):
                    self.parent_app = current
                    break
                current = current.parent() if hasattr(current, 'parent') else None
        self.is_installed = False
        self.frame_selector = 'modPlaque'
        self.setObjectName('modPlaque')
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
        if hasattr(self.mod_data, 'is_gamebanana_mod') and self.mod_data.is_gamebanana_mod:
            self._start_compatibility_check()
        try:
            self.destroyed.connect(self._cleanup_compatibility_thread)
        except Exception:
            pass

    def _cleanup_compatibility_thread(self):
        try:
            thread = getattr(self, '_compatibility_thread', None)
        except Exception:
            thread = None
        if not thread:
            return
        try:
            if thread.isRunning():
                try:
                    thread.requestInterruption()
                except Exception:
                    pass
                try:
                    thread.quit()
                except Exception:
                    pass
                try:
                    thread.compatibility_checked.disconnect()
                    thread.finished.disconnect()
                except (TypeError, RuntimeError):
                    pass

                def cleanup_when_finished():
                    try:
                        if thread and thread.isFinished():
                            thread.deleteLater()
                    except Exception:
                        pass
                try:
                    thread.finished.connect(cleanup_when_finished)
                except (TypeError, RuntimeError):
                    try:
                        if thread.isRunning():
                            thread.wait(2000)
                        if thread.isFinished():
                            thread.deleteLater()
                    except Exception:
                        pass
            elif thread.isFinished():
                try:
                    thread.deleteLater()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self._compatibility_thread = None
        except Exception:
            pass

    def _create_tags_layout_if_needed(self, info_layout):
        tags_layout = QHBoxLayout()
        tags_layout.setContentsMargins(0, 5, 0, 0)
        tags_layout.setSpacing(10)
        modgame = getattr(self.mod_data, 'modgame', 'deltarune')
        modgame_text = ''
        modgame_style = ''
        config = self._resolve_theme_config()
        text_color = get_theme_color(config, 'text', 'white') if config else 'white'
        if modgame == 'deltarune':
            modgame_text = 'DELTARUNE'
            modgame_style = f'background-color: black; color: {text_color}; border: 1px solid white;'
        elif modgame == 'deltarunedemo':
            modgame_text = 'DELTARUNE DEMO'
            modgame_style = f'background-color: black; color: {text_color}; border: 1px solid lightgreen;'
        elif modgame == 'undertale':
            modgame_text = 'UNDERTALE'
            modgame_style = f'background-color: red; color: {text_color}; border: 1px solid red;'
        elif modgame == 'undertaleyellow':
            modgame_text = 'UNDERTALE Yellow'
            modgame_style = f'background-color: #FFD700; color: {text_color}; border: none;'
        if modgame_text:
            modgame_label = QLabel(modgame_text)
            style_sheet = f'font-weight: bold; padding: 2px 5px; border-radius: 3px; {modgame_style}'
            modgame_label.setStyleSheet(style_sheet)
            tags_layout.addWidget(modgame_label)
        if self.mod_data.is_verified:
            verified_label = QLabel(tr('ui.verified_label'))
            verified_label.setStyleSheet('color: #4CAF50; font-size: 14px;')
            tags_layout.addWidget(verified_label)
        if hasattr(self.mod_data, 'is_gamebanana_mod') and self.mod_data.is_gamebanana_mod:
            gb_label = QLabel('GameBanana 🍌')
            gb_label.setStyleSheet('color: yellow; font-size: 14px;')
            gb_label.setToolTip(tr('ui.gamebanana_mod_tooltip'))
            tags_layout.addWidget(gb_label)
            self.gb_status_label = QLabel()
            self.gb_status_label.setObjectName('gbStatusLabel')
            tags_layout.addWidget(self.gb_status_label)
            self._update_gamebanana_status_label()
        tags_layout.addStretch()
        info_layout.addLayout(tags_layout)

    def _resolve_theme_config(self):
        if self.parent_app:
            if hasattr(self.parent_app, 'local_config'):
                return self.parent_app.local_config
            if hasattr(self.parent_app, 'app_state') and hasattr(self.parent_app.app_state, 'local_config'):
                return self.parent_app.app_state.local_config
        return None

    def _get_theme_text_color(self, fallback='white'):
        config = self._resolve_theme_config()
        return get_theme_color(config, 'text', fallback) if config else fallback

    def _get_app_state(self):
        if self.parent_app and hasattr(self.parent_app, 'app_state'):
            return self.parent_app.app_state
        return None

    def _get_mod_identifier(self):
        try:
            if hasattr(self.mod_data, 'is_gamebanana_mod') and self.mod_data.is_gamebanana_mod:
                mod_id = getattr(self.mod_data, 'gamebanana_mod_id', None)
                if mod_id:
                    return f'gb::{mod_id}'
            mod_key = getattr(self.mod_data, 'key', None)
            if mod_key:
                return f'key::{mod_key}'
        except Exception:
            pass
        return None

    def _init_ui(self):
        super()._init_ui()
        downloads_text = ''
        try:
            if hasattr(self.mod_data, 'is_gamebanana_mod') and self.mod_data.is_gamebanana_mod:
                has_full = getattr(self.mod_data, 'has_full_metadata', True)
                if not has_full:
                    downloads_text = tr('ui.loading_placeholder')
                else:
                    downloads_value = getattr(self.mod_data, 'downloads', 0) or 0
                    downloads_text = f'⤓ {downloads_value}'
            else:
                downloads_value = getattr(self.mod_data, 'downloads', 0) or 0
                downloads_text = f'⤓ {downloads_value}'
        except Exception:
            downloads_value = getattr(self.mod_data, 'downloads', 0) or 0
            downloads_text = f'⤓ {downloads_value}'
        self.downloads_label = QLabel(downloads_text)
        self.downloads_label.setObjectName('secondaryText')
        self.downloads_label.setToolTip(tr('ui.downloads_tooltip'))
        self.downloads_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.title_layout.addWidget(self.downloads_label)
        created_date_text = self.mod_data.created_date or 'N/A'
        created_container = QWidget()
        created_container_layout = QHBoxLayout(created_container)
        created_container_layout.setContentsMargins(0, 0, 0, 0)
        created_container_layout.setSpacing(0)
        created_label_title = QLabel(tr('ui.created_label'))
        created_label_title.setObjectName('primaryText')
        created_label_value = QLabel(f' {created_date_text}')
        created_label_value.setObjectName('secondaryText')
        created_container_layout.addWidget(created_label_title)
        created_container_layout.addWidget(created_label_value)
        self.created_container = created_container
        self.created_label_title = created_label_title
        updated_date_text = self.mod_data.last_updated or 'N/A'
        updated_container = QWidget()
        updated_container_layout = QHBoxLayout(updated_container)
        updated_container_layout.setContentsMargins(0, 0, 0, 0)
        updated_container_layout.setSpacing(0)
        updated_label_title = QLabel(tr('ui.updated_label'))
        updated_label_title.setObjectName('primaryText')
        updated_label_value = QLabel(f' {updated_date_text}')
        updated_label_value.setObjectName('secondaryText')
        updated_container_layout.addWidget(updated_label_title)
        updated_container_layout.addWidget(updated_label_value)
        self.updated_container = updated_container
        self.updated_label_title = updated_label_title
        containers = [self.author_container, self.game_version_container, updated_container, created_container]
        for i, container in enumerate(containers):
            self.metadata_layout.addWidget(container)
            if i < len(containers) - 1:
                separator = QLabel('|')
                separator.setObjectName('secondaryText')
                self.metadata_layout.addWidget(separator)
        self.metadata_layout.addStretch()
        self.actions_widget = QWidget()
        actions_layout = QVBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(5)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details_button = QPushButton(tr('ui.details_button'))
        self.details_button.setObjectName('plaqueButton')
        self.details_button.clicked.connect(lambda: self.details_requested.emit(self.mod_data))
        self.install_button = QPushButton(tr('buttons.install'))
        self.install_button.setObjectName('plaqueButtonInstall')
        self.install_button.clicked.connect(self._on_install_button_clicked)
        actions_layout.addWidget(self.details_button)
        actions_layout.addWidget(self.install_button)
        self.actions_widget.setVisible(False)
        self.main_layout.addWidget(self.actions_widget)

    def _update_actions_visibility(self):
        if not hasattr(self, 'actions_widget'):
            return
        if self.is_selected:
            self.actions_widget.setVisible(True)
        else:
            self.actions_widget.setVisible(False)

    def _check_installation_status(self):
        if self.parent_app and hasattr(self.parent_app, 'mod_manager'):
            if hasattr(self.mod_data, 'is_gamebanana_mod') and self.mod_data.is_gamebanana_mod:
                mod_key = getattr(self.mod_data, 'key', '')
                mod_id = getattr(self.mod_data, 'gamebanana_mod_id', '')
                try:
                    self.is_installed = self.parent_app.mod_manager.is_mod_installed(mod_key)
                except Exception as e:
                    import logging
                    logging.error(f'ModPlaqueWidget: Error checking installation by key {mod_key}: {e}', exc_info=True)
                    self.is_installed = False
                if not self.is_installed and mod_id:
                    try:
                        cache = self.parent_app.mod_manager._get_mods_cache()
                        for cached_mod_key, mod_info in cache.items():
                            config_data = mod_info.config_data
                            cached_mod_id = str(config_data.get('gamebanana_mod_id', ''))
                            if config_data.get('is_gamebanana_mod') and cached_mod_id == str(mod_id):
                                self.is_installed = True
                                break
                    except Exception as e:
                        import logging
                        logging.warning(f'ModPlaqueWidget: Error checking cache for mod_id {mod_id}: {e}', exc_info=True)
            else:
                mod_key = getattr(self.mod_data, 'key', '')
                try:
                    self.is_installed = self.parent_app.mod_manager.is_mod_installed(mod_key)
                except Exception as e:
                    import logging
                    logging.error(f'ModPlaqueWidget: Error checking installation for mod (key={mod_key}): {e}', exc_info=True)
                    self.is_installed = False
        else:
            self.is_installed = False
        self._update_install_button()

    def _start_compatibility_check(self):
        if getattr(self.mod_data, 'gamebanana_compatibility_checked', False):
            return
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
            logging.warning(f'ModPlaqueWidget: Failed to start compatibility check: {e}', exc_info=True)

    def _on_compatibility_checked(self, mod_data, compat_info):
        if mod_data != self.mod_data:
            return
        try:
            setattr(self.mod_data, 'gamebanana_supported_files', compat_info.get('supported_files', []))
            setattr(self.mod_data, 'gamebanana_has_compatible_file', compat_info.get('has_supported_files', False))
            setattr(self.mod_data, 'gamebanana_is_tool_compatible', compat_info.get('has_supported_files', False))
            setattr(self.mod_data, 'gamebanana_compatibility_checked', compat_info.get('compatibility_checked', False))
            setattr(self.mod_data, 'gamebanana_preferred_format', compat_info.get('preferred_format', None))
            setattr(self.mod_data, 'gamebanana_has_deltahub_file', compat_info.get('has_deltahub_file', False))
            setattr(self.mod_data, 'gamebanana_has_deltamod_file', compat_info.get('has_deltamod_file', False))
            self._apply_gamebanana_install_styles()
            self._update_gamebanana_status_label()
        except Exception as e:
            logging.warning(f'ModPlaqueWidget: Error updating compatibility info: {e}', exc_info=True)

    def _apply_uninstall_button_style(self):
        if not hasattr(self, 'install_button'):
            return
        text_color = self._get_theme_text_color('white')
        self.install_button.setStyleSheet(f'\n            QPushButton#plaqueButtonUninstall {{\n                background-color: #F44336;\n                color: {text_color};\n                font-weight: bold;\n                min-width: 110px;\n                max-width: 110px;\n                min-height: 35px;\n                max-height: 35px;\n                font-size: 15px;\n                padding: 1px;\n            }}\n            QPushButton#plaqueButtonUninstall:hover {{\n                background-color: #d32f2f;\n            }}\n        ')

    def _update_install_button(self):
        if self.is_installed:
            self.install_button.setText(tr('buttons.delete'))
            self.install_button.setObjectName('plaqueButtonUninstall')
            self._apply_uninstall_button_style()
            self.install_button.setToolTip('')
        else:
            self.install_button.setText(tr('buttons.install'))
            self.install_button.setObjectName('plaqueButtonInstall')
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
        if not hasattr(self.mod_data, 'is_gamebanana_mod') or not self.mod_data.is_gamebanana_mod:
            self.install_button.setStyleSheet('')
            self.install_button.setToolTip('')
            return
        compatible = bool(getattr(self.mod_data, 'gamebanana_is_tool_compatible', False))
        checked = bool(getattr(self.mod_data, 'gamebanana_compatibility_checked', False))
        if checked and (not compatible):
            text_color = self._get_theme_text_color('white')
            style = f'\n                QPushButton#plaqueButtonInstall {{\n                    background-color: #FFC107;\n                    color: {text_color};\n                }}\n                QPushButton#plaqueButtonInstall:hover {{\n                    background-color: #FFB300;\n                }}\n            '
            self.install_button.setStyleSheet(style)
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
        is_gb = bool(getattr(self.mod_data, 'is_gamebanana_mod', False))
        if not is_gb:
            self.gb_status_label.setVisible(False)
            return
        self.gb_status_label.setVisible(True)
        if self.is_installed:
            text = tr('ui.gamebanana_status_installed')
            color = '#4CAF50'
            tooltip = tr('ui.gamebanana_status_installed_tooltip')
            self.gb_status_label.setText(text)
            self.gb_status_label.setStyleSheet(f'color: {color}; font-size: 13px; font-weight: bold; background: transparent;')
            self.gb_status_label.setToolTip(tooltip)
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
        if was_installed and (not self.is_installed):
            if hasattr(self.mod_data, 'is_gamebanana_mod') and self.mod_data.is_gamebanana_mod:
                setattr(self.mod_data, 'gamebanana_compatibility_checked', False)
                setattr(self.mod_data, 'gamebanana_is_tool_compatible', False)
                setattr(self.mod_data, 'gamebanana_supported_files', [])
                self._start_compatibility_check()
                self._update_gamebanana_status_label()
                self._apply_gamebanana_install_styles()

    def update_mod_data(self):
        try:
            if hasattr(self, 'icon_label'):
                from ui.common.styling import load_mod_icon_universal
                load_mod_icon_universal(self.icon_label, self.mod_data, size=80)
            if hasattr(self, 'downloads_label'):
                try:
                    if hasattr(self.mod_data, 'is_gamebanana_mod') and self.mod_data.is_gamebanana_mod:
                        has_full = getattr(self.mod_data, 'has_full_metadata', True)
                        if not has_full:
                            self.downloads_label.setText(tr('ui.loading_placeholder'))
                        else:
                            downloads = getattr(self.mod_data, 'downloads', 0) or 0
                            self.downloads_label.setText(f'⤓ {downloads}')
                    else:
                        downloads = getattr(self.mod_data, 'downloads', 0) or 0
                        self.downloads_label.setText(f'⤓ {downloads}')
                except Exception:
                    downloads = getattr(self.mod_data, 'downloads', 0) or 0
                    self.downloads_label.setText(f'⤓ {downloads}')
            if hasattr(self, 'tagline_label'):
                try:
                    tagline = getattr(self.mod_data, 'tagline', '') or tr('ui.no_description')
                    if hasattr(self.mod_data, 'is_gamebanana_mod') and self.mod_data.is_gamebanana_mod:
                        has_full = getattr(self.mod_data, 'has_full_metadata', True)
                        if not has_full:
                            tagline = tr('ui.loading_placeholder')
                    if len(tagline) > 200:
                        tagline = tagline[:197] + '...'
                    self.tagline_label.setText(tagline)
                except Exception:
                    tagline = getattr(self.mod_data, 'tagline', '') or tr('ui.no_description')
                    if len(tagline) > 200:
                        tagline = tagline[:197] + '...'
                    self.tagline_label.setText(tagline)
            if hasattr(self.mod_data, 'is_gamebanana_mod') and self.mod_data.is_gamebanana_mod:
                checked = bool(getattr(self.mod_data, 'gamebanana_compatibility_checked', False))
                if not checked:
                    if self._compatibility_thread and self._compatibility_thread.isRunning():
                        return
                    if hasattr(self, '_compatibility_check_timer') and self._compatibility_check_timer.isActive():
                        return
                    if self._compatibility_thread and self._compatibility_thread.isFinished():
                        try:
                            self._compatibility_thread.compatibility_checked.disconnect()
                        except (TypeError, RuntimeError):
                            pass
                        try:
                            self._compatibility_thread.finished.disconnect()
                        except (TypeError, RuntimeError):
                            pass
                        self._compatibility_thread = None
                    self._start_compatibility_check()
            self._update_gamebanana_status_label()
            if not self.is_installed:
                self._apply_gamebanana_install_styles()
        except Exception as e:
            import logging
            logging.warning(f'ModPlaqueWidget: Error updating mod data: {e}', exc_info=True)

    def set_selected(self, selected):
        self.is_selected = selected
        if hasattr(self, '_update_actions_visibility'):
            self._update_actions_visibility()
        self._update_style()
        if hasattr(self, 'install_button') and self.is_installed:
            button_obj_name = self.install_button.objectName()
            if button_obj_name == 'plaqueButtonUninstall':
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
