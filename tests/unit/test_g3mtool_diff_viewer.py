"""Unit tests for G3M tool diff viewer safety."""

from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6.QtWidgets import QApplication

from ui.dialogs.g3mtool_diff_viewer import DiffViewerDialog


def test_diff_viewer_close_question_failure_keeps_dialog_open(tmp_path, monkeypatch):
    """Checks failed close confirmation keeps the diff viewer open."""
    app = QApplication.instance() or QApplication([])
    report = tmp_path / "report.md"
    report.write_text("# Report\n\nBody", encoding="utf-8")
    dialog = DiffViewerDialog(str(report), SimpleNamespace(local_config={}))
    event = SimpleNamespace(ignore=Mock(), accept=Mock())
    monkeypatch.setattr(
        "ui.dialogs.g3mtool_diff_viewer.QMessageBox.question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("dialog deleted")),
    )

    dialog.closeEvent(event)

    event.ignore.assert_called_once_with()
    event.accept.assert_not_called()
    dialog.deleteLater()
    app.processEvents()
