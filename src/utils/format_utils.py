"""Formatting utilities for display.

This module provides utilities for formatting data for display including file sizes and dates.
"""


def format_size_mb(size_bytes: int) -> str:
    """Format byte size as megabytes string.

    Args:
        size_bytes: Size in bytes.

    Returns:
        str: Formatted size string (e.g., '5.2 MB').
    """
    if size_bytes <= 0:
        return '0 MB'
    mb = size_bytes / (1024 * 1024)
    return f'{mb:.1f} MB'
