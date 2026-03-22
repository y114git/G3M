"""Path resolution and platform-specific utilities."""

import logging
import ntpath
import os
import re
import stat
import sys
from pathlib import Path

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPixmap

from config.constants import CURRENT_PLATFORM, GAME_EXECUTABLES

_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


def get_launcher_dir():
    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.dirname(__file__))


def safe_profile_name(name: str) -> str:
    safe = re.sub(r"[^\w\- ]+", "_", name or "").strip()[:80] or "Default"
    if CURRENT_PLATFORM == "Windows" and safe.upper() in _WINDOWS_RESERVED_NAMES:
        safe = f"{safe}_"
    return safe


def get_user_data_root():
    home = os.path.expanduser("~")
    if CURRENT_PLATFORM == "Windows":
        return ntpath.join(
            os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or home, "DELTAHUB"
        )
    if CURRENT_PLATFORM == "Darwin":
        return os.path.join(home, "Library", "Application Support", "DELTAHUB")
    return os.path.join(home, ".local", "share", "DELTAHUB")


def get_user_profiles_dir():
    return os.path.join(get_user_data_root(), "profiles")


def get_profile_mods_root(name: str = "Default"):
    return os.path.join(get_user_profiles_dir(), safe_profile_name(name))


def get_user_profile_dir(name: str = "Default"):
    return get_profile_mods_root(name)


def get_user_mods_dir():
    return os.path.join(get_user_data_root(), "mods")


def get_user_plugins_dir():
    return os.path.join(get_user_data_root(), "plugins")


def get_user_lang_dir():
    return os.path.join(get_user_data_root(), "lang")


def get_user_themes_dir():
    return os.path.join(get_user_data_root(), "themes")


def resource_path(relative_path):
    is_frozen = getattr(sys, "frozen", False)
    meipass = getattr(sys, "_MEIPASS", None)
    if is_frozen and meipass:
        base = os.path.join(meipass, "src")
    else:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base, relative_path)


def resolve_game_executable(base_dir, executable_type="deltarune"):
    try:
        if not base_dir or not os.path.isdir(base_dir):
            return None
        search_order = {
            "Windows": ["windows", "linux", "mac"],
            "Linux": ["linux", "windows", "mac"],
            "Darwin": ["mac", "linux", "windows"],
        }.get(CURRENT_PLATFORM, ["windows", "linux", "mac"])
        for plat_key in search_order:
            for name in GAME_EXECUTABLES.get(executable_type, {}).get(plat_key, ()):
                if plat_key == "mac":
                    app = (
                        base_dir
                        if base_dir.endswith(".app") and os.path.isdir(base_dir)
                        else None
                    )
                    if not app:
                        candidate = os.path.join(base_dir, name)
                        if os.path.isdir(candidate):
                            app = candidate
                    if app:
                        return app
                else:
                    exe_path = os.path.join(base_dir, name)
                    if os.path.isfile(exe_path) and (
                        plat_key != "linux"
                        or name.endswith(".exe")
                        or os.access(exe_path, os.X_OK)
                    ):
                        return exe_path
        return None
    except Exception as e:
        logging.debug(f"resolve_game_executable: failed for {base_dir}: {e}")
        return None


def find_chapter_resource_dir(
    base_dir, chapter_id: str, macos_app_names=("DELTARUNE.app", "DELTARUNEdemo.app")
):
    try:
        if not base_dir or not chapter_id:
            return None
        target_base = base_dir
        if CURRENT_PLATFORM == "Darwin":
            if not target_base.endswith(".app"):
                for app_name in macos_app_names:
                    candidate = os.path.join(target_base, app_name)
                    if os.path.isdir(candidate):
                        target_base = candidate
                        break
            target_base = os.path.join(target_base, "Contents", "Resources")
            if not os.path.isdir(target_base):
                return None
        if "_" in str(chapter_id):
            _, suffix = chapter_id.rsplit("_", 1)
            if suffix.isdigit() and int(suffix) > 0:
                prefix = f"chapter{suffix}_"
                return next(
                    (
                        os.path.join(target_base, e)
                        for e in os.listdir(target_base)
                        if os.path.isdir(os.path.join(target_base, e))
                        and e.startswith(prefix)
                    ),
                    None,
                )
        return target_base
    except Exception as e:
        logging.debug(
            f"find_chapter_resource_dir: failed for {base_dir}, chapter {chapter_id}: {e}"
        )
        return None


def _match_steam_path(normalized, steam_path):
    try:
        if not normalized or not steam_path:
            return False
        if os.path.exists(steam_path):
            sp = (
                os.path.normpath(os.path.abspath(steam_path)).lower().replace("\\", "/")
            )
            if normalized == sp or normalized.startswith(sp + "/"):
                return True
    except OSError, ValueError:
        pass
    return False


def is_path_in_steam_common(game_path: str, game_name: str) -> bool:
    if not game_path or not os.path.isdir(game_path):
        return False
    try:
        game_path_normalized = os.path.normpath(os.path.abspath(game_path)).lower()
    except OSError, ValueError:
        return False
    path_parts = game_path_normalized.replace("\\", "/").split("/")
    for i, part in enumerate(path_parts):
        if (
            part == "steamapps"
            and i + 2 < len(path_parts)
            and path_parts[i + 1] == "common"
        ):
            return True
    home = os.path.expanduser("~")
    if CURRENT_PLATFORM == "Windows":
        for pf in filter(
            None, [os.getenv("PROGRAMFILES(X86)"), os.getenv("PROGRAMFILES")]
        ):
            if _match_steam_path(
                game_path_normalized,
                os.path.join(pf, "Steam", "steamapps", "common", game_name),
            ):
                return True
    elif CURRENT_PLATFORM == "Linux":
        for sp in [
            os.path.join(home, ".steam", "steam"),
            os.path.join(home, ".local", "share", "Steam"),
            os.path.join(
                home, ".var", "app", "com.valvesoftware.Steam", "data", "Steam"
            ),
        ]:
            if _match_steam_path(
                game_path_normalized, os.path.join(sp, "steamapps", "common", game_name)
            ):
                return True
    elif CURRENT_PLATFORM == "Darwin":
        for sp in [
            os.path.join(home, "Library", "Application Support", "Steam"),
            os.path.join(home, "Steam"),
        ]:
            if _match_steam_path(
                game_path_normalized, os.path.join(sp, "steamapps", "common", game_name)
            ):
                return True
    return False


def _pizza_names(game_name):
    return (
        ["Pizza Tower", "PizzaTower", "pizzatower"]
        if game_name == "Pizza Tower"
        else [game_name]
    )


def autodetect_path(game_name: str) -> str | None:
    if not game_name:
        return None
    if game_name in (
        "UNDERTALE YELLOW",
        "UndertaleYellow",
        "undertaleyellow",
        "SUGARY SPIRE",
        "SugarySpire",
        "sugaryspire",
    ):
        return None
    system, paths, names = CURRENT_PLATFORM, [], _pizza_names(game_name)
    home = os.path.expanduser("~")
    if system == "Windows":
        pf_dirs = [
            p for p in [os.getenv("PROGRAMFILES(X86)"), os.getenv("PROGRAMFILES")] if p
        ]
        for n in names:
            paths.extend(
                os.path.join(p, "Steam", "steamapps", "common", n) for p in pf_dirs
            )
        steam_subs = [
            ["Steam", "steamapps", "common"],
            ["SteamLibrary", "steamapps", "common"],
            ["Program Files", "Steam", "steamapps", "common"],
            ["Program Files (x86)", "Steam", "steamapps", "common"],
        ]
        for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            for sub in steam_subs:
                for n in names:
                    paths.append(os.path.join(f"{drive}:", *sub, n))
    elif system == "Linux":
        steam_bases = [
            f"{home}/.steam/steam",
            f"{home}/.local/share/Steam",
            f"{home}/.var/app/com.valvesoftware.Steam/data/Steam",
        ]
        for sb in steam_bases:
            for n in names:
                paths.append(f"{sb}/steamapps/common/{n}")
        for mount_base in [
            "/mnt",
            "/media",
            "/run/media",
            f"{home}/.steam/steam/steamapps",
        ]:
            if os.path.isdir(mount_base):
                try:
                    for item in os.listdir(mount_base):
                        item_path = os.path.join(mount_base, item)
                        if os.path.isdir(item_path):
                            for sub in [
                                "SteamLibrary/steamapps/common",
                                "steamapps/common",
                            ]:
                                sp = os.path.join(item_path, sub, game_name)
                                if os.path.exists(sp):
                                    paths.append(sp)
                except OSError, PermissionError:
                    pass
        for extra in [
            "/run/media/mmcblk0p1",
            "/run/media/mmcblk1p1",
            "/mnt/steam",
            "/media/steam",
        ]:
            paths.append(f"{extra}/steamapps/common/{game_name}")
    elif system == "Darwin":
        base_paths = [
            f"{home}/Library/Application Support/Steam/steamapps/common",
            "/Applications",
            f"{home}/Steam/steamapps/common",
        ]
        all_bases = []
        for bp in base_paths:
            for n in names:
                all_bases.append(f"{bp}/{n}")
        if game_name.endswith("demo"):
            for parent in filter(os.path.isdir, all_bases):
                for app in [f"{game_name}.app", "DELTARUNE.app"]:
                    fp = os.path.join(parent, app)
                    if os.path.exists(fp):
                        paths.append(fp)
        else:
            candidates = set(names) | {game_name}
            for bp in all_bases:
                for n in candidates:
                    app_path = f"{bp}/{n}.app"
                    if os.path.isdir(app_path):
                        paths.append(app_path)
    return next((p for p in paths if os.path.exists(p)), None)


def fix_macos_python_symlink(app_dir: Path) -> None:
    try:
        if CURRENT_PLATFORM != "Darwin":
            return
        p = app_dir / "Contents" / "Frameworks" / "Python"
        if not p.exists() or p.is_symlink():
            return
        if p.is_file() and p.stat().st_size < 512:
            try:
                target_rel = p.read_text(encoding="utf-8").strip()
            except Exception as e:
                logging.debug(
                    f"fix_macos_python_symlink: failed to read symlink target: {e}"
                )
                py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
                target_rel = f"Python.framework/Versions/{py_ver}/Python"
            p.unlink(missing_ok=True)
            os.symlink(target_rel, p)
            st = os.lstat(p)
            os.chmod(
                p, stat.S_IMODE(st.st_mode) | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )
    except Exception as e:
        logging.debug(f"fix_macos_python_symlink: failed: {e}")


def cleanup_old_updater_files():
    try:
        if not getattr(sys, "frozen", False):
            return
        system = CURRENT_PLATFORM
        current_exe_path = os.path.realpath(sys.executable)
        if system == "Darwin":
            replace_target = os.path.abspath(
                os.path.join(os.path.dirname(current_exe_path), "..", "..")
            )
        else:
            replace_target = current_exe_path
        backup_path = f"{replace_target}.old"
        if os.path.exists(backup_path):
            from utils.file_utils import safe_rmtree

            safe_rmtree(backup_path)
    except Exception as e:
        logging.debug(f"cleanup_old_updater_files: failed: {e}")


def version_sort_key(v: str):
    try:
        s = (v or "").strip().lower()
        m = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?([a-z0-9._-]*)?$", s)
        if m:
            g = m.groups()
            return (
                int(g[0] or 0),
                int(g[1] or 0),
                int(g[2] or 0),
                1 if g[3] else 0,
                g[3] or "",
            )
        p = [int(x) if x.isdigit() else x for x in re.split("[.-]", s)]
        nums = [x for x in p if isinstance(x, int)][:3]
        nums += [0] * (3 - len(nums))
        suff = next((str(x) for x in p if isinstance(x, str)), "")
        return (*nums, 1 if suff else 0, suff)
    except Exception:
        return (0, 0, 0, 0, "")


_ICON_DEFS = {
    "search": ("search_icon.svg", [('fill="#444"', 'fill="{c}"')]),
    "reset": ("reset_icon.svg", [('stroke="#0C0310"', 'stroke="{c}"')]),
    "refresh": ("refresh_icon.svg", [('stroke="#000000"', 'stroke="{c}"')]),
    "checkmark": (
        "checkmark_icon.svg",
        [
            ('fill="#010002"', 'fill="{c}"'),
            ('style="fill:#010002;"', 'style="fill:{c};"'),
        ],
    ),
    "save": ("save_icon.svg", [('fill="#0F0F0F"', 'fill="{c}"')]),
    "delete": ("delete_icon.svg", [('fill="#0F0F0F"', 'fill="{c}"')]),
    "edit": ("edit_icon.svg", [('fill="#0F0F0F"', 'fill="{c}"')]),
    "minimize": ("minimize_icon.svg", [('fill="#0F0F0F"', 'fill="{c}"')]),
    "maximize": ("maximize_icon.svg", [('fill="#0F0F0F"', 'fill="{c}"')]),
    "restore": ("restore_icon.svg", [('fill="#0F0F0F"', 'fill="{c}"')]),
    "cross": ("cross_icon.svg", [('fill="#0F0F0F"', 'fill="{c}"')]),
    "arrow_down": ("arrow_down.svg", [('fill="#e8e9eb"', 'fill="{c}"')]),
    "arrow_up": ("arrow_up.svg", [('fill="#e8e9eb"', 'fill="{c}"')]),
    "add": ("add_icon.svg", [('fill="#0F0F0F"', 'fill="{c}"')]),
    "download": ("download_icon.svg", [('fill="#0F0F0F"', 'fill="{c}"')]),
    "folder": ("folder_icon.svg", [('fill="#0F0F0F"', 'fill="{c}"')]),
    "like": ("like_icon.svg", [('fill="#0F0F0F"', 'fill="{c}"')]),
    "settings": ("settings_icon.svg", [('fill="#0F0F0F"', 'fill="{c}"')]),
    "update": ("update_icon.svg", [('fill="#000000"', 'fill="{c}"')]),
    "filerestore": ("filerestore_icon.svg", [('fill="#000000"', 'fill="{c}"')]),
    "export": ("export_icon.svg", [('fill="#0D0D0D"', 'fill="{c}"')]),
    "external": ("external_icon.svg", [('fill="#0D0D0D"', 'fill="{c}"')]),
    "import": ("import_icon.svg", [('fill="#0D0D0D"', 'fill="{c}"')]),
    "duplicate": ("duplicate_icon.svg", [('fill="#000000"', 'fill="{c}"')]),
    "tool": ("tool_icon.svg", [('stroke="#000000"', 'stroke="{c}"')]),
}


def _replace_svg_color_tokens(
    svg: str, color: str, replacements: list[tuple[str, str]]
) -> str:
    for old, new_tpl in replacements:
        svg = svg.replace(old, new_tpl.format(c=color))
    svg = re.sub(
        r'fill="(?:#(?:0F0F0F|010002|000000|444)|black)"',
        f'fill="{color}"',
        svg,
        flags=re.IGNORECASE,
    )
    svg = re.sub(
        r'stroke="(?:#(?:0C0310|000000)|black)"',
        f'stroke="{color}"',
        svg,
        flags=re.IGNORECASE,
    )
    svg = re.sub(
        r'style="fill:\s*(?:#(?:0F0F0F|010002|000000|444)|black);?"',
        f'style="fill:{color};"',
        svg,
        flags=re.IGNORECASE,
    )
    svg = re.sub(
        r'<svg([^>]*?)\bfill="(?:#(?:0F0F0F|010002|000000|444)|black)"',
        f'<svg\\1fill="{color}"',
        svg,
        flags=re.IGNORECASE,
    )
    return svg


def colored_icon(name: str, color: str) -> QIcon:
    """Create a themed QIcon by replacing color tokens in an SVG asset."""
    defn = _ICON_DEFS.get(name)
    if not defn:
        return QIcon()
    svg_file, replacements = defn[0], defn[1]
    svg_path = resource_path(f"assets/icons/{svg_file}")
    try:
        with open(svg_path, encoding="utf-8", errors="replace") as f:
            svg = f.read()
        svg = re.sub(r"<\?xml[^?]*\?>", "", svg, count=1)
        svg = _replace_svg_color_tokens(svg, color, replacements)
        svg_bytes = QByteArray(svg.encode("utf-8"))
        from PyQt6.QtGui import QPainter
        from PyQt6.QtSvg import QSvgRenderer

        renderer = QSvgRenderer(svg_bytes)
        if not renderer.isValid():
            return QIcon(svg_path)
        pixmap = QPixmap(128, 128)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon = QIcon()
        icon.addPixmap(pixmap, QIcon.Mode.Normal)
        icon.addPixmap(pixmap, QIcon.Mode.Disabled)
        return icon
    except Exception as e:
        logging.debug(f"colored_icon: failed to render {name}: {e}")
        return QIcon(svg_path)
