"""Shared helpers for plugin services."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import zipfile
from pathlib import Path
from typing import Any

from models.plugin_models import (
    PLUGIN_API_VERSION,
    PLUGIN_HOOKS,
    PLUGIN_TAGS,
    PluginManifest,
)
from services.localization_service import localization_service

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_RANGE_RE = re.compile(r"^(\^|~|>=|<=|>|<)?(.+)$")


class PluginValidationError(ValueError):
    """Stable validation error."""


def _parse_version(version: str) -> tuple[int, int, int]:
    """Parse a semantic version string into a tuple of (major, minor, patch)."""
    if not _SEMVER_RE.fullmatch(version):
        raise ValueError(f"Invalid semver format: {version}")
    major, minor, patch = map(int, version.split('.'))
    return (major, minor, patch)


def _matches_range(current: str, requirement: str) -> bool:
    """Check if current version matches a semver range requirement."""
    try:
        current_parsed = _parse_version(current)
    except ValueError:
        return False

    if _SEMVER_RE.fullmatch(requirement):
        return current == requirement

    match = _RANGE_RE.match(requirement)
    if not match:
        return False

    prefix, req_version = match.groups()

    try:
        req_parsed = _parse_version(req_version)
    except ValueError:
        return False

    major, minor, patch = current_parsed
    req_major, req_minor, req_patch = req_parsed

    if prefix == "^":
        if major != req_major:
            return False
        if major == 0:
            if req_minor == 0:
                return minor == req_minor and patch == req_patch
            else:
                return minor == req_minor and patch >= req_patch
        else:
            return (minor > req_minor) or (minor == req_minor and patch >= req_patch)

    elif prefix == "~":
        if major != req_major or minor != req_minor:
            return False
        return patch >= req_patch

    elif prefix == ">=":
        return current_parsed >= req_parsed

    elif prefix == ">":
        return current_parsed > req_parsed

    elif prefix == "<=":
        return current_parsed <= req_parsed

    elif prefix == "<":
        return current_parsed < req_parsed

    else:
        return False


def is_version_compatible(current_version: str, requirement: str) -> bool:
    requirement = requirement.strip()
    if not requirement:
        return True
    if not _SEMVER_RE.fullmatch(current_version):
        return False
    return _matches_range(current_version, requirement)


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


def load_manifest(path: str) -> PluginManifest:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    manifest = PluginManifest(
        config_version=int(data.get("config_version", 0) or 0),
        id=_normalized_text(data.get("id")),
        name=_normalized_text(data.get("name")),
        description=_normalized_text(data.get("description")),
        author=_normalized_text(data.get("author")),
        version=_normalized_text(data.get("version")),
        api_version=_normalized_text(data.get("api_version")),
        entry=_normalized_text(data.get("entry")),
        icon=_normalized_text(data.get("icon")),
        homepage=_normalized_text(data.get("homepage")),
        tags=[_normalized_text(tag) for tag in data.get("tags", []) if str(tag).strip()],
        relations={
            _normalized_text(key): _normalized_text(value)
            for key, value in (data.get("relations", {}) or {}).items()
            if str(key).strip() and str(value).strip()
        },
        hooks=[
            _normalized_text(hook) for hook in data.get("hooks", []) if str(hook).strip()
        ],
        settings_schema=data.get("settings_schema", {}) or {},
    )
    validate_manifest(manifest, os.path.dirname(path))
    return manifest


def validate_manifest(manifest: PluginManifest, plugin_dir: str) -> None:
    if manifest.config_version != 1:
        raise PluginValidationError("invalid_config_version")
    for attr in ("id", "name", "description", "author", "version", "api_version", "entry"):
        if not getattr(manifest, attr):
            raise PluginValidationError(f"missing_{attr}")
    if not re.fullmatch(r"[a-z0-9_]+", manifest.id):
        raise PluginValidationError("invalid_id")
    if not _SEMVER_RE.fullmatch(manifest.version):
        raise PluginValidationError("invalid_version")
    if not _SEMVER_RE.fullmatch(manifest.api_version) and not _RANGE_RE.fullmatch(manifest.api_version):
        raise PluginValidationError("invalid_api_version")
    entry_path = resolve_plugin_path(plugin_dir, manifest.entry)
    if not os.path.isfile(entry_path):
        raise PluginValidationError("missing_entry")
    if manifest.icon:
        icon_path = resolve_plugin_path(plugin_dir, manifest.icon)
        if not os.path.isfile(icon_path):
            raise PluginValidationError("missing_icon")
    invalid_tags = [tag for tag in manifest.tags if tag not in PLUGIN_TAGS]
    if invalid_tags:
        raise PluginValidationError("invalid_tags")
    invalid_hooks = [hook for hook in manifest.hooks if hook not in PLUGIN_HOOKS]
    if invalid_hooks:
        raise PluginValidationError("invalid_hooks")
    invalid_relations = [
        relation for relation in manifest.relations.values() if relation not in {"require", "conflict"}
    ]
    if invalid_relations:
        raise PluginValidationError("invalid_relations")


def resolve_plugin_path(plugin_dir: str, relative_path: str) -> str:
    target = os.path.normpath(os.path.join(plugin_dir, relative_path))
    root = os.path.normpath(plugin_dir)
    try:
        if os.path.commonpath([root, target]) != root:
            raise PluginValidationError("path_traversal")
    except ValueError as exc:
        raise PluginValidationError("path_traversal") from exc
    if target == root:
        raise PluginValidationError("path_traversal")
    return target


def load_plugin_factory(plugin_id: str, entry_path: str):
    module_name = f"g3m_plugin_{plugin_id}"
    spec = importlib.util.spec_from_file_location(module_name, entry_path)
    if spec is None or spec.loader is None:
        raise PluginValidationError("invalid_entry_spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = getattr(module, "create_plugin", None)
    if not callable(factory):
        raise PluginValidationError("missing_factory")
    return factory


def safe_extract_zip(archive_path: str, target_dir: str) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            member_path = Path(target_dir, member.filename).resolve()
            if Path(target_dir).resolve() not in member_path.parents and member_path != Path(target_dir).resolve():
                raise PluginValidationError("path_traversal")
        archive.extractall(target_dir)


def load_plugin_langs(plugin_dir: str) -> dict[str, dict]:
    langs: dict[str, dict] = {}
    lang_dir = os.path.join(plugin_dir, "lang")
    if not os.path.isdir(lang_dir):
        return langs

    try:
        available_languages = localization_service.get_available_languages()
        supported_codes = list(available_languages.keys()) if available_languages else ["en"]
    except Exception:
        supported_codes = ["en"]

    for code in supported_codes:
        path = os.path.join(lang_dir, f"lang_{code}.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                langs[code] = json.load(handle)
        except (OSError, json.JSONDecodeError) as e:
            logging.warning("Failed to load plugin language file %s: %s", path, e)
            continue
    return langs


def is_plugin_manifest_compatible(manifest: PluginManifest) -> bool:
    if manifest.api_version:
        return is_version_compatible(PLUGIN_API_VERSION, manifest.api_version)
    return False
