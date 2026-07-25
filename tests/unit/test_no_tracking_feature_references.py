"""Guard against restoring the removed usage-reporting feature."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_RECORDS = {"CHANGELOG.md"}
FORBIDDEN = (
    "analy" + "tics",
    "analy" + "tic",
    "аналит" + "ик",
)


def _tracked_text_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=ROOT,
        text=True,
    )
    paths = [ROOT / line for line in output.splitlines() if line]
    paths.extend(
        path
        for path in (ROOT / "functions").rglob("*")
        if path.is_file()
        and not {"venv", "__pycache__"}.intersection(path.relative_to(ROOT).parts)
    )
    return paths


def test_removed_usage_reporting_has_no_tracked_references() -> None:
    matches: list[str] = []
    this_file = Path(__file__).resolve()

    for path in _tracked_text_files():
        if (
            path.resolve() == this_file
            or path.name in HISTORICAL_RECORDS
            or not path.is_file()
        ):
            continue
        try:
            content = path.read_text(encoding="utf-8").casefold()
        except UnicodeDecodeError, OSError:
            continue
        for token in FORBIDDEN:
            if token.casefold() in content:
                matches.append(f"{path.relative_to(ROOT)}: {token}")

    assert not matches, "Removed usage-reporting references remain:\n" + "\n".join(
        matches
    )
