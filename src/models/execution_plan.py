"""Serializable patch and launch plans shared by every execution entry point."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from utils.mod.utils import get_mod_id

PLAN_VERSION = 1


class PlanResolutionError(ValueError):
    """Raised when a serialized plan references an unavailable installed mod."""


def _normalize_steps(value: object) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, (list, tuple)) or not value:
        return ()
    raw_steps = value if isinstance(value[0], (list, tuple)) else (value,)
    steps: list[tuple[str, ...]] = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, (list, tuple)):
            continue
        step = tuple(str(mod_id) for mod_id in raw_step if mod_id)
        if step:
            steps.append(step)
    return tuple(steps)


@dataclass(frozen=True, slots=True)
class PatchPlan:
    """Ordered patch steps keyed by a game's content sections."""

    sections: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = ()
    version: int = PLAN_VERSION

    @classmethod
    def from_runtime(cls, section_mods: Mapping[str, object]) -> PatchPlan:
        serialized: dict[str, list[list[str]]] = {}
        for section_id, value in section_mods.items():
            if not isinstance(value, (list, tuple)) or not value:
                continue
            raw_steps = value if isinstance(value[0], (list, tuple)) else (value,)
            steps: list[list[str]] = []
            for raw_step in raw_steps:
                ids = [get_mod_id(mod) for mod in raw_step if mod]
                if any(not mod_id for mod_id in ids):
                    raise ValueError(
                        f"Patch plan contains a mod without an id: {section_id}"
                    )
                if ids:
                    steps.append([str(mod_id) for mod_id in ids])
            if steps:
                serialized[str(section_id)] = steps
        return cls.from_dict({"version": PLAN_VERSION, "sections": serialized})

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PatchPlan:
        version = payload.get("version", PLAN_VERSION)
        if version != PLAN_VERSION:
            raise ValueError(f"Unsupported patch plan version: {version}")
        raw_sections = payload.get("sections", payload.get("chapters", {}))
        if not isinstance(raw_sections, Mapping):
            raise ValueError("Patch plan sections must be an object")
        sections = tuple(
            (str(section_id), steps)
            for section_id, value in sorted(raw_sections.items())
            if (steps := _normalize_steps(value))
        )
        return cls(sections=sections, version=PLAN_VERSION)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "sections": {
                section_id: [list(step) for step in steps]
                for section_id, steps in self.sections
            },
        }

    def steps_for(self, section_id: str) -> tuple[tuple[str, ...], ...]:
        return next(
            (steps for current, steps in self.sections if current == section_id), ()
        )

    def require_single_mod_steps(self) -> None:
        if any(len(step) != 1 for _section_id, steps in self.sections for step in steps):
            raise ValueError("Shortcut plans support exactly one mod per step")

    def resolve(self, resolver: Callable[[str], Any | None]) -> dict[str, list[list[Any]]]:
        resolved: dict[str, list[list[Any]]] = {}
        cache: dict[str, Any] = {}
        for section_id, steps in self.sections:
            section_steps: list[list[Any]] = []
            for step in steps:
                resolved_step: list[Any] = []
                for mod_id in step:
                    mod = cache.get(mod_id)
                    if mod is None:
                        mod = resolver(mod_id)
                        if mod is None:
                            raise PlanResolutionError(
                                f'Mod "{mod_id}" from content section "{section_id}" '
                                "is not available"
                            )
                        cache[mod_id] = mod
                    resolved_step.append(mod)
                section_steps.append(resolved_step)
            resolved[section_id] = section_steps
        return resolved


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    game_id: str
    patch_plan: PatchPlan = PatchPlan()
    chapter_mode: bool = False
    launch_via_steam: bool = False
    use_portproton: bool = False
    direct_launch_chapter: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> LaunchPlan:
        patch_payload = payload.get("patch_plan", {})
        if not isinstance(patch_payload, Mapping):
            raise ValueError("Launch plan patch_plan must be an object")
        return cls(
            game_id=str(payload.get("game_id") or "deltarune"),
            patch_plan=PatchPlan.from_dict(patch_payload),
            chapter_mode=bool(payload.get("chapter_mode", False)),
            launch_via_steam=bool(payload.get("launch_via_steam", False)),
            use_portproton=bool(payload.get("use_portproton", False)),
            direct_launch_chapter=str(payload.get("direct_launch_chapter") or ""),
        )

    @classmethod
    def from_shortcut_config(cls, payload: Mapping[str, Any]) -> LaunchPlan:
        embedded = payload.get("launch_plan")
        if isinstance(embedded, Mapping):
            plan = cls.from_dict(embedded)
            plan.patch_plan.require_single_mod_steps()
            return plan
        legacy_sections = payload.get("chapter_mods", {})
        sections = {
            str(section_id): [[str(mod_id)]]
            for section_id, mod_id in legacy_sections.items()
            if mod_id
        } if isinstance(legacy_sections, Mapping) else {}
        plan = cls.from_dict(
            {
                **payload,
                "patch_plan": {"version": PLAN_VERSION, "sections": sections},
            }
        )
        plan.patch_plan.require_single_mod_steps()
        return plan

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": PLAN_VERSION,
            "game_id": self.game_id,
            "chapter_mode": self.chapter_mode,
            "launch_via_steam": self.launch_via_steam,
            "use_portproton": self.use_portproton,
            "direct_launch_chapter": self.direct_launch_chapter,
            "patch_plan": self.patch_plan.to_dict(),
        }

    def to_shortcut_config(self) -> dict[str, Any]:
        self.patch_plan.require_single_mod_steps()
        legacy_sections: dict[str, str | None] = {}
        for section_id, steps in self.patch_plan.sections:
            flattened = [mod_id for step in steps for mod_id in step]
            legacy_sections[section_id] = (
                flattened[0] if len(flattened) == 1 else None
            )
        return {
            "game_id": self.game_id,
            "chapter_mode": self.chapter_mode,
            "launch_via_steam": self.launch_via_steam,
            "use_portproton": self.use_portproton,
            "direct_launch_chapter": self.direct_launch_chapter,
            "launch_plan": self.to_dict(),
            "chapter_mods": legacy_sections,
        }
