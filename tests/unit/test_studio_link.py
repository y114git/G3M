from unittest.mock import patch

import pytest

from ui import studio_link


def test_link_is_the_scheme_plus_the_file_uri(tmp_path):
    data = tmp_path / "my, data.win"
    data.write_bytes(b"x")
    link = studio_link.studio_link(str(data))
    assert link.startswith("g3mstudio://file:///")
    assert link.endswith("my%2C%20data.win")


@pytest.mark.parametrize(
    ("name", "expected"),
    [("data.win", True), ("DATA.DROID", True), ("a.ios", True), ("a.unx", True), ("a.txt", False)],
)
def test_only_existing_data_files_get_the_button(tmp_path, name, expected):
    (tmp_path / name).write_bytes(b"x")
    assert studio_link.is_data_file(str(tmp_path / name)) is expected
    assert studio_link.is_data_file(str(tmp_path / "missing.win")) is False


def test_missing_handler_warns_and_does_not_open(tmp_path):
    data = tmp_path / "data.win"
    data.write_bytes(b"x")
    with (
        patch.object(studio_link, "_scheme_registered", return_value=False),
        patch.object(studio_link, "open_url_native") as open_url,
        patch.object(studio_link, "_warn") as warn,
    ):
        assert studio_link.open_in_studio(str(data)) is False
    open_url.assert_not_called()
    warn.assert_called_once()


def test_registered_handler_opens_the_link(tmp_path):
    data = tmp_path / "data.win"
    data.write_bytes(b"x")
    with (
        patch.object(studio_link, "_scheme_registered", return_value=True),
        patch.object(studio_link, "open_url_native", return_value=True) as open_url,
        patch.object(studio_link, "_warn") as warn,
    ):
        assert studio_link.open_in_studio(str(data)) is True
    open_url.assert_called_once()
    warn.assert_not_called()
