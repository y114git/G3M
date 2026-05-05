"""Helpers for launching external processes safely from packaged builds."""

import os
from collections.abc import Mapping


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
