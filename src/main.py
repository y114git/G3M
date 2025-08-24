import sys
import os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
if __name__ == '__main__':
    from src.core.startup import run_app
    from src.utils.file_utils import cleanup_old_updater_files
    cleanup_old_updater_files()
    run_app()