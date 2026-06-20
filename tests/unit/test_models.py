"""Unit tests for test models."""

import pytest

from models.game_modes import (
    GAME_REGISTRY,
    DeltaruneDemoGame,
    DeltaruneGame,
    Frickbears3Game,
    GameDefinition,
    GameTab,
    PizzaTowerGame,
    SugarySpireGame,
    UndertaleGame,
    UndertaleYellowGame,
    get_all_games,
    get_game,
)
from models.mod_models import ModFileData, ModInfo


class TestModInfo:
    """Tests for models."""
    def test_creation_minimal(self):
        """Checks that creationing minimal."""
        mod = ModInfo(id='k', name='N', version='1.0', author='A', description='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarune')
        assert mod.id == 'k'
        assert mod.name == 'N'
        assert mod.game == 'deltarune'

    def test_from_dict_basic(self):
        """Checks that from_dict basic."""
        data = {'id': 'mod_a', 'name': 'Mod A', 'version': '2.0', 'author': 'Auth',
                'description': 'Tag', 'game_version': '1.0', 'description_url': '',
                'downloads': 5, 'game': 'deltarune'}
        mod = ModInfo.from_dict(data)
        assert mod.id == 'mod_a'
        assert mod.version == '2.0'
        assert mod.downloads == 5

    def test_from_dict_defaults(self):
        """Checks that from_dict defaults."""
        mod = ModInfo.from_dict({})
        assert mod.id == ''
        assert mod.game == 'deltarune'
        assert mod.downloads is None

    def test_from_dict_with_files(self):
        """Checks that froming dict with files."""
        data = {
            'id': 'mod_f', 'name': 'F', 'version': '1.0', 'author': 'A',
            'description': 'T', 'game_version': '1.0', 'description_url': '',
            'downloads': 0, 'game': 'deltarune',
            'files': {
                '1': {'data_file_url': 'http://example.com/data.win'},
                '2': {'data_file_url': 'http://example.com/ch2.win'},
            }
        }
        mod = ModInfo.from_dict(data)
        assert '1' in mod.files
        assert '2' in mod.files
        assert isinstance(mod.files['1'], ModFileData)
        assert mod.files['1'].data_file_url == 'http://example.com/data.win'

    def test_from_dict_with_extra_files(self):
        """Checks that froming dict with extra files."""
        data = {
            'id': 'mod_e', 'name': 'E', 'version': '1.0', 'author': 'A',
            'description': 'T', 'game_version': '1.0', 'description_url': '',
            'downloads': 0, 'game': 'deltarune',
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
        assert mod.files['0'].extra_files[0] == 'http://example.com/music.zip'

    def test_get_file_data_direct(self):
        """Checks that getting file data direct."""
        mod = ModInfo(id='k', name='N', version='1.0', author='A', description='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarune',
                      files={'1': ModFileData(data_file_url='url1')})
        assert mod.get_file_data('1') is not None
        assert mod.get_file_data('1').data_file_url == 'url1'
        assert mod.get_file_data('nonexistent') is None

    def test_get_chapter_data_deltarune(self):
        """Checks that getting chapter data deltarune."""
        mod = ModInfo(id='k', name='N', version='1.0', author='A', description='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarune',
                      files={
                          '0': ModFileData(data_file_url='menu_url'),
                          '1': ModFileData(data_file_url='ch1_url'),
                          '2': ModFileData(data_file_url='ch2_url'),
                      })
        assert mod.get_chapter_data('deltarune_0').data_file_url == 'menu_url'
        assert mod.get_chapter_data('deltarune_1').data_file_url == 'ch1_url'
        assert mod.get_chapter_data('deltarune_2').data_file_url == 'ch2_url'
        assert mod.get_chapter_data('deltarune_3') is None

    def test_get_chapter_data_undertale(self):
        """Checks that getting chapter data undertale."""
        mod = ModInfo(id='k', name='N', version='1.0', author='A', description='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='undertale',
                      files={'undertale': ModFileData(data_file_url='ut_url')})
        result = mod.get_chapter_data('undertale')
        assert result is not None
        assert result.data_file_url == 'ut_url'

    def test_get_chapter_data_demo(self):
        """Checks that getting chapter data demo."""
        mod = ModInfo(id='k', name='N', version='1.0', author='A', description='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarunedemo',
                      files={'demo': ModFileData(data_file_url='demo_url')})
        result = mod.get_chapter_data('deltarunedemo')
        assert result is not None
        assert result.data_file_url == 'demo_url'

    def test_is_valid_for_demo(self):
        """Checks that validates for demo."""
        mod = ModInfo(id='k', name='N', version='1.0', author='A', description='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarunedemo',
                      files={'demo': ModFileData(data_file_url='url')})
        assert mod.is_valid_for_demo() is True

    def test_is_valid_for_demo_wrong_game(self):
        """Checks that validates for demo wrong game."""
        mod = ModInfo(id='k', name='N', version='1.0', author='A', description='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarune',
                      files={'demo': ModFileData(data_file_url='url')})
        assert mod.is_valid_for_demo() is False

    def test_is_gamebanana_mod(self):
        """Checks that detects gamebanana mod."""
        mod = ModInfo(id='gb_mod_12345', name='N', version='1.0', author='A', description='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarune')
        assert mod.is_gamebanana_mod() is True
        assert mod.get_gamebanana_mod_id() == '12345'

    def test_is_gamebanana_wip_mod(self):
        """Checks that detects gamebanana wip mod."""
        mod = ModInfo(id='gb_wip_67890', name='N', version='1.0', author='A', description='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarune')
        assert mod.is_gamebanana_mod() is True
        assert mod.get_gamebanana_mod_id() == '67890'

    def test_invalid_gb_key_not_recognized(self):
        """Checks that invaliding gb key not recognized."""
        mod = ModInfo(id='gb_12345', name='N', version='1.0', author='A', description='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarune')
        assert mod.is_gamebanana_mod() is False
        assert mod.get_gamebanana_mod_id() is None

    def test_is_not_gamebanana_mod(self):
        """Checks that rejects non-gamebanana mod."""
        mod = ModInfo(id='local_mod', name='N', version='1.0', author='A', description='T',
                      game_version='1.0', description_url='', downloads=0,
                      game='deltarune')
        assert mod.is_gamebanana_mod() is False
        assert mod.get_gamebanana_mod_id() is None


class TestModFileData:
    """Tests for models."""
    def test_creation(self):
        """Checks that creationing works."""
        fd = ModFileData(description='Test', data_file_url='data.win')
        assert fd.description == 'Test'
        assert fd.data_file_url == 'data.win'
        assert fd.extra_files == []

    def test_with_extra_files(self):
        """Checks that withing with extra files."""
        fd = ModFileData(extra_files=['f1.zip', 'f2.zip'])
        assert len(fd.extra_files) == 2
        assert fd.extra_files[0] == 'f1.zip'

    def test_is_valid_with_url(self):
        """Checks that validates with url."""
        assert ModFileData(data_file_url='url').is_valid() is True

    def test_is_valid_with_extra_files(self):
        """Checks that validates with extra files."""
        assert ModFileData(extra_files=['u']).is_valid() is True

    def test_is_valid_empty(self):
        """Checks that validates empty."""
        assert ModFileData().is_valid() is False


class TestGameTab:
    """Tests for models."""
    def test_creation(self):
        """Checks that creationing works."""
        tab = GameTab(tab_id='deltarune_1', files_key='1', name_key='tabs.chapter_1')
        assert tab.tab_id == 'deltarune_1'
        assert tab.files_key == '1'
        assert tab.name_key == 'tabs.chapter_1'
        assert tab.direct_launch is True

    def test_frozen(self):
        """Checks that frozening works."""
        tab = GameTab(tab_id='deltarune_0', files_key='0', name_key='tabs.menu')
        with pytest.raises(AttributeError):
            tab.tab_id = 'x'

    def test_no_direct_launch(self):
        """Checks that noing direct launch."""
        tab = GameTab(tab_id='deltarunedemo', files_key='demo', name_key='tabs.demo', direct_launch=False)
        assert tab.direct_launch is False


class TestGameDefinition:
    """Tests for models."""
    def test_base_has_defaults(self):
        """Checks that baseing has defaults."""
        gd = GameDefinition()
        assert gd.game_id == ''
        assert gd.tabs == []
        assert gd.is_multi_tab is False
        assert gd.supports_full_install is False
        assert gd.block_steam_with_direct_launch is False

    def test_get_tab_returns_none_for_empty(self):
        """Checks that getting tab returns none for empty."""
        gd = GameDefinition()
        assert gd.get_tab('deltarune_0') is None
        assert gd.get_tab_by_index(0) is None

    def test_get_chapter_id_returns_default_for_empty(self):
        """Checks that getting chapter id returns default for empty."""
        gd = GameDefinition()
        assert gd.get_chapter_id(0) == ''


class TestDeltaruneGame:
    """Tests for models."""
    def test_basic_properties(self):
        """Checks that basicing properties."""
        g = DeltaruneGame()
        assert g.game_id == 'deltarune'
        assert g.steam_app_id != ''
        assert g.path_config_key == 'game_path'
        assert g.block_steam_with_direct_launch is True
        assert g.supports_full_install is False

    def test_has_6_tabs(self):
        """Checks that has 6 tabs."""
        g = DeltaruneGame()
        assert len(g.tabs) == 6
        assert g.is_multi_tab is True
        assert g.tabs[0].files_key == '0'
        assert g.tabs[1].files_key == '1'
        assert g.tabs[5].files_key == '5'

    def test_get_tab_by_id(self):
        """Checks that getting tab by id."""
        g = DeltaruneGame()
        assert g.get_tab('deltarune_0').files_key == '0'
        assert g.get_tab('deltarune_3').files_key == '3'
        assert g.get_tab('nonexistent') is None

    def test_get_chapter_id(self):
        """Checks that getting chapter id."""
        g = DeltaruneGame()
        expected = ['deltarune_0', 'deltarune_1', 'deltarune_2', 'deltarune_3', 'deltarune_4', 'deltarune_5']
        for i in range(6):
            assert g.get_chapter_id(i) == expected[i]

    def test_direct_launch_allowed(self):
        """Checks that directing launch allowed."""
        g = DeltaruneGame()
        assert g.direct_launch_allowed is True

    def test_steam_app_id(self):
        """Checks that steaming app id."""
        g = DeltaruneGame()
        assert g.steam_app_id != ''

    def test_filter_mods_for_ui(self):
        """Checks that filtering mods for ui."""
        g = DeltaruneGame()
        mod1 = ModInfo(id='m1', name='M1', version='1.0', author='A', description='T',
                        game_version='1.0', description_url='', downloads=0,
                        game='deltarune',
                        files={'1': ModFileData(data_file_url='url')})
        mod2 = ModInfo(id='m2', name='M2', version='1.0', author='A', description='T',
                        game_version='1.0', description_url='', downloads=0,
                        game='undertale',
                        files={'undertale': ModFileData(data_file_url='url')})
        result = g.filter_mods_for_ui([mod1, mod2])
        assert len(result) == 6
        assert mod1 in result[1]
        assert mod2 not in result[1]

    def test_filter_hidden_mods_excluded(self):
        """Checks that filtering hidden mods excluded."""
        g = DeltaruneGame()
        hidden = ModInfo(id='h', name='H', version='1.0', author='A', description='T',
                          game_version='1.0', description_url='', downloads=0,
                          game='deltarune', hide_mod=True,
                          files={'0': ModFileData(data_file_url='url')})
        result = g.filter_mods_for_ui([hidden])
        assert hidden not in result[0]

    def test_filter_banned_mods_excluded(self):
        """Checks that filtering banned mods excluded."""
        g = DeltaruneGame()
        banned = ModInfo(id='b', name='B', version='1.0', author='A', description='T',
                          game_version='1.0', description_url='', downloads=0,
                          game='deltarune', ban_status=True,
                          files={'0': ModFileData(data_file_url='url')})
        result = g.filter_mods_for_ui([banned])
        assert banned not in result[0]


class TestDeltaruneDemoGame:
    """Tests for models."""
    def test_basic_properties(self):
        """Checks that basicing properties."""
        g = DeltaruneDemoGame()
        assert g.game_id == 'deltarunedemo'
        assert g.supports_full_install is True
        assert len(g.tabs) == 1
        assert g.is_multi_tab is False
        assert g.tabs[0].direct_launch is False

    def test_direct_launch_not_allowed(self):
        """Checks that directing launch not allowed."""
        g = DeltaruneDemoGame()
        assert g.direct_launch_allowed is False

    def test_filter_mods_demo(self):
        """Checks that filtering mods demo."""
        g = DeltaruneDemoGame()
        valid_demo = ModInfo(id='d1', name='D1', version='1.0', author='A', description='T',
                              game_version='1.0', description_url='', downloads=0,
                              game='deltarunedemo',
                              files={'demo': ModFileData(data_file_url='url')})
        wrong_game = ModInfo(id='d2', name='D2', version='1.0', author='A', description='T',
                              game_version='1.0', description_url='', downloads=0,
                              game='deltarune',
                              files={'demo': ModFileData(data_file_url='url')})
        result = g.filter_mods_for_ui([valid_demo, wrong_game])
        assert valid_demo in result[0]
        assert wrong_game not in result[0]


class TestUndertaleGame:
    """Tests for models."""
    def test_basic_properties(self):
        """Checks that basicing properties."""
        g = UndertaleGame()
        assert g.game_id == 'undertale'
        assert g.steam_app_id != ''
        assert len(g.tabs) == 1
        assert g.is_multi_tab is False
        assert g.tabs[0].files_key == 'undertale'

    def test_filter_mods(self):
        """Checks that filtering mods."""
        g = UndertaleGame()
        ut_mod = ModInfo(id='u1', name='U1', version='1.0', author='A', description='T',
                          game_version='1.0', description_url='', downloads=0,
                          game='undertale',
                          files={'undertale': ModFileData(data_file_url='url')})
        dr_mod = ModInfo(id='d1', name='D1', version='1.0', author='A', description='T',
                          game_version='1.0', description_url='', downloads=0,
                          game='deltarune',
                          files={'1': ModFileData(data_file_url='url')})
        result = g.filter_mods_for_ui([ut_mod, dr_mod])
        assert ut_mod in result[0]
        assert dr_mod not in result[0]


class TestUndertaleYellowGame:
    """Tests for models."""
    def test_basic_properties(self):
        """Checks that basicing properties."""
        g = UndertaleYellowGame()
        assert g.game_id == 'undertaleyellow'
        assert g.supports_full_install is True
        assert g.steam_app_id == ''
        assert g.tabs[0].files_key == 'undertaleyellow'


class TestPizzaTowerGame:
    """Tests for models."""
    def test_basic_properties(self):
        """Checks that basicing properties."""
        g = PizzaTowerGame()
        assert g.game_id == 'pizzatower'
        assert g.steam_app_id != ''
        assert g.direct_launch_allowed is True

    def test_filter_accepts_single_tab_zero_key(self):
        """Checks that filtering accepts single tab zero key."""
        g = PizzaTowerGame()
        mod_legacy = ModInfo(id='p1', name='P1', version='1.0', author='A', description='T',
                              game_version='1.0', description_url='', downloads=0,
                              game='pizzatower',
                              files={'0': ModFileData(data_file_url='url')})
        mod_new = ModInfo(id='p2', name='P2', version='1.0', author='A', description='T',
                          game_version='1.0', description_url='', downloads=0,
                          game='pizzatower',
                          files={'pizzatower': ModFileData(data_file_url='url')})
        result = g.filter_mods_for_ui([mod_legacy, mod_new])
        assert mod_legacy in result[0]
        assert mod_new in result[0]


class TestSugarySpireGame:
    """Tests for models."""
    def test_basic_properties(self):
        """Checks that basicing properties."""
        g = SugarySpireGame()
        assert g.game_id == 'sugaryspire'
        assert g.supports_full_install is True
        assert g.tabs[0].files_key == 'sugaryspire'


class TestFrickbears3Game:
    """Tests for models."""
    def test_basic_properties(self):
        """Checks that basicing properties."""
        g = Frickbears3Game()
        assert g.game_id == 'frickbears3'
        assert g.display_name == 'FRICKBEARS3'
        assert g.supports_full_install is True
        assert g.tabs[0].files_key == 'frickbears3'
        assert g.tabs[0].folder_name == 'frickbears3'


class TestGameRegistry:
    """Tests for models."""
    def test_all_games_registered(self):
        """Checks that alling games registered."""
        expected_ids = {'deltarune', 'deltarunedemo', 'undertale', 'undertaleyellow', 'pizzatower', 'sugaryspire', 'frickbears3'}
        assert expected_ids == set(GAME_REGISTRY.keys())

    def test_get_game_existing(self):
        """Checks that getting game existing."""
        for gid in ['deltarune', 'undertale', 'pizzatower']:
            g = get_game(gid)
            assert g is not None
            assert g.game_id == gid

    def test_get_game_missing(self):
        """Checks that getting game missing."""
        assert get_game('nonexistent') is None

    def test_get_all_games(self):
        """Checks that getting all games."""
        all_games = get_all_games()
        assert len(all_games) == 7
        assert all(isinstance(g, GameDefinition) for g in all_games)

    def test_each_game_has_tabs(self):
        """Checks that eaching game has tabs."""
        for g in get_all_games():
            assert len(g.tabs) >= 1, f'{g.game_id} has no tabs'

    def test_each_game_has_path_config(self):
        """Checks that eaching game has path config."""
        for g in get_all_games():
            assert g.path_config_key, f'{g.game_id} missing path_config_key'
            assert g.custom_exec_config_key, f'{g.game_id} missing custom_exec_config_key'

    def test_each_tab_has_files_key(self):
        """Checks that eaching tab has files key."""
        for g in get_all_games():
            for tab in g.tabs:
                assert tab.files_key, f'{g.game_id} tab {tab.tab_id} missing files_key'
                assert tab.name_key, f'{g.game_id} tab {tab.tab_id} missing name_key'

    def test_only_deltarune_is_multi_tab(self):
        """Checks that onlying deltarune is multi tab."""
        for g in get_all_games():
            if g.game_id == 'deltarune':
                assert g.is_multi_tab is True
            else:
                assert g.is_multi_tab is False, f'{g.game_id} should not be multi-tab'


class TestGamePathHelpers:
    """Tests for models."""
    def test_get_game_path(self):
        """Checks that getting game path."""
        g = DeltaruneGame()
        config = {'game_path': '/some/path'}
        assert g.get_game_path(config) == '/some/path'

    def test_get_game_path_missing(self):
        """Checks that getting game path missing."""
        g = DeltaruneGame()
        assert g.get_game_path({}) == ''

    def test_set_game_path(self):
        """Checks that setting game path."""
        g = UndertaleGame()
        config = {}
        g.set_game_path(config, '/ut/path')
        assert config['undertale_game_path'] == '/ut/path'

    def test_get_custom_exec_config_key(self):
        """Checks that getting custom exec config key."""
        g = PizzaTowerGame()
        assert g.get_custom_exec_config_key() == 'pizzatower_custom_executable_path'
