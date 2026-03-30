"""Settings tab wiring extracted from AppWindow._setup_settings_tab."""

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
    on_settings_game_combo_changed,
    refresh_game_lists,
    reset_custom_executable,
    select_custom_executable_file,
    select_portproton_path,
    update_portproton_ui,
    update_settings_library_tab,
)
from services.localization_service import tr
from ui.common.color_picker import BlackColorPickerEventFilter
from ui.common.styling import display_hex_to_qt_hex


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
            "settings_change_path_button",
            "settings_custom_executable_button",
            "settings_reset_custom_exe_button",
            "skip_patching_warnings_checkbox",
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
            "portproton_path_label",
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
        after_change=w._refresh_scaled_card_displays,
    )
    w._connect_theme_setting_spinbox(
        w.border_radius_spinbox,
        timer_attr="_border_radius_timer",
        config_key="custom_border_radius",
    )
    w.beta_updates_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.beta_updates_checkbox,
            lambda: w.settings_ui.on_toggle_beta_updates(bool(state)),
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
            lambda: w.settings_ui.on_toggle_show_reset_buttons(bool(state)),
        )
    )
    w.analytics_opt_in_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.analytics_opt_in_checkbox,
            lambda: (
                w.settings_service.on_toggle_analytics_opt_in(bool(state)),
                w.analytics_service.set_opt_in_enabled(bool(state)),
                w.analytics_service.record_setting_changed(
                    "analytics_opt_in_enabled", bool(state)
                ),
            ),
        )
    )
    w.fullscreen_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.fullscreen_checkbox,
            lambda: w.settings_ui.on_toggle_fullscreen(bool(state)),
        )
    )
    w.disable_animations_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.disable_animations_checkbox,
            lambda: w.settings_ui.on_toggle_disable_animations(bool(state)),
        )
    )
    w.disable_background_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.disable_background_checkbox,
            lambda: w.settings_ui.on_toggle_disable_background(bool(state)),
        )
    )
    w.disable_startup_sound_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.disable_startup_sound_checkbox,
            lambda: w.settings_ui.on_toggle_disable_startup_sound(bool(state)),
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
            lambda: w.settings_ui.on_toggle_hide_library_filters(bool(state)),
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
    w.settings_change_path_button.clicked.connect(
        lambda: _guarded_trigger(w.settings_change_path_button, w._prompt_for_game_path)
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
    update_settings_library_tab(w)
    w.skip_patching_warnings_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.skip_patching_warnings_checkbox,
            lambda: w.settings_ui.on_toggle_skip_patching_warnings(bool(state)),
        )
    )
    w.launch_via_steam_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.launch_via_steam_checkbox,
            lambda: w.settings_ui.on_toggle_steam_launch(bool(state)),
        )
    )
    w.dont_hide_window_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.dont_hide_window_checkbox,
            lambda: w.settings_ui.on_toggle_dont_hide_window_on_launch(bool(state)),
        )
    )
    if w.use_portproton_checkbox:
        w.use_portproton_checkbox.stateChanged.connect(
            lambda state: _guarded_trigger(
                w.use_portproton_checkbox,
                lambda: (
                    w.settings_ui.on_toggle_portproton(bool(state)),
                    update_portproton_ui(w),
                ),
            )
        )
    if w.select_portproton_path_button:
        w.select_portproton_path_button.clicked.connect(
            lambda: _guarded_trigger(
                w.select_portproton_path_button, lambda: select_portproton_path(w)
            )
        )
    w.hide_mods_browser_tab_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.hide_mods_browser_tab_checkbox,
            lambda: w.settings_ui.on_toggle_hide_mods_browser_tab(bool(state)),
        )
    )
    refresh_game_lists(w)
    w.hide_library_tab_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.hide_library_tab_checkbox,
            lambda: w.settings_ui.on_toggle_hide_library_tab(bool(state)),
        )
    )
    w.merge_properties_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.merge_properties_checkbox,
            lambda: w.settings_ui.on_toggle_merge_properties(bool(state)),
        )
    )
    w.merge_code_checkbox.stateChanged.connect(
        lambda state: _guarded_trigger(
            w.merge_code_checkbox,
            lambda: w.settings_ui.on_toggle_merge_code(bool(state)),
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
                lambda: w.settings_service.on_toggle_downloads_no_auto_use(bool(s)),
            )
        )
    if w.downloads_delete_after_use_checkbox:
        w.downloads_delete_after_use_checkbox.setChecked(
            w.app_state.local_config.get("downloads_delete_after_use", False)
        )
        w.downloads_delete_after_use_checkbox.stateChanged.connect(
            lambda s: _guarded_trigger(
                w.downloads_delete_after_use_checkbox,
                lambda: w.settings_service.on_toggle_downloads_delete_after_use(bool(s)),
            )
        )
    if w.downloads_save_local_imports_checkbox:
        w.downloads_save_local_imports_checkbox.setChecked(
            w.app_state.local_config.get("downloads_save_local_imports", False)
        )
        w.downloads_save_local_imports_checkbox.stateChanged.connect(
            lambda s: _guarded_trigger(
                w.downloads_save_local_imports_checkbox,
                lambda: w.settings_service.on_toggle_downloads_save_local_imports(bool(s)),
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
