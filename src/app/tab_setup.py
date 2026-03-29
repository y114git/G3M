"""Search and library tab setup extracted from AppWindow."""

import contextlib

from app.dialogs import (
    on_profile_combo_changed,
    on_profile_switched,
    open_downloads_dialog,
    open_game_versions_dialog,
    open_modding_tools_dialog,
    open_profile_manager,
    populate_profile_combo,
)
from app.game_ui import (
    on_game_mode_updated_by_state,
    on_toggle_full_install,
    setup_chapter_tabs,
    show_chapter_mode_instruction,
    update_change_path_button_text,
    update_checkbox_visibility,
    update_special_tag_visibility,
    update_steam_launch_checkbox_state,
)
from models.game_modes import DeltaruneGame, get_game


def _update_downloads_badge(btn, count: int):
    """Update downloads badge text on a button."""
    btn.setText(str(count) if count > 0 else "")


def _wire_downloads_badge(w, button_name: str):
    """Connect a downloads button to the shared badge state and sync it once."""
    btn = getattr(w, button_name, None)
    if not btn:
        return
    btn.clicked.connect(lambda: open_downloads_dialog(w))
    w.downloads_manager.badge_changed.connect(
        lambda count, _: _update_downloads_badge(btn, count)
    )
    w.downloads_manager._emit_badge()


def setup_search_tab(w):
    """Build and wire the Mods Browser tab."""
    from ui.builders.search_tab_builder import ModsBrowserTabBuilder

    search_builder = ModsBrowserTabBuilder(w.app_state, w)
    w.search_tab_builder = search_builder
    w.mods_browser_tab = search_builder.build()
    search_widgets = search_builder.get_widgets()
    w._bind_widgets(
        search_widgets,
        required=(
            "mods_browser_container",
            "mods_browser_scroll",
            "mod_list_widget",
            "mod_list_layout",
            "mod_list_columns",
            "sort_combo",
            "modgame_combo",
            "tags_label",
            "show_nsfw_checkbox",
            "tag_textedit",
            "tag_customization",
            "tag_gameplay",
            "tag_other",
            "tag_cyop_afom",
            "search_button",
        ),
        optional=("downloads_button", "blocklist_button"),
    )
    w.sort_combo.currentIndexChanged.connect(w._on_search_sort_changed)
    if "selected_search_game" not in w.app_state.local_config:
        default_game = w.modgame_combo.currentData() or "deltarune"
        w.app_state.local_config["selected_search_game"] = default_game
        w.settings_service.write_local_config()

    def on_modgame_changed():
        selected_game = w.modgame_combo.currentData() or "deltarune"
        w.app_state.local_config["selected_search_game"] = selected_game
        w.settings_service.write_local_config()
        update_special_tag_visibility(w)
        w.app_state.current_page = 1
        w.search_display.load_mods_for_selected_game()

    w.modgame_combo.currentIndexChanged.connect(on_modgame_changed)
    for tag_cb in (
        w.tag_textedit,
        w.tag_customization,
        w.tag_gameplay,
        w.tag_other,
        w.tag_cyop_afom,
    ):
        tag_cb.stateChanged.connect(
            lambda: (
                setattr(w.app_state, "current_page", 1),
                w.search_display.update_filtered_mods(),
            )
        )
    update_special_tag_visibility(w)

    def on_show_nsfw_changed(state):
        w.app_state.local_config["show_nsfw"] = bool(state)
        w.settings_service.write_local_config()
        w.app_state.current_page = 1
        w.search_display.update_filtered_mods()

    w.show_nsfw_checkbox.stateChanged.connect(on_show_nsfw_changed)
    w.search_button.clicked.connect(w.search_display.show_search_dialog)
    if hasattr(w, "blocklist_button") and w.blocklist_button:
        w.blocklist_button.clicked.connect(w.search_display.show_blocklist_dialog)
    _wire_downloads_badge(w, "downloads_button")
    with contextlib.suppress(AttributeError, RuntimeError):
        w.mods_browser_scroll.verticalScrollBar().valueChanged.connect(
            w.search_display.on_scroll_value_changed
        )
    with contextlib.suppress(AttributeError, RuntimeError):
        w.mods_browser_scroll.installEventFilter(w.search_display)
        viewport = w.mods_browser_scroll.viewport()
        if viewport:
            viewport.installEventFilter(w.search_display)


def setup_library_tab(w):
    """Build and wire the Library tab."""
    from ui.builders.library_tab_builder import LibraryTabBuilder

    library_builder = LibraryTabBuilder(w.app_state, w)
    w.library_tab_builder = library_builder
    w.library_tab = library_builder.build()
    library_widgets = library_builder.get_widgets()
    w._bind_widgets(
        library_widgets,
        required=(
            "library_filters_widget",
            "game_type_combo",
            "chapter_mode_checkbox",
            "full_install_checkbox",
            "chapter_tabs_widget",
            "chapter_tabs_layout",
            "chapter_tab_buttons",
            "installed_mods_container",
            "installed_mods_scroll",
            "installed_mods_widget",
            "installed_mods_layout",
            "library_sort_combo",
            "library_sort_order_btn",
            "library_tags_label",
            "library_tag_textedit",
            "library_tag_customization",
            "library_tag_gameplay",
            "library_tag_other",
            "library_tag_cyop_afom",
            "library_tag_gamebanana",
            "library_tag_widgets",
            "library_search_button",
            "library_profile_label",
            "library_game_label",
            "profile_combo",
            "profile_settings_button",
        ),
        optional=(
            "add_mod_button",
            "installed_mods_label",
            "priority_button",
            "create_modpack_button",
            "library_downloads_button",
            "library_game_versions_button",
            "library_modding_tools_button",
            "mod_summary_panel",
        ),
    )
    _wire_library_signals(w)
    _setup_profile_management(w)
    _setup_chapter_mode(w)


def _wire_library_signals(w):
    """Connect library tab widget signals to their handlers."""
    if w.priority_button:
        w.priority_button.clicked.connect(w.library_display.on_priority_button_click)
    if w.create_modpack_button:
        w.create_modpack_button.clicked.connect(
            w.library_display.on_create_modpack_button_click
        )
    w.library_display.connect_summary_panel()
    from controllers.mod_import_export_controller import ModImportExportController

    w.mod_import_export_controller = ModImportExportController(
        w.app_state, w.mod_service, w
    )
    if w.add_mod_button:
        w.add_mod_button.clicked.connect(
            w.mod_import_export_controller.show_add_mod_dialog
        )
    if hasattr(w.installed_mods_container, "files_dropped"):
        w.installed_mods_container.files_dropped.connect(
            w.mod_import_export_controller.import_files_sequentially
        )
    w.game_type_combo.currentIndexChanged.connect(w.settings_ui.on_game_type_changed)
    w.chapter_mode_checkbox.stateChanged.connect(w.settings_ui.on_chapter_mode_changed)
    w.full_install_checkbox.stateChanged.connect(
        lambda state: on_toggle_full_install(w, state)
    )
    saved_lib_sort_index = w.app_state.local_config.get("library_sort_index", 0)
    if 0 <= saved_lib_sort_index < w.library_sort_combo.count():
        w.library_sort_combo.blockSignals(True)
        w.library_sort_combo.setCurrentIndex(saved_lib_sort_index)
        w.library_sort_combo.blockSignals(False)
    w.library_sort_combo.currentIndexChanged.connect(w._on_library_sort_changed)
    w.library_sort_order_btn.clicked.connect(w._toggle_library_sort_order)
    w._apply_sort_order(w.library_sort_ascending, w.library_sort_order_btn)
    for tag in w.library_tag_widgets:
        tag.stateChanged.connect(w.library_display.update_display)
    w.library_search_button.clicked.connect(w._show_library_search_dialog)
    _wire_downloads_badge(w, "library_downloads_button")
    if w.library_game_versions_button:
        w.library_game_versions_button.clicked.connect(
            lambda: open_game_versions_dialog(w)
        )
    if hasattr(w, "library_modding_tools_button") and w.library_modding_tools_button:
        w.library_modding_tools_button.clicked.connect(
            lambda: open_modding_tools_dialog(w)
        )


def _setup_profile_management(w):
    """Wire profile combo, settings button, and profile switch signal."""
    populate_profile_combo(w)
    w.profile_combo.currentIndexChanged.connect(
        lambda index: on_profile_combo_changed(w, index)
    )
    w.profile_settings_button.clicked.connect(lambda: open_profile_manager(w))
    w.profile_service.profile_switched.connect(
        lambda name: on_profile_switched(w, name)
    )


def _setup_chapter_mode(w):
    """Restore chapter/game-mode state from config and wire signals."""
    saved_game_type = w.app_state.local_config.get("selected_game_type", "deltarune")
    saved_chapter_mode = w.app_state.local_config.get("chapter_mode_enabled", False)
    saved_full_install = w.app_state.local_config.get("full_install_enabled", False)
    w._set_checkbox_checked_silently(w.chapter_mode_checkbox, saved_chapter_mode)
    w.game_type_combo.setEnabled(not saved_chapter_mode)
    w._set_checkbox_checked_silently(w.full_install_checkbox, saved_full_install)
    w.game_launch._full_install_checkbox_is_checked = saved_full_install
    w.app_state.is_installing_changed.connect(w.game_launch.update_button_state)
    w.app_state.is_installing_changed.connect(
        lambda v: w.mod_ops.set_install_buttons_enabled(not v)
    )
    w.app_state.is_installing_changed.connect(lambda v: w._update_all_action_buttons())
    w.app_state.current_mode = "chapter" if saved_chapter_mode else "normal"
    w.game_launch.update_button_state()
    w._previous_mode = w.app_state.current_mode
    w.app_state.selected_chapter_id = None
    if saved_chapter_mode and hasattr(w, "chapter_tabs_widget"):
        w.chapter_tabs_widget.setVisible(True)
    game_def = get_game(saved_game_type)
    w.app_state.game_mode = game_def if game_def else DeltaruneGame()
    if not w.app_state.game_mode.is_multi_tab and w.app_state.current_mode == "chapter":
        w._set_checkbox_checked_silently(w.chapter_mode_checkbox, False)
        w.app_state.current_mode = "normal"
        w.game_type_combo.setEnabled(True)
    w.app_state.game_mode_changed.connect(
        lambda mode_obj: on_game_mode_updated_by_state(w, mode_obj)
    )
    update_checkbox_visibility(w)
    update_change_path_button_text(w)
    w.used_mods_service.load_used_mods_state()
    update_steam_launch_checkbox_state(w)
    if hasattr(w, "color_widgets"):
        w.theme.apply_theme()
    setup_chapter_tabs(w)
    if w.app_state.current_mode == "chapter":
        if w.app_state.selected_chapter_id is None:
            show_chapter_mode_instruction(w)
        else:
            w.library_display.update_for_chapter_mode(w.app_state.selected_chapter_id)
        _update_initial_priority_button(w)
    elif w.app_state.current_mode != "chapter":
        w.library_display.update_display()
        w.library_display._update_priority_button_visibility()
        w.app_state.library_initialized = True
    w.library_display.update_mod_widgets_active_status()


def _update_initial_priority_button(w):
    """Set priority button visibility after chapter mode init."""
    if w.app_state.selected_chapter_id is not None:
        w.library_display._update_priority_button_visibility(
            w.app_state.selected_chapter_id
        )
    if hasattr(w, "chapter_tab_buttons") and w.chapter_tab_buttons:
        for btn in w.chapter_tab_buttons:
            if btn.isChecked():
                chapter_id = getattr(btn, "_chapter_id", None)
                if chapter_id is not None:
                    w.library_display._update_priority_button_visibility(chapter_id)
                    break
