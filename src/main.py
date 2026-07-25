"""G3M application entry point.
This module sets up the Python path and launches the application.
"""

import multiprocessing
import os
import sys


def _add_frozen_src_to_path() -> None:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and bundle_root:
        frozen_src = os.path.join(bundle_root, "src")
        if frozen_src not in sys.path:
            sys.path.insert(0, frozen_src)


def _run_shortcut(argv: list[str]) -> int:
    idx = argv.index("--shortcut")
    if idx + 1 >= len(argv):
        sys.stderr.write("Error: --shortcut requires a config argument\n")
        return 2
    try:
        from bootstrap.user_data_bootstrap import (
            resolve_user_data_root_with_migration,
        )

        resolve_user_data_root_with_migration(interactive=False)
    except Exception as error:
        sys.stderr.write(f"Error: {error}\n")
        return 1
    from services.game_runner import run_shortcut

    run_shortcut(argv[idx + 1])
    return 0


def _prepare_process_runtime() -> None:
    """Enable safe child-process startup for frozen Windows builds."""
    multiprocessing.freeze_support()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    _prepare_process_runtime()
    if "--shortcut" in argv:
        return _run_shortcut(argv)
    from app.startup import run_app
    from utils.path_utils import cleanup_old_updater_files

    cleanup_old_updater_files()
    return run_app(argv[1:])


_add_frozen_src_to_path()
if __name__ == "__main__":
    sys.exit(main())
