"""Rich HTML preprocessor for QTextBrowser.

Transforms web HTML (with remote images, CSS classes, font tags, etc.) into
Qt-compatible rich text. Downloads images asynchronously and injects them as
document resources so they render inline (including animated GIFs).
"""

import contextlib
import logging
import re
from collections import OrderedDict

from PyQt6.QtCore import QObject, QRectF, QRunnable, Qt, QThreadPool, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QTextDocument
from PyQt6.QtWidgets import QTextBrowser, QTextEdit

from config.constants import (
    RICH_HTML_ATTR_RE,
    RICH_HTML_CLASS_RE,
    RICH_HTML_CSS_CLASS_MAP,
    RICH_HTML_FONT_COLOR_RE,
    RICH_HTML_IMAGE_CACHE_MAX_SIZE,
    RICH_HTML_IMG_RE,
)
from services.localization_service import tr
from utils.network_utils import get_session


def _parse_attrs(attr_str: str) -> dict:
    return dict(RICH_HTML_ATTR_RE.findall(attr_str))


def _positive_int(value) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _style_dimension(style: str, name: str) -> str:
    if not style:
        return ""
    match = re.search(rf"{name}\s*:\s*([0-9.]+%?)", style, re.IGNORECASE)
    return match.group(1) if match else ""


def _safe_inline_media_width(widget_width: int) -> int:
    try:
        width = int(widget_width or 0)
    except (TypeError, ValueError):
        width = 0
    return max(1, width - 10) if width > 10 else max(1, width)


def _placeholder_resource_width(target_width: int) -> int:
    try:
        width = int(target_width or 0)
    except (TypeError, ValueError):
        width = 0
    if width <= 0:
        return 280
    if width <= 140:
        return max(120, width - 8)
    return max(120, width - 20)


def _browser_available_width(browser: QTextBrowser) -> int:
    viewport = None
    try:
        viewport = browser.viewport()
    except AttributeError, RuntimeError, TypeError:
        viewport = None
    width_candidates = []
    if viewport is not None:
        with contextlib.suppress(AttributeError, RuntimeError, TypeError, ValueError):
            width_candidates.append(int(viewport.contentsRect().width()))
        with contextlib.suppress(AttributeError, RuntimeError, TypeError, ValueError):
            width_candidates.append(int(viewport.width()))
    with contextlib.suppress(AttributeError, RuntimeError, TypeError, ValueError):
        width_candidates.append(int(browser.contentsRect().width()))
    with contextlib.suppress(AttributeError, RuntimeError, TypeError, ValueError):
        width_candidates.append(int(browser.width()))
    available_width = next((width for width in width_candidates if width > 0), 600)
    try:
        document_margin = int(browser.document().documentMargin())
    except AttributeError, TypeError, ValueError:
        document_margin = 0
    return max(available_width - (document_margin * 2), 200)


def _image_requests(html: str, widget_width: int) -> list[dict]:
    requests = []
    safe_width = _safe_inline_media_width(widget_width)
    for match in RICH_HTML_IMG_RE.finditer(html):
        attrs = _parse_attrs(match.group(1))
        src = attrs.get("src", "").strip()
        if not src.startswith(("http://", "https://")):
            continue
        width = _positive_int(attrs.get("width")) or safe_width
        height = _positive_int(attrs.get("height"))
        requests.append(
            {"src": src, "width": max(1, min(safe_width, width)), "height": height}
        )
    return requests


def _create_loading_placeholder(width: int, height: int, text: str) -> QImage:
    placeholder_width = max(120, min(int(width) if width else 320, 960))
    placeholder_height = max(
        80, min(int(height) if height else max(120, placeholder_width // 3), 540)
    )
    screen = QGuiApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen else 2.0
    image = QImage(
        int(placeholder_width * dpr),
        int(placeholder_height * dpr),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.setDevicePixelRatio(dpr)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    left_inset = 5
    top_inset = 5
    right_inset = 20
    bottom_inset = 5
    content_rect = QRectF(
        left_inset,
        top_inset,
        placeholder_width - left_inset - right_inset,
        placeholder_height - top_inset - bottom_inset,
    )
    border_rect = content_rect.adjusted(0, 0, -1, -1)
    painter.fillRect(content_rect, QColor(34, 34, 34, 235))
    painter.setPen(QColor(3, 157, 91, 220))
    painter.drawRoundedRect(border_rect, 12, 12)
    painter.setPen(QColor(232, 233, 235))
    painter.drawText(
        content_rect.adjusted(12, 12, -12, -12),
        Qt.AlignmentFlag.AlignCenter
        | Qt.AlignmentFlag.AlignVCenter
        | Qt.TextFlag.TextWordWrap,
        text,
    )
    painter.end()
    return image


def _refresh_browser_document(browser: QTextBrowser, doc: QTextDocument):
    try:
        from PyQt6 import sip as _sip

        if _sip.isdeleted(browser):
            return
    except (RuntimeError, AttributeError):
        return
    try:
        cursor = browser.textCursor()
        browser.setDocument(doc)
        browser.setTextCursor(cursor)
    except (RuntimeError, AttributeError) as e:
        logging.debug(f"Failed to refresh browser document: {e}")


def _resolve_classes(html: str) -> str:
    """Replace class="ClassName" with equivalent inline style."""

    def _repl(m):
        tag, pre, classes, post = m.group(1), m.group(2), m.group(3), m.group(4)
        styles = []
        for cls in classes.split():
            css = RICH_HTML_CSS_CLASS_MAP.get(cls)
            if css:
                styles.append(css)
        if not styles:
            return (
                m.group(0)
                .replace(f'class="{classes}"', "")
                .replace(f"class='{classes}'", "")
            )
        existing = ""
        style_match = re.search(r'style=["\']([^"\']*)["\']', pre + post)
        if style_match:
            existing = style_match.group(1).rstrip(";") + ";"
            pre = re.sub(r'\s*style=["\'][^"\']*["\']', "", pre)
            post = re.sub(r'\s*style=["\'][^"\']*["\']', "", post)
        style_val = existing + "".join(styles)
        clean_pre = re.sub(r'\s*class=["\'][^"\']*["\']', "", pre)
        clean_post = re.sub(r'\s*class=["\'][^"\']*["\']', "", post)
        return f'<{tag}{clean_pre} style="{style_val}"{clean_post}>'

    return RICH_HTML_CLASS_RE.sub(_repl, html)


def _resolve_font_tags(html: str) -> str:
    """Convert <font color="X">...</font> to <span style="color:X;">...</span>."""

    def _repl(m):
        pre, color, post, inner = m.group(1), m.group(2), m.group(3), m.group(4)
        other_attrs = (pre.strip() + " " + post.strip()).strip()
        if other_attrs:
            return f'<span style="color:{color};" {other_attrs}>{inner}</span>'
        return f'<span style="color:{color};">{inner}</span>'

    return RICH_HTML_FONT_COLOR_RE.sub(_repl, html)


def _build_img_tag(attrs: dict, widget_width: int) -> str:
    """Build a Qt-compatible <img> tag from parsed attributes."""
    src = attrs.get("src", "")
    if not src:
        return ""
    safe_width = _safe_inline_media_width(widget_width)
    style_attr = attrs.get("style", "")
    width_attr = attrs.get("width", "") or _style_dimension(style_attr, "width")
    height_attr = attrs.get("height", "") or _style_dimension(style_attr, "height")
    w = h = 0
    if width_attr:
        if width_attr.endswith("%"):
            try:
                pct = float(width_attr.rstrip("%"))
                w = max(1, int(safe_width * pct / 100))
            except ValueError:
                logging.debug("Failed to parse percentage width, using default")
        else:
            with contextlib.suppress(ValueError):
                w = int(width_attr)
    if height_attr:
        if height_attr.endswith("%"):
            logging.debug("Percentage height not supported for images")
        else:
            with contextlib.suppress(ValueError):
                h = int(height_attr)
    if w and w > safe_width:
        if h:
            try:
                h = max(1, int(h * safe_width / w))
            except (TypeError, ValueError):
                h = 0
        w = safe_width
    size_attrs = ""
    if w:
        size_attrs += f' width="{w}"'
    if h:
        size_attrs += f' height="{h}"'
    return f'<img src="{src}"{size_attrs} />'


def preprocess_html(html: str, widget_width: int = 600) -> str:
    """Preprocess HTML for QTextBrowser: resolve classes, font tags, image sizes.

    Does NOT download images - call ``load_remote_images`` separately for that.
    Returns cleaned HTML string ready for setHtml().
    """
    html = _resolve_classes(html)
    html = _resolve_font_tags(html)

    def _img_repl(m):
        attrs = _parse_attrs(m.group(1))
        tag = _build_img_tag(attrs, widget_width)
        return tag if tag else m.group(0)

    html = RICH_HTML_IMG_RE.sub(_img_repl, html)
    return html


class _ImageSignals(QObject):
    """Bridge to deliver image data from worker threads to the main GUI thread."""

    loaded = pyqtSignal(str, bytes)


class _ImageFetchRunnable(QRunnable):
    """Downloads a single image in a thread pool."""

    def __init__(self, url: str, signals: _ImageSignals) -> None:
        super().__init__()
        self.url = url
        self._signals = signals
        self.setAutoDelete(True)

    def run(self):
        try:
            resp = get_session().get(self.url, timeout=15)
            resp.raise_for_status()
            data = resp.content
            if data:
                self._signals.loaded.emit(self.url, data)
        except Exception as e:
            logging.debug(f"RichHTML: Failed to load image {self.url}: {e}")


_IMAGE_CACHE = OrderedDict()


def _cache_image(url: str, img: QImage):
    _IMAGE_CACHE.pop(url, None)
    _IMAGE_CACHE[url] = img
    if len(_IMAGE_CACHE) > RICH_HTML_IMAGE_CACHE_MAX_SIZE:
        _IMAGE_CACHE.popitem(last=False)


def load_remote_images(
    browser: QTextBrowser, html: str, widget_width: int | None = None
):
    """Find all <img src="http..."> in *html*, download them in background threads,
    and register each as a QTextDocument ImageResource so Qt renders them.

    For animated GIFs a static first-frame fallback is used (QTextBrowser cannot
    play animations inline, but the image will still appear).

    Call this AFTER browser.setHtml(html).
    """
    doc = browser.document()
    if doc is None:
        return

    max_width = max(
        200,
        int(
            widget_width or (browser.viewport().width() if browser.viewport() else 600)
        ),
    )
    image_requests = _image_requests(html, max_width)
    if not image_requests:
        return

    requests_by_url = {}
    for request in image_requests:
        current = requests_by_url.get(request["src"])
        if current is None:
            requests_by_url[request["src"]] = request
            continue
        current["width"] = max(current.get("width", 0), request.get("width", 0))
        current["height"] = max(current.get("height", 0), request.get("height", 0))

    signals = _ImageSignals(browser)
    pool = QThreadPool.globalInstance()

    def _apply_image_resource(url: str, image: QImage):
        request = requests_by_url.get(url, {})
        target_width = max(1, int(request.get("width") or max_width))
        display_image = image
        if display_image.width() > target_width:
            display_image = display_image.scaledToWidth(
                target_width, Qt.TransformationMode.SmoothTransformation
            )
        doc.addResource(
            QTextDocument.ResourceType.ImageResource, QUrl(url), display_image
        )
        _refresh_browser_document(browser, doc)

    for url, request in requests_by_url.items():
        placeholder_text = tr("ui.loading_placeholder")
        placeholder = _create_loading_placeholder(
            _placeholder_resource_width(request.get("width", max_width)),
            request.get("height", 0),
            placeholder_text,
        )
        doc.addResource(
            QTextDocument.ResourceType.ImageResource, QUrl(url), placeholder
        )
    _refresh_browser_document(browser, doc)

    def _on_loaded(url: str, data: bytes):
        try:
            from PyQt6 import sip as _sip

            if _sip.isdeleted(browser) or _sip.isdeleted(doc):
                return
        except (RuntimeError, AttributeError):
            return

        img = QImage()
        if not img.loadFromData(data):
            return

        _cache_image(url, img)
        _apply_image_resource(url, img)

    signals.loaded.connect(_on_loaded)

    for url in requests_by_url:
        cached = _IMAGE_CACHE.get(url)
        if isinstance(cached, QImage) and not cached.isNull():
            _IMAGE_CACHE.move_to_end(url)
            _apply_image_resource(url, cached)
            continue
        runnable = _ImageFetchRunnable(url, signals)
        pool.start(runnable)


def set_rich_html(browser: QTextBrowser, html: str, default_color: str = "#e8e9eb"):
    """One-call convenience: preprocess HTML, set it on the browser, load remote images.

    Args:
        browser: Target QTextBrowser widget.
        html: Raw HTML string (may contain remote images, CSS classes, font tags).
        default_color: Default text color for the wrapper div.
    """
    with contextlib.suppress(AttributeError, RuntimeError, TypeError):
        browser.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
    widget_width = _browser_available_width(browser)
    processed = preprocess_html(html, widget_width=widget_width)
    wrapped = f'<div style="color:{default_color};">{processed}</div>'
    browser.setHtml(wrapped)
    refined_width = _browser_available_width(browser)
    if abs(refined_width - widget_width) >= 4:
        widget_width = refined_width
        processed = preprocess_html(html, widget_width=widget_width)
        wrapped = f'<div style="color:{default_color};">{processed}</div>'
        browser.setHtml(wrapped)
    load_remote_images(browser, processed, widget_width=widget_width)
