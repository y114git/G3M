"""Mod filtering and sorting utilities.

This module provides utilities for filtering and sorting mod lists based on various criteria.
"""
from typing import List, Dict, Any, Optional, Callable
from services.mod_service import parse_mod_date
from services.blocklist_service import BlocklistManager
from adapters.gamebanana_adapter import GameBananaAPI
_TRUE_VALUES = (True, 'true', 'True', 1)


def _get_mod_attr(mod: Any, attr: str, default: Any = None) -> Any:
    """Get an attribute from a mod (dict or object).

    Args:
        mod: Mod data (dict or object).
        attr: Attribute name to retrieve.
        default: Default value if attribute not found.

    Returns:
        Any: Attribute value or default.
    """
    if isinstance(mod, dict):
        return mod.get(attr, default)
    return getattr(mod, attr, default)


def _get_mod_bool_attr(mod: Any, attr: str, default: bool = False) -> bool:
    """Get a boolean attribute from a mod.

    Args:
        mod: Mod data (dict or object).
        attr: Attribute name to retrieve.
        default: Default value if attribute not found.

    Returns:
        bool: Boolean value of the attribute.
    """
    value = _get_mod_attr(mod, attr, default)
    return value in _TRUE_VALUES if value else False


def _date_tuple_to_sortable(date_tuple) -> int:
    """Convert a date tuple to a sortable integer.

    Args:
        date_tuple: Tuple of (year, month, day, hour, minute).

    Returns:
        int: Sortable integer representation of the date.
    """
    if not date_tuple or date_tuple == (0, 0, 0, 0, 0):
        return 0
    try:
        year, month, day, hour, minute = date_tuple
        return year * 100000000 + month * 1000000 + day * 10000 + hour * 100 + minute
    except (ValueError, TypeError, IndexError):
        return 0


def filter_and_sort_mods(mods_list: List[Any], filters: Dict[str, Any], sort_config: Optional[Dict[str, Any]] = None, mod_accessor: Optional[Callable] = None, blocklist_service: Optional[BlocklistManager] = None) -> List[Any]:
    """Filter and sort a list of mods based on criteria.

    Args:
        mods_list: List of mods to filter and sort.
        filters: Dictionary of filter criteria (tags, game, search_text, etc.).
        sort_config: Optional sorting configuration (sort_type, reverse).
        mod_accessor: Optional function to extract mod from list items.
        blocklist_service: Optional blocklist manager for filtering.

    Returns:
        List[Any]: Filtered and sorted list of mods.
    """
    if not mods_list:
        return []
    selected_tags = filters.get('tags', [])
    selected_game = filters.get('game') or filters.get('modgame', '')
    search_text = filters.get('search_text', '')
    hide_banned = filters.get('hide_banned', True)
    hide_local = filters.get('hide_local', False)
    show_only_local = filters.get('show_only_local', False)
    status_filter = filters.get('status_filter', ['approved', 'pending'])
    filtered_list = []
    for item in mods_list:
        mod = mod_accessor(item) if mod_accessor else item
        if hide_banned and _get_mod_bool_attr(mod, 'ban_status'):
            continue
        if isinstance(mod, dict):
            if hide_local and _get_mod_attr(mod, 'is_local_mod', False):
                continue
            if show_only_local and (not _get_mod_attr(mod, 'is_local_mod', False)):
                continue
        else:
            if _get_mod_bool_attr(mod, 'hide_mod'):
                continue
            if hide_local and _get_mod_attr(mod, 'is_local_mod', False):
                continue
            if show_only_local and (not _get_mod_attr(mod, 'is_local_mod', False)):
                continue
        mod_status = _get_mod_attr(mod, 'status', 'approved')
        if mod_status not in status_filter:
            continue
        if blocklist_service and selected_game:
            if blocklist_service.is_mod_blocklisted(mod, selected_game):
                continue
        if selected_tags:
            mod_tags = _get_mod_attr(mod, 'tags', []) or []
            if not isinstance(mod_tags, list):
                mod_tags = []
            if isinstance(mod, dict) and _get_mod_attr(mod, 'is_local_mod') and ('local' not in mod_tags):
                mod_tags = mod_tags.copy() if isinstance(mod_tags, list) else []
                mod_tags.append('local')
            key = _get_mod_attr(mod, 'key', None) or _get_mod_attr(mod, 'mod_key', None)
            is_gamebanana_mod = bool(key and isinstance(key, str) and key.startswith('gb_'))
            if is_gamebanana_mod:
                gamebanana_category = _get_mod_attr(mod, 'gamebanana_category')
                if gamebanana_category:
                    category_tag = GameBananaAPI.category_to_tag(gamebanana_category)
                    if category_tag and category_tag not in mod_tags:
                        if not isinstance(mod_tags, list):
                            mod_tags = []
                        mod_tags = mod_tags.copy() if isinstance(mod_tags, list) else []
                        mod_tags.append(category_tag)
            if not isinstance(mod_tags, list):
                mod_tags = []
            if not all((tag in mod_tags for tag in selected_tags)):
                continue
        if selected_game:
            mod_game = _get_mod_attr(mod, 'game', None) or _get_mod_attr(mod, 'modgame', 'deltarune')
            if mod_game != selected_game:
                continue
        if search_text:
            search_text_lower = search_text.lower()
            mod_name_lower = _get_mod_attr(mod, 'name', '').lower()
            mod_tagline_lower = _get_mod_attr(mod, 'tagline', '').lower()
            if search_text_lower not in mod_name_lower and search_text_lower not in mod_tagline_lower:
                continue
        filtered_list.append(item)
    if sort_config:
        sort_type = sort_config.get('sort_type', 0)
        reverse = sort_config.get('reverse', False)

        def get_sort_key(item):
            """Generate sort key for mod items based on sort configuration.

            This inner function creates a sort key for mod items based on the
            configured sort type (downloads, last updated, or created date).

            Args:
                item: Mod item to generate sort key for.

            Sort types:
            - 0: Downloads count (numeric)
            - 1: Last updated date
            - 2: Created/installed date

            Returns:
                Sortable value appropriate for the selected sort type.
                Returns 0 as fallback for invalid data.
            """
            mod = mod_accessor(item) if mod_accessor else item
            if sort_type == 0:
                downloads = _get_mod_attr(mod, 'downloads', None)
                if downloads is None:
                    downloads = 0
                try:
                    downloads_int = int(downloads) if downloads is not None else 0
                except (ValueError, TypeError):
                    downloads_int = 0
                return downloads_int
            elif sort_type == 1:
                date_str = _get_mod_attr(mod, 'last_updated') or _get_mod_attr(mod, 'updated_date') or '0'
                date_tuple = parse_mod_date(date_str)
                return _date_tuple_to_sortable(date_tuple)
            elif sort_type == 2:
                date_str = _get_mod_attr(mod, 'created_date') or _get_mod_attr(mod, 'installed_date') or '0'
                date_tuple = parse_mod_date(date_str)
                return _date_tuple_to_sortable(date_tuple)
            return 0
        filtered_list.sort(key=get_sort_key, reverse=reverse)
    return filtered_list
