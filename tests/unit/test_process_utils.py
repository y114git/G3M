import requests

from services.localization_service import tr
from utils.process_utils import (
    build_external_process_env,
    format_filesystem_error,
    format_network_error,
    format_plugin_error,
    resolve_portproton_command,
)


def test_build_external_process_env_restores_ld_library_path_from_orig():
    env = {
        "LD_LIBRARY_PATH": "/bundle/lib",
        "LD_LIBRARY_PATH_ORIG": "/usr/lib:/usr/local/lib",
        "PATH": "/usr/bin",
    }

    result = build_external_process_env(system="Linux", base_env=env)

    assert result is not None
    assert result["LD_LIBRARY_PATH"] == "/usr/lib:/usr/local/lib"
    assert result["LD_LIBRARY_PATH_ORIG"] == "/usr/lib:/usr/local/lib"
    assert result["PATH"] == "/usr/bin"


def test_build_external_process_env_removes_ld_library_path_when_orig_missing():
    env = {
        "LD_LIBRARY_PATH": "/bundle/lib",
        "PATH": "/usr/bin",
    }

    result = build_external_process_env(system="Linux", base_env=env)

    assert result is not None
    assert "LD_LIBRARY_PATH" not in result
    assert result["PATH"] == "/usr/bin"


def test_build_external_process_env_returns_none_outside_linux():
    env = {"LD_LIBRARY_PATH": "/bundle/lib"}

    result = build_external_process_env(system="Windows", base_env=env)

    assert result is None


def test_format_filesystem_error_reports_permission_denied():
    error = PermissionError(13, "Permission denied", "C:/mods/protected")

    assert (
        format_filesystem_error(error)
        == tr("errors.permission_denied", path="C:/mods/protected")
    )


def test_format_filesystem_error_reports_missing_file():
    error = FileNotFoundError(2, "No such file", "C:/mods/missing")

    assert (
        format_filesystem_error(error)
        == tr("errors.file_not_found", path="C:/mods/missing")
    )


def test_format_filesystem_error_falls_back_to_generic_message():
    error = OSError("Disk full")

    assert format_filesystem_error(error) == tr(
        "errors.file_operation_failed", error="Disk full"
    )


def test_format_network_error_reports_timeout():
    assert format_network_error(requests.exceptions.Timeout("boom")) == tr(
        "errors.network_timeout"
    )


def test_format_network_error_reports_http_404():
    response = requests.Response()
    response.status_code = 404
    error = requests.exceptions.HTTPError(response=response)

    assert format_network_error(error) == tr("errors.network_http_404")


def test_format_network_error_reports_dns_error():
    error = requests.exceptions.ConnectionError("NameResolutionError")

    assert format_network_error(error) == tr("errors.network_dns_error")


def test_format_plugin_error_reports_missing_entry():
    assert format_plugin_error(
        "missing_entry", plugin_id="sigma", details="C:/plugins/sigma/plugin.py"
    ) == tr("plugins.error_missing_entry", path="C:/plugins/sigma/plugin.py")


def test_format_plugin_error_reports_generic_runtime_failure():
    assert format_plugin_error("boom", plugin_id="sigma") == tr(
        "plugins.error_runtime_failed", plugin="sigma", error="boom"
    )


def test_resolve_portproton_command_falls_back_when_configured_value_is_whitespace():
    assert (
        resolve_portproton_command(
            {
                "custom_portproton_path": "   ",
                "portproton_path": "   ",
            }
        )
        == "portproton"
    )
