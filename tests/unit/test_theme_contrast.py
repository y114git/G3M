import json
import zipfile
from pathlib import Path

from config.config import DEFAULT_COLORS

THEMES_DIR = Path(__file__).resolve().parents[2] / "src" / "assets" / "themes"


def _luminance(color: str) -> float:
    value = color.lstrip("#")[-6:]
    channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_bundled_theme_text_contrast() -> None:
    setting_names = {
        "background": "custom_background_color",
        "elements": "custom_elements_color",
        "hover": "custom_hover_color",
        "main_text": "custom_main_text_color",
        "secondary_text": "custom_secondary_text_color",
    }
    for archive_path in (
        THEMES_DIR / "PIZZAG3M.zip",
        THEMES_DIR / "SUGARYG3M.zip",
    ):
        with zipfile.ZipFile(archive_path) as archive:
            config = json.loads(archive.read("theme_config.json"))
        colors = {
            role: config.get(setting_name) or DEFAULT_COLORS[role]
            for role, setting_name in setting_names.items()
        }
        for foreground, background in (
            ("main_text", "background"),
            ("main_text", "elements"),
            ("main_text", "hover"),
            ("secondary_text", "background"),
            ("secondary_text", "elements"),
        ):
            ratio = _contrast(colors[foreground], colors[background])
            assert ratio >= 4.5, (
                f"{archive_path.name}: {foreground} on {background} is {ratio:.2f}:1"
            )
