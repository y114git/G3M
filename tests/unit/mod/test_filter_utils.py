"""Unit tests for test filter utils."""

from adapters.gamebanana_adapter import GameBananaAPI
from services.mod.filter_service import filter_and_sort_mods


class TestModFilterUtils:
    """Tests for mod filter utils."""

    def test_filter_empty_list(self):
        """Checks that filtering empty list."""
        result = filter_and_sort_mods([], {})
        assert result == []

    def test_filter_with_mod_accessor(self):
        """Checks that filtering with mod accessor."""
        mod_a = {"id": "gb_mod_12345", "name": "Mod A"}
        mod_b = {"id": "gb_mod_67890", "name": "Mod B"}
        mods_list = [{"mod": mod_a}, {"mod": mod_b}]
        filters = {}

        def accessor(item):
            return item.get("mod")

        result = filter_and_sort_mods(mods_list, filters, mod_accessor=accessor)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_filter_search_matches_author(self):
        """Checks that filtering search matches author."""
        mod = {
            "id": "gb_mod_12345",
            "name": "Fancy Mod",
            "description": "Visual refresh",
            "author": "Alice",
        }
        result = filter_and_sort_mods([mod], {"search_text": "alice"})
        assert result == [mod]

    def test_filter_search_matches_dates(self):
        """Checks that filtering search matches dates."""
        mod = {
            "id": "local_12345",
            "name": "Library Mod",
            "author": "Bob",
            "last_updated": "2025-02-11 09:15",
            "added_date": "2025-03-12 18:00",
        }
        assert filter_and_sort_mods([mod], {"search_text": "2025-02-11"}) == [mod]
        assert filter_and_sort_mods([mod], {"search_text": "2025-03-12"}) == [mod]

    def test_filter_search_matches_gamebanana_tags_and_category(self):
        """Checks that filtering search matches gamebanana tags and category."""
        mod = {
            "id": "gb_mod_12345",
            "name": "Custom UI Pack",
            "tags": ["quality of life", "ui"],
            "gamebanana_category": "Customization",
        }
        assert filter_and_sort_mods([mod], {"search_text": "quality"}) == [mod]
        assert filter_and_sort_mods([mod], {"search_text": "ui"}) == [mod]
        assert filter_and_sort_mods([mod], {"search_text": "customization"}) == [mod]

    def test_filter_search_matches_multiple_terms_across_fields(self):
        """Checks that filtering search matches multiple terms across fields."""
        mod = {
            "id": "gb_mod_12345",
            "name": "Story Pack",
            "description": "Expanded scenes",
            "author": "Carol",
            "gamebanana_category": "Narrative",
        }
        result = filter_and_sort_mods([mod], {"search_text": "carol narrative"})
        assert result == [mod]

    def test_filter_hides_gamebanana_content_rated_mods_by_default(self):
        """Checks that filtering hides gamebanana content rated mods by default."""
        safe_mod = {
            "id": "gb_mod_12345",
            "name": "Safe Mod",
            "_bHasContentRatings": False,
        }
        content_rated_mod = {
            "id": "gb_mod_657995",
            "name": "Roaring Knight: Berserk",
            "_bHasContentRatings": True,
        }
        result = filter_and_sort_mods([safe_mod, content_rated_mod], {})
        assert result == [safe_mod]

    def test_filter_matches_any_selected_tag(self):
        text_mod = {"id": "gb_mod_text", "tags": ["textedit"]}
        gameplay_mod = {"id": "gb_mod_gameplay", "tags": ["gameplay"]}
        other_mod = {"id": "gb_mod_other", "tags": ["other"]}

        result = filter_and_sort_mods(
            [text_mod, gameplay_mod, other_mod],
            {"tags": ["textedit", "gameplay"]},
        )

        assert result == [text_mod, gameplay_mod]

    def test_gamebanana_categories_map_to_the_browser_tags(self):
        categories = {
            "Translations": "textedit",
            "Difficulty Changes": "gameplay",
            "Full Game Edits": "gameplay",
            "New Movesets": "gameplay",
            "Custom Guards": "customization",
            "Custom Office": "customization",
            "Animatronic Skins": "customization",
            "Textures": "other",
            "Texts": "textedit",
            "Other/Misc": "other",
            "CYOP/AFOM": "CYOP/AFOM",
        }

        assert {
            category: GameBananaAPI.category_to_tag(category) for category in categories
        } == categories
