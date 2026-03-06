"""Mod filtering and sorting utilities."""
from services.mod_service import parse_mod_date
from adapters.gamebanana_adapter import GameBananaAPI
_TRUE_VALUES = (True, 'true', 'True', 1)


def _get_mod_attr(mod, attr, default=None): return mod.get(attr, default) if isinstance(mod, dict) else getattr(mod, attr, default)


def _get_mod_tags(mod, is_gamebanana: bool = False):
    raw_tags = _get_mod_attr(mod, 'tags') or []
    if isinstance(raw_tags, str):
        tags = [raw_tags]
    elif isinstance(raw_tags, (list, tuple, set)):
        tags = [tag for tag in raw_tags if tag]
    else:
        tags = []
    category = _get_mod_attr(mod, 'gamebanana_category') or _get_mod_attr(mod, 'category')
    if is_gamebanana and category:
        category_tag = GameBananaAPI.category_to_tag(category)
        if category_tag and category_tag not in tags:
            tags.append(category_tag)
    return [str(tag).strip() for tag in tags if str(tag).strip()]


def _build_searchable_text(mod, is_gamebanana: bool = False) -> str:
    search_values = [
        _get_mod_attr(mod, 'name', ''),
        _get_mod_attr(mod, 'tagline', ''),
        _get_mod_attr(mod, 'author', ''),
        _get_mod_attr(mod, 'created_date', ''),
        _get_mod_attr(mod, 'last_updated', ''),
        _get_mod_attr(mod, 'updated_date', ''),
        _get_mod_attr(mod, 'added_date', ''),
        _get_mod_attr(mod, 'gamebanana_category', ''),
        _get_mod_attr(mod, 'category', ''),
    ]
    search_values.extend(_get_mod_tags(mod, is_gamebanana))
    return ' '.join(str(value).strip() for value in search_values if value).casefold()


def _get_mod_bool_attr(mod, attr, default=False):
    v = _get_mod_attr(mod, attr, default)
    return v in _TRUE_VALUES if v else False


def _get_mod_key(mod):
    return _get_mod_attr(mod, 'key') or _get_mod_attr(mod, 'mod_key')


def _is_prefixed_key(key, prefix: str) -> bool:
    return isinstance(key, str) and key.startswith(prefix)


def _int_value(value, default=0):
    try:
        return int(value or 0)
    except (ValueError, TypeError):
        return default


def _sort_date_value(mod, sort_type: int) -> int:
    if sort_type == 1:
        date_str = _get_mod_attr(mod, 'last_updated') or _get_mod_attr(mod, 'updated_date') or '0'
    else:
        date_str = _get_mod_attr(mod, 'created_date') or _get_mod_attr(mod, 'added_date') or '0'
    return _date_tuple_to_sortable(parse_mod_date(date_str))


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
    search_terms = [term for term in str(search_text).casefold().split() if term]
    installed_keys = set(installed_mod_keys or ())
    filtered_list = []
    for item in mods_list:
        mod = mod_accessor(item) if mod_accessor else item
        if hide_banned and _get_mod_bool_attr(mod, 'ban_status'):
            continue
        if not isinstance(mod, dict) and _get_mod_bool_attr(mod, 'hide_mod'):
            continue
        key = _get_mod_key(mod)
        if hide_local and _is_prefixed_key(key, 'local_'):
            continue
        is_gb = _is_prefixed_key(key, 'gb_')
        if hide_wips_without_downloads and is_gb and (_get_mod_bool_attr(mod, 'is_wip') or _get_mod_attr(mod, 'gamebanana_category') == 'Work In Progress'):
            if not _int_value(_get_mod_attr(mod, 'downloads')):
                continue
        if only_gamebanana and not is_gb:
            continue
        if exclude_installed and key in installed_keys:
            continue
        if _get_mod_attr(mod, 'status', 'approved') not in status_filter:
            continue
        if blocklist_service and selected_game and blocklist_service.is_mod_blocklisted(mod, selected_game):
            continue
        if selected_tags:
            mod_tags = _get_mod_tags(mod, is_gb)
            if not all(tag in mod_tags for tag in selected_tags):
                continue
        if selected_game and (_get_mod_attr(mod, 'game') or _get_mod_attr(mod, 'modgame', 'deltarune')) != selected_game:
            continue
        if search_terms:
            searchable_text = _build_searchable_text(mod, is_gb)
            if not all(term in searchable_text for term in search_terms):
                continue
        filtered_list.append(item)
    if sort_config:
        sort_type, reverse = sort_config.get('sort_type', 0), sort_config.get('reverse', False)

        def get_sort_key(item):
            mod = mod_accessor(item) if mod_accessor else item
            if sort_type == 0:
                return _int_value(_get_mod_attr(mod, 'downloads', 0))
            return _sort_date_value(mod, sort_type)
        filtered_list.sort(key=get_sort_key, reverse=reverse)
    return filtered_list
