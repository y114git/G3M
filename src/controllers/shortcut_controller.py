"""Controller for creating game launch shortcuts."""

import base64
import json
import logging
import os
import platform
import stat
import sys

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from services.game_detection_service import get_chapter_id_for_game_mode
from services.localization_service import tr
from services.shortcut_plugin_service import (
    ShortcutPluginContext,
)
from ui.common.styling import get_border_radius
from utils.mod_utils import get_mod_id, get_mod_name
from utils.process_utils import format_filesystem_error


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
            chapter_mods[tab.tab_id] = get_mod_id(mods[0]) if mods else None
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
            chapter_mods[tab.tab_id] = get_mod_id(mod) if has_data else None
    else:
        default_id = get_chapter_id_for_game_mode(game_mode)
        mods = used_mods_service.get_used_mods_list(default_id)
        if len(mods) > 1:
            return None
        chapter_objs[default_id] = mods[0] if mods else None
        chapter_mods[default_id] = get_mod_id(mods[0]) if mods else None

    return chapter_mods, chapter_objs


def _build_shortcut_config(
    app_state,
    chapter_mods: dict[str, str | None],
    plugin_context: ShortcutPluginContext | None = None,
) -> dict:
    """Build the JSON config dict from current app state."""
    is_chapter_mode = app_state.current_mode == "chapter"
    config = {
        "game_id": app_state.game_mode.game_id,
        "chapter_mode": is_chapter_mode,
        "launch_via_steam": app_state.local_config.get("launch_via_steam", False),
        "use_portproton": app_state.local_config.get("use_portproton", False),
        "direct_launch_chapter": app_state.local_config.get("direct_launch_chapter", "")
        if is_chapter_mode
        else "",
        "chapter_mods": chapter_mods,
    }
    if plugin_context and plugin_context.enabled:
        config["plugins_enabled"] = True
        config["plugin_states"] = plugin_context.export_states()
        config["plugin_summary"] = plugin_context.export_summary()
    else:
        config["plugins_enabled"] = False
        config["plugin_states"] = {}
        config["plugin_summary"] = []
    return config


def _collect_shortcut_plugin_blocks(
    plugin_runtime_service,
    plugin_context: ShortcutPluginContext,
) -> list[dict]:
    if not plugin_runtime_service:
        return []
    results = plugin_runtime_service.execute_hook("shortcut_dialog", plugin_context)
    blocks: list[dict] = []
    for result in results:
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    blocks.append(dict(item))
        elif isinstance(result, dict):
            blocks.append(dict(result))
    return blocks


def _generate_shortcut_filename(game_mode, chapter_mod_objects: dict) -> str:
    """Generate a safe default filename for the shortcut (without extension)."""
    game_name = game_mode.display_name.replace(" ", "_")
    selected_mod = next((m for m in chapter_mod_objects.values() if m), None)
    mod_part = (
        get_mod_name(selected_mod, "mod").replace(" ", "_")
        if selected_mod
        else "Vanilla"
    )
    base = f"G3M_{game_name}_{mod_part}"
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
            os.stat(filepath).st_mode | stat.S_IXUSR,
        )
    return filepath


class ShortcutDialog(QDialog):
    """Confirmation dialog for shortcut creation."""

    def __init__(
        self,
        game_mode,
        chapter_mod_objects: dict,
        shortcut_config: dict,
        plugin_context: ShortcutPluginContext | None = None,
        plugin_blocks: list[dict] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._game_mode = game_mode
        self._chapter_mod_objects = chapter_mod_objects
        self._shortcut_config = shortcut_config
        self._plugin_context = plugin_context
        self._plugin_blocks = list(plugin_blocks or [])
        self._plugin_input_widgets: dict[tuple[str, str], QWidget] = {}
        self.setWindowTitle(tr("shortcut.dialog_title"))
        self.setMinimumWidth(540)
        self.setMinimumHeight(220)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        self.header_label = QLabel(tr("shortcut.dialog_header"))
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        self.plugin_actions_checkbox = QCheckBox(self)
        self.plugin_actions_checkbox.setChecked(
            (not bool(plugin_context.enabled)) if plugin_context else False
        )

        self.summary_label = QLabel(
            self._build_summary(game_mode, chapter_mod_objects, shortcut_config)
        )
        self.summary_label.setWordWrap(True)
        cfg = (
            getattr(getattr(parent, "app_state", None), "local_config", None)
            if parent
            else None
        )
        br = get_border_radius(cfg)
        self.summary_label.setStyleSheet(
            f"padding: 8px; background: rgba(0,0,0,0.1); border-radius: {br}px;"
        )
        layout.addWidget(self.summary_label)

        self.plugin_section_widget = QWidget(self)
        self.plugin_section_layout = QVBoxLayout(self.plugin_section_widget)
        self.plugin_section_layout.setContentsMargins(0, 0, 0, 0)
        self.plugin_section_layout.setSpacing(8)
        self._build_plugin_section()
        layout.addWidget(self.plugin_section_widget)
        self.plugin_actions_checkbox.toggled.connect(
            lambda _checked: self._update_plugin_visibility()
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(12)
        footer_layout.addWidget(self.plugin_actions_checkbox)
        footer_layout.addStretch(1)
        footer_layout.addWidget(buttons)
        layout.addLayout(footer_layout)
        self.relocalize_ui()
        self.apply_theme()
        self.scale_ui()

    def _build_summary(self, gm, chapter_objs, cfg) -> str:
        lines = [f"{tr('shortcut.dialog_game')}: {gm.display_name}"]

        if cfg.get("chapter_mode") and gm.is_multi_tab:
            for tab in gm.tabs:
                mod = chapter_objs.get(tab.tab_id)
                mod_name = (
                    get_mod_name(mod, "Unknown") if mod else tr("shortcut.vanilla")
                )
                lines.append(f" {tr(tab.name_key)}: {mod_name}")
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
        if (
            self._plugin_context
            and self.plugin_actions_enabled()
            and self._plugin_context.summary_lines
        ):
            for label, value in self._plugin_context.summary_lines:
                lines.append(f"{label}: {value}")

        return "\n".join(lines)

    def _build_plugin_section(self) -> None:
        while self.plugin_section_layout.count():
            item = self.plugin_section_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._plugin_input_widgets.clear()
        for block in self._plugin_blocks:
            widget = self._create_plugin_block_widget(block)
            if widget is not None:
                self.plugin_section_layout.addWidget(widget)
        self.plugin_section_layout.addStretch(1)

    def _create_plugin_block_widget(self, block: dict) -> QWidget | None:
        block_type = str(block.get("type", "")).strip()
        plugin_id = str(block.get("plugin_id", "")).strip()
        label_text = str(block.get("label", "")).strip()
        key = str(block.get("key", "")).strip()
        if block_type == "text":
            label = QLabel(f"{label_text}: {block.get('value', '')}", self.plugin_section_widget)
            label.setWordWrap(True)
            return label
        if block_type == "select" and plugin_id and key:
            wrapper = QFrame(self.plugin_section_widget)
            row = QHBoxLayout(wrapper)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)
            label = QLabel(label_text, wrapper)
            combo = QComboBox(wrapper)
            for option in block.get("options", []) or []:
                if not isinstance(option, dict):
                    continue
                combo.addItem(str(option.get("label", "")), option.get("value"))
            current_value = block.get("value")
            for index in range(combo.count()):
                if combo.itemData(index) == current_value:
                    combo.setCurrentIndex(index)
                    break
            self._plugin_input_widgets[plugin_id, key] = combo
            row.addWidget(label)
            row.addWidget(combo, 1)
            return wrapper
        if block_type == "checkbox" and plugin_id and key:
            checkbox = QCheckBox(label_text, self.plugin_section_widget)
            checkbox.setChecked(bool(block.get("value")))
            self._plugin_input_widgets[plugin_id, key] = checkbox
            return checkbox
        return None

    def _update_plugin_visibility(self) -> None:
        enabled = self.plugin_actions_enabled()
        self.plugin_section_widget.setVisible(enabled and bool(self._plugin_blocks))
        self.summary_label.setText(
            self._build_summary(
                self._game_mode,
                self._chapter_mod_objects,
                self._shortcut_config,
            )
        )
        self.scale_ui()

    def relocalize_ui(self):
        self.setWindowTitle(tr("shortcut.dialog_title"))
        self.header_label.setText(tr("shortcut.dialog_header"))
        self.plugin_actions_checkbox.setText(tr("shortcut.disable_plugin_actions"))
        self.summary_label.setText(
            self._build_summary(
                self._game_mode,
                self._chapter_mod_objects,
                self._shortcut_config,
            )
        )

    def apply_theme(self) -> None:
        cfg = getattr(getattr(self.parent(), "app_state", None), "local_config", None)
        br = get_border_radius(cfg)
        self.setStyleSheet(
            f"""
            QDialog {{
                border-radius: {br}px;
            }}
            QCheckBox {{
                padding-top: 4px;
            }}
            """
        )

    def scale_ui(self) -> None:
        self.layout().activate()
        self.adjustSize()
        self.resize(self.sizeHint())

    def plugin_actions_enabled(self) -> bool:
        return not self.plugin_actions_checkbox.isChecked()

    def collect_plugin_values(self) -> dict[str, dict]:
        if not self.plugin_actions_enabled():
            return {}
        result: dict[str, dict] = {}
        for (plugin_id, key), widget in self._plugin_input_widgets.items():
            result.setdefault(plugin_id, {})
            if isinstance(widget, QComboBox):
                result[plugin_id][key] = widget.currentData()
            elif isinstance(widget, QCheckBox):
                result[plugin_id][key] = bool(widget.isChecked())
        return result


def _validate_shortcut_prerequisites(app_state, has_any_mod: bool) -> str | None:
    """Return an error message string if shortcut cannot be created, or None if OK."""
    game_path = app_state.game_mode.get_game_path(app_state.local_config)
    if not game_path or not os.path.isdir(game_path):
        return (
            f"Game path for {app_state.game_mode.display_name} is not set. "
            "Please configure the game path in settings first."
        )
    if has_any_mod:
        from adapters.g3mtool_adapter import G3MToolManager

        g3mtool = G3MToolManager(app_state)
        if not g3mtool.is_available():
            return g3mtool.get_unavailable_reason()
    return None


def on_shortcut_button_click(
    app_state, feedback_service, used_mods_service, parent_widget: QWidget
):
    """Handle the Shortcut button click - show dialog, pick file, write shortcut."""
    if not app_state.initialization_completed:
        return

    result = _collect_chapter_data(used_mods_service, app_state)
    if result is None:
        if analytics := getattr(parent_widget, "analytics_service", None):
            analytics.record_action("shortcut_create_blocked", reason="too_many_mods")
        feedback_service.show_message(
            "warning", "common.warning", tr("shortcut.too_many_mods")
        )
        return

    chapter_mods, chapter_mod_objects = result
    error = _validate_shortcut_prerequisites(app_state, any(chapter_mods.values()))
    if error:
        if analytics := getattr(parent_widget, "analytics_service", None):
            analytics.record_action(
                "shortcut_create_blocked",
                reason="prerequisite_failed",
                game=app_state.game_mode.game_id,
            )
        feedback_service.show_message("warning", "common.warning", error)
        return

    plugin_runtime_service = getattr(parent_widget, "plugin_runtime_service", None)
    plugin_context = ShortcutPluginContext(
        {"game_id": app_state.game_mode.game_id},
        enabled=True,
        phase="capture",
    )
    plugin_blocks = _collect_shortcut_plugin_blocks(plugin_runtime_service, plugin_context)
    shortcut_config = _build_shortcut_config(app_state, chapter_mods, None)
    dialog = ShortcutDialog(
        app_state.game_mode,
        chapter_mod_objects,
        shortcut_config,
        plugin_context,
        plugin_blocks,
        parent_widget,
    )
    if (
        dialog.exec()
        != QDialog.DialogCode.Accepted
    ):
        if analytics := getattr(parent_widget, "analytics_service", None):
            analytics.record_action(
                "shortcut_create_cancelled",
                game=app_state.game_mode.game_id,
            )
        return
    if dialog.plugin_actions_enabled():
        for plugin_id, payload in dialog.collect_plugin_values().items():
            plugin_context.set_plugin_state(plugin_id, payload)
        shortcut_config = _build_shortcut_config(app_state, chapter_mods, plugin_context)
    else:
        shortcut_config = _build_shortcut_config(app_state, chapter_mods, None)

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
        if analytics := getattr(parent_widget, "analytics_service", None):
            analytics.record_action(
                "shortcut_save_cancelled",
                game=app_state.game_mode.game_id,
            )
        return

    try:
        _write_shortcut_file(filepath, shortcut_config)
        if analytics := getattr(parent_widget, "analytics_service", None):
            analytics.record_action(
                "shortcut_created",
                game=app_state.game_mode.game_id,
                chapter_mode="yes" if shortcut_config.get("chapter_mode") else "no",
                launch="steam"
                if shortcut_config.get("launch_via_steam")
                else "portproton"
                if shortcut_config.get("use_portproton")
                else "direct",
                plugins="yes" if shortcut_config.get("plugins_enabled") else "no",
            )
        logging.info(f"Shortcut created: {filepath}")
        feedback_service.show_message(
            "info", "shortcut.dialog_title", tr("shortcut.created", path=filepath)
        )
    except Exception as e:
        if analytics := getattr(parent_widget, "analytics_service", None):
            analytics.record_action(
                "shortcut_create_failed",
                game=app_state.game_mode.game_id,
                reason="write_failed",
            )
        logging.error(f"Failed to create shortcut: {e}", exc_info=True)
        feedback_service.show_message(
            "error",
            "errors.error",
            tr("shortcut.creation_failed", error=format_filesystem_error(e, path=filepath)),
        )
