"""Overlay widget for displaying mod details with inline screenshot carousel."""

import collections
import contextlib
import copy
import html
import json
import logging
import threading
import time
from typing import Any, cast, override

from PyQt6 import sip as _sip
from PyQt6.QtCore import Qt, QThread, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyleFactory,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from adapters.gamebanana_adapter import GameBananaAPI
from services.localization_service import tr
from ui.common.styling import (
    apply_scroll_area_chrome,
    build_button_style,
    build_scrollbar_qss,
    get_border_radius,
    get_theme_colors,
    get_widget_border_radius,
    install_scroll_area_update_handlers,
    install_widget_update_handler,
    round_pixmap,
)
from ui.utils.image_loader import ImageLoaderRunnable
from ui.utils.ui_utils import UIAnimator
from utils.mod.utils import get_mod_id
from utils.native_integration import open_url_native
from workers import WorkerSignals

logger = logging.getLogger(__name__)

_MOD_DETAILS_CACHE: collections.OrderedDict[tuple[int, str], tuple[float, dict]] = (
    collections.OrderedDict()
)
_MOD_DETAILS_CACHE_LOCK = threading.Lock()
_MOD_DETAILS_CACHE_TTL_SECONDS = 600
_MOD_DETAILS_CACHE_MAX_ENTRIES = 64


def _safe_int(value, default: int | None = None) -> int | None:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_cached_mod_details(cache_key: tuple[int, str]) -> dict | None:
    with _MOD_DETAILS_CACHE_LOCK:
        cached = _MOD_DETAILS_CACHE.get(cache_key)
        if not cached:
            return None
        if time.time() - cached[0] >= _MOD_DETAILS_CACHE_TTL_SECONDS:
            _MOD_DETAILS_CACHE.pop(cache_key, None)
            return None
        _MOD_DETAILS_CACHE.move_to_end(cache_key)
        return copy.deepcopy(cached[1])


def _store_cached_mod_details(cache_key: tuple[int, str], value: dict) -> None:
    with _MOD_DETAILS_CACHE_LOCK:
        _MOD_DETAILS_CACHE[cache_key] = (time.time(), dict(value))
        _MOD_DETAILS_CACHE.move_to_end(cache_key)
        while len(_MOD_DETAILS_CACHE) > _MOD_DETAILS_CACHE_MAX_ENTRIES:
            _MOD_DETAILS_CACHE.popitem(last=False)


class LoadDescriptionFromUrlThread(QThread):
    description_loaded = pyqtSignal(str)
    error_occurred = pyqtSignal(str, int)

    def __init__(self, url, parent=None) -> None:
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            from utils.network_utils import get_session

            resp = get_session().get(self.url, timeout=10)
            if resp.ok:
                self.description_loaded.emit(resp.text)
            else:
                self.error_occurred.emit("http_error", resp.status_code)
        except Exception as e:
            self.error_occurred.emit(str(e), 0)


class LoadModDetailsThread(QThread):
    details_loaded = pyqtSignal(dict)

    def __init__(self, mod_data, parent=None) -> None:
        super().__init__(parent)
        self.mod_data = mod_data

    def _get_mod_id(self):
        from utils.mod.utils import parse_gamebanana_mod_id

        gb_id = parse_gamebanana_mod_id(get_mod_id(self.mod_data) or "")[1]
        if not gb_id:
            return None
        try:
            return int(gb_id)
        except ValueError:
            return None

    def _is_wip(self):
        from utils.mod.utils import parse_gamebanana_mod_id

        gb_type = parse_gamebanana_mod_id(get_mod_id(self.mod_data) or "")[0]
        return gb_type == "wip"

    def _coerce_text(self, text_field):
        if isinstance(text_field, list):
            text_field = text_field[0] if text_field else None
        return (
            text_field
            if isinstance(text_field, str)
            else (str(text_field) if text_field else None)
        )

    def _extract_screenshots(self, api, screenshots_field):
        is_wip = self._is_wip()
        screenshots_data = screenshots_field
        if (
            isinstance(screenshots_data, list)
            and len(screenshots_data) == 1
            and isinstance(screenshots_data[0], list)
        ):
            screenshots_data = screenshots_data[0]
        if isinstance(screenshots_data, list) and all(
            isinstance(item, str) for item in screenshots_data
        ):
            return [
                item
                for item in screenshots_data
                if item.startswith(("http://", "https://"))
            ]
        if isinstance(screenshots_data, str):
            return api.extract_screenshots_from_api(screenshots_data, is_wip=is_wip)
        if isinstance(screenshots_data, dict):
            try:
                screenshots_data = json.dumps(screenshots_data)
            except (TypeError, ValueError):
                return []
            return api.extract_screenshots_from_api(screenshots_data, is_wip=is_wip)
        if not isinstance(screenshots_data, list):
            return []
        base_url = (
            "https://images.gamebanana.com/img/ss/wips"
            if is_wip
            else "https://images.gamebanana.com/img/ss/mods"
        )
        screenshots = []
        for screenshot_obj in screenshots_data:
            if self.isInterruptionRequested():
                break
            if isinstance(screenshot_obj, dict):
                file_name = (
                    screenshot_obj.get("_sFile800")
                    or screenshot_obj.get("_sFile530")
                    or screenshot_obj.get("_sFile220")
                    or screenshot_obj.get("_sFile")
                    or screenshot_obj.get("_sFile100")
                )
                if file_name:
                    screenshots.append(f"{base_url}/{file_name}")
        return screenshots

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            mod_id = self._get_mod_id()
            if mod_id is None:
                return
            if self.isInterruptionRequested():
                return
            cache_key = (mod_id, "Wip" if self._is_wip() else "Mod")
            cached = _get_cached_mod_details(cache_key)
            if cached is not None:
                if self.isInterruptionRequested():
                    return
                self.details_loaded.emit(cached)
                return
            api = GameBananaAPI()
            itemtype = "Wip" if self._is_wip() else "Mod"
            details = api.get_mod_full_details_for_display(mod_id, itemtype=itemtype)
            if details and (not self.isInterruptionRequested()):
                full_description = self._coerce_text(details.get("text"))
                description = self._coerce_text(details.get("description"))
                downloads_value = _safe_int(
                    details.get("_nDownloadCount")
                    if isinstance(details, dict)
                    else None
                )
                screenshots = self._extract_screenshots(api, details.get("screenshots"))
                result = {
                    "screenshots": screenshots,
                    "downloads": downloads_value if downloads_value is not None else 0,
                }
                if full_description:
                    result["text"] = full_description
                if description:
                    result["description"] = description.strip()
                _store_cached_mod_details(cache_key, result)
                if not self.isInterruptionRequested():
                    self.details_loaded.emit(result)
        except Exception as e:
            if not self.isInterruptionRequested():
                logger.error(f"Error loading mod details: {e}", exc_info=True)


class ScreenshotViewerDialog(QDialog):
    class _ScreenshotContextMenu(QMenu):
        def mousePressEvent(self, a0):
            event = cast(Any, a0)
            if event.button() == Qt.MouseButton.RightButton:
                self.close()
                return
            super().mousePressEvent(event)

        def mouseReleaseEvent(self, a0):  # noqa: N802
            event = cast(Any, a0)
            if event.button() == Qt.MouseButton.RightButton:
                self.close()
                return
            super().mouseReleaseEvent(event)

        def contextMenuEvent(self, a0):  # noqa: N802
            event = cast(Any, a0)
            event.ignore()

    def __init__(self, urls, index=0, parent=None) -> None:
        super().__init__(parent)
        self._urls = urls
        self._index = index
        self._loader = cast(QThreadPool, QThreadPool.globalInstance())
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prev = QPushButton("←")
        self._next = QPushButton("→")
        self._label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._label.customContextMenuRequested.connect(self._show_context_menu)
        self._prev.clicked.connect(lambda: self._shift(-1))
        self._next.clicked.connect(lambda: self._shift(1))
        nav = QHBoxLayout()
        nav.addWidget(self._prev)
        nav.addWidget(self._next)
        layout = QVBoxLayout(self)
        self._label.setMinimumSize(960, 540)
        layout.addWidget(self._label)
        layout.addLayout(nav)
        self._load()

    def _load(self):
        if not self._urls:
            self._label.setText(tr("ui.no_screenshots"))
            return
        signals = WorkerSignals()
        signals.result.connect(self._set_image)
        self._loader.start(ImageLoaderRunnable(self._urls[self._index], signals))

    def relocalize_ui(self) -> None:
        if not self._urls:
            self._label.setText(tr("ui.no_screenshots"))

    def _set_image(self, qimg):
        pm = QPixmap.fromImage(qimg)
        self._label.setPixmap(
            pm.scaled(
                self._label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _show_context_menu(self, pos):
        if not self._urls:
            return
        menu = self._ScreenshotContextMenu()
        self._context_menu = menu
        fusion_style = QStyleFactory.create("Fusion")
        if fusion_style is not None:
            menu.setStyle(fusion_style)
        menu.setObjectName("screenshotContextMenu")
        url = self._urls[self._index]
        menu.addAction(tr("ui.open_image_in_browser"), lambda: open_url_native(url))
        menu.addAction(
            tr("ui.copy_image"),
            lambda: cast(Any, QGuiApplication.clipboard()).setPixmap(
                self._label.pixmap() or QPixmap()
            ),
        )
        menu.addAction(
            tr("ui.copy_image_url"),
            lambda: cast(Any, QGuiApplication.clipboard()).setText(url),
        )
        parent_colors = getattr(self.parent(), "_colors", None) or {}
        elements_bg = parent_colors.get("elements", "#2b2b2b")
        main_text = parent_colors.get("main_text", "#f0f0f0")
        border = parent_colors.get("border", "#19c37d")
        hover = parent_colors.get("hover", "#3d3d3d")
        menu.setStyleSheet(
            f"""
            QMenu {{
                background-color: {elements_bg};
                color: {main_text};
                border: 2px solid {border};
                padding: 8px;
            }}
            QMenu::item {{
                padding: 10px 24px;
                margin: 3px 3px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {hover};
            }}
            QMenu::separator {{
                height: 1px;
                background: {border};
                margin: 4px 8px;
            }}
            """
        )
        menu.aboutToHide.connect(self._clear_context_menu)
        try:
            menu.exec(self._label.mapToGlobal(pos))
        finally:
            self._clear_context_menu()

    def _clear_context_menu(self):
        self._context_menu = None

    def _shift(self, step):
        if not self._urls:
            return
        self._index = (self._index + step) % len(self._urls)
        self._load()


class ModDetailsOverlay(QWidget):
    """Overlay widget for displaying mod details with inline screenshot carousel."""

    HEADER_HEIGHT = 80
    FOOTER_HEIGHT = 100
    IMG_W, IMG_H = 440, 221
    LEFT_COLUMN_WIDTH = 450
    EXTERNAL_BUTTON_WIDTH = 400
    NAV_BUTTON_SIZE = (35, 25)
    LOADING_TEXT = "Loading..."
    NO_SCREENSHOTS_TEXT_KEY = "ui.no_screenshots"
    SCREENSHOT_LIMIT = 10

    def __init__(self, parent=None, mod_data=None, source_card=None) -> None:
        super().__init__(parent)
        self.mod_data: Any = mod_data
        self.source_card: Any = source_card
        self.dialog_closed = False
        self.load_thread = None
        self._ss_urls = []
        self._ss_images = []
        self._ss_loading = []
        self._ss_load_signals = []
        self._ss_index = 0
        self._description_html = ""
        self._last_description_width = 0
        self._thread_pool = cast(QThreadPool, QThreadPool.globalInstance())
        self._original_resize_event = None
        self._last_geometry = None
        self._cleanup_started = False
        self._prev_btn = QPushButton()
        self._next_btn = QPushButton()
        self._fade_anim: Any = None
        self.hide()
        self._setup_ui()
        self.main_window: Any = self._get_main_window()
        if self.main_window and hasattr(self.main_window, "resizeEvent"):
            self._original_resize_event = self.main_window.resizeEvent
            cast(Any, self.main_window).resizeEvent = self._on_main_window_resize

    def _get_main_window(self):
        window = self.parent()
        while window and window.parent():
            window = window.parent()
        return window

    def _calculate_content_geometry(self, main_rect):
        return (
            0,
            self.HEADER_HEIGHT,
            main_rect.width(),
            main_rect.height() - self.HEADER_HEIGHT - self.FOOTER_HEIGHT,
        )

    def _setup_theme(self):
        self._app_state = getattr(self.parent(), "app_state", None)
        local_cfg = (
            getattr(self._app_state, "local_config", None) if self._app_state else None
        )
        self._colors = get_theme_colors(local_cfg)
        self._colors["btn_hover"] = self._colors["hover"]
        self._colors["btn_select"] = self._colors["select"]
        self._border_radius = get_border_radius(local_cfg)

    @staticmethod
    def _layout(layout_cls, parent=None, margins=None, spacing=None) -> Any:
        layout = layout_cls(parent) if parent is not None else layout_cls()
        if margins is not None:
            layout.setContentsMargins(*margins)
        if spacing is not None:
            layout.setSpacing(spacing)
        return layout

    @staticmethod
    def _is_alive(obj) -> bool:
        try:
            return not _sip.isdeleted(obj)
        except (RuntimeError, AttributeError):
            return False

    def _can_update(self) -> bool:
        return (not self.dialog_closed) and self._is_alive(self)

    def _can_update_screenshot(self) -> bool:
        return self._can_update() and self._is_alive(self._img_label)

    @staticmethod
    def _clear_mask_if_needed(target) -> None:
        if not getattr(target, "_rounded_mask_applied", False):
            return
        with contextlib.suppress(RuntimeError, AttributeError):
            target.clearMask()
        target._rounded_mask_applied = False
        target._rounded_mask_cache_key = None

    @staticmethod
    def _set_stylesheet_if_changed(target, stylesheet: str, attr_name: str) -> bool:
        if getattr(target, attr_name, None) == stylesheet:
            return False
        target.setStyleSheet(stylesheet)
        setattr(target, attr_name, stylesheet)
        return True

    @staticmethod
    def _set_contents_margins_if_changed(
        target, margins: tuple[int, int, int, int], attr_name: str
    ) -> bool:
        normalized = tuple(int(value) for value in margins)
        if getattr(target, attr_name, None) == normalized:
            return False
        target.setContentsMargins(*normalized)
        setattr(target, attr_name, normalized)
        return True

    @staticmethod
    def _set_document_margin_if_changed(target, margin: int, attr_name: str) -> bool:
        normalized = int(margin)
        if getattr(target, attr_name, None) == normalized:
            return False
        target.setDocumentMargin(normalized)
        setattr(target, attr_name, normalized)
        return True

    def _apply_overlay_geometry(self, force: bool = False) -> bool:
        if not self.main_window:
            return False
        geometry = tuple(
            int(value)
            for value in self._calculate_content_geometry(self.main_window.rect())
        )
        if (not force) and self._last_geometry == geometry:
            return False
        self._last_geometry = geometry
        self.setGeometry(*geometry)
        return True

    def _radius_for(self, widget, margin: int = 0) -> int:
        return get_widget_border_radius(widget, self._border_radius, margin=margin)

    def _button_style(
        self,
        obj_name: str,
        *,
        text_color: str | None = None,
        bg: str | None = None,
        hover: str | None = None,
        width: int | None = 110,
        height: int | None = 35,
        font_size: int = 15,
        padding: str = "1px",
    ) -> str:
        return build_button_style(
            obj_name,
            bg or self._colors["elements"],
            hover or self._colors["hover"],
            text_color or self._colors["main_text"],
            self._colors["border"],
            width,
            height,
            font_size,
            border_radius=self._border_radius,
            padding=padding,
        )

    def _scrollbar_qss(self, corner_inset: int) -> str:
        return build_scrollbar_qss(
            self._colors["main_text"],
            self._border_radius,
            vertical_margin=(corner_inset, 4, corner_inset, 2),
            horizontal_margin=(2, corner_inset, 4, corner_inset),
            include_corner=True,
        )

    def _install_scroll_clip_handlers(self, target, attr_prefix: str):
        def _apply():
            apply_scroll_area_chrome(
                target,
                max(0, self._radius_for(target) - 2),
                scrollbar_radius=self._border_radius,
            )
            self._clear_mask_if_needed(target)

        install_scroll_area_update_handlers(target, _apply, f"{attr_prefix}_clip")

    def _install_scroller_style(
        self,
        target,
        *,
        selector: str,
        attr_name: str,
        clip_prefix: str,
        content_target=None,
        content_padding_min: int = 24,
        content_padding_factor: int = 6,
        text_color: str | None = None,
        font_size: int | None = None,
        document_margin: bool = False,
    ):
        def _apply():
            radius = self._radius_for(target)
            content_padding = max(
                content_padding_min, (radius * content_padding_factor + 9) // 10
            )
            viewport_inset = max(2, min(10, radius // 5))
            corner_inset = max(6, min(18, radius // 2))
            scrollbar_qss = self._scrollbar_qss(corner_inset)
            rules = [
                f"{selector} {{",
                f"  background-color: {self._colors['background']};",
                *([f"  color: {text_color};"] if text_color else []),
                f"  border: 2px solid {self._colors['border']};",
                f"  border-radius: {radius}px;",
                *([f"  font-size: {font_size}px;"] if font_size is not None else []),
                *(["  padding: 0px;"] if document_margin else []),
                "}",
                scrollbar_qss,
            ]
            stylesheet = "\n".join(rules)
            self._set_stylesheet_if_changed(
                target, stylesheet, f"{attr_name}_stylesheet_cache"
            )
            scrollbar_qss_changed = (
                getattr(target, f"{attr_name}_scrollbar_qss_cache", None)
                != scrollbar_qss
            )
            if scrollbar_qss_changed:
                setattr(target, f"{attr_name}_scrollbar_qss_cache", scrollbar_qss)
            scrollbar_extent = apply_scroll_area_chrome(
                target, qss=scrollbar_qss if scrollbar_qss_changed else None
            )
            try:
                viewport_margins = (
                    viewport_inset,
                    viewport_inset,
                    max(viewport_inset, scrollbar_extent + 2),
                    viewport_inset,
                )
                if (
                    getattr(target, f"{attr_name}_viewport_margins_cache", None)
                    != viewport_margins
                ):
                    target.setViewportMargins(*viewport_margins)
                    setattr(
                        target, f"{attr_name}_viewport_margins_cache", viewport_margins
                    )
            except Exception as e:
                logger.debug(
                    f"Failed to update viewport margins for {attr_name}: {e}",
                    exc_info=True,
                )
            try:
                if content_target is not None:
                    self._set_contents_margins_if_changed(
                        content_target,
                        (
                            content_padding,
                            content_padding,
                            content_padding,
                            content_padding,
                        ),
                        f"{attr_name}_content_margins_cache",
                    )
                elif document_margin:
                    self._set_document_margin_if_changed(
                        target.document(),
                        content_padding,
                        f"{attr_name}_document_margin_cache",
                    )
            except Exception as e:
                logger.debug(
                    f"Failed to update content padding for {attr_name}: {e}",
                    exc_info=True,
                )
            if viewport := target.viewport():
                self._set_stylesheet_if_changed(
                    viewport,
                    f"background-color: {self._colors['background']}; border: none;",
                    f"{attr_name}_viewport_stylesheet_cache",
                )

        install_scroll_area_update_handlers(
            target, _apply, attr_name.removeprefix("_").removesuffix("_filter")
        )
        self._install_scroll_clip_handlers(target, clip_prefix)

    def _html_label(
        self, html: str, *, align=Qt.AlignmentFlag.AlignCenter, wrap: bool = True
    ):
        label = QLabel(html)
        label.setWordWrap(wrap)
        label.setAlignment(align)
        return label

    def _create_button(
        self,
        text: str,
        *,
        obj_name: str,
        style: str,
        clicked=None,
        fixed_width: int | None = None,
        fixed_size: tuple[int, int] | None = None,
    ):
        button = QPushButton(text)
        button.setObjectName(obj_name)
        if clicked:
            button.clicked.connect(clicked)
        if fixed_size is not None:
            button.setFixedSize(*fixed_size)
        elif fixed_width is not None:
            button.setFixedWidth(fixed_width)
        button.setStyleSheet(style)
        return button

    def _install_image_container_style(self, container):
        def _apply(target=container, image_label=self._img_label):
            radius = self._radius_for(target)
            self._set_stylesheet_if_changed(
                target,
                f"background-color:transparent; border:2px solid {self._colors['border']}; border-radius: {radius}px;",
                "_overlay_image_container_stylesheet_cache",
            )
            self._set_stylesheet_if_changed(
                image_label,
                f"border: none; background-color: transparent; border-radius: {radius}px;",
                "_overlay_image_label_stylesheet_cache",
            )

        install_widget_update_handler(
            container, _apply, attr_name="_overlay_image_style_filter"
        )

    def _meta_row_html(self, key: str, value: str) -> str:
        title = html.escape(str(tr(key)))
        text = html.escape(str(value))
        return f'<span style="color:{self._colors["main_text"]};font-weight:bold;font-size:13px;">{title}</span> <span style="color:{self._colors["secondary_text"]};font-size:13px;">{text}</span>'

    def _translated_tags(self) -> str:
        tags = getattr(self.mod_data, "tags", None)
        if not tags:
            return ""
        tag_map = {
            "textedit": tr("tags.textedit"),
            "customization": tr("tags.customization"),
            "gameplay": tr("tags.gameplay"),
            "other": tr("tags.other"),
        }
        return ", ".join(
            tag_map.get(tag) or str(tag)
            for tag in (tags if isinstance(tags, list) else [tags])
            if tag
        )

    def _build_carousel_layout(self):
        carousel = self._layout(QVBoxLayout, spacing=8)
        img_container = QWidget()
        img_container.setFixedSize(self.IMG_W, self.IMG_H)
        self._img_label = QLabel(img_container)
        self._img_label.setFixedSize(self.IMG_W, self.IMG_H)
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setCursor(Qt.CursorShape.PointingHandCursor)
        cast(Any, self._img_label).mousePressEvent = self._on_screenshot_click
        self._install_image_container_style(img_container)
        carousel.addWidget(img_container, 0, Qt.AlignmentFlag.AlignHCenter)
        nav = self._layout(QHBoxLayout, margins=(0, 0, 0, 0), spacing=4)
        nav.addStretch()
        for attr, text, slot in (
            ("_prev_btn", "←", self._ss_prev),
            ("_next_btn", "→", self._ss_next),
        ):
            button = self._create_button(
                text,
                obj_name="overlayNavButton",
                style=self._button_style(
                    "overlayNavButton",
                    width=self.NAV_BUTTON_SIZE[0],
                    height=self.NAV_BUTTON_SIZE[1],
                    font_size=16,
                    padding="0px",
                ),
                clicked=slot,
                fixed_size=self.NAV_BUTTON_SIZE,
            )
            setattr(self, attr, button)
            nav.addWidget(button)
        nav.addStretch()
        carousel.addLayout(nav)
        self._dots_layout = self._layout(QHBoxLayout, spacing=4)
        self._dot_labels = []
        dots_wrap = self._layout(QHBoxLayout)
        dots_wrap.addStretch()
        dots_wrap.addLayout(self._dots_layout)
        dots_wrap.addStretch()
        carousel.addLayout(dots_wrap)
        return carousel

    def _build_metadata_layout(self):
        meta = self._layout(QVBoxLayout, spacing=4)
        self._meta_labels = {}
        version = self.mod_data.version
        downloads_value = getattr(self.mod_data, "downloads", None)
        for key, value in (
            (
                "ui.mod_version_label",
                (version.split("|")[0] if version and "|" in version else version)
                or "N/A",
            ),
            ("ui.author_label", self.mod_data.author),
            ("ui.updated_label", getattr(self.mod_data, "last_updated", None) or "N/A"),
            ("ui.created_label", getattr(self.mod_data, "created_date", None)),
            (
                "ui.downloads_label",
                "0" if downloads_value is None else str(downloads_value),
            ),
            (
                "ui.category_label",
                getattr(self.mod_data, "gamebanana_category", None)
                or getattr(self.mod_data, "category", None),
            ),
        ):
            if value:
                label = QLabel(self._meta_row_html(key, value))
                label.setProperty("metaValue", str(value))
                label.setWordWrap(key == "ui.tags_label")
                label.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                    | Qt.TextInteractionFlag.TextSelectableByKeyboard
                )
                self._meta_labels[key] = label
                meta.addWidget(label)
        if tags := self._translated_tags():
            label = QLabel(self._meta_row_html("ui.tags_label", tags))
            label.setWordWrap(True)
            label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            self._meta_labels["ui.tags_label"] = label
            label.setProperty("translatedTags", True)
            meta.addWidget(label)
        return meta

    def _build_left_column(self):
        left = self._layout(QVBoxLayout, margins=(0, 0, 0, 0), spacing=15)
        if homepage := getattr(self.mod_data, "homepage", None):
            self.homepage_button = self._create_button(
                tr("ui.view_homepage"),
                obj_name="cardButtonExternal",
                style=self._button_style(
                    "cardButtonExternal",
                    text_color="#FFD700",
                    width=self.EXTERNAL_BUTTON_WIDTH,
                    font_size=15,
                ),
                clicked=lambda: open_url_native(homepage),
                fixed_width=self.EXTERNAL_BUTTON_WIDTH,
            )
            left.addWidget(
                self.homepage_button,
                0,
                Qt.AlignmentFlag.AlignCenter,
            )
        self.title_label = QLabel(
            f'<h2 style="color:{self._colors["main_text"]};margin:8px 0;font-size:18px;">{html.escape(self.mod_data.name or "")}</h2>'
        )
        self.title_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.title_label)
        self.description_label = QLabel("")
        self.description_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.description_label.setWordWrap(True)
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.description_label)
        self._update_description_label(getattr(self.mod_data, "description", None))
        left.addLayout(self._build_carousel_layout())
        left.addLayout(self._build_metadata_layout())
        left.addStretch()
        container = QWidget()
        container.setMinimumWidth(self.LEFT_COLUMN_WIDTH)
        container.setMaximumWidth(self.LEFT_COLUMN_WIDTH)
        container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        container.setLayout(left)
        return container

    def _configure_action_button(self):
        if self.source_card and hasattr(self.source_card, "action_button"):
            self._sync_button_from_card()
            self.action_button.clicked.connect(
                lambda: self.source_card.action_button.click()
            )
            try:
                self._sync_timer = QTimer()
                self._sync_timer.timeout.connect(self._sync_button_from_card)
                self._sync_timer.start(250)
            except Exception as e:
                logger.debug(f"QTimer setup failed for _sync_timer: {e}", exc_info=True)
            return
        self.action_button.setText(tr("buttons.download"))
        self.action_button.setObjectName("cardButtonDownload")
        self._set_action_button_style(self._colors["border"])
        if (parent_app := self.parent()) and hasattr(parent_app, "install_mod"):
            self.action_button.clicked.connect(
                lambda: cast(Any, parent_app).install_mod(self.mod_data)
            )

    def _build_action_buttons(self):
        buttons = self._layout(QHBoxLayout)
        buttons.addStretch()
        self.action_button = QPushButton()
        self._configure_action_button()
        buttons.addWidget(self.action_button)
        self.close_button = self._create_button(
            tr("buttons.close"),
            obj_name="cardButtonClose",
            style=self._button_style("cardButtonClose"),
            clicked=self.close_overlay,
        )
        buttons.addWidget(self.close_button)
        return buttons

    def _build_right_column(self):
        right = self._layout(QVBoxLayout, spacing=15)
        self.full_description_label = self._html_label(
            f"<b style='color:{self._colors['main_text']};'>{tr('ui.full_description_label')}</b>"
        )
        right.addWidget(self.full_description_label)
        self.desc_text = QTextBrowser()
        self.desc_text.setMinimumHeight(400)
        self.desc_text.setOpenExternalLinks(True)
        self.desc_text.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        self.desc_text.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.desc_text.setFrameShape(QFrame.Shape.NoFrame)
        self._install_scroller_style(
            self.desc_text,
            selector="QTextBrowser",
            attr_name="_overlay_description_style_filter",
            clip_prefix="overlay_description",
            content_padding_min=14,
            content_padding_factor=4,
            text_color=self._colors["main_text"],
            font_size=16,
            document_margin=True,
        )
        self._desc_default_color = self._colors["main_text"]
        right.addWidget(self.desc_text)
        right.addLayout(self._build_action_buttons())
        container = QWidget()
        container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        container.setLayout(right)
        return container

    def relocalize_ui(self) -> None:
        """Refresh G3M-owned labels while preserving remote mod content."""
        if hasattr(self, "homepage_button"):
            self.homepage_button.setText(tr("ui.view_homepage"))
        self.close_button.setText(tr("buttons.close"))
        self.full_description_label.setText(
            f"<b style='color:{self._colors['main_text']};'>{tr('ui.full_description_label')}</b>"
        )
        for key, label in self._meta_labels.items():
            value = (
                self._translated_tags()
                if label.property("translatedTags")
                else label.property("metaValue")
            )
            label.setText(self._meta_row_html(key, str(value or "")))
        if not self.source_card:
            self.action_button.setText(tr("buttons.download"))

    def _show_loading_description(self):
        self._set_description_message(tr("status.loading_description"))

    def _set_description_message(self, text: str):
        self._description_html = ""
        self.desc_text.setPlainText(text)

    def _start_thread(self, attr_name: str, thread, signal_pairs=()):
        setattr(self, attr_name, thread)
        for signal_name, handler in signal_pairs:
            getattr(thread, signal_name).connect(handler)
        thread.start()

    def _stop_timer(self, attr_name: str):
        if timer := getattr(self, attr_name, None):
            try:
                timer.stop()
                timer.deleteLater()
            except Exception as e:
                logger.debug(
                    f"cleanup_thread: failed to stop/delete {attr_name}: {e}",
                    exc_info=True,
                )
            setattr(self, attr_name, None)

    def _sync_action_button_style(self, src_btn, border: str):
        style_args = {
            "cardButtonUninstall": ("cardButtonUninstall", "#F44336", "#d32f2f"),
        }.get(src_btn.objectName())
        if style_args:
            self._set_action_button_style(border, *style_args)
            return
        self._set_action_button_style(border)

    def _update_description_label(self, description):
        if not hasattr(self, "description_label"):
            return
        clean_description = (description or "").strip()
        if clean_description:
            self.description_label.setText(
                f'<p style="color:{self._colors["secondary_text"]};margin:0 0 15px 0;font-size:14px;font-style:italic;">{html.escape(clean_description)}</p>'
            )
            if self.description_label.parent() is not None:
                self.description_label.setVisible(True)
        else:
            self.description_label.clear()
            self.description_label.setVisible(False)

    def _update_meta_row(self, key: str, value: str, *, wrap: bool = False):
        if not value:
            return
        label = getattr(self, "_meta_labels", {}).get(key)
        if label is None:
            return
        label.setText(self._meta_row_html(key, value))
        label.setWordWrap(wrap)
        label.setVisible(True)

    def _setup_ui(self):
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._setup_theme()
        self.setStyleSheet(
            f"QWidget {{ background-color: {self._colors['background']}; }}"
        )
        root = self._layout(QVBoxLayout, self, margins=(0, 0, 0, 0), spacing=0)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = self._layout(
            QVBoxLayout, content, margins=(20, 20, 20, 20), spacing=15
        )
        self._install_scroller_style(
            scroll,
            selector="QScrollArea",
            attr_name="_overlay_scroll_style_filter",
            clip_prefix="overlay_scroll",
            content_target=content_layout,
        )
        columns = self._layout(QHBoxLayout, margins=(0, 0, 0, 0), spacing=5)
        columns.addWidget(self._build_left_column(), 0)
        columns.addWidget(self._build_right_column(), 1)
        cw = QWidget()
        cw.setLayout(columns)
        content_layout.addWidget(cw)
        scroll.setWidget(content)
        wrap = self._layout(
            QHBoxLayout,
            margins=(
                max(10, self._border_radius // 3),
                max(4, self._border_radius // 6),
                max(10, self._border_radius // 3),
                max(4, self._border_radius // 6),
            ),
        )
        wrap.addWidget(scroll)
        root.addLayout(wrap)

        self._update_ss_nav()
        self._load_description()

    def _set_action_button_style(
        self, border, obj_name="cardButtonDownload", bg="#4CAF50", hover="#5cb85c"
    ):
        """Set action button stylesheet."""
        self.action_button.setStyleSheet(
            build_button_style(
                obj_name,
                bg,
                hover,
                "#e8e9eb",
                border,
                border_radius=self._border_radius,
            )
        )

    def _sync_button_from_card(self):
        """Synchronize action button state with the source mod card."""
        if not (src_btn := getattr(self.source_card, "action_button", None)):
            return
        self.action_button.setText(src_btn.text())
        self.action_button.setObjectName(src_btn.objectName())
        self.action_button.setToolTip(src_btn.toolTip())
        self.action_button.setEnabled(src_btn.isEnabled())
        self._sync_action_button_style(src_btn, self._colors.get("border", "#039d5b"))

    def update_screenshots(self, urls):
        urls = [
            u
            for u in urls
            if isinstance(u, str) and u.startswith(("http://", "https://"))
        ][: self.SCREENSHOT_LIMIT]
        self._ss_urls = urls
        self._ss_images = [None] * len(urls)
        self._ss_loading = [False] * len(urls)
        self._ss_index = 0
        self._rebuild_dots()
        if urls:
            self._ss_show_current()
            self._ss_preload_neighbors()
        self._update_ss_nav()

    def _ss_prev(self):
        self._ss_shift(-1)

    def _ss_next(self):
        self._ss_shift(1)

    def _ss_shift(self, step):
        if not self._ss_urls:
            return
        self._ss_index = (self._ss_index + step) % len(self._ss_urls)
        self._ss_show_current()
        self._ss_preload_neighbors()
        self._ss_unload_distant()

    def _ss_show_current(self):
        if not self._ss_urls:
            self._set_screenshot_text(tr(self.NO_SCREENSHOTS_TEXT_KEY))
            self._update_ss_nav()
            return

        if current_image := self._ss_images[self._ss_index]:
            self._ss_fade_to(current_image)
        else:
            self._ss_load_image(self._ss_index) if not self._ss_loading[
                self._ss_index
            ] else self._set_screenshot_text(self.LOADING_TEXT)

        self._rebuild_dots()
        self._update_ss_nav()

    def _set_screenshot_text(self, text: str):
        if not self._can_update_screenshot():
            return
        self._img_label.clear()
        self._img_label.setText(text)

    def _ss_load_image(self, idx):
        self._set_screenshot_text(self.LOADING_TEXT)
        self._queue_screenshot_load(idx, self._ss_on_loaded)

    def _queue_screenshot_load(self, idx, on_loaded):
        if not (0 <= idx < len(self._ss_urls)) or self._ss_loading[idx]:
            return
        self._ss_loading[idx] = True
        signals = WorkerSignals()
        self._ss_load_signals.append(signals)
        signals.result.connect(
            lambda qimg, i=idx, s=signals: self._ss_on_load_result(
                s, i, on_loaded, qimg
            )
        )
        signals.error.connect(
            lambda url, msg, i=idx, s=signals: self._ss_on_load_error(s, i, msg)
        )
        self._thread_pool.start(ImageLoaderRunnable(self._ss_urls[idx], signals))

    def _forget_screenshot_load_signal(self, signals):
        with contextlib.suppress(ValueError):
            self._ss_load_signals.remove(signals)

    def _ss_on_load_result(self, signals, idx, on_loaded, qimg):
        self._forget_screenshot_load_signal(signals)
        on_loaded(idx, qimg)

    def _ss_on_load_error(self, signals, idx, msg):
        self._forget_screenshot_load_signal(signals)
        self._ss_on_error(idx, msg)

    def _ss_fade_to(self, qimg):
        if not self._can_update_screenshot():
            return
        self._ss_set_pixmap(qimg)
        effect = UIAnimator.get_opacity_effect(self._img_label)
        effect.setOpacity(0.0)
        UIAnimator.fade_in(self._img_label, duration=250, app_state=self._app_state)

    def _ss_set_pixmap(self, qimg):
        if not self._is_alive(self._img_label):
            return
        lw, lh = self._img_label.width(), self._img_label.height()
        pm = QPixmap.fromImage(qimg)
        scaled = pm.scaled(
            lw - 4,
            lh - 4,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        canvas = QPixmap(lw, lh)
        canvas.fill(QColor("transparent"))
        p = QPainter(canvas)
        p.drawPixmap((lw - scaled.width()) // 2, (lh - scaled.height()) // 2, scaled)
        p.end()
        self._img_label.setPixmap(
            round_pixmap(canvas, self._border_radius)
            if self._border_radius > 0
            else canvas
        )

    def _ss_store_image(self, idx, qimg):
        if idx < len(self._ss_images):
            self._ss_images[idx] = qimg
        if idx < len(self._ss_loading):
            self._ss_loading[idx] = False

    def _ss_on_loaded(self, idx, qimg):
        self._ss_store_image(idx, qimg)
        if not self._can_update_screenshot():
            return
        if idx == self._ss_index:
            self._ss_fade_to(qimg)
            self._ss_unload_distant()

    def _ss_on_error(self, idx, msg):
        if idx < len(self._ss_loading):
            self._ss_loading[idx] = False
        if not self._can_update_screenshot():
            return
        if idx == self._ss_index:
            self._set_screenshot_text(tr("errors.file_not_available"))

    def _ss_preload_neighbors(self):
        for offset in (-1, 1):
            i = self._ss_index + offset
            if 0 <= i < len(self._ss_urls) and self._ss_images[i] is None:
                self._queue_screenshot_load(i, self._ss_on_preloaded)

    def _ss_on_preloaded(self, idx, qimg):
        self._ss_store_image(idx, qimg)
        if not self._can_update_screenshot():
            return
        if idx == self._ss_index:
            self._ss_fade_to(qimg)

    def _ss_unload_distant(self):
        n = len(self._ss_urls)
        for i in range(len(self._ss_images)):
            d = min(
                abs(i - self._ss_index),
                abs(i - self._ss_index + n),
                abs(i - self._ss_index - n),
            )
            if d > 1 and self._ss_images[i] is not None:
                self._ss_images[i] = None

    def _update_ss_nav(self):
        show = len(self._ss_urls) > 1
        self._prev_btn.setVisible(show)
        self._next_btn.setVisible(show)
        for lbl in self._dot_labels:
            lbl.setVisible(show)

    def _rebuild_dots(self):
        while len(self._dot_labels) > len(self._ss_urls):
            label = self._dot_labels.pop()
            self._dots_layout.removeWidget(label)
            label.deleteLater()
        tc = self.palette().color(self.foregroundRole()).name()
        dot_style = f"color:{tc};font-size:14px;background-color:transparent;border:none;padding:2px;"
        while len(self._dot_labels) < len(self._ss_urls):
            lbl = QLabel()
            self._dot_labels.append(lbl)
            self._dots_layout.addWidget(lbl)
        for i, lbl in enumerate(self._dot_labels):
            lbl.setText("●" if i == self._ss_index else "○")
            if lbl.styleSheet() != dot_style:
                lbl.setStyleSheet(dot_style)

    def show_overlay(self):
        """Show the overlay with fade-in animation."""
        self._apply_overlay_geometry(force=True)
        effect = UIAnimator.get_opacity_effect(self)
        effect.setOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        UIAnimator.fade_in(self, duration=300, app_state=self._app_state)

    def close_overlay(self):
        """Close the overlay with fade-out animation."""
        self._cleanup_before_delete()

        def cleanup():
            self.hide()
            self.deleteLater()

        if self._fade_anim:
            with contextlib.suppress(TypeError, RuntimeError):
                self._fade_anim.finished.disconnect()

        fade = UIAnimator.fade_out(self, duration=300, app_state=self._app_state)
        if fade:
            fade.finished.connect(cleanup)
        else:
            cleanup()

    def keyPressEvent(self, a0):
        event = cast(Any, a0)
        with contextlib.suppress(RuntimeError, AttributeError):
            if event.key() == Qt.Key.Key_Escape:
                self.close_overlay()
                event.accept()
                return
        with contextlib.suppress(RuntimeError, AttributeError):
            super().keyPressEvent(event)

    def mousePressEvent(self, a0):
        event = cast(Any, a0)
        with contextlib.suppress(RuntimeError, AttributeError):
            if not self.childAt(event.pos()):
                self.close_overlay()
        with contextlib.suppress(RuntimeError, AttributeError):
            super().mousePressEvent(event)

    def _on_main_window_resize(self, event):
        try:
            if self._is_alive(self) and self.isVisible():
                self._apply_overlay_geometry()
        except (RuntimeError, AttributeError) as e:
            logger.debug(f"Failed to apply overlay geometry: {e}")
        if self._original_resize_event:
            with contextlib.suppress(RuntimeError, AttributeError):
                self._original_resize_event(event)

    def resizeEvent(self, a0):
        event = cast(Any, a0)
        super().resizeEvent(event)
        self._last_geometry = (self.x(), self.y(), self.width(), self.height())
        self._update_ss_nav()

    def _load_description(self):
        existing_screenshots = getattr(self.mod_data, "screenshots_url", None) or []
        if existing_screenshots and not self._ss_urls:
            self.update_screenshots(existing_screenshots)
        if (
            hasattr(self.mod_data, "full_description")
            and self.mod_data.full_description
        ):
            self._set_description_html(self.mod_data.full_description)
        elif (
            self.mod_data.is_gamebanana_mod() and self.mod_data.get_gamebanana_mod_id()
        ):
            self._load_gamebanana_description()
        elif (
            hasattr(self.mod_data, "description_url") and self.mod_data.description_url
        ):
            self._load_description_from_url()
        else:
            self._set_description_message(tr("ui.no_description"))

    def _refresh_description_html(self, force=False):
        if not self._description_html:
            return
        try:
            viewport_width = (
                cast(Any, self.desc_text.viewport()).width()
                if self.desc_text.viewport()
                else self.desc_text.width()
            )
        except Exception:
            viewport_width = 0
        if (
            not force
            and viewport_width
            and abs(viewport_width - self._last_description_width) < 24
        ):
            return
        self._last_description_width = viewport_width
        try:
            from ui.common.rich_html import set_rich_html

            set_rich_html(
                self.desc_text,
                self._description_html,
                default_color=self._desc_default_color,
            )
        except Exception as e:
            logger.warning(f"Error setting description HTML: {e}")
            self.desc_text.setPlainText(self._description_html)

    def _set_description_html(self, content):
        """Set description HTML with error handling."""
        self._description_html = content if isinstance(content, str) else str(content)
        self._refresh_description_html(force=True)

    def _load_description_from_url(self):
        """Load description from URL."""
        self._show_loading_description()
        self._start_thread(
            "url_load_thread",
            LoadDescriptionFromUrlThread(self.mod_data.description_url, parent=None),
            (
                ("description_loaded", self._on_url_description_loaded),
                ("error_occurred", self._on_url_description_error),
            ),
        )

    def _on_url_description_loaded(self, html_content):
        """Handle successful URL description load."""
        try:
            if not self._can_update():
                return
            self._set_description_html(html_content)
        except Exception as e:
            logger.error(f"Error in _on_url_description_loaded: {e}", exc_info=True)

    def _on_url_description_error(self, error_msg, status_code):
        """Handle URL description load error."""
        try:
            if not self._can_update():
                return
            if error_msg == "http_error":
                self._set_description_message(
                    tr("errors.description_http_error_code", code=status_code)
                )
            else:
                self._set_description_message(
                    tr("errors.description_load_error_details", error=error_msg)
                )
        except Exception as e:
            logger.error(f"Error in _on_url_description_error: {e}", exc_info=True)

    def _load_gamebanana_description(self):
        """Load GameBanana mod description."""
        self._show_loading_description()
        self._start_thread(
            "load_thread",
            LoadModDetailsThread(self.mod_data, parent=None),
            (("details_loaded", self._on_details_loaded),),
        )

    def _on_details_loaded(self, details):
        try:
            if not self._can_update():
                return
            if details.get("text"):
                self.mod_data.full_description = details["text"]
                self._set_description_html(details["text"])
            elif getattr(self.mod_data, "description_url", None):
                self._load_description_from_url()
            else:
                self.mod_data.full_description = ""
                self._set_description_html("")
            if "description" in details:
                self.mod_data.description = details["description"]
                self._update_description_label(details["description"])
            if "downloads" in details:
                self.mod_data.downloads = details["downloads"]
                self._update_meta_row("ui.downloads_label", str(details["downloads"]))
            ss = details.get("screenshots", [])
            if (
                ss
                and isinstance(ss, list)
                and any(isinstance(u, str) and u.strip() for u in ss)
            ):
                self.mod_data.screenshots_url = ss
                if not self._ss_urls:
                    self.update_screenshots(ss)
        except Exception as e:
            logger.error(f"Error in _on_details_loaded: {e}", exc_info=True)

    def _on_screenshot_click(self, event):
        """Handle screenshot click to open in a larger viewer."""
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._ss_urls
            and 0 <= self._ss_index < len(self._ss_urls)
        ):
            ScreenshotViewerDialog(self._ss_urls, self._ss_index, self).exec()

    def _restore_main_window_resize(self):
        """Restores the original resizeEvent of the main window."""
        if self.main_window and self._original_resize_event:
            try:
                cast(Any, self.main_window).resizeEvent = self._original_resize_event
                self._original_resize_event = None
            except (RuntimeError, AttributeError) as e:
                logger.debug(f"Failed to restore main window resize event: {e}")

    @staticmethod
    def _stop_thread(thread) -> None:
        """Stop and clean up a QThread safely."""
        try:
            thread.blockSignals(True)
            if thread.isRunning():
                thread.requestInterruption()
                thread.quit()
                if not thread.wait(5000):
                    logger.debug(
                        f"{thread.__class__.__name__}: Thread did not stop within 5s; deferring cleanup"
                    )
            if thread.isFinished():
                thread.deleteLater()
            else:
                thread.finished.connect(
                    lambda: thread.deleteLater() if thread.isFinished() else None
                )
        except (RuntimeError, AttributeError) as e:
            logger.debug(f"{thread.__class__.__name__}: cleanup error: {e}")

    def _stop_thread_attr(self, attr_name: str):
        if thread := getattr(self, attr_name, None):
            setattr(self, attr_name, None)
            self._stop_thread(thread)

    def _disconnect_screenshot_loads(self):
        for signals in self._ss_load_signals:
            with contextlib.suppress(RuntimeError, TypeError):
                signals.blockSignals(True)
            with contextlib.suppress(RuntimeError, TypeError):
                signals.result.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                signals.error.disconnect()
        self._ss_load_signals.clear()
        self._ss_loading = [False] * len(self._ss_loading)

    def cleanup_thread(self):
        self._stop_timer("_sync_timer")
        self._disconnect_screenshot_loads()
        self._stop_thread_attr("load_thread")
        self._stop_thread_attr("url_load_thread")

    def _cleanup_before_delete(self):
        if self._cleanup_started:
            return
        self._cleanup_started = True
        self.dialog_closed = True
        self._restore_main_window_resize()
        self.cleanup_thread()

    @override
    def deleteLater(self):
        self._cleanup_before_delete()
        super().deleteLater()

    def closeEvent(self, a0):
        event = cast(Any, a0)
        self._cleanup_before_delete()
        super().closeEvent(event)


def show_mod_details_overlay(parent, mod_data, source_card=None):
    """Show mod details overlay."""
    main_window = parent
    while main_window and main_window.parent():
        main_window = main_window.parent()
    overlay = ModDetailsOverlay(main_window, mod_data, source_card=source_card)
    overlay._apply_overlay_geometry(force=True)
    overlay.show_overlay()
    return overlay
