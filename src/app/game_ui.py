"""Game/chapter UI management extracted from AppWindow."""

import contextlib
import logging
import os
import platform

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from models.game_modes import (
    DeltaruneGame,
    get_first_visible_game_id,
    get_game,
    get_search_game_entries,
    get_visible_game_entries,
)
from services.localization_service import tr
from ui.builders.shared_filters_builder import set_pizzatower_only_tag_visibility
from ui.common.styling import (
    clamp_border_radius,
    get_border_radius,
    get_theme_color,
)
from utils.path_utils import colored_icon


def update_checkbox_visibility(w):
    game_def = w.app_state.game_mode
    w.chapter_mode_checkbox.setVisible(game_def.is_multi_tab)
    w.full_install_checkbox.setVisible(game_def.supports_full_install)
    update_special_tag_visibility(w)


def update_special_tag_visibility(w):
    search_game = (
        w.modgame_combo.currentData()
        if hasattr(w, "modgame_combo") and w.modgame_combo
        else ""
    ) or "deltarune"
    library_game = (
        w.game_type_combo.currentData()
        if hasattr(w, "game_type_combo") and w.game_type_combo
        else getattr(w.app_state.game_mode, "game_id", "deltarune")
    ) or "deltarune"
    set_pizzatower_only_tag_visibility(
        getattr(w, "tag_cyop_afom", None),
        search_game == "pizzatower",
    )
    set_pizzatower_only_tag_visibility(
        getattr(w, "library_tag_cyop_afom", None),
        library_game == "pizzatower",
    )


def on_game_mode_updated_by_state(w, mode_obj):
    try:
        update_checkbox_visibility(w)
        game_def = mode_obj or w.app_state.game_mode
        if not game_def.is_multi_tab:
            w._set_checkbox_checked_silently(w.chapter_mode_checkbox, False)
            if getattr(w.app_state, "current_mode", "normal") != "normal":
                w.app_state.current_mode = "normal"
            w.app_state.selected_chapter_id = None
            w.game_type_combo.setEnabled(True)
        setup_chapter_tabs(w)
        w.used_mods_service.load_used_mods_state()
        w.library_display.update_display()
        update_change_path_button_text(w)
        update_settings_library_tab(w)
    except Exception:
        logging.debug("Error in on_game_mode_updated_by_state", exc_info=True)


def update_change_path_button_text(w):
    update_path_inputs_ui(w)


def update_path_input_localizations(w) -> None:
    placeholder_text = tr("ui.path_field_placeholder")
    for attr_name in (
        "settings_game_path_edit",
        "settings_custom_executable_edit",
        "settings_custom_g3mtool_edit",
        "settings_custom_xdelta_edit",
        "settings_custom_wine_edit",
        "settings_custom_portproton_edit",
    ):
        edit = getattr(w, attr_name, None)
        if edit and hasattr(edit, "setPlaceholderText"):
            edit.setPlaceholderText(placeholder_text)


def on_settings_game_combo_changed(w, index):
    """When the game selector in Settings > Library changes, update the path button text."""
    game_id = w.settings_game_combo.itemData(index)
    if not game_id:
        return
    for i in range(w.game_type_combo.count()):
        if w.game_type_combo.itemData(i) == game_id:
            if w.game_type_combo.currentIndex() != i:
                w.game_type_combo.setCurrentIndex(i)
            break
    game_def = get_game(game_id)
    if game_def:
        update_path_inputs_ui(w)
    update_custom_executable_ui(w, game_id)


def update_settings_library_tab(w):
    """Sync the settings Library tab with the current game mode."""
    current_game_id = w.app_state.game_mode.game_id
    combo = w.settings_game_combo
    for i in range(combo.count()):
        if combo.itemData(i) == current_game_id:
            combo.blockSignals(True)
            combo.setCurrentIndex(i)
            combo.blockSignals(False)
            break
    update_path_inputs_ui(w)
    update_custom_executable_ui(w, current_game_id)
    update_steam_launch_checkbox_state(w)


def refill_game_combo(combo, entries, current_game_id: str) -> None:
    was_blocked = combo.blockSignals(True)
    combo.clear()
    for entry in entries:
        combo.addItem(entry.display_name, entry.id)
    if combo.count():
        combo.setCurrentIndex(max(combo.findData(current_game_id), 0))
    combo.blockSignals(was_blocked)


def update_games_manager_button_style(w) -> None:
    if not hasattr(w, "games_manager_button"):
        return
    combo_height = w.settings_game_combo.sizeHint().height()
    br = clamp_border_radius(
        get_border_radius(w.app_state.local_config),
        width=combo_height,
        height=combo_height,
        border_width=2,
    )
    border = get_theme_color(w.app_state.local_config, "border")
    background = get_theme_color(w.app_state.local_config, "background")
    button = get_theme_color(w.app_state.local_config, "elements")
    hover = get_theme_color(w.app_state.local_config, "hover")
    text = get_theme_color(w.app_state.local_config, "main_text")
    w.games_manager_button.setFixedSize(combo_height, combo_height)
    w.games_manager_button.setIcon(colored_icon("settings", text))
    w.games_manager_button.setStyleSheet(
        f"QPushButton#games_manager_button {{ border: 2px solid {border}; border-radius: {br}px; background-color: {button}; margin: 0px; padding: 0px; }} "
        f"QPushButton#games_manager_button:hover:enabled {{ background-color: {hover}; }} "
        f"QPushButton#games_manager_button:disabled {{ background-color: {background}; border-color: #6f6f6f; }}"
    )


def refresh_game_lists(w, preserve_selection: bool = True) -> None:
    visible_games = get_visible_game_entries()
    search_games = get_search_game_entries()
    if not visible_games:
        return
    selected_game = (
        w.app_state.local_config.get("selected_game_type")
        if preserve_selection
        else w.app_state.game_mode.game_id
    ) or get_first_visible_game_id()
    valid_game = w.game_registry_service.ensure_valid_game_id(selected_game)
    selection_changed = selected_game != valid_game
    search_selection = w.app_state.local_config.get("selected_search_game", "")
    search_ids = {entry.id for entry in search_games}
    if search_selection not in search_ids:
        search_selection = search_games[0].id if search_games else ""
        w.app_state.local_config["selected_search_game"] = search_selection
    if hasattr(w, "game_type_combo"):
        refill_game_combo(w.game_type_combo, visible_games, valid_game)
    if hasattr(w, "settings_game_combo"):
        refill_game_combo(w.settings_game_combo, visible_games, valid_game)
    if hasattr(w, "modgame_combo"):
        refill_game_combo(w.modgame_combo, search_games, search_selection)
    if getattr(w.app_state.game_mode, "game_id", "") != valid_game:
        w.used_mods_service.save_used_mods_state()
        w.used_mods_service.used_mods.clear()
        w.app_state.game_mode = get_game(valid_game) or DeltaruneGame()
    w.app_state.local_config["selected_game_type"] = valid_game
    if not w.app_state.game_mode.is_multi_tab:
        w.app_state.current_mode = "normal"
        w.app_state.local_config["chapter_mode_enabled"] = False
        w._set_checkbox_checked_silently(w.chapter_mode_checkbox, False)
    if not w.app_state.game_mode.supports_full_install:
        w.app_state.local_config["full_install_enabled"] = False
        w._set_checkbox_checked_silently(w.full_install_checkbox, False)
    update_checkbox_visibility(w)
    update_settings_library_tab(w)
    update_games_manager_button_style(w)
    if selection_changed:
        w.profile_service.write_local_config()


def update_steam_launch_checkbox_state(w) -> None:
    if not hasattr(w, "launch_via_steam_checkbox"):
        return
    direct_launch_id = w.app_state.local_config.get("direct_launch_chapter", "")
    should_block = (
        w.app_state.game_mode.block_steam_with_direct_launch
        and w.app_state.current_mode == "chapter"
        and bool(direct_launch_id)
    )
    has_steam_app = bool(w.app_state.game_mode.steam_app_id)
    w.launch_via_steam_checkbox.setEnabled(has_steam_app and not should_block)
    if not has_steam_app:
        w.launch_via_steam_checkbox.setChecked(False)
        w.launch_via_steam_checkbox.setToolTip(tr("games.no_steam_app_tooltip"))
    elif should_block:
        w.launch_via_steam_checkbox.setChecked(False)
        w.app_state.local_config["launch_via_steam"] = False
        w.launch_via_steam_checkbox.setToolTip(
            "<html><body style='white-space: normal;'>"
            + tr("ui.steam_launch_direct_conflict")
            + "</body></html>"
        )
    else:
        w.launch_via_steam_checkbox.setToolTip(
            "<html><body style='white-space: normal;'>"
            + tr("tooltips.steam")
            + "</body></html>"
        )


def on_games_registry_changed(w) -> None:
    fallback = w.game_registry_service.ensure_valid_game_id(
        w.app_state.local_config.get("selected_game_type", "")
    )
    if w.app_state.local_config.get("selected_game_type") != fallback:
        w.profile_service.cleanup_game_references(
            w.app_state.local_config.get("selected_game_type", ""),
            fallback,
        )
        w.profile_service.write_local_config()
    refresh_game_lists(w)
    if w._game_versions_dialog:
        w._game_versions_dialog.relocalize_ui()
    if hasattr(w, "search_display"):
        w.search_display.load_mods_for_selected_game()
    if hasattr(w, "library_display"):
        w.library_display.update_display()


def sync_chapter_tab_buttons(w):
    if not hasattr(w, "chapter_tab_buttons"):
        return []
    tabs = list(getattr(w.app_state.game_mode, "tabs", ()) or ())
    for i, btn in enumerate(w.chapter_tab_buttons):
        with contextlib.suppress(TypeError, RuntimeError):
            btn.clicked.disconnect()
        if i >= len(tabs):
            btn.setChecked(False)
            btn.setVisible(False)
            btn._chapter_id = None
            continue
        tab = tabs[i]
        btn.setVisible(True)
        btn.setText(tr(tab.name_key))
        btn.clicked.connect(
            lambda checked, tid=tab.tab_id: (
                on_chapter_tab_clicked(w, tid) if checked else None
            )
        )
        btn.installEventFilter(w)
        btn._chapter_id = tab.tab_id
    if hasattr(w, "chapter_tabs_widget"):
        w.chapter_tabs_widget.setVisible(
            w.app_state.current_mode == "chapter"
            and w.app_state.game_mode.is_multi_tab
            and bool(tabs)
        )
    return tabs


def setup_chapter_tabs(w):
    sync_chapter_tab_buttons(w)
    update_chapter_tabs_style(w)


def on_chapter_tab_clicked(w, chapter_id):
    logging.debug(f"Chapter tab clicked: {chapter_id}")
    tabs = w.app_state.game_mode.tabs
    for i, btn in enumerate(w.chapter_tab_buttons):
        btn.setChecked(tabs[i].tab_id == chapter_id if i < len(tabs) else False)
    w.app_state.selected_chapter_id = chapter_id
    w.library_display.update_display()
    if hasattr(w.library_display, "_update_priority_button_visibility"):
        w.library_display._update_priority_button_visibility(chapter_id)


def update_chapter_tabs_style(w):
    buttons = getattr(w, "chapter_tab_buttons", None)
    if not isinstance(buttons, list) or not buttons:
        return
    tabs = w.app_state.game_mode.tabs
    direct_launch_chapter_id = w.app_state.local_config.get("direct_launch_chapter", "")
    border_color = get_theme_color(w.app_state.local_config, "border")
    button_color = get_theme_color(w.app_state.local_config, "elements")
    hover_color = get_theme_color(w.app_state.local_config, "hover")
    text_color = get_theme_color(w.app_state.local_config, "main_text")
    fs = max(1, int(14 * w.app_state.local_config.get("ui_scale", 1.0)))
    for i, (tab, btn) in enumerate(zip(tabs, w.chapter_tab_buttons, strict=False)):
        border_style = "dashed" if direct_launch_chapter_id == tab.tab_id else "solid"
        br = clamp_border_radius(
            get_border_radius(w.app_state.local_config),
            height=max(25, btn.sizeHint().height()),
        )
        btn.setStyleSheet(
            f"\n        QPushButton#chapter_tab_{i} {{\n          background-color: {button_color};\n          border: 2px {border_style} {border_color};\n          color: {text_color};\n          font-weight: bold;\n          font-size: {fs}px;\n          border-radius: {br}px;\n          padding: 5px;\n        }}\n        QPushButton#chapter_tab_{i}:checked {{\n          background-color: {hover_color};\n          border: 3px {border_style} {border_color};\n        }}\n        QPushButton#chapter_tab_{i}:hover {{\n          background-color: {hover_color};\n        }}\n      "
        )


def show_chapter_mode_instruction(w):
    if not hasattr(w, "installed_mods_layout"):
        return
    from ui.common.styling import clear_layout_widgets

    clear_layout_widgets(w.installed_mods_layout, keep_last_n=1)
    parent = (
        getattr(w, "installed_mods_widget", None)
        or getattr(w, "installed_mods_scroll", None)
        or w
    )
    instruction_widget = QLabel(tr("ui.chapter_mode_instruction"), parent)
    instruction_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    secondary_text_color = get_theme_color(
        w.app_state.local_config, "secondary_text", "#CCCCCC"
    )
    border_color = get_theme_color(w.app_state.local_config, "border", "#666666")
    instruction_widget.setStyleSheet(
        f"\n      QLabel {{\n        color: {secondary_text_color};\n        font-size: 14px;\n        font-style: italic;\n        padding: 20px;\n        border: 2px dashed {border_color};\n        background-color: rgba(255, 255, 255, 0.1);\n      }}\n    "
    )
    instruction_widget.setWordWrap(True)
    instruction_widget.setMinimumHeight(80)
    w.installed_mods_layout.insertWidget(
        w.installed_mods_layout.count() - 1, instruction_widget
    )


def on_toggle_full_install(w, state):
    w.app_state.is_full_install = bool(state)
    if hasattr(w, "game_launch"):
        w.game_launch._full_install_checkbox_is_checked = bool(state)
    if platform.system() == "Darwin" and w.app_state.is_full_install:
        w.feedback_service.show_message(
            "info", "dialogs.unavailable", tr("dialogs.macos_install_unavailable")
        )
        w._set_checkbox_checked_silently(w.full_install_checkbox, False)
        return
    w.game_launch.update_button_state()


def full_install_tooltip(w) -> str:
    if platform.system() == "Darwin":
        return tr("tooltips.macos_install_unavailable")
    return tr(
        "tooltips.full_install_game_instructions",
        game_name=w.app_state.game_mode.display_label,
    )


def save_custom_executable(w, path: str):
    config_key = w.app_state.game_mode.get_custom_exec_config_key()
    w.app_state.local_config[config_key] = path
    w.settings_service.write_local_config()
    w.settings_service.settings_changed.emit()
    update_path_inputs_ui(w)


def save_custom_executable_text(w, path: str):
    _commit_validated_executable_text(
        w,
        str(path or "").strip(),
        lambda value: save_custom_executable(w, value),
        lambda: update_custom_executable_ui(w),
    )


def _save_binary_override(w, config_key: str, path: str):
    w.app_state.local_config[config_key] = path
    w.settings_service.write_local_config()
    w.settings_service.settings_changed.emit()


def save_custom_g3mtool_text(w, path: str):
    _commit_validated_executable_text(
        w,
        str(path or "").strip(),
        lambda value: _save_binary_override(w, "custom_g3mtool_path", value),
        lambda: update_custom_binary_ui(w),
    )


def save_custom_xdelta_text(w, path: str):
    _commit_validated_executable_text(
        w,
        str(path or "").strip(),
        lambda value: _save_binary_override(w, "custom_xdelta_path", value),
        lambda: update_custom_binary_ui(w),
    )


def save_custom_wine_text(w, path: str):
    _commit_validated_executable_text(
        w,
        str(path or "").strip(),
        lambda value: _save_binary_override(w, "custom_wine_path", value),
        lambda: update_custom_binary_ui(w),
    )


def save_custom_portproton_text(w, path: str):
    _commit_validated_executable_text(
        w,
        str(path or "").strip(),
        lambda value: _save_portproton_override(w, value),
        lambda: update_custom_binary_ui(w),
    )


def _commit_validated_executable_text(w, path: str, save_callback, refresh_callback):
    cleaned_path = str(path or "").strip()
    if cleaned_path and not w.settings_service.validate_executable_path(cleaned_path):
        w.feedback_service.show_message(
            "warning",
            "errors.invalid_executable_file",
            file=os.path.basename(cleaned_path),
        )
        refresh_callback()
        _clear_active_path_focus(w)
        return
    save_callback(cleaned_path)
    refresh_callback()
    _clear_active_path_focus(w)


def _clear_active_path_focus(w):
    focus_widget = getattr(w, "focusWidget", lambda: None)()
    if focus_widget is not None and hasattr(focus_widget, "clearFocus"):
        focus_widget.clearFocus()


def _save_portproton_override(w, path: str):
    cleaned_path = str(path or "").strip()
    w.app_state.local_config["custom_portproton_path"] = cleaned_path
    w.settings_service.write_local_config()
    w.settings_service.settings_changed.emit()


def commit_game_path_text(w, path: str):
    cleaned_path = str(path or "").strip()
    if cleaned_path and not w.settings_service.validate_selected_game_path(cleaned_path):
        w.settings_service.show_invalid_game_path_warning(cleaned_path)
        update_path_inputs_ui(w)
        _clear_active_path_focus(w)
        return
    w.app_state.game_mode.set_game_path(w.app_state.local_config, cleaned_path)
    w.settings_service.write_local_config()
    w.settings_service.settings_changed.emit()
    update_path_inputs_ui(w)
    _clear_active_path_focus(w)


def select_custom_g3mtool_file(w):
    filepath = w.settings_service.select_executable_path(
        tr("buttons.select_g3mtool_binary")
    )
    if filepath:
        _save_binary_override(w, "custom_g3mtool_path", filepath)
        update_custom_binary_ui(w)


def reset_custom_g3mtool_path(w):
    save_custom_g3mtool_text(w, "")


def select_custom_xdelta_file(w):
    filepath = w.settings_service.select_executable_path(
        tr("buttons.select_xdelta_binary")
    )
    if filepath:
        _save_binary_override(w, "custom_xdelta_path", filepath)
        update_custom_binary_ui(w)


def reset_custom_xdelta_path(w):
    save_custom_xdelta_text(w, "")


def select_custom_wine_file(w):
    filepath = w.settings_service.select_executable_path(
        tr("buttons.select_wine_binary")
    )
    if filepath:
        _save_binary_override(w, "custom_wine_path", filepath)
        update_custom_binary_ui(w)


def reset_custom_wine_path(w):
    save_custom_wine_text(w, "")


def select_custom_portproton_file(w):
    filepath = w.settings_service.select_executable_path(
        tr("buttons.select_portproton_path")
    )
    if filepath:
        _save_portproton_override(w, filepath)
        update_custom_binary_ui(w)


def reset_custom_portproton_path(w):
    save_custom_portproton_text(w, "")


def update_custom_binary_ui(w):
    items = (
        (
            "custom_g3mtool_path",
            getattr(w, "settings_custom_g3mtool_edit", None),
            getattr(w, "settings_reset_g3mtool_button", None),
        ),
        (
            "custom_xdelta_path",
            getattr(w, "settings_custom_xdelta_edit", None),
            getattr(w, "settings_reset_xdelta_button", None),
        ),
        (
            "custom_wine_path",
            getattr(w, "settings_custom_wine_edit", None),
            getattr(w, "settings_reset_wine_button", None),
        ),
        (
            "custom_portproton_path",
            getattr(w, "settings_custom_portproton_edit", None),
            getattr(w, "settings_reset_portproton_button", None),
        ),
    )
    for config_key, edit, reset_button in items:
        if not edit:
            continue
        path = str(w.app_state.local_config.get(config_key, "") or "").strip()
        if config_key == "custom_portproton_path" and not path:
            path = str(w.app_state.local_config.get("portproton_path", "") or "").strip()
        edit.set_full_text(path) if hasattr(edit, "set_full_text") else edit.setText(path)
        edit.setToolTip(path)
        if reset_button:
            reset_button.setVisible(bool(path))


def select_custom_executable_file(w):
    filepath = w.settings_service.select_executable_path(tr("ui.select_launch_file"))
    if filepath:
        save_custom_executable(w, filepath)


def reset_custom_executable(w):
    save_custom_executable(w, "")


def update_custom_executable_ui(w, game_id=None):
    game_def = get_game(game_id) if game_id else w.app_state.game_mode
    if not game_def:
        return
    config_key = game_def.get_custom_exec_config_key()
    path = w.app_state.local_config.get(config_key, "")
    edit = getattr(w, "settings_custom_executable_edit", None)
    if edit:
        edit.set_full_text(path) if hasattr(edit, "set_full_text") else edit.setText(path)
        edit.setToolTip(path)
    has_custom_exe = bool(path)
    if (
        hasattr(w, "settings_reset_custom_exe_button")
        and w.settings_reset_custom_exe_button
    ):
        w.settings_reset_custom_exe_button.setVisible(has_custom_exe)


def update_path_inputs_ui(w):
    game_path_label = getattr(w, "settings_game_path_label", None)
    if game_path_label:
        game_name = getattr(w.app_state.game_mode, "display_label", "") or "Game"
        game_path_label.setText(
            tr("ui.settings_game_path_label").replace("{GAME}", str(game_name))
        )
    game_path_edit = getattr(w, "settings_game_path_edit", None)
    game_path = w.app_state.game_mode.get_game_path(w.app_state.local_config) or ""
    if game_path_edit:
        game_path_edit.set_full_text(game_path) if hasattr(game_path_edit, "set_full_text") else game_path_edit.setText(game_path)
        game_path_edit.setToolTip(game_path)
    reset_button = getattr(w, "settings_game_path_reset_button", None)
    if reset_button:
        reset_button.setVisible(bool(game_path))
    update_custom_executable_ui(w)


def update_portproton_ui(w):
    is_steam_launch = w.app_state.local_config.get("launch_via_steam", False)
    if w.use_portproton_checkbox:
        w.use_portproton_checkbox.setEnabled(not is_steam_launch)
        if is_steam_launch:
            w.use_portproton_checkbox.setToolTip(
                tr("tooltips.portproton_disabled_steam")
            )
        else:
            w.use_portproton_checkbox.setToolTip(
                "<html><body style='white-space: normal;'>"
                + tr("tooltips.portproton")
                + "</body></html>"
            )
    update_custom_binary_ui(w)


def on_used_mods_updated(w):
    logging.debug("Used mods updated, refreshing UI")
    if hasattr(w, "library_display"):
        w.library_display.update_mod_widgets_active_status()
        w.library_display._update_priority_button_visibility()
    if w.app_state.current_mode == "chapter":
        selected_chapter_id = getattr(w.app_state, "selected_chapter_id", None)
        if selected_chapter_id is not None:
            w.library_display.update_for_chapter_mode(selected_chapter_id)
