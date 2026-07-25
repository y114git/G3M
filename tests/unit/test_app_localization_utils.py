from unittest.mock import Mock, patch

from app.localization_utils import _relocalize_widgets


def test_relocalizes_every_live_widget_with_supported_contract() -> None:
    main = Mock(spec=[])
    dialog = Mock(spec=["relocalize_ui"])
    card = Mock(spec=["update_labels_text"])
    hidden = Mock(spec=["isVisible", "relocalize_ui"])
    hidden.isVisible.return_value = False

    with patch(
        "app.localization_utils.QApplication.allWidgets",
        return_value=[main, dialog, card, hidden],
    ):
        _relocalize_widgets(main)

    dialog.relocalize_ui.assert_called_once_with()
    card.update_labels_text.assert_called_once_with()
    hidden.relocalize_ui.assert_called_once_with()


def test_broken_widget_does_not_block_other_localization() -> None:
    main = Mock(spec=[])
    broken = Mock(spec=["relocalize_ui"])
    broken.relocalize_ui.side_effect = ValueError("broken plugin widget")
    healthy = Mock(spec=["relocalize_ui"])

    with patch(
        "app.localization_utils.QApplication.allWidgets",
        return_value=[broken, healthy],
    ):
        _relocalize_widgets(main)

    healthy.relocalize_ui.assert_called_once_with()


def test_attribute_error_is_logged_and_does_not_block_relocalization(caplog) -> None:
    main = Mock(spec=[])
    broken = Mock(spec=["relocalize_ui"])
    broken.relocalize_ui.side_effect = AttributeError("missing label")
    healthy = Mock(spec=["relocalize_ui"])

    with patch(
        "app.localization_utils.QApplication.allWidgets",
        return_value=[broken, healthy],
    ):
        _relocalize_widgets(main)

    assert "Failed to relocalize widget" in caplog.text
    healthy.relocalize_ui.assert_called_once_with()


def test_deleted_widget_error_is_ignored_and_does_not_block_relocalization(
    caplog,
) -> None:
    main = Mock(spec=[])
    deleted = Mock(spec=["relocalize_ui"])
    deleted.relocalize_ui.side_effect = RuntimeError(
        "wrapped C/C++ object has been deleted"
    )
    healthy = Mock(spec=["relocalize_ui"])

    with patch(
        "app.localization_utils.QApplication.allWidgets",
        return_value=[deleted, healthy],
    ):
        _relocalize_widgets(main)

    assert "Failed to relocalize widget" not in caplog.text
    healthy.relocalize_ui.assert_called_once_with()
