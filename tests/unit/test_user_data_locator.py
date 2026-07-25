import json
import os

import pytest

from bootstrap.user_data_locator import (
    UserDataLocatorError,
    clear_selected_user_data_root,
    get_locator_path,
    read_selected_user_data_root,
    write_selected_user_data_root,
)


def test_missing_locator_uses_no_custom_root(tmp_path):
    assert read_selected_user_data_root(str(tmp_path / "default")) is None


def test_locator_round_trip_uses_selected_directory_directly(tmp_path):
    default_root = tmp_path / "default"
    selected_root = tmp_path / "external" / "My Library"

    write_selected_user_data_root(str(default_root), str(selected_root))

    assert read_selected_user_data_root(str(default_root)) == os.path.normpath(
        os.path.abspath(selected_root)
    )
    payload = json.loads(get_locator_path(str(default_root)).read_text(encoding="utf-8"))
    assert payload == {"version": 1, "path": os.path.normpath(os.path.abspath(selected_root))}


@pytest.mark.parametrize(
    "payload",
    ["not json", "{}", '{"version": 2, "path": "X:/data"}', '{"version": 1, "path": ""}'],
)
def test_malformed_locator_raises_actionable_error(tmp_path, payload):
    default_root = tmp_path / "default"
    default_root.mkdir()
    get_locator_path(str(default_root)).write_text(payload, encoding="utf-8")

    with pytest.raises(UserDataLocatorError, match="data location"):
        read_selected_user_data_root(str(default_root))


def test_writing_default_root_removes_locator(tmp_path):
    default_root = tmp_path / "default"
    write_selected_user_data_root(str(default_root), str(tmp_path / "custom"))

    write_selected_user_data_root(str(default_root), str(default_root))

    assert not get_locator_path(str(default_root)).exists()
    assert read_selected_user_data_root(str(default_root)) is None


def test_clear_locator_is_idempotent(tmp_path):
    default_root = tmp_path / "default"
    write_selected_user_data_root(str(default_root), str(tmp_path / "custom"))

    clear_selected_user_data_root(str(default_root))
    clear_selected_user_data_root(str(default_root))

    assert not get_locator_path(str(default_root)).exists()
