from typing import List, Dict, Any, Optional, Callable
from managers.mod_manager import parse_mod_date
from utils.gamebanana_api import GameBananaAPI


def _get_mod_attr(mod: Any, attr: str, default: Any = None) -> Any:
    if isinstance(mod, dict):
        return mod.get(attr, default)
    return getattr(mod, attr, default)


def _get_mod_bool_attr(mod: Any, attr: str, default: bool = False) -> bool:
    value = _get_mod_attr(mod, attr, default)
    return value in [True, 'true', 'True', 1] if value else False


def filter_and_sort_mods(mods_list: List[Any], filters: Dict[str, Any], sort_config: Optional[Dict[str, Any]] = None, mod_accessor: Optional[Callable] = None) -> List[Any]:
    if not mods_list:
        return []
    selected_tags = filters.get('tags', [])
    selected_game = filters.get('game') or filters.get('modgame', '')
    search_text = filters.get('search_text', '')
    hide_banned = filters.get('hide_banned', True)
    hide_local = filters.get('hide_local', False)
    show_only_local = filters.get('show_only_local', False)
    hide_mods_without_files = filters.get('hide_mods_without_files', False)
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

        def date_tuple_to_sortable(date_tuple):
            if not date_tuple or date_tuple == (0, 0, 0, 0, 0):
                return 0
            try:
                year, month, day, hour, minute = date_tuple
                return year * 100000000 + month * 1000000 + day * 10000 + hour * 100 + minute
            except (ValueError, TypeError, IndexError):
                return 0

        def get_sort_key(item):
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
                return date_tuple_to_sortable(date_tuple)
            elif sort_type == 2:
                date_str = _get_mod_attr(mod, 'created_date') or _get_mod_attr(mod, 'installed_date') or '0'
                date_tuple = parse_mod_date(date_str)
                return date_tuple_to_sortable(date_tuple)
            return 0
        filtered_list.sort(key=get_sort_key, reverse=reverse)
    return filtered_list
