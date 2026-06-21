"""UI tests for test dialogs."""

import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    from typing import override
except ImportError:
    from typing import override

from PyQt6.QtCore import QMimeData, Qt, QUrl
from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton, QWidget

EXPECTED_DIALOG_WIDTH = 1145


def _close_dialog(qapp, dialog) -> None:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


class TestImportDialog:
    """Tests for dialogs."""
    def test_import_dialog_creation(self, qapp, feedback_service):
        """Checks that importing dialog creation."""
        from services.localization_service import tr
        from ui.dialogs.import_dialog import ImportDialog
        dialog = ImportDialog(None, feedback_service, 'mods')
        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert dialog.windowTitle() == tr("mods.import_mods")

    def test_import_dialog_localizations_never_show_raw_keys(self, qapp, feedback_service):
        """Checks that import dialogs resolve visible localization keys for every shipped language."""
        from services.localization_service import localization_service
        from ui.dialogs.import_dialog import ImportDialog

        original_language = localization_service.get_current_language()
        import_types = ("mods", "themes", "game_versions", "mod_versions")

        try:
            for language_code in localization_service.get_available_languages():
                assert localization_service.load_language(language_code)
                for import_type in import_types:
                    dialog = ImportDialog(None, feedback_service, import_type)
                    labels = [label.text() for label in dialog.findChildren(QLabel)]
                    buttons = [button.text() for button in dialog.findChildren(QPushButton)]
                    visible_texts = [dialog.windowTitle(), dialog.url_input.placeholderText(), *labels, *buttons]

                    assert all(text and not text.startswith("[") for text in visible_texts)
                    _close_dialog(qapp, dialog)
        finally:
            localization_service.load_language(original_language)

    def test_empty_url_feedback_failure_keeps_dialog_open(self, qapp):
        """Checks empty URL warning failure does not accept or crash import dialog."""
        from ui.dialogs.import_dialog import ImportDialog

        feedback_service = Mock()
        feedback_service.show_message.side_effect = RuntimeError("toast deleted")
        dialog = ImportDialog(None, feedback_service, "mods")

        dialog._import_from_url()

        assert dialog.selected_url is None
        assert dialog.import_method is None
        feedback_service.show_message.assert_called_once()
        _close_dialog(qapp, dialog)


class TestGameBananaFilePickerDialog:
    """Tests for dialogs."""
    def test_file_picker_dialog_creation(self, qapp):
        """Checks that file picker dialog creation."""
        from ui.dialogs.file_picker_dialog import GameBananaFilePickerDialog
        dialog = GameBananaFilePickerDialog(None, [], 'Test Mod')
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestCreateModpackDialog:
    """Tests for dialogs."""
    def test_create_modpack_dialog_creation(self, qapp, app_state):
        """Checks that creating modpack dialog creation."""
        from ui.dialogs.mod.pack_create_dialog import CreateModpackDialog
        dialog = CreateModpackDialog(app_state, None)
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestConflictsDialog:
    """Tests for dialogs."""
    def test_conflicts_dialog_creation(self, qapp, temp_dir):
        """Checks that conflictsing dialog creation."""
        import os

        from ui.dialogs.conflicts_dialog import ConflictsDialog
        report_path = os.path.join(temp_dir, 'test_report.md')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('## Merge Report\n\nTotal conflicts: 2\nAuto-resolved: 1\n')
        dialog = ConflictsDialog(report_path, None)
        assert dialog is not None
        assert isinstance(dialog, QDialog)

    def test_conflicts_dialog_missing_report_uses_localized_message(
        self, qapp, temp_dir, monkeypatch
    ):
        from services.localization_service import tr
        from ui.dialogs.conflicts_dialog import ConflictsDialog

        report_path = os.path.join(temp_dir, "missing_report.md")
        dialog = ConflictsDialog(report_path, None)
        calls = []
        monkeypatch.setattr(
            "ui.dialogs.conflicts_dialog.QMessageBox.information",
            lambda *args: calls.append(args),
        )

        dialog._open_report_file()

        assert calls
        assert calls[0][1] == tr("dialogs.conflicts.title")
        assert calls[0][2] == tr("errors.file_not_found", path=report_path)
        _close_dialog(qapp, dialog)

    def test_conflicts_dialog_missing_report_ignores_broken_info_dialog(
        self, qapp, temp_dir, monkeypatch
    ):
        from ui.dialogs.conflicts_dialog import ConflictsDialog

        report_path = os.path.join(temp_dir, "missing_report.md")
        dialog = ConflictsDialog(report_path, None)
        monkeypatch.setattr(
            "ui.dialogs.conflicts_dialog.QMessageBox.information",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog._open_report_file()

        _close_dialog(qapp, dialog)


class TestPluginDetailsDialog:
    def test_plugin_update_button_is_after_delete_and_runs_callback(
        self, qapp, tmp_path
    ):
        from models.plugin_models import InstalledPluginRecord, PluginManifest
        from services.localization_service import tr
        from ui.dialogs.plugin_details_dialog import PluginDetailsDialog

        manifest = PluginManifest(
            config_version=1,
            id="sample_plugin",
            name="Sample",
            description="Sample plugin",
            author="Author",
            version="1.0.0",
            entry="plugin.py",
        )
        plugin = InstalledPluginRecord(manifest=manifest, path=str(tmp_path))
        updated = []
        dialog = PluginDetailsDialog(
            plugin,
            runtime_service=Mock(get_settings_widget=Mock(return_value=None)),
            state_service=Mock(),
            app_state=SimpleNamespace(local_config={}),
            can_update=True,
            on_update=updated.append,
        )

        button_texts = [button.text() for button in dialog.findChildren(QPushButton)]
        delete_index = button_texts.index(tr("plugins.details_delete"))
        update_index = button_texts.index(tr("plugins.details_update"))
        assert update_index == delete_index + 1

        dialog.findChildren(QPushButton)[update_index].click()

        assert updated == ["sample_plugin"]
        _close_dialog(qapp, dialog)

    def test_plugin_delete_confirmation_failure_is_ignored(
        self, qapp, tmp_path, monkeypatch
    ):
        from PyQt6.QtWidgets import QMessageBox

        from models.plugin_models import InstalledPluginRecord, PluginManifest
        from ui.dialogs.plugin_details_dialog import PluginDetailsDialog

        manifest = PluginManifest(
            config_version=1,
            id="sample_plugin",
            name="Sample",
            description="Sample plugin",
            author="Author",
            version="1.0.0",
            entry="plugin.py",
        )
        plugin = InstalledPluginRecord(manifest=manifest, path=str(tmp_path))
        dialog = PluginDetailsDialog(
            plugin,
            runtime_service=Mock(get_settings_widget=Mock(return_value=None)),
            state_service=Mock(),
            app_state=SimpleNamespace(local_config={}),
        )
        monkeypatch.setattr(
            QMessageBox,
            "question",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog._confirm_delete_plugin()

        assert dialog.delete_requested is False
        assert dialog.result() == QDialog.DialogCode.Rejected
        _close_dialog(qapp, dialog)


class TestModPriorityDialog:
    """Tests for dialogs."""
    def test_mod_priority_dialog_creation(self, qapp, app_state):
        """Checks that mod priority dialog creation."""
        from models.mod_models import ModInfo
        from ui.dialogs.mod.priority_dialog import ModPriorityDialog
        mods_list = [ModInfo(id='test_mod_1', name='Test Mod 1', version='1.0.0', author='Author', description='', game_version='', description_url='', downloads=0, game='deltarune')]
        dialog = ModPriorityDialog(mods_list, 1, app_state, None)
        assert dialog is not None
        assert isinstance(dialog, QDialog)


class TestAboutDialog:
    """Tests for dialogs."""
    def test_about_dialog_creation(self, qapp, app_state, temp_dir):
        """Checks that abouting dialog creation."""
        from models.plugin_models import PLUGIN_API_VERSION
        from ui.dialogs.about_dialog import AboutDialog
        dialog = AboutDialog(None, app_state)
        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert dialog.title_label.text() == 'G3M'
        assert dialog.data_path_edit.text() == temp_dir
        assert dialog.plugin_api_value.text() == PLUGIN_API_VERSION
        assert dialog.os_value.text()
        assert dialog.python_value.text()
        _close_dialog(qapp, dialog)

    def test_about_dialog_actions(self, qapp, app_state):
        """Checks that abouting dialog actions."""
        from ui.dialogs.about_dialog import AboutDialog
        dialog = AboutDialog(None, app_state)
        with patch('ui.dialogs.about_dialog.open_url_native') as open_url, patch(
            'ui.dialogs.about_dialog.open_path_native'
        ) as open_path:
            dialog.wiki_button.click()
            dialog.open_folder_button.click()
            open_url.assert_called_once()
            open_path.assert_called_once()
        assert dialog.result() == QDialog.DialogCode.Rejected


class TestChangelogDialog:
    """Tests for dialogs."""
    def test_changelog_dialog_creation_without_source(self, qapp):
        """Checks that changeloging dialog creation without source."""
        from ui.dialogs.changelog_dialog import ChangelogDialog
        dialog = ChangelogDialog(None, '')
        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert hasattr(dialog, 'text_browser')
        assert hasattr(dialog, 'close_button')
        _close_dialog(qapp, dialog)


class TestLogViewerDialog:
    """Tests for dialogs."""

    def test_log_viewer_dialog_creation_and_relocalize(self, qapp, app_state, tmp_path):
        from services.localization_service import tr
        from ui.dialogs.log_viewer_dialog import LogViewerDialog

        logs_dir = tmp_path / "logs"
        patching_dir = logs_dir / "patching"
        patching_dir.mkdir(parents=True)
        (logs_dir / "g3m.log").write_text("g3m line\n", encoding="utf-8")
        (logs_dir / "patching.log").write_text("patching line\n", encoding="utf-8")
        (logs_dir / "conflicts.log").write_text("conflict line\n", encoding="utf-8")

        dialog = LogViewerDialog(app_state, parent=None, user_data_root=str(tmp_path))

        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert dialog._tabs.count() == 3
        assert dialog._tabs.tabText(0) == "G3M"
        assert dialog._tabs.tabText(1) == "Patching"
        assert dialog._tabs.tabText(2) == "Conflicts"
        assert dialog._history_combo.itemText(0) == tr("log_viewer.latest_live")
        assert dialog._open_folder_button.toolTip() == tr("log_viewer.open_folder")
        assert dialog._viewer.toPlainText() == "g3m line\n"

        dialog.relocalize_ui()
        dialog.refresh_theme()

        assert dialog.windowTitle() == tr("log_viewer.title")
        assert dialog._close_button.text() == tr("common.close")
        _close_dialog(qapp, dialog)

    def test_log_viewer_dialog_shows_blank_for_existing_empty_file(
        self, qapp, app_state, tmp_path
    ):
        from ui.dialogs.log_viewer_dialog import LogViewerDialog

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "patching.log").write_text("", encoding="utf-8")

        dialog = LogViewerDialog(app_state, parent=None, user_data_root=str(tmp_path))
        dialog._tabs.setCurrentIndex(1)
        qapp.processEvents()

        assert dialog._viewer.toPlainText() == ""
        _close_dialog(qapp, dialog)


class TestPizzaOvenConversionDialog:
    """Tests for dialogs."""
    def test_dialog_creation(self, qapp):
        """Checks that dialoging creation."""
        from services.localization_service import tr
        from ui.dialogs.pizza_oven_conversion_dialog import PizzaOvenConversionDialog

        dialog = PizzaOvenConversionDialog(None)

        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert dialog.windowTitle() == tr("dialogs.po_convert_title")
        assert dialog.start_button.text() == tr("buttons.start_po_convert")
        assert dialog.cancel_button.text() == tr("dialogs.cancel")
        _close_dialog(qapp, dialog)


class TestGameManagerDialog:
    def test_toggle_visibility_does_not_crash_if_warning_dialog_fails(
        self, qapp, app_state, monkeypatch
    ):
        """Checks that validation errors survive fallback warning dialog failures."""
        from PyQt6.QtWidgets import QMessageBox

        from services.game_registry_service import GameRegistryValidationError
        from ui.dialogs.game.manager_dialog import GameManagerDialog

        registry_service = Mock()
        registry_service.games_changed.connect = Mock()
        registry_service.list_manager_games.return_value = [
            SimpleNamespace(
                id="deltarune",
                display_name="DELTARUNE",
                is_builtin=True,
                is_visible=True,
                steam_app_id=None,
                gamebanana_id=None,
            )
        ]
        registry_service.set_visibility.side_effect = GameRegistryValidationError(
            "games.error_last_visible"
        )

        def fail_warning(*_args, **_kwargs):
            raise RuntimeError("dialog failed")

        monkeypatch.setattr(QMessageBox, "warning", fail_warning)

        dialog = GameManagerDialog(
            registry_service,
            profile_service=Mock(),
            game_versions_manager=Mock(),
            settings_service=Mock(),
            app_state=app_state,
        )
        dialog._on_toggle_visibility("deltarune", False)
        _close_dialog(qapp, dialog)


class TestBlocklistDialog:
    def test_empty_value_does_not_crash_if_warning_dialog_fails(
        self, qapp, monkeypatch
    ):
        """Checks that empty blocklist validation survives warning dialog failures."""
        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.blocklist_dialog import BlocklistDialog

        service = Mock()
        service.get_prefix_types.return_value = [("name", "Name")]
        service.get_blocklist_for_game.return_value = []
        service.get_prefix_type_display_name.return_value = "Name"

        def fail_warning(*_args, **_kwargs):
            raise RuntimeError("dialog failed")

        monkeypatch.setattr(QMessageBox, "warning", fail_warning)

        dialog = BlocklistDialog(
            service,
            current_game="deltarune",
            available_games=[SimpleNamespace(id="deltarune", display_name="DELTARUNE")],
        )
        dialog.value_edit.setText("")
        dialog.add_entry()
        _close_dialog(qapp, dialog)


class TestReadmeUi:
    """Tests for dialogs."""
    def test_mod_readme_dialog_creation(self, qapp, app_state, tmp_path):
        """Checks that mod readme dialog creation."""
        from ui.dialogs.mod.readme_dialog import ModReadmeDialog

        readme_path = tmp_path / "README.md"
        readme_path.write_text("# Guide\n\n[Link](https://example.com)", encoding="utf-8")

        dialog = ModReadmeDialog(app_state, "Test Mod", [str(readme_path)])

        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert dialog._tabs.count() == 1
        assert "QTabWidget::pane" in dialog.styleSheet()
        assert "padding-top: 10px;" in dialog.styleSheet()
        _close_dialog(qapp, dialog)

    def test_mod_readme_markdown_heading_keeps_inline_format_size(
        self, qapp, app_state, tmp_path
    ):
        """Checks that heading inline markup keeps the heading font size."""
        from ui.dialogs.mod.readme_dialog import ModReadmeDialog

        readme_path = tmp_path / "README.md"
        readme_path.write_text(
            "### Start **Bold** _Emphasis_ [Link](https://example.com) Tail",
            encoding="utf-8",
        )

        dialog = ModReadmeDialog(app_state, "Test Mod", [str(readme_path)])
        tab = dialog._tabs.widget(0)
        block = tab.viewer.document().begin()
        sizes = []
        anchors = []
        cursor = QTextCursor(block)
        for _ in range(block.length() - 1):
            cursor.movePosition(
                QTextCursor.MoveOperation.NextCharacter,
                QTextCursor.MoveMode.KeepAnchor,
            )
            text = cursor.selectedText()
            if text.strip():
                fmt = cursor.charFormat()
                sizes.append(round(fmt.font().pointSizeF(), 2))
                anchors.append(fmt.anchorHref())
            cursor.clearSelection()

        assert len(set(sizes)) == 1
        assert any(anchor == "https://example.com" for anchor in anchors)
        _close_dialog(qapp, dialog)

    def test_mod_readme_markdown_accepts_indented_heading_marks(
        self, qapp, app_state, tmp_path
    ):
        """Checks that copied docs with indented heading marks still render headings."""
        from ui.dialogs.mod.readme_dialog import ModReadmeDialog

        readme_path = tmp_path / "README.md"
        readme_path.write_text(
            "  ### Sigma\n\n\t### another sigma\n\n\u00a0### third sigma",
            encoding="utf-8",
        )

        dialog = ModReadmeDialog(app_state, "Test Mod", [str(readme_path)])
        tab = dialog._tabs.widget(0)

        assert tab.viewer.toPlainText() == "Sigma\nanother sigma\nthird sigma"
        _close_dialog(qapp, dialog)

    def test_mod_readme_markdown_accepts_escaped_heading_marks(
        self, qapp, app_state, tmp_path
    ):
        """Checks that editor-escaped heading marks still render headings."""
        from ui.dialogs.mod.readme_dialog import ModReadmeDialog

        readme_path = tmp_path / "README.md"
        readme_path.write_text("\\### Sigma\n\n\\### another sigma", encoding="utf-8")

        dialog = ModReadmeDialog(app_state, "Test Mod", [str(readme_path)])
        tab = dialog._tabs.widget(0)

        assert tab.viewer.toPlainText() == "Sigma\nanother sigma"
        _close_dialog(qapp, dialog)

    def test_mod_readme_markdown_preserves_heading_levels_and_fenced_code(
        self, qapp, app_state, tmp_path
    ):
        """Checks that all heading levels render while fenced code stays literal."""
        from ui.dialogs.mod.readme_dialog import ModReadmeDialog

        readme_path = tmp_path / "README.md"
        readme_path.write_text(
            "\n".join(
                [
                    "# H1",
                    "## H2",
                    "### H3",
                    "#### H4",
                    "##### H5",
                    "###### H6",
                    "```",
                    "\\### not a heading",
                    "```",
                ]
            ),
            encoding="utf-8",
        )

        dialog = ModReadmeDialog(app_state, "Test Mod", [str(readme_path)])
        tab = dialog._tabs.widget(0)
        levels = []
        block = tab.viewer.document().begin()
        while block.isValid():
            level = block.blockFormat().headingLevel()
            if level:
                levels.append(level)
            block = block.next()

        assert levels == [1, 2, 3, 4, 5, 6]
        assert "\\### not a heading" in tab.viewer.toPlainText()
        _close_dialog(qapp, dialog)

    def test_mod_readme_markdown_renders_common_inline_formatting(
        self, qapp, app_state, tmp_path
    ):
        """Checks that common Markdown inline formatting survives rendering."""
        from ui.dialogs.mod.readme_dialog import ModReadmeDialog

        readme_path = tmp_path / "README.md"
        readme_path.write_text(
            "**bold** *italic* _under_ [link](https://example.com) <u>htmlu</u>",
            encoding="utf-8",
        )

        dialog = ModReadmeDialog(app_state, "Test Mod", [str(readme_path)])
        tab = dialog._tabs.widget(0)
        document = tab.viewer.document()

        assert document.find("bold").charFormat().fontWeight() > 400
        assert document.find("italic").charFormat().fontItalic()
        assert document.find("under").charFormat().fontUnderline()
        assert document.find("link").charFormat().anchorHref() == "https://example.com"
        assert document.find("htmlu").charFormat().fontUnderline()
        _close_dialog(qapp, dialog)

    def test_mod_readme_html_renders_as_html(self, qapp, app_state, tmp_path):
        """Checks that HTML INFO files render instead of showing raw tags."""
        from ui.dialogs.mod.readme_dialog import ModReadmeDialog

        readme_path = tmp_path / "README.html"
        readme_path.write_text("<h1>Guide</h1><p>Rendered <b>HTML</b></p>", encoding="utf-8")

        dialog = ModReadmeDialog(app_state, "Test Mod", [str(readme_path)])
        tab = dialog._tabs.widget(0)
        cursor = tab.viewer.document().find("HTML")

        assert tab.viewer.toPlainText() == "Guide\nRendered HTML"
        assert cursor.charFormat().fontWeight() > 400
        _close_dialog(qapp, dialog)

    def test_mod_readme_html_loads_relative_local_image(self, qapp, app_state, tmp_path):
        """Checks that HTML INFO files can render images beside the mod file."""
        from PyQt6.QtGui import QImage

        from ui.dialogs.mod.readme_dialog import ModReadmeDialog

        image_dir = tmp_path / "images"
        image_dir.mkdir()
        image_path = image_dir / "debug.png"
        image = QImage(12, 12, QImage.Format.Format_RGB32)
        image.fill(0x00FF00)
        assert image.save(str(image_path))
        readme_path = tmp_path / "Debug Mode Controls.html"
        readme_path.write_text(
            '<h1>Debug Mode Controls</h1><img src="images/debug.png" width="80">',
            encoding="utf-8",
        )

        dialog = ModReadmeDialog(app_state, "Debug Mode Controls", [str(readme_path)])
        tab = dialog._tabs.widget(0)
        qapp.processEvents()

        resource_url = QUrl.fromLocalFile(str(image_path))
        resource = tab.viewer.document().resource(
            QTextDocument.ResourceType.ImageResource,
            resource_url,
        )
        assert not resource.isNull()
        assert resource.width() == 12
        assert "Debug Mode Controls" in tab.viewer.toPlainText()
        _close_dialog(qapp, dialog)

    def test_mod_readme_html_loads_remote_image_from_local_file(
        self, qapp, app_state, tmp_path
    ):
        """Checks that local HTML INFO files may load remote img sources."""
        from PyQt6.QtGui import QImage
        from PyQt6.QtTest import QTest

        from ui.dialogs.mod.readme_dialog import ModReadmeDialog

        image = QImage(24, 24, QImage.Format.Format_RGB32)
        image.fill(0x0000FF)
        url = "https://example.invalid/remote.png"
        readme_path = tmp_path / "Remote.html"
        readme_path.write_text(f'<h1>Remote</h1><img src="{url}" width="96">', encoding="utf-8")

        with patch("ui.common.rich_html.get_session") as get_session:
            response = Mock()
            image_bytes = bytearray()
            buffer = QImage(image)
            from PyQt6.QtCore import QBuffer, QByteArray, QIODevice

            data = QByteArray()
            qbuffer = QBuffer(data)
            qbuffer.open(QIODevice.OpenModeFlag.WriteOnly)
            assert buffer.save(qbuffer, "PNG")
            image_bytes.extend(bytes(data))
            response.content = bytes(image_bytes)
            response.raise_for_status = Mock()
            get_session.return_value.get.return_value = response
            dialog = ModReadmeDialog(app_state, "Remote", [str(readme_path)])
            tab = dialog._tabs.widget(0)
            for _ in range(20):
                qapp.processEvents()
                QTest.qWait(25)

                resource = tab.viewer.document().resource(
                    QTextDocument.ResourceType.ImageResource,
                    QUrl(url),
                )
                if not resource.isNull() and resource.width() == 24:
                    break
            assert not resource.isNull()
            assert resource.width() == 24
            _close_dialog(qapp, dialog)

    def test_mod_readme_html_rerenders_images_after_resize(
        self, qapp, app_state, tmp_path
    ):
        """Checks that lazy HTML loading does not lock images to fallback width."""
        from PyQt6.QtGui import QImage
        from PyQt6.QtTest import QTest

        from ui.dialogs.mod.readme_dialog import ModReadmeDialog

        image_dir = tmp_path / "images"
        image_dir.mkdir()
        image_path = image_dir / "wide.png"
        image = QImage(640, 120, QImage.Format.Format_RGB32)
        image.fill(0x00FF00)
        assert image.save(str(image_path))
        readme_path = tmp_path / "README.html"
        readme_path.write_text('<img src="images/wide.png" width="620">', encoding="utf-8")

        dialog = ModReadmeDialog(app_state, "Test Mod", [str(readme_path)])
        dialog.resize(900, 640)
        dialog.show()
        for _ in range(5):
            qapp.processEvents()
            QTest.qWait(30)
        tab = dialog._tabs.widget(0)
        html = tab.viewer.toHtml()

        assert str(image_path).replace("\\", "/") in html
        _close_dialog(qapp, dialog)

    def test_mod_readme_html_renders_common_formatting(
        self, qapp, app_state, tmp_path
    ):
        """Checks that common HTML formatting survives rendering."""
        from ui.dialogs.mod.readme_dialog import ModReadmeDialog

        readme_path = tmp_path / "README.html"
        readme_path.write_text(
            "<h1>Title</h1><p><strong>bold</strong> <em>italic</em> "
            "<u>under</u> <a href='https://example.com'>link</a></p>",
            encoding="utf-8",
        )

        dialog = ModReadmeDialog(app_state, "Test Mod", [str(readme_path)])
        tab = dialog._tabs.widget(0)
        document = tab.viewer.document()

        assert document.find("Title").block().blockFormat().headingLevel() == 1
        assert document.find("bold").charFormat().fontWeight() > 400
        assert document.find("italic").charFormat().fontItalic()
        assert document.find("under").charFormat().fontUnderline()
        assert document.find("link").charFormat().anchorHref() == "https://example.com"
        _close_dialog(qapp, dialog)

    def test_mod_readme_html_stays_unstyled_next_to_markdown(
        self, qapp, app_state, tmp_path
    ):
        """Checks that HTML tabs keep their own default styling in mixed readme sets."""
        from ui.dialogs.mod.readme_dialog import ModReadmeDialog

        md_path = tmp_path / "README.md"
        html_path = tmp_path / "README.html"
        md_path.write_text("# Guide", encoding="utf-8")
        html_path.write_text("<p><a href='https://example.com'>Link</a></p>", encoding="utf-8")

        dialog = ModReadmeDialog(app_state, "Test Mod", [str(md_path), str(html_path)])
        dialog._tabs.setCurrentIndex(1)
        qapp.processEvents()
        tab = dialog._tabs.widget(1)

        assert tab.viewer.document().defaultStyleSheet().strip() == ""
        _close_dialog(qapp, dialog)

    def test_mod_readme_pdf_loads_in_pdf_viewer(self, qapp, app_state, tmp_path):
        """Checks that PDF INFO files load through Qt PDF support."""
        from PyQt6.QtPdfWidgets import QPdfView

        from ui.dialogs.mod.readme_dialog import ModReadmeDialog

        readme_path = tmp_path / "README.pdf"
        readme_path.write_bytes(
            b"%PDF-1.1\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
            b"4 0 obj\n<< /Length 44 >>\nstream\n"
            b"BT /F1 12 Tf 72 120 Td (Hello PDF) Tj ET\n"
            b"endstream\nendobj\n"
            b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
            b"xref\n0 6\n0000000000 65535 f \n"
            b"trailer\n<< /Root 1 0 R /Size 6 >>\nstartxref\n405\n%%EOF\n"
        )

        dialog = ModReadmeDialog(app_state, "Test Mod", [str(readme_path)])
        tab = dialog._tabs.widget(0)

        assert isinstance(tab.pdf_viewer, QPdfView)
        assert tab._pdf_document.pageCount() == 1
        _close_dialog(qapp, dialog)

    def test_mod_readme_pdf_error_shows_loading_error(self, qapp, app_state, tmp_path):
        """Checks that unreadable PDF INFO files show an error state."""
        from services.localization_service import tr
        from ui.dialogs.mod.readme_dialog import ModReadmeDialog

        readme_path = tmp_path / "README.pdf"
        readme_path.write_bytes(b"not a pdf")

        dialog = ModReadmeDialog(app_state, "Test Mod", [str(readme_path)])
        tab = dialog._tabs.widget(0)

        assert tab.pdf_viewer.isHidden()
        assert not tab.pdf_error_label.isHidden()
        assert tab.pdf_error_label.text() == tr("status.loading_error")
        _close_dialog(qapp, dialog)

    def test_mod_summary_panel_uses_localized_info_button(self, qapp, app_state):
        """Checks that mod summary panel uses localized info button."""
        from services.localization_service import tr
        from ui.widgets.mod.mod_summary_panel import ModSummaryPanel

        panel = ModSummaryPanel(app_state)

        assert panel._readme_button.text() == tr("dialogs.info")
        panel.update_labels_text()
        assert panel._readme_button.text() == tr("dialogs.info")
        panel.apply_theme()
        assert panel.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        assert panel._scroll.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        assert panel._scroll.viewport().testAttribute(
            Qt.WidgetAttribute.WA_StyledBackground
        )
        panel.deleteLater()

    def test_profile_manager_metadata_uses_new_format(self, qapp, app_state):
        """Checks that profile manager metadata uses new format."""
        from unittest.mock import Mock

        from PyQt6.QtWidgets import QLabel

        from ui.dialogs.profile_manager_dialog import ProfileManagerDialog

        profile_service = Mock()
        profile_service.active_name = "Default"
        profile_service.list_profiles.return_value = ["Default"]
        profile_service.get_profile_summary.return_value = {
            "name": "Default",
            "game": "deltarune",
            "game_display_name": "DELTARUNE",
            "game_mod_count": 3,
            "total_mod_count": 7,
            "chapter_mode": False,
            "direct_launch": "",
        }

        dialog = ProfileManagerDialog(profile_service, app_state)
        item_widget = dialog.list_widget.itemWidget(dialog.list_widget.item(0))
        detail_label = item_widget.findChild(QLabel, "profileDetailLabel")

        assert "3 mods for DELTARUNE" in detail_label.text()
        assert "7 mods in profile" in detail_label.text()
        dialog.close()

    def test_profile_manager_external_drop_imports_multiple_archives(self, qapp, app_state, temp_dir):
        """Checks that profile manager external drop imports multiple archives."""
        import os

        from ui.dialogs.profile_manager_dialog import ProfileManagerDialog

        first = os.path.join(temp_dir, "one.zip")
        second = os.path.join(temp_dir, "two.zip")
        open(first, "wb").close()
        open(second, "wb").close()

        profile_service = Mock()
        profile_service.active_name = "Default"
        profile_service.list_profiles.return_value = ["Default"]
        profile_service.get_profile_summary.return_value = {
            "name": "Default",
            "game": "deltarune",
            "game_display_name": "DELTARUNE",
            "game_mod_count": 1,
            "total_mod_count": 1,
            "chapter_mode": False,
            "direct_launch": "",
        }
        profile_service.import_profile.side_effect = ["ImportedOne", "ImportedTwo"]

        dialog = ProfileManagerDialog(profile_service, app_state)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(first), QUrl.fromLocalFile(second)])

        class _Event:
            def __init__(self) -> None:
                self.accepted = False

            @override
            def mimeData(self):
                return mime

            def source(self):
                return None

            @override
            def acceptProposedAction(self):
                self.accepted = True

        event = _Event()
        with patch("ui.dialogs.profile_manager_dialog.QMessageBox.information"):
            dialog.list_widget.dropEvent(event)
        assert event.accepted is True
        assert os.path.normpath(profile_service.import_profile.call_args_list[0].args[0]) == os.path.normpath(first)
        assert os.path.normpath(profile_service.import_profile.call_args_list[1].args[0]) == os.path.normpath(second)
        dialog.close()

    def test_profile_manager_import_error_does_not_crash_if_critical_dialog_fails(
        self, qapp, app_state, tmp_path, monkeypatch
    ):
        """Checks that profile import errors survive fallback critical dialog failures."""
        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.profile_manager_dialog import ProfileManagerDialog

        archive = tmp_path / "broken.zip"
        archive.write_bytes(b"not a profile")

        profile_service = Mock()
        profile_service.active_name = "Default"
        profile_service.list_profiles.return_value = ["Default"]
        profile_service.get_profile_summary.return_value = {
            "name": "Default",
            "game": "deltarune",
            "game_display_name": "DELTARUNE",
            "game_mod_count": 1,
            "total_mod_count": 1,
            "chapter_mode": False,
            "direct_launch": "",
        }
        profile_service.import_profile.side_effect = RuntimeError("profile broken")

        def fail_critical(*_args, **_kwargs):
            raise RuntimeError("dialog failed")

        monkeypatch.setattr(QMessageBox, "critical", fail_critical)

        dialog = ProfileManagerDialog(profile_service, app_state)
        dialog.import_profiles_from_paths([str(archive)])
        _close_dialog(qapp, dialog)

    def test_game_versions_dialog_drop_imports_multiple_files_and_urls(self, qapp, app_state, temp_dir):
        """Checks that game versions dialog drop imports multiple files and urls."""
        import os

        from ui.dialogs.game.versions_dialog import GameVersionsDialog

        first = os.path.join(temp_dir, "one.zip")
        second = os.path.join(temp_dir, "two.zip")
        open(first, "wb").close()
        open(second, "wb").close()

        manager = Mock()
        manager.records_for_game.return_value = []
        manager.record_added.connect = Mock()
        manager.record_removed.connect = Mock()
        manager.record_updated.connect = Mock()
        manager.progress_updated.connect = Mock()
        manager.operation_error.connect = Mock()

        dialog = GameVersionsDialog(manager, app_state)
        mime = QMimeData()
        mime.setUrls(
            [
                QUrl.fromLocalFile(first),
                QUrl.fromLocalFile(second),
                QUrl("https://example.com/one.zip"),
                QUrl("https://example.com/two.zip"),
            ]
        )

        class _Event:
            def __init__(self) -> None:
                self.accepted = False

            @override
            def mimeData(self):
                return mime

            def source(self):
                return None

            @override
            def acceptProposedAction(self):
                self.accepted = True

            def ignore(self):
                self.accepted = False

        event = _Event()
        dialog.dropEvent(event)
        game_id = dialog._current_game()
        assert event.accepted is True
        actual_first_path = manager.import_game_version_from_file.call_args_list[0].args[1]
        actual_second_path = manager.import_game_version_from_file.call_args_list[1].args[1]
        assert os.path.normpath(actual_first_path) == os.path.normpath(first)
        assert os.path.normpath(actual_second_path) == os.path.normpath(second)
        assert manager.import_game_version_from_url.call_args_list[0].args == (game_id, "https://example.com/one.zip")
        assert manager.import_game_version_from_url.call_args_list[1].args == (game_id, "https://example.com/two.zip")
        dialog.close()

    def test_game_versions_error_does_not_crash_if_warning_dialog_fails(
        self, qapp, app_state, monkeypatch
    ):
        """Checks that operation errors survive fallback warning dialog failures."""
        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.game.versions_dialog import GameVersionsDialog

        manager = Mock()
        manager.records_for_game.return_value = []
        manager.record_added.connect = Mock()
        manager.record_removed.connect = Mock()
        manager.record_updated.connect = Mock()
        manager.progress_updated.connect = Mock()
        manager.operation_error.connect = Mock()

        def fail_warning(*_args, **_kwargs):
            raise RuntimeError("dialog failed")

        monkeypatch.setattr(QMessageBox, "warning", fail_warning)

        dialog = GameVersionsDialog(manager, app_state)
        dialog._on_error("operation failed")
        dialog.close()

    def test_mod_versions_dialog_drop_queues_multiple_imports(self, qapp, app_state, tmp_path):
        """Checks that mod versions dialog drop queues multiple imports."""
        import os

        from ui.dialogs.mod.versions_dialog import ModVersionsDialog

        mod_folder = tmp_path / "mod"
        mod_folder.mkdir()
        (mod_folder / "mod_config.json").write_text('{"name":"Mod"}', encoding="utf-8")
        first = tmp_path / "one.zip"
        second = tmp_path / "two.zip"
        first.write_bytes(b"1")
        second.write_bytes(b"2")

        dialog = ModVersionsDialog(
            str(mod_folder),
            {"id": "mod", "name": "Mod"},
            app_state,
            parent=None,
        )
        imported_files = []
        imported_urls = []
        dialog._import_from_path = lambda path, version_name=None, prompt_for_name=True: imported_files.append((path, prompt_for_name)) or dialog._process_next_import()
        dialog._start_url_worker = lambda url, version_name=None, prompt_for_name=True: imported_urls.append((url, prompt_for_name)) or dialog._process_next_import()

        mime = QMimeData()
        mime.setUrls(
            [
                QUrl.fromLocalFile(str(first)),
                QUrl.fromLocalFile(str(second)),
                QUrl("https://example.com/modA.zip"),
                QUrl("https://example.com/modB.zip"),
            ]
        )

        class _Event:
            def __init__(self) -> None:
                self.accepted = False

            @override
            def mimeData(self):
                return mime

            def source(self):
                return None

            @override
            def acceptProposedAction(self):
                self.accepted = True

            def ignore(self):
                self.accepted = False

        event = _Event()
        dialog.dropEvent(event)
        assert event.accepted is True
        assert [(os.path.normpath(path), flag) for path, flag in imported_files] == [(os.path.normpath(str(first)), False), (os.path.normpath(str(second)), False)]
        assert imported_urls == [
            ("https://example.com/modA.zip", False),
            ("https://example.com/modB.zip", False),
        ]
        dialog.close()


class TestThemeManagementDialog:
    """Tests for dialogs."""

    def test_theme_import_dialog_uses_real_localized_text(self, qapp):
        """Checks that theme import dialog never shows raw localization keys."""
        from unittest.mock import Mock

        from ui.dialogs.import_dialog import ImportDialog

        dialog = ImportDialog(None, Mock(), "themes", "*.zip")
        visible_text = [dialog.windowTitle(), dialog.url_input.placeholderText()]
        visible_text.extend(
            widget.text()
            for widget in dialog.findChildren((QLabel, QPushButton))
            if widget.text()
        )

        assert visible_text
        assert all("themes." not in text for text in visible_text)
        assert all(not (text.startswith("[") and text.endswith("]")) for text in visible_text)
        dialog.close()

    def test_theme_management_dialog_creation(self, qapp, app_state):
        """Checks that themeing management dialog creation."""
        from unittest.mock import Mock

        from services.customization_service import CustomizationManager
        from services.localization_service import tr
        from ui.dialogs.theme_dialog import ThemeManagementDialog

        class FakeThemeController:
            def __init__(self, state) -> None:
                self.app_state = state
                self.customization_service = CustomizationManager(state)
                self.settings_service = Mock()

        theme_controller = FakeThemeController(app_state)
        dialog = ThemeManagementDialog(None, theme_controller)
        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert dialog.findChildren(QPushButton)[0].toolTip() == tr("tooltips.import_theme")

        settings_text = dialog._build_settings_text()
        assert isinstance(settings_text, str)
        assert 'themes.no_customizations' in settings_text or len(settings_text) > 0
        dialog.close()

    def test_theme_management_dialog_hides_default_border_radius(
        self, qapp, app_state
    ):
        """Checks that themeing management dialog hides default border radius."""
        from unittest.mock import Mock

        from services.customization_service import CustomizationManager
        from ui.dialogs.theme_dialog import ThemeManagementDialog

        class FakeThemeController:
            def __init__(self, state) -> None:
                self.app_state = state
                self.customization_service = CustomizationManager(state)
                self.settings_service = Mock()

        app_state.local_config["custom_border_radius"] = 7
        theme_controller = FakeThemeController(app_state)
        dialog = ThemeManagementDialog(None, theme_controller)

        settings_text = dialog._build_settings_text()

        assert "Border Radius" not in settings_text
        dialog.close()


class TestModdingToolsDialog:
    """Tests for dialogs."""
    def test_dialog_uses_raised_tab_styling(self, qapp, app_state):
        """Checks that dialoging uses raised tab styling."""
        from ui.dialogs.modding_tools_dialog import ModdingToolsDialog

        dialog = ModdingToolsDialog(Mock(), app_state)

        assert dialog._tabs.documentMode() is True
        assert "QTabWidget::pane" in dialog.styleSheet()
        assert "padding-top: 10px;" in dialog.styleSheet()
        dialog.close()


class TestDialogTheme:
    """Tests for dialogs."""
    def test_dialog_theme_uses_hover_color_for_selection(self, app_state):
        """Checks that dialoging theme uses hover color for selection."""
        from ui.common.dialog_theme import build_dialog_theme_stylesheet

        app_state.local_config = {
            'custom_hover_color': '#112233',
            'custom_select_color': '#445566',
        }
        stylesheet = build_dialog_theme_stylesheet(app_state)

        assert 'background-color: #112233;' in stylesheet
        assert 'selection-background-color: #112233;' in stylesheet
        assert '#445566' not in stylesheet


class TestModEditorDialog:
    """Tests for dialogs."""
    def test_mod_editor_default_width_is_thirty_pixels_wider(self, qapp, tmp_path):
        """Checks that mod editor opens with the updated default width."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()

        dialog = ModEditorDialog(parent, is_creating=True)

        assert dialog.width() >= EXPECTED_DIALOG_WIDTH
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_defaults_to_current_library_game(self, qapp, tmp_path):
        """Checks that create mod defaults to the current library game."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(
            local_config={},
            mods_dir=str(tmp_path),
            game_mode=SimpleNamespace(game_id="pizzatower"),
        )
        parent.settings_service = Mock()
        parent.mod_service = Mock()

        dialog = ModEditorDialog(parent, is_creating=True)

        assert dialog.game_combo.currentData() == "pizzatower"
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_populates_metadata_schema_config(self, qapp, tmp_path):
        """Checks that mod editor reads canonical metadata configs."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_folder = tmp_path / "metadata_mod"
        mod_folder.mkdir()
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_folder)))
        response = Mock()
        response.content = b"not an image"
        response.raise_for_status = Mock()
        session = Mock()
        session.get.return_value = response
        with patch("utils.network_utils.get_session", return_value=session):
            dialog = ModEditorDialog(
                parent,
                is_creating=False,
                mod_data={
                    "metadata": {
                        "id": "gb_mod_665180",
                        "name": "Lap Hell",
                        "author": "Unknown",
                        "description": "desc",
                        "version": "1.0.0",
                        "game": "pizzatower",
                        "homepage": "https://gamebanana.com/mods/665180",
                        "icon": "https://images.gamebanana.com/example.jpg",
                    },
                    "files": {"pizzatower": {"data_file_path": "laphell.xdelta"}},
                    "folder_path": str(mod_folder),
                },
            )

        assert dialog.name_edit.text() == "Lap Hell"
        assert dialog.homepage_edit.text() == "https://gamebanana.com/mods/665180"
        assert dialog.icon_edit.text() == "https://images.gamebanana.com/example.jpg"
        _close_dialog(qapp, dialog)
        parent.deleteLater()

    def test_mod_editor_metadata_fields_stay_editable_when_editing(self, qapp, tmp_path):
        """Checks that editing a mod does not lock normal metadata fields."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_folder = tmp_path / "metadata_mod"
        mod_folder.mkdir()
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_folder)))
        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                "id": "local_test_mod",
                "name": "Test Mod",
                "author": "Old Author",
                "description": "desc",
                "version": "1.0.0",
                "game": "deltarune",
                "files": {},
                "folder_path": str(mod_folder),
            },
        )

        editable_fields = [
            dialog.name_edit,
            dialog.author_edit,
            dialog.description_edit,
            dialog.homepage_edit,
            dialog.icon_edit,
            dialog.version_edit,
            dialog.game_version_edit,
        ]
        assert all(not field.isReadOnly() and field.isEnabled() for field in editable_fields)
        dialog.author_edit.setText("New Author")
        assert dialog.author_edit.text() == "New Author"
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_populates_saved_files_as_relative_paths(self, qapp, tmp_path):
        """Checks that mod editor populates saved files as relative paths."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_folder = tmp_path / 'bossrush_mod'
        chapter_folder = mod_folder / 'chapter_4'
        chapter_folder.mkdir(parents=True)
        (chapter_folder / 'BOSSRUSH.win').write_text('data', encoding='utf-8')
        (chapter_folder / 'bonus.zip').write_text('extra', encoding='utf-8')
        (mod_folder / 'icon.png').write_text('icon', encoding='utf-8')
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_folder)))
        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                'id': 'local_manual_bossrush',
                'name': 'BOSSRUSH',
                'author': 'Unknown',
                'description': 'Desc',
                'version': '1.0.0',
                'game': 'deltarune',
                'icon': 'icon.png',
                'files': {
                    'deltarune_4': {
                        'data_file_path': 'BOSSRUSH.win',
                        'extra_files': ['bonus.zip'],
                    }
                },
            },
        )

        collected = dialog._collect_files()

        assert dialog.icon_edit.text() == 'icon.png'
        assert dialog.findChild(QWidget, 'modEditorIntroCard') is None
        assert collected['deltarune_4']['data_file_path'] == 'BOSSRUSH.win'
        assert collected['deltarune_4']['extra_files'] == ['bonus.zip']
        assert dialog._resolve_file_path('BOSSRUSH.win') == str(
            chapter_folder / 'BOSSRUSH.win'
        )
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_hides_add_data_button_per_tab_until_data_frame_removed(
        self, qapp, tmp_path
    ):
        """Checks that mod editor hides add data button per tab until data frame removed."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QPushButton

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        first_tab = dialog.file_tabs.widget(0)
        second_tab = dialog.file_tabs.widget(1)
        first_layout = first_tab._file_layout
        first_button = first_tab._data_button
        second_button = second_tab._data_button

        assert not first_button.isHidden()
        assert not second_button.isHidden()

        dialog._on_add_data(first_tab, first_layout)

        file_cards = [
            first_layout.itemAt(i).widget()
            for i in range(first_layout.count())
            if first_layout.itemAt(i) and first_layout.itemAt(i).widget()
        ]
        data_frame = next(
            (
                widget
                for widget in file_cards
                if widget is not None
                and widget.findChild(QPushButton) is not None
                and any(
                    child.property("file_type") == "data"
                    for child in widget.findChildren(QWidget)
                )
            ),
            None,
        )

        assert data_frame is not None
        assert first_button.isHidden()
        assert not second_button.isHidden()

        dialog._remove_file_frame(first_layout, data_frame, "data")

        assert not first_button.isHidden()
        assert not second_button.isHidden()
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_file_container_has_larger_minimum_height(self, qapp, tmp_path):
        """Checks that mod editor file container has larger minimum height."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        first_tab = dialog.file_tabs.widget(0)
        scroll = first_tab._file_scroll

        assert scroll.minimumHeight() >= 300
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_saves_folder_targets_with_trailing_slash(self, qapp, tmp_path):
        """Checks that mod editor saves folder targets with trailing slash."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        folder_source = tmp_path / "sprites"
        folder_source.mkdir()
        (folder_source / "sprite.png").write_text("img", encoding="utf-8")

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        first_tab = dialog.file_tabs.widget(0)
        layout = first_tab._file_layout
        dialog._create_file_frame(layout, "extra")
        extra_inputs = [
            w
            for w in first_tab.findChildren(type(dialog.icon_edit))
            if w.property("is_local_extra_path")
        ]
        extra_inputs[0].setText(str(folder_source).replace("\\", "/") + "/")

        files = dialog._collect_files()

        first_tab_key = "deltarune_0"
        assert files[first_tab_key]["extra_files"] == [
            str(folder_source).replace("\\", "/") + "/"
        ]
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_extra_path_fields_are_editable(self, qapp, tmp_path):
        """Checks that mod editor extra path fields are editable."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        first_tab = dialog.file_tabs.widget(0)
        layout = first_tab._file_layout
        dialog._create_file_frame(layout, "extra")
        extra_inputs = [
            w
            for w in first_tab.findChildren(type(dialog.icon_edit))
            if w.property("is_local_extra_path")
        ]

        assert extra_inputs
        assert not extra_inputs[0].isReadOnly()
        extra_inputs[0].setText("nested/path/")

        files = dialog._collect_files()

        assert files["deltarune_0"]["extra_files"] == ["nested/path/"]
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_numbers_extra_file_section_titles_by_visual_order(
        self, qapp, tmp_path
    ):
        """Checks that extra file section titles are numbered top-to-bottom and renumber on delete."""
        from types import SimpleNamespace

        from services.localization_service import tr
        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        first_tab = dialog.file_tabs.widget(0)
        layout = first_tab._file_layout
        dialog._create_file_frame(layout, "extra")
        dialog._create_file_frame(layout, "extra")

        extra_title_labels = list(
            dialog._iter_file_title_labels(layout, file_type="extra")
        )

        assert [label.text() for label in extra_title_labels] == [
            tr("files.extra_files_title", number=1),
            tr("files.extra_files_title", number=2),
        ]

        first_frame = extra_title_labels[0].parentWidget()
        dialog._remove_file_frame(layout, first_frame, "extra")
        qapp.processEvents()

        remaining_extra_titles = [
            label.text()
            for label in dialog._iter_file_title_labels(layout, file_type="extra")
        ]
        assert remaining_extra_titles == [tr("files.extra_files_title", number=1)]
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_marks_pizzatower_towers_extra_as_special_runtime_target(
        self, qapp, tmp_path
    ):
        from types import SimpleNamespace

        from services.localization_service import tr
        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)
        for i in range(dialog.game_combo.count()):
            if dialog.game_combo.itemData(i) == "pizzatower":
                dialog.game_combo.setCurrentIndex(i)
                break

        first_tab = dialog.file_tabs.widget(0)
        layout = first_tab._file_layout
        dialog._create_file_frame(layout, "extra")
        extra_input = next(
            w
            for w in first_tab.findChildren(type(dialog.icon_edit))
            if w.property("is_local_extra_path")
        )
        extra_input.setText("towers/")

        frame = extra_input.parentWidget()
        assert frame.property("specialRuntimeTarget") is True
        hint_label = frame.findChild(QLabel, "special_runtime_hint")
        assert hint_label is not None
        assert hint_label.text() == tr(
            "tooltips.mod_editor_special_extra_target_towers",
            target_path="%APPDATA%/PizzaTower_GM2/towers/",
        )
        alignment = hint_label.alignment()
        assert alignment & Qt.AlignmentFlag.AlignLeft
        assert alignment & Qt.AlignmentFlag.AlignVCenter
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_marks_frickbears3_addons_extra_as_special_runtime_target(
        self, qapp, tmp_path
    ):
        from types import SimpleNamespace

        from services.localization_service import tr
        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)
        for i in range(dialog.game_combo.count()):
            if dialog.game_combo.itemData(i) == "frickbears3":
                dialog.game_combo.setCurrentIndex(i)
                break

        first_tab = dialog.file_tabs.widget(0)
        layout = first_tab._file_layout
        dialog._create_file_frame(layout, "extra")
        extra_input = next(
            w
            for w in first_tab.findChildren(type(dialog.icon_edit))
            if w.property("is_local_extra_path")
        )
        extra_input.setText("addons/")

        frame = extra_input.parentWidget()
        assert frame.property("specialRuntimeTarget") is True
        hint_label = frame.findChild(QLabel, "special_runtime_hint")
        assert hint_label is not None
        assert hint_label.text() == tr(
            "tooltips.mod_editor_special_extra_target_addons",
            target_path="%LOCALAPPDATA%/Frickbears3/addons/",
        )
        alignment = hint_label.alignment()
        assert alignment & Qt.AlignmentFlag.AlignLeft
        assert alignment & Qt.AlignmentFlag.AlignVCenter
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_uses_two_pixel_borders_for_file_cards_and_special_targets(
        self, qapp, tmp_path
    ):
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        stylesheet = dialog.styleSheet()

        assert 'QFrame[fileCard="true"] {' in stylesheet
        assert "border: 2px solid" in stylesheet
        assert 'QFrame[fileCard="true"][specialRuntimeTarget="true"] {' in stylesheet
        assert "border: 2px dashed" in stylesheet
        assert "border: 1px solid" not in stylesheet

        dialog.close()
        parent.deleteLater()

    def test_mod_editor_populates_extra_file_paths_in_visible_inputs(self, qapp, tmp_path):
        """Checks that mod editor populates extra file paths in visible inputs."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_folder = tmp_path / "bossrush_mod"
        chapter_folder = mod_folder / "chapter_4"
        chapter_folder.mkdir(parents=True)
        (chapter_folder / "extras").mkdir()
        (chapter_folder / "extras" / "bonus.zip").write_text("extra", encoding="utf-8")
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_folder)))
        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                'id': 'local_manual_bossrush',
                'name': 'BOSSRUSH',
                'author': 'Unknown',
                'description': 'Desc',
                'version': '1.0.0',
                'game': 'deltarune',
                'files': {
                    'deltarune_4': {
                        'extra_files': ['extras/bonus.zip'],
                    }
                },
            },
        )

        extra_inputs = [
            w
            for w in dialog.findChildren(type(dialog.icon_edit))
            if w.property("is_local_extra_path") and w.text()
        ]
        extra_labels = [
            w
            for w in dialog.findChildren(QLabel)
            if w.text().strip() == "bonus.zip"
        ]

        assert any(inp.text() == 'extras/bonus.zip' for inp in extra_inputs)
        assert not extra_labels
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_collects_info_files_in_custom_order(self, qapp, tmp_path):
        """Checks that mod editor saves info file order and visibility."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        doc_a = tmp_path / "A.txt"
        doc_b = tmp_path / "B.txt"
        doc_a.write_text("A", encoding="utf-8")
        doc_b.write_text("B", encoding="utf-8")

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        dialog._add_info_file_entry(str(doc_b), visible=False)
        dialog._add_info_file_entry(str(doc_a), visible=True)

        data = dialog._collect_mod_data()

        assert data["info_files"] == {
            "B.txt": "hide",
            "A.txt": "show",
        }
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_populates_existing_info_files_and_root_docs(self, qapp, tmp_path):
        """Checks that mod editor shows saved info_files and discovered root docs together."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_folder = tmp_path / "info_mod"
        mod_folder.mkdir()
        (mod_folder / "A.txt").write_text("A", encoding="utf-8")
        (mod_folder / "B.txt").write_text("B", encoding="utf-8")

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_folder)))
        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                "id": "local_info_mod",
                "name": "Info Mod",
                "author": "Author",
                "description": "Desc",
                "version": "1.0.0",
                "game": "deltarune",
                "info_files": {"B.txt": "hide"},
                "files": {},
                "folder_path": str(mod_folder),
            },
        )

        listed = [
            (
                dialog._info_files_list.item(i).data(Qt.ItemDataRole.UserRole)["path"],
                dialog._info_files_list.item(i).data(Qt.ItemDataRole.UserRole)["state"],
                dialog._info_files_list.item(i).data(Qt.ItemDataRole.UserRole)["custom"],
            )
            for i in range(dialog._info_files_list.count())
        ]

        assert listed == [
            ("B.txt", "hide", True),
            ("A.txt", "show", False),
        ]
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_marks_missing_info_files_from_config(self, qapp, tmp_path):
        """Checks that missing INFO files stay visible and marked in the editor."""
        from types import SimpleNamespace

        from services.localization_service import tr
        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_folder = tmp_path / "renamed_info_mod"
        mod_folder.mkdir()
        (mod_folder / "README.md").write_text("renamed", encoding="utf-8")

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_folder)))
        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                "id": "local_renamed_info_mod",
                "name": "Renamed Info Mod",
                "author": "Author",
                "description": "Desc",
                "version": "1.0.0",
                "game": "deltarune",
                "info_files": {"0 - README.md": "show"},
                "files": {},
                "folder_path": str(mod_folder),
            },
        )

        listed = [
            (
                dialog._info_files_list.item(i).data(Qt.ItemDataRole.UserRole)["path"],
                dialog._info_files_list.item(i).data(Qt.ItemDataRole.UserRole).get(
                    "missing"
                ),
                dialog._info_files_list.item(i).text(),
            )
            for i in range(dialog._info_files_list.count())
        ]

        assert listed == [
            (
                "0 - README.md",
                True,
                f"0 - README.md [{tr('ui.visible')}] [{tr('ui.missing')}]",
            ),
            ("README.md", False, f"README.md [{tr('ui.visible')}]"),
        ]
        assert dialog._collect_info_files() == {"0 - README.md": "show"}
        dialog._info_files_list.setCurrentRow(0)
        dialog._reset_selected_info_file()
        assert dialog._info_files_list.count() == 2
        assert dialog._collect_info_files() == {"0 - README.md": "show"}
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_delete_missing_info_file_removes_entry_only(
        self, qapp, tmp_path
    ):
        """Checks that deleting a missing INFO file removes only its config entry."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_folder = tmp_path / "missing_info_mod"
        mod_folder.mkdir()

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_folder)))
        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                "id": "local_missing_info_mod",
                "name": "Missing Info Mod",
                "author": "Author",
                "description": "Desc",
                "version": "1.0.0",
                "game": "deltarune",
                "info_files": {"Gone.md": "hide"},
                "files": {},
                "folder_path": str(mod_folder),
            },
        )
        dialog._ask_delete_info_file_action = Mock(return_value="entry")

        dialog._info_files_list.setCurrentRow(0)
        dialog._delete_selected_info_file()

        assert dialog._info_files_list.count() == 0
        assert dialog._collect_info_files() == {}
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_delete_existing_info_entry_only_saves_remove_tombstone(
        self, qapp, tmp_path
    ):
        """Checks that entry-only deletion survives future auto-discovery."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_folder = tmp_path / "entry_only_info_mod"
        mod_folder.mkdir()
        (mod_folder / "Guide.md").write_text("guide", encoding="utf-8")

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_folder)))
        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                "id": "local_entry_only_info_mod",
                "name": "Entry Only Info Mod",
                "author": "Author",
                "description": "Desc",
                "version": "1.0.0",
                "game": "deltarune",
                "info_files": {"Guide.md": "show"},
                "files": {},
                "folder_path": str(mod_folder),
            },
        )
        dialog._ask_delete_info_file_action = Mock(return_value="entry")

        dialog._info_files_list.setCurrentRow(0)
        dialog._delete_selected_info_file()

        assert dialog._info_files_list.count() == 0
        assert (mod_folder / "Guide.md").is_file()
        assert dialog._collect_info_files() == {"Guide.md": "remove"}
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_delete_info_file_can_remove_entry_and_file(
        self, qapp, tmp_path
    ):
        """Checks that INFO deletion can remove both the entry and physical file."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_folder = tmp_path / "delete_info_mod"
        mod_folder.mkdir()
        info_file = mod_folder / "Guide.md"
        info_file.write_text("guide", encoding="utf-8")

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_folder)))
        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                "id": "local_delete_info_mod",
                "name": "Delete Info Mod",
                "author": "Author",
                "description": "Desc",
                "version": "1.0.0",
                "game": "deltarune",
                "info_files": {"Guide.md": "show"},
                "files": {},
                "folder_path": str(mod_folder),
            },
        )
        dialog._ask_delete_info_file_action = Mock(return_value="entry_and_file")

        dialog._info_files_list.setCurrentRow(0)
        dialog._delete_selected_info_file()

        assert dialog._info_files_list.count() == 0
        assert not info_file.exists()
        assert dialog._collect_info_files() == {}
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_delete_info_file_refuses_external_source_file(
        self, qapp, tmp_path, monkeypatch
    ):
        """Checks that entry-and-file deletion cannot remove files outside the mod folder."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_folder = tmp_path / "delete_info_mod"
        mod_folder.mkdir()
        external_file = tmp_path / "external.md"
        external_file.write_text("external", encoding="utf-8")

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_folder)))
        dialog = ModEditorDialog(parent, is_creating=True)
        dialog._set_info_file_entries(
            [
                {
                    "path": "external.md",
                    "state": "show",
                    "custom": True,
                    "source_path": str(external_file),
                    "missing": False,
                }
            ]
        )
        dialog._ask_delete_info_file_action = Mock(return_value="entry_and_file")
        critical_calls = []
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            lambda *args, **kwargs: critical_calls.append((args, kwargs)),
        )

        dialog._info_files_list.setCurrentRow(0)
        dialog._delete_selected_info_file()

        assert external_file.is_file()
        assert dialog._info_files_list.count() == 1
        assert critical_calls
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_delete_missing_info_question_failure_is_ignored(
        self, qapp, tmp_path, monkeypatch
    ):
        """Checks broken missing-info delete confirmation keeps entry intact."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_folder = tmp_path / "missing_info_mod"
        mod_folder.mkdir()
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_folder)))
        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                "id": "local_missing_info_mod",
                "name": "Missing Info Mod",
                "author": "Author",
                "description": "Desc",
                "version": "1.0.0",
                "game": "deltarune",
                "info_files": {"Gone.md": "hide"},
                "files": {},
                "folder_path": str(mod_folder),
            },
        )
        monkeypatch.setattr(
            QMessageBox,
            "question",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog._info_files_list.setCurrentRow(0)
        dialog._delete_selected_info_file()

        assert dialog._info_files_list.count() == 1
        assert dialog._collect_info_files() == {"Gone.md": "hide"}
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_reset_rechecks_stale_missing_info_file(self, qapp, tmp_path):
        """Checks that reset proceeds when a previously missing file now exists."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_folder = tmp_path / "stale_missing_info_mod"
        mod_folder.mkdir()
        restored_file = mod_folder / "Restored.md"

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_folder)))
        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                "id": "local_stale_missing_info_mod",
                "name": "Stale Missing Info Mod",
                "author": "Author",
                "description": "Desc",
                "version": "1.0.0",
                "game": "deltarune",
                "info_files": {"Restored.md": "hide"},
                "files": {},
                "folder_path": str(mod_folder),
            },
        )
        restored_file.write_text("restored", encoding="utf-8")

        dialog._info_files_list.setCurrentRow(0)
        dialog._reset_selected_info_file()

        entry = dialog._info_files_list.item(0).data(Qt.ItemDataRole.UserRole)
        assert entry == {
            "path": "Restored.md",
            "state": "show",
            "custom": False,
            "source_path": str(restored_file),
            "missing": False,
        }
        assert dialog._collect_info_files() == {}
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_info_widgets_are_parented_inside_section_content(self, qapp, tmp_path):
        """Checks that info widgets are created inside the info section, not on the dialog root."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        info_content = dialog._section_widgets["info_files"]["content"]

        assert dialog._info_files_list.parentWidget() is info_content
        assert dialog._info_add_button.parentWidget() is info_content
        assert dialog._info_toggle_button.parentWidget() is info_content
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_sections_are_pinned_to_top_with_bottom_spacer(self, qapp, tmp_path):
        """Checks that the outer layout keeps collapsed sections packed at the top."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        from PyQt6.QtWidgets import QScrollArea

        scroll = dialog.findChild(QScrollArea)
        outer_layout = scroll.widget().layout()

        assert outer_layout.itemAt(outer_layout.count() - 1).spacerItem() is not None
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_removes_stale_managed_files_after_replace_or_delete(
        self, qapp, tmp_path
    ):
        """Checks that mod editor removes stale managed files after replace or delete."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_folder = tmp_path / "managed_mod"
        chapter_folder = mod_folder / "chapter_4"
        chapter_folder.mkdir(parents=True)
        stale_data = chapter_folder / "old.win"
        stale_extra = chapter_folder / "old_extra.zip"
        fresh_data = chapter_folder / "new.win"
        stale_data.write_text("old-data", encoding="utf-8")
        stale_extra.write_text("old-extra", encoding="utf-8")
        fresh_data.write_text("new-data", encoding="utf-8")

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        dialog._remove_stale_managed_files(
            str(mod_folder),
            {
                "deltarune_4": {
                    "data_file_url": "old.win",
                    "extra_files": {"extras": ["old_extra.zip"]},
                }
            },
            {
                "deltarune_4": {
                    "data_file_url": "new.win",
                }
            },
            "deltarune",
        )

        assert not stale_data.exists()
        assert not stale_extra.exists()
        assert fresh_data.exists()
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_finish_creation_saves_local_mod(self, qapp, tmp_path, monkeypatch):
        """Checks that mod editor finish creation saves local mod instead of crashing."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog
        from utils.file_utils import save_json

        source_file = tmp_path / "source.xdelta"
        source_file.write_text("patch", encoding="utf-8")

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path / "mods"))
        parent.app_state.mods_dir = str(tmp_path / "mods")
        os.makedirs(parent.app_state.mods_dir, exist_ok=True)
        parent.settings_service = SimpleNamespace(write_json=save_json)
        parent.mod_service = Mock(
            invalidate_mods_cache=Mock(),
            load_local_mods=Mock(),
            mod_list_updated=SimpleNamespace(emit=Mock()),
        )
        parent.library_display = SimpleNamespace(update_display=Mock())

        info_calls = []
        monkeypatch.setattr(
            QMessageBox, "information", lambda *args, **kwargs: info_calls.append((args, kwargs))
        )
        monkeypatch.setattr(
            QMessageBox, "warning", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Unexpected warning"))
        )
        monkeypatch.setattr(
            QMessageBox, "critical", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Unexpected critical"))
        )

        dialog = ModEditorDialog(parent, is_creating=True)
        dialog.name_edit.setText("Created Mod")
        first_tab = dialog.file_tabs.widget(0)
        layout = first_tab._file_layout
        dialog._create_file_frame(layout, "data")
        data_input = next(
            w for w in first_tab.findChildren(type(dialog.icon_edit)) if w.property("is_local_path")
        )
        data_input.setText(str(source_file))

        dialog._save_mod()

        created_dirs = [p for p in (tmp_path / "mods").iterdir() if p.is_dir()]
        assert len(created_dirs) == 1
        config_path = created_dirs[0] / "mod_config.json"
        assert config_path.is_file()
        assert info_calls
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_closes_before_refresh_and_success_message(
        self, qapp, tmp_path, monkeypatch
    ):
        """Checks that saving closes editor before refreshing library widgets."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog
        from utils.file_utils import load_json, save_json

        mod_dir = tmp_path / "mods" / "editable"
        mod_dir.mkdir(parents=True)
        config_path = mod_dir / "mod_config.json"
        save_json(
            str(config_path),
            {
                "id": "local_editable",
                "name": "Editable",
                "version": "1.0.0",
                "author": "Author",
                "description": "Desc",
                "game": "deltarune",
                "files": {},
            },
        )

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path / "mods"))
        call_order = []
        parent.settings_service = SimpleNamespace(read_json=load_json, write_json=save_json)
        parent.mod_service = Mock(
            get_mod_folder_path=Mock(return_value=str(mod_dir)),
            invalidate_mods_cache=Mock(side_effect=lambda: call_order.append(("refresh", dialog.isVisible()))),
            load_local_mods=Mock(),
            mod_list_updated=SimpleNamespace(emit=Mock()),
        )
        parent.library_display = SimpleNamespace(update_display=Mock())

        def record_information(owner, *_args, **_kwargs):
            call_order.append(("message", dialog.isVisible(), owner is parent))

        monkeypatch.setattr(QMessageBox, "information", record_information)
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("Unexpected critical")
            ),
        )

        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                "id": "local_editable",
                "folder_path": str(mod_dir),
                "name": "Editable",
                "version": "1.0.0",
                "author": "Author",
                "description": "Desc",
                "game": "deltarune",
                "files": {},
            },
        )
        dialog.show()
        qapp.processEvents()

        dialog.name_edit.setText("Edited")
        dialog._save_mod()

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert call_order == [("refresh", False), ("message", False, True)]
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_suppresses_success_message_failure_after_save(
        self, qapp, tmp_path, monkeypatch
    ):
        """Checks that a broken success dialog does not turn a completed save into a crash."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path / "mods"))
        parent.mod_service = Mock(
            invalidate_mods_cache=Mock(),
            load_local_mods=Mock(),
            mod_list_updated=SimpleNamespace(emit=Mock()),
        )
        parent.library_display = SimpleNamespace(update_display=Mock())
        monkeypatch.setattr(
            QMessageBox,
            "information",
            Mock(side_effect=RuntimeError("message box failed")),
        )

        dialog = ModEditorDialog(parent, is_creating=True)

        dialog._finish_successful_save("Saved", "Done")

        assert dialog.result() == QDialog.DialogCode.Accepted
        parent.mod_service.invalidate_mods_cache.assert_called_once_with()
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_create_error_cleans_up_when_error_dialog_fails(
        self, qapp, tmp_path, monkeypatch
    ):
        """Checks a broken error dialog does not leave a partial local mod folder."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        source_file = tmp_path / "source.xdelta"
        source_file.write_text("patch", encoding="utf-8")

        parent = QWidget()
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(mods_dir))
        parent.settings_service = SimpleNamespace(
            write_json=Mock(side_effect=OSError("disk full"))
        )
        parent.mod_service = Mock()
        parent.library_display = SimpleNamespace(update_display=Mock())
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog = ModEditorDialog(parent, is_creating=True)
        dialog.name_edit.setText("Broken Save")
        first_tab = dialog.file_tabs.widget(0)
        dialog._create_file_frame(first_tab._file_layout, "data")
        data_input = next(
            w
            for w in first_tab.findChildren(type(dialog.icon_edit))
            if w.property("is_local_path")
        )
        data_input.setText(str(source_file))

        dialog._save_mod()

        assert not list(mods_dir.iterdir())
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert dialog._save_button.isEnabled()
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_validation_warning_failure_does_not_start_save(
        self, qapp, tmp_path, monkeypatch
    ):
        """Checks validation warnings cannot crash or start a save when the dialog fails."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path / "mods"))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        parent.library_display = SimpleNamespace(update_display=Mock())
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog = ModEditorDialog(parent, is_creating=True)
        dialog.name_edit.setText("")
        dialog._create_local_mod = Mock()

        dialog._save_mod()

        dialog._create_local_mod.assert_not_called()
        assert dialog.result() == QDialog.DialogCode.Rejected
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_blocks_save_when_created_file_section_is_empty(
        self, qapp, tmp_path, monkeypatch
    ):
        """Checks save is blocked, warnings include extra section number, and empty fields are highlighted."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from services.localization_service import tr
        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path / "mods"))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        parent.library_display = SimpleNamespace(update_display=Mock())
        warning_calls = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *args: warning_calls.append(args),
        )

        dialog = ModEditorDialog(parent, is_creating=True)
        dialog.name_edit.setText("Section Validation")
        dialog._create_local_mod = Mock()

        first_tab = dialog.file_tabs.widget(0)
        layout = first_tab._file_layout

        dialog._create_file_frame(layout, "data")
        dialog._save_mod()

        dialog._create_local_mod.assert_not_called()
        assert warning_calls[-1][2] == tr(
            "dialogs.empty_data_file_section",
            tab_name=dialog.file_tabs.tabText(0),
        )
        data_input = next(
            w for w in first_tab.findChildren(type(dialog.icon_edit)) if w.property("is_local_path")
        )
        assert data_input.property("validation_error") is True
        assert "#d9534f" in data_input.styleSheet()

        data_input.setText("data.win")
        assert not data_input.property("validation_error")
        assert data_input.styleSheet() == ""

        dialog._create_file_frame(layout, "extra")
        dialog._create_file_frame(layout, "extra")
        extra_inputs = [
            w
            for w in first_tab.findChildren(type(dialog.icon_edit))
            if w.property("is_local_extra_path")
        ]
        extra_inputs[0].setText("bonus.zip")
        dialog._save_mod()

        dialog._create_local_mod.assert_not_called()
        assert warning_calls[-1][2] == tr(
            "dialogs.empty_extra_file_section",
            tab_name=dialog.file_tabs.tabText(0),
            number=2,
        )
        assert extra_inputs[1].property("validation_error") is True
        assert "#d9534f" in extra_inputs[1].styleSheet()
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_cancel_question_failure_keeps_dialog_open(
        self, qapp, tmp_path, monkeypatch
    ):
        """Checks broken cancel confirmation does not reject the editor."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        monkeypatch.setattr(
            QMessageBox,
            "question",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog = ModEditorDialog(parent, is_creating=True)
        dialog.reject = Mock()

        dialog._on_cancel()

        dialog.reject.assert_not_called()
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_delete_question_failure_does_not_delete(
        self, qapp, tmp_path, monkeypatch
    ):
        """Checks broken delete confirmation defaults to no deletion."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_dir = tmp_path / "mods" / "delete_me"
        mod_dir.mkdir(parents=True)
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path / "mods"))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_dir)))
        monkeypatch.setattr(
            QMessageBox,
            "question",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                "id": "local_delete_me",
                "folder_path": str(mod_dir),
                "name": "Delete Me",
                "version": "1.0.0",
                "author": "Author",
                "description": "Desc",
                "game": "deltarune",
                "files": {},
            },
        )

        dialog._delete_mod()

        assert mod_dir.exists()
        assert dialog.result() == QDialog.DialogCode.Rejected
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_delete_missing_id_critical_failure_is_ignored(
        self, qapp, tmp_path, monkeypatch
    ):
        """Checks delete error feedback failure does not crash the editor."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        monkeypatch.setattr(
            QMessageBox,
            "question",
            Mock(return_value=QMessageBox.StandardButton.Yes),
        )
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog = ModEditorDialog(parent, is_creating=False, mod_data={"files": {}})

        dialog._delete_mod()

        assert dialog.result() == QDialog.DialogCode.Rejected
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_open_missing_folder_warning_failure_is_ignored(
        self, qapp, tmp_path, monkeypatch
    ):
        """Checks missing folder warning failure does not crash open-folder action."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=""))
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                "id": "local_missing_folder",
                "name": "Missing Folder",
                "files": {},
            },
        )

        dialog._open_mod_folder()

        assert dialog.result() == QDialog.DialogCode.Rejected
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_export_success_message_failure_is_ignored(
        self, qapp, tmp_path, monkeypatch
    ):
        """Checks export completion is not undone by broken success dialog."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_dir = tmp_path / "mods" / "export_me"
        mod_dir.mkdir(parents=True)
        (mod_dir / "mod_config.json").write_text("{}", encoding="utf-8")
        export_path = tmp_path / "export.zip"
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path / "mods"))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_dir)))
        monkeypatch.setattr(
            "ui.dialogs.mod_editor.dialog.get_save_file_name",
            lambda *_args, **_kwargs: (str(export_path), ""),
        )
        monkeypatch.setattr(
            QMessageBox,
            "information",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            Mock(side_effect=AssertionError("Unexpected export failure dialog")),
        )

        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                "id": "local_export_me",
                "folder_path": str(mod_dir),
                "name": "Export Me",
                "files": {},
            },
        )

        dialog._export_mod()

        assert export_path.exists()
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_export_missing_folder_critical_failure_is_ignored(
        self, qapp, tmp_path, monkeypatch
    ):
        """Checks missing export source warning cannot crash the editor."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path / "mods"))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=""))
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={"id": "local_missing_export", "name": "Missing", "files": {}},
        )

        dialog._export_mod()

        assert dialog.result() == QDialog.DialogCode.Rejected
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_export_error_message_failure_is_ignored(
        self, qapp, tmp_path, monkeypatch
    ):
        """Checks export filesystem errors stay handled if critical dialog breaks."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_dir = tmp_path / "mods" / "export_fail"
        mod_dir.mkdir(parents=True)
        export_path = tmp_path / "missing_parent" / "export.zip"
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path / "mods"))
        parent.settings_service = Mock()
        parent.mod_service = Mock(get_mod_folder_path=Mock(return_value=str(mod_dir)))
        monkeypatch.setattr(
            "ui.dialogs.mod_editor.dialog.get_save_file_name",
            lambda *_args, **_kwargs: (str(export_path), ""),
        )
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog = ModEditorDialog(
            parent,
            is_creating=False,
            mod_data={
                "id": "local_export_fail",
                "folder_path": str(mod_dir),
                "name": "Export Fail",
                "files": {},
            },
        )

        dialog._export_mod()

        assert dialog.result() == QDialog.DialogCode.Rejected
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_ignores_duplicate_save_clicks(self, qapp, tmp_path, monkeypatch):
        """Checks that repeated save clicks cannot start concurrent saves."""
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QMessageBox

        from ui.dialogs.mod_editor.dialog import ModEditorDialog
        from utils.file_utils import save_json

        source_file = tmp_path / "source.xdelta"
        source_file.write_text("patch", encoding="utf-8")
        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path / "mods"))
        parent.app_state.mods_dir = str(tmp_path / "mods")
        os.makedirs(parent.app_state.mods_dir, exist_ok=True)
        parent.settings_service = SimpleNamespace(write_json=Mock(side_effect=lambda *args, **kwargs: dialog._save_mod() or save_json(*args, **kwargs)))
        parent.mod_service = Mock(
            invalidate_mods_cache=Mock(),
            load_local_mods=Mock(),
            mod_list_updated=SimpleNamespace(emit=Mock()),
        )
        parent.library_display = SimpleNamespace(update_display=Mock())
        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("Unexpected critical")
            ),
        )

        dialog = ModEditorDialog(parent, is_creating=True)
        dialog.name_edit.setText("Created Once")
        first_tab = dialog.file_tabs.widget(0)
        dialog._create_file_frame(first_tab._file_layout, "data")
        data_input = next(
            w for w in first_tab.findChildren(type(dialog.icon_edit)) if w.property("is_local_path")
        )
        data_input.setText(str(source_file))

        dialog._save_mod()

        created_dirs = [p for p in (tmp_path / "mods").iterdir() if p.is_dir()]
        assert len(created_dirs) == 1
        assert parent.settings_service.write_json.call_count == 1
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_copy_preserves_existing_relative_chapter_paths(
        self, qapp, tmp_path
    ):
        """Checks that editing keeps stored chapter-relative paths intact."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        mod_dir = tmp_path / "mod"
        (mod_dir / "chapter3" / "lang").mkdir(parents=True)
        (mod_dir / "chapter3" / "data.g3mpatch").write_text("patch", encoding="utf-8")
        (mod_dir / "chapter3" / "lang" / "lang_en.json").write_text(
            "lang", encoding="utf-8"
        )

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(tmp_path))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)
        dialog._find_mod_folder = Mock(return_value=str(mod_dir))

        processed = dialog._copy_files_to_mod_dir(
            str(mod_dir),
            {
                "deltarune_3": {
                    "data_file_path": "chapter3/data.g3mpatch",
                    "extra_files": ["chapter3/lang/lang_en.json"],
                }
            },
            "deltarune",
        )

        assert processed["deltarune_3"]["data_file_path"] == "chapter3/data.g3mpatch"
        assert processed["deltarune_3"]["extra_files"] == ["chapter3/lang/lang_en.json"]
        dialog.close()
        parent.deleteLater()

    def test_mod_editor_copy_places_external_chapter_files_under_chapter_folder(
        self, qapp, tmp_path
    ):
        """Checks that chapter-specific external files are stored under the chapter folder."""
        from types import SimpleNamespace

        from ui.dialogs.mod_editor.dialog import ModEditorDialog

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        patch_file = source_dir / "data.g3mpatch"
        patch_file.write_text("patch", encoding="utf-8")

        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        mod_dir = mods_dir / "created"
        mod_dir.mkdir()

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={}, mods_dir=str(mods_dir))
        parent.settings_service = Mock()
        parent.mod_service = Mock()
        dialog = ModEditorDialog(parent, is_creating=True)

        processed = dialog._copy_files_to_mod_dir(
            str(mod_dir),
            {"deltarune_3": {"data_file_path": str(patch_file)}},
            "deltarune",
        )

        assert processed["deltarune_3"]["data_file_path"] == "chapter_3/data.g3mpatch"
        assert (mod_dir / "chapter_3" / "data.g3mpatch").is_file()
        dialog.close()
        parent.deleteLater()


class TestManualInstallDialog:
    """Tests for dialogs."""
    def test_manual_install_dialog_shows_summary_for_found_files(self, qapp, tmp_path):
        """Checks that manualing install dialog shows summary for found files."""
        from services.localization_service import tr
        from ui.dialogs.manual_install.dialog import ManualModInstallDialog

        prepared = tmp_path / 'prepared'
        prepared.mkdir()
        (prepared / 'README.md').write_text('# guide', encoding='utf-8')
        (prepared / 'mod.win').write_text('data', encoding='utf-8')

        dialog = ManualModInstallDialog(None, str(prepared))

        assert hasattr(dialog, 'files_summary_label')
        assert dialog.files_summary_label.text()
        assert dialog.game_combo.toolTip() == tr("tooltips.manual_install_game")
        assert dialog.files_summary_label.toolTip() == tr("tooltips.manual_install_summary")
        dialog.close()

    def test_manual_install_dialog_ignores_gamebanana_game_for_default_selection(
        self, qapp, tmp_path
    ):
        """Checks that manualing install dialog ignores gamebanana game for default selection."""
        from ui.dialogs.manual_install.dialog import ManualModInstallDialog

        prepared = tmp_path / "prepared"
        prepared.mkdir()
        (prepared / "README.md").write_text("# guide", encoding="utf-8")

        dialog = ManualModInstallDialog(
            None,
            str(prepared),
            gamebanana_metadata={"game": "pizzatower"},
        )

        assert dialog.game_combo.currentData() != "pizzatower"
        dialog.close()

    def test_manual_install_dialog_shows_deltarune_extra_hint(self, qapp, tmp_path):
        """Checks that DELTARUNE extra files hint mentions chapter prefixes."""
        from services.localization_service import tr
        from ui.dialogs.manual_install.dialog import ManualModInstallDialog

        prepared = tmp_path / "prepared"
        prepared.mkdir()
        (prepared / "README.md").write_text("# guide", encoding="utf-8")

        dialog = ManualModInstallDialog(None, str(prepared))
        dialog.game_combo.setCurrentIndex(
            next(
                i
                for i in range(dialog.game_combo.count())
                if dialog.game_combo.itemData(i) == "deltarune"
            )
        )

        assert dialog.extra_instructions_label.text() == tr(
            "dialogs.extra_files_path_instructions_deltarune"
        )
        dialog.close()

    def test_manual_install_dialog_normalizes_paths_relative_to_selected_chapter(
        self, qapp, tmp_path
    ):
        """Checks that manual install strips chapter root prefixes from targets."""
        from ui.dialogs.manual_install.dialog import ManualModInstallDialog

        prepared = tmp_path / "prepared"
        prepared.mkdir()
        (prepared / "data.win").write_text("data", encoding="utf-8")

        dialog = ManualModInstallDialog(None, str(prepared))
        dialog.game_combo.setCurrentIndex(
            next(
                i
                for i in range(dialog.game_combo.count())
                if dialog.game_combo.itemData(i) == "deltarune"
            )
        )
        dialog._get_target_root_for_chapter = Mock(
            return_value=str(tmp_path / "chapter1_windows")
        )

        assert (
            dialog._normalize_relative_target_path(
                "chapter1_windows/lang_es/",
                "deltarune_1",
                trailing_slash=True,
            )
            == "lang_es/"
        )
        assert (
            dialog._normalize_relative_target_path(
                "chapter_1/lang_es/file.txt",
                "deltarune_1",
            )
            == "lang_es/file.txt"
        )
        dialog.close()

    def test_manual_install_dialog_missing_doc_uses_localized_file_not_found(
        self, qapp, tmp_path, monkeypatch
    ):
        from services.localization_service import tr
        from ui.dialogs.manual_install.dialog import ManualModInstallDialog

        prepared = tmp_path / "prepared"
        prepared.mkdir()
        dialog = ManualModInstallDialog(None, str(prepared))
        missing_file = str(prepared / "missing_readme.md")
        calls = []
        monkeypatch.setattr(
            "ui.dialogs.manual_install.dialog.QMessageBox.warning",
            lambda *args: calls.append(args),
        )

        dialog._open_local_file(missing_file)

        assert calls
        assert calls[0][2] == tr("errors.file_not_found", path=missing_file)
        dialog.close()

    def test_manual_install_missing_doc_warning_failure_is_ignored(
        self, qapp, tmp_path, monkeypatch
    ):
        from ui.dialogs.manual_install.dialog import ManualModInstallDialog

        prepared = tmp_path / "prepared"
        prepared.mkdir()
        dialog = ManualModInstallDialog(None, str(prepared))
        missing_file = str(prepared / "missing_readme.md")
        monkeypatch.setattr(
            "ui.dialogs.manual_install.dialog.QMessageBox.warning",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog._open_local_file(missing_file)

        assert dialog.result() == QDialog.DialogCode.Rejected
        dialog.close()

    def test_manual_install_finish_warning_failure_does_not_crash(
        self, qapp, tmp_path, monkeypatch
    ):
        from ui.dialogs.manual_install.dialog import ManualModInstallDialog

        prepared = tmp_path / "prepared"
        prepared.mkdir()
        dialog = ManualModInstallDialog(None, str(prepared))
        monkeypatch.setattr(
            "ui.dialogs.manual_install.dialog.QMessageBox.warning",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog._on_finish()

        assert dialog.result() == QDialog.DialogCode.Rejected
        dialog.close()

    def test_manual_install_no_data_files_info_failure_is_ignored(
        self, qapp, tmp_path, monkeypatch
    ):
        from ui.dialogs.manual_install.dialog import ManualModInstallDialog

        prepared = tmp_path / "prepared"
        prepared.mkdir()
        (prepared / "README.md").write_text("# guide", encoding="utf-8")
        dialog = ManualModInstallDialog(None, str(prepared))
        monkeypatch.setattr(
            "ui.dialogs.manual_install.dialog.QMessageBox.information",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog._browse_data_file("deltarune_1")

        assert dialog.result() == QDialog.DialogCode.Rejected
        dialog.close()

    def test_manual_install_no_xdelta_files_info_failure_is_ignored(
        self, qapp, tmp_path, monkeypatch
    ):
        from ui.dialogs.manual_install.dialog import ManualModInstallDialog

        prepared = tmp_path / "prepared"
        prepared.mkdir()
        (prepared / "data.win").write_text("data", encoding="utf-8")
        dialog = ManualModInstallDialog(None, str(prepared))
        dialog.data_file_selections["deltarune_1"] = str(prepared / "data.win")
        monkeypatch.setattr(
            "ui.dialogs.manual_install.dialog.QMessageBox.information",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog._add_xdelta_patch("deltarune_1")

        assert dialog.result() == QDialog.DialogCode.Rejected
        dialog.close()

    def test_manual_install_xdelta_outside_path_warning_failure_is_ignored(
        self, qapp, tmp_path, monkeypatch
    ):
        from ui.dialogs.manual_install.dialog import ManualModInstallDialog

        prepared = tmp_path / "prepared"
        prepared.mkdir()
        patch_file = prepared / "patch.xdelta"
        patch_file.write_text("patch", encoding="utf-8")
        target_root = tmp_path / "game"
        target_root.mkdir()
        outside_file = tmp_path / "outside.win"
        outside_file.write_text("data", encoding="utf-8")
        dialog = ManualModInstallDialog(None, str(prepared))
        dialog._get_target_root_for_chapter = Mock(return_value=str(target_root))
        monkeypatch.setattr(
            "ui.dialogs.manual_install.dialog.get_open_file_name",
            lambda *_args, **_kwargs: (str(outside_file), ""),
        )
        monkeypatch.setattr(
            "ui.dialogs.manual_install.dialog.QMessageBox.warning",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog._browse_xdelta_target_file(str(patch_file), "deltarune_1")

        assert dialog.result() == QDialog.DialogCode.Rejected
        dialog.close()

    def test_manual_install_extra_outside_path_warning_failure_is_ignored(
        self, qapp, tmp_path, monkeypatch
    ):
        from ui.dialogs.manual_install.dialog import ManualModInstallDialog

        prepared = tmp_path / "prepared"
        prepared.mkdir()
        extra_file = prepared / "extra.txt"
        extra_file.write_text("extra", encoding="utf-8")
        game_root = tmp_path / "game"
        game_root.mkdir()
        outside_folder = tmp_path / "outside"
        outside_folder.mkdir()
        dialog = ManualModInstallDialog(None, str(prepared))
        dialog._get_or_prompt_game_folder = Mock(return_value=str(game_root))
        monkeypatch.setattr(
            "ui.dialogs.manual_install.dialog.get_existing_directory",
            lambda *_args, **_kwargs: str(outside_folder),
        )
        monkeypatch.setattr(
            "ui.dialogs.manual_install.dialog.QMessageBox.warning",
            Mock(side_effect=RuntimeError("dialog already deleted")),
        )

        dialog._browse_target_folder(str(extra_file))

        assert dialog.result() == QDialog.DialogCode.Rejected
        dialog.close()

    def test_profile_manager_import_failure_uses_localized_filesystem_error(
        self, qapp, tmp_path, monkeypatch
    ):
        from services.localization_service import tr
        from ui.dialogs.profile_manager_dialog import ProfileManagerDialog

        archive_path = tmp_path / "profile.zip"
        archive_path.write_bytes(b"zip")
        profile_service = Mock()
        profile_service.active_name = "Default"
        profile_service.list_profiles.return_value = ["Default"]
        profile_service.get_profile_summary.return_value = {
            "name": "Default",
            "game": "deltarune",
            "game_display_name": "DELTARUNE",
            "game_mod_count": 0,
            "total_mod_count": 0,
            "chapter_mode": False,
            "direct_launch": "",
        }
        profile_service.import_profile.side_effect = PermissionError(
            13, "Permission denied", str(archive_path)
        )
        app_state = Mock(local_config={})
        dialog = ProfileManagerDialog(profile_service, app_state)
        calls = []
        monkeypatch.setattr(
            "ui.dialogs.profile_manager_dialog.QMessageBox.critical",
            lambda *args: calls.append(args),
        )

        dialog.import_profiles_from_paths([str(archive_path)])

        assert calls
        assert calls[0][2] == tr(
            "profiles.import_failed",
            error=tr("errors.permission_denied", path=str(archive_path)),
        )
        _close_dialog(qapp, dialog)
