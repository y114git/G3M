"""Utilities for parsing mod config data into model objects."""
import os
from typing import Optional

from models.mod_models import ModExtraFile
from utils.mod_utils import resolve_mod_icon


def parse_extra_files_raw(extra_files_raw, ch_info: dict,
                          chapter_folder: Optional[str] = None,
                          as_dicts: bool = False) -> list:
    """Parse extra_files data from a chapter config into a list.

    Args:
        extra_files_raw: Raw extra_files data (list, dict, or None).
        ch_info: The parent chapter info dict (for 'versions' lookups).
        chapter_folder: If set, resolve relative URLs against this folder.
        as_dicts: If True, return dicts instead of ModExtraFile objects.

    Returns:
        List of ModExtraFile objects (or dicts if as_dicts=True).
    """
    result = []
    if not extra_files_raw:
        return result

    def _make_entry(key: str, version: str, url: str):
        if as_dicts:
            return {'key': key, 'version': version, 'url': url}
        return ModExtraFile(key=key, version=version, url=url)

    if isinstance(extra_files_raw, list):
        for ef_data in extra_files_raw:
            if isinstance(ef_data, dict):
                try:
                    url = ef_data.get('url', '')
                    if url and chapter_folder and not os.path.isabs(url):
                        url = os.path.join(chapter_folder, url)
                    result.append(_make_entry(
                        key=ef_data.get('key', ''),
                        version=ef_data.get('version', '1.0.0'),
                        url=url,
                    ))
                except (KeyError, TypeError, ValueError):
                    pass
            elif isinstance(ef_data, ModExtraFile):
                if as_dicts:
                    result.append({'key': ef_data.key, 'version': ef_data.version, 'url': ef_data.url})
                else:
                    result.append(ef_data)
    elif isinstance(extra_files_raw, dict):
        versions = ch_info.get('versions', {})
        if not isinstance(versions, dict):
            versions = {}
        for group_key, filenames in extra_files_raw.items():
            if isinstance(filenames, list):
                for filename in filenames:
                    url = filename
                    if chapter_folder and filename and not os.path.isabs(filename):
                        url = os.path.join(chapter_folder, filename)
                    result.append(_make_entry(
                        key=group_key,
                        version=versions.get(group_key, '1.0.0'),
                        url=url,
                    ))
    return result


def resolve_data_file_version(ch_info: dict) -> str:
    """Extract the data file version from a chapter info dict."""
    version = ch_info.get('data_file_version')
    if not version and isinstance(ch_info.get('versions'), dict):
        version = ch_info.get('versions', {}).get('data')
    return version or '1.0.0'


def resolve_chapter_folder(file_key: str, mod_folder_path: str, game: str = None) -> Optional[str]:
    """Resolve the chapter subfolder path for a given file_key."""
    if not mod_folder_path:
        return None
    if file_key == 'demo':
        return os.path.join(mod_folder_path, 'demo')
    if file_key == 'undertale':
        return os.path.join(mod_folder_path, 'undertale')
    try:
        from utils.file_utils import get_chapter_folder_name
        chapter_id = int(file_key)
        folder_name = get_chapter_folder_name(chapter_id, game)
        return os.path.join(mod_folder_path, folder_name)
    except (ValueError, TypeError):
        return None


def resolve_local_icon_url(config_data: dict, mod_folder_path: Optional[str]) -> str:
    """Resolve a mod's icon URL from config data and folder path."""
    if not mod_folder_path:
        return config_data.get('icon_url', '')
    icon_url_from_config = config_data.get('icon_url', '')
    icon_url = ''
    if icon_url_from_config and not icon_url_from_config.startswith(('http://', 'https://')):
        if not os.path.isabs(icon_url_from_config):
            resolved = os.path.normpath(os.path.join(mod_folder_path, icon_url_from_config))
            if os.path.exists(resolved) and os.path.isfile(resolved):
                icon_url = resolved
        else:
            icon_url = icon_url_from_config
    if not icon_url:
        resolved_icon = resolve_mod_icon(config_data, mod_folder_path)
        if resolved_icon:
            icon_url = resolved_icon
    return icon_url


def normalize_files_data(files_data: dict) -> dict:
    """Normalize files_data dict for use with ModInfo.from_dict().

    Returns a dict where each chapter's extra_files are list-of-dicts
    and data_file_version is resolved.
    """
    normalized = {}
    for file_key, ch_info in files_data.items():
        if not isinstance(ch_info, dict):
            continue
        extra_files_list = parse_extra_files_raw(
            ch_info.get('extra_files', []),
            ch_info,
            as_dicts=True,
        )
        normalized[file_key] = {
            'description': ch_info.get('description'),
            'data_file_url': ch_info.get('data_file_url'),
            'data_file_version': resolve_data_file_version(ch_info),
            'extra_files': extra_files_list,
        }
    return normalized
