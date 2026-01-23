"""Custom exception classes and error handling decorators.

This module defines the exception hierarchy for DELTAHUB, including exceptions
for mod operations, network errors, file operations, and data parsing.
"""
from typing import Optional, List, Callable, Any
from functools import wraps
import logging
logger = logging.getLogger(__name__)


class DELTAHUBError(Exception):
    """Base exception class for all DELTAHUB-specific errors."""
    pass


class AppError(DELTAHUBError):
    """Application-level error with localization support."""

    def __init__(self, key: str, **kwargs):
        """Initialize with a localization key and optional parameters.

        Args:
            key: Localization key for the error message.
            **kwargs: Additional parameters for message formatting.
        """
        self.key = key
        self.kwargs = kwargs
        from services.localization_service import tr
        super().__init__(tr(key, **kwargs))

    def get_message(self) -> str:
        """Get the localized error message.

        Returns:
            str: Localized error message.
        """
        from services.localization_service import tr
        return tr(self.key, **self.kwargs)


def handle_errors(error_key: str = 'errors.operation_failed', log_level: str = 'error', reraise: bool = False, default_return: Any = None):
    """Decorator for handling errors in functions with logging and optional reraising.

    Args:
        error_key: Localization key for error messages.
        log_level: Logging level ('error', 'warning', etc.).
        reraise: Whether to reraise as AppError.
        default_return: Default value to return on error.

    Returns:
        Callable: Decorated function.
    """

    def decorator(func: Callable) -> Callable:

        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except AppError:
                raise
            except Exception as e:
                log_func = getattr(logger, log_level, logger.error)
                log_func(f'{func.__name__}: {e}', exc_info=True)
                if reraise:
                    raise AppError(error_key, error=str(e)) from e
                return default_return
        return wrapper
    return decorator


def safe_operation(func: Callable) -> Callable:
    """Decorator for safe operation execution that logs warnings on failure.

    Args:
        func: Function to wrap.

    Returns:
        Callable: Wrapped function that returns None on error.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.warning(f'{func.__name__}: {e}')
            return None
    return wrapper


class ModError(DELTAHUBError):
    """Base exception for mod-related errors."""

    def __init__(self, message: str, key: Optional[str] = None, mod_name: Optional[str] = None):
        """Initialize mod error with message and optional metadata.

        Args:
            message: Error message.
            key: Mod key identifier.
            mod_name: Name of the mod.
        """
        super().__init__(message)
        self.key = key
        self.mod_name = mod_name


class ModInstallationError(ModError):
    """Exception raised when mod installation fails."""

    def __init__(self, message: str, key: Optional[str] = None, mod_name: Optional[str] = None, reason: Optional[str] = None):
        """Initialize installation error.

        Args:
            message: Error message.
            key: Mod key identifier.
            mod_name: Name of the mod.
            reason: Reason for installation failure.
        """
        super().__init__(message, key, mod_name)
        self.reason = reason


class ModUninstallationError(ModError):
    """Exception raised when mod uninstallation fails."""

    def __init__(self, message: str, key: Optional[str] = None, mod_name: Optional[str] = None, reason: Optional[str] = None):
        """Initialize uninstallation error.

        Args:
            message: Error message.
            key: Mod key identifier.
            mod_name: Name of the mod.
            reason: Reason for uninstallation failure.
        """
        super().__init__(message, key, mod_name)
        self.reason = reason


class ModValidationError(ModError):
    """Exception raised when mod validation fails."""

    def __init__(self, message: str, key: Optional[str] = None, mod_name: Optional[str] = None, validation_errors: Optional[List[str]] = None):
        """Initialize validation error.

        Args:
            message: Error message.
            key: Mod key identifier.
            mod_name: Name of the mod.
            validation_errors: List of validation error messages.
        """
        super().__init__(message, key, mod_name)
        self.validation_errors = validation_errors or []


class ModConfigError(ModError):
    """Exception raised when mod configuration is invalid."""

    def __init__(self, message: str, config_path: Optional[str] = None, key: Optional[str] = None, mod_name: Optional[str] = None):
        """Initialize configuration error.

        Args:
            message: Error message.
            config_path: Path to the config file.
            key: Mod key identifier.
            mod_name: Name of the mod.
        """
        super().__init__(message, key, mod_name)
        self.config_path = config_path


class ModUpdateError(ModError):
    """Exception raised when mod update fails."""

    def __init__(self, message: str, key: Optional[str] = None, mod_name: Optional[str] = None, reason: Optional[str] = None):
        """Initialize update error.

        Args:
            message: Error message.
            key: Mod key identifier.
            mod_name: Name of the mod.
            reason: Reason for update failure.
        """
        super().__init__(message, key, mod_name)
        self.reason = reason


class NetworkError(DELTAHUBError):
    """Base exception for network-related errors."""

    def __init__(self, message: str, url: Optional[str] = None, status_code: Optional[int] = None):
        """Initialize network error.

        Args:
            message: Error message.
            url: URL that caused the error.
            status_code: HTTP status code if applicable.
        """
        super().__init__(message)
        self.url = url
        self.status_code = status_code


class NetworkTimeoutError(NetworkError):
    """Exception raised when a network request times out."""

    def __init__(self, message: str, url: Optional[str] = None, timeout: Optional[float] = None):
        """Initialize timeout error.

        Args:
            message: Error message.
            url: URL that timed out.
            timeout: Timeout duration in seconds.
        """
        super().__init__(message, url)
        self.timeout = timeout


class NetworkConnectionError(NetworkError):
    """Exception raised when network connection fails."""
    pass


class HTTPError(NetworkError):
    """Exception raised for HTTP errors."""

    def __init__(self, message: str, url: Optional[str] = None, status_code: Optional[int] = None, response_body: Optional[str] = None):
        """Initialize HTTP error.

        Args:
            message: Error message.
            url: URL that returned the error.
            status_code: HTTP status code.
            response_body: Response body content.
        """
        super().__init__(message, url, status_code)
        self.response_body = response_body


class FileOperationError(DELTAHUBError):
    """Base exception for file operation errors."""

    def __init__(self, message: str, file_path: Optional[str] = None, operation: Optional[str] = None):
        """Initialize file operation error.

        Args:
            message: Error message.
            file_path: Path to the file.
            operation: Operation that failed.
        """
        super().__init__(message)
        self.file_path = file_path
        self.operation = operation


class MissingFileError(FileOperationError):
    """Exception raised when a required file is missing."""
    pass


class FilePermissionError(FileOperationError):
    """Exception raised when file permission is denied."""

    def __init__(self, message: str, file_path: Optional[str] = None, operation: Optional[str] = None, required_permission: Optional[str] = None):
        """Initialize permission error.

        Args:
            message: Error message.
            file_path: Path to the file.
            operation: Operation that was denied.
            required_permission: Required permission level.
        """
        super().__init__(message, file_path, operation)
        self.required_permission = required_permission


class ArchiveError(FileOperationError):
    """Exception raised for archive operation errors."""

    def __init__(self, message: str, archive_path: Optional[str] = None, archive_type: Optional[str] = None):
        """Initialize archive error.

        Args:
            message: Error message.
            archive_path: Path to the archive file.
            archive_type: Type of archive (zip, rar, etc.).
        """
        super().__init__(message, archive_path, 'extract')
        self.archive_type = archive_type


class ArchiveCorruptedError(ArchiveError):
    """Exception raised when an archive file is corrupted."""
    pass


class DataParsingError(DELTAHUBError):
    """Base exception for data parsing errors."""

    def __init__(self, message: str, data_source: Optional[str] = None, data_type: Optional[str] = None):
        """Initialize data parsing error.

        Args:
            message: Error message.
            data_source: Source of the data.
            data_type: Type of data being parsed.
        """
        super().__init__(message)
        self.data_source = data_source
        self.data_type = data_type


class JSONParsingError(DataParsingError):
    """Exception raised when JSON parsing fails."""

    def __init__(self, message: str, json_source: Optional[str] = None, line_number: Optional[int] = None, column_number: Optional[int] = None):
        """Initialize JSON parsing error.

        Args:
            message: Error message.
            json_source: Source of the JSON data.
            line_number: Line number where error occurred.
            column_number: Column number where error occurred.
        """
        super().__init__(message, json_source, 'JSON')
        self.line_number = line_number
        self.column_number = column_number
