"""G3M application entry point.
This module sets up the Python path and launches the application.
"""

import os
import sys


def _add_frozen_src_to_path() -> None:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        frozen_src = os.path.join(sys._MEIPASS, "src")
        if frozen_src not in sys.path:
            sys.path.insert(0, frozen_src)


def _run_shortcut(argv: list[str]) -> int:
    idx = argv.index("--shortcut")
    if idx + 1 >= len(argv):
        sys.stderr.write("Error: --shortcut requires a config argument\n")
        return 2
    from services.game_runner import run_shortcut

    run_shortcut(argv[idx + 1])
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if "--shortcut" in argv:
        return _run_shortcut(argv)
    from app.startup import run_app
    from utils.path_utils import cleanup_old_updater_files

    cleanup_old_updater_files()
    return run_app(argv[1:])


_add_frozen_src_to_path()
if __name__ == "__main__":
    sys.exit(main())
