"""Tests for the classified, localized problem texts."""

import pytest

from services.localization_service import tr
from utils.mod.operation_plan import PlanFinding
from utils.problem_text import (
    classify_tool_output,
    describe_finding,
    friendly_merge_error,
)

XDELTA_CHECKSUM = (
    "Failed to apply xdelta 'kaizo_knight.xdelta': xdelta3: target window checksum mismatch: XD3_INVALID_INPUT\n"
    "xdelta3: normally this indicates that the source file is incorrect\n"
    "xdelta exited with code 1"
)


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (XDELTA_CHECKSUM, "wrong_base"),
        ("Integrity validation failed: ROOM.MissingSprite", "wrong_base"),
        ("xdelta3: not a VCDIFF input", "patch_invalid"),
        ("Patch file not found: C:\\mods\\a.xdelta", "missing_file"),
        ("xdelta timed out after 300s and was terminated", "timeout"),
        ("Out of memory while merging: x", "no_memory"),
        ("xdelta3: write failed: No space left on device", "no_space"),
        ("Access to the path 'data.win' is denied.", "access_denied"),
        ("Unsupported patch input 'a.bin' (.bin).", "unsupported_format"),
        ("something nobody classified", "unknown"),
    ],
)
def test_tool_output_is_classified(raw, code):
    assert classify_tool_output(raw) == code


def test_merge_error_hides_raw_tool_text():
    text = friendly_merge_error(XDELTA_CHECKSUM, ["C:/mods/knight/a.xdelta", "C:/mods/b/b.xdelta"], "C:/game/data.win")

    assert "XD3_INVALID_INPUT" not in text
    assert "xdelta3" not in text
    assert "knight/a.xdelta" in text and "game/data.win" in text
    assert tr("problems.tool.wrong_base") in text


def test_finding_text_names_the_operation_and_path():
    finding = PlanFinding("error", "target_missing", 3, "raw", "C:\\Game\\data.win")

    text = describe_finding(finding)

    assert text.startswith(tr("problems.plan.operation", n=3, text="").split(":")[0])
    assert "C:\\Game\\data.win" in text
    assert "raw" not in text


def test_unknown_finding_code_falls_back_to_the_plain_message():
    assert describe_finding(PlanFinding("warning", "brand_new_code", 0, "plain message")) == "plain message"
