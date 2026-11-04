"""Dialogs that pick which saved mod versions are exported or installed."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from services.localization_service import tr
from ui.common.dialog_theme import (
    DynamicDialog,
    build_dialog_theme_stylesheet,
    get_dialog_theme_values,
)
from ui.common.styling import get_ui_scale_factor
from ui.utils.gui_thread import GuiThreadCall, dialog_parent
from ui.utils.ui_utils import format_size
from utils.date_format import format_timestamp
from utils.mod.version_package import (
    ASK,
    VERSION_MODES,
    VersionSelection,
    preset_export,
    preset_install,
)

EXPORT_MODE_KEY = "mod_versions_export_mode"
IMPORT_MODE_KEY = "mod_versions_import_mode"


def _version_info(version: dict) -> str:
    parts = []
    if version.get("size"):
        parts.append(format_size(version["size"]))
    if version.get("mtime"):
        parts.append(format_timestamp(version["mtime"]))
    return " · ".join(parts)


class _VersionRow(QFrame):
    """One selectable version: a checkbox with its details and, optionally, an Active radio."""

    toggled = pyqtSignal()

    def __init__(self, key: str | None, title: str, info: str, tag_key: str = "", with_radio: bool = False, selectable: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self._info = info
        self._tag_key = tag_key
        self.setObjectName("version_choice_row")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        self.check = QCheckBox(self)
        self.check.setChecked(True)
        self.check.toggled.connect(lambda _checked: self.toggled.emit())
        self.check.setVisible(selectable)
        layout.addWidget(self.check, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = QLabel(title, self)
        self.title.setObjectName("version_choice_name")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.details = QLabel(self)
        self.details.setObjectName("version_choice_info")
        self.details.setWordWrap(True)
        self.details.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text.addWidget(self.title)
        text.addWidget(self.details)
        layout.addLayout(text, 1)
        self.radio: QRadioButton | None = None
        if with_radio:
            self.radio = QRadioButton(self)
            self.radio.toggled.connect(lambda _checked: self.toggled.emit())
            layout.addWidget(self.radio, 0, Qt.AlignmentFlag.AlignVCenter)
        self.relocalize_ui()

    def relocalize_ui(self) -> None:
        self.details.setText(" · ".join(part for part in (tr(self._tag_key) if self._tag_key else "", self._info) if part))
        self.details.setVisible(bool(self.details.text()))
        if self.radio:
            self.radio.setText(tr("mod_versions.choice_active"))

    def mousePressEvent(self, a0) -> None:
        if self.check.isVisibleTo(self) and self.check.isEnabled():
            self.check.toggle()
        super().mousePressEvent(a0)


class _VersionChoiceDialog(DynamicDialog):
    """Shared frame: title, intro, optional switch, scrolling version list and two buttons."""

    def __init__(self, title_key: str, accept_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app_state = self.theme_state()
        self.rows: list[_VersionRow] = []
        self.set_localized_title(title_key)
        self.setModal(True)
        scale = get_ui_scale_factor(getattr(self._app_state, "local_config", None))
        self.setMinimumSize(round(460 * scale), round(360 * scale))
        self.resize(round(540 * scale), round(480 * scale))
        self._main = QVBoxLayout(self)
        self._main.setContentsMargins(16, 16, 16, 16)
        self._main.setSpacing(10)
        self.title_label = self.localize_text(QLabel(self), title_key)
        self.title_label.setObjectName("version_choice_title")
        self._main.addWidget(self.title_label)
        self.intro = QLabel(self)
        self.intro.setWordWrap(True)
        self.intro.setObjectName("version_choice_intro")
        self._main.addWidget(self.intro)
        self._extras = QVBoxLayout()
        self._extras.setSpacing(8)
        self._main.addLayout(self._extras)
        self.list_scroll = QScrollArea(self)
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName("version_choice_holder")
        self.list_layout = QVBoxLayout(holder)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch()
        self.list_scroll.setWidget(holder)
        self._main.addWidget(self.list_scroll, 1)
        self.note = QLabel(self)
        self.note.setObjectName("version_choice_note")
        self.note.setWordWrap(True)
        self._main.addWidget(self.note)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = self.localize_text(QPushButton(self), "dialogs.cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.accept_button = self.localize_text(QPushButton(self), accept_key)
        self.accept_button.setDefault(True)
        self.accept_button.clicked.connect(self.accept)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.accept_button)
        self._main.addLayout(buttons)
        self.refresh_theme()

    def add_row(self, row: _VersionRow) -> _VersionRow:
        self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        self.rows.append(row)
        return row

    def refresh_theme(self) -> None:
        theme = get_dialog_theme_values(self.theme_state())
        indicator = theme["checkbox_indicator_radius"]
        self.set_theme_stylesheet(
            build_dialog_theme_stylesheet(self.theme_state())
            + f"""
            QLabel#version_choice_title {{ font-size: 17px; font-weight: bold; }}
            QLabel#version_choice_intro, QLabel#version_choice_note {{ color: {theme["secondary_text"]}; font-size: 12px; }}
            QLabel#version_choice_name {{ font-size: 13px; font-weight: bold; }}
            QLabel#version_choice_info {{ color: {theme["secondary_text"]}; font-size: 11px; }}
            QWidget#version_choice_holder {{ background: transparent; }}
            QFrame#version_choice_row {{
                background-color: {theme["elements"]};
                border: 2px solid {theme["border"]};
                border-radius: {theme["button_radius"]}px;
            }}
            QFrame#version_choice_row:disabled {{ background-color: {theme["background"]}; }}
            QRadioButton {{ color: {theme["main_text"]}; spacing: 6px; }}
            QRadioButton:disabled {{ color: #8f8f8f; }}
            QRadioButton::indicator {{
                width: 18px; height: 18px;
                background-color: {theme["elements"]};
                border: 2px solid {theme["border"]};
                border-radius: 11px;
            }}
            QRadioButton::indicator:checked {{ background-color: {theme["select"]}; }}
            QRadioButton::indicator:disabled {{ background-color: #6f6f6f; border-color: #6f6f6f; }}
            QCheckBox::indicator {{ border-radius: {indicator}px; }}
            QCheckBox::indicator:disabled:checked {{ background-color: #9a9a9a; }}
            QScrollArea {{ background: transparent; }}
            """
        )

    def relocalize_ui(self) -> None:
        super().relocalize_ui()
        for row in self.rows:
            row.relocalize_ui()
        self.update_texts()

    def update_texts(self) -> None:
        """Refresh texts that depend on the current state and language."""


class ExportVersionsDialog(_VersionChoiceDialog):
    """Asks which saved versions go into an exported mod; only the active one by default."""

    def __init__(self, mod_name: str, active_label: str, versions: list[dict], parent: QWidget | None = None) -> None:
        super().__init__("mod_versions.choice_export_title", "actions.export", parent)
        self._mod_name = mod_name
        self._active_label = active_label
        self.only_active = self.localize_text(QCheckBox(self), "mod_versions.choice_export_active_only")
        self.only_active.setToolTip(tr("mod_versions.choice_export_active_only_tip"))
        self.only_active.setChecked(True)
        self.only_active.toggled.connect(self._update_state)
        self._extras.addWidget(self.only_active)
        self.active_row = self.add_row(
            _VersionRow(None, active_label or tr("mod_versions.choice_main_version"), "", "mod_versions.choice_active", selectable=False, parent=self)
        )
        for version in versions:
            self.add_row(_VersionRow(version["name"], version["name"], _version_info(version), parent=self))
        for row in self.rows[1:]:
            row.toggled.connect(self._update_state)
        self._update_state()
        self.update_texts()

    def update_texts(self) -> None:
        self.intro.setText(tr("mod_versions.choice_export_intro", name=self._mod_name))
        self.active_row.title.setText(self._active_label or tr("mod_versions.choice_main_version"))
        self.only_active.setToolTip(tr("mod_versions.choice_export_active_only_tip"))
        self.note.setText(tr("mod_versions.choice_export_note"))

    def _update_state(self) -> None:
        for row in self.rows[1:]:
            row.setEnabled(not self.only_active.isChecked())

    def selected_versions(self) -> frozenset[str]:
        if self.only_active.isChecked():
            return frozenset()
        return frozenset(row.key for row in self.rows[1:] if row.key and row.check.isChecked())


class InstallVersionsDialog(_VersionChoiceDialog):
    """Asks which versions of a downloaded mod to install and which one is active."""

    def __init__(self, mod_name: str, root_label: str, versions: list[dict], parent: QWidget | None = None) -> None:
        super().__init__("mod_versions.choice_install_title", "mod_versions.choice_install_button", parent)
        self._mod_name = mod_name
        self._group = QButtonGroup(self)
        self.add_row(_VersionRow(None, root_label or tr("mod_versions.choice_main_version"), "", "mod_versions.choice_default", True, parent=self))
        for version in versions:
            self.add_row(_VersionRow(version["name"], version["name"], _version_info(version), "", True, parent=self))
        for row in self.rows:
            if row.radio:
                self._group.addButton(row.radio)
            row.toggled.connect(self._update_state)
        if default_radio := self.rows[0].radio:
            default_radio.setChecked(True)
        self._update_state()
        self.update_texts()

    def update_texts(self) -> None:
        self.intro.setText(tr("mod_versions.choice_install_intro", name=self._mod_name))
        self.note.setText("" if self.accept_button.isEnabled() else tr("mod_versions.choice_none_selected"))
        self.note.setVisible(not self.accept_button.isEnabled())

    def _update_state(self) -> None:
        for row in self.rows:
            if row.radio:
                row.radio.setEnabled(row.check.isChecked())
        active = next((row for row in self.rows if row.radio and row.radio.isChecked()), None)
        if active is None or not active.check.isChecked():
            fallback = next((row for row in self.rows if row.check.isChecked()), None)
            if fallback and fallback.radio:
                fallback.radio.setChecked(True)
        self.accept_button.setEnabled(any(row.check.isChecked() for row in self.rows))
        self.update_texts()

    def selection(self) -> VersionSelection:
        active = next((row for row in self.rows if row.radio and row.radio.isChecked()), self.rows[0])
        return VersionSelection(
            versions=frozenset(row.key for row in self.rows if row.key and row.check.isChecked()),
            keep_root=self.rows[0].check.isChecked(),
            active=active.key,
        )


def _configured_mode(owner: QObject | None, key: str) -> str:
    """Read the "what to do with saved versions" setting from the app state nearest to ``owner``."""
    while owner is not None:
        if (state := getattr(owner, "app_state", None)) is not None:
            mode = getattr(state, "local_config", {}).get(key, ASK)
            return mode if mode in VERSION_MODES else ASK
        owner = owner.parent()
    return ASK


def choose_export_versions(owner: QObject | None, mod_name: str, active_label: str, versions: list[dict]) -> frozenset[str] | None:
    """Pick the saved versions to export, asking unless the settings decide; ``None`` on cancel."""
    if (mode := _configured_mode(owner, EXPORT_MODE_KEY)) != ASK:
        return preset_export(mode, versions)
    dialog = ExportVersionsDialog(mod_name, active_label, versions, dialog_parent(owner))
    return dialog.selected_versions() if dialog.exec() else None


def choose_install_versions(owner: QObject | None, mod_name: str, root_label: str, versions: list[dict]) -> VersionSelection | None:
    """Pick the versions to install, asking unless the settings decide; ``None`` on cancel."""
    if (mode := _configured_mode(owner, IMPORT_MODE_KEY)) != ASK:
        return preset_install(mode, versions)
    dialog = InstallVersionsDialog(mod_name, root_label, versions, dialog_parent(owner))
    return dialog.selection() if dialog.exec() else None


class WorkerVersionChoice(GuiThreadCall):
    """Lets a worker thread ask for an install choice; create it on the GUI thread."""

    def ask(self, mod_name: str, root_label: str, versions: list[dict], is_cancelled: Callable[[], bool] = lambda: False) -> VersionSelection | None:
        """Block the calling worker until the user answers; ``None`` means they cancelled."""
        return self.call(
            lambda: choose_install_versions(self._owner, mod_name, root_label, versions),
            is_cancelled,
            headless=VersionSelection(frozenset(version["name"] for version in versions)),
        )
