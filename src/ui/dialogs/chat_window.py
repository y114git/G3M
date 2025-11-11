import logging
import time
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QScrollArea, QWidget, QFrame, QSpinBox
from PyQt6.QtCore import Qt, QTimer
from managers.localization_manager import tr
from managers.chat_manager import ChatManager
from ui.common.styling import get_theme_color
from utils.network_utils import check_internet_connection


class ChatWindow(QDialog):

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.chat_manager = ChatManager()
        self.current_channel = None
        self.messages = []
        self.last_send_time = 0
        self.send_cooldown = 5
        self._loading_messages = False
        self._refreshing_messages = False
        self._last_message_ids = set()
        self._message_widgets = {}
        self.max_messages_limit = self.app_state.local_config.get('chat_message_limit', 50)
        if not isinstance(self.max_messages_limit, int) or self.max_messages_limit < 1 or self.max_messages_limit > 100:
            self.max_messages_limit = 50
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._refresh_messages_async)
        self.update_timer.setInterval(5000)
        self.setWindowTitle(tr('chat.window_title'))
        self.setMinimumSize(600, 500)
        self.resize(800, 600)
        self.setup_ui()
        self._apply_theme()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        channels_layout = QHBoxLayout()
        channels_layout.setSpacing(10)
        channels_layout.addStretch()
        self.channel_buttons = {}
        self._updating_channel_buttons = False
        channels = [('en', 'chat.channel_english'), ('ru', 'chat.channel_russian'), ('es', 'chat.channel_spanish'), ('zh', 'chat.channel_chinese'), ('int', 'chat.channel_international')]
        for channel_code, channel_key in channels:
            btn = QPushButton(tr(channel_key))
            btn.setCheckable(True)

            def make_switch_handler(ch):

                def handler(checked):
                    if self._updating_channel_buttons:
                        return
                    if self._loading_messages or self._refreshing_messages:
                        return
                    if checked:
                        self._switch_channel(ch)
                return handler
            btn.clicked.connect(make_switch_handler(channel_code))
            channels_layout.addWidget(btn)
            self.channel_buttons[channel_code] = btn
        channels_layout.addStretch()
        layout.addLayout(channels_layout)
        self.messages_area = QScrollArea()
        self.messages_area.setWidgetResizable(True)
        self.messages_area.setFrameShape(QFrame.Shape.NoFrame)
        self.messages_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.messages_widget = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.messages_layout.setSpacing(5)
        self.messages_layout.setContentsMargins(10, 10, 10, 10)
        self.select_channel_label = QLabel(tr('chat.select_channel_first'))
        self.select_channel_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.select_channel_label.hide()
        self.messages_layout.addWidget(self.select_channel_label)
        self.messages_area.setWidget(self.messages_widget)
        layout.addWidget(self.messages_area)
        input_layout = QHBoxLayout()
        input_layout.setSpacing(10)
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText(tr('chat.message_input_placeholder'))
        self.message_input.setMaxLength(ChatManager.MESSAGE_MAX_LENGTH)
        self.message_input.returnPressed.connect(self._send_message)
        self.message_input.textChanged.connect(self._on_input_changed)
        self.message_input.setEnabled(False)
        input_layout.addWidget(self.message_input)
        self.send_button = QPushButton(tr('chat.send_button'))
        self.send_button.clicked.connect(self._send_message)
        self.send_button.setEnabled(False)
        input_layout.addWidget(self.send_button)
        layout.addLayout(input_layout)
        limit_layout = QHBoxLayout()
        limit_layout.addStretch()
        self.limit_label = QLabel(tr('chat.message_limit_label'))
        limit_layout.addWidget(self.limit_label)
        self.message_limit_spinbox = QSpinBox()
        self.message_limit_spinbox.setMinimum(1)
        self.message_limit_spinbox.setMaximum(100)
        self.message_limit_spinbox.setValue(self.max_messages_limit)
        self.message_limit_spinbox.valueChanged.connect(self._on_limit_changed)
        limit_layout.addWidget(self.message_limit_spinbox)
        limit_layout.addStretch()
        layout.addLayout(limit_layout)
        self.cooldown_label = QLabel()
        self.cooldown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cooldown_label.hide()
        layout.addWidget(self.cooldown_label)
        self.cooldown_timer = QTimer(self)
        self.cooldown_timer.timeout.connect(self._update_cooldown)
        self.cooldown_timer.setInterval(100)
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        self._show_select_channel_message()

    def _sync_channel_buttons(self):
        if not self.current_channel:
            return
        self._updating_channel_buttons = True
        try:
            for ch, btn in self.channel_buttons.items():
                btn.blockSignals(True)
                btn.setChecked(ch == self.current_channel)
                btn.blockSignals(False)
        finally:
            self._updating_channel_buttons = False

    def _switch_channel(self, channel: str):
        if not check_internet_connection():
            self.status_label.setText(tr('chat.no_internet'))
            return
        if self.current_channel == channel:
            return
        if self._loading_messages:
            return
        self.update_timer.stop()
        self._updating_channel_buttons = True
        try:
            for ch, btn in self.channel_buttons.items():
                btn.blockSignals(True)
                btn.setChecked(ch == channel)
                btn.blockSignals(False)
        finally:
            self._updating_channel_buttons = False
        self._clear_messages_display()
        self.messages = []
        self._last_message_ids = set()
        self._message_widgets.clear()
        self.current_channel = channel
        self.select_channel_label.hide()
        self.message_input.setEnabled(True)
        self.update_timer.start()
        self._load_messages_async()

    def _load_messages_async(self):
        if not self.current_channel or self._loading_messages:
            return
        self._loading_messages = True
        self.status_label.setText(tr('chat.loading_messages'))
        self.message_input.setEnabled(False)
        self.send_button.setEnabled(False)
        QTimer.singleShot(0, self._load_messages_sync)

    def _load_messages_sync(self):
        if not self.current_channel:
            self._loading_messages = False
            return
        channel = self.current_channel
        try:
            self.messages = []
            self._last_message_ids = set()
            self._clear_messages_display()
            new_messages = self.chat_manager.get_messages(channel)
            if self.current_channel != channel:
                return
            limited_messages = new_messages[-self.max_messages_limit:] if len(new_messages) > self.max_messages_limit else new_messages
            self.messages = limited_messages
            self._last_message_ids = {msg['id'] for msg in limited_messages}
            self._update_messages_display()
            self._sync_channel_buttons()
            self.status_label.setText('')
            self.message_input.setEnabled(True)
            self._on_input_changed(self.message_input.text())
        except Exception as e:
            logging.warning(f'ChatWindow: Failed to load messages: {e}')
            self.status_label.setText(tr('chat.error_loading'))
            self.message_input.setEnabled(True)
        finally:
            self._loading_messages = False

    def _refresh_messages_immediate(self, channel: str):
        if not self.current_channel or self.current_channel != channel:
            return
        if self._loading_messages or self._refreshing_messages:
            return
        if not check_internet_connection():
            return
        self._refreshing_messages = True
        QTimer.singleShot(0, self._refresh_messages_sync)

    def _refresh_messages_async(self):
        if not self.current_channel or self._loading_messages or self._refreshing_messages:
            return
        if not check_internet_connection():
            return
        self._refreshing_messages = True
        QTimer.singleShot(0, self._refresh_messages_sync)

    def _refresh_messages_sync(self):
        channel = self.current_channel
        if not channel:
            self._refreshing_messages = False
            return
        try:
            new_messages = self.chat_manager.get_messages(channel)
            if self.current_channel != channel:
                return
            limited_messages = new_messages[-self.max_messages_limit:] if len(new_messages) > self.max_messages_limit else new_messages
            new_message_ids = {msg['id'] for msg in limited_messages}
            if new_message_ids != self._last_message_ids:
                self.messages = limited_messages
                self._last_message_ids = new_message_ids
                self._update_messages_display_incremental(new_message_ids)
        except Exception as e:
            logging.debug(f'ChatWindow: Failed to refresh messages: {e}')
        finally:
            self._refreshing_messages = False

    def _clear_messages_display(self):
        for msg_id, widget in list(self._message_widgets.items()):
            if widget and widget != self.select_channel_label:
                self.messages_layout.removeWidget(widget)
                widget.deleteLater()
        self._message_widgets.clear()

    def _update_messages_display(self):
        self._clear_messages_display()
        self._update_messages_display_incremental(set())

    def _update_messages_display_incremental(self, new_message_ids: set):
        widgets_to_remove = []
        for msg_id, widget in list(self._message_widgets.items()):
            if msg_id not in new_message_ids:
                widgets_to_remove.append(msg_id)
        for msg_id in widgets_to_remove:
            widget = self._message_widgets.pop(msg_id, None)
            if widget and widget != self.select_channel_label:
                self.messages_layout.removeWidget(widget)
                widget.deleteLater()
        added_count = 0
        for msg in self.messages:
            msg_id = msg['id']
            if msg_id in self._message_widgets:
                widget = self._message_widgets[msg_id]
                widget.setText(f"{msg['timestamp']}: {msg['message']}")
            else:
                msg_widget = QLabel(f"{msg['timestamp']}: {msg['message']}")
                msg_widget.setWordWrap(True)
                msg_widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
                message_bg_color = 'rgba(255, 255, 255, 0.1)'
                msg_widget.setStyleSheet(f'padding: 5px; background-color: {message_bg_color}; border-radius: 3px; color: {text_color};')
                self.messages_layout.addWidget(msg_widget)
                self._message_widgets[msg_id] = msg_widget
                added_count += 1
        if added_count > 0:
            scroll_bar = self.messages_area.verticalScrollBar()
            if scroll_bar:
                QTimer.singleShot(50, lambda: scroll_bar.setValue(scroll_bar.maximum()))

    def _show_select_channel_message(self):
        self._clear_messages_display()
        self.select_channel_label.show()
        self.update_timer.stop()

    def _on_input_changed(self, text: str):
        if not self.current_channel:
            self.send_button.setEnabled(False)
            return
        has_text = bool(text.strip())
        can_send = has_text and self._can_send() and (not self._loading_messages)
        self.send_button.setEnabled(can_send)

    def _on_limit_changed(self, value: int):
        self.max_messages_limit = value
        self.app_state.local_config['chat_message_limit'] = value
        parent = self.parent()
        if parent and hasattr(parent, 'settings_manager'):
            settings_mgr = getattr(parent, 'settings_manager', None)
            if settings_mgr and hasattr(settings_mgr, 'write_local_config'):
                settings_mgr.write_local_config()
        if self.current_channel:
            QTimer.singleShot(100, self._reload_messages_with_limit)

    def _reload_messages_with_limit(self):
        if not self.current_channel or self._loading_messages:
            return
        self._loading_messages = True
        try:
            all_messages = self.chat_manager.get_messages(self.current_channel)
            limited_messages = all_messages[-self.max_messages_limit:] if len(all_messages) > self.max_messages_limit else all_messages
            self.messages = limited_messages
            self._last_message_ids = {msg['id'] for msg in limited_messages}
            self._update_messages_display()
        except Exception as e:
            logging.warning(f'ChatWindow: Failed to reload messages with limit: {e}')
        finally:
            self._loading_messages = False

    def _can_send(self) -> bool:
        if not self.current_channel:
            return False
        current_time = time.time()
        time_since_last_send = current_time - self.last_send_time
        return time_since_last_send >= self.send_cooldown

    def _send_message(self):
        if not check_internet_connection():
            self.status_label.setText(tr('chat.no_internet'))
            return
        if not self.current_channel:
            self.status_label.setText(tr('chat.select_channel_first'))
            return
        if self._loading_messages:
            return
        message = self.message_input.text().strip()
        if not message:
            return
        if not self._can_send():
            return
        if len(message) > ChatManager.MESSAGE_MAX_LENGTH:
            self.status_label.setText(tr('chat.message_too_long'))
            return
        if self.chat_manager._contains_url(message):
            self.status_label.setText(tr('chat.contains_url'))
            return
        saved_channel = self.current_channel
        if not saved_channel:
            logging.error('ChatWindow: No channel selected, cannot send message')
            return
        self._updating_channel_buttons = True
        self.message_input.setEnabled(False)
        self.send_button.setEnabled(False)
        QTimer.singleShot(0, lambda: self._send_message_async(saved_channel, message))

    def _send_message_async(self, channel: str, message: str):
        try:
            if self.current_channel != channel:
                self.status_label.setText(tr('chat.error_sending'))
                return
            success, error = self.chat_manager.send_message(channel, message)
            if success:
                if self.current_channel != channel:
                    if channel in self.channel_buttons:
                        self._switch_channel(channel)
                    return
                self.message_input.clear()
                self.last_send_time = time.time()
                self._start_cooldown()
                self.status_label.setText('')
                self._sync_channel_buttons()
                QTimer.singleShot(200, lambda: self._refresh_messages_immediate(channel))
            elif error == 'message_too_long':
                self.status_label.setText(tr('chat.message_too_long'))
            elif error == 'contains_url':
                self.status_label.setText(tr('chat.contains_url'))
            elif error == 'no_internet':
                self.status_label.setText(tr('chat.no_internet'))
            elif error == 'config_error':
                self.status_label.setText(tr('chat.config_error'))
            elif error == 'channel_error':
                self.status_label.setText(tr('chat.channel_error'))
            else:
                self.status_label.setText(tr('chat.error_sending'))
        except Exception as e:
            logging.warning(f'ChatWindow: Failed to send message: {e}')
            self.status_label.setText(tr('chat.error_sending'))
        finally:
            self._updating_channel_buttons = False
            self._sync_channel_buttons()
            if self.current_channel == channel:
                self.message_input.setEnabled(True)
                self._on_input_changed(self.message_input.text())
            elif channel in self.channel_buttons:
                self._switch_channel(channel)

    def _start_cooldown(self):
        self.last_send_time = time.time()
        self.cooldown_timer.start()
        self.cooldown_label.show()
        self.send_button.setEnabled(False)

    def _update_cooldown(self):
        current_time = time.time()
        time_since_last_send = current_time - self.last_send_time
        remaining = max(0, self.send_cooldown - time_since_last_send)
        if remaining > 0:
            self.cooldown_label.setText(tr('chat.wait_before_send', seconds=int(remaining)))
            self.send_button.setEnabled(False)
        else:
            self.cooldown_label.hide()
            self.cooldown_timer.stop()
            if self.current_channel and self.message_input.text().strip() and (not self._loading_messages):
                self.send_button.setEnabled(True)

    def _apply_theme(self):
        bg_color = get_theme_color(self.app_state.local_config, 'background', '#000000')
        border_color = get_theme_color(self.app_state.local_config, 'border', 'white')
        button_color = get_theme_color(self.app_state.local_config, 'button', 'black')
        hover_color = get_theme_color(self.app_state.local_config, 'button_hover', '#333')
        text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
        secondary_text_color = get_theme_color(self.app_state.local_config, 'version_text', '#888888')
        message_bg_color = 'rgba(255, 255, 255, 0.1)'
        self.setStyleSheet(f'\n            QDialog {{\n                background-color: {bg_color};\n                color: {text_color};\n            }}\n            QPushButton {{\n                background-color: {button_color};\n                border: 2px solid {border_color};\n                color: {text_color};\n                padding: 8px 15px;\n                font-weight: bold;\n            }}\n            QPushButton:hover {{\n                background-color: {hover_color};\n            }}\n            QPushButton:checked {{\n                background-color: {hover_color};\n                border: 2px solid {hover_color};\n            }}\n            QPushButton:disabled {{\n                background-color: #555;\n                color: #999;\n            }}\n            QLineEdit {{\n                background-color: {bg_color};\n                border: 2px solid {border_color};\n                color: {text_color};\n                padding: 8px;\n                font-size: 13px;\n            }}\n            QLineEdit:focus {{\n                border: 2px solid {hover_color};\n            }}\n            QSpinBox {{\n                background-color: {bg_color};\n                border: 1px solid {border_color};\n                color: {secondary_text_color};\n                padding: 2px;\n                font-size: 12px;\n                min-width: 60px;\n                max-width: 80px;\n            }}\n            QSpinBox:focus {{\n                border: 1px solid {hover_color};\n            }}\n            QScrollArea {{\n                background-color: {bg_color};\n                border: 2px solid {border_color};\n            }}\n            QLabel {{\n                color: {text_color};\n            }}\n        ')
        self.select_channel_label.setStyleSheet(f'color: {secondary_text_color}; font-size: 16px; padding: 50px;')
        self.cooldown_label.setStyleSheet('color: orange; font-size: 11px;')
        self.status_label.setStyleSheet(f'color: {secondary_text_color}; font-size: 10px;')
        self.limit_label.setStyleSheet(f'color: {secondary_text_color}; font-size: 12px;')
        for msg_widget in self._message_widgets.values():
            if msg_widget and msg_widget != self.select_channel_label:
                msg_widget.setStyleSheet(f'padding: 5px; background-color: {message_bg_color}; border-radius: 3px; color: {text_color};')

    def closeEvent(self, event):
        self.update_timer.stop()
        self.cooldown_timer.stop()
        self.messages = []
        self._message_widgets.clear()
        self.current_channel = None
        event.accept()
