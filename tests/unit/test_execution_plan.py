from types import SimpleNamespace

import pytest

from models.execution_plan import LaunchPlan, PatchPlan, PlanResolutionError


def _mod(mod_id: str):
    return SimpleNamespace(id=mod_id)


def test_patch_plan_roundtrip_preserves_chapters_steps_and_priority():
    plan = PatchPlan.from_runtime(
        {
            "chapter_2": [[_mod("base")], [_mod("addon"), _mod("translation")]],
            "empty": [],
        }
    )

    payload = plan.to_dict()

    assert payload == {
        "version": 1,
        "sections": {
            "chapter_2": [["base"], ["addon", "translation"]],
        },
    }
    assert PatchPlan.from_dict(payload) == plan


def test_patch_plan_normalizes_legacy_flat_chapter_values():
    plan = PatchPlan.from_dict(
        {"version": 1, "chapters": {"chapter_1": ["a", "b"]}}
    )

    assert plan.steps_for("chapter_1") == (("a", "b"),)


def test_patch_plan_reads_legacy_chapters_but_writes_neutral_sections():
    plan = PatchPlan.from_dict(
        {"version": 1, "chapters": {"frickbears3": [["mod"]]}}
    )

    assert plan.to_dict() == {
        "version": 1,
        "sections": {"frickbears3": [["mod"]]},
    }


def test_patch_plan_resolves_ids_once_at_execution_boundary():
    plan = PatchPlan.from_dict(
        {"version": 1, "sections": {"chapter_1": [["base"], ["addon"]]}}
    )
    mods = {mod_id: _mod(mod_id) for mod_id in ("base", "addon")}

    resolved = plan.resolve(mods.get)

    assert [[mod.id for mod in step] for step in resolved["chapter_1"]] == [
        ["base"],
        ["addon"],
    ]


def test_patch_plan_rejects_missing_mod_before_patching_starts():
    plan = PatchPlan.from_dict(
        {"version": 1, "sections": {"chapter_1": [["missing"]]}}
    )

    with pytest.raises(PlanResolutionError, match='section "chapter_1"'):
        plan.resolve(lambda _mod_id: None)


def test_launch_plan_roundtrip_and_legacy_shortcut_compatibility():
    legacy = {
        "game_id": "deltarune",
        "chapter_mode": True,
        "launch_via_steam": False,
        "use_portproton": True,
        "direct_launch_chapter": "deltarune_2",
        "chapter_mods": {"deltarune_2": "base"},
    }

    plan = LaunchPlan.from_shortcut_config(legacy)

    assert plan.patch_plan.steps_for("deltarune_2") == (("base",),)
    assert LaunchPlan.from_dict(plan.to_dict()) == plan
    shortcut_config = plan.to_shortcut_config()
    assert shortcut_config["chapter_mods"] == {
        "deltarune_2": "base"
    }
    assert LaunchPlan.from_shortcut_config(shortcut_config) == plan


def test_shortcut_config_rejects_multiple_mods_in_one_step():
    payload = {
        "launch_plan": {
            "game_id": "deltarune",
            "patch_plan": {
                "version": 1,
                "sections": {"deltarune_2": [["base", "addon"]]},
            },
        }
    }

    with pytest.raises(ValueError, match="one mod per step"):
        LaunchPlan.from_shortcut_config(payload)
