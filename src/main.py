import sys
import os

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    path_to_src = os.path.join(getattr(sys, '_MEIPASS'), 'src')
else:
    path_to_src = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, path_to_src)

if __name__ == '__main__':
    from core.startup import run_app
    from utils.file_utils import cleanup_old_updater_files
    cleanup_old_updater_files()
    run_app()
