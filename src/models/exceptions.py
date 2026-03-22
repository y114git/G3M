"""Custom exception classes."""


class DELTAHUBError(Exception):
    """Base exception class for all DELTAHUB-specific errors."""

    pass


class AppError(DELTAHUBError):
    """Application-level error with localization support."""

    def __init__(self, key: str, **kwargs) -> None:
        self.key, self.kwargs = key, kwargs
        from services.localization_service import tr

        super().__init__(tr(key, **kwargs))


class ModError(DELTAHUBError):
    """Base exception for mod-related errors."""

    def __init__(
        self, message: str, key: str | None = None, mod_name: str | None = None
    ) -> None:
        super().__init__(message)
        self.key, self.mod_name = key, mod_name


class ModInstallationError(ModError):
    """Exception raised when mod installation fails."""

    def __init__(
        self,
        message: str,
        key: str | None = None,
        mod_name: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message, key, mod_name)
        self.reason = reason


class ModUninstallationError(ModError):
    """Exception raised when mod uninstallation fails."""

    def __init__(
        self,
        message: str,
        key: str | None = None,
        mod_name: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message, key, mod_name)
        self.reason = reason
