"""Unit tests for test status."""

from types import SimpleNamespace

from app.window.status import (
    on_progress_update,
    set_status_text,
    set_update_ui_enabled,
    update_status,
)


class _Widget:
    def __init__(self) -> None:
        self.enabled = None

    def setEnabled(self, value):  # noqa: N802
        self.enabled = value


class _Label:
    def __init__(self) -> None:
        self._word_wrap = False
        self.text_value = ""
        self.style_value = ""

    def wordWrap(self):  # noqa: N802
        return self._word_wrap

    def setWordWrap(self, value):  # noqa: N802
        self._word_wrap = value

    def setText(self, value):  # noqa: N802
        self.text_value = value

    def setStyleSheet(self, value):  # noqa: N802
        self.style_value = value


class _ProgressBar:
    def __init__(self) -> None:
        self.value = None
        self.visible = False

    def setValue(self, value):  # noqa: N802
        self.value = value

    def isVisible(self):  # noqa: N802
        return self.visible

    def setVisible(self, value):  # noqa: N802
        self.visible = value


def test_set_update_ui_enabled_toggles_all_controls():
    window = SimpleNamespace(
        action_button=_Widget(),
        chat_button=_Widget(),
        change_background_button=_Widget(),
        top_refresh_button=_Widget(),
        settings_button=_Widget(),
    )

    set_update_ui_enabled(window, False)

    assert window.action_button.enabled is False
    assert window.chat_button.enabled is False
    assert window.change_background_button.enabled is False
    assert window.top_refresh_button.enabled is False
    assert window.settings_button.enabled is False


def test_set_status_text_updates_label_and_color():
    label = _Label()
    window = SimpleNamespace(status_label=label)

    set_status_text(window, "Launcher settings", "status_info")

    assert window._last_status_color == "status_info"
    assert label.wordWrap() is True
    assert label.text_value == "Launcher settings"
    assert "color:" in label.style_value


def test_on_progress_update_shows_progress_bar_when_value_positive():
    progress_bar = _ProgressBar()
    window = SimpleNamespace(progress_bar=progress_bar)

    on_progress_update(window, 42)

    assert progress_bar.value == 42
    assert progress_bar.visible is True


def test_update_status_tracks_last_translation_state():
    label = _Label()
    window = SimpleNamespace(status_label=label)

    update_status(window, "Plain message", "white")

    assert hasattr(window, "_last_status_translation")
    assert label.text_value == "Plain message"
