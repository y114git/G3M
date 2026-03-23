"""DELTAHUB application entry point.
This module sets up the Python path and launches the application.
"""

import os
import sys

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _frozen_src = os.path.join(sys._MEIPASS, "src")
    if _frozen_src not in sys.path:
        sys.path.insert(0, _frozen_src)
if __name__ == "__main__":
    if "--shortcut" in sys.argv:
        idx = sys.argv.index("--shortcut")
        if idx + 1 >= len(sys.argv):
            import sys

            sys.stderr.write("Error: --shortcut requires a config argument\n")
            sys.exit(2)
        from services.game_runner import run_shortcut

        run_shortcut(sys.argv[idx + 1])
        sys.exit(0)

    from app.startup import run_app
    from utils.path_utils import cleanup_old_updater_files

    cleanup_old_updater_files()
    sys.exit(run_app())
