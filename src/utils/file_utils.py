"""File operation utilities."""

import contextlib
import json
import logging
import os
import re
import shutil
import stat
import tempfile
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from config.constants import (
    ICON_PNG_FILENAME,
    IS_WINDOWS_PLATFORM,
    LEGACY_META_JSON_FILENAME,
    LEGACY_MOD_CONFIG_FILENAME,
    META_JSON_FILENAME,
    MOD_CONFIG_FILENAME,
)
from utils.network_utils import download_file, get_filename_from_url, get_session

T = TypeVar("T")


def _retry_operation[T](
    operation: Callable[[], T],
    max_retries: int = 5,
    delay: float = 0.1,
    op_name: str = "operation",
    path: str = "",
) -> T:
    """Retry a file operation with exponential backoff."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return operation()
        except (OSError, PermissionError, shutil.Error) as e:
            last_error = e
            if attempt < max_retries - 1:
                logging.debug(
                    f"{op_name}: Attempt {attempt + 1}/{max_retries} failed for {path}: {e}, retrying..."
                )
                time.sleep(delay * (attempt + 1))
            else:
                logging.warning(
                    f"{op_name}: Failed for {path} after {max_retries} attempts: {e}"
                )
    raise last_error if last_error else RuntimeError(f"{op_name} failed")


def _fix_windows_permissions(path: str) -> None:
    if IS_WINDOWS_PLATFORM:
        with contextlib.suppress(OSError):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def download_file_with_progress(
    url: str,
    target_path: str,
    progress_callback=None,
    session=None,
    cancel_check=None,
    on_response=None,
    downloaded_ref=None,
) -> bool:
    from config.constants import NETWORK_TIMEOUT_HEAD

    session = session or get_session()
    total_size = 0
    try:
        total_size = int(
            session.head(
                url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD
            ).headers.get("content-length", 0)
        )
    except Exception as e:
        logging.debug(f"download_file_with_progress: Could not get content-length: {e}")
    downloaded_ref = downloaded_ref or [0]
    try:
        download_file(
            session,
            url,
            target_path,
            progress_callback=progress_callback,
            total_size=total_size,
            downloaded_ref=downloaded_ref,
            cancel_check=cancel_check,
            on_response=on_response,
        )
        if progress_callback:
            progress_callback(100)
        return True
    except RuntimeError as e:
        if str(e) == "download_cancelled":
            logging.debug("download_file_with_progress: Download cancelled")
            return False
        logging.error(
            f"download_file_with_progress: Download failed: {e}", exc_info=True
        )
        return False
    except Exception as e:
        logging.error(
            f"download_file_with_progress: Download failed: {e}", exc_info=True
        )
        return False


def download_and_extract_archive(
    url: str,
    target_dir: str,
    progress_callback=None,
    total_size: int = 0,
    downloaded_ref: list[int] | None = None,
    session=None,
    is_game_installation=False,
    cancel_check=None,
    on_response=None,
):
    from utils.archive_utils import extract_archive

    downloaded_ref, session = downloaded_ref or [0], session or get_session()
    os.makedirs(target_dir, exist_ok=True)
    fname = get_filename_from_url(session, url)
    with tempfile.TemporaryDirectory(prefix="deltahub-dl-") as tmp:
        tmp_path = os.path.join(tmp, fname)
        download_file(
            session,
            url,
            tmp_path,
            progress_callback,
            total_size,
            downloaded_ref,
            cancel_check=cancel_check,
            on_response=on_response,
        )
        if not (cancel_check and cancel_check()):
            extract_archive(
                tmp_path,
                target_dir,
                fname=fname,
                is_game_installation=is_game_installation,
            )


def _is_symlink(path: str) -> bool:
    try:
        return os.path.islink(path)
    except OSError:
        return False


def _safe_join(base: str, *paths: str) -> str:
    base_abs = os.path.abspath(base)
    for path in paths:
        normalized = str(path).replace("\\", "/")
        if (
            normalized.startswith("/")
            or normalized.startswith("..")
            or "/../" in normalized
            or re.match(r"^[A-Za-z]:", str(path))
        ):
            raise ValueError("path_traversal")
    final = os.path.abspath(os.path.join(base_abs, *paths))
    if os.path.commonpath([final, base_abs]) != base_abs:
        raise ValueError("path_traversal")
    return final


def normalize_mod_package(
    mod_root: str,
    *,
    check_executables: bool = True,
    require_mod_config: bool = False,
    require_manifest: bool = False,
) -> dict[str, str | None]:
    if not os.path.isdir(mod_root):
        raise ValueError("mod_root_not_directory")
    _flatten_single_child_directories(mod_root)
    meta_path, mod_config_path, icon_path = (
        find_deltamod_info_file(mod_root),
        _find_file_recursive(mod_root, MOD_CONFIG_FILENAME),
        _find_file_recursive(mod_root, ICON_PNG_FILENAME),
    )
    if require_manifest and not meta_path:
        raise FileNotFoundError("manifest_missing")
    if require_mod_config and not mod_config_path:
        raise FileNotFoundError("mod_config_missing")
    if check_executables:
        _ensure_no_prohibited_files(mod_root)
    return {
        "meta_path": meta_path,
        "mod_config_path": mod_config_path,
        "icon_path": icon_path,
    }


def _flatten_single_child_directories(root: str):
    while True:
        try:
            entries = [
                e
                for e in os.listdir(root)
                if e not in (".", "..") and not e.startswith("__MACOSX")
            ]
        except OSError:
            return
        files, dirs = (
            [e for e in entries if os.path.isfile(os.path.join(root, e))],
            [e for e in entries if os.path.isdir(os.path.join(root, e))],
        )
        if files or len(dirs) != 1:
            return
        child = os.path.join(root, dirs[0])
        try:
            for item in os.listdir(child):
                src, dst = os.path.join(child, item), os.path.join(root, item)
                if os.path.exists(dst):
                    safe_rmtree(dst) if os.path.isdir(dst) else safe_remove(dst)
                safe_move(src, dst)
            os.rmdir(child)
        except OSError:
            return


def _find_file_recursive(root: str, filename: str) -> str | None:
    fn_lower = filename.lower()
    for r, _, files in os.walk(root):
        for f in files:
            if f.lower() == fn_lower:
                return os.path.join(r, f)
    return None


def _ensure_no_prohibited_files(root: str):
    prohibited = {".exe", ".js", ".ts", ".bat", ".cmd"}
    for r, _, files in os.walk(root):
        for f in files:
            if os.path.splitext(f)[1].lower() in prohibited:
                raise ValueError(f"prohibited_file:{os.path.join(r, f)}")


def sanitize_filename(name: str) -> str:
    return re.sub('[\\\\/*?:"<>|]', "", name).strip()


def _cleanup_tmp(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def save_json(
    path: str, data: dict, indent: int = 2, max_retries: int = 5, delay: float = 0.1
) -> None:
    """Save JSON data to file with retry logic."""
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    to_save = data.copy() if isinstance(data, dict) else data
    if isinstance(to_save, dict) and (
        path.endswith("mod_config.json")
        or (path.endswith("config.json") and ("mod_key" in to_save or "key" in to_save))
    ):
        if "mod_key" in to_save:
            if "key" not in to_save:
                to_save["key"] = to_save["mod_key"]
            del to_save["mod_key"]
        if "modgame" in to_save and "game" in to_save:
            del to_save["modgame"]
    tmp = os.path.join(
        dir_path or ".",
        f"{os.path.basename(path)}.{os.getpid()}.{threading.get_ident()}.tmp",
    )
    for attempt in range(max_retries):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(to_save, f, indent=indent, ensure_ascii=False)
            if os.path.exists(path):
                _fix_windows_permissions(path)
            os.replace(tmp, path)
            return
        except (PermissionError, OSError) as e:
            if attempt < max_retries - 1:
                logging.debug(
                    f"save_json: Attempt {attempt + 1}/{max_retries} failed for {path}: {e}, retrying..."
                )
                time.sleep(delay * (attempt + 1))
                _cleanup_tmp(tmp)
            else:
                _cleanup_tmp(tmp)
                raise
        except (TypeError, ValueError) as e:
            _cleanup_tmp(tmp)
            raise ValueError(f"Data is not JSON-serializable: {e}") from e


def load_json(path: str, migrate_config: bool = True) -> dict:
    """Load JSON file with optional config migration."""
    try:
        if (
            migrate_config
            and path.endswith("mod_config.json")
            and not os.path.exists(path)
        ):
            l_path = path.replace("mod_config.json", "config.json")
            if os.path.exists(l_path):
                path = l_path
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if migrate_config and isinstance(data, dict):
            m = False
            is_cfg = path.endswith("mod_config.json") or (
                path.endswith("config.json") and ("mod_key" in data or "key" in data)
            )
            if is_cfg:
                for k, nk in [
                    ("mod_key", "key"),
                    ("modgame", "game"),
                    ("chapters", "files"),
                ]:
                    if k in data:
                        if nk not in data:
                            data[nk] = data.pop(k)
                        else:
                            del data[k]
                        m = True
                if "is_demo_mod" in data and "game" not in data:
                    data["game"] = (
                        "deltarunedemo" if data.get("is_demo_mod") else "deltarune"
                    )
                    m = True
                    del data["is_demo_mod"]
                if "tags" in data:
                    t = data["tags"]
                    if isinstance(t, list) and "translation" in t:
                        data["tags"] = [
                            ("textedit" if x == "translation" else x) for x in t
                        ]
                        m = True
                    elif t == "translation":
                        data["tags"] = "textedit"
                        m = True
            if m:
                save_json(path, data)
        return data
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError) as e:
        if isinstance(e, json.JSONDecodeError):
            bak = f"{path}.invalid.bak"
            with contextlib.suppress(OSError):
                os.replace(path, bak)
            logging.warning(f"Corrupted JSON, backed up to {bak}")
        elif not isinstance(e, FileNotFoundError):
            logging.warning(f"Error loading JSON {path}: {e}")
        return {}
    except Exception as e:
        logging.error(f"Error loading JSON {path}: {e}", exc_info=True)
        return {}


def remove_archive_extension(filename: str) -> str:
    fl = filename.lower()
    return (
        filename[:-7]
        if fl.endswith(".tar.gz")
        else (
            filename[:-9] if fl.endswith(".tar.lzma") else os.path.splitext(filename)[0]
        )
    )


def get_chapter_folder_name(chapter_id, game=None) -> str:
    cid = str(chapter_id)
    from models.game_modes import get_game

    game_def = get_game(game) if game else None
    if game_def:
        return game_def.get_folder_name(cid)
    if "_" in cid:
        prefix = cid.rsplit("_", 1)[0]
        game_def = get_game(prefix)
        if game_def:
            return game_def.get_folder_name(cid)
        return f"chapter_{cid.rsplit('_', 1)[1]}"
    game_def = get_game(cid)
    if game_def:
        return game_def.get_folder_name(cid)
    return cid


def chapter_id_to_file_key(chapter_id) -> str:
    """Convert chapter_id to the file key used in mod config 'files' dict."""
    cid = str(chapter_id)
    from models.game_modes import get_game

    for lookup in (cid, cid.rsplit("_", 1)[0] if "_" in cid else None):
        if lookup:
            game_def = get_game(lookup)
            if game_def:
                tab = game_def.get_tab(cid)
                if tab:
                    return tab.files_key
    if "_" in cid:
        return cid.rsplit("_", 1)[1]
    return cid


def get_unique_mod_dir(mods_dir, mod_name):
    sanitized = sanitize_filename(mod_name)
    if not os.path.exists(os.path.join(mods_dir, sanitized)):
        return sanitized
    counter = 1
    while os.path.exists(os.path.join(mods_dir, f"{sanitized}_{counter}")):
        counter += 1
    return f"{sanitized}_{counter}"


def ensure_writable(path: str) -> bool:
    try:
        if os.path.exists(path):
            st = os.stat(path)
            os.chmod(path, st.st_mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWRITE)
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for name in dirs + files:
                    p = os.path.join(root, name)
                    try:
                        st = os.stat(p)
                        os.chmod(
                            p, st.st_mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWRITE
                        )
                    except OSError, PermissionError:
                        continue
        return True
    except OSError, PermissionError:
        return False


def get_file_filter(filter_type: str) -> str:
    filter_extensions = {
        "image_files": "*.jpg *.png *.bmp *.gif *.webp *.ico *.jpeg",
        "background_images": "*.jpg *.png *.bmp *.gif *.webp *.ico *.jpeg *.mp4 *.webm *.avi *.mkv *.mov *.m4v *.3gp *.mpg *.mpeg *.flv *.wmv",
        "xdelta_files": "*.xdelta *.vcdiff",
        "data_files": "*.win *.unx *.ios *.droid *.xdelta *.vcdiff *.csx *.zip",
        "archive_files": "*.zip *.rar *.7z *.tar.gz *.tar.bz2 *.tar.xz *.tar *.tgz *.tbz2 *.txz *.lzma",
        "all_files": "*",
        "extended_archives": "*.zip *.rar *.7z *.tar.gz *.tar.bz2 *.tar.xz *.tar *.tgz *.tbz2 *.txz *.lzma",
        "game_files": "*.exe",
        "text_files": "*.txt",
    }

    def tr(key):
        return key.replace("file_descriptions.", "").replace("_", " ").title()

    filter_descriptions = {
        "image_files": tr("file_descriptions.image_files"),
        "background_images": tr("file_descriptions.background_images"),
        "xdelta_files": tr("file_descriptions.xdelta_files"),
        "data_files": tr("file_descriptions.data_files"),
        "archive_files": tr("file_descriptions.archives"),
        "extended_archives": tr("file_descriptions.archives"),
        "game_files": tr("file_descriptions.game_files"),
        "text_files": tr("file_descriptions.text_files"),
        "all_files": tr("file_descriptions.all_files"),
    }
    extensions = filter_extensions.get(filter_type, "*")
    description = filter_descriptions.get(filter_type, filter_type)
    all_files_desc = filter_descriptions.get("all_files", "All files")
    return f"{description} ({extensions});;{all_files_desc} (*)"


def find_deltamod_info_file(directory: str) -> str | None:
    for name in (META_JSON_FILENAME, LEGACY_META_JSON_FILENAME):
        path = os.path.join(directory, name)
        if os.path.exists(path):
            return path
    return None


def has_deltamod_info_file(file_list: list[str] | set[str]) -> bool:
    file_set = set(file_list)
    return META_JSON_FILENAME in file_set or LEGACY_META_JSON_FILENAME in file_set


def check_filename_is_deltamod_info(filename: str) -> bool:
    return filename.lower() in {
        META_JSON_FILENAME.lower(),
        LEGACY_META_JSON_FILENAME.lower(),
    }


def _ensure_dst_dir(dst: str, op_name: str) -> bool:
    dst_dir = os.path.dirname(dst)
    if dst_dir and not os.path.exists(dst_dir):
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError as e:
            logging.warning(f"{op_name}: Failed to create dest dir {dst_dir}: {e}")
            return False
    return True


def safe_copy(src: str, dst: str, max_retries: int = 5, delay: float = 0.1) -> bool:
    try:
        if os.path.abspath(src) == os.path.abspath(dst):
            return True
    except Exception as e:
        logging.debug(
            f"safe_copy: failed to compare source/destination paths {src} -> {dst}: {e}",
            exc_info=True,
        )
    if not _ensure_dst_dir(dst, "safe_copy"):
        return False
    try:
        _retry_operation(
            lambda: shutil.copy2(src, dst),
            max_retries,
            delay,
            "safe_copy",
            f"{src} -> {dst}",
        )
        return True
    except Exception:
        return False


def safe_remove(path: str, max_retries: int = 5, delay: float = 0.1) -> bool:
    if not os.path.exists(path):
        return True

    def do_remove():
        _fix_windows_permissions(path)
        os.remove(path)

    try:
        _retry_operation(do_remove, max_retries, delay, "safe_remove", path)
        return True
    except Exception:
        return False


def safe_move(src: str, dst: str, max_retries: int = 5, delay: float = 0.1) -> bool:
    if not os.path.exists(src):
        return False
    if not _ensure_dst_dir(dst, "safe_move"):
        return False

    def do_move():
        if os.path.isfile(src):
            _fix_windows_permissions(src)
        shutil.move(src, dst)

    try:
        _retry_operation(do_move, max_retries, delay, "safe_move", f"{src} -> {dst}")
        return True
    except Exception:
        return False


def _rmtree_error_handler(func, path, _):
    if IS_WINDOWS_PLATFORM:
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            func(path)
        except OSError:
            pass


def safe_rmtree(path: str, max_retries: int = 3, delay: float = 0.5) -> bool:
    if not os.path.exists(path):
        return True
    if not os.path.isdir(path):
        return safe_remove(path, max_retries, delay)
    import sys

    rmtree_kwargs = (
        {"onexc": _rmtree_error_handler}
        if sys.version_info >= (3, 12)
        else {
            "onerror": lambda func, path, exc_info: _rmtree_error_handler(
                func, path, exc_info[1]
            )
        }
    )
    try:
        _retry_operation(
            lambda: shutil.rmtree(path, **rmtree_kwargs),
            max_retries,
            delay,
            "safe_rmtree",
            path,
        )
        return True
    except Exception:
        if not IS_WINDOWS_PLATFORM:
            try:
                renamed = os.path.join(
                    tempfile.gettempdir(), f"deltahub_cleanup_{int(time.time())}"
                )
                if not os.path.exists(renamed):
                    os.rename(path, renamed)
                    threading.Thread(
                        target=lambda: (
                            time.sleep(5),
                            shutil.rmtree(renamed, ignore_errors=True),
                        ),
                        daemon=True,
                    ).start()
                    return True
            except Exception as e:
                logging.debug(
                    f"safe_rmtree: failed to rename {path} for deferred cleanup: {e}",
                    exc_info=True,
                )
        return False


def migrate_mod_config(mod_dir: str) -> bool:
    old_config_path = os.path.join(mod_dir, LEGACY_MOD_CONFIG_FILENAME)
    config_path = os.path.join(mod_dir, MOD_CONFIG_FILENAME)
    if os.path.exists(old_config_path) and (not os.path.exists(config_path)):
        success = safe_move(old_config_path, config_path)
        if success:
            logging.info(
                f"Successfully migrated mod config.json to mod_config.json in {os.path.basename(mod_dir)}"
            )
        else:
            logging.error(
                f"Failed to migrate mod config.json to mod_config.json in {os.path.basename(mod_dir)}"
            )
        return success
    return True
