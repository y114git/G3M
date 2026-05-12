"""Deltamod format conversion utilities."""

import json
import logging
import os
import re
import shutil
import uuid
from typing import Any

from defusedxml import ElementTree

from config.config import MOD_DOCUMENTATION_EXTENSIONS
from services.localization_service import tr
from utils.file_utils import find_deltamod_info_file, get_unique_mod_dir
from utils.mod_config_parser import build_mod_config_data

DELTAMOD_GAME_MAP: dict[str, str] = {
    "toby.deltarune": "deltarune",
    "toby.deltarune.demo": "deltarunedemo",
    "toby.undertale": "undertale",
    "fans.utyellow": "undertaleyellow",
    "other.pizzatower": "pizzatower",
}


class DeltamodConverter:
    """Converts deltamod format mods to G3M format."""

    def __init__(
        self, source_path: str, mods_dir: str, gamebanana_metadata: dict | None = None
    ) -> None:
        self.source_path = source_path
        self.mods_dir = mods_dir
        self.gamebanana_metadata = gamebanana_metadata or {}
        self.deltamod_info: dict[str, Any] = {}
        self.modding_xml: ElementTree.Element | None = None
        self._target_game = "deltarune"

    def convert(self) -> str | None:
        try:
            if not self._validate_source():
                return None
            config_data = self._generate_config_json()
            if not config_data:
                return None
            config_metadata = (
                config_data.get("metadata", config_data)
                if isinstance(config_data, dict)
                else {}
            )
            mod_name = self._normalize_folder_name(
                config_metadata.get("name") or self._fallback_mod_name()
            )
            folder_name = get_unique_mod_dir(self.mods_dir, mod_name)
            target_mod_dir = os.path.join(self.mods_dir, folder_name)
            if os.path.exists(target_mod_dir):
                for item in os.listdir(target_mod_dir):
                    if item == "mod_versions":
                        continue
                    item_path = os.path.join(target_mod_dir, item)
                    if os.path.isdir(item_path):
                        try:
                            shutil.rmtree(item_path)
                        except OSError as e:
                            logging.error(
                                f"Failed to remove directory {item_path} in {target_mod_dir}: {e}"
                            )
                            raise
                    else:
                        try:
                            os.remove(item_path)
                        except OSError as e:
                            logging.error(
                                f"Failed to remove file {item_path} in {target_mod_dir}: {e}"
                            )
                            raise
            os.makedirs(target_mod_dir, exist_ok=True)
            self._process_files(target_mod_dir)
            icon_path = os.path.join(target_mod_dir, "_icon.png")
            if not os.path.exists(icon_path):
                icon_path = os.path.join(target_mod_dir, "icon.png")
            if os.path.exists(icon_path):
                config_metadata["icon"] = (
                    "_icon.png"
                    if os.path.basename(icon_path) == "_icon.png"
                    else "icon.png"
                )
            config_path = os.path.join(target_mod_dir, "mod_config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(build_mod_config_data(config_data), f, indent=4, ensure_ascii=False)
            logging.info(
                f"Deltamod converted: {config_data.get('name')} → {target_mod_dir}"
            )
            return target_mod_dir
        except Exception as e:
            logging.error(f"Deltamod conversion failed: {e}")
            return None

    def _find_file_case_insensitive(
        self, base_path: str, relative_path: str
    ) -> str | None:
        if os.name != "nt":
            return None
        try:
            parts = relative_path.replace("\\", "/").split("/")
            current_path = base_path
            for part in parts:
                if not part:
                    continue
                if not os.path.exists(current_path):
                    return None
                try:
                    found = next(
                        (
                            e
                            for e in os.listdir(current_path)
                            if e.lower() == part.lower()
                        ),
                        None,
                    )
                    if found is None:
                        return None
                    current_path = os.path.join(current_path, found)
                except OSError:
                    return None
            return current_path if os.path.exists(current_path) else None
        except Exception:
            return None

    def _find_file_recursive(self, base_path: str, filename: str) -> str | None:
        if not os.path.exists(base_path):
            return None
        filename_lower = filename.lower()
        try:
            for root, _dirs, files in os.walk(base_path):
                for file in files:
                    if file.lower() == filename_lower:
                        return os.path.join(root, file)
        except Exception as e:
            logging.debug(f"Error in recursive file search: {e}")
        return None

    def _parse_to_path(self, to_path: str) -> tuple[str | None, str | None, str]:
        if not to_path:
            return (None, None, "")
        to_path = to_path.lstrip("./").replace("\\", "/")
        chapter_key = None
        if "demo" in to_path.lower():
            chapter_key = "demo"
        else:
            match = re.search(r"chapter(\d+)", to_path, re.IGNORECASE)
            if match:
                chapter_num = int(match.group(1))
                if chapter_num >= 0:
                    chapter_key = str(chapter_num)
            else:
                chapter_key = "0"
        if not chapter_key:
            return (None, None, "")
        path_without_chapter = re.sub(
            r"chapter\d+_windows?/", "", to_path, flags=re.IGNORECASE
        )
        path_without_chapter = path_without_chapter.lstrip("./")
        dir_part = os.path.dirname(path_without_chapter)
        filename = os.path.basename(path_without_chapter)
        relative_path = dir_part.replace("\\", "/") + "/" if dir_part else ""
        return (chapter_key, relative_path, filename)

    @staticmethod
    def _build_stored_path(relative_path: str | None, filename: str) -> str:
        return f"{relative_path}{filename}" if relative_path else filename

    def _validate_source(self) -> bool:
        info_path = find_deltamod_info_file(self.source_path)
        xml_path = os.path.join(self.source_path, "modding.xml")
        if not info_path:
            return False
        if not os.path.exists(xml_path):
            return False
        try:
            with open(info_path, encoding="utf-8") as f:
                self.deltamod_info = json.load(f)
        except Exception as e:
            logging.debug(
                f"DeltamodConverter._validate_source: failed to read {info_path}: {e}"
            )
            return False
        try:
            self.modding_xml = ElementTree.parse(xml_path).getroot()
        except ElementTree.ParseError:
            try:
                with open(xml_path, encoding="utf-8") as f:
                    xml_content = f.read().strip()
                if not xml_content.startswith("<?xml"):
                    xml_content = (
                        '<?xml version="1.0" encoding="UTF-8"?>\n<patches>\n'
                        + xml_content
                        + "\n</patches>"
                    )
                else:
                    xml_lines = xml_content.split("\n", 1)
                    xml_content = (
                        xml_lines[0] + "\n<patches>\n" + xml_lines[1] + "\n</patches>"
                    )
                self.modding_xml = ElementTree.fromstring(xml_content)
            except Exception as e:
                logging.debug(
                    f"DeltamodConverter._validate_source: failed to parse XML fallback: {e}"
                )
                self.modding_xml = None
        except Exception as e:
            logging.debug(
                f"DeltamodConverter._validate_source: failed to parse XML: {e}"
            )
            self.modding_xml = None
        return True

    def _collect_patches(self) -> list:
        if self.modding_xml is None or not hasattr(self.modding_xml, "tag"):
            return []
        if self.modding_xml.tag == "patch":
            return [self.modding_xml]
        return list(self.modding_xml.findall("patch"))

    def _map_deltamod_game(self, game_id: Any) -> str | None:
        if not isinstance(game_id, str):
            return None
        return DELTAMOD_GAME_MAP.get(game_id.strip().lower())

    def _resolve_target_game(self, meta: dict[str, Any]) -> str:
        mapped_game = self._map_deltamod_game(meta.get("game"))
        if mapped_game:
            return mapped_game
        if meta.get("demoMod"):
            return "deltarunedemo"
        return "deltarune"

    def _resolve_game_version(self, game_value: str) -> str:
        if game_value != "deltarune":
            return ""
        return self.deltamod_info.get("deltaruneTargetVersion", tr("defaults.not_specified"))

    def _normalize_content_key(self, chapter_key: str) -> str:
        from models.game_modes import get_game

        game_def = get_game(self._target_game)
        if not game_def:
            return chapter_key
        if chapter_key == "demo":
            return game_def.default_tab
        if game_def.is_multi_tab:
            tab = game_def.get_tab(chapter_key)
            return tab.tab_id if tab else chapter_key
        return game_def.default_tab

    def _fallback_mod_name(self) -> str:
        file_name = str(self.gamebanana_metadata.get("file_name") or "").strip()
        if file_name:
            return self._normalize_folder_name(os.path.splitext(file_name)[0])
        source_name = os.path.basename(os.path.normpath(self.source_path))
        return source_name or "imported_mod"

    @staticmethod
    def _normalize_folder_name(name: str) -> str:
        return re.sub(r"[\s._-]*v?\d+(?:[._-]\d+)*$", "", name, flags=re.IGNORECASE).strip() or name

    def _generate_config_json(self) -> dict[str, Any] | None:
        if not self.deltamod_info or self.modding_xml is None:
            return None
        patches = self._collect_patches()
        meta = self.deltamod_info.get("metadata", {})

        if self.gamebanana_metadata and "mod_id" in self.gamebanana_metadata:
            mod_id = f"gb_{self.gamebanana_metadata['mod_id']}"
        else:
            package_id = meta.get("packageID", "")
            if package_id and package_id != "und.und.und":
                mod_id = package_id.replace(".", "_")
            else:
                mod_id = f"local_{meta.get('name', 'unnamed')}_{uuid.uuid4().hex[:8]}"

        game_value = self._resolve_target_game(meta)
        self._target_game = game_value
        config = {
            "id": mod_id,
            "version": meta.get("version", "1.0.0"),
            "name": meta.get("name") or self._fallback_mod_name(),
            "description": meta.get("description", tr("defaults.no_description")),
            "author": ", ".join(meta.get("author", [tr("defaults.unknown")])),
            "homepage": (
                self.gamebanana_metadata.get("homepage")
                or self.gamebanana_metadata.get("profile_url")
                or meta.get("url", "")
            ),
            "game": game_value,
            "game_version": self._resolve_game_version(game_value),
            "files": self._generate_files_structure(patches),
            "tags": meta.get("tags", []),
        }

        if self.gamebanana_metadata:
            from adapters.gamebanana_adapter import GameBananaAPI

            if self.gamebanana_metadata.get("icon"):
                config["icon"] = self.gamebanana_metadata["icon"]
            if self.gamebanana_metadata.get("tags"):
                gb_tags = self.gamebanana_metadata["tags"]
                if isinstance(gb_tags, list):
                    existing_tags = config.get("tags", [])
                    for tag in gb_tags:
                        if tag and tag not in existing_tags:
                            existing_tags.append(tag)
                    config["tags"] = existing_tags
            category_tag = GameBananaAPI.category_to_tag(
                self.gamebanana_metadata.get("category")
            )
            if category_tag:
                existing_tags = config.get("tags", [])
                if not isinstance(existing_tags, list):
                    existing_tags = [existing_tags] if existing_tags else []
                if category_tag not in existing_tags:
                    existing_tags.append(category_tag)
                config["tags"] = existing_tags

        return build_mod_config_data(config)

    def _generate_files_structure(self, patches: list) -> dict[str, Any]:
        files_structure = {}
        if self.modding_xml is None:
            return {}
        for patch in patches:
            to_path = patch.get("to", "")
            patch_file = patch.get("patch", "")
            patch_type = patch.get("type", "")
            if not to_path or not patch_file or (not patch_type):
                logging.warning(
                    f"DeltamodConverter: skipping patch with missing fields (to={to_path}, patch={patch_file}, type={patch_type})"
                )
                continue
            chapter_key, relative_path, filename = self._parse_to_path(to_path)
            if not chapter_key:
                logging.warning(
                    f"DeltamodConverter: could not determine chapter for path: {to_path}"
                )
                continue
            content_key = self._normalize_content_key(chapter_key)
            if content_key not in files_structure:
                files_structure[content_key] = {}
            if patch_type == "xdelta":
                files_structure[content_key]["data_file_path"] = os.path.basename(
                    patch_file.lstrip("./").replace("\\", "/")
                )
            elif patch_type == "override":
                stored_path = self._build_stored_path(relative_path, filename)
                files_structure[content_key].setdefault("extra_files", []).append(
                    stored_path
                )
        return files_structure

    def _resolve_patch_file(self, patch_file_rel: str) -> str | None:
        for variant in (
            patch_file_rel,
            patch_file_rel.replace("\\", "/"),
            patch_file_rel.replace("/", "\\"),
        ):
            candidate = os.path.join(self.source_path, variant)
            if os.path.exists(candidate):
                return candidate
        if os.name == "nt":
            found = self._find_file_case_insensitive(self.source_path, patch_file_rel)
            if found:
                return found
        found = self._find_file_recursive(
            self.source_path, os.path.basename(patch_file_rel)
        )
        return found

    def _process_files(self, target_mod_dir: str) -> None:
        if self.modding_xml is None:
            return
        patches = self._collect_patches()
        self._copy_root_docs(target_mod_dir)
        icon_path = os.path.join(self.source_path, "_icon.png")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(self.source_path, "icon.png")
        if os.path.exists(icon_path):
            target_icon_path = os.path.join(
                target_mod_dir,
                "_icon.png"
                if os.path.basename(icon_path) == "_icon.png"
                else "icon.png",
            )
            shutil.copy2(icon_path, target_icon_path)
        for patch in patches:
            to_path = patch.get("to", "")
            patch_file_rel = patch.get("patch", "").lstrip("./")
            patch_type = patch.get("type", "")
            if not to_path or not patch_type:
                logging.warning(
                    f"DeltamodConverter: skipping patch with missing to or type: {to_path}, {patch_type}"
                )
                continue
            chapter_key, relative_path, filename = self._parse_to_path(to_path)
            if not chapter_key:
                logging.warning(
                    f"DeltamodConverter: could not determine chapter for path: {to_path}"
                )
                continue
            content_key = self._normalize_content_key(chapter_key)
            from utils.file_utils import get_chapter_folder_name

            chapter_dir_name = get_chapter_folder_name(content_key, game=self._target_game)
            target_chapter_dir = os.path.join(target_mod_dir, chapter_dir_name)
            os.makedirs(target_chapter_dir, exist_ok=True)
            if patch_type == "override":
                patch_file_abs = self._resolve_patch_file(patch_file_rel)
                if not patch_file_abs:
                    logging.error(
                        f"DeltamodConverter: override patch file not found: {patch_file_rel}"
                    )
                    continue
                stored_path = self._build_stored_path(relative_path, filename)
                target_override_path = os.path.join(
                    target_chapter_dir, stored_path.replace("/", os.sep)
                )
                parent_dir = os.path.dirname(target_override_path)
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)
                shutil.copy2(patch_file_abs, target_override_path)
                logging.info(
                    "Copied override file: %s for chapter %s into %s",
                    stored_path,
                    chapter_key,
                    chapter_dir_name,
                )
            elif patch_type == "xdelta":
                patch_file_abs = self._resolve_patch_file(patch_file_rel)
                if not patch_file_abs:
                    logging.warning(
                        f"DeltamodConverter: xdelta patch file not found: {patch_file_rel}"
                    )
                    continue
                target_patch_path = os.path.join(
                    target_chapter_dir, os.path.basename(patch_file_abs)
                )
                shutil.copy2(patch_file_abs, target_patch_path)
                logging.info(
                    "Copied xdelta patch: %s for chapter %s into %s",
                    os.path.basename(patch_file_abs),
                    chapter_key,
                    chapter_dir_name,
                )
            else:
                logging.warning(f"DeltamodConverter: unknown patch type: {patch_type}")

    def _copy_root_docs(self, target_mod_dir: str) -> None:
        try:
            for item in os.listdir(self.source_path):
                source_path = os.path.join(self.source_path, item)
                if not os.path.isfile(source_path):
                    continue
                if os.path.splitext(item)[1].lower() not in MOD_DOCUMENTATION_EXTENSIONS:
                    continue
                shutil.copy2(source_path, os.path.join(target_mod_dir, item))
        except Exception as e:
            logging.debug(
                "DeltamodConverter: failed to copy root docs from %s: %s",
                self.source_path,
                e,
                exc_info=True,
            )
