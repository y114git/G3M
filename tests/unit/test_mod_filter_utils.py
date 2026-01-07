import pytest
from utils.mod_filter_utils import filter_and_sort_mods


class TestModFilterUtils:

    def test_filter_hide_mods_without_files_enabled(self):
        mod_with_files = {'key': 'gb_12345', 'name': 'Mod with Files', 'gamebanana_has_supported_files': True}
        mod_without_files = {'key': 'gb_67890', 'name': 'Mod without Files', 'gamebanana_has_supported_files': False}
        mod_without_attribute = {'key': 'gb_11111', 'name': 'Mod no attr'}
        mods_list = [mod_with_files, mod_without_files, mod_without_attribute]
        filters = {'hide_mods_without_files': True}
        result = filter_and_sort_mods(mods_list, filters)
        assert isinstance(result, list)

    def test_filter_hide_mods_without_files_disabled(self):
        mod_with_files = {'key': 'gb_12345', 'name': 'Mod with Files', 'gamebanana_has_supported_files': True}
        mod_without_files = {'key': 'gb_67890', 'name': 'Mod without Files', 'gamebanana_has_supported_files': False}
        mods_list = [mod_with_files, mod_without_files]
        filters = {'hide_mods_without_files': False}
        result = filter_and_sort_mods(mods_list, filters)
        assert isinstance(result, list)

    def test_filter_empty_list(self):
        result = filter_and_sort_mods([], {'hide_mods_without_files': True})
        assert result == []

    def test_filter_with_mod_accessor(self):
        mod_with_files = {'key': 'gb_12345', 'name': 'Mod with Files', 'gamebanana_has_supported_files': True}
        mod_without_files = {'key': 'gb_67890', 'name': 'Mod without Files', 'gamebanana_has_supported_files': False}
        mods_list = [{'mod': mod_with_files}, {'mod': mod_without_files}]
        filters = {'hide_mods_without_files': False}
        def accessor(item):
            return item.get('mod')
        result = filter_and_sort_mods(mods_list, filters, mod_accessor=accessor)
        assert isinstance(result, list)
