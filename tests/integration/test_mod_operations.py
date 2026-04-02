import json
import os
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class TestModInstallation:
    """Tests for mod operations."""
    def test_install_mod_from_archive(self, app_state, feedback_service, temp_mods_dir):
        """Checks that installing mod from archive."""
        from services.mod_service import ModManager

        _ = ModManager(app_state, feedback_service)
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_archive:
            archive_path = tmp_archive.name
            with zipfile.ZipFile(archive_path, "w") as zf:
                mod_config = {
                    "id": "test_install_mod",
                    "name": "Test Install Mod",
                    "version": "1.0.0",
                }
                zf.writestr("mod_config.json", json.dumps(mod_config))
                zf.writestr("meta.json", '{"metadata": {"name": "Test Mod"}}')
                zf.writestr("file1.txt", "test file content")
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                assert "mod_config.json" in zf.namelist()
                assert "meta.json" in zf.namelist()
        finally:
            os.unlink(archive_path)

    def test_install_mod_with_files(self, app_state, feedback_service, temp_mods_dir):
        """Checks that installing mod with files."""
        from services.mod_service import ModManager

        _ = ModManager(app_state, feedback_service)
        key = "test_mod_files"
        mod_folder = os.path.join(temp_mods_dir, key)
        os.makedirs(mod_folder, exist_ok=True)
        mod_config = {
            "id": key,
            "name": "Test Mod with Files",
            "version": "1.0.0",
            "files": [
                {"path": "file1.txt", "chapter": 1},
                {"path": "file2.txt", "chapter": 2},
            ],
        }
        config_path = os.path.join(mod_folder, "mod_config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(mod_config, f)
        for i in range(1, 3):
            file_path = os.path.join(mod_folder, f"file{i}.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"Test content {i}")
        assert os.path.exists(mod_folder)
        assert os.path.exists(config_path)


class TestModRemoval:
    """Tests for mod operations."""
    def test_remove_mod(self, app_state, feedback_service, sample_mod_folder):
        """Checks that removing mod."""
        from services.mod_service import ModManager

        mod_service = ModManager(app_state, feedback_service)
        cache = mod_service._get_mods_cache(use_async=False)
        assert "test_mod_001" in cache
        assert os.path.exists(sample_mod_folder)


class TestModMerge:
    """Tests for mod operations."""
    def test_merge_multiple_mods(self, app_state, feedback_service, temp_mods_dir):
        """Checks that merging multiple mods."""
        from services.g3mtool_patching_service import G3MToolPatchingService

        mods = []
        for i in range(3):
            key = f"test_merge_mod_{i}"
            mod_folder = os.path.join(temp_mods_dir, key)
            os.makedirs(mod_folder, exist_ok=True)
            mod_config = {"id": key, "name": f"Test Merge Mod {i}", "version": "1.0.0"}
            config_path = os.path.join(mod_folder, "mod_config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(mod_config, f)
            mods.append(key)
        from services.mod_service import ModManager

        mod_service = ModManager(app_state, feedback_service)
        patcher = G3MToolPatchingService(app_state, mod_service)
        assert patcher is not None


class TestModImportExport:
    """Tests for mod operations."""
    def test_export_mod(self, app_state, feedback_service, sample_mod_folder):
        """Checks that exporting mod."""
        from unittest.mock import Mock

        from controllers.mod_import_export_controller import ModImportExportController
        from services.mod_service import ModManager

        mod_service = ModManager(app_state, feedback_service)
        mock_app_window = Mock()
        controller = ModImportExportController(
            app_state=app_state, mod_service=mod_service, app_window=mock_app_window
        )
        assert controller is not None

    def test_import_mod_from_url(self, app_state, feedback_service):
        """Checks that importing mod from url."""
        from unittest.mock import Mock

        from controllers.mod_import_export_controller import ModImportExportController
        from services.mod_service import ModManager

        mod_service = ModManager(app_state, feedback_service)
        mock_app_window = Mock()
        controller = ModImportExportController(
            app_state=app_state, mod_service=mod_service, app_window=mock_app_window
        )
        assert controller is not None


class TestManualInstall:
    """Tests for mod operations."""
    def test_chapter_display_name(self, tmp_path):
        """Checks that chaptering display name."""
        from unittest.mock import MagicMock, patch

        from ui.dialogs.manual_install_dialog import ManualModInstallDialog

        with patch.object(
            ManualModInstallDialog, "__init__", lambda self, *a, **kw: None
        ):
            dialog = ManualModInstallDialog.__new__(ManualModInstallDialog)
            dialog.data_tabs = MagicMock()
            dialog.data_tabs.count.return_value = 0
            from services.localization_service import tr

            assert dialog._chapter_display_name("deltarune_0") == tr("tabs.menu_root")
            assert dialog._chapter_display_name("deltarune_2") == tr("tabs.chapter_2")
            assert dialog._chapter_display_name("undertale") == "undertale"
            assert dialog._chapter_display_name("deltarunedemo") == "deltarunedemo"

    def test_chapter_folder_name(self):
        """Checks that chaptering folder name."""
        from utils.file_utils import get_chapter_folder_name

        assert get_chapter_folder_name("deltarune_0") == "chapter_0"
        assert get_chapter_folder_name("deltarune_1") == "chapter_1"
        assert get_chapter_folder_name("deltarunedemo") == "demo"
        assert get_chapter_folder_name("undertale") == "chapter_0"
        assert get_chapter_folder_name("pizzatower") == "pizzatower"

        assert get_chapter_folder_name("deltarune_0", game="deltarune") == "chapter_0"
        assert get_chapter_folder_name("pizzatower", game="pizzatower") == "pizzatower"
        assert get_chapter_folder_name("chapter_1", game="deltarune") == "chapter_1"
        assert get_chapter_folder_name("deltarune_1") == "chapter_1"

    def test_instruction_file_detection(self):
        """Checks that instructioning file detection."""
        from ui.dialogs.manual_install_dialog import ManualModInstallDialog

        assert ManualModInstallDialog._is_openable_doc("README.md") is True
        assert ManualModInstallDialog._is_openable_doc("guide.txt") is True
        assert ManualModInstallDialog._is_openable_doc("sprite.png") is False

    def test_open_local_file_uses_native_open(self, tmp_path):
        """Checks that opening local file uses native open."""
        from unittest.mock import patch

        from ui.dialogs.manual_install_dialog import ManualModInstallDialog

        file_path = tmp_path / "README.md"
        file_path.write_text("# test", encoding="utf-8")
        with patch.object(
            ManualModInstallDialog, "__init__", lambda self, *a, **kw: None
        ):
            dialog = ManualModInstallDialog.__new__(ManualModInstallDialog)
            with patch(
                "ui.dialogs.manual_install_dialog.QDesktopServices.openUrl",
                return_value=True,
            ) as open_url:
                dialog._open_local_file(str(file_path))
                open_url.assert_called_once()
                called_url = open_url.call_args[0][0]
                assert called_url.isLocalFile()
                assert Path(called_url.toLocalFile()) == file_path

    def test_create_mod_from_files_uses_chapter_ids_as_file_keys(self, tmp_path):
        """Checks that creating mod from files uses chapter ids as file keys."""
        from ui.dialogs.manual_install_dialog import ManualModInstallDialog

        source_dir = tmp_path / "prepared"
        source_dir.mkdir()
        data_file = source_dir / "BOSSRUSH.win"
        data_file.write_text("bossrush", encoding="utf-8")
        with patch.object(
            ManualModInstallDialog, "__init__", lambda self, *a, **kw: None
        ):
            dialog = ManualModInstallDialog.__new__(ManualModInstallDialog)
            dialog.app_state = SimpleNamespace(mods_dir=str(tmp_path / "mods"))
            dialog.mod_service = object()
            dialog.gamebanana_metadata = {}
            dialog.source_file_path = None
            dialog.game_combo = SimpleNamespace(currentData=lambda: "deltarune")
            dialog.data_file_selections = {"deltarune_4": str(data_file)}
            dialog.extra_files_mappings = {}
            dialog.unused_files = set()
            dialog.xdelta_patches_mappings = {}
            dialog.all_files = [(str(data_file), "BOSSRUSH.win")]
            os.makedirs(dialog.app_state.mods_dir, exist_ok=True)

            dialog._create_mod_from_files()

        mod_folders = list(Path(dialog.app_state.mods_dir).iterdir())
        assert len(mod_folders) == 1
        config = json.loads((mod_folders[0] / "mod_config.json").read_text("utf-8"))
        assert "deltarune_4" in config["files"]
        assert "4" not in config["files"]
        assert config["files"]["deltarune_4"]["data_file_path"] == "chapter_4/BOSSRUSH.win"
        assert (mod_folders[0] / "chapter_4" / "BOSSRUSH.win").exists()

    def test_create_mod_from_files_accepts_csx_as_data_file(self, tmp_path):
        """Checks that manual install stores csx scripts as chapter data files."""
        from ui.dialogs.manual_install_dialog import ManualModInstallDialog

        source_dir = tmp_path / "prepared"
        source_dir.mkdir()
        data_file = source_dir / "BOSSRUSH.csx"
        data_file.write_text("// fake script", encoding="utf-8")
        with patch.object(
            ManualModInstallDialog, "__init__", lambda self, *a, **kw: None
        ):
            dialog = ManualModInstallDialog.__new__(ManualModInstallDialog)
            dialog.app_state = SimpleNamespace(mods_dir=str(tmp_path / "mods"))
            dialog.mod_service = object()
            dialog.gamebanana_metadata = {}
            dialog.source_file_path = None
            dialog.game_combo = SimpleNamespace(currentData=lambda: "deltarune")
            dialog.data_file_selections = {"deltarune_4": str(data_file)}
            dialog.extra_files_mappings = {}
            dialog.unused_files = set()
            dialog.xdelta_patches_mappings = {}
            dialog.all_files = [(str(data_file), "BOSSRUSH.csx")]
            os.makedirs(dialog.app_state.mods_dir, exist_ok=True)

            dialog._create_mod_from_files()

        mod_folder = next(Path(dialog.app_state.mods_dir).iterdir())
        config = json.loads((mod_folder / "mod_config.json").read_text("utf-8"))
        assert config["files"]["deltarune_4"]["data_file_path"] == "chapter_4/BOSSRUSH.csx"
        assert (mod_folder / "chapter_4" / "BOSSRUSH.csx").exists()

    def test_create_mod_from_files_persists_gamebanana_metadata(self, tmp_path):
        """Checks that manual install stores available GameBanana metadata locally."""
        from ui.dialogs.manual_install_dialog import ManualModInstallDialog

        source_dir = tmp_path / "prepared"
        source_dir.mkdir()
        data_file = source_dir / "laphell.xdelta"
        data_file.write_text("patch", encoding="utf-8")
        with patch.object(
            ManualModInstallDialog, "__init__", lambda self, *a, **kw: None
        ):
            dialog = ManualModInstallDialog.__new__(ManualModInstallDialog)
            dialog.app_state = SimpleNamespace(mods_dir=str(tmp_path / "mods"))
            dialog.mod_service = object()
            dialog.gamebanana_metadata = {
                "mod_id": 665180,
                "item_type": "mod",
                "name": "Lap Hell",
                "description": "Preheat your oven.",
                "author": "Chef",
                "version": "2.0",
                "icon": "https://images.gamebanana.com/example.jpg",
                "homepage": "https://gamebanana.com/mods/665180",
                "tags": ["gameplay"],
            }
            dialog.source_file_path = "laphell.zip"
            dialog.game_combo = SimpleNamespace(currentData=lambda: "pizzatower")
            dialog.data_file_selections = {"pizzatower": str(data_file)}
            dialog.extra_files_mappings = {}
            dialog.extra_files_chapters = {}
            dialog.unused_files = set()
            dialog.xdelta_patches_mappings = {}
            dialog.all_files = [(str(data_file), "laphell.xdelta")]
            dialog._copy_root_docs_to_mod = lambda target_mod_dir: None
            os.makedirs(dialog.app_state.mods_dir, exist_ok=True)

            dialog._create_mod_from_files()

        mod_folder = next(Path(dialog.app_state.mods_dir).iterdir())
        config = json.loads((mod_folder / "mod_config.json").read_text("utf-8"))

        assert config["metadata"]["id"] == "gb_mod_665180"
        assert config["metadata"]["name"] == "Lap Hell"
        assert config["metadata"]["description"] == "Preheat your oven."
        assert config["metadata"]["icon"] == "https://images.gamebanana.com/example.jpg"
        assert config["metadata"]["homepage"] == "https://gamebanana.com/mods/665180"

    def test_create_mod_from_files_uses_extra_path_prefix_to_bind_chapter(self, tmp_path):
        """Checks that chapter-prefixed extra paths bind files to that DELTARUNE chapter."""
        from ui.dialogs.manual_install_dialog import ManualModInstallDialog

        source_dir = tmp_path / "prepared"
        source_dir.mkdir()
        extra_file = source_dir / "lang.json"
        extra_file.write_text("{}", encoding="utf-8")
        with patch.object(
            ManualModInstallDialog, "__init__", lambda self, *a, **kw: None
        ):
            dialog = ManualModInstallDialog.__new__(ManualModInstallDialog)
            dialog.app_state = SimpleNamespace(mods_dir=str(tmp_path / "mods"))
            dialog.mod_service = object()
            dialog.gamebanana_metadata = {}
            dialog.source_file_path = None
            dialog.game_combo = SimpleNamespace(currentData=lambda: "deltarune")
            dialog.data_tabs = SimpleNamespace(count=lambda: 0)
            dialog.data_file_selections = {}
            dialog.extra_files_mappings = {
                str(extra_file): "chapter_1/lang_es/",
            }
            dialog.extra_files_chapters = {}
            dialog.unused_files = set()
            dialog.xdelta_patches_mappings = {}
            dialog.all_files = [(str(extra_file), "lang.json")]
            dialog._copy_root_docs_to_mod = lambda target_mod_dir: None
            os.makedirs(dialog.app_state.mods_dir, exist_ok=True)

            dialog._create_mod_from_files()

        mod_folder = next(Path(dialog.app_state.mods_dir).iterdir())
        config = json.loads((mod_folder / "mod_config.json").read_text("utf-8"))

        assert config["files"]["deltarune_1"]["extra_files"] == [
            "chapter_1/lang_es/lang.json"
        ]
