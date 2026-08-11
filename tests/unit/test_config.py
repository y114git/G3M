"""Unit tests for test config."""

import ast
import sys
import types
from pathlib import Path

import pytest
from dotenv import load_dotenv as real_load_dotenv


class TestConstants:
    """Tests for config."""
    def test_constants_import(self):
        """Checks that constantsing import."""
        from config.config import (
            APP_VERSION,
            GAMEBANANA_API_BASE,
            SOCIAL_LINKS,
            UI_COLORS,
        )

        assert APP_VERSION is not None
        assert isinstance(UI_COLORS, dict)
        assert isinstance(SOCIAL_LINKS, dict)
        assert GAMEBANANA_API_BASE is not None

    def test_ui_colors_structure(self):
        """Checks that uiing colors structure."""
        from config.config import UI_COLORS

        assert "status_error" in UI_COLORS
        assert "status_success" in UI_COLORS
        assert "status_warning" in UI_COLORS
        assert "status_info" in UI_COLORS

    def test_onboarding_is_incomplete_by_default(self):
        from config.settings_schema import DEFAULT_APP_SETTINGS

        assert DEFAULT_APP_SETTINGS["onboarding_completed"] is False

    def test_gamebanana_constants(self):
        """Checks that gamebananaing constants."""
        from config.config import (
            GAMEBANANA_TOOL_ID_DELTAMOD,
            GAMEBANANA_TOOL_ID_G3M,
        )
        from models.game_modes import BUILTIN_GAME_REGISTRY

        for game_id in (
            "deltarune",
            "undertale",
            "undertaleyellow",
            "pizzatower",
            "sugaryspire",
            "frickbears3",
        ):
            assert game_id in BUILTIN_GAME_REGISTRY, f"{game_id} missing from registry"
            assert BUILTIN_GAME_REGISTRY[game_id].gamebanana_id, (
                f"{game_id} has no gamebanana_id"
            )
        assert GAMEBANANA_TOOL_ID_G3M is not None
        assert GAMEBANANA_TOOL_ID_DELTAMOD is not None

    @staticmethod
    def _reload_config_module() -> types.ModuleType:
        sys.modules.pop("config.config", None)
        import config.config as config_module

        return config_module

    def test_env_config_loading_without_env(self, monkeypatch):
        """Checks that enving config loading without env."""
        monkeypatch.delenv("CLOUD_FUNCTIONS_BASE_URL", raising=False)
        monkeypatch.delenv("DRP_CLIENT_ID", raising=False)
        monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)

        config_module = self._reload_config_module()

        assert isinstance(config_module.CLOUD_FUNCTIONS_BASE_URL, str)
        assert config_module.CLOUD_FUNCTIONS_BASE_URL == ""
        assert isinstance(config_module.DRP_CLIENT_ID, str)
        assert config_module.DRP_CLIENT_ID == ""

    def test_env_config_loading_with_dotenv_file(self, monkeypatch, tmp_path):
        """Checks that enving config loading with dotenv file."""
        configured_value = "https://example.com/functions"
        configured_drp_client_id = "discord-client-id"
        monkeypatch.delenv("CLOUD_FUNCTIONS_BASE_URL", raising=False)
        monkeypatch.delenv("DRP_CLIENT_ID", raising=False)
        dotenv_path = tmp_path / "src" / ".env"
        dotenv_path.parent.mkdir()
        dotenv_path.write_text(
            (
                f"CLOUD_FUNCTIONS_BASE_URL={configured_value}\n"
                f"DRP_CLIENT_ID={configured_drp_client_id}\n"
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)
        monkeypatch.setattr(
            "dotenv.load_dotenv",
            lambda *args, **kwargs: real_load_dotenv(dotenv_path=dotenv_path, override=True),
        )

        config_module = self._reload_config_module()

        assert isinstance(config_module.CLOUD_FUNCTIONS_BASE_URL, str)
        assert configured_value == config_module.CLOUD_FUNCTIONS_BASE_URL
        assert isinstance(config_module.DRP_CLIENT_ID, str)
        assert configured_drp_client_id == config_module.DRP_CLIENT_ID

    def test_presence_timing_constants(self):
        """Checks that presenceing timing constants."""
        from config.config import ONLINE_UPDATE_INTERVAL

        expected = 10 * 60 * 1000
        assert expected == ONLINE_UPDATE_INTERVAL

    def test_pyinstaller_spec_packages_dotenv_into_src(self):
        """Checks that frozen builds package .env where config expects it."""
        spec_path = Path(__file__).resolve().parents[2] / "builds" / "G3MExecutable.spec"
        if not spec_path.exists():
            pytest.skip("PyInstaller spec file is not available in this checkout")
        spec_text = spec_path.read_text(encoding="utf-8")

        assert "os.path.join(project_root, 'src', '.env')" in spec_text
        assert "datas_extra.append((env_path, 'src'))" in spec_text

    def test_pyinstaller_spec_keeps_difflib_for_mod_diagnostics(self):
        """Checks that frozen builds keep difflib required by diagnostics UI."""
        spec_path = Path(__file__).resolve().parents[2] / "builds" / "G3MExecutable.spec"
        if not spec_path.exists():
            pytest.skip("PyInstaller spec file is not available in this checkout")
        spec_text = spec_path.read_text(encoding="utf-8")
        dialog_module_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ui"
            / "dialogs"
            / "mod_diagnostics_dialog.py"
        )
        dialog_tree = ast.parse(dialog_module_path.read_text(encoding="utf-8"))

        uses_difflib = False
        for node in ast.walk(dialog_tree):
            if isinstance(node, ast.Import):
                uses_difflib = any(alias.name == "difflib" for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module == "difflib":
                uses_difflib = True
            if uses_difflib:
                break

        assert uses_difflib
        assert "'difflib'" not in spec_text

    def test_pyinstaller_spec_keeps_decimal_for_support_package_statistics(self):
        """Checks that the support package's statistics dependency is not excluded."""
        spec_path = Path(__file__).resolve().parents[2] / "builds" / "G3MExecutable.spec"
        if not spec_path.exists():
            pytest.skip("PyInstaller spec file is not available in this checkout")

        assert "'decimal'" not in spec_path.read_text(encoding="utf-8")

    def test_native_dialogs_do_not_require_tkinter(self):
        """Checks that file dialogs stay on Qt so frozen builds can keep tkinter excluded."""
        native_integration_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "utils"
            / "native_integration.py"
        )
        native_integration_text = native_integration_path.read_text(encoding="utf-8")

        assert "QFileDialog" in native_integration_text
        assert "tkinter" not in native_integration_text

    def test_pyinstaller_spec_does_not_exclude_runtime_imports(self):
        """Checks that frozen builds do not exclude modules imported by runtime code."""
        spec_path = Path(__file__).resolve().parents[2] / "builds" / "G3MExecutable.spec"
        if not spec_path.exists():
            pytest.skip("PyInstaller spec file is not available in this checkout")

        spec_tree = ast.parse(spec_path.read_text(encoding="utf-8"))
        excludes: set[str] = set()
        for node in ast.walk(spec_tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Analysis":
                for keyword in node.keywords:
                    if keyword.arg == "excludes" and isinstance(keyword.value, ast.List):
                        excludes = {
                            element.value
                            for element in keyword.value.elts
                            if isinstance(element, ast.Constant)
                            and isinstance(element.value, str)
                        }
                        break

        runtime_imports: set[str] = set()
        src_root = Path(__file__).resolve().parents[2] / "src"
        for path in src_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    runtime_imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    runtime_imports.add(node.module)

        def _conflicts(import_name: str, excluded_name: str) -> bool:
            return (
                import_name == excluded_name
                or import_name.startswith(f"{excluded_name}.")
            )

        direct_conflicts = sorted(
            f"{runtime_import} <- {excluded}"
            for runtime_import in runtime_imports
            for excluded in excludes
            if _conflicts(runtime_import, excluded)
        )
        assert direct_conflicts == []
