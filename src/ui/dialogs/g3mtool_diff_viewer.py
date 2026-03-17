"""Diff viewer dialog for G3M Actions diff reports."""
import logging
import re
import shutil

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from services.localization_service import tr
from ui.common.dialog_theme import build_dialog_theme_stylesheet, get_dialog_theme_values
from ui.common.styling import get_theme_color, rgba_from_color

logger = logging.getLogger(__name__)

_H_RE = re.compile(r'^(#{1,3})\s+(.+)', re.MULTILINE)


def _parse_tree(md_text: str):
    """Parse markdown into a flat list of (level, title, body) tuples."""
    matches = list(_H_RE.finditer(md_text))
    if not matches:
        return [(1, 'Report', md_text)]
    sections = []
    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        body = md_text[start:end].strip()
        sections.append((level, title, body))
    return sections or [(1, 'Report', md_text)]


def _esc(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _looks_like_diff(lines):
    for ln in lines[:10]:
        if ln.startswith('---') or ln.startswith('+++') or ln.startswith('@@'):
            return True
    return False


def _format_code_block(code_lines, lang, background_color):
    """Format a fenced code block with optional diff highlighting."""
    is_diff = lang == 'diff' or (not lang and _looks_like_diff(code_lines))
    parts = [f'<pre style="background:{background_color};border-radius:4px;padding:8px;'
             'font-family:Consolas,monospace;font-size:11px;white-space:pre-wrap">']
    for raw in code_lines:
        e = _esc(raw)
        if is_diff:
            if raw.startswith('+'):
                parts.append(f'<span style="color:#98c379">{e}</span>\n')
            elif raw.startswith('-'):
                parts.append(f'<span style="color:#e06c75">{e}</span>\n')
            elif raw.startswith('@@'):
                parts.append(f'<span style="color:#c678dd">{e}</span>\n')
            else:
                parts.append(e + '\n')
        else:
            parts.append(e + '\n')
    parts.append('</pre>')
    return ''.join(parts)


def _md_to_html(body: str, quote_border_color: str, quote_text_color: str, code_background_color: str, inline_code_background_color: str) -> str:
    """Convert markdown body to styled HTML."""
    lines = []
    in_table = in_list = in_code = False
    code_lines = []
    code_lang = ''
    for raw in body.splitlines():
        s = raw.strip()
        if s.startswith('```'):
            if in_code:
                lines.append(_format_code_block(code_lines, code_lang, code_background_color))
                code_lines, code_lang, in_code = [], '', False
            else:
                if in_list:
                    lines.append('</ul>')
                    in_list = False
                if in_table:
                    lines.append('</table>')
                    in_table = False
                code_lang, in_code = s[3:].strip(), True
            continue
        if in_code:
            code_lines.append(raw)
            continue
        if s.startswith('|') and s.endswith('|'):
            if not in_table:
                if in_list:
                    lines.append('</ul>')
                    in_list = False
                lines.append('<table cellspacing="0" cellpadding="4" style="border-collapse:collapse;width:100%">')
                in_table = True
            if set(s.replace('|', '').strip()) <= {'-', ':'}:
                continue
            cells = [c.strip() for c in s.strip('|').split('|')]
            tag = 'th' if not any('<td' in ln for ln in lines[-3:]) else 'td'
            lines.append('<tr>' + ''.join(f'<{tag}>{_inline(c, inline_code_background_color)}</{tag}>' for c in cells) + '</tr>')
            continue
        if in_table:
            lines.append('</table><br>')
            in_table = False
        if s.startswith('> '):
            if in_list:
                lines.append('</ul>')
                in_list = False
            lines.append(f'<blockquote style="border-left:3px solid {quote_border_color};'
                         f'margin:4px 0;padding:2px 12px;color:{quote_text_color}">'
                         f'{_inline(s[2:], inline_code_background_color)}</blockquote>')
        elif s.startswith('- '):
            if not in_list:
                lines.append('<ul>')
                in_list = True
            lines.append(f'<li>{_inline(s[2:], inline_code_background_color)}</li>')
        elif s.startswith('### '):
            if in_list:
                lines.append('</ul>')
                in_list = False
            lines.append(f'<h4>{_inline(s[4:], inline_code_background_color)}</h4>')
        elif s.startswith('## '):
            if in_list:
                lines.append('</ul>')
                in_list = False
            lines.append(f'<h3>{_inline(s[3:], inline_code_background_color)}</h3>')
        elif s:
            if in_list:
                lines.append('</ul>')
                in_list = False
            lines.append(f'<p>{_inline(s, inline_code_background_color)}</p>')
        else:
            if in_list:
                lines.append('</ul>')
                in_list = False
            lines.append('<br>')
    if in_table:
        lines.append('</table>')
    if in_list:
        lines.append('</ul>')
    if in_code:
        lines.append(_format_code_block(code_lines, code_lang, code_background_color))
    return '\n'.join(lines)


def _inline(text: str, inline_code_background_color: str) -> str:
    text = _esc(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'`(.+?)`', f'<code style="background:{inline_code_background_color};padding:1px 4px;border-radius:3px">\\1</code>', text)
    return text


def _get_app_font(app_state) -> str:
    """Return the current DELTAHUB font family or fallback."""
    parent = app_state
    while parent and not hasattr(parent, 'custom_font_family'):
        parent = getattr(parent, 'parent', None)
    ff = getattr(parent, 'custom_font_family', None) if parent else None
    return ff or 'Segoe UI'


class _CollapsibleSection(QWidget):
    """A section header that toggles body visibility."""
    clicked = pyqtSignal(int)

    def __init__(self, index: int, title: str, body_html: str, font_family: str, parent=None):
        super().__init__(parent)
        self._index = index
        self._expanded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._header = QPushButton(f'\u25b6  {title}')
        self._header.setObjectName('g3m_actions_section_header')
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.clicked.connect(self._toggle)
        self._title = title
        lay.addWidget(self._header)

        self._body = QTextEdit()
        self._body.setReadOnly(True)
        self._body.setObjectName('g3m_actions_section_body')
        self._body.setVisible(False)
        self._body.setHtml(f'<div style="font-family:\'{font_family}\';font-size:12px">{body_html}</div>')
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._body.document().setDocumentMargin(8)
        lay.addWidget(self._body)

    def _toggle(self):
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        arrow = '\u25bc' if self._expanded else '\u25b6'
        self._header.setText(f'{arrow}  {self._title}')
        if self._expanded:
            doc_h = int(self._body.document().size().height()) + 16
            self._body.setMinimumHeight(min(doc_h, 500))
            self._body.setMaximumHeight(min(doc_h, 500))
            self.clicked.emit(self._index)
        else:
            self._body.setMinimumHeight(0)
            self._body.setMaximumHeight(0)


class DiffViewerDialog(QDialog):
    """Show parsed diff report with collapsible sections."""

    def __init__(self, md_path: str, app_state, parent=None):
        super().__init__(parent)
        self._app_state = app_state
        self._md_path = md_path
        self.setWindowTitle(tr('g3m_actions.diff_viewer_title'))
        self.setMinimumSize(900, 600)
        self.resize(1300, 820)
        self.setModal(False)
        self._sections = []
        self._section_widgets = []
        self._load(md_path)
        self._build_ui()
        self._apply_theme()

    def _load(self, path: str):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                self._sections = _parse_tree(f.read())
        except Exception as e:
            logger.error('Failed to read diff report: %s', e)
            self._sections = [(1, 'Error', str(e))]

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(6)

        header = QHBoxLayout()
        self._title_label = QLabel(tr('g3m_actions.diff_viewer_title'))
        self._title_label.setObjectName('g3m_actions_title')
        font = self._title_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self._title_label.setFont(font)
        header.addWidget(self._title_label)
        header.addStretch()
        self._export_btn = QPushButton()
        self._export_btn.setObjectName('g3m_actions_export_btn')
        self._export_btn.setToolTip(tr('g3m_actions.export_report'))
        self._export_btn.clicked.connect(self._on_export)
        self._export_btn.setFixedSize(30, 30)
        try:
            from utils.path_utils import colored_icon
            tc = get_theme_color(self._app_state.local_config, 'text', '#ffffff')
            self._export_btn.setIcon(colored_icon('export', tc))
            self._export_btn.setIconSize(QSize(18, 18))
        except Exception:
            self._export_btn.setText('Export')
        header.addWidget(self._export_btn)
        header.addSpacing(4)
        self._close_btn = QPushButton(tr('common.close'))
        self._close_btn.setObjectName('g3m_actions_close_btn')
        self._close_btn.clicked.connect(self.close)
        header.addWidget(self._close_btn)
        main.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName('g3m_actions_diff_scroll')
        container = QWidget()
        self._container_lay = QVBoxLayout(container)
        self._container_lay.setContentsMargins(4, 4, 4, 4)
        self._container_lay.setSpacing(4)

        font_family = _get_app_font(self._app_state)
        config = getattr(self._app_state, 'local_config', None)
        quote_border_color = rgba_from_color(get_theme_color(config, 'text', '#ffffff'), alpha=76, fallback='rgba(255, 255, 255, 76)')
        quote_text_color = rgba_from_color(get_theme_color(config, 'text', '#ffffff'), alpha=178, fallback='rgba(255, 255, 255, 178)')
        code_background_color = rgba_from_color(get_theme_color(config, 'background', '#000000'), alpha=76, fallback='rgba(0, 0, 0, 76)')
        inline_code_background_color = rgba_from_color(get_theme_color(config, 'text', '#ffffff'), alpha=15, fallback='rgba(255, 255, 255, 15)')
        for i, (level, title, body) in enumerate(self._sections):
            html = _md_to_html(body, quote_border_color, quote_text_color, code_background_color, inline_code_background_color)
            sec = _CollapsibleSection(i, title, html, font_family)
            indent = (level - 1) * 16
            if indent > 0:
                sec.setContentsMargins(indent, 0, 0, 0)
            self._section_widgets.append(sec)
            self._container_lay.addWidget(sec)
        self._container_lay.addStretch()

        scroll.setWidget(container)
        main.addWidget(scroll, 1)

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr('g3m_actions.export_report'), '', 'Markdown files (*.md);;All Files (*)',
        )
        if path:
            try:
                shutil.copy2(self._md_path, path)
            except Exception as exc:
                logger.error('Failed to export diff report: %s', exc)

    def _apply_theme(self):
        base = build_dialog_theme_stylesheet(self._app_state)
        theme = get_dialog_theme_values(self._app_state)
        font_family = _get_app_font(self._app_state)
        extra = f'''
            QLabel#g3m_actions_title {{
                font-size: 16px;
            }}
            QPushButton#g3m_actions_section_header {{
                background-color: {theme["button"]};
                border: 2px solid {theme["border"]};
                border-radius: {theme["button_radius"]}px;
                color: {theme["text"]};
                font-family: '{font_family}';
                font-size: 13px;
                font-weight: bold;
                padding: 8px 12px;
                text-align: left;
            }}
            QPushButton#g3m_actions_section_header:hover {{
                background-color: {theme["button_hover"]};
            }}
            QTextEdit#g3m_actions_section_body {{
                background-color: {theme["background"]};
                border: 2px solid {theme["border"]};
                border-top: none;
                border-bottom-left-radius: {theme["field_radius"]}px;
                border-bottom-right-radius: {theme["field_radius"]}px;
                color: {theme["text"]};
                font-family: '{font_family}';
                font-size: 12px;
                padding: 6px;
            }}
            QScrollArea#g3m_actions_diff_scroll {{
                border: none;
                background: transparent;
            }}
            QPushButton#g3m_actions_export_btn {{
                background-color: {theme["button"]};
                border: 2px solid {theme["border"]};
                border-radius: {theme["button_radius"]}px;
            }}
            QPushButton#g3m_actions_export_btn:hover {{
                background-color: {theme["button_hover"]};
            }}
        '''
        self.setStyleSheet(base + extra)

    def closeEvent(self, event):
        reply = QMessageBox.question(
            self, tr('g3m_actions.diff_viewer_title'), tr('g3m_actions.confirm_close'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            event.accept()
            self.deleteLater()
        else:
            event.ignore()

    def relocalize_ui(self):
        self.setWindowTitle(tr('g3m_actions.diff_viewer_title'))
        self._title_label.setText(tr('g3m_actions.diff_viewer_title'))
        self._close_btn.setText(tr('common.close'))
        self._export_btn.setToolTip(tr('g3m_actions.export_report'))

    def refresh_theme(self):
        self._apply_theme()
