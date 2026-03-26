"""Tests for the library profiles system."""

import json
import os
import zipfile

import pytest


@pytest.fixture
def profiles_dir(temp_dir):
    d = os.path.join(temp_dir, "profiles")
    os.makedirs(d, exist_ok=True)
    return d


@pytest.fixture
def legacy_mods_dir(temp_dir):
    d = os.path.join(temp_dir, "mods")
    os.makedirs(d, exist_ok=True)
    return d


@pytest.fixture
def profile_service(
    app_state, feedback_service, temp_dir, profiles_dir, legacy_mods_dir, monkeypatch
):
    from services.profile_service import ProfileService
    from services.settings_service import SettingsManager

    monkeypatch.setattr(
        "services.profile_service.get_user_profiles_dir", lambda: profiles_dir
    )
    monkeypatch.setattr(
        "services.profile_service.get_user_mods_dir", lambda: legacy_mods_dir
    )
    settings_service = SettingsManager(app_state, feedback_service, None, parent=None)
    app_state.local_config = {
        "selected_game_type": "deltarune",
        "chapter_mode_enabled": True,
        "full_install_enabled": False,
        "direct_launch_chapter": "ch2",
        "used_mods_deltarune": {"mod_a": True},
        "some_other_setting": "keep_me",
    }
    return ProfileService(app_state, settings_service, parent=None)


def _profile_dir(profiles_dir, name):
    return os.path.join(profiles_dir, name)


def _profile_json(profiles_dir, name):
    return os.path.join(_profile_dir(profiles_dir, name), f"{name}.json")


class TestProfileMigration:
    def test_migrate_creates_default_profile_folder(
        self, profile_service, profiles_dir, app_state
    ):
        profile_service.initialize()
        default_path = _profile_json(profiles_dir, "Default")
        assert os.path.exists(default_path)
        with open(default_path, encoding="utf-8") as f:
            data = json.loads(f.read())
        assert data["selected_game_type"] == "deltarune"
        assert data["chapter_mode_enabled"] is True
        assert data["used_mods_deltarune"] == {"mod_a": True}
        assert "some_other_setting" not in data
        assert app_state.mods_dir == _profile_dir(profiles_dir, "Default")
        assert app_state.mods_metadata_path == os.path.join(
            _profile_dir(profiles_dir, "Default"), "mods_data.json"
        )

    def test_migrate_moves_legacy_mods_into_default_profile(
        self, profile_service, profiles_dir, legacy_mods_dir
    ):
        os.makedirs(os.path.join(legacy_mods_dir, "legacy_mod"), exist_ok=True)
        with open(
            os.path.join(legacy_mods_dir, "mods_data.json"), "w", encoding="utf-8"
        ) as f:
            json.dump({"legacy": True}, f)
        profile_service.initialize()
        assert not os.path.exists(os.path.join(legacy_mods_dir, "legacy_mod"))
        assert os.path.isdir(
            os.path.join(_profile_dir(profiles_dir, "Default"), "legacy_mod")
        )
        with open(
            os.path.join(_profile_dir(profiles_dir, "Default"), "mods_data.json"),
            encoding="utf-8",
        ) as f:
            assert json.load(f) == {"legacy": True}

    def test_migrate_removes_profile_keys_from_settings_json(
        self, profile_service, app_state
    ):
        profile_service.initialize()
        profile_service.save_settings_only()
        with open(app_state.config_path, encoding="utf-8") as f:
            settings = json.loads(f.read())
        assert "selected_game_type" not in settings
        assert "used_mods_deltarune" not in settings
        assert settings["some_other_setting"] == "keep_me"

    def test_migrate_is_idempotent(self, profile_service, profiles_dir):
        profile_service.initialize()
        default_path = _profile_json(profiles_dir, "Default")
        with open(default_path, encoding="utf-8") as f:
            data_before = f.read()
        profile_service._migrate_from_settings()
        with open(default_path, encoding="utf-8") as f:
            data_after = f.read()
        assert data_before == data_after


class TestProfileCRUD:
    def test_create_profile(self, profile_service, profiles_dir):
        profile_service.initialize()
        assert profile_service.create("gaming")
        assert "gaming" in profile_service.list_profiles()
        assert os.path.exists(_profile_json(profiles_dir, "gaming"))

    def test_create_duplicate_name_fails(self, profile_service):
        profile_service.initialize()
        profile_service.create("gaming")
        assert not profile_service.create("gaming")

    def test_duplicate_profile_copies_mod_folders(self, profile_service, profiles_dir):
        profile_service.initialize()
        os.makedirs(os.path.join(_profile_dir(profiles_dir, "Default"), "mod_a"))
        assert profile_service.duplicate("Default", "copy_of_default")
        copy_path = _profile_json(profiles_dir, "copy_of_default")
        assert os.path.exists(copy_path)
        assert os.path.isdir(
            os.path.join(_profile_dir(profiles_dir, "copy_of_default"), "mod_a")
        )

    def test_rename_profile(self, profile_service, profiles_dir):
        profile_service.initialize()
        profile_service.create("old_name")
        assert profile_service.rename("old_name", "new_name")
        assert not os.path.exists(_profile_dir(profiles_dir, "old_name"))
        assert os.path.exists(_profile_json(profiles_dir, "new_name"))
        assert "new_name" in profile_service.list_profiles()
        assert "old_name" not in profile_service.list_profiles()

    def test_rename_default_fails(self, profile_service):
        profile_service.initialize()
        assert not profile_service.rename("Default", "something")

    def test_delete_profile(self, profile_service, profiles_dir):
        profile_service.initialize()
        profile_service.create("deleteme")
        assert profile_service.delete("deleteme")
        assert not os.path.exists(_profile_dir(profiles_dir, "deleteme"))

    def test_delete_default_fails(self, profile_service):
        profile_service.initialize()
        assert not profile_service.delete("Default")

    def test_list_profiles_contains_default(self, profile_service):
        profile_service.initialize()
        profile_service.create("zzz")
        profile_service.create("aaa")
        profiles = profile_service.list_profiles()
        assert "Default" in profiles


class TestProfileSwitching:
    def test_switch_loads_new_profile_data(self, profile_service, app_state):
        profile_service.initialize()
        profile_service.create("alt")
        alt_data = {"selected_game_type": "undertale", "chapter_mode_enabled": False}
        profile_service._write_profile("alt", alt_data)
        profile_service.switch("alt")
        assert app_state.local_config["selected_game_type"] == "undertale"
        assert app_state.local_config.get("chapter_mode_enabled") is False
        assert profile_service.active_name == "alt"
        assert app_state.mods_dir.endswith(os.path.join("profiles", "alt"))

    def test_switch_saves_previous_profile(
        self, profile_service, app_state, profiles_dir
    ):
        profile_service.initialize()
        profile_service.create("alt")
        app_state.local_config["selected_game_type"] = "pizzatower"
        profile_service.switch("alt")
        with open(_profile_json(profiles_dir, "Default"), encoding="utf-8") as f:
            default_data = json.loads(f.read())
        assert default_data["selected_game_type"] == "pizzatower"

    def test_switch_preserves_non_profile_settings(self, profile_service, app_state):
        profile_service.initialize()
        app_state.local_config["some_other_setting"] = "preserved"
        profile_service.create("alt")
        profile_service.switch("alt")
        assert app_state.local_config["some_other_setting"] == "preserved"


class TestProfileSummary:
    def test_get_profile_summary(self, profile_service, profiles_dir):
        profile_service.initialize()
        os.makedirs(os.path.join(_profile_dir(profiles_dir, "Default"), "mod_a"))
        summary = profile_service.get_profile_summary("Default")
        assert summary["name"] == "Default"
        assert summary["game"] == "deltarune"
        assert summary["game_display_name"] == "DELTARUNE"
        assert summary["chapter_mode"] is True
        assert summary["game_mod_count"] == 1
        assert summary["total_mod_count"] == 1
        assert summary["profile_mod_count"] == 0

    def test_summary_counts_individual_mods(self, profile_service):
        profile_service.initialize()
        profile_service.create("multi")
        profile_service._write_profile(
            "multi",
            {
                "selected_game_type": "deltarune",
                "used_mods_deltarune": {
                    "ch1": "mod_a",
                    "ch2": ["mod_b", "mod_c", "mod_d"],
                },
                "used_mods_undertale": {"ut": ["mod_x", "mod_y"]},
            },
        )
        summary = profile_service.get_profile_summary("multi")
        assert summary["game_mod_count"] == 4
        assert summary["total_mod_count"] == 6

    def test_summary_counts_all_mod_folders(self, profile_service, profiles_dir):
        profile_service.initialize()
        for name in ("mod_a", "mod_b"):
            folder = os.path.join(_profile_dir(profiles_dir, "Default"), name)
            os.makedirs(folder, exist_ok=True)
            with open(
                os.path.join(folder, "mod_config.json"), "w", encoding="utf-8"
            ) as f:
                json.dump({"id": name}, f)
        assert profile_service.get_profile_summary("Default")["profile_mod_count"] == 2


class TestSaveActiveMerge:
    def test_save_active_preserves_keys_not_in_config(
        self, profile_service, app_state, profiles_dir
    ):
        profile_service.initialize()
        profile_service._write_profile(
            "Default",
            {
                "selected_game_type": "deltarune",
                "used_mods_deltarune": {"ch1": "mod_a"},
                "used_mods_undertale": {"ut": "mod_b"},
            },
        )
        for k in [
            k for k in app_state.local_config if k.startswith("used_mods_undertale")
        ]:
            del app_state.local_config[k]
        profile_service.save_active()
        with open(_profile_json(profiles_dir, "Default"), encoding="utf-8") as f:
            data = json.loads(f.read())
        assert data["used_mods_undertale"] == {"ut": "mod_b"}


class TestWriteLocalConfig:
    def test_write_local_config_splits_data(
        self, profile_service, app_state, profiles_dir
    ):
        profile_service.initialize()
        app_state.local_config["selected_game_type"] = "undertale"
        app_state.local_config["some_other_setting"] = "hello"
        profile_service.write_local_config()
        with open(app_state.config_path, encoding="utf-8") as f:
            settings = json.loads(f.read())
        assert "selected_game_type" not in settings
        assert settings["some_other_setting"] == "hello"
        with open(_profile_json(profiles_dir, "Default"), encoding="utf-8") as f:
            default_data = json.loads(f.read())
        assert default_data["selected_game_type"] == "undertale"


class TestImportExport:
    def test_export_and_import_profile_round_trip(
        self, profile_service, profiles_dir, temp_dir
    ):
        profile_service.initialize()
        mod_dir = os.path.join(_profile_dir(profiles_dir, "Default"), "mod_a")
        os.makedirs(mod_dir, exist_ok=True)
        with open(os.path.join(mod_dir, "mod_config.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "mod_a"}, f)
        export_path = os.path.join(temp_dir, "default.zip")
        assert profile_service.export("Default", export_path)
        imported = profile_service.import_profile(export_path)
        assert imported == "Default_1"
        assert os.path.exists(_profile_json(profiles_dir, "Default_1"))
        assert os.path.isdir(
            os.path.join(_profile_dir(profiles_dir, "Default_1"), "mod_a")
        )

    def test_import_profile_without_profile_json_uses_unnamed(
        self, profile_service, profiles_dir, temp_dir
    ):
        profile_service.initialize()
        archive_path = os.path.join(temp_dir, "broken.zip")
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mod_a/mod_config.json", json.dumps({"id": "mod_a"}))
        imported = profile_service.import_profile(archive_path)
        assert imported == "Unnamed"
        with open(_profile_json(profiles_dir, "Unnamed"), encoding="utf-8") as f:
            assert json.load(f) == {}

    def test_import_profile_from_wrapped_root_folder(
        self, profile_service, profiles_dir, temp_dir
    ):
        profile_service.initialize()
        archive_path = os.path.join(temp_dir, "wrapped.zip")
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "Wrapped/Custom.json", json.dumps({"selected_game_type": "undertale"})
            )
            zf.writestr("Wrapped/mod_a/mod_config.json", json.dumps({"id": "mod_a"}))
        imported = profile_service.import_profile(archive_path)
        assert imported == "Custom"
        assert os.path.exists(_profile_json(profiles_dir, "Custom"))
        assert os.path.isdir(
            os.path.join(_profile_dir(profiles_dir, "Custom"), "mod_a")
        )


class TestReorder:
    def test_reorder_profiles(self, profile_service, app_state):
        profile_service.initialize()
        profile_service.create("b")
        profile_service.create("a")
        profile_service.reorder(["a", "Default", "b"])
        profiles = profile_service.list_profiles()
        assert profiles[0] == "a"
        assert profiles[1] == "Default"
        assert profiles[2] == "b"
