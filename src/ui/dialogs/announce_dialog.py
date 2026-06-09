"""Dialog for application announcements."""

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from services.announce_service import AnnounceService
from services.localization_service import tr
from ui.common.dialog_theme import apply_dialog_theme, get_dialog_theme_values
from utils.native_integration import open_url_native


class AnnouncePanel(QWidget):
    accepted_with_ok = pyqtSignal()

    def __init__(
        self,
        announce: dict,
        parent=None,
        *,
        app_state=None,
        on_submit_poll=None,
        close_on_ok: bool = True,
    ) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self._announce = announce or {}
        self._on_submit_poll = on_submit_poll
        self._close_on_ok = close_on_ok
        self._announce_type = AnnounceService.get_announce_type(self._announce)
        self._poll_options = AnnounceService.get_poll_options(self._announce)
        self._allow_multiple = AnnounceService.allows_multiple_selection(self._announce)
        self._option_buttons: list[QPushButton] = []
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(0, 0, 0, 0)
        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(True)
        document = self.text_browser.document()
        if document is not None:
            document.setDefaultStyleSheet("p { margin: 0.5em 0; }")
        try:
            from ui.common.rich_html import set_rich_html

            set_rich_html(self.text_browser, self._announce.get("message", ""))
        except Exception as e:
            logging.debug(f"set_rich_html failed, falling back to setHtml: {e}")
            self.text_browser.setHtml(self._announce.get("message", ""))
        self.text_browser.setReadOnly(True)
        layout.addWidget(self.text_browser, 1)
        link_layout = QHBoxLayout()
        link_layout.addStretch()
        self.details_button = QPushButton(tr("dialogs.announce_details_button"))
        self.details_button.setToolTip(tr("tooltips.announcement_details"))
        self.details_button.clicked.connect(self._open_link)
        link_layout.addWidget(self.details_button)
        link_layout.addStretch()
        layout.addLayout(link_layout)
        button_layout = QHBoxLayout()
        self._poll_buttons_layout = QHBoxLayout()
        self._poll_buttons_layout.setSpacing(8)
        button_layout.addLayout(self._poll_buttons_layout)
        button_layout.addStretch()
        self.ok_button = QPushButton(tr("ui.ok"))
        self.ok_button.setToolTip(tr("tooltips.confirm"))
        self.ok_button.clicked.connect(self._on_ok_clicked)
        self.ok_button.setDefault(True)
        button_layout.addWidget(self.ok_button)
        layout.addLayout(button_layout)
        self._populate_poll_buttons()
        self._apply_poll_button_theme()
        self.details_button.setVisible(bool(self._announce.get("link", "")))
        self.sync_ok_button_state()

    def selected_options(self) -> list[str]:
        return [
            button.text()
            for button in self._option_buttons
            if button.isChecked()
        ]

    @property
    def option_buttons(self) -> list[QPushButton]:
        """Public access to option buttons for testing purposes."""
        return self._option_buttons

    def select_option(self, index_or_label: int | str) -> None:
        """Select an option by index (0-based) or by label text."""
        if isinstance(index_or_label, int):
            if 0 <= index_or_label < len(self._option_buttons):
                self._option_buttons[index_or_label].click()
        else:
            for button in self._option_buttons:
                if button.text() == index_or_label:
                    button.click()
                    break

    def click_option(self, index_or_label: int | str) -> None:
        """Alias for select_option - click an option by index or label."""
        self.select_option(index_or_label)

    def set_preview_announce(self, announce: dict) -> None:
        self._announce = announce or {}
        self._announce_type = AnnounceService.get_announce_type(self._announce)
        self._poll_options = AnnounceService.get_poll_options(self._announce)
        self._allow_multiple = AnnounceService.allows_multiple_selection(self._announce)
        try:
            from ui.common.rich_html import set_rich_html

            set_rich_html(self.text_browser, self._announce.get("message", ""))
        except Exception:
            self.text_browser.setHtml(self._announce.get("message", ""))
        if self.details_button is not None:
            self.details_button.setVisible(bool(self._announce.get("link", "")))
        self._populate_poll_buttons()
        self.sync_ok_button_state()

    def _on_ok_clicked(self):
        if AnnounceService.is_poll_announce(self._announce):
            if not self.selected_options():
                return
            if callable(self._on_submit_poll) and not self._on_submit_poll(self.selected_options()):
                return
        self.accepted_with_ok.emit()

    def _open_link(self):
        link = str(self._announce.get("link", "") or "").strip()
        if link:
            try:
                open_url_native(link)
            except Exception as e:
                logging.error(f"Failed to open announce link: {e}")

    def _populate_poll_buttons(self) -> None:
        while self._poll_buttons_layout.count():
            item = self._poll_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._option_buttons.clear()
        if not AnnounceService.is_poll_announce(self._announce):
            return
        for option in self._poll_options:
            button = QPushButton(option)
            button.setCheckable(True)
            button.setProperty("pollOption", True)
            button.setToolTip(tr("tooltips.announcement_option"))
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(0)
            button.setMaximumWidth(max(70, button.sizeHint().width() + 18))
            button.clicked.connect(
                lambda is_checked, btn=button: self._handle_option_clicked(btn, is_checked)
            )
            self._poll_buttons_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
            self._option_buttons.append(button)

    def _handle_option_clicked(self, clicked_button: QPushButton, checked: bool) -> None:
        if not self._allow_multiple:
            if checked:
                for button in self._option_buttons:
                    if button is not clicked_button:
                        button.blockSignals(True)
                        button.setChecked(False)
                        button.blockSignals(False)
            else:
                clicked_button.blockSignals(True)
                clicked_button.setChecked(True)
                clicked_button.blockSignals(False)
        self.sync_ok_button_state()

    def sync_ok_button_state(self) -> None:
        if not AnnounceService.is_poll_announce(self._announce):
            self.ok_button.setEnabled(True)
            return
        self.ok_button.setEnabled(bool(self.selected_options()))

    def _apply_poll_button_theme(self) -> None:
        theme = get_dialog_theme_values(self.app_state)
        poll_styles = f"""
            QPushButton[pollOption="true"] {{
                padding: 6px 12px;
                min-height: 30px;
            }}
            QPushButton[pollOption="true"]:checked {{
                background-color: {theme["hover"]};
                border-color: {theme["border"]};
            }}
            QPushButton[pollOption="true"]:checked:hover {{
                background-color: {theme["hover"]};
            }}
            """
        existing = self.styleSheet() or ""
        if "pollOption" not in existing:
            self.setStyleSheet(existing + poll_styles)

    def relocalize_ui(self) -> None:
        self.details_button.setText(tr("dialogs.announce_details_button"))
        self.details_button.setToolTip(tr("tooltips.announcement_details"))
        self.ok_button.setText(tr("ui.ok"))
        self.sync_ok_button_state()


class AnnounceDialog(QDialog):
    accepted_with_ok = pyqtSignal()

    def __init__(self, announce: dict, parent=None, *, on_submit_poll=None) -> None:
        super().__init__(parent)
        self._parent_window = parent
        self.app_state = getattr(parent, "app_state", None)
        self._announce = announce or {}
        try:
            self._announce_version = int(self._announce.get("version") or 0)
        except (TypeError, ValueError):
            self._announce_version = 0
        self.setWindowTitle(tr("dialogs.announce_title"))
        self.setMinimumSize(860, 680)
        apply_dialog_theme(self, self.app_state)
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        self.panel = AnnouncePanel(
            announce,
            self,
            app_state=self.app_state,
            on_submit_poll=on_submit_poll,
        )
        self.panel.accepted_with_ok.connect(self._on_panel_accepted)
        layout.addWidget(self.panel, 1)

    def _on_panel_accepted(self) -> None:
        self.accepted_with_ok.emit()
        self.accept()

    def reject(self) -> None:
        self._save_current_version()
        super().reject()

    def _save_current_version(self) -> None:
        if self._announce_version > 0 and self.app_state is not None:
            self.app_state.local_config["announce_version"] = self._announce_version
            settings_service = getattr(
                getattr(self._parent_window, "settings_service", None),
                "write_local_config",
                None,
            )
            if callable(settings_service):
                settings_service()

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("dialogs.announce_title"))
        self.panel.relocalize_ui()
