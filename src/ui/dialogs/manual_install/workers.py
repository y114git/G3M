"""Background detection, metadata refresh and atomic manual-import saving."""

from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from PyQt6.QtCore import pyqtSignal

from adapters.g3mtool_adapter import G3MToolManager
from adapters.gamebanana_adapter import GameBananaAPI
from ui.dialogs.manual_install.detection import (
    copy_file,
    detect_operations,
    pack_patch,
    verify_operations,
)
from ui.utils.thread_lifetime import ManagedQThread, safe_emit
from utils.file_utils import find_mod_dir_by_id, get_unique_mod_dir, replace_mod_dir
from utils.mod.archive import archive_format, list_archive_members
from utils.mod.config import write_mod_config
from utils.mod.hashing import sha256_path
from utils.process_utils import format_filesystem_error

logger = logging.getLogger(__name__)


class DetectionThread(ManagedQThread):
    result_ready = pyqtSignal(dict, str)
    progress = pyqtSignal(int, int)

    def __init__(self, files, context, config, *, checks=None, game="") -> None:
        super().__init__()
        self.files, self.context, self.config = files, context, config
        self.checks, self.game = checks, game

    def run(self) -> None:
        tool = G3MToolManager(SimpleNamespace(local_config=self.config))
        done = threading.Event()
        deadline = [float("inf")]

        def monitor() -> None:
            while not done.wait(0.1):
                if self.isInterruptionRequested() or time.monotonic() > deadline[0]:
                    tool.cancel_active_processes()

        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()

        def apply(kind, base, patch, output):
            if self.isInterruptionRequested() or not tool.is_available():
                return None
            deadline[0] = time.monotonic() + 30 if self.checks is None else float("inf")
            try:
                method = tool.xpatch_apply if kind == "xdelta" else tool.apply_patch
                succeeded = method(str(base), str(patch), str(output))[0] == 0
                return (
                    None
                    if time.monotonic() > deadline[0] or self.isInterruptionRequested()
                    else succeeded
                )
            finally:
                deadline[0] = float("inf")

        result, error = {}, ""
        try:
            if self.checks is not None:
                result = verify_operations(
                    self.files,
                    self.context,
                    self.checks,
                    apply,
                    self.isInterruptionRequested,
                    game=self.game,
                )
            else:
                result = detect_operations(
                    self.files,
                    self.context,
                    apply,
                    cancelled=self.isInterruptionRequested,
                    progress=lambda completed, total: safe_emit(
                        self.__class__.__name__, self.progress, completed, total
                    ),
                    docs_as_info=self.config.get("manual_install_docs_as_info", True),
                )
        except InterruptedError:
            pass
        except ValueError as exception:
            error = str(exception)
        except Exception as exception:
            logger.exception(f"Manual-install file detection failed for {len(self.files)} file(s)")
            error = format_filesystem_error(exception)
        finally:
            done.set()
            watcher.join()
        if not self.isInterruptionRequested():
            safe_emit(self.__class__.__name__, self.result_ready, result, error)


def write_import(
    files,
    config,
    mods_dir: Path,
    cancelled=lambda: False,
    import_root: Path | None = None,
) -> Path:
    mods_dir.mkdir(parents=True, exist_ok=True)
    previous = find_mod_dir_by_id(str(mods_dir), config["id"])
    target = mods_dir / get_unique_mod_dir(str(mods_dir), config["name"])
    target.mkdir()
    try:
        hashes = {
            leaf["source"].removeprefix("${mod_path}/files/"): leaf["source_hash"]
            for leaf in config["files"]
            if leaf.get("source_hash")
        }
        for source, relative in files:
            if cancelled():
                raise InterruptedError
            stored = PurePosixPath("files") / PurePosixPath(relative.replace("\\", "/"))
            destination = target.joinpath(*stored.parts)
            if (
                not destination.resolve().is_relative_to(target.resolve())
                or Path(source).is_symlink()
                or Path(source).is_junction()
                or (
                    import_root is not None
                    and not Path(source).resolve().is_relative_to(import_root)
                )
            ):
                raise ValueError("source path must remain inside the selected import")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if relative.endswith("/"):
                destination.mkdir(parents=True, exist_ok=True)
            elif Path(source).is_dir():
                pack_patch(Path(source), destination, cancelled)
            else:
                copy_file(Path(source), destination, cancelled)
                shutil.copystat(source, destination)
        for relative, expected in hashes.items():
            if (
                sha256_path(target / "files" / relative, cancelled=cancelled)
                != expected
            ):
                raise ValueError(f"{relative}: source changed during saving")
        for leaf in config["files"]:
            relative = leaf["source"].removeprefix("${mod_path}/files/")
            source = target / "files" / relative
            if (
                leaf["type"].endswith("extract")
                and source.is_file()
                and archive_format(source)
            ):
                try:
                    list_archive_members(source)
                except Exception as error:
                    raise ValueError(f"{relative}: {error}") from error
        if cancelled():
            raise InterruptedError
        write_mod_config(target / "mod_config.json", config)
        if cancelled():
            raise InterruptedError
        if previous:
            return Path(replace_mod_dir(previous, str(target)))
        return target
    except Exception:
        # Only this freshly-created mod directory belongs to this attempt.
        shutil.rmtree(target, ignore_errors=True)
        raise


class SaveThread(ManagedQThread):
    result_ready = pyqtSignal(object, str)

    def __init__(self, files, config, mods_dir, import_root) -> None:
        super().__init__()
        self.files, self.config, self.mods_dir = files, config, mods_dir
        self.import_root = Path(import_root).resolve()

    def run(self) -> None:
        folder, error = None, ""
        try:
            folder = write_import(
                self.files,
                self.config,
                self.mods_dir,
                self.isInterruptionRequested,
                self.import_root,
            )
        except InterruptedError:
            pass
        except Exception as exception:
            logger.exception(f"Manual import into {self.mods_dir!r} failed")
            error = (
                str(exception)
                if isinstance(exception, ValueError)
                else format_filesystem_error(exception)
            )
        safe_emit(self.__class__.__name__, self.result_ready, folder, error)


class MetadataThread(ManagedQThread):
    result_ready = pyqtSignal(dict)

    def __init__(self, metadata: dict) -> None:
        super().__init__()
        self.metadata = dict(metadata)

    def run(self) -> None:
        try:
            result = GameBananaAPI().get_install_metadata(self.metadata)
        except Exception:
            logger.warning("Could not initialize GameBanana metadata client", exc_info=True)
            result = {}
        if not self.isInterruptionRequested():
            safe_emit(self.__class__.__name__, self.result_ready, result)
