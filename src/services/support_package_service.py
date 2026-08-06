"""Build privacy-aware local support archives."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import socket
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psutil

from config.config import APP_VERSION, MOD_CONFIG_FILENAME
from services.background_operations import background_operations
from utils.frickbears3_addons_utils import get_frickbears3_addons_dir
from utils.path_utils import get_user_data_root
from utils.pizzatower_afom_utils import get_pizzatower_towers_dir

SECRET_KEY = re.compile(
    r"(?:token|secret|password|passwd|authorization|api[_-]?key|cookie|session)", re.I
)


def _identity_tokens() -> set[str]:
    values = {
        os.environ.get("USERNAME", ""),
        os.environ.get("USER", ""),
        os.environ.get("COMPUTERNAME", ""),
        socket.gethostname(),
        Path.home().name,
    }
    return {value for value in values if value and len(value) > 1}


class SupportPackageService:
    """Collect selected diagnostics without transmitting them."""

    def __init__(self, app_state, root: str | None = None, mod_service=None) -> None:
        self.app_state = app_state
        self.mod_service = mod_service
        self.root = Path(root or get_user_data_root()).resolve()
        self._identity = sorted(_identity_tokens(), key=len, reverse=True)

    @staticmethod
    def archive_component(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
        return cleaned or "item"

    def installed_mods(self) -> list[tuple[str, str, Path]]:
        result = []
        for mod in getattr(self.app_state, "all_mods", []):
            mod_id = str(getattr(mod, "id", "") or "")
            name = str(getattr(mod, "name", "") or mod_id or "Unknown mod")
            folder = getattr(mod, "folder_path", None)
            if not folder and self.mod_service and mod_id:
                try:
                    folder = self.mod_service.get_mod_folder_path(mod_id)
                except (AttributeError, OSError, RuntimeError):
                    folder = None
            path = Path(folder).resolve() if folder and Path(folder).is_dir() else None
            if mod_id and path:
                result.append((mod_id, name, path))
        return sorted(result, key=lambda item: item[1].casefold())

    def shareable_g3m_files(self) -> list[Path]:
        mod_roots = [path for _, _, path in self.installed_mods()]
        result = []
        for path in self.root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            if path.suffix.casefold() not in {".json", ".md", ".txt"}:
                continue
            resolved = path.resolve()
            if any(resolved.is_relative_to(mod_root) for mod_root in mod_roots):
                continue
            result.append(path)
        return sorted(result, key=lambda path: str(path).casefold())

    def game_roots(self) -> list[tuple[str, Path]]:
        candidates = {
            "DELTARUNE": getattr(self.app_state, "game_path", ""),
            "DELTARUNE Demo": getattr(self.app_state, "demo_game_path", ""),
            "UNDERTALE": getattr(self.app_state, "undertale_game_path", ""),
        }
        config = getattr(self.app_state, "local_config", {})
        for key, value in config.items():
            if key.endswith("_game_path") and isinstance(value, str) and value:
                candidates.setdefault(
                    key.removesuffix("_game_path").replace("_", " ").title(), value
                )
        result = []
        seen = set()
        for name, value in candidates.items():
            if not value:
                continue
            path = Path(value).resolve()
            if path.is_dir() and path not in seen:
                seen.add(path)
                result.append((name, path))
        return result

    @staticmethod
    def special_appdata_roots() -> list[tuple[str, Path]]:
        result = []
        for name, value in (
            ("Frickbears3 addons", get_frickbears3_addons_dir()),
            ("Pizza Tower towers", get_pizzatower_towers_dir()),
        ):
            path = Path(value).resolve()
            if path.is_dir():
                result.append((name, path))
        return result

    def g3mpatch_manifests(self) -> list[tuple[Path, str]]:
        result = []
        roots = [self.root, *(path for _, _, path in self.installed_mods())]
        seen = set()
        for root in roots:
            for path in root.rglob("*.g3mpatch"):
                if path.is_symlink() or not path.is_file() or path in seen:
                    continue
                seen.add(path)
                try:
                    with zipfile.ZipFile(path) as archive:
                        for name in archive.namelist():
                            if Path(name).name.casefold() == "g3mpatch.json":
                                result.append((path, name))
                except (OSError, ValueError, zipfile.BadZipFile):
                    continue
        return sorted(result, key=lambda item: str(item[0]).casefold())

    def redact_text(self, value: str) -> str:
        result = value
        for token in self._identity:
            result = re.sub(re.escape(token), "USERNAME", result, flags=re.I)
        result = re.sub(
            r"(?i)\b(token|secret|password|passwd|authorization|api[_-]?key|cookie|session)"
            r"(\s*[:=]\s*)([^\s,;]+)",
            r"\1\2[REDACTED]",
            result,
        )
        result = re.sub(
            r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", result
        )
        return result

    def sanitize(self, value: Any, key: str = "") -> Any:
        if SECRET_KEY.search(key):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {str(k): self.sanitize(v, str(k)) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self.sanitize(item) for item in value]
        if isinstance(value, str):
            return self.redact_text(value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return self.redact_text(str(value))

    def available_logs(self) -> list[Path]:
        logs = self.root / "logs"
        if not logs.is_dir():
            return []
        return sorted(
            (
                path
                for path in logs.rglob("*")
                if path.is_file() and not path.is_symlink()
            ),
            key=lambda path: str(path).casefold(),
        )

    def _selected_logs(self, names: set[str], days: int | None) -> Iterable[Path]:
        cutoff = None if days is None else datetime.now(UTC) - timedelta(days=days)
        for path in self.available_logs():
            relative = path.relative_to(self.root).as_posix()
            if relative not in names:
                continue
            if cutoff is not None:
                modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                if modified < cutoff:
                    continue
            yield path

    def _structure_for_root(
        self, root: Path, cancelled: Callable[[], bool], excluded: set[Path]
    ) -> list[dict[str, Any]]:
        result = []
        for current, dirs, files in os.walk(root, followlinks=False):
            if cancelled():
                break
            dirs[:] = sorted(d for d in dirs if not (Path(current) / d).is_symlink())
            base = Path(current)
            try:
                directory_stat = base.stat()
                directory_relative = base.relative_to(root).as_posix() or "."
                result.append(
                    {
                        "path": self.redact_text(str(base)),
                        "relative_path": directory_relative,
                        "type": "directory",
                        "modified": datetime.fromtimestamp(
                            directory_stat.st_mtime, UTC
                        ).isoformat(),
                    }
                )
            except (OSError, ValueError):
                pass
            for name in sorted(files):
                path = base / name
                if path.resolve(strict=False) in excluded:
                    continue
                try:
                    stat = path.lstat()
                    relative = path.relative_to(root).as_posix()
                except (OSError, ValueError):
                    continue
                result.append(
                    {
                        "path": self.redact_text(str(root / relative)),
                        "relative_path": relative,
                        "type": "file",
                        "size": stat.st_size,
                        "extension": path.suffix.casefold(),
                        "created": datetime.fromtimestamp(
                            stat.st_ctime, UTC
                        ).isoformat(),
                        "modified": datetime.fromtimestamp(
                            stat.st_mtime, UTC
                        ).isoformat(),
                        "mode": oct(stat.st_mode),
                        "symlink": path.is_symlink(),
                    }
                )
        return result

    def _structure(
        self, cancelled: Callable[[], bool], excluded: set[Path]
    ) -> list[dict[str, Any]]:
        return self._structure_for_root(self.root, cancelled, excluded)

    def _processes(self) -> list[dict[str, Any]]:
        records = []
        for process in psutil.process_iter(
            ["pid", "name", "status", "cpu_percent", "memory_info", "create_time"]
        ):
            try:
                info = process.info
                memory = info.pop("memory_info", None)
                info["memory_rss"] = memory.rss if memory else None
                records.append(self.sanitize(info))
            except (psutil.Error, OSError):
                continue
        return records

    def _network(self) -> dict[str, Any]:
        counters = psutil.net_io_counters(pernic=True)
        return {
            name: {
                "bytes_sent": value.bytes_sent,
                "bytes_received": value.bytes_recv,
                "packets_sent": value.packets_sent,
                "packets_received": value.packets_recv,
                "errors_in": value.errin,
                "errors_out": value.errout,
                "drops_in": value.dropin,
                "drops_out": value.dropout,
            }
            for name, value in counters.items()
        }

    def _performance(self) -> dict[str, Any]:
        before = psutil.net_io_counters()
        started = time.monotonic()
        cpu_percent = psutil.cpu_percent(interval=0.25, percpu=True)
        elapsed = max(time.monotonic() - started, 0.001)
        after = psutil.net_io_counters()
        return {
            "cpu_percent_per_core": cpu_percent,
            "disk_usage": psutil.disk_usage(
                str(self.root.anchor or self.root)
            )._asdict(),
            "sample_seconds": elapsed,
            "network_bytes_sent_per_second": (after.bytes_sent - before.bytes_sent)
            / elapsed,
            "network_bytes_received_per_second": (after.bytes_recv - before.bytes_recv)
            / elapsed,
        }

    def _write_json(self, archive: zipfile.ZipFile, name: str, value: Any) -> None:
        archive.writestr(
            name,
            json.dumps(
                self.sanitize(value), ensure_ascii=False, indent=2, sort_keys=True
            ),
        )

    def _write_log(
        self,
        archive: zipfile.ZipFile,
        path: Path,
        archive_name: str,
        cancelled: Callable[[], bool],
    ) -> None:
        with (
            path.open("r", encoding="utf-8", errors="replace") as source,
            archive.open(archive_name, "w") as destination,
        ):
            for line in source:
                if cancelled():
                    raise InterruptedError
                destination.write(self.redact_text(line).encode("utf-8"))

    def _write_shareable_file(
        self,
        archive: zipfile.ZipFile,
        source: Path,
        archive_name: str,
        cancelled: Callable[[], bool],
    ) -> None:
        if source.suffix.casefold() == ".json":
            try:
                value = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                value = {"read_error": type(error).__name__}
            self._write_json(archive, archive_name, value)
            return
        self._write_log(archive, source, archive_name, cancelled)

    def _write_tree(
        self,
        archive: zipfile.ZipFile,
        root: Path,
        prefix: str,
        cancelled: Callable[[], bool],
        excluded: set[Path],
    ) -> None:
        for current, dirs, files in os.walk(root, followlinks=False):
            if cancelled():
                raise InterruptedError
            base = Path(current)
            dirs[:] = sorted(d for d in dirs if not (base / d).is_symlink())
            for name in sorted(files):
                source = base / name
                resolved = source.resolve(strict=False)
                if (
                    source.is_symlink()
                    or resolved in excluded
                    or SECRET_KEY.search(name)
                ):
                    continue
                relative = source.relative_to(root).as_posix()
                archive_name = f"{prefix}/{relative}"
                if source.suffix.casefold() in {".json", ".md", ".txt", ".log"}:
                    self._write_shareable_file(archive, source, archive_name, cancelled)
                else:
                    archive.write(source, archive_name)

    def _write_dynamic_selections(
        self,
        archive: zipfile.ZipFile,
        selected: set[str],
        cancelled: Callable[[], bool],
        excluded: set[Path],
    ) -> None:
        g3m_files = {
            path.relative_to(self.root).as_posix(): path
            for path in self.shareable_g3m_files()
        }
        mods = {mod_id: (name, root) for mod_id, name, root in self.installed_mods()}
        games = {
            self.archive_component(name): (name, root) for name, root in self.game_roots()
        }
        special = {
            self.archive_component(name): (name, root)
            for name, root in self.special_appdata_roots()
        }
        manifests = {
            f"{path.resolve()}::{entry}": (path, entry)
            for path, entry in self.g3mpatch_manifests()
        }
        for option in sorted(selected):
            if cancelled():
                raise InterruptedError
            kind, separator, value = option.partition("::")
            if not separator:
                continue
            if kind == "g3m_file" and value in g3m_files:
                self._write_shareable_file(
                    archive,
                    g3m_files[value],
                    f"g3m_files/{value}",
                    cancelled,
                )
            elif kind == "mod_config" and value in mods:
                name, root = mods[value]
                config = root / MOD_CONFIG_FILENAME
                if config.is_file() and not config.is_symlink():
                    self._write_shareable_file(
                        archive,
                        config,
                        f"mods/{self.archive_component(name)}_{self.archive_component(value)}/{MOD_CONFIG_FILENAME}",
                        cancelled,
                    )
            elif kind == "mod_structure" and value in mods:
                name, root = mods[value]
                self._write_json(
                    archive,
                    f"mods/{self.archive_component(name)}_{self.archive_component(value)}/structure.json",
                    self._structure_for_root(root, cancelled, excluded),
                )
            elif kind == "mod_files" and value in mods:
                name, root = mods[value]
                self._write_tree(
                    archive,
                    root,
                    f"mods/{self.archive_component(name)}_{self.archive_component(value)}/files",
                    cancelled,
                    excluded,
                )
            elif kind == "game_structure" and value in games:
                name, root = games[value]
                self._write_json(
                    archive,
                    f"games/{self.archive_component(name)}/structure.json",
                    self._structure_for_root(root, cancelled, excluded),
                )
            elif kind == "appdata_structure" and value in special:
                name, root = special[value]
                self._write_json(
                    archive,
                    f"appdata/{self.archive_component(name)}/structure.json",
                    self._structure_for_root(root, cancelled, excluded),
                )
            elif kind == "patch_manifest" and value in manifests:
                path, entry = manifests[value]
                with zipfile.ZipFile(path) as source_archive:
                    info = source_archive.getinfo(entry)
                    if info.file_size > 8 * 1024 * 1024:
                        manifest = {"read_error": "g3mpatch.json exceeds 8 MiB"}
                    else:
                        raw = source_archive.read(info)
                        try:
                            manifest = json.loads(raw.decode("utf-8"))
                        except (UnicodeError, json.JSONDecodeError):
                            manifest = {"read_error": "Invalid g3mpatch.json"}
                identity = hashlib.sha256(str(path).encode()).hexdigest()[:8]
                self._write_json(
                    archive,
                    f"g3mpatch/{self.archive_component(path.stem)}_{identity}/g3mpatch.json",
                    manifest,
                )

    def build(
        self,
        destination: str,
        selected: set[str],
        *,
        log_names: set[str],
        log_days: int | None,
        runtime_metrics: dict[str, Any] | None = None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> str:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            suffix=".zip.tmp", prefix="g3m-support-", dir=target.parent
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                if "app.version" in selected:
                    self._write_json(
                        archive, "application/version.json", {"version": APP_VERSION}
                    )
                state_options = {
                    "app.state",
                    "app.selection",
                    "app.operations",
                    "app.background",
                    "app.launch",
                }
                if selected & state_options:
                    window = getattr(self.app_state, "_app_window", None)
                    launcher = getattr(window, "game_launcher", None)
                    transaction = getattr(launcher, "launch_transaction", None)
                    state = {}
                    if "app.state" in selected or "app.selection" in selected:
                        profile_service = getattr(window, "profile_service", None)
                        state["selection"] = {
                            "game": getattr(
                                getattr(self.app_state, "game_mode", None), "key", None
                            ),
                            "chapter": getattr(
                                self.app_state, "selected_chapter_id", None
                            ),
                            "profile": getattr(profile_service, "active_name", None),
                        }
                    if "app.state" in selected or "app.operations" in selected:
                        state["operations"] = {
                            "game_running": getattr(
                                self.app_state, "game_is_running", False
                            ),
                            "installing": getattr(
                                self.app_state, "is_installing", False
                            ),
                            "patching": getattr(self.app_state, "is_patching", False),
                            "initialization_completed": getattr(
                                self.app_state, "initialization_completed", False
                            ),
                            "has_internet": getattr(
                                self.app_state, "has_internet", None
                            ),
                        }
                    if "app.state" in selected or "app.background" in selected:
                        state["background_operations"] = (
                            background_operations.snapshot()
                        )
                    if "app.state" in selected or "app.launch" in selected:
                        state["launch_transaction"] = (
                            transaction.snapshot() if transaction else None
                        )
                    self._write_json(
                        archive,
                        "application/state.json",
                        state,
                    )
                system = {}
                if "system.os" in selected:
                    system["os"] = platform.platform()
                    system["release"] = platform.release()
                if "system.machine" in selected:
                    system["machine"] = platform.machine()
                    system["processor"] = platform.processor()
                if "system.python" in selected:
                    system["python"] = sys.version
                if "system.memory" in selected:
                    system["memory"] = psutil.virtual_memory()._asdict()
                if "system.boot" in selected:
                    system["boot_time"] = datetime.fromtimestamp(
                        psutil.boot_time(), UTC
                    ).isoformat()
                    system["collected_at"] = datetime.now(UTC).isoformat()
                if system:
                    self._write_json(archive, "system/system.json", system)
                if "system.processes" in selected:
                    self._write_json(
                        archive, "system/processes.json", self._processes()
                    )
                if "system.network" in selected:
                    self._write_json(archive, "system/network.json", self._network())
                if "system.performance" in selected:
                    self._write_json(
                        archive, "system/performance.json", self._performance()
                    )
                if "system.ui_performance" in selected:
                    self._write_json(
                        archive,
                        "system/g3m_ui_performance.json",
                        runtime_metrics or {"available": False},
                    )
                if "metadata.settings" in selected:
                    self._write_json(
                        archive,
                        "metadata/settings.json",
                        getattr(self.app_state, "local_config", {}),
                    )
                if "metadata.mods" in selected:
                    mods = [
                        getattr(mod, "__dict__", str(mod))
                        for mod in self.app_state.all_mods
                    ]
                    self._write_json(archive, "metadata/mods.json", mods)
                if "structure.files" in selected:
                    excluded = {target.resolve(strict=False), temporary.resolve()}
                    self._write_json(
                        archive,
                        "structure/files.json",
                        self._structure(cancelled, excluded),
                    )
                else:
                    excluded = {target.resolve(strict=False), temporary.resolve()}
                self._write_dynamic_selections(archive, selected, cancelled, excluded)
                for path in self._selected_logs(log_names, log_days):
                    if cancelled():
                        raise InterruptedError
                    relative = path.relative_to(self.root).as_posix()
                    self._write_log(
                        archive,
                        path,
                        f"logs/{relative.removeprefix('logs/')}",
                        cancelled,
                    )
                if cancelled():
                    raise InterruptedError
                self._write_json(
                    archive,
                    "manifest.json",
                    {"format": 1, "created": time.time(), "selected": sorted(selected)},
                )
            os.replace(temporary, target)
            return str(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
