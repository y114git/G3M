"""Rich HTML preprocessor for QTextBrowser.

Transforms web HTML (with remote images, CSS classes, font tags, etc.) into
Qt-compatible rich text. Downloads images asynchronously and injects them as
document resources so they render inline (including animated GIFs).
"""

import contextlib
import html as html_lib
import logging
import os
import re
import weakref
from collections import OrderedDict
from pathlib import PureWindowsPath
from urllib.parse import quote

from PyQt6.QtCore import QObject, QRectF, QRunnable, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QTextDocument
from PyQt6.QtWidgets import QTextBrowser, QTextEdit

from config.config import (
    RICH_HTML_ATTR_RE,
    RICH_HTML_CLASS_RE,
    RICH_HTML_CSS_CLASS_MAP,
    RICH_HTML_FONT_COLOR_RE,
    RICH_HTML_IMAGE_CACHE_MAX_SIZE,
    RICH_HTML_IMG_RE,
)
from services.background_operations import background_operations
from services.localization_service import tr
from ui.utils.image_loader import get_image_loader_pool
from utils.network_utils import get_session

logger = logging.getLogger(__name__)

_CSS_DOTS_PER_METER = 2835
_STYLE_BLOCK_RE = re.compile(
    r"<style\b[^>]*>(.*?)</style\s*>", re.IGNORECASE | re.DOTALL
)
_SCRIPT_BLOCK_RE = re.compile(
    r"<script\b[^>]*>.*?</script\b[^>]*>", re.IGNORECASE | re.DOTALL
)
_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE | re.DOTALL)
_CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]+)\}", re.IGNORECASE | re.DOTALL)
_UNQUOTED_ATTR_RE = re.compile(r"(\w[\w-]*)=([^\s\"'>/]+)")
_WINDOWS_DRIVE_PATTERN = re.compile(r"^[a-zA-Z]:[\\/]")
_OPEN_TAG_RE_TEMPLATE = r"<({tag})\b([^>]*)>"
_FIGCAPTION_RE = re.compile(
    r"<figcaption\b([^>]*)>(.*?)</figcaption>", re.IGNORECASE | re.DOTALL
)
_FIGURE_RE = re.compile(r"<figure\b([^>]*)>(.*?)</figure>", re.IGNORECASE | re.DOTALL)
_FLOAT_BLOCK_RE = re.compile(
    r"<(div|span)\b([^>]*(?:float\s*:\s*(?:left|right)|class=[\"'][^\"']*(?:floatleft|floatright|thumb|tright|tleft)[^\"']*[\"'])[^>]*)>(.*?)</\1>",
    re.IGNORECASE | re.DOTALL,
)
_CALLOUT_BLOCK_RE = re.compile(
    r"<div\b([^>]*(?:class=[\"'][^\"']*(?:note|warning|alert|important)[^\"']*[\"']|style=[\"'][^\"']*(?:background|border-left)[^\"']*[\"'])[^>]*)>(.*?)</div>",
    re.IGNORECASE | re.DOTALL,
)
_HEADING_WITH_RULE_RE = re.compile(
    r"<h([1-6])\b([^>]*)style=\"([^\"]*border-bottom:[^\"]*)\"([^>]*)>(.*?)</h\1>",
    re.IGNORECASE | re.DOTALL,
)
_LAYOUT_CONTAINER_CLASSES = {
    "page",
    "container",
    "wrapper",
    "content",
    "main",
    "grid",
    "row",
    "column",
}


def _parse_attrs(attr_str: str) -> dict:
    attrs = dict(RICH_HTML_ATTR_RE.findall(attr_str))
    for key, value in _UNQUOTED_ATTR_RE.findall(attr_str):
        attrs.setdefault(key, value)
    return attrs


def _attrs_to_string(attrs: dict) -> str:
    return "".join(
        f' {key}="{html_lib.escape(str(value), quote=True)}"'
        for key, value in attrs.items()
        if value
    )


def _append_style(attrs: dict, style: str) -> dict:
    if not style:
        return attrs
    existing = attrs.get("style", "").strip()
    if existing and not existing.endswith(";"):
        existing += ";"
    attrs["style"] = existing + style
    return attrs


def _css_declarations_to_inline(css: str) -> str:
    supported = []
    for raw_decl in css.split(";"):
        if ":" not in raw_decl:
            continue
        name, value = raw_decl.split(":", 1)
        name = name.strip().lower()
        value = value.strip()
        if not name or not value:
            continue
        if name in {
            "color",
            "background-color",
            "background",
            "font-family",
            "font-size",
            "font-style",
            "font-weight",
            "text-decoration",
            "text-align",
            "vertical-align",
            "line-height",
            "margin",
            "margin-left",
            "margin-right",
            "margin-top",
            "margin-bottom",
            "padding",
            "padding-left",
            "padding-right",
            "padding-top",
            "padding-bottom",
            "border",
            "border-left",
            "border-right",
            "border-top",
            "border-bottom",
            "width",
            "height",
        }:
            if name == "background" and re.fullmatch(r"#[0-9a-fA-F]{3,8}|\w+", value):
                name = "background-color"
            supported.append(f"{name}:{value};")
    return "".join(supported)


def _strip_block_paint_styles(inline: str) -> str:
    kept = []
    for raw_decl in inline.split(";"):
        if ":" not in raw_decl:
            continue
        name, value = raw_decl.split(":", 1)
        name = name.strip().lower()
        if name.startswith(("background", "border", "padding", "margin")):
            continue
        kept.append(f"{name}:{value.strip()};")
    return "".join(kept)


def _css_style_maps_from_style_blocks(
    html: str,
) -> tuple[dict[str, str], dict[str, str]]:
    class_map: dict[str, str] = {}
    element_map: dict[str, str] = {}
    for block in _STYLE_BLOCK_RE.findall(html):
        css = re.sub(r"/\*.*?\*/", "", block, flags=re.DOTALL)
        for selector_text, declarations in _CSS_RULE_RE.findall(css):
            inline = _css_declarations_to_inline(declarations)
            if not inline:
                continue
            for selector in selector_text.split(","):
                selector = selector.strip()
                if not selector:
                    continue
                selector_inline = inline
                if re.fullmatch(r"\.[\w-]+", selector):
                    class_name = selector[1:]
                    if class_name.lower() in _LAYOUT_CONTAINER_CLASSES:
                        selector_inline = _strip_block_paint_styles(selector_inline)
                        if not selector_inline:
                            continue
                    class_map[class_name] = (
                        class_map.get(class_name, "") + selector_inline
                    )
                    continue
                class_match = re.fullmatch(r"[a-z][\w-]*\.([\w-]+)", selector, re.I)
                if class_match:
                    class_name = class_match.group(1)
                    if class_name.lower() in _LAYOUT_CONTAINER_CLASSES:
                        selector_inline = _strip_block_paint_styles(selector_inline)
                        if not selector_inline:
                            continue
                    class_map[class_name] = (
                        class_map.get(class_name, "") + selector_inline
                    )
                    continue
                if re.fullmatch(r"[a-z][\w-]*", selector, re.I):
                    element = selector.lower()
                    element_map[element] = (
                        element_map.get(element, "") + selector_inline
                    )
    return class_map, element_map


def _strip_unsupported_blocks(html: str) -> str:
    html = _SCRIPT_BLOCK_RE.sub("", html)
    html = _LINK_TAG_RE.sub("", html)
    return _STYLE_BLOCK_RE.sub("", html)


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


def _style_text(style: str, name: str) -> str:
    if not style:
        return ""
    match = re.search(rf"{name}\s*:\s*([^;]+)", style, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _style_color(style: str, name: str) -> str:
    value = _style_text(style, name)
    if not value:
        return ""
    for token in value.split():
        color = token.strip()
        if re.fullmatch(r"#[0-9a-fA-F]{3,8}", color):
            return color
    color = value.split()[0].strip()
    return color if re.fullmatch(r"\w+", color) else ""


def _style_float(style: str) -> str:
    value = _style_text(style, "float").lower()
    return value if value in {"left", "right"} else ""


def _class_float(classes: str) -> str:
    normalized = {cls.lower() for cls in classes.split()}
    if normalized.intersection({"floatright", "tright", "thumb", "thumbinner"}):
        return "right"
    if normalized.intersection({"floatleft", "tleft"}):
        return "left"
    return ""


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


def _widget_available_width(widget: QTextBrowser | QTextEdit) -> int:
    viewport = None
    try:
        viewport = widget.viewport()
    except (AttributeError, RuntimeError, TypeError):
        viewport = None
    width_candidates = []
    if viewport is not None:
        with contextlib.suppress(AttributeError, RuntimeError, TypeError, ValueError):
            width_candidates.append(int(viewport.contentsRect().width()))
        with contextlib.suppress(AttributeError, RuntimeError, TypeError, ValueError):
            width_candidates.append(int(viewport.width()))
    with contextlib.suppress(AttributeError, RuntimeError, TypeError, ValueError):
        width_candidates.append(int(widget.contentsRect().width()))
    with contextlib.suppress(AttributeError, RuntimeError, TypeError, ValueError):
        width_candidates.append(int(widget.width()))
    available_width = next((width for width in width_candidates if width > 0), 600)
    try:
        document_margin = int(widget.document().documentMargin())
    except (AttributeError, TypeError, ValueError):
        document_margin = 0
    return max(available_width - (document_margin * 2), 200)


def _is_remote_image_src(src: str) -> bool:
    return src.startswith(("http://", "https://"))


def _is_absolute_local_path(src: str) -> bool:
    if os.path.isabs(src):
        return True
    return bool(_WINDOWS_DRIVE_PATTERN.match(src))


def _local_image_path_from_src(src: str) -> str:
    url = QUrl(src)
    if url.scheme().lower() == "file":
        return url.toLocalFile()
    if not url.scheme() and _is_absolute_local_path(src):
        return src
    return ""


def _resolve_image_src(src: str, base_path: str | None = None) -> str:
    src = (src or "").strip()
    if not src:
        return ""
    url = QUrl(src)
    scheme = url.scheme().lower()
    if scheme in {"http", "https", "data", "file"}:
        return src
    if scheme:
        return src
    if _is_absolute_local_path(src):
        return QUrl.fromLocalFile(src).toString()
    if base_path:
        if _WINDOWS_DRIVE_PATTERN.match(base_path):
            resolved = str(
                PureWindowsPath(base_path).joinpath(*src.replace("\\", "/").split("/"))
            ).replace("\\", "/")
            return f"file:///{quote(resolved, safe='/:')}"
        return QUrl.fromLocalFile(
            os.path.abspath(os.path.join(base_path, src))
        ).toString()
    return src


def _image_requests(html: str, widget_width: int) -> list[dict]:
    requests = []
    safe_width = _safe_inline_media_width(widget_width)
    for match in RICH_HTML_IMG_RE.finditer(html):
        attrs = _parse_attrs(match.group(1))
        src = attrs.get("src", "").strip()
        if not _is_remote_image_src(src) and not _local_image_path_from_src(src):
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
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
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


def _refresh_browser_document(browser: QTextBrowser | QTextEdit, doc: QTextDocument):
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
        logger.debug(f"Failed to refresh browser document: {e}")


def _normalize_media_blocks(html: str) -> str:
    html = _FIGCAPTION_RE.sub(
        lambda m: (
            f'<div{m.group(1)} style="font-size:90%; color:#bbbbbb; text-align:center;">{m.group(2)}</div>'
        ),
        html,
    )
    html = _FIGURE_RE.sub(
        lambda m: f'<div{m.group(1)} class="thumb">{m.group(2)}</div>',
        html,
    )

    def _float_repl(match):
        _tag, attr_text, inner = match.group(1), match.group(2), match.group(3)
        attrs = _parse_attrs(attr_text)
        classes = attrs.get("class", "")
        align = _style_float(attrs.get("style", "")) or _class_float(classes) or "right"
        attrs.pop("class", None)
        _append_style(
            attrs,
            "background-color:#222222; border:1px solid #444444; padding:6px; margin:6px;",
        )
        return (
            f'<table align="{align}" cellspacing="0" cellpadding="6"'
            f"{_attrs_to_string(attrs)}><tr><td>{inner}</td></tr></table>"
        )

    return _FLOAT_BLOCK_RE.sub(_float_repl, html)


def _resolve_element_styles(html: str, element_map: dict[str, str]) -> str:
    for tag, style in element_map.items():
        if not style:
            continue
        tag_re = re.compile(
            _OPEN_TAG_RE_TEMPLATE.format(tag=re.escape(tag)),
            re.IGNORECASE | re.DOTALL,
        )

        def _repl(match, inline_style=style):
            attrs = _parse_attrs(match.group(2))
            _append_style(attrs, inline_style)
            return f"<{match.group(1)}{_attrs_to_string(attrs)}>"

        html = tag_re.sub(_repl, html)
    return html


def _normalize_callout_blocks(html: str) -> str:
    def _repl(match):
        attrs = _parse_attrs(match.group(1))
        style = attrs.get("style", "")
        bgcolor = _style_color(style, "background-color") or _style_color(
            style, "background"
        )
        border = _style_color(style, "border-left") or _style_color(style, "border")
        table_attrs = ' width="100%" cellspacing="0" cellpadding="8"'
        if bgcolor:
            table_attrs += f' bgcolor="{bgcolor}"'
        if border:
            table_attrs += f' style="border-left:4px solid {border};"'
        return f"<table{table_attrs}><tr><td>{match.group(2)}</td></tr></table>"

    return _CALLOUT_BLOCK_RE.sub(_repl, html)


def _normalize_heading_rules(html: str) -> str:
    def _repl(match):
        level, pre_attrs, style, post_attrs, inner = match.groups()
        border = _style_color(style, "border-bottom") or "#444444"
        clean_style = re.sub(
            r"border-bottom\s*:\s*[^;]+;?", "", style, flags=re.IGNORECASE
        )
        attrs = _parse_attrs(pre_attrs + post_attrs)
        attrs["style"] = clean_style
        return (
            f"<h{level}{_attrs_to_string(attrs)}>{inner}</h{level}>"
            f'<hr width="100%" color="{border}" />'
        )

    return _HEADING_WITH_RULE_RE.sub(_repl, html)


def _normalize_html_structure(html: str) -> str:
    html = re.sub(
        r"<\s*/?\s*section\b([^>]*)>",
        lambda m: "<div" + m.group(1) + ">" if "/" not in m.group(0) else "</div>",
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(
        r"<\s*/?\s*article\b([^>]*)>",
        lambda m: "<div" + m.group(1) + ">" if "/" not in m.group(0) else "</div>",
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(
        r"<\s*/?\s*main\b([^>]*)>",
        lambda m: "<div" + m.group(1) + ">" if "/" not in m.group(0) else "</div>",
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(
        r"<\s*/?\s*header\b([^>]*)>",
        lambda m: "<div" + m.group(1) + ">" if "/" not in m.group(0) else "</div>",
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(
        r"<\s*/?\s*footer\b([^>]*)>",
        lambda m: "<div" + m.group(1) + ">" if "/" not in m.group(0) else "</div>",
        html,
        flags=re.IGNORECASE,
    )
    return html


def _resolve_classes(html: str, extra_class_map: dict[str, str] | None = None) -> str:
    """Replace class="ClassName" with equivalent inline style."""
    class_map = dict(RICH_HTML_CSS_CLASS_MAP)
    if extra_class_map:
        class_map.update(extra_class_map)

    def _repl(m):
        tag, pre, classes, post = m.group(1), m.group(2), m.group(3), m.group(4)
        styles = []
        for cls in classes.split():
            css = class_map.get(cls)
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


def _build_img_tag(attrs: dict, widget_width: int, base_path: str | None = None) -> str:
    """Build a Qt-compatible <img> tag from parsed attributes."""
    src = _resolve_image_src(attrs.get("src", ""), base_path)
    if not src:
        return ""
    safe_width = _safe_inline_media_width(widget_width)
    style_attr = attrs.get("style", "")
    width_attr = (
        attrs.get("width", "")
        or _style_dimension(style_attr, "width")
        or _style_dimension(style_attr, "max-width")
    )
    height_attr = attrs.get("height", "") or _style_dimension(style_attr, "height")
    w = h = 0
    if width_attr:
        if width_attr.endswith("%"):
            try:
                pct = float(width_attr.rstrip("%"))
                w = max(1, int(safe_width * pct / 100))
            except ValueError:
                logger.debug("Failed to parse percentage width, using default")
        else:
            with contextlib.suppress(ValueError):
                w = int(width_attr)
    if height_attr:
        if height_attr.endswith("%"):
            logger.debug("Percentage height not supported for images")
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
    img_tag = f'<img src="{src}"{size_attrs}>'
    if w >= 120:
        return f"<br />{img_tag}<br />"
    return img_tag


def preprocess_html(
    html: str, widget_width: int = 600, base_path: str | None = None
) -> str:
    """Preprocess HTML for QTextBrowser: resolve classes, font tags, image sizes.

    Does NOT download images - call ``load_remote_images`` separately for that.
    Returns cleaned HTML string ready for setHtml().
    """
    class_map, element_map = _css_style_maps_from_style_blocks(html)
    html = _strip_unsupported_blocks(html)
    html = _normalize_html_structure(html)
    html = _normalize_media_blocks(html)
    html = _resolve_element_styles(html, element_map)
    html = _resolve_classes(html, class_map)
    html = _normalize_callout_blocks(html)
    html = _normalize_heading_rules(html)
    html = _resolve_font_tags(html)

    def _img_repl(m):
        attrs = _parse_attrs(m.group(1))
        tag = _build_img_tag(attrs, widget_width, base_path=base_path)
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
        self._signals_ref = weakref.ref(signals)
        self.setAutoDelete(True)

    def run(self):
        try:
            resp = get_session().get(self.url, timeout=15)
            resp.raise_for_status()
            data = resp.content
            signals = self._signals_ref()
            if data and signals is not None:
                with contextlib.suppress(RuntimeError):
                    signals.loaded.emit(self.url, data)
        except Exception as e:
            logger.debug(f"RichHTML: Failed to load image {self.url}: {e}")


_IMAGE_CACHE = OrderedDict()


def _cache_image(url: str, img: QImage):
    _IMAGE_CACHE.pop(url, None)
    _IMAGE_CACHE[url] = img
    if len(_IMAGE_CACHE) > RICH_HTML_IMAGE_CACHE_MAX_SIZE:
        _IMAGE_CACHE.popitem(last=False)


def load_remote_images(
    browser: QTextBrowser | QTextEdit, html: str, widget_width: int | None = None
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
    pool = get_image_loader_pool()

    def _apply_image_resource(url: str, image: QImage):
        request = requests_by_url.get(url, {})
        target_width = max(1, int(request.get("width") or max_width))
        display_image = QImage(image)
        display_image.setDotsPerMeterX(_CSS_DOTS_PER_METER)
        display_image.setDotsPerMeterY(_CSS_DOTS_PER_METER)
        if display_image.width() > target_width:
            display_image = display_image.scaledToWidth(
                target_width, Qt.TransformationMode.SmoothTransformation
            )
            display_image.setDotsPerMeterX(_CSS_DOTS_PER_METER)
            display_image.setDotsPerMeterY(_CSS_DOTS_PER_METER)
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
        local_path = _local_image_path_from_src(url)
        if local_path:
            img = QImage(local_path)
            if not img.isNull():
                _cache_image(url, img)
                _apply_image_resource(url, img)
            continue
        runnable = _ImageFetchRunnable(url, signals)
        background_operations.start_runnable(pool, runnable)


def set_rich_html(
    browser: QTextBrowser | QTextEdit,
    html: str,
    default_color: str = "#e8e9eb",
    base_path: str | None = None,
):
    """One-call convenience: preprocess HTML, set it on the browser, load remote images.

    Args:
        browser: Target QTextBrowser widget.
        html: Raw HTML string (may contain remote images, CSS classes, font tags).
        default_color: Default text color for the wrapper div.
    """
    with contextlib.suppress(AttributeError, RuntimeError, TypeError):
        browser.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
    widget_width = _widget_available_width(browser)
    processed = preprocess_html(html, widget_width=widget_width, base_path=base_path)
    wrapped = f'<div style="color:{default_color};">{processed}</div>'
    browser.setHtml(wrapped)
    refined_width = _widget_available_width(browser)
    if abs(refined_width - widget_width) >= 4:
        widget_width = refined_width
        processed = preprocess_html(
            html, widget_width=widget_width, base_path=base_path
        )
        wrapped = f'<div style="color:{default_color};">{processed}</div>'
        browser.setHtml(wrapped)
    load_remote_images(browser, processed, widget_width=widget_width)
