"""Pre-save preparation helpers for the mod editor dialog."""

from ui.dialogs.mod_editor.save import build_saved_mod_config


def prepare_mod_save_payload(
    *,
    mod_id: str,
    mod_dir: str,
    collect_mod_data,
    process_icon,
    copy_files_to_mod_dir,
    copy_info_files_to_mod_dir,
    existing_config: dict | None = None,
):
    data = collect_mod_data()
    icon_val = process_icon(mod_dir)
    processed_files = copy_files_to_mod_dir(
        mod_dir,
        data.get("files", {}),
        data["game"],
    )
    copy_info_files_to_mod_dir(mod_dir)
    config = build_saved_mod_config(
        mod_id=mod_id,
        data=data,
        processed_files=processed_files,
        icon_val=icon_val,
        existing_config=existing_config,
    )
    return data, icon_val, processed_files, config
