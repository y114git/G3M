"""Tests for asynchronous metadata loading functionality."""
import pytest
from unittest.mock import Mock, patch, MagicMock
import time
from concurrent.futures import ThreadPoolExecutor


class TestAsyncMetadataLoader:
    """Test cases for AsyncMetadataLoader."""
    
    def test_load_mods_metadata_async_empty_list(self):
        """Test that empty mod list returns empty results."""
        from utils.async_metadata_loader import AsyncMetadataLoader
        loader = AsyncMetadataLoader()
        results = loader.load_mods_metadata_async([])
        assert results == []
    
    @patch('utils.async_metadata_loader.GameBananaAPI')
    def test_load_mods_metadata_async_success(self, mock_api_class):
        """Test successful async loading of metadata."""
        from utils.async_metadata_loader import AsyncMetadataLoader
        
        # Mock API instance
        mock_api = Mock()
        mock_api_class.return_value = mock_api
        mock_api.get_mod_downloads_only.return_value = 100
        mock_api.get_mod_description_only.return_value = "Test description for mod"
        mock_api.get_mod_category_only.return_value = "Test Category"
        
        loader = AsyncMetadataLoader(max_workers=2, batch_size=2)
        mod_ids = ['12345', '67890']
        
        results = loader.load_mods_metadata_async(mod_ids)
        
        assert len(results) == 2
        assert results[0][0] == '12345'
        assert results[0][1]['downloads'] == 100
        assert results[0][1]['tagline'] == "Test description for mod"
        assert results[0][1]['category'] == "Test Category"
        
        # Verify API was called for each mod
        assert mock_api.get_mod_downloads_only.call_count == 2
        assert mock_api.get_mod_description_only.call_count == 2
        assert mock_api.get_mod_category_only.call_count == 2
    
    @patch('utils.async_metadata_loader.GameBananaAPI')
    def test_load_mods_metadata_async_with_cache(self, mock_api_class):
        """Test async loading with cache hits."""
        from utils.async_metadata_loader import AsyncMetadataLoader
        from adapters.gamebanana_cache import GameBananaMetadataCache
        
        # Mock cache
        mock_cache = Mock()
        mock_cache.is_valid.return_value = True  # All mods are cached
        mock_cache.get_field.side_effect = lambda mod_id, field: {
            ('12345', 'downloads'): 100,
            ('12345', 'tagline'): 'Cached description',
            ('12345', 'category'): 'Cached category',
            ('67890', 'downloads'): 200,
            ('67890', 'tagline'): 'Another cached description',
            ('67890', 'category'): 'Another cached category'
        }.get((mod_id, field))
        
        loader = AsyncMetadataLoader()
        mod_ids = ['12345', '67890']
        
        results = loader.load_mods_metadata_async(mod_ids, metadata_cache=mock_cache)
        
        assert len(results) == 2
        assert results[0][0] == '12345'
        assert results[0][1]['downloads'] == 100
        assert results[0][1]['tagline'] == 'Cached description'
        
        # API should not be called since all data is cached
        mock_api_class.assert_not_called()
    
    @patch('utils.async_metadata_loader.GameBananaAPI')
    def test_load_mods_metadata_async_partial_failure(self, mock_api_class):
        """Test async loading with some failures."""
        from utils.async_metadata_loader import AsyncMetadataLoader
        
        # Mock API with partial failures
        mock_api = Mock()
        mock_api_class.return_value = mock_api
        
        # First mod succeeds, second fails
        def side_effect_mod_downloads(mod_id, external_url=None):
            if mod_id == 12345:
                return 100
            raise Exception("Network error")
        
        def side_effect_mod_description(mod_id, external_url=None):
            if mod_id == 12345:
                return "Success description"
            raise Exception("Network error")
        
        mock_api.get_mod_downloads_only.side_effect = side_effect_mod_downloads
        mock_api.get_mod_description_only.side_effect = side_effect_mod_description
        mock_api.get_mod_category_only.side_effect = side_effect_mod_description
        
        loader = AsyncMetadataLoader(max_workers=2)
        mod_ids = ['12345', '67890']
        
        results = loader.load_mods_metadata_async(mod_ids)
        
        # Should still get one successful result
        assert len(results) == 1
        assert results[0][0] == '12345'
        assert results[0][1]['downloads'] == 100


class TestAsyncGameModsLoader:
    """Test cases for AsyncGameModsLoader."""
    
    def test_load_game_mods_async_empty_pages(self):
        """Test that empty pages list returns empty results."""
        from utils.async_metadata_loader import AsyncGameModsLoader
        loader = AsyncGameModsLoader()
        results = loader.load_game_mods_async('test_game', 12345, [])
        assert results == ([], [])
    
    @patch('utils.async_metadata_loader.GameBananaAPI')
    def test_load_game_mods_async_success(self, mock_api_class):
        """Test successful async loading of game mods."""
        from utils.async_metadata_loader import AsyncGameModsLoader
        from models.mod_models import ModInfo
        
        # Mock API response
        mock_api = Mock()
        mock_api_class.return_value = mock_api
        
        mock_mod = ModInfo(
            key='gb_12345',
            name='Test Mod',
            version='1.0.0',
            author='Test Author',
            tagline='Test tagline',
            game_version='1.0',
            description_url='',
            downloads=100,
            game='deltarune',
            is_verified=False
        )
        
        mock_api.get_game_mods.return_value = ([mock_mod], ['12345'])
        
        loader = AsyncGameModsLoader(max_workers=2)
        pages = [1, 2]
        
        mods, needing_metadata = loader.load_game_mods_async(
            'deltarune', 6755, pages, per_page=20, sort='default'
        )
        
        assert len(mods) == 2  # One mod per page
        assert len(needing_metadata) == 2  # One mod per page needing metadata
        assert mods[0].name == 'Test Mod'
        
        # Verify API was called for each page
        assert mock_api.get_game_mods.call_count == 2
    
    @patch('utils.async_metadata_loader.GameBananaAPI')
    def test_load_game_mods_async_with_failure(self, mock_api_class):
        """Test async loading with API failures."""
        from utils.async_metadata_loader import AsyncGameModsLoader
        
        # Mock API with failure
        mock_api = Mock()
        mock_api_class.return_value = mock_api
        mock_api.get_game_mods.side_effect = Exception("API Error")
        
        loader = AsyncGameModsLoader()
        pages = [1, 2]
        
        mods, needing_metadata = loader.load_game_mods_async(
            'deltarune', 6755, pages, per_page=20
        )
        
        # Should return empty results on failure
        assert mods == []
        assert needing_metadata == []


class TestAsyncIntegration:
    """Integration tests for async loading functionality."""
    
    @patch('utils.async_metadata_loader.GameBananaAPI')
    def test_concurrent_loading_performance(self, mock_api_class):
        """Test that concurrent loading is faster than sequential."""
        from utils.async_metadata_loader import AsyncMetadataLoader, AsyncGameModsLoader
        from models.mod_models import ModInfo
        
        # Mock API with delay to simulate network latency
        mock_api = Mock()
        mock_api_class.return_value = mock_api
        
        def delayed_response(*args, **kwargs):
            time.sleep(0.1)  # 100ms delay per request
            return 100
        
        mock_api.get_mod_downloads_only.side_effect = delayed_response
        mock_api.get_mod_description_only.side_effect = lambda *args, **kwargs: "Test description"
        mock_api.get_mod_category_only.side_effect = lambda *args, **kwargs: "Test category"
        
        # Test async loading
        start_time = time.time()
        loader = AsyncMetadataLoader(max_workers=4, batch_size=4)
        mod_ids = ['12345', '67890', '11111', '22222']
        async_results = loader.load_mods_metadata_async(mod_ids)
        async_time = time.time() - start_time
        
        # Test sequential loading (simulate)
        start_time = time.time()
        sequential_results = []
        for mod_id in mod_ids:
            time.sleep(0.1)  # Simulate sequential delay
            sequential_results.append((mod_id, {
                'downloads': 100,
                'tagline': 'Test description',
                'category': 'Test category'
            }))
        sequential_time = time.time() - start_time
        
        # Async should be significantly faster
        assert async_time < sequential_time * 0.8  # At least 20% faster
        assert len(async_results) == len(sequential_results)
    
    def test_executor_cleanup(self):
        """Test that executors are properly cleaned up."""
        from utils.async_metadata_loader import AsyncMetadataLoader, AsyncGameModsLoader
        
        # Create and destroy loaders
        loader1 = AsyncMetadataLoader()
        loader2 = AsyncGameModsLoader()
        
        # Access executors to verify they exist
        assert hasattr(loader1, 'executor')
        assert hasattr(loader2, 'executor')
        
        # Delete loaders (should trigger cleanup)
        del loader1
        del loader2
        
        # Test passes if no exceptions occur during cleanup
