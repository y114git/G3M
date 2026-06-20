"""Strict archive detection and G3M conversion for FRICKBEARS3 addons."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from typing import Any

from utils.file_utils import (
    get_unique_mod_dir,
    remove_archive_extension,
    sanitize_filename,
    save_json,
)
from utils.mod.config_parser import build_mod_config_data

_SIGNATURE_FILES = (
    "opening_dialogue.txt",
    "icon.png",
    "portrait.png",
    "selection.png",
    "reflection.png",
    "silhouette.png",
    "outside.png",
)


@dataclass(slots=True)
class Frickbears3AddonsInspection:
    eligible: bool
    layout: str = ""
    guard_root_dirs: list[str] = field(default_factory=list)
    reason: str = ""


class Frickbears3AddonsService:
    """Detect strict FRICKBEARS3 addon layouts and convert them into G3M mods."""

    def inspect_extracted_archive(self, extract_dir: str) -> Frickbears3AddonsInspection:
        if not extract_dir or not os.path.isdir(extract_dir):
            return Frickbears3AddonsInspection(False, reason="Extracted archive directory does not exist")

        root_entries = sorted(os.listdir(extract_dir))
        if not root_entries:
            return Frickbears3AddonsInspection(False, reason="Archive is empty")

        if self._is_valid_addon_root(extract_dir):
            return Frickbears3AddonsInspection(True, layout="flat_root", guard_root_dirs=[extract_dir])

        root_dirs: list[str] = []
        for entry in root_entries:
            entry_path = os.path.join(extract_dir, entry)
            if not os.path.isdir(entry_path):
                return Frickbears3AddonsInspection(False, reason="Archive root contains files outside addon folders")
            if not self._is_valid_addon_root(entry_path):
                return Frickbears3AddonsInspection(False, reason=f"Folder is not a valid addon root: {entry}")
            root_dirs.append(entry_path)
        return Frickbears3AddonsInspection(
            bool(root_dirs),
            layout="single_root" if len(root_dirs) == 1 else "multi_root",
            guard_root_dirs=root_dirs,
        )

    def convert_extracted_archive(
        self,
        extract_dir: str,
        mods_dir: str,
        *,
        source_file_path: str | None = None,
        gamebanana_metadata: dict[str, Any] | None = None,
    ) -> str:
        inspection = self.inspect_extracted_archive(extract_dir)
        if not inspection.eligible:
            raise ValueError(inspection.reason or "Archive is not a valid FRICKBEARS3 addon")
        if not mods_dir:
            raise ValueError("Mods directory is not configured")

        metadata = dict(gamebanana_metadata or {})
        mod_name = self._resolve_mod_name(
            inspection.guard_root_dirs,
            source_file_path=source_file_path,
            metadata=metadata,
        )
        target_mod_dir = os.path.join(mods_dir, get_unique_mod_dir(mods_dir, mod_name))
        os.makedirs(target_mod_dir, exist_ok=True)

        addons_root = os.path.join(target_mod_dir, "addons")
        os.makedirs(addons_root, exist_ok=True)
        for root_dir in inspection.guard_root_dirs:
            guard_name = self._resolve_guard_folder_name(root_dir)
            shutil.copytree(root_dir, os.path.join(addons_root, guard_name), dirs_exist_ok=True)

        save_json(
            os.path.join(target_mod_dir, "mod_config.json"),
            build_mod_config_data(self._build_config_data(mod_name, metadata)),
            indent=2,
        )
        return target_mod_dir

    @staticmethod
    def _is_valid_addon_root(root_dir: str) -> bool:
        metadata = Frickbears3AddonsService._read_extras_info(os.path.join(root_dir, "extras_info.txt"))
        if not metadata.get("FULL_NAME"):
            return False
        present = sum(1 for file_name in _SIGNATURE_FILES if os.path.isfile(os.path.join(root_dir, file_name)))
        return present >= 4

    @staticmethod
    def _read_extras_info(path: str) -> dict[str, Any]:
        try:
            with open(path, encoding="utf-8", errors="ignore") as handle:
                data = json.load(handle)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _resolve_guard_folder_name(root_dir: str) -> str:
        extras_info = Frickbears3AddonsService._read_extras_info(os.path.join(root_dir, "extras_info.txt"))
        full_name = str(extras_info.get("FULL_NAME") or "").strip()
        if full_name:
            return sanitize_filename(full_name) or os.path.basename(root_dir)
        return os.path.basename(root_dir)

    @staticmethod
    def _resolve_mod_name(
        root_dirs: list[str],
        *,
        source_file_path: str | None,
        metadata: dict[str, Any],
    ) -> str:
        name = str(metadata.get("name") or "").strip()
        if name:
            return name
        if len(root_dirs) == 1:
            root_name = Frickbears3AddonsService._resolve_guard_folder_name(root_dirs[0]).strip()
            if root_name:
                return root_name
        if source_file_path:
            source_name = remove_archive_extension(os.path.basename(source_file_path)).strip()
            if source_name:
                return source_name
        return f"FRICKBEARS3 Addon {uuid.uuid4().hex[:8]}"

    @staticmethod
    def _build_config_data(mod_name: str, metadata: dict[str, Any]) -> dict[str, Any]:
        item_type = str(metadata.get("item_type") or "mod").strip() or "mod"
        gb_mod_id = str(metadata.get("mod_id") or "").strip()
        mod_id = f"gb_{item_type}_{gb_mod_id}" if gb_mod_id else f"local_frickbears3_addon_{uuid.uuid4().hex[:8]}"
        config_data: dict[str, Any] = {
            "id": mod_id,
            "name": mod_name,
            "game": "frickbears3",
            "author": str(metadata.get("author") or "Unknown"),
            "version": str(metadata.get("version") or "1.0.0"),
            "files": {"frickbears3": {"extra_files": ["addons/"]}},
        }
        for field_name in ("description", "icon", "homepage"):
            value = metadata.get(field_name)
            if value not in (None, "", [], {}):
                config_data[field_name] = value
        return config_data
