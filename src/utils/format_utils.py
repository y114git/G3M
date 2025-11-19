def format_size_mb(size_bytes: int) -> str:
    if size_bytes <= 0:
        return '0 MB'
    mb = size_bytes / (1024 * 1024)
    return f'{mb:.1f} MB'
