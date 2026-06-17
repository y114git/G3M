"""Unit tests for user data bootstrap failure handling."""

from unittest.mock import Mock


def test_user_data_migration_warning_failure_does_not_abort_bootstrap(
    monkeypatch, tmp_path
):
    from bootstrap import user_data_bootstrap

    legacy_root = tmp_path / "legacy"
    g3m_root = tmp_path / "g3m"
    legacy_root.mkdir()
    monkeypatch.setattr(
        user_data_bootstrap,
        "get_default_user_data_root",
        lambda: str(g3m_root),
    )
    monkeypatch.setattr(
        user_data_bootstrap,
        "get_legacy_user_data_root",
        lambda: str(legacy_root),
    )
    monkeypatch.setattr(
        user_data_bootstrap,
        "_ask_user_data_migration_choice",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        user_data_bootstrap,
        "_copy_missing_entries",
        Mock(side_effect=OSError("copy failed")),
    )
    warning = Mock(side_effect=RuntimeError("dialog already deleted"))
    monkeypatch.setattr(user_data_bootstrap.QMessageBox, "warning", warning)

    resolved = user_data_bootstrap.resolve_user_data_root_with_migration()

    assert resolved == str(g3m_root)
    assert g3m_root.is_dir()
    warning.assert_called_once()
