"""Mod filtering and sorting utilities."""
from services.mod_service import parse_mod_date
from adapters.gamebanana_adapter import GameBananaAPI
_TRUE_VALUES = (True, 'true', 'True', 1)


def _get_mod_attr(mod, attr, default=None): return mod.get(attr, default) if isinstance(mod, dict) else getattr(mod, attr, default)


def _get_mod_bool_attr(mod, attr, default=False):
    v = _get_mod_attr(mod, attr, default)
    return v in _TRUE_VALUES if v else False


def _date_tuple_to_sortable(dt) -> int:
    if not dt or dt == (0, 0, 0, 0, 0):
        return 0
    try:
        return dt[0] * 100000000 + dt[1] * 1000000 + dt[2] * 10000 + dt[3] * 100 + dt[4]
    except (ValueError, TypeError, IndexError):
        return 0


def filter_and_sort_mods(mods_list, filters, sort_config=None, mod_accessor=None, blocklist_service=None, installed_mod_keys=None):
    if not mods_list:
        return []
    selected_tags, selected_game = filters.get('tags', []), filters.get('game') or filters.get('modgame', '')
    search_text, hide_banned = filters.get('search_text', ''), filters.get('hide_banned', True)
    only_gamebanana, status_filter = filters.get('only_gamebanana', False), filters.get('status_filter', ['approved', 'pending'])
    exclude_installed = filters.get('exclude_installed', False)
    hide_local = filters.get('hide_local', False)
    hide_wips_without_downloads = filters.get('hide_wips_without_downloads', False)
    filtered_list = []
    for item in mods_list:
        mod = mod_accessor(item) if mod_accessor else item
        if hide_banned and _get_mod_bool_attr(mod, 'ban_status'):
            continue
        if not isinstance(mod, dict) and _get_mod_bool_attr(mod, 'hide_mod'):
            continue
        key = _get_mod_attr(mod, 'key') or _get_mod_attr(mod, 'mod_key')
        if hide_local and key and isinstance(key, str) and key.startswith('local_'):
            continue
        is_gb = bool(key and isinstance(key, str) and key.startswith('gb_'))
        if hide_wips_without_downloads and is_gb and (_get_mod_bool_attr(mod, 'is_wip') or _get_mod_attr(mod, 'gamebanana_category') == 'Work In Progress'):
            try:
                if not int(_get_mod_attr(mod, 'downloads') or 0):
                    continue
            except (ValueError, TypeError):
                continue
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
        if search_text and (stl := search_text.lower()) not in (_get_mod_attr(mod, 'name', '') or '').lower() and stl not in (_get_mod_attr(mod, 'tagline', '') or '').lower():
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
