from types import SimpleNamespace

from PyQt6.QtWidgets import QWidget


class TestAnnounceDialog:
    def test_poll_single_enables_ok_only_after_selection(self, qapp):
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
        dialog.panel.select_option(0)
        assert dialog.panel.ok_button.isEnabled() is True
        assert dialog.panel.selected_options() == ["A"]

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
