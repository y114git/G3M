"""Turn raw tool output and plan findings into short, localized text that says what happened and what to do.

The raw text stays in the log. Only the classified text is shown in dialogs, status bars and reports.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from services.localization_service import tr

# First match wins, so the specific causes come before the broad ones.
_TOOL_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cancelled", re.compile(r"^cancell?ed\.?$", re.I | re.M)),
    ("tool_missing", re.compile(r"xdelta executable not found|no xdelta is bundled", re.I)),
    ("timeout", re.compile(r"timed out", re.I)),
    ("no_memory", re.compile(r"out of memory|malloc:|memoryerror|cannot allocate memory", re.I)),
    ("no_space", re.compile(r"no space left|not enough space|disk full", re.I)),
    (
        "access_denied",
        re.compile(r"access to the path|permission denied|being used by another process|access is denied", re.I),
    ),
    (
        "unsupported_format",
        re.compile(r"unsupported patch input|unsupported file combination|root chunk|too short to hold a form", re.I),
    ),
    (
        "wrong_base",
        re.compile(
            r"checksum mismatch|source file too short|source file is incorrect|wrong data reconstruction|"
            r"integrity validation failed|patch apply failed|resource type\(s\) failed|hash differs|"
            r"does not match the file",
            re.I,
        ),
    ),
    (
        "patch_invalid",
        re.compile(
            r"not a vcdiff|invalid delta indicator|vcdiff input version|overflow (in|while)|window overflows|decode error|invalid patch|"
            r"unsupported resource type in patch|secondary decoder|xd3_invalid|xd3_unimplemented",
            re.I,
        ),
    ),
    (
        "missing_file",
        re.compile(r"file not found|not found:|error reading source|does not exist|no such file|could not find", re.I),
    ),
)


def classify_tool_output(text: object) -> str:
    """Name the cause behind raw G3MTool or xdelta output, or `unknown` when no rule is sure."""
    value = str(text or "")
    for code, pattern in _TOOL_RULES:
        if pattern.search(value):
            return code
    return "unknown"


def friendly_tool_error(text: object) -> str:
    """Localized cause and fix for raw tool output."""
    return tr(f"problems.tool.{classify_tool_output(text)}")


def _short(path: object) -> str:
    """The folder and file name: enough to find a mod file without a long path."""
    parts = str(path).replace(chr(92), "/").rstrip("/").split("/")
    return "/".join(parts[-2:])


def friendly_patch_error(text: object, patch: object = "", target: object = "") -> str:
    """Which patch failed on which game file, why, and what to do."""
    return tr(
        "problems.patch_failed", patch=_short(patch), target=_short(target), reason=friendly_tool_error(text)
    )


def friendly_merge_error(text: object, patches: Sequence[object] = (), target: object = "") -> str:
    """Which patches could not be merged into which game file, why, and what to do."""
    names = [_short(patch) for patch in patches]
    listed = ", ".join(names[:3]) + (f" (+{len(names) - 3})" if len(names) > 3 else "")
    return tr("problems.merge_failed", patches=listed, target=_short(target), reason=friendly_tool_error(text))


def describe_finding(finding) -> str:
    """Localized text of a plan finding: the operation it is about, then what is wrong and what to do."""
    detail = getattr(finding, "detail", "") or ""
    key = f"problems.plan.{finding.code}"
    known = "." not in finding.code and finding.code not in {"operation", "title", "fix", "generic"}
    text = tr(key, detail=detail) if known else f"[{key}]"
    if text == f"[{key}]":  # no text for this code: the generic line carries the plain message
        text = tr("problems.plan.generic", detail=detail or finding.message)
    if finding.operation_index > 0:
        return tr("problems.plan.operation", n=finding.operation_index, text=text)
    return text
