"""Show dates in the format chosen in the system region settings."""

from datetime import datetime

from PyQt6.QtCore import QDate, QDateTime, QLocale, QTime

# Shapes G3M stores: GameBanana "dd.mm.yy HH:MM", local installs "YYYY-MM-DD HH:MM:SS".
_STORED_FORMATS = ("%d.%m.%y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def format_local_datetime(value: datetime) -> str:
    """Qt reads the short date and time patterns the user picked in the system settings, custom ones included."""
    local = value.astimezone() if value.tzinfo else value
    return QLocale().toString(
        QDateTime(QDate(local.year, local.month, local.day), QTime(local.hour, local.minute)),
        QLocale.FormatType.ShortFormat,
    )


def format_timestamp(timestamp: float) -> str:
    return format_local_datetime(datetime.fromtimestamp(timestamp))


def format_stored_date(text: str | None) -> str | None:
    """Show a date stored by G3M in the system format; text that is not a stored date is returned unchanged."""
    if not text:
        return text
    for stored_format in _STORED_FORMATS:
        try:
            return format_local_datetime(datetime.strptime(text, stored_format))
        except ValueError:
            continue
    return text
