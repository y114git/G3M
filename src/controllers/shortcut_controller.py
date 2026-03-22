"""Controller for creating game launch shortcuts."""

import base64
import json
import logging
import os
import platform
import stat
import sys

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from services.game_detection_service import get_chapter_id_for_game_mode
from services.localization_service import tr
from ui.common.styling import get_border_radius
from utils.mod_utils import get_mod_key, get_mod_name


def _get_platform_extension() -> str:
    return {"Windows": ".vbs", "Darwin": ".command"}.get(platform.system(), ".sh")


def _collect_chapter_data(
    used_mods_service, app_state
) -> tuple[dict[str, str | None], dict] | None:
    """Collect mod selections for ALL chapters. Returns (chapter_mods, chapter_mod_objects) or None if >1 mod per chapter."""
    game_mode = app_state.game_mode
    is_chapter_mode = app_state.current_mode == "chapter"
    chapter_mods, chapter_objs = {}, {}

    if is_chapter_mode and game_mode.is_multi_tab:
        for tab in game_mode.tabs:
            mods = used_mods_service.get_used_mods_list(tab.tab_id)
            if len(mods) > 1:
                return None
            chapter_objs[tab.tab_id] = mods[0] if mods else None
            chapter_mods[tab.tab_id] = get_mod_key(mods[0]) if mods else None
    elif not is_chapter_mode and game_mode.is_multi_tab:
        default_id = get_chapter_id_for_game_mode(game_mode)
        mods = used_mods_service.get_used_mods_list(default_id)
        if len(mods) > 1:
            return None
        mod = mods[0] if mods else None
        for tab in game_mode.tabs:
            has_data = (
                mod
                and hasattr(mod, "get_chapter_data")
                and mod.get_chapter_data(tab.tab_id)
            )
            chapter_objs[tab.tab_id] = mod if has_data else None
            chapter_mods[tab.tab_id] = get_mod_key(mod) if has_data else None
    else:
        default_id = get_chapter_id_for_game_mode(game_mode)
        mods = used_mods_service.get_used_mods_list(default_id)
        if len(mods) > 1:
            return None
        chapter_objs[default_id] = mods[0] if mods else None
        chapter_mods[default_id] = get_mod_key(mods[0]) if mods else None

    return chapter_mods, chapter_objs


def _build_shortcut_config(app_state, chapter_mods: dict[str, str | None]) -> dict:
    """Build the JSON config dict from current app state."""
    is_chapter_mode = app_state.current_mode == "chapter"
    return {
        "game_id": app_state.game_mode.game_id,
        "chapter_mode": is_chapter_mode,
        "launch_via_steam": app_state.local_config.get("launch_via_steam", False),
        "use_portproton": app_state.local_config.get("use_portproton", False),
        "direct_launch_chapter": app_state.local_config.get("direct_launch_chapter", "")
        if is_chapter_mode
        else "",
        "chapter_mods": chapter_mods,
    }


def _generate_shortcut_filename(game_mode, chapter_mod_objects: dict) -> str:
    """Generate a safe default filename for the shortcut (without extension)."""
    game_name = game_mode.display_name.replace(" ", "_")
    selected_mod = next((m for m in chapter_mod_objects.values() if m), None)
    mod_part = (
        get_mod_name(selected_mod, "mod").replace(" ", "_")
        if selected_mod
        else "Vanilla"
    )
    base = f"DELTAHUB_{game_name}_{mod_part}"
    return "".join(c for c in base if c.isalnum() or c in ("_", "-"))


def _write_shortcut_file(filepath: str, shortcut_config: dict) -> str:
    """Write a single self-contained shortcut file with embedded config. Returns the path written."""
    exe_path = sys.executable
    script_path = (
        None
        if getattr(sys, "frozen", False)
        else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))
    )
    config_b64 = base64.b64encode(
        json.dumps(shortcut_config, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    system = platform.system()

    if system == "Windows":
        vbs_cmd = f'"""" & "{exe_path}" & ""' + (
            f' "" & "{script_path}" & """"' if script_path else '""'
        )
        content = f'Set shell = CreateObject("WScript.Shell")\r\nshell.Run {vbs_cmd} & " --shortcut {config_b64}", 0, False\r\n'
    else:
        bash_cmd = f'"{exe_path}"' + (f' "{script_path}"' if script_path else "")
        decode_flag = "-D" if system == "Darwin" else "-d"
        content = f'#!/bin/bash\nCONFIG=$(echo "{config_b64}" | base64 {decode_flag})\n{bash_cmd} --shortcut "$CONFIG" &\n'

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    if system != "Windows":
        os.chmod(
            filepath,
            os.stat(filepath).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH,
        )

    return filepath


class ShortcutDialog(QDialog):
    """Confirmation dialog for shortcut creation."""

    def __init__(
        self, game_mode, chapter_mod_objects: dict, shortcut_config: dict, parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("shortcut.dialog_title"))
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        header = QLabel(tr("shortcut.dialog_header"))
        header.setWordWrap(True)
        layout.addWidget(header)

        summary = QLabel(
            self._build_summary(game_mode, chapter_mod_objects, shortcut_config)
        )
        summary.setWordWrap(True)
        _cfg = (
            getattr(getattr(parent, "app_state", None), "local_config", None)
            if parent
            else None
        )
        br = get_border_radius(_cfg)
        summary.setStyleSheet(
            f"padding: 8px; background: rgba(0,0,0,0.1); border-radius: {br}px;"
        )
        layout.addWidget(summary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_summary(self, gm, chapter_objs, cfg) -> str:
        lines = [f"{tr('shortcut.dialog_game')}: {gm.display_name}"]

        if cfg.get("chapter_mode") and gm.is_multi_tab:
            for tab in gm.tabs:
                mod = chapter_objs.get(tab.tab_id)
                mod_name = (
                    get_mod_name(mod, "Unknown") if mod else tr("shortcut.vanilla")
                )
                lines.append(f"  {tr(tab.name_key)}: {mod_name}")
        else:
            any_mod = next((m for m in chapter_objs.values() if m), None)
            mod_name = (
                get_mod_name(any_mod, "Unknown") if any_mod else tr("shortcut.vanilla")
            )
            lines.append(f"{tr('shortcut.dialog_mod')}: {mod_name}")

        direct_ch = cfg.get("direct_launch_chapter", "")
        if (
            direct_ch
            and "_" in direct_ch
            and not direct_ch.endswith("_0")
            and cfg.get("chapter_mode")
        ):
            tab = gm.get_tab(direct_ch)
            lines.append(
                f"{tr('shortcut.dialog_direct_launch')}: {tr(tab.name_key) if tab else direct_ch}"
            )

        launch = (
            "Steam"
            if cfg.get("launch_via_steam")
            else "PortProton"
            if cfg.get("use_portproton")
            else tr("shortcut.direct")
        )
        lines.append(f"{tr('shortcut.dialog_launch')}: {launch}")

        return "\n".join(lines)

    def relocalize_ui(self):
        pass


def _validate_shortcut_prerequisites(app_state, has_any_mod: bool) -> str | None:
    """Return an error message string if shortcut cannot be created, or None if OK."""
    game_path = app_state.game_mode.get_game_path(app_state.local_config)
    if not game_path or not os.path.isdir(game_path):
        return tr("shortcut.error_no_game_path", game=app_state.game_mode.display_name)
    if has_any_mod:
        from adapters.g3mtool_adapter import G3MToolManager

        if not G3MToolManager().is_available():
            return tr("shortcut.error_g3mtool_unavailable")
    return None


def on_shortcut_button_click(
    app_state, feedback_service, used_mods_service, parent_widget: QWidget
):
    """Handle the Shortcut button click — show dialog, pick file, write shortcut."""
    if not app_state.initialization_completed:
        return

    result = _collect_chapter_data(used_mods_service, app_state)
    if result is None:
        feedback_service.show_message(
            "warning", "common.warning", tr("shortcut.too_many_mods")
        )
        return

    chapter_mods, chapter_mod_objects = result
    error = _validate_shortcut_prerequisites(app_state, any(chapter_mods.values()))
    if error:
        feedback_service.show_message("warning", "common.warning", error)
        return

    shortcut_config = _build_shortcut_config(app_state, chapter_mods)
    if (
        ShortcutDialog(
            app_state.game_mode, chapter_mod_objects, shortcut_config, parent_widget
        ).exec()
        != QDialog.DialogCode.Accepted
    ):
        return

    ext = _get_platform_extension()
    default_name = (
        _generate_shortcut_filename(app_state.game_mode, chapter_mod_objects) + ext
    )
    ext_label = {"vbs": "VBScript", "command": "Command", "sh": "Shell Script"}.get(
        ext.lstrip("."), "Script"
    )

    filepath, _ = QFileDialog.getSaveFileName(
        parent_widget,
        tr("shortcut.select_folder"),
        default_name,
        f"{ext_label} (*{ext})",
    )
    if not filepath:
        return

    try:
        _write_shortcut_file(filepath, shortcut_config)
        logging.info(f"Shortcut created: {filepath}")
        feedback_service.show_message(
            "info", "shortcut.dialog_title", tr("shortcut.created", path=filepath)
        )
    except Exception as e:
        logging.error(f"Failed to create shortcut: {e}", exc_info=True)
        feedback_service.show_message(
            "error", "errors.error", tr("shortcut.creation_failed", error=str(e))
        )
