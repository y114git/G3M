"""Helpers for launching external processes safely from packaged builds."""

import errno
import os
import shutil
from collections.abc import Mapping

from services.localization_service import tr


def build_external_process_env(
    *, system: str, base_env: Mapping[str, str] | None = None
) -> dict[str, str] | None:
    """Sanitize inherited env for system processes launched from frozen Linux apps.

    PyInstaller adjusts ``LD_LIBRARY_PATH`` so the bundled app prefers its own shared
    libraries. External programs such as Wine should not inherit that modified search
    path, or they may load incompatible Qt/OpenGL/Vulkan libraries from the bundle.
    """

    if system != "Linux":
        return None

    env = dict(os.environ if base_env is None else base_env)
    original_ld_library_path = env.get("LD_LIBRARY_PATH_ORIG")
    if original_ld_library_path is not None:
        env["LD_LIBRARY_PATH"] = original_ld_library_path
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


def resolve_wine_command(local_config: Mapping[str, str] | None = None) -> str:
    """Resolve the Wine executable name/path for Linux launches."""

    config = local_config or {}
    custom_wine_path = str(config.get("custom_wine_path", "") or "").strip()
    if custom_wine_path:
        return custom_wine_path
    if shutil.which("wine"):
        return "wine"
    if shutil.which("wine64"):
        return "wine64"
    return "wine"


def resolve_portproton_command(local_config: Mapping[str, str] | None = None) -> str:
    """Resolve the PortProton executable name/path for Linux launches."""

    config = local_config or {}
    candidate = str(
        config.get("custom_portproton_path") or config.get("portproton_path") or ""
    ).strip()
    return candidate or "portproton"


def is_path_like_command(command_name: str) -> bool:
    return bool(command_name) and (
        os.path.isabs(command_name) or "/" in command_name or "\\" in command_name
    )


def format_external_process_error(
    process_error: Exception,
    *,
    command: list[str] | None = None,
    target_path: str = "",
) -> str:
    command = command or []
    command_name = str(command[0]) if command else ""
    base_name = os.path.basename(command_name).lower()
    error_path = str(getattr(process_error, "filename", "") or "")
    error_errno = getattr(process_error, "errno", None)
    error_text = str(process_error).lower()

    if isinstance(process_error, IsADirectoryError) or error_errno == errno.EISDIR:
        return tr(
            "errors.launch_target_is_directory",
            path=error_path or target_path or command_name,
        )

    if isinstance(process_error, FileNotFoundError) or error_errno == errno.ENOENT:
        if "g3mtool" in base_name:
            if is_path_like_command(command_name):
                return tr("errors.custom_g3mtool_not_found", path=command_name)
            return tr("errors.g3mtool_command_not_found")
        if "portproton" in base_name:
            if is_path_like_command(command_name):
                return tr("errors.custom_portproton_not_found", path=command_name)
            return tr("errors.portproton_not_found")
        if base_name.startswith("wine"):
            if is_path_like_command(command_name):
                return tr("errors.custom_wine_not_found", path=command_name)
            return tr("errors.wine_not_found")
        if error_path and target_path and os.path.abspath(error_path) == os.path.abspath(target_path):
            return tr("errors.launch_target_missing", path=target_path)
        if error_path and command_name and error_path == command_name:
            if is_path_like_command(command_name):
                return tr("errors.launch_command_missing_path", path=command_name)
            return tr("errors.launch_command_not_found", command=command_name)
        if command_name:
            if is_path_like_command(command_name):
                return tr("errors.launch_command_missing_path", path=command_name)
            return tr("errors.launch_command_not_found", command=command_name)
        return tr("errors.launch_target_missing", path=target_path)

    if isinstance(process_error, PermissionError) or error_errno in (
        errno.EACCES,
        errno.EPERM,
    ):
        if "g3mtool" in base_name:
            return tr(
                "errors.g3mtool_permission_denied",
                path=error_path or command_name or target_path,
            )
        return tr(
            "errors.launch_permission_denied",
            path=error_path or target_path or command_name,
        )

    invalid_exe_keywords = [
        "not a valid",
        "invalid",
        "cannot execute",
        "exec format error",
        "bad executable",
        "invalid executable",
    ]
    if error_errno == errno.ENOEXEC or any(
        keyword in error_text for keyword in invalid_exe_keywords
    ):
        if "g3mtool" in base_name:
            return tr(
                "errors.g3mtool_invalid_executable",
                path=command_name or error_path,
            )
        return tr(
            "errors.invalid_executable_file",
            file=os.path.basename(target_path or command_name),
        )

    return tr("errors.game_launch_error", error=str(process_error))


def format_filesystem_error(error: Exception, *, path: str = "") -> str:
    error_path = str(getattr(error, "filename", "") or path or "?")
    if isinstance(error, PermissionError):
        return tr("errors.permission_denied", path=error_path)
    if isinstance(error, FileNotFoundError):
        return tr("errors.file_not_found", path=error_path)
    return tr("errors.file_operation_failed", error=str(error))


def format_network_error(error: Exception, *, url: str = "") -> str:
    try:
        import requests
    except Exception:
        requests = None

    error_text = str(error)
    lowered = error_text.lower()
    if requests is not None:
        if isinstance(error, requests.exceptions.Timeout):
            return tr("errors.network_timeout")
        if isinstance(error, requests.exceptions.SSLError):
            return tr("errors.network_ssl_error")
        if isinstance(error, requests.exceptions.HTTPError):
            response = getattr(error, "response", None)
            status_code = int(getattr(response, "status_code", 0) or 0)
            if status_code == 403:
                return tr("errors.network_http_403")
            if status_code == 404:
                return tr("errors.network_http_404")
            if status_code == 429:
                return tr("errors.network_http_429")
            if 500 <= status_code <= 599:
                return tr("errors.network_http_5xx", status_code=status_code)
            if status_code:
                return tr("errors.network_http_error", status_code=status_code)
        if isinstance(error, requests.exceptions.ConnectionError):
            if (
                "name resolution" in lowered
                or "nameresolutionerror" in lowered
                or "getaddrinfo" in lowered
            ):
                return tr("errors.network_dns_error")
            if "connection refused" in lowered:
                return tr("errors.network_connection_refused")
            return tr("errors.network_connection_error")
        if isinstance(error, requests.exceptions.RequestException):
            return tr("errors.network_request_failed", error=error_text)

    if isinstance(error, OSError) and "connection dropped during download" in lowered:
        return tr("errors.network_connection_interrupted")
    return tr("errors.network_request_failed", error=error_text or url or "unknown error")


def format_plugin_error(
    error: Exception | str,
    *,
    plugin_id: str = "",
    details: str = "",
) -> str:
    error_code = str(error or "").strip()
    plugin_label = plugin_id or "plugin"
    plugin_path = details or plugin_label
    error_map = {
        "plugin_not_available": tr("plugins.error_not_available", plugin=plugin_label),
        "missing_manifest": tr("plugins.error_missing_manifest", plugin=plugin_label),
        "invalid_config_version": tr("plugins.error_invalid_manifest", plugin=plugin_label),
        "invalid_id": tr("plugins.error_invalid_manifest", plugin=plugin_label),
        "invalid_version": tr("plugins.error_invalid_manifest", plugin=plugin_label),
        "invalid_api_version": tr("plugins.error_invalid_manifest", plugin=plugin_label),
        "invalid_tags": tr("plugins.error_invalid_manifest", plugin=plugin_label),
        "invalid_hooks": tr("plugins.error_invalid_manifest", plugin=plugin_label),
        "invalid_relations": tr("plugins.error_invalid_manifest", plugin=plugin_label),
        "missing_id": tr("plugins.error_invalid_manifest", plugin=plugin_label),
        "missing_name": tr("plugins.error_invalid_manifest", plugin=plugin_label),
        "missing_description": tr("plugins.error_invalid_manifest", plugin=plugin_label),
        "missing_author": tr("plugins.error_invalid_manifest", plugin=plugin_label),
        "missing_version": tr("plugins.error_invalid_manifest", plugin=plugin_label),
        "missing_api_version": tr("plugins.error_invalid_manifest", plugin=plugin_label),
        "missing_entry": tr("plugins.error_missing_entry", path=plugin_path),
        "missing_icon": tr("plugins.error_missing_icon", path=plugin_path),
        "path_traversal": tr("plugins.error_unsafe_path", plugin=plugin_label),
        "invalid_entry_spec": tr("plugins.error_invalid_entry", plugin=plugin_label),
        "missing_factory": tr("plugins.error_missing_factory", plugin=plugin_label),
        "archive_too_many_files": tr("plugins.error_archive_invalid", plugin=plugin_label),
        "archive_too_large": tr("plugins.error_archive_invalid", plugin=plugin_label),
        "plugin_not_found": tr("plugins.error_not_found", plugin=plugin_label),
        "plugin_incompatible": tr("plugins.error_incompatible_api", plugin=plugin_label),
        "missing_dependencies": tr("plugins.error_missing_dependencies", plugin=plugin_label),
        "conflicts_present": tr("plugins.error_conflicts_present", plugin=plugin_label),
    }
    if error_code in error_map:
        return error_map[error_code]
    if isinstance(error, FileNotFoundError):
        return tr("plugins.error_file_not_found", path=getattr(error, "filename", "") or plugin_path)
    if isinstance(error, PermissionError):
        return tr("plugins.error_permission_denied", path=getattr(error, "filename", "") or plugin_path)
    return tr("plugins.error_runtime_failed", plugin=plugin_label, error=error_code or details or "unknown error")
