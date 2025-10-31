from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QScrollArea, QTextBrowser
from managers.localization_manager import tr
from ui.common.styling import get_theme_color, load_mod_icon_universal
from ui.widgets.common.outlined_label import OutlinedTextLabel
from ui.widgets.common.screenshots_carousel import ScreenshotsCarousel
import webbrowser


def open_mod_details_dialog(parent, mod_data):
    dialog = QDialog(parent)
    dialog.setWindowTitle(tr('ui.mod_details_title', mod_name=mod_data.name))
    dialog.setMinimumSize(700, 700)
    dialog.resize(800, 750)
    app_state = getattr(parent, 'app_state', None)
    local_cfg = getattr(app_state, 'local_config', None) if app_state is not None else None
    secondary_text_color = get_theme_color(local_cfg, 'version_text', 'rgba(255, 255, 255, 178)')
    layout = QVBoxLayout(dialog)
    layout.setSpacing(15)
    scroll_area = QScrollArea()
    scroll_widget = QWidget()
    scroll_layout = QVBoxLayout(scroll_widget)
    header_layout = QHBoxLayout()
    left_layout = QVBoxLayout()
    icon_label = QLabel()
    icon_label.setFixedSize(120, 120)
    icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon_label.setStyleSheet('border: 2px solid #fff;')
    load_mod_icon_universal(icon_label, mod_data, 120)
    left_layout.addWidget(icon_label)
    left_container = QWidget()
    left_container.setMaximumWidth(200)
    left_container.setLayout(left_layout)
    metadata_layout = QVBoxLayout()
    metadata_layout.setSpacing(3)
    author_text = mod_data.author or tr('defaults.unknown')
    author_label = QLabel(f"""<span style="color: white;">{tr('ui.author_label')}</span> <span style="color: {secondary_text_color};">{author_text}</span>""")
    author_label.setStyleSheet('font-size: 12px;')
    metadata_layout.addWidget(author_label)
    game_version_text = mod_data.game_version or 'N/A'
    game_version_label = QLabel(f"""<span style="color: white;">{tr('ui.game_version_label')}</span> <span style="color: {secondary_text_color};">{game_version_text}</span>""")
    game_version_label.setStyleSheet('font-size: 12px;')
    metadata_layout.addWidget(game_version_label)
    created_date_text = mod_data.created_date or 'N/A'
    created_label = QLabel(f"""<span style="color: white;">{tr('ui.created_label')}</span> <span style="color: {secondary_text_color};">{created_date_text}</span>""")
    created_label.setStyleSheet('font-size: 12px;')
    metadata_layout.addWidget(created_label)
    updated_date_text = mod_data.last_updated or 'N/A'
    updated_label = QLabel(f"""<span style="color: white;">{tr('ui.updated_label')}</span> <span style="color: {secondary_text_color};">{updated_date_text}</span>""")
    updated_label.setStyleSheet('font-size: 12px;')
    metadata_layout.addWidget(updated_label)
    downloads_label = QLabel(f"""<span style="color: white;">{tr('ui.downloads_label')}</span> <span style="color: {secondary_text_color};">{mod_data.downloads}</span>""")
    downloads_label.setStyleSheet('font-size: 12px;')
    metadata_layout.addWidget(downloads_label)
    if hasattr(mod_data, 'tags') and mod_data.tags:
        metadata_layout.addSpacing(8)
        tags_header = QLabel(tr('ui.tags_label'))
        tags_header.setStyleSheet('font-size: 12px; color: white; font-weight: bold;')
        metadata_layout.addWidget(tags_header)
        tag_translations = {'translation': tr('tags.translation'), 'customization': tr('tags.customization'), 'gameplay': tr('tags.gameplay'), 'other': tr('tags.other')}
        tags_list = mod_data.tags if isinstance(mod_data.tags, list) else [mod_data.tags]
        filtered_tags = [tag for tag in tags_list if tag]
        translated_tags = [tag_translations.get(tag, tag) or tag for tag in filtered_tags]
        for tag in translated_tags:
            tag_label = QLabel(tag)
            tag_label.setStyleSheet(f'font-size: 12px; color: {secondary_text_color}; margin-left: 10px;')
            tag_label.setMaximumWidth(190)
            metadata_layout.addWidget(tag_label)
    left_layout.addLayout(metadata_layout)
    left_layout.addStretch()
    header_layout.addWidget(left_container)
    right_layout = QVBoxLayout()
    if hasattr(mod_data, 'external_url') and mod_data.external_url:
        external_url_button = QPushButton(tr('ui.view_on_external_site'))
        external_url_button.clicked.connect(lambda: webbrowser.open(mod_data.external_url))
        external_url_button.setStyleSheet('color: #FFD700; font-weight: bold;')
        right_layout.addWidget(external_url_button)
    title_label = QLabel(f'<h2>{mod_data.name}</h2>')
    title_label.setWordWrap(True)
    right_layout.addWidget(title_label)
    mod_version = mod_data.version.split('|')[0] if mod_data.version and '|' in mod_data.version else mod_data.version
    version_text = mod_version or 'N/A'
    version_label = QLabel(tr('ui.mod_version_label', version_text=version_text))
    version_label.setStyleSheet(f'font-size: 14px; color: {secondary_text_color}; margin-bottom: 10px;')
    right_layout.addWidget(version_label)
    tagline_container = QWidget()
    tagline_container.setMinimumHeight(180)
    tagline_layout = QVBoxLayout(tagline_container)
    tagline_layout.setContentsMargins(0, 0, 0, 0)
    if mod_data.tagline:
        tagline_label = QLabel(mod_data.tagline)
        tagline_label.setWordWrap(True)
        tagline_label.setStyleSheet('font-size: 14px; color: #ddd;')
        tagline_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        tagline_layout.addWidget(tagline_label)
    tagline_layout.addSpacing(20)
    status_layout = QVBoxLayout()
    status_layout.setSpacing(15)
    modgame_container = QVBoxLayout()
    modgame_container.setSpacing(4)
    modgame_label = OutlinedTextLabel(tr(f'ui.{mod_data.modgame}_label'))
    fill_color = 'white'
    outline_color = '#222222'
    if mod_data.modgame == 'deltarune':
        outline_color = '#222222'
    elif mod_data.modgame == 'deltarunedemo':
        outline_color = 'lightgreen'
    elif mod_data.modgame == 'undertale':
        outline_color = '#750B0B'
    f = modgame_label.font()
    f.setBold(True)
    f.setPointSize(15)
    modgame_label.setFont(f)
    modgame_label.setColors(fill_color, outline_color)
    modgame_label.setOutlineWidth(0.8)
    modgame_label.setMinimumHeight(26)
    modgame_label.setLeftMargin(0)
    modgame_container.addWidget(modgame_label)
    modgame_desc = OutlinedTextLabel(tr(f'ui.{mod_data.modgame}_desc'))
    df = modgame_desc.font()
    df.setPointSize(11)
    modgame_desc.setFont(df)
    modgame_desc.setColors(fill_color, outline_color)
    modgame_desc.setOutlineWidth(0.7)
    modgame_desc.setMinimumHeight(18)
    modgame_desc.setLeftMargin(12)
    modgame_container.addWidget(modgame_desc)
    status_layout.addLayout(modgame_container)
    tagline_layout.addLayout(status_layout)
    tagline_layout.addStretch()
    right_layout.addWidget(tagline_container)
    if getattr(mod_data, 'is_verified', False):
        verified_container = QVBoxLayout()
        verified_container.setSpacing(4)
        verified_label = QLabel(tr('ui.verified_label'))
        verified_label.setStyleSheet('color: #4CAF50; font-size: 15px;')
        verified_container.addWidget(verified_label)
        verified_desc = QLabel(tr('ui.verified_desc'))
        verified_desc.setStyleSheet('color: #4CAF50; font-size: 11px; margin-left: 12px;')
        verified_desc.setWordWrap(True)
        verified_container.addWidget(verified_desc)
        status_layout.addLayout(verified_container)
    if getattr(mod_data, 'is_xdelta', False):
        patching_container = QVBoxLayout()
        patching_container.setSpacing(4)
        patching_label = QLabel(tr('ui.patching_label'))
        patching_label.setStyleSheet('color: #2196F3; font-size: 15px;')
        patching_container.addWidget(patching_label)
        patching_desc = QLabel(tr('ui.patching_desc'))
        patching_desc.setStyleSheet('color: #2196F3; font-size: 11px; margin-left: 12px;')
        patching_desc.setWordWrap(True)
        patching_container.addWidget(patching_desc)
        status_layout.addLayout(patching_container)
    else:
        replacement_container = QVBoxLayout()
        replacement_container.setSpacing(4)
        replacement_label = QLabel(tr('ui.file_replacement_label'))
        replacement_label.setStyleSheet('color: #FF9800; font-size: 15px;')
        replacement_container.addWidget(replacement_label)
        replacement_desc = QLabel(tr('ui.file_replacement_desc'))
        replacement_desc.setStyleSheet('color: #FF9800; font-size: 11px; margin-left: 12px;')
        replacement_desc.setWordWrap(True)
        replacement_container.addWidget(replacement_desc)
        status_layout.addLayout(replacement_container)
    header_layout.addLayout(right_layout)
    scroll_layout.addLayout(header_layout)
    separator = QWidget()
    separator.setMinimumHeight(1)
    separator.setStyleSheet('background: rgba(255,255,255,0.25);')
    scroll_layout.addWidget(separator)
    screenshots = getattr(mod_data, 'screenshots_url', []) or []
    if isinstance(screenshots, list) and any((isinstance(u, str) and u.strip() for u in screenshots)):
        screenshots_title = QLabel(f"<b>{tr('ui.screenshots_title')}</b>")
        screenshots_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll_layout.addWidget(screenshots_title)
        carousel = ScreenshotsCarousel(screenshots, parent)
        container = QWidget()
        cont_layout = QHBoxLayout(container)
        cont_layout.setContentsMargins(0, 0, 0, 0)
        cont_layout.addStretch()
        cont_layout.addWidget(carousel)
        cont_layout.addStretch()
        scroll_layout.addWidget(container)
        scroll_layout.addSpacing(12)
    full_desc_label = QLabel(f"<b>{tr('ui.full_description_label')}</b>")
    full_desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    scroll_layout.addWidget(full_desc_label)
    scroll_layout.addSpacing(6)
    desc_text = QTextBrowser()
    desc_text.setMinimumHeight(300)
    desc_text.setOpenExternalLinks(True)
    if hasattr(mod_data, 'description_url') and mod_data.description_url:
        try:
            import requests
            desc_text.setPlainText(tr('status.loading_description'))
            response = requests.get(mod_data.description_url, timeout=10)
            if response.ok:
                content = response.text
                is_markdown = mod_data.description_url.lower().endswith(('.md', '.markdown')) or '# ' in content or '## ' in content or ('**' in content) or ('__' in content)
                if is_markdown:
                    desc_text.setMarkdown(content)
                else:
                    desc_text.setPlainText(content)
            else:
                desc_text.setPlainText(tr('errors.description_http_error_code', code=response.status_code))
        except Exception as e:
            desc_text.setPlainText(tr('errors.description_load_error_details', error=str(e)))
    else:
        desc_text.setPlainText(tr('ui.no_description'))
    scroll_layout.addWidget(desc_text)
    scroll_area.setWidget(scroll_widget)
    scroll_area.setWidgetResizable(True)
    layout.addWidget(scroll_area)
    buttons_layout = QHBoxLayout()
    if hasattr(mod_data, 'url') and mod_data.url:
        open_url_btn = QPushButton(tr('ui.open_in_browser'))
        open_url_btn.clicked.connect(lambda: webbrowser.open(mod_data.url))
        buttons_layout.addWidget(open_url_btn)
    buttons_layout.addStretch()
    close_btn = QPushButton(tr('buttons.close'))
    close_btn.clicked.connect(dialog.close)
    buttons_layout.addWidget(close_btn)
    layout.addLayout(buttons_layout)
    dialog.exec()
