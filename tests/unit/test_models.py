from models.mod_models import ModInfo, ModChapterData


class TestModInfo:

    def test_mod_info_creation(self):
        mod_info = ModInfo(key='test_mod', name='Test Mod', version='1.0.0', author='Test Author', tagline='Test tagline', game_version='1.0.0', description_url='', downloads=0, game='deltarune', is_verified=False)
        assert mod_info.key == 'test_mod'
        assert mod_info.name == 'Test Mod'
        assert mod_info.version == '1.0.0'
        assert mod_info.author == 'Test Author'

    def test_mod_info_from_dict(self):
        mod_data = {'key': 'test_mod_002', 'name': 'Test Mod 2', 'version': '2.0.0', 'author': 'Test Author', 'tagline': 'Test tagline', 'game_version': '1.0.0', 'description_url': '', 'downloads': 0, 'game': 'deltarune', 'is_verified': False}
        mod_info = ModInfo.from_dict(mod_data)
        assert mod_info.key == 'test_mod_002'
        assert mod_info.name == 'Test Mod 2'
        assert mod_info.version == '2.0.0'


class TestModChapterData:

    def test_mod_chapter_data_creation(self):
        from models.mod_models import ModExtraFile
        extra_file1 = ModExtraFile(key='file1', version='1.0.0', url='file1.txt')
        extra_file2 = ModExtraFile(key='file2', version='1.0.0', url='file2.txt')
        chapter_data = ModChapterData(description='Test chapter', data_file_url='data.win', data_file_version='1.0.0', extra_files=[extra_file1, extra_file2])
        assert chapter_data.description == 'Test chapter'
        assert chapter_data.data_file_url == 'data.win'
        assert len(chapter_data.extra_files) == 2
        assert chapter_data.extra_files[0].key == 'file1'


class TestGameModes:

    def test_full_game_mode(self):
        from models.game_modes import FullGameMode
        mode = FullGameMode()
        assert mode is not None
        assert hasattr(mode, 'get_chapter_id')
        assert hasattr(mode, 'filter_mods_for_ui')
        assert mode.steam_id is not None

    def test_demo_game_mode(self):
        from models.game_modes import DemoGameMode
        mode = DemoGameMode()
        assert mode is not None

    def test_undertale_game_mode(self):
        from models.game_modes import UndertaleGameMode
        mode = UndertaleGameMode()
        assert mode is not None

    def test_undertale_yellow_game_mode(self):
        from models.game_modes import UndertaleYellowGameMode
        mode = UndertaleYellowGameMode()
        assert mode is not None

    def test_pizza_tower_game_mode(self):
        from models.game_modes import PizzaTowerGameMode
        mode = PizzaTowerGameMode()
        assert mode is not None
        assert hasattr(mode, 'get_chapter_id')
        assert hasattr(mode, 'filter_mods_for_ui')
        assert mode.steam_id is not None
        assert mode.direct_launch_allowed is True

    def test_sugary_spire_game_mode(self):
        from models.game_modes import SugarySpireGameMode
        mode = SugarySpireGameMode()
        assert mode is not None
        assert hasattr(mode, 'get_chapter_id')
        assert hasattr(mode, 'filter_mods_for_ui')
        assert mode.direct_launch_allowed is True
