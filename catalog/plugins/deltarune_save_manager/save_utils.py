"""
Utility functions for Deltarune save management.
This module contains functions that are specific to save file handling
and should not be part of the main launcher codebase.
"""
import os
import re

SAVE_SLOT_FINISH_MAP = {0: 3, 1: 4, 2: 5}


def is_valid_save_path(path: str) -> bool:
    """
    Check if the given path is a valid Deltarune save folder.
    A valid save folder should contain at least one save file matching the pattern filech{chapter}_{slot}.

    Args:
        path: Path to the directory to check

    Returns:
        True if the path contains at least one valid save file, False otherwise
    """
    if not path or not os.path.isdir(path):
        return False
    try:
        save_file_pattern = re.compile(r'^filech\d+_\d+$')
        for entry in os.listdir(path):
            if save_file_pattern.match(entry) and os.path.isfile(os.path.join(path, entry)):
                return True
    except (OSError, PermissionError):
        return False
    return False
