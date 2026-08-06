import contextlib
import json
import zipfile
from types import SimpleNamespace

from services.support_package_service import SupportPackageService


def _state():
    return SimpleNamespace(
        local_config={"token": "private", "path": r"C:\Users\Alice\G3M"},
        all_mods=[],
        game_mode=SimpleNamespace(key="deltarune"),
        selected_chapter_id=4,
        game_is_running=False,
        initialization_completed=True,
    )


def test_build_redacts_secrets_and_identity(monkeypatch, tmp_path):
    root = tmp_path / "Alice" / "G3M"
    (root / "logs").mkdir(parents=True)
    (root / "logs" / "g3m.log").write_text(
        f"user={root.parent.name} token=safe-to-redact", encoding="utf-8"
    )
    monkeypatch.setenv("USERNAME", "Alice")
    service = SupportPackageService(_state(), str(root))
    target = tmp_path / "support.zip"

    service.build(
        str(target),
        {"metadata.settings", "app.state"},
        log_names={"logs/g3m.log"},
        log_days=None,
    )

    with zipfile.ZipFile(target) as archive:
        settings = json.loads(archive.read("metadata/settings.json"))
        log = archive.read("logs/g3m.log").decode()
    assert settings["token"].startswith("[RED")
    assert "Alice" not in json.dumps(settings)
    assert "Alice" not in log
    assert "USERNAME" in log
    assert "safe-to-redact" not in log


def test_build_does_not_follow_structure_symlinks(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        return
    service = SupportPackageService(_state(), str(root))
    target = tmp_path / "support.zip"

    service.build(str(target), {"structure.files"}, log_names=set(), log_days=None)

    with zipfile.ZipFile(target) as archive:
        structure = json.loads(archive.read("structure/files.json"))
    assert all("secret.txt" not in entry["path"] for entry in structure)


def test_cancel_removes_partial_archive(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "support.zip"
    service = SupportPackageService(_state(), str(root))

    with contextlib.suppress(InterruptedError):
        service.build(
            str(target),
            {"structure.files"},
            log_names=set(),
            log_days=None,
            cancelled=lambda: True,
        )

    assert not target.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_dynamic_files_mods_structures_and_patch_manifest(tmp_path):
    root = tmp_path / "G3M"
    root.mkdir()
    (root / "profiles.json").write_text(
        '{"token":"hidden","value":1}', encoding="utf-8"
    )
    (root / "notes.md").write_text("User Alice", encoding="utf-8")
    mod_root = tmp_path / "mods" / "sample"
    (mod_root / "empty").mkdir(parents=True)
    (mod_root / "mod_config.json").write_text('{"id":"sample"}', encoding="utf-8")
    (mod_root / "data.bin").write_bytes(b"mod-data")
    patch = mod_root / "sample.g3mpatch"
    with zipfile.ZipFile(patch, "w") as archive:
        archive.writestr("g3mpatch.json", '{"format":1}')
    state = _state()
    state.all_mods = [
        SimpleNamespace(id="sample", name="Sample", folder_path=str(mod_root))
    ]
    service = SupportPackageService(state, str(root))
    manifest_key = f"patch_manifest::{patch.resolve()}::g3mpatch.json"
    target = tmp_path / "support.zip"

    service.build(
        str(target),
        {
            "g3m_file::profiles.json",
            "g3m_file::notes.md",
            "mod_config::sample",
            "mod_structure::sample",
            "mod_files::sample",
            manifest_key,
        },
        log_names=set(),
        log_days=None,
    )

    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        profile = json.loads(archive.read("g3m_files/profiles.json"))
        structure = json.loads(archive.read("mods/Sample_sample/structure.json"))
    assert profile["token"].startswith("[RED")
    assert "g3m_files/notes.md" in names
    assert "mods/Sample_sample/mod_config.json" in names
    assert "mods/Sample_sample/files/data.bin" in names
    assert any(
        name.startswith("g3mpatch/sample_") and name.endswith("/g3mpatch.json")
        for name in names
    )
    assert any(
        item["type"] == "directory" and item["relative_path"] == "empty"
        for item in structure
    )
