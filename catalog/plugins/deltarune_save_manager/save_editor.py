import json
import logging
import os
import re
import shutil
from functools import lru_cache

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ui.common.styling import clamp_border_radius, get_theme_color, rgba_from_color

logger = logging.getLogger(__name__)

FORMAT_LINE_COUNTS = {1: 10318, 2: 3055}
SAVE_PATH_RE = re.compile(r"filech(?P<chapter>\d+)_(?P<slot>\d+)$")

def tr(k, **kw):
    return k

def _parse_number(value: str):
    text = value.strip()
    if not text:
        return 0
    lower = text.lower()
    try:
        number = float(text) if "." in lower or "e" in lower else int(text)
    except ValueError:
        return 0
    return int(number) if isinstance(number, float) and number.is_integer() else number

def _serialize_number(value) -> str:
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, (int, float)) and abs(float(value)) >= 1e6:
        return f"{float(value):.0e}".replace("e+", "e+0")
    return str(value)

class _LineCursor:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.index = 0

    def _require_available(self, action: str, count: int = 1) -> None:
        if self.index + count > len(self.lines):
            raise ValueError(
                f"_LineCursor.{action} out of range at index {self.index} for {len(self.lines)} line(s)"
            )

    def next_string(self) -> str:
        self._require_available("next_string")
        value = self.lines[self.index].rstrip(" ")
        self.index += 1
        return value

    def next_number(self):
        self._require_available("next_number")
        value = _parse_number(self.lines[self.index])
        self.index += 1
        return value

    def skip(self, count: int) -> None:
        if count < 0:
            raise ValueError(f"_LineCursor.skip does not support negative count: {count}")
        self._require_available("skip", count)
        self.index += count

class _LazyPage(QWidget):
    def __init__(self, builder, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._builder = builder
        self._loaded = False

    def ensure_loaded(self) -> None:
        if self._loaded or self._builder is None:
            return
        self.layout().addWidget(self._builder())
        self._loaded = True
        self._builder = None

def _detect_format(lines: list[str]) -> int:
    count = len(lines)
    for save_format, expected in FORMAT_LINE_COUNTS.items():
        if expected <= count <= expected + 10:
            return save_format
    raise ValueError(f"Unrecognized save format ({count} lines)")

def parse_save_lines(lines: list[str], chapter: int, slot: int) -> dict:
    cursor = _LineCursor(lines)
    save_format = _detect_format(lines)
    player_name = cursor.next_string()
    vessel_name = cursor.next_string()
    cursor.skip(5)
    party = [int(cursor.next_number()) for _ in range(3)]
    money = cursor.next_number()
    xp = cursor.next_number()
    lv = cursor.next_number()
    inv = cursor.next_number()
    invc = cursor.next_number()
    in_dark_world = bool(cursor.next_number())
    character_count = 4 if save_format == 1 else 5
    characters = []
    for _ in range(character_count):
        character = {
            "health": cursor.next_number(),
            "maxHealth": cursor.next_number(),
            "attack": cursor.next_number(),
            "defence": cursor.next_number(),
            "magic": cursor.next_number(),
            "guts": cursor.next_number(),
            "weapon": int(cursor.next_number()),
            "primaryArmor": int(cursor.next_number()),
            "secondaryArmor": int(cursor.next_number()),
            "weaponStyle": cursor.next_string() if save_format == 1 else int(cursor.next_number()),
            "weaponStats": [],
            "spells": [],
        }
        for _ in range(4):
            weapon_stats = {
                "attack": cursor.next_number(),
                "defence": cursor.next_number(),
                "magic": cursor.next_number(),
                "bolts": cursor.next_number(),
                "grazeAmount": cursor.next_number(),
                "grazeSize": cursor.next_number(),
                "boltSpeed": cursor.next_number(),
                "special": cursor.next_number(),
            }
            if save_format == 2:
                weapon_stats["element"] = cursor.next_number()
                weapon_stats["elementAmount"] = cursor.next_number()
            character["weaponStats"].append(weapon_stats)
        for _ in range(12):
            character["spells"].append(int(cursor.next_number()))
        characters.append(character)
    battle = {
        "boltSpeed": cursor.next_number(),
        "grazeAmount": cursor.next_number(),
        "grazeSize": cursor.next_number(),
    }
    inventory = {"consumables": [], "keyItems": [], "weapons": [], "armors": []}
    if save_format == 1:
        for _ in range(13):
            inventory["consumables"].append(int(cursor.next_number()))
            inventory["keyItems"].append(int(cursor.next_number()))
            inventory["weapons"].append(int(cursor.next_number()))
            inventory["armors"].append(int(cursor.next_number()))
    else:
        for _ in range(13):
            inventory["consumables"].append(int(cursor.next_number()))
            inventory["keyItems"].append(int(cursor.next_number()))
        for _ in range(48):
            inventory["weapons"].append(int(cursor.next_number()))
            inventory["armors"].append(int(cursor.next_number()))
        inventory["storage"] = [int(cursor.next_number()) for _ in range(72)]
    battle["tension"] = cursor.next_number()
    battle["maxTension"] = cursor.next_number()
    light_world = {
        "weapon": int(cursor.next_number()),
        "armor": int(cursor.next_number()),
        "experience": cursor.next_number(),
        "level": cursor.next_number(),
        "money": cursor.next_number(),
        "health": cursor.next_number(),
        "maxHealth": cursor.next_number(),
        "attack": cursor.next_number(),
        "defence": cursor.next_number(),
        "weaponStrength": cursor.next_number(),
        "armorDefence": cursor.next_number(),
        "items": [],
        "phone": [],
    }
    for _ in range(8):
        light_world["items"].append(int(cursor.next_number()))
        light_world["phone"].append(int(cursor.next_number()))
    flags_count = 9999 if save_format == 1 else 2500
    flags = [cursor.next_number() for _ in range(flags_count)]
    return {
        "meta": {"format": save_format, "chapter": chapter, "slot": slot},
        "playerName": player_name,
        "vesselName": vessel_name,
        "party": party,
        "money": money,
        "xp": xp,
        "lv": lv,
        "inv": inv,
        "invc": invc,
        "inDarkWorld": in_dark_world,
        "characters": characters,
        "battle": battle,
        "inventory": inventory,
        "lightWorld": light_world,
        "flags": flags,
        "plot": cursor.next_number(),
        "room": int(cursor.next_number()),
        "time": cursor.next_number(),
    }

def serialize_save_data(save: dict) -> list[str]:
    save_format = save["meta"]["format"]
    lines = [save["playerName"], save["vesselName"], "", "", "", "", ""]
    lines.extend(_serialize_number(v) for v in save["party"])
    lines.extend(_serialize_number(save[key]) for key in ("money", "xp", "lv", "inv", "invc"))
    lines.append(_serialize_number(1 if save["inDarkWorld"] else 0))
    for character in save["characters"]:
        for key in ("health", "maxHealth", "attack", "defence", "magic", "guts", "weapon", "primaryArmor", "secondaryArmor"):
            lines.append(_serialize_number(character[key]))
        lines.append(str(character["weaponStyle"]))
        for weapon_stats in character["weaponStats"]:
            for key in ("attack", "defence", "magic", "bolts", "grazeAmount", "grazeSize", "boltSpeed", "special"):
                lines.append(_serialize_number(weapon_stats[key]))
            if save_format == 2:
                lines.append(_serialize_number(weapon_stats.get("element", 0)))
                lines.append(_serialize_number(weapon_stats.get("elementAmount", 0)))
        for spell in character["spells"]:
            lines.append(_serialize_number(spell))
    for key in ("boltSpeed", "grazeAmount", "grazeSize"):
        lines.append(_serialize_number(save["battle"][key]))
    if save_format == 1:
        for idx in range(13):
            for key in ("consumables", "keyItems", "weapons", "armors"):
                lines.append(_serialize_number(save["inventory"][key][idx] or 0))
    else:
        for idx in range(13):
            for key in ("consumables", "keyItems"):
                lines.append(_serialize_number(save["inventory"][key][idx] or 0))
        for idx in range(48):
            lines.append(_serialize_number(save["inventory"]["weapons"][idx] or 0))
            lines.append(_serialize_number(save["inventory"]["armors"][idx] or 0))
        for idx in range(72):
            lines.append(_serialize_number(save["inventory"]["storage"][idx] or 0))
    for key in ("tension", "maxTension"):
        lines.append(_serialize_number(save["battle"][key]))
    for key in ("weapon", "armor", "experience", "level", "money", "health", "maxHealth", "attack", "defence", "weaponStrength", "armorDefence"):
        lines.append(_serialize_number(save["lightWorld"][key]))
    for idx in range(8):
        lines.append(_serialize_number(save["lightWorld"]["items"][idx] or 0))
        lines.append(_serialize_number(save["lightWorld"]["phone"][idx] or 0))
    flags_count = 9999 if save_format == 1 else 2500
    for idx in range(flags_count):
        lines.append(_serialize_number(save["flags"][idx] if idx < len(save["flags"]) else 0))
    lines.append(_serialize_number(save["plot"]))
    lines.append(_serialize_number(save["room"]))
    lines.append(_serialize_number(save["time"]))
    return [line if idx <= 6 else f"{line} " for idx, line in enumerate(lines)]

@lru_cache(maxsize=1)
def load_simple_mode_data() -> dict:
    try:
        with open(os.path.join(os.path.dirname(__file__), "simple_mode_data.json"), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        logger.error("Failed to load simple mode data: %s", error)
        return {}

def _safe_name(meta: dict | None, fallback: str) -> str:
    return (meta or {}).get("displayName") or fallback

STORY_FLAG_GROUPS = {
    1: [
        ("ui.vessel_editor", ["VESSEL_HEAD", "VESSEL_BODY", "VESSEL_LEGS", "VESSEL_FOOD", "VESSEL_BLOOD_TYPE", "VESSEL_COLOR", "VESSEL_GIFT", "VESSEL_FEELING", "VESSEL_HONESTY", "VESSEL_PAIN_SEIZURE"]),
        ("ui.thrash_machine_editor", ["THRASH_MACHINE_HEAD", "THRASH_MACHINE_BODY", "THRASH_MACHINE_SHOE", "THRASH_MACHINE_HEAD_COLOR", "THRASH_MACHINE_BODY_COLOR", "THRASH_MACHINE_SHOE_COLOR"]),
        ("ui.dark_world_flags", ["RUNNING_TUTORIAL", "GOT_MOSS_CH1", "STARWALKER", "INSPECTED_BEDS_CH1", "GOT_SPINCAKE", "PEACEFUL_KING", "VIOLENT_ENDING_CH1", "JEVIL_PROGRESS", "EGG_ROOM_CH1", "MANUAL_STATUS"]),
        ("ui.onion_flags", ["ONION_CH1", "ONION_YOUR_NAME", "ONION_NAME"]),
        ("ui.light_world_flags", ["PICNIC_TABLE_FINGERS", "TALKED_BERDLY_CH1", "TALKED_CATTY", "TALKED_ALPHYS", "TALKED_UNDYNE", "USED_RUDY_SINK", "TALKED_RUDY", "TALKED_QC", "TALKED_BURGERPANTS", "TALKED_SANS", "GOT_SANS_PHONE", "TALKED_NOELLE", "ASGORE_FLOWERS_PROGRESS", "EGG_FRIDGE", "ENTERED_HOME_COUNT"]),
    ],
    2: [
        ("ui.weird_route_flags", ["WEIRDROUTE_FAILED", "WEIRDROUTE_PROGRESS_CH2", "BERDLY_BROKEN_ARM", "NOELLE_ICE_SHOCK_COUNT"]),
        ("ui.dark_world_flags", ["INSPECTED_BED_KRIS", "INSPECTED_BED_SUSIE", "INSPECTED_BED_LANCER", "INSPECTED_BED_CLOVER", "INSPECTED_BED_NOELLE", "INSPECTED_BEDS_CH2", "CAN_PARTY_ACT", "HUGGED_DUMMY", "RECRUITED_HACKER", "GOT_MOSS_CH2", "GOT_MOSS_WITH_NOELLE", "GOT_MOSS_WITH_SUSIE", "CARNIVAL_GIFT", "SPAMTON_PROGRESS", "RALSEI_PHOTO_STATUS", "EGG_ROOM_CH2", "CARS_HIT_COUNT"]),
        ("ui.light_world_flags", ["TOOK_ASRIEL_MONEY", "TALKED_METTATON", "ONION_CH2", "ONION_MISSED"]),
    ],
    3: [
        ("ui.gameshow_flags", ["UNLOCKED_SUSIEZILLA", "GAMESHOW_LETTER_FIRST", "GAMESHOW_LETTER_SECOND", "GAMESHOW_LETTER_THIRD", "RANK_BOARD_1", "RANK_BOARD_2", "SCORE_COOKING", "RANK_COOKING", "SCORE_LIGHTNERS_LIVE", "RANK_LIGHTNERS_LIVE", "SCORE_SUSIEZILLA", "RANK_SUSIEZILLA"]),
        ("ui.dark_world_flags", ["GOT_MOSS_CH3", "EGG_CH3", "SKIPPED_INTRO_CH3", "GOT_GOLDEN_TENNA", "ENTERED_1225_ROOM", "STARWALKER_CH3", "SUSIE_HEAL_COUNT", "KNIGHT_FIGHT", "SWORD_PROGRESS", "BIBLIOX_PROGRESS"]),
    ],
    4: [
        ("ui.dark_world_flags", ["GOT_MOSS_CH4", "EGG_CH4", "TALKED_KING_KNIGHT", "SAW_TENNA_KING_SCENE", "AXE_OF_JUSTICE_PROGRESS", "SUSIE_HEAL_COUNT", "DONATION_FOUNTAIN_COUNT", "PURIFIED_COUNT"]),
        ("ui.light_world_flags", ["GOT_SUSIE_PRIZE", "CLEANED_UP_BLOOD_STAIN", "SHOWED_FAMILY_PHOTO_TO_SUSIE", "SHOWED_ASRIEL_PHOTO_TO_SUSIE", "TALKED_NAPSTABLOOK_UNDYNE", "TALKED_NAPSTABLOOK_SHELTER", "TALKED_ASGORE_OUTFIT", "TALKED_ASGORE_WELLBEING", "INSPECTED_GLASS_WITH_NOELLE", "WEIRDROUTE_FAILED_CH4", "TALKED_METTATON_TENNA"]),
    ],
}

CUSTOMIZATION_FLAG_GROUPS = [
    ("ui.vessel_editor", [
        "VESSEL_HEAD",
        "VESSEL_BODY",
        "VESSEL_LEGS",
        "VESSEL_FOOD",
        "VESSEL_BLOOD_TYPE",
        "VESSEL_COLOR",
        "VESSEL_FEELING",
        "VESSEL_HONESTY",
        "VESSEL_PAIN_SEIZURE",
        "VESSEL_GIFT",
    ]),
    ("ui.thrash_machine_editor", [
        "THRASH_MACHINE_HEAD",
        "THRASH_MACHINE_BODY",
        "THRASH_MACHINE_SHOE",
        "THRASH_MACHINE_HEAD_COLOR",
        "THRASH_MACHINE_BODY_COLOR",
        "THRASH_MACHINE_SHOE_COLOR",
    ]),
]

class SaveEditorDialog(QDialog):
    def __init__(self, file_path: str, app_state=None, parent=None, tr_func=None) -> None:
        super().__init__(parent)
        self.tr_func = tr_func or tr
        self.app_state = app_state
        self.file_path = file_path
        self.simple_mode_data = load_simple_mode_data()
        self._simple_ready = False
        self._original_newline = "\n"
        self._had_trailing_newline = False
        self._load_failed = False
        self._switch_guard = False
        self._advanced_lines_cache = []
        self._advanced_labels_cache = {}
        self._simple_tab = QWidget()
        self._simple_layout = QVBoxLayout(self._simple_tab)
        self._simple_layout.setContentsMargins(0, 0, 0, 0)
        self._advanced_tab = QWidget()
        self._advanced_layout = QVBoxLayout(self._advanced_tab)
        self._advanced_layout.setContentsMargins(0, 0, 0, 0)
        self.advanced_details_toggle = QCheckBox()
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setMinimumSectionSize(80)
        self.mode_tabs = QTabWidget()
        self.mode_tabs.addTab(self._simple_tab, "")
        self.mode_tabs.addTab(self._advanced_tab, "")
        self.mode_tabs.currentChanged.connect(self._on_mode_changed)
        self.cancel_btn = QPushButton()
        self.save_btn = QPushButton()
        self.setWindowTitle(self.tr_func("dialogs.save_editing"))
        scale = 1.0 if not self.app_state else float(self.app_state.local_config.get("ui_scale", 1.0))
        self.resize(int(1120 * scale), int(760 * scale))
        root = QVBoxLayout(self)
        root.addWidget(self.mode_tabs)
        self.advanced_details_toggle.toggled.connect(lambda _checked: self._ensure_advanced_table())
        self._advanced_layout.addWidget(self.advanced_details_toggle)
        self._advanced_layout.addWidget(self.table)
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.save_btn.clicked.connect(self._on_save)
        btn_bar.addWidget(self.cancel_btn)
        btn_bar.addWidget(self.save_btn)
        root.addLayout(btn_bar)
        self._load_file()
        self._original_lines = self._current_advanced_lines()
        self.relocalize_ui()
        self.apply_theme()

    def relocalize_ui(self) -> None:
        self.setWindowTitle(self.tr_func("dialogs.save_editing"))
        self.mode_tabs.setTabText(0, self.tr_func("ui.simple_mode"))
        self.mode_tabs.setTabText(1, self.tr_func("ui.advanced_mode"))
        self.advanced_details_toggle.setText(self.tr_func("ui.show_advanced_details"))
        self.table.setHorizontalHeaderLabels(
            [
                self.tr_func("ui.line_label"),
                self.tr_func("ui.field_label"),
                self.tr_func("ui.value_label"),
            ]
        )
        self.cancel_btn.setText(self.tr_func("ui.cancel_button"))
        self.save_btn.setText(self.tr_func("ui.save"))

    def apply_theme(self) -> None:
        config = getattr(self.app_state, "local_config", {}) if self.app_state else {}
        border = get_theme_color(config, "border", "#039d5b")
        text = get_theme_color(config, "main_text", "#f5f5f5")
        button = get_theme_color(config, "elements", "#202020")
        button_hover = get_theme_color(config, "hover", "#2b2b2b")
        background = rgba_from_color(get_theme_color(config, "background", "#181818"))
        radius = clamp_border_radius(config.get("custom_border_radius", 10), width=48, height=36)
        self.setStyleSheet(
            f"""
            QDialog {{ background-color: {background}; color: {text}; }}
            QTabWidget::pane, QFrame#simpleSectionBody {{ border: 2px solid {border}; border-radius: {radius}px; }}
            QLabel#simpleSectionTitle {{ font-size: 13px; font-weight: 600; padding: 0 2px; }}
            QPushButton {{ background-color: {button}; border: 2px solid {border}; border-radius: {radius}px; color: {text}; padding: 6px 10px; }}
            QPushButton:hover {{ background-color: {button_hover}; }}
            QLineEdit, QComboBox, QSpinBox, QTableWidget {{ background-color: rgba(0,0,0,0.16); border: 2px solid {border}; border-radius: {radius}px; color: {text}; padding: 6px 8px; }}
            QComboBox, QLineEdit, QSpinBox {{ min-height: 36px; }}
            QScrollArea {{ border: none; background: transparent; }}
            """
        )

    def _load_file(self) -> None:
        self._original_newline = "\n"
        self._had_trailing_newline = False
        try:
            with open(self.file_path, "rb") as handle:
                sample = handle.read(8192)
            self._original_newline = "\r\n" if b"\r\n" in sample else "\n"
            with open(self.file_path, encoding="utf-8") as handle:
                content = handle.read()
            self._had_trailing_newline = content.endswith("\n")
            self._advanced_lines_cache = content.splitlines()
            self._try_build_simple_mode()
        except UnicodeDecodeError:
            self._load_failed = True
            logger.warning("SaveEditorDialog: file contains invalid UTF-8 bytes: %s", self.file_path)
            QMessageBox.warning(self, self.tr_func("errors.error"), self.tr_func("dialogs.save_file_error", error=self.tr_func("dialogs.invalid_utf8")))
        except OSError as error:
            self._load_failed = True
            logger.warning("SaveEditorDialog: failed to read file: %s", error)
            QMessageBox.warning(self, self.tr_func("errors.error"), self.tr_func("dialogs.save_file_error", error=str(error)))

    def _set_advanced_lines(self, lines: list[str]) -> None:
        self._advanced_lines_cache = list(lines)
        labels = self._advanced_labels(lines)
        self.table.setRowCount(0)
        for row, line in enumerate(lines):
            self.table.insertRow(row)
            label, details = labels[row] if row < len(labels) else ("", "")
            number_item = QTableWidgetItem(f"{row + 1}{f' ({label})' if self.advanced_details_toggle.isChecked() and label else ''}")
            field_item = QTableWidgetItem(details if self.advanced_details_toggle.isChecked() else label)
            for column, item in ((0, number_item), (1, field_item)):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
            self.table.setItem(row, 2, QTableWidgetItem(line))
        self.table.resizeColumnToContents(0)
        self.table.setColumnWidth(1, max(self.table.columnWidth(1), 260))

    def _current_advanced_lines(self) -> list[str]:
        if self.table.rowCount() == 0:
            return list(self._advanced_lines_cache)
        return [("" if self.table.item(row, 2) is None else self.table.item(row, 2).text()) for row in range(self.table.rowCount())]

    def _ensure_advanced_table(self) -> None:
        lines = self._current_advanced_lines()
        if lines:
            self._set_advanced_lines(lines)

    def _save_identity(self) -> tuple[int, int]:
        match = SAVE_PATH_RE.search(os.path.basename(self.file_path))
        if not match:
            raise ValueError(f"Unexpected save file name: {self.file_path}")
        return int(match.group("chapter")), int(match.group("slot"))

    def _try_build_simple_mode(self) -> None:
        try:
            chapter, slot = self._save_identity()
            self.save_data = parse_save_lines(self._current_advanced_lines(), chapter, slot)
        except Exception as error:
            logger.warning("SaveEditorDialog: simple mode unavailable: %s", error)
            self._simple_ready = False
            self._clear_layout(self._simple_layout)
            label = QLabel(self.tr_func("dialogs.simple_mode_unavailable"))
            label.setWordWrap(True)
            self._simple_layout.addWidget(label)
            return
        self._simple_ready = True
        self._rebuild_simple_mode()

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child is not None:
                self._clear_layout(child)

    def _wrap_scroll(self, widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        return scroll

    def _lazy_tabs(self, pages: list[tuple[str, object]]) -> QTabWidget:
        tabs = QTabWidget()
        for title, builder in pages:
            page = _LazyPage(builder)
            tabs.addTab(page, title)

        def ensure(index: int) -> None:
            page = tabs.widget(index)
            if not isinstance(page, _LazyPage):
                return
            page.ensure_loaded()
        tabs.currentChanged.connect(ensure)
        if tabs.count():
            ensure(0)
        return tabs

    def _section(self, title: str, layout_class=QFormLayout) -> tuple[QWidget, QFormLayout | QGridLayout | QVBoxLayout]:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        header = QLabel(title)
        header.setObjectName("simpleSectionTitle")
        body = QFrame()
        body.setObjectName("simpleSectionBody")
        layout = layout_class(body)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        outer.addWidget(header)
        outer.addWidget(body)
        return root, layout

    def _control_min_height(self, widget: QWidget, padding: int = 16) -> int:
        return max(36, widget.fontMetrics().height() + padding)

    def _configure_editor_widget(self, widget: QWidget) -> QWidget:
        widget.setMinimumHeight(self._control_min_height(widget))
        widget.setMinimumWidth(max(widget.minimumWidth(), 132))
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        return widget

    def _format_option_label(self, group: str, item_id: int) -> tuple[str, str]:
        meta = self._group_meta(group).get(str(item_id), {})
        label = _safe_name(meta, str(item_id))
        tooltip_parts = [label]
        if meta.get("description"):
            tooltip_parts.append(str(meta["description"]).strip())
        title = meta.get("title") or {}
        if isinstance(title, dict) and title.get("description"):
            tooltip_parts.append(str(title["description"]).strip())
        return f"{label} ({item_id})", "\n\n".join(part for part in tooltip_parts if part)

    def _make_spin(self, value, on_change, minimum=-999999, maximum=999999) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(int(value))
        spin.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        spin.valueChanged.connect(on_change)
        return self._configure_editor_widget(spin)

    def _make_line_edit(self, value: str, on_change) -> QLineEdit:
        edit = QLineEdit(value)
        edit.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        edit.textChanged.connect(on_change)
        return self._configure_editor_widget(edit)

    def _make_combo(self, current_id: int, options: list[tuple], on_change) -> QComboBox:
        combo = QComboBox()
        normalized_options: list[tuple[int, str, str]] = []
        for option in options:
            if len(option) >= 3:
                item_id, label, tooltip = option[0], option[1], option[2]
            elif len(option) == 2:
                item_id, label = option
                tooltip = str(label)
            else:
                continue
            normalized_options.append((int(item_id), str(label), str(tooltip)))
        seen = {item_id for item_id, _label, _tooltip in normalized_options}
        for item_id, label, tooltip in normalized_options:
            combo.addItem(label, item_id)
            combo.setItemData(combo.count() - 1, tooltip, Qt.ItemDataRole.ToolTipRole)
        if current_id not in seen:
            combo.addItem(f"{current_id} - {self.tr_func('ui.unknown_value')}", current_id)
            combo.setItemData(combo.count() - 1, str(current_id), Qt.ItemDataRole.ToolTipRole)
        combo.setCurrentIndex(max(0, combo.findData(current_id)))
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        combo.view().setWordWrap(True)
        combo.view().setUniformItemSizes(False)
        combo.view().setTextElideMode(Qt.TextElideMode.ElideNone)
        combo.view().setSpacing(2)
        combo.view().setStyleSheet("QAbstractItemView::item { padding: 6px 8px; min-height: 28px; }")
        combo.currentIndexChanged.connect(lambda idx: on_change(combo.itemData(idx)))
        return self._configure_editor_widget(combo)

    def _group_ids(self, group: str) -> dict[str, int]:
        return self.simple_mode_data[group]["ids"]

    def _group_meta(self, group: str) -> dict[str, dict]:
        return self.simple_mode_data[group]["meta"]

    def _option_list(self, group: str, allowed: list[int] | set[int], include_current: int | None = None) -> list[tuple[int, str, str]]:
        option_ids = list(allowed)
        if include_current is not None and include_current not in option_ids:
            option_ids.append(include_current)
        return sorted(((int(item_id), *self._format_option_label(group, int(item_id))) for item_id in option_ids), key=lambda item: (item[1].lower(), item[0]))

    def _chapter_content(self) -> dict:
        return self.simple_mode_data["chapters"]["meta"][str(self.save_data["meta"]["chapter"])]["content"]

    def _flag_id(self, name: str) -> int | None:
        return self._group_ids("flags").get(name)

    def _flag_meta(self, flag_id: int) -> dict:
        return self._group_meta("flags").get(str(flag_id), {})

    def _flag_name(self, flag_id: int) -> str:
        for name, value in self._group_ids("flags").items():
            if value == flag_id:
                return name
        return f"FLAG_{flag_id}"

    def _set_flag(self, flag_id: int, value) -> None:
        if 0 <= flag_id < len(self.save_data["flags"]):
            self.save_data["flags"][flag_id] = value

    def _format_time(self, seconds) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"

    def _parse_time(self, value: str):
        parts = value.split(":")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            return self.save_data["time"]
        hours, minutes, seconds = map(int, parts)
        return hours * 3600 + minutes * 60 + seconds

    def _advanced_labels(self, lines: list[str]) -> list[tuple[str, str]]:
        try:
            chapter, _slot = self._save_identity()
            save_format = _detect_format(lines)
        except Exception:
            return [("", "") for _ in lines]
        cache_key = (chapter, save_format, len(lines), lines[-2] if len(lines) > 1 else "")
        cached = self._advanced_labels_cache.get(cache_key)
        if cached is not None:
            return cached
        flags_ids = self._group_ids("flags")
        flags_meta = self._group_meta("flags")
        characters_meta = self._group_meta("characters")
        rooms_meta = self._group_meta("rooms")
        rows: list[tuple[str, str]] = []

        def add(label: str, details: str = "") -> None:
            rows.append((label, details))

        def add_indexed(prefix: str, count: int, details) -> None:
            for idx in range(count):
                info = details(idx)
                add(f"{prefix}[{idx}]", info if isinstance(info, str) else "")

        add("playerName", self.tr_func("ui.player_name"))
        add("vesselName", self.tr_func("ui.vessel_name"))
        add_indexed("unusedHeader", 5, lambda idx: self.tr_func("ui.reserved_line_label", number=idx + 1))
        add_indexed("party", 3, lambda idx: f"{self.tr_func('ui.party_member')} {idx + 1}")
        for key, title in (("money", self.tr_func("ui.money_label")), ("xp", self.tr_func("ui.xp")), ("lv", self.tr_func("ui.level")), ("inv", self.tr_func("ui.inventory_count")), ("invc", self.tr_func("ui.inventory_capacity")), ("inDarkWorld", self.tr_func("ui.in_dark_world"))):
            add(key, title)
        for character_id in range(4 if save_format == 1 else 5):
            character_name = _safe_name(characters_meta.get(str(character_id)), f"Character {character_id + 1}")
            prefix = f"characters[{character_id}]"
            for key, title in (("health", self.tr_func("ui.current_hp")), ("maxHealth", self.tr_func("ui.max_hp")), ("attack", self.tr_func("ui.attack")), ("defence", self.tr_func("ui.defence")), ("magic", self.tr_func("ui.magic")), ("guts", self.tr_func("ui.guts")), ("weapon", self.tr_func("ui.weapon_label")), ("primaryArmor", self.tr_func("ui.armor_one")), ("secondaryArmor", self.tr_func("ui.armor_two")), ("weaponStyle", self.tr_func("ui.weapon_style"))):
                add(f"{prefix}.{key}", f"{character_name}: {title}")
            for weapon_idx in range(4):
                weapon_prefix = f"{prefix}.weaponStats[{weapon_idx}]"
                for key in ("attack", "defence", "magic", "bolts", "grazeAmount", "grazeSize", "boltSpeed", "special"):
                    add(f"{weapon_prefix}.{key}", f"{character_name} {self.tr_func('ui.weapon_set_label', number=weapon_idx + 1)}: {key}")
                if save_format == 2:
                    add(f"{weapon_prefix}.element", f"{character_name} {self.tr_func('ui.weapon_set_label', number=weapon_idx + 1)}: {self.tr_func('ui.element')}")
                    add(f"{weapon_prefix}.elementAmount", f"{character_name} {self.tr_func('ui.weapon_set_label', number=weapon_idx + 1)}: {self.tr_func('ui.element_power')}")
            add_indexed(f"{prefix}.spells", 12, lambda idx, name=character_name: f"{name}: {self.tr_func('ui.spell_label')} {idx + 1}")
        for key in ("boltSpeed", "grazeAmount", "grazeSize"):
            add(f"battle.{key}", f"{self.tr_func('ui.battle')}: {key}")
        if save_format == 1:
            for idx in range(13):
                for key in ("consumables", "keyItems", "weapons", "armors"):
                    add(f"inventory.{key}[{idx}]", f"{key}[{idx + 1}]")
        else:
            for idx in range(13):
                add(f"inventory.consumables[{idx}]", f"consumables[{idx + 1}]")
                add(f"inventory.keyItems[{idx}]", f"keyItems[{idx + 1}]")
            add_indexed("inventory.weapons", 48, lambda idx: f"weapons[{idx + 1}]")
            add_indexed("inventory.armors", 48, lambda idx: f"armors[{idx + 1}]")
            add_indexed("inventory.storage", 72, lambda idx: f"storage[{idx + 1}]")
        add("battle.tension", f"{self.tr_func('ui.battle')}: {self.tr_func('ui.current_tp')}")
        add("battle.maxTension", f"{self.tr_func('ui.battle')}: {self.tr_func('ui.max_tp')}")
        for key, title in (("weapon", self.tr_func("ui.weapon_label")), ("armor", self.tr_func("ui.armor_label")), ("experience", self.tr_func("ui.experience")), ("level", self.tr_func("ui.level")), ("money", self.tr_func("ui.money_label")), ("health", self.tr_func("ui.current_hp")), ("maxHealth", self.tr_func("ui.max_hp")), ("attack", self.tr_func("ui.attack")), ("defence", self.tr_func("ui.defence")), ("weaponStrength", self.tr_func("ui.weapon_strength")), ("armorDefence", self.tr_func("ui.armor_defence"))):
            add(f"lightWorld.{key}", f"{self.tr_func('ui.light_world')}: {title}")
        add_indexed("lightWorld.items", 8, lambda idx: f"{self.tr_func('ui.items_label')} {idx + 1}")
        add_indexed("lightWorld.phone", 8, lambda idx: f"{self.tr_func('ui.phone_contacts')} {idx + 1}")
        flags_count = 9999 if save_format == 1 else 2500
        name_by_id = {value: key for key, value in flags_ids.items()}
        for flag_id in range(flags_count):
            meta = flags_meta.get(str(flag_id), {})
            name = name_by_id.get(flag_id, f"FLAG_{flag_id}")
            add(f"flags[{flag_id}]", f"{_safe_name(meta, name)}: {meta.get('description', name)}".strip(": "))
        add("plot", self.tr_func("ui.plot_label"))
        room_name = _safe_name(rooms_meta.get(str(_parse_number(lines[-2]) if len(lines) > 1 else 0)), self.tr_func("ui.room_label"))
        add("room", f"{self.tr_func('ui.room_label')}: {room_name}")
        add("time", self.tr_func("ui.playtime_label"))
        if len(rows) < len(lines):
            rows.extend([("", "")] * (len(lines) - len(rows)))
        self._advanced_labels_cache[cache_key] = rows[: len(lines)]
        return self._advanced_labels_cache[cache_key]

    def _flag_editor(self, flag_id: int) -> QWidget:
        meta = self._flag_meta(flag_id)
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = QLabel(_safe_name(meta, self._flag_name(flag_id)))
        label.setToolTip(meta.get("description", ""))
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        value = self.save_data["flags"][flag_id]
        value_type = meta.get("valueType", "number")
        rules = meta.get("valueRules") or {}
        inferred_boolean = value_type == "number" and not rules.get("map") and int(rules.get("min", -999999)) == 0 and int(rules.get("max", 999999)) == 1
        if value_type == "boolean" or inferred_boolean:
            editor = QCheckBox()
            inverted = bool(rules.get("invertedBoolean"))
            editor.setChecked(not bool(value) if inverted else bool(value))
            editor.stateChanged.connect(lambda state, fid=flag_id, inv=inverted: self._set_flag(fid, 0 if state and inv else 1 if state else 1 if inv else 0))
        elif value_type == "map" and rules.get("map"):
            items = sorted(((_parse_number(key), label) for key, label in rules["map"].items()), key=lambda item: float(item[0]))
            editor = self._make_combo(value, items, lambda selected, fid=flag_id: self._set_flag(fid, _parse_number(str(selected or 0))))
        elif value_type == "color":
            editor = self._make_spin(value, lambda new_value, fid=flag_id: self._set_flag(fid, new_value), 0, 31)
        else:
            editor = self._make_spin(value, lambda new_value, fid=flag_id: self._set_flag(fid, new_value), int(rules.get("min", -999999)), int(rules.get("max", 999999)))
        layout.addWidget(editor)
        return wrapper

    def _flag_group_widget(self, title: str, names: list[str]) -> QWidget:
        group, layout = self._section(title)
        for name in names:
            flag_id = self._flag_id(name)
            if flag_id is None or flag_id not in self._chapter_content()["flags"]:
                continue
            layout.addRow(self._flag_editor(flag_id))
        return group

    def _build_customization_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        team_name_id = self._flag_id("TEAM_NAME")
        chapter_flags = set(self._chapter_content()["flags"])
        if team_name_id is not None and team_name_id in chapter_flags:
            team_box, team_layout = self._section(self.tr_func("ui.party_customization"))
            team_layout.addRow(self._flag_editor(team_name_id))
            layout.addWidget(team_box)
        for title_key, names in CUSTOMIZATION_FLAG_GROUPS:
            visible_names = []
            for name in names:
                flag_id = self._flag_id(name)
                if flag_id is not None and flag_id in chapter_flags:
                    visible_names.append(name)
            if visible_names:
                layout.addWidget(self._flag_group_widget(self.tr_func(title_key), visible_names))
        layout.addStretch()
        return page

    def _build_battle_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        battle_box, battle_layout = self._section(self.tr_func("ui.battle"))
        battle = self.save_data["battle"]
        for key, title, minimum, maximum in (
            ("tension", self.tr_func("ui.current_tp"), 0, 99999),
            ("maxTension", self.tr_func("ui.max_tp"), 0, 99999),
            ("boltSpeed", self.tr_func("ui.bolt_speed"), -99999, 99999),
            ("grazeAmount", self.tr_func("ui.graze_amount"), -99999, 99999),
            ("grazeSize", self.tr_func("ui.graze_size"), -99999, 99999),
        ):
            battle_layout.addRow(title, self._make_spin(battle[key], lambda value, field=key: battle.__setitem__(field, value), minimum, maximum))
        layout.addWidget(battle_box)
        chapter = self.save_data["meta"]["chapter"]
        if chapter >= 3:
            extras_box, extras_layout = self._section(self.tr_func("ui.chapter_extras"))
            if chapter == 3:
                points = self._flag_id("POINTS")
                if points is not None:
                    extras_layout.addRow(self._flag_editor(points))
            if chapter == 4:
                donation = self._flag_id("DONATION_FOUNTAIN_COUNT")
                purified = self._flag_id("PURIFIED_COUNT")
                if donation is not None:
                    extras_layout.addRow(self._flag_editor(donation))
                if purified is not None:
                    extras_layout.addRow(self._flag_editor(purified))
            if extras_layout.rowCount():
                layout.addWidget(extras_box)
        layout.addStretch()
        return page

    def _build_general_page(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        info_box, info_layout = self._section(self.tr_func("ui.general"))
        info_layout.addRow(self.tr_func("ui.chapter_label"), QLabel(str(self.save_data["meta"]["chapter"])))
        info_layout.addRow(self.tr_func("ui.slot_label"), QLabel(str(self.save_data["meta"]["slot"] + 1)))
        info_layout.addRow(self.tr_func("ui.player_name"), self._make_line_edit(self.save_data["playerName"], lambda text: self.save_data.__setitem__("playerName", text)))
        info_layout.addRow(self.tr_func("ui.vessel_name"), self._make_line_edit(self.save_data["vesselName"], lambda text: self.save_data.__setitem__("vesselName", text)))
        info_layout.addRow(self.tr_func("ui.money_label"), self._make_spin(self.save_data["money"], lambda value: self.save_data.__setitem__("money", value), 0, 9999999))
        info_layout.addRow(self.tr_func("ui.xp"), self._make_spin(self.save_data["xp"], lambda value: self.save_data.__setitem__("xp", value), 0, 9999999))
        info_layout.addRow(self.tr_func("ui.level"), self._make_spin(self.save_data["lv"], lambda value: self.save_data.__setitem__("lv", value), 0, 999999))
        info_layout.addRow(self.tr_func("ui.inventory_count"), self._make_spin(self.save_data["inv"], lambda value: self.save_data.__setitem__("inv", value), 0, 999999))
        info_layout.addRow(self.tr_func("ui.inventory_capacity"), self._make_spin(self.save_data["invc"], lambda value: self.save_data.__setitem__("invc", value), 0, 999999))
        info_layout.addRow(self.tr_func("ui.playtime_label"), self._make_line_edit(self._format_time(self.save_data["time"]), lambda text: self.save_data.__setitem__("time", self._parse_time(text))))
        info_layout.addRow(self.tr_func("ui.plot_label"), self._make_spin(self.save_data["plot"], lambda value: self.save_data.__setitem__("plot", value), 0, 999999))
        info_layout.addRow(self.tr_func("ui.room_label"), self._make_combo(self.save_data["room"], self._option_list("rooms", self._chapter_content()["rooms"], self.save_data["room"]), lambda value: self.save_data.__setitem__("room", int(value or 0))))
        in_dark = QCheckBox(self.tr_func("ui.in_dark_world"))
        in_dark.setChecked(bool(self.save_data["inDarkWorld"]))
        in_dark.stateChanged.connect(lambda state: self.save_data.__setitem__("inDarkWorld", bool(state)))
        info_layout.addRow(in_dark)
        layout.addWidget(info_box)
        layout.addStretch()
        return root

    def _build_party_overview_page(self) -> QWidget:
        root = QWidget()
        layout = QFormLayout(root)
        options = self._option_list("characters", self._chapter_content()["characters"])
        for idx in range(3):
            layout.addRow(f"{self.tr_func('ui.party_member')} {idx + 1}", self._make_combo(self.save_data["party"][idx], options, lambda value, index=idx: self.save_data["party"].__setitem__(index, int(value or 0))))
        return root

    def _build_character_page(self, character_id: int) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        chapter = self._chapter_content()
        character_meta = self._group_meta("characters").get(str(character_id), {})
        character = self.save_data["characters"][character_id]
        stats_box, stats_layout = self._section(_safe_name(character_meta, str(character_id)))
        for key, title in (("health", self.tr_func("ui.current_hp")), ("maxHealth", self.tr_func("ui.max_hp")), ("attack", self.tr_func("ui.attack")), ("defence", self.tr_func("ui.defence")), ("magic", self.tr_func("ui.magic")), ("guts", self.tr_func("ui.guts"))):
            stats_layout.addRow(title, self._make_spin(character[key], lambda value, field=key: character.__setitem__(field, value), 0, 99999))
        allowed_weapons = chapter["weapons"] if not character_meta.get("allowedWeapons") else [item for item in chapter["weapons"] if item in character_meta["allowedWeapons"]]
        allowed_armors = chapter["armors"] if not character_meta.get("allowedArmors") else [item for item in chapter["armors"] if item in character_meta["allowedArmors"]]
        allowed_spells = chapter["spells"] if not character_meta.get("allowedSpells") else [item for item in chapter["spells"] if item in character_meta["allowedSpells"]]
        stats_layout.addRow(self.tr_func("ui.weapon_label"), self._make_combo(character["weapon"], self._option_list("weapons", allowed_weapons, character["weapon"]), lambda value: character.__setitem__("weapon", int(value or 0))))
        for key, title in (("primaryArmor", self.tr_func("ui.armor_one")), ("secondaryArmor", self.tr_func("ui.armor_two"))):
            stats_layout.addRow(title, self._make_combo(character[key], self._option_list("armors", allowed_armors, character[key]), lambda value, field=key: character.__setitem__(field, int(value or 0))))
        if self.save_data["meta"]["format"] == 2:
            stats_layout.addRow(self.tr_func("ui.weapon_style"), self._make_spin(character["weaponStyle"], lambda value: character.__setitem__("weaponStyle", value), -99999, 99999))
        else:
            stats_layout.addRow(self.tr_func("ui.weapon_style"), self._make_line_edit(str(character["weaponStyle"]), lambda text: character.__setitem__("weaponStyle", text)))
        layout.addWidget(stats_box)
        spells_box, spells_layout = self._section(self.tr_func("ui.spells"), QGridLayout)
        for idx in range(len(character["spells"])):
            row = idx % 6
            column = 0 if idx < 6 else 2
            spells_layout.addWidget(QLabel(f"{self.tr_func('ui.spell_label')} {idx + 1}"), row, column)
            spells_layout.addWidget(self._make_combo(character["spells"][idx], self._option_list("spells", allowed_spells, character["spells"][idx]), lambda value, index=idx: character["spells"].__setitem__(index, int(value or 0))), row, column + 1)
        layout.addWidget(spells_box)
        weapon_box, weapon_layout = self._section(self.tr_func("ui.weapon_sets"), QGridLayout)
        stat_titles = (
            ("attack", self.tr_func("ui.stat_attack_short")),
            ("defence", self.tr_func("ui.stat_defence_short")),
            ("magic", self.tr_func("ui.stat_magic_short")),
            ("bolts", self.tr_func("ui.bolts")),
            ("grazeAmount", self.tr_func("ui.graze")),
            ("grazeSize", self.tr_func("ui.graze_size")),
            ("boltSpeed", self.tr_func("ui.bolt_speed")),
            ("special", self.tr_func("ui.special")),
        )
        if self.save_data["meta"]["format"] == 2:
            stat_titles = (*stat_titles, ("element", self.tr_func("ui.element")), ("elementAmount", self.tr_func("ui.element_power")))
        for weapon_idx, weapon_stats in enumerate(character["weaponStats"]):
            title = QLabel(f"{self.tr_func('ui.set_label')} {weapon_idx + 1}")
            weapon_layout.addWidget(title, 0, weapon_idx * 2)
            for row, (key, label) in enumerate(stat_titles, start=1):
                weapon_layout.addWidget(QLabel(label), row, weapon_idx * 2)
                weapon_layout.addWidget(self._make_spin(weapon_stats.get(key, 0), lambda value, stats=weapon_stats, field=key: stats.__setitem__(field, value), -99999, 99999), row, weapon_idx * 2 + 1)
        layout.addWidget(weapon_box)
        layout.addStretch()
        return root

    def _build_inventory_page(self, key: str, group: str) -> QWidget:
        root = QWidget()
        layout = QGridLayout(root)
        chapter = self._chapter_content()
        allowed_key = "consumables" if key == "storage" else key
        values = self.save_data["inventory"][key]
        for idx, value in enumerate(values):
            layout.addWidget(QLabel(f"{self.tr_func('ui.slot_label')} {idx + 1}"), idx, 0)
            layout.addWidget(self._make_combo(value, self._option_list(group, chapter[allowed_key], value), lambda selected, index=idx: values.__setitem__(index, int(selected or 0))), idx, 1)
        return root

    def _build_light_world_page(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        stats_box, stats_layout = self._section(self.tr_func("ui.light_world"))
        light_world = self.save_data["lightWorld"]
        for key, title in (("health", self.tr_func("ui.current_hp")), ("maxHealth", self.tr_func("ui.max_hp")), ("level", self.tr_func("ui.level")), ("experience", self.tr_func("ui.experience")), ("attack", self.tr_func("ui.attack")), ("defence", self.tr_func("ui.defence")), ("money", self.tr_func("ui.money_label")), ("weaponStrength", self.tr_func("ui.weapon_strength")), ("armorDefence", self.tr_func("ui.armor_defence"))):
            stats_layout.addRow(title, self._make_spin(light_world[key], lambda value, field=key: light_world.__setitem__(field, value), 0, 99999))
        chapter = self._chapter_content()
        light_world_items = chapter["lightWorld"]["items"]
        weapon_options = [item_id for item_id in light_world_items if self._group_meta("lightWorldItems").get(str(item_id), {}).get("weapon")]
        armor_options = [item_id for item_id in light_world_items if self._group_meta("lightWorldItems").get(str(item_id), {}).get("armor")]
        stats_layout.addRow(self.tr_func("ui.weapon_label"), self._make_combo(light_world["weapon"], self._option_list("lightWorldItems", weapon_options, light_world["weapon"]), lambda value: light_world.__setitem__("weapon", int(value or 0))))
        stats_layout.addRow(self.tr_func("ui.armor_label"), self._make_combo(light_world["armor"], self._option_list("lightWorldItems", armor_options, light_world["armor"]), lambda value: light_world.__setitem__("armor", int(value or 0))))
        layout.addWidget(stats_box)
        items_box, items_layout = self._section(self.tr_func("ui.items_label"), QGridLayout)
        for idx in range(8):
            items_layout.addWidget(QLabel(f"{self.tr_func('ui.slot_label')} {idx + 1}"), idx, 0)
            items_layout.addWidget(self._make_combo(light_world["items"][idx], self._option_list("lightWorldItems", chapter["lightWorld"]["items"], light_world["items"][idx]), lambda value, index=idx: light_world["items"].__setitem__(index, int(value or 0))), idx, 1)
        layout.addWidget(items_box)
        phone_box, phone_layout = self._section(self.tr_func("ui.phone_contacts"), QGridLayout)
        for idx in range(8):
            phone_layout.addWidget(QLabel(f"{self.tr_func('ui.slot_label')} {idx + 1}"), idx, 0)
            phone_layout.addWidget(self._make_combo(light_world["phone"][idx], self._option_list("phoneContacts", chapter["lightWorld"]["phoneContacts"], light_world["phone"][idx]), lambda value, index=idx: light_world["phone"].__setitem__(index, int(value or 0))), idx, 1)
        layout.addWidget(phone_box)
        layout.addStretch()
        return root

    def _build_recruits_page(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        recruit_box, recruit_layout = self._section(self.tr_func("ui.recruits"))

        def set_recruit_value(flag_id: int, recruit_count: int, count: int) -> None:
            normalized = max(-1, min(recruit_count, int(count)))
            if recruit_count <= 1 or normalized in (0, -1):
                self._set_flag(flag_id, normalized)
            else:
                self._set_flag(flag_id, normalized / recruit_count)

        for enemy_id in self._chapter_content()["enemies"]:
            enemy_meta = self._group_meta("enemies").get(str(enemy_id), {})
            if not enemy_meta.get("recruitable"):
                continue
            recruit_flag = enemy_meta.get("recruitFlag")
            if recruit_flag is None:
                continue
            recruit_count = int(enemy_meta.get("recruitCount") or 1)
            current_value = self.save_data["flags"][recruit_flag]
            current_count = current_value if recruit_count <= 1 or current_value in (0, -1) else current_value * recruit_count
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            check = QCheckBox(_safe_name(enemy_meta, str(enemy_id)))
            check.setChecked(current_count == recruit_count)
            row_layout.addWidget(check)
            if recruit_count <= 1:
                check.stateChanged.connect(lambda state, fid=recruit_flag: self._set_flag(fid, 1 if state else 0))
            else:
                count_spin = self._make_spin(current_count, lambda value, fid=recruit_flag, rc=recruit_count, box=check: (set_recruit_value(fid, rc, value), box.setChecked(value == rc)), -1, recruit_count)
                check.stateChanged.connect(lambda state, fid=recruit_flag, rc=recruit_count, spin=count_spin: spin.setValue(rc if state else 0))
                row_layout.addWidget(count_spin)
            recruit_layout.addRow(row)
        layout.addWidget(recruit_box)
        layout.addStretch()
        return root

    def _build_flags_page(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        search = QLineEdit()
        search.setPlaceholderText(self.tr_func("ui.search_flags"))
        layout.addWidget(search)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        rows = []
        for flag_id in self._chapter_content()["flags"]:
            row = self._flag_editor(flag_id)
            container_layout.addWidget(row)
            haystack = (self._flag_name(flag_id) + " " + self._flag_meta(flag_id).get("description", "")).lower()
            rows.append((row, haystack))
        container_layout.addStretch()
        search.textChanged.connect(lambda text: [row.setVisible(text.lower().strip() in haystack if text.strip() else True) for row, haystack in rows])
        layout.addWidget(self._wrap_scroll(container), 1)
        return root

    def _build_story_page(self) -> QWidget:
        return self._lazy_tabs(
            [
                (
                    self.tr_func("ui.chapter_tab_title", chapter_num=chapter),
                    lambda current_chapter=chapter: self._wrap_scroll(self._build_story_chapter_page(current_chapter)),
                )
                for chapter in range(1, self.save_data["meta"]["chapter"] + 1)
            ]
        )

    def _build_story_chapter_page(self, chapter: int) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        for title_key, names in STORY_FLAG_GROUPS.get(chapter, []):
            layout.addWidget(self._flag_group_widget(self.tr_func(title_key), names))
        layout.addStretch()
        return page

    def _rebuild_simple_mode(self) -> None:
        self._clear_layout(self._simple_layout)
        party_pages = [(self.tr_func("ui.overview"), lambda: self._wrap_scroll(self._build_party_overview_page()))]
        for name in ("KRIS", "SUSIE", "RALSEI", "NOELLE"):
            character_id = self._group_ids("characters").get(name)
            if character_id is None or character_id >= len(self.save_data["characters"]) or character_id not in self._chapter_content()["characters"]:
                continue
            party_pages.append((_safe_name(self._group_meta("characters").get(str(character_id)), name.title()), lambda current_id=character_id: self._wrap_scroll(self._build_character_page(current_id))))
        inventory_pages = [(self.tr_func("ui.consumables"), lambda: self._wrap_scroll(self._build_inventory_page("consumables", "consumables")))]
        if "storage" in self.save_data["inventory"]:
            inventory_pages.append((self.tr_func("ui.storage"), lambda: self._wrap_scroll(self._build_inventory_page("storage", "consumables"))))
        inventory_pages.extend([
            (self.tr_func("ui.key_items"), lambda: self._wrap_scroll(self._build_inventory_page("keyItems", "keyitems"))),
            (self.tr_func("ui.weapons"), lambda: self._wrap_scroll(self._build_inventory_page("weapons", "weapons"))),
            (self.tr_func("ui.armors"), lambda: self._wrap_scroll(self._build_inventory_page("armors", "armors"))),
        ])
        simple_tabs = self._lazy_tabs([
            (self.tr_func("ui.general"), lambda: self._wrap_scroll(self._build_general_page())),
            (self.tr_func("ui.party"), lambda: self._lazy_tabs(party_pages)),
            (self.tr_func("ui.inventory"), lambda: self._lazy_tabs(inventory_pages)),
            (self.tr_func("ui.battle"), lambda: self._wrap_scroll(self._build_battle_page())),
            (self.tr_func("ui.customization"), lambda: self._wrap_scroll(self._build_customization_page())),
            (self.tr_func("ui.story"), self._build_story_page),
            (self.tr_func("ui.light_world"), lambda: self._wrap_scroll(self._build_light_world_page())),
            (self.tr_func("ui.recruits"), lambda: self._wrap_scroll(self._build_recruits_page())),
            (self.tr_func("ui.flags"), self._build_flags_page),
        ])
        self._simple_layout.addWidget(simple_tabs)

    def _on_mode_changed(self, index: int) -> None:
        if self._switch_guard or self._load_failed:
            return
        if index == 0:
            try:
                chapter, slot = self._save_identity()
                self.save_data = parse_save_lines(self._current_advanced_lines(), chapter, slot)
            except Exception as error:
                QMessageBox.warning(self, self.tr_func("errors.error"), self.tr_func("dialogs.simple_mode_parse_error", error=str(error)))
                self._switch_guard = True
                self.mode_tabs.setCurrentIndex(1)
                self._switch_guard = False
                return
            self._simple_ready = True
            self._rebuild_simple_mode()
        elif index == 1:
            if self._simple_ready:
                self._advanced_lines_cache = serialize_save_data(self.save_data)
            self._ensure_advanced_table()

    def _current_lines_for_save(self) -> list[str]:
        return serialize_save_data(self.save_data) if self.mode_tabs.currentIndex() == 0 and self._simple_ready else self._current_advanced_lines()

    def _on_cancel(self) -> None:
        if self._current_lines_for_save() != self._original_lines:
            reply = QMessageBox.question(self, self.tr_func("dialogs.cancel_changes"), self.tr_func("dialogs.changes_will_be_lost"))
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.reject()

    def _on_save(self) -> None:
        if self._load_failed:
            QMessageBox.warning(self, self.tr_func("errors.error"), self.tr_func("dialogs.save_file_error", error=self.tr_func("dialogs.cannot_save_unloaded")))
            return
        lines = self._current_lines_for_save()
        if lines != self._original_lines:
            reply = QMessageBox.question(self, self.tr_func("dialogs.save_changes"), self.tr_func("dialogs.original_save_overwrite"))
            if reply != QMessageBox.StandardButton.Yes:
                return
        tmp = None
        try:
            tmp = f"{self.file_path}.tmp"
            with open(tmp, "w", encoding="utf-8", newline="") as handle:
                content = self._original_newline.join(lines)
                if self._had_trailing_newline:
                    content += self._original_newline
                handle.write(content)
            shutil.move(tmp, self.file_path)
            self.accept()
        except PermissionError:
            QMessageBox.critical(self, self.tr_func("dialogs.access_error"), self.tr_func("dialogs.no_write_permissions", path=os.path.dirname(self.file_path)))
        except OSError as error:
            QMessageBox.critical(self, self.tr_func("errors.error"), self.tr_func("dialogs.save_file_error", error=str(error)))
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    logger.warning("SaveEditorDialog: failed to remove temporary file: %s", tmp)
