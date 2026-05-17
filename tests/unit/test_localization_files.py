import json
import re
from pathlib import Path

LANG_DIR = Path(__file__).resolve().parents[2] / "src" / "assets" / "lang"
PLUGIN_DIR = Path(__file__).resolve().parents[2] / "catalog" / "plugins"


def _flatten_keys(data: dict, prefix: str = "") -> dict[str, str]:
    keys = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys.update(_flatten_keys(value, full_key))
        else:
            keys[full_key] = value
    return keys


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
        assert not raw_values, f"{lang_path.name} has raw localization values: {raw_values}"


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
