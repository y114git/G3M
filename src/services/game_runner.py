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
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace

from models.game_modes import get_game
from services.background_operations import background_operations
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
from utils.log_format import ConciseFormatter
from utils.mod.archive import ArchiveVirtualPath
from utils.native_integration import open_url_native
from utils.path_utils import (
    find_chapter_resource_dir,
    get_profile_mods_root,
    get_user_data_root,
    resolve_execution_runtime,
    resolve_game_executable,
    safe_profile_name,
)
from utils.process_utils import (
    build_external_process_env,
    format_external_process_error,
    resolve_portproton_command,
    resolve_wine_command,
)

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
    fmt = ConciseFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
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
    from utils.mod.config import load_mod_config

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
                if load_mod_config(config_path).get("id") == mod_id:
                    return folder_path
            except (OSError, ValueError) as error:
                logger.debug(
                    "_find_mod_source_dir: failed to inspect %s: %s", config_path, error,
                    exc_info=True,
                )
    return None


def _execute_operation_plan(
    mod_ids: tuple[str, ...],
    game_path: str,
    game_mode,
    local_config: dict,
    *,
    merge_steps: Sequence[Sequence[str]] = (),
    legacy_sections: Mapping[str, Sequence[str]] | None = None,
):
    """Execute a shortcut plan through strict current configs only."""
    from services.mod_operation_executor import (
        ModOperationExecutor,
        ModOperationJournal,
    )
    from services.mod_operation_support import (
        create_g3mtool_merger,
        create_g3mtool_patcher,
        direct_operation_paths_preapproved,
        format_direct_operation_plan_paths,
    )
    from utils.mod.config import load_mod_config
    from utils.mod.operation_plan import ModPathContext, build_profile_operation_plan

    journal_root = Path(get_user_data_root()) / "settings" / "operation-shortcut-session"
    if not _recover_shortcut_operation_session(journal_root, ModOperationJournal):
        return None
    ordered_ids = tuple(dict.fromkeys(mod_ids))
    configs: dict[str, dict[str, object]] = {}
    contexts: dict[str, ModPathContext] = {}
    execution_runtime = resolve_execution_runtime(
        _get_executable_path(game_mode, local_config, game_path), platform.system()
    )
    for mod_id in ordered_ids:
        mod_root = _find_mod_source_dir(mod_id, local_config)
        if not mod_root:
            logger.error('Current config for shortcut mod "%s" was not found', mod_id)
            return None
        config_path = os.path.join(mod_root, "mod_config.json")
        try:
            configs[mod_id] = load_mod_config(config_path)
        except (OSError, ValueError) as error:
            logger.error('Invalid current shortcut mod "%s": %s', mod_id, error)
            return None
        contexts[mod_id] = ModPathContext.create(
            mod_path=mod_root,
            game_path=game_path,
            game_data_path=game_mode.get_data_path(local_config),
            user_path=Path.home(),
            runtime=execution_runtime,
        )
    operation_plan = build_profile_operation_plan(
        configs, contexts, ordered_ids, merge_steps=merge_steps
    )
    if legacy_sections:
        operation_plan = _filter_legacy_shortcut_operations(
            operation_plan, legacy_sections, game_mode.game_id, Path(game_path)
        )
    if operation_plan.has_errors:
        logger.error("Invalid operation shortcut operation: %s", operation_plan.findings[0].message)
        return None
    direct_path_details = format_direct_operation_plan_paths(operation_plan)
    if direct_path_details and not direct_operation_paths_preapproved(local_config):
        logger.error(
            "Shortcut operation uses direct absolute paths and requires confirmation in G3M:\n%s\n"
            "Open G3M, review the mod paths, then disable only this warning if you want "
            "future shortcuts to use these paths without a prompt.",
            direct_path_details,
        )
        return None
    patcher: Callable[[Path, Path, Path], bool] | None = None
    if any(operation.type == "patch" for operation in operation_plan.operations):
        patcher = create_g3mtool_patcher()
    merger = create_g3mtool_merger(SimpleNamespace(local_config=local_config))
    try:
        return ModOperationExecutor(
            journal_root, patcher=patcher, merger=merger
        ).execute(operation_plan)
    except Exception as error:
        logger.error("shortcut operation execution failed: %s", error, exc_info=True)
        return None


def _filter_legacy_shortcut_operations(
    operation_plan,
    legacy_sections: Mapping[str, Sequence[str]],
    game_id: str,
    game_path: Path,
):
    """Keep legacy chapter shortcut selections scoped to their selected targets."""
    if game_id != "deltarune":
        return operation_plan
    selected_by_mod: dict[str, set[str]] = {}
    for section_id, mod_ids in legacy_sections.items():
        section = _canonical_legacy_section(section_id)
        if section is None:
            continue
        for mod_id in mod_ids:
            selected_by_mod.setdefault(mod_id, set()).add(section)
    if not selected_by_mod:
        return operation_plan
    operations = [
        operation
        for operation in operation_plan.operations
        if _legacy_operation_is_selected(operation, selected_by_mod, game_path)
    ]
    excluded_indices = {operation.index for operation in operation_plan.operations} - {
        operation.index for operation in operations
    }
    findings = tuple(
        finding for finding in operation_plan.findings
        if finding.operation_index not in excluded_indices
    )
    return type(operation_plan)(tuple(operations), findings)


def _canonical_legacy_section(section_id: str) -> str | None:
    if section_id.startswith("chapter_") and section_id[8:].isdecimal():
        return f"deltarune_{section_id[8:]}"
    if re.fullmatch(r"deltarune_\d+", section_id):
        return section_id
    return None


def _legacy_operation_is_selected(operation, selected_by_mod: Mapping[str, set[str]], game_path: Path) -> bool:
    selected_sections = selected_by_mod.get(operation.mod_id or "")
    target = operation.target
    if not selected_sections or not isinstance(target, (Path, ArchiveVirtualPath)):
        return True
    target_path = target.archive if isinstance(target, ArchiveVirtualPath) else target
    try:
        relative = target_path.relative_to(game_path)
    except ValueError:
        return True
    section = "deltarune_0"
    target_parts = relative.parts
    if isinstance(target, ArchiveVirtualPath):
        target_parts += tuple(part for part in target.member.split("/") if part)
    for part in target_parts:
        match = re.fullmatch(r"chapter(\d+)_(?:windows|mac)", part, re.IGNORECASE)
        if match:
            section = f"deltarune_{match.group(1)}"
            break
    return section in selected_sections


def _recover_shortcut_operation_session(journal_root: Path, journal_type) -> bool:
    """Recover an interrupted shortcut before starting a replacement session."""
    if not (journal_root / "manifest.json").is_file():
        return True
    try:
        journal = journal_type.load(journal_root)
        if journal.state not in {"restored", "retired"}:
            journal.restore()
        return True
    except Exception as error:
        logger.error(
            "Shortcut recovery needs attention and was not overwritten: %s", error,
            exc_info=True,
        )
        return False


def _restore_operation_session(journal) -> bool:
    """Restore a completed shortcut operation session exactly once."""
    if journal is None:
        return True
    logger.info("Restoring operation session...")
    try:
        journal.restore()
        logger.info("Operation session restored successfully")
        return True
    except Exception as error:
        logger.error("Failed to restore operation session: %s", error, exc_info=True)
        return False


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
    startup_checks = int(GAME_PROCESS_START_TIMEOUT_SECONDS / GAME_PROCESS_POLL_SECONDS)
    for _ in range(startup_checks):
        if tracker.refresh():
            logger.info("Game process detected")
            break
        if process and platform.system() != "Linux" and process.poll() is not None:
            logger.info("Launched process exited before detection")
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
        name for name in game_mode.get_process_names() if name.casefold() != "runner"
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
                process = subprocess.Popen(["steam", steam_url])
                background_operations.track_process(process, cancel=lambda: None)
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
        logger.error(
            f"No executable found for {game_mode.game_id} in game folder {game_path!r} "
            "(set a custom executable in the game settings or check the game path)"
        )
        return None

    system = platform.system()
    command = [launch_target]
    creationflags = 0
    launch_env = build_external_process_env(system=system)
    execution_runtime = resolve_execution_runtime(launch_target, system)

    if system == "Darwin" and execution_runtime == "macos" and launch_target.endswith(".app"):
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
        if system != "Windows" and execution_runtime == "windows":
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
    background_operations.register_process(process, cancel=lambda: None)
    try:
        _wait_for_game_exit(process, process_names, baseline_processes)
    finally:
        background_operations.release_process(process)
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


def _shortcut_mod_ids(shortcut_config: dict) -> tuple[str, ...]:
    """Read current and legacy shortcut mod selections."""
    raw_mod_ids = shortcut_config.get("mod_ids")
    if raw_mod_ids is None:
        launch_plan = shortcut_config.get("launch_plan")
        patch_plan = launch_plan.get("patch_plan") if isinstance(launch_plan, Mapping) else None
        sections = (
            patch_plan.get("sections", patch_plan.get("chapters", {}))
            if isinstance(patch_plan, Mapping)
            else shortcut_config.get("chapter_mods", {})
        )
        raw_mod_ids = []
        if isinstance(sections, Mapping):
            for _section, values in sorted(sections.items(), key=lambda item: str(item[0])):
                steps = values if isinstance(values, list) else [values]
                for step in steps:
                    mod_ids = step if isinstance(step, list) else [step]
                    raw_mod_ids.extend(mod_id for mod_id in mod_ids if mod_id not in (None, ""))
    if not isinstance(raw_mod_ids, list) or any(
        not isinstance(mod_id, str) or not mod_id for mod_id in raw_mod_ids
    ):
        raise ValueError("Shortcut mod_ids must be an array of mod IDs")
    return tuple(dict.fromkeys(raw_mod_ids))


def _shortcut_legacy_sections(shortcut_config: dict) -> dict[str, tuple[str, ...]]:
    """Return current or legacy shortcut section assignments."""
    if "section_mod_ids" in shortcut_config:
        sections = shortcut_config["section_mod_ids"]
        selected_ids = _shortcut_mod_ids(shortcut_config)
        if not isinstance(sections, dict) or any(
            not isinstance(section, str)
            or (shortcut_config.get("game_id") == "deltarune" and _canonical_legacy_section(section) is None)
            or not isinstance(mod_ids, list)
            or any(not isinstance(mod_id, str) or mod_id not in selected_ids for mod_id in mod_ids)
            for section, mod_ids in sections.items()
        ):
            raise ValueError("Shortcut section_mod_ids must contain selected mod IDs")
        assigned_ids = {mod_id for mod_ids in sections.values() for mod_id in mod_ids}
        if assigned_ids != set(selected_ids):
            raise ValueError("Shortcut section_mod_ids must assign every selected mod")
        return {section: tuple(dict.fromkeys(mod_ids)) for section, mod_ids in sections.items() if mod_ids}
    if shortcut_config.get("mod_ids") is not None:
        return {}
    launch_plan = shortcut_config.get("launch_plan")
    patch_plan = launch_plan.get("patch_plan") if isinstance(launch_plan, Mapping) else None
    sections = (
        patch_plan.get("sections", patch_plan.get("chapters", {}))
        if isinstance(patch_plan, Mapping)
        else shortcut_config.get("chapter_mods", {})
    )
    if not isinstance(sections, Mapping):
        return {}
    selected: dict[str, tuple[str, ...]] = {}
    for section_id, values in sections.items():
        if not isinstance(section_id, str):
            continue
        steps = values if isinstance(values, list) else [values]
        mod_ids = tuple(
            mod_id
            for step in steps
            for mod_id in (step if isinstance(step, list) else [step])
            if isinstance(mod_id, str) and mod_id
        )
        if mod_ids:
            selected[section_id] = mod_ids
    return selected


def _shortcut_merge_steps(
    shortcut_config: dict, mod_ids: tuple[str, ...]
) -> tuple[tuple[str, ...], ...]:
    raw_steps = shortcut_config.get("merge_steps", [])
    if not isinstance(raw_steps, list) or any(
        not isinstance(step, list)
        or any(not isinstance(mod_id, str) or not mod_id for mod_id in step)
        or any(mod_id not in mod_ids for mod_id in step)
        for step in raw_steps
    ):
        raise ValueError("Shortcut merge_steps must contain selected mod IDs")
    return tuple(tuple(step) for step in raw_steps if len(step) > 1)


def run_shortcut(shortcut_arg: str):
    """Main entry point for headless shortcut execution.

    Config format:
      {
        "game_id": "deltarune",
        "chapter_mode": true,
        "launch_via_steam": false,
        "use_portproton": false,
        "direct_launch_chapter": "",
        "mod_ids": ["first-mod", "second-mod"]
      }
    """
    _configure_logging()
    logger.info("=== G3M Shortcut Runner ===")

    try:
        shortcut_config = _parse_shortcut_arg(shortcut_arg)
    except Exception as e:
        logger.error(f"Invalid shortcut config: {e}")
        sys.exit(1)

    if not isinstance(shortcut_config, dict):
        logger.error(f"Invalid shortcut config: expected a JSON object, got {type(shortcut_config).__name__}")
        sys.exit(1)
    game_id = str(shortcut_config.get("game_id") or "")
    is_chapter_mode = bool(shortcut_config.get("chapter_mode", False))
    try:
        mod_ids = _shortcut_mod_ids(shortcut_config)
        merge_steps = _shortcut_merge_steps(shortcut_config, mod_ids)
        selected_sections = _shortcut_legacy_sections(shortcut_config)
    except ValueError as error:
        logger.error("%s", error)
        sys.exit(1)

    logger.info(
        "Config: game=%s, chapter_mode=%s, mod_ids=%s",
        game_id,
        is_chapter_mode,
        mod_ids or "vanilla",
    )

    game_mode = get_game(game_id)
    if not game_mode:
        logger.error(f"Unknown game_id: {game_id}")
        sys.exit(1)

    local_config = _load_config()
    profile_name = shortcut_config.get("active_profile")
    if profile_name is not None:
        if not isinstance(profile_name, str) or safe_profile_name(profile_name) != profile_name:
            logger.error(f"Invalid shortcut profile name {profile_name!r}: it must be a plain profile folder name")
            sys.exit(1)
        local_config["active_profile"] = profile_name
    game_path = game_mode.get_game_path(local_config)
    if not game_path or not os.path.isdir(game_path):
        logger.error(f"Game path not found: {game_path}")
        sys.exit(1)
    if mod_ids:
        from services.mod_config_migration_service import migrate_managed_mods

        migration = migrate_managed_mods(
            get_profile_mods_root(local_config.get("active_profile", "Default"))
        )
        for issue in migration.issues:
            logger.warning("Managed mod migration failed for %s: %s", issue.path, issue.message)
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
        _restore_shortcut_state(
            runtime_service, shortcut_plugin_context, shortcut_config, None
        )
        sys.exit(1)

    journal = None
    if mod_ids:
        journal = _execute_operation_plan(
            mod_ids,
            game_path,
            game_mode,
            local_config,
            merge_steps=merge_steps,
            legacy_sections=selected_sections,
        )
        if journal is None:
            _restore_shortcut_state(
                runtime_service, shortcut_plugin_context, shortcut_config, None
            )
            sys.exit(1)
        logger.info("All selected mod operations applied successfully")

    after_apply_hook_succeeded = execute_shortcut_plugin_hook(
        runtime_service,
        "after_mod_apply_before_launch_shortcut",
        shortcut_plugin_context,
        shortcut_config,
    )
    if journal is not None:
        try:
            journal.checkpoint()
        except Exception as error:
            logger.error(
                "Shortcut operation checkpoint failed: %s",
                error,
                exc_info=True,
            )
            _restore_shortcut_state(
                runtime_service, shortcut_plugin_context, shortcut_config, journal
            )
            sys.exit(1)
    if not after_apply_hook_succeeded:
        logger.warning("Shortcut launch blocked by a plugin after mod apply")
        _restore_shortcut_state(
            runtime_service, shortcut_plugin_context, shortcut_config, journal
        )
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

    restored = _restore_shortcut_state(
        runtime_service, shortcut_plugin_context, shortcut_config, journal
    )

    if launch_failed or not restored:
        sys.exit(1)

    logger.info("=== Shortcut Runner finished ===")


def _restore_shortcut_state(
    runtime_service,
    shortcut_plugin_context: ShortcutPluginContext,
    shortcut_config: dict,
    journal,
) -> bool:
    plugin_restore = bool(
        journal is not None
        and runtime_service is not None
        and shortcut_plugin_context.enabled
        and runtime_service.has_enabled_hook("before_restore_after_exit_shortcut")
    )
    if plugin_restore and journal is not None:
        try:
            journal.verify_deployed()
        except Exception:
            logger.exception("Shortcut files changed externally; operation journal retained")
            return False
    if not execute_shortcut_plugin_hook(
        runtime_service,
        "before_restore_after_exit_shortcut",
        shortcut_plugin_context,
        shortcut_config,
    ):
        logger.error("Shortcut plugin restoration failed; operation journal retained")
        return False
    if plugin_restore and journal is not None:
        try:
            journal.checkpoint()
        except Exception:
            logger.exception("Shortcut plugin restoration checkpoint failed")
            return False
    if _restore_operation_session(journal) is False:
        return False
    return execute_shortcut_plugin_hook(
        runtime_service,
        "after_restore_after_exit_shortcut",
        shortcut_plugin_context,
        shortcut_config,
    )
