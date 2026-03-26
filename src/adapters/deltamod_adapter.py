"""Deltamod format conversion utilities."""

import json
import logging
import os
import re
import shutil
import uuid
import zipfile
from typing import Any

from defusedxml import ElementTree

from services.localization_service import tr
from utils.file_utils import find_deltamod_info_file, get_unique_mod_dir
from utils.mod_config_parser import build_mod_config_data


class DeltamodConverter:
    """Converts deltamod format mods to DELTAHUB format."""

    def __init__(
        self, source_path: str, mods_dir: str, gamebanana_metadata: dict | None = None
    ) -> None:
        self.source_path = source_path
        self.mods_dir = mods_dir
        self.gamebanana_metadata = gamebanana_metadata or {}
        self.deltamod_info: dict[str, Any] = {}
        self.modding_xml: ElementTree.Element | None = None

    def convert(self) -> str | None:
        try:
            if not self._validate_source():
                return None
            config_data = self._generate_config_json()
            if not config_data:
                return None
            mod_name = config_data.get("name", "unnamed_mod")
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
                config_data["icon"] = (
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
        if self.modding_xml is None:
            return []
        if self.modding_xml.tag == "patch":
            return [self.modding_xml]
        return list(self.modding_xml.findall("patch"))

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

        game_value = "deltarune"
        if self.gamebanana_metadata and self.gamebanana_metadata.get("game"):
            game_value = self.gamebanana_metadata["game"]
        elif meta.get("demoMod"):
            game_value = "deltarunedemo"
        config = {
            "id": mod_id,
            "version": meta.get("version", "1.0.0"),
            "name": meta.get("name", tr("defaults.local_mod")),
            "description": meta.get("description", tr("defaults.no_description")),
            "author": ", ".join(meta.get("author", [tr("defaults.unknown")])),
            "external_url": self.gamebanana_metadata.get("profile_url")
            if self.gamebanana_metadata.get("profile_url")
            else meta.get("url", ""),
            "game": game_value,
            "game_version": self.deltamod_info.get(
                "deltaruneTargetVersion", tr("defaults.not_specified")
            ),
            "files": self._generate_files_structure(patches),
            "tags": meta.get("tags", []),
        }

        if self.gamebanana_metadata:
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
            if chapter_key not in files_structure:
                files_structure[chapter_key] = {}
            if patch_type == "xdelta":
                files_structure[chapter_key]["data_file_url"] = os.path.basename(
                    patch_file
                )
                files_structure[chapter_key]["data_file_version"] = (
                    self.deltamod_info.get("metadata", {}).get("version", "1.0.0")
                )
            elif patch_type == "override":
                if "extra_files" not in files_structure[chapter_key]:
                    files_structure[chapter_key]["extra_files"] = {}
                archive_key = (
                    (relative_path + filename).replace("/", "_").replace("\\", "_")
                )
                if not archive_key:
                    archive_key = filename
                if archive_key not in files_structure[chapter_key]["extra_files"]:
                    files_structure[chapter_key]["extra_files"][archive_key] = []
                archive_name = f"extra_file_{archive_key}.zip"
                if (
                    archive_name
                    not in files_structure[chapter_key]["extra_files"][archive_key]
                ):
                    files_structure[chapter_key]["extra_files"][archive_key].append(
                        archive_name
                    )
        return files_structure

    def _create_extra_file_archive(
        self, source_file: str, archive_path: str, relative_path: str, filename: str
    ) -> bool:
        try:
            if not os.path.exists(source_file):
                logging.error(f"Source file does not exist: {source_file}")
                return False
            os.makedirs(os.path.dirname(archive_path), exist_ok=True)
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                archive_internal_path = relative_path + filename
                zipf.write(source_file, archive_internal_path)
            logging.debug(
                f"Created extra_file archive: {archive_path} with internal path: {archive_internal_path}"
            )
            return True
        except Exception as e:
            logging.error(
                f"Failed to create extra_file archive {archive_path}: {e}",
                exc_info=True,
            )
            return False

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
            chapter_dir_name = (
                "demo" if chapter_key == "demo" else f"chapter_{chapter_key}"
            )
            target_chapter_dir = os.path.join(target_mod_dir, chapter_dir_name)
            os.makedirs(target_chapter_dir, exist_ok=True)
            if patch_type == "override":
                patch_file_abs = self._resolve_patch_file(patch_file_rel)
                if not patch_file_abs:
                    logging.error(
                        f"DeltamodConverter: override patch file not found: {patch_file_rel}"
                    )
                    continue
                archive_key = (
                    (relative_path + filename).replace("/", "_").replace("\\", "_")
                )
                if not archive_key:
                    archive_key = filename
                archive_name = f"extra_file_{archive_key}.zip"
                archive_path = os.path.join(target_chapter_dir, archive_name)
                if self._create_extra_file_archive(
                    patch_file_abs, archive_path, relative_path, filename
                ):
                    logging.info(
                        f"Created override archive: {archive_name} for chapter {chapter_key} with path {relative_path}{filename}"
                    )
                else:
                    logging.error(f"Failed to create override archive for: {to_path}")
            elif patch_type == "xdelta":
                patch_file_abs = os.path.join(self.source_path, patch_file_rel)
                if not os.path.exists(patch_file_abs):
                    logging.warning(
                        f"DeltamodConverter: xdelta patch file not found: {patch_file_abs}"
                    )
                    continue
                target_patch_path = os.path.join(
                    target_chapter_dir, os.path.basename(patch_file_abs)
                )
                shutil.copy2(patch_file_abs, target_patch_path)
                logging.info(
                    f"Copied xdelta patch: {os.path.basename(patch_file_abs)} for chapter {chapter_key}, target: {to_path}"
                )
            else:
                logging.warning(f"DeltamodConverter: unknown patch type: {patch_type}")
