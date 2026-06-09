"""Unit tests for test feedback."""

import html
from types import SimpleNamespace
from unittest.mock import Mock


def _make_message_box_stub():
    box = SimpleNamespace()
    box.Icon = SimpleNamespace(Question=object())
    box.StandardButton = SimpleNamespace(Yes=1, No=2)
    box.setIcon = Mock()
    box.setWindowTitle = Mock()
    box.setText = Mock(side_effect=lambda value: setattr(box, "text", value))
    box.setStandardButtons = Mock()
    box.setDefaultButton = Mock()
    box.exec = Mock(return_value=box.StandardButton.Yes)
    box.text = ""
    factory = Mock(return_value=box)
    factory.Icon = box.Icon
    factory.StandardButton = box.StandardButton
    return factory, box


def test_ask_question_keeps_html_details(monkeypatch, qapp):
    from ui.common import feedback as feedback_module
    from ui.common.feedback import FeedbackManager

    factory, box = _make_message_box_stub()
    monkeypatch.setattr(feedback_module, "QMessageBox", factory)
    manager = FeedbackManager()

    result = manager.ask_question(
        "status.update_available",
        "status.update_available",
        "<b>New launcher version</b><br>Line 2",
        default_yes=True,
        details_is_html=True,
    )

    assert result is True
    assert box.text.endswith("<b>New launcher version</b><br>Line 2")


def test_ask_question_escapes_plain_details(monkeypatch, qapp):
    from ui.common import feedback as feedback_module
    from ui.common.feedback import FeedbackManager

    factory, box = _make_message_box_stub()
    monkeypatch.setattr(feedback_module, "QMessageBox", factory)
    manager = FeedbackManager()

    result = manager.ask_question(
        "status.update_available",
        "status.update_available",
        "<b>New launcher version</b><br>Line 2",
        True,
    )

    assert result is True
    assert html.escape("<b>New launcher version</b><br>Line 2", quote=False) in box.text


def test_show_message_does_not_escape_plain_apostrophes_to_entities(monkeypatch, qapp):
    from ui.common import feedback as feedback_module
    from ui.common.feedback import FeedbackManager

    factory, box = _make_message_box_stub()
    factory.Icon.Critical = object()
    factory.Icon.Warning = object()
    factory.Icon.Information = object()
    monkeypatch.setattr(feedback_module, "QMessageBox", factory)
    manager = FeedbackManager(
        tr_func=lambda key, **kwargs: {
            "dialogs.warning": "Warning",
            "errors.mod_no_files": "Mod '{mod_name}' has no files to install.",
        }.get(key, key).format(**kwargs)
    )

    manager.show_message(
        "warning", "errors.mod_no_files", mod_name="CoolMod"
    )

    assert "&#x27;" not in box.text
    assert box.text == "Mod 'CoolMod' has no files to install."


def test_feedback_manager_scoped_translator_localizes_titles_and_messages(
    monkeypatch, qapp
):
    from ui.common import feedback as feedback_module
    from ui.common.feedback import FeedbackManager

    factory, box = _make_message_box_stub()
    monkeypatch.setattr(feedback_module, "QMessageBox", factory)
    manager = FeedbackManager(
        tr_func=lambda key, **_kwargs: {
            "dialogs.delete_save": "Delete save?",
            "dialogs.delete_save_confirmation": "Delete permanently?",
        }.get(key, f"[{key}]")
    )
    scoped = manager.scoped(
        lambda key, **_kwargs: {
            "dialogs.delete_save": "Delete save?",
            "dialogs.delete_save_confirmation": "Delete permanently?",
        }.get(key, f"[{key}]")
    )

    result = scoped.ask_question(
        "dialogs.delete_save",
        "dialogs.delete_save_confirmation",
    )

    assert result is True
    box.setWindowTitle.assert_called_once_with("Delete save?")
    assert "Delete permanently?" in box.text
