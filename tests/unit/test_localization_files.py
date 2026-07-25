"""Unit tests for test localization files."""

import ast
import hashlib
import json
import re
import zipfile
from pathlib import Path

LANG_DIR = Path(__file__).resolve().parents[2] / "src" / "assets" / "lang"
PLUGIN_DIR = Path(__file__).resolve().parents[2] / "catalog" / "plugins"
UI_DIR = Path(__file__).resolve().parents[2] / "src" / "ui"


def test_localized_dialogs_expose_live_relocalization() -> None:
    """Prevent persistent dialog text from becoming restart-only again."""
    missing: list[str] = []
    for path in UI_DIR.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            is_dialog = any(
                ast.unparse(base).endswith("QDialog") for base in node.bases
            )
            if not is_dialog or "tr(" not in (
                ast.get_source_segment(source, node) or ""
            ):
                continue
            methods = {
                item.name for item in node.body if isinstance(item, ast.FunctionDef)
            }
            if "relocalize_ui" not in methods:
                missing.append(f"{path.relative_to(UI_DIR)}:{node.name}")
    assert not missing, "Localized dialogs without relocalize_ui(): " + ", ".join(
        missing
    )


def _flatten_keys(data: dict, prefix: str = "") -> dict[str, str]:
    keys = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys.update(_flatten_keys(value, full_key))
        else:
            keys[full_key] = value
    return keys


def _normalized_text_bytes(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _is_text_bytes(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _semantic_file_bytes(data: bytes) -> bytes:
    if _is_text_bytes(data):
        return _normalized_text_bytes(data)
    return data


def _plugin_file_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    return _semantic_file_bytes(data)


def test_all_language_files_have_same_translation_keys():
    """Checks that every shipped language contains every English key."""
    english_keys = set(
        _flatten_keys(json.loads((LANG_DIR / "lang_en.json").read_text("utf-8")))
    )

    for lang_path in LANG_DIR.glob("lang_*.json"):
        keys = set(_flatten_keys(json.loads(lang_path.read_text("utf-8"))))
        assert keys == english_keys, (
            f"{lang_path.name} localization keys differ from English. "
            f"Missing: {sorted(english_keys - keys)}. Extra: {sorted(keys - english_keys)}"
        )


def test_all_language_files_keep_the_english_top_level_order():
    """Checks that top-level localization sections stay aligned across languages."""
    english_order = list(json.loads((LANG_DIR / "lang_en.json").read_text("utf-8")))

    for lang_path in LANG_DIR.glob("lang_*.json"):
        order = list(json.loads(lang_path.read_text("utf-8")))
        assert order == english_order, (
            f"{lang_path.name} top-level order differs from English. "
            f"Expected: {english_order}. Got: {order}"
        )


def test_shipped_default_font_name_is_explicit():
    """Checks that bundled language metadata uses the explicit default font name."""
    for lang_path in LANG_DIR.glob("lang_*.json"):
        metadata = json.loads(lang_path.read_text("utf-8"))["metadata"]
        font_name = metadata.get("font", "")
        assert font_name != "main.ttf", f"{lang_path.name} still references main.ttf"


def test_language_files_do_not_ship_raw_localization_keys_as_text():
    """Checks that visible translations are not placeholder localization keys."""
    raw_key_pattern = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")

    for lang_path in LANG_DIR.glob("lang_*.json"):
        flattened = _flatten_keys(json.loads(lang_path.read_text("utf-8")))
        raw_values = [
            f"{key}={value}"
            for key, value in flattened.items()
            if isinstance(value, str)
            and key not in {"metadata.font"}
            and (raw_key_pattern.fullmatch(value) or value == f"[{key}]")
        ]
        assert not raw_values, (
            f"{lang_path.name} has raw localization values: {raw_values}"
        )


def test_plugin_language_files_match_their_english_keys():
    """Checks that every plugin language file contains the same keys as its English base."""
    for plugin_lang_dir in PLUGIN_DIR.glob("*/lang"):
        en_path = plugin_lang_dir / "lang_en.json"
        if not en_path.is_file():
            continue
        english_keys = set(_flatten_keys(json.loads(en_path.read_text("utf-8"))))
        for lang_path in plugin_lang_dir.glob("lang_*.json"):
            keys = set(_flatten_keys(json.loads(lang_path.read_text("utf-8"))))
            assert keys == english_keys, (
                f"{lang_path.relative_to(PLUGIN_DIR.parent)} localization keys differ from English. "
                f"Missing: {sorted(english_keys - keys)}. Extra: {sorted(keys - english_keys)}"
            )


def test_plugin_archives_include_korean_localizations():
    """Checks that shipped plugin archives include the Korean localization files."""
    for plugin_dir in PLUGIN_DIR.iterdir():
        if not plugin_dir.is_dir():
            continue
        archive_path = PLUGIN_DIR / f"{plugin_dir.name}.zip"
        if not archive_path.is_file():
            continue
        expected_entry = "lang/lang_ko.json"
        with zipfile.ZipFile(archive_path) as archive:
            entries = {info.filename for info in archive.infolist()}
        assert expected_entry in entries, (
            f"{archive_path.name} is missing {expected_entry}"
        )


def test_plugin_archives_match_source_folders_without_python_cache():
    """Checks that shipped plugin archives contain current source files only."""
    ignored_suffixes = (".pyc", ".pyo")
    ignored_parts = {"__pycache__"}

    for plugin_dir in PLUGIN_DIR.iterdir():
        if not plugin_dir.is_dir():
            continue
        archive_path = PLUGIN_DIR / f"{plugin_dir.name}.zip"
        if not archive_path.is_file():
            continue

        source_files = {
            path.relative_to(plugin_dir).as_posix(): hashlib.sha256(
                _plugin_file_bytes(path)
            ).hexdigest()
            for path in plugin_dir.rglob("*")
            if path.is_file()
            and ignored_parts.isdisjoint(path.relative_to(plugin_dir).parts)
            and not path.name.endswith(ignored_suffixes)
        }
        with zipfile.ZipFile(archive_path) as archive:
            archived_files = {
                info.filename: hashlib.sha256(
                    _semantic_file_bytes(archive.read(info.filename))
                ).hexdigest()
                for info in archive.infolist()
                if not info.is_dir()
            }

        forbidden = [
            name
            for name in archived_files
            if "__pycache__" in Path(name).parts or name.endswith(ignored_suffixes)
        ]
        source_names = set(source_files)
        archived_names = set(archived_files)
        assert not forbidden, (
            f"{archive_path.name} ships Python cache files: {forbidden}"
        )
        assert archived_files == source_files, (
            f"{archive_path.name} does not match {plugin_dir.name}. "
            f"Missing: {sorted(source_names - archived_names)}. "
            f"Extra: {sorted(archived_names - source_names)}. "
            f"Changed: {sorted(k for k in source_files.keys() & archived_files.keys() if source_files[k] != archived_files[k])}"
        )


def test_plugin_language_files_do_not_ship_raw_localization_keys_as_text():
    """Checks that plugin translations do not expose raw localization keys as visible text."""
    raw_key_pattern = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")

    for plugin_lang_dir in PLUGIN_DIR.glob("*/lang"):
        for lang_path in plugin_lang_dir.glob("lang_*.json"):
            flattened = _flatten_keys(json.loads(lang_path.read_text("utf-8")))
            raw_values = [
                f"{key}={value}"
                for key, value in flattened.items()
                if isinstance(value, str)
                and (raw_key_pattern.fullmatch(value) or value == f"[{key}]")
            ]
            assert not raw_values, (
                f"{lang_path.relative_to(PLUGIN_DIR.parent)} has raw localization values: {raw_values}"
            )
