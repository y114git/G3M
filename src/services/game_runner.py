"""Headless shortcut runner - patches mods and launches the game without GUI.

Uses the canonical patching service without constructing a QApplication.
Supports multi-chapter sequential patch plans embedded in shortcut configs.
"""

import atexit
import contextlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time

from models.execution_plan import LaunchPlan
from models.game_modes import get_game
from services.game_detection_service import (
    GAME_PROCESS_EXIT_CONFIRMATION_CHECKS,
    GAME_PROCESS_POLL_SECONDS,
    GAME_PROCESS_START_TIMEOUT_SECONDS,
    GameProcessTracker,
    get_executable_name_for_game,
    get_matching_process_identities,
)
from services.plugins.shortcut_service import (
    ShortcutPluginContext,
    build_headless_plugin_runtime,
    execute_shortcut_plugin_hook,
)
from utils.native_integration import open_url_native
from utils.path_utils import (
    find_chapter_resource_dir,
    get_profile_mods_root,
    get_user_data_root,
    resolve_game_executable,
)
from utils.process_utils import (
    build_external_process_env,
    format_external_process_error,
    resolve_portproton_command,
    resolve_wine_command,
)

logger = logging.getLogger(__name__)

logger = logging.getLogger("shortcut_runner")


def _install_process_exit_logging() -> None:
    started_at = time.monotonic()

    def _log_process_exit() -> None:
        uptime = max(0.0, time.monotonic() - started_at)
        logger.info("Shortcut runner process exiting after %.2fs", uptime)
        for handler in logging.getLogger().handlers:
            with contextlib.suppress(Exception):
                handler.flush()

    atexit.register(_log_process_exit)


def _configure_logging():
    logs_dir = os.path.join(get_user_data_root(), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = logging.FileHandler(
        os.path.join(logs_dir, "shortcut.log"), mode="w", encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)
    root.addHandler(ch)
    _install_process_exit_logging()


def _load_config() -> dict:
    user_root = get_user_data_root()
    path = os.path.join(user_root, "settings", "settings.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    return {}


def _find_mod_source_dir(mod_id: str, local_config: dict) -> str | None:
    """Resolve a mod id to its root directory on disk."""
    from config.config import MOD_CONFIG_FILENAME

    mods_dir = get_profile_mods_root(local_config.get("active_profile", "Default"))
    if not os.path.isdir(mods_dir):
        return None
    for folder_name in os.listdir(mods_dir):
        folder_path = os.path.join(mods_dir, folder_name)
        if not os.path.isdir(folder_path):
            continue
        config_path = os.path.join(folder_path, MOD_CONFIG_FILENAME)
        if os.path.isfile(config_path):
            try:
                with open(config_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                if isinstance(cfg, dict):
                    from utils.mod.config_parser import normalize_mod_config_data

                    normalize_mod_config_data(cfg, mod_root_path=folder_path)
                if isinstance(cfg, dict) and cfg.get("id") == mod_id:
                    return folder_path
            except Exception as e:
                logger.debug(
                    f"_find_mod_source_dir: failed to inspect {config_path}: {e}",
                    exc_info=True,
                )

    for d in os.listdir(mods_dir):
        if d == mod_id or d.lower() == mod_id.lower():
            candidate = os.path.join(mods_dir, d)
            if os.path.isdir(candidate):
                return candidate
    return None


def _load_installed_mod(mod_id: str, local_config: dict):
    """Load one installed mod for a headless plan without constructing the GUI."""
    from models.mod_models import LocalModInfo
    from utils.mod.config_parser import normalize_mod_config_data

    mod_root = _find_mod_source_dir(mod_id, local_config)
    if not mod_root:
        return None
    config_path = os.path.join(mod_root, "mod_config.json")
    try:
        with open(config_path, encoding="utf-8") as handle:
            config_data = json.load(handle)
        if not isinstance(config_data, dict):
            return None
        normalize_mod_config_data(config_data, mod_root_path=mod_root)
        return LocalModInfo.from_dict(config_data)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as e:
        logger.error('Failed to load mod "%s": %s', mod_id, e, exc_info=True)
        return None


class _HeadlessModService:
    def __init__(self, local_config: dict) -> None:
        self._local_config = local_config

    def get_mod_folder_path(self, mod_id: str) -> str | None:
        return _find_mod_source_dir(mod_id, self._local_config)


def _execute_patch_plan(plan, game_path: str, game_mode, local_config: dict):
    """Execute a shortcut plan through the same patcher used by GUI launches."""
    from types import SimpleNamespace

    from services.g3mtool_patching_service import G3MToolPatchingService

    app_state = SimpleNamespace(
        game_mode=game_mode,
        local_config=local_config,
        config_dir=os.path.join(get_user_data_root(), "settings"),
    )
    patcher = G3MToolPatchingService(
        app_state, _HeadlessModService(local_config), None
    )
    patcher.set_override_game_path(game_path)
    patcher._session_manifest_path = os.path.join(app_state.config_dir, "session.lock")
    cache = {}

    def resolve(mod_id: str):
        if mod_id not in cache:
            cache[mod_id] = _load_installed_mod(mod_id, local_config)
        return cache[mod_id]

    if not patcher.process_patch_plan(plan, resolve, is_modpack=False):
        patcher.restore_all_backups()
        patcher.cleanup(force=True)
        return None
    return patcher


def _restore_patch_session(patcher) -> None:
    """Restore a completed/failed shortcut session exactly once."""
    if patcher is None:
        return
    logger.info("Restoring backups...")
    try:
        patcher.restore_all_backups()
        logger.info("Backups restored successfully")
    except Exception as e:
        logger.error("Failed to restore backups: %s", e, exc_info=True)
    finally:
        patcher.cleanup(force=True)


def _get_executable_path(game_mode, local_config: dict, game_path: str) -> str | None:
    custom_path = local_config.get(game_mode.get_custom_exec_config_key(), "")
    if custom_path and os.path.isfile(custom_path):
        return custom_path
    if not game_path or not os.path.isdir(game_path):
        return None
    return resolve_game_executable(game_path, game_mode.executable_type)


def _wait_for_game_exit(
    process: subprocess.Popen | None,
    process_names: tuple[str, ...],
    baseline_processes: set[tuple[int, float]],
) -> None:
    """Wait for one launched game, including wrapper and Steam process hand-offs."""
    root_pid = getattr(process, "pid", None)
    tracker = GameProcessTracker(root_pid, process_names, baseline_processes)
    startup_checks = int(
        GAME_PROCESS_START_TIMEOUT_SECONDS / GAME_PROCESS_POLL_SECONDS
    )
    for _ in range(startup_checks):
        if tracker.refresh():
            logger.info("Game process detected")
            break
        time.sleep(GAME_PROCESS_POLL_SECONDS)
    else:
        logger.warning("Game process did not appear after launch")
        return

    missing_checks = 0
    while missing_checks < GAME_PROCESS_EXIT_CONFIRMATION_CHECKS:
        if tracker.refresh():
            missing_checks = 0
        else:
            missing_checks += 1
        if missing_checks < GAME_PROCESS_EXIT_CONFIRMATION_CHECKS:
            time.sleep(GAME_PROCESS_POLL_SECONDS)


def _launch_game(
    shortcut_config: dict, game_mode, local_config: dict, game_path: str
) -> subprocess.Popen | None:
    use_steam = shortcut_config.get("launch_via_steam", False)
    direct_launch_chapter = shortcut_config.get("direct_launch_chapter", "")
    is_chapter_mode = shortcut_config.get("chapter_mode", False)
    process_names = [
        name
        for name in game_mode.get_process_names()
        if name.casefold() != "runner"
    ]
    custom_path = local_config.get(game_mode.get_custom_exec_config_key(), "")
    if custom_path:
        custom_name = os.path.basename(str(custom_path))
        custom_stem, _ = os.path.splitext(custom_name)
        process_names.extend((custom_name, custom_stem))
    process_names = tuple(name for name in dict.fromkeys(process_names) if name)
    baseline_processes = get_matching_process_identities(process_names)

    if use_steam and game_mode.steam_app_id:
        steam_url = f"steam://rungameid/{game_mode.steam_app_id}"
        system = platform.system()
        if system == "Linux":
            try:
                subprocess.Popen(["steam", steam_url])
            except FileNotFoundError:
                open_url_native(steam_url)
        else:
            open_url_native(steam_url)
        logger.info(f"Launched via Steam: {steam_url}")
        _wait_for_game_exit(None, process_names, baseline_processes)
        return None

    is_direct = (
        bool(direct_launch_chapter)
        and "_" in direct_launch_chapter
        and not direct_launch_chapter.endswith("_0")
        and is_chapter_mode
        and game_mode.direct_launch_allowed
        and platform.system() != "Darwin"
    )

    launch_target = None
    working_dir = game_path
    cleanup_info = None

    if is_direct:
        chapter_folder = find_chapter_resource_dir(game_path, direct_launch_chapter)
        source_exe = _get_executable_path(game_mode, local_config, game_path)
        if chapter_folder and source_exe:
            exe_name = (
                get_executable_name_for_game(game_mode.executable_type)
                or "DELTARUNE.exe"
            )
            target_exe = os.path.join(chapter_folder, exe_name)
            shutil.copy2(source_exe, target_exe)
            launch_target = target_exe
            working_dir = chapter_folder
            cleanup_info = {"target_exe": target_exe}
            logger.info(f"Direct launch: copied {source_exe} -> {target_exe}")
    else:
        launch_target = _get_executable_path(game_mode, local_config, game_path)

    if not launch_target:
        logger.error("No executable found for game launch")
        return None

    system = platform.system()
    command = [launch_target]
    creationflags = 0
    launch_env = build_external_process_env(system=system)

    if system == "Darwin":
        command = ["open", "-W", launch_target]
        try:
            process = subprocess.Popen(command)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            friendly_error = format_external_process_error(
                e, command=command, target_path=launch_target
            )
            logger.error("Launch failed: %s | raw=%s", friendly_error, e, exc_info=True)
            raise RuntimeError(friendly_error) from e
    else:
        if system == "Linux" and launch_target.lower().endswith(".exe"):
            use_portproton = shortcut_config.get("use_portproton", False)
            if use_portproton:
                command = [
                    resolve_portproton_command(local_config),
                    "run",
                    launch_target,
                ]
            else:
                command.insert(0, resolve_wine_command(local_config))
        if system == "Windows":
            creationflags = subprocess.DETACHED_PROCESS
        try:
            process = subprocess.Popen(
                command, cwd=working_dir, creationflags=creationflags, env=launch_env
            )
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            friendly_error = format_external_process_error(
                e, command=command, target_path=launch_target
            )
            logger.error("Launch failed: %s | raw=%s", friendly_error, e, exc_info=True)
            raise RuntimeError(friendly_error) from e

    logger.info(
        f"Game launched: {launch_target} (pid={process.pid if process else '?'})"
    )

    target_name = os.path.basename(launch_target)
    target_stem, _ = os.path.splitext(target_name)
    process_names = tuple(
        name
        for name in dict.fromkeys((*process_names, target_name, target_stem))
        if name
    )
    _wait_for_game_exit(process, process_names, baseline_processes)
    if cleanup_info:
        target_exe = cleanup_info["target_exe"]
        if os.path.exists(target_exe):
            try:
                os.remove(target_exe)
                logger.info(f"Cleaned up direct launch exe: {target_exe}")
            except Exception as e:
                logger.warning(f"Failed to clean direct launch exe: {e}")

    return process


def _parse_shortcut_arg(shortcut_arg: str) -> dict:
    """Parse the shortcut argument: base64 string, JSON file path, or inline JSON."""
    import base64

    try:
        decoded = base64.b64decode(shortcut_arg, validate=True).decode("utf-8")
        logger.info("Parsed config from base64")
        return json.loads(decoded)
    except Exception as e:
        logger.debug(
            f"_parse_shortcut_arg: base64 decode path failed for input {shortcut_arg!r}: {e}",
            exc_info=True,
        )
    if os.path.isfile(shortcut_arg):
        logger.info(f"Loading config from file: {shortcut_arg}")
        with open(shortcut_arg, encoding="utf-8") as f:
            return json.load(f)
    return json.loads(shortcut_arg)


def run_shortcut(shortcut_arg: str):
    """Main entry point for headless shortcut execution.

    Config format:
      {
        "game_id": "deltarune",
        "chapter_mode": true,
        "launch_via_steam": false,
        "use_portproton": false,
        "direct_launch_chapter": "",
        "launch_plan": {"patch_plan": {"sections": {...}}}
      }
    Legacy ``chapter_mods`` configs remain supported.
    """
    _configure_logging()
    logger.info("=== G3M Shortcut Runner ===")

    try:
        shortcut_config = _parse_shortcut_arg(shortcut_arg)
    except Exception as e:
        logger.error(f"Invalid shortcut config: {e}")
        sys.exit(1)

    try:
        launch_plan = LaunchPlan.from_shortcut_config(shortcut_config)
    except (TypeError, ValueError) as e:
        logger.error("Invalid launch plan: %s", e)
        sys.exit(1)
    game_id = launch_plan.game_id
    is_chapter_mode = launch_plan.chapter_mode

    logger.info(
        "Config: game=%s, chapter_mode=%s, patch_plan=%s",
        game_id,
        is_chapter_mode,
        launch_plan.patch_plan.to_dict()["sections"] or "vanilla",
    )

    game_mode = get_game(game_id)
    if not game_mode:
        logger.error(f"Unknown game_id: {game_id}")
        sys.exit(1)

    local_config = _load_config()
    game_path = game_mode.get_game_path(local_config)
    if not game_path or not os.path.isdir(game_path):
        logger.error(f"Game path not found: {game_path}")
        sys.exit(1)
    shortcut_plugin_context = ShortcutPluginContext.from_shortcut_config(
        shortcut_config
    )
    runtime_service = (
        build_headless_plugin_runtime(
            local_config,
            game_mode=game_mode,
            current_mode="chapter" if is_chapter_mode else "full",
        )
        if shortcut_plugin_context.enabled
        else None
    )

    if not execute_shortcut_plugin_hook(
        runtime_service,
        "before_mod_apply_shortcut",
        shortcut_plugin_context,
        shortcut_config,
    ):
        logger.warning("Shortcut launch blocked by a plugin before mod apply")
        sys.exit(1)

    patcher = None
    if launch_plan.patch_plan.sections:
        patcher = _execute_patch_plan(
            launch_plan.patch_plan, game_path, game_mode, local_config
        )
        if patcher is None:
            sys.exit(1)
        logger.info("All chapters patched successfully")

    if not execute_shortcut_plugin_hook(
        runtime_service,
        "after_mod_apply_before_launch_shortcut",
        shortcut_plugin_context,
        shortcut_config,
    ):
        logger.warning("Shortcut launch blocked by a plugin after mod apply")
        _restore_patch_session(patcher)
        sys.exit(1)

    logger.info("Launching game...")
    launch_failed = False
    try:
        _launch_game(shortcut_config, game_mode, local_config, game_path)
    except Exception as e:
        logger.error("Shortcut launch failed: %s", e, exc_info=True)
        launch_failed = True
    else:
        logger.info("Game exited")

    execute_shortcut_plugin_hook(
        runtime_service,
        "before_restore_after_exit_shortcut",
        shortcut_plugin_context,
        shortcut_config,
    )
    _restore_patch_session(patcher)

    execute_shortcut_plugin_hook(
        runtime_service,
        "after_restore_after_exit_shortcut",
        shortcut_plugin_context,
        shortcut_config,
    )

    if launch_failed:
        sys.exit(1)

    logger.info("=== Shortcut Runner finished ===")
