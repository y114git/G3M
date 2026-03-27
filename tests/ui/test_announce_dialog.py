from types import SimpleNamespace

from PyQt6.QtWidgets import QWidget


class TestAnnounceDialog:
    def test_poll_single_enables_ok_only_after_selection(self, qapp):
        from services.localization_service import tr
        from ui.dialogs.announce_dialog import AnnounceDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={})
        dialog = AnnounceDialog(
            {
                "type": "poll_single",
                "message": "<b>Hello</b>",
                "poll": {"A": {}, "B": {}},
            },
            parent,
        )

        assert dialog.panel.ok_button.isEnabled() is False
        assert dialog.panel.text_browser.toolTip() == tr("tooltips.announcement_text")
        assert dialog.panel.ok_button.toolTip() == tr("tooltips.confirm")
        dialog.panel.select_option(0)
        assert dialog.panel.ok_button.isEnabled() is True
        assert dialog.panel.selected_options() == ["A"]
        assert dialog.panel.option_buttons[0].toolTip() == tr("tooltips.announcement_option")

        dialog.close()
        parent.deleteLater()

    def test_relocalize_ui_updates_visible_texts(self, qapp):
        from services.localization_service import localization_service
        from ui.dialogs.announce_dialog import AnnounceDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={})
        dialog = AnnounceDialog(
            {
                "type": "poll_single",
                "message": "Hello",
                "poll": {"A": {}, "B": {}},
            },
            parent,
        )

        initial_title = dialog.windowTitle()
        initial_button = dialog.panel.details_button.text()

        original_language = localization_service.get_current_language()
        try:
            available_languages = localization_service.get_available_languages()
            other_language = None
            for lang_code in available_languages:
                if lang_code != original_language:
                    other_language = lang_code
                    break

            if other_language and localization_service.load_language(other_language):
                dialog.relocalize_ui()

                assert dialog.windowTitle() != initial_title, "Window title should change after language switch"
                assert dialog.panel.details_button.text() != initial_button, "Details button text should change after language switch"
            else:
                dialog.relocalize_ui()
        finally:
            localization_service.load_language(original_language)

        dialog.close()
        parent.deleteLater()

    def test_poll_multiple_allows_multiple_checked_buttons(self, qapp):
        from ui.dialogs.announce_dialog import AnnounceDialog

        parent = QWidget()
        parent.app_state = SimpleNamespace(local_config={})
        dialog = AnnounceDialog(
            {
                "type": "poll_multiple",
                "message": "Hello",
                "poll": {"A": {}, "B": {}, "C": {}},
            },
            parent,
        )

        dialog.panel.select_option(0)
        dialog.panel.select_option(1)

        assert dialog.panel.selected_options() == ["A", "B"]

        dialog.close()
        parent.deleteLater()
