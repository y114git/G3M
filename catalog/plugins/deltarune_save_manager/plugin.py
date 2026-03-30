"""New-style DR Save Manager plugin."""

from __future__ import annotations

import importlib.util
import os

from ui.common.styling import get_theme_color


def _load_local_module(filename: str, module_name: str):
    path = os.path.join(os.path.dirname(__file__), filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _PluginApiAdapter:
    def __init__(self, settings_accessor) -> None:
        self._settings = settings_accessor

    def get_config(self, key: str, default=None):
        return self._settings.get(key, default)

    def set_config(self, key: str, value) -> None:
        self._settings.set(key, value)


class _SaveManagerWidgetController:
    def __init__(self, app_state, save_manager, widgets, tr_func) -> None:
        self.app_state = app_state
        self.save_manager = save_manager
        self.widgets = widgets
        self.tr = tr_func
        self._hovered_slot = None
        self._connect()
        self.refresh_slots()

    def _connect(self) -> None:
        self.widgets["save_tabs"].currentChanged.connect(
            lambda: self._on_chapter_tab_changed()
        )
        self.widgets["change_save_path_btn"].clicked.connect(
            lambda: self.save_manager.prompt_for_save_path() and self.refresh_slots()
        )
        self.widgets["switch_collection_btn"].clicked.connect(
            lambda: self.save_manager.toggle_collection_view() and self.refresh_slots()
        )
        self.widgets["left_col_btn"].clicked.connect(
            lambda: self.save_manager.navigate_collection(-1) or self.refresh_slots()
        )
        self.widgets["right_col_btn"].clicked.connect(
            lambda: self.save_manager.navigate_collection(1) or self.refresh_slots()
        )
        self.widgets["rename_collection_btn"].clicked.connect(
            lambda: self.save_manager.rename_current_collection(
                self.save_manager.current_collection_idx
            )
            and self.refresh_slots()
        )
        self.widgets["delete_collection_btn"].clicked.connect(
            lambda: self.save_manager.delete_current_collection(
                self.save_manager.current_collection_idx
            )
            and self.refresh_slots()
        )
        self.widgets["copy_from_main_btn"].clicked.connect(
            lambda: self.save_manager.copy_between_storages(
                self.widgets["save_tabs"].currentIndex() + 1,
                True,
                self.save_manager.selected_slot,
            )
            or self.refresh_slots()
        )
        self.widgets["copy_to_main_btn"].clicked.connect(
            lambda: self.save_manager.copy_between_storages(
                self.widgets["save_tabs"].currentIndex() + 1,
                False,
                self.save_manager.selected_slot,
            )
            or self.refresh_slots()
        )
        self.widgets["edit_btn"].clicked.connect(self._edit_selected_slot)
        self.widgets["show_btn"].clicked.connect(self._show_selected_slot)
        self.widgets["erase_btn"].clicked.connect(self._erase_selected_slot)
        self.widgets["import_btn"].clicked.connect(
            lambda: self._import_export_selected(True)
        )
        self.widgets["export_btn"].clicked.connect(
            lambda: self._import_export_selected(False)
        )
        for (chapter, slot), label in self.widgets["slot_labels"].items():
            label.clicked.connect(lambda _c=chapter, _s=slot: self._on_slot_clicked(_c, _s))
            label.double_clicked.connect(
                lambda _c=chapter, _s=slot: self._on_slot_double_clicked(_c, _s)
            )
            if hasattr(label, "hover_entered"):
                label.hover_entered.connect(
                    lambda ch, sl: self._on_slot_hover_changed((ch, sl))
                )
            if hasattr(label, "hover_left"):
                label.hover_left.connect(lambda _ch, _sl: self._on_slot_hover_changed(None))
        for (chapter, slot), row in self.widgets.get("slot_rows", {}).items():
            row.hover_entered.connect(lambda ch=chapter, sl=slot: self._on_slot_hover_changed((ch, sl)))
            row.hover_left.connect(lambda: self._on_slot_hover_changed(None))

    def _selected_indices(self) -> tuple[int, int] | None:
        return self.save_manager.selected_slot

    def _edit_selected_slot(self) -> None:
        selected = self._selected_indices()
        if selected:
            self._on_slot_double_clicked(*selected)

    def _show_selected_slot(self) -> None:
        selected = self._selected_indices()
        if selected:
            self.save_manager.action_show_save(*selected)

    def _erase_selected_slot(self) -> None:
        selected = self._selected_indices()
        if selected and self.save_manager.action_delete_save(*selected):
            self.refresh_slots()

    def _import_export_selected(self, is_import: bool) -> None:
        selected = self._selected_indices()
        if selected and self.save_manager.action_import_export(*selected, is_import):
            self.refresh_slots()

    def refresh_slots(self) -> None:
        if not self.save_manager.find_and_validate_save_path():
            return
        chapter = self.widgets["save_tabs"].currentIndex() + 1
        for slot, (_, text) in self.save_manager.refresh_save_slots_data(
            chapter
        ).items():
            self.widgets["slot_labels"][chapter, slot].setText(text)
        self._update_collection_ui()
        self._update_slot_highlight()
        self._update_action_bar()

    def _update_collection_ui(self) -> None:
        ui_state = self.save_manager.get_collection_ui_state()
        in_collection = ui_state["in_collection"]
        self.widgets["switch_collection_btn"].setText(
            self.tr("buttons.additional_slots")
            if not in_collection
            else self.tr("dialogs.main_slots")
        )
        self.widgets["left_col_btn"].setEnabled(ui_state["can_navigate_left"])
        self.widgets["right_col_btn"].setEnabled(ui_state["can_navigate_right"])
        for key in (
            "rename_collection_btn",
            "delete_collection_btn",
            "copy_from_main_btn",
            "copy_to_main_btn",
        ):
            self.widgets[key].setVisible(in_collection)
        self.widgets["change_save_path_btn"].setVisible(not in_collection)
        self.widgets["collection_name_lbl"].setVisible(bool(ui_state["collection_name"]))
        self.widgets["collection_name_lbl"].setText(ui_state["collection_name"])

    def _update_slot_highlight(self) -> None:
        selected = self.save_manager.selected_slot
        border = get_theme_color(self.app_state.local_config, "border", "#039d5b")
        selected_border = get_theme_color(self.app_state.local_config, "select")
        hover_border = get_theme_color(self.app_state.local_config, "hover")
        background = get_theme_color(
            self.app_state.local_config, "background", "#282828"
        )
        radius = self.app_state.local_config.get("custom_border_radius", 0)
        for (chapter, slot), row in self.widgets["slot_rows"].items():
            current_slot = (chapter, slot)
            base_border = (
                selected_border
                if selected == current_slot
                else hover_border
                if self._hovered_slot == current_slot
                else border
            )
            row.setStyleSheet(
                f"""
QFrame#slot_row_{chapter}_{slot} {{
    border: 2px solid {base_border};
    background-color: {background};
    padding: 0;
    border-radius: {radius}px;
}}
"""
            )

    def _on_slot_hover_changed(self, slot) -> None:
        if self._hovered_slot == slot:
            return
        self._hovered_slot = slot
        self._update_slot_highlight()

    def _update_action_bar(self) -> None:
        selected = self.save_manager.selected_slot
        visible = selected is not None
        for key in ("edit_btn", "show_btn", "erase_btn", "import_btn", "export_btn"):
            self.widgets[key].setVisible(visible)
        has_data = False
        if selected:
            chapter, slot = selected
            base = self.save_manager.get_collection_path(
                self.save_manager.current_collection_idx
            )
            file_path = os.path.join(base, f"filech{chapter}_{slot}")
            try:
                has_data = os.path.getsize(file_path) > 0
            except OSError:
                has_data = False
        self.widgets["edit_btn"].setEnabled(has_data)
        self.widgets["show_btn"].setEnabled(has_data)
        self.widgets["erase_btn"].setEnabled(has_data)
        self.widgets["export_btn"].setEnabled(has_data)
        self.widgets["import_btn"].setEnabled(bool(selected))

    def _on_slot_clicked(self, chapter: int, slot: int) -> None:
        self.save_manager.selected_slot = (chapter, slot)
        self._update_slot_highlight()
        self._update_action_bar()

    def _on_slot_double_clicked(self, chapter: int, slot: int) -> None:
        base = self.save_manager.get_collection_path(
            self.save_manager.current_collection_idx
        )
        file_path = os.path.join(base, f"filech{chapter}_{slot}")
        if not (os.path.exists(file_path) and os.path.getsize(file_path) > 0):
            return
        editor_module = _load_local_module(
            "save_editor.py", "g3m_plugin_save_editor"
        )
        dialog = editor_module.SaveEditorDialog(file_path, self.app_state, self.save_manager.parent_widget, self.tr)
        if dialog.exec():
            self.refresh_slots()

    def _on_chapter_tab_changed(self) -> None:
        self.save_manager.selected_slot = None
        self.refresh_slots()


class DRSaveManagerPlugin:
    def __init__(self) -> None:
        self._backup_info = {}
        self._context = None
        self._save_manager = None

    def on_load(self, context) -> None:
        self._context = context

    def _tr(self):
        return self._context.localization_service.get_plugin_tr("deltarune_save_manager")

    def _save_manager_instance(self, parent=None):
        if self._save_manager is not None:
            return self._save_manager
        module = _load_local_module("save_manager.py", "g3m_plugin_save_manager")
        module.tr = self._tr()
        self._save_manager = module.SaveManager(
            self._context.app_state,
            self._context.feedback_service,
            self._context.settings_service,
            _PluginApiAdapter(self._context.plugin_settings),
            parent,
        )
        return self._save_manager

    def create_main_widget(self, ui_context, parent):
        builder_module = _load_local_module(
            "save_manager_view_builder.py",
            "g3m_plugin_save_manager_view_builder",
        )
        builder_module.tr = self._tr()
        builder = builder_module.SaveManagerViewBuilder(ui_context.app_state, parent)
        widget = builder.build()
        save_manager = self._save_manager_instance(parent)
        controller = _SaveManagerWidgetController(
            ui_context.app_state,
            save_manager,
            builder.get_widgets(),
            self._tr(),
        )
        save_manager.slots_updated.connect(controller.refresh_slots)
        widget._plugin_controller = controller
        widget.setVisible(True)
        return widget

    def on_before_mod_apply(self, context, *_args):
        manager = self._save_manager_instance()
        collection_idx = manager.prompt_for_save_collection_on_launch()
        if collection_idx is None:
            return False
        if collection_idx != -1:
            backup_info = manager.apply_collection_saves_for_launch(collection_idx)
            if not backup_info:
                return False
            self._backup_info = backup_info
        return True

    def on_after_restore_after_exit(self, context, *_args):
        if self._backup_info:
            self._save_manager_instance().restore_original_saves_after_launch(
                self._backup_info
            )
            self._backup_info = {}


def create_plugin():
    return DRSaveManagerPlugin()

