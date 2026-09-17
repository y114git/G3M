from unittest.mock import Mock

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from ui.dialogs.g3mtool_diff_viewer import DiffViewerDialog


def test_failed_report_export_keeps_report_for_retry(
    qtbot, app_state, tmp_path, monkeypatch
):
    source = tmp_path / "report.md"
    source.write_text("# Comparison\nOne changed resource.\n", encoding="utf-8")
    destination = tmp_path / "missing" / "export.md"
    monkeypatch.setattr(
        "ui.dialogs.g3mtool_diff_viewer.get_save_file_name",
        lambda *args: (str(destination), ""),
    )
    warning = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warning)
    monkeypatch.setattr(
        "ui.dialogs.g3mtool_diff_viewer.safe_question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    dialog = DiffViewerDialog(str(source), app_state)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog._export_btn.width() == dialog._export_btn.height()
    section = dialog._section_widgets[0]
    section._header.setFocus()
    qtbot.keyClick(section._header, Qt.Key.Key_Space)
    assert section._body.isVisible()
    assert section._header.arrowType() == Qt.ArrowType.DownArrow
    qtbot.keyClick(section._header, Qt.Key.Key_Space)
    assert not section._body.isVisible()
    dialog._export_btn.click()
    warning.assert_called_once()
    assert "export.md" in warning.call_args.args[2]
    assert dialog.isVisible()
    assert source.is_file()
    destination.parent.mkdir()
    dialog._export_btn.click()
    assert destination.read_bytes() == source.read_bytes()
    assert warning.call_count == 1
