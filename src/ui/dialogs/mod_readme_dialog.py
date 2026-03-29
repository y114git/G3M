"""Dialog for viewing README/text files from a mod folder."""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from services.localization_service import tr
from ui.common.dialog_theme import (
    build_dialog_theme_stylesheet,
    get_dialog_theme_values,
)
from utils.mod_readme_utils import is_markdown_file, read_mod_readme


class _ReadmeTab(QWidget):
    def __init__(self, file_path: str, parent=None) -> None:
        super().__init__(parent)
        self.file_path = file_path
        self._loaded = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.viewer = QTextBrowser(self)
        self.viewer.setOpenExternalLinks(False)
        self.viewer.anchorClicked.connect(self._open_link)
        self.viewer.setReadOnly(True)
        layout.addWidget(self.viewer)

    def load_content(self) -> None:
        if self._loaded:
            return
        content = read_mod_readme(self.file_path)
        if is_markdown_file(self.file_path):
            self.viewer.setMarkdown(content)
        else:
            self.viewer.setPlainText(content)
        self._loaded = True

    def unload_content(self) -> None:
        if not self._loaded:
            return
        self.viewer.clear()
        self._loaded = False

    def _open_link(self, url: QUrl) -> None:
        allowed_schemes = {"http", "https", "mailto"}
        if url and url.isValid() and url.scheme().lower() in allowed_schemes:
            QDesktopServices.openUrl(url)


class ModReadmeDialog(QDialog):
    """Tabbed README viewer with lazy per-tab loading."""

    def __init__(self, app_state, mod_name: str, readme_files: list[str], parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._mod_name = mod_name or "Mod"
        self._readme_files = list(readme_files or [])
        self._current_index = -1
        self._build_ui()
        self.relocalize_ui()
        self.refresh_theme()
        if self._tabs.count():
            self._tabs.setCurrentIndex(0)
            self._on_tab_changed(0)

    def _build_ui(self) -> None:
        self.resize(920, 680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self._title_label = QLabel(self)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setObjectName("readmeTitle")
        layout.addWidget(self._title_label)

        self._tabs = QTabWidget(self)
        self._tabs.setDocumentMode(True)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs, 1)

        for file_path in self._readme_files:
            tab = _ReadmeTab(file_path, self._tabs)
            self._tabs.addTab(tab, os.path.basename(file_path))

        self._empty_label = QLabel(tr("dialogs.no_readme_files"), self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_label)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self._close_button = QPushButton(self)
        self._close_button.clicked.connect(self.accept)
        button_row.addWidget(self._close_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self._sync_empty_state()

    def _sync_empty_state(self) -> None:
        has_tabs = self._tabs.count() > 0
        self._tabs.setVisible(has_tabs)
        self._empty_label.setVisible(not has_tabs)

    def _on_tab_changed(self, index: int) -> None:
        if self._current_index == index:
            return
        if 0 <= self._current_index < self._tabs.count():
            old_tab = self._tabs.widget(self._current_index)
            if isinstance(old_tab, _ReadmeTab):
                old_tab.unload_content()
        self._current_index = index
        if 0 <= index < self._tabs.count():
            new_tab = self._tabs.widget(index)
            if isinstance(new_tab, _ReadmeTab):
                new_tab.load_content()

    def refresh_theme(self) -> None:
        theme = get_dialog_theme_values(self._app_state)
        markdown_css = f"""
            body {{
                color: {theme["main_text"]};
                font-size: 14px;
                line-height: 1.45;
            }}
            a {{
                color: {theme["hover"]};
            }}
            pre, code {{
                background-color: {theme["background"]};
                color: {theme["main_text"]};
                border-radius: 8px;
            }}
            pre {{
                padding: 10px;
            }}
            blockquote {{
                border-left: 3px solid {theme["border"]};
                margin-left: 0;
                padding-left: 12px;
                color: {theme["secondary_text"]};
            }}
        """
        self.setStyleSheet(
            build_dialog_theme_stylesheet(self._app_state)
            + f"""
            QLabel {{
                color: {theme["main_text"]};
            }}
            QLabel#readmeTitle {{
                font-size: 18px;
                font-weight: 700;
            }}
            QTabWidget::tab-bar {{
                alignment: center;
                top: 4px;
            }}
            QTabWidget::pane {{
                border: 2px solid {theme["border"]};
                border-radius: {theme["border_radius"]}px;
                background-color: {theme["background"]};
                padding-top: 10px;
                top: -2px;
            }}
            QTabBar::tab {{
                background-color: {theme["elements"]};
                color: {theme["main_text"]};
                border: 2px solid {theme["border"]};
                border-bottom: none;
                padding: 8px 16px;
                margin: 0 4px 6px 4px;
                border-top-left-radius: {theme["button_radius"]}px;
                border-top-right-radius: {theme["button_radius"]}px;
            }}
            QTabBar::tab:selected {{
                background-color: {theme["hover"]};
                margin-bottom: 2px;
            }}
            QTextBrowser {{
                background-color: {theme["elements"]};
                color: {theme["main_text"]};
                border: none;
                padding: 14px;
                selection-background-color: {theme["hover"]};
            }}
            """
        )
        self._title_label.setObjectName("readmeTitle")
        for index in range(self._tabs.count()):
            tab = self._tabs.widget(index)
            if isinstance(tab, _ReadmeTab):
                tab.viewer.document().setDefaultStyleSheet(markdown_css)

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("dialogs.readme_viewer_title", mod_name=self._mod_name))
        self._title_label.setText(
            tr("dialogs.readme_viewer_title", mod_name=self._mod_name)
        )
        self._empty_label.setText(tr("dialogs.no_readme_files"))
        self._close_button.setText(tr("ui.close_button"))

    def closeEvent(self, event) -> None:
        for index in range(self._tabs.count()):
            tab = self._tabs.widget(index)
            if isinstance(tab, _ReadmeTab):
                tab.unload_content()
        super().closeEvent(event)
