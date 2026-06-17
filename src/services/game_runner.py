"""Headless shortcut runner - patches mods and launches the game without GUI.

Uses G3MToolManager and BackupManager directly (plain classes) so no
QApplication is needed. Supports multi-chapter mod selections via the
``chapter_mods`` dict embedded in the shortcut config.
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
import tempfile
import time

from models.game_modes import get_game
from services.game_detection_service import (
    get_executable_name_for_game,
    is_game_running,
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


def _resolve_chapter_source_dir(mod_source_dir: str, chapter_id: str) -> str | None:
    """Given a mod's root directory, find the subfolder for a specific chapter."""
    if not mod_source_dir or not os.path.isdir(mod_source_dir):
        return None
    from utils.file_utils import get_chapter_folder_name

    for subdir in (get_chapter_folder_name(chapter_id), "universal"):
        candidate = os.path.join(mod_source_dir, subdir)
        if os.path.isdir(candidate):
            return candidate
    return mod_source_dir


def _load_chapter_config_entry(mod_root_dir: str, chapter_id: str) -> dict:
    config_path = os.path.join(mod_root_dir, "mod_config.json")
    if not os.path.isfile(config_path):
        return {}
    try:
        with open(config_path, encoding="utf-8") as handle:
            config_data = json.load(handle)
        from utils.mod.config_parser import normalize_mod_config_data

        normalize_mod_config_data(config_data, mod_root_path=mod_root_dir)
        files_data = config_data.get("files", {})
        chapter_info = files_data.get(chapter_id)
        return chapter_info if isinstance(chapter_info, dict) else {}
    except Exception as e:
        logger.debug(
            "_load_chapter_config_entry: failed to inspect %s: %s",
            config_path,
            e,
            exc_info=True,
        )
        return {}


def _classify_mod(mod_source_dir: str):
    """Classify a mod chapter dir and return (patch_file, mod_type)."""
    from utils.patching import mod_content_utils as mod_content

    if not os.path.isdir(mod_source_dir):
        return (None, "overrides_only")
    g3m_patches = mod_content.find_g3m_patches(mod_source_dir)
    if g3m_patches:
        return (g3m_patches[0], "g3mpatch")
    for f in os.listdir(mod_source_dir):
        fl = f.lower()
        if fl.endswith((".xdelta", ".vcdiff")):
            return (os.path.join(mod_source_dir, f), "xdelta")
    csx_scripts = mod_content.find_csx_scripts(mod_source_dir)
    if csx_scripts:
        return (csx_scripts[0], "csx")
    ready_files = mod_content.find_ready_data_win_files(mod_source_dir)
    if ready_files:
        return (ready_files[0], "datafile")
    return (None, "overrides_only")


def _apply_file_overrides(
    mod_root_dir: str,
    mod_source_dir: str,
    target_dir: str,
    backup_mgr,
    chapter_id: str,
    g3mtool,
):
    """Copy non-patch files from mod source into game target, with backup."""
    from utils.patching.file_override_utils import apply_file_overrides

    if not os.path.isdir(mod_source_dir):
        return

    class _ShortcutPatcher:
        def __init__(self) -> None:
            self.xdelta_modpack = False
            self.patching_logger = logger

        def _backup_or_mark_file(self, chapter_key, target_file: str) -> None:
            if os.path.exists(target_file):
                backup_mgr.backup_file(chapter_key, target_file)
            else:
                backup_mgr.mark_file_added(chapter_key, target_file)

        def _apply_xdelta_to_file(self, target_file: str, patch_path: str) -> bool:
            temp_out = target_file + ".tmp"
            returncode, _stdout, _stderr = g3mtool.xpatch_apply(
                target_file, patch_path, temp_out
            )
            if returncode == 0 and os.path.exists(temp_out):
                shutil.move(temp_out, target_file)
                return True
            if os.path.exists(temp_out):
                os.remove(temp_out)
            return False

        def _request_warning(
            self,
            message_text: str,
            details_text: str = "",
            report_path: str | None = None,
        ):
            del message_text, details_text, report_path
            return True

    chapter_info = _load_chapter_config_entry(mod_root_dir, chapter_id)
    configured_paths = (
        chapter_info.get("extra_files", []) if isinstance(chapter_info, dict) else None
    )
    apply_file_overrides(
        _ShortcutPatcher(),
        mod_source_dir,
        target_dir,
        set(),
        False,
        chapter_id,
        mod_name=os.path.basename(mod_root_dir),
        game_id="deltarune",
        configured_paths=configured_paths,
        mod_root_dir=mod_root_dir,
    )


def _patch_chapter(
    chapter_id: str,
    mod_root_dir: str,
    mod_source_dir: str,
    game_path: str,
    game_mode,
    g3mtool,
    backup_mgr,
    temp_dir: str,
) -> bool:
    """Patch a single chapter: backup data.win, apply patch, copy overrides."""
    from utils.patching import mod_content_utils as mod_content

    target_dir = find_chapter_resource_dir(game_path, chapter_id)
    if not target_dir or not os.path.isdir(target_dir):
        logger.error(f"Target directory not found for chapter {chapter_id}")
        return False

    data_win_path = mod_content.find_data_win(target_dir, game_id=game_mode.game_id)
    patch_file, mod_type = _classify_mod(mod_source_dir)

    if mod_type == "overrides_only" or not data_win_path:
        if data_win_path and not patch_file:
            logger.info(f"Chapter {chapter_id}: overrides only (no patch file)")
        elif not data_win_path:
            logger.warning(
                f"Chapter {chapter_id}: no data.win found, applying overrides only"
            )
        _apply_file_overrides(
            mod_root_dir, mod_source_dir, target_dir, backup_mgr, chapter_id, g3mtool
        )
        return True

    if not backup_mgr.backup_file(chapter_id, data_win_path):
        logger.error(f"CRITICAL: Failed to backup {data_win_path}")
        return False

    logs_dir = os.path.join(get_user_data_root(), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, "g3mtool.log")
    temp_output = os.path.join(
        temp_dir, f"output_{chapter_id}_{os.path.basename(data_win_path)}"
    )

    success = False
    if mod_type == "g3mpatch":
        logger.info(f"Applying g3mpatch: {patch_file}")
        returncode, stdout, stderr = g3mtool.apply_patch(
            data_win_path, patch_file, temp_output, log_path=log_path
        )
        if returncode != 0:
            logger.error(f"G3MTool patch apply failed: {(stderr or stdout)[:500]}")
            return False
        success = True
    elif mod_type == "xdelta":
        logger.info(f"Applying xdelta patch: {patch_file}")
        returncode, stdout, stderr = g3mtool.xpatch_apply(
            data_win_path, patch_file, temp_output
        )
        if returncode != 0:
            logger.error(f"xpatch apply failed: {(stderr or stdout)[:500]}")
            return False
        success = True
    elif mod_type == "datafile":
        logger.info(f"Copying replacement data file: {patch_file}")
        try:
            shutil.copy2(patch_file, temp_output)
            success = True
        except Exception as e:
            logger.error(f"Failed to copy data file: {e}")
            return False
    elif mod_type == "csx":
        logger.info(f"Executing csx script: {patch_file}")
        returncode, stdout, stderr = g3mtool.execute(
            patch_file,
            data_file=data_win_path,
            output_path=temp_output,
        )
        if returncode != 0:
            logger.error(f"g3mtool execute failed: {(stderr or stdout)[:500]}")
            return False
        success = os.path.exists(temp_output)
        if not success:
            logger.error(f"CSX script produced no output file: {temp_output}")
            return False

    if success:
        try:
            shutil.move(temp_output, data_win_path)
            logger.info(f"Patched data.win placed at {data_win_path}")
        except Exception as e:
            logger.error(f"Failed to move patched file: {e}")
            return False

    _apply_file_overrides(
        mod_root_dir, mod_source_dir, target_dir, backup_mgr, chapter_id, g3mtool
    )
    return True


def _patch_all_chapters(
    chapter_mods: dict[str, str],
    game_path: str,
    game_mode,
    local_config: dict,
) -> object | None:
    """Patch all chapters and return the BackupManager for later restore.

    ``chapter_mods`` maps chapter_id -> mod_id.
    Returns None on failure (backups already restored).
    """
    from adapters.g3mtool_adapter import G3MToolManager
    from services.backup_service import BackupManager

    g3mtool = G3MToolManager()
    if not g3mtool.is_available():
        logger.error("G3MTool not available")
        return None

    backup_dir = os.path.join(get_user_data_root(), "patching_backups")
    backup_mgr = BackupManager(backup_dir, patching_logger=logger)
    manifest_path = os.path.join(get_user_data_root(), "settings", "session.lock")
    temp_dir = tempfile.mkdtemp(prefix="g3m_shortcut_patch_")

    try:
        for chapter_id, mod_id in sorted(chapter_mods.items()):
            if not mod_id:
                continue

            mod_source_dir = _find_mod_source_dir(mod_id, local_config)
            if not mod_source_dir:
                logger.error(f'Mod "{mod_id}" not found on disk')
                _restore_and_cleanup(backup_mgr, chapter_mods, temp_dir, manifest_path)
                return None

            chapter_source_dir = _resolve_chapter_source_dir(mod_source_dir, chapter_id)
            if not chapter_source_dir:
                logger.error(f"No chapter data for {chapter_id} in {mod_source_dir}")
                _restore_and_cleanup(backup_mgr, chapter_mods, temp_dir, manifest_path)
                return None

            logger.info(
                f'Patching chapter {chapter_id} with mod "{mod_id}" from {chapter_source_dir}'
            )

            ok = _patch_chapter(
                chapter_id,
                mod_source_dir,
                chapter_source_dir,
                game_path,
                game_mode,
                g3mtool,
                backup_mgr,
                temp_dir,
            )
            if not ok:
                logger.error(f"Patching failed for chapter {chapter_id}")
                _restore_and_cleanup(backup_mgr, chapter_mods, temp_dir, manifest_path)
                return None

            backup_mgr.save_backups_to_manifest(manifest_path)

        return backup_mgr
    except Exception as e:
        logger.error(f"Patching failed: {e}", exc_info=True)
        _restore_and_cleanup(backup_mgr, chapter_mods, temp_dir, manifest_path)
        return None
    finally:
        if os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def _restore_and_cleanup(backup_mgr, chapter_mods, temp_dir, manifest_path):
    """Restore all backups and clean up temp files after a failure."""
    try:
        backup_mgr.restore_all_backups()
        backup_mgr.clear_backup_dir()
    except Exception as e:
        logger.error(f"Failed to restore backups: {e}", exc_info=True)
    if os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


def _get_executable_path(game_mode, local_config: dict, game_path: str) -> str | None:
    custom_path = local_config.get(game_mode.get_custom_exec_config_key(), "")
    if custom_path and os.path.isfile(custom_path):
        return custom_path
    if not game_path or not os.path.isdir(game_path):
        return None
    return resolve_game_executable(game_path, game_mode.executable_type)


def _wait_for_game_exit(
    process: subprocess.Popen | None = None, wait_for_start: bool = False
):
    """Wait for the game process to finish."""
    if process:
        process.wait()
    if wait_for_start:
        logger.info("Waiting for game process to appear...")
        for _ in range(30):
            if is_game_running():
                logger.info("Game process detected")
                break
            time.sleep(2)
    while is_game_running():
        time.sleep(2)


def _launch_game(
    shortcut_config: dict, game_mode, local_config: dict, game_path: str
) -> subprocess.Popen | None:
    use_steam = shortcut_config.get("launch_via_steam", False)
    direct_launch_chapter = shortcut_config.get("direct_launch_chapter", "")
    is_chapter_mode = shortcut_config.get("chapter_mode", False)

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
        _wait_for_game_exit(wait_for_start=True)
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

    _wait_for_game_exit(process)
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
        "chapter_mods": {"deltarune_0": "mod_id_1", "deltarune_2": "mod_id_2", ...}
      }
    Chapters with null/empty values are vanilla (no patching).
    """
    _configure_logging()
    logger.info("=== G3M Shortcut Runner ===")

    try:
        shortcut_config = _parse_shortcut_arg(shortcut_arg)
    except Exception as e:
        logger.error(f"Invalid shortcut config: {e}")
        sys.exit(1)

    game_id = shortcut_config.get("game_id", "deltarune")
    chapter_mods_raw = shortcut_config.get("chapter_mods", {})
    is_chapter_mode = shortcut_config.get("chapter_mode", False)

    chapter_mods = {cid: mk for cid, mk in chapter_mods_raw.items() if mk}

    logger.info(
        f"Config: game={game_id}, chapter_mode={is_chapter_mode}, chapter_mods={chapter_mods or 'vanilla'}"
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

    backup_mgr = None
    if chapter_mods:
        backup_mgr = _patch_all_chapters(
            chapter_mods, game_path, game_mode, local_config
        )
        if backup_mgr is None:
            sys.exit(1)
        logger.info("All chapters patched successfully")

    if not execute_shortcut_plugin_hook(
        runtime_service,
        "after_mod_apply_before_launch_shortcut",
        shortcut_plugin_context,
        shortcut_config,
    ):
        logger.warning("Shortcut launch blocked by a plugin after mod apply")
        if backup_mgr:
            backup_mgr.restore_all_backups()
            backup_mgr.clear_backup_dir()
        sys.exit(1)

    logger.info("Launching game...")
    try:
        _launch_game(shortcut_config, game_mode, local_config, game_path)
    except Exception as e:
        logger.error("Shortcut launch failed: %s", e, exc_info=True)
        sys.exit(1)

    logger.info("Game exited")

    execute_shortcut_plugin_hook(
        runtime_service,
        "before_restore_after_exit_shortcut",
        shortcut_plugin_context,
        shortcut_config,
    )
    if backup_mgr:
        logger.info("Restoring backups...")
        try:
            backup_mgr.restore_all_backups()
            backup_mgr.clear_backup_dir()
            logger.info("Backups restored successfully")
        except Exception as e:
            logger.error(f"Failed to restore backups: {e}", exc_info=True)

    execute_shortcut_plugin_hook(
        runtime_service,
        "after_restore_after_exit_shortcut",
        shortcut_plugin_context,
        shortcut_config,
    )

    logger.info("=== Shortcut Runner finished ===")
