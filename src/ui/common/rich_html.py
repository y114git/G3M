"""Rich HTML preprocessor for QTextBrowser.

Transforms web HTML (with remote images, CSS classes, font tags, etc.) into
Qt-compatible rich text. Downloads images asynchronously and injects them as
document resources so they render inline (including animated GIFs).
"""
import re
import logging
from PyQt6.QtCore import QUrl, QRunnable, QThreadPool, QObject, pyqtSignal
from PyQt6.QtGui import QImage, QTextDocument
from PyQt6.QtWidgets import QTextBrowser
from utils.network_utils import get_session

_CSS_CLASS_MAP = {
    'RedColor': 'color:#ff4444;',
    'BlueColor': 'color:#5599ff;',
    'GreenColor': 'color:#44ff44;',
    'YellowColor': 'color:#ffdd44;',
    'WhiteColor': 'color:#ffffff;',
    'SelectedElement': '',
}

_IMG_RE = re.compile(
    r'<img\b([^>]*)/?>', re.IGNORECASE | re.DOTALL
)
_ATTR_RE = re.compile(r'(\w[\w-]*)=["\']([^"\']*)["\']')
_CLASS_RE = re.compile(
    r'<(\w+)\b([^>]*?)\bclass=["\']([^"\']*)["\']([^>]*)>', re.IGNORECASE
)
_FONT_COLOR_RE = re.compile(
    r'<font\b([^>]*?)\bcolor=["\']([^"\']*)["\']([^>]*)>(.*?)</font>',
    re.IGNORECASE | re.DOTALL
)


def _parse_attrs(attr_str: str) -> dict:
    return dict(_ATTR_RE.findall(attr_str))


def _resolve_classes(html: str) -> str:
    """Replace class="ClassName" with equivalent inline style."""
    def _repl(m):
        tag, pre, classes, post = m.group(1), m.group(2), m.group(3), m.group(4)
        styles = []
        for cls in classes.split():
            css = _CSS_CLASS_MAP.get(cls)
            if css:
                styles.append(css)
        if not styles:
            return m.group(0).replace(f'class="{classes}"', '').replace(f"class='{classes}'", '')
        existing = ''
        style_match = re.search(r'style=["\']([^"\']*)["\']', pre + post)
        if style_match:
            existing = style_match.group(1).rstrip(';') + ';'
            pre = re.sub(r'\s*style=["\'][^"\']*["\']', '', pre)
            post = re.sub(r'\s*style=["\'][^"\']*["\']', '', post)
        style_val = existing + ''.join(styles)
        clean_pre = re.sub(r'\s*class=["\'][^"\']*["\']', '', pre)
        clean_post = re.sub(r'\s*class=["\'][^"\']*["\']', '', post)
        return f'<{tag}{clean_pre} style="{style_val}"{clean_post}>'
    return _CLASS_RE.sub(_repl, html)


def _resolve_font_tags(html: str) -> str:
    """Convert <font color="X">...</font> to <span style="color:X;">...</span>."""
    def _repl(m):
        pre, color, post, inner = m.group(1), m.group(2), m.group(3), m.group(4)
        other_attrs = (pre.strip() + ' ' + post.strip()).strip()
        if other_attrs:
            return f'<span style="color:{color};" {other_attrs}>{inner}</span>'
        return f'<span style="color:{color};">{inner}</span>'
    return _FONT_COLOR_RE.sub(_repl, html)


def _build_img_tag(attrs: dict, widget_width: int) -> str:
    """Build a Qt-compatible <img> tag from parsed attributes."""
    src = attrs.get('src', '')
    if not src:
        return ''
    width_attr = attrs.get('width', '')
    height_attr = attrs.get('height', '')
    w = h = 0
    if width_attr:
        if width_attr.endswith('%'):
            try:
                pct = float(width_attr.rstrip('%'))
                w = max(1, int(widget_width * pct / 100))
            except ValueError:
                pass
        else:
            try:
                w = int(width_attr)
            except ValueError:
                pass
    if height_attr:
        if height_attr.endswith('%'):
            pass
        else:
            try:
                h = int(height_attr)
            except ValueError:
                pass
    size_attrs = ''
    if w:
        size_attrs += f' width="{w}"'
    if h:
        size_attrs += f' height="{h}"'
    return f'<img src="{src}"{size_attrs} />'


def preprocess_html(html: str, widget_width: int = 600) -> str:
    """Preprocess HTML for QTextBrowser: resolve classes, font tags, image sizes.

    Does NOT download images — call ``load_remote_images`` separately for that.
    Returns cleaned HTML string ready for setHtml().
    """
    html = _resolve_classes(html)
    html = _resolve_font_tags(html)

    def _img_repl(m):
        attrs = _parse_attrs(m.group(1))
        tag = _build_img_tag(attrs, widget_width)
        return tag if tag else m.group(0)
    html = _IMG_RE.sub(_img_repl, html)
    return html


class _ImageSignals(QObject):
    """Bridge to deliver image data from worker threads to the main GUI thread."""
    loaded = pyqtSignal(str, bytes)


class _ImageFetchRunnable(QRunnable):
    """Downloads a single image in a thread pool."""

    def __init__(self, url: str, signals: _ImageSignals):
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
            logging.debug(f'RichHTML: Failed to load image {self.url}: {e}')


def load_remote_images(browser: QTextBrowser, html: str):
    """Find all <img src="http..."> in *html*, download them in background threads,
    and register each as a QTextDocument ImageResource so Qt renders them.

    For animated GIFs a static first-frame fallback is used (QTextBrowser cannot
    play animations inline, but the image will still appear).

    Call this AFTER browser.setHtml(html).
    """
    doc = browser.document()
    if doc is None:
        return

    urls = list(dict.fromkeys(
        m.group(1) for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if m.group(1).startswith(('http://', 'https://'))
    ))
    if not urls:
        return

    signals = _ImageSignals(browser)
    pool = QThreadPool.globalInstance()

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

        doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), img)

        try:
            from PyQt6 import sip as _sip
            if not _sip.isdeleted(browser):
                cursor = browser.textCursor()
                browser.setDocument(doc)
                browser.setTextCursor(cursor)
        except (RuntimeError, AttributeError):
            pass

    signals.loaded.connect(_on_loaded)

    for url in urls:
        runnable = _ImageFetchRunnable(url, signals)
        pool.start(runnable)


def set_rich_html(browser: QTextBrowser, html: str, default_color: str = 'white'):
    """One-call convenience: preprocess HTML, set it on the browser, load remote images.

    Args:
        browser: Target QTextBrowser widget.
        html: Raw HTML string (may contain remote images, CSS classes, font tags).
        default_color: Default text color for the wrapper div.
    """
    widget_width = max(browser.viewport().width() - 30, 200) if browser.viewport() else 600
    processed = preprocess_html(html, widget_width=widget_width)
    wrapped = f'<div style="color:{default_color};">{processed}</div>'
    browser.setHtml(wrapped)
    load_remote_images(browser, processed)
