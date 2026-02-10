import pytest
from models.mod_models import ModInfo, ModFileData, ModExtraFile
from models.game_modes import (
    GameDefinition, GameTab, DeltaruneGame, DeltaruneDemoGame,
    UndertaleGame, UndertaleYellowGame, PizzaTowerGame, SugarySpireGame,
    GAME_REGISTRY, get_game, get_all_games,
)


# =========================================================================
# ModInfo tests
# =========================================================================

class TestModInfo:

    def test_creation_minimal(self):
        mod = ModInfo(key='k', name='N', version='1.0', author='A', tagline='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarune', is_verified=False)
        assert mod.key == 'k'
        assert mod.name == 'N'
        assert mod.game == 'deltarune'

    def test_from_dict_basic(self):
        data = {'key': 'mod_a', 'name': 'Mod A', 'version': '2.0', 'author': 'Auth',
                'tagline': 'Tag', 'game_version': '1.0', 'description_url': '',
                'downloads': 5, 'game': 'deltarune', 'is_verified': True}
        mod = ModInfo.from_dict(data)
        assert mod.key == 'mod_a'
        assert mod.version == '2.0'
        assert mod.downloads == 5
        assert mod.is_verified is True

    def test_from_dict_defaults(self):
        mod = ModInfo.from_dict({})
        assert mod.key == ''
        assert mod.game == 'deltarune'
        assert mod.is_verified is False

    def test_from_dict_with_files(self):
        data = {
            'key': 'mod_f', 'name': 'F', 'version': '1.0', 'author': 'A',
            'tagline': 'T', 'game_version': '1.0', 'description_url': '',
            'downloads': 0, 'game': 'deltarune', 'is_verified': False,
            'files': {
                '1': {'data_file_url': 'http://example.com/data.win', 'data_file_version': '1.0'},
                '2': {'data_file_url': 'http://example.com/ch2.win'},
            }
        }
        mod = ModInfo.from_dict(data)
        assert '1' in mod.files
        assert '2' in mod.files
        assert isinstance(mod.files['1'], ModFileData)
        assert mod.files['1'].data_file_url == 'http://example.com/data.win'

    def test_from_dict_with_extra_files(self):
        data = {
            'key': 'mod_e', 'name': 'E', 'version': '1.0', 'author': 'A',
            'tagline': 'T', 'game_version': '1.0', 'description_url': '',
            'downloads': 0, 'game': 'deltarune', 'is_verified': False,
            'files': {
                '0': {
                    'data_file_url': 'http://example.com/data.win',
                    'extra_files': [
                        {'key': 'music', 'version': '1.0', 'url': 'http://example.com/music.zip'},
                    ]
                }
            }
        }
        mod = ModInfo.from_dict(data)
        assert len(mod.files['0'].extra_files) == 1
        assert isinstance(mod.files['0'].extra_files[0], ModExtraFile)
        assert mod.files['0'].extra_files[0].key == 'music'

    def test_get_file_data_direct(self):
        mod = ModInfo(key='k', name='N', version='1.0', author='A', tagline='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarune', is_verified=False,
                      files={'1': ModFileData(data_file_url='url1')})
        assert mod.get_file_data('1') is not None
        assert mod.get_file_data('1').data_file_url == 'url1'
        assert mod.get_file_data('nonexistent') is None

    def test_get_chapter_data_deltarune(self):
        mod = ModInfo(key='k', name='N', version='1.0', author='A', tagline='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarune', is_verified=False,
                      files={
                          '0': ModFileData(data_file_url='menu_url'),
                          '1': ModFileData(data_file_url='ch1_url'),
                          '2': ModFileData(data_file_url='ch2_url'),
                      })
        assert mod.get_chapter_data(0).data_file_url == 'menu_url'
        assert mod.get_chapter_data(1).data_file_url == 'ch1_url'
        assert mod.get_chapter_data(2).data_file_url == 'ch2_url'
        assert mod.get_chapter_data(3) is None

    def test_get_chapter_data_undertale(self):
        """Undertale mods use 'undertale' key, accessed via tab_id=0."""
        mod = ModInfo(key='k', name='N', version='1.0', author='A', tagline='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='undertale', is_verified=False,
                      files={'undertale': ModFileData(data_file_url='ut_url')})
        result = mod.get_chapter_data(0)
        assert result is not None
        assert result.data_file_url == 'ut_url'

    def test_get_chapter_data_demo(self):
        mod = ModInfo(key='k', name='N', version='1.0', author='A', tagline='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarunedemo', is_verified=False,
                      files={'demo': ModFileData(data_file_url='demo_url')})
        result = mod.get_chapter_data(-1)
        assert result is not None
        assert result.data_file_url == 'demo_url'

    def test_is_valid_for_demo(self):
        mod = ModInfo(key='k', name='N', version='1.0', author='A', tagline='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarunedemo', is_verified=False,
                      files={'demo': ModFileData(data_file_url='url')})
        assert mod.is_valid_for_demo() is True

    def test_is_valid_for_demo_wrong_game(self):
        mod = ModInfo(key='k', name='N', version='1.0', author='A', tagline='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarune', is_verified=False,
                      files={'demo': ModFileData(data_file_url='url')})
        assert mod.is_valid_for_demo() is False

    def test_is_gamebanana_mod(self):
        mod = ModInfo(key='gb_12345', name='N', version='1.0', author='A', tagline='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarune', is_verified=False)
        assert mod.is_gamebanana_mod() is True
        assert mod.get_gamebanana_mod_id() == '12345'

    def test_is_not_gamebanana_mod(self):
        mod = ModInfo(key='local_mod', name='N', version='1.0', author='A', tagline='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarune', is_verified=False)
        assert mod.is_gamebanana_mod() is False
        assert mod.get_gamebanana_mod_id() is None


# =========================================================================
# ModFileData tests
# =========================================================================

class TestModFileData:

    def test_creation(self):
        fd = ModFileData(description='Test', data_file_url='data.win', data_file_version='1.0')
        assert fd.description == 'Test'
        assert fd.data_file_url == 'data.win'
        assert fd.data_file_version == '1.0'
        assert fd.extra_files == []

    def test_with_extra_files(self):
        ef1 = ModExtraFile(key='f1', version='1.0', url='f1.zip')
        ef2 = ModExtraFile(key='f2', version='2.0', url='f2.zip')
        fd = ModFileData(extra_files=[ef1, ef2])
        assert len(fd.extra_files) == 2
        assert fd.extra_files[0].key == 'f1'

    def test_is_valid_with_url(self):
        assert ModFileData(data_file_url='url').is_valid() is True

    def test_is_valid_with_extra_files(self):
        assert ModFileData(extra_files=[ModExtraFile(key='k', version='v', url='u')]).is_valid() is True

    def test_is_valid_empty(self):
        assert ModFileData().is_valid() is False


# =========================================================================
# GameTab tests
# =========================================================================

class TestGameTab:

    def test_creation(self):
        tab = GameTab(tab_id=1, files_key='1', name_key='tabs.chapter_1')
        assert tab.tab_id == 1
        assert tab.files_key == '1'
        assert tab.name_key == 'tabs.chapter_1'
        assert tab.direct_launch is True

    def test_frozen(self):
        tab = GameTab(tab_id=0, files_key='0', name_key='tabs.menu')
        with pytest.raises(AttributeError):
            tab.tab_id = 5

    def test_no_direct_launch(self):
        tab = GameTab(tab_id=-1, files_key='demo', name_key='tabs.demo', direct_launch=False)
        assert tab.direct_launch is False


# =========================================================================
# GameDefinition base class tests
# =========================================================================

class TestGameDefinition:

    def test_base_has_defaults(self):
        gd = GameDefinition()
        assert gd.game_id == ''
        assert gd.tabs == []
        assert gd.is_multi_tab is False
        assert gd.supports_full_install is False
        assert gd.block_steam_with_direct_launch is False

    def test_get_tab_returns_none_for_empty(self):
        gd = GameDefinition()
        assert gd.get_tab(0) is None
        assert gd.get_tab_by_index(0) is None

    def test_get_chapter_id_returns_0_for_empty(self):
        gd = GameDefinition()
        assert gd.get_chapter_id(0) == 0


# =========================================================================
# Concrete game definition tests
# =========================================================================

class TestDeltaruneGame:

    def test_basic_properties(self):
        g = DeltaruneGame()
        assert g.game_id == 'deltarune'
        assert g.steam_app_id != ''
        assert g.path_config_key == 'game_path'
        assert g.block_steam_with_direct_launch is True
        assert g.supports_full_install is False

    def test_has_5_tabs(self):
        g = DeltaruneGame()
        assert len(g.tabs) == 5
        assert g.is_multi_tab is True
        assert g.tabs[0].files_key == '0'
        assert g.tabs[1].files_key == '1'
        assert g.tabs[4].files_key == '4'

    def test_get_tab_by_id(self):
        g = DeltaruneGame()
        assert g.get_tab(0).files_key == '0'
        assert g.get_tab(3).files_key == '3'
        assert g.get_tab(99) is None

    def test_get_chapter_id(self):
        g = DeltaruneGame()
        for i in range(5):
            assert g.get_chapter_id(i) == i

    def test_direct_launch_allowed(self):
        g = DeltaruneGame()
        assert g.direct_launch_allowed is True

    def test_steam_app_id(self):
        g = DeltaruneGame()
        assert g.steam_app_id != ''

    def test_filter_mods_for_ui(self):
        g = DeltaruneGame()
        mod1 = ModInfo(key='m1', name='M1', version='1.0', author='A', tagline='T',
                       game_version='1.0', description_url='', downloads=0,
                       game='deltarune', is_verified=False,
                       files={'1': ModFileData(data_file_url='url')})
        mod2 = ModInfo(key='m2', name='M2', version='1.0', author='A', tagline='T',
                       game_version='1.0', description_url='', downloads=0,
                       game='undertale', is_verified=False,
                       files={'undertale': ModFileData(data_file_url='url')})
        result = g.filter_mods_for_ui([mod1, mod2])
        assert len(result) == 5
        assert mod1 in result[1]
        assert mod2 not in result[1]

    def test_filter_hidden_mods_excluded(self):
        g = DeltaruneGame()
        hidden = ModInfo(key='h', name='H', version='1.0', author='A', tagline='T',
                         game_version='1.0', description_url='', downloads=0,
                         game='deltarune', is_verified=False, hide_mod=True,
                         files={'0': ModFileData(data_file_url='url')})
        result = g.filter_mods_for_ui([hidden])
        assert hidden not in result[0]

    def test_filter_banned_mods_excluded(self):
        g = DeltaruneGame()
        banned = ModInfo(key='b', name='B', version='1.0', author='A', tagline='T',
                         game_version='1.0', description_url='', downloads=0,
                         game='deltarune', is_verified=False, ban_status=True,
                         files={'0': ModFileData(data_file_url='url')})
        result = g.filter_mods_for_ui([banned])
        assert banned not in result[0]


class TestDeltaruneDemoGame:

    def test_basic_properties(self):
        g = DeltaruneDemoGame()
        assert g.game_id == 'deltarunedemo'
        assert g.supports_full_install is True
        assert len(g.tabs) == 1
        assert g.is_multi_tab is False
        assert g.tabs[0].direct_launch is False

    def test_direct_launch_not_allowed(self):
        g = DeltaruneDemoGame()
        assert g.direct_launch_allowed is False

    def test_filter_mods_demo(self):
        g = DeltaruneDemoGame()
        valid_demo = ModInfo(key='d1', name='D1', version='1.0', author='A', tagline='T',
                             game_version='1.0', description_url='', downloads=0,
                             game='deltarunedemo', is_verified=False,
                             files={'demo': ModFileData(data_file_url='url')})
        wrong_game = ModInfo(key='d2', name='D2', version='1.0', author='A', tagline='T',
                             game_version='1.0', description_url='', downloads=0,
                             game='deltarune', is_verified=False,
                             files={'demo': ModFileData(data_file_url='url')})
        result = g.filter_mods_for_ui([valid_demo, wrong_game])
        assert valid_demo in result[0]
        assert wrong_game not in result[0]


class TestUndertaleGame:

    def test_basic_properties(self):
        g = UndertaleGame()
        assert g.game_id == 'undertale'
        assert g.steam_app_id != ''
        assert len(g.tabs) == 1
        assert g.is_multi_tab is False
        assert g.tabs[0].files_key == 'undertale'

    def test_filter_mods(self):
        g = UndertaleGame()
        ut_mod = ModInfo(key='u1', name='U1', version='1.0', author='A', tagline='T',
                         game_version='1.0', description_url='', downloads=0,
                         game='undertale', is_verified=False,
                         files={'undertale': ModFileData(data_file_url='url')})
        dr_mod = ModInfo(key='d1', name='D1', version='1.0', author='A', tagline='T',
                         game_version='1.0', description_url='', downloads=0,
                         game='deltarune', is_verified=False,
                         files={'1': ModFileData(data_file_url='url')})
        result = g.filter_mods_for_ui([ut_mod, dr_mod])
        assert ut_mod in result[0]
        assert dr_mod not in result[0]


class TestUndertaleYellowGame:

    def test_basic_properties(self):
        g = UndertaleYellowGame()
        assert g.game_id == 'undertaleyellow'
        assert g.supports_full_install is True
        assert g.steam_app_id == ''
        assert g.tabs[0].files_key == 'undertale'


class TestPizzaTowerGame:

    def test_basic_properties(self):
        g = PizzaTowerGame()
        assert g.game_id == 'pizzatower'
        assert g.steam_app_id != ''
        assert g.direct_launch_allowed is True

    def test_filter_accepts_legacy_key(self):
        """Pizza Tower accepts both '0' and 'pizzatower' as files keys."""
        g = PizzaTowerGame()
        mod_legacy = ModInfo(key='p1', name='P1', version='1.0', author='A', tagline='T',
                             game_version='1.0', description_url='', downloads=0,
                             game='pizzatower', is_verified=False,
                             files={'0': ModFileData(data_file_url='url')})
        mod_new = ModInfo(key='p2', name='P2', version='1.0', author='A', tagline='T',
                          game_version='1.0', description_url='', downloads=0,
                          game='pizzatower', is_verified=False,
                          files={'pizzatower': ModFileData(data_file_url='url')})
        result = g.filter_mods_for_ui([mod_legacy, mod_new])
        assert mod_legacy in result[0]
        assert mod_new in result[0]


class TestSugarySpireGame:

    def test_basic_properties(self):
        g = SugarySpireGame()
        assert g.game_id == 'sugaryspire'
        assert g.supports_full_install is True
        assert g.tabs[0].files_key == 'undertale'


# =========================================================================
# Game registry tests
# =========================================================================

class TestGameRegistry:

    def test_all_games_registered(self):
        expected_ids = {'deltarune', 'deltarunedemo', 'undertale', 'undertaleyellow', 'pizzatower', 'sugaryspire'}
        assert expected_ids == set(GAME_REGISTRY.keys())

    def test_get_game_existing(self):
        for gid in ['deltarune', 'undertale', 'pizzatower']:
            g = get_game(gid)
            assert g is not None
            assert g.game_id == gid

    def test_get_game_missing(self):
        assert get_game('nonexistent') is None

    def test_get_all_games(self):
        all_games = get_all_games()
        assert len(all_games) == 6
        assert all(isinstance(g, GameDefinition) for g in all_games)

    def test_each_game_has_tabs(self):
        for g in get_all_games():
            assert len(g.tabs) >= 1, f'{g.game_id} has no tabs'

    def test_each_game_has_path_config(self):
        for g in get_all_games():
            assert g.path_config_key, f'{g.game_id} missing path_config_key'
            assert g.custom_exec_config_key, f'{g.game_id} missing custom_exec_config_key'
            assert g.path_button_key, f'{g.game_id} missing path_button_key'

    def test_each_tab_has_files_key(self):
        for g in get_all_games():
            for tab in g.tabs:
                assert tab.files_key, f'{g.game_id} tab {tab.tab_id} missing files_key'
                assert tab.name_key, f'{g.game_id} tab {tab.tab_id} missing name_key'

    def test_only_deltarune_is_multi_tab(self):
        for g in get_all_games():
            if g.game_id == 'deltarune':
                assert g.is_multi_tab is True
            else:
                assert g.is_multi_tab is False, f'{g.game_id} should not be multi-tab'

    def test_backward_compat_aliases(self):
        """Old class names still work as aliases."""
        from models.game_modes import DeltaruneGame, DeltaruneDemoGame, UndertaleGame
        assert DeltaruneGame is DeltaruneGame
        assert DeltaruneDemoGame is DeltaruneDemoGame
        assert UndertaleGame is UndertaleGame


# =========================================================================
# Game path helpers
# =========================================================================

class TestGamePathHelpers:

    def test_get_game_path(self):
        g = DeltaruneGame()
        config = {'game_path': '/some/path'}
        assert g.get_game_path(config) == '/some/path'

    def test_get_game_path_missing(self):
        g = DeltaruneGame()
        assert g.get_game_path({}) == ''

    def test_set_game_path(self):
        g = UndertaleGame()
        config = {}
        g.set_game_path(config, '/ut/path')
        assert config['undertale_game_path'] == '/ut/path'

    def test_get_custom_exec_config_key(self):
        g = PizzaTowerGame()
        assert g.get_custom_exec_config_key() == 'pizzatower_custom_executable_path'


# =========================================================================
# Game detection service tests
# =========================================================================

class TestGameDetectionService:

    def test_get_game_type_string(self):
        from services.game_detection_service import get_game_type_string
        assert get_game_type_string(DeltaruneGame()) == 'deltarune'
        assert get_game_type_string(UndertaleGame()) == 'undertale'
        assert get_game_type_string(PizzaTowerGame()) == 'pizzatower'

    def test_get_game_name_string(self):
        from services.game_detection_service import get_game_name_string
        assert get_game_name_string(DeltaruneGame()) == 'DELTARUNE'
        assert get_game_name_string(UndertaleGame()) == 'UNDERTALE'
        assert get_game_name_string(SugarySpireGame()) == 'Sugary Spire'

    def test_get_chapter_id_for_game_mode(self):
        from services.game_detection_service import get_chapter_id_for_game_mode
        from config.constants import TAB_ALL
        assert get_chapter_id_for_game_mode(DeltaruneGame()) == TAB_ALL
        assert get_chapter_id_for_game_mode(DeltaruneDemoGame()) == -10
        assert get_chapter_id_for_game_mode(UndertaleGame()) == -20
