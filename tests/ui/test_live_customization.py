"""Open controls keep their state when language, theme or scale changes."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import sip
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPalette, QPixmap, QTextCursor
from PyQt6.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models.plugin_models import CatalogPluginEntry
from services.diagnostics.preflight_service import PreflightReport
from services.localization_service import localization_service, tr
from services.mod_diagnostics_service import (
    DiagnosticsReport,
    DiagnosticsSummary,
    FileImpact,
)
from services.warning_service import create_warning_event, get_warning_definition
from ui.common.dialog_theme import (
    DynamicDialog,
    DynamicMessageBox,
    apply_dialog_theme,
    scale_stylesheet,
)
from ui.common.feedback import FeedbackManager
from ui.common.live_updates import refresh_live_widgets
from ui.common.localized_label import LocalizedMessage
from ui.dialogs.mod.readme_dialog import ReadmeFileViewer
from ui.dialogs.mod.updates_dialog import ModUpdatesDialog
from ui.dialogs.mod_diagnostics_dialog import ModDiagnosticsDialog
from ui.dialogs.modding_tools_dialog import (
    _BatchDataConvertWorkerThread,
    _DataConvertTab,
    _emit_localized_progress,
)
from ui.dialogs.plugin_details_dialog import PluginDetailsDialog
from ui.dialogs.profile_manager_dialog import ProfileManagerDialog


@pytest.fixture
def language():
    original = localization_service.get_current_language()
    assert localization_service.load_language("en")
    yield
    localization_service.load_language(original)


@pytest.mark.parametrize("parent_has_state", [True, False])
def test_live_dispatch_refreshes_unregistered_dialog_and_prunes_deleted_controls(qtbot, language, parent_has_state):
    parent = QWidget()
    state = SimpleNamespace(local_config={})
    if parent_has_state:
        vars(parent)["app_state"] = state
    qtbot.addWidget(parent)
    dialog = DynamicDialog(parent)
    qtbot.addWidget(dialog)
    layout = QVBoxLayout(dialog)
    button = dialog.localize_text(QPushButton(), "common.close")
    layout.addWidget(button)
    edit = QLineEdit("unsaved input")
    layout.addWidget(edit)
    dialog.set_localized_title("dialogs.manual_install_title")
    obsolete = dialog.localize_text(QLabel(), "ui.file")
    sip.delete(obsolete)
    apply_dialog_theme(dialog, state)
    original_style = dialog.styleSheet()
    assert localization_service.load_language("ru")
    state.local_config.update(ui_scale=1.5, custom_border_color="#123456")
    refresh_live_widgets(parent, "relocalize_ui")
    refresh_live_widgets(parent, "apply_theme")
    refresh_live_widgets(parent, "rescale_ui")
    assert button.text() == tr("common.close")
    assert dialog.windowTitle() == tr("dialogs.manual_install_title")
    assert edit.text() == "unsaved input"
    assert dialog.styleSheet() != original_style
    assert "padding: 12px;" in dialog.styleSheet()
    assert len(dialog._text_bindings) == 1
    once = dialog.styleSheet()
    refresh_live_widgets(parent, "rescale_ui")
    assert dialog.styleSheet() == once


def test_scaling_preserves_urls_and_quoted_text():
    state = SimpleNamespace(local_config={"ui_scale": 1.5})
    assert scale_stylesheet('QLabel { padding: 8px; image: url(C:/16px/icon.png); font-family: "12px"; }', state) == 'QLabel { padding: 12px; image: url(C:/16px/icon.png); font-family: "12px"; }'


def test_message_box_retranslates_title_body_and_actions(qtbot, language):
    dialog = DynamicMessageBox()
    qtbot.addWidget(dialog)
    dialog.set_localized_title("dialogs.manual_install_title")
    dialog.localize(dialog.setText, "ui.manual_install_patch_warning")
    save = dialog.add_localized_button("ui.manual_install_save", dialog.ButtonRole.AcceptRole)
    cancel = dialog.add_localized_button("dialogs.cancel", dialog.ButtonRole.RejectRole)
    assert localization_service.load_language("ru")
    dialog.relocalize_ui()
    # QMessageBox ignores window titles on macOS, following platform conventions.
    expected_title = "" if sys.platform == "darwin" else tr("dialogs.manual_install_title")
    assert dialog.windowTitle() == expected_title
    assert dialog.text() == tr("ui.manual_install_patch_warning")
    assert save.text() == tr("ui.manual_install_save")
    assert cancel.text() == tr("dialogs.cancel")


def test_mod_update_customization_preserves_busy_progress_and_checks(qtbot, language):
    state = SimpleNamespace(local_config={})
    dialog = ModUpdatesDialog(state, ["Default"], "Default")
    qtbot.addWidget(dialog)
    candidates = [{"id": "first", "name": "First", "game": "deltarune", "version": "1", "resolved": {"metadata": {"version": "2"}}}, {"id": "second", "name": "Second", "game": "deltarune", "version": "1", "resolved": {"metadata": {"version": "2"}}}]
    dialog.set_candidates(candidates)
    game = dialog._tree.topLevelItem(0)
    assert game is not None
    first, second = game.child(0), game.child(1)
    assert isinstance(first, QTreeWidgetItem) and isinstance(second, QTreeWidgetItem)
    first.setCheckState(0, Qt.CheckState.Unchecked)
    dialog._tree.setCurrentItem(second)
    game.setExpanded(False)
    dialog.set_busy(True)
    dialog.set_progress(1, 2, "Second")
    assert localization_service.load_language("ru")
    state.local_config["ui_scale"] = 1.5
    dialog.relocalize_ui()
    dialog.apply_theme()
    dialog.rescale_ui()
    assert dialog._tree.topLevelItem(0) is game
    assert first.checkState(0) == Qt.CheckState.Unchecked
    assert second.checkState(0) == Qt.CheckState.Checked
    assert dialog._tree.currentItem() is second
    assert not game.isExpanded()
    assert not dialog._update_button.isEnabled()
    assert dialog._progress.value() == dialog._progress.maximum() // 2
    assert dialog._status.text() == tr("mod_updates.progress", current=1, total=2, name="Second")


def test_readme_customization_uses_cached_content_and_preserves_selection(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "README.md"
    path.write_text("# Heading\n\n[First **bold**](https://example.com/first) [Second](https://example.com/second)\n\nBody", encoding="utf-8")
    viewer = ReadmeFileViewer(str(path))
    qtbot.addWidget(viewer)
    viewer.load_content()
    assert viewer.viewer is not None
    cursor = viewer.viewer.textCursor()
    cursor.setPosition(1)
    cursor.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
    viewer.viewer.setTextCursor(cursor)
    monkeypatch.setattr("ui.dialogs.mod.readme_dialog.read_mod_readme", lambda _path: pytest.fail("Customization reread the file"))
    viewer.apply_theme()
    viewer.rescale_ui()
    assert viewer.viewer.textCursor().anchor() == 1
    assert viewer.viewer.textCursor().position() == 5
    assert "Heading" in viewer.viewer.toPlainText()
    document = viewer.viewer.document()
    assert document is not None
    hrefs = set()
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            fmt = fragment.charFormat()
            if fmt.isAnchor():
                hrefs.add(fmt.anchorHref())
                assert fmt.foreground().color() == viewer.viewer.palette().color(QPalette.ColorRole.Text)
                assert fmt.fontUnderline()
            iterator += 1
        block = block.next()
    assert hrefs == {"https://example.com/first", "https://example.com/second"}


def test_profile_manager_customization_preserves_selected_profile_and_scales_rows(qtbot, language):
    service = Mock(active_name="Default")
    service.list_profiles.return_value = ["Default", "Other"]
    service.get_profile_summary.side_effect = lambda name: {"name": name, "game": "undertale", "game_display_name": "UNDERTALE", "game_mod_count": 3, "total_mod_count": 7, "chapter_mode": False, "direct_launch": ""}
    state = SimpleNamespace(local_config={})
    dialog = ProfileManagerDialog(service, state)
    qtbot.addWidget(dialog)
    dialog.list_widget.setCurrentRow(1)
    assert localization_service.load_language("ru")
    state.local_config["ui_scale"] = 1.5
    dialog.relocalize_ui()
    dialog.apply_theme()
    dialog.rescale_ui()
    dialog.show()
    qtbot.waitUntil(lambda: dialog.add_btn.width() >= 57)
    assert dialog._selected_name() == "Other"
    item = dialog.list_widget.currentItem()
    assert item is not None
    assert item.sizeHint().height() == 126
    assert dialog.add_btn.width() >= 57
    assert dialog.add_btn.iconSize().width() == 30


def test_conversion_progress_and_completed_status_retranslate_nested_messages(qtbot, monkeypatch, language):
    monkeypatch.setattr(_DataConvertTab, "_populate_profiles", lambda _self: None)
    monkeypatch.setattr(_DataConvertTab, "_scan_mods", lambda *_args: None)
    tab = _DataConvertTab(None, SimpleNamespace(local_config={}))
    qtbot.addWidget(tab)
    worker = _BatchDataConvertWorkerThread(None, [], "g3mpatch")
    tab._worker = worker
    worker.progress.connect(tab._show_progress)
    worker.result_ready.connect(tab._on_finished)
    _emit_localized_progress(worker, "modding_tools.convert_batch_item_progress", mod="Example", message=LocalizedMessage("modding_tools.convert_saving_version", {"version": "1.0"}))
    assert localization_service.load_language("ru")
    tab._status_label.relocalize_ui()
    assert tab._status_label.text() == tr("modding_tools.convert_batch_item_progress", mod="Example", message=tr("modding_tools.convert_saving_version", version="1.0"))
    worker.run()
    assert tab._worker is None
    assert localization_service.load_language("en")
    tab._status_label.relocalize_ui()
    assert tab._status_label.text() == tr("modding_tools.convert_batch_success", count=0, total=0)


@pytest.mark.parametrize("quick_conflicts", [None, 2, 10])
def test_diagnostics_translation_preserves_tab_and_preflight_conflicts(qtbot, app_state, monkeypatch, tmp_path, language, quick_conflicts):
    monkeypatch.setattr(ModDiagnosticsDialog, "_load_initial_mods", lambda _self: None)
    monkeypatch.setattr(ModDiagnosticsDialog, "_run_analysis", lambda _self: None)
    dialog = ModDiagnosticsDialog(app_state, Mock(), Mock())
    qtbot.addWidget(dialog)
    source = tmp_path / "new.txt"
    source.write_text("preview content", encoding="utf-8")
    impact = FileImpact("game", "mod", "Mod", str(source), "game_path", "file.txt", str(tmp_path / "file.txt"), "add", False)
    if quick_conflicts is not None:
        dialog._on_report_ready(DiagnosticsReport(DiagnosticsSummary(conflicts=quick_conflicts), (impact,), (), ()))
    else:
        item = QTreeWidgetItem(["file.txt"])
        item.setData(0, Qt.ItemDataRole.UserRole, impact)
        dialog._file_tree.addTopLevelItem(item)
    dialog._on_preflight_ready(PreflightReport(True, False, 0.1, conflict_count=7))
    item = dialog._file_tree.topLevelItem(0)
    assert item is not None
    if quick_conflicts is not None:
        item = item.child(0)
        assert item is not None
    dialog._file_tree.setCurrentItem(item)
    dialog._tabs.setCurrentIndex(1)
    assert localization_service.load_language("ru")
    dialog.relocalize_ui()
    assert dialog._tabs.currentIndex() == 1
    assert "preview content" in dialog._preview_compare_panel.toPlainText()
    assert dialog._summary_labels["conflicts"].text() == tr("diagnostics.summary_conflicts", count=max(quick_conflicts or 0, 7))
    dialog._clear_preflight_result()
    assert dialog._summary_labels["conflicts"].text() == tr("diagnostics.summary_conflicts", count=quick_conflicts or 0)


def test_catalog_icon_theme_refresh_uses_loader_instead_of_caching_placeholder(qtbot, app_state, monkeypatch):
    loads = []
    def load_icon(label, entry, *, size, fit):
        loads.append((size, fit))
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor("blue" if len(loads) == 1 else "red"))
        label.setPixmap(pixmap)
    monkeypatch.setattr("ui.dialogs.plugin_details_dialog.load_mod_icon_universal", load_icon)
    entry = CatalogPluginEntry("test", "Test", "Description", "Author", "1.0", "1.0", icon="https://example.com/icon.png")
    dialog = PluginDetailsDialog(None, Mock(), Mock(), app_state, catalog_entry=entry)
    qtbot.addWidget(dialog)
    assert loads == [(96, True)]
    app_state.local_config["ui_scale"] = 1.5
    dialog.apply_theme()
    dialog.rescale_ui()
    assert loads == [(96, True), (144, True), (144, True)]
    pixmap = dialog._icon_label.pixmap()
    assert pixmap is not None
    assert pixmap.width() == 144
    assert pixmap.toImage().pixelColor(0, 0) == QColor("red")


def test_open_warning_retranslates_body_and_preserves_external_details(qapp, language):
    manager = FeedbackManager()
    event = create_warning_event("xdelta_apply_failed")
    definition = get_warning_definition(event.warning_id)
    errors = []
    def interact():
        dialog = None
        try:
            dialog = qapp.activeModalWidget()
            assert isinstance(dialog, DynamicDialog)
            assert localization_service.load_language("ru")
            dialog.relocalize_ui()
            assert dialog.windowTitle() == tr(definition.title_key)
            scroll = dialog.findChild(QScrollArea)
            assert scroll is not None
            label = scroll.widget()
            assert isinstance(label, QLabel)
            assert label.text() == manager._format_html(tr(definition.body_key)) + "<br><br>&lt;details&gt;"
            button = next(button for button in dialog.findChildren(QPushButton) if button.text() == tr("dialogs.patching_warning.continue_button"))
            button.click()
        except BaseException as error:
            errors.append(error)
            if isinstance(dialog, DynamicDialog):
                dialog.reject()
            elif dialog is not None:
                dialog.close()
    QTimer.singleShot(0, interact)
    accepted = manager.ask_patching_warning(event, details="<details>")
    assert not errors, errors
    assert accepted
