"""Config assembly helpers for the mod editor dialog."""


def build_saved_mod_config(
    *,
    mod_id: str,
    data: dict,
    processed_files: dict,
    icon_val: str | None = None,
    existing_config: dict | None = None,
) -> dict:
    config = dict(existing_config or {})
    config.update(
        {
            "id": mod_id,
            "version": data["version"],
            "name": data["name"],
            "description": data["description"],
            "author": data["author"],
            "homepage": data["homepage"],
            "game": data["game"],
            "game_version": data["game_version"],
            "tags": data["tags"],
            "info_files": data["info_files"],
            "files": processed_files,
        }
    )
    if icon_val:
        config["icon"] = icon_val
    return config
