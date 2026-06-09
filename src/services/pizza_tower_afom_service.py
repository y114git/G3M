"""AFOM/CYOP archive detection and G3M conversion for Pizza Tower."""

from __future__ import annotations

import configparser
import os
import shutil
import uuid
from dataclasses import dataclass, field
from typing import Any

from config.config import CYOP_AFOM_TAG
from utils.file_utils import get_unique_mod_dir, remove_archive_extension, save_json
from utils.mod.config_parser import build_mod_config_data


@dataclass(slots=True)
class PizzaTowerAFOMInspection:
    eligible: bool
    root_dirs: list[str] = field(default_factory=list)
    reason: str = ""


class PizzaTowerAFOMService:
    """Detect AFOM/CYOP archive layouts and convert them into G3M mods."""

    def inspect_extracted_archive(self, extract_dir: str) -> PizzaTowerAFOMInspection:
        if not extract_dir or not os.path.isdir(extract_dir):
            return PizzaTowerAFOMInspection(
                eligible=False,
                reason="Extracted archive directory does not exist",
            )

        root_entries = sorted(os.listdir(extract_dir))
        if not root_entries:
            return PizzaTowerAFOMInspection(
                eligible=False,
                reason="Archive is empty",
            )

        root_dirs: list[str] = []
        for entry in root_entries:
            entry_path = os.path.join(extract_dir, entry)
            if not os.path.isdir(entry_path):
                return PizzaTowerAFOMInspection(
                    eligible=False,
                    reason="Archive root contains files outside AFOM folders",
                )
            if not self._is_valid_afom_root(entry_path):
                return PizzaTowerAFOMInspection(
                    eligible=False,
                    reason=f"Folder is not a valid AFOM root: {entry}",
                )
            root_dirs.append(entry_path)

        return PizzaTowerAFOMInspection(eligible=True, root_dirs=root_dirs)

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
            raise ValueError(inspection.reason or "Archive is not a valid AFOM mod")
        if not mods_dir:
            raise ValueError("Mods directory is not configured")

        metadata = dict(gamebanana_metadata or {})
        mod_name = self._resolve_mod_name(
            inspection.root_dirs,
            source_file_path=source_file_path,
            metadata=metadata,
        )
        target_mod_dir = os.path.join(mods_dir, get_unique_mod_dir(mods_dir, mod_name))
        os.makedirs(target_mod_dir, exist_ok=True)

        towers_root = os.path.join(target_mod_dir, "towers")
        os.makedirs(towers_root, exist_ok=True)
        for root_dir in inspection.root_dirs:
            shutil.copytree(
                root_dir,
                os.path.join(towers_root, os.path.basename(root_dir)),
                dirs_exist_ok=True,
            )

        config_data = self._build_config_data(mod_name, metadata)
        config_path = os.path.join(target_mod_dir, "mod_config.json")
        save_json(config_path, build_mod_config_data(config_data), indent=2)
        return target_mod_dir

    @staticmethod
    def _is_valid_afom_root(root_dir: str) -> bool:
        try:
            ini_candidates = [
                os.path.join(root_dir, entry)
                for entry in os.listdir(root_dir)
                if os.path.isfile(os.path.join(root_dir, entry))
                and entry.lower().endswith(".ini")
            ]
        except OSError:
            return False
        return any(PizzaTowerAFOMService._has_afom_properties(path) for path in ini_candidates)

    @staticmethod
    def _has_afom_properties(ini_path: str) -> bool:
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str.lower
        try:
            with open(ini_path, encoding="utf-8", errors="ignore") as handle:
                parser.read_file(handle)
        except Exception:
            return False
        if not parser.has_section("properties"):
            return False
        section = parser["properties"]
        return bool(section.get("mainlevel")) and bool(section.get("name"))

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
            base_name = os.path.basename(root_dirs[0]).strip()
            if base_name:
                return base_name
        if source_file_path:
            source_name = remove_archive_extension(os.path.basename(source_file_path)).strip()
            if source_name:
                return source_name
        return f"AFOM Mod {uuid.uuid4().hex[:8]}"

    @staticmethod
    def _build_config_data(mod_name: str, metadata: dict[str, Any]) -> dict[str, Any]:
        item_type = str(metadata.get("item_type") or "mod").strip() or "mod"
        gb_mod_id = str(metadata.get("mod_id") or "").strip()
        mod_id = (
            f"gb_{item_type}_{gb_mod_id}"
            if gb_mod_id
            else f"local_afom_{uuid.uuid4().hex[:8]}"
        )
        config_data: dict[str, Any] = {
            "id": mod_id,
            "name": mod_name,
            "game": "pizzatower",
            "author": str(metadata.get("author") or "Unknown"),
            "version": str(metadata.get("version") or "1.0.0"),
            "tags": [CYOP_AFOM_TAG],
            "files": {
                "pizzatower": {
                    "extra_files": ["towers/"],
                }
            },
        }
        for field_name in ("description", "icon", "homepage", "tags"):
            value = metadata.get(field_name)
            if value not in (None, "", [], {}):
                config_data[field_name] = value
        return config_data
