"""Mod filtering and sorting utilities."""
from typing import List, Dict, Any, Optional, Callable
from services.mod_service import parse_mod_date
from services.blocklist_service import BlocklistManager
from adapters.gamebanana_adapter import GameBananaAPI
_TRUE_VALUES = (True, 'true', 'True', 1)


def _get_mod_attr(mod: Any, attr: str, default: Any = None) -> Any:
    return mod.get(attr, default) if isinstance(mod, dict) else getattr(mod, attr, default)


def _get_mod_bool_attr(mod: Any, attr: str, default: bool = False) -> bool:
    value = _get_mod_attr(mod, attr, default)
    return value in _TRUE_VALUES if value else False


def _date_tuple_to_sortable(date_tuple) -> int:
    if not date_tuple or date_tuple == (0, 0, 0, 0, 0):
        return 0
    try:
        y, m, d, h, mi = date_tuple
        return y * 100000000 + m * 1000000 + d * 10000 + h * 100 + mi
    except (ValueError, TypeError, IndexError):
        return 0


def filter_and_sort_mods(mods_list: List[Any], filters: Dict[str, Any], sort_config: Optional[Dict[str, Any]] = None, mod_accessor: Optional[Callable] = None, blocklist_service: Optional[BlocklistManager] = None, installed_mod_keys: Optional[set] = None) -> List[Any]:
    if not mods_list:
        return []
    selected_tags, selected_game = filters.get('tags', []), filters.get('game') or filters.get('modgame', '')
    search_text, hide_banned = filters.get('search_text', ''), filters.get('hide_banned', True)
    only_gamebanana, status_filter = filters.get('only_gamebanana', False), filters.get('status_filter', ['approved', 'pending'])
    exclude_installed = filters.get('exclude_installed', False)
    filtered_list = []
    for item in mods_list:
        mod = mod_accessor(item) if mod_accessor else item
        if hide_banned and _get_mod_bool_attr(mod, 'ban_status'):
            continue
        if not isinstance(mod, dict) and _get_mod_bool_attr(mod, 'hide_mod'):
            continue
        key = _get_mod_attr(mod, 'key') or _get_mod_attr(mod, 'mod_key')
        is_gb = bool(key and isinstance(key, str) and key.startswith('gb_'))
        if only_gamebanana and not is_gb:
            continue
        if exclude_installed and installed_mod_keys and key in installed_mod_keys:
            continue
        if _get_mod_attr(mod, 'status', 'approved') not in status_filter:
            continue
        if blocklist_service and selected_game and blocklist_service.is_mod_blocklisted(mod, selected_game):
            continue
        if selected_tags:
            mod_tags = list(_get_mod_attr(mod, 'tags') or [])
            if is_gb and (cat := _get_mod_attr(mod, 'gamebanana_category')) and (cat_tag := GameBananaAPI.category_to_tag(cat)) and cat_tag not in mod_tags:
                mod_tags.append(cat_tag)
            if not all(tag in mod_tags for tag in selected_tags):
                continue
        if selected_game and (_get_mod_attr(mod, 'game') or _get_mod_attr(mod, 'modgame', 'deltarune')) != selected_game:
            continue
        if search_text:
            stl = search_text.lower()
            if stl not in _get_mod_attr(mod, 'name', '').lower() and stl not in _get_mod_attr(mod, 'tagline', '').lower():
                continue
        filtered_list.append(item)
    if sort_config:
        sort_type, reverse = sort_config.get('sort_type', 0), sort_config.get('reverse', False)

        def get_sort_key(item):
            mod = mod_accessor(item) if mod_accessor else item
            if sort_type == 0:
                try:
                    return int(_get_mod_attr(mod, 'downloads', 0) or 0)
                except (ValueError, TypeError):
                    return 0
            date_str = (_get_mod_attr(mod, 'last_updated') or _get_mod_attr(mod, 'updated_date') or '0') if sort_type == 1 else (_get_mod_attr(mod, 'created_date') or _get_mod_attr(mod, 'added_date') or '0')
            return _date_tuple_to_sortable(parse_mod_date(date_str))
        filtered_list.sort(key=get_sort_key, reverse=reverse)
    return filtered_list
