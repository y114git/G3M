from typing import Dict, Any
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton
from core.managers.localization_manager import tr
from PyQt6.QtWidgets import QTabWidget
from ui.widgets.custom_controls import ClickableLabel


class SaveManagerViewBuilder:

    def __init__(self, app_state, parent=None):
        self.app_state = app_state
        self.parent = parent
        self.widgets = {}

    def build(self) -> QFrame:
        save_manager_widget = QFrame()
        save_manager_widget.setObjectName('save_manager_widget')
        lay = QVBoxLayout(save_manager_widget)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        top = QHBoxLayout()
        top.setAlignment(Qt.AlignmentFlag.AlignCenter)
        save_back_btn = QPushButton(tr('ui.back_button'))
        save_back_btn.setVisible(False)
        change_save_path_btn = QPushButton(tr('buttons.change_save_path'))
        top.addWidget(change_save_path_btn)
        lay.addLayout(top)
        save_tabs = QTabWidget()
        slot_labels = {}
        for ch in range(1, 5):
            tab = QWidget()
            v = QVBoxLayout(tab)
            for s in range(3):
                lbl = ClickableLabel(ch, s, tr('status.empty_save_slot'))
                lbl.setObjectName(f'slot_{ch}_{s}')
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setMinimumWidth(300)
                lbl.setStyleSheet('border:1px solid white; background-color: rgba(0,0,0,128); padding:4px;')
                v.addWidget(lbl)
                slot_labels[ch, s] = lbl
            v.addStretch()
            save_tabs.addTab(tab, tr('ui.chapter_tab_title', chapter_num=ch))
        chapter_bar = QHBoxLayout()
        chapter_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chapter_bar.setSpacing(2)
        chapter_bar.setContentsMargins(0, 0, 0, 0)
        chapter_buttons = []
        for ch in range(1, 5):
            btn = QPushButton(tr('ui.chapter_button_title', chapter_num=ch))
            btn.setCheckable(True)
            btn.setMinimumWidth(80)
            if ch == 1:
                btn.setChecked(True)
            chapter_buttons.append(btn)
            chapter_bar.addWidget(btn)
        lay.addLayout(chapter_bar)
        lay.addWidget(save_tabs)
        collection_name_lbl = QLabel('')
        collection_name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        collection_name_lbl.setVisible(False)
        lay.addWidget(collection_name_lbl)
        bottom = QHBoxLayout()
        bottom.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        left_col_btn = QPushButton('←')
        bottom.addWidget(left_col_btn)
        switch_collection_btn = QPushButton(tr('buttons.additional_slots'))
        bottom.addWidget(switch_collection_btn)
        right_col_btn = QPushButton('→')
        bottom.addWidget(right_col_btn)
        lay.addLayout(bottom)
        rename_collection_btn = QPushButton(tr('buttons.rename_collection'))
        delete_collection_btn = QPushButton(tr('buttons.delete_collection'))
        rename_collection_btn.setVisible(False)
        delete_collection_btn.setVisible(False)
        copy_bar = QHBoxLayout()
        copy_bar.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        copy_bar.addStretch()
        copy_from_main_btn = QPushButton(tr('buttons.copy_from_main'))
        copy_bar.addWidget(copy_from_main_btn)
        copy_to_main_btn = QPushButton(tr('buttons.copy_to_main'))
        copy_bar.addWidget(copy_to_main_btn)
        copy_bar.addStretch()
        lay.addLayout(copy_bar)
        slot_actions = QHBoxLayout()
        slot_actions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        show_btn = QPushButton(tr('buttons.show'))
        erase_btn = QPushButton(tr('buttons.erase'))
        import_btn = QPushButton(tr('buttons.import'))
        export_btn = QPushButton(tr('buttons.export'))
        for b in (show_btn, erase_btn, import_btn, export_btn):
            b.setVisible(False)
            slot_actions.addWidget(b)
        lay.addLayout(slot_actions)
        top.addWidget(rename_collection_btn)
        top.addWidget(delete_collection_btn)
        save_manager_widget.setVisible(False)
        self.widgets['save_manager_widget'] = save_manager_widget
        self.widgets['save_back_btn'] = save_back_btn
        self.widgets['change_save_path_btn'] = change_save_path_btn
        self.widgets['save_tabs'] = save_tabs
        self.widgets['slot_labels'] = slot_labels
        self.widgets['chapter_buttons'] = chapter_buttons
        self.widgets['collection_name_lbl'] = collection_name_lbl
        self.widgets['left_col_btn'] = left_col_btn
        self.widgets['switch_collection_btn'] = switch_collection_btn
        self.widgets['right_col_btn'] = right_col_btn
        self.widgets['rename_collection_btn'] = rename_collection_btn
        self.widgets['delete_collection_btn'] = delete_collection_btn
        self.widgets['copy_from_main_btn'] = copy_from_main_btn
        self.widgets['copy_to_main_btn'] = copy_to_main_btn
        self.widgets['slot_actions'] = slot_actions
        self.widgets['show_btn'] = show_btn
        self.widgets['erase_btn'] = erase_btn
        self.widgets['import_btn'] = import_btn
        self.widgets['export_btn'] = export_btn
        return save_manager_widget

    def get_widgets(self) -> Dict[str, Any]:
        return self.widgets
