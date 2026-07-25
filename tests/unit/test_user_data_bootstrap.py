"""Unit tests for user data bootstrap failure handling."""

from unittest.mock import Mock

import pytest

from bootstrap.user_data_locator import write_selected_user_data_root
from utils.path_utils import get_user_data_root, set_user_data_root_override


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


def test_bootstrap_uses_saved_custom_root_without_appending_name(monkeypatch, tmp_path):
    from bootstrap import user_data_bootstrap

    default_root = tmp_path / "default"
    custom_root = tmp_path / "Portable Library"
    custom_root.mkdir()
    write_selected_user_data_root(str(default_root), str(custom_root))
    monkeypatch.setattr(user_data_bootstrap, "get_default_user_data_root", lambda: str(default_root))
    monkeypatch.setattr(user_data_bootstrap, "get_legacy_user_data_root", lambda: str(tmp_path / "legacy"))
    set_user_data_root_override(None)

    try:
        resolved = user_data_bootstrap.resolve_user_data_root_with_migration(interactive=False)
        assert resolved == str(custom_root)
        assert get_user_data_root() == str(custom_root)
        assert not (custom_root / "G3M").exists()
    finally:
        set_user_data_root_override(None)


def test_headless_bootstrap_rejects_missing_custom_root(monkeypatch, tmp_path):
    from bootstrap import user_data_bootstrap

    default_root = tmp_path / "default"
    write_selected_user_data_root(str(default_root), str(tmp_path / "missing-drive"))
    monkeypatch.setattr(user_data_bootstrap, "get_default_user_data_root", lambda: str(default_root))
    monkeypatch.setattr(user_data_bootstrap, "get_legacy_user_data_root", lambda: str(tmp_path / "legacy"))

    with pytest.raises(user_data_bootstrap.UserDataRootUnavailableError, match="not available"):
        user_data_bootstrap.resolve_user_data_root_with_migration(interactive=False)


def test_interactive_bootstrap_can_return_to_default_root(monkeypatch, tmp_path):
    from bootstrap import user_data_bootstrap

    default_root = tmp_path / "default"
    default_root.mkdir()
    write_selected_user_data_root(str(default_root), str(tmp_path / "missing-drive"))
    monkeypatch.setattr(user_data_bootstrap, "get_default_user_data_root", lambda: str(default_root))
    monkeypatch.setattr(user_data_bootstrap, "get_legacy_user_data_root", lambda: str(tmp_path / "legacy"))
    monkeypatch.setattr(
        user_data_bootstrap,
        "_ask_unavailable_root_action",
        lambda *_args: ("default", ""),
    )

    resolved = user_data_bootstrap.resolve_user_data_root_with_migration(interactive=True)

    assert resolved == str(default_root)
    assert not (default_root / "data-root.json").exists()


def test_headless_legacy_resolution_never_opens_migration_prompt(monkeypatch, tmp_path):
    from bootstrap import user_data_bootstrap

    default_root = tmp_path / "default"
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    prompt = Mock(side_effect=AssertionError("prompt must not open"))
    monkeypatch.setattr(user_data_bootstrap, "get_default_user_data_root", lambda: str(default_root))
    monkeypatch.setattr(user_data_bootstrap, "get_legacy_user_data_root", lambda: str(legacy_root))
    monkeypatch.setattr(user_data_bootstrap, "_ask_user_data_migration_choice", prompt)

    assert user_data_bootstrap.resolve_user_data_root_with_migration(interactive=False) == str(default_root)
    prompt.assert_not_called()


def test_selected_root_requires_real_write_probe_before_override(monkeypatch, tmp_path):
    from bootstrap import user_data_bootstrap

    selected = tmp_path / "selected"
    selected.mkdir()
    override = Mock()
    monkeypatch.setattr(
        user_data_bootstrap.tempfile,
        "mkstemp",
        Mock(side_effect=PermissionError("read-only")),
    )
    monkeypatch.setattr(user_data_bootstrap, "set_user_data_root_override", override)

    with pytest.raises(user_data_bootstrap.UserDataRootUnavailableError):
        user_data_bootstrap._validate_selected_root(str(selected))

    override.assert_not_called()
