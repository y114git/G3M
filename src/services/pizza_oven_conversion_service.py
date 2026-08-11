"""PizzaOven normal-mod inspection and conversion into G3M mods."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from adapters.g3mtool_adapter import G3MToolManager
from config.config import MOD_CONFIG_FILENAME, MOD_DOCUMENTATION_EXTENSIONS
from services.localization_service import tr
from utils.file_utils import get_unique_mod_dir, remove_archive_extension, save_json
from utils.mod.config_parser import build_mod_config_data
from utils.patching.patch_verification_utils import files_match, verify_generated_patch

logger = logging.getLogger(__name__)

_LANG_RE = re.compile(r'lang\s*=\s*"([^"]+)"', re.IGNORECASE)
_MODJSON_SKIP_NAMES = {
    "mod.json",
    ".disable_gb1click",
    ".disable_gb1click_pizzaoven",
    ".disable_gb1click_pizzaovenplus",
}
_GML_FOLDERS = {
    "audio",
    "code",
    "lib",
    "config",
    "csx",
    "room",
    "shader",
    "texture",
    "textures",
    "xdelta",
}
_PASS1_EXTENSIONS = {
    ".xdelta",
    ".vcdiff",
    ".txt",
    ".win",
    ".bank",
    ".dll",
    ".mp4",
}
_PASS2_EXTENSIONS = {
    ".ttf",
    ".otf",
    ".def",
    ".png",
    ".json",
}
_FONT_NAMES = {"bigfont", "captionfont", "credits", "tutorial"}
_RELEVANT_MOD_EXTENSIONS = _PASS1_EXTENSIONS | _PASS2_EXTENSIONS
_METADATA_FIELDS = ("name", "author", "description", "homepage", "icon", "version")


class PizzaOvenConversionError(RuntimeError):
    """Raised when PizzaOven conversion cannot proceed."""


class PizzaOvenPatchTool(Protocol):
    """G3MTool operations required by PizzaOven conversion."""

    def is_available(self) -> bool: ...

    def xpatch_apply(
        self, original_file: str, patch_path: str, output_path: str
    ) -> tuple[int, str, str]: ...

    def patch_create(
        self, original_file: str, modified_file: str, output_path: str
    ) -> tuple[int, str, str]: ...

    def xpatch_create(
        self, original_file: str, modified_file: str, output_path: str
    ) -> tuple[int, str, str]: ...


@dataclass(slots=True)
class PizzaOvenInspection:
    eligible: bool
    mod_type: str
    reason: str = ""
    relevant_files: list[str] = field(default_factory=list)
    disable_all: bool = False
    disable_pizzaoven: bool = False
    disable_pizzaovenplus: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PizzaOvenConversionResult:
    mod_dir: str
    changed_files: list[str]
    data_file_name: str | None
    used_source_files: list[str]


@dataclass(slots=True)
class PizzaOvenSimulationResult:
    used_source_files: list[str]
    touched_files: set[str]
    reusable_patches: dict[str, str] = field(default_factory=dict)


class PizzaOvenConversionService:
    """Converts PizzaOven normal mods into G3M mods via temp simulation."""

    def __init__(self, g3mtool: PizzaOvenPatchTool | None = None) -> None:
        self._g3mtool = g3mtool or G3MToolManager()

    def validate_game_path(self, game_path: str) -> None:
        self._validate_game_path(game_path)

    def inspect_source(self, source_dir: str) -> PizzaOvenInspection:
        if not source_dir or not os.path.isdir(source_dir):
            return PizzaOvenInspection(
                eligible=False,
                mod_type="UNKNOWN",
                reason="Source directory does not exist",
            )
        rel_files = self._collect_relative_files(source_dir)
        file_names = {os.path.basename(path).lower() for path in rel_files}
        disable_all = ".disable_gb1click" in file_names
        disable_pizzaoven = ".disable_gb1click_pizzaoven" in file_names
        disable_pizzaovenplus = ".disable_gb1click_pizzaovenplus" in file_names
        metadata = self._extract_source_metadata(source_dir)
        mod_type = self._detect_mod_type(source_dir)
        relevant_files = [
            rel_path for rel_path in rel_files if self._is_relevant_mod_file(rel_path)
        ]
        if disable_all or (disable_pizzaoven and disable_pizzaovenplus):
            return self._build_inspection(
                eligible=False,
                mod_type=mod_type,
                reason="PizzaOven manager integration disabled by mod author",
                relevant_files=relevant_files,
                disable_all=disable_all,
                disable_pizzaoven=disable_pizzaoven,
                disable_pizzaovenplus=disable_pizzaovenplus,
                metadata=metadata,
            )
        if mod_type != "NORMAL":
            return self._build_inspection(
                eligible=False,
                mod_type=mod_type,
                reason=f"{mod_type} mods are not supported for conversion",
                relevant_files=relevant_files,
                disable_all=disable_all,
                disable_pizzaoven=disable_pizzaoven,
                disable_pizzaovenplus=disable_pizzaovenplus,
                metadata=metadata,
            )
        if not relevant_files:
            return self._build_inspection(
                eligible=False,
                mod_type=mod_type,
                reason="No PizzaOven-normal files detected",
                relevant_files=relevant_files,
                disable_all=disable_all,
                disable_pizzaoven=disable_pizzaoven,
                disable_pizzaovenplus=disable_pizzaovenplus,
                metadata=metadata,
            )
        return self._build_inspection(
            eligible=True,
            mod_type=mod_type,
            relevant_files=relevant_files,
            disable_all=disable_all,
            disable_pizzaoven=disable_pizzaoven,
            disable_pizzaovenplus=disable_pizzaovenplus,
            metadata=metadata,
        )

    @staticmethod
    def _build_inspection(
        *,
        eligible: bool,
        mod_type: str,
        reason: str = "",
        relevant_files: list[str] | None = None,
        disable_all: bool = False,
        disable_pizzaoven: bool = False,
        disable_pizzaovenplus: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> PizzaOvenInspection:
        return PizzaOvenInspection(
            eligible=eligible,
            mod_type=mod_type,
            reason=reason,
            relevant_files=relevant_files or [],
            disable_all=disable_all,
            disable_pizzaoven=disable_pizzaoven,
            disable_pizzaovenplus=disable_pizzaovenplus,
            metadata=metadata or {},
        )

    def convert(
        self,
        source_dir: str,
        mods_dir: str,
        game_path: str,
        *,
        source_file_path: str | None = None,
        gamebanana_metadata: dict[str, Any] | None = None,
        progress_callback=None,
    ) -> PizzaOvenConversionResult:
        inspection = self.inspect_source(source_dir)
        if not inspection.eligible:
            raise PizzaOvenConversionError(
                inspection.reason or "Conversion is not available"
            )
        if not game_path or not os.path.isdir(game_path):
            raise PizzaOvenConversionError("Pizza Tower game path is invalid")
        self._validate_game_path(game_path)
        if not mods_dir:
            raise PizzaOvenConversionError("Mods directory is not configured")
        merged_metadata = self._merge_metadata(
            inspection.metadata,
            gamebanana_metadata or {},
            source_file_path,
            source_dir,
        )
        if progress_callback:
            progress_callback(5, tr("status.po_convert_inspecting_source"))
        temp_root = tempfile.mkdtemp(prefix="g3m_po_convert_")
        try:
            working_game_dir = os.path.join(temp_root, "game")
            if progress_callback:
                progress_callback(20, tr("status.po_convert_copying_game"))
            shutil.copytree(game_path, working_game_dir)
            if progress_callback:
                progress_callback(45, tr("status.po_convert_applying"))
            simulation = self._simulate_normal_build(source_dir, working_game_dir)
            if progress_callback:
                progress_callback(68, tr("status.po_convert_collecting_changes"))
            changed_files = self._collect_changed_files(
                game_path,
                working_game_dir,
                candidate_paths=simulation.touched_files,
            )
            if not changed_files:
                raise PizzaOvenConversionError(
                    "PizzaOven conversion produced no game changes"
                )
            if progress_callback:
                progress_callback(82, tr("status.po_convert_building_mod"))
            result = self._build_g3m_mod(
                source_dir,
                source_file_path,
                mods_dir,
                game_path,
                working_game_dir,
                changed_files,
                simulation.used_source_files,
                merged_metadata,
                simulation.reusable_patches,
            )
            if progress_callback:
                progress_callback(100, tr("status.po_convert_completed_detail"))
            return result
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    @staticmethod
    def _collect_relative_files(source_dir: str) -> list[str]:
        rel_files: list[str] = []
        for root, _dirs, files in os.walk(source_dir):
            for file_name in files:
                rel_path = os.path.relpath(
                    os.path.join(root, file_name), source_dir
                ).replace("\\", "/")
                rel_files.append(rel_path)
        rel_files.sort(key=str.lower)
        return rel_files

    @staticmethod
    def _load_mod_json(source_dir: str) -> dict[str, Any]:
        mod_json_path = os.path.join(source_dir, "mod.json")
        if not os.path.isfile(mod_json_path):
            return {}
        try:
            with open(mod_json_path, encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.debug(
                "Failed to read PizzaOven mod.json from %s: %s", mod_json_path, e
            )
            return {}

    def _extract_source_metadata(self, source_dir: str) -> dict[str, Any]:
        mod_json = self._load_mod_json(source_dir)
        metadata: dict[str, Any] = {"game": "pizzatower"}
        if mod_json.get("title"):
            metadata["name"] = str(mod_json["title"]).strip()
        if mod_json.get("submitter"):
            metadata["author"] = str(mod_json["submitter"]).strip()
        if mod_json.get("description"):
            metadata["description"] = str(mod_json["description"]).strip()
        if mod_json.get("homepage"):
            metadata["homepage"] = str(mod_json["homepage"]).strip()
        if mod_json.get("preview"):
            metadata["icon"] = str(mod_json["preview"]).strip()
        return metadata

    @staticmethod
    def _merge_metadata(
        source_metadata: dict[str, Any],
        gamebanana_metadata: dict[str, Any],
        source_file_path: str | None,
        source_dir: str,
    ) -> dict[str, Any]:
        metadata = dict(source_metadata)
        metadata["game"] = "pizzatower"
        for metadata_field in _METADATA_FIELDS:
            value = gamebanana_metadata.get(metadata_field)
            if value:
                metadata[metadata_field] = value
        tags = gamebanana_metadata.get("tags")
        if tags:
            metadata["tags"] = tags if isinstance(tags, list) else [tags]
        if gamebanana_metadata.get("mod_id"):
            item_type = str(gamebanana_metadata.get("item_type", "mod")).lower()
            metadata["id"] = f"gb_{item_type}_{gamebanana_metadata['mod_id']}"
        if not metadata.get("name"):
            base = source_file_path or source_dir
            metadata["name"] = (
                remove_archive_extension(os.path.basename(base)) or "PizzaOven Mod"
            )
        metadata.setdefault("author", "Unknown")
        metadata.setdefault("version", "1.0.0")
        return metadata

    @staticmethod
    def _validate_game_path(game_path: str) -> None:
        required_files = ("data.win",)
        missing = [
            file_name
            for file_name in required_files
            if not os.path.isfile(os.path.join(game_path, file_name))
        ]
        if missing:
            raise PizzaOvenConversionError(
                "Pizza Tower folder is missing required original files: "
                + ", ".join(missing)
            )
        if not PizzaOvenConversionService._get_executable_targets(game_path):
            raise PizzaOvenConversionError(
                "Pizza Tower folder is missing a game executable"
            )

    def _detect_mod_type(self, source_dir: str) -> str:
        rel_files = self._collect_relative_files(source_dir)
        exts = {
            os.path.splitext(path)[1].lower().lstrip(".")
            for path in rel_files
            if os.path.basename(path).lower() != "mod.json"
            and os.path.splitext(path)[1]
        }
        has_levels_dir = False
        potential_gmloader = False
        xdeltainfolder = False
        for root, dirs, _files in os.walk(source_dir):
            for dir_name in dirs:
                dir_lower = dir_name.lower()
                if dir_lower == "levels":
                    has_levels_dir = True
                if dir_lower in _GML_FOLDERS:
                    potential_gmloader = True
                if dir_lower == "xdelta":
                    xdelta_dir = os.path.join(root, dir_name)
                    if any(
                        os.path.basename(entry).lower() == "xdelta"
                        for entry in os.listdir(xdelta_dir)
                    ):
                        xdeltainfolder = True
        mod_json = self._load_mod_json(source_dir)
        category = str(mod_json.get("cat", "")).strip()
        if category == "GMLoader":
            return "GMLOADER"
        if category == "CYOP/AFOM":
            return "AFOM"
        if "xdelta" in exts and not xdeltainfolder:
            return "NORMAL"
        if potential_gmloader:
            return "GMLOADER"
        if has_levels_dir and "json" in exts and "ini" in exts:
            return "AFOM"
        return "NORMAL"

    @staticmethod
    def _is_relevant_mod_file(rel_path: str) -> bool:
        base_name = os.path.basename(rel_path).lower()
        if base_name in _MODJSON_SKIP_NAMES:
            return False
        return os.path.splitext(base_name)[1].lower() in _RELEVANT_MOD_EXTENSIONS

    def _simulate_normal_build(
        self, source_dir: str, working_game_dir: str
    ) -> PizzaOvenSimulationResult:
        mod_files = self._iter_mod_files(source_dir)
        files_to_patch = self._get_patch_targets(working_game_dir)
        used_source_files: list[str] = []
        touched_files: set[str] = set()
        patch_sources: dict[str, list[str]] = {}
        replaced_files: set[str] = set()
        for source_path, rel_path in mod_files:
            ext = os.path.splitext(source_path)[1].lower()
            if ext in (".xdelta", ".vcdiff"):
                target_file = self._apply_xdelta_file(source_path, files_to_patch)
                if not target_file:
                    raise PizzaOvenConversionError(
                        f"PizzaOven patch could not be applied: {os.path.basename(source_path)}"
                    )
                used_source_files.append(rel_path)
                target_rel_path = os.path.relpath(
                    target_file, working_game_dir
                ).replace("\\", "/")
                touched_files.add(target_rel_path)
                patch_sources.setdefault(target_rel_path, []).append(source_path)
                continue
            if ext == ".txt":
                text = self._read_text_safe(source_path)
                basename = os.path.splitext(os.path.basename(source_path))[0]
                if "lang = " in text.lower():
                    target_path = os.path.join(
                        working_game_dir, "lang", os.path.basename(source_path)
                    )
                    self._copy_file(source_path, target_path)
                    used_source_files.append(rel_path)
                    touched_files.add(
                        self._record_replaced_file(
                            target_path, working_game_dir, replaced_files
                        )
                    )
                elif "credits" in basename.lower():
                    target_path = os.path.join(
                        working_game_dir, os.path.basename(source_path)
                    )
                    self._copy_file(source_path, target_path)
                    used_source_files.append(rel_path)
                    touched_files.add(
                        self._record_replaced_file(
                            target_path, working_game_dir, replaced_files
                        )
                    )
                continue
            if ext == ".win":
                target_path = os.path.join(working_game_dir, "data.win")
                self._copy_file(source_path, target_path)
                used_source_files.append(rel_path)
                touched_files.add("data.win")
                replaced_files.add("data.win")
                continue
            if ext == ".bank":
                target_path = self._copy_bank_file(
                    source_dir, source_path, working_game_dir
                )
                used_source_files.append(rel_path)
                touched_files.add(
                    self._record_replaced_file(
                        target_path, working_game_dir, replaced_files
                    )
                )
                continue
            if ext in {".dll", ".mp4"}:
                target_path = os.path.join(
                    working_game_dir, os.path.basename(source_path)
                )
                self._copy_file(
                    source_path,
                    target_path,
                )
                used_source_files.append(rel_path)
                touched_files.add(
                    self._record_replaced_file(
                        target_path, working_game_dir, replaced_files
                    )
                )
        lang_names, lang_files = self._collect_language_names(working_game_dir)
        for source_path, rel_path in mod_files:
            ext = os.path.splitext(source_path)[1].lower()
            basename = os.path.splitext(os.path.basename(source_path))[0]
            if ext in {".ttf", ".otf"}:
                target_path = os.path.join(
                    working_game_dir, "lang", "fonts", os.path.basename(source_path)
                )
                self._copy_file(
                    source_path,
                    target_path,
                )
                used_source_files.append(rel_path)
                touched_files.add(
                    self._record_replaced_file(
                        target_path, working_game_dir, replaced_files
                    )
                )
                continue
            if ext == ".def":
                target_path = os.path.join(
                    working_game_dir, "lang", os.path.basename(source_path)
                )
                self._copy_file(
                    source_path,
                    target_path,
                )
                used_source_files.append(rel_path)
                touched_files.add(
                    self._record_replaced_file(
                        target_path, working_game_dir, replaced_files
                    )
                )
                continue
            if ext == ".png":
                target_dir = self._resolve_png_target_dir(
                    basename, lang_names, lang_files
                )
                if target_dir:
                    target_path = os.path.join(
                        working_game_dir,
                        "lang",
                        target_dir,
                        os.path.basename(source_path),
                    )
                    self._copy_file(
                        source_path,
                        target_path,
                    )
                    used_source_files.append(rel_path)
                    touched_files.add(
                        self._record_replaced_file(
                            target_path, working_game_dir, replaced_files
                        )
                    )
                continue
            if ext == ".json" and basename in (set(lang_names) | set(lang_files)):
                target_path = os.path.join(
                    working_game_dir, "lang", "graphics", os.path.basename(source_path)
                )
                self._copy_file(
                    source_path,
                    target_path,
                )
                used_source_files.append(rel_path)
                touched_files.add(
                    self._record_replaced_file(
                        target_path, working_game_dir, replaced_files
                    )
                )
        if not used_source_files:
            raise PizzaOvenConversionError(
                "PizzaOven conversion found no usable mod files"
            )
        return PizzaOvenSimulationResult(
            used_source_files=used_source_files,
            touched_files=touched_files,
            reusable_patches={
                target: sources[0]
                for target, sources in patch_sources.items()
                if len(sources) == 1 and target not in replaced_files
            },
        )

    @staticmethod
    def _record_replaced_file(
        target_path: str, working_game_dir: str, replaced_files: set[str]
    ) -> str:
        rel_path = os.path.relpath(target_path, working_game_dir).replace("\\", "/")
        replaced_files.add(rel_path)
        return rel_path

    @staticmethod
    def _iter_mod_files(source_dir: str) -> list[tuple[str, str]]:
        files: list[tuple[str, str]] = []
        for root, _dirs, file_names in os.walk(source_dir):
            for file_name in file_names:
                source_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(source_path, source_dir).replace("\\", "/")
                files.append((source_path, rel_path))
        files.sort(key=lambda item: item[1].lower())
        return files

    @staticmethod
    def _read_text_safe(path: str) -> str:
        for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
            try:
                with open(path, encoding=encoding) as handle:
                    return handle.read()
            except UnicodeDecodeError:
                continue
        with open(path, "rb") as handle:
            return handle.read().decode("latin-1", errors="ignore")

    @staticmethod
    def _copy_file(source_path: str, target_path: str) -> None:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.copy2(source_path, target_path)

    @staticmethod
    def _collect_language_names(working_game_dir: str) -> tuple[list[str], list[str]]:
        lang_dir = os.path.join(working_game_dir, "lang")
        lang_names: list[str] = []
        lang_files: list[str] = []
        if not os.path.isdir(lang_dir):
            return lang_names, lang_files
        for file_name in sorted(os.listdir(lang_dir), key=str.lower):
            if not file_name.lower().endswith(".txt"):
                continue
            file_path = os.path.join(lang_dir, file_name)
            if not os.path.isfile(file_path):
                continue
            match = _LANG_RE.search(
                PizzaOvenConversionService._read_text_safe(file_path)
            )
            if match:
                lang_names.append(match.group(1))
                lang_files.append(os.path.splitext(file_name)[0])
        return lang_names, lang_files

    @staticmethod
    def _resolve_png_target_dir(
        basename: str, lang_names: list[str], lang_files: list[str]
    ) -> str | None:
        normalized = re.sub(r"^\d+", "", basename)
        match = next(
            (
                name
                for name in lang_names
                if normalized.lower().startswith(name.lower())
            ),
            None,
        )
        if match is None:
            match = next(
                (
                    name
                    for name in lang_files
                    if normalized.lower().startswith(name.lower())
                ),
                None,
            )
        if match is not None:
            normalized = match
        else:
            normalized = re.sub(r"\d+$", "", normalized)
        graphics_match = (
            normalized in lang_names
            or normalized in lang_files
            or any(name.lower().startswith(normalized.lower()) for name in lang_names)
        )
        if graphics_match and not any(
            font_name.lower().startswith(normalized.lower())
            for font_name in _FONT_NAMES
        ):
            return "graphics"
        for lang_name, lang_file in zip(lang_names, lang_files, strict=False):
            if (
                normalized.lower() in {name.lower() for name in _FONT_NAMES}
                or normalized.lower().endswith(f"_{lang_name.lower()}")
                or normalized.lower().endswith(f"_{lang_file.lower()}")
            ):
                return "fonts"
        return None

    @staticmethod
    def _get_patch_targets(working_game_dir: str) -> list[str]:
        targets = []
        data_file = os.path.join(working_game_dir, "data.win")
        if os.path.isfile(data_file):
            targets.append(data_file)
        targets.extend(
            PizzaOvenConversionService._get_executable_targets(working_game_dir)
        )
        sound_dir = os.path.join(working_game_dir, "sound", "Desktop")
        if os.path.isdir(sound_dir):
            sound_files = []
            for root, _dirs, files in os.walk(sound_dir):
                for file_name in files:
                    sound_files.append(os.path.join(root, file_name))
            sound_files.sort(key=lambda value: value.lower())
            targets.extend(sound_files)
        return targets

    @staticmethod
    def _get_executable_targets(game_dir: str) -> list[str]:
        if not os.path.isdir(game_dir):
            return []
        targets: list[str] = []
        seen: set[str] = set()

        def add_if_executable(path: str) -> None:
            normalized = os.path.normcase(os.path.abspath(path))
            if normalized in seen or not os.path.isfile(path):
                return
            file_name = os.path.basename(path)
            if not (
                file_name.lower().endswith(".exe")
                or file_name.casefold() == "pizzatower"
                or (os.name != "nt" and os.access(path, os.X_OK))
            ):
                return
            seen.add(normalized)
            targets.append(path)

        for preferred in ("PizzaTower.exe", "PizzaTower"):
            add_if_executable(os.path.join(game_dir, preferred))
        for file_name in sorted(os.listdir(game_dir), key=str.casefold):
            add_if_executable(os.path.join(game_dir, file_name))
        return targets

    def _apply_xdelta_file(
        self, patch_path: str, target_files: list[str]
    ) -> str | None:
        if not self._g3mtool.is_available():
            raise PizzaOvenConversionError(
                "G3MTool is required for PizzaOven xdelta conversion"
            )
        for target_file in target_files:
            if not os.path.isfile(target_file):
                continue
            temp_dir = tempfile.mkdtemp(prefix="g3m_po_patch_")
            try:
                temp_output = os.path.join(temp_dir, os.path.basename(target_file))
                returncode = self._g3mtool.xpatch_apply(
                    target_file, patch_path, temp_output
                )[0]
                if returncode == 0 and os.path.isfile(temp_output):
                    shutil.move(temp_output, target_file)
                    return target_file
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    @staticmethod
    def _copy_bank_file(
        source_dir: str, source_path: str, working_game_dir: str
    ) -> str:
        target_path = os.path.join(
            working_game_dir, "sound", "Desktop", os.path.basename(source_path)
        )
        if os.path.isfile(target_path):
            PizzaOvenConversionService._copy_file(source_path, target_path)
            return target_path
        parent_name = os.path.basename(os.path.dirname(source_path))
        mod_root_name = os.path.basename(source_dir)
        if parent_name.lower() not in {"desktop", mod_root_name.lower()}:
            target_path = os.path.join(
                working_game_dir,
                "sound",
                "Desktop",
                parent_name,
                os.path.basename(source_path),
            )
        PizzaOvenConversionService._copy_file(source_path, target_path)
        return target_path

    def _collect_changed_files(
        self,
        original_root: str,
        modified_root: str,
        *,
        candidate_paths: set[str] | None = None,
    ) -> list[str]:
        original_files = self._scan_file_map(original_root)
        modified_files = self._scan_file_map(modified_root)
        changed: list[str] = []
        rel_paths = (
            sorted(candidate_paths, key=str.lower)
            if candidate_paths
            else sorted(modified_files, key=str.lower)
        )
        for rel_path in rel_paths:
            modified_path = modified_files.get(rel_path)
            if not modified_path:
                continue
            original_path = original_files.get(rel_path)
            if not original_path:
                changed.append(rel_path)
                continue
            if self._files_differ(original_path, modified_path):
                changed.append(rel_path)
        return changed

    @staticmethod
    def _files_differ(original_path: str, modified_path: str) -> bool:
        return not files_match(original_path, modified_path)

    @staticmethod
    def _scan_file_map(root_dir: str) -> dict[str, str]:
        file_map: dict[str, str] = {}
        for root, _dirs, files in os.walk(root_dir):
            for file_name in files:
                abs_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(abs_path, root_dir).replace("\\", "/")
                file_map[rel_path] = abs_path
        return file_map

    def _build_g3m_mod(
        self,
        source_dir: str,
        source_file_path: str | None,
        mods_dir: str,
        original_game_dir: str,
        working_game_dir: str,
        changed_files: list[str],
        used_source_files: list[str],
        metadata: dict[str, Any],
        reusable_patches: dict[str, str],
    ) -> PizzaOvenConversionResult:
        mod_name = str(metadata.get("name") or "PizzaOven Mod").strip()
        mod_id = str(metadata.get("id") or f"local_po_{uuid.uuid4().hex[:12]}")
        target_mod_dir = self._prepare_target_mod_dir(mods_dir, mod_name, mod_id)
        files_structure: dict[str, dict[str, Any]] = {"pizzatower": {}}
        changed_remaining = list(changed_files)
        data_file_name = self._write_data_patch(
            target_mod_dir,
            original_game_dir,
            working_game_dir,
            changed_remaining,
            reusable_patches.get("data.win"),
        )
        if data_file_name:
            files_structure["pizzatower"]["data_file_path"] = data_file_name
        extra_files = self._write_extra_files(
            target_mod_dir,
            working_game_dir,
            changed_remaining,
            reusable_patches,
        )
        if extra_files:
            files_structure["pizzatower"]["extra_files"] = extra_files
        self._copy_root_docs(source_dir, target_mod_dir, set(used_source_files))
        self._copy_icon_asset(source_dir, target_mod_dir, metadata)
        config_data: dict[str, Any] = {
            "id": mod_id,
            "name": mod_name,
            "game": "pizzatower",
            "version": str(metadata.get("version") or "1.0.0"),
            "author": str(metadata.get("author") or "Unknown"),
            "description": str(metadata.get("description") or ""),
            "files": files_structure,
        }
        if homepage := metadata.get("homepage"):
            config_data["homepage"] = homepage
        if icon := metadata.get("icon"):
            config_data["icon"] = icon
        if tags := metadata.get("tags"):
            config_data["tags"] = tags if isinstance(tags, list) else [tags]
        save_json(
            os.path.join(target_mod_dir, MOD_CONFIG_FILENAME),
            build_mod_config_data(config_data),
            indent=2,
        )
        return PizzaOvenConversionResult(
            mod_dir=target_mod_dir,
            changed_files=changed_files,
            data_file_name=data_file_name,
            used_source_files=used_source_files,
        )

    @staticmethod
    def _prepare_target_mod_dir(mods_dir: str, mod_name: str, mod_id: str) -> str:
        os.makedirs(mods_dir, exist_ok=True)
        existing = PizzaOvenConversionService._find_existing_mod_dir(mods_dir, mod_id)
        if existing:
            for item in os.listdir(existing):
                if item == "mod_versions":
                    continue
                item_path = os.path.join(existing, item)
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path, ignore_errors=True)
                else:
                    try:
                        os.remove(item_path)
                    except OSError:
                        logger.debug(
                            "Failed to remove %s during PO reconvert", item_path
                        )
            return existing
        folder_name = get_unique_mod_dir(mods_dir, mod_name)
        target_mod_dir = os.path.join(mods_dir, folder_name)
        os.makedirs(target_mod_dir, exist_ok=True)
        return target_mod_dir

    @staticmethod
    def _find_existing_mod_dir(mods_dir: str, mod_id: str) -> str | None:
        for folder_name in os.listdir(mods_dir):
            folder_path = os.path.join(mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            config_path = os.path.join(folder_path, "mod_config.json")
            if not os.path.isfile(config_path):
                continue
            try:
                with open(config_path, encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict) and data.get("id") == mod_id:
                    return folder_path
            except Exception:
                logger.debug("Failed to inspect %s", config_path, exc_info=True)
        return None

    @classmethod
    def _write_extra_files(
        cls,
        target_mod_dir: str,
        working_game_dir: str,
        changed_files: list[str],
        reusable_patches: dict[str, str],
    ) -> list[str]:
        extra_files = []
        for rel_path in changed_files:
            if not rel_path:
                continue
            patch_source = reusable_patches.get(rel_path)
            if patch_source:
                patch_rel_path = f"{rel_path}.xdelta"
                target_path = os.path.join(
                    target_mod_dir, patch_rel_path.replace("/", os.sep)
                )
                cls._copy_file(patch_source, target_path)
                extra_files.append(patch_rel_path)
                continue
            source_path = os.path.join(working_game_dir, rel_path.replace("/", os.sep))
            target_path = os.path.join(target_mod_dir, rel_path.replace("/", os.sep))
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(source_path, target_path)
            extra_files.append(rel_path)
        return extra_files

    def _write_data_patch(
        self,
        target_mod_dir: str,
        original_game_dir: str,
        working_game_dir: str,
        changed_remaining: list[str],
        data_patch_source: str | None,
    ) -> str | None:
        if "data.win" not in changed_remaining:
            return None
        if data_patch_source and os.path.isfile(data_patch_source):
            target_patch = os.path.join(target_mod_dir, "data.xdelta")
            self._copy_file(data_patch_source, target_patch)
            changed_remaining.remove("data.win")
            return "data.xdelta"
        original_data = os.path.join(original_game_dir, "data.win")
        modified_data = os.path.join(working_game_dir, "data.win")
        if not os.path.isfile(original_data) or not os.path.isfile(modified_data):
            raise PizzaOvenConversionError("Converted Pizza Tower data.win is missing")
        if self._g3mtool.is_available():
            g3m_path = os.path.join(target_mod_dir, "data.g3mpatch")
            returncode = self._g3mtool.patch_create(
                original_data, modified_data, g3m_path
            )[0]
            if (
                returncode == 0
                and os.path.isfile(g3m_path)
                and self._verify_patch_output(
                    original_data, modified_data, g3m_path, patch_type="g3mpatch"
                )
            ):
                changed_remaining.remove("data.win")
                return "data.g3mpatch"
            if os.path.exists(g3m_path):
                os.remove(g3m_path)
            xdelta_path = os.path.join(target_mod_dir, "data.win.xdelta")
            returncode = self._g3mtool.xpatch_create(
                original_data, modified_data, xdelta_path
            )[0]
            if (
                returncode == 0
                and os.path.isfile(xdelta_path)
                and self._verify_patch_output(
                    original_data, modified_data, xdelta_path, patch_type="xdelta"
                )
            ):
                changed_remaining.remove("data.win")
                return "data.win.xdelta"
            if os.path.exists(xdelta_path):
                os.remove(xdelta_path)
        target_data = os.path.join(target_mod_dir, "data.win")
        self._copy_file(modified_data, target_data)
        changed_remaining.remove("data.win")
        return "data.win"

    def _verify_patch_output(
        self,
        original_data: str,
        modified_data: str,
        patch_path: str,
        *,
        patch_type: str,
    ) -> bool:
        verified = verify_generated_patch(
            self._g3mtool,
            original_data,
            modified_data,
            patch_path,
            patch_type=patch_type,
        )[0]
        return verified

    @staticmethod
    def _copy_icon_asset(
        source_dir: str, target_mod_dir: str, metadata: dict[str, Any]
    ) -> None:
        icon_value = str(metadata.get("icon") or "").strip()
        if not icon_value or icon_value.startswith(("http://", "https://")):
            return
        icon_source = icon_value
        if not os.path.isabs(icon_source):
            icon_source = os.path.normpath(
                os.path.join(source_dir, icon_source.replace("/", os.sep))
            )
        if not os.path.isfile(icon_source):
            fallback_name = os.path.basename(icon_value)
            fallback_path = os.path.join(source_dir, fallback_name)
            if not os.path.isfile(fallback_path):
                return
            icon_source = fallback_path
        icon_name = os.path.basename(icon_source)
        shutil.copy2(icon_source, os.path.join(target_mod_dir, icon_name))
        metadata["icon"] = icon_name

    @staticmethod
    def _copy_root_docs(
        source_dir: str, target_mod_dir: str, used_source_files: set[str]
    ) -> None:
        for file_name in os.listdir(source_dir):
            source_path = os.path.join(source_dir, file_name)
            rel_path = file_name.replace("\\", "/")
            if not os.path.isfile(source_path):
                continue
            if rel_path in used_source_files:
                continue
            if (
                os.path.splitext(file_name)[1].lower()
                not in MOD_DOCUMENTATION_EXTENSIONS
            ):
                continue
            shutil.copy2(source_path, os.path.join(target_mod_dir, file_name))
