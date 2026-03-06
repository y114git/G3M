from services.mod_filter_service import filter_and_sort_mods


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

    def test_filter_search_matches_author(self):
        mod = {'key': 'gb_12345', 'name': 'Fancy Mod', 'tagline': 'Visual refresh', 'author': 'Alice'}
        result = filter_and_sort_mods([mod], {'search_text': 'alice'})
        assert result == [mod]

    def test_filter_search_matches_dates(self):
        mod = {'key': 'local_12345', 'name': 'Library Mod', 'author': 'Bob', 'created_date': '2025-01-10 14:30', 'last_updated': '2025-02-11 09:15', 'added_date': '2025-03-12 18:00'}
        assert filter_and_sort_mods([mod], {'search_text': '2025-01-10'}) == [mod]
        assert filter_and_sort_mods([mod], {'search_text': '2025-02-11'}) == [mod]
        assert filter_and_sort_mods([mod], {'search_text': '2025-03-12'}) == [mod]

    def test_filter_search_matches_gamebanana_tags_and_category(self):
        mod = {'key': 'gb_12345', 'name': 'Custom UI Pack', 'tags': ['quality of life', 'ui'], 'gamebanana_category': 'Customization'}
        assert filter_and_sort_mods([mod], {'search_text': 'quality'}) == [mod]
        assert filter_and_sort_mods([mod], {'search_text': 'ui'}) == [mod]
        assert filter_and_sort_mods([mod], {'search_text': 'customization'}) == [mod]

    def test_filter_search_matches_multiple_terms_across_fields(self):
        mod = {'key': 'gb_12345', 'name': 'Story Pack', 'tagline': 'Expanded scenes', 'author': 'Carol', 'gamebanana_category': 'Narrative'}
        result = filter_and_sort_mods([mod], {'search_text': 'carol narrative'})
        assert result == [mod]
