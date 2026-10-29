"""Strict parsing and validation for the portable mod config operation format."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from collections.abc import Iterator, Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from config.config import MOD_DOCUMENTATION_EXTENSIONS
from utils.mod.archive import (
    ArchiveValidationError,
    archive_write_supported,
    split_archive_virtual_path,
)

MOD_CONFIG_VERSION = "2.0.0"
MOD_CONFIG_MAX_BYTES = 4 * 1024 * 1024
MOD_CONFIG_MAX_JSON_DEPTH = 64
MOD_CONFIG_MAX_GROUP_DEPTH = 32
MOD_CONFIG_MAX_LEAVES = 5_000
MOD_CONFIG_MAX_GROUPS = 2_000
MOD_CONFIG_MAX_PLACEHOLDERS = 128
MOD_CONFIG_MAX_RELATIONS = 512
MOD_CONFIG_MAX_AUTHORS = 64
MOD_CONFIG_MAX_TAGS = 64
MOD_CONFIG_MAX_DISPLAY_CHARS = 128
MOD_CONFIG_MAX_DESCRIPTION_CHARS = 16 * 1024
MOD_CONFIG_MAX_URL_CHARS = 2_048
MOD_CONFIG_MAX_PATH_CHARS = 4_096

MOD_CONFIG_TYPES = frozenset(
    {
        "patch",
        "overwrite",
        "soft-overwrite",
        "hard-overwrite",
        "extract",
        "soft-extract",
        "hard-extract",
        "info",
    }
)
MOD_CONFIG_RELATION_MODES = frozenset(
    {
        "before",
        "after",
        "before-step",
        "after-step",
        "before-priority",
        "after-priority",
    }
)
MOD_CONFIG_TAGS = frozenset(
    {"textedit", "customization", "gameplay", "other", "CYOP/AFOM", "FB-Addon"}
)

_ID_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_CUSTOM_PLACEHOLDER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_RELATION_RE = re.compile(
    r"(?P<id>[a-z][a-z0-9_-]{0,63})(?::(?P<mode>[a-z-]+))?\Z"
)
_HASH_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DRIVE_PATH_RE = re.compile(r"[A-Za-z]:/")
_PLACEHOLDER_RE = re.compile(r"\$\{(?P<name>[A-Za-z][A-Za-z0-9_]*)\}")
_DELTARUNE_CHAPTER_TARGET_RE = re.compile(
    r"^\$\{game_path\}/chapter(?P<number>\d+)_(?:windows|mac)(?:/|$)"
)
_BUILTIN_PATHS = frozenset(
    {"mod_path", "game_path", "game_data_path", "user_path"}
)

_REQUIRED_FIELDS = (
    "config_version",
    "id",
    "name",
    "version",
    "authors",
    "game",
    "files",
)
_OPTIONAL_FIELDS = (
    "description",
    "homepage",
    "icon",
    "game_version",
    "tags",
    "placeholders",
    "dependencies",
    "conflicts",
)
_TOP_LEVEL_FIELDS = frozenset((*_REQUIRED_FIELDS, *_OPTIONAL_FIELDS))
_LEAF_FIELDS = frozenset({"source", "target", "type", "source_hash", "target_hash"})
_CANONICAL_FIELD_ORDER = (*_REQUIRED_FIELDS[:-1], *_OPTIONAL_FIELDS, "files")


@dataclass(frozen=True, slots=True)
class DirectOperationPath:
    """A literal filesystem path in a mod operation."""

    operation_index: int
    group_path: tuple[str, ...]
    field: str
    value: str


def iter_mod_config_leaves(
    entries: list[object], group_path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], Mapping[str, object]]]:
    """Yield file leaves in their depth-first execution order."""
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        if "source" in entry or "type" in entry:
            yield group_path, entry
            continue
        if len(entry) != 1:
            continue
        name, children = next(iter(entry.items()))
        if isinstance(name, str) and isinstance(children, list):
            yield from iter_mod_config_leaves(children, (*group_path, name))


def is_direct_absolute_path(value: object) -> bool:
    """Return whether a config path bypasses a placeholder root."""
    return isinstance(value, str) and (
        value.startswith("/") or bool(_DRIVE_PATH_RE.match(value))
    )


def iter_direct_operation_paths(config: Mapping[str, object]) -> Iterator[DirectOperationPath]:
    """Yield source and target fields that use raw absolute paths."""
    files = config.get("files")
    if not isinstance(files, list):
        return
    for index, (group_path, leaf) in enumerate(iter_mod_config_leaves(files), start=1):
        for field in ("source", "target"):
            value = leaf.get(field)
            if isinstance(value, str) and is_direct_absolute_path(value):
                yield DirectOperationPath(index, group_path, field, value)


def config_has_files_for_section(
    config: Mapping[str, object], section_id: str
) -> bool:
    """Return whether a operation config has a non-info operation for a game section."""
    files = config.get("files")
    if not isinstance(files, list):
        return False
    game = config.get("game")
    placeholders = config.get("placeholders")
    aliases = placeholders if isinstance(placeholders, Mapping) else {}
    has_operation = False
    unscoped = False
    chapters: set[str] = set()
    for _group_path, leaf in iter_mod_config_leaves(files):
        if leaf.get("type") == "info":
            continue
        has_operation = True
        target = leaf.get("target")
        if not isinstance(target, str) or game != "deltarune":
            unscoped = True
            continue
        placeholder = _PLACEHOLDER_RE.match(target)
        if placeholder and placeholder.group("name") in aliases:
            alias = aliases[placeholder.group("name")]
            if isinstance(alias, str):
                target = f"{alias}{target[placeholder.end():]}"
        match = _DELTARUNE_CHAPTER_TARGET_RE.match(target)
        if match:
            chapters.add(match.group("number"))
        elif target.startswith("${game_path}/"):
            chapters.add("0")
        else:
            unscoped = True
    if not has_operation:
        return False
    if game != "deltarune" or unscoped:
        return True
    suffix = str(section_id).rsplit("_", 1)[-1]
    return suffix in chapters


@dataclass(frozen=True, slots=True)
class ConfigValidationIssue:
    """One actionable static config validation result."""

    code: str
    path: str
    message: str
    severity: str = "error"
    correction: str = ""

    def __post_init__(self) -> None:
        if not self.correction:
            object.__setattr__(
                self, "correction", f"Correct {self.path}: {self.message}"
            )


class ModConfigValidationError(ValueError):
    """Raised when a operation config cannot be used safely."""

    def __init__(self, issues: tuple[ConfigValidationIssue, ...]) -> None:
        self.issues = issues
        details = [f"{issue.path}: {issue.message}" for issue in issues]
        if len(details) > 10:
            details = [*details[:10], f"... and {len(details) - 10} more"]
        super().__init__("; ".join(details))


class _DuplicateJsonKeyError(ValueError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(key)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(key)
        result[key] = value
    return result


def _contains_forbidden_character(value: str, *, allow_newlines: bool = False) -> bool:
    for character in value:
        if allow_newlines and character == "\n":
            continue
        category = unicodedata.category(character)
        if category in {"Cc", "Cf", "Cs"}:
            return True
    return False


def _is_nfc(value: str) -> bool:
    return value == unicodedata.normalize("NFC", value)


def _append(
    issues: list[ConfigValidationIssue], code: str, path: str, message: str
) -> None:
    issues.append(
        ConfigValidationIssue(
            code,
            path,
            message,
            correction=f"Correct {path}: {message}",
        )
    )


def _validate_display(
    value: object,
    path: str,
    *,
    limit: int,
    issues: list[ConfigValidationIssue],
    allow_newlines: bool = False,
) -> None:
    if not isinstance(value, str):
        _append(issues, "type", path, "must be a string")
        return
    if not value:
        _append(issues, "empty", path, "must not be empty")
    if len(value) > limit:
        _append(issues, "too_long", path, f"must be at most {limit} characters")
    if value != value.strip() and not allow_newlines:
        _append(issues, "surrounding_whitespace", path, "must not have surrounding whitespace")
    if "\r" in value:
        _append(issues, "line_endings", path, "must use LF line endings")
    if _contains_forbidden_character(value, allow_newlines=allow_newlines):
        _append(issues, "forbidden_character", path, "contains a control or format character")
    if not _is_nfc(value):
        _append(issues, "not_nfc", path, "must use Unicode NFC")


def _validate_id(value: object, path: str, issues: list[ConfigValidationIssue]) -> str | None:
    if not isinstance(value, str):
        _append(issues, "type", path, "must be a lowercase ASCII mod ID")
        return None
    if not _ID_RE.fullmatch(value):
        _append(
            issues,
            "invalid_id",
            path,
            "must match [a-z][a-z0-9_-]{0,63}",
        )
        return None
    if value == "self":
        _append(issues, "reserved_id", path, "must not use the reserved ID 'self'")
        return None
    return value


def _validate_url(value: object, path: str, issues: list[ConfigValidationIssue]) -> None:
    if not isinstance(value, str):
        _append(issues, "type", path, "must be an absolute http or https URL")
        return
    if not value or len(value) > MOD_CONFIG_MAX_URL_CHARS:
        _append(issues, "invalid_url", path, "must be a non-empty URL up to 2048 characters")
        return
    if any(character.isspace() for character in value) or _contains_forbidden_character(value):
        _append(issues, "invalid_url", path, "must not contain whitespace or control characters")
        return
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        _append(issues, "invalid_url", path, "must be a valid absolute http or https URL")
        return
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        _append(issues, "invalid_url", path, "must be an absolute http or https URL without credentials")


def _validate_hash(value: object, path: str, issues: list[ConfigValidationIssue]) -> None:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        _append(issues, "invalid_hash", path, "must be sha256: followed by 64 lowercase hexadecimal characters")


def _path_error(path_value: str) -> str | None:
    if not path_value:
        return "must not be empty"
    if len(path_value) > MOD_CONFIG_MAX_PATH_CHARS:
        return "must be at most 4096 characters"
    if path_value != path_value.strip():
        return "must not have surrounding whitespace"
    if "\\" in path_value:
        return "must use / as its separator"
    if _contains_forbidden_character(path_value):
        return "contains a control or format character"
    if "//" in path_value:
        return "must not contain empty path segments"
    if any(part in {".", ".."} for part in path_value.split("/")):
        return "must not contain . or .. path segments"
    return None


def _path_root(path_value: str) -> tuple[str | None, str | None]:
    """Return the placeholder root and suffix, or ``(None, None)`` for absolute paths."""
    match = _PLACEHOLDER_RE.match(path_value)
    if match and match.start() == 0:
        root = match.group("name")
        return root, path_value[match.end() :]
    return None, None


def mod_local_relative_path(
    path_value: str, placeholders: Mapping[str, object]
) -> str | None:
    """Resolve a `${mod_path}` path or alias to a safe relative path."""
    root, suffix = _path_root(path_value)
    if root == "mod_path":
        base = ""
    else:
        alias = placeholders.get(root) if root is not None else None
        if not isinstance(alias, str):
            return None
        alias_root, base = _path_root(alias)
        if alias_root != "mod_path":
            return None
    return "/".join(part.strip("/") for part in (base, suffix) if part)


def portable_user_path(path: str) -> str:
    """Replace only the current user's normalized home-directory prefix."""
    value = str(path or "").replace("\\", "/")
    home = os.path.normpath(os.path.expanduser("~")).replace("\\", "/").rstrip("/")
    normalized = os.path.normpath(value).replace("\\", "/")
    if os.path.normcase(normalized) == os.path.normcase(home):
        return "${user_path}"
    if os.path.normcase(normalized).startswith(os.path.normcase(f"{home}/")):
        return f"${{user_path}}/{normalized[len(home) + 1:]}"
    return value


def _validate_path(
    value: object,
    path: str,
    *,
    is_target: bool,
    placeholders: Mapping[str, str],
    issues: list[ConfigValidationIssue],
) -> None:
    if not isinstance(value, str):
        _append(issues, "type", path, "must be a path string")
        return
    error = _path_error(value)
    if error:
        _append(issues, "invalid_path", path, error)
        return

    try:
        virtual_path = split_archive_virtual_path(value)
    except ArchiveValidationError as archive_error:
        _append(issues, "invalid_archive_path", path, str(archive_error))
        return
    if is_target and virtual_path is not None and not archive_write_supported(virtual_path.archive):
        _append(issues, "target_archive_write", path, "targets inside this archive format cannot be written")
        return

    placeholder_names = [
        match.group("name") for match in _PLACEHOLDER_RE.finditer(value)
    ]
    root, suffix = _path_root(value)
    if root is not None:
        if len(placeholder_names) != 1 or root not in {*_BUILTIN_PATHS, *placeholders}:
            _append(issues, "invalid_placeholder", path, "must start with one known path placeholder")
            return
        if not suffix or not suffix.startswith("/"):
            _append(issues, "invalid_path", path, "must contain a path below its placeholder root")
            return
        if root == "mod_path" and is_target:
            _append(issues, "invalid_target_root", path, "must not target the mod directory")
            return
        if root in placeholders and is_target and placeholders[root].startswith("${mod_path}"):
            _append(issues, "invalid_target_root", path, "must not target a mod-path custom placeholder")
            return
        return

    if placeholder_names:
        _append(issues, "invalid_placeholder", path, "placeholders may only appear at the start of a path")
        return
    if not (_DRIVE_PATH_RE.match(value) or value.startswith("/")):
        _append(issues, "relative_path", path, "must use a placeholder root or an absolute path")
    elif value.startswith("//"):
        _append(issues, "invalid_path", path, "must not use a network or device path")


def _validate_custom_placeholders(
    value: object, issues: list[ConfigValidationIssue]
) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        _append(issues, "type", "placeholders", "must be an object of custom placeholders")
        return {}
    if not value:
        _append(issues, "empty", "placeholders", "must be omitted when empty")
        return {}
    if len(value) > MOD_CONFIG_MAX_PLACEHOLDERS:
        _append(issues, "too_many", "placeholders", "contains too many entries")

    result: dict[str, str] = {}
    seen_names: set[str] = set()
    for name, raw_value in value.items():
        path = f"placeholders.{name}"
        if not isinstance(name, str) or not _CUSTOM_PLACEHOLDER_RE.fullmatch(name):
            _append(issues, "invalid_custom_placeholder", path, "must use ASCII letters, digits, or underscores and start with a letter")
            continue
        normalized_name = name.casefold()
        if normalized_name in _BUILTIN_PATHS:
            _append(issues, "reserved_custom_placeholder", path, "must not shadow a built-in placeholder")
            continue
        if normalized_name in seen_names:
            _append(issues, "duplicate_custom_placeholder", path, "duplicates another custom placeholder")
            continue
        seen_names.add(normalized_name)
        if not isinstance(raw_value, str):
            _append(issues, "type", path, "must be a path string")
            continue
        error = _path_error(raw_value)
        root, suffix = _path_root(raw_value)
        if error:
            _append(issues, "invalid_custom_placeholder", path, error)
        elif root not in _BUILTIN_PATHS or not suffix or not suffix.startswith("/"):
            _append(issues, "invalid_custom_placeholder", path, "must start with one built-in root and a path suffix")
        elif len(_PLACEHOLDER_RE.findall(raw_value)) != 1:
            _append(issues, "invalid_custom_placeholder", path, "must not contain nested placeholders")
        else:
            result[name] = raw_value
    return result


def _validate_relations(
    config: Mapping[str, object],
    config_id: str | None,
    issues: list[ConfigValidationIssue],
) -> None:
    relation_ids: dict[str, set[str]] = {}
    for field in ("dependencies", "conflicts"):
        raw_items = config.get(field)
        if raw_items is None:
            relation_ids[field] = set()
            continue
        if not isinstance(raw_items, list):
            _append(issues, "type", field, "must be an array of mod IDs or ID:mode entries")
            relation_ids[field] = set()
            continue
        if not raw_items:
            _append(issues, "empty", field, "must be omitted when empty")
        if len(raw_items) > MOD_CONFIG_MAX_RELATIONS:
            _append(issues, "too_many", field, "contains too many entries")
        seen: set[str] = set()
        for index, item in enumerate(raw_items):
            path = f"{field}[{index}]"
            if not isinstance(item, str):
                _append(issues, "type", path, "must be a mod ID or ID:mode entry")
                continue
            match = _RELATION_RE.fullmatch(item)
            if not match:
                _append(issues, "invalid_relation", path, "must be <id> or <id>:<mode>")
                continue
            relation_id = match.group("id")
            mode = match.group("mode")
            if relation_id == "self":
                _append(issues, "reserved_id", path, "must not use the reserved ID 'self'")
            if mode is not None and mode not in MOD_CONFIG_RELATION_MODES:
                _append(issues, "invalid_relation_mode", path, "uses an unsupported relationship mode")
            if relation_id == config_id:
                _append(issues, "self_relation", path, "must not reference this mod")
            if relation_id in seen:
                _append(issues, "duplicate_relation", path, "duplicates an earlier relation ID")
            seen.add(relation_id)
        relation_ids[field] = seen

    overlap = relation_ids["dependencies"] & relation_ids["conflicts"]
    for relation_id in sorted(overlap):
        _append(
            issues,
            "contradictory_relation",
            "dependencies",
            f"must not also list {relation_id!r} as a conflict",
        )


def _validate_leaf(
    value: Mapping[str, object],
    path: str,
    custom_placeholders: Mapping[str, str],
    issues: list[ConfigValidationIssue],
) -> None:
    for key in value:
        if key not in _LEAF_FIELDS:
            _append(issues, "unknown_field", f"{path}.{key}", "is not valid for a file entry")
    source = value.get("source")
    operation_type = value.get("type")
    if not isinstance(operation_type, str):
        operation_type = None
    if "source" not in value:
        _append(issues, "missing_field", path, "requires source")
    else:
        _validate_path(
            source,
            f"{path}.source",
            is_target=False,
            placeholders=custom_placeholders,
            issues=issues,
        )
    if operation_type not in MOD_CONFIG_TYPES:
        _append(issues, "invalid_type", f"{path}.type", "must be a supported file operation type")
    has_target = "target" in value
    if operation_type == "info":
        if has_target:
            _append(issues, "forbidden_field", f"{path}.target", "is not valid for an info entry")
        if "target_hash" in value:
            _append(issues, "forbidden_field", f"{path}.target_hash", "is not valid for an info entry")
        if isinstance(source, str):
            source_root, _ = _path_root(source)
            alias = custom_placeholders.get(source_root, "") if source_root else ""
            is_mod_source = source_root == "mod_path" or (
                isinstance(alias, str) and alias.startswith("${mod_path}/")
            )
            if not is_mod_source or source.endswith("/"):
                _append(
                    issues,
                    "info_source",
                    f"{path}.source",
                    "must be a file inside ${mod_path}",
                )
            elif Path(source).suffix.casefold() not in MOD_DOCUMENTATION_EXTENSIONS:
                _append(
                    issues,
                    "info_extension",
                    f"{path}.source",
                    "must use a supported documentation file extension",
                )
    elif operation_type in MOD_CONFIG_TYPES:
        if not has_target:
            _append(issues, "missing_field", path, "requires target")
        else:
            _validate_path(
                value["target"],
                f"{path}.target",
                is_target=True,
                placeholders=custom_placeholders,
                issues=issues,
            )
            target = value["target"]
            if operation_type in {"extract", "soft-extract", "hard-extract"} and isinstance(target, str):
                lzma_target = target.casefold().endswith(".lzma")
                if operation_type == "hard-extract" and lzma_target:
                    _append(issues, "target_kind", f"{path}.target", "hard-extract cannot target an LZMA stream")
                elif not lzma_target and not target.endswith("/"):
                    _append(issues, "target_kind", f"{path}.target", "extract requires a directory target")
    if operation_type == "patch" and isinstance(source, str) and source.endswith("/"):
        _append(issues, "source_kind", f"{path}.source", "patch requires a file source")
    if operation_type == "patch" and has_target and isinstance(value["target"], str) and value["target"].endswith("/"):
        _append(issues, "target_kind", f"{path}.target", "patch requires a file target")
    if "source_hash" in value:
        _validate_hash(value["source_hash"], f"{path}.source_hash", issues)
    if "target_hash" in value and operation_type != "info":
        _validate_hash(value["target_hash"], f"{path}.target_hash", issues)


def _validate_files(
    files: object,
    custom_placeholders: Mapping[str, str],
    issues: list[ConfigValidationIssue],
) -> None:
    if not isinstance(files, list):
        _append(issues, "type", "files", "must be an ordered array")
        return

    group_names: set[str] = set()
    counters = {"leaves": 0, "groups": 0}

    def visit(items: list[object], path: str, depth: int) -> None:
        if depth > MOD_CONFIG_MAX_GROUP_DEPTH:
            _append(issues, "group_depth", path, "exceeds the maximum group depth")
            return
        for index, item in enumerate(items):
            item_path = f"{path}[{index}]"
            if not isinstance(item, Mapping):
                _append(issues, "type", item_path, "must be a file entry or named group")
                continue
            if "source" in item or "type" in item:
                counters["leaves"] += 1
                _validate_leaf(item, item_path, custom_placeholders, issues)
                continue
            if len(item) != 1:
                _append(issues, "invalid_group", item_path, "must contain exactly one group name")
                continue
            name, children = next(iter(item.items()))
            _validate_display(
                name,
                f"{item_path}.name",
                limit=MOD_CONFIG_MAX_DISPLAY_CHARS,
                issues=issues,
            )
            if isinstance(name, str):
                normalized_name = unicodedata.normalize("NFC", name)
                if normalized_name in group_names:
                    _append(issues, "duplicate_group", item_path, "duplicates an earlier group name")
                group_names.add(normalized_name)
            counters["groups"] += 1
            if not isinstance(children, list):
                _append(issues, "type", item_path, "group contents must be an array")
                continue
            visit(children, item_path, depth + 1)

    visit(files, "files", 1)
    if counters["leaves"] > MOD_CONFIG_MAX_LEAVES:
        _append(issues, "too_many", "files", "contains too many file entries")
    if counters["groups"] > MOD_CONFIG_MAX_GROUPS:
        _append(issues, "too_many", "files", "contains too many groups")


def validate_mod_config(config: object) -> tuple[ConfigValidationIssue, ...]:
    """Return all static validation issues for a operation config without coercion."""
    issues: list[ConfigValidationIssue] = []
    if not isinstance(config, Mapping):
        return (ConfigValidationIssue("type", "$", "must be a JSON object"),)
    if _json_depth(config) > MOD_CONFIG_MAX_JSON_DEPTH:
        _append(issues, "json_depth", "$", "exceeds the maximum JSON nesting depth")
        return tuple(issues)

    for key in config:
        if key not in _TOP_LEVEL_FIELDS:
            _append(issues, "unknown_field", str(key), "is not a valid config field")
    for field in _REQUIRED_FIELDS:
        if field not in config:
            _append(issues, "missing_field", field, "is required")

    if config.get("config_version") != MOD_CONFIG_VERSION:
        _append(issues, "config_version", "config_version", "must be exactly 2.0.0")
    config_id = _validate_id(config.get("id"), "id", issues)
    _validate_display(
        config.get("name"),
        "name",
        limit=MOD_CONFIG_MAX_DISPLAY_CHARS,
        issues=issues,
    )
    _validate_display(
        config.get("version"),
        "version",
        limit=MOD_CONFIG_MAX_DISPLAY_CHARS,
        issues=issues,
    )
    _validate_id(config.get("game"), "game", issues)

    authors = config.get("authors")
    if not isinstance(authors, list):
        _append(issues, "type", "authors", "must be an array")
    else:
        if len(authors) > MOD_CONFIG_MAX_AUTHORS:
            _append(issues, "too_many", "authors", "contains too many authors")
        for index, author_name in enumerate(authors):
            _validate_display(
                author_name,
                f"authors[{index}]",
                limit=MOD_CONFIG_MAX_DISPLAY_CHARS,
                issues=issues,
            )

    if "description" in config:
        _validate_display(
            config["description"],
            "description",
            limit=MOD_CONFIG_MAX_DESCRIPTION_CHARS,
            issues=issues,
            allow_newlines=True,
        )
    if "homepage" in config:
        _validate_url(config["homepage"], "homepage", issues)

    custom_placeholders = _validate_custom_placeholders(
        config.get("placeholders"), issues
    )
    if "icon" in config:
        icon = config["icon"]
        if isinstance(icon, str) and icon.startswith(("http://", "https://")):
            _validate_url(icon, "icon", issues)
        else:
            _validate_path(
                icon,
                "icon",
                is_target=False,
                placeholders=custom_placeholders,
                issues=issues,
            )
            if isinstance(icon, str) and not mod_local_relative_path(
                icon, custom_placeholders
            ):
                _append(issues, "invalid_icon", "icon", "must identify a file inside ${mod_path}")

    if "game_version" in config:
        _validate_display(
            config["game_version"],
            "game_version",
            limit=MOD_CONFIG_MAX_DISPLAY_CHARS,
            issues=issues,
        )
    if "tags" in config:
        tags = config["tags"]
        if not isinstance(tags, list):
            _append(issues, "type", "tags", "must be an array")
        else:
            if not tags:
                _append(issues, "empty", "tags", "must be omitted when empty")
            if len(tags) > MOD_CONFIG_MAX_TAGS:
                _append(issues, "too_many", "tags", "contains too many entries")
            seen_tags: set[str] = set()
            for index, tag in enumerate(tags):
                tag_path = f"tags[{index}]"
                if not isinstance(tag, str) or tag not in MOD_CONFIG_TAGS:
                    _append(issues, "invalid_tag", tag_path, "must be a supported tag")
                elif tag in seen_tags:
                    _append(issues, "duplicate_tag", tag_path, "duplicates an earlier tag")
                if isinstance(tag, str):
                    seen_tags.add(tag)

    _validate_relations(config, config_id, issues)
    _validate_files(config.get("files"), custom_placeholders, issues)
    return tuple(issues)


def _json_depth(value: object, depth: int = 0) -> int:
    if depth > MOD_CONFIG_MAX_JSON_DEPTH:
        return 0
    if isinstance(value, Mapping):
        return 1 + max((_json_depth(item, depth + 1) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_json_depth(item, depth + 1) for item in value), default=0)
    return 0


def parse_mod_config(config: object) -> dict[str, object]:
    """Validate and return a deep-copied operation config in canonical key order."""
    issues = validate_mod_config(config)
    if issues:
        raise ModConfigValidationError(issues)
    if not isinstance(config, Mapping):
        raise ModConfigValidationError(
            (ConfigValidationIssue("type", "$", "must be a JSON object"),)
        )
    return {key: deepcopy(config[key]) for key in _CANONICAL_FIELD_ORDER if key in config}


def read_mod_config_bytes(path: str | Path) -> bytes:
    """Read a bounded config document before decoding or migrating it."""
    try:
        with Path(path).open("rb") as source:
            raw = source.read(MOD_CONFIG_MAX_BYTES + 1)
    except OSError as error:
        raise ModConfigValidationError(
            (ConfigValidationIssue("read_error", "$", f"cannot read config: {error}"),)
        ) from error
    if len(raw) > MOD_CONFIG_MAX_BYTES:
        raise ModConfigValidationError(
            (ConfigValidationIssue("too_large", "$", "exceeds the 4 MiB size limit"),)
        )
    return raw


def load_mod_config(path: str | Path) -> dict[str, object]:
    """Read one config file with a size limit and duplicate-key rejection."""
    try:
        raw = read_mod_config_bytes(path).decode("utf-8")
    except UnicodeDecodeError as error:
        raise ModConfigValidationError(
            (ConfigValidationIssue("invalid_utf8", "$", "must be UTF-8"),)
        ) from error
    try:
        parsed = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateJsonKeyError as error:
        raise ModConfigValidationError(
            (ConfigValidationIssue("duplicate_key", "$", f"duplicates JSON key {error.key!r}"),)
        ) from error
    except json.JSONDecodeError as error:
        raise ModConfigValidationError(
            (ConfigValidationIssue("invalid_json", "$", f"invalid JSON: {error.msg}"),)
        ) from error
    except RecursionError as error:
        raise ModConfigValidationError(
            (ConfigValidationIssue("json_depth", "$", "exceeds the maximum JSON nesting depth"),)
        ) from error
    return parse_mod_config(parsed)


def newer_config_mod_name(path: str | Path) -> str | None:
    """Name of the mod when its config_version is above the one this G3M reads, otherwise None."""
    try:
        data = json.loads(read_mod_config_bytes(path).decode("utf-8"))
    except ValueError:
        return None
    version = data.get("config_version") if isinstance(data, dict) else None
    if not isinstance(version, str):
        return None
    parts = tuple(int(part) for part in re.findall(r"\d+", version)[:3])
    if parts <= tuple(int(part) for part in MOD_CONFIG_VERSION.split(".")):
        return None
    return str(data.get("name") or data.get("id") or Path(path).parent.name)


def _write_config_payload(config_path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{config_path.name}.", suffix=".tmp", dir=config_path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, config_path)
    except OSError as error:
        raise ModConfigValidationError(
            (ConfigValidationIssue("write_error", "$", f"cannot replace config: {error}"),)
        ) from error
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)


def write_mod_config(
    path: str | Path,
    config: Mapping[str, object],
    *,
    indent: int = 2,
) -> dict[str, object]:
    """Atomically write one validated current-format config."""
    config_path = Path(path)
    prepared = parse_mod_config(config)
    payload = (json.dumps(prepared, ensure_ascii=False, indent=indent) + "\n").encode("utf-8")
    _write_config_payload(config_path, payload)
    return prepared
