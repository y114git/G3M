"""Game detection and validation utilities."""

import logging
import os
import platform
from pathlib import Path
from typing import TYPE_CHECKING

import psutil

from models.game_modes import get_all_process_names, get_game
from utils.path_utils import find_supported_game_data_file

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from models.game_modes import GameDefinition

ProcessIdentity = tuple[int, float]
GAME_PROCESS_POLL_SECONDS = 0.25
GAME_PROCESS_RUNNING_POLL_SECONDS = 1.0
GAME_PROCESS_START_TIMEOUT_SECONDS = 5 * 60
GAME_PROCESS_EXIT_CONFIRMATION_CHECKS = 4


def _process_identity(process: psutil.Process) -> ProcessIdentity | None:
    try:
        return process.pid, process.create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def get_matching_process_identities(
    process_names: tuple[str, ...] | list[str] | set[str] | None = None,
) -> set[ProcessIdentity]:
    """Return stable identities for running processes with the requested names."""
    names = process_names or get_all_process_names()
    normalized_names = {name.casefold() for name in names if name}
    identities: set[ProcessIdentity] = set()
    if not normalized_names:
        return identities
    for process in psutil.process_iter(["name"]):
        try:
            name = process.info.get("name")
            if name and name.casefold() in normalized_names:
                identity = _process_identity(process)
                if identity is not None:
                    identities.add(identity)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return identities


def get_process_tree_identities(pid: int | None) -> set[ProcessIdentity]:
    """Return the live root process and descendants, tolerating process hand-off."""
    if not pid:
        return set()
    try:
        root = psutil.Process(pid)
        processes = [root, *root.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return set()
    return {
        identity
        for process in processes
        if (identity := _process_identity(process)) is not None
    }


def is_process_identity_running(identity: ProcessIdentity) -> bool:
    """Check a PID together with its creation time so PID reuse is harmless."""
    pid, created_at = identity
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.create_time() == created_at
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


class GameProcessTracker:
    """Track one launch across wrapper, child, and platform process hand-offs."""

    def __init__(
        self,
        root_pid: int | None,
        process_names: tuple[str, ...],
        baseline_processes: set[ProcessIdentity] | None = None,
    ) -> None:
        self.root_pid = root_pid
        self.process_names = tuple(name for name in process_names if name) or tuple(
            get_all_process_names()
        )
        self.baseline = (
            set(baseline_processes)
            if baseline_processes is not None
            else get_matching_process_identities(self.process_names)
        )
        self.tracked = get_process_tree_identities(root_pid)

    def discover(self) -> set[ProcessIdentity]:
        named_processes = (
            get_matching_process_identities(self.process_names) - self.baseline
        )
        return get_process_tree_identities(self.root_pid) | named_processes

    def refresh(self) -> bool:
        self.tracked.update(self.discover())
        self.tracked = {
            identity
            for identity in self.tracked
            if is_process_identity_running(identity)
        }
        return bool(self.tracked)


def is_game_running(pid: int | None = None):
    if pid is not None:
        try:
            return psutil.pid_exists(pid)
        except (TypeError, OverflowError):
            return False
    return bool(get_matching_process_identities())


def get_running_game_process_name() -> str | None:
    process_names = {name.casefold() for name in get_all_process_names() if name}
    for proc in psutil.process_iter(["name"]):
        try:
            name = proc.info["name"]
            if name and name.casefold() in process_names:
                return name
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return None


def is_valid_mac_game_path(path: str, skip_data_check: bool, game_type: str) -> bool:
    app_path = Path(path)
    from models.game_modes import get_game

    gm = get_game(game_type)
    if not gm:
        logger.warning("Unknown game_type '%s' in is_valid_mac_game_path", game_type)
        return False
    app_names = gm.macos_app_names
    data_file_name = getattr(gm, "data_file_name", "")
    if not path.endswith(".app"):
        app_path = next(
            (app_path / name for name in app_names if (app_path / name).is_dir()), None
        )
    if not app_path or not app_path.is_dir():
        return False
    macos_dir, res_dir = (
        app_path / "Contents" / "MacOS",
        app_path / "Contents" / "Resources",
    )
    if not (macos_dir.is_dir() and res_dir.is_dir()):
        return False
    try:
        has_executable = any(
            p.is_file() and os.access(p, os.X_OK) for p in macos_dir.iterdir()
        )
    except OSError:
        return False
    return (
        has_executable
        if skip_data_check
        else has_executable
        and bool(
            find_supported_game_data_file(
                str(res_dir),
                data_file_name,
                fallback_to_supported_names=not bool(data_file_name),
            )
        )
    )


def is_valid_game_path(
    path: str, skip_data_check: bool = False, game_type: str = "deltarune"
) -> bool:
    if not path or not os.path.isdir(path):
        return False
    if platform.system() == "Darwin":
        return is_valid_mac_game_path(path, skip_data_check, game_type)
    platform_key = "windows" if platform.system() == "Windows" else "linux"
    game = get_game(game_type)
    if not game:
        logger.warning("Unknown game_type '%s' in is_valid_game_path", game_type)
        return False
    executables = game.get_executable_candidates(platform_key)
    return any(os.path.isfile(os.path.join(path, exe)) for exe in executables)


def get_game_type_string(game_mode: GameDefinition) -> str:
    return getattr(game_mode, "game_id", "deltarune")


def get_game_name_string(game_mode: GameDefinition) -> str:
    return getattr(game_mode, "display_name", "DELTARUNE")


def get_chapter_id_for_game_mode(game_mode: GameDefinition) -> str:
    return getattr(game_mode, "default_tab", "") or getattr(
        game_mode, "game_id", "deltarune"
    )


def get_executable_name_for_game(
    game_type: str, os_type: str | None = None
) -> str | None:
    if os_type is None:
        os_type = (
            "windows"
            if platform.system() == "Windows"
            else ("mac" if platform.system() == "Darwin" else "linux")
        )
    game = get_game(game_type)
    if not game:
        logger.warning(
            "Unknown game_type '%s' in get_executable_name_for_game", game_type
        )
        return None
    executables = game.get_executable_candidates(os_type)
    return executables[0] if executables else None
