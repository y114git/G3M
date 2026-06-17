"""Dialog for the integrated chat view."""

import contextlib
import logging
import time

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.config import CHAT_MESSAGE_BACKGROUND_COLOR
from services.chat_service import ChatManager
from services.localization_service import tr
from ui.common.dialog_theme import (
    build_dialog_theme_stylesheet,
    get_dialog_theme_values,
)
from ui.common.styling import clamp_border_radius
from utils.path_utils import colored_icon

logger = logging.getLogger(__name__)


class ChatWindow(QDialog):
    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.chat_service = ChatManager()
        self.current_channel = None
        self.messages = []
        self.last_send_time = 0
        self.send_cooldown = 5
        self._loading_messages = False
        self._refreshing_messages = False
        self._last_message_ids = set()
        self._message_widgets = {}
        self._closed = False
        self.max_messages_limit = self.app_state.local_config.get(
            "chat_message_limit", 50
        )
        if (
            not isinstance(self.max_messages_limit, int)
            or self.max_messages_limit < 1
            or self.max_messages_limit > 100
        ):
            self.max_messages_limit = 50
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._refresh_messages_async)
        self.update_timer.setInterval(5000)
        from workers.chat_request_worker import ChatRequestThread

        self.chat_request_thread = ChatRequestThread(self)
        self.chat_request_thread.messages_received.connect(self._on_messages_received)
        self.chat_request_thread.message_sent.connect(self._on_message_sent)
        self.chat_request_thread.error_occurred.connect(self._on_chat_error)
        self._settings_service = (
            parent.settings_service
            if parent and hasattr(parent, "settings_service")
            else None
        )
        self.setWindowTitle(tr("chat.window_title"))
        self.setMinimumSize(600, 500)
        self.resize(800, 600)
        self.setup_ui()
        self._apply_theme()
        saved_channel = self.app_state.local_config.get("last_chat_channel")
        if saved_channel and saved_channel in self.channel_buttons:
            self._switch_channel(saved_channel)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        channels_layout = QHBoxLayout()
        channels_layout.setSpacing(10)

        tabs_container = QWidget()
        tabs_container_layout = QHBoxLayout(tabs_container)
        tabs_container_layout.setContentsMargins(0, 0, 0, 0)
        tabs_container_layout.setSpacing(10)
        self.channel_buttons = {}
        self._updating_channel_buttons = False
        channels = [
            ("en", "chat.channel_english"),
            ("ru", "chat.channel_russian"),
            ("es", "chat.channel_spanish"),
            ("zh", "chat.channel_chinese"),
            ("int", "chat.channel_international"),
        ]
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
            tabs_container_layout.addWidget(btn)
            self.channel_buttons[channel_code] = btn

        tabs_container.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
        )
        channels_layout.addWidget(tabs_container)
        channels_layout.addStretch()

        refresh_container = QWidget()
        refresh_container_layout = QHBoxLayout(refresh_container)
        refresh_container_layout.setContentsMargins(0, 0, 0, 0)
        refresh_container_layout.setSpacing(0)
        self.refresh_button = QPushButton()
        self.refresh_button.clicked.connect(self._manual_refresh_messages)
        refresh_container_layout.addWidget(self.refresh_button)
        channels_layout.addWidget(refresh_container)
        layout.addLayout(channels_layout)
        self.messages_area = QScrollArea()
        self.messages_area.setWidgetResizable(True)
        self.messages_area.setFrameShape(QFrame.Shape.NoFrame)
        self.messages_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.messages_widget = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.messages_layout.setSpacing(5)
        self.messages_layout.setContentsMargins(10, 10, 10, 10)
        self.select_channel_label = QLabel(tr("chat.select_channel_first"))
        self.select_channel_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.select_channel_label.hide()
        self.messages_layout.addWidget(self.select_channel_label)
        self.messages_area.setWidget(self.messages_widget)
        layout.addWidget(self.messages_area)
        input_layout = QHBoxLayout()
        input_layout.setSpacing(10)
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText(tr("chat.message_input_placeholder"))
        self.message_input.setMaxLength(ChatManager.MESSAGE_MAX_LENGTH)
        self.message_input.returnPressed.connect(self._send_message)
        self.message_input.textChanged.connect(self._on_input_changed)
        self.message_input.setEnabled(False)
        input_layout.addWidget(self.message_input)
        self.send_button = QPushButton(tr("chat.send_button"))
        self.send_button.clicked.connect(self._send_message)
        self.send_button.setEnabled(False)
        input_layout.addWidget(self.send_button)
        layout.addLayout(input_layout)
        limit_layout = QHBoxLayout()
        limit_layout.addStretch()
        self.limit_label = QLabel(tr("chat.message_limit_label"))
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
        self._set_channel_buttons(self.current_channel)

    def _set_channel_buttons(self, channel: str):
        self._updating_channel_buttons = True
        try:
            for ch, btn in self.channel_buttons.items():
                btn.blockSignals(True)
                btn.setChecked(ch == channel)
                btn.blockSignals(False)
        finally:
            self._updating_channel_buttons = False

    def _switch_channel(self, channel: str):
        if not getattr(self.app_state, "has_internet", False):
            self.status_label.setText(tr("chat.no_internet"))
            return
        if self.current_channel == channel:
            return
        if self._loading_messages:
            return
        self.update_timer.stop()
        self._set_channel_buttons(channel)
        self._clear_messages_display()
        self.messages = []
        self._last_message_ids = set()
        self._message_widgets.clear()
        self.current_channel = channel
        self.app_state.local_config["last_chat_channel"] = channel
        if self._settings_service:
            self._settings_service.write_local_config()
        self.select_channel_label.hide()
        self.message_input.setEnabled(True)
        self.update_timer.start()
        self._load_messages_async()

    def _load_messages_async(self):
        if not self.current_channel or self._loading_messages:
            return
        self._loading_messages = True
        self.status_label.setText(tr("chat.loading_messages"))
        self.message_input.setEnabled(False)
        self.send_button.setEnabled(False)
        if self.chat_request_thread.isRunning():
            self.chat_request_thread.wait(1000)
        self.chat_request_thread.request_messages(self.current_channel)

    def _on_messages_received(self, channel: str, new_messages: list):
        if self._closed:
            return
        if self._loading_messages:
            if not self.current_channel or self.current_channel != channel:
                self._loading_messages = False
                return
            try:
                if self._closed:
                    return
                self.messages = []
                self._last_message_ids = set()
                self._clear_messages_display()
                limited_messages = (
                    new_messages[-self.max_messages_limit :]
                    if len(new_messages) > self.max_messages_limit
                    else new_messages
                )
                self.messages = limited_messages
                self._last_message_ids = {msg["id"] for msg in limited_messages}
                if not self._closed:
                    self._update_messages_display()
                    self._sync_channel_buttons()
                    self.status_label.setText("")
                    self.message_input.setEnabled(True)
                    self._on_input_changed(self.message_input.text())
            except (RuntimeError, AttributeError) as e:
                self._closed = True
                logger.debug(
                    f"ChatWindow: Widget deleted while processing messages: {e}"
                )
                return
            except Exception as e:
                logger.warning(f"ChatWindow: Failed to process messages: {e}")
                if not self._closed:
                    try:
                        self.status_label.setText(tr("chat.error_loading"))
                        self.message_input.setEnabled(True)
                    except (RuntimeError, AttributeError):
                        self._closed = True
            finally:
                self._loading_messages = False
        elif self._refreshing_messages:
            self._on_messages_refreshed(channel, new_messages)

    def _refresh_messages_immediate(self, channel: str):
        if not self.current_channel or self.current_channel != channel:
            return
        if self._loading_messages or self._refreshing_messages:
            return
        self._request_refresh_messages(force_refresh=True)

    def _request_refresh_messages(self, force_refresh: bool = False):
        if not getattr(self.app_state, "has_internet", False):
            return
        self._refreshing_messages = True
        if self.chat_request_thread.isRunning():
            self._refreshing_messages = False
            return
        self.chat_request_thread.request_messages(
            self.current_channel, force_refresh=force_refresh
        )

    def _manual_refresh_messages(self):
        if not self.current_channel or self._loading_messages or self._refreshing_messages:
            return
        if not getattr(self.app_state, "has_internet", False):
            return
        self._refreshing_messages = True
        if self.chat_request_thread.isRunning():
            self._refreshing_messages = False
            return
        self.chat_request_thread.request_messages(
            self.current_channel, force_refresh=True
        )

    def _refresh_messages_async(self):
        if (
            not self.current_channel
            or self._loading_messages
            or self._refreshing_messages
        ):
            return
        self._request_refresh_messages()

    def _on_messages_refreshed(self, channel: str, new_messages: list):
        if self._closed:
            self._refreshing_messages = False
            return
        if not self.current_channel or self.current_channel != channel:
            self._refreshing_messages = False
            return
        try:
            limited_messages = (
                new_messages[-self.max_messages_limit :]
                if len(new_messages) > self.max_messages_limit
                else new_messages
            )
            new_message_ids = {msg["id"] for msg in limited_messages}
            if new_message_ids != self._last_message_ids:
                self.messages = limited_messages
                self._last_message_ids = new_message_ids
                if not self._closed:
                    self._update_messages_display_incremental(new_message_ids)
        except (RuntimeError, AttributeError) as e:
            self._closed = True
            logger.debug(f"ChatWindow: Widget deleted while refreshing messages: {e}")
        except Exception as e:
            logger.debug(f"ChatWindow: Failed to refresh messages: {e}")
        finally:
            self._refreshing_messages = False

    def _clear_messages_display(self):
        for widget in self._iter_message_widgets():
            self.messages_layout.removeWidget(widget)
            widget.deleteLater()
        self._message_widgets.clear()

    def _iter_message_widgets(self):
        for widget in self._message_widgets.values():
            if widget and widget != self.select_channel_label:
                yield widget

    @staticmethod
    def _style_message_widget(msg_widget, border_radius: int, text_color: str) -> None:
        msg_radius = clamp_border_radius(
            border_radius, height=max(1, msg_widget.sizeHint().height())
        )
        msg_widget.setStyleSheet(
            f"padding: 5px; background-color: {CHAT_MESSAGE_BACKGROUND_COLOR}; border-radius: {msg_radius}px; color: {text_color};"
        )

    def _update_messages_display(self):
        self._clear_messages_display()
        self._update_messages_display_incremental(set())

    def _update_messages_display_incremental(self, new_message_ids: set):
        theme = get_dialog_theme_values(self.app_state)
        widgets_to_remove = []
        for msg_id in list(self._message_widgets):
            if msg_id not in new_message_ids:
                widgets_to_remove.append(msg_id)
        for msg_id in widgets_to_remove:
            widget = self._message_widgets.pop(msg_id, None)
            if widget and widget != self.select_channel_label:
                self.messages_layout.removeWidget(widget)
                widget.deleteLater()
        added_count = 0
        for msg in self.messages:
            msg_id = msg["id"]
            if msg_id in self._message_widgets:
                widget = self._message_widgets[msg_id]
                widget.setText(f"{msg['timestamp']}: {msg['message']}")
            else:
                msg_widget = QLabel(f"{msg['timestamp']}: {msg['message']}")
                msg_widget.setWordWrap(True)
                msg_widget.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                self._style_message_widget(
                    msg_widget, theme["border_radius"], theme["main_text"]
                )
                self.messages_layout.addWidget(msg_widget)
                self._message_widgets[msg_id] = msg_widget
                added_count += 1
        if added_count > 0:
            scroll_bar = self.messages_area.verticalScrollBar()
            if scroll_bar:
                scroll_bar.setValue(scroll_bar.maximum())

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
        self.app_state.local_config["chat_message_limit"] = value
        parent = self.parent()
        if parent and hasattr(parent, "settings_service"):
            settings_mgr = getattr(parent, "settings_service", None)
            if settings_mgr and hasattr(settings_mgr, "write_local_config"):
                settings_mgr.write_local_config()
        if self.current_channel:
            self._reload_messages_with_limit()

    def _reload_messages_with_limit(self):
        if not self.current_channel or self._loading_messages:
            return
        self._loading_messages = True
        if self.chat_request_thread.isRunning():
            self.chat_request_thread.cancel()
        self.chat_request_thread.request_messages(self.current_channel)

    def _can_send(self) -> bool:
        if not self.current_channel:
            return False
        current_time = time.time()
        time_since_last_send = current_time - self.last_send_time
        return time_since_last_send >= self.send_cooldown

    def _send_message(self):
        if not getattr(self.app_state, "has_internet", False):
            self.status_label.setText(tr("chat.no_internet"))
            return
        if not self.current_channel:
            self.status_label.setText(tr("chat.select_channel_first"))
            return
        if self._loading_messages:
            return
        message = self.message_input.text().strip()
        if not message:
            return
        if not self._can_send():
            return
        if len(message) > ChatManager.MESSAGE_MAX_LENGTH:
            self.status_label.setText(tr("chat.message_too_long"))
            return
        if self.chat_service._contains_url(message):
            self.status_label.setText(tr("chat.contains_url"))
            return
        saved_channel = self.current_channel
        if not saved_channel:
            logger.error("ChatWindow: No channel selected, cannot send message")
            return
        self._updating_channel_buttons = True
        self.message_input.setEnabled(False)
        self.send_button.setEnabled(False)
        self._send_message_async(saved_channel, message)

    def _send_message_async(self, channel: str, message: str):
        if self.chat_request_thread.isRunning():
            self.status_label.setText(tr("chat.error_sending"))
            return
        self.chat_request_thread.request_send_message(channel, message)

    def _on_message_sent(self, channel: str, success: bool, error: str):
        if self._closed:
            return
        try:
            if self.current_channel != channel:
                if not self._closed:
                    try:
                        self.status_label.setText(tr("chat.error_sending"))
                    except (RuntimeError, AttributeError):
                        self._closed = True
                return
            if success:
                if self.current_channel != channel:
                    if channel in self.channel_buttons:
                        self._switch_channel(channel)
                    return
                if not self._closed:
                    try:
                        self.message_input.clear()
                        self.last_send_time = time.time()
                        self._start_cooldown()
                        self.status_label.setText("")
                        self._sync_channel_buttons()
                        if not self._closed:
                            self._refresh_messages_immediate(channel)
                    except (RuntimeError, AttributeError):
                        self._closed = True
            elif not self._closed:
                try:
                    error_keys = {
                        "message_too_long": "chat.message_too_long",
                        "contains_url": "chat.contains_url",
                        "no_internet": "chat.no_internet",
                        "config_error": "chat.config_error",
                        "channel_error": "chat.channel_error",
                    }
                    self.status_label.setText(
                        tr(error_keys.get(error, "chat.error_sending"))
                    )
                except (RuntimeError, AttributeError):
                    self._closed = True
        except (RuntimeError, AttributeError) as e:
            self._closed = True
            logger.debug(f"ChatWindow: Widget deleted while handling send result: {e}")
        except Exception as e:
            logger.warning(f"ChatWindow: Failed to handle send result: {e}")
            if not self._closed:
                try:
                    self.status_label.setText(tr("chat.error_sending"))
                except (RuntimeError, AttributeError):
                    self._closed = True
        finally:
            if not self._closed:
                try:
                    self._updating_channel_buttons = False
                    self._sync_channel_buttons()
                    if self.current_channel == channel:
                        self.message_input.setEnabled(True)
                        self._on_input_changed(self.message_input.text())
                    elif channel in self.channel_buttons:
                        self._switch_channel(channel)
                except (RuntimeError, AttributeError):
                    self._closed = True

    def _on_chat_error(self, channel: str, error_message: str):
        if self._closed:
            return
        if self._loading_messages:
            if not self._closed:
                try:
                    self.status_label.setText(tr("chat.error_loading"))
                    self.message_input.setEnabled(True)
                except (RuntimeError, AttributeError):
                    self._closed = True
            self._loading_messages = False
        elif self._refreshing_messages:
            self._refreshing_messages = False
        logger.warning(
            f"ChatWindow: Chat request error for channel {channel}: {error_message}"
        )

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
            self.cooldown_label.setText(
                tr("chat.wait_before_send", seconds=int(remaining))
            )
            self.send_button.setEnabled(False)
        else:
            self.cooldown_label.hide()
            self.cooldown_timer.stop()
            if (
                self.current_channel
                and self.message_input.text().strip()
                and (not self._loading_messages)
            ):
                self.send_button.setEnabled(True)

    def _apply_theme(self):
        theme = get_dialog_theme_values(self.app_state)
        self.setStyleSheet(
            build_dialog_theme_stylesheet(self.app_state)
            + f"""\n      QPushButton:checked {{\n        background-color: {theme["hover"]};\n        border: 2px solid {theme["hover"]};\n      }}\n      QPushButton:disabled {{\n        background-color: #555;\n        color: #999;\n      }}\n      QSpinBox {{\n        background-color: {theme["background"]};\n        border: 2px solid {theme["border"]};\n        color: {theme["secondary_text"]};\n        padding: 2px;\n        font-size: 12px;\n        min-width: 60px;\n        max-width: 80px;\n      }}\n      QSpinBox:focus {{\n        border: 2px solid {theme["hover"]};\n      }}\n      QScrollArea {{\n        background-color: {theme["background"]};\n        border: 2px solid {theme["border"]};\n      }}\n    """
        )
        self.select_channel_label.setStyleSheet(
            f"color: {theme['secondary_text']}; font-size: 16px; padding: 50px;"
        )
        self.cooldown_label.setStyleSheet("color: orange; font-size: 11px;")
        self.status_label.setStyleSheet(
            f"color: {theme['secondary_text']}; font-size: 10px;"
        )
        self.limit_label.setStyleSheet(
            f"color: {theme['secondary_text']}; font-size: 12px;"
        )
        self.refresh_button.setIcon(colored_icon("refresh", theme["main_text"]))
        self.refresh_button.setIconSize(QSize(20, 20))
        for msg_widget in self._iter_message_widgets():
            self._style_message_widget(
                msg_widget, theme["border_radius"], theme["main_text"]
            )

    def closeEvent(self, event):
        self._closed = True
        self.update_timer.stop()
        self.cooldown_timer.stop()
        if self.chat_request_thread.isRunning():
            self.chat_request_thread.cancel()
            try:
                self.chat_request_thread.blockSignals(True)
                for sig in (
                    self.chat_request_thread.messages_received,
                    self.chat_request_thread.message_sent,
                    self.chat_request_thread.error_occurred,
                ):
                    with contextlib.suppress(TypeError, RuntimeError):
                        sig.disconnect()
                self.chat_request_thread.blockSignals(False)
            except (TypeError, RuntimeError, AttributeError):
                pass
        self.messages = []
        self._message_widgets.clear()
        self.current_channel = None
        event.accept()
