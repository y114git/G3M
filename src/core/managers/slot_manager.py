from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QDialog, QListWidget, QDialogButtonBox
from typing import Dict, Optional, Any, TYPE_CHECKING
if TYPE_CHECKING:
    from core.app_window import AppWindow
from core.app_state import AppState
from ui.feedback import FeedbackManager
from core.managers.mod_manager import ModManager
from core.managers.settings_manager import SettingsManager
from models.game_modes import DemoGameMode, UndertaleGameMode
from ui.widgets.custom_controls import SlotFrame
from ui.styling import get_theme_color, clear_layout_widgets, load_mod_icon_universal
from core.managers.localization_manager import tr


class SlotManager(QObject):
    slots_updated = pyqtSignal()
    slot_state_changed = pyqtSignal(int)
    chapter_mode_changed = pyqtSignal(bool)
    action_button_update_needed = pyqtSignal()
    mod_widgets_update_needed = pyqtSignal()

    def __init__(self, app_state: AppState, mod_manager: ModManager, feedback_manager: FeedbackManager, settings_manager: SettingsManager, parent: Optional['AppWindow'] = None):
        super().__init__(parent)
        self.app_state = app_state
        self.mod_manager = mod_manager
        self.feedback_manager = feedback_manager
        self.settings_manager = settings_manager
        self.parent_widget: Optional['AppWindow'] = parent
        self.chapter_indicators: Dict[int, Dict[str, Any]] = {}
        self._previous_mode = None

    def init_slots_system(self, active_slots_layout=None):
        if active_slots_layout is None and self.parent_widget and hasattr(self.parent_widget, 'active_slots_layout'):
            active_slots_layout = self.parent_widget.active_slots_layout
        self.update_slots_display(active_slots_layout)

    def update_slots_display(self, active_slots_layout=None):
        if active_slots_layout is not None:
            clear_layout_widgets(active_slots_layout, keep_last_n=0)
        if not hasattr(self.app_state, 'slots'):
            self.app_state.slots = {}
        else:
            self.app_state.slots.clear()
        is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
        if self.app_state.current_mode == 'normal':
            if is_demo_mode:
                slot = self.create_slot_widget(tr('ui.demo_slot'), -10)
                if active_slots_layout is not None:
                    active_slots_layout.addWidget(slot)
                self.app_state.slots[-10] = slot
            elif isinstance(self.app_state.game_mode, UndertaleGameMode):
                slot = self.create_slot_widget(tr('ui.mod_slot'), -20)
                if active_slots_layout is not None:
                    active_slots_layout.addWidget(slot)
                self.app_state.slots[-20] = slot
            else:
                slot = self.create_slot_widget(tr('ui.mod_slot'), -1)
                if active_slots_layout is not None:
                    active_slots_layout.addWidget(slot)
                self.app_state.slots[-1] = slot
                self.create_chapter_indicators(active_slots_layout)
        else:
            slot_names = [tr('chapters.menu'), tr('tabs.chapter_1'), tr('tabs.chapter_2'), tr('tabs.chapter_3'), tr('tabs.chapter_4')]
            for i, name in enumerate(slot_names):
                slot = self.create_slot_widget(name, i)
                if active_slots_layout is not None:
                    active_slots_layout.addWidget(slot)
                self.app_state.slots[i] = slot
        self.load_slots_state()

    def create_slot_widget(self, name: str, chapter_id: int) -> SlotFrame:
        slot_frame = SlotFrame()
        if chapter_id in [-1, -10, -20]:
            slot_frame.setFixedSize(250, 100)
        else:
            slot_frame.setFixedSize(150, 100)
        slot_frame.setObjectName('mod_slot')
        slot_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(slot_frame)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label = QLabel(name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet('font-weight: bold; border: none; background-color: transparent;')
        layout.addWidget(name_label)
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mod_icon = QLabel(tr('ui.empty'))
        mod_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mod_icon.setObjectName('secondaryText')
        content_layout.addWidget(mod_icon)
        layout.addWidget(content_widget)
        slot_frame.chapter_id = chapter_id
        slot_frame.assigned_mod = None
        slot_frame.content_widget = content_widget
        slot_frame.mod_icon = mod_icon
        slot_frame.is_selected = False
        slot_frame.click_handler = lambda: self.on_slot_clicked(slot_frame)
        slot_frame.double_click_handler = lambda: self.on_slot_frame_double_clicked(slot_frame)
        self.update_slot_visual_state(slot_frame)
        return slot_frame

    def update_slot_visual_state(self, slot_frame: SlotFrame):
        user_bg_hex = get_theme_color(self.app_state.local_config, 'background', None)
        if user_bg_hex and self._is_valid_hex_color(user_bg_hex):
            slot_bg_color = f"#C0{user_bg_hex.lstrip('#')}"
        else:
            slot_bg_color = 'rgba(0, 0, 0, 150)'
        slot_border_color = get_theme_color(self.app_state.local_config, 'border', 'white')
        direct_launch_slot_id = self.app_state.local_config.get('direct_launch_slot_id', -1)
        is_direct_launch_slot = direct_launch_slot_id >= 0 and slot_frame.chapter_id >= 0 and (slot_frame.chapter_id == direct_launch_slot_id)
        border_style = '3px dashed' if is_direct_launch_slot else '3px solid'
        if getattr(slot_frame, 'is_selected', False):
            border_color = slot_border_color
            bg_color = slot_bg_color.replace('0.75', '0.9').replace('150', '200')
        else:
            border_color = slot_border_color
            bg_color = slot_bg_color
        slot_frame.setStyleSheet(f"\n            QFrame#mod_slot {{\n                border: {border_style} {border_color};\n                background-color: {bg_color};\n            }}\n            QFrame#mod_slot:hover {{\n                border: {border_style} {border_color};\n                background-color: {bg_color.replace('150', '180').replace('0.75', '0.85')};\n            }}\n        ")

    def _is_valid_hex_color(self, s: str) -> bool:
        return self.settings_manager.is_valid_hex_color(s)

    def _get_chapter_name(self, chapter_id: int) -> str:
        chapter_names = {0: tr('chapters.menu'), 1: tr('tabs.chapter_1'), 2: tr('tabs.chapter_2'), 3: tr('tabs.chapter_3'), 4: tr('tabs.chapter_4')}
        return chapter_names.get(chapter_id, str(chapter_id + 1))

    def on_slot_clicked(self, slot_frame: SlotFrame):
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        if not is_chapter_mode:
            if slot_frame.assigned_mod:
                mod_name = getattr(slot_frame.assigned_mod, 'name', getattr(slot_frame.assigned_mod, 'key', 'Unknown'))
                if self.feedback_manager.ask_question('ui.remove_mod_from_slot', 'ui.remove_mod_question', '', False, mod_name=mod_name):
                    self.remove_mod_from_slot(slot_frame, slot_frame.assigned_mod)
                    self.save_slots_state()
            else:
                self.show_mod_selection_for_slot(slot_frame)
        else:
            for other_slot in self.app_state.slots.values():
                if other_slot != slot_frame:
                    other_slot.is_selected = False
                    self.update_slot_visual_state(other_slot)
            slot_frame.is_selected = not slot_frame.is_selected
            self.update_slot_visual_state(slot_frame)
            if slot_frame.is_selected:
                selected_chapter = slot_frame.chapter_id
                self.app_state.selected_chapter_id = selected_chapter
                self.slots_updated.emit()
            else:
                self.app_state.selected_chapter_id = None
                self.slots_updated.emit()

    def on_slot_frame_double_clicked(self, slot_frame: SlotFrame):
        if slot_frame.chapter_id < 0:
            return
        direct_launch_slot_id = self.app_state.local_config.get('direct_launch_slot_id', -1)
        current_is_direct = slot_frame.chapter_id == direct_launch_slot_id
        if not current_is_direct:
            chapter_name = self._get_chapter_name(slot_frame.chapter_id)
            if self.feedback_manager.ask_question('ui.direct_launch', 'ui.enable_direct_launch', '', False, chapter=chapter_name):
                self.toggle_direct_launch_for_slot(slot_frame.chapter_id)
        else:
            chapter_name = self._get_chapter_name(slot_frame.chapter_id)
            if self.feedback_manager.ask_question('ui.direct_launch', 'ui.disable_direct_launch', '', False, chapter=chapter_name):
                self.toggle_direct_launch_for_slot(-1)

    def assign_mod_to_slot(self, slot_frame: SlotFrame, mod_data, save_state: bool = True):
        slot_frame.assigned_mod = mod_data
        if slot_frame.content_widget:
            slot_frame.content_widget.setParent(None)
            slot_frame.content_widget = None
            slot_frame.mod_icon = None
        is_large_slot = slot_frame.chapter_id < 0
        title_label = None
        layout = slot_frame.layout()
        if layout:
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item and item.widget() and isinstance(item.widget(), QLabel):
                    title_label = item.widget()
                    break
        if is_large_slot and title_label:
            title_label.setVisible(False)
        new_content_widget = QWidget()
        new_content_layout = QHBoxLayout(new_content_widget)
        new_content_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        mod_icon = QLabel()
        mod_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        border_color = self.app_state.local_config.get('custom_color_border') or 'white'
        mod_icon.setStyleSheet(f'border: 1px solid {border_color};')
        text_vbox = QVBoxLayout()
        text_vbox.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        name_label = QLabel()
        status_text, status_color = ('', 'gray')
        is_local_mod = getattr(mod_data, 'is_local_mod', False)
        if is_large_slot:
            new_content_layout.setContentsMargins(8, 0, 8, 0)
            new_content_layout.setSpacing(10)
            mod_icon.setFixedSize(48, 48)
            text_vbox.setSpacing(2)
            name_label.setWordWrap(True)
            name_label.setStyleSheet('font-weight: bold; font-size: 13px; border: none; background: transparent;')
            name_label.setText(mod_data.name)
            if is_local_mod:
                status_text, status_color = (tr('defaults.local_mod'), '#FFD700')
            else:
                needs_update = any((self.mod_manager.mod_has_files_for_chapter(mod_data, i) and self.mod_manager.get_mod_status(mod_data, i) == 'update' for i in range(5)))
                status_text, status_color = (tr('status.update_available'), 'orange') if needs_update else (tr('status.version_current'), 'lightgreen')
            version_label = QLabel(status_text)
            version_label.setStyleSheet(f'color: {status_color}; font-size: 10px; border: none; background: transparent;')
        else:
            new_content_layout.setContentsMargins(8, 0, 8, 0)
            new_content_layout.setSpacing(8)
            mod_icon.setFixedSize(40, 40)
            text_vbox.setSpacing(1)
            name_label.setStyleSheet('font-weight: bold; font-size: 11px; border: none; background: transparent;')
            original_name = mod_data.name
            display_name = original_name[:7] + '...' if len(original_name) > 10 else original_name
            name_label.setText(display_name)
            name_label.setToolTip(original_name)
            if is_local_mod:
                status_text, status_color = (tr('tags.local'), '#FFD700')
            else:
                needs_update = any((self.mod_manager.mod_has_files_for_chapter(mod_data, i) and self.mod_manager.get_mod_status(mod_data, i) == 'update' for i in range(5)))
                status_text, status_color = (tr('status.update_short'), 'orange') if needs_update else (tr('status.current_short'), 'lightgreen')
            version_label = QLabel(status_text)
            version_label.setStyleSheet(f'color: {status_color}; font-size: 9px; border: none; background: transparent;')
        load_mod_icon_universal(mod_icon, mod_data, 32)
        new_content_layout.addWidget(mod_icon)
        text_vbox.addWidget(name_label)
        text_vbox.addWidget(version_label)
        new_content_layout.addLayout(text_vbox)
        new_content_layout.addStretch()
        layout = slot_frame.layout()
        if layout:
            layout.addWidget(new_content_widget)
        slot_frame.content_widget = new_content_widget
        slot_frame.mod_icon = mod_icon
        self.mod_widgets_update_needed.emit()
        if slot_frame.chapter_id == -1:
            self.update_chapter_indicators(mod_data)
        self.action_button_update_needed.emit()
        if save_state:
            self.save_slots_state()

    def remove_mod_from_slot(self, slot_frame: SlotFrame, mod_data):
        slot_frame.assigned_mod = None
        if slot_frame.content_widget:
            slot_frame.content_widget.setParent(None)
            slot_frame.content_widget = None
        slot_frame.mod_icon = None
        is_large_slot = slot_frame.chapter_id < 0
        title_label = None
        layout = slot_frame.layout()
        if layout:
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item and item.widget() and isinstance(item.widget(), QLabel):
                    title_label = item.widget()
                    break
        if is_large_slot and title_label:
            title_label.setVisible(True)
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mod_icon = QLabel(tr('ui.empty'))
        mod_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mod_icon.setObjectName('secondaryText')
        content_layout.addWidget(mod_icon)
        layout = slot_frame.layout()
        if layout:
            layout.addWidget(content_widget)
        slot_frame.content_widget = content_widget
        slot_frame.mod_icon = mod_icon
        self.mod_widgets_update_needed.emit()
        if slot_frame.chapter_id == -1:
            self.update_chapter_indicators(None)
        self.action_button_update_needed.emit()

    def show_mod_selection_for_slot(self, slot_frame: SlotFrame):
        if not self.parent_widget:
            return
        installed_mods = self.parent_widget._get_installed_mods_list()
        available_mods = []
        for mod_info in installed_mods:
            if not mod_info:
                continue
            mod_exists = self.mod_manager.check_mod_exists(mod_info)
            if not mod_exists:
                continue
            mod_modgame = mod_info.get('modgame', 'deltarune')
            slot_id = slot_frame.chapter_id
            if slot_id == -10:
                if mod_modgame != 'deltarunedemo':
                    continue
            elif slot_id == -20:
                if mod_modgame != 'undertale':
                    continue
            elif slot_id == -1:
                if mod_modgame not in ['deltarune', 'deltarunedemo']:
                    continue
            elif mod_modgame != 'deltarune':
                continue
            mod_data = self.parent_widget._create_mod_object_from_info(mod_info)
            if mod_data and (not self.find_mod_in_slots(mod_data)):
                available_mods.append(mod_data)
        if not available_mods:
            self.feedback_manager.show_info('ui.no_available_mods', tr('ui.no_mods_to_insert'))
            return
        dialog = QDialog(self.parent_widget)
        dialog.setWindowTitle(tr('dialogs.select_mod'))
        dialog.setFixedSize(350, 250)
        layout = QVBoxLayout(dialog)
        label = QLabel(tr('ui.select_mod_for_slot'))
        layout.addWidget(label)
        mod_list = QListWidget()
        for mod_data in available_mods:
            mod_list.addItem(mod_data.name)
        layout.addWidget(mod_list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_items = mod_list.selectedItems()
            if selected_items:
                selected_index = mod_list.row(selected_items[0])
                selected_mod = available_mods[selected_index]
                self.assign_mod_to_slot(slot_frame, selected_mod)

    def find_mod_in_slots(self, mod_data, exclude_chapter_id: Optional[int] = None):
        if not mod_data:
            return None
        mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
        if not mod_key:
            return None
        for slot_frame in self.app_state.slots.values():
            if exclude_chapter_id is not None and slot_frame.chapter_id == exclude_chapter_id:
                continue
            if slot_frame.assigned_mod:
                assigned_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if assigned_key == mod_key:
                    return slot_frame
        return None

    def remove_mod_from_all_slots(self, mod_data):
        mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
        if not mod_key:
            return
        for slot_frame in self.app_state.slots.values():
            if slot_frame.assigned_mod:
                assigned_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if assigned_key == mod_key:
                    self.remove_mod_from_slot(slot_frame, slot_frame.assigned_mod)
        self.save_slots_state()

    def clear_all_slots(self):
        for slot_frame in self.app_state.slots.values():
            if slot_frame.assigned_mod:
                self.remove_mod_from_slot(slot_frame, slot_frame.assigned_mod)
            slot_frame.is_selected = False
            self.update_slot_visual_state(slot_frame)

    def update_all_slots_visual_state(self):
        for slot_frame in self.app_state.slots.values():
            self.update_slot_visual_state(slot_frame)

    def create_chapter_indicators(self, active_slots_layout=None):
        chapter_names = [tr('ui.menu_label'), tr('ui.chapter_1_label'), tr('ui.chapter_2_label'), tr('ui.chapter_3_label'), tr('ui.chapter_4_label')]
        self.chapter_indicators = {}
        main_text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
        for i, chapter_name in enumerate(chapter_names):
            indicator_frame = QFrame()
            indicator_layout = QVBoxLayout(indicator_frame)
            indicator_layout.setContentsMargins(5, 5, 5, 5)
            indicator_layout.setSpacing(2)
            chapter_label = QLabel(chapter_name)
            chapter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chapter_label.setStyleSheet(f'color: {main_text_color}; font-size: 14px; font-weight: bold;')
            status_label = QLabel('?')
            status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_label.setStyleSheet('color: #FFD700; font-size: 16px; font-weight: bold;')
            indicator_layout.addWidget(chapter_label)
            indicator_layout.addWidget(status_label)
            self.chapter_indicators[i] = {'status_label': status_label, 'chapter_label': chapter_label, 'frame': indicator_frame}
            if active_slots_layout is not None:
                active_slots_layout.addWidget(indicator_frame)

    def update_chapter_indicators(self, mod=None):
        if not hasattr(self, 'chapter_indicators') or not self.chapter_indicators:
            return
        if mod is None:
            for i in range(5):
                if i in self.chapter_indicators:
                    self.chapter_indicators[i]['status_label'].setText('?')
                    self.chapter_indicators[i]['status_label'].setStyleSheet('color: #FFD700; font-size: 16px; font-weight: bold;')
        else:
            for i in range(5):
                if i in self.chapter_indicators:
                    has_files = self.mod_manager.mod_has_files_for_chapter(mod, i)
                    if has_files:
                        self.chapter_indicators[i]['status_label'].setText('✓')
                        self.chapter_indicators[i]['status_label'].setStyleSheet('color: #00FF00; font-size: 16px; font-weight: bold;')
                    else:
                        self.chapter_indicators[i]['status_label'].setText('✗')
                        self.chapter_indicators[i]['status_label'].setStyleSheet('color: #FF0000; font-size: 16px; font-weight: bold;')

    def update_chapter_indicators_style(self):
        if hasattr(self, 'chapter_indicators') and self.chapter_indicators:
            main_text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
            for indicator_data in self.chapter_indicators.values():
                if 'chapter_label' in indicator_data:
                    indicator_data['chapter_label'].setStyleSheet(f'color: {main_text_color}; font-size: 14px; font-weight: bold;')

    def toggle_direct_launch_for_slot(self, slot_id: int):
        self.app_state.local_config['direct_launch_slot_id'] = slot_id
        self.settings_manager.write_local_config()
        self.update_all_slots_visual_state()
        self.action_button_update_needed.emit()

    def get_slots_config_key(self, game_mode_instance=None, is_chapter_mode: Optional[bool] = None):
        if game_mode_instance is None:
            game_mode_instance = self.app_state.game_mode
        if is_chapter_mode is None:
            is_chapter_mode = self.app_state.current_mode == 'chapter'
        if isinstance(game_mode_instance, DemoGameMode):
            return 'saved_slots_deltarunedemo'
        elif isinstance(game_mode_instance, UndertaleGameMode):
            return 'saved_slots_undertale'
        else:
            return 'saved_slots_deltarune_chapter' if is_chapter_mode else 'saved_slots_deltarune'

    def save_slots_state(self):
        if not hasattr(self.app_state, 'slots'):
            return
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        config_key = self.get_slots_config_key(self.app_state.game_mode, is_chapter_mode)
        slots_data = {}
        for slot_id, slot_frame in self.app_state.slots.items():
            if slot_frame.assigned_mod:
                mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if mod_key:
                    slots_data[str(slot_id)] = {'mod_key': mod_key, 'mod_name': slot_frame.assigned_mod.name}
        self.app_state.local_config[config_key] = slots_data
        self.settings_manager.write_local_config()

    def load_slots_state(self, mode=None):
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        config_key = self.get_slots_config_key(self.app_state.game_mode, is_chapter_mode)
        for slot in self.app_state.slots.values():
            if slot.assigned_mod:
                self.remove_mod_from_slot(slot, slot.assigned_mod)
        if isinstance(self.app_state.game_mode, DemoGameMode):
            config_key = 'saved_slots_deltarunedemo'
        elif isinstance(self.app_state.game_mode, UndertaleGameMode):
            config_key = 'saved_slots_undertale'
        else:
            is_chapter_mode = self.app_state.current_mode == 'chapter'
            config_key = 'saved_slots_deltarune_chapter' if is_chapter_mode else 'saved_slots_deltarune'
        slots_data = self.app_state.local_config.get(config_key, {})
        if not slots_data:
            return
        for slot_id, slot_data in list(slots_data.items()):
            try:
                numeric_slot_id = int(slot_id)
            except ValueError:
                continue
            is_chapter_mode = self.app_state.current_mode == 'chapter'
            if isinstance(self.app_state.game_mode, DemoGameMode):
                if numeric_slot_id != -10:
                    continue
            elif isinstance(self.app_state.game_mode, UndertaleGameMode):
                if numeric_slot_id != -20:
                    continue
            elif is_chapter_mode:
                if numeric_slot_id not in [0, 1, 2, 3, 4]:
                    continue
            elif numeric_slot_id != -1:
                continue
            if numeric_slot_id not in self.app_state.slots:
                continue
            slot_frame = self.app_state.slots[numeric_slot_id]
            mod_key = slot_data.get('mod_key')
            if not mod_key:
                continue
            mod_data = None
            if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                for mod in self.app_state.all_mods:
                    if getattr(mod, 'key', None) == mod_key:
                        mod_data = mod
                        break
            if not mod_data and self.parent_widget:
                installed_mods = self.parent_widget._get_installed_mods_list()
                for installed_mod in installed_mods:
                    installed_mod_key = installed_mod.get('mod_key') or installed_mod.get('key') or installed_mod.get('name')
                    if installed_mod_key == mod_key:
                        mod_data = self.parent_widget._create_mod_object_from_info(installed_mod)
                        break
            if not mod_data and self.parent_widget:
                mod_config = self.mod_manager.get_mod_config(mod_key)
                if mod_config:
                    mod_data = self.parent_widget._create_mod_object_from_info(mod_config)
            if mod_data:
                current_slot = self.find_mod_in_slots(mod_data)
                if not current_slot:
                    self.assign_mod_to_slot(slot_frame, mod_data, save_state=False)
            elif slot_id in slots_data:
                del slots_data[slot_id]
        if slots_data != self.app_state.local_config.get(config_key, {}):
            self.app_state.local_config[config_key] = slots_data
            self.settings_manager.write_json(self.app_state.config_path, self.app_state.local_config)
        QTimer.singleShot(100, self.slots_updated.emit)
        QTimer.singleShot(200, self.mod_widgets_update_needed.emit)
        QTimer.singleShot(300, self.action_button_update_needed.emit)

    def is_mod_in_specific_slot(self, mod_data, chapter_id: int) -> bool:
        if not mod_data:
            return False
        mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
        if not mod_key:
            return False
        for slot_frame in self.app_state.slots.values():
            if slot_frame.chapter_id == chapter_id and slot_frame.assigned_mod:
                assigned_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if assigned_key == mod_key:
                    return True
        return False

    def refresh_slots_content(self):
        for slot_frame in self.app_state.slots.values():
            if slot_frame.assigned_mod:
                self.assign_mod_to_slot(slot_frame, slot_frame.assigned_mod, save_state=False)

    def check_active_slots_need_updates(self) -> bool:
        for slot_frame in self.app_state.slots.values():
            if not slot_frame.assigned_mod:
                continue
            mod_data = slot_frame.assigned_mod
            is_local_mod = getattr(mod_data, 'is_local_mod', False)
            if is_local_mod:
                continue
            for i in range(5):
                if self.mod_manager.mod_has_files_for_chapter(mod_data, i):
                    status = self.mod_manager.get_mod_status(mod_data, i)
                    if status == 'update':
                        return True
        return False
