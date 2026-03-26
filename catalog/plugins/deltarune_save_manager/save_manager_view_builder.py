import importlib.util
import os
from typing import Any, override

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


def tr(k, **kw):
    return k


class _SlotRowFrame(QFrame):
    hover_entered = pyqtSignal(int, int)
    hover_left = pyqtSignal(int, int)
    clicked = pyqtSignal(int, int)
    double_clicked = pyqtSignal(int, int)

    def __init__(self, chapter: int, slot: int, parent=None) -> None:
        super().__init__(parent)
        self._chapter = chapter
        self._slot = slot

    @override
    def enterEvent(self, ev):
        self.hover_entered.emit(self._chapter, self._slot)
        super().enterEvent(ev)

    @override
    def leaveEvent(self, ev):
        self.hover_left.emit(self._chapter, self._slot)
        super().leaveEvent(ev)

    @override
    def mousePressEvent(self, ev):
        if ev and ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._chapter, self._slot)
        super().mousePressEvent(ev)

    @override
    def mouseDoubleClickEvent(self, ev):
        if ev and ev.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._chapter, self._slot)
        super().mouseDoubleClickEvent(ev)


class _SlotHeightSyncMixin:
    def _sync_slot_height(self) -> None:
        row = getattr(self, "_slot_row", None)
        if row is None:
            return
        line_count = max(1, self.text().count("\n") + 1)
        vertical_padding = 16
        target_height = max(self.sizeHint().height(), self.fontMetrics().lineSpacing() * line_count + vertical_padding)
        self.setFixedHeight(target_height)
        row.setFixedHeight(target_height)
        row.updateGeometry()
        self.updateGeometry()

    def _schedule_slot_height_sync(self) -> None:
        QTimer.singleShot(0, self._sync_slot_height)

    def setText(self, text: str) -> None:  # noqa: N802 - PyQt6 method override must use camelCase
        super().setText(text)
        self._schedule_slot_height_sync()

    def event(self, ev):
        result = super().event(ev)
        if ev is not None and ev.type() in {
            QEvent.Type.Show,
            QEvent.Type.Polish,
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
            QEvent.Type.Resize,
            QEvent.Type.LayoutRequest,
        }:
            self._schedule_slot_height_sync()
        return result


class SaveManagerViewBuilder:

    def __init__(self, app_state, parent=None) -> None:
        self.app_state = app_state
        self.parent = parent
        self.widgets = {}

    def build(self) -> QFrame:
        plugin_dir = os.path.dirname(__file__)
        custom_controls_path = os.path.join(plugin_dir, 'custom_controls.py')
        spec = importlib.util.spec_from_file_location("custom_controls_module", custom_controls_path)
        if spec and spec.loader:
            custom_controls_module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(custom_controls_module)
                clickable_label_cls = custom_controls_module.ClickableLabel
            except (AttributeError, Exception) as err:
                if isinstance(err, AttributeError):
                    raise ImportError("ClickableLabel class is missing from custom_controls.py") from err
                else:
                    raise ImportError(f"Failed to load custom_controls.py: {err}") from err
        else:
            from PyQt6.QtCore import pyqtSignal
            from PyQt6.QtWidgets import QLabel as QLabelBase

            class _ClickableLabel(QLabelBase):
                clicked = pyqtSignal(int, int)
                double_clicked = pyqtSignal(int, int)

                def __init__(self, chapter, slot, *args, **kwargs) -> None:
                    super().__init__(*args, **kwargs)
                    self._ch = chapter
                    self._sl = slot

                def mousePressEvent(self, ev):
                    if ev and ev.button() == Qt.MouseButton.LeftButton:
                        self.clicked.emit(self._ch, self._sl)
                    super().mousePressEvent(ev)

                def mouseDoubleClickEvent(self, ev):
                    if ev and ev.button() == Qt.MouseButton.LeftButton:
                        self.double_clicked.emit(self._ch, self._sl)
                    super().mouseDoubleClickEvent(ev)

            clickable_label_cls = _ClickableLabel

        slot_label_cls = type("SlotClickableLabel", (_SlotHeightSyncMixin, clickable_label_cls), {})

        save_manager_widget = QFrame(self.parent)
        save_manager_widget.setObjectName('save_manager_widget')
        lay = QVBoxLayout(save_manager_widget)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        top = QHBoxLayout()
        top.setAlignment(Qt.AlignmentFlag.AlignCenter)
        save_back_btn = QPushButton(tr('ui.back_button'))
        save_back_btn.setVisible(False)
        top.addWidget(save_back_btn)
        change_save_path_btn = QPushButton(tr('buttons.change_save_path'))
        top.addWidget(change_save_path_btn)
        lay.addLayout(top)
        save_tabs = QTabWidget()
        slot_labels = {}
        slot_rows = {}
        for ch in range(1, 5):
            tab = QWidget()
            v = QVBoxLayout(tab)
            for s in range(3):
                row = _SlotRowFrame(ch, s)
                row.setObjectName(f'slot_row_{ch}_{s}')
                row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(0)
                lbl = slot_label_cls(ch, s, tr('status.empty_save_slot'))
                lbl.setObjectName(f'slot_{ch}_{s}')
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                lbl.setWordWrap(False)
                lbl._slot_row = row
                lbl._schedule_slot_height_sync()
                row_layout.addWidget(lbl, 1)
                v.addWidget(row)
                slot_labels[ch, s] = lbl
                slot_rows[ch, s] = row
            v.addStretch()
            save_tabs.addTab(tab, tr('ui.chapter_tab_title', chapter_num=ch))
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
        edit_btn = QPushButton(tr('buttons.edit'))
        show_btn = QPushButton(tr('buttons.show'))
        erase_btn = QPushButton(tr('buttons.erase'))
        import_btn = QPushButton(tr('buttons.import'))
        export_btn = QPushButton(tr('buttons.export'))
        for b in (edit_btn, show_btn, erase_btn, import_btn, export_btn):
            b.setVisible(False)
            slot_actions.addWidget(b)
        lay.addLayout(slot_actions)
        top.addWidget(rename_collection_btn)
        top.addWidget(delete_collection_btn)
        self.widgets['save_manager_widget'] = save_manager_widget
        self.widgets['save_back_btn'] = save_back_btn
        self.widgets['change_save_path_btn'] = change_save_path_btn
        self.widgets['save_tabs'] = save_tabs
        self.widgets['slot_labels'] = slot_labels
        self.widgets['slot_rows'] = slot_rows
        self.widgets['collection_name_lbl'] = collection_name_lbl
        self.widgets['left_col_btn'] = left_col_btn
        self.widgets['switch_collection_btn'] = switch_collection_btn
        self.widgets['right_col_btn'] = right_col_btn
        self.widgets['rename_collection_btn'] = rename_collection_btn
        self.widgets['delete_collection_btn'] = delete_collection_btn
        self.widgets['copy_from_main_btn'] = copy_from_main_btn
        self.widgets['copy_to_main_btn'] = copy_to_main_btn
        self.widgets['slot_actions'] = slot_actions
        self.widgets['edit_btn'] = edit_btn
        self.widgets['show_btn'] = show_btn
        self.widgets['erase_btn'] = erase_btn
        self.widgets['import_btn'] = import_btn
        self.widgets['export_btn'] = export_btn
        return save_manager_widget

    def get_widgets(self) -> dict[str, Any]:
        return self.widgets
