"""Settings tab wiring extracted from AppWindow._setup_settings_tab."""

import logging
from collections.abc import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.dialogs import open_game_manager
from app.game_ui import (
    commit_game_path_text,
    on_settings_game_combo_changed,
    refresh_game_lists,
    reset_custom_executable,
    reset_custom_g3mtool_path,
    reset_custom_portproton_path,
    reset_custom_wine_path,
    reset_custom_xdelta_path,
    save_custom_executable_text,
    save_custom_g3mtool_text,
    save_custom_portproton_text,
    save_custom_wine_text,
    save_custom_xdelta_text,
    select_custom_executable_file,
    select_custom_g3mtool_file,
    select_custom_portproton_file,
    select_custom_wine_file,
    select_custom_xdelta_file,
    update_custom_binary_ui,
    update_portproton_ui,
    update_settings_library_tab,
)
from services.localization_service import tr
from ui.common.color_picker import BlackColorPickerEventFilter
from ui.common.styling import display_hex_to_qt_hex
from ui.dialogs.warning_preferences_dialog import WarningPreferencesDialog

logger = logging.getLogger(__name__)


def _color_to_display_hex(color: QColor) -> str:
    if color.alpha() < 255:
        return f"#{color.red():02X}{color.green():02X}{color.blue():02X}{color.alpha():02X}"
    return color.name().upper()


def _sync_color_dialog_html_value(
    color_name_line_edit: QLineEdit, display_hex: str, html_edit_state: dict
):
    html_edit_state["syncing"] = True
    html_edit_state["dirty"] = False
    was_blocked = color_name_line_edit.blockSignals(True)
    color_name_line_edit.setText(display_hex)
    color_name_line_edit.setCursorPosition(len(display_hex))
    color_name_line_edit.blockSignals(was_blocked)
    html_edit_state["syncing"] = False


def _on_color_dialog_html_text_edited(_text: str, html_edit_state: dict):
    if not html_edit_state.get("syncing"):
        html_edit_state["dirty"] = True


def _on_color_dialog_html_edited(
    dialog: QColorDialog, color_name_line_edit: QLineEdit, html_edit_state: dict
):
    if html_edit_state.get("syncing") or not html_edit_state.get("dirty"):
        return
    html_edit_state["dirty"] = False
    updated_color = QColor(display_hex_to_qt_hex(color_name_line_edit.text().strip()))
    if updated_color.isValid():
        dialog.setCurrentColor(updated_color)


def _run_actions(*actions: Callable[[], None]) -> None:
    for action in actions:
        try:
            action()
        except Exception:
            logger.exception(
                "settings_setup: action failed in _run_actions: %r",
                action,
            )


def prepare_color_dialog(w, dialog: QColorDialog):
    zoom_factor = w.app_state.local_config.get("ui_scale", 1.0)
    dialog.setWindowTitle(tr("ui.select_color"))
    dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
    dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, True)
    dialog.ensurePolished()
    dialog.setMinimumWidth(max(dialog.minimumWidth(), int(760 * zoom_factor)))
    spin_boxes = dialog.findChildren(QSpinBox)
    for spin_box in spin_boxes:
        spin_box.setMinimumWidth(max(spin_box.minimumWidth(), int(115 * zoom_factor)))
        if line_edit := spin_box.lineEdit():
            line_edit.setMinimumWidth(
                max(line_edit.minimumWidth(), int(72 * zoom_factor))
            )
            line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
    color_name_line_edit = dialog.findChild(QLineEdit, "qt_colorname_lineedit")
    if color_name_line_edit:
        color_name_line_edit.setMinimumWidth(
            max(color_name_line_edit.minimumWidth(), int(160 * zoom_factor))
        )
        color_name_line_edit.setMaxLength(9)
        color_name_line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
    html_edit_state = {"dirty": False, "syncing": False}
    preview_outer_radius = max(6, int(8 * zoom_factor))
    preview_inner_radius = max(4, preview_outer_radius - 2)
    preview_container = QWidget(dialog)
    preview_layout = QHBoxLayout(preview_container)
    preview_layout.setContentsMargins(0, int(8 * zoom_factor), 0, 0)
    preview_layout.setSpacing(int(12 * zoom_factor))
    preview_layout.addStretch()
    preview_frames = []
    for background_color in ("#FFFFFF", "#000000"):
        preview_base = QFrame(preview_container)
        preview_base.setFixedSize(int(92 * zoom_factor), int(56 * zoom_factor))
        preview_base.setStyleSheet(
            f"background-color: {background_color}; border: 2px solid #808080; "
            f"border-radius: {preview_outer_radius}px;"
        )
        preview_base_layout = QVBoxLayout(preview_base)
        preview_base_layout.setContentsMargins(1, 1, 1, 1)
        preview_base_layout.setSpacing(0)
        preview_fill = QFrame(preview_base)
        preview_base_layout.addWidget(preview_fill)
        preview_frames.append(preview_fill)
        preview_layout.addWidget(preview_base)
    preview_layout.addStretch()

    def sync_color_dialog_ui(color: QColor):
        if not color.isValid():
            return
        for preview_frame in preview_frames:
            preview_frame.setStyleSheet(
                f"background-color: rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()}); "
                f"border: none; border-radius: {preview_inner_radius}px;"
            )
        if color_name_line_edit:
            display_hex = _color_to_display_hex(color)
            QTimer.singleShot(
                0,
                lambda text=display_hex, line_edit=color_name_line_edit: (
                    _sync_color_dialog_html_value(line_edit, text, html_edit_state)
                ),
            )

    if dialog.layout():
        dialog.layout().insertWidget(
            max(0, dialog.layout().count() - 1), preview_container
        )

    color_picker_widget = next(
        (
            widget
            for widget in dialog.findChildren(QWidget)
            if widget.metaObject().className().endswith("QColorPicker")
        ),
        None,
    )
    if color_picker_widget:
        dialog._black_color_picker_filter = BlackColorPickerEventFilter(dialog)
        color_picker_widget.installEventFilter(dialog._black_color_picker_filter)
    if color_name_line_edit:
        color_name_line_edit.textEdited.connect(
            lambda text: _on_color_dialog_html_text_edited(text, html_edit_state)
        )
        color_name_line_edit.editingFinished.connect(
            lambda: _on_color_dialog_html_edited(
                dialog, color_name_line_edit, html_edit_state
            )
        )
    dialog.currentColorChanged.connect(sync_color_dialog_ui)
    sync_color_dialog_ui(dialog.currentColor())
    dialog.adjustSize()


def _pick_color_for_edit(w, target_edit):
    current_text = target_edit.text().strip()
    initial_color = (
        QColor(display_hex_to_qt_hex(current_text)) if current_text else QColor()
    )
    dialog = QColorDialog(w)
    prepare_color_dialog(w, dialog)
    if initial_color.isValid():
        dialog.setCurrentColor(initial_color)
    if dialog.exec() == QColorDialog.DialogCode.Accepted:
        target_edit.setText(_color_to_display_hex(dialog.currentColor()))
        w.theme.on_custom_style_edited()


def _reset_display_hex(le: QLineEdit, w):
    """Reset line edit to default display hex and trigger theme update."""
    default_hex = le.property("default_display_hex") or ""
    le.setText(default_hex)
    le.setProperty("last_valid_display_hex", default_hex)
    w.theme.on_custom_style_edited()


def _commit_color_edit(w, target_edit: QLineEdit):
    color_text = target_edit.text().strip().upper()
    if w.settings_service.is_valid_hex_color(color_text) and color_text != (
        target_edit.property("last_valid_display_hex") or ""
    ).strip().upper():
        target_edit.setText(color_text)
        target_edit.setProperty("last_valid_display_hex", color_text)
        w.theme.on_custom_style_edited()


def _schedule_color_edit_commit(w, target_edit: QLineEdit):
    timer = getattr(target_edit, "_color_commit_timer", None)
    if timer is None:
        timer = QTimer(target_edit)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda le=target_edit: _commit_color_edit(w, le))
        target_edit._color_commit_timer = timer
    timer.start(300)


def _guarded_trigger(widget, callback, cooldown_ms: int = 500):
    if getattr(widget, "_click_guard_active", False):
        return
    widget._click_guard_active = True
    try:
        callback()
    finally:
        QTimer.singleShot(
            cooldown_ms,
            lambda w=widget: setattr(w, "_click_guard_active", False),
        )


def _record_setting_change(w, setting_name: str, enabled: bool):
    analytics = getattr(w, "analytics_service", None)
    if analytics:
        analytics.record_setting_changed(setting_name, bool(enabled))


def setup_settings_tab(w):
    """Wire all settings tab widgets, signals, and initial state."""
    from ui.builders.settings_view_builder import SettingsViewBuilder

    settings_builder = SettingsViewBuilder(w.app_state, w)
    w.settings_builder = settings_builder
    w.settings_widget = settings_builder.build()
    if hasattr(w, "main_layout") and w.main_layout:
        insert_index = (
            w.main_layout.indexOf(w.main_tab_widget)
            if hasattr(w, "main_tab_widget")
            else -1
        )
        if insert_index >= 0:
            w.main_layout.insertWidget(insert_index, w.settings_widget)
        else:
            w.main_layout.addWidget(w.settings_widget)
    settings_widgets = settings_builder.get_widgets()
    w._bind_widgets(
        settings_widgets,
        required=(
            "settings_tab_widget",
            "language_label",
            "language_combo",
            "beta_updates_checkbox",
            "show_reset_buttons_checkbox",
            "analytics_opt_in_checkbox",
            "fullscreen_checkbox",
            "disable_animations_checkbox",
            "disable_background_checkbox",
            "disable_startup_sound_checkbox",
            "pause_background_music_unfocused_checkbox",
            "change_background_button",
            "change_logo_button",
            "change_font_button",
            "background_music_button",
            "startup_sound_button",
            "custom_style_frame",
            "color_widgets",
            "color_labels",
            "color_config",
            "theme_button",
            "themes_list_widget",
            "theme_apply_btn",
            "theme_save_btn",
            "theme_delete_btn",
            "do_not_save_theme_checkbox",
            "hide_library_filters_checkbox",
            "settings_game_combo",
            "games_manager_button",
            "settings_game_path_label",
            "settings_game_path_edit",
            "settings_game_path_browse_button",
            "settings_game_path_reset_button",
            "settings_custom_executable_label",
            "settings_custom_executable_edit",
            "settings_custom_executable_button",
            "settings_reset_custom_exe_button",
            "settings_custom_g3mtool_label",
            "settings_custom_g3mtool_edit",
            "settings_custom_g3mtool_button",
            "settings_reset_g3mtool_button",
            "settings_custom_xdelta_label",
            "settings_custom_xdelta_edit",
            "settings_custom_xdelta_button",
            "settings_reset_xdelta_button",
            "settings_custom_wine_label",
            "settings_custom_wine_edit",
            "settings_custom_wine_button",
            "settings_reset_wine_button",
            "settings_custom_portproton_label",
            "settings_custom_portproton_edit",
            "settings_custom_portproton_button",
            "settings_reset_portproton_button",
            "manage_warnings_button",
            "clear_g3mtool_cache_button",
            "launch_via_steam_checkbox",
            "dont_hide_window_checkbox",
            "hide_mods_browser_tab_checkbox",
            "hide_library_tab_checkbox",
            "merge_properties_checkbox",
            "merge_code_checkbox",
            "ui_scale_label",
            "ui_scale_spinbox",
            "border_radius_label",
            "border_radius_spinbox",
            "plugins_layout",
            "plugins_tab",
        ),
        optional=(
            "use_portproton_checkbox",
            "select_portproton_path_button",
            "settings_portproton_path_label",
            "portproton_path_edit",
            "settings_portproton_path_reset_button",
            "portproton_frame",
            "downloads_no_auto_use_checkbox",
            "downloads_delete_after_use_checkbox",
            "downloads_save_local_imports_checkbox",
            "plugins_installed_only_checkbox",
            "plugins_tag_interface_checkbox",
            "plugins_tag_game_experience_checkbox",
            "plugins_tag_tool_checkbox",
            "plugins_tag_other_checkbox",
            "plugins_widget",
            "plugins_container",
        ),
    )
    w._section_headers = settings_widgets.get("_section_headers", [])
    w._section_lines = settings_widgets.get("_section_lines", [])
    w._section_reset_buttons = settings_widgets.get("_section_reset_buttons", [])
    w.language_combo.currentTextChanged.connect(
        lambda: w.settings_ui.on_language_changed(w.language_combo.currentData())
    )
    w._connect_theme_setting_spinbox(
        w.ui_scale_spinbox,
        timer_attr="_ui_scale_timer",
        config_key="ui_scale",
        value_transform=lambda value: value / 100.0,
        after_change=w._schedule_scaled_card_refresh,
    )
    w._connect_theme_setting_spinbox(
        w.border_radius_spinbox,
        timer_attr="_border_radius_timer",
        config_key="custom_border_radius",
    )
    w.beta_updates_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.beta_updates_checkbox,
            lambda: _run_actions(
                lambda: w.settings_ui.on_toggle_beta_updates(bool(state)),
                lambda: _record_setting_change(w, "beta_updates_enabled", bool(state)),
            ),
        )
    )
    for reset_btn, section_key, lang_key, content in w._section_reset_buttons:
        reset_btn.clicked.connect(
            lambda _, section=section_key, lang=lang_key, section_content=content, b=reset_btn: _guarded_trigger(
                b,
                lambda: w.settings_ui.reset_section(section, lang, section_content),
            )
        )
    w.show_reset_buttons_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.show_reset_buttons_checkbox,
            lambda: _run_actions(
                lambda: w.settings_ui.on_toggle_show_reset_buttons(bool(state)),
                lambda: _record_setting_change(w, "show_reset_buttons", bool(state)),
            ),
        )
    )
    w.analytics_opt_in_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.analytics_opt_in_checkbox,
            lambda: _run_actions(
                lambda: w.settings_service.on_toggle_analytics_opt_in(bool(state)),
                lambda: w.analytics_service.set_opt_in_enabled(bool(state)),
                lambda: _record_setting_change(
                    w, "analytics_opt_in_enabled", bool(state)
                ),
            ),
        )
    )
    w.fullscreen_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.fullscreen_checkbox,
            lambda: _run_actions(
                lambda: w.settings_ui.on_toggle_fullscreen(bool(state)),
                lambda: _record_setting_change(w, "fullscreen_enabled", bool(state)),
            ),
        )
    )
    w.disable_animations_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.disable_animations_checkbox,
            lambda: _run_actions(
                lambda: w.settings_ui.on_toggle_disable_animations(bool(state)),
                lambda: _record_setting_change(w, "disable_animations", bool(state)),
            ),
        )
    )
    w.disable_background_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.disable_background_checkbox,
            lambda: _run_actions(
                lambda: w.settings_ui.on_toggle_disable_background(bool(state)),
                lambda: _record_setting_change(w, "background_disabled", bool(state)),
            ),
        )
    )
    w.disable_startup_sound_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.disable_startup_sound_checkbox,
            lambda: _run_actions(
                lambda: w.settings_ui.on_toggle_disable_startup_sound(bool(state)),
                lambda: _record_setting_change(w, "disable_startup_sound", bool(state)),
            ),
        )
    )
    w.pause_background_music_unfocused_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.pause_background_music_unfocused_checkbox,
            lambda: _run_actions(
                lambda: w.settings_ui.on_toggle_pause_background_music_unfocused(
                    bool(state)
                ),
                lambda: _record_setting_change(
                    w, "pause_background_music_unfocused", bool(state)
                ),
            ),
        )
    )
    w.change_background_button.clicked.connect(
        lambda: _guarded_trigger(
            w.change_background_button, w.theme.on_background_button_click
        )
    )
    w.theme.update_background_button_state()
    w.change_logo_button.setText(w.customization_service.get_logo_button_text())
    w.change_logo_button.clicked.connect(
        lambda: _guarded_trigger(w.change_logo_button, w.theme.on_logo_button_click)
    )
    w.change_font_button.setText(w.customization_service.get_font_button_text())
    w.change_font_button.clicked.connect(
        lambda: _guarded_trigger(
            w.change_font_button, w.settings_service.on_font_button_click
        )
    )
    w.background_music_button.setText(
        w.customization_service.get_background_music_button_text()
    )
    w.background_music_button.clicked.connect(
        lambda: _guarded_trigger(
            w.background_music_button, w.theme.on_background_music_button_click
        )
    )
    w.startup_sound_button.setText(
        w.customization_service.get_startup_sound_button_text()
    )
    w.startup_sound_button.clicked.connect(
        lambda: _guarded_trigger(
            w.startup_sound_button, w.theme.on_startup_sound_button_click
        )
    )
    w.disable_startup_sound_checkbox.setChecked(
        w.app_state.local_config.get("disable_startup_sound", False)
    )
    w.pause_background_music_unfocused_checkbox.setChecked(
        w.app_state.local_config.get("pause_background_music_unfocused", False)
    )
    w.theme_button.clicked.connect(
        lambda: _guarded_trigger(w.theme_button, w.theme.on_theme_button_click)
    )
    w.theme_apply_btn.clicked.connect(
        lambda: _guarded_trigger(w.theme_apply_btn, w.theme.on_theme_apply_clicked)
    )
    w.theme_save_btn.clicked.connect(
        lambda: _guarded_trigger(w.theme_save_btn, w.theme.on_theme_save_clicked)
    )
    w.theme_delete_btn.clicked.connect(
        lambda: _guarded_trigger(w.theme_delete_btn, w.theme.on_theme_delete_clicked)
    )
    w.theme.init_theme_list()

    w._color_btns = {}
    for key in w.color_config:
        line_edit = w.color_widgets[key]
        btn = settings_widgets[f"color_btn_{key}"]
        w._color_btns[key] = btn
        reset_btn = settings_widgets[f"color_reset_{key}"]
        line_edit.textChanged.connect(
            lambda _text, le=line_edit: _schedule_color_edit_commit(w, le)
        )
        btn.clicked.connect(
            lambda _, le=line_edit, b=btn: _guarded_trigger(
                b, lambda: _pick_color_for_edit(w, le)
            )
        )
        reset_btn.clicked.connect(
            lambda _, le=line_edit, b=reset_btn: _guarded_trigger(
                b, lambda le=le: _reset_display_hex(le, w)
            )
        )
    w.hide_library_filters_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.hide_library_filters_checkbox,
            lambda: _run_actions(
                lambda: w.settings_ui.on_toggle_hide_library_filters(bool(state)),
                lambda: _record_setting_change(w, "hide_library_filters", bool(state)),
            ),
        )
    )
    w.settings_game_combo.currentIndexChanged.connect(
        lambda index: on_settings_game_combo_changed(w, index)
    )
    w.games_manager_button.clicked.connect(
        lambda: _guarded_trigger(
            w.games_manager_button, lambda: open_game_manager(w)
        )
    )
    w.settings_game_path_browse_button.clicked.connect(
        lambda: _guarded_trigger(
            w.settings_game_path_browse_button, w._prompt_for_game_path
        )
    )
    w.settings_game_path_reset_button.clicked.connect(
        lambda: _guarded_trigger(
            w.settings_game_path_reset_button,
            lambda: commit_game_path_text(w, ""),
        )
    )
    w.settings_game_path_edit.editingFinished.connect(
        lambda: commit_game_path_text(
            w,
            w.settings_game_path_edit.full_text()
            if hasattr(w.settings_game_path_edit, "full_text")
            else w.settings_game_path_edit.text(),
        )
    )
    w.settings_custom_executable_edit.editingFinished.connect(
        lambda: save_custom_executable_text(
            w,
            w.settings_custom_executable_edit.full_text()
            if hasattr(w.settings_custom_executable_edit, "full_text")
            else w.settings_custom_executable_edit.text(),
        )
    )
    w.settings_custom_executable_button.clicked.connect(
        lambda: _guarded_trigger(
            w.settings_custom_executable_button,
            lambda: select_custom_executable_file(w),
        )
    )
    w.settings_reset_custom_exe_button.clicked.connect(
        lambda: _guarded_trigger(
            w.settings_reset_custom_exe_button,
            lambda: reset_custom_executable(w),
        )
    )
    w.settings_custom_g3mtool_button.clicked.connect(
        lambda: _guarded_trigger(
            w.settings_custom_g3mtool_button,
            lambda: select_custom_g3mtool_file(w),
        )
    )
    w.settings_custom_g3mtool_edit.editingFinished.connect(
        lambda: save_custom_g3mtool_text(
            w,
            w.settings_custom_g3mtool_edit.full_text()
            if hasattr(w.settings_custom_g3mtool_edit, "full_text")
            else w.settings_custom_g3mtool_edit.text(),
        )
    )
    w.settings_reset_g3mtool_button.clicked.connect(
        lambda: _guarded_trigger(
            w.settings_reset_g3mtool_button,
            lambda: reset_custom_g3mtool_path(w),
        )
    )
    w.settings_custom_xdelta_button.clicked.connect(
        lambda: _guarded_trigger(
            w.settings_custom_xdelta_button,
            lambda: select_custom_xdelta_file(w),
        )
    )
    w.settings_custom_xdelta_edit.editingFinished.connect(
        lambda: save_custom_xdelta_text(
            w,
            w.settings_custom_xdelta_edit.full_text()
            if hasattr(w.settings_custom_xdelta_edit, "full_text")
            else w.settings_custom_xdelta_edit.text(),
        )
    )
    w.settings_reset_xdelta_button.clicked.connect(
        lambda: _guarded_trigger(
            w.settings_reset_xdelta_button,
            lambda: reset_custom_xdelta_path(w),
        )
    )
    if hasattr(w, "settings_custom_wine_button") and w.settings_custom_wine_button:
        w.settings_custom_wine_button.clicked.connect(
            lambda: _guarded_trigger(
                w.settings_custom_wine_button,
                lambda: select_custom_wine_file(w),
            )
        )
    if hasattr(w, "settings_custom_wine_edit") and w.settings_custom_wine_edit:
        w.settings_custom_wine_edit.editingFinished.connect(
            lambda: save_custom_wine_text(
                w,
                w.settings_custom_wine_edit.full_text()
                if hasattr(w.settings_custom_wine_edit, "full_text")
                else w.settings_custom_wine_edit.text(),
            )
        )
    if hasattr(w, "settings_reset_wine_button") and w.settings_reset_wine_button:
        w.settings_reset_wine_button.clicked.connect(
            lambda: _guarded_trigger(
                w.settings_reset_wine_button,
                lambda: reset_custom_wine_path(w),
            )
        )
    if (
        hasattr(w, "settings_custom_portproton_button")
        and w.settings_custom_portproton_button
    ):
        w.settings_custom_portproton_button.clicked.connect(
            lambda: _guarded_trigger(
                w.settings_custom_portproton_button,
                lambda: select_custom_portproton_file(w),
            )
        )
    if hasattr(w, "settings_custom_portproton_edit") and w.settings_custom_portproton_edit:
        w.settings_custom_portproton_edit.editingFinished.connect(
            lambda: save_custom_portproton_text(
                w,
                w.settings_custom_portproton_edit.full_text()
                if hasattr(w.settings_custom_portproton_edit, "full_text")
                else w.settings_custom_portproton_edit.text(),
            )
        )
    if (
        hasattr(w, "settings_reset_portproton_button")
        and w.settings_reset_portproton_button
    ):
        w.settings_reset_portproton_button.clicked.connect(
            lambda: _guarded_trigger(
                w.settings_reset_portproton_button,
                lambda: reset_custom_portproton_path(w),
            )
        )
    update_settings_library_tab(w)
    update_custom_binary_ui(w)
    w.manage_warnings_button.clicked.connect(
        lambda: _guarded_trigger(
            w.manage_warnings_button,
            lambda: open_warning_preferences_dialog(w),
        )
    )
    w.clear_g3mtool_cache_button.clicked.connect(
        lambda: _guarded_trigger(
            w.clear_g3mtool_cache_button,
            w.settings_service.clear_g3mtool_cache,
        )
    )
    w.launch_via_steam_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.launch_via_steam_checkbox,
            lambda: _run_actions(
                lambda: w.settings_ui.on_toggle_steam_launch(bool(state)),
                lambda: _record_setting_change(w, "launch_via_steam", bool(state)),
            ),
        )
    )
    w.dont_hide_window_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.dont_hide_window_checkbox,
            lambda: _run_actions(
                lambda: w.settings_ui.on_toggle_dont_hide_window_on_launch(bool(state)),
                lambda: _record_setting_change(
                    w, "dont_hide_window_on_launch", bool(state)
                ),
            ),
        )
    )
    if w.use_portproton_checkbox:
        w.use_portproton_checkbox.stateChanged.connect(
            lambda state: _guarded_trigger(
                w.use_portproton_checkbox,
                lambda: _run_actions(
                    lambda: w.settings_ui.on_toggle_portproton(bool(state)),
                    lambda: update_portproton_ui(w),
                    lambda: _record_setting_change(w, "use_portproton", bool(state)),
                ),
            )
        )
    w.hide_mods_browser_tab_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.hide_mods_browser_tab_checkbox,
            lambda: _run_actions(
                lambda: w.settings_ui.on_toggle_hide_mods_browser_tab(bool(state)),
                lambda: _record_setting_change(w, "hide_mods_browser_tab", bool(state)),
            ),
        )
    )
    refresh_game_lists(w)
    w.hide_library_tab_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.hide_library_tab_checkbox,
            lambda: _run_actions(
                lambda: w.settings_ui.on_toggle_hide_library_tab(bool(state)),
                lambda: _record_setting_change(w, "hide_library_tab", bool(state)),
            ),
        )
    )
    w.merge_properties_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.merge_properties_checkbox,
            lambda: _run_actions(
                lambda: w.settings_ui.on_toggle_merge_properties(bool(state)),
                lambda: _record_setting_change(w, "merge_properties", bool(state)),
            ),
        )
    )
    w.merge_code_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.merge_code_checkbox,
            lambda: _run_actions(
                lambda: w.settings_ui.on_toggle_merge_code(bool(state)),
                lambda: _record_setting_change(w, "merge_code", bool(state)),
            ),
        )
    )
    w.show_reset_buttons_checkbox.setChecked(
        w.app_state.local_config.get("show_reset_buttons", False)
    )
    w.analytics_opt_in_checkbox.blockSignals(True)
    w.analytics_opt_in_checkbox.setChecked(
        w.app_state.local_config.get("analytics_opt_in_enabled", False)
    )
    w.analytics_opt_in_checkbox.blockSignals(False)
    w.hide_mods_browser_tab_checkbox.setChecked(
        w.app_state.local_config.get("hide_mods_browser_tab", False)
    )
    w.hide_library_tab_checkbox.setChecked(
        w.app_state.local_config.get("hide_library_tab", False)
    )
    if w.downloads_no_auto_use_checkbox:
        w.downloads_no_auto_use_checkbox.setChecked(
            w.app_state.local_config.get("downloads_no_auto_use", False)
        )
        w.downloads_no_auto_use_checkbox.stateChanged.connect(
            lambda s: _guarded_trigger(
                w.downloads_no_auto_use_checkbox,
                lambda: _run_actions(
                    lambda: w.settings_service.on_toggle_downloads_no_auto_use(bool(s)),
                    lambda: _record_setting_change(w, "downloads_no_auto_use", bool(s)),
                ),
            )
        )
    if w.downloads_delete_after_use_checkbox:
        w.downloads_delete_after_use_checkbox.setChecked(
            w.app_state.local_config.get("downloads_delete_after_use", False)
        )
        w.downloads_delete_after_use_checkbox.stateChanged.connect(
            lambda s: _guarded_trigger(
                w.downloads_delete_after_use_checkbox,
                lambda: _run_actions(
                    lambda: w.settings_service.on_toggle_downloads_delete_after_use(bool(s)),
                    lambda: _record_setting_change(
                        w, "downloads_delete_after_use", bool(s)
                    ),
                ),
            )
        )
    if w.downloads_save_local_imports_checkbox:
        w.downloads_save_local_imports_checkbox.setChecked(
            w.app_state.local_config.get("downloads_save_local_imports", False)
        )
        w.downloads_save_local_imports_checkbox.stateChanged.connect(
            lambda s: _guarded_trigger(
                w.downloads_save_local_imports_checkbox,
                lambda: _run_actions(
                    lambda: w.settings_service.on_toggle_downloads_save_local_imports(bool(s)),
                    lambda: _record_setting_change(
                        w, "downloads_save_local_imports", bool(s)
                    ),
                ),
            )
        )
    if hasattr(w, "plugins_ui") and w.plugins_ui:
        w.settings_tab_widget.currentChanged.connect(w.plugins_ui.on_tab_changed)
        if hasattr(w, "plugins_widget") and hasattr(w.plugins_widget, "files_dropped"):
            w.plugins_widget.files_dropped.connect(w.plugins_ui.import_paths)
        for checkbox in (
            w.plugins_installed_only_checkbox,
            w.plugins_tag_interface_checkbox,
            w.plugins_tag_game_experience_checkbox,
            w.plugins_tag_tool_checkbox,
            w.plugins_tag_other_checkbox,
        ):
            if checkbox:
                checkbox.stateChanged.connect(w.plugins_ui.on_filters_changed)
        w.plugins_ui.restore_filter_state()
    w._update_section_reset_buttons_visibility()


def open_warning_preferences_dialog(w) -> None:
    dialog = WarningPreferencesDialog(w.app_state.local_config, w)
    if dialog.exec():
        w.settings_service.write_local_config()
