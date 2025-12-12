from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QScrollArea, QTextBrowser
from managers.localization_manager import tr
from ui.common.styling import get_theme_color, load_mod_icon_universal
from ui.widgets.common.outlined_label import OutlinedTextLabel
from ui.widgets.common.screenshots_carousel import ScreenshotsCarousel
import logging
import webbrowser


class LoadModDetailsThread(QThread):
    details_loaded = pyqtSignal(dict)

    def __init__(self, mod_data, cache_dir=None, parent=None):
        super().__init__(parent)
        self.mod_data = mod_data
        self.cache_dir = cache_dir

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            mod_key = getattr(self.mod_data, 'key', None) or getattr(self.mod_data, 'mod_key', None)
            if not key or not key.startswith('gb_'):
                return
            mod_id_str = key.replace('gb_', '', 1)
            if not mod_id_str:
                return
            mod_id = int(mod_id_str)
            mod_id_str = str(mod_id)
            metadata_cache = None
            cached_text = None
            cached_screenshots = None
            if self.cache_dir:
                try:
                    if self.isInterruptionRequested():
                        return
                    from utils.gamebanana_cache import GameBananaMetadataCache
                    metadata_cache = GameBananaMetadataCache(self.cache_dir)
                    if metadata_cache.is_valid(mod_id_str):
                        cached_text = metadata_cache.get_full_description(mod_id_str)
                        cached_screenshots = metadata_cache.get_screenshots(mod_id_str)
                        if cached_text or cached_screenshots:
                            logging.debug(f'LoadModDetailsThread: Using cached data for mod {mod_id_str}')
                            result = {}
                            if cached_text:
                                result['text'] = cached_text
                            if cached_screenshots:
                                result['screenshots'] = cached_screenshots
                            if result:
                                if not self.isInterruptionRequested():
                                    self.details_loaded.emit(result)
                                return
                except Exception as e:
                    logging.warning(f'LoadModDetailsThread: Error accessing cache: {e}', exc_info=True)
            if self.isInterruptionRequested():
                return
            from utils.gamebanana_api import GameBananaAPI
            api = GameBananaAPI()
            details = api.get_mod_text_and_screenshots(mod_id)
            if details and (not self.isInterruptionRequested()):
                result = {}
                text_field = details.get('text')
                full_description = None
                if text_field:
                    if isinstance(text_field, list) and len(text_field) > 0:
                        full_description = text_field[0]
                    elif isinstance(text_field, str):
                        full_description = text_field
                    else:
                        full_description = str(text_field)
                    result['text'] = full_description
                screenshots_field = details.get('screenshots')
                screenshots = []
                if screenshots_field:
                    screenshots_data = None
                    if isinstance(screenshots_field, list) and len(screenshots_field) > 0:
                        screenshots_data = screenshots_field[0]
                    elif not isinstance(screenshots_field, list):
                        screenshots_data = screenshots_field
                    if isinstance(screenshots_data, str):
                        screenshots = api.extract_screenshots_from_api(screenshots_data)
                    elif isinstance(screenshots_data, list):
                        base_url = 'https://images.gamebanana.com/img/ss/mods'
                        for screenshot_obj in screenshots_data:
                            if self.isInterruptionRequested():
                                break
                            if isinstance(screenshot_obj, dict):
                                file_name = screenshot_obj.get('_sFile') or screenshot_obj.get('_sFile800') or screenshot_obj.get('_sFile530') or screenshot_obj.get('_sFile220')
                                if file_name:
                                    screenshot_url = f'{base_url}/{file_name}'
                                    screenshots.append(screenshot_url)
                    elif isinstance(screenshots_data, dict):
                        import json
                        try:
                            screenshots_str = json.dumps(screenshots_data)
                            screenshots = api.extract_screenshots_from_api(screenshots_str)
                        except (TypeError, ValueError):
                            screenshots = []
                result['screenshots'] = screenshots
                if metadata_cache and (full_description or screenshots):
                    try:
                        if not self.isInterruptionRequested():
                            metadata_cache.set(mod_id_str, full_description=full_description, screenshots=screenshots if screenshots else None)
                            logging.debug(f'LoadModDetailsThread: Saved details to cache for mod {mod_id_str}')
                    except Exception as e:
                        logging.warning(f'LoadModDetailsThread: Error saving to cache: {e}', exc_info=True)
                if not self.isInterruptionRequested():
                    self.details_loaded.emit(result)
        except Exception as e:
            if not self.isInterruptionRequested():
                logging.error(f'Error loading mod details: {e}', exc_info=True)


def open_mod_details_dialog(parent, mod_data):
    dialog = QDialog(parent)
    dialog.setWindowTitle(tr('ui.mod_details_title', mod_name=mod_data.name))
    dialog.setMinimumSize(700, 700)
    dialog.resize(800, 750)
    app_state = getattr(parent, 'app_state', None)
    local_cfg = getattr(app_state, 'local_config', None) if app_state is not None else None
    text_color = get_theme_color(local_cfg, 'text', 'white')
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
    border_color = get_theme_color(local_cfg, 'border', '#fff')
    icon_label.setStyleSheet(f'border: 2px solid {border_color};')
    load_mod_icon_universal(icon_label, mod_data, 120)
    left_layout.addWidget(icon_label)
    left_container = QWidget()
    left_container.setMaximumWidth(200)
    left_container.setLayout(left_layout)
    metadata_layout = QVBoxLayout()
    metadata_layout.setSpacing(3)
    author_text = mod_data.author or tr('defaults.unknown')
    author_label = QLabel(f"""<span style="color: {text_color};">{tr('ui.author_label')}</span> <span style="color: {secondary_text_color};">{author_text}</span>""")
    author_label.setStyleSheet('font-size: 12px;')
    metadata_layout.addWidget(author_label)
    game_version_text = mod_data.game_version or 'N/A'
    game_version_label = QLabel(f"""<span style="color: {text_color};">{tr('ui.game_version_label')}</span> <span style="color: {secondary_text_color};">{game_version_text}</span>""")
    game_version_label.setStyleSheet('font-size: 12px;')
    metadata_layout.addWidget(game_version_label)
    created_date_text = mod_data.created_date or 'N/A'
    created_label = QLabel(f"""<span style="color: {text_color};">{tr('ui.created_label')}</span> <span style="color: {secondary_text_color};">{created_date_text}</span>""")
    created_label.setStyleSheet('font-size: 12px;')
    metadata_layout.addWidget(created_label)
    updated_date_text = mod_data.last_updated or 'N/A'
    updated_label = QLabel(f"""<span style="color: {text_color};">{tr('ui.updated_label')}</span> <span style="color: {secondary_text_color};">{updated_date_text}</span>""")
    updated_label.setStyleSheet('font-size: 12px;')
    metadata_layout.addWidget(updated_label)
    downloads_label = QLabel(f"""<span style="color: {text_color};">{tr('ui.downloads_label')}</span> <span style="color: {secondary_text_color};">{mod_data.downloads}</span>""")
    downloads_label.setStyleSheet('font-size: 12px;')
    metadata_layout.addWidget(downloads_label)
    if hasattr(mod_data, 'tags') and mod_data.tags:
        metadata_layout.addSpacing(8)
        tags_header = QLabel(tr('ui.tags_label'))
        tags_header.setStyleSheet(f'font-size: 12px; color: {text_color}; font-weight: bold;')
        metadata_layout.addWidget(tags_header)
        tag_translations = {'textedit': tr('tags.textedit'), 'translation': tr('tags.textedit'), 'customization': tr('tags.customization'), 'gameplay': tr('tags.gameplay'), 'other': tr('tags.other')}
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
        tagline_label.setStyleSheet(f'font-size: 14px; color: {secondary_text_color};')
        tagline_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        tagline_layout.addWidget(tagline_label)
    tagline_layout.addSpacing(20)
    status_layout = QVBoxLayout()
    status_layout.setSpacing(15)
    modgame_container = QVBoxLayout()
    modgame_container.setSpacing(4)
    game_value = getattr(mod_data, 'game', None) or getattr(mod_data, 'modgame', 'deltarune')
    modgame_label = OutlinedTextLabel(tr(f'ui.{game_value}_label'))
    fill_color = text_color
    outline_color = '#222222'
    if game_value == 'deltarune':
        outline_color = '#222222'
    elif game_value == 'deltarunedemo':
        outline_color = 'lightgreen'
    elif game_value == 'undertale':
        outline_color = '#750B0B'
    elif game_value == 'undertaleyellow':
        outline_color = '#FFD700'
    f = modgame_label.font()
    f.setBold(True)
    f.setPointSize(15)
    modgame_label.setFont(f)
    modgame_label.setColors(fill_color, outline_color)
    modgame_label.setOutlineWidth(0.8)
    modgame_label.setMinimumHeight(26)
    modgame_label.setLeftMargin(0)
    modgame_container.addWidget(modgame_label)
    modgame_desc = OutlinedTextLabel(tr(f'ui.{game_value}_desc'))
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
    header_layout.addLayout(right_layout)
    scroll_layout.addLayout(header_layout)
    separator = QWidget()
    separator.setMinimumHeight(1)
    separator.setStyleSheet('background: rgba(255,255,255,0.25);')
    scroll_layout.addWidget(separator)
    screenshots_container = QWidget()
    screenshots_container_layout = QVBoxLayout(screenshots_container)
    screenshots_container_layout.setContentsMargins(0, 0, 0, 0)
    screenshots = getattr(mod_data, 'screenshots_url', []) or []
    screenshots_widget = None
    if isinstance(screenshots, list) and any((isinstance(u, str) and u.strip() for u in screenshots)):
        screenshots_title = QLabel(f"<b>{tr('ui.screenshots_title')}</b>")
        screenshots_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        screenshots_container_layout.addWidget(screenshots_title)
        app_state = getattr(parent, 'app_state', None) if parent else None
        screenshots_widget = ScreenshotsCarousel(screenshots, parent, app_state)
        container = QWidget()
        cont_layout = QHBoxLayout(container)
        cont_layout.setContentsMargins(0, 0, 0, 0)
        cont_layout.addStretch()
        cont_layout.addWidget(screenshots_widget)
        cont_layout.addStretch()
        screenshots_container_layout.addWidget(container)
    scroll_layout.addWidget(screenshots_container)
    scroll_layout.addSpacing(12)
    full_desc_label = QLabel(f"<b>{tr('ui.full_description_label')}</b>")
    full_desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    scroll_layout.addWidget(full_desc_label)
    scroll_layout.addSpacing(6)
    desc_text = QTextBrowser()
    desc_text.setMinimumHeight(300)
    desc_text.setOpenExternalLinks(True)
    dialog_closed = False

    def update_ui_with_details(details_dict):
        nonlocal dialog_closed
        try:
            if dialog_closed:
                return
            try:
                from PyQt6 import sip as _sip
                if _sip.isdeleted(dialog) or _sip.isdeleted(desc_text) or _sip.isdeleted(screenshots_container):
                    dialog_closed = True
                    return
            except (ImportError, AttributeError):
                try:
                    if not dialog.isVisible() or not hasattr(dialog, 'isVisible'):
                        dialog_closed = True
                        return
                except (RuntimeError, AttributeError):
                    dialog_closed = True
                    return
            except (RuntimeError, AttributeError):
                dialog_closed = True
                return
            if dialog_closed:
                return
            if details_dict.get('text'):
                try:
                    if dialog_closed:
                        return
                    try:
                        from PyQt6 import sip as _sip
                        if _sip.isdeleted(desc_text):
                            dialog_closed = True
                            return
                    except (ImportError, AttributeError, RuntimeError):
                        pass
                    desc_text.setHtml(details_dict['text'])
                except (RuntimeError, AttributeError) as e:
                    dialog_closed = True
                    logging.debug(f'Widget deleted while setting description: {e}')
                    return
                except Exception as e:
                    logging.warning(f'Error setting full_description HTML: {e}')
                    try:
                        if not dialog_closed:
                            desc_text.setPlainText(details_dict['text'])
                    except (RuntimeError, AttributeError):
                        dialog_closed = True
                        return
                    except Exception:
                        pass
            new_screenshots = details_dict.get('screenshots', [])
            if new_screenshots and isinstance(new_screenshots, list) and any((isinstance(u, str) and u.strip() for u in new_screenshots)):
                try:
                    if dialog_closed:
                        return
                    try:
                        from PyQt6 import sip as _sip
                        if _sip.isdeleted(screenshots_container) or _sip.isdeleted(screenshots_container_layout):
                            dialog_closed = True
                            return
                    except (ImportError, AttributeError, RuntimeError):
                        pass
                    while screenshots_container_layout.count() > 0:
                        item = screenshots_container_layout.takeAt(0)
                        widget = item.widget() if item else None
                        if widget:
                            try:
                                widget.deleteLater()
                            except (RuntimeError, AttributeError):
                                pass
                    if dialog_closed:
                        return
                    screenshots_title = QLabel(f"<b>{tr('ui.screenshots_title')}</b>")
                    screenshots_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    screenshots_container_layout.addWidget(screenshots_title)
                    app_state = getattr(parent, 'app_state', None) if parent else None
                    new_carousel = ScreenshotsCarousel(new_screenshots, parent, app_state)
                    container = QWidget()
                    cont_layout = QHBoxLayout(container)
                    cont_layout.setContentsMargins(0, 0, 0, 0)
                    cont_layout.addStretch()
                    cont_layout.addWidget(new_carousel)
                    cont_layout.addStretch()
                    screenshots_container_layout.addWidget(container)
                except (RuntimeError, AttributeError) as e:
                    dialog_closed = True
                    logging.debug(f'Widget deleted while updating screenshots: {e}')
                except Exception as e:
                    logging.warning(f'Error updating screenshots in mod details dialog: {e}', exc_info=True)
        except Exception as e:
            logging.error(f'Error in update_ui_with_details: {e}', exc_info=True)
            dialog_closed = True
    needs_load = hasattr(mod_data, 'is_gamebanana_mod') and mod_data.is_gamebanana_mod and hasattr(mod_data, 'gamebanana_mod_id') and mod_data.gamebanana_mod_id and (not hasattr(mod_data, 'full_description') or not mod_data.full_description)
    load_thread = None
    if needs_load:
        desc_text.setPlainText(tr('status.loading_description'))
        cache_dir = None
        if app_state and hasattr(app_state, 'cache_dir'):
            cache_dir = app_state.cache_dir
        load_thread = LoadModDetailsThread(mod_data, cache_dir=cache_dir, parent=None)
        load_thread.details_loaded.connect(update_ui_with_details)
        load_thread.start()

    def cleanup_thread():
        nonlocal load_thread, dialog_closed
        dialog_closed = True
        if load_thread is not None:
            thread_to_cleanup = load_thread
            load_thread = None
            try:
                thread_to_cleanup.blockSignals(True)
                try:
                    thread_to_cleanup.details_loaded.disconnect()
                except (TypeError, RuntimeError):
                    pass
                thread_to_cleanup.blockSignals(False)
            except (TypeError, RuntimeError, AttributeError):
                pass
            try:
                if thread_to_cleanup.isRunning():
                    thread_to_cleanup.requestInterruption()
                    thread_to_cleanup.quit()
                    if not thread_to_cleanup.wait(2000):
                        logging.warning('LoadModDetailsThread: Thread did not stop within 2s timeout, but continuing cleanup')
            except (RuntimeError, AttributeError) as e:
                logging.debug(f'LoadModDetailsThread: Error waiting for thread: {e}')
            try:
                if thread_to_cleanup.isFinished():
                    thread_to_cleanup.deleteLater()
                else:

                    def delayed_cleanup():
                        try:
                            if thread_to_cleanup.isFinished():
                                thread_to_cleanup.deleteLater()
                        except (RuntimeError, AttributeError):
                            pass
                    try:
                        thread_to_cleanup.finished.connect(delayed_cleanup)
                    except (TypeError, RuntimeError):
                        pass
            except (RuntimeError, AttributeError):
                pass

    def on_dialog_close(event):
        cleanup_thread()
        event.accept()
    dialog.closeEvent = on_dialog_close
    if not needs_load:
        key = getattr(mod_data, 'mod_key', None)
        if key and key.startswith('gb_') and hasattr(mod_data, 'full_description') and mod_data.full_description:
            try:
                desc_text.setHtml(mod_data.full_description)
            except Exception as e:
                logging.warning(f'Error setting full_description HTML: {e}')
                desc_text.setPlainText(mod_data.full_description)
        elif hasattr(mod_data, 'description_url') and mod_data.description_url:
            try:
                from utils.network_utils import get_session
                desc_text.setPlainText(tr('status.loading_description'))
                response = get_session().get(mod_data.description_url, timeout=10)
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
