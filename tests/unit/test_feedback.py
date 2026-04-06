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
    assert html.escape("<b>New launcher version</b><br>Line 2") in box.text
